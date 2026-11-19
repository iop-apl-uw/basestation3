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

import logging
import pathlib
import shutil
import time
import types

import netCDF4
import numpy as np
import pytest
import testutils

import Base
import BaseLog
import BaseNetCDF
import FlightModel
import MakeDiveProfiles
import Sensors

test_cases = (
    ("", ["Files up-to-date for dive:2; nothing to do"], [""]),
    (
        "p2720002.nc",
        ["Could not parse p2720002.nc (invalid literal for int() with base 10"],
        [""],
    ),
    ("--force", ["Dives processed = [2]", "Loading data from original files"], [""]),
    ("2", ["Loading data from netCDF files"], [""]),
)


@pytest.mark.parametrize(
    "additional_options,required_msgs,allowed_msgs",
    test_cases,
)
def test_reprocess(tmp_path, caplog, additional_options, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles")
    mission_dir = tmp_path / "mission_dir"

    def update_ncdf_timestamp(mission_dir: pathlib.Path) -> None:
        time.sleep(1)
        (mission_dir / "p2720002.nc").touch()

    testutils.run_mission(
        data_dir,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} {additional_options}".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
        pre_test_hook=update_ncdf_timestamp,
    )
    # import pdb

    # pdb.set_trace()


def _make_legacy_int_pressure_nc(nc_path: pathlib.Path, value: str) -> None:
    """Rewrites nc_path as a pre-Apr 2026 basestation would have, with
    log_INTERNAL_PRESSURE saved as a single multi-valued string

    Args:
        nc_path: dive netCDF file to rewrite in place
        value: the comma separated string to store for log_INTERNAL_PRESSURE

    Returns:
        None

    Raises:
        None
    """
    drop_vars = {"log_INTERNAL_PRESSURE", "log_INTERNAL_PRESSURE_LATCH"}
    src_path = nc_path.with_suffix(".orig.nc")
    nc_path.rename(src_path)
    # netCDF4 requires str paths
    with (
        netCDF4.Dataset(str(src_path)) as src,
        netCDF4.Dataset(str(nc_path), "w") as dst,
    ):
        src.set_auto_maskandscale(False)
        src.set_auto_chartostring(False)
        dst.set_auto_chartostring(False)
        dst.setncatts({k: src.getncattr(k) for k in src.ncattrs()})
        for name, dim in src.dimensions.items():
            dst.createDimension(name, None if dim.isunlimited() else len(dim))
        for name, var in src.variables.items():
            if name in drop_vars:
                continue
            attrs = {k: var.getncattr(k) for k in var.ncattrs()}
            fill_value = attrs.pop("_FillValue", None)
            new_var = dst.createVariable(
                name, var.datatype, var.dimensions, fill_value=fill_value
            )
            new_var.set_auto_maskandscale(False)
            new_var.setncatts(attrs)
            new_var[...] = var[...]
        string_dim = f"string_{len(value)}"
        if string_dim not in dst.dimensions:
            dst.createDimension(string_dim, len(value))
        legacy_var = dst.createVariable("log_INTERNAL_PRESSURE", "S1", (string_dim,))
        legacy_var[:] = np.array(list(value), dtype="S1")
    src_path.unlink()


@pytest.mark.parametrize("legacy_nc", [False, True])
def test_reload_legacy_multi_value_log_string(tmp_path, caplog, legacy_nc):
    """Pre-Apr 2026 netCDF files hold $INTERNAL_PRESSURE,psia,latch as one string -
    reloading must split it (as LogFile does) rather than fail and drop it"""
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles")
    mission_dir = tmp_path / "mission_dir"

    def make_legacy(mission_dir: pathlib.Path) -> None:
        if legacy_nc:
            _make_legacy_int_pressure_nc(
                mission_dir / "p2720002.nc", "8.35631,14.8032"
            )

    testutils.run_mission(
        data_dir,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} 2".split(),
        caplog,
        # Pre-existing warnings from this fixture, unrelated to the reload
        [
            "Substantial unmodeled flight time",
            "Large mis-match between predicted and observed w",
            "codaTODO_c0 not found",
        ],
        required_msgs=["Loading data from netCDF files"],
        pre_test_hook=make_legacy,
    )

    # netCDF4 requires str paths
    with netCDF4.Dataset(str(mission_dir / "p2720002.nc")) as ds:
        for var_name, expected in (
            ("log_INTERNAL_PRESSURE", 8.35631),
            ("log_INTERNAL_PRESSURE_LATCH", 14.8032),
        ):
            assert ds.variables[var_name].dtype == np.float64
            assert ds.variables[var_name].getValue().item() == pytest.approx(expected)


def test_ignore_truck_legato_columns_kept_without_errors(tmp_path, caplog):
    """sg267 (WHIRLS, Sep 2026) sets ignore_truck_legato = 1, so its truck
    eng columns rbr_* are renamed ignore_rbr_* (Sensors/legato_ext.py) to
    keep them out of CT processing. Nothing registered netCDF metadata for
    those names, so every dive logged 8 errors ("Unknown nc metadata for
    ignore_rbr_*" / "Unknown result variable eng_ignore_rbr_* -- dropped")
    and a "Missing metadata for sg_cal_ignore_truck_legato" warning. They
    must now be kept in the .nc, quietly.

    This dive's Legato had failed (truck columns all NaN, no scicon ct.dat),
    so MDP still bails out on "Legato CT data specified, but no data found" -
    a genuine data problem, not what this test is about."""
    src = pathlib.Path("testdata/sg267_WHIRLS_Sep26_ignore_truck_legato")
    mission_dir = tmp_path / "mission_dir"
    shutil.copytree(src, mission_dir)
    # Stand-in for a fresh process, as in testutils.run_mission()
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()
    Base.set_globals()
    BaseLog.BaseLogger.reset()

    MakeDiveProfiles.main(["--verbose", "--force", "--mission_dir", str(mission_dir)])

    messages = [r.getMessage() for r in caplog.records]
    assert not [m for m in messages if "ignore_rbr" in m or "sg_cal_ignore_truck_legato" in m]
    assert any("Legato CT data specified, but no data found" in m for m in messages)

    with netCDF4.Dataset(str(mission_dir / "p2670399.nc")) as ds:
        assert float(ds["sg_cal_ignore_truck_legato"][...]) == 1.0
        for col in ("conduc", "conducTemp", "temp", "pressure"):
            var = ds[f"eng_ignore_rbr_{col}"]
            assert var.dimensions == ("sg_data_point",)
            assert "ignore_truck_legato" in var.comment
            assert not hasattr(var, "standard_name")
        assert "eng_rbr_temp" not in ds.variables


def _fix(time_s: float, lat_dd: float, lon_dd: float) -> types.SimpleNamespace:
    return types.SimpleNamespace(time_s=time_s, lat_dd=lat_dd, lon_dd=lon_dd, error=10.0)


def test_gps_surface_drift_northward() -> None:
    # 0.001 deg of latitude (~111 m) in 600 s, due north: ~18.6 cm/s
    drift = MakeDiveProfiles.gps_surface_drift(
        _fix(0.0, 47.000, -122.0), _fix(600.0, 47.001, -122.0)
    )
    assert drift["surface_curr_north"] == pytest.approx(18.55, abs=0.01)
    assert drift["surface_curr_east"] == pytest.approx(0.0, abs=1e-6)
    assert drift["surface_curr_error"] == pytest.approx(20.0 / 600.0)


@pytest.mark.parametrize("dt", [0.0, -30.0])
def test_gps_surface_drift_no_time_advance(caplog: pytest.LogCaptureFixture, dt: float) -> None:
    """GPS1 and GPS2 at the same time must not divide by zero (sg250 dive 451)."""
    with caplog.at_level(logging.WARNING):
        drift = MakeDiveProfiles.gps_surface_drift(
            _fix(1000.0, 77.4, 10.0), _fix(1000.0 + dt, 77.4, 10.0)
        )
    assert np.isnan(drift["surface_curr_east"]) and np.isnan(drift["surface_curr_north"])
    assert "surface_curr_error" not in drift
    assert "Unable to determine surface drift" in caplog.text


@pytest.mark.parametrize(
    ("mass_line", "required"),
    [
        # sg256 AMOS_Aug24 (2024): a non-numeric mass reached FlightModel.estimate_volmax
        ("mass = '72.7 kg'; % (kg) scale weight", "mass = '72.7 kg' is not a number"),
        ("% mass removed", "mass in sg_calib_constants.m is missing or not a number (None)"),
    ],
)
def test_bad_calib_mass_fails_cleanly(tmp_path, caplog, mass_line: str, required: str) -> None:
    """A missing or non-numeric mass fails the dive with a clear error, not a traceback."""
    mission_dir = tmp_path / "mission_dir"
    shutil.copytree("testdata/sg272_NANOOS_Feb26_makediveprofiles", mission_dir)
    calib = mission_dir / "sg_calib_constants.m"
    calib.write_text(calib.read_text().replace("mass = 73.956; % (kg) scale weight", mass_line))

    # Fresh module state, as testutils.run_mission does (it requires a 0 exit, so isn't used)
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()
    Base.set_globals()
    BaseLog.BaseLogger.reset()
    with caplog.at_level(logging.INFO):
        rc = MakeDiveProfiles.main(f"--verbose --mission_dir {mission_dir} --force".split())
    assert rc != 0  # the dive failed
    assert required in caplog.text
    assert "fix sg_calib_constants.m and reprocess" in caplog.text
    assert "Traceback" not in caplog.text
    assert "estimate_volmax" not in caplog.text


def test_missing_end_gps_falls_back(tmp_path, caplog) -> None:
    """A log without $GPS uses $GPS2 as the end fix (its warning used to raise AttributeError, sg274 2026-11-03)."""
    mission_dir = tmp_path / "mission_dir"

    def drop_end_gps(mission_dir: pathlib.Path) -> None:
        log = mission_dir / "p2720002.log"
        log.write_text("".join(s for s in log.read_text().splitlines(keepends=True) if not s.startswith("$GPS,")))

    testutils.run_mission(
        pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles"),
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} --force".split(),
        caplog,
        [""],
        pre_test_hook=drop_end_gps,
        required_msgs=[
            f"Couldn't find $GPS in {mission_dir / 'p2720002.log'} - using $GPS2 as the end fix (no DAC)",
            "Bad GPS2 or GPSE; unable to compute depth-average current",
            "Dives processed = [2]",
        ],
    )
    # netCDF4 requires str paths
    with netCDF4.Dataset(str(mission_dir / "p2720002.nc")) as nc:
        gps2 = nc.variables["log_GPS2"][:].tobytes().decode()
        gpse = nc.variables["log_GPS"][:].tobytes().decode()
        assert gpse == ",".join(["$GPS"] + gps2.split(",")[1:9])
        assert nc.variables["log_gps_time"][2] == nc.variables["log_gps_time"][1]


_GARBLED_GPS = {
    # position field garbled (line noise) - time parses, lat doesn't
    "$GPS1": ("$GPS1,030226,193327,4654.694,-12454.175,", "$GPS1,030226,193327,46#4.694,-12454.175,", "GPS2", 0),
    "$GPS2": ("$GPS2,030226,193532,4654.710,", "$GPS2,030226,193532,4654.7Q0,", "GPS1", 1),
    "$GPS": ("$GPS,030226,200233,4654.708,", "$GPS,030226,200233,~654.708,", "GPS2", 2),
    # cut short - GPSFix sets no time or position at all
    "$GPS2 short": ("$GPS2,030226,193532,4654.710,-12454.180,3,0.8,3,15.3,0.8,264.3,12,8.9", "$GPS2,030226,1935", "GPS1", 1),
}


@pytest.mark.parametrize("case", list(_GARBLED_GPS))
def test_garbled_gps_line_marks_fix_bad(tmp_path, caplog, case: str) -> None:
    """A garbled $GPS1/$GPS2/$GPS line marks that fix bad; the dive processes from the others (was a TypeError)."""
    old, new, stand_in, gps_i = _GARBLED_GPS[case]
    mission_dir = tmp_path / "mission_dir"

    def garble(mission_dir: pathlib.Path) -> None:
        log = mission_dir / "p2720002.log"
        text = log.read_text()
        assert text.count(old) == 1
        log.write_text(text.replace(old, new))

    testutils.run_mission(
        pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles"),
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} --force".split(),
        caplog,
        [""],
        pre_test_hook=garble,
        required_msgs=[
            f"fix marked bad, using {stand_in}'s time and position",
            "Dives processed = [2]",
        ],
    )
    # GPSFix logs its own "Invalid GPS line" with the ValueError; nothing else may raise
    assert "TypeError" not in caplog.text
    # netCDF4 requires str paths
    with netCDF4.Dataset(str(mission_dir / "p2720002.nc")) as nc:
        assert nc.variables["log_gps_qc"][gps_i].tobytes() == b"0"  # stored as chars
        assert np.isnan(nc.variables["log_gps_lat"][gps_i])
        name = new.split(",")[0].lstrip("$")
        assert nc.variables[f"log_{name}"][:].tobytes().decode().startswith(new)


# The magvar (9th) field of p2720002.log's fixes - all 15.3
_GPS1_MAGVAR = "$GPS1,030226,193327,4654.694,-12454.175,1,0.8,2,15.3,"
_GPS2_MAGVAR = "$GPS2,030226,193532,4654.710,-12454.180,3,0.8,3,15.3,"
_GPSE_MAGVAR = "$GPS,030226,200233,4654.708,-12454.235,1,0.9,3,15.3"


@pytest.mark.parametrize(
    ("replacements", "magvar", "required"),
    [
        # GPS1's set apart (15.4), to show it's the one used
        (
            {_GPS2_MAGVAR: _GPS2_MAGVAR.replace("15.3", "1#.3"), _GPS1_MAGVAR: _GPS1_MAGVAR.replace("15.3", "15.4")},
            15.4,
            ["$GPS2 has no magnetic variation", "using GPS1's (15.4 degrees)"],
        ),
        (
            {line: line.replace("15.3", "1#.3") for line in (_GPS1_MAGVAR, _GPS2_MAGVAR, _GPSE_MAGVAR)},
            0.0,
            [
                "no other fix has one - headings uncorrected (0.0 degrees), $GPS2 marked bad",
                "Bad GPS2 or GPSE; unable to compute depth-average current",
            ],
        ),
    ],
    ids=["from_gps1", "none_usable"],
)
def test_gps2_without_magvar(
    tmp_path: pathlib.Path,
    caplog: pytest.LogCaptureFixture,
    replacements: dict[str, str],
    magvar: float,
    required: list[str],
) -> None:
    """A $GPS2 garbled in its magvar field takes another fix's, else 0.0 with GPS2 bad (was a TypeError)."""
    mission_dir = tmp_path / "mission_dir"

    def garble(mission_dir: pathlib.Path) -> None:
        log = mission_dir / "p2720002.log"
        text = log.read_text()
        for old, new in replacements.items():
            assert text.count(old) == 1
            text = text.replace(old, new)
        log.write_text(text)

    testutils.run_mission(
        pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles"),
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} --force".split(),
        caplog,
        [""],
        pre_test_hook=garble,
        required_msgs=[*required, "Dives processed = [2]"],
    )
    assert "TypeError" not in caplog.text
    # netCDF4 requires str paths
    with netCDF4.Dataset(str(mission_dir / "p2720002.nc")) as nc:
        assert nc.variables["magnetic_variation"].getValue() == pytest.approx(magvar)
        assert np.isnan(nc.variables["log_gps_magvar"][1])  # the raw $GPS2 value, not the one used
        assert nc.variables["log_gps_qc"][1].tobytes() == b"0"  # GPS2 bad (stored as chars)


def test_all_gps_lines_garbled_fails_cleanly(tmp_path, caplog) -> None:
    """With no usable fix at all the dive fails with an error naming the log, not a traceback."""
    mission_dir = tmp_path / "mission_dir"
    shutil.copytree("testdata/sg272_NANOOS_Feb26_makediveprofiles", mission_dir)
    log = mission_dir / "p2720002.log"
    text = log.read_text()
    for old, new, _, _ in list(_GARBLED_GPS.values())[:3]:
        text = text.replace(old, new)
    log.write_text(text)

    # Fresh module state, as testutils.run_mission does (it requires a 0 exit, so isn't used)
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()
    Base.set_globals()
    BaseLog.BaseLogger.reset()
    with caplog.at_level(logging.INFO):
        MakeDiveProfiles.main(f"--verbose --mission_dir {mission_dir} --force".split())
    assert f"No usable GPS fix in {log}" in caplog.text
    assert "TypeError" not in caplog.text
    assert "Exception when" not in caplog.text


# $GC vbd_secs (the 15th field) of the flare GC and the apogee pump GC in p2720002.log
_FLARE_GC = "$GC,108.59,2597,-145.99,-1.35,-80.00,2892.0,2814.4,2969.6,235.8,2000.7,2.61,-1.48,9,131.00,0.00,"
_APOGEE_GC = "$GC,435.04,10243,0.00,-0.33,0.00,2895.0,2814.5,2975.6,1910.7,2048.2,60.04,-13.75,67,563.92,125.00,"


@pytest.mark.parametrize(
    ("gc_lines", "required"),
    [
        ([_FLARE_GC], "Unable to compute acceleration during flare (no good speeds after the flare)"),
        ([_APOGEE_GC], "Unable to compute acceleration during the apogee pump"),
        ([_FLARE_GC, _APOGEE_GC], "Unable to compute acceleration during the apogee pump"),
    ],
    ids=["flare", "apogee", "both"],
)
def test_solve_flare_apogee_speed_short_intervals(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, gc_lines: list[str], required: str
) -> None:
    """A flare or apogee pump that runs past the data skips that fit (was an IndexError, TypeError or NameError)."""
    mission_dir = tmp_path / "mission_dir"

    def stretch_gcs(mission_dir: pathlib.Path) -> None:
        log = mission_dir / "p2720002.log"
        text = log.read_text()
        for gc_line in gc_lines:
            assert text.count(gc_line) == 1
            # a vbd move longer than the dive puts the interval's end past the last CTD point
            text = text.replace(gc_line, gc_line.removesuffix(",").rsplit(",", 1)[0] + ",99999.00,")
        log.write_text(text)
        calib = mission_dir / "sg_calib_constants.m"
        calib.write_text(calib.read_text() + "solve_flare_apogee_speed = 1;\n")

    testutils.run_mission(
        pathlib.Path("testdata/sg272_NANOOS_Feb26_makediveprofiles"),
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose --mission_dir {mission_dir} --force".split(),
        caplog,
        [""],
        pre_test_hook=stretch_gcs,
        required_msgs=[required, "Dives processed = [2]"],
    )
    for err in ("IndexError", "TypeError", "NameError", "Exception when"):
        assert err not in caplog.text
