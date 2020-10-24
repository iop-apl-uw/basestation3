##
## Copyright (c) 2006-2020 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

"""Supporting routines for creating plots from netCDF data
"""

import os
import sys
import json
import plotly
import plotly.graph_objects
import plotly.io

import Utils
from BaseLog import *

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


def write_output_files(plot_conf, base_file_name, fig):
    """
    Helper routine to output various file formats - .png and .div all the time
    and standalone .html and .svg based on conf file settings

    Input:
        plot_conf - configuration object
        base_file_name - file name base for the output file names (i.e. no extension)
        fig - plotly figure object
    Returns:
        List of fully qualified filenames that have been generated.
    """
    std_config_dict = {
        "modeBarButtonsToRemove": ["lasso2d", "select2d"],
        "scrollZoom": True,
    }

    if plot_conf.plot_directory is None:
        log_warning("plot_directory not specified - bailing out")
        return []

    base_file_name = os.path.join(plot_conf.plot_directory, base_file_name)

    ret_list = []

    if plot_conf.full_html:
        # if plot_opts full_html
        output_name = base_file_name + ".html"
        fig.write_html(
            file=output_name,
            include_plotlyjs="cdn",
            full_html=True,
            auto_open=False,
            validate=True,
            config=std_config_dict,
            include_mathjax = 'cdn',
        )
        ret_list.append(output_name)

    # For IOP site - raw div
    output_name = base_file_name + ".div"
    fig.write_html(
        file=output_name,
        include_plotlyjs=False,
        full_html=False,
        auto_open=False,
        validate=True,
        config=std_config_dict,
        include_mathjax = 'cdn'
    )
    ret_list.append(output_name)

    def save_img_file(output_fmt):
        output_name = base_file_name + "." + output_fmt
        # No return code
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

    if plot_conf.save_png:
        ret_list.append(save_img_file("png"))

    if plot_conf.save_svg:
        ret_list.append(save_img_file("svg"))

    return ret_list
