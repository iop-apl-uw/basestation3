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

import contextlib
import io
import json
import pathlib
import signal
import threading
import time
import types
import warnings
from collections.abc import Iterator
from typing import TYPE_CHECKING, Literal

import brotli
import kaleido
import PIL.Image
import plotly
import plotly.graph_objects
import plotly.io
from choreographer.errors import (
    BrowserClosedError,
    BrowserDepsError,
    BrowserFailedError,
    ChannelClosedError,
    ChromeNotFoundError,
)

from BaseLog import log_debug, log_error, log_info, log_warning

if TYPE_CHECKING:
    from BaseOpts import BaseOptions

# IOP Standard Figure size
std_width = 1058
std_height = 894
std_scale = 1.0

# Matches what vis is expecting
thumbnail_width = 185
thumbnail_height = 185

# Matches BaseOpts.plot_dive_timeout's default; used as the timeout for static
# image generation in call sites that have no base_opts (and thus no
# plot_dive_timeout/plot_mission_timeout) available.
DEFAULT_STATIC_IMAGE_TIMEOUT_SECS = 120

# Closing a healthy kaleido server (sentinel + thread exit) is near-instant;
# this only needs to be long enough to not fire on a healthy shutdown.
DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS = 30


class PlotTimeout(BaseException):
    """Raised when static image generation (kaleido/Chrome) exceeds its allotted time.

    Extends BaseException, not Exception, so the broad ``except Exception``
    blocks common throughout the plotting pipeline don't accidentally swallow
    it before it reaches the caller responsible for handling a timeout.
    """


def _raise_plot_timeout(signum: int, frame: types.FrameType | None) -> None:
    """Signal handler installed by static_image_timeout(); raises PlotTimeout.

    Args:
        signum: Signal number delivered (always signal.SIGALRM here).
        frame: Interrupted stack frame. Unused.

    Returns:
        None.

    Raises:
        PlotTimeout: Always.
    """
    raise PlotTimeout()


@contextlib.contextmanager
def static_image_timeout(seconds: int | None) -> Iterator[None]:
    """Bounds a block that may call into kaleido/Chrome with a SIGALRM timeout.

    Only one SIGALRM can be outstanding per process, so if an outer caller
    (e.g. BasePlot.py's plot_dives()/plot_mission()) already has an alarm
    running, this becomes a no-op passthrough that restores the outer alarm
    unchanged rather than clobbering it with a shorter- or longer-lived one.

    Args:
        seconds: Timeout in seconds. A falsy value (0 or None) disables the
            timeout entirely.

    Yields:
        None.

    Raises:
        PlotTimeout: If the protected block doesn't complete within
            `seconds` and no outer timeout is already active.
    """
    if not seconds:
        yield
        return

    remaining = signal.alarm(0)
    if remaining:
        # An outer static_image_timeout() (or BasePlot.py's own alarm) already
        # owns the process's single SIGALRM; defer to it instead of nesting.
        signal.alarm(remaining)
        yield
        return

    prev_handler = signal.signal(signal.SIGALRM, _raise_plot_timeout)
    signal.alarm(seconds)
    try:
        yield
    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, prev_handler)


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

    # Not every base_opts has plot_dive_timeout (only apps that add the
    # "Base"/"Reprocess"/"BasePlot"/"BaseDB" option groups do) - fall back to
    # the shared default so standalone callers (e.g. SimplePlotExtension.py,
    # MakePlotTSProfile.py, FlightModel.py) still get protection.
    image_timeout = getattr(
        base_opts, "plot_dive_timeout", DEFAULT_STATIC_IMAGE_TIMEOUT_SECS
    )
    try:
        with static_image_timeout(image_timeout):
            for opt_name, ext in formats:
                if getattr(base_opts, opt_name):
                    try:
                        ret_list.append(save_img_file(ext))
                    except Exception as e:
                        log_error(f"Failed to write out {base_file_name}.{ext}: {e}")
    except PlotTimeout:
        log_error(
            f"Timeout: static image generation for {base_file_name} exceeded timeout ({image_timeout})",
            alert="PLOT_TIMEOUT",
        )

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


def _bounded_close_global_server(timeout: float) -> None:
    """Best-effort close of kaleido's global server singleton, bounded by a timeout.

    kaleido's own ``GlobalKaleidoServer.close()`` joins its background render
    thread with no timeout, so a wedged thread (e.g. left mid-render by a
    previously-interrupted static_image_timeout()) hangs the caller forever.
    This runs that close() in a daemon thread and only waits up to `timeout`
    seconds for it, so callers can never be blocked longer than that no
    matter how wedged the background thread is.

    Args:
        timeout: Seconds to wait for the close to complete before giving up
            on it.

    Returns:
        None.
    """
    server = getattr(kaleido, "_global_server", None)
    if server is None:
        return

    def _close() -> None:
        with contextlib.suppress(Exception):
            server.close()

    closer = threading.Thread(target=_close, daemon=True)
    closer.start()
    closer.join(timeout)
    if closer.is_alive():
        log_error(
            f"Timeout: kaleido server shutdown did not complete within "
            f"{timeout}s (background render thread likely wedged) - "
            "abandoning it and starting fresh",
            alert="PLOT_TIMEOUT",
        )

    # Dynamically capture the true class type (independent of Kaleido
    # version) and re-instantiate a completely fresh copy - unconditionally,
    # since the old instance may still be wedged in the abandoned close()
    # above and must never be reused as the process-wide singleton.
    ServerClass = server if isinstance(server, type) else server.__class__
    kaleido._global_server = ServerClass()


class KaleidoServer:
    """Manages the lifecycle, exception handling, and health of the global Kaleido server.

    This class handles starting, stopping, and resetting the Kaleido global sync
    server, trapping background thread exceptions, and exporting static plots.

    Attributes:
        server_running (bool): Tracks the current runtime state of the server.
        base_opts (Any): Configuration object containing format flags (e.g., save_png).
    """

    # Class-level configuration for supported image formats
    FORMATS: list[str] = [
        "save_png",
        "save_jpg",
        "save_webp",
        "save_svg",
    ]

    def __init__(self, base_opts: BaseOptions) -> None:
        """Initializes the KaleidoServer with configuration options.

        Args:
            base_opts (Any): Configuration object containing target format boolean flags.
        """
        self.server_running: bool = False
        self.base_opts: BaseOptions = base_opts

    def should_start_kaleido(self) -> bool:
        """Determines if the Kaleido server needs to start based on version compatibility.

        Returns:
            bool: True if the Kaleido version is >= 1.0.0 or if no version string
            exists (indicating a modern version), False otherwise.
        """
        has_version = hasattr(kaleido, "__version__")
        return (has_version and kaleido.__version__ >= "1.0.0") or not has_version

    def is_static_plot_generation_enabled(self) -> bool:
        """Checks if any static image export options are currently enabled.

        Returns:
            bool: True if at least one save format flag evaluates to True.
        """
        return any(getattr(self.base_opts, fmt, False) for fmt in self.FORMATS)

    def reset_kaleido_server(self) -> None:
        """Resets the global Kaleido server instance to a clean post-import state.

        Safely breaks down any open communication channels (bounded, so a
        wedged background render thread can't hang this call - see
        _bounded_close_global_server()) before re-instantiating a fresh copy
        of the server class type.
        """
        if getattr(kaleido, "_global_server", None) is None:
            log_info("No global server instance found to reset.")
            return

        _bounded_close_global_server(DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS)
        log_debug(
            "Kaleido global server has been dynamically reset to a clean post-import state."
        )

    def is_kaleido_global_server_running(self) -> tuple[bool, str]:
        """Checks if the persistent global server thread is active and warm.

        Returns:
            tuple[bool, str]: A tuple containing:
                - bool: True if the server thread is completely active, False otherwise.
                - str: A descriptive status or error message outlining health state.
        """
        if not self.should_start_kaleido():
            return True, ""

        server = getattr(kaleido, "_global_server", None)
        if server is None:
            return False, "Global server has not been initialized."

        # Verify the thread health
        thread = getattr(server, "_thread", None)
        if thread is None:
            return (
                False,
                "Server state says running, but the background thread object is missing.",
            )

        if not thread.is_alive():
            return (
                False,
                "The background engine thread has died (likely due to ChromeNotFoundError).",
            )

        # Normalize handle for whether is_running is a property or a callable method
        is_running_attr = getattr(server, "is_running", False)
        is_running = is_running_attr() if callable(is_running_attr) else is_running_attr

        if not is_running:
            return False, "Kaleido state indicates the server is NOT running."

        return True, "Success! The persistent global server thread is active and warm."

    def thread_exception_handler(self, args: threading.ExceptHookArgs) -> None:
        """Captures background thread crashes relating to Chromium errors.

        Args:
            args (threading.ExceptHookArgs): Arguments passed automatically by the
                threading hook containing exception details.
        """
        exc_type = args.exc_type
        exc_value = str(args.exc_value)

        chrome_errors = (
            BrowserClosedError,
            BrowserDepsError,
            BrowserFailedError,
            ChannelClosedError,
            ChromeNotFoundError,
        )

        if exc_type in chrome_errors:
            log_error(
                f"Problem with Chrome installation for static plot generation ({exc_type.__name__}, {exc_value})",
                alert="CHROME_ISSUE",
                max_count=1,
            )
            return

        threading.__excepthook__(args)

    def start_kaleido_global_server(self) -> None:
        """Registers the global hook and safely boots up the background server.

        If initialization fails or the server does not register as warm after a
        brief delay, it attempts a recovery reset.
        """
        if not self.is_static_plot_generation_enabled() or self.server_running:
            return

        # Register the global thread exception trap
        original_hook = threading.excepthook
        threading.excepthook = self.thread_exception_handler

        kaleido.start_sync_server(n=1)
        time.sleep(0.1)  # Let the server startup

        status, msg = self.is_kaleido_global_server_running()
        if not status:
            log_debug("Resetting kaleido")
            # This step is needed to back out from the failure in kaleido.start_sync_server(n=1)
            self.reset_kaleido_server()
            self.server_running = False
        else:
            self.server_running = True
        threading.excepthook = original_hook

    def stop_kaleido_global_server(self) -> None:
        """Stops the underlying synchronized server execution.

        Bounded (see _bounded_close_global_server()) so a wedged background
        render thread can't hang the caller forever - this was the root
        cause of a multi-hour production hang (sg180, 2026-08-09) where an
        earlier per-plot timeout left the shared kaleido thread wedged, and
        the unguarded shutdown here then blocked forever.
        """
        if self.server_running:
            _bounded_close_global_server(DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS)
            self.server_running = False
