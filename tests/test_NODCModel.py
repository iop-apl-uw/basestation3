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

"""NODC.yml validation: per-file keys and values, the site/mission merge, the CLI and update_globals_from_nodc."""

import logging
import pathlib
from types import SimpleNamespace

import pytest
import yaml

import Base  # noqa: F401 - normal import order
import BaseLog
import BaseNetCDF
import NODCModel

SAMPLE = pathlib.Path("sg000/NODC.yml")
SAMPLE_VALUES = {
    "license": "These data may be redistributed and used without restriction.",
    "keywords": "Water Temperature, Conductivity, Salinity, Density, Potential Density, Potential Temperature",
}
# The shape of the real per-deployment files (folded multi-line strings, only overridable keys)
DEPLOYMENT = """\
institution: >-
  Some University
  Some Department
creator_name: A Person
creator_email: a.person@example.edu
contributor_name: >-
  A Person
  B Person
title: Data from Seaglider SG123 deployed on 2026-01-01
keywords: Water Temperature, Conductivity, Salinity, Oxygen
"""


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_sample_and_deployment_valid(tmp_path: pathlib.Path) -> None:
    for path in (SAMPLE, _write(tmp_path, "NODC.yml", DEPLOYMENT)):
        loaded, problems, warnings, bad = NODCModel.check_file(path)
        assert loaded is not None and (problems, warnings, bad) == ([], [], set())
    assert NODCModel.load_merged([SAMPLE]).values == SAMPLE_VALUES


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("title: [a, b]\n", "title: must be a string or a number, not list (input: ['a', 'b']) - ignored"),
        ("title: {a: 1}\n", "title: must be a string or a number, not dict"),
        ("title: yes\n", "title: must be a string or a number, not bool"),
        ("featureType: profile\n", "featureType: set by basestation - can't be overridden in NODC.yml - ignored"),
        ("5: x\n", "attribute name 5 must be a string - ignored"),
    ],
)
def test_bad_key_dropped(tmp_path: pathlib.Path, text: str, message: str) -> None:
    """Each bad key is an error at its line and dropped; the rest of the file still applies."""
    path = _write(tmp_path, "NODC.yml", "summary: kept\n" + text)
    loaded, problems, _, bad = NODCModel.check_file(path)
    assert loaded is not None and len(problems) == 1 and len(bad) == 1
    assert problems[0].startswith(f"{path}:2: {message}")
    assert NODCModel.load_merged([path]).values == {"summary": "kept"}


def test_unknown_key_warned_and_kept(tmp_path: pathlib.Path) -> None:
    path = _write(tmp_path, "NODC.yml", "my_attr: 3.5\n")
    _, problems, warnings, _ = NODCModel.check_file(path)
    assert problems == [] and warnings == [f"{path}:1: my_attr: not a known netCDF global attribute - written as given"]
    assert NODCModel.load_merged([path]).values == {"my_attr": 3.5}


def test_file_unusable(tmp_path: pathlib.Path) -> None:
    """A YAML error, a non-mapping or an unreadable file can't be used; an empty one is empty."""
    syntax = _write(tmp_path, "a.yml", "title: [x\n")
    assert NODCModel.check_file(syntax)[0] is None
    listed = _write(tmp_path, "b.yml", "- title\n")
    loaded, problems, _, _ = NODCModel.check_file(listed)
    assert loaded is None and problems == [f"{listed}: NODC.yml must map attribute names to values (got list)"]
    loaded, problems, _, _ = NODCModel.check_file(tmp_path)
    assert loaded is None and problems[0].startswith(f"{tmp_path}: could not read (")
    loaded, problems, _, _ = NODCModel.check_file(_write(tmp_path, "c.yml", "# nothing\n"))
    assert loaded is not None and loaded.data == {} and problems == []


def test_merge(tmp_path: pathlib.Path) -> None:
    """The mission overrides the site, a null leaves the earlier value, a bad mission file leaves the site's."""
    site = _write(tmp_path, "site.yml", "title: site title\nsummary: site summary\nlicense: site license\n")
    mission = _write(tmp_path, "mission.yml", "title: mission title\nlicense: null\n")
    result = NODCModel.load_merged([site, mission])
    assert result.values == {"title": "mission title", "summary": "site summary"}
    changes = "\n".join(result.changes)
    assert f"{mission}:1: title: overrides {site}:1" in changes and f"{mission}:2: license: removes it" in changes
    broken = _write(tmp_path, "broken.yml", "- not a mapping\n")
    result = NODCModel.load_merged([site, broken])
    assert result.values["title"] == "site title" and len(result.problems) == 1


def test_config_files(tmp_path: pathlib.Path) -> None:
    """The order the files are merged in: basestation etc, --group_etc, mission dir."""
    for sub in ("etc", "group", "mission"):
        (tmp_path / sub).mkdir()
    (tmp_path / "mission/NODC.yml").write_text("{}\n")
    opts = SimpleNamespace(basestation_etc=tmp_path / "etc", group_etc=None, mission_dir=tmp_path / "mission")
    assert NODCModel.config_files(opts) == [tmp_path / "mission/NODC.yml"]
    (tmp_path / "etc/NODC.yml").write_text("{}\n")
    (tmp_path / "group/NODC.yml").write_text("{}\n")
    assert NODCModel.config_files(opts) == [tmp_path / "etc/NODC.yml", tmp_path / "mission/NODC.yml"]
    opts.group_etc = tmp_path / "group"
    assert NODCModel.config_files(opts) == [
        tmp_path / "etc/NODC.yml",
        tmp_path / "group/NODC.yml",
        tmp_path / "mission/NODC.yml",
    ]


def test_update_globals_site_group_mission(tmp_path: pathlib.Path) -> None:
    """The group file overrides the site, the mission overrides the group; null falls back to the earlier value."""
    for sub, text in (
        ("etc", "license: site license\ninstitution: site institution\n"),
        ("group", "institution: group institution\ncreator_name: group creator\ntitle: group title\n"),
        ("mission", "title: mission title\ncreator_name: null\n"),
    ):
        (tmp_path / sub).mkdir()
        (tmp_path / sub / "NODC.yml").write_text(text)
    opts = SimpleNamespace(basestation_etc=tmp_path / "etc", group_etc=tmp_path / "group", mission_dir=tmp_path / "mission")
    globals_d = {"creator_name": "default creator"}
    BaseNetCDF.update_globals_from_nodc(opts, globals_d)
    assert globals_d == {
        "license": "site license",
        "institution": "group institution",
        "creator_name": "default creator",
        "title": "mission title",
    }


def test_update_globals_from_nodc(tmp_path: pathlib.Path) -> None:
    """A bad key raises NODC_CONFIG and the rest still apply; an empty mission file no longer loses the site's values."""
    (tmp_path / "etc").mkdir()
    (tmp_path / "mission").mkdir()
    (tmp_path / "etc/NODC.yml").write_text(SAMPLE.read_text())
    (tmp_path / "mission/NODC.yml").write_text("title: My title\nfeatureType: profile\n")
    opts = SimpleNamespace(basestation_etc=tmp_path / "etc", mission_dir=tmp_path / "mission")
    globals_d = {"featureType": "trajectory", "title": "default"}
    BaseNetCDF.update_globals_from_nodc(opts, globals_d)
    assert globals_d == {"featureType": "trajectory", "title": "My title", **SAMPLE_VALUES}
    (alert,) = BaseLog.log_alerts()["NODC_CONFIG"]
    assert "featureType: set by basestation" in alert

    (tmp_path / "mission/NODC.yml").write_text("")
    globals_d = {}
    BaseNetCDF.update_globals_from_nodc(opts, globals_d)
    assert globals_d == SAMPLE_VALUES


def test_cli_single_file(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    assert NODCModel.main(["check", str(SAMPLE)]) == 0
    capsys.readouterr()
    assert NODCModel.main(["dump", str(SAMPLE)]) == 0
    assert yaml.safe_load(capsys.readouterr().out) == SAMPLE_VALUES
    bad = _write(tmp_path, "NODC.yml", "title: [a]\nmy_attr: x\n")
    with caplog.at_level(logging.WARNING):
        assert NODCModel.main(["check", str(bad)]) == 1
        assert NODCModel.main(["dump", str(bad)]) == 1
        assert NODCModel.main(["check"]) == 1
    assert f"{bad}:1: title: must be a string" in caplog.text and f"{bad}:2: my_attr: not a known" in caplog.text
    assert "check needs a NODC.yml file" in caplog.text and capsys.readouterr().out == ""


def test_cli_merged(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    etc = tmp_path / "etc"
    mission = tmp_path / "mission"
    etc.mkdir()
    mission.mkdir()
    (etc / "NODC.yml").write_text(SAMPLE.read_text())
    (mission / "NODC.yml").write_text(DEPLOYMENT)
    args = ["-m", str(mission), "--basestation_etc", str(etc)]
    with caplog.at_level(logging.INFO):
        assert NODCModel.main(["--verbose", "check_merged", *args]) == 0
    assert "keywords: overrides" in caplog.text and "Merged: 7 attribute(s) - license, keywords, institution" in caplog.text
    group = tmp_path / "group"
    group.mkdir()
    (group / "NODC.yml").write_text("sea_name: North Pacific Ocean\n")
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert NODCModel.main(["--verbose", "check_merged", *args, "--group_etc", str(group)]) == 0
    assert f"Reading {group / 'NODC.yml'}" in caplog.text and "Merged: 8 attribute(s)" in caplog.text
    capsys.readouterr()
    assert NODCModel.main(["dump_merged", *args]) == 0
    dumped = yaml.safe_load(capsys.readouterr().out)
    assert dumped["license"] == SAMPLE_VALUES["license"] and dumped["institution"] == "Some University Some Department"
    (mission / "NODC.yml").write_text("featureType: profile\nmy_attr: x\n")
    with caplog.at_level(logging.WARNING):
        assert NODCModel.main(["check_merged", *args]) == 1
        assert NODCModel.main(["check_merged"]) == 1
        assert NODCModel.main(["dump_merged", str(SAMPLE), *args]) == 1
    assert "featureType: set by basestation" in caplog.text and "my_attr: not a known" in caplog.text
    assert "check_merged needs --mission_dir" in caplog.text and "dump_merged takes no file" in caplog.text
