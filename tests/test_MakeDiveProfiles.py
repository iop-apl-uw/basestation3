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

import pathlib
import shutil
import time

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
