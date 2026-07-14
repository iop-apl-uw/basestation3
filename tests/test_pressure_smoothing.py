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

"""Tests for optional truck-pressure smoothing and gold-standard slope auto-correction."""

import pathlib

import netCDF4
import numpy as np
import pytest
import testutils

import Globals
import MakeDiveProfiles
import Utils

DATA_DIR = pathlib.Path("testdata/sg180_Shilshole_01Jul26_pressure_smoothing")
DIVE_NUM = "5"
DIVE_NC_NAME = "p1800005.nc"


def _append_calib_const(mission_dir: pathlib.Path, line: str) -> None:
    """Appends a line to the mission's sg_calib_constants.m file.

    Args:
        mission_dir: mission directory containing sg_calib_constants.m.
        line: line to append (e.g. "smooth_truck_pressure = 1;").
    """
    with open(mission_dir / "sg_calib_constants.m", "a") as f:
        f.write("\n" + line + "\n")


# --- Mission-level integration tests (reprocess-from-netCDF) ---


@pytest.fixture(autouse=True)
def _skip_adcp_postnetcdf_extension(monkeypatch):
    """Skips the unrelated adcp/BaseADCP.py postnetcdf extension for these tests.

    That extension is a separate, in-development ADCP inversion subsystem (its own
    venv, own config) with a pre-existing fragility around GPS/CTD time alignment
    that is unrelated to pressure smoothing/slope-correction - it's out of scope here.
    """
    monkeypatch.setitem(
        Globals.extensions_to_skip,
        "adcp/BaseADCP.py",
        "skipped for pressure-smoothing tests (unrelated ADCP inversion subsystem)",
    )


def test_reprocess_default_unchanged(caplog):
    """With neither new flag set, no pressure_raw is added (regression guard)."""
    mission_dir = DATA_DIR / "mission_dir"
    testutils.run_mission(
        DATA_DIR,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} {DIVE_NUM}".split(),
        caplog,
        [""],
        required_msgs=["Loading data from netCDF files"],
    )
    with netCDF4.Dataset(mission_dir / DIVE_NC_NAME) as ds:
        assert "pressure_raw" not in ds.variables


def test_reprocess_smoothing_enabled(caplog):
    """With smooth_truck_pressure=1, pressure_raw is added and pressure is smoother."""
    mission_dir = DATA_DIR / "mission_dir"

    def enable_smoothing(mission_dir: pathlib.Path) -> None:
        _append_calib_const(mission_dir, "smooth_truck_pressure = 1;")

    testutils.run_mission(
        DATA_DIR,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} {DIVE_NUM}".split(),
        caplog,
        [""],
        required_msgs=["Loading data from netCDF files"],
        pre_test_hook=enable_smoothing,
    )
    with netCDF4.Dataset(mission_dir / DIVE_NC_NAME) as ds:
        assert "pressure_raw" in ds.variables
        press_raw = ds.variables["pressure_raw"][:]
        press = ds.variables["pressure"][:]
        assert not np.array_equal(press, press_raw)
        # Smoothed signal is less noisy sample-to-sample, but still tracks the raw signal
        assert np.std(np.diff(press)) < np.std(np.diff(press_raw))
        assert np.max(np.abs(press - press_raw)) < 5.0  # dbar


def test_reprocess_gold_standard_slope_correction(caplog):
    """With depth_slope_correction_gold_standard set, pressure tracks ad2cp_pressure better."""
    mission_dir = DATA_DIR / "mission_dir"

    def enable_gold_standard(mission_dir: pathlib.Path) -> None:
        _append_calib_const(
            mission_dir, "depth_slope_correction_gold_standard = 'ad2cp_pressure';"
        )

    testutils.run_mission(
        DATA_DIR,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} {DIVE_NUM}".split(),
        caplog,
        [""],
        required_msgs=["Loading data from netCDF files"],
        pre_test_hook=enable_gold_standard,
    )
    with netCDF4.Dataset(mission_dir / DIVE_NC_NAME) as ds:
        assert "pressure_raw" in ds.variables
        press_raw = np.ma.filled(ds.variables["pressure_raw"][:], np.nan)
        press = np.ma.filled(ds.variables["pressure"][:], np.nan)
        time = np.ma.filled(ds.variables["time"][:], np.nan)
        ad2cp_time = np.ma.filled(ds.variables["ad2cp_time"][:], np.nan)
        ad2cp_press = np.ma.filled(ds.variables["ad2cp_pressure"][:], np.nan)

        press_interp = Utils.interp1d(time, press, ad2cp_time, kind="linear")
        press_raw_interp = Utils.interp1d(time, press_raw, ad2cp_time, kind="linear")

        rms_corrected = np.sqrt(np.mean((press_interp - ad2cp_press) ** 2))
        rms_raw = np.sqrt(np.mean((press_raw_interp - ad2cp_press) ** 2))
        assert rms_corrected <= rms_raw


# --- Direct unit tests: Utils.smooth_pressure ---


def _synthetic_press(
    n: int = 300, dt: float = 2.0, seed: int = 0
) -> tuple[np.ndarray, np.ndarray]:
    """Builds a synthetic noisy pressure time series for direct unit tests."""
    t = np.arange(0, n * dt, dt)
    rng = np.random.RandomState(seed)
    press = 50 - 0.0005 * (t - t[len(t) // 2]) ** 2 + rng.normal(0, 0.2, t.shape)
    return t, press


def test_smooth_pressure_basic():
    t, press = _synthetic_press()
    smoothed = Utils.smooth_pressure(t, press, window_secs=42.0, polyorder=3)
    assert smoothed.shape == press.shape
    assert not np.array_equal(smoothed, press)
    assert np.std(np.diff(smoothed)) < np.std(np.diff(press))


def test_smooth_pressure_too_short(caplog):
    t = np.array([0.0, 2.0])
    press = np.array([1.0, 2.0])
    result = Utils.smooth_pressure(t, press)
    assert np.array_equal(result, press)
    assert any(
        "returning unsmoothed" in record.getMessage() for record in caplog.records
    )


def test_smooth_pressure_nan(caplog):
    t, press = _synthetic_press(n=20)
    press[3] = np.nan
    result = Utils.smooth_pressure(t, press)
    assert np.array_equal(result, press, equal_nan=True)
    assert any(
        "returning unsmoothed" in record.getMessage() for record in caplog.records
    )


def test_smooth_pressure_non_positive_interval(caplog):
    t = np.zeros(5)
    press = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = Utils.smooth_pressure(t, press)
    assert np.array_equal(result, press)
    assert any(
        "non-positive median sample interval" in record.getMessage()
        for record in caplog.records
    )


def test_smooth_pressure_window_larger_than_profile(caplog):
    t = np.arange(0, 10, 2.0)
    press = np.array([1.0, 2.0, 3.0, 4.0, 5.0])
    result = Utils.smooth_pressure(t, press, window_secs=100.0)
    assert np.array_equal(result, press)
    assert any(
        "returning unsmoothed" in record.getMessage() for record in caplog.records
    )


# --- Direct unit tests: Utils.fit_pressure_slope ---


def test_fit_pressure_slope_recovers_known_slope():
    t = np.arange(0, 600, 2.0)
    press = 10 + 0.01 * t
    ref_press = press * 1.15
    slope = Utils.fit_pressure_slope(t, press, t, ref_press)
    assert slope is not None
    assert abs(slope - 1.15) < 0.01


def test_fit_pressure_slope_no_overlap(caplog):
    t = np.arange(0, 600, 2.0)
    press = np.ones_like(t)
    slope = Utils.fit_pressure_slope(t, press, t + 100000, press)
    assert slope is None
    assert any(
        "insufficient time overlap" in record.getMessage() for record in caplog.records
    )


def test_fit_pressure_slope_too_few_samples(caplog):
    slope = Utils.fit_pressure_slope(
        np.array([0.0]), np.array([1.0]), np.arange(0, 10, 2.0), np.ones(5)
    )
    assert slope is None
    assert any(
        "insufficient samples" in record.getMessage() for record in caplog.records
    )


def test_fit_pressure_slope_insufficient_valid_samples(caplog):
    t = np.arange(0, 20, 2.0)
    press = np.arange(len(t), dtype=float)
    ref_press = np.full(len(t), np.nan)
    ref_press[0] = 5.0  # a single valid reference sample - still not enough to fit
    slope = Utils.fit_pressure_slope(t, press, t, ref_press)
    assert slope is None
    assert any(
        "insufficient valid overlapping samples" in record.getMessage()
        for record in caplog.records
    )


# --- Direct unit tests: MakeDiveProfiles.process_truck_pressure ---


def _base_calib_consts() -> dict:
    return {
        "smooth_truck_pressure": 0,
        "smooth_truck_pressure_window_secs": 42.0,
        "smooth_truck_pressure_polyorder": 3,
        "depth_slope_correction_gold_standard": "",
        "depth_slope_correction": MakeDiveProfiles.DEPTH_SLOPE_CORRECTION_DEFAULT,
    }


def test_process_truck_pressure_neither_enabled():
    t, press = _synthetic_press()
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        _base_calib_consts(), t, press, {}
    )
    assert np.array_equal(out_press, press)
    assert raw is None


def test_process_truck_pressure_smoothing_only():
    t, press = _synthetic_press()
    calib_consts = _base_calib_consts()
    calib_consts["smooth_truck_pressure"] = 1
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        calib_consts, t, press, {}
    )
    assert raw is not None
    assert np.array_equal(raw, press)
    assert not np.array_equal(out_press, press)


def test_process_truck_pressure_gold_standard_only():
    t, press = _synthetic_press()
    ref_press = press * 1.2
    calib_consts = _base_calib_consts()
    calib_consts["depth_slope_correction_gold_standard"] = "ad2cp_pressure"
    results_d = {"ad2cp_pressure": ref_press, "ad2cp_time": t}
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        calib_consts, t, press, results_d
    )
    assert raw is not None
    np.testing.assert_allclose(out_press, press * 1.2, rtol=0.05)


def test_process_truck_pressure_both_enabled():
    t, press = _synthetic_press()
    ref_press = press * 1.2
    calib_consts = _base_calib_consts()
    calib_consts["smooth_truck_pressure"] = 1
    calib_consts["depth_slope_correction_gold_standard"] = "ad2cp_pressure"
    results_d = {"ad2cp_pressure": ref_press, "ad2cp_time": t}
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        calib_consts, t, press, results_d
    )
    assert raw is not None
    assert not np.array_equal(out_press, press)


def test_process_truck_pressure_missing_reference(caplog):
    t, press = _synthetic_press()
    calib_consts = _base_calib_consts()
    calib_consts["depth_slope_correction_gold_standard"] = "ad2cp_pressure"
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        calib_consts, t, press, {}
    )
    assert raw is None
    assert np.array_equal(out_press, press)
    assert any("not found" in record.getMessage() for record in caplog.records)


def test_process_truck_pressure_explicit_depth_slope_correction_wins():
    """A depth_slope_correction that differs from the default suppresses auto-correction."""
    t, press = _synthetic_press()
    ref_press = press * 1.2
    calib_consts = _base_calib_consts()
    calib_consts["depth_slope_correction_gold_standard"] = "ad2cp_pressure"
    calib_consts["depth_slope_correction"] = 1.05
    results_d = {"ad2cp_pressure": ref_press, "ad2cp_time": t}
    out_press, raw = MakeDiveProfiles.process_truck_pressure(
        calib_consts, t, press, results_d
    )
    assert raw is None
    assert np.array_equal(out_press, press)


if __name__ == "__main__":
    pytest.main([__file__])
