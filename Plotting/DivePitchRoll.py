#t  /usr/bin/env python
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


class pitchFitClass:
    def __init__(self):
        pass

    def fitfun_shift_fixed(self, x, ctr, gain):
        y = gain * (x[:, 0] * self.cnv - ctr * self.cnv - x[:, 1] * self.shift)
        return y

    def fitfun_shift_solved(self, x, ctr, gain, shift):
        return gain * (x[:, 0] * self.cnv - ctr * self.cnv - x[:, 1] * shift)


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
        vehicle_pitch_degrees_v = dive_nc_file.variables["eng_pitchAng"][:]
        vehicle_roll_degrees_v = dive_nc_file.variables["eng_rollAng"][:]
        vehicle_head_degrees_v = dive_nc_file.variables["eng_head"][:]
        sg_np = dive_nc_file.dimensions["sg_data_point"].size

        GC_st_secs = dive_nc_file.variables["gc_st_secs"][:]
        GC_end_secs = dive_nc_file.variables["gc_end_secs"][:]
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
    except Exception as e:
        log_error(
            f"Could not fetch needed variables {e} - skipping pitch and roll plots",
            "exc",
        )
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

    #
    # pitch calculations
    #

    xmax = 3.5
    xmin = -3.5
    in_fit = np.logical_and.reduce(
        (
            pitch_AD_rate < 2,
            pitch_AD_rate > -2,
            pitch_control < xmax,
            pitch_control > xmin,
            roll_control < 10,
            roll_control > -10,
        )
    )

    inds = np.nonzero(in_fit)[0]
    outside_inds = np.nonzero(np.logical_not(in_fit))[0]

    fit = scipy.stats.linregress(pitchAD[inds], vehicle_pitch_degrees_v[inds])
    implied_C = -fit.intercept / fit.slope
    implied_gain = fit.slope / pitch_cnv

    log_info(f"implied_cpitch {implied_C}, implied_pitchgain {implied_gain}")

    if dbcon == None:
        conn = Utils.open_mission_database(base_opts)
        log_info("plot_pitch_roll db opened")
    else:
        conn = dbcon

    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_C_PITCH", implied_C, con=conn
    )
    BaseDB.addValToDB(
        base_opts,
        dive_nc_file.dive_number,
        "implied_PITCH_GAIN",
        implied_gain,
        con=conn,
    )
    try:
        BaseDB.addSlopeValToDB(
            base_opts, dive_nc_file.dive_number, ["implied_C_PITCH"], con=conn
        )
    except:
        log_error("Failed to add slope value to database", "exc")

    inst = pitchFitClass()
    inst.cnv = pitch_cnv
    inst.shift = vbd_shift

    c0 = [[0, 0]]
    c1 = [[0, 0, 0]]
    if vbd_control is not None:
        try:
            c0 = scipy.optimize.curve_fit(
                inst.fitfun_shift_fixed,
                np.column_stack((pitchAD[inds], vbd_control[inds])),
                vehicle_pitch_degrees_v[inds],
                p0=[c_pitch, pitch_gain],
            )
        except:
            pass

        # c1 = scipy.optimize.curve_fit(inst.fitfun_shift_solved, np.column_stack((pitchAD[inds], vbd_control[inds])), vehicle_pitch_degrees_v[inds], p0=[ c_pitch, pitch_gain, vbd_shift ], bounds=([100, 5, 0.0005], [4000, 75, 0.005]))
        try:
            c1 = scipy.optimize.curve_fit(
                inst.fitfun_shift_solved,
                np.column_stack((pitchAD[inds], vbd_control[inds])),
                vehicle_pitch_degrees_v[inds],
                p0=[c_pitch, pitch_gain, vbd_shift],
            )
        except:
            pass

    ctr0 = c0[0][0]
    gain0 = c0[0][1]
    ctr1 = c1[0][0]
    gain1 = c1[0][1]
    shift1 = c1[0][2]

    figs_list = []
    file_list = []

    if generate_plots:
        pitchAD_Fit = [min(pitchAD), max(pitchAD)]
        pitch_Fit = (pitchAD_Fit - implied_C) * implied_gain * pitch_cnv

        #
        # pitch plot
        #

        fig = plotly.graph_objects.Figure()

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
                "name": "Pitch control/Pitch (not used in fit)",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "LightBlue",
                },
                # "mode": "lines",
                # "line": {"dash": "solid", "color": "Blue"},
                "hovertemplate": pitch_template,
            }
        )

        fig.add_trace(
            {
                "x": pitchAD[inds],
                "y": vehicle_pitch_degrees_v[inds],
                "customdata": np.squeeze(
                    np.dstack(
                        (
                            np.transpose(pitch_control[inds]),
                            np.transpose(roll_control[inds]),
                        )
                    )
                ),
                "name": "Pitch control/Pitch (used in fit)",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-down",
                    "color": "DarkBlue",
                },
                # "mode": "lines",
                # "line": {"dash": "solid", "color": "Blue"},
                "hovertemplate": pitch_template,
            }
        )
        if min(pitch_Fit) > -120 and max(pitch_Fit) < 120:
            fig.add_trace(
                {
                    "x": pitchAD_Fit,
                    "y": pitch_Fit,
                    "name": "linfit C_PITCH, PITCH_GAIN",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "Red"},
                    "hovertemplate": f"Fit w/o VBD shift C_PITCH={implied_C:.0f} PITCH_GAIN={implied_gain:.2f}<br><extra></extra>",
                }
            )

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Pitch control vs Pitch"
        fit_line = f"<br>     Linear (w/o VBD shift): C_PITCH={implied_C:.0f}ad PITCH_GAIN={implied_gain:.2f}deg/cm                              <br>"
        fit_line += f"Nonlinear w/VBD shift fixed: C_PITCH={ctr0:.0f}ad PITCH_GAIN={gain0:.2f}deg/cm                              <br>"
        fit_line += f"      Nonlinear w/VBD shift: C_PITCH={ctr1:.0f}ad PITCH_GAIN={gain1:.2f}deg/cm PITCH_VBD_SHIFT={shift1:.5f}cm/cc<br>"
        fit_line += f"                  Current: C_PITCH={c_pitch:.0f}ad PITCH_GAIN={pitch_gain:.0f}deg/cm PITCH_VBD_SHIFT={vbd_shift:.5f}cm/cc."

        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"pitch control (counts)<br>{fit_line}",
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
        base_opts,
        dive_nc_file.dive_number,
        "implied_roll_C_ROLL_DIVE",
        c_roll_dive_imp,
        con=conn,
    )
    BaseDB.addValToDB(
        base_opts,
        dive_nc_file.dive_number,
        "implied_roll_C_ROLL_CLIMB",
        c_roll_climb_imp,
        con=conn,
    )

    if dbcon == None:
        try:
            conn.commit()
        except Exception as e:
            conn.rollback()
            log_error(f"Failed commit, DivePitchRoll {e}", "exc")

        conn.close()
        log_info("plot_pitch_roll db closed")

    rollAD_Fit_dive = np.array([min(rollAD), max(rollAD)])
    roll_Fit_dive = fitd.intercept + fitd.slope * rollAD_Fit_dive
    rollAD_Fit_climb = np.array([min(rollAD[iwp].ravel()), max(rollAD[iwp].ravel())])
    roll_Fit_climb = fitc.intercept + fitc.slope * rollAD_Fit_climb

    #
    # roll plot
    #

    if generate_plots:
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
        fit_line = (
            f"Best fit implies <b>C_ROLL_DIVE={c_roll_dive_imp:.0f}ad C_ROLL_CLIMB={c_roll_climb_imp:.0f}ad</b><br>"
            f"  Current values C_ROLL_DIVE={c_roll_dive:.0f}ad C_ROLL_CLIMB={c_roll_climb:.0f}ad"
        )

        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"roll control (counts)<br>{fit_line}",
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
    if generate_plots:
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
            if centered is False and abs(roll_control[i]) < 5:
                centered = True
                centered_start_t = sg_time[i]
                centered_start_head = vehicle_head_degrees_v[i]
                centered_start_head = vehicle_head_degrees_v[i]
                centered_pitch = vehicle_pitch_degrees_v[i]
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
        ircd = np.where(pitch_control < 0)
        ircc = np.where(pitch_control > 0)

        fitd = scipy.stats.linregress(rollAD[ircd].ravel(), turnRate[ircd].ravel())
        c_roll_dive_imp_all = -fitd.intercept / fitd.slope

        fitc = scipy.stats.linregress(rollAD[ircc].ravel(), turnRate[ircc].ravel())
        c_roll_climb_imp_all = -fitc.intercept / fitc.slope

        rollAD_Fit_all = np.array([max([0, min(rollAD)]), min([max(rollAD), 4096])])
        roll_Fit_climb_all = fitc.intercept + fitc.slope * rollAD_Fit_all
        roll_Fit_dive_all = fitd.intercept + fitd.slope * rollAD_Fit_all

        #
        # roll rate plot
        #
        roll_rate_template = "AvgRollAD %{x:.0f}<br>AvgRate %{y:.2f} deg/s<br>Time %{customdata[0]:.2f} min<br>PitchObs %{customdata[1]:.2f} deg<extra></extra>"

        fig = plotly.graph_objects.Figure()
        fig.add_trace(
            {
                "x": rollAD[ircd],
                "y": turnRate[ircd],
                "name": "Roll control/turn rate dive",
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
                "x": rollAD[ircc],
                "y": turnRate[ircc],
                "name": "Roll control/turn rate climb",
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
                "x": rollAD_Fit_all,
                "y": roll_Fit_dive_all,
                "name": "linfit C_ROLL_DIVE all",
                "mode": "lines",
                "line": {"dash": "longdash", "color": "DarkBlue"},
                "hovertemplate": f"Fit all C_ROLL_DIVE={c_roll_dive_imp_all:.0f}<extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": rollAD_Fit_all,
                "y": roll_Fit_climb_all,
                "name": "linfit C_ROLL_CLIMB all",
                "mode": "lines",
                "line": {"dash": "longdash", "color": "Red"},
                "hovertemplate": f"Fit all C_ROLL_CLIMB={c_roll_climb_imp_all:.0f}<extra></extra>",
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
                "name": "Roll control/turn rate dive (centered)",
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
                "name": "Roll control/turn rate climb (centered)",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "circle-open",
                    "color": "Red",
                },
                "hovertemplate": roll_rate_template,
            }
        )
        if len(roll_Fit_dive):
            fig.add_trace(
                {
                    "x": rollAD_Fit,
                    "y": roll_Fit_dive,
                    "name": "linfit C_ROLL_DIVE (centered)",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "DarkBlue"},
                    "hovertemplate": f"centered Fit C_ROLL_DIVE={c_roll_dive_imp:.0f}<extra></extra>",
                }
            )
        if len(roll_Fit_climb):
            fig.add_trace(
                {
                    "x": rollAD_Fit,
                    "y": roll_Fit_climb,
                    "name": "linfit C_ROLL_CLIMB (centered)",
                    "mode": "lines",
                    "line": {"dash": "solid", "color": "Red"},
                    "hovertemplate": f"centered Fit C_ROLL_CLIMB={c_roll_climb_imp:.0f}<extra></extra>",
                }
            )


        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>Roll control vs turn rate"
        fit_line = (
            f"     All fit implies <b>C_ROLL_DIVE={c_roll_dive_imp_all:.0f}ad C_ROLL_CLIMB={c_roll_climb_imp_all:.0f}ad</b><br>"
            f"      Current values C_ROLL_DIVE={c_roll_dive:.0f}ad C_ROLL_CLIMB={c_roll_climb:.0f}ad<br>"
            f"Centered fit implies C_ROLL_DIVE={c_roll_dive_imp:.0f}ad C_ROLL_CLIMB={c_roll_climb_imp:.0f}ad"
        )
        fig.update_layout(
            {
                "xaxis": {
                    "title": {
                        "text": f"roll control (counts)<br>{fit_line}",
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
    # log_info("Leaving dive_pitch_roll")
    return (figs_list, file_list)
