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

    fig_json=json.dumps({'data': redata,'layout': relayout})

    if fpath:
        with open(fpath, 'w') as f:
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
    with open(fpath, 'r') as f:
        v = json.loads(f.read())

    fig = plotly.graph_objects.Figure(data=v['data'], layout=v['layout'])
    #fig.show()
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
    std_config_dict = {'modeBarButtonsToRemove': ['lasso2d', 'select2d'],
                       'scrollZoom': True,
    }
    
    if plot_conf.plot_directory is None:
        log_warning("plot_directory not specified - bailing out")
        return []
    
    base_file_name = os.path.join(plot_conf.plot_directory, base_file_name)

    ret_list = []
    
    if plot_conf.full_html:
        # if plot_opts full_html
        output_name = base_file_name + '.html'
        fig.write_html(file = output_name, include_plotlyjs = 'cdn', full_html = True, auto_open = False, validate = True,
                       config = std_config_dict)
        ret_list.append(output_name)

    # For IOP site - raw div
    output_name = base_file_name + '.div'
    fig.write_html(file = output_name, include_plotlyjs = False, full_html = False, auto_open = False, validate = True,
                   config = std_config_dict)
    ret_list.append(output_name)

    def save_img_file(output_fmt):
        #if sys.platform == 'darwin':
        if 1:
            # This path appears to be the most solid for OSX and linux (for now)
            if 'linux' in sys.platform:
                # orca - the app that creates the .png files, opens /tmp/orca-build with 775 for permissions:
                # https://github.com/plotly/orca/issues/140
                # this causes the orca app to merely hang on execution - very helpful indeed - so we check for the
                # permissions and warn if it looks bad
                orca_build_dir = "/tmp/orca-build"
                if os.access(orca_build_dir, os.F_OK):
                    if not os.access(orca_build_dir, os.W_OK):
                        log_error("%s not writable - the call to orca to convert image will hang!!!! Bailing out" % orca_build_dir)
                        return None
                
            json_file_name = base_file_name + '.json'
            plotlyfig2json(fig, fpath = json_file_name)
            output_name = base_file_name + '.' + output_fmt
            head, tail = os.path.split(output_name)
            if head == '' or head is None:
                head = '.'
            cmd_line = "orca graph %s --width %d --height %d --scale 1.0 -d %s -o %s --parallel-limit 0" \
                       % (json_file_name, std_width, std_height, head, tail)
            #log_info("Running %s" % cmd_line)
            try:
                ret_code = Utils.check_call(cmd_line, use_shell=True)
            except:
                log_info("Except in run", 'exc')
            #log_info("Done")
            os.remove(json_file_name)
            if ret_code:
                log_error("%s returned %d" % (cmd_line, ret_code))
                return None
            else:
                return output_name
        else:
            # 2020/01/02 GBS - this code path runs with a plotly and ploty_orca installed from
            # anaconda (on rendezvous), but hangs here.  Note in both cases, xvfb was installed and
            # #plotly.io.orca.config.use_xvfb = True
            # was set.
            output_name = base_file_name + '.' + output_fmt
            fig.write_image(file = output_name, format = output_fmt, width = std_width, height = std_height, scale = std_scale, validate = True)
            return output_name

    ret_list.append(save_img_file('png'))
    
    if plot_conf.save_svg:
        ret_list.append(save_img_file('svg'))
    
    return ret_list
