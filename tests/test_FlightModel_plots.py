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

"""Synthetic-data unit tests for FlightModel's 5 render_* plot functions.

These exercise the plotting code directly - with small, made-up numpy grids
and flight_data instances - so they don't need a mission directory, real dive
data, or a full FlightModel run.
"""

import types

import numpy as np
import plotly.graph_objects
import pytest

import FlightModel

ENGINES = ["matplotlib", "plotly"]


def _base_opts(engine):
    return types.SimpleNamespace(fm_plot_engine=engine)


def _make_hd_grids():
    hd_a_grid = np.linspace(0.001, 0.02, 5)
    hd_b_grid = np.linspace(0.005, 0.03, 4)
    HD_A, HD_B = np.meshgrid(hd_a_grid, hd_b_grid)
    return hd_a_grid, hd_b_grid, HD_A, HD_B


def _make_flight_data(dive_num, hd_a, hd_b, vbdbias, abs_compress, bottom_press, hd_ab_trusted=False):
    dd = FlightModel.flight_data(dive_num)
    dd.hd_a = hd_a
    dd.hd_b = hd_b
    dd.vbdbias = vbdbias
    dd.median_vbdbias = vbdbias
    dd.w_rms_vbdbias = 1.2
    dd.abs_compress = abs_compress
    dd.bottom_press = bottom_press
    dd.hd_ab_trusted = hd_ab_trusted
    return dd


@pytest.fixture(autouse=True)
def _clear_matplotlib_figure():
    """Ensures matplotlib figure state doesn't bleed between tests."""
    yield
    FlightModel.plt.clf()


def _assert_plotly_result(result, expected_trace_name=None):
    assert isinstance(result, plotly.graph_objects.Figure)
    assert len(result.data) > 0
    if expected_trace_name is not None:
        names = [trace.name for trace in result.data]
        assert expected_trace_name in names


def _assert_matplotlib_result(result):
    assert result is None
    assert len(FlightModel.plt.gcf().get_axes()) > 0


@pytest.mark.parametrize("engine", ENGINES)
def test_render_dac_plot(engine):
    hd_a_grid, hd_b_grid, HD_A, HD_B = _make_hd_grids()
    hd_a_c, hd_b_c = hd_a_grid[2], hd_b_grid[1]
    pHD_A = HD_A / hd_a_c
    pHD_B = HD_B / hd_b_c
    rng = np.random.default_rng(0)
    DAC_u = rng.uniform(-0.05, 0.05, HD_A.shape)
    DAC_v = rng.uniform(-0.05, 0.05, HD_A.shape)
    DACm = np.sqrt(DAC_u**2 + DAC_v**2)
    W_misfit_RMS = np.full(HD_A.shape, 0.05)
    w_misfit_rms_levels = FlightModel.ab_tolerance * np.array([1.0, 2.0, 3.0, 4.0])

    data = FlightModel.DACPlotData(
        dive_num=5,
        glider_mission_string="SG500 Test Mission",
        min_misfit=1.1,
        compare_velo=0,
        hd_a_c=hd_a_c,
        hd_b_c=hd_b_c,
        DACmm=0.02,
        pHD_A=pHD_A,
        pHD_B=pHD_B,
        DAC_u=DAC_u,
        DAC_v=DAC_v,
        DACm=DACm,
        W_misfit_RMS=W_misfit_RMS,
        w_misfit_rms_levels=w_misfit_rms_levels,
        mass_comp=1.5,
        pressmin=10,
        pressmax=6000,
        volmax=53000.0,
        abs_compress=2.5e-6,
        hd_c=1.0,
        hd_s=1.0,
        therm_expan=1e-4,
        glider_length=2.0,
    )
    result = FlightModel.render_dac_plot(_base_opts(engine), data)
    if engine == "plotly":
        _assert_plotly_result(result, expected_trace_name="Best fit w_rms")
    else:
        _assert_matplotlib_result(result)


@pytest.mark.parametrize("engine", ENGINES)
@pytest.mark.parametrize("with_previous_solution", [False, True])
def test_render_ab_grid_plot(engine, with_previous_solution):
    hd_a_grid, hd_b_grid, HD_A, HD_B = _make_hd_grids()
    ia, ib = 2, 1
    W_misfit_RMS = np.full(HD_A.shape, 0.05)
    last_W_misfit_RMS = np.full(HD_A.shape, 0.08) if with_previous_solution else None
    w_misfit_rms_levels = FlightModel.ab_tolerance * np.array([1.0, 2.0, 3.0, 4.0])
    prev_w_misfit_rms_levels = [FlightModel.ab_tolerance]

    data = FlightModel.ABGridPlotData(
        dive_num=5,
        ia=ia,
        ib=ib,
        min_misfit=0.05,
        W_misfit_RMS=W_misfit_RMS,
        last_W_misfit_RMS=last_W_misfit_RMS,
        hd_a_grid=hd_a_grid,
        hd_b_grid=hd_b_grid,
        HD_A=HD_A,
        HD_B=HD_B,
        w_misfit_rms_levels=w_misfit_rms_levels,
        prev_w_misfit_rms_levels=prev_w_misfit_rms_levels,
        ab_tolerance=FlightModel.ab_tolerance,
        w_rms_func_bad=FlightModel.w_rms_func_bad,
        mass_comp=1.5,
        pressmin=10,
        pressmax=6000,
        dive_set=[3, 4, 5],
        pitch_diff=18,
        compare_velo=0,
        glider_mission_string="SG500 Test Mission",
        show_previous_ab_solution=with_previous_solution,
        committed_hd_a=hd_a_grid[ia],
        committed_hd_b=hd_b_grid[ib],
        volmax=53000.0,
        abs_compress=2.5e-6,
        hd_c=1.0,
        hd_s=1.0,
        therm_expan=1e-4,
        glider_length=2.0,
    )
    result = FlightModel.render_ab_grid_plot(_base_opts(engine), data)
    if engine == "plotly":
        _assert_plotly_result(result, expected_trace_name="New min a/b (with tolerance span)")
    else:
        _assert_matplotlib_result(result)


def _make_mission_dict(dds, hd_a_grid, hd_b_grid, any_hd_ab_trusted=False):
    return {
        "volmax": 53000.0,
        "abs_compress": 2.0e-6,
        "hd_a": dds[-1].hd_a,
        "hd_b": dds[-1].hd_b,
        "VBD_CNV": None,
        "ac_min": 0.0,
        "ac_max": 5.0e-6,
        "ac_min_press": 500,
        "any_hd_ab_trusted": any_hd_ab_trusted,
        "mass": 60.0,
        "mass_comp": 1.5,
        "hd_a_grid": hd_a_grid,
        "hd_b_grid": hd_b_grid,
        **{dd.dive_num: dd for dd in dds},
    }


@pytest.mark.parametrize("engine", ENGINES)
def test_render_vbdbias_plot(engine):
    dive_nums = [2, 3, 4, 5]
    dds = [
        _make_flight_data(d, 0.005, 0.02, vbdbias=10.0 * i, abs_compress=2e-6, bottom_press=1000)
        for i, d in enumerate(dive_nums)
    ]
    hd_a_grid, hd_b_grid, _, _ = _make_hd_grids()
    flight_dive_data_d = _make_mission_dict(dds, hd_a_grid, hd_b_grid)

    result = FlightModel.render_vbdbias_plot(
        _base_opts(engine),
        dive_nums,
        flight_dive_data_d,
        "SG500 Test Mission",
        "14 Jul 2026 00:00:00",
        vbdbias_filter=5,
        show_implied_c_vbd=None,
    )
    if engine == "plotly":
        _assert_plotly_result(result)
    else:
        _assert_matplotlib_result(result)


@pytest.mark.parametrize("engine", ENGINES)
def test_render_abs_compress_plot(engine):
    dive_nums = [2, 3, 4, 5]
    dds = [
        _make_flight_data(
            d, 0.005, 0.02, vbdbias=10.0, abs_compress=2e-6 + i * 1e-7, bottom_press=1000 + i * 100
        )
        for i, d in enumerate(dive_nums)
    ]
    hd_a_grid, hd_b_grid, _, _ = _make_hd_grids()
    flight_dive_data_d = _make_mission_dict(dds, hd_a_grid, hd_b_grid)

    result = FlightModel.render_abs_compress_plot(
        _base_opts(engine),
        dive_nums,
        flight_dive_data_d,
        "SG500 Test Mission",
        "14 Jul 2026 00:00:00",
    )
    if engine == "plotly":
        _assert_plotly_result(result)
    else:
        _assert_matplotlib_result(result)


@pytest.mark.parametrize("engine", ENGINES)
def test_render_ab_dives_plot(engine):
    dive_nums = [2, 3, 4, 5]
    dds = [
        _make_flight_data(
            d,
            0.005,
            0.02,
            vbdbias=10.0,
            abs_compress=2e-6,
            bottom_press=1000,
            hd_ab_trusted=(d == 5),
        )
        for d in dive_nums
    ]
    hd_a_grid, hd_b_grid, _, _ = _make_hd_grids()
    flight_dive_data_d = _make_mission_dict(dds, hd_a_grid, hd_b_grid, any_hd_ab_trusted=True)

    W_misfit_RMS = np.full((len(hd_b_grid), len(hd_a_grid)), 0.05)
    ab_grid_cache_d = {
        4: (W_misfit_RMS, 2, 1, 0.05, [3, 4], 18),
        5: (W_misfit_RMS, 2, 1, 0.05, [5], 18),
    }

    result = FlightModel.render_ab_dives_plot(
        _base_opts(engine),
        dive_nums,
        flight_dive_data_d,
        ab_grid_cache_d,
        hd_a_grid,
        hd_b_grid,
        "SG500 Test Mission",
        "14 Jul 2026 00:00:00",
    )
    if engine == "plotly":
        _assert_plotly_result(result, expected_trace_name="a*10")
    else:
        _assert_matplotlib_result(result)
