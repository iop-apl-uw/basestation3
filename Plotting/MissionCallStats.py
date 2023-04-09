#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023  University of Washington.
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

""" Plots file transfer stats from comm.log
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import os
import sys
import typing

import plotly
import scipy
import numpy as np

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import CommLog
import PlotUtilsPlotly

from BaseLog import log_error, log_info
from Plotting import plotmissionsingle

DEBUG_PDB = "darwin" in sys.platform
# DEBUG_PDB = False

call_plot_map_nt = collections.namedtuple("call_plot_map_nt", ["description", "color"])

call_plot_map = {
    "pmd": call_plot_map_nt("PMAR data", "lightgreen"),
    "tmd": call_plot_map_nt("TMICRO data", "darkgreen"),
    "scd": call_plot_map_nt("SCICON data", "purple"),
    "sgd": call_plot_map_nt("SG data", "cyan"),
    "sgk": call_plot_map_nt("SG capture", "deepskyblue"),
    "sgl": call_plot_map_nt("SG log", "powderblue"),
    "sgp": call_plot_map_nt("SG pdos", "saddlebrown"),
    "std": call_plot_map_nt("SG selftest data", "lightgray"),
    "stk": call_plot_map_nt("SG selftest cap", "darkgray"),
    "stl": call_plot_map_nt("SG selftest log", "silver"),
    "cpd": call_plot_map_nt("ADCP_CP data", "darkred"),
    "esd": call_plot_map_nt("ADCP_ES data", "red"),
}


@plotmissionsingle
def mission_callstats(
    base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True
) -> tuple[list, list]:
    """Plots file transfer stats from comm.log"""
    if not generate_plots:
        return ([], [])

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"), base_opts
    )
    if comm_log is None:
        log_error("Could not process comm.log -- bailing out")
        return ([], [])

    # Collect stats
    files_transfered_num = []
    files_transfered = []
    bytes_transfered = []
    secs_transfered = []
    crc_errors = []
    dive_number = []
    crc_errors_present = False
    # rate = []
    for session in comm_log.sessions:
        # log_info(session.transfered_size)
        files_transfered_num.append(len(list(session.transfered_size.keys())))
        files_transfered.append(session.transfered_size)
        secs = 0
        nbytes = 0
        for k in session.file_stats:
            fs = session.file_stats[k]
            if fs.bps > 0:
                secs += fs.receivedsize / fs.bps
            nbytes += fs.receivedsize
        bytes_transfered.append(nbytes)
        secs_transfered.append(secs)
        crc_errors.append(len(list(session.crc_errors.keys())))
        if len(list(session.crc_errors.keys())):
            crc_errors_present = True
        dive_number.append(session.dive_num)

    t = np.linspace(
        start=0,
        stop=len(files_transfered_num),
        num=len(files_transfered_num),
        endpoint=False,
    )

    # Find all unique types
    file_types = set()
    for fs in files_transfered:
        for f in fs:
            head, _ = os.path.splitext(f)
            if len(head) == 8:
                if head[6:7] == "a" or head[6:7] == "b":
                    tmp = "d"
                else:
                    tmp = head[6:7]
                tag = "%s%s" % (head[0:2], tmp)
                file_types.add(tag)

    log_info("File types found %s" % file_types)

    file_type_tots = collections.OrderedDict()
    file_type_count = collections.OrderedDict()

    for ft in file_types:
        file_type_tots[ft] = np.zeros(len(files_transfered_num))
        file_type_count[ft] = np.zeros(len(files_transfered_num))

    files_transfered_bytes = np.zeros(len(files_transfered_num))

    import pdb

    pdb.set_trace()

    # Walk the list
    for ii in range(len(files_transfered)):
        for f in list(files_transfered[ii].keys()):
            head, _ = os.path.splitext(f)
            if len(head) == 8:
                if head[6:7] == "a" or head[6:7] == "b":
                    tmp = "d"
                else:
                    tmp = head[6:7]
                for ty in list(file_type_tots.keys()):
                    if head[0:2] == ty[0:2] and tmp == ty[2:3]:
                        # log_info(files_transfered[ii])
                        # log_info(files_transfered[ii][f])
                        if isinstance(files_transfered[ii][f], int):
                            # Raw
                            file_type_tots[ty][ii] += files_transfered[ii][f]
                            files_transfered_bytes[ii] += files_transfered[ii][f]
                            file_type_count[ty][ii] += 1
                        else:
                            # XModem
                            for ft in files_transfered[ii][f]:
                                file_type_tots[ty][ii] += ft.block_len
                                files_transfered_bytes[ii] += ft.block_len
                                file_type_count[ty][ii] += 1

    fig = plotly.graph_objects.Figure()

    # Clean up dive_number array - deal with previous stuff in comm.log
    dive_nums = dive_number.copy()
    for ii in range(len(dive_nums)):
        if dive_nums[ii] is None:
            continue
        if dive_nums[ii] > dive_nums[-1] or dive_nums[ii] < 0:
            dive_nums[ii] = 0

    # Interpolate over missing dive numbers
    dive_nums_i = list(
        filter(
            lambda i: dive_nums[i] is not None,
            range(len(dive_nums)),
        )
    )
    dive_f = scipy.interpolate.interp1d(
        np.array(dive_nums_i),
        np.array(dive_nums)[dive_nums_i],
        kind="nearest",
        bounds_error=False,
        fill_value=0,
    )

    for ii in t:
        if dive_nums[int(ii)] is None:
            dive_nums[int(ii)] = int(dive_f(int(ii)))

    # Select some points on the graph for the dive numbers
    divevals = []
    divetext = []
    for ii in t[:: len(t) // 7]:
        divevals.append(ii)
        divetext.append(dive_nums[int(ii)])
    divevals.append(t[-1])
    divetext.append(dive_nums[-1])

    fig.add_trace(
        {
            "name": "Hidden Trace for Dive Number",
            "x": t,
            "y": t,
            "xaxis": "x2",
            "yaxis": "y1",
            "mode": "markers",
            "visible": False,
        }
    )

    fig.add_trace(
        {
            "name": "Total files transfered",
            "x": t,
            "y": files_transfered_num,
            "meta": dive_number,
            "yaxis": "y1",
            "mode": "lines",
            "line": {"dash": "dash", "width": 1, "color": "Black"},
            "hovertemplate": "Total transfered<br>Call Number %{x:.0f}<br>Dive Number %{meta:.0f}<br>count %{y:.0f}<extra></extra>",
        }
    )

    fig.add_trace(
        {
            "name": "Total bytes transfered",
            "x": t,
            "y": files_transfered_bytes,
            "meta": dive_number,
            "yaxis": "y2",
            "mode": "lines",
            "line": {"dash": "solid", "width": 1, "color": "Black"},
            "hovertemplate": "Total transfered<br>Call Number %{x:.0f}<br>Dive Number %{meta:.0f}<br> bytes %{y:.0f}<extra></extra>",
        }
    )

    if crc_errors_present:
        fig.add_trace(
            {
                "name": "XMODEM CRC Errors",
                "x": t,
                "y": crc_errors,
                "meta": dive_number,
                "yaxis": "y1",
                "mode": "lines",
                "line": {"dash": "solid", "width": 1, "color": "Red"},
                "hovertemplate": "Call Number %{x:.0f}<br>Dive Number %{meta:.0f}<br>XMODEM CRC Errors %{y:.0f} num<extra></extra>",
            }
        )

    for ty in file_type_tots:
        if ty in call_plot_map:
            # (pl,) = plt.plot(t, file_type_tots[ty], color=call_plot_map[ty].color)
            fig.add_trace(
                {
                    "name": f"{call_plot_map[ty].description} (bytes)",
                    "x": t,
                    "y": file_type_tots[ty],
                    "meta": dive_number,
                    "yaxis": "y2",
                    "mode": "lines",
                    "line": {
                        "dash": "solid",
                        "width": 1,
                        "color": call_plot_map[ty].color,
                    },
                    "hovertemplate": "Call Number %{x:.0f}<br>Dive Number %{meta:.0f}<br>"
                    + call_plot_map[ty].description
                    + " %{y:.0f} bytes<extra></extra>",
                }
            )

    for ty in file_type_count:
        if ty in call_plot_map:
            fig.add_trace(
                {
                    "name": f"{call_plot_map[ty].description} (count)",
                    "x": t,
                    "y": file_type_count[ty],
                    "meta": dive_number,
                    "yaxis": "y1",
                    "mode": "lines",
                    "line": {
                        "dash": "dash",
                        "width": 1,
                        "color": call_plot_map[ty].color,
                    },
                    "hovertemplate": "Call Number %{x:.0f}<br>Dive Number %{meta:.0f}<br>"
                    + call_plot_map[ty].description
                    + " %{y:.0f} count<extra></extra>",
                }
            )

    title_text = f"{mission_str}<br>Download Statistics vs Call Num"
    fig.update_layout(
        {
            "xaxis": {
                # "title": "Dive Number",
                "title": "Call Number",
                "showgrid": True,
                # "side": "top"
                # "domain": [0.0, 0.925],
            },
            "xaxis2": {
                "title": "Dive Number",
                "showgrid": False,
                "overlaying": "x1",
                "side": "top",
                "range": [min(t), max(t)],
                "tickmode": "array",
                "tickvals": divevals,
                "ticktext": divetext,
                # "position": 0.925,
            },
            "yaxis": {
                "title": "Count",
                "showgrid": True,
                # Fixed ratio
                # "scaleanchor": "x",
                # "scaleratio": (plot_lon_max - plot_lon_min)
                # / (plot_lat_max - plot_lat_min),
                # Fixed ratio
            },
            "yaxis2": {
                "title": "Bytes",
                "showgrid": False,
                "overlaying": "y1",
                "side": "right",
                # "position": 0.925,
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 150,
            },
            "legend": {
                "x": 1.075,
                "y": 1,
            }
            # "annotations": tuple(l_annotations),
        },
    )

    # l_artists = []
    # l_labels = []

    # (pl,) = plt.plot(t, files_transfered_num, "k")
    # l_artists.append(pl)
    # l_labels.append("Number files downloaded (count)")

    # if crc_errors_present:
    #     (pl,) = plt.plot(t, crc_errors, "r")
    #     l_artists.append(pl)
    #     l_labels.append("XMODEM CRC Errors")

    # ax = plt.gca()
    # ax.xaxis.grid(True)
    # ax.yaxis.grid(True)

    # plt.ylabel("Count")
    # plt.xlabel("Call Number")

    # ax2 = plt.twinx()
    # ax2.xaxis.set_major_locator(plt.MaxNLocator(10))
    # # ay2 = plt.twiny()
    # # ay2.xaxis.tick_top()
    # # ay2.grid(True)

    # (pl,) = plt.plot(t, bytes_transfered, "b")
    # l_artists.append(pl)
    # l_labels.append("Total downloaded (bytes)")

    # for ty in list(file_type_tots.keys()):
    #     if ty in list(call_plot_map.keys()):
    #         (pl,) = plt.plot(t, file_type_tots[ty], color=call_plot_map[ty].color)
    #         l_artists.append(pl)
    #         l_labels.append(call_plot_map[ty].description)

    # plt.ylabel("Bytes")
    # ay2 = plt.twiny()
    # ay2.xaxis.tick_top()
    # # ay2.grid(True)

    # #
    # # An attempt to remap the x-axis to be dive number
    # #
    # ay2.xaxis.set_major_locator(plt.MaxNLocator(10))
    # call_nums = ax.xaxis.get_majorticklocs()
    # labels = []

    # # if(comm_log.sessions[0].dive_num is not None):
    # #    labels.append(comm_log.sessions[0].dive_num)

    # # First and last are misleading
    # labels.append("")
    # if len(call_nums) > 3:
    #     for c in call_nums[1:-1]:
    #         if int(c) >= 0 and int(c) < len(comm_log.sessions):
    #             dn = comm_log.sessions[int(c)].dive_num
    #         else:
    #             dn = None
    #         if dn is not None:
    #             labels.append("%d" % comm_log.sessions[int(c)].dive_num)
    #         else:
    #             labels.append("")
    # # labels.append(comm_log.sessions[-1].dive_num)
    # labels.append("")
    # ay2.set_xticklabels(labels)
    # plt.xlabel("Dive number")

    # font = FontProperties(size="xx-small")

    # lg = plt.legend(
    #     l_artists, l_labels, loc="upper left", fancybox=True, prop=font, numpoints=1
    # )

    # lg.get_frame().set_alpha(0.5)

    # plt.suptitle("%s Download Statistics vs Call Num" % (mission_dive_str,))
    # output_name = "eng_download_stats.png"

    # if base_opts.plot_directory:
    #     output_name = os.path.join(base_opts.plot_directory, output_name)

    # plt.savefig(output_name, format="png")
    # if base_opts.save_svg:
    #     plt.savefig(output_name.replace(".png", ".svg"), format="svg")
    # ret_val.append(output_name)
    # if base_opts.save_svg:
    #     ret_val.append(output_name.replace(".png", ".svg"))
    # plt.clf()

    out = (
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "eng_download_stats",
            fig,
        ),
    )
    return (
        [fig],
        [out],
    )
