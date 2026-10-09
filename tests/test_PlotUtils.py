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

"""Tests for PlotUtils.add_sample_range_overlay() with bad depth data.

Production case: sg274's lab-test mission (2026-09) - bench data with no
usable depth made the overlay fail with IndexError (negative max depth ->
empty bin grid) or try to allocate 1.33 TiB (a ~1e12 m depth), taking the
whole Legato plot down with it.
"""

import logging
import types

import netCDF4
import numpy as np
import plotly.graph_objects as go
import pytest

import PlotUtils

N = 20
MAX_DEPTH_I = 10


def _overlay(
    depth_dive: np.ndarray, depth_climb: np.ndarray, caplog, tmp_path
) -> go.Figure:
    depth = np.concatenate((depth_dive, depth_climb))
    time_var = np.arange(float(N))

    def f_depth(t: np.ndarray) -> np.ndarray:
        return depth[t.astype(int)]

    # The science-grid part after the overlay only needs a mission_dir
    base_opts = types.SimpleNamespace(mission_dir=tmp_path, science_grid=None)
    fig = go.Figure()
    with caplog.at_level(logging.WARNING):
        PlotUtils.add_sample_range_overlay(
            base_opts, "legato", 5, time_var, MAX_DEPTH_I, 0.0, fig, f_depth
        )
    return fig


def _names(fig: go.Figure) -> list[str]:
    """The samples/meter overlay traces added."""
    return [t.name for t in fig.data if t.name and t.name.endswith("samples stats")]


def _depth_warnings(caplog) -> list[str]:
    return [
        r.getMessage()
        for r in caplog.records
        if "implausible max depth" in r.getMessage()
    ]


def test_normal_profile_adds_both_traces(caplog, tmp_path) -> None:
    fig = _overlay(
        np.linspace(0, 100, MAX_DEPTH_I),
        np.linspace(100, 0, N - MAX_DEPTH_I),
        caplog,
        tmp_path,
    )
    assert _names(fig) == ["Dive samples stats", "Climb samples stats"]
    assert not _depth_warnings(caplog)


@pytest.mark.parametrize(
    "bad",
    [
        np.full(
            MAX_DEPTH_I, -3.0
        ),  # bench: below the surface reference -> empty bin grid
        np.full(MAX_DEPTH_I, np.nan),  # no usable depth at all
        np.full(MAX_DEPTH_I, 9.2e11),  # garbage depth -> TiB-sized bin grid
    ],
    ids=["negative", "all-nan", "absurd"],
)
def test_implausible_depth_skips_only_that_half(bad, caplog, tmp_path) -> None:
    fig = _overlay(bad, np.linspace(100, 0, N - MAX_DEPTH_I), caplog, tmp_path)
    assert _names(fig) == ["Climb samples stats"]
    warnings = [r for r in caplog.records if "implausible max depth" in r.getMessage()]
    assert len(warnings) == 1
    assert warnings[0].levelname == "WARNING"
    assert "legato dive 5: implausible max depth" in warnings[0].getMessage()
    assert (
        "dive samples - skipping the samples/meter overlay" in warnings[0].getMessage()
    )


def test_implausible_depth_both_halves_adds_nothing(caplog, tmp_path) -> None:
    fig = _overlay(
        np.full(MAX_DEPTH_I, -3.0), np.full(N - MAX_DEPTH_I, np.nan), caplog, tmp_path
    )
    assert _names(fig) == []
    assert len(_depth_warnings(caplog)) == 2


def test_zero_max_depth_is_plotted(caplog, tmp_path) -> None:
    """A surface-only half (max depth exactly 0) is valid, not bad data."""
    fig = _overlay(
        np.zeros(MAX_DEPTH_I), np.linspace(10, 0, N - MAX_DEPTH_I), caplog, tmp_path
    )
    assert _names(fig) == ["Dive samples stats", "Climb samples stats"]
    assert not _depth_warnings(caplog)


# --- Nsquared on a dive cut short (sg263 NANOOS_Aug26 dive 176) ---------------


def _ctd_dive_file(tmp_path, n_good: int, n: int = 200) -> netCDF4.Dataset:
    """A dive file with a down/up CT profile, only the first n_good points valid."""
    f = tmp_path / "p2630176.nc"
    depth = np.concatenate((np.linspace(1.0, 800.0, n // 2), np.linspace(800.0, 1.0, n - n // 2)))
    ct = 15.0 - depth / 100.0
    sa = 34.0 + depth / 1000.0
    ct[n_good:] = np.nan
    sa[n_good:] = np.nan
    with netCDF4.Dataset(str(f), "w") as nc:  # str: netCDF4 wants a path string
        nc.dive_number = 176
        nc.createDimension("ctd_data_point", n)
        for name, values in (("ctd_depth", depth), ("conservative_temperature", ct), ("absolute_salinity", sa)):
            nc.createVariable(name, "f8", ("ctd_data_point",))[:] = values
        nc.createVariable("avg_latitude", "f8", ())[:] = 47.24
    return netCDF4.Dataset(str(f), "r")


def test_nsquared_too_few_good_points(tmp_path, caplog) -> None:
    """2 good CT points of 670 (a humidity-leak abort): one warning and None, not a traceback."""
    ds = _ctd_dive_file(tmp_path, n_good=2)
    try:
        with caplog.at_level(logging.WARNING):
            assert PlotUtils.Nsquared(ds) is None
    finally:
        ds.close()
    assert "Dive 176: too few good CT points for buoyancy frequency (2 of 200) - not computed" in caplog.text
    assert "Traceback" not in caplog.text and "Failed to compute Nsquared" not in caplog.text


def test_nsquared_full_profile(tmp_path) -> None:
    ds = _ctd_dive_file(tmp_path, n_good=200)
    try:
        n2 = PlotUtils.Nsquared(ds)
    finally:
        ds.close()
    assert n2 is not None and n2.shape == (200,)


def test_ctdvars_buoyancy_frequency_defaults_to_none() -> None:
    """plot_CTD reads buoy_f_dive/buoy_f_climb even when Nsquared failed - they were
    declared under other names, so the read raised AttributeError."""
    import Plotting.DiveCTD

    ctd_vars = Plotting.DiveCTD.CTDVars()
    assert ctd_vars.buoy_f_dive is None and ctd_vars.buoy_f_climb is None
