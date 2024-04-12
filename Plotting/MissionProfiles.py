#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2024  University of Washington.
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

# fmt: off

""" Plots sections of sensor data
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing
import time

import plotly

import os
import yaml
import cmocean
import numpy
import ExtractTimeseries

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils

from BaseLog import log_error, log_warning, log_info
from Plotting import plotmissionsingle


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
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True, dbcon=None
) -> tuple[list, list]:

    if not generate_plots:
        return ([], [])

    section_file_name = os.path.join(base_opts.mission_dir, "sections.yml")
    if not os.path.exists(section_file_name):
        return ([], [])

    with open(section_file_name, "r") as f:
        x = yaml.safe_load(f.read())

    if "variables" not in x or len(x["variables"]) == 0:
        log_error(f"No 'variables' key found in {section_file_name} - not plotting")
        return ([], [])

    if "sections" not in x or len(x["sections"]) == 0:
        log_error(f"No 'sections' key found in {section_file_name} - not plotting")
        return ([], [])

    if dbcon is None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])

        log_info("mission_profiles db opened (ro)")
    else:
        conn = dbcon

    try:
        cur = conn.cursor() 
        cur.execute("SELECT dive FROM dives ORDER BY dive DESC LIMIT 1;")
        res = cur.fetchone()
        cur.close()
        if res:
            latest = res[0]
        else:
            log_warning("No dives found")
            if dbcon is None:
                conn.close()
                log_info("mission_profiles db closed")
            return([], [])
    except Exception:
        log_error("Could not fetch data", "exc")
        if dbcon is None:
            conn.close()
            log_info("mission_profiles db closed")
        return ([], [])

    if dbcon is None:
        conn.close()
        log_info("mission_profiles db closed")

    #print(latest)
 
    figs = []
    outs = []

    ncname = Utils.get_mission_timeseries_name(base_opts)

    try:
        nci = Utils.open_netcdf_file(ncname, "r")
    except Exception:
        log_error(f"Unable to open {ncname}", "exc")
        return ([], [])

    # Simple hack for case where the most recent dives aren't in the timeseries file
    # (due to processing errors typically)
    latest = min(nci.variables["dive_number"][-1], latest)

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
            decimals = getValue(x, 'decimals', sk, vk, None)

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
                                           top, bott, binZ, None, extnci=nci, x=prev_x)

            if not d:
                log_warning(f"Could not extract timeseries for {vk} - skipping")
                continue
            
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

            # profile_times = []
            # for tt in d['avg_time']:
            #     profile_times.append(time.strftime("%Y-%m-%dT%H:%M", time.gmtime(tt)))

            # Time axis
            timevals = []
            timetext = []

            if (max(d['avg_time']) - min(d['avg_time'])) / 86400 > 7:
                divisor = 10
                fmt = "%Y-%m-%d"
            else:
                divisor = 7
                fmt = "%Y-%m-%dT%H:%M"
            incr = len(d['avg_time']) // divisor
            if incr == 0:
                incr = 1
               
            for tt in d['avg_time'][::incr]:
                timetext.append(time.strftime(fmt, time.gmtime(tt)))
            for dd in d['dive'][::incr]:                    
                timevals.append(dd - 0.5)

            # Trim off the ends of the range so they don't interfere with the colorbar
            for ii in range(len(timevals)):
                if timevals[ii] <= ((max(d['dive']) - min(d['dive'])) * 0.1) + min(d['dive']) - 0.5 or timevals[ii] == min(d['dive']) - 0.5:
                    timetext[ii] = " "
                if timevals[ii] >= ((max(d['dive']) - min(d['dive'])) * 0.9) + min(d['dive']) - 0.5 or timevals[ii] == max(d['dive']) - 0.5:
                    timetext[ii] = " "

            unit_tag = f" {units}" if units else ""

            if decimals is not None:
                z = d[vk].round(decimals=decimals)
                format_spec = f":.{decimals}f"
            else:
                z = d[vk]
                format_spec = ""
            props = {
                        'x': numpy.array(d['dive']) - 0.5,
                        'y': d['depth'],
                        'z': z,
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
                        "hovertemplate" : f"Dive %{{x:.0f}}<br>Depth %{{y}} meters<br>%{{z{format_spec}}}{unit_tag}<extra></extra>",
                    }

            if zmin is not None:
                props['zmin'] = zmin
            if zmax is not None:
                props['zmax'] = zmax

            fig.add_trace(plotly.graph_objects.Contour( **props ) )

            fig.add_trace(
                {
                    "name": "Hidden Trace for Profile Time",
                    "x": timevals,
                    "y": numpy.zeros(len(timevals)) * numpy.nan,
                    "xaxis": "x2",
                    "yaxis": "y1",
                    "mode": "markers",
                    "showlegend": False,
                }
            )

            title_text = f"{mission_str}<br>{vk}<br>section {sk}: {start}-{stop}"

            if flip:
                timevals.reverse()
                timetext.reverse()

            #print(timevals, timetext)
 
            fig.update_layout(
                {
                    "xaxis": {
                        "title": "dive",
                        "showgrid": False,
                        "autorange": "reversed" if flip else True,
                    },
                    "xaxis2": {
                        # The title takes up too much room
                        #"title": "Profile Time",
                        "title": "",
                        "showgrid": False,
                        "overlaying": "x1",
                        "side": "top",
                        "range": [max(timevals), min(timevals)] if flip else [min(timevals), max(timevals)],
                        "tickmode": "array",
                        "tickvals": timevals,
                        "ticktext": timetext,
                    },
                    "yaxis": {
                        "title": "depth",
                        "showgrid": False,
                        "tickformat": "d",
                        "autorange": "reversed",
                        "domain": [0, 0.95],
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


    return (
        figs,
        outs,
    )
