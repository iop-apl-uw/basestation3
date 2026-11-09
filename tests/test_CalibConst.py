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

"""CalibConst: declared-numeric constants that don't parse are reported and left unset."""

import logging
import subprocess
import sys
from pathlib import Path

import pytest

import Base  # noqa: F401 - normal import order (CalibConst on its own is a circular import)
import CalibConst
import MakeDiveProfiles
from BaseLog import BaseLogger, log_alerts


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLogger.reset()
    yield
    BaseLogger.reset()


def test_non_numeric_values(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    calib = tmp_path / "sg_calib_constants.m"
    calib.write_text(
        "id_str = '272';\n"
        "mission_title = 'Test mission';\n"  # a declared string - kept
        "mass = 73.956; % (kg)\n"
        "t_g = 4.40419474-03;\n"  # sg679 WHICEAS_test: missing 'e' - SyntaxError
        "c_i = foo;\n"  # NameError
        "my_own_thing = abc;\n"  # unknown variable - kept as a string, as before
    )
    with caplog.at_level(logging.ERROR):
        consts = CalibConst.getSGCalibrationConstants(calib, suppress_required_error=True)
    assert consts["mass"] == 73.956
    assert consts["mission_title"] == "Test mission"
    assert consts["my_own_thing"] == "abc"
    assert "t_g" not in consts and "c_i" not in consts
    assert f"{calib}:4: t_g = '4.40419474-03' is not a number (SyntaxError:" in caplog.text
    assert f"{calib}:5: c_i = 'foo' is not a number (" in caplog.text
    assert len(log_alerts()["CALIB_COMM_SYNTAX"]) == 2


def test_non_numeric_required_mass_is_left_out(tmp_path: Path) -> None:
    calib = tmp_path / "sg_calib_constants.m"
    calib.write_text("id_str = '272';\nmission_title = 'T';\nmass = 72.7 kg;\n")
    consts = CalibConst.getSGCalibrationConstants(calib, suppress_required_error=True)
    assert "mass" not in consts


@pytest.mark.parametrize(("mass", "ok"), [(73.9, True), (73, True), (None, False), ("72.7 kg", False), (0, False), (True, False)])
def test_calib_mass_ok(caplog: pytest.LogCaptureFixture, mass: object, ok: bool) -> None:
    with caplog.at_level(logging.ERROR):
        assert MakeDiveProfiles.calib_mass_ok({"mass": mass}, "dive 2") is ok
    assert ("can't process dive 2" in caplog.text) is not ok


@pytest.mark.parametrize(("calib_text", "exit_code"), [("id_str = '272';\nmission_title = 'T';\nmass = 73.9;\n", 0), (None, 1)], ids=["calib file", "no calib file"])
def test_script_exit_status(tmp_path: Path, calib_text: str | None, exit_code: int) -> None:
    """Run as a script, CalibConst exits with main's status (it always exited 1)."""
    if calib_text is not None:
        (tmp_path / "sg_calib_constants.m").write_text(calib_text)
    ret = subprocess.run(
        [sys.executable, "CalibConst.py", "--mission_dir", str(tmp_path)], capture_output=True, text=True, check=False
    )
    assert ret.returncode == exit_code, ret.stdout + ret.stderr


def test_missing_required_keys_left_out_and_reported(tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
    """A required key the file doesn't define is absent (not None), so `not in` checks see it - and it's logged."""
    calib = tmp_path / "sg_calib_constants.m"
    calib.write_text("id_str = '272';\n")
    with caplog.at_level(logging.ERROR):
        consts = CalibConst.getSGCalibrationConstants(calib)
    assert "id_str" in consts
    assert "mass" not in consts and "mission_title" not in consts
    assert "missing from" in caplog.text and "'mission_title', 'mass'" in caplog.text
