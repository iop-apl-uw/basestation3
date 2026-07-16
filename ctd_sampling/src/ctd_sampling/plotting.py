"""Plotly figures visualizing the WKB-stretched sampling schedule.

Recreates the two figures produced by ``glider_sampling_5_dives_v3_GS.m``,
using ``plotly`` (already a project dependency; ``matplotlib`` is not) in
place of MATLAB's interactive figure windows, so they can be saved as
standalone HTML and viewed without a display.
"""

from collections.abc import Sequence

import numpy as np
import plotly.graph_objects as go
from numpy.typing import NDArray
from plotly.subplots import make_subplots

from ctd_sampling.wkb import GriddedDives, WkbDirectionResult, WkbResult

_OPTION_COLORS = ("#d62728", "#1a1a1a", "#1f77b4")  # red, black, blue

# WKB stretching (ctd_sampling.wkb) works in rad/s throughout, the
# natural unit for its integral; cycles/hour is only for display here.
_RAD_PER_S_TO_CPH = 3600.0 / (2.0 * np.pi)

_BF_HOVERTEMPLATE = "depth: %{y:.0f} m<br>buoyancy frequency: %{x:.3f} cph<extra></extra>"
_SAMPLING_HOVERTEMPLATE = (
    "%{fullData.name}<br>depth: %{customdata:.0f} m<br>dive time: %{x:.2f} min"
    "<br>sampling interval: %{y:.1f} s<extra></extra>"
)


def build_buoyancy_figure(sg: GriddedDives, result: WkbResult) -> go.Figure:
    """Builds the buoyancy-frequency profile figure.

    Shows the per-cast ("5-m") buoyancy frequency, the cross-cast smoothed
    profile used for WKB stretching, and the single uniform reference
    frequency that WKB-stretched sampling is made uniform with respect to.

    Args:
        sg: Gridded dive stack.
        result: WKB schedule result, as returned by ``compute_wkb_schedule``.

    Returns:
        A plotly Figure with depth increasing downward.
    """
    raw_cph = sg.buoyancy_freq * _RAD_PER_S_TO_CPH
    smooth_cph = result.buoyancy_freq * _RAD_PER_S_TO_CPH
    reference_cph = result.reference_buoyancy_freq * _RAD_PER_S_TO_CPH

    fig = go.Figure()
    for k in range(raw_cph.shape[1]):
        fig.add_trace(
            go.Scatter(
                x=raw_cph[:, k],
                y=sg.z,
                mode="lines",
                line={"color": "rgba(0,0,0,0.3)", "width": 1},
                name="5-m buoyancy frequency",
                legendgroup="raw",
                showlegend=(k == 0),
                hovertemplate=_BF_HOVERTEMPLATE,
            )
        )
    fig.add_trace(
        go.Scatter(
            x=smooth_cph,
            y=result.z,
            mode="lines",
            line={"color": "black", "width": 2},
            name="smooth buoyancy frequency",
            hovertemplate=_BF_HOVERTEMPLATE,
        )
    )
    # The z grid always spans the full [0, wkb_z_max] range regardless of
    # how deep any actual cast reached, so a fixed [z_max, 0] axis range
    # left shallow dives mostly blank below their real data. Use whichever
    # is shallower: the deepest depth any trace actually has data at (with
    # a little padding so it isn't flush against the axis edge), or the
    # grid's own max depth (i.e. unchanged from before, for dives that
    # really do reach that deep).
    has_data = np.any(np.isfinite(sg.buoyancy_freq), axis=1) | np.isfinite(smooth_cph)
    finite_z_idx = np.flatnonzero(has_data)
    deepest_observed = float(sg.z[finite_z_idx[-1]]) if finite_z_idx.size else float(sg.z[-1])
    y_max = min(deepest_observed * 1.1, float(sg.z[-1]))

    fig.add_trace(
        go.Scatter(
            x=[reference_cph, reference_cph],
            y=[0, y_max],
            mode="lines",
            line={"color": "black", "width": 2, "dash": "dash"},
            name="uniform buoyancy frequency",
            hovertemplate=_BF_HOVERTEMPLATE,
        )
    )
    x_max = float(np.nanmax(smooth_cph)) * 1.1
    fig.update_layout(
        xaxis={"title": "buoyancy freq. [cycles/hour]", "range": [0, x_max]},
        yaxis={"title": "depth [m]", "range": [y_max, 0]},
        title="Buoyancy frequency",
        template="plotly_white",
    )
    return fig


def _add_direction_traces(
    fig: go.Figure,
    row: int,
    direction_label: str,
    z: NDArray[np.float64],
    direction: WkbDirectionResult,
    relative_N: NDArray[np.float64],
    depth_labels: Sequence[float],
    y_max: float,
) -> None:
    """Adds one direction's (dive or climb) sampling-interval-vs-time traces to a subplot row."""
    time_min = direction.time_dive / 60

    fig.add_trace(
        go.Scatter(
            x=time_min,
            y=direction.dt_old,
            customdata=z,
            mode="lines",
            line={"color": "rgba(128,128,128,1)", "width": 4},
            name=f"current sampling, {direction.n_points} points ({direction_label})",
            legendgroup="current",
            legendrank=0,
            showlegend=True,
            hovertemplate=_SAMPLING_HOVERTEMPLATE,
        ),
        row=row,
        col=1,
    )

    z_1m_time_min = np.interp(direction.z_1m, z, direction.time_dive) / 60

    # The "N points" label for each option is anchored to that option's
    # deepest *reached* bucket, not literally the last bucket (buckets_depths'
    # deepest entry, e.g. 1200 m by default) - most dives don't reach that
    # deep, leaving it NaN, which previously sent every option's label to
    # the same undefined (null) position, stacking them on top of each
    # other. Then, since options can still legitimately end up with close
    # (but now valid) rates, nudge any that are still nearly-coincident
    # apart just enough to stay readable.
    label_ys = np.full(direction.n_new.size, np.nan)
    for option in range(direction.n_new.size):
        valid = np.flatnonzero(np.isfinite(direction.buckets_sampling_rate[:, option]))
        if valid.size:
            label_ys[option] = direction.buckets_sampling_rate[valid[-1], option]
    min_gap = 0.06 * y_max
    placed_ys = label_ys.copy()
    prev = None
    for idx in np.argsort(label_ys):  # ascending; NaNs sort last and are skipped below
        if not np.isfinite(placed_ys[idx]):
            continue
        if prev is not None and placed_ys[idx] < prev + min_gap:
            placed_ys[idx] = prev + min_gap
        prev = placed_ys[idx]

    for option in range(direction.n_new.size):
        color = _OPTION_COLORS[option % len(_OPTION_COLORS)]
        legendgroup = f"option{option}"
        fig.add_trace(
            go.Scatter(
                x=time_min,
                y=direction.dt_new[:, option],
                customdata=z,
                mode="lines",
                line={"color": color, "width": 1},
                name=f"wkb sampling, option {option} ({direction_label})",
                legendgroup=legendgroup,
                showlegend=True,
                hovertemplate=_SAMPLING_HOVERTEMPLATE,
            ),
            row=row,
            col=1,
        )
        fig.add_trace(
            go.Scatter(
                x=z_1m_time_min,
                y=direction.sr_1m[:, option],
                customdata=direction.z_1m,
                mode="lines",
                line={"color": color, "width": 3},
                name=f"{int(direction.n_new[option])} points ({relative_N[option]:.1f}*) ({direction_label})",
                legendgroup=legendgroup,
                showlegend=True,
                hovertemplate=_SAMPLING_HOVERTEMPLATE,
            ),
            row=row,
            col=1,
        )
        if np.isfinite(placed_ys[option]):
            fig.add_annotation(
                x=float(np.nanmax(time_min)) + 1,
                y=float(placed_ys[option]),
                text=f"{int(direction.n_new[option])} points",
                showarrow=False,
                font={"color": color, "size": 12},
                xanchor="left",
                row=row,
                col=1,
            )

    for depth_label in depth_labels:
        crossing = np.flatnonzero(z >= depth_label)
        if crossing.size == 0:
            continue
        t = direction.time_dive[crossing[0]] / 60
        if not np.isfinite(t):
            continue
        # A plain add_vline always spans the full subplot height (it can't
        # take a finite y1 - see its docstring), which put its top end
        # directly behind the depth label below. add_shape with an explicit
        # data-space y1 stops the line short of the label instead. Both are
        # fractions of y_max (matching the original hardcoded 58/63 out of
        # a fixed 65 max) so they stay proportionally placed near the top
        # regardless of how tall the axis needs to be for this dive.
        fig.add_shape(
            type="line",
            x0=float(t),
            x1=float(t),
            y0=0,
            y1=y_max * 0.892,
            line={"color": "blue", "width": 1, "dash": "dash"},
            row=row,
            col=1,
        )
        fig.add_annotation(
            x=float(t),
            y=y_max * 0.969,
            text=f"{int(depth_label)} m",
            showarrow=False,
            font={"color": "blue", "size": 11},
            row=row,
            col=1,
        )


def build_sampling_schedule_figure(
    result: WkbResult,
    label: str,
    dive_range: tuple[int, int],
    relative_N: NDArray[np.float64],
    depth_labels: Sequence[float] = tuple(range(0, 1100, 100)),
) -> go.Figure:
    """Builds the current-vs-WKB sampling-interval-vs-depth figure (dive and climb subplots).

    Args:
        result: WKB schedule result, as returned by ``compute_wkb_schedule``.
        label: Glider/deployment label used in the figure title.
        dive_range: (first, last) dive numbers included, for the title.
        relative_N: The same point-count multipliers passed to
            ``compute_wkb_schedule`` (e.g. ``[0.8, 1, 1.5]``), shown in each
            option's legend name, e.g. ``(1.0*)``.
        depth_labels: Depths (m) at which to draw reference gridlines.

    Returns:
        A plotly Figure with two stacked subplots (dive, climb).
    """
    fig = make_subplots(
        rows=2,
        cols=1,
        subplot_titles=(
            f"dive ({result.dive.n_points} points)",
            f"climb ({result.climb.n_points} points)",
        ),
    )
    # A fixed [0, 65] range clipped real traces whenever a dive's proposed
    # sampling interval legitimately exceeded 65s (e.g. a shallow/sparse
    # bucket) - size the axis to comfortably fit every trace in both
    # subplots instead, with a little headroom above the tallest one.
    peaks = [
        np.nanmax(direction.dt_old) if np.any(np.isfinite(direction.dt_old)) else np.nan
        for direction in (result.dive, result.climb)
    ] + [
        np.nanmax(direction.dt_new) if np.any(np.isfinite(direction.dt_new)) else np.nan
        for direction in (result.dive, result.climb)
    ]
    finite_peaks = [float(p) for p in peaks if np.isfinite(p)]
    y_max = max(finite_peaks) * 1.1 if finite_peaks else 65.0
    _add_direction_traces(fig, 1, "dive", result.z, result.dive, relative_N, depth_labels, y_max)
    _add_direction_traces(fig, 2, "climb", result.z, result.climb, relative_N, depth_labels, y_max)

    trace_groups = [trace.legendgroup for trace in fig.data]
    n_options = result.dive.n_new.size
    buttons = [
        {
            "args2": [{"visible": True}],
            "args": [{"visible": "legendonly"}],
            "label": "All",
            "method": "restyle",
        },
        {
            "args2": [{"visible": True}, [i for i, group in enumerate(trace_groups) if group == "current"]],
            "args": [{"visible": "legendonly"}, [i for i, group in enumerate(trace_groups) if group == "current"]],
            "label": "Current",
            "method": "restyle",
        },
    ]
    for option in range(n_options):
        idx = [i for i, group in enumerate(trace_groups) if group == f"option{option}"]
        buttons.append(
            {
                "args2": [{"visible": True}, idx],
                "args": [{"visible": "legendonly"}, idx],
                "label": f"Option {option}",
                "method": "restyle",
            }
        )

    fig.update_xaxes(title_text="dive time [min]", range=[0, None])
    fig.update_yaxes(title_text="sampling interval [sec]", range=[0, y_max])
    fig.update_layout(
        title=f"{label} , dives {dive_range[0]}-{dive_range[1]}",
        template="plotly_white",
        height=800,
        legend={"groupclick": "togglegroup"},
        updatemenus=[
            {
                "type": "buttons",
                "direction": "right",
                "buttons": buttons,
                "x": 0.0,
                "y": 1.12,
                "xanchor": "left",
                "yanchor": "top",
                "showactive": False,
            }
        ],
    )
    return fig
