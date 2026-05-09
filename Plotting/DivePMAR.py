#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2025, 2026  University of Washington.
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

"""Plots PMAR data"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import pathlib
import time
import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
from BaseLog import log_debug, log_error, log_info, log_warning
from Plotting import plotdivesingle

# import QC


def pmar_create_stats_lines(dive_nc_file, ch_tag, plot_type):
    """Creates the line of text for all the statistics included in the pmar eng files"""
    profile_stats = collections.OrderedDict()
    dive_stats = collections.OrderedDict()
    climb_stats = collections.OrderedDict()

    # Half-profile independent stats
    for statistic in ("gain", "gain0", "gain1", "cutoff", "osc", "samplerate"):
        stat_tag = f"{statistic}{ch_tag}"
        var_nm = f"pmar_{stat_tag}"
        if var_nm in dive_nc_file.variables:
            profile_stats[stat_tag] = climb_stats[stat_tag] = dive_stats[stat_tag] = (
                dive_nc_file.variables[var_nm].getValue()
            )

    # Half-profile dependent stats
    if plot_type == "logavg":
        stats_tuple = (
            "motordroppedblocks",
            "clipdroppedblocks",
            "goodblocks",
            "samplesprocessed",
            "totalclip",
            "totaldespike",
            "writeerrors",
            "bufferfull",
            "datafiles",
            "datafailedfiles",
        )
    elif plot_type == "base":
        stats_tuple = ("writeerrors", "bufferfull", "datafiles", "datafailedfiles")
    else:
        log_warning("Unknown plot_type %s - no stats line being created")
        return ("", "", "")

    for statistic in stats_tuple:
        stat_tag = f"{statistic}{ch_tag}"
        profile_stats[stat_tag] = 0
        dive_stats[stat_tag] = 0
        climb_stats[stat_tag] = 0
        for cast in ("a", "b", "c", "d"):
            var_nm = f"pmar_{statistic}_{cast}{ch_tag}"
            # DEBUG print var_nm
            if var_nm in dive_nc_file.variables:
                profile_stats[stat_tag] += dive_nc_file.variables[var_nm].getValue()
                if cast == "a":
                    dive_stats[stat_tag] = dive_nc_file.variables[var_nm].getValue()
                else:
                    climb_stats[stat_tag] = dive_nc_file.variables[var_nm].getValue()

    profile_stats_line = ""
    for s in profile_stats:
        profile_stats_line = "%s%s" % (
            profile_stats_line,
            "%s:%d " % (s, profile_stats[s]),
        )
        if plot_type == "logavg":
            if "motordropped" in s or "totaldespike" in s:
                profile_stats_line = f"{profile_stats_line}<br>"
        else:
            if "osc" in s:
                profile_stats_line = f"{profile_stats_line}<br>"

    dive_stats_line = ""
    for s in dive_stats:
        dive_stats_line = "%s%s" % (dive_stats_line, "%s:%d " % (s, dive_stats[s]))
        if "osc" in s:
            dive_stats_line = f"{dive_stats_line}<br>"
    climb_stats_line = ""
    for s in climb_stats:
        climb_stats_line = "%s%s" % (climb_stats_line, "%s:%d " % (s, climb_stats[s]))
        if "samplerate" in s:
            climb_stats_line = f"{climb_stats_line}<br>"

    return (profile_stats_line, dive_stats_line, climb_stats_line)


@plotdivesingle
def plot_PMAR(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plots PMAR data"""

    pmar_present = False
    for v in dive_nc_file.variables:
        if "pmar_" in v:
            pmar_present = True

    if not pmar_present or not generate_plots:
        return ([], [])

    # Plot the base values
    ret_figs = []
    ret_plots = []

    start_time = dive_nc_file.start_time

    # TODO Get stats line working
    # TODO Sort out signal/gc discrepancy in vertical plots
    try:
        depth_time = dive_nc_file.variables["time"][:]
        if "depth" in dive_nc_file.variables:
            depth = dive_nc_file.variables["depth"][:]
        else:
            depth = dive_nc_file.variables["eng_depth"][:] / 100.0
        # Interpolate around missing depth observations
        depth = PlotUtils.interp_missing_depth(depth_time, depth)

    except KeyError as e:
        log_info(f"Could not find variable {e.args[0]} - skipping pmar plot")
        return (ret_figs, ret_plots)
    except Exception:
        log_error("Error fetching dive variables - skipping pmar plot", "exc")
        return (ret_figs, ret_plots)

    for ch_tag, ch_title in (
        ("", ""),
        ("_ch00", " Channel 00"),
        ("_ch01", " Channel 01"),
    ):
        if (
            (f"pmar_base_time{ch_tag}_a" not in dive_nc_file.variables)
            and (f"pmar_base_time{ch_tag}_b" not in dive_nc_file.variables)
            and (f"pmar_logavg_time{ch_tag}_a" not in dive_nc_file.variables)
            and (f"pmar_logavg_time{ch_tag}_b" not in dive_nc_file.variables)
        ):
            continue

        sigmean_dive = sigstddev_dive = pmar_time_dive = clip_max_count_dive = (
            clip_min_count_dive
        ) = clip_count_dive = clip_count_dive_normalized = None
        sigmean_climb = sigstddev_climb = pmar_time_climb = clip_max_count_climb = (
            clip_min_count_climb
        ) = clip_count_climb = clip_count_climb_normalized = None
        datawindow_dive = datawindow_climb = samplerate_dive = samplerate_climb = None

        try:
            sigmean_dive = abs(
                dive_nc_file.variables[f"pmar_base_sigmean{ch_tag}_a"][:]
            )
            sigstddev_dive = dive_nc_file.variables[f"pmar_base_sigstddev{ch_tag}_a"][:]
            pmar_time_dive = dive_nc_file.variables[f"pmar_base_time{ch_tag}_a"][:]
            clip_min_count_dive = dive_nc_file.variables[
                f"pmar_base_clipmincount{ch_tag}_a"
            ][:]
            clip_max_count_dive = dive_nc_file.variables[
                f"pmar_base_clipmaxcount{ch_tag}_a"
            ][:]
            datawindow_dive = dive_nc_file.variables[
                f"pmar_datawindow{ch_tag}"
            ].getValue()
            samplerate_dive = dive_nc_file.variables[
                f"pmar_samplerate{ch_tag}"
            ].getValue()
        except KeyError as e:
            log_debug(f"Could not find variable {e.args[0]} - skipping dive plot")
        except Exception:
            log_error("Error fetching dive variables - skipping dive plot", "exc")
        else:
            clip_count_dive = clip_min_count_dive + clip_max_count_dive

        try:
            sigmean_climb = abs(
                dive_nc_file.variables[f"pmar_base_sigmean{ch_tag}_b"][:]
            )
            sigstddev_climb = dive_nc_file.variables[f"pmar_base_sigstddev{ch_tag}_b"][
                :
            ]
            pmar_time_climb = dive_nc_file.variables[f"pmar_base_time{ch_tag}_b"][:]
            clip_min_count_climb = dive_nc_file.variables[
                f"pmar_base_clipmincount{ch_tag}_b"
            ][:]
            clip_max_count_climb = dive_nc_file.variables[
                f"pmar_base_clipmaxcount{ch_tag}_b"
            ][:]
            datawindow_climb = dive_nc_file.variables[
                f"pmar_datawindow{ch_tag}"
            ].getValue()
            samplerate_climb = dive_nc_file.variables[
                f"pmar_samplerate{ch_tag}"
            ].getValue()
        except KeyError as e:
            log_debug(f"Could not find variable {e.args[0]} - skipping climb plot")
        except Exception:
            log_error("Error fetching variables - skipping climb plot", "exc")
        else:
            clip_count_climb = clip_min_count_climb + clip_max_count_climb

        # Look for clip count in logavg file
        if pmar_time_dive is None:
            try:
                pmar_time_dive = dive_nc_file.variables[f"pmar_logavg_time{ch_tag}_a"][
                    :
                ]
                clip_count_dive = dive_nc_file.variables[
                    f"pmar_logavg_clipcount{ch_tag}_a"
                ][:]
            except KeyError as e:
                log_info(f"Could not find variable {e.args[0]} - skipping dive plot")
            except Exception:
                log_error("Error fetching dive variables - skipping dive plot", "exc")

            try:
                pmar_time_climb = dive_nc_file.variables[f"pmar_logavg_time{ch_tag}_b"][
                    :
                ]
                clip_count_climb = dive_nc_file.variables[
                    f"pmar_logavg_clipcount{ch_tag}_b"
                ][:]
            except KeyError as e:
                log_info(f"Could not find variable {e.args[0]} - skipping dive plot")
            except Exception:
                log_error("Error fetching dive variables - skipping dive plot", "exc")

        if clip_count_dive is not None and datawindow_dive is not None:
            clip_count_dive_normalized = clip_count_dive / (
                samplerate_dive * datawindow_dive
            )

        if clip_count_climb is not None and datawindow_climb is not None:
            clip_count_climb_normalized = clip_count_climb / (
                samplerate_climb * datawindow_climb
            )

        _, dive_stats_line, climb_stats_line = pmar_create_stats_lines(
            dive_nc_file, ch_tag, "base"
        )

        f = scipy.interpolate.interp1d(
            depth_time, depth, kind="linear", bounds_error=False, fill_value=0.0
        )

        if pmar_time_dive is not None:
            pmar_depth_dive = f(pmar_time_dive)
        else:
            pmar_depth_dive = None

        if pmar_time_climb is not None:
            pmar_depth_climb = f(pmar_time_climb)
        else:
            pmar_depth_climb = None

        gc_moves = PlotUtils.extract_gc_moves(dive_nc_file)[0]

        pmar_gc_dive = []
        pmar_gc_climb = []

        for gc in gc_moves:
            start_depth = np.float64(f(start_time + gc.start_time))
            end_depth = np.float64(f(start_time + gc.end_time))
            if pmar_time_dive is not None and (
                (
                    start_time + gc.start_time >= min(pmar_time_dive)
                    and start_time + gc.start_time <= max(pmar_time_dive)
                )
                or (
                    start_time + gc.end_time >= min(pmar_time_dive)
                    and start_time + gc.end_time <= max(pmar_time_dive)
                )
            ):
                pmar_gc_dive.append(
                    PlotUtils.gc_move_depth(
                        start_depth,
                        end_depth,
                        gc.move_type,
                        gc.end_time - gc.start_time,
                    )
                )

            if pmar_time_climb is not None and (
                (
                    start_time + gc.start_time >= min(pmar_time_climb)
                    and start_time + gc.start_time <= max(pmar_time_climb)
                )
                or (
                    start_time + gc.end_time >= min(pmar_time_climb)
                    and start_time + gc.end_time <= max(pmar_time_climb)
                )
            ):
                pmar_gc_climb.append(
                    PlotUtils.gc_move_depth(
                        start_depth,
                        end_depth,
                        gc.move_type,
                        gc.end_time - gc.start_time,
                    )
                )

        bp = collections.namedtuple(
            "base_plot",
            [
                "x_label",
                "y_label",
                "depth",
                "data",
                "gc_moves",
                "xaxis_type",
                "figtitle",
                "filename",
                "color",
                "stats_line",
            ],
        )

        bp_plots = [
            bp(
                "Signal StdDev",
                "Signal StdDev dive",
                pmar_depth_dive,
                sigstddev_dive,
                pmar_gc_dive,
                "log",
                "Signal StdDev (Dive)",
                "sigstddev_dive",
                "Magenta",
                dive_stats_line,
            ),
            bp(
                "Signal StdDev",
                "Signal StdDev climb",
                pmar_depth_climb,
                sigstddev_climb,
                pmar_gc_climb,
                "log",
                "Signal StdDev (Climb)",
                "sigstddev_climb",
                "Red",
                climb_stats_line,
            ),
            bp(
                "Signal Mean Abs",
                "Signal Mean Abs dive",
                pmar_depth_dive,
                sigmean_dive,
                pmar_gc_dive,
                "log",
                "Signal Mean Abs (Dive)",
                "sigmean_dive",
                "Black",
                dive_stats_line,
            ),
            bp(
                "Signal Mean Abs",
                "Signal Mean Abs climb",
                pmar_depth_climb,
                sigmean_climb,
                pmar_gc_climb,
                "log",
                "Signal Mean Abs (Climb)",
                "sigmean_climb",
                "Green",
                climb_stats_line,
            ),
        ]

        if clip_count_dive_normalized is not None:
            bp_plots.append(
                bp(
                    "Clip Count Normalized",
                    "Clip Count dive normalized",
                    pmar_depth_dive,
                    clip_count_dive_normalized,
                    pmar_gc_dive,
                    "linear",
                    "Clip Count Normalized (Dive)",
                    "clip_count_normalized_dive",
                    "Black",
                    dive_stats_line,
                )
            )
        elif clip_count_dive is not None:
            bp_plots.append(
                bp(
                    "Clip Count",
                    "Clip Count dive",
                    pmar_depth_dive,
                    clip_count_dive,
                    pmar_gc_dive,
                    "linear",
                    "Clip Count (Dive)",
                    "clip_count_dive",
                    "Black",
                    dive_stats_line,
                )
            )

        if clip_count_climb_normalized is not None:
            bp_plots.append(
                bp(
                    "Clip Count Normalized",
                    "Clip Count climb normalized",
                    pmar_depth_climb,
                    clip_count_climb_normalized,
                    pmar_gc_climb,
                    "linear",
                    "Clip Count Normalized (Climb)",
                    "clip_count_normalized_climb",
                    "Green",
                    climb_stats_line,
                )
            )
        elif clip_count_climb is not None:
            bp_plots.append(
                bp(
                    "Clip Count",
                    "Clip Count climb",
                    pmar_depth_climb,
                    clip_count_climb,
                    pmar_gc_climb,
                    "linear",
                    "Clip Count (Climb)",
                    "clip_count_climb",
                    "Green",
                    climb_stats_line,
                )
            )

        for p in bp_plots:
            if p.data is None or p.depth is None:
                continue

            fig = plotly.graph_objects.Figure()

            show_label = collections.defaultdict(lambda: True)

            for gc in p.gc_moves:
                min_data = np.nanmin(p.data)
                max_data = np.nanmax(p.data)
                # Enforce a minium size here so you get some indication of the gc move
                if min_data == max_data:
                    max_data += 1.0

                fig.add_trace(
                    {
                        "type": "scatter",
                        "y": (
                            gc.start_depth,
                            gc.start_depth,
                            gc.end_depth,
                            gc.end_depth,
                        ),
                        "x": (
                            min_data,
                            max_data,
                            max_data,
                            min_data,
                        ),
                        "xaxis": "x1",
                        "yaxis": "y1",
                        "fill": "toself",
                        "fillcolor": PlotUtils.gc_move_colormap[gc.move_type].color,
                        "line": {
                            "dash": "solid",
                            # proxy for line opacity - lines are needed for short moves (like roll)
                            "width": 0.25,
                            "color": PlotUtils.gc_move_colormap[gc.move_type].color,
                        },
                        "mode": "lines",
                        "legendgroup": f"{PlotUtils.gc_move_colormap[gc.move_type].name}_group",
                        "name": f"GC {PlotUtils.gc_move_colormap[gc.move_type].name}",
                        "showlegend": show_label[
                            PlotUtils.gc_move_colormap[gc.move_type].name
                        ],
                        "text": f"GC {PlotUtils.gc_move_colormap[gc.move_type].name}, Start {gc.start_depth:.2f} m, End {gc.end_depth:.2f} m<br>Duration {gc.duration:.02f} secs",
                        "hoverinfo": "text",
                    }
                )
                show_label[PlotUtils.gc_move_colormap[gc.move_type].name] = False

            fig.add_trace(
                {
                    "name": p.x_label,
                    "type": "scatter",
                    "x": p.data,
                    "y": p.depth,
                    "xaxis": "x1",
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {
                        "symbol": "circle",
                        "color": p.color,
                        # "size": 3,
                    },
                    "hovertemplate": p.x_label
                    + "<br>%{x:.2f}units <br>%{y:.2f} m<extra></extra>",
                }
            )

            mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
            title_text = f"{mission_dive_str}\nPMAR{ch_title} {p.figtitle} vs Depth"

            xaxis_title = p.x_label
            if len(p.stats_line) > 0:
                xaxis_title += f"<br>{p.stats_line}"

            fig.update_layout(
                {
                    "xaxis": {
                        "title": xaxis_title,
                        "showgrid": True,
                        "type": p.xaxis_type,
                    },
                    "yaxis": {
                        "title": "Depth (m)",
                        "autorange": "reversed",
                        "showgrid": True,
                        # "range": [-100.0, 80.0],
                        # "nticks": 19,
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
                        "x": 1.05,
                        "y": 1,
                    },
                }
            )

            output_name = "dv%04d_pmar_%s%s" % (
                dive_nc_file.dive_number,
                p.filename,
                ch_tag,
            )

            ret_figs.append(fig)
            ret_plots.extend(
                PlotUtilsPlotly.write_output_files(base_opts, output_name, fig)
            )

        # Log average
        # spectra_dive_qc = spectra_climb_qc = None
        cf_dive = cf_climb = spectra_dive = spectra_climb = spectra_time_dive = (
            spectra_time_climb
        ) = None

        for cf_var in (
            f"pmar_logavg{ch_tag}_a_center_freqs",
            f"pmar_logavg_center_freqs{ch_tag}_a",
        ):
            if cf_var in dive_nc_file.variables:
                cf_dive = dive_nc_file.variables[cf_var][:]
                break
        else:
            log_info(
                "Could not find center freq variable for a profile - skipping related plot"
            )

        if cf_dive is not None:
            try:
                # cf = dive_nc_file.variables[f"pmar_logavg{ch_tag}_a_center_freqs"][:]
                spectra_dive = dive_nc_file.variables[f"pmar_logavg{ch_tag}_a"][:]
                spectra_time_dive = dive_nc_file.variables[
                    f"pmar_logavg_time{ch_tag}_a"
                ][:]

                # tmp = array([QC.decode_qc(dive_nc_file.variables['pmar_logavg_a_qc'])])
                # spectra_dive_qc = tile(tmp.transpose(), (1, shape(spectra_dive)[1]))
                # spectra_dive = ma.array(spectra_dive, mask=(isnan(spectra_dive) | bad_qc(spectra_dive_qc,mask=True)) )
            except KeyError as e:
                log_info(f"Could not find variable {e.args[0]} - skipping related plot")
            except Exception:
                log_error(
                    "Error fetching dive variables - skipping related plot", "exc"
                )

        # try:
        #     spectra_dive_qc = QC.decode_qc(
        #         dive_nc_file.variables[f"pmar_logavg{ch_tag}_a_qc"]
        #     )
        # except Exception:
        #     log_warning("Could not spectra dive qc variable")
        #     spectra_dive_qc = None

        for cf_var in (
            f"pmar_logavg{ch_tag}_b_center_freqs",
            f"pmar_logavg_center_freqs{ch_tag}_b",
        ):
            if cf_var in dive_nc_file.variables:
                cf_climb = dive_nc_file.variables[cf_var][:]
                break
        else:
            log_info(
                "Could not find center freq variable for b profile - skipping related plot"
            )

        if cf_climb is not None:
            try:
                cf = dive_nc_file.variables[f"pmar_logavg{ch_tag}_b_center_freqs"][:]
                spectra_climb = dive_nc_file.variables[f"pmar_logavg{ch_tag}_b"][:]
                spectra_time_climb = dive_nc_file.variables[
                    f"pmar_logavg_time{ch_tag}_b"
                ][:]
                # tmp = array([QC.decode_qc(dive_nc_file.variables['pmar_logavg_b_qc'])])
                # spectra_climb_qc = tile(tmp.transpose(), (1, shape(spectra_climb)[1]))
                # spectra_climb = ma.array(spectra_climb, mask=(isnan(spectra_climb) | bad_qc(spectra_dive_qc,mask=True)) )
            except KeyError as e:
                log_info(f"Could not find variable {e.args[0]} - skipping dive plot")
            except Exception:
                log_error("Error fetching dive variables - skipping dive plot", "exc")

        # try:
        #     spectra_climb_qc = QC.decode_qc(
        #         dive_nc_file.variables[f"pmar_logavg{ch_tag}_b_qc"]
        #     )
        # except Exception:
        #     log_warning("Could not spectra climb qc variable")
        #     spectra_climb_qc = None

        # TODO - it is possible for the dive and climb to have two different logmaps, which would mean two different plots
        # of the spectra. For now, use the last one in (this is the way the code has been for a long time)
        cf = cf_climb if cf_climb is not None else cf_dive

        spectra = None
        spectra_time = None
        # spectra_qc = None
        if spectra_dive is not None:
            if spectra_climb is not None:
                spectra = np.vstack((spectra_dive, spectra_climb))
                # if spectra_dive_qc is not None and spectra_climb_qc is not None:
                #     spectra_qc = np.concatenate(
                #         (np.transpose(spectra_dive_qc), np.transpose(spectra_climb_qc))
                #     )
                spectra_time = np.concatenate(
                    (np.transpose(spectra_time_dive), np.transpose(spectra_time_climb))
                )
            else:
                spectra = spectra_dive
                # if spectra_dive_qc is not None:
                #    spectra_qc = np.transpose(spectra_dive_qc)
                spectra_time = np.transpose(spectra_time_dive)
        elif spectra_climb is not None:
            spectra = spectra_climb
            # if spectra_climb_qc is not None:
            #    specta_qc = np.transpose(spectra_climb_qc)
            spectra_time = np.transpose(spectra_time_climb)

        # log_info("spectra shape:%s, spectra_qc shape:%s spectra_time shape:%s" % (shape(spectra), shape(spectra_qc), shape(spectra_time)))
        # log_info(spectra_time)

        # log_info("spectra_qc = %s" % spectra_qc)
        # log_info("spectra_qc mask = %s" % where(bad_qc(spectra_qc,mask=True))

        if spectra is None:
            continue
            # return ret_val

        profile_stats_line, _, _ = pmar_create_stats_lines(
            dive_nc_file, ch_tag, "logavg"
        )
        spectra_depth = None

        depth_f = scipy.interpolate.interp1d(
            depth_time, depth, kind="linear", bounds_error=False, fill_value=0.0
        )
        spectra_depth = depth_f(spectra_time)

        # Plot the spectra
        fig = plotly.graph_objects.Figure()

        spectra_times = []
        for tt in spectra_time:
            spectra_times.append(
                time.strftime("%Y-%m-%dT%H:%M:%S", time.gmtime(tt))
                + ".%03d" % (np.modf(tt)[0] * 1000.0)
            )

        # Plot depth
        if spectra_depth is not None:
            fig.add_trace(
                {
                    "name": "Depth (m)",
                    "type": "scatter",
                    "x": spectra_time - start_time,
                    "y": spectra_depth,
                    "xaxis": "x1",
                    "yaxis": "y2",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "Black"},
                    "hovertemplate": "Depth (m)<br>%{x:.2f} secs <br>%{y:.2f} m<extra></extra>",
                }
            )

            PlotUtils.add_gc_moves(
                fig,
                gc_moves,
                spectra_depth,
                yaxis="y2",
                time_range=spectra_time - start_time,
            )

        # c_list = plotly.colors.sequential.Jet
        # c_list = plotly.colors.sequential.Rainbow

        # Choose evenly spaced colors
        c_l = plotly.colors.sequential.Plasma
        c_list = []
        for _ in range(np.ceil(len(cf) / len(c_l)).astype(int)):
            c_list += c_l

        idx = np.round(np.linspace(0, len(c_list) - 1, len(cf))).astype(int)
        c_list = np.array(c_list)[idx].tolist()

        x_min = np.nanmin(spectra_time - start_time)
        x_max = np.nanmax(spectra_time - start_time)
        x_rng = x_max - x_min
        x_min = x_min - (x_rng * 0.05)
        x_max = x_max + (x_rng * 0.05)

        for ii in range(len(cf)):
            try:
                s = spectra[:, ii]

                # color = c_list[ii % len(c_list)]
                color = c_list[ii]

                fig.add_trace(
                    {
                        "name": f"CF {cf[ii]:.1f} Hz",
                        "type": "scatter",
                        "x": spectra_time - start_time,
                        "y": s,
                        "meta": spectra_times,
                        "xaxis": "x1",
                        "yaxis": "y1",
                        "mode": "lines+markers",
                        "marker": {
                            "symbol": "cross",
                            "color": color,
                            # "color": p.color,
                            # "size": 3,
                        },
                        "hovertemplate": f"CF {cf[ii]:.1f} Hz"
                        + "<br>%{x:.2f} secs <br>%{y:.2f} counts^2/Hz<br>%{meta}<extra></extra>",
                    }
                )
                # Shadow trace for the top GMT xaxis
                if ii == 0:
                    fig.add_trace(
                        {
                            "name": "epoch_time_trace",
                            "type": "scatter",
                            "x": spectra_times,
                            # Best solution I found to hide a trace - make it all nans
                            "y": np.zeros(len(s)) * np.nan,
                            "xaxis": "x2",
                            "yaxis": "y1",
                            "mode": "lines+markers",
                            "marker": {
                                "symbol": "cross",
                            },
                            "showlegend": False,
                        }
                    )
            except Exception:
                log_error("Failed to plot spectra - skipping", "exc")

        if base_opts.pmar_logavg_min != 0.0:
            y1_min = np.log10(base_opts.pmar_logavg_min)
        else:
            y1_min = 0.0
        if base_opts.pmar_logavg_max != 0.0:
            y1_max = np.log10(base_opts.pmar_logavg_max)
        else:
            y1_max = 0.0

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}\nPMAR{ch_title} Logavg Spectra vs Time"

        xaxis_title = "Time Into Dive (s)"
        if len(profile_stats_line) > 0:
            xaxis_title += f"<br>{profile_stats_line}"

        fig.update_layout(
            {
                "xaxis": {
                    "title": xaxis_title,
                    "showgrid": True,
                    "range": (x_min, x_max),
                },
                "xaxis2": {
                    "title": "GMT Time",
                    "showgrid": False,
                    "overlaying": "x1",
                    "side": "top",
                },
                "yaxis": {
                    "title": r"$counts^2/hZ$",
                    "showgrid": True,
                    "type": "log",
                    "exponentformat": "power",
                    "range": [y1_min, y1_max],
                },
                "yaxis2": {
                    "title": "Depth (m)",
                    "range": [np.nanmax(spectra_depth), np.nanmin(spectra_depth)],
                    "showgrid": False,
                    "overlaying": "y1",
                    "side": "right",
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
                    # "b": 150,
                },
                "legend": {
                    "x": 1.05,
                    "y": 1,
                },
            }
        )

        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                "dv%04d_pmar_logavg_spectra%s" % (dive_nc_file.dive_number, ch_tag),
                fig,
            )
        )

    return (ret_figs, ret_plots)
