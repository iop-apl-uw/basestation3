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
import threading
import time
import warnings
from typing import TYPE_CHECKING

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

    for opt_name, ext in formats:
        if getattr(base_opts, opt_name):
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

        Safely breaks down any open communication channels before re-instantiating
        a fresh copy of the server class type.
        """
        server = getattr(kaleido, "_global_server", None)

        if server is not None:
            with contextlib.suppress(Exception):
                # 1. Safely break down any open communication channels
                server.close()

            # 2. Dynamically capture the true Class type (independent of Kaleido version)
            ServerClass = server if isinstance(server, type) else server.__class__

            # 3. Re-instantiate a completely fresh copy of that class using ()
            kaleido._global_server = ServerClass()
            log_debug(
                "Kaleido global server has been dynamically reset to a clean post-import state."
            )
        else:
            log_info("No global server instance found to reset.")

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
        """Stops the underlying synchronized server execution."""
        if self.server_running:
            kaleido.stop_sync_server()
            self.server_running = False
