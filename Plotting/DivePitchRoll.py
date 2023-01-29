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

"""Plots for pitch and roll regressions"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations
import typing

import numpy as np

import scipy.interpolate
import plotly.graph_objects

if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

import BaseDB
import PlotUtils
import PlotUtilsPlotly
import Utils

from BaseLog import (
    log_warning,
    log_error,
    log_info,
)
from Plotting import plotdivesingle


def headingDiff(hdg1, hdg2):
    """Computes difference in two headings with wraparound"""
    diff = hdg2 - hdg1
    if diff > 180:
        diff = diff - 360
    elif diff < -180:
        diff = diff + 360

    return diff


@plotdivesingle
def plot_pitch_roll(
    base_opts: BaseOpts.BaseOptions, dive_nc_file: scipy.io._netcdf.netcdf_file
) -> tuple[list, list]:
    """Plots pitch and roll regressions"""

    if "eng_pitchAng" not in dive_nc_file.variables:
        log_error("No compass in nc - skipping")
        return ([], [])

    # Preliminaries
    try:
        # unused start_time = dive_nc_file.start_time

        # unused
        # mhead = (
        #     dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
        #     .tobytes()
        #     .decode("utf-8")
        #     .split(",")
        # )

        c_pitch = dive_nc_file.variables["log_C_PITCH"].getValue()
        # unused
        # pitch_gain = dive_nc_file.variables["log_PITCH_GAIN"].getValue()
        # if "log_IMPLIED_C_PITCH" in dive_nc_file.variables:
        #     c_pitch_implied = float(
        #         dive_nc_file.variables["log_IMPLIED_C_PITCH"][:]
        #         .tobytes()
        #         .decode("utf-8")
        #         .split(",")[0]
        #     )
        # else:
        #     c_pitch_implied = 0

        # unused pitch_min = dive_nc_file.variables["log_PITCH_MIN"].getValue()
        # unused pitch_max = dive_nc_file.variables["log_PITCH_MAX"].getValue()
        pitch_cnv = dive_nc_file.variables["log_PITCH_CNV"].getValue()
        roll_cnv = dive_nc_file.variables["log_ROLL_CNV"].getValue()
        c_roll_dive = dive_nc_file.variables["log_C_ROLL_DIVE"].getValue()
        c_roll_climb = dive_nc_file.variables["log_C_ROLL_CLIMB"].getValue()

        # SG eng time base
        sg_time = dive_nc_file.variables["time"][:]
        vehicle_pitch_degrees_v = dive_nc_file.variables["eng_pitchAng"][:]
        vehicle_roll_degrees_v = dive_nc_file.variables["eng_rollAng"][:]
        vehicle_head_degrees_v = dive_nc_file.variables["eng_head"][:]
        sg_np = dive_nc_file.dimensions["sg_data_point"]

        bad_i_v = [i for i in range(sg_np) if np.isnan(vehicle_pitch_degrees_v[i])]
        if len(bad_i_v):
            log_warning(
                "Compass invalid out for %d of %d points - interpolating bad points"
                % (len(bad_i_v), sg_np)
            )
            nans, x = Utils.nan_helper(vehicle_pitch_degrees_v)
            vehicle_pitch_degrees_v[nans] = np.interp(
                x(nans), x(~nans), vehicle_pitch_degrees_v[~nans]
            )

        bad_i_v = [i for i in range(sg_np) if np.isnan(vehicle_roll_degrees_v[i])]
        if len(bad_i_v):
            log_warning(
                "Compass invalid out for %d of %d points - interpolating bad points"
                % (len(bad_i_v), sg_np)
            )
            nans, x = Utils.nan_helper(vehicle_roll_degrees_v)
            vehicle_roll_degrees_v[nans] = np.interp(
                x(nans), x(~nans), vehicle_roll_degrees_v[~nans]
            )

        GC_st_secs = dive_nc_file.variables["gc_st_secs"][:]
        GC_end_secs = dive_nc_file.variables["gc_end_secs"][:]
        GC_pitch_AD_start = dive_nc_file.variables["gc_pitch_ad_start"][:]
        GC_pitch_AD_end = dive_nc_file.variables["gc_pitch_ad"][:]

        GC_roll_AD_start = dive_nc_file.variables["gc_roll_ad_start"][:]
        GC_roll_AD_end = dive_nc_file.variables["gc_roll_ad"][:]

        # unused nGC = len(GC_st_secs) * 2
        gc_t = np.concatenate((GC_st_secs, GC_end_secs))
        gc_t = np.transpose(gc_t).ravel()
        gc_x = np.concatenate((GC_pitch_AD_start, GC_pitch_AD_end))
        gc_x = np.transpose(gc_x).ravel()

        f = scipy.interpolate.interp1d(
            gc_t, gc_x, kind="linear", bounds_error=False, fill_value=(gc_x[0], gc_x[-1]) # "extrapolate"
        )
        pitchAD = f(sg_time)
        pitch_control = (pitchAD - c_pitch) * pitch_cnv

        iwn = np.argwhere(pitch_control < 0)
        iwp = np.argwhere(pitch_control > 0)

        gc_x = np.concatenate((GC_roll_AD_start, GC_roll_AD_end))
        gc_x = np.transpose(gc_x).ravel()

        f = scipy.interpolate.interp1d(
            gc_t, gc_x, kind="linear", bounds_error=False, fill_value=(gc_x[0], gc_x[-1]) # "extrapolate"
        )
        rollAD = f(sg_time)
        roll_control = (rollAD - c_roll_dive) * roll_cnv
        roll_control[iwp] = (rollAD[iwp] - c_roll_climb) * roll_cnv
        # unused pitch_control_slope = 1.0 / pitch_cnv

    except:
        log_error(
            "Could not fetch needed variables - skipping pitch and roll plots", "exc"
        )
        return ([], [])

    #
    # pitch calculations
    #

    xmax = 3.5
    xmin = -3.5
    inds = np.nonzero(
        np.logical_and.reduce(
            (
                pitch_control < xmax,
                pitch_control > xmin,
                roll_control < 10,
                roll_control > -10,
            )
        )
    )[0]

    fit = scipy.stats.linregress(pitchAD[inds], vehicle_pitch_degrees_v[inds])
    implied_C = -fit.intercept / fit.slope
    implied_gain = fit.slope / pitch_cnv

    log_info(f"implied_cpitch {implied_C}, implied_pitchgain {implied_gain}")
    
    BaseDB.addValToDB(base_opts, dive_nc_file.dive_number, "implied_C_PITCH", implied_C)
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_PITCH_GAIN", implied_gain
    )
    try:
        BaseDB.addSlopeValToDB(base_opts, dive_nc_file.dive_number, ["implied_C_PITCH"], None)
    except:
        log_error("Failed to add values to database", "exc")

    pitchAD_Fit = [min(pitchAD), max(pitchAD)]
    pitch_Fit = (pitchAD_Fit - implied_C) * implied_gain * pitch_cnv

    figs_list = []
    file_list = []

    #
    # pitch plot
    #

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": pitchAD,
            "y": vehicle_pitch_degrees_v,
            "name": "Pitch control/Pitch",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkBlue",
            },
            # "mode": "lines",
            # "line": {"dash": "solid", "color": "Blue"},
            "hovertemplate": "PitchAD<br>%{x:.0f}<br>%{y:.2f} deg<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": pitchAD_Fit,
            "y": pitch_Fit,
            "name": "linfit C_PITCH, PITCH_GAIN",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Red"},
            "hovertemplate": f"Fit C_PITCH={implied_C:.0f} PITCH_GAIN={implied_gain:.2f}<br><extra></extra>",
        }
    )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Pitch control vs Pitch"
    fit_line = f"Best fit pitch regression implies C_PITCH={implied_C:.0f}ad PITCH_GAIN={implied_gain:.2f}deg/cm"

    fig.update_layout(
        {
            "xaxis": {
                "title": f"pitch control (counts)<br>{fit_line}",
                "showgrid": True,
                # "side": "top"
            },
            "yaxis": {
                "title": "pitch (deg)",
                "showgrid": True,
                # "autorange": "reversed",
                # "range": [
                #     max(
                #         depth_dive.max() if len(depth_dive) > 0 else 0,
                #         depth_climb.max() if len(depth_climb) > 0 else 0,
                #     ),
                #     0,
                # ],
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
                "b": 125,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_pitch" % (dive_nc_file.dive_number,),
            fig,
        )
    )

    #
    # roll calculations
    #

    fitd = scipy.stats.linregress(
        rollAD[iwn].ravel(), vehicle_roll_degrees_v[iwn].ravel()
    )
    c_roll_dive_imp = -fitd.intercept / fitd.slope

    fitc = scipy.stats.linregress(
        rollAD[iwp].ravel(), vehicle_roll_degrees_v[iwp].ravel()
    )
    c_roll_climb_imp = -fitc.intercept / fitc.slope

    log_info(f"c_roll_dive {c_roll_dive_imp}, c_roll_climb {c_roll_climb_imp}")

    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_roll_C_ROLL_DIVE", c_roll_dive_imp
    )
    BaseDB.addValToDB(
        base_opts,
        dive_nc_file.dive_number,
        "implied_roll_C_ROLL_CLIMB",
        c_roll_climb_imp,
    )

    rollAD_Fit_dive = np.array([min(rollAD), max(rollAD)])
    roll_Fit_dive = fitd.intercept + fitd.slope * rollAD_Fit_dive
    rollAD_Fit_climb = np.array([min(rollAD[iwp].ravel()), max(rollAD[iwp].ravel())])
    roll_Fit_climb = fitc.intercept + fitc.slope * rollAD_Fit_climb

    #
    # roll plot
    #

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": rollAD[iwn].ravel(),
            "y": vehicle_roll_degrees_v[iwn].ravel(),
            "name": "Dive roll control/roll",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkBlue",
            },
            "hovertemplate": "RollAD<br>%{x:.0f}<br>%{y:.2f} deg<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": rollAD[iwp].ravel(),
            "y": vehicle_roll_degrees_v[iwp].ravel(),
            "name": "Climb roll control/roll",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Red",
            },
            "hovertemplate": "RollAD<br>%{x:.0f}<br>%{y:.2f} deg<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": rollAD_Fit_dive,
            "y": roll_Fit_dive,
            "name": "linfit C_ROLL_DIVE",
            "mode": "lines",
            "line": {"dash": "solid", "color": "DarkBlue"},
            "hovertemplate": f"Fit C_ROLL_DIVE={c_roll_dive_imp:.0f}<extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": rollAD_Fit_climb,
            "y": roll_Fit_climb,
            "name": "linfit C_ROLL_CLIMB",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Red"},
            "hovertemplate": f"Fit C_ROLL_CLIMB={c_roll_climb_imp:.0f}<extra></extra>",
        }
    )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Roll control vs Roll"
    fit_line = f"Best fit implies C_ROLL_DIVE={c_roll_dive_imp:.0f}ad C_ROLL_CLIMB={c_roll_climb_imp:.0f}ad"

    fig.update_layout(
        {
            "xaxis": {
                "title": f"roll control (counts)<br>{fit_line}",
                "showgrid": True,
                # "side": "top"
            },
            "yaxis": {
                "title": "roll (deg)",
                "showgrid": True,
                # "autorange": "reversed",
                # "range": [
                #     max(
                #         depth_dive.max() if len(depth_dive) > 0 else 0,
                #         depth_climb.max() if len(depth_climb) > 0 else 0,
                #     ),
                #     0,
                # ],
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
                "b": 125,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_roll" % (dive_nc_file.dive_number,),
            fig,
        )
    )

    #
    # roll rate
    #

    n = len(roll_control)
    i = 0
    centered = False
    centeredAD_d = []
    centeredRate_d = []
    centeredAD_c = []
    centeredRate_c = []

    while i < n:
        if centered is False and abs(roll_control[i]) < 5:
            centered = True
            centered_start_t = sg_time[i]
            centered_start_head = vehicle_head_degrees_v[i]
            centeredAD = rollAD[i]
            centeredN = 1
        elif centered is True and abs(roll_control[i]) > 5:
            centered = False
            if pitch_control[i] < 0 and centeredN > 1:
                centeredAD_d.append(centeredAD / centeredN)
                centeredRate_d.append(
                    headingDiff(centered_start_head, vehicle_head_degrees_v[i - 1])
                    / (sg_time[i - 1] - centered_start_t)
                )
            elif centeredN > 1:
                centeredAD_c.append(centeredAD / centeredN)
                centeredRate_c.append(
                    headingDiff(centered_start_head, vehicle_head_degrees_v[i - 1])
                    / (sg_time[i - 1] - centered_start_t)
                )

        elif centered:
            centeredAD = centeredAD + rollAD[i]
            centeredN = centeredN + 1

        i = i + 1

    ADs = []
    if len(centeredAD_d) > 1:
        fitd = scipy.stats.linregress(centeredAD_d, centeredRate_d)
        c_roll_dive_imp = -fitd.intercept / fitd.slope
        ADs = ADs + centeredAD_d + [c_roll_dive_imp]
    else:
        fitd = False

    if len(centeredAD_c) > 1:
        fitc = scipy.stats.linregress(centeredAD_c, centeredRate_c)
        c_roll_climb_imp = -fitc.intercept / fitc.slope
        ADs = ADs + centeredAD_c + [c_roll_climb_imp]
    else:
        fitc = False

    if fitc or fitd:
        rollAD_Fit = np.array([max([0,min(ADs)]), min([max(ADs), 4096])])

    if fitd is not False:
        roll_Fit_dive = fitd.intercept + fitd.slope * rollAD_Fit
    else:
        roll_Fit_dive = []

    if fitc is not False:
        roll_Fit_climb = fitc.intercept + fitc.slope * rollAD_Fit
    else:
        roll_Fit_climb = []

    #    turnRate = Utils.ctr_1st_diff(vehicle_head_degrees_v, sg_time - start_time)
    #
    #    ircd = np.where(np.logical_and(np.abs(roll_control) < 5, pitch_control < 0))
    #    ircc = np.where(np.logical_and(np.abs(roll_control) < 5, pitch_control > 0))
    #
    #    fitd = scipy.stats.linregress( rollAD[ircd].ravel(), turnRate[ircd].ravel() )
    #    c_roll_dive_imp = -fitd.intercept / fitd.slope
    #
    #    fitc = scipy.stats.linregress( rollAD[ircc].ravel(), turnRate[ircc].ravel() )
    #    c_roll_climb_imp = -fitc.intercept / fitc.slope

    #
    # roll rate plot
    #

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": centeredAD_d,
            "y": centeredRate_d,
            "name": "Roll control/turn rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "DarkBlue",
            },
            "hovertemplate": "RollAD<br>%{x:.0f}<br>%{y:.2f} deg/s<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": centeredAD_c,
            "y": centeredRate_c,
            "name": "Roll control/turn rate",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "Red",
            },
            "hovertemplate": "RollAD<br>%{x:.0f}<br>%{y:.2f} deg/s<br><extra></extra>",
        }
    )
    if len(roll_Fit_dive):
        fig.add_trace(
            {
                "x": rollAD_Fit,
                "y": roll_Fit_dive,
                "name": "linfit C_ROLL_DIVE",
                "mode": "lines",
                "line": {"dash": "solid", "color": "DarkBlue"},
                "hovertemplate": f"Fit C_ROLL_DIVE={c_roll_dive_imp:.0f}<extra></extra>",
            }
        )
    if len(roll_Fit_climb):
        fig.add_trace(
            {
                "x": rollAD_Fit,
                "y": roll_Fit_climb,
                "name": "linfit C_ROLL_CLIMB",
                "mode": "lines",
                "line": {"dash": "solid", "color": "Red"},
                "hovertemplate": f"Fit C_ROLL_CLIMB={c_roll_climb_imp:.0f}<extra></extra>",
            }
        )

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Roll control vs turn rate while centered"
    fit_line = f"Best fit implies C_ROLL_DIVE={c_roll_dive_imp:.0f}ad C_ROLL_CLIMB={c_roll_climb_imp:.0f}ad"

    fig.update_layout(
        {
            "xaxis": {
                "title": f"roll control (counts)<br>{fit_line}",
                "showgrid": True,
            },
            "yaxis": {
                "title": "turn rate (deg/s)",
                "showgrid": True,
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
                "b": 125,
            },
        }
    )

    figs_list.append(fig)
    file_list.append(
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_roll_rate" % (dive_nc_file.dive_number,),
            fig,
        )
    )

    return (figs_list, file_list)
