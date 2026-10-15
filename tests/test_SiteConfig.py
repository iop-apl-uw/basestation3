# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

import dataclasses
import pathlib
import pwd

import pytest

import BaseLog
import SiteConfig

GOOD_YAML = """
seaglider:
  watch_dir: {seaglider_dir}
  jail_root: {seaglider_dir}/jail
  runner_user: ioprunner
ioptest:
  watch_dir: {ioptest_dir}
  runner_user: runner-ioptest
  archive: true
"""


@pytest.fixture(autouse=True)
def _fresh_baselog():
    """SiteConfig.main sets up BaseLogger; start each test without one left by another test."""
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _fake_pwent(uid: int, gid: int) -> pwd.struct_passwd:
    return pwd.struct_passwd(
        ("ioprunner", "x", uid, gid, "", "/nonexistent", "/usr/sbin/nologin")
    )


@pytest.fixture
def patch_lookup_user(monkeypatch):
    """Maps a fixed set of account names to fixed uid/gid pairs."""
    known = {
        "ioprunner": (5001, 6001),
        "runner-ioptest": (5002, 6002),
    }

    def _lookup(name: str) -> pwd.struct_passwd:
        try:
            uid, gid = known[name]
        except KeyError:
            raise KeyError(name) from None
        return _fake_pwent(uid, gid)

    monkeypatch.setattr(SiteConfig, "lookup_user", _lookup)
    return known


def test_load_sites_config_valid(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider" / "rundir"
    seaglider_dir.mkdir(parents=True)
    ioptest_dir = tmp_path / "ioptest" / "rundir"
    ioptest_dir.mkdir(parents=True)

    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        GOOD_YAML.format(seaglider_dir=seaglider_dir, ioptest_dir=ioptest_dir)
    )

    sites = SiteConfig.load_sites_config(config_path)

    assert sites is not None
    assert set(sites) == {"seaglider", "ioptest"}

    seaglider = sites["seaglider"]
    assert seaglider.name == "seaglider"
    assert seaglider.watch_dir == seaglider_dir.resolve()
    assert seaglider.jail_root == (seaglider_dir / "jail").resolve()
    assert seaglider.runner_user == "ioprunner"
    assert seaglider.archive is False
    assert seaglider.runner_uid == 5001
    assert seaglider.runner_gid == 6001
    assert seaglider.mission_dir == seaglider.watch_dir
    assert seaglider.python_version == "/opt/basestation/bin/python"
    assert seaglider.queue_scripts is True
    assert seaglider.docker_uid == -1
    assert seaglider.cpu_quota_pct is None
    assert seaglider.cpu_weight is None

    assert seaglider.jailed is True  # inferred: jail_root is set

    ioptest = sites["ioptest"]
    assert ioptest.archive is True
    assert ioptest.jail_root is None
    assert ioptest.jailed is False  # inferred: no jail_root
    assert ioptest.runner_uid == 5002
    assert ioptest.runner_gid == 6002


def test_load_sites_config_unjailed_site_with_jail_root(tmp_path, patch_lookup_user):
    """A site can widen its containment root without being a real jail."""
    watch_dir = tmp_path / "rundir"
    watch_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"test:\n"
        f"  watch_dir: {watch_dir}\n"
        f"  jail_root: {tmp_path}\n"
        f"  jailed: false\n"
        f"  runner_user: ioprunner\n"
    )
    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None
    assert sites["test"].jail_root == tmp_path.resolve()
    assert sites["test"].jailed is False


def test_load_sites_config_jailed_true_requires_jail_root(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    watch_dir = tmp_path / "rundir"
    watch_dir.mkdir()
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {watch_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  jailed: true\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_site_config_is_frozen(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: ioprunner\n")

    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None

    with pytest.raises(dataclasses.FrozenInstanceError):
        sites["seaglider"].name = "not-seaglider"  # ty: ignore[invalid-assignment]


def test_load_sites_config_missing_file(tmp_path, caplog):
    missing = tmp_path / "does-not-exist.yaml"
    assert SiteConfig.load_sites_config(missing) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_empty_file(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_not_a_mapping(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("- just\n- a\n- list\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_entry_not_a_mapping(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("seaglider: just-a-string\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_missing_required_key(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    # Missing watch_dir
    config_path.write_text("seaglider:\n  runner_user: ioprunner\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_bad_scalar_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  docker_uid: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_cpu_fields_present(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_quota_pct: 60\n"
        f"  cpu_weight: 50\n"
    )
    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None
    assert sites["seaglider"].cpu_quota_pct == 60
    assert sites["seaglider"].cpu_weight == 50


def test_load_sites_config_bad_cpu_quota_pct_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_quota_pct: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_bad_cpu_weight_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_weight: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_memory_fields_present(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  memory_high_mb: 512\n"
        f"  memory_max_mb: 1024\n"
    )
    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None
    assert sites["seaglider"].memory_high_mb == 512
    assert sites["seaglider"].memory_max_mb == 1024


def test_load_sites_config_bad_memory_high_mb_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  memory_high_mb: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_bad_memory_max_mb_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  memory_max_mb: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_unknown_runner_user(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: runner-does-not-exist\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_one_bad_entry_fails_whole_file(
    tmp_path, caplog, patch_lookup_user
):
    """A single malformed site must abort the whole load, not just skip it."""
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: ioprunner\n"
        f"broken:\n  runner_user: ioprunner\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None


def test_lookup_user_delegates_to_pwd(monkeypatch):
    sentinel = _fake_pwent(1234, 5678)

    def _fake_getpwnam(name: str) -> pwd.struct_passwd:
        assert name == "someone"
        return sentinel

    monkeypatch.setattr(pwd, "getpwnam", _fake_getpwnam)
    assert SiteConfig.lookup_user("someone") == sentinel


def test_resolve_ids_success(monkeypatch):
    monkeypatch.setattr(
        SiteConfig, "lookup_user", lambda name: _fake_pwent(42, 43)
    )
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=pathlib.Path("/tmp/seaglider"),
        jail_root=None,
        runner_user="ioprunner",
    )
    assert SiteConfig.resolve_ids(site) is True
    assert site.runner_uid == 42
    assert site.runner_gid == 43


def test_is_contained_true_for_root_itself(tmp_path):
    assert SiteConfig.is_contained(tmp_path, tmp_path) is True


def test_is_contained_true_for_descendant(tmp_path):
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)
    assert SiteConfig.is_contained(child, tmp_path) is True


def test_is_contained_false_for_unrelated_path(tmp_path):
    sibling = tmp_path.parent / "not-related"
    assert SiteConfig.is_contained(sibling, tmp_path) is False


def test_is_contained_false_for_parent_of_root(tmp_path):
    # tmp_path's parent is NOT contained within tmp_path itself.
    assert SiteConfig.is_contained(tmp_path.parent, tmp_path) is False


def test_is_contained_rejects_traversal_out_of_root(tmp_path):
    site_root = tmp_path / "site"
    site_root.mkdir()
    escaping = site_root / ".." / "escaped"
    assert SiteConfig.is_contained(escaping, site_root) is False


def test_is_contained_false_when_resolve_raises(tmp_path, monkeypatch):
    def _raise_resolve(self, *args, **kwargs):
        raise OSError("simulated resolve failure")

    monkeypatch.setattr(pathlib.Path, "resolve", _raise_resolve)
    assert SiteConfig.is_contained(tmp_path / "x", tmp_path) is False


def test_site_cgroup_path(tmp_path):
    assert SiteConfig.site_cgroup_path(tmp_path, "aoml") == tmp_path / "site-aoml"


def test_job_cgroup_path(tmp_path):
    assert (
        SiteConfig.job_cgroup_path(tmp_path, "aoml", "job-123")
        == tmp_path / "site-aoml" / "job-job-123"
    )


def test_resolve_ids_unknown_user(monkeypatch, caplog):
    def _raise(name: str) -> pwd.struct_passwd:
        raise KeyError(name)

    monkeypatch.setattr(SiteConfig, "lookup_user", _raise)
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=pathlib.Path("/tmp/seaglider"),
        jail_root=None,
        runner_user="runner-does-not-exist",
    )
    assert SiteConfig.resolve_ids(site) is False
    assert site.runner_uid == -1
    assert site.runner_gid == -1
    assert any(r.levelname == "ERROR" for r in caplog.records)


# --- strict validation (check_sites), the fail-closed report and the CLI -------------------------------------

ENTRY = "s:\n  watch_dir: /srv/s\n  runner_user: ioprunner\n"


@pytest.mark.parametrize(
    ("extra", "line", "message"),
    [
        ("  cpu_quota: 60\n", 4, "s.cpu_quota: Extra inputs are not permitted"),
        ('  jailed: "false"\n', 4, "s.jailed: Input should be a valid boolean"),
        ("  cpu_weight: 0\n", 4, "s.cpu_weight: Input should be greater than or equal to 1"),
        ("  cpu_weight: 20000\n", 4, "s.cpu_weight: Input should be less than or equal to 10000"),
        ('  cpu_quota_pct: "60"\n', 4, "s.cpu_quota_pct: Input should be a valid integer"),
        ("  cpu_quota_pct: 60.5\n", 4, "s.cpu_quota_pct: Input should be a valid integer"),
        ("  jailed: true\n", 1, "s: Value error, jailed is true but jail_root is not set"),
        ("  memory_high_mb: 128\n  memory_max_mb: 64\n", 1, "memory_high_mb (128) is above memory_max_mb (64)"),
        ("  python_version: ''\n", 4, "s.python_version: String should have at least 1 character"),
    ],
)
def test_check_sites_problem_at_line(tmp_path, patch_lookup_user, extra, line, message):
    path = tmp_path / "sites.yaml"
    path.write_text(ENTRY + extra)
    sites, problems = SiteConfig.check_sites(path)
    assert sites is None and len(problems) == 1
    assert problems[0].startswith(f"{path}:{line}: ") and message in problems[0]


def test_check_sites_reports_every_problem(tmp_path, patch_lookup_user):
    """Two bad sites and an unknown user are all reported in one load, and nothing loads (fail closed)."""
    path = tmp_path / "sites.yaml"
    path.write_text(
        "a:\n  watch_dir: /srv/a\n  runner_user: ioprunner\n  cpu_quota: 60\n"
        "b:\n  watch_dir: /srv/b\n"
        "c:\n  watch_dir: /srv/c\n  runner_user: nobody-here\n"
        "d: just text\n"
        "5:\n  watch_dir: /srv/5\n  runner_user: ioprunner\n"
    )
    sites, problems = SiteConfig.check_sites(path)
    assert sites is None
    text = "\n".join(problems)
    assert f"{path}:4: a.cpu_quota: Extra inputs are not permitted" in text
    assert f"{path}:5: b.runner_user: Field required" in text
    assert f"{path}:9: c.runner_user: unknown account 'nobody-here'" in text
    assert f"{path}:10: d: Input should be a valid dictionary" in text
    assert f"{path}:11: site name 5 must be a string" in text
    # Off the server: the form only
    _, problems = SiteConfig.check_sites(path, resolve_users=False)
    assert not any("unknown account" in p for p in problems)


def test_check_sites_unusable_file(tmp_path):
    syntax = tmp_path / "a.yaml"
    syntax.write_text("s: [x\n")
    assert SiteConfig.check_sites(syntax)[1][0].startswith(f"{syntax}:")
    assert SiteConfig.check_sites(tmp_path / "missing.yaml")[1][0].startswith(f"{tmp_path / 'missing.yaml'}: could not read")


@pytest.mark.parametrize("path", ["docs/sites.example.yaml", "testlong/fixtures/sites.yaml"])
def test_repo_samples_check_clean(path):
    sites, problems = SiteConfig.check_sites(pathlib.Path(path), resolve_users=False)
    assert problems == [] and sites


def test_load_sites_config_logs_each_problem_without_traceback(tmp_path, caplog, patch_lookup_user):
    path = tmp_path / "sites.yaml"
    path.write_text(ENTRY + "  cpu_quota: 60\n  archive: maybe\n")
    assert SiteConfig.load_sites_config(path) is None
    messages = [r.getMessage() for r in caplog.records if r.levelname == "ERROR"]
    assert any("s.cpu_quota: Extra inputs" in m for m in messages)
    assert any("s.archive: Input should be a valid boolean" in m for m in messages)
    assert messages[-1].endswith(f"{path}: 2 problem(s) - not loading any site")
    assert "Traceback" not in caplog.text


def test_cli(tmp_path, caplog, capsys, patch_lookup_user):
    import logging

    import yaml

    good = tmp_path / "good.yaml"
    good.write_text(ENTRY + "  cpu_quota_pct: 200\n")
    with caplog.at_level(logging.INFO):
        assert SiteConfig.main(["--verbose", "check", str(good)]) == 0
    assert f"{good}: OK - 1 site(s): s" in caplog.text
    capsys.readouterr()
    assert SiteConfig.main(["dump", str(good)]) == 0
    dumped = yaml.safe_load(capsys.readouterr().out)
    assert dumped["s"]["watch_dir"] == str(pathlib.Path("/srv/s").resolve())
    assert dumped["s"]["cpu_quota_pct"] == 200 and dumped["s"]["queue_scripts"] is True
    assert dumped["s"]["runner_uid"] == 5001
    bad = tmp_path / "bad.yaml"
    bad.write_text("s:\n  watch_dir: /srv/s\n  runner_user: someone-else\n")
    with caplog.at_level(logging.ERROR):
        assert SiteConfig.main(["check", str(bad)]) == 1
    assert "s.runner_user: unknown account" in caplog.text
    assert SiteConfig.main(["check", "--no-resolve_users", str(bad)]) == 0
