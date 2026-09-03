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

"""Regression tests for GliderDAC.py's QC_INTERPOLATED marking of depth,
lat and lon in the exported GliderDAC netCDF.
"""

import pathlib

import numpy as np
import testutils
import xarray as xr

import Base
import GliderDAC
import QC

DATA_DIR_NAME = "sg160_sbe43_scicon"
DIVE_BASE = "p1600001"

# Reused from tests/test_DiveSBE43.py's sg160_sbe43_scicon case - the
# warnings/errors this fixture is known to emit when built through the real
# pipeline (plots are disabled here via --plot_types none, since this test
# only needs the per-dive netCDF, so plot-related noise doesn't apply).
ALLOWED_MSGS = [
    "value ignored. v3 Flight Model does not use this value",
    "Found Disconnect with no previous Connected",
    "timeout(s) seen in",
    "Ignoring temperature frequency limits",
    "Ignoring conductivity frequency limits",
    "Substantial unmodeled flight time",
    "Large mis-match between predicted and observed w",
    "Missing metadata for sg_cal_",
    "Unclassified qc_str changed temperature implies changed SBE43 oxygen",
]

BASE_CONFIG = pathlib.Path("docs/gliderdac/seaglider.yml")
PROJECT_CONFIG = pathlib.Path("docs/gliderdac/project.yml")
DEPLOYMENT_CONFIG = pathlib.Path("testdata") / DATA_DIR_NAME / "gliderdac_deployment.yml"


def _build_mission(caplog) -> pathlib.Path:
    """Runs the real raw-to-netCDF pipeline for the sg160_sbe43_scicon
    fixture and returns the resulting mission_dir.

    Args:
        caplog: pytest log-capture fixture.

    Returns:
        The mission_dir the per-dive netCDF was built into.
    """
    data_dir = pathlib.Path("testdata").joinpath(DATA_DIR_NAME)
    mission_dir = data_dir.joinpath("mission_dir")
    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        [
            "--verbose",
            "--mission_dir",
            str(mission_dir),
            "--plot_types",
            "none",
            "--no-notify_vis",
        ],
        caplog,
        ALLOWED_MSGS,
    )
    return mission_dir


def _run_gliderdac(mission_dir: pathlib.Path, gliderdac_dir: pathlib.Path, bin_width: float) -> xr.Dataset:
    """Runs GliderDAC.main directly against an already-built mission_dir and
    returns the resulting output dataset.

    Args:
        mission_dir: mission_dir already populated with a per-dive netCDF
            (see _build_mission).
        gliderdac_dir: directory to write the GliderDAC output netCDF into -
            distinct per call since the output filename is derived from the
            dive's own start time, not wall-clock time, and would otherwise
            collide between the interpolated and binned runs.
        bin_width: value for --gliderdac_bin_width (0.0 = timeseries/
            interpolated path, >0 = binned path).

    Returns:
        The opened GliderDAC output dataset for the single dive.
    """
    result = GliderDAC.main(
        cmdline_args=[
            "--mission_dir",
            str(mission_dir),
            "--gliderdac_base_config",
            str(BASE_CONFIG),
            "--gliderdac_project_config",
            str(PROJECT_CONFIG),
            "--gliderdac_deployment_config",
            str(DEPLOYMENT_CONFIG),
            "--gliderdac_directory",
            str(gliderdac_dir),
            "--gliderdac_bin_width",
            str(bin_width),
        ]
    )
    assert result == 0
    out_files = list(gliderdac_dir.glob("*.nc"))
    assert len(out_files) == 1
    return xr.open_dataset(out_files[0])


def test_gliderdac_qc_interpolated(caplog):
    """Checks that the timeseries (interpolated) GliderDAC output marks
    depth/lat/lon points that were interpolated onto sbe43's own sample
    time as QC_INTERPOLATED, while CTD-timebase points stay QC_NO_CHANGE.
    """
    mission_dir = _build_mission(caplog)

    ds = _run_gliderdac(mission_dir, mission_dir / "gliderdac_interp", bin_width=0.0)
    try:
        for qc_var in ("depth_qc", "lat_qc", "lon_qc"):
            qc_v = ds[qc_var].values.astype(np.int8)
            assert np.any(qc_v == QC.QC_INTERPOLATED), (
                f"{qc_var} never marked QC_INTERPOLATED"
            )
            assert np.any(qc_v == QC.QC_NO_CHANGE), (
                f"{qc_var} never has a CTD-timebase (QC_NO_CHANGE) point"
            )

        interpolated_i = np.nonzero(
            ds["depth_qc"].values.astype(np.int8) == QC.QC_INTERPOLATED
        )[0]
        assert interpolated_i.size
        lat_v = ds["lat"].values
        lon_v = ds["lon"].values
        assert not np.any(np.isnan(lat_v[interpolated_i]))
        assert not np.any(np.isnan(lon_v[interpolated_i]))
        assert np.all((lat_v > -90) & (lat_v < 90))
        assert np.all((lon_v > -180) & (lon_v < 180))
    finally:
        ds.close()


def test_gliderdac_binned_excludes_interpolated_depth_qc(caplog):
    """Checks that the binned GliderDAC output never marks depth_qc
    QC_INTERPOLATED - bin centers are a fixed regular grid, not
    interpolated estimates, per GliderDAC.py's binned code path.
    """
    mission_dir = _build_mission(caplog)

    ds = _run_gliderdac(mission_dir, mission_dir / "gliderdac_binned", bin_width=1.0)
    try:
        qc_v = ds["depth_qc"].values.astype(np.int8)
        assert not np.any(qc_v == QC.QC_INTERPOLATED)
    finally:
        ds.close()
