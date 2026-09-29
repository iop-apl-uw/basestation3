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

"""Mission db write-lock contention between Base.py plotting and GliderEarlyGPS.

Production pattern (2026-09, both servers): a glider redials after a dropped
call while Base.py is still processing the dropped session. BasePlot's
plot_dives()/plot_mission() shared one connection with plot functions that
write to the db (DivePitchRoll, DiveVertVelocityNew, MissionEnergy, ...) and
only committed at the end, holding the write lock for minutes; with
busy_timeout=200 ms, GliderEarlyGPS's calls-table insert for the new call
failed ("could not check schema" + "database is locked inserting comm.log
session") and the call record was lost.
"""

import logging
import pathlib
import shutil
import sqlite3
import types

import pytest

import BaseDB
import BaseLog
import BasePlot
import GliderEarlyGPS
import Utils

NC_FILE = pathlib.Path("testdata/sg686_Shilshole_28Oct25/p6860005.nc")


class FakeSession:
    """Minimal stand-in for CommLog.ConnectSession as used by addSession()."""

    def __init__(self, dive: int = 5, call: int = 1) -> None:
        self.dive_num = dive
        self.calls_made = call

    def to_message_dict(self) -> dict:
        fields = [
            "connected", "lat", "lon", "epoch", "RH", "intP", "temp", "volts10", "volts24", "pitch",
            "depth", "pitchAD", "rollAD", "vbdAD", "iridLat", "iridLon", "irid_t", "sst", "sss", "density",
        ]  # fmt: skip
        d = dict.fromkeys(fields, 0.0)
        d.update({"dive": self.dive_num, "cycle": 0, "call": self.calls_made})
        return d


@pytest.fixture
def base_opts(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> types.SimpleNamespace:
    # log_info() is a no-op unless BaseLogger is at INFO (--verbose)
    monkeypatch.setattr(BaseLog.BaseLogger, "log_level", logging.DEBUG)
    opts = types.SimpleNamespace(mission_dir=tmp_path, instrument_id=686)
    BaseDB.createDB(opts)
    return opts


def _hold_uncommitted_plot_write(base_opts: types.SimpleNamespace) -> sqlite3.Connection:
    """What a plot function did via dbcon: a write left uncommitted on a shared connection."""
    con = Utils.open_mission_database(base_opts)  # ty: ignore[invalid-argument-type]
    assert con is not None
    con.cursor().execute("INSERT INTO dives(dive) VALUES(5);")
    BaseDB.addValToDB(base_opts, 5, "pitch_test", 1.5, con=con)
    assert con.in_transaction
    return con


def _calls_rows(base_opts: types.SimpleNamespace) -> list:
    con = Utils.open_mission_database(base_opts, ro=True)  # ty: ignore[invalid-argument-type]
    assert con is not None
    try:
        return con.execute("SELECT dive, call FROM calls").fetchall()
    finally:
        con.close()


def test_uncommitted_plot_write_blocks_add_session(base_opts, caplog) -> None:
    caplog.set_level(logging.INFO)
    holder = _hold_uncommitted_plot_write(base_opts)
    try:
        assert BaseDB.addSession(base_opts, FakeSession()) is False
        assert any(
            r.levelname == "ERROR" and "database is locked inserting comm.log session" in r.getMessage()
            for r in caplog.records
        )
        caplog.clear()
        # A caller that will retry gets INFO, not ERROR
        assert BaseDB.addSession(base_opts, FakeSession(), retry_on_lock=True) is False
        assert not [r for r in caplog.records if r.levelname == "ERROR"]
        assert any("will retry" in r.getMessage() for r in caplog.records)
    finally:
        holder.commit()
        holder.close()
    # Once the writer commits, the same insert succeeds (and is idempotent)
    assert BaseDB.addSession(base_opts, FakeSession(), retry_on_lock=True) is True
    assert BaseDB.addSession(base_opts, FakeSession(), retry_on_lock=True) is True
    assert _calls_rows(base_opts) == [(5, 1)]


def test_check_schema_current_needs_no_write_lock(base_opts, caplog) -> None:
    """checkSchema() on an up-to-date db must not write PRAGMA user_version -
    that write failed under contention ("could not check schema")."""
    caplog.set_level(logging.INFO)
    holder = _hold_uncommitted_plot_write(base_opts)
    try:
        con = Utils.open_mission_database(base_opts)
        assert con is not None
        BaseDB.checkSchema(None, con)
        con.close()
        assert not [r for r in caplog.records if "could not check schema" in r.getMessage()]
    finally:
        holder.commit()
        holder.close()


def test_check_schema_upgrades_old_version(base_opts) -> None:
    con = Utils.open_mission_database(base_opts)
    assert con is not None
    con.execute("PRAGMA user_version = 3")
    BaseDB.checkSchema(None, con)
    con.commit()
    assert con.execute("PRAGMA user_version").fetchone()[0] == BaseDB.currentSchemaVersion
    con.close()


def test_plot_dives_commits_after_each_plot_function(base_opts, tmp_path) -> None:
    """A later plot function (standing in for GliderEarlyGPS running
    concurrently) can write to the db once an earlier one has written via
    dbcon - i.e. plot_dives() doesn't hold the write lock across plots."""
    nc = tmp_path / NC_FILE.name
    shutil.copy(NC_FILE, nc)
    probe_results: list[bool] = []

    def writing_plot(base_opts, dive_ncf, generate_plots=True, dbcon=None):
        BaseDB.addValToDB(base_opts, 5, "pitch_test", 1.5, con=dbcon)
        return ([], [])

    def probe_plot(base_opts, dive_ncf, generate_plots=True, dbcon=None):
        probe_results.append(BaseDB.addSession(base_opts, FakeSession(), retry_on_lock=True))
        return ([], [])

    BasePlot.plot_dives(
        base_opts,
        {"writer": writing_plot, "probe": probe_plot},
        [nc],
        generate_plots=False,
    )
    assert probe_results == [True]
    assert _calls_rows(base_opts) == [(5, 1)]


def test_plot_mission_commits_after_each_plot_function(base_opts) -> None:
    probe_results: list[bool] = []

    def writing_plot(base_opts, mission_str, dive=None, generate_plots=True, dbcon=None):
        BaseDB.addValToDB(base_opts, 5, "energy_test", 2.5, con=dbcon)
        return ([], [])

    def probe_plot(base_opts, mission_str, dive=None, generate_plots=True, dbcon=None):
        probe_results.append(BaseDB.addSession(base_opts, FakeSession(), retry_on_lock=True))
        return ([], [])

    BasePlot.plot_mission(
        base_opts,
        {"writer": writing_plot, "probe": probe_plot},
        "SG686 test",
        generate_plots=False,
    )
    assert probe_results == [True]


def test_caller_owned_connection_is_not_committed(base_opts) -> None:
    """When a caller passes dbcon (BaseDB.updateDBFromPlots inside loadDB),
    it owns the transaction - plot_mission() must not commit it."""
    con = Utils.open_mission_database(base_opts)
    assert con is not None

    def writing_plot(base_opts, mission_str, dive=None, generate_plots=True, dbcon=None):
        BaseDB.addValToDB(base_opts, 5, "energy_test", 2.5, con=dbcon)
        return ([], [])

    BasePlot.plot_mission(
        base_opts,
        {"writer": writing_plot},
        "SG686 test",
        generate_plots=False,
        dbcon=con,
    )
    assert con.in_transaction
    con.rollback()
    con.close()


def _client(base_opts) -> GliderEarlyGPS.GliderEarlyGPSClient:
    return GliderEarlyGPS.GliderEarlyGPSClient(base_opts.mission_dir / "comm.log", base_opts, [])


def test_gliderearlygps_queues_and_retries_locked_session(base_opts, caplog) -> None:
    caplog.set_level(logging.INFO)
    client = _client(base_opts)
    holder = _hold_uncommitted_plot_write(base_opts)
    try:
        client._log_session(FakeSession(dive=5, call=2))
        assert len(client._pending_sessions) == 1
        client._retry_pending_sessions()  # still locked
        assert len(client._pending_sessions) == 1
    finally:
        holder.commit()
        holder.close()
    client._retry_pending_sessions()
    assert client._pending_sessions == []
    assert _calls_rows(base_opts) == [(5, 2)]
    assert any("Logged queued session dive:5 call:2" in r.getMessage() for r in caplog.records)
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "WARNING")]


def test_gliderearlygps_final_retry_warns_once(base_opts, caplog) -> None:
    caplog.set_level(logging.INFO)
    client = _client(base_opts)
    holder = _hold_uncommitted_plot_write(base_opts)
    try:
        client._log_session(FakeSession())
        client._retry_pending_sessions(final=True)
    finally:
        holder.commit()
        holder.close()
    problems = [(r.levelname, r.getMessage()) for r in caplog.records if r.levelname in ("ERROR", "WARNING")]
    assert len(problems) == 1
    assert problems[0][0] == "WARNING"
    assert "Could not log 1 session(s) to the mission db (database locked)" in problems[0][1]


def test_gliderearlygps_empty_retry_is_noop(base_opts) -> None:
    client = _client(base_opts)
    client._retry_pending_sessions(final=True)
    assert client._pending_sessions == []
