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

"""sections.yml checks (warn and proceed), the shared lookup, the CLI and mission_profiles."""

import logging
import pathlib
import re
from types import SimpleNamespace
from typing import Annotated

import pytest
import testutils
import yaml
from pydantic import ConfigDict, Field, StrictInt, create_model

import Base  # noqa: F401 - normal import order
import BaseLog
import SectionsModel

SAMPLE = pathlib.Path("sg000/sections.yml")
FIXTURE = pathlib.Path("testdata/sg686_Shilshole_25Oct25_multidive/sections.yml")
GOOD = """\
defaults:
  top: 0
  bottom: 990
variables:
  temperature: {colormap: thermal, min: 3, max: 20}
  sigma_t: {colormap: dense}
sections:
  "000": {start: 1, stop: -1}
"""


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: pathlib.Path, text: str, name: str = "sections.yml") -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text)
    return p


@pytest.mark.parametrize("path", [SAMPLE, FIXTURE])
def test_repo_files_clean(path: pathlib.Path) -> None:
    cleaned, warnings, problems = SectionsModel.check_file(path)
    assert cleaned is not None and (warnings, problems) == ([], [])


def test_extension_key_left_alone(tmp_path: pathlib.Path) -> None:
    """adcp_variables belongs to the adcp extension: no warning here, passed through as written."""
    adcp = {"ad2cp_inv_profile_vocn": {"colormap": "balance", "bogus": 1}}
    path = _write(tmp_path, GOOD + yaml.safe_dump({"adcp_variables": adcp}))
    cleaned, warnings, _ = SectionsModel.check_file(path)
    assert warnings == [] and cleaned is not None and cleaned["adcp_variables"] == adcp
    # ... and the extension checks its own entries with the same rules
    loaded = SectionsModel.YamlValidation.LoadedYaml(path, yaml.safe_load(path.read_text()), lambda loc: None)
    kept, warnings = SectionsModel.check_entries(loaded, "adcp_variables")
    assert kept == {"ad2cp_inv_profile_vocn": {"colormap": "balance"}} and "bogus" in warnings[0]


@pytest.mark.parametrize(
    ("entry", "message"),
    [
        ("{max 27.5: }", "temperature.max 27.5: Extra inputs are not permitted (input: None) - ignored - did you mean 'max: 27.5'?"),
        ("{step: 0}", "temperature.step: Input should be greater than or equal to 1"),
        ("{which: 7}", "temperature.which: Input should be less than or equal to 4"),
        ('{flip: "yes"}', "temperature.flip: Input should be a valid boolean"),
        ('{min: "low"}', "temperature.min: Input should be a valid number"),
        ("{colour: red}", "temperature.colour: Extra inputs are not permitted"),
    ],
)
def test_bad_value_warned_and_left_out(tmp_path: pathlib.Path, entry: str, message: str) -> None:
    """A bad key or value is a warning at its line and left out; the rest of the entry is kept."""
    path = _write(tmp_path, f"variables:\n  temperature: {entry}\n  salinity: {{units: psu}}\nsections:\n  \"000\": {{start: 1}}\n")
    cleaned, warnings, problems = SectionsModel.check_file(path)
    assert problems == [] and cleaned is not None
    assert cleaned["variables"]["temperature"] == {} and cleaned["variables"]["salinity"] == {"units": "psu"}
    assert len(warnings) == 1 and warnings[0].startswith(f"{path}:2: variables.") and message in warnings[0]


def test_other_warnings(tmp_path: pathlib.Path) -> None:
    path = _write(
        tmp_path,
        "variable:\n  x: {}\n"
        "defaults: {colormap: dense_r}\n"
        "variables:\n  temperature: {min: 30, max: 20}\n  salinity: just text\n"
        "sections:\n  001: {start: 1}\n  \"002\":\n",
    )
    cleaned, warnings, problems = SectionsModel.check_file(path)
    assert problems == [] and cleaned is not None
    text = "\n".join(warnings)
    assert f"{path}:1: variable: not a sections.yml key (defaults, variables, sections, adcp_variables) - ignored" in text
    assert f"{path}:3: defaults.colormap: 'dense_r' isn't one of the known colormaps" in text
    assert f"{path}:6: variables.salinity: should be a mapping of keys to values, not str - ignored" in text
    # (the line map holds the name as written, 001, so this lands on the sections: line)
    assert f"{path}:7: sections.1: the name should be quoted (\"1\") - yaml reads it as int 1" in text
    assert f"{path}:5: variables.temperature in section 1: min (30) is above max (20)" in text
    assert cleaned["defaults"] == {"colormap": "dense_r"}  # kept - drawn with thermal
    assert "salinity" not in cleaned["variables"] and cleaned["sections"]["002"] == {}


@pytest.mark.parametrize(
    ("text", "problem"),
    [
        ("variables: [x\n", None),
        ("- a\n", "sections.yml must be a mapping with variables and sections (got list)"),
        ("sections:\n  \"000\": {}\n", "no variables - nothing to plot"),
        ("variables:\n  t: {}\n", "no sections - nothing to plot"),
        ("variables: 3\nsections:\n  \"000\": {}\n", "no variables - nothing to plot"),
    ],
)
def test_unusable_file(tmp_path: pathlib.Path, text: str, problem: str | None) -> None:
    path = _write(tmp_path, text)
    cleaned, _, problems = SectionsModel.check_file(path)
    assert cleaned is None and len(problems) == 1 and problems[0].startswith(f"{path}")
    if problem:
        assert problem in problems[0]
    cleaned, _, problems = SectionsModel.check_file(tmp_path / "missing.yml")
    assert cleaned is None and "could not read" in problems[0]


def test_no_defaults_and_get_value(tmp_path: pathlib.Path) -> None:
    """No defaults key is fine (it raised a KeyError); the lookup goes section, variable, defaults, fallback."""
    path = _write(tmp_path, "variables:\n  t: {min: 2, units: C}\nsections:\n  \"000\": {min: 1}\n")
    cleaned, warnings, _ = SectionsModel.check_file(path)
    assert cleaned is not None and warnings == [] and cleaned["defaults"] == {}
    assert SectionsModel.get_value(cleaned, "min", "000", "t", 9) == 1
    assert SectionsModel.get_value(cleaned, "units", "000", "t", None) == "C"
    assert SectionsModel.get_value(cleaned, "bin", "000", "t", 5) == 5
    cleaned["defaults"] = {"bin": 10}
    assert SectionsModel.get_value(cleaned, "bin", "000", "t", 5) == 10
    assert SectionsModel.get_value({"adcp_variables": {"a": {"flip": True}}}, "flip", "x", "a", False, "adcp_variables")


def test_adding_a_key_is_one_line(monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path) -> None:
    """A new ENTRY_KEYS line is accepted at every level and in an extension's entries."""
    keys = {**SectionsModel.ENTRY_KEYS, "opacity": (Annotated[StrictInt, Field(ge=0, le=100)], "trace opacity")}
    model = create_model(
        "SectionValues", __config__=ConfigDict(extra="forbid"), **{k: (t | None, None) for k, (t, _) in keys.items()}
    )
    monkeypatch.setattr(SectionsModel, "SectionValues", model)
    path = _write(
        tmp_path,
        "defaults: {opacity: 50}\nvariables:\n  t: {opacity: 60}\nsections:\n  \"000\": {opacity: 70}\n"
        "adcp_variables:\n  a: {opacity: 80}\n",
    )
    cleaned, warnings, _ = SectionsModel.check_file(path)
    assert warnings == [] and cleaned is not None and SectionsModel.get_value(cleaned, "opacity", "000", "t", 0) == 70
    loaded = SectionsModel.YamlValidation.LoadedYaml(path, yaml.safe_load(path.read_text()), lambda loc: None)
    assert SectionsModel.check_entries(loaded, "adcp_variables") == ({"a": {"opacity": 80}}, [])


def test_sample_documents_every_key() -> None:
    """The sg000 sample's key list names every ENTRY_KEYS key."""
    documented = set(re.findall(r"^#\s+(\w+)\s+-", SAMPLE.read_text(), re.MULTILINE))
    assert set(SectionsModel.ENTRY_KEYS) <= documented


def test_cli(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    good = _write(tmp_path, GOOD)
    with caplog.at_level(logging.INFO):
        assert SectionsModel.main(["--verbose", "check", str(good)]) == 0
    assert f"{good}: OK - 2 variable(s), 1 section(s)" in caplog.text
    capsys.readouterr()
    assert SectionsModel.main(["dump", str(good)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["variables"]["sigma_t"] == {"colormap": "dense"}
    warned = _write(tmp_path, GOOD.replace("min: 3", "min 3"), "warned.yml")
    with caplog.at_level(logging.WARNING):
        assert SectionsModel.main(["check", str(warned)]) == 1
    assert "did you mean 'min: 3'?" in caplog.text
    assert SectionsModel.main(["check", str(_write(tmp_path, "- a\n", "bad.yml"))]) == 1


def test_mission_profiles_unusable_file_alert(tmp_path: pathlib.Path) -> None:
    from Plotting import MissionProfiles

    _write(tmp_path, "variables:\n  t: {}\n")
    assert MissionProfiles.mission_profiles(SimpleNamespace(mission_dir=tmp_path), []) == ([], [])
    (alert,) = BaseLog.log_alerts()["SECTIONS_CONFIG"]
    assert "no sections - nothing to plot - not plotting" in alert


def test_mission_profiles_draws_with_warnings(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """A bad key raises SECTIONS_CONFIG and is left out; the section plots are still drawn."""

    def typo(mission_dir: pathlib.Path) -> None:
        sections = mission_dir / "sections.yml"
        sections.write_text(sections.read_text().replace("min: 31.5, max: 34.5", "min: 31.5, max 34.5"))

    mission_dir = tmp_path / "mission_dir"
    testutils.run_mission(
        pathlib.Path("testdata/sg686_Shilshole_25Oct25_multidive"),
        mission_dir,
        Base.main,
        [
            "--verbose", "--mission_dir", str(mission_dir), "p6860001.nc", "--plot_types", "mission",
            "--mission_plots", "mission_profiles", "--make_mission_profile", "--no-notify_vis",
        ],  # fmt: skip
        caplog,
        [""],
        pre_test_hook=typo,
        required_msgs=["variables.salinity.max 34.5: Extra inputs are not permitted", "did you mean 'max: 34.5'?"],
    )
    assert list(mission_dir.joinpath("plots").glob("*salinity*.webp")), "the salinity section plot wasn't drawn"


def test_check_file_for_an_extension(tmp_path: pathlib.Path) -> None:
    """adcp: its own variables key is required/checked and its warnings alone returned; ADCP-only files work."""
    text = (
        "defaults: {colormap: dense_r}\n"
        "variables:\n  temperature: {bogus: 1}\n"
        "adcp_variables:\n  vocn: {colormap: balance, step: 0, min: 1, max: 0}\n"
        "sections:\n  \"000\": {start: 1}\n"
    )
    path = _write(tmp_path, text)
    cleaned, warnings, problems = SectionsModel.check_file(path, "adcp_variables", report_levels={"adcp_variables"})
    assert problems == [] and cleaned is not None
    assert cleaned["adcp_variables"] == {"vocn": {"colormap": "balance", "min": 1, "max": 0}}
    assert len(warnings) == 2 and all("adcp_variables.vocn" in w for w in warnings)
    assert any("step" in w for w in warnings) and any("min (1) is above max (0)" in w for w in warnings)
    # mission_profiles' view of the same file reports the shared and variables problems (and not adcp's)
    _, warnings, _ = SectionsModel.check_file(path)
    assert {w.split(": ")[1].split(".")[0] for w in warnings} == {"defaults", "variables"}
    # An ADCP-only file: fine for adcp, unusable for mission_profiles
    adcp_only = _write(tmp_path, "adcp_variables:\n  vocn: {}\nsections:\n  \"000\": {}\n", "adcp.yml")
    assert SectionsModel.check_file(adcp_only, "adcp_variables")[0] is not None
    assert "no variables - nothing to plot" in SectionsModel.check_file(adcp_only)[2][0]
    # No adcp_variables: unusable for adcp unless it's optional
    assert SectionsModel.check_file(path.with_name("x.yml"), "adcp_variables")[0] is None
    no_adcp = _write(tmp_path, GOOD, "no_adcp.yml")
    assert SectionsModel.check_file(no_adcp, "adcp_variables")[2] == [f"{no_adcp}: no adcp_variables - nothing to plot"]
    cleaned, _, problems = SectionsModel.check_file(no_adcp, "adcp_variables", require_variables=False)
    assert problems == [] and cleaned is not None and cleaned["adcp_variables"] == {}
