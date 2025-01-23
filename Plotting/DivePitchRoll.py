#t  /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022, 2023, 2024 by University of Washington.  All rights reserved.
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


def pitchfun_shift_solved(x, pitch, ad, vbd, cnv):
    c = x[0]
    g = x[1]
    s = x[2]

    p = g*(cnv*(ad - c) - vbd*s)
    return np.sqrt(np.nanmean((p - pitch)**2))

def pitchfun_shift_fixed(x, pitch, ad, vbd, cnv, s):
    c = x[0]
    g = x[1]

    p = g*(cnv*(ad - c) - vbd*s)
    return np.sqrt(np.nanmean((p - pitch)**2))

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
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plots pitch and roll regressions"""
    log_info("Starting dive_pitch_roll")

    if "eng_pitchAng" not in dive_nc_file.variables:
        log_error("No compass in nc - skipping")
        return ([], [])

    # Preliminaries
    try:
        start_time = dive_nc_file.start_time

        # unused
        # mhead = (
        #     dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
        #     .tobytes()
        #     .decode("utf-8")
        #     .split(",")
        # )

        c_pitch = dive_nc_file.variables["log_C_PITCH"].getValue()
        pitch_gain = dive_nc_file.variables["log_PITCH_GAIN"].getValue()
        # unused
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
        vbd_cnv = dive_nc_file.variables["log_VBD_CNV"].getValue()
        vbd_shift = dive_nc_file.variables["log_PITCH_VBD_SHIFT"].getValue()
        c_vbd = dive_nc_file.variables["log_C_VBD"].getValue()
        c_roll_dive = dive_nc_file.variables["log_C_ROLL_DIVE"].getValue()
        c_roll_climb = dive_nc_file.variables["log_C_ROLL_CLIMB"].getValue()

        # SG eng time base
        sg_time = dive_nc_file.variables["time"][:]
        depth = dive_nc_file.variables["depth"][:]
        vehicle_pitch_degrees_v = dive_nc_file.variables["eng_pitchAng"][:]
        vehicle_roll_degrees_v = dive_nc_file.variables["eng_rollAng"][:]
        vehicle_head_degrees_v = dive_nc_file.variables["eng_head"][:]
        sg_np = dive_nc_file.dimensions["sg_data_point"].size

        GC_st_secs = dive_nc_file.variables["gc_st_secs"][:]
        GC_end_secs = dive_nc_file.variables["gc_end_secs"][:]
        GC_vbd_secs = dive_nc_file.variables["gc_vbd_secs"][:]
        GC_pitch_AD_start = dive_nc_file.variables["gc_pitch_ad_start"][:]
        GC_pitch_AD_end = dive_nc_file.variables["gc_pitch_ad"][:]

        GC_roll_AD_start = dive_nc_file.variables["gc_roll_ad_start"][:]
        GC_roll_AD_end = dive_nc_file.variables["gc_roll_ad"][:]

        pot1_start = dive_nc_file.variables["gc_vbd_pot1_ad_start"][:]
        pot2_start = dive_nc_file.variables["gc_vbd_pot2_ad_start"][:]
        pot1 = dive_nc_file.variables["gc_vbd_pot1_ad"][:]
        pot2 = dive_nc_file.variables["gc_vbd_pot2_ad"][:]
        try:
            vbd_lp_ignore = dive_nc_file.variables["log_VBD_LP_IGNORE"].getValue()
        except KeyError:
            vbd_lp_ignore = 0  # both available
        if vbd_lp_ignore == 0:
            GC_vbd_AD_start = np.zeros(np.size(pot1_start))
            GC_vbd_AD_end = np.zeros(np.size(pot1))
            for ii in range(np.size(pot1_start)):
                GC_vbd_AD_start[ii] = np.nanmean([pot1_start[ii], pot2_start[ii]])
                GC_vbd_AD_end[ii] = np.nanmean([pot1[ii], pot2[ii]])
        elif vbd_lp_ignore == 1:
            GC_vbd_AD_start = pot2_start
            GC_vbd_AD_end = pot2
        elif vbd_lp_ignore == 2:
            GC_vbd_AD_start = pot1_start
            GC_vbd_AD_end = pot1
    except KeyError as e:
        log_error(
            f"Could not fetch needed variables {e} - skipping pitch and roll plots - skipping",
        )
        return ([], [])
    except Exception:
        log_error("Problems in pitch and roll plots - skipping", "exc")
        return ([], [])


    try:
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

        # unused nGC = len(GC_st_secs) * 2
        gc_t = np.concatenate((GC_st_secs, GC_end_secs))
        gc_t = np.transpose(gc_t).ravel()
        gc_x = np.concatenate((GC_pitch_AD_start, GC_pitch_AD_end))
        gc_x = np.transpose(gc_x).ravel()

        f = scipy.interpolate.interp1d(
            gc_t,
            gc_x,
            kind="linear",
            bounds_error=False,
            fill_value=(gc_x[0], gc_x[-1]),  # "extrapolate"
        )
        pitchAD = f(sg_time)
        pitch_control = (pitchAD - c_pitch) * pitch_cnv

        pitch_AD_rate = Utils.ctr_1st_diff(pitchAD, sg_time)
        pitch_rate = Utils.ctr_1st_diff(vehicle_pitch_degrees_v, sg_time)

        iwn = np.argwhere(pitch_control < 0)
        iwp = np.argwhere(pitch_control > 0)

        gc_x = np.concatenate((GC_roll_AD_start, GC_roll_AD_end))
        gc_x = np.transpose(gc_x).ravel()

        f = scipy.interpolate.interp1d(
            gc_t,
            gc_x,
            kind="linear",
            bounds_error=False,
            fill_value=(gc_x[0], gc_x[-1]),  # "extrapolate"
        )
        rollAD = f(sg_time)
        roll_control = (rollAD - c_roll_dive) * roll_cnv
        roll_control[iwp] = (rollAD[iwp] - c_roll_climb) * roll_cnv
        # unused pitch_control_slope = 1.0 / pitch_cnv

        gc_x = np.concatenate((GC_vbd_AD_start, GC_vbd_AD_end))
        gc_x = np.transpose(gc_x).ravel()
    except Exception as e:
        log_error(
            f"Could not interp needed variables {e} - skipping pitch and roll plots",
            "exc",
        )
        return ([], [])

    try:
        f = scipy.interpolate.interp1d(
            gc_t,
            gc_x,
            kind="linear",
            bounds_error=False,
            fill_value=(gc_x[0], gc_x[-1]),  # "extrapolate"
        )
        vbdAD = f(sg_time)
        vbd_control = (vbdAD - c_vbd) * vbd_cnv
    except:
        vbd_control = None

    t_stable_pitch = sg_time.copy()
    t_stable_roll = sg_time.copy()
    
    for k, t in enumerate(sg_time):
        t_stable_roll[k] = False
        t_stable_pitch[k] = False
        for j, tg in enumerate(GC_st_secs):
            if t > tg and t < GC_end_secs[j] and GC_vbd_secs[j] == 0:
                t_stable_pitch[k] = t > (tg + 10)
                t_stable_roll[k] = t > (tg + 30)
                break
            elif (t > GC_end_secs[j] and j < len(GC_st_secs) - 1 and t < GC_st_secs[j+1]) or j == len(GC_st_secs) - 1:
                t_stable_pitch[k] = t > (GC_end_secs[j] + 10)
                t_stable_roll[k] = t > (GC_end_secs[j] + 30)
                break

    #
    # pitch calculations
    #


    xmax = 3.5
    xmin = -3.5
    in_fit = np.logical_and.reduce(
        (
            pitch_AD_rate < 2,
            pitch_AD_rate > -2,
            pitch_rate > -0.02,
            pitch_rate < 0.02,
            pitch_control < xmax,
            pitch_control > xmin,
            roll_control < 10,
            roll_control > -10,
            t_stable_pitch,
            depth > 7,
        )
    )

    inds = np.nonzero(in_fit)[0]
    outside_inds = np.nonzero(np.logical_not(in_fit))[0]

    # current "model" result
    pitch_curr =  pitch_gain * (pitch_cnv*(pitchAD[inds] - c_pitch) - vbd_control[inds] * vbd_shift)
    rms_curr = np.sqrt(np.nanmean((pitch_curr - vehicle_pitch_degrees_v[inds])**2))

    # linear model
    fit = scipy.stats.linregress(pitchAD[inds], vehicle_pitch_degrees_v[inds])
    implied_C = -fit.intercept / fit.slope
    implied_gain = fit.slope / pitch_cnv
    
    pitch_linear =  implied_gain * (pitch_cnv*(pitchAD[inds] - implied_C) - vbd_control[inds] * vbd_shift)
    rms_linear = np.sqrt(np.nanmean((pitch_linear - vehicle_pitch_degrees_v[inds])**2))

    log_info(f"implied_cpitch {implied_C}, implied_pitchgain {implied_gain}, RMS={rms_linear}")

    if dbcon == None:
        conn = Utils.open_mission_database(base_opts)
        log_info("plot_pitch_roll db opened")
    else:
        conn = dbcon

    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "pitch_flying_rmse", rms_curr, con=conn
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "pitch_linear_rmse", rms_linear, con=conn
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "pitch_linear_C_PITCH", implied_C, con=conn
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "pitch_linear_PITCH_GAIN", implied_gain, con=conn
    )
    try:
        BaseDB.addSlopeValToDB(
            base_opts, dive_nc_file.dive_number, ["pitch_linear_C_PITCH"], con=conn
        )
    except:
        log_error("Failed to add slope value to database", "exc")

    c0 = [0, 0]
    c1 = [0, 0, 0]
    if vbd_control is not None:
        try:
            c0, rms_0, niter, calls, warns = scipy.optimize.fmin(func=pitchfun_shift_fixed,
                                                                x0=[c_pitch, pitch_gain],
                                                                args=(vehicle_pitch_degrees_v[inds], pitchAD[inds], vbd_control[inds], pitch_cnv, vbd_shift),
                                                                maxiter=500, maxfun=1000, ftol=1e-3, full_output=True, disp=True)

            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_fixed_rmse", rms_0, con=conn
            )
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_fixed_C_PITCH", c0[0], con=conn
            )
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_fixed_PITCH_GAIN", c0[1], con=conn
            )
        except Exception as e:
            log_error(e)
            pass

        try:
            c1, rms_1, niter, calls, warns = scipy.optimize.fmin(func=pitchfun_shift_solved,
                                                                x0=[c_pitch, pitch_gain, vbd_shift],
                                                                args=(vehicle_pitch_degrees_v[inds], pitchAD[inds], vbd_control[inds], pitch_cnv),
                                                                maxiter=500, maxfun=1000, ftol=1e-3, full_output=True, disp=True)
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_shift_rmse", rms_1, con=conn
            )
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_shift_C_PITCH", c1[0], con=conn
            )
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_shift_PITCH_GAIN", c1[1], con=conn
            )
            BaseDB.addValToDB(
                base_opts, dive_nc_file.dive_number, "pitch_shift_PITCH_VBD_SHIFT", c1[2], con=conn
            )
        except Exception as e:
            log_error(e)
            pass

    ctr0 = c0[0]
    gain0 = c0[1]

    ctr1 = c1[0]
    gain1 = c1[1]
    shift1 = c1[2]

    pitch_0 =  gain0 * (pitch_cnv*(pitchAD[inds] - ctr0) - vbd_control[inds] * vbd_shift)
    pitch_1 =  gain1 * (pitch_cnv*(pitchAD[inds] - ctr1) - vbd_control[inds] * shift1)

    figs_list = []
    file_list = []

    if generate_plots:
        pitchAD_Fit = [min(pitchAD), max(pitchAD)]
        pitch_Fit = (pitchAD_Fit - implied_C) * implied_gain * pitch_cnv

        #
        # pitch plot
        #

        fig = plotly.graph_objects.Figure()

        customdata = np.squeeze(
                        np.dstack(
                            (
                                np.transpose(pitch_control[inds]),
                                np.transpose(roll_control[inds]),
                            )
                        )
                     )

        pitch_template = "PitchAD %{x:.0f}<br>obs pitch %{y:.2f} deg<br>pitch ctrl %{customdata[0]:.2f} cm<br>roll ctrl %{customdata[1]:.2f} deg<extra></extra>"

        fig.add_trace(
            {
                "x": pitchAD[outside_inds],
                "y": vehicle_pitch_degrees_v[outside_inds],
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(pitch_control[outside_inds]),
                            np.transpose(roll_control[outside_inds]),
                        )
                    )
                ),
                "name": "Observed pitch (not used in fit)",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "LightBlue",
                },
                # "mode": "lines",
                # "line": {"dash": "solid", "color": "Blue"},
                "hovertemplate": pitch_template,
                "visible": "legendonly",
            }
        )


        fig.add_trace(
            {
                "x": pitchAD[inds],
                "y": vehicle_pitch_degrees_v[inds],
                "customdata": customdata,
                "name": "Observed pitch (used in fits)",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "black",
                },
                # "mode": "lines",
                # "line": {"dash": "solid", "color": "Blue"},
                "hovertemplate": pitch_template,
            }
        )

        fig.add_trace(
            {
                "x": pitchAD[inds],
                "y": pitch_curr,
                "customdata": customdata,
                "name": f"<b>Model as flying on glider</b><br>C_PITCH={c_pitch:.0f},GAIN={pitch_gain:.2f},SHIFT={vbd_shift:.4f}<br>RMS={rms_curr:.2f}&#176;",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle",
                    "color": "blue",
                },
                "hovertemplate": pitch_template,
            }
        )
        fig.add_trace(
            {
                "x": pitchAD[inds],
                "y": pitch_linear,
                "customdata": customdata,
                "name": f"<b>Linear fit</b><br>&#8594;C_PITCH={implied_C:.0f},GAIN={implied_gain:.2f}<br>RMS={rms_linear:.2f}&#176;",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle",
                    "color": "salmon",
                },
                "hovertemplate": pitch_template,
            }
        )
        if ctr0 > 0:
            fig.add_trace(
                {
                    "x": pitchAD[inds],
                    "y": pitch_0,
                    "customdata": customdata,
                    "name": f"<b>Nonlinear fit fixed shift</b><br>&#8594;C_PITCH={ctr0:.0f},GAIN={gain0:.2f}<br>RMS={rms_0:.2f}&#176;",
                    "type": "scatter",
                    "mode": "markers",
                    "marker": {
                        "symbol": "circle",
                        "color": "crimson",
                    },
                    "hovertemplate": pitch_template,
                }
            )
        if ctr1 > 0:
            fig.add_trace(
                {
                    "x": pitchAD[inds],
                    "y": pitch_1,
                    "customdata": customdata,
                    "name": f"<b>Nonlinear fit</b><br>&#8594;C_PITCH={ctr1:.0f},GAIN={gain1:.2f},SHIFT={shift1:.4f}<br>RMS={rms_1:.2f}&#176;",
                    "type": "scatter",
                    "mode": "markers",
                    "marker": {
                        "symbol": "circle",
                        "color": "magenta",
                    },
                    "hovertemplate": pitch_template,
                }
            )


        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Pitch control vs Pitch<br>Models closer to observed (black triangles) are better. Lower RMS values (model pitch - observed pitch) are better."

        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"pitch control (counts)",
                        "font": {"family": "Courier New, Arial"},
                    },
                    "showgrid": True,
                    # "side": "top"
                },
                "yaxis": {
                    "title": "pitch (deg)",
                    "showgrid": True,
                    "autorange": True,
                    # "autorangeoptions": dict(clipmin=-70, clipmax=70),
                    # "range": [-70,70],
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

    in_fit_d = np.logical_and.reduce(
        (
            pitch_control < 0,
            depth > 7,
            t_stable_roll,
            pitch_AD_rate < 2,
            pitch_AD_rate > -2,
            pitch_rate > -0.02,
            pitch_rate < 0.02,
        )
    )
    in_fit_c = np.logical_and.reduce(
        (
            pitch_control > 0,
            depth > 7,
            t_stable_roll,
            pitch_AD_rate < 2,
            pitch_AD_rate > -2,
            pitch_rate > -0.02,
            pitch_rate < 0.02,
        )
    )

    try:
        fitd = scipy.stats.linregress(
            rollAD[in_fit_d].ravel(), vehicle_roll_degrees_v[in_fit_d].ravel()
        )
        c_roll_dive_imp = -fitd.intercept / fitd.slope
    except:
        c_roll_dive_imp = 0
        fitd = None

    try:
        fitc = scipy.stats.linregress(
            rollAD[in_fit_c].ravel(), vehicle_roll_degrees_v[in_fit_c].ravel()
        )
        c_roll_climb_imp = -fitc.intercept / fitc.slope
    except:
        c_roll_climb_imp = 0
        fitc = None
 
    log_info(f"c_roll_dive {c_roll_dive_imp}, c_roll_climb {c_roll_climb_imp}")

    BaseDB.addValToDB(
        base_opts,
        dive_nc_file.dive_number,
        "roll_C_ROLL_DIVE",
        c_roll_dive_imp,
        con=conn,
    )
    BaseDB.addValToDB(
        base_opts,
        dive_nc_file.dive_number,
        "roll_C_ROLL_CLIMB",
        c_roll_climb_imp,
        con=conn,
    )


    if fitd:
        rollAD_Fit_dive = np.array([min(rollAD), max(rollAD)])
        roll_Fit_dive = fitd.intercept + fitd.slope * rollAD_Fit_dive

    if fitc:
        rollAD_Fit_climb = np.array([min(rollAD[iwp].ravel()), max(rollAD[iwp].ravel())])
        roll_Fit_climb = fitc.intercept + fitc.slope * rollAD_Fit_climb

    #
    # roll plot - implied centers for roll rate not generated without plots
    #

    if generate_plots:
        customdata_d = np.squeeze(
                           np.dstack(
                               (
                                   np.transpose((sg_time[in_fit_d] - start_time)/60.0),
                                   np.transpose(pitch_control[in_fit_d]),
                                   np.transpose(roll_control[in_fit_d]),
                               )
                           )
                       )    
        customdata_c = np.squeeze(
                           np.dstack(
                               (
                                   np.transpose((sg_time[in_fit_c] - start_time)/60.0),
                                   np.transpose(pitch_control[in_fit_c]),
                                   np.transpose(roll_control[in_fit_c]),
                               )
                           )
                       )    

        fig = plotly.graph_objects.Figure()
        fig.add_trace(
            {
                "x": rollAD[in_fit_d].ravel(),
                "y": vehicle_roll_degrees_v[in_fit_d].ravel(),
                "customdata": customdata_d,
                "name": "Observed roll - dive",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkBlue",
                },
                "hovertemplate": "RollAD %{x:.0f}<br>%{y:.2f} deg<br>t=%{customdata[0]:.2f}<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": [c_roll_dive],
                "y": [0],
                "name": f"<b>Current center - dive</b><br>C_ROLL_DIVE={c_roll_dive:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "square",
                    "color": "DarkBlue",
                },
                "hovertemplate": "C_ROLL_DIVE=%{x:.0f}<extra></extra>",
            }
        )
        if fitd:
            fig.add_trace(
                {
                    "x": rollAD_Fit_dive,
                    "y": roll_Fit_dive,
                    "name": f"<b>Linear model - dive</b><br>&#8594;C_ROLL_DIVE={c_roll_dive_imp:.0f}",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "DarkBlue"},
                    "hovertemplate": f"Fit C_ROLL_DIVE={c_roll_dive_imp:.0f}<extra></extra>",
                }
            )
        fig.add_trace(
            {
                "x": rollAD[in_fit_c].ravel(),
                "y": vehicle_roll_degrees_v[in_fit_c].ravel(),
                "customdata": customdata_c,
                "name": "Observed roll - climb",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Red",
                },
                "hovertemplate": "RollAD %{x:.0f}<br>%{y:.2f} deg<br>t=%{customdata[0]:.2f}<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": [c_roll_climb],
                "y": [0],
                "name": f"<b>Current center - climb</b><br>C_ROLL_CLIMB={c_roll_climb:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "square",
                    "color": "Red",
                },
                "hovertemplate": "C_ROLL_CLIMB=%{x:.0f}<extra></extra>",
            }
        )
        if fitc:
            fig.add_trace(
                {
                    "x": rollAD_Fit_climb,
                    "y": roll_Fit_climb,
                    "name": f"<b>Linear model - climb</b><br>&#8594;C_ROLL_DIVE={c_roll_climb_imp:.0f}",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "Red"},
                    "hovertemplate": f"Fit C_ROLL_CLIMB={c_roll_climb_imp:.0f}<extra></extra>",
                }
            )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Roll control vs Roll"

        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"roll control (counts)",
                        "font": {
                            "family": "Courier New, Arial",
                        },
                    },
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
                    "b": 50,
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
    centeredStart_t_c = []
    centeredPitch_c = []
    centeredAD_c = []
    centeredRate_c = []
    centeredStart_t_d = []
    centeredPitch_d = []

    while i < n:
        if centered is False and abs(roll_control[i]) < 10 and t_stable_roll[i]:
            centered = True
            centered_start_t = sg_time[i]
            centered_start_head = vehicle_head_degrees_v[i]
            centered_pitch = vehicle_pitch_degrees_v[i]
            centeredAD = rollAD[i]
            centeredN = 1
        elif centered is True and (abs(roll_control[i]) > 10 or not t_stable_roll[i]):
            centered = False
            if pitch_control[i] < 0 and centeredN > 1:
                centeredAD_d.append(centeredAD / centeredN)
                centeredRate_d.append(
                    headingDiff(centered_start_head, vehicle_head_degrees_v[i - 1])
                    / (sg_time[i - 1] - centered_start_t)
                )
                centeredStart_t_d.append(centered_start_t)
                centeredPitch_d.append(centered_pitch)
            elif centeredN > 1:
                centeredAD_c.append(centeredAD / centeredN)
                centeredRate_c.append(
                    headingDiff(centered_start_head, vehicle_head_degrees_v[i - 1])
                    / (sg_time[i - 1] - centered_start_t)
                )
                centeredStart_t_c.append(centered_start_t)
                centeredPitch_c.append(centered_pitch)

        elif centered and abs(vehicle_pitch_degrees_v[i]) < 45:
            centeredAD = centeredAD + rollAD[i]
            centeredN = centeredN + 1

        i = i + 1

    ADs = []
    if len(centeredAD_d) > 1:
        try:
            fitd = scipy.stats.linregress(centeredAD_d, centeredRate_d)
            c_roll_dive_imp = -fitd.intercept / fitd.slope
            ADs = ADs + centeredAD_d + [c_roll_dive_imp]

            BaseDB.addValToDB(
                base_opts,
                dive_nc_file.dive_number,
                "turn_centered_C_ROLL_DIVE",
                c_roll_dive_imp,
                con=conn,
            )
        except:
            c_roll_dive_imp = 0
            fitd = False

    else:
        fitd = False

    if len(centeredAD_c) > 1:
        try:
            fitc = scipy.stats.linregress(centeredAD_c, centeredRate_c)
            c_roll_climb_imp = -fitc.intercept / fitc.slope
            ADs = ADs + centeredAD_c + [c_roll_climb_imp]

            BaseDB.addValToDB(
                base_opts,
                dive_nc_file.dive_number,
                "turn_centered_C_ROLL_CLIMB",
                c_roll_climb_imp,
                con=conn,
            )
        except:
            fitc = False
            c_roll_climb_imp = 0

    else:
        fitc = False

    if fitc or fitd:
        rollAD_Fit = np.array([max([0, min(ADs)]), min([max(ADs), 4096])])

    if fitd is not False:
        roll_Fit_dive = fitd.intercept + fitd.slope * rollAD_Fit
    else:
        roll_Fit_dive = []

    if fitc is not False:
        roll_Fit_climb = fitc.intercept + fitc.slope * rollAD_Fit
    else:
        roll_Fit_climb = []

    hdgdiff = np.concatenate((np.array([0]), np.diff(vehicle_head_degrees_v)))
    hdgdiff = np.mod(hdgdiff, 360)
    idw = np.where(hdgdiff > 180)
    hdgdiff[idw] = hdgdiff[idw] - 360
    hdgwrapped = hdgdiff[0] + np.cumsum(hdgdiff)
    turnRate = Utils.ctr_1st_diff(hdgwrapped, sg_time)  #  - start_time)

    # ircd = np.where(np.logical_and(np.abs(roll_control) < 5, pitch_control < 0))
    # ircc = np.where(np.logical_and(np.abs(roll_control) < 5, pitch_control > 0))
    ircd = in_fit_d # np.where(pitch_control < 0)
    ircc = in_fit_c # np.where(pitch_control > 0)

    rollAD_Fit_all = np.array([max([0, min(rollAD)]), min([max(rollAD), 4096])])

    try:
        fitd = scipy.stats.linregress(rollAD[ircd].ravel(), turnRate[ircd].ravel())
        c_roll_dive_imp_all = -fitd.intercept / fitd.slope
        roll_Fit_dive_all = fitd.intercept + fitd.slope * rollAD_Fit_all

        BaseDB.addValToDB(
            base_opts,
            dive_nc_file.dive_number,
            "turn_all_C_ROLL_DIVE",
            c_roll_dive_imp_all,
            con=conn,
        )
    except:
        c_roll_dive_imp_all = 0
        fitd = None

    try:
        fitc = scipy.stats.linregress(rollAD[ircc].ravel(), turnRate[ircc].ravel())
        c_roll_climb_imp_all = -fitc.intercept / fitc.slope
        roll_Fit_climb_all = fitc.intercept + fitc.slope * rollAD_Fit_all

        BaseDB.addValToDB(
            base_opts,
            dive_nc_file.dive_number,
            "turn_all_C_ROLL_CLIMB",
            c_roll_climb_imp_all,
            con=conn,
        )
    except:
        fitc = None
        c_roll_climb_imp_all = 0


        #
        # roll rate plot
        #
    if generate_plots:
        roll_rate_template = "AvgRollAD %{x:.0f}<br>AvgRate %{y:.2f} deg/s<br>Time %{customdata[0]:.2f} min<br>PitchObs %{customdata[1]:.2f} deg<extra></extra>"

        fig = plotly.graph_objects.Figure()
        fig.add_trace(
            {
                "x": rollAD[ircd],
                "y": turnRate[ircd],
                "name": "Observed turn rate - dive",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkBlue",
                },
                "hovertemplate": "RollAD %{x:.0f}<br>Rate %{y:.2f} deg/s<br><extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": centeredAD_d,
                "y": centeredRate_d,
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(centeredStart_t_d - start_time) / 60.0,
                            np.transpose(centeredPitch_d),
                        )
                    )
                ),
                "name": "Observed turn rate while centered - dive",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle-open",
                    "color": "DarkBlue",
                },
                "hovertemplate": roll_rate_template,
            }
        )
        fig.add_trace(
            {
                "x": [c_roll_dive],
                "y": [0],
                "name": f"<b>Current center - dive</b><br>C_ROLL_DIVE={c_roll_dive:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "square",
                    "color": "DarkBlue",
                },
                "hovertemplate": "C_ROLL_DIVE=%{x:.0f}<extra></extra>",
            }
        )
        if fitd:
            fig.add_trace(
                {
                    "x": rollAD_Fit_all,
                    "y": roll_Fit_dive_all,
                    "name": f"<b>All data linear model - dive</b><br>&#8594;C_ROLL_DIVE={c_roll_dive_imp_all:.0f}",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "DarkBlue"},
                    "hovertemplate": f"Fit all C_ROLL_DIVE={c_roll_dive_imp_all:.0f}<extra></extra>",
                }
            )
        if len(roll_Fit_dive):
            fig.add_trace(
                {
                    "x": rollAD_Fit,
                    "y": roll_Fit_dive,
                    "name": f"<b>Centered data linear model - dive</b><br>&#8594;C_ROLL_DIVE={c_roll_dive_imp:.0f}",
                    "mode": "lines",
                    "line": {"dash": "dash", "color": "DarkBlue"},
                    "hovertemplate": f"centered Fit C_ROLL_DIVE={c_roll_dive_imp:.0f}<extra></extra>",
                }
            )

        fig.add_trace(
            {
                "x": rollAD[ircc],
                "y": turnRate[ircc],
                "name": "Observed turn rate - climb",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Red",
                },
                "hovertemplate": "RollAD %{x:.0f}<br>Rate %{y:.2f} deg/s<br><extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": centeredAD_c,
                "y": centeredRate_c,
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(centeredStart_t_c - start_time) / 60.0,
                            np.transpose(centeredPitch_c),
                        )
                    )
                ),
                "name": "Observed turn rate while centered - climb",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle-open",
                    "color": "Red",
                },
                "hovertemplate": roll_rate_template,
            }
        )
        fig.add_trace(
            {
                "x": [c_roll_climb],
                "y": [0],
                "name": f"<b>Current center - climb</b><br>C_ROLL_CLIMB={c_roll_climb:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "square",
                    "color": "Red",
                },
                "hovertemplate": "C_ROLL_CLIMB=%{x:.0f}<extra></extra>",
            }
        )

        if fitc:
            fig.add_trace(
                {
                    "x": rollAD_Fit_all,
                    "y": roll_Fit_climb_all,
                    "name": f"<b>All data linear model - climb</b><br>&#8594;C_ROLL_CLIMB={c_roll_climb_imp_all:.0f}",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "Red"},
                    "hovertemplate": f"Fit all C_ROLL_CLIMB={c_roll_climb_imp_all:.0f}<extra></extra>",
                }
            )
        if len(roll_Fit_climb):
            fig.add_trace(
                {
                    "x": rollAD_Fit,
                    "y": roll_Fit_climb,
                    "name": f"<b>Centered data linear model - climb</b><br>&#8594;C_ROLL_CLIMB={c_roll_climb_imp:.0f}",
                    "mode": "lines",
                    "line": {"dash": "dash", "color": "Red"},
                    "hovertemplate": f"centered Fit C_ROLL_CLIMB={c_roll_climb_imp:.0f}<extra></extra>",
                }
            )

        traces = []
        for d in fig.data:
            traces.append(d["name"])

        ctlTraces = {}

        ctlTraces["all data"] = [
            "Observed turn rate - dive",
            "Observed turn rate - climb",
            "All data linear model - dive",
            "All data linear model - climb",
        ]
        ctlTraces["centered data"] = [
            "Observed turn rate while centered - dive",
            "Observed turn rate while centered - climb",
            "Centered data linear model - dive",
            "Centered data linear model - climb",
        ]

        buttons = [ ]

        for c in ctlTraces.keys():
            buttons.append(
                dict(
                    args2=[
                        {"visible": True},
                        [i for i, x in enumerate(traces) if any(filter(lambda y: y in x, ctlTraces[c]))],
                    ],
                    args=[
                        {"visible": "legendonly"},
                        [i for i, x in enumerate(traces) if any(filter(lambda y: y in x, ctlTraces[c]))],
                    ],
                    label=c,
                    method="restyle",
                    visible=True,
                )
            )

        fig.update_layout(
            updatemenus=[
                dict(
                    type="buttons",
                    direction="left",
                    buttons=buttons,
                    x=1.2,
                    y=1.06,
                    visible=True,
                    showactive=False,
                ),
            ]
        )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Roll control vs turn rate"
        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"roll control (counts)",
                        "font": {"family": "Courier New, Arial"},
                    },
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
                    "b": 60,
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

    if dbcon == None:
        try:
            conn.commit()
        except Exception as e:
            conn.rollback()
            log_error(f"Failed commit, DivePitchRoll {e}", "exc")

        conn.close()
        log_info("plot_pitch_roll db closed")

    # log_info("Leaving dive_pitch_roll")
    return (figs_list, file_list)
