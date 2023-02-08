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

"""Plots gliders course through the water """

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import typing

import numpy as np
import plotly.graph_objects

if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import log_error
from Plotting import plotdivesingle


@plotdivesingle
def plot_COG(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
) -> tuple[list, list]:
    """Plots the glider course over ground"""

    if (
        not (
            "latitude" in dive_nc_file.variables
            and "longitude" in dive_nc_file.variables
            and "log_gps_lat" in dive_nc_file.variables
        )
        or not generate_plots
    ):
        return ([], [])

    # Preliminaries
    try:
        start_time = dive_nc_file.start_time
        ctd_time = dive_nc_file.variables["ctd_time"][:]
        lats = dive_nc_file.variables["latitude"][:]
        lons = dive_nc_file.variables["longitude"][:]
        lat_gps = dive_nc_file.variables["log_gps_lat"][:]
        lon_gps = dive_nc_file.variables["log_gps_lon"][:]
    except:
        log_error("Problems in plot_COG", "exc")
        return ([], [])

    # Additional meta data
    pitch_ang = roll_ang = None
    try:
        eng_time = dive_nc_file.variables["time"][:]
        ctd_depth = dive_nc_file.variables["ctd_depth"][:]
        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_roll_ang = dive_nc_file.variables["eng_rollAng"][:]
    except KeyError:
        pass
    except:
        log_error("Unexpected problem with NEWHEAD variables", "exc")
    else:
        pitch_ang = Utils.interp1d(eng_time, eng_pitch_ang, ctd_time, kind="linear")
        roll_ang = Utils.interp1d(eng_time, eng_roll_ang, ctd_time, kind="linear")

    # Plot newhead messages
    newhead_heading_lat = newhead_heading_lon = None
    try:
        newhead_heading = dive_nc_file.variables["gc_msg_NEWHEAD_heading"][:]
        newhead_depth = dive_nc_file.variables["gc_msg_NEWHEAD_depth"][:]
        newhead_secs = dive_nc_file.variables["gc_msg_NEWHEAD_secs"][:]
        ctd_time = dive_nc_file.variables["ctd_time"][:]
    except KeyError:
        pass
    except:
        log_error("Unexpected problem with NEWHEAD variables", "exc")
    else:
        newhead_lats = Utils.interp1d(ctd_time, lats, newhead_secs, kind="linear")
        newhead_lons = Utils.interp1d(ctd_time, lons, newhead_secs, kind="linear")

        newhead_vector_len = np.max(
            [
                np.abs(np.nanmax(lats) - np.nanmin(lats)) * 0.05,
                np.abs(np.nanmax(lons) - np.nanmin(lons)) * 0.05,
            ]
        )

        head_true_deg_v = 90.0 - newhead_heading
        bad_deg_i_v = np.nonzero(head_true_deg_v >= 360.0)
        head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] - 360.0
        bad_deg_i_v = np.nonzero(head_true_deg_v < 0.0)
        head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] + 360.0
        head_polar_rad_v = np.radians(head_true_deg_v)
        # log_info(f"head_polar_rad_v {head_polar_rad_v}")

        newhead_heading_lat = newhead_lats + (
            np.sin(head_polar_rad_v) * newhead_vector_len
        )
        newhead_heading_lon = newhead_lons + (
            np.cos(head_polar_rad_v) * newhead_vector_len
        )

    fig = plotly.graph_objects.Figure()

    ctd_time = (ctd_time - start_time) / 60.0

    if pitch_ang is not None:
        customdata = np.squeeze(
            np.dstack(
                (
                    np.transpose(ctd_time),
                    np.transpose(ctd_depth),
                    np.transpose(pitch_ang),
                    np.transpose(roll_ang),
                )
            )
        )
        hovertemplate = (
            "COG HDM<br>lat %{y:.4f} deg<br>lon %{x:.4f} deg<br>Time %{customdata[0]:.2f} mins<br>"
            "Depth %{customdata[1]:.2f} m<br>Pitch %{customdata[2]:.2f} deg<br>Roll %{customdata[3]:.2f} deg<br><extra></extra>"
        )
    else:
        customdata = np.squeeze(
            np.dstack(
                (
                    np.transpose(ctd_time),
                    np.transpose(ctd_depth),
                )
            )
        )
        hovertemplate = (
            "COG HDM<br>lat %{y:.4f} deg<br>lon %{x:.4f} deg<br>Time %{customdata[0]:.2f} mins<br>"
            "Depth %{customdata[1]:.2f} m<extra></extra>"
        )

    fig.add_trace(
        {
            "y": lats,
            "x": lons,
            "name": "Course Over Ground",
            "type": "scatter",
            "mode": "markers",
            "customdata": customdata,
            "marker": {
                "symbol": "circle",
                "color": "DarkBlue",
                "size": 3,
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
            "hovertemplate": hovertemplate,
        }
    )

    fig.add_trace(
        {
            "y": (lat_gps[1],),
            "x": (lon_gps[1],),
            "name": "GPS2",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "star",
                "color": "Red",
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
        }
    )

    fig.add_trace(
        {
            "y": (lat_gps[2],),
            "x": (lon_gps[2],),
            "name": "GPSEND",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Red",
                #'line':{'width':1, 'color':'LightSlateGrey'}
            },
        }
    )
    if newhead_heading_lat is not None:
        for ii in range(len(newhead_heading_lat)):
            # log_info(newhead_heading_lat[ii], newhead_heading_lon[ii])
            fig.add_annotation(
                {
                    "xref": "x",
                    "yref": "y",
                    "x": newhead_lons[ii],
                    "y": newhead_lats[ii],
                    "axref": "x",
                    "ayref": "y",
                    "ax": newhead_heading_lon[ii],
                    "ay": newhead_heading_lat[ii],
                    "showarrow": True,
                    # "arrowhead": 2,
                    # "arrowsize": 1,
                    # "arrowwidth": 2,
                    "arrowside": "start",
                    "arrowcolor": "#636363",
                    # "bordercolor": "#c7c7c7",
                    # "borderwidth": 2,
                    # "borderpad": 4,
                    # "bgcolor": "#ff7f0e",
                    # "opacity": 0.8,
                    "hovertext": "New heading:"
                    + f"{newhead_heading[ii]:.2f} deg<br>Depth:{newhead_depth[ii]:.2f} m<br>Time:{(newhead_secs[ii] - start_time)/60.0:.2f} min",
                }
            )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = "%s<br>Course over Ground" % (mission_dive_str,)

    fig.update_layout(
        {
            "xaxis": {
                "title": "Longitude",
                "showgrid": True,
                #'range' : [min_salinity, max_salinity],
            },
            "yaxis": {
                "title": "Latitude",
                #'range' : [max(depth_dive.max() if len(depth_dive) > 0 else 0, depth_climb.max() if len(depth_climb) > 0 else 0), 0]
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
            },
            "legend": {
                "x": 1.05,
                "y": 1,
            },
        }
    )

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts, "dv%04d_cog" % (dive_nc_file.dive_number), fig
        ),
    )
