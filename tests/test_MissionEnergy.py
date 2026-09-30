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

"""Tests for Plotting/MissionEnergy.py"""

import sqlite3
import types

import numpy as np
import pytest

import PlotUtilsPlotly
from Plotting import MissionEnergy

N_DIVES = 10


def _make_single_pack_db() -> sqlite3.Connection:
    """Builds an in-memory dives table shaped like a single (10V only) pack glider.

    All the 24V columns are NULL, matching what BaseDB writes when the
    glider log carries no $AH0_24V/$24V_AH/$FG_AHR_24Vo (sg262_BBOS_Sep26).

    Returns:
        An open sqlite3 connection holding the seeded dives table.
    """
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE dives (dive INTEGER PRIMARY KEY,"
        " fg_kJ_used_10V FLOAT, fg_kJ_used_24V FLOAT,"
        " fg_batt_capacity_10V FLOAT, fg_batt_capacity_24V FLOAT,"
        " fg_ah_used_10V FLOAT, fg_ah_used_24V FLOAT,"
        " log_FG_AHR_10Vo FLOAT, log_FG_AHR_24Vo FLOAT,"
        " batt_capacity_10V FLOAT, batt_capacity_24V FLOAT,"
        " batt_Ahr_cap_10V FLOAT, batt_Ahr_cap_24V FLOAT,"
        " batt_ah_10V FLOAT, batt_ah_24V FLOAT,"
        " batt_volts_10V FLOAT, batt_volts_24V FLOAT,"
        " batt_kJ_used_10V FLOAT, batt_kJ_used_24V FLOAT,"
        " time_seconds_on_surface FLOAT, time_seconds_diving FLOAT,"
        " log_gps_time FLOAT, log_gps2_time FLOAT,"
        " device_GPS_joules FLOAT, sensor_SciCon_joules FLOAT)"
    )
    t0 = 1_790_000_000.0
    dive_secs = 21600.0
    for dive in range(1, N_DIVES + 1):
        fg_ah = 0.3 * dive
        model_ah = 0.07 * dive
        conn.execute(
            "INSERT INTO dives (dive, fg_kJ_used_10V, fg_batt_capacity_10V,"
            " fg_ah_used_10V, log_FG_AHR_10Vo, batt_capacity_10V,"
            " batt_capacity_24V, batt_Ahr_cap_10V, batt_ah_10V, batt_ah_24V,"
            " batt_volts_10V, batt_volts_24V, batt_kJ_used_10V, batt_kJ_used_24V,"
            " time_seconds_on_surface, time_seconds_diving, log_gps_time,"
            " log_gps2_time, device_GPS_joules, sensor_SciCon_joules)"
            " VALUES (?, 16.0, ?, 0.3, ?, ?, 0.0, 575.0, ?, 0.0,"
            " 14.8, 0.0, 3.7, 0.0, 500.0, ?, ?, ?, 500.0, 60000.0)",
            (
                dive,
                (575.0 - fg_ah) / 575.0,
                fg_ah,
                (575.0 - model_ah) / 575.0,
                model_ah,
                dive_secs - 500.0,
                t0 + dive * dive_secs,
                t0 + (dive - 1) * dive_secs + 500.0,
            ),
        )
    conn.commit()
    return conn


def test_mission_energy_single_pack_fuel_gauge_trace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A single-pack glider's all-NULL 24V fuel gauge column must not NaN out
    the plotted Fuel Gauge trace - regression test for a Series-is-None check
    that never fell back to 0 (sg262_BBOS_Sep26 showed no fuel gauge trace).

    Args:
        monkeypatch: pytest fixture, used to skip writing plot files to disk.
    """
    monkeypatch.setattr(PlotUtilsPlotly, "write_output_files", lambda *_: [])
    base_opts = types.SimpleNamespace(
        mission_energy_dives_back=5,
        mission_energy_reserve_percent=0.15,
    )
    conn = _make_single_pack_db()

    figs, _ = MissionEnergy.mission_energy(
        base_opts, "SG262 test", dive=None, generate_plots=True, dbcon=conn
    )
    conn.close()

    assert len(figs) == 1
    traces = {trace.name: trace for trace in figs[0].data}
    for name, expected in (("Fuel Gauge", 16.0), ("Modeled", 3.7)):
        assert name in traces, f"{name} trace missing"
        y = np.asarray(traces[name].y, dtype=float)
        assert np.all(np.isfinite(y)), f"{name} trace has non-finite values"
        np.testing.assert_allclose(y, expected)
