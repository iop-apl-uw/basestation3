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

"""Plots TMICL data """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import typing

import numpy as np
import plotly.graph_objects
import scipy

if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtils
import PlotUtilsPlotly
from BaseLog import log_warning, log_info, log_debug, log_error
from Plotting import plotdivesingle


@plotdivesingle
def plot_TMICL(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
) -> tuple[list, list]:
    """Plots TMICL data"""

    tmicl_present = False
    for v in dive_nc_file.variables:
        if "tmicl_" in v:
            tmicl_present = True
    if not tmicl_present or not generate_plots:
        return ([], [])

    # Plot the base values
    ret_plots = []
    ret_figs = []

    try:
        ttime = dive_nc_file.variables["time"][:]
        if "depth" in dive_nc_file.variables:
            depth = dive_nc_file.variables["depth"][:]
        else:
            depth = dive_nc_file.variables["eng_depth"][:] / 100.0
    except KeyError as e:
        log_warning(f"Could not find variable {e.args[0]} - skipping this plot")
        return (ret_figs, ret_plots)
    except:
        log_error("Error fetching depth variables - skipping this plot", "exc")
        return (ret_figs, ret_plots)

    try:
        start_time = dive_nc_file.start_time
    except:
        start_time = ttime[0]

    for ch in ("ch0", "ch1", "shear", "temp", "temp0", "temp1"):
        if not (f"tmicl_time_{ch}_a" in dive_nc_file.variables) and not (
            f"tmicl_time_{ch}_b" in dive_nc_file.variables
        ):
            continue

        max_depth_sample_index = np.argmax(depth)

        # Create dive and climb vectors
        time_dive = (ttime[0:max_depth_sample_index] - start_time) / 60.0
        time_climb = (ttime[max_depth_sample_index:] - start_time) / 60.0

        sigmean_dive = sigvar_dive = intvar_dive = tmicl_time_dive = None
        sigmean_climb = sigvar_climb = intvar_climb = tmicl_time_climb = None

        try:
            sigmean_dive = dive_nc_file.variables[f"tmicl_sigmean_{ch}_a"][:]
            sigvar_dive = dive_nc_file.variables[f"tmicl_sigvar_{ch}_a"][:]
            tmicl_time_dive = dive_nc_file.variables[f"tmicl_time_{ch}_a"][:]
        except KeyError as e:
            log_debug(f"Could not find variable {e.args[0]} - skipping dive plot")
        except:
            log_error("Error fetching dive variables - skipping dive plot", "exc")

        try:
            sigmean_climb = dive_nc_file.variables[f"tmicl_sigmean_{ch}_b"][:]
            sigvar_climb = dive_nc_file.variables[f"tmicl_sigvar_{ch}_b"][:]
            tmicl_time_climb = dive_nc_file.variables[f"tmicl_time_{ch}_b"][:]
        except KeyError as e:
            log_info(f"Could not find variable {e.args[0]} - skipping climb plot")
        except:
            log_error("Error fetching variables - skipping climb plot", "exc")

        # Older version of the code generated this - failing to find it is not
        # an error
        try:
            intvar_dive = dive_nc_file.variables["tmicl_intvar_%s_a" % ch][:]
        except KeyError as e:
            log_debug("Could not find variable %s - skipping dive plot" % e.args[0])
        except:
            log_warning("Error fetching variable - skipping climb plot", "exc")

        try:
            intvar_climb = dive_nc_file.variables["tmicl_intvar_%s_b" % ch][:]
        except KeyError as e:
            log_debug("Could not find variable %s - skipping climb plot" % e.args[0])
        except:
            log_warning("Error fetching variables - skipping climb plot", "exc")

        is_shear = None
        try:
            is_shear = dive_nc_file.tmicl_S
        except:
            pass

        # Interp
        f = scipy.interpolate.interp1d(
            ttime, depth, kind="linear", bounds_error=False, fill_value=0.0
        )

        tmicl_depth_dive = tmicl_depth_climb = None

        if tmicl_time_dive is not None:
            tmicl_depth_dive = f(tmicl_time_dive)

        if tmicl_time_climb is not None:
            tmicl_depth_climb = f(tmicl_time_climb)

        bp = collections.namedtuple(
            "base_plot",
            [
                "name",
                "units",
                "dive_data",
                "climb_data",
                "scale_type",
                "dive_color",
                "climb_color",
                "xaxis",
            ],
        )

        fig = plotly.graph_objects.Figure()

        xaxis2_name = None

        for p in (
            bp(
                "Signal Variance",
                "Volts/sec^2",
                sigvar_dive,
                sigvar_climb,
                "log",
                "Magenta",
                "Red",
                "x2",
            ),
            bp(
                "Integrated Variance",
                "Volts/sec^2",
                intvar_dive,
                intvar_climb,
                "log",
                "Blue",
                "Cyan",
                "x2",
            ),
            bp(
                "Signal Mean",
                "",
                sigmean_dive,
                sigmean_climb,
                "linear",
                "Black",
                "Green",
                "x1",
            ),
        ):

            # figure(num=None, figsize=(1024, 768), dpi=100)
            if p.dive_data is None and p.climb_data is None:
                continue

            if p.xaxis == "x2":
                xaxis2_name = p.name

            if "shear" in ch and "Mean" in p.name:
                visible = "legendonly"
            else:
                visible = True

            # Plot sigvar vs depth
            if p.dive_data is not None and tmicl_depth_dive is not None:

                fig.add_trace(
                    {
                        "y": tmicl_depth_dive,
                        "x": p.dive_data,
                        "meta": time_dive,
                        "name": f"{p.name} Dive",
                        "type": "scatter",
                        "xaxis": p.xaxis,
                        "yaxis": "y1",
                        "mode": "lines+markers",
                        "marker": {
                            "symbol": "triangle-down",
                            "color": p.dive_color,
                        },
                        "visible": visible,
                        "hovertemplate": f"{p.name} Dive<br>"
                        + "%{x:.2f} "
                        + f"{p.units}<br>"
                        + "%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                    }
                )

            if p.climb_data is not None and tmicl_depth_climb is not None:
                fig.add_trace(
                    {
                        "y": tmicl_depth_climb,
                        "x": p.climb_data,
                        "meta": time_climb,
                        "name": f"{p.name} Climb",
                        "type": "scatter",
                        "xaxis": p.xaxis,
                        "yaxis": "y1",
                        "mode": "lines+markers",
                        "marker": {
                            "symbol": "triangle-down",
                            "color": p.climb_color,
                        },
                        "visible": visible,
                        "hovertemplate": f"{p.name} Climb<br>"
                        + "%{x:.2f} "
                        + f"{p.units}<br>"
                        + "%{y:.2f} meters<br>%{meta:.2f} mins<extra></extra>",
                    }
                )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = (
            f"{mission_dive_str}<br>Tmicl {ch} Signal Mean and Variance vs Depth"
        )
        output_name = "dv%04d_tmicl_signal_mean_variance_%s" % (
            dive_nc_file.dive_number,
            ch,
        )

        update_dict = {
            "xaxis": {"title": "Signal Mean", "type": "linear"},
            "yaxis": {
                "title": "Depth (m)",
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
                "t": 150,
            },
        }

        if xaxis2_name:
            update_dict["xaxis2"] = {
                "title": f"{xaxis2_name} (Volts/sec^2)",
                "type": "log",
                "overlaying": "x1",
                "side": "top",
            }

        fig.update_layout(update_dict)

        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                output_name,
                fig,
            )
        )

    # Plot logavg
    for ch in ("ch0", "ch1", "shear", "temp", "temp0", "temp1"):
        for cast in ("a", "b", "c", "d"):

            if f"tmicl_logavg_{ch}_{cast}_time" not in dive_nc_file.variables:
                continue
            try:
                logavg = dive_nc_file.variables[f"tmicl_logavg_{ch}_{cast}"][:]
                logavg_time = dive_nc_file.variables[f"tmicl_logavg_{ch}_{cast}_time"][
                    :
                ]
                center_freqs = dive_nc_file.variables[
                    f"tmicl_logavg_{ch}_{cast}_center_freqs"
                ][:]
            except:
                log_warning(
                    "Could not find tmicl variable (but found matching time variable) - skipping this plot",
                    "exc",
                )
                continue

            try:
                ttime = dive_nc_file.variables["time"][:]
                depth = dive_nc_file.variables["depth"][:]
            except KeyError as e:
                log_warning(f"Could not find variable {e.args[0]} - skipping this plot")
                continue
            except:
                log_error("Error fetching depth variables - skipping this plot", "exc")
                continue

            # Hack - First observation is garbage - need to track down where
            # this is in the processing stream
            logavg = logavg[1:]
            logavg_time = logavg_time[1:]

            # Interp for the depth
            f = scipy.interpolate.interp1d(
                ttime, depth, kind="linear", bounds_error=False, fill_value=0.0
            )
            logavg_depth_m_v = f(logavg_time)

            # Per Luc - these are the desired ranges to fix things to
            # TODO: Make config param
            # z_max = 9
            # z_min = 4
            z_max = 15
            z_min = 0
            # np.ma.masked_where(logavg <= 0, np.ma.masked_invalid(logavg))
            logavg[np.nonzero(logavg <= 0)[0]] = np.nan
            fig = plotly.graph_objects.Figure(
                data=plotly.graph_objects.Heatmap(
                    z=np.log10(logavg),
                    x=center_freqs,
                    y=logavg_depth_m_v,
                    colorscale="jet",
                    hovertemplate="Center freq %{x:.2f} Hz<br>Depth: %{y:.2f}<br>%{z:.2f} log10(counts^2/Hz)<extra></extra>",
                    zmax=z_max,
                    zmin=z_min,
                )
            )
            mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
            title_text = "%s<br>%s %s %s Logavg Spectrum vs Depth" % (
                mission_dive_str,
                "Shear" if is_shear else "Tmicl",
                ch,
                "down profile" if cast == "a" else "up profile",
            )
            output_name = "dv%04d_tmicl_logavg_%s_%s" % (
                dive_nc_file.dive_number,
                ch,
                cast,
            )

            fig.update_layout(
                {
                    "xaxis": {
                        "title": "Frequency (Hz)",
                        "showgrid": True,
                        "type": "log",
                    },
                    "yaxis": {
                        "title": "Depth (m)",
                        "showgrid": True,
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
                        "t": 150,
                    },
                }
            )

            ret_figs.append(fig)
            ret_plots.extend(
                PlotUtilsPlotly.write_output_files(base_opts, output_name, fig)
            )
    return (ret_figs, ret_plots)
