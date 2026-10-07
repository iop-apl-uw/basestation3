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

"""mission_map with bad map limits in sg_plot_constants.m (sg261 BBOS_Sep26, 2026-08-31)."""

import logging
import pathlib
import sqlite3

import pytest

import Base  # noqa: F401 - import order: avoids the CalibConst circular import
import BaseOpts
import PlotUtils
from Plotting import MissionMap

_ETOPO = pathlib.Path(__file__).parent.parent / "data" / "ETOPO2v2g_f4.nc"


def _mission(tmp_path: pathlib.Path, plot_constants: str) -> tuple[BaseOpts.BaseOptions, sqlite3.Connection]:
    """A mission dir with sg_plot_constants.m and an in-memory dives table near sg261's positions."""
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    (mission_dir / "sg_plot_constants.m").write_text(plot_constants)
    base_opts = BaseOpts.BaseOptions(
        "", cmdline_args=["--mission_dir", str(mission_dir)], calling_module="BasePlot"
    )
    PlotUtils.setup_plot_directory(base_opts)
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE dives (dive INTEGER, log_gps_lat REAL, log_gps_lon REAL)")
    conn.executemany(
        "INSERT INTO dives VALUES (?, ?, ?)",
        [(1, 72.078, -68.745), (2, 72.079, -68.720), (3, 72.080, -68.705), (4, 72.085, -68.679)],
    )
    return base_opts, conn


def test_mission_map_ignores_swapped_lat_limits(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    base_opts, conn = _mission(
        tmp_path, "lat_north = 71.25;\nlat_south = 72.75;\nlon_west = -69;\nlon_east = -64.5;\n"
    )
    with caplog.at_level(logging.WARNING):
        _, files = MissionMap.mission_map(base_opts, ["SG261 test"], dbcon=conn)
    assert "lat_south (72.75) is not south of lat_north (71.25)" in caplog.text
    assert "ignoring the plot limits" in caplog.text
    assert files
    assert "Traceback" not in caplog.text


@pytest.mark.skipif(not _ETOPO.exists(), reason="needs data/ETOPO2v2g_f4.nc")
def test_mission_map_without_bathymetry_in_extent(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """lon_west east of lon_east: the bathymetry subset is empty - draw without it, don't raise."""
    base_opts, conn = _mission(
        tmp_path, "lat_north = 72.75;\nlat_south = 71.25;\nlon_west = -64.5;\nlon_east = -69;\n"
    )
    with caplog.at_level(logging.WARNING):
        _, files = MissionMap.mission_map(base_opts, ["SG261 test"], dbcon=conn)
    assert "No bathymetry within the map extent" in caplog.text
    assert "Traceback" not in caplog.text
