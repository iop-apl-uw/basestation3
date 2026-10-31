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

"""BaseDB writes values as bound parameters, so NaN/masked values don't break the SQL.

sg284 (SG284_MR_testing, 2026-10-27) logged nan in the $GC vbd_ctl/pitch_ctl fields.
processGC formatted each value into the INSERT text, so nan read as a column name
("no such column: nan") and the dive's gc rows never reached the db.
"""

import logging
import pathlib
import shutil
import sqlite3

import netCDF4
import numpy
import pytest

import BaseDB
import BaseLog
import BaseOpts
import Utils

NC_FILE = pathlib.Path("testdata/sg171_EKAMSAT_Apr24/p1710103.nc")
DIVE = 103

# (gc event, column) cells the tests set to non-finite values
NAN_CELLS = {(0, "vbd_ctl"), (1, "pitch_ctl"), (2, "vbd_secs")}
# vbd_rate and vbd_eff are derived from vbd_secs
DERIVED_CELLS = {(2, "vbd_rate"), (2, "vbd_eff")}

TC_VARS = (
    "p", "d", "i", "rollDeg", "rollAD", "sec", "destAD", "endAD",
    "amps", "maxAmps", "volts", "errors", "start_time", "end_time",
)  # fmt: skip


def _base_opts(mission_dir: pathlib.Path) -> BaseOpts.BaseOptions:
    mission_dir.mkdir()
    shutil.copy(NC_FILE.parent / "sg_calib_constants.m", mission_dir)
    # Base.py's options - it is the production caller of loadDB
    opts = BaseOpts.BaseOptions(
        "t",
        cmdline_args=["--mission_dir", str(mission_dir), "--instrument_id", "171"],
        calling_module="Base",
    )
    BaseDB.createDB(opts)
    return opts


def _copy_nc(tmp_path: pathlib.Path, name: str) -> pathlib.Path:
    nc = tmp_path / name
    nc.mkdir()
    nc = nc / NC_FILE.name
    shutil.copy(NC_FILE, nc)
    return nc


def _gc_rows(opts: BaseOpts.BaseOptions) -> list[dict]:
    con = Utils.open_mission_database(opts, ro=True)  # ty: ignore[invalid-argument-type]
    assert con is not None
    try:
        con.row_factory = sqlite3.Row
        rows = con.execute(
            "SELECT * FROM gc WHERE dive=? ORDER BY idx", (DIVE,)
        ).fetchall()
        return [dict(r) for r in rows]
    finally:
        con.close()


@pytest.fixture(autouse=True)
def _info_logging(monkeypatch: pytest.MonkeyPatch) -> None:
    # log_* are no-ops below BaseLogger's level
    monkeypatch.setattr(BaseLog.BaseLogger, "log_level", logging.DEBUG)


def test_gc_nan_values_load_as_null(tmp_path, caplog) -> None:
    clean_nc = _copy_nc(tmp_path, "clean")
    nan_nc = _copy_nc(tmp_path, "nan")
    with netCDF4.Dataset(nan_nc, "r+") as ds:
        ds.variables["gc_vbd_ctl"][0] = numpy.nan
        ds.variables["gc_pitch_ctl"][1] = numpy.nan
        ds.variables["gc_vbd_secs"][2] = numpy.inf

    clean_opts = _base_opts(tmp_path / "clean_mission")
    BaseDB.loadDB(clean_opts, clean_nc, run_dive_plots=False)

    caplog.clear()
    caplog.set_level(logging.WARNING)
    nan_opts = _base_opts(tmp_path / "nan_mission")
    BaseDB.loadDB(nan_opts, nan_nc, run_dive_plots=False)
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]

    clean = _gc_rows(clean_opts)
    nan = _gc_rows(nan_opts)
    assert len(clean) == len(nan) == 28

    for ii, (c_row, n_row) in enumerate(zip(clean, nan, strict=True)):
        for col, c_val in c_row.items():
            if (ii, col) in NAN_CELLS:
                assert n_row[col] is None, (ii, col)
            elif (ii, col) not in DERIVED_CELLS:
                assert n_row[col] == c_val, (ii, col)


def test_tc_nan_values_load_as_null(tmp_path, caplog) -> None:
    nc = _copy_nc(tmp_path, "tc")
    n_events = 3
    with netCDF4.Dataset(nc, "r+") as ds:
        ds.createDimension("tc_event", n_events)
        for var_n in TC_VARS:
            var = ds.createVariable(f"tc_{var_n}", "f8", ("tc_event",))
            var[:] = numpy.arange(1, n_events + 1, dtype=numpy.float64)
        ds.variables["tc_amps"][1] = numpy.nan

    opts = _base_opts(tmp_path / "mission")
    con = Utils.open_mission_database(opts)  # ty: ignore[invalid-argument-type]
    assert con is not None
    caplog.set_level(logging.WARNING)
    with netCDF4.Dataset(nc) as nci:
        cur = con.cursor()
        BaseDB.processTC(DIVE, cur, nci)
        con.commit()
    rows = con.execute(
        "SELECT amps, p, roll_ad FROM tc WHERE dive=? ORDER BY idx", (DIVE,)
    ).fetchall()
    con.close()

    assert "Failed to load tc event" not in caplog.text
    assert rows == [(1.0, 1.0, 0.0), (None, 2.0, 0.0), (3.0, 3.0, 0.0)]


@pytest.mark.parametrize(
    ("val", "expected"),
    [
        (numpy.ma.masked, None),
        (numpy.ma.masked_array(1.5, mask=True), None),
        (numpy.ma.masked_array(1.5, mask=False), 1.5),
        (numpy.nan, None),
        (numpy.inf, None),
        (-numpy.inf, None),
        (numpy.float64(numpy.nan), None),
        (numpy.int32(7), 7),
        (numpy.float32(0.5), 0.5),
        (numpy.array(2.0), 2.0),
        (5, 5),
        (2.5, 2.5),
        ("it's", "it's"),
        (None, None),
    ],
)
def test_sql_value(val, expected) -> None:
    out = BaseDB._sql_value(val)
    assert out == expected
    assert type(out) is type(expected)


def test_insert_column_binds_values(tmp_path) -> None:
    opts = _base_opts(tmp_path / "mission")
    con = Utils.open_mission_database(opts)  # ty: ignore[invalid-argument-type]
    assert con is not None
    cur = con.cursor()
    cur.execute("INSERT INTO dives(dive) VALUES(?)", (DIVE,))
    BaseDB.insertColumn(DIVE, cur, "log_TGT_NAME", "O'Brien's", "TEXT")
    BaseDB.insertColumn(DIVE, cur, "bad_float", numpy.float32(numpy.nan), "FLOAT")
    BaseDB.insertColumn(
        numpy.int32(DIVE), cur, "good_float", numpy.float32(0.25), "FLOAT"
    )
    BaseDB.insertColumn(DIVE, cur, "masked_float", numpy.ma.masked, "FLOAT")
    con.commit()
    row = con.execute(
        "SELECT log_TGT_NAME, bad_float, good_float, masked_float FROM dives WHERE dive=?",
        (DIVE,),
    ).fetchone()
    con.close()
    assert row == ("O'Brien's", None, 0.25, None)
