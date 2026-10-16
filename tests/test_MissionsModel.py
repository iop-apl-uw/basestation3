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


"""missions.yml checker: warnings at file:line (it only reports), domains/includes, the CLI and its users."""

import logging
import pathlib
import subprocess
import sys

import pytest
import yaml

import Base  # noqa: F401 - normal import order
import BaseLog
import MissionsModel

CLEAN = """\
organization:
  orgname: Org
colors:
  blue: &blue "#0000ff"
assets:
  A: { type: fixed, lat: 1, lon: 2, color: *blue }
endpoints:
  defaults: { groups: [basic] }
missions:
  - { glider: 249, mission: Exp_May24, path: sg249, status: active }
  - { glider: 249, mission: Exp_Apr24, path: sg249/Exp_Apr24, status: complete, reason: "CTD, optode failed" }
"""


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: pathlib.Path, text: str, name: str = "missions.yml") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_clean_file_and_quiet_anchor_holder(tmp_path: pathlib.Path) -> None:
    """colors: only holds anchors aliased from assets - accepted quietly."""
    data, warnings, problems = MissionsModel.check_file(_write(tmp_path, CLEAN))
    assert (warnings, problems) == ([], []) and data is not None
    assert data["assets"]["A"]["color"] == "#0000ff"  # the alias, resolved


@pytest.mark.parametrize(
    ("mission", "message"),
    [
        ("{ glider: 1, reason: CTD, optode failed }", "missions.0.optode failed: not a mission key - ignored - a comma inside"),
        ("{ glider: 1, status:active }", "missions.0.status:active: not a mission key - ignored - needs a space after the colon ('status: active')"),
        ("{ glider: 1, organization: X }", "missions.0.organization: not a mission key - ignored"),
        ("{ mission: X }", "missions.0: no glider - skipped by vis"),
        ("{ glider: abc }", "missions.0.glider: 'abc' isn't a glider number - skipped by vis"),
        ("{ glider: 1, path: 5 }", "missions.0.path: should be text, not int"),
        ("{ glider: 1, status: done }", "missions.0.status: 'done' isn't one of active, complete"),
        ("just text", "missions.0: should be a mapping, not str - skipped by vis"),
    ],
)
def test_mission_warnings(tmp_path: pathlib.Path, mission: str, message: str) -> None:
    path = _write(tmp_path, f"missions:\n  - {mission}\n")
    data, warnings, problems = MissionsModel.check_file(path)
    assert data is not None and problems == [] and len(warnings) == 1
    assert warnings[0].startswith(f"{path}:2: ") and message in warnings[0]


def test_duplicates(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "missions:\n  - { glider: 1, mission: a }\n  - { glider: 1, mission: b }\n"
        "  - { glider: 2, mission: c, status: complete }\n  - { glider: 2, mission: c, status: complete }\n",
    )
    _, warnings, _ = MissionsModel.check_file(path)
    assert warnings == [
        f"{path}:3: missions.1: sg001 already has an active mission (entry 0) - vis uses that one",
        f"{path}:5: missions.3: sg002 c is listed twice (entry 2) - vis skips this one",
    ]


def test_top_level_and_sections(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "mission:\n  - x\n"
        "unused:\n  red: &red \"#ff0000\"\n"
        "missions: { glider: 1 }\n"
        "endpoints:\n  kml: { allow: true }\n  pos: text\n"
        "assets:\n  B: { type: fixed, color: 7e1e9c }\n  C: { type: fixed, color: red }\n"
        "domains:\n  root: seaglider.pub\n  x: { root: /a }\n"
        "admins: 3\n",
    )
    _, warnings, problems = MissionsModel.check_file(path)
    text = "\n".join(warnings)
    assert problems == []
    assert f"{path}:1: mission: not a missions.yml key - ignored" in text
    assert f"{path}:3: unused: not a missions.yml key" in text  # anchors never aliased
    assert f"{path}:5: missions: should be a list of missions, not dict" in text
    assert f"{path}:7: endpoints.kml.allow: not a endpoint key - ignored" in text
    assert f"{path}:8: endpoints.pos: should be a mapping, not str" in text
    assert f"{path}:10: assets.B.color: '7e1e9c' isn't a color" in text
    assert "assets.C" not in text and "domains.root" not in text
    assert f"{path}:14: domains.x: no missions file - skipped" in text
    assert "admins" not in text  # types of other top-level keys aren't checked
    _, warnings, _ = MissionsModel.check_file(_write(tmp_path, "assets: [a]\n", "assets.yml"))
    assert warnings[0].endswith("assets: should be a mapping, not list")


def test_unusable(tmp_path: pathlib.Path) -> None:
    syntax = _write(tmp_path, "missions:\n  - { glider: 1 }\n - { glider: 2 }\n")
    data, _, problems = MissionsModel.check_file(syntax)
    assert data is None and problems[0].startswith(f"{syntax}:3: ")
    listed = _write(tmp_path, "- a\n", "b.yml")
    assert MissionsModel.check_file(listed)[2] == [f"{listed}: missions.yml must be a mapping (got list)"]
    assert "could not read" in MissionsModel.check_file(tmp_path / "missing.yml")[2][0]
    assert MissionsModel._anchor_holders("a: [x\n") == set() and MissionsModel._anchor_holders("- a\n") == set()


def test_domains_followed(tmp_path: pathlib.Path) -> None:
    """domains:/includes: files are checked too (path_map for server paths), each once; --no-follow checks just one."""
    mirror = tmp_path / "mirror"
    (mirror / "a").mkdir(parents=True)
    _write(mirror / "a", "missions:\n  - { glider: 1, colour: red }\n")
    _write(tmp_path, "includes:\n  back: { missions: master.yml }\n", "loop.yml")
    master = _write(
        tmp_path,
        "domains:\n  root: x\n  a: { missions: /home/jails/a/missions.yml }\n"
        "  gone: { missions: /home/jails/gone/missions.yml }\n  loop: { missions: loop.yml }\n",
        "master.yml",
    )
    _, warnings, _ = MissionsModel.check_file(master, {"/home/jails": str(mirror)})
    text = "\n".join(warnings)
    assert f"{mirror / 'a' / 'missions.yml'}:2: missions.0.colour: not a mission key" in text
    assert f"{mirror / 'gone' / 'missions.yml'} not found - not checked" in text
    assert "already checked (cyclic includes?)" in text
    _, warnings, _ = MissionsModel.check_file(master, {"/home/jails": str(mirror)}, follow=False)
    assert warnings == []
    broken = _write(mirror / "a", "missions:\n  - { glider: 1 }\n - x\n")
    assert MissionsModel.check_file(master, {"/home/jails": str(mirror)})[2][0].startswith(f"{broken}:3:")
    assert MissionsModel.apply_path_map("/home/jails", {"/home/jails/": "/m"}) == pathlib.Path("/m")
    assert MissionsModel.apply_path_map("/elsewhere/x", {"/home/jails": "/m"}) == pathlib.Path("/elsewhere/x")


def test_cli(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    clean = _write(tmp_path, CLEAN)
    with caplog.at_level(logging.INFO):
        assert MissionsModel.main(["--verbose", "check", str(clean)]) == 0
    assert f"{clean}: OK" in caplog.text
    capsys.readouterr()
    assert MissionsModel.main(["dump", str(clean)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["assets"]["A"]["color"] == "#0000ff"
    bad = _write(tmp_path, "missions:\n  - { glider: 1, status:active }\n", "bad.yml")
    with caplog.at_level(logging.WARNING):
        assert MissionsModel.main(["check", str(bad)]) == 1
        assert MissionsModel.main(["check", str(bad), "--no-follow", "--path_map", "/a=/b"]) == 1
        assert MissionsModel.main(["check", str(bad), "--path_map", "nonsense"]) == 1
    assert "needs a space after the colon" in caplog.text and "expected FROM=TO" in caplog.text
    broken = _write(tmp_path, "- a\n", "broken.yml")
    assert MissionsModel.main(["check", str(broken)]) == 1
    assert MissionsModel.main(["dump", str(broken)]) == 1


def test_make_kml_ssh_missions_logs_warnings(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """MakeKMLSSHMissions logs the checker's warnings; what it loads doesn't change."""
    sys.path.insert(0, "ssh")
    import MakeKMLSSHMissions

    (tmp_path / "sg001").mkdir()
    path = _write(tmp_path, "missions:\n  - { glider: 1, path: sg001, status:active }\n")
    with caplog.at_level(logging.WARNING):
        missions = MakeKMLSSHMissions.load_active_missions(path)
    assert missions is not None and [m.glider for m in missions] == [1]
    assert "needs a space after the colon" in caplog.text
    with caplog.at_level(logging.ERROR):
        assert MakeKMLSSHMissions.load_active_missions(_write(tmp_path, "- a\n", "b.yml")) is None
    assert "must be a mapping" in caplog.text


def test_get_active_missions_warns_on_stderr(tmp_path: pathlib.Path) -> None:
    """tools/GetActiveMissions.py writes the warnings to stderr; its output is unchanged."""
    path = _write(tmp_path, "missions:\n  - { glider: 1, path: sg001, status:active }\n  - { glider: 2, path: sg002, status: complete }\n")
    run = subprocess.run(
        [sys.executable, "tools/GetActiveMissions.py", str(path)], capture_output=True, text=True, check=True
    )
    assert run.stdout == f"glider:1 mission_dir:{tmp_path / 'sg001'}\n"
    assert "needs a space after the colon" in run.stderr
