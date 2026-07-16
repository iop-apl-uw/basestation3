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

"""Plots a WKB-stretched CTD sampling schedule from a trailing window of dives"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import argparse
import json
import math
import pathlib
import typing

import ctd_sampling.plotting
import ctd_sampling.wkb
import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import BaseOptsType
import MakeDiveProfiles
import PlotUtils
import PlotUtilsPlotly
import ScienceGrid
import WkbConfigText
from BaseLog import log_warning
from Plotting import add_arguments, plotdivesingle

_DEFAULT_BUCKETS_DEPTHS = (
    100.0,
    200.0,
    300.0,
    400.0,
    500.0,
    600.0,
    700.0,
    800.0,
    1200.0,
)
_DEFAULT_RELATIVE_N = (0.8, 1.0, 1.5)
_DZ = 5.0
_Z_MAX = 1000.0
_TOP_SAMPLING_RATE = 5.0


def _parse_float_tuple(value: str) -> tuple[float, ...]:
    """Parses a comma-separated string of floats into a tuple.

    Used as the ``var_type`` for the ``--wkb_buckets_depths``/
    ``--wkb_relative_n`` options, e.g. ``"0.8,1,1.5"`` -> ``(0.8, 1.0, 1.5)``.
    """
    return tuple(float(v) for v in value.split(","))


# (builder attr on the result dict below, help-link slug, output file tag, title suffix)
_FIGURE_SPECS = (
    ("buoyancy", "dv_wkb_buoyfreq", "wkb_buoyfreq", "Buoyancy Frequency"),
    ("schedule", "dv_wkb_schedule", "wkb_schedule", "WKB-Stretched Sampling Schedule"),
)

# Extra bottom margin (px) reserved for the note and the (now two-column,
# so about half as tall) swapped-in proposed-config text.
_CONFIG_TEXT_MARGIN_B = 320
_NOTE_Y = -0.13
# Right-anchored under PlotUtilsPlotly.add_help_link's "Help for this plot"
# (x=1.0, xanchor="left", y=0.0) - same x, xanchor="right" instead so the
# monospace block's right edge lines up with the plot's right edge rather
# than spilling past it.
_CONFIG_TEXT_X = 1.0
# ctd_sampling.plotting.build_sampling_schedule_figure's own height (800)
# assumes Plotly's default ~80px bottom margin; increasing margin.b to make
# room for the note eats directly into the two subplots' drawing area unless
# height grows to compensate - without this, the fixed-paper-fraction button
# row (y=1.12 in ctd_sampling/plotting.py) sits too close (in pixels) to the
# subplot titles near paper y=1.0, since the shrunken drawing area shrinks
# that fractional gap's pixel size too (confirmed empirically via headless
# Chrome - the button row visibly overlapped the "dive (N points)" subplot
# title once this compensation was dropped).
_FIGURE_HEIGHT = 800 - 80 + _CONFIG_TEXT_MARGIN_B


def _two_column_display(text: str) -> str:
    """Reformats a `ct = { ... }` block into two side-by-side columns for
    display, splitting the depth,interval lines as evenly as possible.

    Purely a display transform - the raw single-column text (what the
    "Copy schedule" button copies) is unaffected, since callers keep their
    own reference to the original text for that. Halving the visual height
    of the longest (9-bucket) case is what makes it fit back at the same y
    position as before the block grew tall enough to need its own space
    below the legend/help-link area.

    Args:
        text: A `ct = {\\n depth,interval\\n ...\\n}` block, optionally
            preceded by one or more WkbConfigText.comment_line lines.

    Returns:
        The same block with its body lines arranged in two columns,
        left-aligned and padded to line up. Any leading comment lines are
        kept verbatim, above the two columns. The closing brace is the last
        entry of the right column (bottom-right), not a row of its own
        trailing under the left column.
    """
    lines = text.split("\n")
    comment_lines = []
    while lines and lines[0].startswith("/"):
        comment_lines.append(lines.pop(0))
    if len(lines) <= 3:
        return "\n".join([*comment_lines, *lines])
    header, *body, footer = lines
    split = math.ceil(len(body) / 2)
    left, right = body[:split], [*body[split:], footer]
    width = max(len(line) for line in left)
    rows = []
    for i in range(len(right)):
        left_cell = left[i].ljust(width) if i < len(left) else " " * width
        rows.append(f"{left_cell}   {right[i]}".rstrip())
    return "\n".join([*comment_lines, header, *rows])


def _config_annotation(text: str) -> dict:
    """Builds a hidden monospace annotation dict for one config-text block."""
    return {
        "text": _two_column_display(text).replace("\n", "<br>"),
        "showarrow": False,
        "align": "left",
        "xref": "paper",
        "yref": "paper",
        "x": _CONFIG_TEXT_X,
        "y": _NOTE_Y,
        "xanchor": "right",
        "yanchor": "top",
        "font": {"family": "monospace", "size": 12},
        "visible": False,
    }


def _note_annotation(dive_nc_file: scipy.io._netcdf.netcdf_file) -> dict:
    """Builds the permanent (always-visible) explanatory note annotation.

    Reports the dive's actual CT type/mount - the only place that
    information affects the display, since the proposed/current schedule
    text itself is always shown in scicon's ct = {...} format regardless of
    mount (see WkbConfigText.proposed_config_text).
    """
    type_name = WkbConfigText.ct_type_name(dive_nc_file)
    mount = WkbConfigText.ct_mount(dive_nc_file)
    text = (
        f"Click Current or an Option button above for that schedule.<br>"
        f"CT: {type_name} ({mount}-mounted)"
    )
    return {
        "text": text,
        "showarrow": False,
        "align": "left",
        "xref": "paper",
        "yref": "paper",
        "x": 0.0,
        "y": _NOTE_Y,
        "xanchor": "left",
        "yanchor": "top",
        "font": {"size": 12},
    }


_COPY_BUTTON_POST_SCRIPT = """
(function() {{
  // plotly.py replaces the literal "{{plot_id}}" token below with this
  // specific plot's own div id before this script ever runs - do not use
  // document.getElementsByClassName('plotly-graph-div')[0] here, which
  // would silently grab a *different* plot's div (and mismatch its own
  // annotations/updatemenus) on any page showing more than one plot.
  var gd = document.getElementById('{{plot_id}}');
  var texts = {texts_json};
  var btn = document.createElement('button');
  var label = 'Copy schedule';
  btn.textContent = label;
  btn.style.cssText = 'position:absolute;display:none;padding:6px 14px;'
    + 'font-family:monospace;font-size:12px;cursor:pointer;z-index:10;';
  btn.addEventListener('click', function() {{
    var idx = Object.keys(texts).find(function(i) {{
      var a = gd.layout.annotations[i];
      return a && a.visible;
    }});
    if (idx === undefined) {{
      btn.textContent = 'Nothing shown to copy';
    }} else {{
      navigator.clipboard.writeText(texts[idx]).then(function() {{
        btn.textContent = 'Copied!';
      }}, function() {{
        btn.textContent = 'Copy failed';
      }});
    }}
    setTimeout(function() {{ btn.textContent = label; }}, 1500);
  }});
  gd.insertAdjacentElement('afterend', btn);

  function updateVisibility() {{
    var anyVisible = Object.keys(texts).some(function(i) {{
      var a = gd.layout.annotations[i];
      return a && a.visible;
    }});
    btn.style.display = anyVisible ? '' : 'none';
  }}

  // Finds the CSS containing-block origin for an absolutely positioned
  // element the same way the spec does: the padding edge of the nearest
  // ancestor that is itself positioned (non-static) OR establishes a new
  // containing block via transform/perspective/filter/will-change/contain
  // (yes, even a no-op transform like matrix(1,0,0,1,0,0) counts - found
  // empirically via vis.py's real dashboard, which applies exactly that
  // to <body>, unlike its bare standalone plot page). offsetParent alone
  // isn't enough to detect this: it reports <body> as a DOM API fallback
  // whether or not <body> is actually such an ancestor, and body's own
  // rect is offset by its default browser margin - not the same origin
  // position:absolute measures from when there's truly no such ancestor
  // (that case instead falls back to the initial containing block, i.e.
  // the viewport origin adjusted for the page's current scroll).
  function establishesContainingBlock(el) {{
    var cs = getComputedStyle(el);
    return cs.position !== 'static'
      || cs.transform !== 'none'
      || cs.perspective !== 'none'
      || cs.filter !== 'none'
      || /transform|perspective|filter/.test(cs.willChange)
      || (cs.contain && /layout|paint|strict|content/.test(cs.contain));
  }}
  function containingBlockOrigin(el) {{
    var ancestor = el.parentElement;
    while (ancestor && ancestor !== document.documentElement) {{
      if (establishesContainingBlock(ancestor)) {{
        var r = ancestor.getBoundingClientRect();
        var cs = getComputedStyle(ancestor);
        return {{left: r.left + parseFloat(cs.borderLeftWidth) || 0, top: r.top + parseFloat(cs.borderTopWidth) || 0}};
      }}
      ancestor = ancestor.parentElement;
    }}
    return {{left: -window.scrollX, top: -window.scrollY}};
  }}

  function positionButton() {{
    // Scoped to gd's own SVG, not document, so this can't find some
    // *other* plot's "Option 2" button if the page shows more than one.
    var opt2 = Array.from(gd.querySelectorAll('g.updatemenu-button')).find(function(g) {{
      var t = g.querySelector('text');
      return t && t.textContent.trim() === 'Option 2';
    }});
    if (!opt2) return;
    var targetRect = opt2.getBoundingClientRect();
    var origin = containingBlockOrigin(btn);
    btn.style.left = (targetRect.right - origin.left + 8) + 'px';
    btn.style.top = (targetRect.top - origin.top) + 'px';
  }}

  // The updatemenu buttons aren't in the DOM yet the instant newPlot
  // resolves (post_script runs before Plotly's own layout pass), and even
  // once plotly_afterplot fires, this plot's own responsive resize (fit
  // to its container) can still be pending for another frame or two -
  // measuring synchronously inside the plotly_afterplot handler reads
  // stale rects whenever this plot is embedded in a page with its own
  // layout (e.g. a dashboard, as opposed to a bare standalone plot page),
  // silently leaving the button mispositioned relative to Option 2 with
  // no error. A couple of animation frames covers Plotly's own resize;
  // a dashboard page can *also* have its own outer panel/layout code
  // that settles the plot's container size later still (confirmed
  // empirically against vis.py's real pilot dashboard - a plain rAF-based
  // reposition was still off by ~20px there), on a timeline this script
  // has no way to know in advance - so re-check a few more times over the
  // following second and a half as a pragmatic catch-all, on top of the
  // event-driven repositioning below.
  function positionButtonSettled() {{
    requestAnimationFrame(function() {{ requestAnimationFrame(positionButton); }});
  }}
  [50, 200, 500, 1000, 1500].forEach(function(delay) {{ setTimeout(positionButton, delay); }});
  gd.on('plotly_afterplot', function() {{ positionButtonSettled(); updateVisibility(); }});
  gd.on('plotly_relayout', function() {{ positionButtonSettled(); updateVisibility(); }});
  gd.on('plotly_autosize', positionButtonSettled);
  window.addEventListener('resize', positionButtonSettled);
  positionButtonSettled();
  updateVisibility();
}})();
"""


def _add_config_annotations(
    fig: plotly.graph_objects.Figure,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    base_opts: BaseOpts.BaseOptions,
    result: ctd_sampling.wkb.WkbResult,
) -> str:
    """Adds per-option proposed-config and current-config text annotations,
    swapped in by the existing All/Current/Option-N toggle buttons.

    Args:
        fig: The schedule figure returned by
            ctd_sampling.plotting.build_sampling_schedule_figure.
        dive_nc_file: Open per-dive netCDF dataset.
        base_opts: Basestation options (for the science grid).
        result: WKB schedule result, as returned by compute_wkb_schedule.

    Returns:
        A post_script (for PlotUtilsPlotly.write_output_files) that adds a
        "Copy schedule" button copying whichever text is currently visible.
    """
    buckets_depths = np.array(base_opts.wkb_buckets_depths)
    annotation_idx_by_option: dict[int, int] = {}
    raw_text_by_idx: dict[int, str] = {}
    annotations = [*(fig.layout.annotations or ()), _note_annotation(dive_nc_file)]

    relative_N = np.array(base_opts.wkb_relative_n)
    for option in range(result.dive.n_new.size):
        text = WkbConfigText.proposed_config_text(
            buckets_depths, result.dive.buckets_sampling_rate[:, option]
        )
        # Same relative_N used to compute result (and shown in the legend
        # trace name, e.g. "(1.0*)"), so the comment line matches what the
        # pilot sees when picking an option.
        text = f"{WkbConfigText.comment_line(f'{relative_N[option]:.1f} * points')}\n{text}"
        idx = len(annotations)
        annotation_idx_by_option[option] = idx
        raw_text_by_idx[idx] = text
        annotations.append(_config_annotation(text))

    ScienceGrid.setup_science_grid(base_opts)
    instr_name = WkbConfigText.ctd_instrument_name(dive_nc_file)
    current_grid = ScienceGrid.find_current_grid(
        base_opts, dive_nc_file.dive_number, "a", instr_name
    )
    current_text = WkbConfigText.current_grid_block(current_grid.grid)
    current_idx = None
    if current_text is not None:
        current_text = f"{WkbConfigText.comment_line('Current')}\n{current_text}"
        current_idx = len(annotations)
        raw_text_by_idx[current_idx] = current_text
        annotations.append(_config_annotation(current_text))

    fig.update_layout(
        annotations=annotations,
        margin={"b": _CONFIG_TEXT_MARGIN_B},
        height=_FIGURE_HEIGHT,
    )

    all_idx = list(annotation_idx_by_option.values()) + (
        [current_idx] if current_idx is not None else []
    )
    hide_all = {f"annotations[{idx}].visible": False for idx in all_idx}
    # For every button, args hides that button's own traces (legendonly) and
    # args2 restores them (visible) - keep the text paired with whichever
    # side actually shows the traces, so trace and text always toggle
    # together (never one shown while the other is hidden).
    for button in fig.layout.updatemenus[0]["buttons"]:
        args_relayout = dict(hide_all)
        args2_relayout = dict(hide_all)
        if button["label"] == "Current":
            if current_idx is not None:
                args2_relayout[f"annotations[{current_idx}].visible"] = True
        elif button["label"].startswith("Option "):
            option = int(button["label"].removeprefix("Option "))
            if option in annotation_idx_by_option:
                args2_relayout[
                    f"annotations[{annotation_idx_by_option[option]}].visible"
                ] = True
        button["method"] = "update"
        button["args"] = [button["args"][0], args_relayout, *button["args"][1:]]
        button["args2"] = [button["args2"][0], args2_relayout, *button["args2"][1:]]

    return _COPY_BUTTON_POST_SCRIPT.format(texts_json=json.dumps(raw_text_by_idx))


@add_arguments(
    additional_arguments={
        "wkb_dives_back": BaseOptsType.options_t(
            5,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_dives_back",),
            int,
            {
                "help": "How many dives back (inclusive of the current dive) to include "
                "in the WKB-stretched sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_buckets_depths": BaseOptsType.options_t(
            _DEFAULT_BUCKETS_DEPTHS,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_buckets_depths",),
            _parse_float_tuple,
            {
                "help": "Comma-separated depth bucket boundaries (m) for the WKB-stretched "
                "sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_relative_n": BaseOptsType.options_t(
            _DEFAULT_RELATIVE_N,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_relative_n",),
            _parse_float_tuple,
            {
                "help": "Comma-separated candidate point-count multipliers (relative to the "
                "current sampling) to propose in the WKB-stretched sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_dz": BaseOptsType.options_t(
            _DZ,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_dz",),
            float,
            {
                "help": "Depth bin size (m) used when gridding dives for the WKB-stretched "
                "sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_z_max": BaseOptsType.options_t(
            _Z_MAX,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_z_max",),
            float,
            {
                "help": "Maximum depth (m) used when gridding dives for the WKB-stretched "
                "sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_top_sampling_rate": BaseOptsType.options_t(
            _TOP_SAMPLING_RATE,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_top_sampling_rate",),
            float,
            {
                "help": "Sampling interval (s) assumed above the shallowest depth bucket in "
                "the WKB-stretched sampling schedule plot",
                "section": "plotting",
                "option_group": "plotting",
            },
        ),
        "wkb_buoyfreq": BaseOptsType.options_t(
            True,
            {"Base", "BasePlot", "Reprocess"},
            ("--wkb_buoyfreq",),
            bool,
            {
                "help": "Also generate the companion WKB buoyancy frequency plot "
                "(--no-wkb_buoyfreq to skip it and only generate the schedule plot)",
                "section": "plotting",
                "option_group": "plotting",
                "action": argparse.BooleanOptionalAction,
            },
        ),
    }
)
@plotdivesingle
def plot_wkb_schedule(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots a WKB-stretched CTD sampling schedule from the trailing dive window"""
    if not generate_plots:
        return ([], [])

    latest = dive_nc_file.dive_number
    sg_label = f"{dive_nc_file.glider:03d}"
    window_start = latest - base_opts.wkb_dives_back + 1

    all_nc = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
    dive_numbers = sorted(
        n for f in all_nc if window_start <= (n := int(f.name[4:8])) <= latest
    )
    if not dive_numbers:
        return ([], [])

    z = np.arange(0.0, base_opts.wkb_z_max + base_opts.wkb_dz, base_opts.wkb_dz)
    sg = ctd_sampling.wkb.build_dive_stack(
        base_opts.mission_dir, sg_label, dive_numbers, z, base_opts.wkb_dz
    )
    try:
        result = ctd_sampling.wkb.compute_wkb_schedule(
            sg,
            buckets_depths=np.array(base_opts.wkb_buckets_depths),
            top_sampling_rate=base_opts.wkb_top_sampling_rate,
            relative_N=np.array(base_opts.wkb_relative_n),
        )
    except ValueError as exc:
        # E.g. every dive in the trailing window is too shallow/short to
        # reach past buckets_depths[0] - not enough data for a WKB-stretched
        # schedule, so skip this plot rather than crash the whole run.
        log_warning(f"Skipping plot_wkb_schedule for dive {latest}: {exc}")
        return ([], [])

    dives_str = (
        f"Dives {dive_numbers[0]} - {dive_numbers[-1]}"
        if len(dive_numbers) > 1
        else f"Dive {dive_numbers[0]}"
    )
    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file, dives_str=dives_str)

    built = {
        "schedule": ctd_sampling.plotting.build_sampling_schedule_figure(
            result,
            sg_label,
            (dive_numbers[0], dive_numbers[-1]),
            np.array(base_opts.wkb_relative_n),
        ),
    }
    if base_opts.wkb_buoyfreq:
        built["buoyancy"] = ctd_sampling.plotting.build_buoyancy_figure(sg, result)

    # Only the schedule plot's proposed-config text needs the "Copy schedule"
    # button - the buoyancy plot never gets a post_script at all, below.
    copy_post_script = _add_config_annotations(
        built["schedule"], dive_nc_file, base_opts, result
    )

    ret_figs = []
    ret_plots = []
    for key, help_slug, tag, title_suffix in _FIGURE_SPECS:
        if key not in built:
            continue
        fig = built[key]
        fig.update_layout(
            {
                "title": {
                    "text": f"{mission_dive_str}<br>{title_suffix}",
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {
                    "t": 150,
                },
                "annotations": tuple(fig.layout.annotations or ())
                + (PlotUtilsPlotly.add_help_link(help_slug),),
            }
        )
        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                f"dv{latest:04d}_{tag}",
                fig,
                post_script=copy_post_script if key == "schedule" else None,
            )
        )

    return (ret_figs, ret_plots)
