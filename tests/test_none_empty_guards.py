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

"""Latent crashes found in the None vs empty review (2026-11-06): each path took an
empty or missing result it didn't guard against."""

import asyncio
import pathlib
import sys
import types

import numpy as np
import pytest

import ExtractTimeseries
import FlightModel
import rafos
import Utils2

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import tmicl_ext  # noqa: E402  # ty: ignore[unresolved-import]


@pytest.mark.parametrize("data", [np.empty((0, 3)), np.ones((3, 2))[:0], None])
def test_tmicl_eng_file_reader_no_data(data, monkeypatch: pytest.MonkeyPatch) -> None:
    """An array from the binary branch made "if not data" raise; empty or None skips the file."""
    monkeypatch.setattr(tmicl_ext, "extract_file_metadata", lambda *_: ({"columns": "time a b"}, None))
    monkeypatch.setattr(tmicl_ext, "extract_file_data", lambda *_: data)
    ret_list, _ = tmicl_ext.eng_file_reader([{"file_name": "pc0001a_base_ch00.eng"}], {}, {})
    assert ret_list == []


def test_rafos_no_timeseries(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """extractVars returning None (no timeseries file) used to raise TypeError at del(data['time'])."""
    monkeypatch.setattr(Utils2, "get_mission_timeseries_name", lambda *_: tmp_path / "missing.nc")
    monkeypatch.setattr(ExtractTimeseries, "extractVars", lambda *_: None)
    assert asyncio.run(rafos.hitsTable(str(tmp_path))) == []


def test_flight_checkpoint_before_any_dive(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """With checkpointing on, saving before any dive is processed (flight_dive_nums == []) raised in max()."""
    FlightModel.set_globals()
    db = tmp_path / "flight_dive_data.pkl"
    capture = types.SimpleNamespace(stopStringCapture=lambda: "", startStringCapture=lambda: None)
    monkeypatch.setattr(FlightModel.BaseLogger, "self", capture, raising=False)
    monkeypatch.setattr(FlightModel, "flight_dive_data_filename", str(db))
    monkeypatch.setattr(FlightModel, "flight_dive_data_d", {"last_updated": 0, "history": ""})
    monkeypatch.setattr(FlightModel, "flight_dive_nums", [])
    monkeypatch.setattr(FlightModel, "checkpoint_flight_dive_data", True)
    monkeypatch.setattr(FlightModel, "dump_checkpoint_data_matfiles", False)
    monkeypatch.setattr(FlightModel, "flight_directory", str(tmp_path))
    FlightModel.save_flight_database(None)
    assert db.exists()
    assert not list(tmp_path.glob("fdd_*"))
