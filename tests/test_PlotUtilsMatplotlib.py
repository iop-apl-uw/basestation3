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

import types

import matplotlib.axes
import matplotlib.collections
import matplotlib.colors
import matplotlib.figure
import numpy as np
import plotly.graph_objects as go
import pytest
from matplotlib.backends.backend_agg import FigureCanvasAgg

import PlotUtilsMatplotlib


def _new_axes() -> matplotlib.axes.Axes:
    """Builds a bare matplotlib Axes for exercising one renderer function in isolation."""
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    return fig.add_subplot()


# ---------------------------------------------------------------------------
# Pure helper functions
# ---------------------------------------------------------------------------


def test_as_float_array_plain_list() -> None:
    arr = PlotUtilsMatplotlib._as_float_array([1, 2, 3])
    assert arr.dtype == np.float64
    np.testing.assert_array_equal(arr, [1.0, 2.0, 3.0])


def test_as_float_array_masked_entries_become_nan() -> None:
    """A masked array (as Plotly sometimes hands back for gappy data) must
    turn into NaN, not whatever the mask's underlying fill value happens to
    be - matplotlib draws a NaN as a gap, which is the correct rendering."""
    masked = np.ma.array([1.0, 2.0, 3.0], mask=[False, True, False])
    arr = PlotUtilsMatplotlib._as_float_array(masked)
    assert not np.ma.is_masked(arr)
    assert np.isnan(arr[1])
    np.testing.assert_array_equal(arr[[0, 2]], [1.0, 3.0])


def test_align_lengths_trims_to_shortest() -> None:
    x = np.array([1.0, 2.0, 3.0, 4.0])
    y = np.array([10.0, 20.0, 30.0])
    x_trimmed, y_trimmed = PlotUtilsMatplotlib._align_lengths(x, y)
    assert x_trimmed.shape[0] == 3
    assert y_trimmed.shape[0] == 3
    np.testing.assert_array_equal(x_trimmed, [1.0, 2.0, 3.0])


def test_align_lengths_three_arrays() -> None:
    a = np.arange(5.0)
    b = np.arange(5.0)
    c = np.arange(3.0)
    out = PlotUtilsMatplotlib._align_lengths(a, b, c)
    assert all(arr.shape[0] == 3 for arr in out)


def test_align_grid_trims_x_y_z_to_shared_shape() -> None:
    """Mirrors the same off-by-one quirk _align_lengths handles for 1D data,
    but for a 2D z grid (e.g. MissionProfiles.py's section plots)."""
    x = np.arange(5.0)
    y = np.arange(4.0)
    z = np.zeros((3, 6))
    x_trimmed, y_trimmed, z_trimmed = PlotUtilsMatplotlib._align_grid(x, y, z)
    assert x_trimmed.shape[0] == 5  # min(5, z.shape[1]=6) -> 5
    assert y_trimmed.shape[0] == 3  # min(4, z.shape[0]=3) -> 3
    assert z_trimmed.shape == (3, 5)


def test_to_mpl_color_named() -> None:
    assert PlotUtilsMatplotlib._to_mpl_color("black") == "black"


def test_to_mpl_color_hex() -> None:
    assert PlotUtilsMatplotlib._to_mpl_color("#1f77b4") == "#1f77b4"


def test_to_mpl_color_rgba_string() -> None:
    color = PlotUtilsMatplotlib._to_mpl_color("rgba(31,119,180,0.5)")
    assert color == pytest.approx((31 / 255, 119 / 255, 180 / 255, 0.5))


def test_to_mpl_color_rgb_string_defaults_alpha_to_one() -> None:
    color = PlotUtilsMatplotlib._to_mpl_color("rgba(255,0,0)")
    assert color == pytest.approx((1.0, 0.0, 0.0, 1.0))


def test_to_mpl_color_none_returns_none() -> None:
    assert PlotUtilsMatplotlib._to_mpl_color(None) is None


def test_to_mpl_color_non_string_returns_none() -> None:
    # A per-point color array reaching here (rather than the marker-
    # colorscale path that actually handles arrays) isn't a real call this
    # converter itself makes - only exercising _to_mpl_color()'s own
    # isinstance(value, str) defensive check, which is stricter than its
    # `str | None` signature declares.
    assert PlotUtilsMatplotlib._to_mpl_color(["red", "blue"]) is None  # ty: ignore[invalid-argument-type]


def test_to_mpl_color_unrecognized_string_returns_none() -> None:
    assert PlotUtilsMatplotlib._to_mpl_color("not-a-real-color") is None


def test_to_mpl_cmap_known_name() -> None:
    assert PlotUtilsMatplotlib._to_mpl_cmap("viridis") == "viridis"


def test_to_mpl_cmap_unknown_name_falls_back_to_viridis() -> None:
    assert PlotUtilsMatplotlib._to_mpl_cmap("NotARealColorscale") == "viridis"


def test_to_mpl_cmap_resolved_stops_list() -> None:
    """The common case: Plotly resolves a colorscale *name* to a stop list
    the moment it's assigned to a trace, so this converter needs to handle
    the resolved-stops form directly, not just a bare name."""
    trace = go.Scatter(marker=dict(color=[1, 2, 3], colorscale="Viridis"))
    cmap = PlotUtilsMatplotlib._to_mpl_cmap(trace.marker.colorscale)
    assert isinstance(cmap, matplotlib.colors.LinearSegmentedColormap)


def test_to_mpl_cmap_empty_falls_back_to_viridis() -> None:
    assert PlotUtilsMatplotlib._to_mpl_cmap(()) == "viridis"


@pytest.mark.parametrize(
    "dash,expected",
    [
        (None, "-"),
        ("solid", "-"),
        ("dot", ":"),
        ("dash", "--"),
        ("dashdot", "-."),
        ("longdashdot", "-."),
    ],
)
def test_line_style_maps_dash_variants(dash, expected) -> None:
    line = go.scatter.Line(dash=dash) if dash is not None else None
    assert PlotUtilsMatplotlib._line_style(line) == expected


def test_line_style_unrecognized_dash_defaults_to_solid() -> None:
    """`_line_style()` is typed `Any` and only ever reads `.dash` off
    whatever it's handed - a real Plotly Line validates its own `dash`
    enum, so this stand-in (not a real go.scatter.Line) is what actually
    exercises the fallback branch."""
    line = types.SimpleNamespace(dash="some-unrecognized-dash-value")
    assert PlotUtilsMatplotlib._line_style(line) == "-"


def test_scaled_linewidth_pt_scales_proportionally() -> None:
    narrow = PlotUtilsMatplotlib._scaled_linewidth_pt(1.0)
    wide = PlotUtilsMatplotlib._scaled_linewidth_pt(10.0)
    assert wide > narrow


def test_scaled_linewidth_pt_floors_at_minimum() -> None:
    assert (
        PlotUtilsMatplotlib._scaled_linewidth_pt(0.0001)
        == PlotUtilsMatplotlib._MIN_LINEWIDTH_PT
    )


def test_scaled_linewidth_pt_uses_default_when_unset() -> None:
    assert PlotUtilsMatplotlib._scaled_linewidth_pt(
        None
    ) == PlotUtilsMatplotlib._scaled_linewidth_pt(
        PlotUtilsMatplotlib._DEFAULT_LINE_WIDTH_PX
    )


def test_clean_title_text_strips_html_tags() -> None:
    assert (
        PlotUtilsMatplotlib._clean_title_text("<b>Salinity</b><br>Dive 5")
        == "Salinity Dive 5"
    )


def test_clean_title_text_truncates_long_text() -> None:
    long_title = "x" * 80
    cleaned = PlotUtilsMatplotlib._clean_title_text(long_title)
    assert cleaned is not None
    assert len(cleaned) == PlotUtilsMatplotlib._TITLE_MAX_CHARS
    assert cleaned.endswith("…")


def test_clean_title_text_none_for_falsy() -> None:
    assert PlotUtilsMatplotlib._clean_title_text(None) is None
    assert PlotUtilsMatplotlib._clean_title_text("") is None
    assert PlotUtilsMatplotlib._clean_title_text("<br>") is None


def test_resolve_bgcolors_explicit_layout_colors() -> None:
    fig = go.Figure()
    fig.update_layout(paper_bgcolor="black", plot_bgcolor="red")
    paper, plot = PlotUtilsMatplotlib._resolve_bgcolors(fig.layout)
    assert paper == "black"
    assert plot == "red"


def test_resolve_bgcolors_falls_back_to_template_defaults() -> None:
    """A figure that never sets paper_bgcolor/plot_bgcolor reads those back
    as None - only fig.layout.template carries the resolved default."""
    fig = go.Figure()
    paper, plot = PlotUtilsMatplotlib._resolve_bgcolors(fig.layout)
    assert paper == PlotUtilsMatplotlib._DEFAULT_PAPER_BGCOLOR
    assert plot == PlotUtilsMatplotlib._DEFAULT_PLOT_BGCOLOR


def test_resolve_color_range_from_trace_own_colorscale() -> None:
    trace = go.Heatmap(z=[[1, 2], [3, 4]], zmin=0, zmax=10)
    cmap, vmin, vmax = PlotUtilsMatplotlib._resolve_color_range(trace, go.Layout())
    assert vmin == 0
    assert vmax == 10


def test_resolve_color_range_from_shared_coloraxis() -> None:
    """adcp/MissionOcean.py's two heatmap traces share one colorbar via
    layout.coloraxis rather than each carrying its own colorscale/zmin/zmax."""
    layout = go.Layout(coloraxis=dict(colorscale="Cividis", cmin=1, cmax=9))
    trace = go.Heatmap(z=[[1, 2], [3, 4]], coloraxis="coloraxis")
    _cmap, vmin, vmax = PlotUtilsMatplotlib._resolve_color_range(trace, layout)
    assert vmin == 1
    assert vmax == 9


# ---------------------------------------------------------------------------
# _render_markers / _render_scatter
# ---------------------------------------------------------------------------


def test_render_markers_scalar_color() -> None:
    ax = _new_axes()
    marker = go.scatter.Marker(color="red")
    PlotUtilsMatplotlib._render_markers(
        ax, np.array([1.0, 2.0]), np.array([3.0, 4.0]), marker, fallback_color=None
    )
    assert len(ax.collections) == 1


def test_render_markers_numeric_colorscale_array() -> None:
    ax = _new_axes()
    marker = go.scatter.Marker(color=[1.0, 2.0, 3.0], colorscale="Viridis")
    PlotUtilsMatplotlib._render_markers(
        ax,
        np.array([1.0, 2.0, 3.0]),
        np.array([1.0, 2.0, 3.0]),
        marker,
        fallback_color=None,
    )
    assert len(ax.collections) == 1
    assert ax.collections[0].get_array() is not None


def test_render_markers_non_numeric_color_array_falls_back() -> None:
    """Defense in depth: a non-numeric marker.color array (not currently
    produced by any registered plot) must fall back to a flat color instead
    of crashing on _to_mpl_color()'s ambiguous-array-truth-value check."""
    ax = _new_axes()
    marker = go.scatter.Marker(color=["red", "blue"])
    PlotUtilsMatplotlib._render_markers(
        ax, np.array([1.0, 2.0]), np.array([1.0, 2.0]), marker, fallback_color="green"
    )
    assert len(ax.collections) == 1


def _last_collection_size(ax: matplotlib.axes.Axes) -> float:
    """Reads the rendered marker area off the most recently added collection.

    ax.scatter() always returns a PathCollection (which declares
    get_sizes()), but matplotlib's own stubs only type ax.collections as the
    more general Collection base class - this narrows it back for ty.
    """
    collection = ax.collections[-1]
    assert isinstance(collection, matplotlib.collections.PathCollection)
    return collection.get_sizes()[0]


def test_render_markers_sparse_vs_dense_area() -> None:
    """Marker size is a fixed constant chosen by point-count bucket, not
    scaled from the trace's own declared marker.size - confirmed here by
    checking the actual rendered size crosses the density threshold."""
    ax = _new_axes()
    marker = go.scatter.Marker(color="red")

    sparse_x = np.arange(10.0)
    PlotUtilsMatplotlib._render_markers(
        ax, sparse_x, sparse_x, marker, fallback_color=None
    )
    sparse_size = _last_collection_size(ax)

    dense_x = np.arange(
        PlotUtilsMatplotlib._DENSE_TRACE_POINT_THRESHOLD + 1, dtype=float
    )
    PlotUtilsMatplotlib._render_markers(
        ax, dense_x, dense_x, marker, fallback_color=None
    )
    dense_size = _last_collection_size(ax)

    assert sparse_size == PlotUtilsMatplotlib._MARKER_AREA_SPARSE_PT2
    assert dense_size == PlotUtilsMatplotlib._MARKER_AREA_DENSE_PT2
    assert dense_size < sparse_size


def test_render_scatter_lines_mode_draws_line() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=[1, 2, 3], y=[4, 5, 6], mode="lines")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 1
    assert len(ax.collections) == 0


def test_render_scatter_markers_mode_draws_markers() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=[1, 2, 3], y=[4, 5, 6], mode="markers")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 0
    assert len(ax.collections) == 1


def test_render_scatter_lines_and_markers_mode_draws_both() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=[1, 2, 3], y=[4, 5, 6], mode="lines+markers")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 1
    assert len(ax.collections) == 1


def test_render_scatter_fill_toself_draws_patch() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=[0, 1, 1, 0], y=[0, 0, 1, 1], fill="toself")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.patches) == 1
    assert len(ax.lines) == 0


def test_render_scatter_empty_trace_is_noop() -> None:
    """MissionMotors.py's VBD-efficiency scatter, when a mission/dive has no
    pump data: x/y are both zero-length. Must be a plain no-op, not a crash -
    see _render_markers' empty-color-array defense-in-depth comment."""
    ax = _new_axes()
    trace = go.Scatter(x=[], y=[], mode="markers")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 0
    assert len(ax.collections) == 0


def test_render_scatter_none_x_is_noop() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=None, y=[1, 2, 3])
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 0


def test_render_scatter_mismatched_lengths_trimmed() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=[1, 2, 3, 4, 5], y=[1, 2, 3, 4], mode="lines")
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    (line,) = ax.lines
    assert np.asarray(line.get_xdata()).shape[0] == 4


def test_render_scatter_non_numeric_x_all_nan_y_is_noop() -> None:
    """DivePMAR.py's epoch_time_trace: a non-numeric (ISO datetime string)
    x-axis, but the trace is deliberately hidden via an all-NaN y - so
    skipping it has no visual effect, and isn't the NotImplementedError
    case below."""
    ax = _new_axes()
    trace = go.Scatter(x=["2026-01-01", "2026-01-02"], y=[float("nan"), float("nan")])
    PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())
    assert len(ax.lines) == 0
    assert len(ax.collections) == 0


def test_render_scatter_non_numeric_x_real_y_raises_not_implemented() -> None:
    ax = _new_axes()
    trace = go.Scatter(x=["2026-01-01", "2026-01-02"], y=[1.0, 2.0])
    with pytest.raises(NotImplementedError):
        PlotUtilsMatplotlib._render_scatter(ax, trace, go.Layout())


# ---------------------------------------------------------------------------
# _render_heatmap / _render_contour / _render_cone
# ---------------------------------------------------------------------------


def test_render_heatmap_basic() -> None:
    ax = _new_axes()
    trace = go.Heatmap(z=[[1, 2], [3, 4]], x=[0, 1], y=[0, 1])
    PlotUtilsMatplotlib._render_heatmap(ax, trace, go.Layout())
    assert len(ax.collections) == 1


def test_render_heatmap_without_xy_uses_z_shape() -> None:
    ax = _new_axes()
    trace = go.Heatmap(z=[[1, 2], [3, 4]])
    PlotUtilsMatplotlib._render_heatmap(ax, trace, go.Layout())
    assert len(ax.collections) == 1


def test_render_heatmap_shared_coloraxis() -> None:
    ax = _new_axes()
    layout = go.Layout(coloraxis=dict(colorscale="Cividis", cmin=0, cmax=10))
    trace = go.Heatmap(z=[[1, 2], [3, 4]], coloraxis="coloraxis")
    PlotUtilsMatplotlib._render_heatmap(ax, trace, layout)
    mesh = ax.collections[0]
    assert mesh.get_clim() == (0, 10)


def test_render_contour_unfilled_draws_lines() -> None:
    ax = _new_axes()
    trace = go.Contour(z=[[0, 1, 2], [1, 2, 3], [2, 3, 4]])
    PlotUtilsMatplotlib._render_contour(ax, trace, go.Layout())
    assert len(ax.collections) >= 1


def test_render_contour_filled_draws_contourf() -> None:
    ax = _new_axes()
    trace = go.Contour(
        z=[[0, 1, 2], [1, 2, 3], [2, 3, 4]], contours=dict(coloring="heatmap")
    )
    PlotUtilsMatplotlib._render_contour(ax, trace, go.Layout())
    assert len(ax.collections) >= 1


def test_render_cone_draws_quiver_and_inverts_depth_axis() -> None:
    ax = _new_axes()
    trace = go.Cone(x=[0, 1], y=[0, 1], z=[0.0, 10.0], u=[1, 1], v=[0, 1], w=[0, 0])
    PlotUtilsMatplotlib._render_cone(ax, trace, go.Layout())
    assert len(ax.collections) == 1
    assert ax.yaxis_inverted()


# ---------------------------------------------------------------------------
# _AxesResolver
# ---------------------------------------------------------------------------


def _new_resolver(layout: go.Layout) -> PlotUtilsMatplotlib._AxesResolver:
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    return PlotUtilsMatplotlib._AxesResolver(fig, layout, plot_bgcolor="white")


def test_axes_resolver_single_panel_full_domain() -> None:
    resolver = _new_resolver(go.Layout())
    ax = resolver.get("x", "y")
    left, bottom, width, height = ax.get_position().bounds
    assert width > 0
    assert height > 0
    # Same (x, y) pair returns the same Axes on a second call.
    assert resolver.get("x", "y") is ax


def test_axes_resolver_secondary_y_uses_twinx() -> None:
    layout = go.Layout(yaxis2=dict(overlaying="y"))
    resolver = _new_resolver(layout)
    primary = resolver.get("x", "y")
    secondary = resolver.get("x", "y2")
    assert secondary is not primary
    # twinx() shares the same x-position/width as the primary Axes.
    assert secondary.get_position().bounds[0] == primary.get_position().bounds[0]


def test_axes_resolver_secondary_x_uses_twiny() -> None:
    layout = go.Layout(xaxis3=dict(overlaying="x"))
    resolver = _new_resolver(layout)
    primary = resolver.get("x", "y")
    secondary = resolver.get("x3", "y")
    assert secondary is not primary


def test_axes_resolver_full_secondary_pair_uses_fresh_axes() -> None:
    """Neither twinx() nor twiny() fits a *both*-directions overlay
    (DiveCTD.py's temperature-on-depth overlay on a salinity/depth
    primary) - needs a fresh, identically-positioned, transparent Axes."""
    layout = go.Layout(xaxis2=dict(overlaying="x"), yaxis2=dict(overlaying="y"))
    resolver = _new_resolver(layout)
    primary = resolver.get("x", "y")
    secondary = resolver.get("x2", "y2")
    assert secondary is not primary
    assert secondary.get_position().bounds == primary.get_position().bounds
    assert secondary.patch.get_visible() is False


def test_axes_resolver_reuses_axes_for_matching_domain_under_different_ids() -> None:
    """Two different (xaxis_id, yaxis_id) pairs that resolve to the same
    (unset, full [0, 1]) domain must share one Axes, not each get their own -
    the domain-keyed cache, not just the id-keyed one."""
    resolver = _new_resolver(go.Layout())
    primary = resolver.get("x", "y")
    other = resolver.get("x5", "y5")
    assert other is primary


def test_axes_resolver_axis_id_with_no_layout_entry_still_gets_axes() -> None:
    """A trace can reference a numbered axis (e.g. "x2") that the figure's
    layout never explicitly configured at all - relying on Plotly's own
    implicit default subplot creation. _apply_range_and_label() must treat
    a missing layout.xaxis2/etc. object as "nothing to apply", not raise."""
    resolver = _new_resolver(go.Layout())
    ax = resolver.get("x9", "y9")
    assert ax is not None
    assert ax.get_xlabel() == ""


def test_axes_resolver_subplot_grid_separate_domains() -> None:
    layout = go.Layout(xaxis=dict(domain=[0.0, 0.45]), xaxis2=dict(domain=[0.55, 1.0]))
    resolver = _new_resolver(layout)
    left_ax = resolver.get("x", "y")
    right_ax = resolver.get("x2", "y")
    assert left_ax is not right_ax
    assert left_ax.get_position().bounds[0] < right_ax.get_position().bounds[0]


def test_axes_resolver_log_axis_range_converted_from_log10() -> None:
    """Plotly expresses a log-axis's range in log10 space - DivePMAR.py's
    spectra plot "shifted high" bug this fixes."""
    layout = go.Layout(yaxis=dict(type="log", range=[-2, 2]))
    resolver = _new_resolver(layout)
    ax = resolver.get("x", "y")
    assert ax.get_yscale() == "log"
    lo, hi = ax.get_ylim()
    assert lo == pytest.approx(10.0**-2)
    assert hi == pytest.approx(10.0**2)


def test_axes_resolver_reversed_autorange_inverts() -> None:
    layout = go.Layout(yaxis=dict(autorange="reversed"))
    resolver = _new_resolver(layout)
    ax = resolver.get("x", "y")
    assert ax.yaxis_inverted()


def test_axes_resolver_partial_range_deferred_until_apply_pending_ranges() -> None:
    """A one-sided range (e.g. ctd_sampling/plotting.py's range=[0, None])
    must not lock the Axes to matplotlib's default (0, 1) view before real
    data is drawn - confirmed by drawing real data, then applying the
    pending range, and checking the free bound reflects the data, not (0, 1)."""
    layout = go.Layout(xaxis=dict(range=[0, None]))
    resolver = _new_resolver(layout)
    ax = resolver.get("x", "y")
    ax.plot([0, 50, 100], [1, 2, 3])
    ax.relim()
    ax.autoscale_view()

    resolver.apply_pending_ranges()

    lo, hi = ax.get_xlim()
    assert lo == 0
    assert hi > 1.0  # not left locked at matplotlib's default (0, 1) view


def test_axes_resolver_showgrid_false_suppresses_grid() -> None:
    layout = go.Layout(xaxis=dict(showgrid=False))
    resolver = _new_resolver(layout)
    ax = resolver.get("x", "y")
    assert not any(line.get_visible() for line in ax.xaxis.get_gridlines())


def test_axes_resolver_hidden_axis_suppresses_label() -> None:
    """DiveCTD.py's xaxis3/4/5: hidden but its range must still apply so
    traces plotted against it land correctly - only the label is dropped."""
    layout = go.Layout(xaxis3=dict(overlaying="x", visible=False, title="Hidden"))
    resolver = _new_resolver(layout)
    ax = resolver.get("x3", "y")
    assert ax.get_xlabel() == ""


def test_axes_resolver_visible_axis_sets_label() -> None:
    layout = go.Layout(xaxis=dict(title=dict(text="Depth (m)")))
    resolver = _new_resolver(layout)
    ax = resolver.get("x", "y")
    assert ax.get_xlabel() == "Depth (m)"


# ---------------------------------------------------------------------------
# _render_shapes
# ---------------------------------------------------------------------------


def test_render_shapes_line_shape_drawn() -> None:
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    resolver = PlotUtilsMatplotlib._AxesResolver(fig, go.Layout(), plot_bgcolor="white")
    layout = go.Layout(
        shapes=[
            dict(type="line", x0=0, x1=1, y0=0, y1=1, xref="x", yref="y"),
        ]
    )
    PlotUtilsMatplotlib._render_shapes(resolver, layout)
    ax = resolver.get("x", "y")
    assert len(ax.lines) == 1


def test_render_shapes_no_shapes_is_noop() -> None:
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    resolver = PlotUtilsMatplotlib._AxesResolver(fig, go.Layout(), plot_bgcolor="white")
    PlotUtilsMatplotlib._render_shapes(resolver, go.Layout(shapes=[]))
    assert fig.axes == []


def test_render_shapes_unsupported_type_raises() -> None:
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    resolver = PlotUtilsMatplotlib._AxesResolver(fig, go.Layout(), plot_bgcolor="white")
    layout = go.Layout(shapes=[dict(type="rect", x0=0, x1=1, y0=0, y1=1)])
    with pytest.raises(NotImplementedError):
        PlotUtilsMatplotlib._render_shapes(resolver, layout)


def test_render_shapes_paper_relative_raises() -> None:
    fig = matplotlib.figure.Figure()
    FigureCanvasAgg(fig)
    resolver = PlotUtilsMatplotlib._AxesResolver(fig, go.Layout(), plot_bgcolor="white")
    layout = go.Layout(
        shapes=[dict(type="line", x0=0, x1=1, y0=0, y1=1, xref="paper", yref="y")]
    )
    with pytest.raises(NotImplementedError):
        PlotUtilsMatplotlib._render_shapes(resolver, layout)


# ---------------------------------------------------------------------------
# render_thumbnail (end-to-end)
# ---------------------------------------------------------------------------


class _NoKaleidoFigure(go.Figure):
    """A real plotly Figure whose write_image() raises if ever called -
    proves render_thumbnail() structurally never reaches for kaleido/Chrome,
    per the plan's "no fallback" requirement, rather than merely happening
    not to call it in today's implementation."""

    def write_image(self, *args, **kwargs):
        raise AssertionError(
            "render_thumbnail() must never call fig.write_image() (kaleido)"
        )


def test_render_thumbnail_never_touches_write_image(tmp_path) -> None:
    fig = _NoKaleidoFigure(data=[go.Scatter(x=[1, 2, 3], y=[4, 5, 6])])
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_basic_scatter_writes_correct_size(tmp_path) -> None:
    import PIL.Image

    fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[4, 5, 6], mode="lines+markers")])
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path, width=185, height=185)

    assert output_path.exists()
    with PIL.Image.open(output_path) as image:
        assert image.size == (185, 185)


def test_render_thumbnail_custom_dimensions(tmp_path) -> None:
    import PIL.Image

    fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[4, 5, 6])])
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path, width=64, height=48)

    with PIL.Image.open(output_path) as image:
        assert image.size == (64, 48)


def test_render_thumbnail_hides_legendonly_and_invisible_traces(tmp_path) -> None:
    """A trace-visibility toggle button (e.g. DiveCTDCorrections.py) just
    renders whichever traces are visible/legendonly at figure-build time -
    no special-casing of the button UI itself."""
    fig = go.Figure(
        data=[
            go.Scatter(x=[1, 2], y=[1, 2], visible=True),
            go.Scatter(x=[1, 2], y=[3, 4], visible="legendonly"),
            go.Scatter(x=[1, 2], y=[5, 6], visible=False),
        ]
    )
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_unsupported_trace_type_raises(tmp_path) -> None:
    fig = go.Figure(data=[go.Bar(x=[1, 2, 3], y=[4, 5, 6])])
    with pytest.raises(NotImplementedError):
        PlotUtilsMatplotlib.render_thumbnail(fig, tmp_path / "thumb.webp")


def test_render_thumbnail_with_title_does_not_raise(tmp_path) -> None:
    fig = go.Figure(data=[go.Scatter(x=[1, 2, 3], y=[4, 5, 6])])
    fig.update_layout(title=dict(text="<b>Dive 5</b> CTD"))
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_secondary_y_dual_axis(tmp_path) -> None:
    """MissionMotors.py-style dual-axis plot: two traces on independent
    y-scales sharing one x-axis."""
    fig = go.Figure(
        data=[
            go.Scatter(x=[1, 2, 3], y=[1, 2, 3], yaxis="y"),
            go.Scatter(x=[1, 2, 3], y=[100, 200, 300], yaxis="y2"),
        ]
    )
    fig.update_layout(yaxis2=dict(overlaying="y", side="right"))
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_subplot_grid(tmp_path) -> None:
    fig = go.Figure(
        data=[
            go.Scatter(x=[1, 2, 3], y=[1, 2, 3], xaxis="x", yaxis="y"),
            go.Scatter(x=[1, 2, 3], y=[3, 2, 1], xaxis="x2", yaxis="y2"),
        ]
    )
    fig.update_layout(
        xaxis=dict(domain=[0.0, 0.45]),
        xaxis2=dict(domain=[0.55, 1.0]),
        yaxis2=dict(anchor="x2"),
    )
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_heatmap_with_shared_coloraxis(tmp_path) -> None:
    fig = go.Figure(
        data=[
            go.Heatmap(z=[[1, 2], [3, 4]], x=[0, 1], y=[0, 1], coloraxis="coloraxis"),
        ]
    )
    fig.update_layout(coloraxis=dict(colorscale="Cividis", cmin=0, cmax=5))
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_shapes_rendered(tmp_path) -> None:
    fig = go.Figure(data=[go.Scatter(x=[0, 10], y=[0, 10])])
    fig.add_shape(type="line", x0=0, x1=10, y0=5, y1=5, xref="x", yref="y")
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_cone_quiver_projection(tmp_path) -> None:
    fig = go.Figure(
        data=[
            go.Cone(
                x=[0, 1, 2],
                y=[0, 1, 2],
                z=[0.0, 10.0, 20.0],
                u=[1, 1, 1],
                v=[0, 1, -1],
                w=[0, 0, 0],
            )
        ]
    )
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()


def test_render_thumbnail_fill_toself_band(tmp_path) -> None:
    """The fill="toself" shaded-band overlay pattern shared by PlotUtils.py's
    add_gc_moves/add_sample_range_overlay/add_timeout_overlays helpers."""
    fig = go.Figure(data=[go.Scatter(x=[0, 1, 1, 0], y=[0, 0, 1, 1], fill="toself")])
    output_path = tmp_path / "thumb.webp"
    PlotUtilsMatplotlib.render_thumbnail(fig, output_path)
    assert output_path.exists()
