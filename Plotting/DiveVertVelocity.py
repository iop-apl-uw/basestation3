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

""" Plots dive vertical velocty and estimates C_VBD
"""
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
import HydroModel
import MakeDiveProfiles
import PlotUtils
import PlotUtilsPlotly
import Utils

from BaseLog import log_warning, log_error, log_info, log_debug
from Plotting import plotdivesingle

import pdb

#
# Utilities
#
def compute_smoothed_w(elapsed_time, dzdt, window=5):
    """Computes a smoothed w, using a rolling average
    Input:
        elapsed_time - cumulative time
        sample_depth - vehicle depth (corrected for latitude), in meters
        window - window length, in seconds

    Output:
        smoothed vehicle vertical velocity in m/s

    """
    w_smoothed_v = np.zeros(len(elapsed_time))

    # dt = np.zeros(len(elapsed_time))
    # dt[1:] = elapsed_time[1:] - elapsed_time[:-1]

    # dd = np.zeros(len(elapsed_time))
    # dd[1:] = sample_depth[1:] - sample_depth[:-1]

    # dzdt = np.zeros(len(elapsed_time))

    # dzdt[1:] = np.diff(sample_depth) / np.diff(elapsed_time)

    for ii in range(len(w_smoothed_v)):
        w_smoothed_v[ii] = np.nanmean(
            dzdt[
                np.logical_and(
                    elapsed_time <= elapsed_time[ii],
                    elapsed_time >= elapsed_time[ii] - window,
                )
            ]
        )
    return w_smoothed_v


def compute_w_obs(elapsed_time, sample_depth):
    """Computes w observed in a way similar to the glider
    Input:
        elapsed_time - cumulative time
        sample_depth - vehicle depth (corrected for latitude), in meters

    need the points on the timeline when the wObs is reset

    Output:
        w_obs_v - vehicle vertical velocity in m/s

    """

    w_obs_v = np.zeros(len(elapsed_time))

    dt = np.zeros(len(elapsed_time))
    dt[1:] = elapsed_time[1:] - elapsed_time[:-1]

    dd = np.zeros(len(elapsed_time))
    dd[1:] = sample_depth[1:] - sample_depth[:-1]
    # dt = np.diff(elapsed_time)
    # dd = np.diff(sample_depth)

    for ii in range(len(elapsed_time)):
        sumxy = sumx2 = 0.0
        m = 0
        # Here is where you limit the scan back based on the vehicle
        # flight transitions (DIVE, LOITER, CLIMB, COAST_TO_SURFACE
        for jj in range(30):
            if (ii - jj) < 0:
                break
            sumx2 += dt[ii - jj] * dt[ii - jj]
            sumxy += dt[ii - jj] * dd[ii - jj]
            m += 1
            if m >= 5 and (
                (sample_depth[ii - jj] > sample_depth[ii] + 3)
                or (sample_depth[ii - jj] < sample_depth[ii] - 3)
            ):
                break

        if sumx2 != 0.0:
            w_obs_v[ii] = -sumxy / sumx2

    return w_obs_v


def run_hydro(dv, buoy, vehicle_pitch_degrees_v, calib_consts):
    """
    Input:
        dv - dive number
        buoyancy_v - n_pts vector (grams, positive is upward)
        vehicle_pitch_degrees_v - observed vehicle pitch (degrees (! not radians), positive nose up)
        calib_consts - dictonary
                        hd_a, hd_b, hd_c - hydrodynamic parameters for lift, drag, and induced drag
                        hd_s - how drag scales by shape
                        rho - density of deep water (maximum density encountered)
                        glider_length - the length of the vehicle

    Output:
        vert_speed_hdm - vertical speed in cm/s
        stalled_i_v - locations where stalled
    """

    (
        hm_converged,
        hdm_speed_unsteady_cm_s_v,
        hdm_glide_angle_unsteady_rad_v,
        stalled_i_v,
    ) = HydroModel.hydro_model(buoy, vehicle_pitch_degrees_v, calib_consts)

    hdm_speed_unsteady_cm_s_v[stalled_i_v] = np.nan
    hdm_glide_angle_unsteady_rad_v[stalled_i_v] = np.nan

    hdm_speed_steady_cm_s_v = np.ma.array(
        hdm_speed_unsteady_cm_s_v, mask=np.isnan(hdm_speed_unsteady_cm_s_v)
    )
    hdm_glide_angle_steady_rad_v = np.ma.array(
        hdm_glide_angle_unsteady_rad_v, mask=np.isnan(hdm_glide_angle_unsteady_rad_v)
    )

    vert_speed_hdm = hdm_speed_steady_cm_s_v * np.sin(hdm_glide_angle_steady_rad_v)
    return (vert_speed_hdm, stalled_i_v, hm_converged)


# TODO typing.List(plotly.fig)
@plotdivesingle
def plot_vert_vel(
    base_opts: BaseOpts.BaseOptions, dive_nc_file: scipy.io._netcdf.netcdf_file
) -> tuple[list, list]:
    """Plots various measures of vetical velocity and estimates volmax and C_VBD"""
    # There is a significant difference in what MDP is creating for vertical velocity and what is done below.
    # Some traced back to a difference in calculated volume of the vehicle.  Results are about 30-50 cc difference in
    # buoyancy (sg124 NISKEN dives 124 and 160) even when both models are feed (far as I can tell) the same input.
    # This divergence needs to be sorted out.

    # Several things to add here:
    # 1) a set of diagnostics to alert the pilot when there are discrepancies in inputs (ABC, vbd_min/vbd_max, rho and mass)
    # 2) a new plot that just compares 0) the original ctr_first_diff dz/dt, 1) the smoothed dz/dt, 2) running the hydro_model in the old way and
    # 3) output in the basestations idea of vertical velocity.  Should also display mean differences between the measurements

    # Beyond that, there are three inputs that could be used to display the traditional plot and the bias alignment - sg_calib_constants,
    # OVERRIDES in calib constants and the current values in the logfile.  Need to decide what this plot actually is

    # np.set_printoptions(threshold="nan")

    if "vert_speed" not in dive_nc_file.variables:
        log_error("Not HDM output in plot - skipping")
        return ([], [])

    f_analysis = True
    f_use_glider_abc = False

    # Preliminaries
    try:
        start_time = dive_nc_file.start_time
        # glider_id = dive_nc_file.glider
        # mission_name = (
        #    dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        # )
        # dive_)number = dive_nc_file.dive_number
        # start_time_string = dive_nc_file.time_coverage_start

        mhead = (
            dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")
        )

        log_HD_A = dive_nc_file.variables["log_HD_A"].getValue()
        log_HD_B = dive_nc_file.variables["log_HD_B"].getValue()
        log_HD_C = dive_nc_file.variables["log_HD_C"].getValue()

        c_vbd = dive_nc_file.variables["log_C_VBD"].getValue()

        vbd_min = dive_nc_file.variables["log_VBD_MIN"].getValue()
        vbd_max = dive_nc_file.variables["log_VBD_MAX"].getValue()
        vbd_cnv = dive_nc_file.variables["log_VBD_CNV"].getValue()
        vbd_cnts_per_cc = 1.0 / vbd_cnv

        # Gilder based variables, normalized to MKS units
        log_RHO = dive_nc_file.variables["log_RHO"].getValue() * 1000.0
        log_MASS = dive_nc_file.variables["log_MASS"].getValue() / 1000.0

        # SG eng time base
        sg_time = dive_nc_file.variables["time"][:]
        depth = dive_nc_file.variables["depth"][:]
        vehicle_pitch_degrees_v = dive_nc_file.variables["eng_pitchAng"][:]
        sg_np = dive_nc_file.dimensions["sg_data_point"]
        vbd = dive_nc_file.variables["eng_vbdCC"][:]  # - vbdbias
        # log_info("vbd")
        # print vbd

        # CTD time base
        ctd_time = dive_nc_file.variables["ctd_time"][:]
        ctd_depth = dive_nc_file.variables["ctd_depth"][:]
        vert_speed_hdm_ctd = dive_nc_file.variables["vert_speed"][:]
        buoy_ctd = dive_nc_file.variables["buoyancy"][:]
        density_ctd = dive_nc_file.variables["density"][:]
        inds = np.nonzero(
            np.logical_and.reduce(
                (
                    np.isfinite(vert_speed_hdm_ctd),
                    np.isfinite(buoy_ctd),
                    np.isfinite(density_ctd),
                )
            )
        )[0]
        ctd_time = ctd_time[inds]
        ctd_depth = ctd_depth[inds]
        vert_speed_hdm_ctd = vert_speed_hdm_ctd[inds]
        buoy_ctd = buoy_ctd[inds]
        density_ctd = density_ctd[inds]
    except:
        log_error(
            "Could not fetch needed variables - skipping vertical velocity plot", "exc"
        )
        return ([], [])

    w_desired = np.fabs(float(mhead[2]))

    # We do this interpolation to recover the original hydro model output - done on sg_data_points basis - so
    # as to not clutter the plot with odd interpolation artifacts and to provide the pilot with a picture that
    # matches what is happening on the truck.
    f = scipy.interpolate.interp1d(
        ctd_time,
        vert_speed_hdm_ctd,
        kind="nearest",
        bounds_error=False,
        fill_value="extrapolate",
    )
    vert_speed_hdm = f(sg_time)

    f = scipy.interpolate.interp1d(
        ctd_time,
        density_ctd,
        kind="nearest",
        bounds_error=False,
        fill_value="extrapolate",
    )
    density = f(sg_time)

    # log_info("density")
    # print(density)

    vert_speed_press = Utils.ctr_1st_diff(-depth * 100, sg_time - start_time)

    obs_w = compute_w_obs(sg_time, depth)
    smooth_window = 10  # In seconds

    smoothed_w = compute_smoothed_w(
        sg_time,
        Utils.ctr_1st_diff(-depth, sg_time - start_time),
        window=smooth_window,
    )

    # TODO - Convert this display to use the smoothed output and have the crt_1st_diff displayed on a vertical velocity
    # comparision plot
    # vert_speed_press = obs_w

    bias_vert_speed_hdm = None

    if f_analysis:
        # Run the hydro model
        obs_time = np.zeros(len(sg_time))
        obs_time[1:] = sg_time[1:] - sg_time[:-1]
        # print(obs_time)

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

        # Extract the calib constants, then fill in any missing ones with defaults
        calib_consts = Utils.extract_calib_consts(dive_nc_file)
        MakeDiveProfiles.sg_config_constants(calib_consts)

        log_info(
            "Basestation: hd_a:%f hd_b:%f hd_c:%f mass:%.3f rho:%.1f"
            % (
                calib_consts["hd_a"],
                calib_consts["hd_b"],
                calib_consts["hd_c"],
                calib_consts["mass"],
                calib_consts["rho0"],
            )
        )
        log_info(
            "LogFile: hd_a:%f hd_b:%f hd_c:%f mass:%.3f rho:%.1f"
            % (log_HD_A, log_HD_B, log_HD_C, log_MASS, log_RHO)
        )

        # Because FM is now assumes 1027.5 as rho0, we take the gliders idea of
        # rho.  Long term, FM needs to be fixed
        rho0 = log_RHO

        if f_use_glider_abc:
            calib_consts["hd_a"] = log_HD_A
            calib_consts["hd_b"] = log_HD_B
            calib_consts["hd_c"] = log_HD_C
            calib_consts["rho0"] = rho0
            calib_consts["mass"] = log_MASS
            vol0 = log_MASS / rho0 * 1e6
            mass = log_MASS
            # volmax = vol0 - (c_vbd - vbd_min)/calib_consts['vbd_cnts_per_cc']
        else:
            calib_consts["rho0"] = rho0
            vol0 = calib_consts["mass"] / rho0 * 1e6
            mass = calib_consts["mass"]

        log_info(
            "Using: hd_a:%f hd_b:%f hd_c:%f mass:%.3f rho:%.1f"
            % (
                calib_consts["hd_a"],
                calib_consts["hd_b"],
                calib_consts["hd_c"],
                calib_consts["mass"],
                calib_consts["rho0"],
            )
        )

        # Find the VBD bias range where the hydro model converges and returns a reasonable
        # percentage of non-stalled poings
        log_info("VBD bias search")
        biases_dict = {}
        for bias in np.arange(-450, 500, 50):
            vol = vol0 + vbd - bias
            bias_buoy = 1000.0 * (-mass + density * vol * 1.0e-6)
            bias_vert_speed_hdm, stalled_i, hm_converged = run_hydro(
                dive_nc_file.dive_number,
                bias_buoy,
                vehicle_pitch_degrees_v,
                calib_consts,
            )
            log_info(
                f"Bias:{bias} cc, Stalled Ration:{float(len(stalled_i)) / float(len(bias_vert_speed_hdm)):.03f}, converged:{hm_converged}"
            )
            # TODO - check for the stalls being very asymetric?
            # Break the dive in two and check the failures on one profile versis the other?

            # 20% stalled is a bit agressive for shallow (45m) dives, but it helps filter out solutions
            # for asymetric dive profiles where the down or up cast is completely eliminated due to stalling
            # in the larger bias values
            biases_dict[bias] = (
                float(len(stalled_i)) / float(len(bias_vert_speed_hdm)),
                hm_converged,
            )

        biases = [
            x for x in biases_dict if biases_dict[x][0] < 0.2 and biases_dict[x][1]
        ]
        min_val = 1.0
        min_key = None
        if not biases:
            log_warning(
                "No bias met the criteria - selecting the least worst bias based on stalls"
            )
            for k, v in biases_dict.items():
                if v[0] < min_val:
                    min_key = k
                    min_val = v[0]
            biases = [min_val]

        log_info(f"Starting biases {biases}")

        bias_w_diff = np.zeros(21)
        bias_cc = np.zeros(21)
        bias_cc[0] = min(biases)
        bias_cc[1] = max(biases)
        bias_cc[2] = 0
        low = 0
        high = 1

        log_info(f"Search from {bias_cc[0]} cc to {bias_cc[1]} cc")

        vol_range = vol0 + vbd
        log_info(
            f"vol range min:{np.nanmin(vol_range):.2f}, max:{np.nanmax(vol_range):.2f}, mean:{np.nanmean(vol_range):.2f}"
        )

        for ii in range(20):
            # log_info(f"bias {bias_cc[ii]:f})")
            vol = vol0 + vbd - bias_cc[ii]
            # print(vol)
            bias_buoy = 1000.0 * (-mass + density * vol * 1.0e-6)
            # print (bias_buoy)
            bias_vert_speed_hdm, stalled_i, hm_converged = run_hydro(
                dive_nc_file.dive_number,
                bias_buoy,
                vehicle_pitch_degrees_v,
                calib_consts,
            )
            if not hm_converged:
                log_warning(
                    f"Unable to converge during hydro-model calculations (Dive:{dive_nc_file.dive_number}, Iteration:{ii})"
                )

            # log_info(f"Iteration {ii}, stalled_pts:{len(stalled_i)}")

            tmp = vert_speed_press.copy()
            tmp[stalled_i] = np.nan
            vert_speed_press_ma = np.ma.array(tmp, mask=np.isnan(tmp))

            # Weight by time between observations
            bias_w_diff[ii] = np.ma.average(
                vert_speed_press_ma - bias_vert_speed_hdm, weights=obs_time
            )
            if ii >= 2:
                if bias_w_diff[ii] * bias_w_diff[low] < 0:
                    bias_cc[ii + 1] = 0.5 * (bias_cc[ii] + bias_cc[low])
                    high = ii
                else:
                    bias_cc[ii + 1] = 0.5 * (bias_cc[ii] + bias_cc[high])
                    low = ii
                if np.fabs(bias_cc[ii + 1] - bias_cc[ii]) < 0.5:
                    break

        iterations = ii + 1
        for ii in range(iterations):
            log_info(f"Bias {ii} CC:{bias_cc[ii]:.1f} vert_v:{bias_w_diff[ii]:.2f}")

        del ii
        min_bias = bias_cc[iterations]

    # Glide Slope output
    (
        gsm_converged,
        gsm_total_speed_cm_s_v,
        gsm_theta_rad_v,
        gsm_stalled_i_v,
    ) = HydroModel.glide_slope(
        vert_speed_press,
        np.radians(
            vehicle_pitch_degrees_v,
        ),
        calib_consts,
    )

    vert_speed_gsm = gsm_total_speed_cm_s_v * np.sin(gsm_theta_rad_v)

    # TODO - re-impliment flightvec and use that for an alternate approach (compare with hydro)

    # def new_cvbd(volmax, mass, vbd_min_cnts, vbd_cnts_per_cc=-4.0767, rho0=1027.5):
    #     return -1.0 * ((volmax - mass*1000./(rho0/1000.)) * vbd_cnts_per_cc - vbd_min_cnts)

    # def volmax(mass, vbd_min_cnts, c_vbd, rho0=1027.5, vbd_cnts_per_cc=-4.0767):
    #     return mass*1000./(rho0/1000.) + (vbd_min_cnts - c_vbd)/vbd_cnts_per_cc

    implied_volmax = (
        vol0 - ((c_vbd + min_bias * vbd_cnts_per_cc) - vbd_min) / vbd_cnts_per_cc
    )
    implied_cvbd = c_vbd + min_bias * vbd_cnts_per_cc

    implied_max_maxbuoy = -(implied_cvbd - vbd_max) / vbd_cnts_per_cc * (rho0 / 1000)
    implied_max_smcc = -(implied_cvbd - vbd_min) / vbd_cnts_per_cc

    log_info(
        f"implied_cvbd {implied_cvbd:.0f}, implied_volmax {implied_volmax:.1f}, implied_max_smcc {implied_max_smcc:.1f}, implied_max_maxbuoy {implied_max_maxbuoy:.1f}"
    )

    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_C_VBD", implied_cvbd
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_volmax", implied_volmax
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_max_MAX_BUOY", implied_max_maxbuoy
    )
    BaseDB.addValToDB(
        base_opts, dive_nc_file.dive_number, "implied_max_SM_CC", implied_max_smcc
    )
    try:
        BaseDB.addSlopeValToDB(
            base_opts, dive_nc_file.dive_number, ["implied_volmax", "implied_C_VBD"], None
        )
    except:
        log_error("Failed to add values to database", "exc")

    # Find the deepest sample
    max_depth_sample_index = np.argmax(depth)

    depth_dive = depth[0:max_depth_sample_index]
    depth_climb = depth[max_depth_sample_index:]

    # dz_dt = Utils.ctr_1st_diff(-depth * 100, depth_time - start_time)
    diff_w = abs(vert_speed_press - vert_speed_hdm)
    upwelling_descent = diff_w[0:max_depth_sample_index]
    upwelling_ascent = diff_w[max_depth_sample_index:]

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": [-w_desired, -w_desired],
            "y": [np.nanmin(depth), np.nanmax(depth)],
            "name": "Vert Speed Desired (dive)",
            "mode": "lines",
            "line": {"dash": "dash", "color": "Blue"},
            "hovertemplate": "Vert Speed Desired (dive)",
        }
    )
    fig.add_trace(
        {
            "x": [w_desired, w_desired],
            "y": [np.nanmin(depth), np.nanmax(depth)],
            "name": "Vert Speed Desired (climb)",
            "mode": "lines",
            "line": {"dash": "dash", "color": "Blue"},
            "hovertemplate": "Vert Speed Desired (climb)",
        }
    )
    fig.add_trace(
        {
            "x": vert_speed_hdm,
            "y": depth,
            "name": "Vert Speed Buoy/Pitch (HDM)",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Cyan"},
            "hovertemplate": "Buoy/Pitch<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": vert_speed_gsm,
            "y": depth,
            "name": "Vert Speed GSM",
            "mode": "lines",
            "line": {"dash": "solid", "color": "LightBlue"},
            "hovertemplate": "GSM<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": vert_speed_press,
            "y": depth,
            "name": "Vert Speed dz/dt",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Blue"},
            "hovertemplate": "dz/dt<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": obs_w * 100.0,
            "y": depth,
            "name": "Vert Speed smoothed dz/dt (glider model)",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Black"},
            "hovertemplate": "Glider smoothed dz/dt<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": smoothed_w * 100.0,
            "y": depth,
            "name": f"Vert Speed smoothed dz/dt ({smooth_window} sec window)",
            "mode": "lines",
            "line": {"dash": "solid", "color": "Violet"},
            "hovertemplate": "Smoothed dz/dt<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": upwelling_descent,
            "y": depth,
            "name": "Upwelling Descent",
            "mode": "lines",
            "line": {"dash": "dash", "color": "Red"},
            "hovertemplate": "Upwelling Descent<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": upwelling_ascent,
            "y": depth,
            "name": "Upwelling Ascent",
            "mode": "lines",
            "line": {"dash": "dash", "color": "Magenta"},
            "hovertemplate": "Upwelling Ascent<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
        }
    )
    if bias_vert_speed_hdm is not None:
        fig.add_trace(
            {
                "x": bias_vert_speed_hdm,
                "y": depth,
                "name": "Vert Speed Buoy/Pitch (HDM)<br>Biased by %.1f cc (%d iterations)"
                % (min_bias, iterations),
                "mode": "lines",
                "line": {"dash": "solid", "color": "Green"},
                "hovertemplate": "Buoy/Pitch Biased<br>%{x:.2f} cm/sec<br>%{y:.2f} meters<br><extra></extra>",
            }
        )
    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    title_text = f"{mission_dive_str}<br>Vertical Velocity vs Depth"
    fit_line = f"Best Fit VBD bias={min_bias:.0f}cc Implies C_VBD={implied_cvbd:.0f}ad volmax={implied_volmax:.0f}cc max SM_CC={implied_max_smcc:.0f}cc max MAX_BUOY={implied_max_maxbuoy:.0f}cc"

    fig.update_layout(
        {
            "xaxis": {
                "title": f"Vertical Velocity (cm/sec)<br>{fit_line}",
                "showgrid": True,
                # "side": "top"
            },
            "yaxis": {
                "title": "Depth (m)",
                "showgrid": True,
                "autorange": "reversed",
                "range": [
                    max(
                        depth_dive.max() if len(depth_dive) > 0 else 0,
                        depth_climb.max() if len(depth_climb) > 0 else 0,
                    ),
                    0,
                ],
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
    # Abandon in favor of adding to the y-axis title.
    # Layout engine does a better job with it.
    #
    # l_annotations = [
    #     {
    #         "text": fit_line,
    #         "showarrow": False,
    #         "xref": "paper",
    #         "yref": "paper",
    #         "align": "left",
    #         "xanchor": "left",
    #         "valign": "top",
    #         "x": 0,
    #         "y": -0.08,
    #         # "x": 1.2,
    #         # "y": 0.0,
    #     }
    # ]
    # fig.update_layout({"annotations": tuple(l_annotations)})

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_vert_vel" % (dive_nc_file.dive_number,),
            fig,
        ),
    )
