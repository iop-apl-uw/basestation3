#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022, 2023 by University of Washington.  All rights reserved.
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

""" Plots sections of sensor data
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing
import sqlite3

import plotly

import os
import yaml
import BaseDB
import Globals
import cmocean
import numpy
import ExtractTimeseries

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils

from BaseLog import log_error, log_warning
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

def getValue(x, v, sk, vk, fallback):
    if v in x['sections'][sk]:
        y = x['sections'][sk][v]
    elif v in x['variables'][vk]:
        y = x['variables'][vk][v]
    elif v in x['defaults']:
        y = x['defaults'][v]
    else:
        y = fallback

    return y

def cmocean_to_plotly(cmapname, pl_entries):
    maps = { "thermal": cmocean.cm.thermal, "haline": cmocean.cm.haline, "solar": cmocean.cm.solar,
             "ice": cmocean.cm.ice, "gray": cmocean.cm.gray, "oxy": cmocean.cm.oxy, "deep": cmocean.cm.deep,
             "dense": cmocean.cm.dense, "algae": cmocean.cm.algae, "matter": cmocean.cm.matter,
             "turbid": cmocean.cm.turbid, "speed": cmocean.cm.speed, "amp": cmocean.cm.amp,
             "tempo": cmocean.cm.tempo, "phase": cmocean.cm.phase, "balance": cmocean.cm.balance, 
             "delta": cmocean.cm.delta, "curl": cmocean.cm.curl }

    if cmapname in maps:
        cmap = maps[cmapname]
    else:
        cmap = cmocean.cm.thermal

    h = 1.0/(pl_entries-1)
    pl_colorscale = []

    for k in range(pl_entries):
        C = list(map(numpy.uint8, numpy.array(cmap(k*h)[:3])*255))
        pl_colorscale.append([k*h, 'rgb'+str((C[0], C[1], C[2]))])

    return pl_colorscale

@plotmissionsingle
def mission_profiles(
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True
) -> tuple[list, list]:

    if not generate_plots:
        return ([], [])

    section_file_name = os.path.join(base_opts.mission_dir, "sections.yml")
    if not os.path.exists(section_file_name):
        return ([], [])

    with open(section_file_name, "r") as f:
        x = yaml.safe_load(f.read())

    if not "variables" in x or len(x["variables"]) == 0:
        log_error(f"No 'variables' key found in {section_file_name} - not plotting")
        return ([], [])

    if not "sections" in x or len(x["sections"]) == 0:
        log_error(f"No 'sections' key found in {section_file_name} - not plotting")
        return ([], [])

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    try:
        cur = conn.cursor() 
        cur.execute("SELECT dive FROM dives ORDER BY dive DESC LIMIT 1;")
        res = cur.fetchone()
        latest = res[0]
        cur.close()
    except Exception as e:
        print(e)
        conn.close()
        return ([], [])

    print(latest)
 
    figs = []
    outs = []

    ncname = Utils.get_mission_timeseries_name(base_opts)

    try:
        nci = Utils.open_netcdf_file(ncname, "r")
    except:
        print(f"Unable to open {ncname}")
        return ([], [])

    for vk in list(x['variables'].keys()):
        prev_x = None
        for sk in list(x['sections'].keys()):

            start = getValue(x, 'start', sk, vk, 1)
            step = getValue(x, 'step',   sk, vk, 1)
            stop = getValue(x, 'stop',   sk, vk, -1)
            top  = getValue(x, 'top',    sk, vk, 0)
            bott = getValue(x, 'bottom', sk, vk, 990)
            binZ = getValue(x, 'bin',    sk, vk, 5)
            flip = getValue(x, 'flip',   sk, vk, False)
            whch = getValue(x, 'which',  sk, vk, 4)
            cmap = getValue(x, 'colormap', sk, vk, 'thermal')
            zmin = getValue(x, 'min', sk, vk, None)
            zmax = getValue(x, 'max', sk, vk, None)
            units = getValue(x, 'units', sk, vk, None)
            fill  = getValue(x, 'fill', sk, vk, False)

            if stop == -1 or stop >= latest:
                stop = latest
                force = True
            else:
                force = False

            fname = f"sg_{vk}_section_{sk}"
            fullname = os.path.join(base_opts.mission_dir, f"plots/{fname}.webp")
            if os.path.exists(fullname) and not force:
                continue

            fig = plotly.graph_objects.Figure()
 
            (d, prev_x) = ExtractTimeseries.timeSeriesToProfile(vk, whch,
                                           start, stop, step,
                                           top, bott, binZ, None, nci=nci, x=prev_x)

            
            contours={
                        "coloring": "heatmap",
                        "showlabels": True,
                        "labelfont": 
                        {
                            "family": "Raleway",
                            "size": 12,
                            "color": "white"
                        },
                     }

            props = {
                        'x': d['dive'],
                        'y': d['depth'],
                        'z': d[vk],
                        'contours_coloring': 'heatmap',
                        'colorscale':        cmocean_to_plotly(cmap, 100),
                        'connectgaps':       fill,
                        'contours':          contours,
                        "colorbar": {
                            "title": {
                                "text": units,
                                "side": "top",
                            },
                            # "thickness": 0.02,
                            # "thicknessmode": "fraction",
                        },
                    }

            if zmin is not None:
                props['zmin'] = zmin
            if zmax is not None:
                props['zmax'] = zmax

            fig.add_trace(plotly.graph_objects.Contour( **props ) )

            title_text = f"{mission_str}<br>{vk}<br>section {sk}: {start}-{stop}"
 
            fig.update_layout(
                {
                    "xaxis": {
                        "title": "dive",
                        # "title": units,
                        "showgrid": False,
                        "autorange": "reversed" if flip else True,
                    },
                    "xaxis2": {
                        "title": units,
                        "showgrid": False,
                        "side": "top",
                        "overlaying": "x1",
                    },

                    "yaxis": {
                        "title": "depth",
                        "showgrid": False,
                        "tickformat": "d",
                        "autorange": "reversed",
                    },
                    "title": {
                        "text": title_text,
                        "xanchor": "center",
                        "yanchor": "top",
                        "x": 0.5,
                        "y": 0.95,
                    },
                    "margin": {
                        "b": 120,
                    },
                },
            )

            figs.append(fig)
            out = PlotUtilsPlotly.write_output_files(
                        base_opts,
                        fname,
                        fig,
                  ),
            outs.append(out)

    conn.close()

    return (
        figs,
        outs,
    )
