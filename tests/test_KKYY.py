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

"""KKYY: a dive file without the variables KKYY needs is skipped with a warning, not a traceback."""

import logging
import pathlib
import shutil

import pytest
import xarray as xr

import Base  # noqa: F401 - normal import order
import BaseLog
import KKYY

FIXTURE = pathlib.Path("testdata/sg171_EKAMSAT_Apr24_SimplePlotExtension/p1710100.nc")


def _run(mission_dir: pathlib.Path, nc: pathlib.Path) -> int:
    BaseLog.BaseLogger.reset()
    return KKYY.main(["--mission_dir", str(mission_dir), str(nc)])  # argparse takes str


def test_kkyy_writes_files(tmp_path: pathlib.Path) -> None:
    nc = tmp_path / FIXTURE.name
    shutil.copy(FIXTURE, nc)
    assert _run(tmp_path, nc) == 0
    assert nc.with_suffix(".up_kkyy").exists() and nc.with_suffix(".dn_kkyy").exists()


def test_kkyy_dive_missing_ctd_vars(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """sg265 M03JAN2026 dive 414 (2026-05-01): KKYY read the dive file before its CT data was in."""
    nc = tmp_path / FIXTURE.name
    with xr.open_dataset(FIXTURE, decode_times=False) as ds:
        ds.drop_vars(["ctd_depth", "salinity"]).to_netcdf(nc)
    with caplog.at_level(logging.WARNING):
        assert _run(tmp_path, nc) == 0
    assert f"{nc} lacks ctd_depth, salinity - no KKYY files for this dive (yet)" in caplog.text
    assert "Traceback" not in caplog.text and "KeyError" not in caplog.text
    assert not nc.with_suffix(".up_kkyy").exists()
