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

import logging
import pathlib
import shutil
import zipfile

import numpy as np
import pandas as pd

import BaseOpts
import MakeKML

TRACK_VARS = ["ctd_depth", "longitude", "latitude", "ctd_time"]


def test_complete_track_points_drops_rows_with_any_nan() -> None:
    """NaNs in different rows per column must not leave the columns different lengths.

    Dropping them column by column made depth shorter than time, and
    printDive indexed past its end (IndexError, sg274 2026-09-21).
    """
    nan = np.nan
    dive_track = pd.DataFrame(
        {
            "ctd_depth": [1.0, nan, 3.0, 4.0, 5.0],
            "longitude": [-122.1, -122.2, nan, -122.4, -122.5],
            "latitude": [47.1, 47.2, 47.3, 47.4, nan],
            "ctd_time": [10.0, 20.0, 30.0, 40.0, 50.0],
        }
    )
    vectors = MakeKML.complete_track_points(dive_track, TRACK_VARS)

    assert vectors is not None
    depth, lon, lat, time_vals = vectors
    assert len(depth) == len(lon) == len(lat) == len(time_vals) == 2
    np.testing.assert_array_equal(time_vals, [10.0, 40.0])
    np.testing.assert_array_equal(depth, [1.0, 4.0])


def test_complete_track_points_none_when_no_complete_row() -> None:
    dive_track = pd.DataFrame(
        {
            "ctd_depth": [1.0, np.nan],
            "longitude": [np.nan, -122.2],
            "latitude": [47.1, 47.2],
            "ctd_time": [10.0, 20.0],
        }
    )
    assert MakeKML.complete_track_points(dive_track, TRACK_VARS) is None


def test_print_targets_skips_bad_target_line(tmp_path, caplog) -> None:
    """A target with blank coordinates is warned about and skipped, the rest are written.

    sg676 ARIA2026_backup (2026-02-02, release 3.0.6) had `ESCAPE lat= lon= ...`, which raised
    a ValueError in printTargets before d110515 added the input checks.
    """
    import io

    import Base  # noqa: F401 - normal import order

    targets = tmp_path / "targets"
    targets.write_text(
        "T1 lat=-6805.787 lon=-6956.447 radius=500 goto=T1 escape=T2\n"
        "ESCAPE lat= lon= radius=1000 goto=ESCAPE escape=ESCAPE\n"
    )
    fo = io.StringIO()
    with caplog.at_level(logging.WARNING):
        MakeKML.printTargets("T1", False, targets, 676, True, fo)
    kml = fo.getvalue()
    assert "<name>T1</name>" in kml
    assert "<name>ESCAPE</name>" not in kml
    assert f"Failed to convert lat= (could not convert string to float: '') (file:{targets}, lineno:2" in caplog.text
    assert "Traceback" not in caplog.text


def test_main_without_parquet_reads_the_netcdf_files(tmp_path, caplog) -> None:
    """With kml_use_parquet off, the dive netCDF files (Paths) are read - printDive only took a str
    and sent each Path down the parquet branch (AttributeError)."""
    mission_dir = tmp_path / "mission_dir"
    shutil.copytree("testdata/sg236_NANOOS_May23_netcdfs", mission_dir)
    shutil.copy(pathlib.Path("testdata/sg236_NANOOS_May23") / "sg_calib_constants.m", mission_dir)
    base_opts = BaseOpts.BaseOptions(
        "test", cmdline_args=["--mission_dir", str(mission_dir), "--no-kml_use_parquet"], calling_module="MakeKML"
    )
    processed: list[pathlib.Path] = []
    with caplog.at_level(logging.ERROR):
        assert MakeKML.main(base_opts, None, processed) == 0
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    with zipfile.ZipFile(mission_dir / "sg236.kmz") as kmz:
        kml = kmz.read(kmz.namelist()[0]).decode()
    assert all(f"SG236 dive {d:03d} end" in kml for d in range(1, 6))
