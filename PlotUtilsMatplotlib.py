#! /usr/bin/env python
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

"""Renders small static thumbnail previews of Plotly figures via matplotlib.

Replaces kaleido/headless-Chrome for `PlotUtilsPlotly.write_output_files()`'s
185x185 `.webp` thumbnail path (see
`.claude/plans/2026-08-20-matplotlib-thumbnail-engine.md`) with matplotlib's
Agg backend - pure C, no subprocess, none of kaleido/Chrome's wedge/OOM
failure modes. This is not a general-purpose Plotly-to-matplotlib converter:
it covers only the trace types and layout features (subplot grids,
secondary_y, layout.shapes) this project's registered dive/mission plots
actually use, scoped against a direct inventory documented in the plan
above. An unsupported trace type or shape raises NotImplementedError rather
than silently rendering something misleading or falling back to kaleido.

At thumbnail size, `layout.annotations`, axis tick labels/numbers, and the
legend are dropped entirely - illegible or too visually noisy at 185px
regardless of plot, and not worth the implementation cost of replicating
exactly. A figure title, per-axis labels, and gridlines are kept, in a
small font, as a legibility-permitting *suggestion* of what the full-size
render shows - not a faithful reproduction. The goal is a recognizable preview,
not full visual fidelity with the full-size kaleido render.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal

import matplotlib

matplotlib.use("agg")

import matplotlib.axes
import matplotlib.colors
import matplotlib.figure
import numpy as np
from matplotlib.backends.backend_agg import FigureCanvasAgg

if TYPE_CHECKING:
    import pathlib

    import plotly.graph_objects

# Deliberately not read from PlotUtilsPlotly.thumbnail_width/thumbnail_height:
# PlotUtilsPlotly.py imports this module to reach render_thumbnail(), so
# importing back from it here would be circular. Callers pass the real
# values explicitly; these are just this function's own defaults.
_DEFAULT_THUMBNAIL_WIDTH = 185
_DEFAULT_THUMBNAIL_HEIGHT = 185
_DEFAULT_DPI = 100

# Line widths/marker sizes on a Plotly trace are CSS pixels sized for
# kaleido's full std_width=1058px render (PlotUtilsPlotly.py) - reused
# as-is at thumbnail size looked cartoonishly oversized (each pixel is a
# much bigger fraction of a 185px canvas). This scales a trace's own
# declared width proportionally down to thumbnail size, then converts
# pixels to matplotlib's point units at _DEFAULT_DPI, rather than
# dropping per-trace width variation (e.g. a bold "primary" line vs a
# thin reference line) entirely.
_REFERENCE_FULL_WIDTH_PX = 1058.0
_SIZE_SCALE = _DEFAULT_THUMBNAIL_WIDTH / _REFERENCE_FULL_WIDTH_PX
_PX_TO_PT = 72.0 / _DEFAULT_DPI
_MIN_LINEWIDTH_PT = 0.2
_DEFAULT_LINE_WIDTH_PX = 2.0  # Plotly's own per-trace line.width default
_DEFAULT_GRID_WIDTH_PX = 1.0  # Plotly's own per-axis gridwidth default

# Fixed per density bucket, not scaled from the trace's own declared
# marker.size - the same "recognizable preview, not fidelity"
# simplification already applied to legends/annotations/tick labels, per
# the user's direction. _MARKER_AREA_SPARSE_PT2 calibrated by direct
# visual comparison against plots_kaleido_baseline/ (DivePitchRoll.py-
# style sparse marker traces, confirmed via real vis.py screenshots) -
# DivePitchRoll.py declares no explicit marker.size (Plotly's own
# default, 6px), which is what the earlier proportional-scaling
# approach's "good" state was actually rendering at (~0.57 area).
# A single constant undershoots on a *dense* marker-only trace though
# (e.g. Plotting/DiveCTD.py's plot_CTD, ~540 points along a curve
# spanning far fewer raster pixels than that in a 185px thumbnail - the
# points overlap regardless of individual marker size, so a size that
# looks right for ~20 sparse points compounds through overlap into a
# visibly "fatter" band on ~540 dense ones): _MARKER_AREA_DENSE_PT2 is
# smaller. Circle marker, not square: a square has a hard rendering
# cutoff around area 0.75 (see _render_markers()'s docstring) where a
# circle just fades - measured empirically that a circle's rendered
# footprint stops shrinking meaningfully below area ~0.001 (antialiasing
# floor, ~5-6px regardless of nominal area), but a direct side-by-side
# comparison against plots_kaleido_baseline/dv0781_ctd.webp preferred
# 0.05 over 0.001 - smaller isn't automatically better past a point,
# this value is a real visual judgment call, not just "as small as
# rendering allows."

_DENSE_TRACE_POINT_THRESHOLD = 100
_MARKER_AREA_SPARSE_PT2 = 0.57
_MARKER_AREA_DENSE_PT2 = 0.05

# Plotly's built-in default template (confirmed empirically via
# go.Figure().layout.template - not set explicitly anywhere in this
# codebase, so every registered plot renders against these defaults).
# fig.layout.paper_bgcolor/plot_bgcolor read directly off an unmodified
# figure are None (only the *template*, not the layout, carries the
# resolved default) - see _resolve_bgcolors().
_DEFAULT_PAPER_BGCOLOR = "white"
_DEFAULT_PLOT_BGCOLOR = "#E5ECF6"

_TITLE_FONTSIZE = 5.0
_AXIS_LABEL_FONTSIZE = 4.0
_TITLE_MAX_CHARS = 40

# Leaves room around each Axes' Plotly-domain rectangle for the title/axis
# labels below, which the domain fractions alone (often the full [0, 1]
# span) don't reserve any space for. The right margin is wider than a
# single-axis plot strictly needs so a secondary_y twin Axes' own y-label
# (e.g. MissionMotors.py's dual-axis current/rate plots) has room to
# render without clipping off the canvas edge.
_FIGURE_MARGIN_LEFT = 0.16
_FIGURE_MARGIN_RIGHT = 0.14
_FIGURE_MARGIN_BOTTOM = 0.14
_FIGURE_MARGIN_TOP = 0.12

_DASH_STYLES: dict[str, str] = {
    "solid": "-",
    "dot": ":",
    "dash": "--",
    "longdash": "--",
    "dashdot": "-.",
    "longdashdot": "-.",
}

_RGBA_PATTERN = re.compile(
    r"rgba?\(\s*([\d.]+)\s*,\s*([\d.]+)\s*,\s*([\d.]+)\s*(?:,\s*([\d.]+)\s*)?\)"
)

_HTML_TAG_PATTERN = re.compile(r"<[^>]+>")

type _MplColor = str | tuple[float, float, float, float]


def _as_float_array(values: object) -> np.ndarray:
    """Converts a Plotly trace's x/y/shape-coordinate values to a plain float array.

    Args:
        values: A sequence (list, numpy array, or numpy masked array, as
            found on Plotly trace attributes) of coordinate values.

    Returns:
        A plain (non-masked) float64 numpy array, with any masked entries
        replaced by NaN so matplotlib draws them as gaps rather than
        whatever the mask's underlying fill value happened to be.
    """
    arr = np.ma.asarray(values)
    if np.ma.is_masked(arr):
        return np.ma.filled(arr.astype(float), np.nan)
    return np.asarray(values, dtype=float)


def _align_lengths(*arrays: np.ndarray) -> tuple[np.ndarray, ...]:
    """Trims same-role arrays (e.g. x/y, or x/y/marker-color) to their shared minimum length.

    A defensive measure, not a workaround for anything this converter gets
    wrong: real registered plots build slightly length-mismatched arrays
    (e.g. `MakePlotTSProfile.py`'s `depth = np.arange(start, stop, step)`,
    which isn't guaranteed to come out exactly `len(temperature)` due to
    float rounding). Plotly/kaleido tolerates this silently; matplotlib's
    stricter `ax.plot()`/`ax.scatter()` raise on any length mismatch. This
    matches kaleido's real tolerance rather than crashing (and producing no
    thumbnail at all) over a pre-existing, otherwise-harmless data quirk
    upstream of this converter.

    Args:
        *arrays: Arrays that are meant to be the same length.

    Returns:
        The same arrays, each trimmed from the end to the shortest input's
        length.
    """
    min_len = min(arr.shape[0] for arr in arrays)
    return tuple(arr[:min_len] for arr in arrays)


def _align_grid(
    x: np.ndarray, y: np.ndarray, z: np.ndarray
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Trims a Heatmap/Contour trace's x/y coordinate arrays and z grid to consistent shapes.

    The same real-world quirk `_align_lengths()` handles for 1D x/y (e.g.
    `MissionProfiles.py`'s section-plot z grid coming out with 200 rows
    against a 201-element y coordinate array - another off-by-one from
    upstream binning) also shows up in 2D gridded data. Plotly/kaleido
    tolerates it; matplotlib's `pcolormesh()`/`contour()`/`contourf()`
    raise if `len(y) != z.shape[0]` or `len(x) != z.shape[1]`.

    Args:
        x: Column coordinates, meant to satisfy `len(x) == z.shape[1]`.
        y: Row coordinates, meant to satisfy `len(y) == z.shape[0]`.
        z: The 2D data grid.

    Returns:
        `(x, y, z)`, each trimmed on the relevant axis to the shared
        minimum of its own length and z's corresponding dimension.
    """
    ny = min(y.shape[0], z.shape[0])
    nx = min(x.shape[0], z.shape[1])
    return x[:nx], y[:ny], z[:ny, :nx]


def _to_mpl_color(
    value: str | None,
) -> _MplColor | None:
    """Converts a Plotly scalar color (named, hex, or rgba(...) string) to a matplotlib color.

    Args:
        value: A Plotly color string, e.g. "black", "#1f77b4", or
            "rgba(31,119,180,0.5)". None or a non-string (e.g. a per-point
            color array, handled separately by the marker-colorscale path)
            returns None.

    Returns:
        A matplotlib-compatible color (passed through unchanged for a named/
        hex string matplotlib already understands, or converted to an
        (r, g, b, a) tuple in [0, 1] for a Plotly "rgba(...)" string), or
        None if `value` isn't a usable color.
    """
    if not value or not isinstance(value, str):
        return None
    match = _RGBA_PATTERN.match(value.strip())
    if match:
        r, g, b = (float(match.group(i)) / 255.0 for i in (1, 2, 3))
        a = float(match.group(4)) if match.group(4) is not None else 1.0
        return (r, g, b, a)
    if matplotlib.colors.is_color_like(value):
        return value
    return None


def _to_mpl_cmap(colorscale: Any) -> str | matplotlib.colors.Colormap:
    """Converts a Plotly colorscale to a matplotlib colormap.

    Args:
        colorscale: Either a Plotly colorscale name (e.g. "Jet") or the
            resolved sequence of `(fraction, color)` stop tuples Plotly's
            own validators normally store on `marker.colorscale` the
            moment a name is assigned to a trace - a bare name reaching
            here at all is the unusual case, not the common one, so the
            stop-list form is handled directly rather than treated as a
            fallback.

    Returns:
        A matplotlib colormap name (for the name case, tried against
        `matplotlib.colormaps` in a couple of case variants), or a
        `LinearSegmentedColormap` built directly from the stops (for the
        resolved-stops case). Falls back to "viridis" if neither form
        resolves to something usable.
    """
    if isinstance(colorscale, str):
        for candidate in (colorscale, colorscale.lower(), colorscale.capitalize()):
            if candidate in matplotlib.colormaps:
                return candidate
        return "viridis"
    if isinstance(colorscale, (list, tuple)) and colorscale:
        stops = []
        for fraction, color in colorscale:
            mpl_color = _to_mpl_color(color)
            if mpl_color is not None:
                stops.append((float(fraction), mpl_color))
        if stops:
            return matplotlib.colors.LinearSegmentedColormap.from_list(
                "plotly_colorscale", stops
            )
    return "viridis"


def _line_style(line: Any) -> str:
    """Maps a Plotly Line object's `dash` value to a matplotlib linestyle.

    Args:
        line: A Plotly `line` sub-object (e.g. `trace.line`, `shape.line`),
            or None. Typed `Any`: Plotly's graph_objects classes are
            metaprogrammed at import time (per-trace-type attribute sets),
            not amenable to precise static typing.

    Returns:
        A matplotlib linestyle string. Defaults to a solid line ("-") for
        an unset or unrecognized dash value.
    """
    dash: str | None = getattr(line, "dash", None) if line is not None else None
    if dash is None:
        return "-"
    return _DASH_STYLES.get(dash, "-")


def _scaled_linewidth_pt(
    width_px: float | None, default_px: float = _DEFAULT_LINE_WIDTH_PX
) -> float:
    """Converts a Plotly line's declared CSS-pixel width to a thumbnail-proportional matplotlib linewidth.

    Args:
        width_px: The trace/shape/gridline's declared width (CSS pixels,
            as Plotly interprets it at kaleido's full `std_width`-scale
            render), or None if unset.
        default_px: Value to use in place of `width_px` when it's unset -
            Plotly's own default differs by context (a trace `line.width`
            defaults to 2px, a `gridwidth` to 1px), so callers pass the
            one matching what they're scaling.

    Returns:
        A linewidth in matplotlib points, scaled down by the same ratio
        the thumbnail itself is smaller than kaleido's full-size render
        (`_SIZE_SCALE`), floored at `_MIN_LINEWIDTH_PT` so a line stays
        visible rather than vanishing entirely.
    """
    px = width_px if width_px else default_px
    return max(px * _SIZE_SCALE * _PX_TO_PT, _MIN_LINEWIDTH_PT)


def _clean_title_text(text: str | None) -> str | None:
    """Strips Plotly's HTML-like markup from a title/axis-label string and truncates it for thumbnail size.

    Args:
        text: A Plotly title string, which may contain `<br>`/`<b>`/etc.
            tags Plotly's own text renderer supports but matplotlib's
            plain-text title/label APIs don't.

    Returns:
        The text with tags replaced by spaces and whitespace collapsed,
        truncated to `_TITLE_MAX_CHARS` (with a trailing ellipsis) if
        longer - a full multi-line title is well beyond what a 185px
        canvas can show legibly regardless. None if `text` is falsy.
    """
    if not text:
        return None
    cleaned = " ".join(_HTML_TAG_PATTERN.sub(" ", text).split())
    if not cleaned:
        return None
    if len(cleaned) > _TITLE_MAX_CHARS:
        return cleaned[: _TITLE_MAX_CHARS - 1] + "…"
    return cleaned


def _resolve_bgcolors(layout: Any) -> tuple[_MplColor, _MplColor]:
    """Resolves a figure's paper/plot background colors, including Plotly's un-set template default.

    Args:
        layout: The source Plotly figure's `layout` object. Typed `Any` -
            see `_line_style()`.

    Returns:
        A (paper_bgcolor, plot_bgcolor) tuple of matplotlib-compatible
        color strings. Prefers an explicit `layout.paper_bgcolor`/
        `plot_bgcolor` if the figure set one; otherwise resolves Plotly's
        *default template*'s colors (`layout.template` returns a fully
        resolved template even when the figure never explicitly set one -
        confirmed empirically; unlike `layout.paper_bgcolor` itself, which
        reads back as None until explicitly set) rather than assuming
        white, since no plot in this codebase sets a template explicitly
        and Plotly's real default `plot_bgcolor` is a light blue-grey
        (`#E5ECF6`), not white.
    """
    template_layout = getattr(getattr(layout, "template", None), "layout", None)
    paper = (
        layout.paper_bgcolor
        or getattr(template_layout, "paper_bgcolor", None)
        or (_DEFAULT_PAPER_BGCOLOR)
    )
    plot = (
        layout.plot_bgcolor
        or getattr(template_layout, "plot_bgcolor", None)
        or (_DEFAULT_PLOT_BGCOLOR)
    )
    return (
        _to_mpl_color(paper) or _DEFAULT_PAPER_BGCOLOR,
        _to_mpl_color(plot) or _DEFAULT_PLOT_BGCOLOR,
    )


def _render_markers(
    ax: matplotlib.axes.Axes,
    x: np.ndarray,
    y: np.ndarray,
    marker: Any,
    fallback_color: _MplColor | None,
) -> None:
    """Draws a Scatter trace's markers, resolving either a scalar color or a per-point colorscale.

    Args:
        ax: Target matplotlib Axes.
        x: X coordinates.
        y: Y coordinates.
        marker: The trace's `marker` sub-object (never None on a real
            Plotly Scatter trace, though its `.color` may be unset). Typed
            `Any` - see `_line_style()`.
        fallback_color: Color to use if the marker itself specifies none
            (e.g. the trace's line color, for a "lines+markers" trace).

    Returns:
        None.

    Note:
        Marker size is a fixed constant per density bucket
        (`_MARKER_AREA_SPARSE_PT2`/`_MARKER_AREA_DENSE_PT2`, chosen by
        point count), deliberately ignoring the trace's own declared
        `marker.size` - unlike line width, which *is* scaled from the
        trace's own `line.width` (`_scaled_linewidth_pt()`) and confirmed
        to look right that way. Proportional scaling from the declared
        size was tried for markers too, but real-world comparison
        (`plots_kaleido_baseline/`, via actual vis.py screenshots) showed
        a fixed size serves the common (sparse, individually-meaningful
        points, e.g. `DivePitchRoll.py`'s pitch-control markers) case
        better than deriving anything from the declared size - but a
        single fixed size doesn't transfer to a dense marker-only trace
        (e.g. `Plotting/DiveCTD.py`'s `plot_CTD`, ~540 points along a
        curve spanning far fewer raster pixels than that in a 185px
        thumbnail): points overlap regardless of individual marker size
        there, so a size that looks right for ~20 sparse points compounds
        through overlap into a visibly "fatter" band on ~540 dense ones.
        Default circle marker, not a square: confirmed empirically that a
        square marker has a hard rendering cutoff around area 0.75
        (`matplotlib`'s `Agg` backend renders nothing at all below that
        for a square - no antialiasing halo the way a circle's curved
        edge gets), which silently produced *blank* thumbnails at the
        dense bucket's small, intentional size. A circle stays visible
        all the way down.
    """
    marker_area = (
        _MARKER_AREA_DENSE_PT2
        if x.shape[0] > _DENSE_TRACE_POINT_THRESHOLD
        else _MARKER_AREA_SPARSE_PT2
    )
    color = getattr(marker, "color", None) if marker is not None else None
    if isinstance(color, (list, tuple, np.ndarray)):
        color_arr = np.asarray(color)
        if color_arr.dtype.kind in "if":
            cmap = _to_mpl_cmap(getattr(marker, "colorscale", None))
            mx, my, mc = _align_lengths(x, y, color_arr.astype(float))
            ax.scatter(mx, my, c=mc, cmap=cmap, s=marker_area)
            return
        # A non-numeric color array (dtype.kind not in "if") isn't a
        # colorscale this converter supports - e.g. a genuinely empty
        # array (dtype defaults to object with nothing to infer from;
        # ruled out upstream in _render_scatter()'s x.size == 0 check,
        # but kept here too as defense in depth) or literal per-point
        # color-name strings (not currently used by any registered plot,
        # per the trace-type survey this converter was scoped against).
        # Neither belongs in the scalar-color path below - _to_mpl_color()
        # expects a single string, not an array, and would raise on the
        # array's own ambiguous truth value. Fall back to a flat color
        # instead of crashing.
        ax.scatter(x, y, color=fallback_color, s=marker_area)
        return
    scalar_color = _to_mpl_color(color) or fallback_color
    ax.scatter(x, y, color=scalar_color, s=marker_area)


def _render_scatter(ax: matplotlib.axes.Axes, trace: Any, layout: Any) -> None:
    """Draws one Scatter/Scattergl trace's lines/markers/fill onto an Axes.

    Args:
        ax: Target matplotlib Axes (already resolved for this trace's
            xaxis/yaxis pair).
        trace: A Plotly Scatter or Scattergl trace object. Typed `Any` -
            see `_line_style()`.
        layout: Unused - accepted only so every entry in `_TRACE_RENDERERS`
            shares one call signature with the renderers that do need it
            (`_render_heatmap`/`_render_contour`, for shared `coloraxis`
            resolution).

    Returns:
        None.
    """
    if trace.x is None or trace.y is None:
        return
    try:
        x = _as_float_array(trace.x)
    except ValueError, TypeError:
        # A non-numeric x-axis (e.g. Plotting/DivePMAR.py's
        # "epoch_time_trace" - a shadow trace that exists only to
        # register a secondary GMT-time axis scale, x = a list of ISO
        # datetime strings, deliberately hidden via an all-NaN y: "Best
        # solution I found to hide a trace - make it all nans") isn't
        # scoped by this converter in general. But if the trace's own
        # y-data is entirely NaN, it draws nothing regardless of x, so
        # skipping it has no visual effect - not a silently dropped
        # feature, just a no-op on an already-invisible trace. A trace
        # with real y-data on a non-numeric x-axis is a genuine gap,
        # raised loudly per the "no fallback" requirement.
        if np.all(np.isnan(_as_float_array(trace.y))):
            return
        raise NotImplementedError(
            "PlotUtilsMatplotlib: non-numeric x-axis data not supported "
            f"(trace {getattr(trace, 'name', None)!r})"
        ) from None
    x, y = _align_lengths(x, _as_float_array(trace.y))
    if x.size == 0:
        # A trace with no data points at all (e.g. Plotting/MissionMotors.py's
        # "VBD Efficiency" scatter when a mission/dive has no pump data to
        # plot - confirmed empirically: Plotly represents an *empty*
        # marker.color array as dtype=object rather than float, which
        # _render_markers()'s numeric-colorscale check below doesn't
        # recognize, falling through to a scalar-color code path that then
        # raises on an ambiguous empty-array truth value). Nothing to draw
        # regardless of color handling - a plain no-op, not a dropped
        # feature.
        return

    line = trace.line
    line_color = (
        _to_mpl_color(getattr(line, "color", None)) if line is not None else None
    )
    linewidth = _scaled_linewidth_pt(getattr(line, "width", None))

    if trace.fill == "toself":
        ax.fill(x, y, color=line_color or "C0", alpha=0.4, linewidth=0)
        return

    mode = trace.mode or "lines"
    if "lines" in mode:
        ax.plot(
            x, y, color=line_color, linestyle=_line_style(line), linewidth=linewidth
        )
    if "markers" in mode:
        _render_markers(ax, x, y, trace.marker, fallback_color=line_color)


def _resolve_color_range(
    trace: Any, layout: Any
) -> tuple[str | matplotlib.colors.Colormap, float | None, float | None]:
    """Resolves the colormap and value range for a Heatmap/Contour trace.

    Args:
        trace: A Plotly Heatmap or Contour trace object.
        layout: The source Plotly figure's `layout` object - consulted only
            when `trace.coloraxis` is set (Plotly's shared-colorbar feature,
            e.g. `adcp/MissionOcean.py`'s two heatmap traces sharing one
            scale via `layout.coloraxis`).

    Returns:
        A (colormap, vmin, vmax) tuple, resolved from `layout.coloraxis`
        when `trace.coloraxis` references one, else from the trace's own
        `colorscale`/`zmin`/`zmax`. `vmin`/`vmax` of None means "let
        matplotlib auto-scale from the data", matching Plotly's own
        behavior when `zmin`/`zmax`/`cmin`/`cmax` are unset.
    """
    coloraxis_id = getattr(trace, "coloraxis", None)
    if coloraxis_id:
        coloraxis_obj = getattr(layout, coloraxis_id, None)
        cmap = _to_mpl_cmap(getattr(coloraxis_obj, "colorscale", None))
        vmin = getattr(coloraxis_obj, "cmin", None)
        vmax = getattr(coloraxis_obj, "cmax", None)
        return cmap, vmin, vmax
    cmap = _to_mpl_cmap(getattr(trace, "colorscale", None))
    vmin = getattr(trace, "zmin", None)
    vmax = getattr(trace, "zmax", None)
    return cmap, vmin, vmax


def _render_heatmap(ax: matplotlib.axes.Axes, trace: Any, layout: Any) -> None:
    """Draws one Heatmap trace as a matplotlib `pcolormesh`.

    Args:
        ax: Target matplotlib Axes.
        trace: A Plotly Heatmap trace object.
        layout: The source Plotly figure's `layout` object, for shared-
            `coloraxis` resolution (see `_resolve_color_range()`).

    Returns:
        None.
    """
    z = _as_float_array(trace.z)
    cmap, vmin, vmax = _resolve_color_range(trace, layout)
    if trace.x is not None and trace.y is not None:
        x, y, z = _align_grid(_as_float_array(trace.x), _as_float_array(trace.y), z)
        ax.pcolormesh(x, y, z, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")
    else:
        ax.pcolormesh(z, cmap=cmap, vmin=vmin, vmax=vmax, shading="auto")


def _render_contour(ax: matplotlib.axes.Axes, trace: Any, layout: Any) -> None:
    """Draws one Contour trace as a matplotlib `contourf`/`contour`.

    Args:
        ax: Target matplotlib Axes.
        trace: A Plotly Contour trace object.
        layout: The source Plotly figure's `layout` object, for shared-
            `coloraxis` resolution when `contours.coloring == "heatmap"`
            (see `_resolve_color_range()`).

    Returns:
        None.
    """
    z = _as_float_array(trace.z)
    x = _as_float_array(trace.x) if trace.x is not None else np.arange(z.shape[1])
    y = _as_float_array(trace.y) if trace.y is not None else np.arange(z.shape[0])
    x, y, z = _align_grid(x, y, z)

    filled = getattr(getattr(trace, "contours", None), "coloring", None) == "heatmap"
    if filled:
        cmap, vmin, vmax = _resolve_color_range(trace, layout)
        ax.contourf(x, y, z, cmap=cmap, vmin=vmin, vmax=vmax)
    else:
        line = trace.line
        color = (
            _to_mpl_color(getattr(line, "color", None)) if line is not None else None
        )
        linewidth = _scaled_linewidth_pt(getattr(line, "width", None))
        ax.contour(x, y, z, colors=color or "black", linewidths=linewidth)


def _render_cone(ax: matplotlib.axes.Axes, trace: Any, layout: Any) -> None:
    """Draws a 3D `cone` (vector-field) trace as a 2D matplotlib `quiver` depth profile.

    Not a 3D rendering - projects the trace's horizontal velocity
    components (`u`, `v`) onto a 2D stick/feather plot (sample index on
    one axis, depth on the other, inverted so depth increases downward),
    per the plan's confirmed resolution for `adcp/DiveOcean.py`'s
    `plot_ocean_velocity_3d`: "not full 3D fidelity, but a recognizable
    directional preview."

    Args:
        ax: Target matplotlib Axes.
        trace: A Plotly `cone` trace object (`u`/`v`/`w` vector components
            at `x`/`y`/`z` positions; only `u`, `v`, and `z` (depth) are
            used here).
        layout: Unused - accepted only for `_TRACE_RENDERERS` signature
            uniformity, see `_render_scatter()`.

    Returns:
        None.
    """
    depth = _as_float_array(trace.z)
    u = _as_float_array(trace.u)
    v = _as_float_array(trace.v)
    index = np.arange(depth.size, dtype=float)
    ax.quiver(index, depth, u, v, angles="xy")
    ax.invert_yaxis()


_TRACE_RENDERERS: dict[str, Callable[[matplotlib.axes.Axes, Any, Any], None]] = {
    "scatter": _render_scatter,
    "scattergl": _render_scatter,
    "heatmap": _render_heatmap,
    "contour": _render_contour,
    "cone": _render_cone,
}


class _AxesResolver:
    """Maps Plotly (xaxis, yaxis) id pairs to matplotlib Axes, mirroring subplot/overlay-axis layout.

    Plotly figures place traces via short axis-id strings (e.g. "x", "x2",
    "y", "y3") that key into `layout.xaxis`/`xaxis2`/.../`yaxis`/`yaxis2`/...
    objects carrying a `domain` (figure-fraction rectangle) and, for a
    secondary axis, an `overlaying` reference to the primary axis it shares
    a domain with (Plotly's secondary-axis feature - independently
    available per direction, so a secondary axis can overlay just x, just
    y, or both at once; `Plotting/DiveCTD.py`'s `plot_CTD` uses all three
    shapes across its axes). This resolver builds one matplotlib Axes per
    unique domain rectangle (reused across every trace/shape that shares
    it), a `twinx()`/`twiny()` Axes for a single-direction overlay, and a
    fresh, identically-positioned, transparent-background Axes for a
    both-directions overlay (`twinx()`/`twiny()` alone can't represent two
    fully independent scales at once) - rather than ever misplacing an
    overlay trace onto the wrong scale.
    """

    def __init__(
        self, mpl_fig: matplotlib.figure.Figure, layout: Any, plot_bgcolor: _MplColor
    ) -> None:
        """Initializes the resolver against one matplotlib Figure/Plotly layout pair.

        Args:
            mpl_fig: The matplotlib Figure new Axes are added to.
            layout: The source Plotly figure's `layout` object. Typed
                `Any` - see `_line_style()`.
            plot_bgcolor: Background color applied to each newly created
                primary Axes (see `_resolve_bgcolors()`). Not applied to a
                `twinx()` secondary_y Axes, which stays transparent so the
                primary Axes' own background shows through instead of a
                second, redundantly-painted rectangle on top of it.

        Returns:
            None.
        """
        self._mpl_fig = mpl_fig
        self._layout = layout
        self._plot_bgcolor = plot_bgcolor
        self._axes_by_ids: dict[tuple[str, str], matplotlib.axes.Axes] = {}
        self._axes_by_domain: dict[
            tuple[float, float, float, float], matplotlib.axes.Axes
        ] = {}
        # (ax, letter, fixed_lo, fixed_hi) for a Plotly range with exactly
        # one bound set (e.g. ctd_sampling/plotting.py's range=[0, None]) -
        # applied only after every trace/shape is drawn, see
        # apply_pending_ranges().
        self._pending_partial_ranges: list[
            tuple[matplotlib.axes.Axes, Literal["x", "y"], float | None, float | None]
        ] = []

    def get(self, xaxis_id: str, yaxis_id: str) -> matplotlib.axes.Axes:
        """Returns the Axes a trace/shape referencing this (xaxis, yaxis) pair should draw into.

        Args:
            xaxis_id: Plotly short x-axis id (e.g. "x", "x2").
            yaxis_id: Plotly short y-axis id (e.g. "y", "y2").

        Returns:
            A matplotlib Axes, created (or reused from a prior call) so
            every trace sharing a domain, or a secondary-axis overlay
            relationship, lands on the same Axes.
        """
        key = (xaxis_id, yaxis_id)
        if key in self._axes_by_ids:
            return self._axes_by_ids[key]

        x_overlay = self._overlaying_axis("x", xaxis_id)
        y_overlay = self._overlaying_axis("y", yaxis_id)

        if x_overlay is not None and y_overlay is not None:
            # A full secondary axis pair (e.g. Plotting/DiveCTD.py's
            # xaxis2/yaxis2 temperature overlay on the salinity/depth
            # primary): neither twinx() (shares x) nor twiny() (shares y)
            # fits, since *both* scales are independent. A fresh Axes
            # placed at the primary's exact position, with a transparent
            # background, is the matplotlib equivalent.
            primary_ax = self.get(x_overlay, y_overlay)
            ax = self._mpl_fig.add_axes(primary_ax.get_position().bounds)
            ax.patch.set_visible(False)
            self._apply_range_and_label(ax, "x", xaxis_id)
            self._apply_range_and_label(ax, "y", yaxis_id)
        elif y_overlay is not None:
            primary_ax = self.get(xaxis_id, y_overlay)
            ax = primary_ax.twinx()
            ax.patch.set_visible(False)
            self._apply_range_and_label(ax, "y", yaxis_id)
        elif x_overlay is not None:
            # E.g. Plotting/DiveCTD.py's xaxis3/4/5 (conductivity/sigma_t/
            # buoyancy frequency), each overlaying x1 while sharing y1.
            primary_ax = self.get(x_overlay, yaxis_id)
            ax = primary_ax.twiny()
            ax.patch.set_visible(False)
            self._apply_range_and_label(ax, "x", xaxis_id)
        else:
            domain_rect = self._domain_rect(xaxis_id, yaxis_id)
            if domain_rect in self._axes_by_domain:
                ax = self._axes_by_domain[domain_rect]
            else:
                ax = self._mpl_fig.add_axes(domain_rect)
                ax.set_facecolor(self._plot_bgcolor)
                self._axes_by_domain[domain_rect] = ax
                self._apply_range_and_label(ax, "x", xaxis_id)
                self._apply_range_and_label(ax, "y", yaxis_id)

        self._axes_by_ids[key] = ax
        return ax

    def _overlaying_axis(self, letter: Literal["x", "y"], axis_id: str) -> str | None:
        """Returns the primary axis id `axis_id` overlays, or None if it's primary.

        Args:
            letter: "x" or "y".
            axis_id: Plotly short axis id (e.g. "x2", "y2").

        Returns:
            The short id of the same-direction axis this one shares a
            domain with (e.g. "x1"/"x", per Plotly's `overlaying` layout
            attribute), or None if this axis isn't an overlay at all.
        """
        axis_obj = getattr(self._layout, f"{letter}axis{axis_id[1:]}", None)
        return getattr(axis_obj, "overlaying", None) if axis_obj is not None else None

    def _apply_range_and_label(
        self,
        ax: matplotlib.axes.Axes,
        letter: Literal["x", "y"],
        axis_id: str,
    ) -> None:
        """Applies one axis's explicit range/reversal, gridlines, and title text to a newly created Axes.

        Args:
            ax: The Axes just created for `axis_id`.
            letter: "x" or "y".
            axis_id: Plotly short axis id (e.g. "x", "y2").

        Returns:
            None.

        Note:
            Applying `set_xlim`/`set_ylim` explicitly (rather than leaving
            it to matplotlib's default autoscale-to-data behavior) also
            disables that axis's autoscaling going forward, so a range set
            here before any trace is drawn survives every later `ax.plot()`/
            `ax.scatter()`/etc. call onto the same Axes - this is what
            reproduces a depth-vs-something plot's "0 at top, increasing
            downward" range (e.g. `Plotting/DiveCTD.py`'s
            `yaxis.range=[depth.max(), 0]`), which a plain autoscaled
            Axes would otherwise render upside down relative to the
            kaleido original.
        """
        axis_obj = getattr(self._layout, f"{letter}axis{axis_id[1:]}", None)
        if axis_obj is None:
            return

        is_log = getattr(axis_obj, "type", None) == "log"
        if is_log:
            (ax.set_xscale if letter == "x" else ax.set_yscale)("log")

        axis_range = getattr(axis_obj, "range", None)
        if axis_range:
            lo = float(axis_range[0]) if axis_range[0] is not None else None
            hi = float(axis_range[1]) if axis_range[1] is not None else None
            if is_log:
                # Plotly expresses a log-axis's range in log10 space (e.g.
                # Plotting/DivePMAR.py's yaxis range=[y1_min, y1_max] with
                # type="log" means the axis spans 10**y1_min to
                # 10**y1_max) - matplotlib's set_xlim()/set_ylim() on a
                # log-scale Axes expect actual data values, not
                # log10-transformed ones. Applying the raw Plotly range
                # unconverted put the real (linearly-plotted, since
                # set_yscale("log") wasn't being called at all before this
                # fix) spectra data far outside a tiny log10-space ylim
                # like [-3, 3] - the "shifted high" symptom this fixes.
                lo = 10.0**lo if lo is not None else None
                hi = 10.0**hi if hi is not None else None
            if lo is not None and hi is not None:
                (ax.set_xlim if letter == "x" else ax.set_ylim)(lo, hi)
            else:
                # Plotly allows either bound to be None (e.g.
                # ctd_sampling/plotting.py's range=[0, None]), meaning
                # "fixed at this end, auto-scaled at the other". Calling
                # set_xlim()/set_ylim() at all - even passing the other
                # bound as None - permanently locks matplotlib's
                # autoscale to today's default (0, 1) view (confirmed
                # empirically: it does NOT mean "auto" the way Plotly's
                # partial range does), silently dropping every trace
                # plotted onto this Axes afterward outside that tiny
                # window. Deferred to apply_pending_ranges(), called only
                # once every trace/shape is drawn and autoscale has had
                # real data to work from.
                self._pending_partial_ranges.append((ax, letter, lo, hi))
        elif getattr(axis_obj, "autorange", None) == "reversed":
            (ax.invert_xaxis if letter == "x" else ax.invert_yaxis)()

        if getattr(axis_obj, "showgrid", True) is not False:
            gridcolor = _to_mpl_color(getattr(axis_obj, "gridcolor", None)) or "white"
            gridwidth = _scaled_linewidth_pt(
                getattr(axis_obj, "gridwidth", None), default_px=_DEFAULT_GRID_WIDTH_PX
            )
            ax.grid(True, axis=letter, color=gridcolor, linewidth=gridwidth)

        # An axis explicitly hidden (e.g. Plotting/DiveCTD.py's xaxis3/4/5,
        # "Not visible - no good way to control the bottom margin so there
        # is room for this") still needs its range applied above so the
        # traces plotted against it land in the right place, but the
        # author's choice to hide the axis itself should mean no label
        # either - matching what a real Plotly render does.
        if getattr(axis_obj, "visible", True) is False:
            return

        label_text = _clean_title_text(
            getattr(getattr(axis_obj, "title", None), "text", None)
        )
        if label_text:
            set_label = ax.set_xlabel if letter == "x" else ax.set_ylabel
            set_label(label_text, fontsize=_AXIS_LABEL_FONTSIZE)

    def apply_pending_ranges(self) -> None:
        """Applies every deferred partial-range request queued by `_apply_range_and_label()`.

        Must be called only after every trace/shape has been drawn, so
        each Axes' autoscale has real data to compute the free bound
        from - see the note in `_apply_range_and_label()`.

        Returns:
            None.
        """
        for ax, letter, lo, hi in self._pending_partial_ranges:
            cur_lo, cur_hi = ax.get_xlim() if letter == "x" else ax.get_ylim()
            (ax.set_xlim if letter == "x" else ax.set_ylim)(
                lo if lo is not None else cur_lo, hi if hi is not None else cur_hi
            )

    def _domain_rect(
        self, xaxis_id: str, yaxis_id: str
    ) -> tuple[float, float, float, float]:
        """Resolves the (left, bottom, width, height) figure-fraction rect for one subplot cell.

        Args:
            xaxis_id: Plotly short x-axis id (e.g. "x", "x2").
            yaxis_id: Plotly short y-axis id (e.g. "y", "y2").

        Returns:
            A (left, bottom, width, height) tuple in matplotlib's
            `Figure.add_axes()` figure-fraction convention, derived from
            the corresponding `layout.xaxis<N>`/`yaxis<N>.domain` and
            inset by `_FIGURE_MARGIN_*` to leave room for the title/axis
            labels around the actual data area (Plotly's own domain
            fractions carry no such margin - a plot with no explicit
            subplot grid uses the full [0, 1] span).
        """
        x0, x1 = self._axis_domain("x", xaxis_id)
        y0, y1 = self._axis_domain("y", yaxis_id)
        usable_width = 1.0 - _FIGURE_MARGIN_LEFT - _FIGURE_MARGIN_RIGHT
        usable_height = 1.0 - _FIGURE_MARGIN_BOTTOM - _FIGURE_MARGIN_TOP
        left = _FIGURE_MARGIN_LEFT + x0 * usable_width
        right = _FIGURE_MARGIN_LEFT + x1 * usable_width
        bottom = _FIGURE_MARGIN_BOTTOM + y0 * usable_height
        top = _FIGURE_MARGIN_BOTTOM + y1 * usable_height
        return (left, bottom, right - left, top - bottom)

    def _axis_domain(
        self, letter: Literal["x", "y"], axis_id: str
    ) -> tuple[float, float]:
        """Reads one axis's `domain` from the layout, defaulting to the full [0, 1] span.

        Args:
            letter: "x" or "y".
            axis_id: Plotly short axis id (e.g. "x", "y3").

        Returns:
            A (start, end) domain tuple in [0, 1] figure-fraction units -
            the full span for a single-panel figure with no explicit
            subplot grid (where `layout.xaxis`/`yaxis` carry no `domain`).
        """
        axis_obj = getattr(self._layout, f"{letter}axis{axis_id[1:]}", None)
        domain = getattr(axis_obj, "domain", None) if axis_obj is not None else None
        return (float(domain[0]), float(domain[1])) if domain else (0.0, 1.0)


def _render_shapes(resolver: _AxesResolver, layout: Any) -> None:
    """Draws every `layout.shapes` entry this converter supports onto its resolved subplot.

    Args:
        resolver: The `_AxesResolver` for the figure being rendered.
        layout: The source Plotly figure's `layout` object. Typed `Any` -
            see `_line_style()`.

    Returns:
        None.

    Raises:
        NotImplementedError: If a shape isn't a data-anchored line shape
            (the only kind any registered plot uses as of this writing -
            see the plan doc's WKB inventory) - e.g. a "rect" shape, or one
            anchored to "paper" coordinates rather than a data axis.
    """
    for shape in layout.shapes or ():
        if shape.type != "line":
            raise NotImplementedError(
                f"PlotUtilsMatplotlib: unsupported layout.shapes type {shape.type!r}"
            )
        xref = shape.xref or "x"
        yref = shape.yref or "y"
        if xref == "paper" or yref == "paper":
            raise NotImplementedError(
                "PlotUtilsMatplotlib: paper-relative layout.shapes are not yet supported"
            )
        ax = resolver.get(xref, yref)
        line = shape.line
        color = (
            _to_mpl_color(getattr(line, "color", None)) if line is not None else None
        )
        linewidth = _scaled_linewidth_pt(getattr(line, "width", None))
        ax.plot(
            [shape.x0, shape.x1],
            [shape.y0, shape.y1],
            color=color or "black",
            linestyle=_line_style(line),
            linewidth=linewidth,
        )


def render_thumbnail(
    fig: plotly.graph_objects.Figure,
    output_path: pathlib.Path,
    width: int = _DEFAULT_THUMBNAIL_WIDTH,
    height: int = _DEFAULT_THUMBNAIL_HEIGHT,
) -> None:
    """Renders a small static preview of a Plotly figure via matplotlib, in place of kaleido/Chrome.

    Not a general-purpose Plotly renderer: covers only the trace types and
    layout features this project's registered dive/mission plots actually
    use, per the inventory in
    `.claude/plans/2026-08-20-matplotlib-thumbnail-engine.md`. Deliberately
    raises rather than silently rendering something misleading, or falling
    back to kaleido, when it encounters a trace type or shape it doesn't
    yet handle - see that plan's "no fallback" requirement.

    `layout.annotations`, axis tick labels/numbers, and the legend are
    dropped entirely - illegible or too visually noisy at thumbnail size
    regardless of plot. A figure title, per-axis labels, and gridlines are
    kept in a small font, as a legibility-permitting suggestion of the
    full-size render rather than a faithful reproduction.

    Args:
        fig: The built Plotly figure to render a thumbnail of.
        output_path: Destination image file path; format is inferred from
            its suffix (e.g. ".webp").
        width: Output image width in pixels.
        height: Output image height in pixels.

    Returns:
        None.

    Raises:
        NotImplementedError: If `fig` uses a trace type (`_TRACE_RENDERERS`)
            or `layout.shapes` type this converter doesn't yet handle.
    """
    paper_bgcolor, plot_bgcolor = _resolve_bgcolors(fig.layout)

    mpl_fig = matplotlib.figure.Figure(
        figsize=(width / _DEFAULT_DPI, height / _DEFAULT_DPI),
        dpi=_DEFAULT_DPI,
        facecolor=paper_bgcolor,
    )
    # Explicit canvas attachment (rather than matplotlib.pyplot's stateful
    # global current-figure API) keeps this thread-safe: write_output_files()
    # invokes this via bounded_render() on a background worker thread, and
    # pyplot's global state isn't safe to share across concurrent renders.
    FigureCanvasAgg(mpl_fig)

    resolver = _AxesResolver(mpl_fig, fig.layout, plot_bgcolor)
    for trace in fig.data:
        visible = getattr(trace, "visible", True)
        if visible is False or visible == "legendonly":
            continue
        renderer = _TRACE_RENDERERS.get(trace.type)
        if renderer is None:
            raise NotImplementedError(
                f"PlotUtilsMatplotlib: no thumbnail renderer for trace type {trace.type!r}"
            )
        # 3D trace types (e.g. "cone") have no .xaxis/.yaxis at all - only
        # .scene - since Plotly doesn't place them on a 2D subplot grid.
        # This converter always projects them onto a flat single-panel
        # drawing (see _render_cone()), so "x"/"y" is the right fallback,
        # not an error.
        xaxis_id = getattr(trace, "xaxis", None) or "x"
        yaxis_id = getattr(trace, "yaxis", None) or "y"
        renderer(resolver.get(xaxis_id, yaxis_id), trace, fig.layout)

    _render_shapes(resolver, fig.layout)
    resolver.apply_pending_ranges()

    # length=0 + all four label positions off hides tick marks/numbers
    # without clearing the underlying tick *locations* the way
    # set_xticks([])/set_yticks([]) would - ax.grid() (_apply_range_and_
    # label()) draws gridlines at those same locations, so clearing them
    # here would silently erase the grid too.
    for ax in mpl_fig.axes:
        ax.tick_params(
            axis="both",
            which="both",
            length=0,
            labelbottom=False,
            labelleft=False,
            labeltop=False,
            labelright=False,
        )

    title_text = _clean_title_text(
        getattr(getattr(fig.layout, "title", None), "text", None)
    )
    if title_text:
        mpl_fig.suptitle(title_text, fontsize=_TITLE_FONTSIZE, y=0.99)

    mpl_fig.savefig(output_path, dpi=_DEFAULT_DPI, facecolor=paper_bgcolor)
