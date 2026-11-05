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

"""Sensors with one column of a set missing: logged and skipped (each used to raise TypeError)."""

import collections
import importlib
import logging
import pathlib
import sys
from unittest.mock import MagicMock

import numpy as np
import pytest

import Base  # noqa: F401 - normal import order
import BaseNetCDF

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))


def _datafile(present: list[str]) -> MagicMock:
    """A data file with only some columns.

    Args:
        present: The columns it has.

    Returns:
        The fake data file.
    """
    datafile = MagicMock()
    datafile.version = 67.0
    datafile.eng_cols = []
    datafile.eng_dict = {}
    columns = {c: np.array([1000.0, 2000.0]) for c in present}
    datafile.remove_col.side_effect = lambda label: columns.pop(label, None)
    datafile.remove_col_regex.return_value = None
    return datafile


@pytest.mark.parametrize(
    ("module", "present"),
    [
        ("aa3830_ext", ["aa3830.O2", "aa3830.temp"]),
        ("aa3830_ext", ["aa3830.O2", "aa3830.dphase"]),
        ("aa4330_ext", ["aa4330.O2", "aa4330.AirSat", "aa4330.Temp", "aa4330.CalPhase"]),
        ("aa4330_ext", ["aa4831.O2", "aa4831.AirSat", "aa4831.Temp", "aa4831.TCPhase"]),
        ("sailct_ext", ["sailct.CondFreq"]),
        ("sbect_ext", ["sbect.CondFreq"]),
        ("sbect_ext", ["scct.condFreq"]),
    ],
)
def test_asc2eng_incomplete_set(module: str, present: list[str], caplog: pytest.LogCaptureFixture) -> None:
    datafile = _datafile(present)
    with caplog.at_level(logging.ERROR):
        assert importlib.import_module(module).asc2eng(None, module, datafile) == -1
    assert "not converting" in caplog.text
    assert datafile.eng_dict == {}


@pytest.mark.parametrize(
    ("module", "present", "message"),
    [
        ("aa3830_ext", "O2", "aa3830 O2 column without dphase"),
        ("aa4330_ext", "aa4330_O2", "column without"),
    ],
)
def test_sensor_data_processing_eng_without_phase(
    module: str, present: str, message: str, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(BaseNetCDF, "fetch_instrument_metadata", lambda _: {})
    eng_f = MagicMock()
    eng_f.find_col.side_effect = lambda cols: (present, np.ones(2)) if present in cols else (None, None)
    l_dict = collections.defaultdict(lambda: None, results_d={})
    sensor = importlib.import_module(module)
    if module == "aa4330_ext":
        # Filled by init_sensor: data_info, time var, eng O2 and TCPhase, then scicon and results names
        vars_ = ["info", "time", "aa4330_O2", "aa4330_TCPhase", *["unused"] * 10]
        monkeypatch.setattr(sensor, "canonical_data_to_results_d", {"aa4330": vars_})
    with caplog.at_level(logging.ERROR):
        assert sensor.sensor_data_processing(None, module, l_dict, eng_f, {}) == -1
    assert message in caplog.text
