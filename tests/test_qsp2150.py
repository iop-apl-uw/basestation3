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

"""Tests for the Biospherical QSP2150 support: Sensors/qsp2150_ext.py (mode-aware
metadata and in-water PAR), Plotting/DiveQSP2150.py and tools/GetQSPConstants.py.

The fixture is sg615 Shilshole 03-Nov-26 dive 4, flown in mode D (raw volts), with
the SN 50141 cal sheet entries in sg_calib_constants.m. The two captures are sg615's
selftest with a sensor menu added after "fetching metadata for QSP2150": the
manufacturer's example (mode B), and a mode C unit with capture-line prefixes.
"""

import pathlib
import re
import sys
from unittest.mock import MagicMock

import brotli
import netCDF4
import numpy as np
import pytest
import testutils

import Base
import tools.GetQSPConstants

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import qsp2150_ext  # noqa: E402  # ty: ignore[unresolved-import]

DATA_DIR = pathlib.Path("testdata/sg615_Shilshole_03Nov26_qsp")
FULL = {"qsp_mode": "D", "qsp_cal_factor": 9.86e-4, "qsp_immersion": 0.5664, "qsp_dark": 0.0099}
ALLOWED = [
    "Optode data found but foil calibration constant",
    "timeout(s) seen",
    "ALERT:TIMEOUT",
    "Did not find corrected optode O2",
    "Missing metadata for log entry $MAMPSTAT",
    "Displacements under-estimate likely positions",
    "Substantial unmodeled flight time",
    "Large mis-match between predicted and observed w",
    "Can't find the climb pump",
]


# ----- the extension, unit level -----


@pytest.mark.parametrize(
    ("consts", "expected"),
    (
        ({"qsp_mode": "A", "qsp_cal_factor": 0.001, "qsp_immersion": 0.5}, [2.0, 4.0]),
        ({"qsp_mode": "B", "qsp_immersion": 0.5}, [2.0, 4.0]),
        ({"qsp_mode": "C"}, [1.0, 2.0]),
        ({"qsp_mode": "D", "qsp_cal_factor": 0.001, "qsp_immersion": 0.5, "qsp_dark": 0.5}, [1000.0, 3000.0]),
    ),
)
def test_calibrated_par(consts: dict, expected: list[float]) -> None:
    raw = np.array([0.001, 0.002]) if consts["qsp_mode"] == "A" else np.array([1.0, 2.0])
    mode = qsp2150_ext.calib_mode(consts)
    assert np.allclose(qsp2150_ext.calibrated_par(raw, mode, consts), expected)


@pytest.mark.parametrize(("consts", "missing"), (({"qsp_mode": "D"}, "qsp_cal_factor"), ({"qsp_mode": "B"}, "qsp_immersion")))
def test_calibrated_par_missing_constant(consts: dict, missing: str, caplog: pytest.LogCaptureFixture) -> None:
    assert qsp2150_ext.calibrated_par(np.ones(2), consts["qsp_mode"], consts) is None
    assert missing in caplog.text


def test_calibrated_par_no_mode() -> None:
    assert qsp2150_ext.calibrated_par(np.ones(2), None, {}) is None


@pytest.mark.parametrize(
    ("consts", "mode", "units"),
    (
        ({}, None, "unknown"),
        ({"qsp_mode": "d"}, "D", "V"),
        ({"qsp_mode": "A"}, "A", "V"),
        ({"qsp_mode": "B"}, "B", "uE/m^2/sec"),
        ({"qsp_mode": "C", "qsp_units": "uE/cm2/sec"}, "C", "uE/cm2/sec"),
        ({"qsp_mode": "E"}, None, "unknown"),
    ),
)
def test_mode_and_units(consts: dict, mode: str | None, units: str) -> None:
    assert qsp2150_ext.calib_mode(consts) == mode
    got_units, description = qsp2150_ext.raw_metadata(mode, consts)
    assert got_units == units
    assert ("not known" in description) if mode is None else (f"mode {mode}" in description)


def test_asc2eng_scales_and_takes_the_column() -> None:
    datafile = MagicMock()
    datafile.remove_col.return_value = np.array([1622591.0, 9876.0])
    datafile.eng_cols = []
    datafile.eng_dict = {}
    assert qsp2150_ext.asc2eng(None, "qsp2150_ext", datafile) == 0
    datafile.remove_col.assert_called_once_with("qsp.PARuV")
    assert np.allclose(datafile.eng_dict["qsp.PARuV"], [1.622591, 0.009876])
    datafile.remove_col.return_value = None
    assert qsp2150_ext.asc2eng(None, "qsp2150_ext", datafile) == 1
    assert qsp2150_ext.asc2eng(None, "qsp2150_ext", None) == -1


def test_eng_decimal_pts() -> None:
    pts: dict[str, int] = {}
    assert qsp2150_ext.eng_decimal_pts(None, "qsp2150_ext", ["depth", "qsp.PARuV"], pts) == 0
    assert pts == {"qsp.PARuV": 6}
    assert qsp2150_ext.eng_decimal_pts(None, "qsp2150_ext", ["depth"], {}) == 1
    assert qsp2150_ext.eng_decimal_pts(None, "qsp2150_ext", None, {}) == -1


def test_sensor_data_processing_version_mismatch() -> None:
    assert qsp2150_ext.sensor_data_processing(None, "qsp2150_ext", None, None, None) == -1


# ----- the pipeline: the three cases of sg_calib_constants -----


def _div_text(path: pathlib.Path) -> str:
    """Reads a plot's .div (brotli-compressed when --compress_div is on, the default)."""
    data = path.read_bytes()
    try:
        text = brotli.decompress(data).decode()
    except brotli.error:
        text = data.decode()
    return text.replace("\\u002f", "/")  # plotly's JSON escapes "/"


def _calib_hook(keep: tuple[str, ...]):
    """Leaves only the qsp_* entries in keep (calibcomm_qsp goes too unless kept)."""

    def hook(mission_dir: pathlib.Path) -> None:
        calib = mission_dir / "sg_calib_constants.m"
        lines = []
        for line in calib.read_text().splitlines():
            m = re.match(r"\s*(qsp_\w+|calibcomm_qsp)\s*=", line)
            if m and m.group(1) not in keep:
                continue
            lines.append(line)
        calib.write_text("\n".join(lines) + "\n")

    return hook


def _run(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, keep: tuple[str, ...] | None) -> pathlib.Path:
    mission_dir = tmp_path / "mission_dir"
    testutils.run_mission(
        DATA_DIR,
        mission_dir,
        Base.main,
        f"--verbose --local --no-notify_vis --skip_flight_model --plot_types dives --dive_plots plot_qsp2150 --mission_dir {mission_dir}".split(),
        caplog,
        [*ALLOWED, "QSP2150 plot: units unknown", "QSP2150 calibration mode D needs"],
        pre_test_hook=None if keep is None else _calib_hook(keep),
    )
    return mission_dir


def test_pipeline_calibrated(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Case 3: mode D and its constants - qsp_PAR from the column, labelled V, 6 decimals in .eng."""
    mission_dir = _run(tmp_path, caplog, None)

    eng = (mission_dir / "p6150004.eng").read_text().splitlines()
    cols = next(line for line in eng if line.startswith("%columns:")).removeprefix("%columns:").strip().split(",")
    first = next(line for line in eng if not line.startswith("%")).split()
    assert re.fullmatch(r"\d+\.\d{6}", first[cols.index("qsp.PARuV")])

    with netCDF4.Dataset(mission_dir / "p6150004.nc") as ds:
        raw = ds.variables["eng_qsp_PARuV"]
        assert raw.units == "V"
        assert "mode D" in raw.comment
        par = ds.variables["qsp_PAR"]
        assert par.units == "uE/m^2/sec"
        expected = (raw[:] - FULL["qsp_dark"]) / (FULL["qsp_cal_factor"] * FULL["qsp_immersion"])
        assert np.allclose(par[:], expected, equal_nan=True)
        assert "SN 50141" in ds.variables["sg_cal_calibcomm_qsp"][:].tobytes().decode()

    div = _div_text(mission_dir / "plots" / "dv0004_qsp2150.div")
    assert "Log Scale" in div and "Linear Scale" in div
    assert "PAR (uE/m^2/sec, in water)" in div
    assert "As recorded (V)" in div


def test_pipeline_mode_only(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Case 2: only qsp_mode = D - the column labelled V, no qsp_PAR, the plot on the column."""
    mission_dir = _run(tmp_path, caplog, ("qsp_mode",))
    with netCDF4.Dataset(mission_dir / "p6150004.nc") as ds:
        assert ds.variables["eng_qsp_PARuV"].units == "V"
        assert "qsp_PAR" not in ds.variables
    assert "qsp_cal_factor" in caplog.text  # the warning names what mode D still needs
    div = _div_text(mission_dir / "plots" / "dv0004_qsp2150.div")
    assert "QSP2150 output as recorded (V)" in div


def test_pipeline_no_entries(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Case 1: no qsp entries - still a plot, with the units marked unknown."""
    mission_dir = _run(tmp_path, caplog, ())
    with netCDF4.Dataset(mission_dir / "p6150004.nc") as ds:
        assert ds.variables["eng_qsp_PARuV"].units == "unknown"
        assert "qsp_PAR" not in ds.variables
    div = _div_text(mission_dir / "plots" / "dv0004_qsp2150.div")
    assert "units unknown - set qsp_mode" in div


# ----- tools/GetQSPConstants.py -----


@pytest.mark.parametrize(
    ("capture", "required"),
    (
        (
            "pt6150003_qsp_mode_b.cap",
            [
                "calibcomm_qsp = 'Biospherical QSR2150A SN 50279, mode B (in air), cal 0.000674 V/(uE/m2/sec)';",
                "qsp_mode = 'B';",
                "qsp_cal_factor = 0.000674;",
                "qsp_immersion = 1.000000;",
                "qsp_dark = 0.010538;",
                "qsp_units = 'uE/m2/sec';",
                "Mode B with immersion factor 1.0",
            ],
        ),
        (
            "pt6150003_qsp_mode_c_prefixed.cap",
            [
                "calibcomm_qsp = 'Biospherical QSP2150 SN 50225, mode C (in water), cal 0.001034 V/(uE/m2/sec)';",
                "qsp_mode = 'C';",
                "qsp_immersion = 0.566400;",
            ],
        ),
    ),
)
def test_get_qsp_constants(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str], capture: str, required: list[str]
) -> None:
    mission_dir = tmp_path / "mission_dir"
    testutils.run_mission(
        DATA_DIR,
        mission_dir,
        tools.GetQSPConstants.main,
        ["--verbose", str(mission_dir / capture)],
        caplog,
        [""],
        required_msgs=required,
        capsys=capsys,
    )


def test_get_qsp_constants_section_ends_at_next_module() -> None:
    lines = [
        "246.090,HQSP2150,N,fetching metadata for QSP2150",
        "Calibration Mode = D",
        "246.111,HTRIDENTE,N,fetching metadata for tridente",
        "Calibration Mode = A",
    ]
    assert tools.GetQSPConstants.parse_settings(tools.GetQSPConstants.qsp_section(lines)) == {"mode": "D"}


def test_get_qsp_constants_no_metadata(tmp_path: pathlib.Path) -> None:
    capture = tmp_path / "pt0001.cap"
    capture.write_text("246.090,HQSP2150,N,fetching metadata for QSP2150\n246.111,SUSR,N,next\n")
    assert tools.GetQSPConstants.main(["--verbose", str(capture)]) == 1
