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

"""Whole-mission config checker: entries warned about at file:line and left out, Utils.whole_mission_cfg, the CLI."""

import logging
import shutil
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml

import Base  # noqa: F401 - normal import order
import BaseLog
import BaseNetCDF
import Sensors
import Utils
import WholeMissionModel

KNOWN = {"temperature", "salinity", "depth_avg_curr_east_gsm"}
FIXTURE = Path("testdata/sg236_NANOOS_May23")


@pytest.fixture(autouse=True)
def _fresh_state() -> Iterator[None]:
    """Fresh logger and module state (the CLI calls Sensors.init_extensions, which runs once per process)."""
    BaseLog.BaseLogger.reset()
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    yield
    BaseLog.BaseLogger.reset()
    Sensors.set_globals()
    BaseNetCDF.set_globals()


def _write(tmp_path: Path, text: str, name: str = "whole_mission.yml") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_clean_file(tmp_path: Path) -> None:
    path = _write(
        tmp_path,
        "timeseries:\n  temperature: f\n  salinity: False\nprofile:\n  depth_avg_curr_east_gsm: True\n",
    )
    settings, warnings, problems = WholeMissionModel.check_file(path, KNOWN)
    assert (warnings, problems) == ([], [])
    assert settings == {
        "profile": {"depth_avg_curr_east_gsm": True},
        "timeseries": {"temperature": "f", "salinity": False},
    }


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        (
            "timeserie:\n  temperature: f\n",
            1,
            "timeserie: not a section (profile, timeseries) - ignored",
        ),
        (
            "profile:\n",
            1,
            "profile: should be a mapping of variable: setting, not NoneType - ignored",
        ),
        (
            "profile: [temperature]\n",
            1,
            "profile: should be a mapping of variable: setting, not list - ignored",
        ),
        (
            "profile:\n  tempurature: f\n",
            2,
            "profile.tempurature: not a known variable - skipped",
        ),
        (
            "profile:\n  1: f\n",
            2,
            "profile.1: a variable name should be text, not int - skipped",
        ),
        (
            "profile:\n  temperature: x\n",
            2,
            "profile.temperature: 'x' should be True, False or a netCDF type",
        ),
        (
            "profile:\n  temperature: c\n",
            2,
            "profile.temperature: 'c' should be True, False or a netCDF type",
        ),
        (
            "profile:\n  temperature: 1\n",
            2,
            "profile.temperature: 1 should be True, False or a netCDF type",
        ),
    ],
    ids=[
        "unknown_section",
        "empty_section",
        "list_section",
        "unknown_var",
        "int_name",
        "bad_type",
        "char_type",
        "int",
    ],
)
def test_warnings(tmp_path: Path, text: str, line: int, message: str) -> None:
    """Each problem is a warning at file:line, and the entry (or section) is left out."""
    path = _write(tmp_path, text)
    settings, warnings, problems = WholeMissionModel.check_file(path, KNOWN)
    assert problems == [] and settings == {"profile": {}, "timeseries": {}}
    assert len(warnings) == 1 and warnings[0].startswith(f"{path}:{line}: {message}"), (
        warnings
    )


def test_bad_entry_leaves_the_rest(tmp_path: Path) -> None:
    path = _write(tmp_path, "timeseries:\n  temperature: x\n  salinity: d\n")
    settings, warnings, _ = WholeMissionModel.check_file(path, KNOWN)
    assert (
        settings is not None
        and settings["timeseries"] == {"salinity": "d"}
        and len(warnings) == 1
    )


def test_unusable(tmp_path: Path) -> None:
    empty = _write(tmp_path, "")
    assert WholeMissionModel.check_file(empty, KNOWN) == (
        {"profile": {}, "timeseries": {}},
        [f"{empty}: empty - no whole-mission changes"],
        [],
    )
    listed = _write(tmp_path, "- temperature\n", "list.yml")
    assert WholeMissionModel.check_file(listed, KNOWN)[0] is None
    syntax = _write(tmp_path, "profile:\n  temperature: [f\n", "syntax.yml")
    assert WholeMissionModel.check_file(syntax, KNOWN)[2][0].startswith(f"{syntax}:")
    assert (
        "could not read"
        in WholeMissionModel.check_file(tmp_path / "missing.yml", KNOWN)[2][0]
    )


def test_utils_whole_mission_cfg(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Utils.whole_mission_cfg logs the checker's messages and never raises (an empty file used to)."""
    known = dict.fromkeys(KNOWN)
    path = _write(
        tmp_path,
        "timeseries:\n  temperature: f\n  bogus: d\nprofile:\n  salinity: True\n",
    )
    with caplog.at_level(logging.WARNING):
        assert Utils.whole_mission_cfg(path, known) == (
            {"salinity": True},
            {"temperature": "f"},
        )
    assert "timeseries.bogus: not a known variable - skipped" in caplog.text
    assert Utils.whole_mission_cfg(_write(tmp_path, "", "empty.yml"), known) == ({}, {})
    with caplog.at_level(logging.ERROR):
        assert Utils.whole_mission_cfg(
            _write(tmp_path, "- x\n", "list.yml"), known
        ) == ({}, {})
    assert "must be a mapping" in caplog.text and "ignoring contents" in caplog.text
    assert Utils.whole_mission_cfg(None, known) == ({}, {})  # ty: ignore[invalid-argument-type]


def test_utils_alerts_once(tmp_path: Path) -> None:
    """Each message is a WHOLE_MISSION_CONFIG alert, once, though the file is read once per product."""
    known = dict.fromkeys(KNOWN)
    path = _write(tmp_path, "timeseries:\n  bogus: d\n")
    listed = _write(tmp_path, "- x\n", "list.yml")
    for _ in range(3):
        Utils.whole_mission_cfg(path, known)
        Utils.whole_mission_cfg(listed, known)
    alerts = BaseLog.log_alerts()[WholeMissionModel.ALERT]
    assert len(alerts) == 2, alerts
    assert alerts[0].startswith("WARNING: ") and "timeseries.bogus" in alerts[0]
    assert alerts[1].startswith("ERROR: ") and alerts[1].endswith("- ignoring contents")
    Utils.whole_mission_cfg(
        _write(tmp_path, "profile:\n  temperature: f\n", "ok.yml"), known
    )
    assert len(BaseLog.log_alerts()[WholeMissionModel.ALERT]) == 2


def _mission(tmp_path: Path) -> Path:
    """A mission directory with sg236's .extensions (CTDAdjustment adds temperature_adjusted etc.)."""
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    shutil.copy2(FIXTURE / ".extensions", mission_dir / ".extensions")
    return mission_dir


def test_cli(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    """Variables from the sensor and the mission's own extensions are known; check and dump."""
    mission_dir = _mission(tmp_path)
    config = shutil.copy2(
        FIXTURE / "sg236_whole_mission.yml", tmp_path / "whole_mission.yml"
    )
    with caplog.at_level(logging.INFO):
        assert (
            WholeMissionModel.main(
                ["--verbose", "check", str(config), "--mission_dir", str(mission_dir)]
            )
            == 0
        )
    assert f"{config}: OK" in caplog.text
    BaseLog.BaseLogger.reset()
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    capsys.readouterr()
    assert (
        WholeMissionModel.main(["dump", str(config), "--mission_dir", str(mission_dir)])
        == 0
    )
    assert yaml.safe_load(capsys.readouterr().out) == {
        "profile": {},
        "timeseries": {"temperature_adjusted": "f", "salinity_adjusted": "f"},
    }


def test_cli_problems(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    mission_dir = _mission(tmp_path)
    bad = _write(tmp_path, "timeseries:\n  temperature_adjustd: f\n")
    with caplog.at_level(logging.WARNING):
        assert (
            WholeMissionModel.main(
                ["check", str(bad), "--mission_dir", str(mission_dir)]
            )
            == 1
        )
    assert "timeseries.temperature_adjustd: not a known variable" in caplog.text
    for action in ("check", "dump"):
        BaseLog.BaseLogger.reset()
        Sensors.set_globals()
        BaseNetCDF.set_globals()
        listed = _write(tmp_path, "- x\n", "list.yml")
        assert (
            WholeMissionModel.main(
                [action, str(listed), "--mission_dir", str(mission_dir)]
            )
            == 1
        )


def test_cli_sensor_init_fails(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(Sensors, "init_extensions", lambda _base_opts: (None, 1))
    config = _write(tmp_path, "profile: {}\n")
    with caplog.at_level(logging.ERROR):
        assert (
            WholeMissionModel.main(
                ["check", str(config), "--mission_dir", str(_mission(tmp_path))]
            )
            == 1
        )
    assert "Sensor initialization failed" in caplog.text
