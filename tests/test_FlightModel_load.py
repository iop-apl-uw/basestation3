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

"""FlightModel.load_dive_data paths the normal FMS run doesn't take: a velo_NNNN.mat
from a tracking range, and the decimation debug setting."""

import pathlib
import shutil
import types

import netCDF4
import numpy as np
import pytest
import scipy.io as sio

import FlightModel

DATA_DIR = pathlib.Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
DIVE_NUM = 5


@pytest.fixture
def fm_mission(tmp_path, monkeypatch):
    """Copy dive DIVE_NUM's netCDF from the sg561 fixture and set up the FlightModel
    globals load_dive_data reads, as FlightModel.main would.

    Returns:
        The mission directory.
    """
    mission_dir = tmp_path / "mission_dir"
    mission_dir.mkdir()
    nc_name = f"p561{DIVE_NUM:04d}.nc"
    shutil.copy(DATA_DIR / nc_name, mission_dir / nc_name)
    with netCDF4.Dataset(mission_dir / nc_name) as ds:
        volmax = float(ds.variables["sg_cal_volmax"].getValue())

    FlightModel.set_globals()
    monkeypatch.setattr(FlightModel, "mission_directory", str(mission_dir))
    monkeypatch.setattr(FlightModel, "nc_path_format", str(mission_dir / "p561%04d.nc"))
    monkeypatch.setattr(
        FlightModel,
        "angles",
        np.linspace(0, FlightModel.pitchmax, FlightModel.pitchmax + 1),
    )
    monkeypatch.setattr(FlightModel, "flight_dive_data_d", {"volmax": volmax})
    yield mission_dir
    FlightModel.set_globals()


def _load(dive_num=DIVE_NUM):
    dive_data = FlightModel.flight_data(dive_num)
    data_d = FlightModel.load_dive_data(types.SimpleNamespace(use_gsw=True), dive_data)
    return dive_data, data_d


def _num_pts(mission_dir, dive_num=DIVE_NUM):
    with netCDF4.Dataset(mission_dir / f"p561{dive_num:04d}.nc") as ds:
        assert "velo_speed" not in ds.variables
        return len(ds.variables["ctd_depth"])


@pytest.mark.parametrize("shape", ["column", "row"])
def test_velo_mat_file_used(fm_mission, monkeypatch, shape):
    """A velo_NNNN.mat (MATLAB column or row vector) supplies velo_speed."""
    num_pts = _num_pts(fm_mission)
    speed = np.full(num_pts, 0.25)
    sio.savemat(
        fm_mission / f"velo_{DIVE_NUM}.mat",
        {"velo_speed": speed.reshape(-1, 1) if shape == "column" else speed},
    )
    monkeypatch.setattr(FlightModel, "compare_velo", 3)

    dive_data, data_d = _load()
    assert dive_data.dive_data_ok
    assert data_d["n_velo"] > 0
    assert data_d["velo_speed"].ndim == 1
    assert len(data_d["velo_speed"]) == data_d["n_velo"]
    np.testing.assert_allclose(data_d["velo_speed"], 0.25)


def test_velo_mat_file_wrong_length(fm_mission, monkeypatch, caplog):
    """A velo_NNNN.mat that doesn't match the dive's points is reported and not used."""
    num_pts = _num_pts(fm_mission)
    sio.savemat(
        fm_mission / f"velo_{DIVE_NUM}.mat",
        {"velo_speed": np.full(num_pts - 3, 0.25)},
    )
    monkeypatch.setattr(FlightModel, "compare_velo", 3)

    dive_data, data_d = _load()
    assert dive_data.dive_data_ok
    assert data_d["n_velo"] == 0
    assert any(
        r.levelname == "WARNING" and f"velo_{DIVE_NUM}.mat" in r.getMessage()
        for r in caplog.records
    )


def test_no_velo_mat_file_quiet(fm_mission, monkeypatch, caplog):
    """No velo data at all is the normal case - nothing logged about it."""
    monkeypatch.setattr(FlightModel, "compare_velo", 3)

    dive_data, data_d = _load()
    assert dive_data.dive_data_ok
    assert data_d["n_velo"] == 0
    assert not any("velo" in r.getMessage() for r in caplog.records)


@pytest.mark.parametrize("ignore_salinity_qc", [False, True])
def test_decimation(fm_mission, monkeypatch, ignore_salinity_qc):
    """Decimation keeps every Nth good point, with or without the salinity QC filter."""
    monkeypatch.setattr(FlightModel, "ignore_salinity_qc", ignore_salinity_qc)
    monkeypatch.setattr(FlightModel, "data_density_max_depth", 0)
    _, full_d = _load()
    assert full_d is not None

    monkeypatch.setattr(FlightModel, "decimation", 2)
    dive_data, decimated_d = _load()
    assert dive_data.dive_data_ok
    assert decimated_d is not None
    assert 0 < len(decimated_d["w"]) < len(full_d["w"])
