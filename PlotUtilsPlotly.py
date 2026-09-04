#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""Supporting routines for creating plots from netCDF data"""

from __future__ import annotations

import io
import json
import pathlib
import warnings
from typing import TYPE_CHECKING, Literal

import brotli
import PIL.Image
import plotly
import plotly.graph_objects
import plotly.io

import PlotUtilsMatplotlib
from BaseLog import log_error, log_warning

if TYPE_CHECKING:
    from BaseOpts import BaseOptions

# IOP Standard Figure size
std_width = 1058
std_height = 894
std_scale = 1.0

# Matches what vis is expecting
thumbnail_width = 370
thumbnail_height = 370


#
# Utility functions
#
def plotlyfig2json(fig, fpath=None):
    """
    Serialize a plotly figure object to JSON so it can be persisted to disk.
    Figures persisted as JSON can be rebuilt using the plotly JSON chart API:

    http://help.plot.ly/json-chart-schema/

    If `fpath` is provided, JSON is written to file.

    Modified from https://github.com/nteract/nteract/issues/1229

    Returns:
       Serialized json object
    """

    redata = json.loads(json.dumps(fig.data, cls=plotly.utils.PlotlyJSONEncoder))
    relayout = json.loads(json.dumps(fig.layout, cls=plotly.utils.PlotlyJSONEncoder))

    fig_json = json.dumps({"data": redata, "layout": relayout})

    if fpath:
        with open(fpath, "w") as f:
            f.write(fig_json)
    return fig_json


def plotlyfromjson(fpath):
    """Render a plotly figure from a json file
    - For documentation only - this is the display side of the above persistance

    Input:
        fpath - file path to the json file defining the figure
    Returns:
        plotly figure object
    """
    with open(fpath, "r") as f:
        v = json.loads(f.read())

    fig = plotly.graph_objects.Figure(data=v["data"], layout=v["layout"])
    # fig.show()
    return fig


def write_output_files(
    base_opts: BaseOptions,
    base_file_name: str,
    fig: plotly.graph_objects.Figure,
    post_script: str | list[str] | None = None,
    thumbnail_fig: plotly.graph_objects.Figure | None = None,
) -> list[pathlib.Path]:
    """
    Helper routine to output various file formats - .png and .div all the time
    and standalone .html and .svg based on conf file settings

    Input:
        base_opts - all options
        base_file_name - file name base for the output file names (i.e. no extension)
        fig - plotly figure object
        post_script - optional raw JS (str or list of str) run after the plot
            renders, passed straight through to plotly's fig.write_html.
            Unused by default; only plots that need it (e.g. a custom
            copy-to-clipboard button) pass it. Applied to both the
            standalone .html and the .div fragment output, since vis.py
            embeds .div fragments (possibly several per page) - any script
            passed here must target only its own plot (e.g. via plotly's
            "{plot_id}" post_script placeholder, substituted with that
            plot's own div id) rather than assuming it's the only plot on
            the page.
        thumbnail_fig - optional alternate figure used only for the
            matplotlib thumbnail-webp render (see PlotUtilsMatplotlib.
            render_thumbnail()), in place of `fig`. Unused by default; for
            a plot whose real figure is unsuitable for a *static* preview
            (e.g. DiveCTD.py's plot_CTD_series, an animated figure whose
            base fig.data reflects its oldest frame, not its current one -
            see .claude/plans/2026-08-20-matplotlib-thumbnail-engine.md),
            the caller builds a reduced, non-animated figure representing
            the state a thumbnail should freeze on and passes it here. The
            .div/.html/full-size-image outputs still render from `fig`
            unchanged - only the thumbnail is affected.
    Returns:
        List of fully qualified filenames that have been generated.
    """
    std_config_dict = {
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "scrollZoom": True,
        "modeBarButtonsToAdd": ["v1hovermode", "toggleSpikelines"],
    }

    if not base_opts.plot_directory:
        log_warning("plot_directory not specified - bailing out")
        return []

    base_file_name: pathlib.Path = base_opts.plot_directory / base_file_name

    ret_list: list[pathlib.Path] = []

    if base_opts.full_html:
        # if plot_opts full_html
        output_name = base_file_name.with_suffix(".html")
        fig.write_html(
            file=output_name,
            include_plotlyjs="cdn",
            full_html=True,
            auto_open=False,
            validate=True,
            config=std_config_dict,
            include_mathjax="cdn",
            auto_play=False,
            post_script=post_script,
            div_id='plotly-plot-div',
        )
        ret_list.append(output_name)

    # For IOP site - raw div
    output_name = base_file_name.with_suffix(".div")
    if base_opts.compress_div:
        fo_t = io.StringIO()
    else:
        fo_t = output_name

    try:
        fig.write_html(
            file=fo_t,
            include_plotlyjs=False,
            full_html=False,
            auto_open=False,
            validate=True,
            config=std_config_dict,
            include_mathjax="cdn",
            auto_play=False,
            post_script=post_script,
            div_id='plotly-plot-div',
        )

        if base_opts.compress_div:
            fo_t.seek(0, 0)
            with open(output_name, "wb") as fo:
                fo.write(brotli.compress(fo_t.read().encode("utf-8")))
            fo_t.close()
        ret_list.append(output_name)
    except Exception:
        log_error(f"Failed to write out {output_name}", "exc")

    def save_img_file(output_fmt: str) -> pathlib.Path:
        output_name = base_file_name.with_suffix(f".{output_fmt}")

        if (
            output_fmt == "webp"
            and base_opts.thumbnail_webp
            and getattr(base_opts, "thumbnail_engine", "matplotlib") == "matplotlib"
        ):
            # No kaleido/Chrome involved at all in this branch - see
            # .claude/plans/2026-08-20-matplotlib-thumbnail-engine.md's "no
            # fallback" requirement. A rendering failure here surfaces as a
            # normal logged error (via the except Exception below, same as
            # any other format), never a silent reach for kaleido.
            PlotUtilsMatplotlib.render_thumbnail(
                thumbnail_fig if thumbnail_fig is not None else fig,
                output_name,
                width=thumbnail_width,
                height=thumbnail_height,
            )
            return output_name

        # No return code
        # TODO - for kelido 0.2.1 and python 3.10 (and later) we get this warning:
        #   File "/Users/gbs/.pyenv/versions/3.10.7/lib/python3.10/threading.py", line 1224, in setDaemon
        #   warnings.warn('setDaemon() is deprecated, set the daemon attribute instead',
        #   DeprecationWarning: setDaemon() is deprecated, set the daemon attribute instead
        #
        # Remove when kelido is updated

        if output_fmt == "webp" and base_opts.thumbnail_webp:
            output_stream = io.BytesIO()
        else:
            output_stream = output_name

        # import pdb

        # pdb.set_trace()
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            fig.write_image(
                output_stream,
                format=output_fmt,
                width=std_width,
                height=std_height,
                scale=std_scale,
                validate=True,
            )

        if output_fmt == "webp" and base_opts.thumbnail_webp:
            image = PIL.Image.open(output_stream)
            resized_image = image.resize((thumbnail_height, thumbnail_width))
            resized_image.save(output_name)

        return output_name

    formats = [
        ("save_png", "png"),
        ("save_jpg", "jpg"),
        ("save_webp", "webp"),
        ("save_svg", "svg"),
    ]

    # A failure on one format doesn't affect the others - each is written
    # independently under its own try/except.
    for opt_name, ext in formats:
        if not getattr(base_opts, opt_name):
            continue
        try:
            ret_list.append(save_img_file(ext))
        except Exception as e:
            log_error(f"Failed to write out {base_file_name}.{ext}: {e}")

    def isnotebook():
        try:
            shell = get_ipython().__class__.__name__  # ty: ignore[unresolved-reference]
            # print(shell)
            if shell == "ZMQInteractiveShell":
                return True  # Jupyter notebook or qtconsole
            elif shell == "TerminalInteractiveShell":
                return False  # Terminal running IPython
            else:
                return False  # Other type (?)
        except NameError:
            return False  # Probably standard Python interpreter

    if isnotebook():
        fig.update_layout(width=std_width, height=std_height)
        fig.show()

    return ret_list


def add_help_link(
    plot_name: str,
    x_pos: float = 1.0,
    # y_pos: float = -0.08,
    y_pos=0.0,
) -> dict:
    root_dir_name = "/plothelp"

    plot_help_location = f"{root_dir_name}/{plot_name}.html"
    return {
        "text": f'<a href="{plot_help_location}">Help for this plot</a>',
        "showarrow": False,
        "xref": "paper",
        "yref": "paper",
        "x": x_pos,
        "y": y_pos,
        "xanchor": "left",
        "yanchor": "top",
    }


_CLIPBOARD_BUTTON_TEMPLATE = """
(function() {
  // plotly.py replaces the literal "{plot_id}" token below with this
  // specific plot's own div id before this script ever runs - do not use
  // document.getElementsByClassName('plotly-graph-div')[0] here, which
  // would silently grab a *different* plot's div (and mismatch its own
  // annotations/elements) on any page showing more than one plot.
  var gd = document.getElementById('{plot_id}');
  var label = __BUTTON_LABEL_JSON__;
  var btn = document.createElement('button');
  btn.textContent = label;
  btn.style.cssText = 'position:absolute;display:none;padding:6px 14px;'
    + 'font-family:monospace;font-size:12px;cursor:pointer;z-index:10;';

  function getCopyText() { __GET_COPY_TEXT_JS__ }
  function findAnchorElement() { __ANCHOR_ELEMENT_JS__ }
  function isVisible() { __IS_VISIBLE_JS__ }

  btn.addEventListener('click', function() {
    var text = getCopyText();
    if (!text) {
      btn.textContent = 'Nothing shown to copy';
    } else {
      navigator.clipboard.writeText(text).then(function() {
        btn.textContent = 'Copied!';
      }, function() {
        btn.textContent = 'Copy failed';
      });
    }
    setTimeout(function() { btn.textContent = label; }, 1500);
  });
  gd.insertAdjacentElement('afterend', btn);

  function updateVisibility() {
    btn.style.display = isVisible() ? '' : 'none';
  }

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
  function establishesContainingBlock(el) {
    var cs = getComputedStyle(el);
    return cs.position !== 'static'
      || cs.transform !== 'none'
      || cs.perspective !== 'none'
      || cs.filter !== 'none'
      || /transform|perspective|filter/.test(cs.willChange)
      || (cs.contain && /layout|paint|strict|content/.test(cs.contain));
  }
  function containingBlockOrigin(el) {
    var ancestor = el.parentElement;
    while (ancestor && ancestor !== document.documentElement) {
      if (establishesContainingBlock(ancestor)) {
        var r = ancestor.getBoundingClientRect();
        var cs = getComputedStyle(ancestor);
        return {left: r.left + parseFloat(cs.borderLeftWidth) || 0, top: r.top + parseFloat(cs.borderTopWidth) || 0};
      }
      ancestor = ancestor.parentElement;
    }
    return {left: -window.scrollX, top: -window.scrollY};
  }

  function positionButton() {
    // Scoped to gd's own DOM subtree, not document, so this can't find
    // some *other* plot's anchor element if the page shows more than
    // one plot.
    var target = findAnchorElement();
    if (!target) return;
    var targetRect = target.getBoundingClientRect();
    var origin = containingBlockOrigin(btn);
    __PLACEMENT_OFFSET_JS__
  }

  // The anchor element isn't necessarily in the DOM yet the instant
  // newPlot resolves (post_script runs before Plotly's own layout pass),
  // and even once plotly_afterplot fires, this plot's own responsive
  // resize (fit to its container) can still be pending for another frame
  // or two - measuring synchronously inside the plotly_afterplot handler
  // reads stale rects whenever this plot is embedded in a page with its
  // own layout (e.g. a dashboard, as opposed to a bare standalone plot
  // page), silently leaving the button mispositioned with no error. A
  // couple of animation frames covers Plotly's own resize; a dashboard
  // page can *also* have its own outer panel/layout code that settles
  // the plot's container size later still (confirmed empirically against
  // vis.py's real pilot dashboard - a plain rAF-based reposition was
  // still off by ~20px there), on a timeline this script has no way to
  // know in advance - so re-check a few more times over the following
  // second and a half as a pragmatic catch-all, on top of the
  // event-driven repositioning below.
  function positionButtonSettled() {
    requestAnimationFrame(function() { requestAnimationFrame(positionButton); });
  }
  [50, 200, 500, 1000, 1500].forEach(function(delay) { setTimeout(positionButton, delay); });
  gd.on('plotly_afterplot', function() { positionButtonSettled(); updateVisibility(); });
  gd.on('plotly_relayout', function() { positionButtonSettled(); updateVisibility(); });
  gd.on('plotly_autosize', positionButtonSettled);
  window.addEventListener('resize', positionButtonSettled);
  positionButtonSettled();
  updateVisibility();
})();
"""

_CLIPBOARD_BUTTON_PLACEMENT_OFFSETS: dict[str, str] = {
    "right_of": (
        "btn.style.left = (targetRect.right - origin.left + {gap}) + 'px';"
        "btn.style.top = (targetRect.top - origin.top) + 'px';"
    ),
    "below": (
        "btn.style.left = (targetRect.left - origin.left) + 'px';"
        "btn.style.top = (targetRect.bottom - origin.top + {gap}) + 'px';"
    ),
    # translateY(-100%) shifts the button up by its own rendered height
    # after positioning `top` at the desired *bottom* edge - avoids
    # needing to know the button's pixel height in advance (it can't be
    # measured reliably while display:none, which it is until
    # updateVisibility() first runs).
    "above": (
        "btn.style.left = (targetRect.left - origin.left) + 'px';"
        "btn.style.top = (targetRect.top - origin.top - {gap}) + 'px';"
        "btn.style.transform = 'translateY(-100%)';"
    ),
    # translateX(-50%) centers the button on the target's horizontal
    # center after positioning `left` there - same not-knowing-the-
    # button's-own-size trick as "above"'s translateY(-100%).
    "below_centered": (
        "btn.style.left = (targetRect.left + targetRect.width / 2 - origin.left) + 'px';"
        "btn.style.top = (targetRect.bottom - origin.top + {gap}) + 'px';"
        "btn.style.transform = 'translateX(-50%)';"
    ),
}


def build_clipboard_button_post_script(
    button_label: str,
    get_copy_text_js: str,
    anchor_element_js: str,
    is_visible_js: str,
    placement: Literal["right_of", "below", "above", "below_centered"] = "right_of",
    gap_px: int = 8,
) -> str:
    """Builds a post_script that adds a positioned clipboard-copy button.

    The button is injected via Plotly's post_script hook (see
    write_output_files), correctly positioned regardless of what page the
    plot ends up embedded in (a CSS containing-block-aware algorithm, not
    just offsetParent), and safely scoped to its own plot's div even on a
    page showing more than one plot (via Plotly's "{plot_id}" post_script
    substitution and gd-scoped DOM queries only - see the generated
    script's inline comments for why each of those matters).

    Args:
        button_label: Text shown on the button, and restored after the
            "Copied!"/"Copy failed"/"Nothing shown to copy" feedback
            message times out.
        get_copy_text_js: JS statements, forming the body of a function
            closing over `gd` (this plot's own div), that must `return`
            the string to copy, or a falsy value if nothing is currently
            copyable.
        anchor_element_js: JS statements (same calling convention) that
            must `return` the DOM element the button should be
            positioned next to, or a falsy value if it isn't found yet.
        is_visible_js: JS statements (same calling convention) that must
            `return` whether the button should currently be shown.
        placement: "right_of" positions the button immediately to the
            right of the anchor element, top-aligned with it; "below"
            positions it directly under the anchor element's left edge;
            "above" positions it directly above the anchor element's own
            top-left corner (e.g. anchoring to a plot's rect.bg puts the
            button just above the chart's own drawing area, left-aligned
            with it - the same conventional spot Plotly's own default
            updatemenu buttons use, e.g. Plotting/DiveOCR504i.py's
            Linear/Log Scale buttons); "below_centered" positions it
            under the anchor element, horizontally centered on it rather
            than left-aligned (e.g. anchoring to a plot's x-axis title
            group puts the button below the plot, centered under the
            x-axis label - see DiveMagCal.py's plot_mag). Prefer
            anchoring to the actual element whose bottom/top edge should
            be cleared (an axis title, a chart's rect.bg) over a fixed
            pixel offset from some other element - axis label/margin
            content sizes vary by dataset and can collide with a naive
            fixed gap.
        gap_px: Pixel gap between the anchor element and the button.

    Returns:
        A post_script string for PlotUtilsPlotly.write_output_files.
    """
    return (
        _CLIPBOARD_BUTTON_TEMPLATE.replace(
            "__BUTTON_LABEL_JSON__", json.dumps(button_label)
        )
        .replace("__GET_COPY_TEXT_JS__", get_copy_text_js)
        .replace("__ANCHOR_ELEMENT_JS__", anchor_element_js)
        .replace("__IS_VISIBLE_JS__", is_visible_js)
        .replace(
            "__PLACEMENT_OFFSET_JS__",
            _CLIPBOARD_BUTTON_PLACEMENT_OFFSETS[placement].format(gap=gap_px),
        )
    )
