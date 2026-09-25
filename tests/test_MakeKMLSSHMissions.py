# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
##
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Tests for ssh/MakeKMLSSHMissions.py: master missions.yml traversal, mission to
site assignment, per-site processing, and the fork/drop-privilege driver."""

import io
import logging
import os
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ssh"))
import MakeKMLSSHMissions  # noqa: E402  # ty: ignore[unresolved-import]

import SiteConfig

Mission = MakeKMLSSHMissions.Mission


def _site(
    name: str,
    tree: pathlib.Path,
    jailed: bool = True,
    uid: int | None = None,
    gid: int | None = None,
) -> SiteConfig.SiteConfig:
    """A resolved SiteConfig rooted at tree (tree/home/rundir is its watch_dir)."""
    site = SiteConfig.SiteConfig(
        name=name,
        watch_dir=tree / "home" / "rundir",
        jail_root=tree if jailed else None,
        jailed=jailed,
        runner_user=f"runner-{name}",
    )
    object.__setattr__(site, "runner_uid", os.geteuid() if uid is None else uid)
    object.__setattr__(site, "runner_gid", os.getegid() if gid is None else gid)
    return site


class FakeBaseOpts:
    def __init__(self, tmp_path: pathlib.Path, **overrides: object) -> None:
        self.data_dir = tmp_path / "data"
        self.mission_yml = tmp_path / "missions.yml"
        self.sites_config = tmp_path / "sites.yml"
        self.jobs = 1
        self.force = False
        self.fetch_ssh = False
        self.mergessh = True
        self.basestation_directory = tmp_path
        for key, value in overrides.items():
            setattr(self, key, value)


# --- load_active_missions ---------------------------------------------------


def test_load_missions_list_status_and_default_path(tmp_path: pathlib.Path) -> None:
    (tmp_path / "missions.yml").write_text(
        """
missions:
  - {glider: 1, path: sg001/m1}
  - {glider: 2}
  - {glider: 3, path: sg003, status: complete}
  - {glider: 4, path: sg004, status: active}
  - {path: no_glider}
"""
    )

    missions = MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml")

    base = tmp_path.resolve()
    assert missions == [
        Mission(base / "sg001/m1", 1),
        Mission(base / "sg002", 2),
        Mission(base / "sg004", 4),
    ]


def test_load_missions_follows_domains_with_and_without_root(tmp_path: pathlib.Path) -> None:
    (tmp_path / "a").mkdir()
    (tmp_path / "a" / "missions.yml").write_text("missions:\n  - {glider: 10, path: sg010}\n")
    (tmp_path / "b").mkdir()
    (tmp_path / "b" / "missions.yml").write_text("missions:\n  - {glider: 20}\n")
    (tmp_path / "missions.yml").write_text(
        f"""
missions:
  - {{glider: 1}}
domains:
  root: {{missions: ignored.yml}}
  a: {{missions: a/missions.yml, root: {tmp_path / "a_root"}}}
  b: {{missions: b/missions.yml}}
"""
    )

    missions = MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml")

    base = tmp_path.resolve()
    assert missions == [
        Mission(base / "sg001", 1),
        Mission(tmp_path / "a_root" / "sg010", 10),
        Mission(base / "b" / "sg020", 20),
    ]


def test_load_missions_includes_and_nesting(tmp_path: pathlib.Path) -> None:
    (tmp_path / "leaf.yml").write_text("missions:\n  - {glider: 30}\n")
    (tmp_path / "mid.yml").write_text("includes:\n  leaf: {missions: leaf.yml}\n")
    (tmp_path / "missions.yml").write_text("includes:\n  mid: {missions: mid.yml}\n")

    missions = MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml")

    assert missions == [Mission(tmp_path.resolve() / "sg030", 30)]


def test_load_missions_missing_domain_and_cycle(tmp_path: pathlib.Path) -> None:
    (tmp_path / "missions.yml").write_text(
        """
missions:
  - {glider: 1}
domains:
  gone: {missions: gone.yml}
  self: {missions: missions.yml}
"""
    )

    missions = MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml")

    assert missions == [Mission(tmp_path.resolve() / "sg001", 1)]


@pytest.mark.parametrize("content", ["just a string\n", "other: 1\n", "missions: [\n"])
def test_load_missions_malformed_top_level(tmp_path: pathlib.Path, content: str) -> None:
    (tmp_path / "missions.yml").write_text(content)

    assert MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml") is None


def test_load_missions_unreadable(tmp_path: pathlib.Path) -> None:
    assert MakeKMLSSHMissions.load_active_missions(tmp_path / "missing.yml") is None


def test_load_missions_single_group_mode(tmp_path: pathlib.Path) -> None:
    """follow_includes=False/default_path=False: the pre-sites.yml behavior."""
    (tmp_path / "a.yml").write_text("missions:\n  - {glider: 10, path: sg010}\n")
    (tmp_path / "missions.yml").write_text(
        """
missions:
  - {glider: 1, path: sg001}
  - {glider: 2}
domains:
  a: {missions: a.yml}
"""
    )

    missions = MakeKMLSSHMissions.load_active_missions(
        tmp_path / "missions.yml", follow_includes=False, default_path=False
    )

    assert missions == [Mission(tmp_path.resolve() / "sg001", 1)]


def test_load_missions_domains_only_file_in_single_group_mode(tmp_path: pathlib.Path) -> None:
    """A master with only domains: has nothing of its own to process."""
    (tmp_path / "missions.yml").write_text("domains:\n  a: {missions: a.yml}\n")

    assert (
        MakeKMLSSHMissions.load_active_missions(tmp_path / "missions.yml", follow_includes=False)
        is None
    )


# --- assign_missions --------------------------------------------------------


def test_assign_missions(tmp_path: pathlib.Path) -> None:
    outer = _site("outer", tmp_path / "outer", jailed=False)  # tree: outer/home
    jailed = _site("jailed", tmp_path / "jails" / "j1")  # tree: jails/j1
    nested = _site("nested", tmp_path / "outer" / "home" / "inner")  # inside outer's tree
    sites = {"outer": outer, "jailed": jailed, "nested": nested}

    in_outer = Mission(tmp_path / "outer" / "home" / "sg001", 1)
    in_jail = Mission(tmp_path / "jails" / "j1" / "home" / "sg002", 2)
    in_nested = Mission(tmp_path / "outer" / "home" / "inner" / "home" / "sg003", 3)
    stray = Mission(tmp_path / "elsewhere" / "sg004", 4)

    by_site, unmatched = MakeKMLSSHMissions.assign_missions(
        [in_outer, in_jail, in_nested, stray], sites
    )

    assert by_site == {"outer": [in_outer], "jailed": [in_jail], "nested": [in_nested]}
    assert list(by_site) == ["outer", "jailed", "nested"]
    assert unmatched == [stray]


# --- find_last_update -------------------------------------------------------


def test_find_last_update(tmp_path: pathlib.Path) -> None:
    assert MakeKMLSSHMissions.find_last_update(tmp_path / "missing") is None
    assert MakeKMLSSHMissions.find_last_update(tmp_path) is None
    (tmp_path / "f.nc").write_text("")
    assert MakeKMLSSHMissions.find_last_update(tmp_path) == pytest.approx(time.time(), abs=60)


# --- process_site_missions --------------------------------------------------


@pytest.fixture
def kml_stubs(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> dict[str, list]:
    """Stubs make_kml and the MakeKML.py merge path, recording calls."""
    calls: dict[str, list] = {"make_kml": [], "run_cmd_shell": [], "notifyVis": []}

    def _make_kml(*args: object, **kwargs: object) -> str:
        calls["make_kml"].append(args)
        return str(tmp_path / "fake.kmz")

    monkeypatch.setattr(MakeKMLSSHMissions.MakeKMLSSH, "make_kml", _make_kml)
    monkeypatch.setattr(MakeKMLSSHMissions.Utils, "check_lock_file", lambda base_opts, name: 0)
    monkeypatch.setattr(
        MakeKMLSSHMissions.Utils,
        "run_cmd_shell",
        lambda cmd_line: calls["run_cmd_shell"].append(cmd_line) or (0, None),
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions.Utils, "notifyVis", lambda *a, **kw: calls["notifyVis"].append(a)
    )
    return calls


def _mission_dir(tmp_path: pathlib.Path, glider: int) -> Mission:
    mission_dir = tmp_path / f"sg{glider:03d}"
    mission_dir.mkdir()
    (mission_dir / "sg_plot_constants.m").write_text("")
    return Mission(mission_dir, glider)


def test_process_site_missions_success(tmp_path: pathlib.Path, kml_stubs: dict[str, list]) -> None:
    mission = _mission_dir(tmp_path, 7)

    assert MakeKMLSSHMissions.process_site_missions(FakeBaseOpts(tmp_path), [mission])

    assert len(kml_stubs["make_kml"]) == 1
    assert "--mission_dir" in kml_stubs["run_cmd_shell"][0]
    assert "sg007.conf" in kml_stubs["run_cmd_shell"][0]
    assert kml_stubs["notifyVis"][0][0] == 7


def test_process_site_missions_skips_missing_plot_constants(
    tmp_path: pathlib.Path, kml_stubs: dict[str, list]
) -> None:
    (tmp_path / "sg008").mkdir()

    assert MakeKMLSSHMissions.process_site_missions(
        FakeBaseOpts(tmp_path), [Mission(tmp_path / "sg008", 8)]
    )
    assert kml_stubs["make_kml"] == []


def test_process_site_missions_no_merge(tmp_path: pathlib.Path, kml_stubs: dict[str, list]) -> None:
    mission = _mission_dir(tmp_path, 9)

    assert MakeKMLSSHMissions.process_site_missions(FakeBaseOpts(tmp_path, mergessh=False), [mission])
    assert kml_stubs["run_cmd_shell"] == []


def test_process_site_missions_logs_error_when_makekml_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
    kml_stubs: dict[str, list],
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A failed MakeKML.py run must be logged explicitly, not silently missed."""
    mission = _mission_dir(tmp_path, 7)
    monkeypatch.setattr(MakeKMLSSHMissions.Utils, "run_cmd_shell", lambda cmd_line: (1, None))

    with caplog.at_level(logging.ERROR):
        ok = MakeKMLSSHMissions.process_site_missions(FakeBaseOpts(tmp_path), [mission])

    assert not ok
    assert any("MakeKML.py exited 1" in r.message for r in caplog.records)


def test_process_site_missions_make_kml_raises(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, kml_stubs: dict[str, list]
) -> None:
    first = _mission_dir(tmp_path, 1)
    second = _mission_dir(tmp_path, 2)

    def _boom(*args: object, **kwargs: object) -> str:
        if "sg001" in str(args[1]):
            raise RuntimeError("boom")
        return "ok.kmz"

    monkeypatch.setattr(MakeKMLSSHMissions.MakeKMLSSH, "make_kml", _boom)

    assert not MakeKMLSSHMissions.process_site_missions(FakeBaseOpts(tmp_path), [first, second])
    # The second mission is still processed
    assert len(kml_stubs["run_cmd_shell"]) == 1


# --- site children ----------------------------------------------------------


def test_child_command(tmp_path: pathlib.Path) -> None:
    base_opts = FakeBaseOpts(tmp_path, mergessh=False, fetch_ssh=True, verbose=True)

    cmd = MakeKMLSSHMissions.child_command(base_opts, "aoml")

    assert cmd[0] == sys.executable
    assert cmd[1].endswith("MakeKMLSSHMissions.py")
    assert cmd[2:] == [
        "--site_child",
        "aoml",
        "--no-mergessh",
        "--fetch_ssh",
        "--verbose",
        str(tmp_path / "data"),
        str(tmp_path / "missions.yml"),
    ]


def test_child_popen_kwargs_same_user(tmp_path: pathlib.Path) -> None:
    kwargs = MakeKMLSSHMissions.child_popen_kwargs(_site("me", tmp_path))

    assert set(kwargs) == {"env"}
    assert kwargs["env"].get("HOME") == os.environ.get("HOME")


def test_child_popen_kwargs_drops_to_runner(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(MakeKMLSSHMissions.os, "getgrouplist", lambda user, gid: [gid, 20])

    kwargs = MakeKMLSSHMissions.child_popen_kwargs(_site("x", tmp_path, uid=5001, gid=6001))

    assert (kwargs["user"], kwargs["group"], kwargs["extra_groups"]) == (5001, 6001, [6001, 20])
    assert kwargs["env"]["HOME"] == "/tmp/makekml-ssh-runner-x"
    assert kwargs["env"]["MPLCONFIGDIR"] == "/tmp/makekml-ssh-runner-x"


def test_missions_json_round_trip(tmp_path: pathlib.Path) -> None:
    missions = [Mission(tmp_path / "sg001", 1), Mission(tmp_path / "sg002", 2)]

    text = MakeKMLSSHMissions.missions_to_json(missions)

    assert MakeKMLSSHMissions.missions_from_json(text) == missions


# Stand-in for a site child: records the missions it was given, fails for glider 666
FAKE_CHILD = """
import json, pathlib, sys
markers, site = pathlib.Path(sys.argv[1]), sys.argv[2]
missions = json.loads(sys.stdin.read())
for m in missions:
    (markers / f"{site}-sg{m['glider']:03d}").write_text(m["path"])
sys.exit(1 if any(m["glider"] == 666 for m in missions) else 0)
"""


@pytest.mark.parametrize("jobs", [1, 2])
def test_run_sites(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, jobs: int
) -> None:
    markers = tmp_path / "markers"
    markers.mkdir()
    fake_child = tmp_path / "fake_child.py"
    fake_child.write_text(FAKE_CHILD)
    monkeypatch.setattr(
        MakeKMLSSHMissions,
        "child_command",
        lambda base_opts, name: [sys.executable, str(fake_child), str(markers), name],
    )
    sites = {name: _site(name, tmp_path / name) for name in ("a", "b", "c")}
    by_site = {
        "a": [Mission(tmp_path / "a" / "sg001", 1)],
        "b": [Mission(tmp_path / "b" / "sg002", 2), Mission(tmp_path / "b" / "sg003", 3)],
        "c": [Mission(tmp_path / "c" / "sg666", 666)],
    }

    failed = MakeKMLSSHMissions.run_sites(FakeBaseOpts(tmp_path), by_site, sites, jobs)

    assert failed == ["c"]
    assert sorted(p.name for p in markers.iterdir()) == ["a-sg001", "b-sg002", "b-sg003", "c-sg666"]
    assert (markers / "b-sg003").read_text() == str(tmp_path / "b" / "sg003")


def test_run_sites_permission_error(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    """A worker without CAP_SETUID/CAP_SETGID fails that site loudly and moves on."""
    started: list[str] = []
    real_popen = MakeKMLSSHMissions.subprocess.Popen

    def _popen(cmd: list[str], **kwargs: object) -> object:
        if "user" in kwargs:
            raise PermissionError(1, "Operation not permitted")
        started.append(cmd[-1])
        return real_popen([sys.executable, "-c", "import sys; sys.stdin.read()"], **kwargs)

    monkeypatch.setattr(MakeKMLSSHMissions.subprocess, "Popen", _popen)
    monkeypatch.setattr(MakeKMLSSHMissions.os, "getgrouplist", lambda user, gid: [gid])
    monkeypatch.setattr(MakeKMLSSHMissions, "child_command", lambda base_opts, name: [name])
    sites = {
        "nocaps": _site("nocaps", tmp_path / "n", uid=5001, gid=6001),
        "me": _site("me", tmp_path / "m"),
    }
    by_site = {name: [Mission(tmp_path / name, 1)] for name in sites}

    with caplog.at_level(logging.INFO):
        failed = MakeKMLSSHMissions.run_sites(FakeBaseOpts(tmp_path), by_site, sites, 1)

    assert failed == ["nocaps"]
    assert started == ["me"]
    assert any(
        r.levelno == logging.CRITICAL and "nocaps" in r.message and "CAP_SETUID" in r.message
        for r in caplog.records
    )


def test_site_child_mode(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missions = [Mission(tmp_path / "sg001", 1)]
    received: list[list[Mission]] = []
    monkeypatch.setattr(MakeKMLSSHMissions, "BaseLogger", lambda *a, **kw: None)
    monkeypatch.setattr(
        MakeKMLSSHMissions,
        "process_site_missions",
        lambda base_opts, ms: received.append(ms) or True,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(MakeKMLSSHMissions.missions_to_json(missions)))
    # A child never reads the sites file
    base_opts = FakeBaseOpts(tmp_path, site_child="aoml", sites_config=tmp_path / "missing.yml")

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0
    assert received == [missions]

    monkeypatch.setattr(sys, "stdin", io.StringIO("not json"))
    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 1


def test_site_child_drops_capabilities_first(
    tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The child sheds inherited capabilities before reading or processing anything,
    and processes nothing if it can't."""
    events: list[str] = []
    monkeypatch.setattr(MakeKMLSSHMissions, "BaseLogger", lambda *a, **kw: None)
    monkeypatch.setattr(
        MakeKMLSSHMissions.Capabilities, "drop_all_capabilities", lambda: events.append("drop")
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions,
        "process_site_missions",
        lambda base_opts, ms: events.append("process") or True,
    )
    monkeypatch.setattr(sys, "stdin", io.StringIO(MakeKMLSSHMissions.missions_to_json([])))
    base_opts = FakeBaseOpts(tmp_path, site_child="aoml")

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0
    assert events == ["drop", "process"]

    def _fail() -> None:
        raise PermissionError(1, "Operation not permitted")

    events.clear()
    monkeypatch.setattr(MakeKMLSSHMissions.Capabilities, "drop_all_capabilities", _fail)
    monkeypatch.setattr(sys, "stdin", io.StringIO(MakeKMLSSHMissions.missions_to_json([])))
    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 1
    assert events == []


# --- main -------------------------------------------------------------------


SITES_YML = """
jailed:
  watch_dir: {tmp}/jails/j1/home/rundir
  jail_root: {tmp}/jails/j1
  runner_user: runner-j1
"""


@pytest.fixture
def main_env(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> tuple[FakeBaseOpts, list[tuple]]:
    """A master missions.yml with one site mission and one stray; run_sites recorded."""
    monkeypatch.setattr(MakeKMLSSHMissions, "BaseLogger", lambda *a, **kw: None)
    monkeypatch.setattr(
        SiteConfig,
        "lookup_user",
        lambda name: SiteConfig.pwd.struct_passwd(
            (name, "x", os.geteuid(), os.getegid(), "", "/", "/bin/false")
        ),
    )
    (tmp_path / "sites.yml").write_text(SITES_YML.format(tmp=tmp_path))
    (tmp_path / "data").mkdir()
    (tmp_path / "data" / "ssh.nc").write_text("")
    (tmp_path / "missions.yml").write_text(
        f"""
missions:
  - {{glider: 1, path: {tmp_path}/jails/j1/home/sg001}}
  - {{glider: 2, path: {tmp_path}/elsewhere/sg002}}
"""
    )
    runs: list[tuple] = []
    monkeypatch.setattr(
        MakeKMLSSHMissions,
        "run_sites",
        lambda base_opts, by_site, sites, jobs: runs.append((by_site, list(sites), jobs)) or [],
    )
    return FakeBaseOpts(tmp_path), runs


def test_main_assigns_and_runs(
    main_env: tuple[FakeBaseOpts, list[tuple]], caplog: pytest.LogCaptureFixture
) -> None:
    base_opts, runs = main_env

    with caplog.at_level(logging.WARNING):
        assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0

    (by_site, site_names, jobs), = runs
    assert site_names == ["jailed"]
    assert [m.glider for m in by_site["jailed"]] == [1]
    assert jobs == 1
    assert any("sg002" in r.message and "not under any site" in r.message for r in caplog.records)


def test_main_site_failure_exits_1(
    main_env: tuple[FakeBaseOpts, list[tuple]], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_opts, _ = main_env
    monkeypatch.setattr(MakeKMLSSHMissions, "run_sites", lambda *a: ["jailed"])

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 1


def test_main_stale_data_does_nothing(
    main_env: tuple[FakeBaseOpts, list[tuple]], monkeypatch: pytest.MonkeyPatch
) -> None:
    base_opts, runs = main_env
    monkeypatch.setattr(
        MakeKMLSSHMissions, "find_last_update", lambda data_dir: time.time() - 6 * 24 * 3600
    )

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0
    assert runs == []

    base_opts.force = True
    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0
    assert len(runs) == 1


def test_main_without_sites_config_is_single_group(
    main_env: tuple[FakeBaseOpts, list[tuple]],
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: pathlib.Path,
) -> None:
    """No --sites_config: the given file's own missions, processed in-process
    as the current user - no site children, no domains followed."""
    base_opts, runs = main_env
    base_opts.sites_config = None
    (tmp_path / "missions.yml").write_text(
        f"""
missions:
  - {{glider: 1, path: {tmp_path}/sg001}}
  - {{glider: 2}}
  - {{glider: 3, path: {tmp_path}/sg003, status: complete}}
domains:
  a: {{missions: a.yml}}
"""
    )
    (tmp_path / "a.yml").write_text(f"missions:\n  - {{glider: 10, path: {tmp_path}/sg010}}\n")
    processed: list[list[Mission]] = []
    monkeypatch.setattr(
        MakeKMLSSHMissions,
        "process_site_missions",
        lambda b, missions: processed.append(missions) or True,
    )

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 0
    assert processed == [[Mission(tmp_path / "sg001", 1)]]
    assert runs == []

    monkeypatch.setattr(MakeKMLSSHMissions, "process_site_missions", lambda b, missions: False)
    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 1


@pytest.mark.parametrize("broken", ["sites", "missions", "jobs"])
def test_main_bad_inputs_exit_1(
    main_env: tuple[FakeBaseOpts, list[tuple]], tmp_path: pathlib.Path, broken: str
) -> None:
    base_opts, runs = main_env
    if broken == "sites":
        base_opts.sites_config = tmp_path / "missing.yml"
    elif broken == "missions":
        base_opts.mission_yml = tmp_path / "missing.yml"
    else:
        base_opts.jobs = 0

    assert MakeKMLSSHMissions.main(base_opts=base_opts) == 1
    assert runs == []
