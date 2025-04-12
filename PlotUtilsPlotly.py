#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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

import io
import json
import os
import warnings

import brotli
import plotly
import plotly.graph_objects
import plotly.io

from BaseLog import log_warning

# IOP Standard Figure size
std_width = 1058
std_height = 894
std_scale = 1.0


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


def write_output_files(base_opts, base_file_name, fig):
    """
    Helper routine to output various file formats - .png and .div all the time
    and standalone .html and .svg based on conf file settings

    Input:
        base_opts - all options
        base_file_name - file name base for the output file names (i.e. no extension)
        fig - plotly figure object
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

    base_file_name = os.path.join(base_opts.plot_directory, base_file_name)

    ret_list = []

    if base_opts.full_html:
        # if plot_opts full_html
        output_name = base_file_name + ".html"
        fig.write_html(
            file=output_name,
            include_plotlyjs="cdn",
            full_html=True,
            auto_open=False,
            validate=True,
            config=std_config_dict,
            include_mathjax="cdn",
            auto_play=False,
        )
        ret_list.append(output_name)

    # For IOP site - raw div
    output_name = base_file_name + ".div"
    if base_opts.compress_div:
        fo_t = io.StringIO()
    else:
        fo_t = output_name

    fig.write_html(
        file=fo_t,
        include_plotlyjs=False,
        full_html=False,
        auto_open=False,
        validate=True,
        config=std_config_dict,
        include_mathjax="cdn",
        auto_play=False,
    )

    if base_opts.compress_div:
        fo_t.seek(0, 0)
        with open(output_name, "wb") as fo:
            fo.write(brotli.compress(fo_t.read().encode("utf-8")))
        fo_t.close()
    ret_list.append(output_name)

    def save_img_file(output_fmt):
        output_name = base_file_name + "." + output_fmt
        # No return code
        # TODO - for kelido 0.2.1 and python 3.10 (and later) we get this warning:
        #   File "/Users/gbs/.pyenv/versions/3.10.7/lib/python3.10/threading.py", line 1224, in setDaemon
        #   warnings.warn('setDaemon() is deprecated, set the daemon attribute instead',
        #   DeprecationWarning: setDaemon() is deprecated, set the daemon attribute instead
        #
        # Remove when kelido is updated
        with warnings.catch_warnings():
            warnings.filterwarnings("ignore")
            fig.write_image(
                output_name,
                format=output_fmt,
                width=std_width,
                height=std_height,
                scale=std_scale,
                validate=True,
                engine="kaleido",
            )
        return output_name

    if base_opts.save_png:
        ret_list.append(save_img_file("png"))

    if base_opts.save_jpg:
        ret_list.append(save_img_file("jpg"))

    if base_opts.save_webp:
        ret_list.append(save_img_file("webp"))

    if base_opts.save_svg:
        ret_list.append(save_img_file("svg"))

    def isnotebook():
        try:
            shell = get_ipython().__class__.__name__
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
