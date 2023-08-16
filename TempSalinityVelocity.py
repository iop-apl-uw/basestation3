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

"""Routines for computing corrected temperature, salinity, glider speed and angle
"""

import math
import os
import time

import numpy as np
from scipy.integrate import cumtrapz
import scipy.signal  # for convolve
import scipy.io  # for loadmat
from scipy.interpolate import RectBivariateSpline

import seawater
import gsw

import QC
import TraceArray
import Utils

from pchip import pchip
from HydroModel import hydro_model
from BaseLog import log_debug, log_error, log_info, log_warning

c3515 = (
    4.2914  # Conductivity at S=35, T=15, P=0, mS/10cm, where conductivity ratio is 1
)
kg2g = 1000.0
cm2m = 0.01
m2cm = 100.0

kappa = 1.45e-7  # thermal diffusivity of water [m^2/s] (was 1.4e-7)
nominal_ocean_density = 1026  # PARAMETER [kg/m^3] -- why not rho0?
# Thermal conductivity is diffusivity*density*heat capacity
specific_heat_capacity_water = 4185.5  # thermal heat capacity of water in J/kg*degC)
thermal_cond_sw = (
    kappa * nominal_ocean_density * specific_heat_capacity_water
)  # CONSTANT thermal conductivity of seawater [W/degC/m] for nominal density (0.57456)
thermal_cond_glass = 0.96  # CONSTANT thermal conductivity of glass [W/degC/m]
# UNUSED in this version?
thermal_cond_epoxy = (
    0.18  # CONSTANT thermal conductivity of jacket on pumped SBE4 CTs [W/(degC m)]
)
thermal_cond_polyurethane = (
    0.2394  # CONSTANT thermal conductivity of jacket on unpumped SBE41 CTs [W/(degC m)]
)


# Support for hollow cylinder multi-mode correction
# Cached mode state; use dictionary to avoid direct variable assignment which makes the variable a local...ah, for Py3.0's nonlocal declaration
#
# These files contain the cached results of computing the individual radial heat
# transfer modes through the glass/epoxy jacket (see discussion around eqns 10,
# 14, 16, and 17 in CCE's paper).  The solutions involve solving Bessel
# functions of the first and second kind and reflect the structural and material
# properties of the glass/epoxy for the SG gun style CT.  These are interpolated
# as needed for the different flow regimes in the CT tube according to its
# length and the vehicle speed below.
mode_cache = {}


def load_thermal_inertia_modes(base_opts, num_modes=5, force=False, cell_type="SGgun"):
    """Load thermal-inertia mode tables
    base_opts -- options from which we get path to mode files
    num_modes -- How many modes to use; should be an odd number
                 - 1 is somewhat equivalent to previous version; though better, not best
                 - 3 is a little better than 1 and quicker than 5
                 - 5 is what CCE prefers
                 - 0 disables modal correction and uses previous version
    force     -- Force reloading of modal data
    cell_type -- The type of CT instrument
    """
    try:
        modes = mode_cache["modes"]
        if modes == num_modes and not force:
            return  # already loaded correctly
    except KeyError:
        pass  # try to load

    # Reset globals before reloading
    mode_cache.clear()
    mode_cache["modes"] = num_modes  # Number of modes available
    try:  # protect against file reading failure
        if num_modes > 0:
            # mode support

            base_dir = os.path.join(base_opts.basestation_directory, "tsv_mat")
            # Explicitly bind filename for any error report below
            filename = os.path.join(base_dir, "Bim%s" % cell_type)
            data_d = scipy.io.loadmat(filename)
            Bim = data_d["Bim"]
            filename = os.path.join(base_dir, "Bem%s" % cell_type)
            data_d = scipy.io.loadmat(filename)
            Bem = data_d["Bem"]
            # Biot number bounds of the mode tables
            mode_cache["Bim_max"] = np.max(Bim)
            mode_cache["Bem_max"] = np.max(Bem)
            mode_cache["Bim_min"] = np.min(Bim)
            mode_cache["Bem_min"] = np.min(Bem)
            Bi_v = Bim[0, :]  # array of values from meshgrid results
            Be_v = Bem[:, 0]  # array of values from meshgrid results
            # A tuple of tau and Ai interpolation function tuples
            mode_data = ()
            for mode in range(num_modes):
                data_d = {}
                filename = os.path.join(base_dir, "Tau%d%s" % (mode + 1, cell_type))
                scipy.io.loadmat(filename, data_d)
                filename = os.path.join(base_dir, "Ai%d%s" % (mode + 1, cell_type))
                scipy.io.loadmat(filename, data_d)
                # create interp2 'linear' spline closures.
                mode_data = mode_data + (
                    (
                        RectBivariateSpline(
                            Bi_v, Be_v, np.transpose(data_d["TAU"]), kx=1, ky=1
                        ),
                        RectBivariateSpline(
                            Bi_v, Be_v, np.transpose(data_d["AI"]), kx=1, ky=1
                        ),
                    ),
                )
            mode_cache["mode_data"] = mode_data
        else:  # modes = 0 # original code if extant
            pass  # raise RuntimeError() eventually
    except Exception as exc:
        mode_cache.clear()
        raise RuntimeError(
            True, "Unable to load thermal-inertia mode parameter data (%s)!" % filename
        ) from exc

    return  # end of function


# From MATLAB, not found in numpy
def triang(L):
    """Return an L-point triangular window in a vector w.
    See matlab doc on triang(L), adjusted for 0-based indices
    http://www.mathworks.com/access/helpdesk/help/toolbox/signal/triang.html

    Input:
      L - size of the vector

    Returns:
      w_v - triangular window

    Raises:
      Any exceptions raised are considered critical errors and not expected
    """
    L = int(L)  # ensure integer
    w_v = np.zeros(L)
    L_1 = L + 1
    odd = L % 2 == 1  # if L is odd, there are an even number of points in matlab [1..L]
    midpoint = L_1 // 2
    for n in range(1, midpoint + 1):
        w_v[n - 1] = 2.0 * n / L_1 if odd else 2.0 * n / L
    for n in range(midpoint + 1 if odd else L / 2 + 1 + 1, L_1):
        w_v[n - 1] = 2.0 * (L - n + 1) / L_1 if odd else 2.0 * (L - n + 1) / L
    return w_v


def trifilt(x_v, n):
    """xf_v is x_v filtered with a triangular filter of half-width n
    xf_v has the same length as x_v so that features in xf_v and x_v
    line up.  Endpoints are corrected by filter area so that
    effective filter area is half at the endpoints and progressively
    increases to unity 2*n points from the ends of the series x_v

    Input:
      x_v - input vector
      n - half-width size desired

    Returns:
      xf_v - filtered version of x_v

    Raises:
      Any exceptions raised are considered critical errors and not expected

    """
    n = int(n)  # ensure integer
    m = len(x_v)
    g_v = triang(2 * n - 1) / n
    y_v = scipy.signal.convolve(x_v, g_v)
    s = len(y_v)
    # this indices generate an off-by-one too few bug len(xf_v) == m - 1 rather than m
    begin_i = (s - m) // 2 + 1 - 1  # added -1 to adjust the array size
    end_i = (s - m) // 2 + m
    xf_v = y_v[begin_i:end_i]
    u_v = np.ones(m)
    v_v = scipy.signal.convolve(u_v, g_v)
    u_v = v_v[begin_i:end_i]
    xf_v = xf_v / u_v  # element-wise division
    return xf_v


def filter_unsteady(
    tau_i,
    r_elapsed_time_s_v,
    time_fine_s_v,
    r_dt,
    hdm_speed_steady_cm_s_v,
    hdm_glide_angle_steady_rad_v,
):
    if tau_i:
        # We deal with unsteady flight by smoothing accelerations assuming flight speed
        # is a 1st order inertial process with lag tau_i seconds
        # This models the effect of acceleration as a linear response to change in speed
        # Must do this on velocity COMPONENTS since it is a linear process
        # speed in polar coordinates is sqrt(w^2 + h^2)

        tau_x = np.fix(max(tau_i, 1.0)) / r_dt  # protect trifilt; must be an integer
        hdm_horizontal_speed_steady_cm_s_v = hdm_speed_steady_cm_s_v * np.cos(
            hdm_glide_angle_steady_rad_v
        )
        hdm_w_steady_cm_s_v = hdm_speed_steady_cm_s_v * np.sin(
            hdm_glide_angle_steady_rad_v
        )

        hspd_stdy_fine_v = pchip(
            r_elapsed_time_s_v, hdm_horizontal_speed_steady_cm_s_v, time_fine_s_v
        )  # interp to 1 s
        hspd_stdy_fine_filt_v = trifilt(hspd_stdy_fine_v, tau_x)  # filter
        hspd_unstdy_v = pchip(
            time_fine_s_v, hspd_stdy_fine_filt_v, r_elapsed_time_s_v
        )  # decimate

        w_stdy_fine_v = pchip(
            r_elapsed_time_s_v, hdm_w_steady_cm_s_v, time_fine_s_v
        )  # interp to 1 s
        w_stdy_fine_filt_v = trifilt(w_stdy_fine_v, tau_x)  # filter
        w_unstdy_v = pchip(
            time_fine_s_v, w_stdy_fine_filt_v, r_elapsed_time_s_v
        )  # decimate
        # re-estimate speed and angle
        hdm_speed_unsteady_cm_s_v = np.sqrt(
            hspd_unstdy_v**2 + w_unstdy_v**2
        )  # [cm/s]
        hdm_glide_angle_unsteady_deg_v = np.degrees(
            np.arctan2(w_unstdy_v, hspd_unstdy_v)
        )  # deg
    else:
        hdm_speed_unsteady_cm_s_v = hdm_speed_steady_cm_s_v  # [cm/s]
        hdm_glide_angle_unsteady_deg_v = np.degrees(hdm_glide_angle_steady_rad_v)  # deg
    return (hdm_speed_unsteady_cm_s_v, hdm_glide_angle_unsteady_deg_v)


# pylint: disable=too-many-arguments disable=too-many-locals


# A note on the use of nonzero() as a replacement for matlab find()
# It all seems so promising, since it is fast and the results can be used for numpy array indexing. BUT....
# - it returns a tuple of array([...]) value so if you want to iterate you need nonzero(...)[0].tolist() for vectors
# - it sometimes returns () instead of (array([])) (this occurs if the array being tested is NOT numpy.array)
# - it doesn't handle boolean conditions against two or more arrays even over the same length
# So, even though it is slower we use filter(lambda ...) to get what we want
# ALTERNATIVE: use np.where with np.logical_and and np.logical_or to handle multiple conditions,
#  e,g, np.logical_and(np.where(x > 2), np.where(y < 5))
# empty index arrays no longer a problem?  But iteration still requires fancy footwork
def TSV_iterative(
    base_opts,
    elapsed_time_s_v,
    start_of_climb_i,
    # measurements, corrected
    temp_init_cor_v,
    temp_init_cor_qc_v,
    cond_init_cor_v,
    cond_init_cor_qc_v,
    salin_init_cor_v,
    salin_init_cor_qc_v,
    pressure_v,
    vehicle_pitch_degrees_v,
    # info about the glider and the instrument
    calib_consts,
    directives,
    volume_v,
    # how to make the calculations
    perform_thermal_inertia_correction,
    interpolate_extreme_tmc_points,
    use_averaged_speeds,
    # initial guess about flight
    gsm_speed_cm_s_v,
    gsm_glide_angle_deg_v,
    longitude,
    latitude,
):
    """Compute and return corrected salinity (and possibly temperature) and glider speed consistent with
    the buoyancy the corrected salinity implies.

    Input:
      elapsed_time_s_v - elapsed time of each sample [s]
      start_of_climb_i - start of climb (2nd apogee pump)
      temp_init_cor_v - initial corrected temperature
      temp_init_cor_qc_v - initial corrected temperature QC tags
      cond_init_cor_v - initial corrected conductivity
      cond_init_cor_qc_v - initial corrected conductivity QC tags
      salin_init_cor_v - initial corrected salinity
      salin_init_cor_qc_v - initial corrected salinity QC tags
      pressure_v - observed pressure corrected for latitude [psi]?
      vehicle_pitch_degrees_v - measured vehicle pitch [degrees]
      calib_consts - dictionary of glider calibation constants
      directives - instance of ProfileDirectives for this profile
      volume_v - volume [cc]
      perform_thermal_inertia_correction - whether to do this correction
      interpolate_extreme_tmc_points - whether to do this correction
      use_averaged_speeds - how to average speeds if iterative
      gsm_speed_cm_s_v - initial guess of total glider speed [cm/s] -- NOT observed w
      gsm_glide_angle_deg_v - initial guess of glide angle [deg] UNUSED HERE
    Returns:
      converged - boolean whether we converged
      temp_cor_v - possibly corrected temperature (via interpolation)
      temp_cor_qc_v - possibly updated temperature QC tags
      salin_cor_v - final corrected salinity
      salin_cor_qc_v - final corrected salinity QC tags
      final_density_v - seawater potential density
      final_density_insitu_v - seawater insitu density
      final_buoyancy_v - glider buoyancy
      final_speed_cm_s_v - total speed through the water
      final_glide_angle_rad_v - glider angle
      speed_qc_v - QC tags for final speeds

    Raises:
      Any exceptions raised are considered critical errors and not expected

    """

    sg_np = len(elapsed_time_s_v)
    full_i_v = list(range(sg_np))
    valid_i_v = np.array(full_i_v)

    # Setup return arrays with an initial guess
    temp_cor_v = np.array(temp_init_cor_v)
    temp_cor_qc_v = np.array(temp_init_cor_qc_v)

    salin_cor_v = np.array(salin_init_cor_v)
    salin_cor_qc_v = np.array(salin_init_cor_qc_v)

    final_density_v = np.nan * np.ones(sg_np)
    final_density_insitu_v = np.nan * np.ones(sg_np)
    final_buoyancy_v = np.nan * np.ones(sg_np)

    # A word about the various speeds in this routine
    # We return final_speed_cm_s_v, which is in full space and a copy of the last hdm_speed_unsteady_cm_s_v to valid_i_v we compute
    # Our initial guess serves as our first final_speed_cm_s_v and hdm_speed_unsteady_cm_s_v but this will be updated by HDM below
    # hdm_speed_cm_s_v is our iterative speed estimation in reduced space and is used for TMC and for controlling the loop

    # Initially we use GSM as a guess but it has issues.  To the positive, during flare and post-apogee it is likely to record
    # the actual accelerations experienced by the vehicle, while the HDM model does not.  Apparently the vehicle is moving from
    # a form-drag limited regime into a different drag regime at low speeds.  Since we tune b (the drag coefficient)
    # during steady flight (regress_vbd avoids flare, etc.) we don't have a model of b during these accelerations (and b might itself be changing).
    # Second, the GSM values, based on measured w (and pitch), are subject to changes in the pressure signal due to sensor noise or internal waves,
    # making it appear that the vehicle is accelerating and decelerating. In fact, the vehicle is actually in steady flight relative to
    # the surrounding water as it is being heaved up and down. The HDM model based on buoyancy (density of the water) avoids this effect.

    # We need a version of HDM that deals with non-steady flight in low-velocity regimes.
    # The reason this is critical is that quite frequently the top part of the water column is warmer than the subsurface and
    # the thermal-inertia eqns need to see both the temperature signal and the speed signal to model the correction properly.
    # Otherwise we initialize the state of the system incorrectly and it takes several tau foldings in eventually cooler water
    # to establish a proper correction.  Of course, all this requires actual, rapidly-resolved measurements in the upper part
    # of the water column and for the calling code not to drop those points.

    final_speed_cm_s_v = np.array(
        gsm_speed_cm_s_v
    )  # this is our current best guess about vehicle speed (from GSM)
    final_glide_angle_deg_v = np.array(
        gsm_glide_angle_deg_v
    )  # and final glider angle [deg]

    # Find bad salinities but don't mark them here
    # Let the caller do it.  It also papers over a bug:
    # If we reduce over any of these points we could then interpolate
    # across the bad points (in full space), replacing NaN and QC_BAD tags
    # inappropriately.  If the caller does it, it gets the last word.
    uncorrectable_i_v = QC.manual_qc(
        directives,
        "bad_salinity",
        "salin_QC_BAD",
        QC.QC_BAD,
        salin_cor_qc_v,
        "salinity",
    )
    uncorrectable_i_v = QC.bad_qc(salin_cor_qc_v)

    speed_qc_v, bad_speed_i_v = init_speed_qc(
        sg_np, salin_cor_qc_v, vehicle_pitch_degrees_v
    )
    uncorrectable_i_v = Utils.union(uncorrectable_i_v, bad_speed_i_v)

    salin_cor_v[uncorrectable_i_v] = np.NaN
    TraceArray.trace_array(
        "uncorrectable_i", np.array(uncorrectable_i_v) + 1
    )  # +1 for matlab
    salin_init_cor_qc_v = salin_cor_qc_v  # RESET!!  we want to restart from this state

    valid_i_v = Utils.setdiff(full_i_v, uncorrectable_i_v)
    salin_cor_v[uncorrectable_i_v] = np.NaN  # set once...
    # We will mark these as QC_BAD in caller
    final_speed_cm_s_v[uncorrectable_i_v] = np.NaN
    final_glide_angle_deg_v[uncorrectable_i_v] = np.NaN

    # initialize for reduction below
    # actually this is from our GSM guess so this has been done and all stalls are set to 0 but just to be sure...
    stalled_i_v = [
        i
        for i in range(sg_np)
        if (
            final_speed_cm_s_v[i] >= calib_consts["max_stall_speed"]
            or final_speed_cm_s_v[i] <= calib_consts["min_stall_speed"]
        )
    ]

    earliest_time_v = elapsed_time_s_v[0] * np.ones(sg_np)
    start_of_climb_time = elapsed_time_s_v[
        start_of_climb_i
    ]  # ensure it is a measurement elapsed time
    earliest_time_v[list(range(start_of_climb_i, sg_np))] = start_of_climb_time

    # When computing tau_1 we use vehicle_pitch_degrees_v as radians.  Do this once here
    vehicle_pitch_rad_v = np.radians(vehicle_pitch_degrees_v)

    TraceArray.trace_array("time", elapsed_time_s_v)
    TraceArray.trace_array("earliest_time", earliest_time_v)
    TraceArray.trace_array("temp_lag", temp_init_cor_v)
    TraceArray.trace_array("cond", cond_init_cor_v)
    TraceArray.trace_array("press", pressure_v)
    TraceArray.trace_array("pitch", vehicle_pitch_degrees_v)
    TraceArray.trace_array("salin_guess", salin_init_cor_v)
    TraceArray.trace_array("speed_guess", gsm_speed_cm_s_v)
    TraceArray.trace_array("glideangle_guess", gsm_glide_angle_deg_v)

    # Setup constants and control parameters here
    # We do this after setting up initial return variables in case we need to bail below

    # prepare for inter-solution comparisons
    modes = mode_cache["modes"]
    if modes:
        # Unpack these values
        # See plots in Figure 6.
        # Bi is the cell wall interior Biot number and min/max are its bounds for interpolation
        # Be is the exterioud jacket wall Biot number and min/max are its bounds for interpolation
        Bim_max = mode_cache["Bim_max"]
        Bem_max = mode_cache["Bem_max"]
        Bim_min = mode_cache["Bim_min"]
        Bem_min = mode_cache["Bem_min"]
        mode_data = mode_cache["mode_data"]
    else:
        log_debug("Thermal-inertia correction disabled.")
        perform_thermal_inertia_correction = 0  # False

    previous_max_residual_speed = (
        1000000.0  # [cm/s] start with an impossibly large value
    )
    spd_diff_threshold = 0.1  # PARAMETER speed difference convergence threshold [cm/s] between iterations
    itermax = 20  # PARAMETER number of times through the tsv iteration (if 40 might not converge)
    itermax = itermax + 1  # account for zero-based count
    converged = False  # Assume the worst
    interp_ts_i_v = []
    full_suspects_i_v = []
    try:
        mass = calib_consts["mass"]

        glider_interstitial_length = calib_consts["glider_interstitial_length"]
        if glider_interstitial_length > 0.0:
            glider_interstitial_volume = calib_consts["glider_interstitial_volume"]
            glider_r_en = calib_consts["glider_r_en"]

        glider_wake_entry_thickness = calib_consts["glider_wake_entry_thickness"]
        if glider_wake_entry_thickness > 0.0:
            glider_vol_wake = calib_consts["glider_vol_wake"]
            glider_r_fair = calib_consts["glider_r_fair"]

        sbect_unpumped = calib_consts["sbect_unpumped"]
        sb_ct_type = calib_consts["sg_ct_type"]
        if sb_ct_type != 4:  # Does not apply to the legato
            sbect_cell_length = calib_consts["sbect_cell_length"]
            sbect_x_w = calib_consts["sbect_x_w"]
            sbect_r_w = calib_consts["sbect_r_w"]
            sbect_r_n = calib_consts["sbect_r_n"]
            sbect_x_T = calib_consts["sbect_x_T"]
            sbect_z_T = calib_consts["sbect_z_T"]
            sbect_x_m = calib_consts["sbect_x_m"]
            sbect_r_m = calib_consts["sbect_r_m"]
            if not sbect_unpumped:
                sbect_gpctd_u_f = calib_consts["sbect_gpctd_u_f"]
                sbect_gpctd_tau_1 = calib_consts["sbect_gpctd_tau_1"]

            # Derived quantities
            sbect_b_m = (
                sbect_r_m - sbect_r_w
            ) / sbect_x_m  # slope of (conical) mouth opening
            # mouth is a truncated cone
            sbect_vol_mouth = (
                math.pi
                * sbect_x_m
                * (
                    sbect_r_w * sbect_r_w
                    + sbect_r_w * sbect_b_m * sbect_x_m
                    + sbect_b_m * sbect_b_m * sbect_x_m * sbect_x_m / 3
                )
            )  # mouth volume [m^3]
            # wide part of the tube
            sbect_vol_wide = (
                math.pi * sbect_r_w * sbect_r_w * sbect_x_w
            )  # volume of wide portion of cell entry section [m^3]
            sbect_vol_mouth_wide = sbect_vol_mouth + sbect_vol_wide
            sbect_area_narrow = (
                math.pi * sbect_r_n * sbect_r_n
            )  # area of narrow tube [m^2]
            sbect_vol_narrow = (
                sbect_area_narrow * sbect_cell_length
            )  # volume of sample section of cell [m^3]

            # sbect_tau_T = calib_consts["sbect_tau_T"]
            sbect_C_d0 = calib_consts["sbect_C_d0"]

            sbect_inlet_bl_factor = calib_consts["sbect_inlet_bl_factor"]
            sbect_Nu_0i = calib_consts["sbect_Nu_0i"]
            sbect_Nu_0e = calib_consts["sbect_Nu_0e"]

    except KeyError:
        log_error("A critical constant for TSV is missing", "exc")
        loop = itermax = 0  # skip the loop below and return non-converged

    # The drag coefficient scales as the cell mouth area increases as the ratio of the mouth areas
    # or the ratio of the squares of sbect_r_m.  Thus the new mounting has a radius of 0.0123m vs. 0.0081m
    # for the old SG mounting yields an expected scale factor of 2.3x.  However, CCE measured the actual
    # C_d0 for the new at 2.4 for a 2x.
    original_C_d0 = 1.2  # cell drag coefficient (measured) C_d0 = 1.2 in 23 Feb 2006 cell head vs flume speed regressions

    # Corrected attack angles to be with 0.5 and 10 degrees, which is where CCEs flume regressions are operative
    # NOTE: Given the length of the vehicle and the location of the CT sail the actual operative attack angles
    # that aren't affected by the wake of the glider body are smaller.  CCE estimates 6deg for SG and 3deg for DG.
    # Should we clamp harder?  Warn?  Worry?
    min_attack_angle = 0.5  # PARAMETER [deg]
    max_attack_angle = 10.0  # PARAMETER [deg]

    # Setup for iterative scheme...
    # we must iterate if we have an unpumped CTD and we are using a TMC other than the SBE scheme
    iterative_scheme = sbect_unpumped and perform_thermal_inertia_correction == 1
    reduce = True  # force this...since we are likely to have initial QC issues
    recompute_TS_interpolation = True  # force this as well
    r_extrapolated_i_v = []  # initialize
    max_temp_c_diff = 0  # assume all is well

    tau_i = 20  # PARAMETER estimated lag [s] of unsteady solution behind steady speed calculation (MUST BE > 1)

    # TODO put this entire loop in a try: except: block to catch numeric issues and continue gracefully
    for loop in range(itermax):
        log_debug("TSV Iteration %d" % loop)
        # The only annotations that count are on the last time through the loop

        # REDUCE code here
        if reduce:
            # in salinity, bad points occur are because of bad T or C (uncorrectable_i_v) and, in the case of unpumped CTD,
            # because of stalls and recoveries in the tube, which correspond to vehicle stalls.

            # in vehicle speed, which depends on salinity (for buoyancy), there are two kinds of problems:
            # unknown speeds, where salinity is bad for T and C, and stalled, where flight goes bad.
            # the former we mark as NaN, the later as 0

            # in any case we recompute the valid_i_v points where the salinity is not bad and solve the TMC against these
            # reduced variables, since the TMC code can't handle stalled tube speeds in the unpumped case.
            TraceArray.trace_comment("reduce %d" % loop)

            recompute_TS_interpolation = True  # force this
            reduce = False  # reset

            # reset the QC variable so we can mark QC_INTERPOLATE points afresh
            temp_cor_qc_v = np.array(temp_init_cor_qc_v)
            salin_cor_qc_v = np.array(salin_init_cor_qc_v)

            # compute the set of 'bad' points
            reduce_i_v = uncorrectable_i_v  # these don't change from loop to loop
            if sbect_unpumped:
                # stalls are no good for thermal inertia correction
                reduce_i_v = Utils.sort_i(
                    Utils.union(reduce_i_v, stalled_i_v)
                )  # these might...

            # The new set of valid points to compute TMC and speed over...
            valid_i_v = Utils.setdiff(full_i_v, reduce_i_v)
            valid_i_v = np.array(valid_i_v)
            TraceArray.trace_array("valid_i_%d" % loop, valid_i_v + 1)
            # match matlab

            # reduce the data set for the next round
            r_sg_np = len(valid_i_v)
            if r_sg_np < 3:
                # insufficient valid points to continue (labsea sep04 sg015 240)
                valid_i_v = full_i_v  # return our initial guesses...
                break  # can't converge

            r_elapsed_time_s_v = elapsed_time_s_v[valid_i_v]
            # Determine the scale for the fine time grid
            # for eng files this is to the nearest second
            # for scicon and gpctd this has to be finer...
            min_r_time_s = min(np.diff(r_elapsed_time_s_v))
            for r_dt in [1, 0.5, 0.25, 0.1]:
                if min_r_time_s > r_dt:
                    break
            time_fine_s_v = np.arange(
                int(r_elapsed_time_s_v[0]), int(r_elapsed_time_s_v[-1] + 1.0), r_dt
            )  # make r_dt second time grid; add 1 for python range

            # find new start of climb point in reduced space (DEAD?? since we don't use r_start_of_climb_i)
            r_start_of_climb_i = [
                i
                for i in range(r_sg_np)
                if r_elapsed_time_s_v[i] >= start_of_climb_time
            ]
            if len(r_start_of_climb_i):
                r_start_of_climb_i = r_start_of_climb_i[0]
            else:
                r_start_of_climb_i = r_sg_np
                log_info("TSV: Eliminated start of climb point.")

            r_temp_cor_v = temp_cor_v[valid_i_v]
            r_cond_cor_v = cond_init_cor_v[valid_i_v]
            r_pressure_v = pressure_v[valid_i_v]
            r_earliest_time_v = earliest_time_v[valid_i_v]
            r_volume_v = volume_v[valid_i_v]
            r_vehicle_pitch_degrees_v = vehicle_pitch_degrees_v[valid_i_v]
            r_vehicle_pitch_rad_v = vehicle_pitch_rad_v[valid_i_v]
            r_speed_cm_s_v = final_speed_cm_s_v[valid_i_v]
            r_glide_angle_deg_v = final_glide_angle_deg_v[valid_i_v]

            ## All arrays have been reduced at this point...
            still_stalled_i_v = [
                i for i in range(r_sg_np) if r_speed_cm_s_v[i] == 0
            ]  # this should always be empty!!
            if len(still_stalled_i_v):
                if sbect_unpumped:
                    log_error(
                        "HOW CAN THIS BE? Found stalled points on reduced r_speed_cm_s_v!"
                    )
                    break  # return not converged
                else:
                    # GPCTD doesn't care about stalls but we have divide by zero in interstitial calc below
                    if glider_interstitial_length > 0.0:
                        r_speed_cm_s_v[still_stalled_i_v] = 0.001  # fake it...

        # Always determine the viscosity of the water, which depends on temperature
        # dynamic viscosity mu10 = 1.397e-3; % Miyake & Koizumi(1948) JMR,v7,63-67 Cl=19 T=10
        # used by interstital buoyancy calc as well
        mu_v = (1.88e-3) / (
            1 + 0.03222 * r_temp_cor_v + 0.0002377 * r_temp_cor_v**2
        )  # Table II Cl=19
        TraceArray.trace_array("mu_%d" % loop, mu_v)
        nu_v = mu_v / nominal_ocean_density  # kinematic viscosity [m^2/s]
        TraceArray.trace_array("nu_%d" % loop, nu_v)
        if perform_thermal_inertia_correction:
            if sbect_unpumped:
                # Compute glide angle (in degrees), attack angle in degrees, and speed to m_s based on last estimate
                # We need these to perform the next round of temperature corrections
                speed_m_s_v = r_speed_cm_s_v * cm2m  # aka spd = speed
                theta_rad_v = np.radians(r_glide_angle_deg_v)
                attack_angle_deg_v = (
                    r_vehicle_pitch_degrees_v - r_glide_angle_deg_v
                )  # [deg] defn

                # Cap attack angles
                for i in range(r_sg_np):
                    aa = attack_angle_deg_v[i]
                    aaa = abs(aa)
                    if aaa < min_attack_angle or aaa > max_attack_angle:
                        # make the proper adjustment
                        if aa > max_attack_angle:
                            aa = max_attack_angle
                        elif aa < -max_attack_angle:
                            aa = -max_attack_angle
                        elif aa >= 0 and aa < min_attack_angle:
                            aa = min_attack_angle
                        elif aa < 0 and aa > -min_attack_angle:  # convert to else:
                            aa = -min_attack_angle
                        attack_angle_deg_v[i] = aa  # install fixed value

                # Correct temperature for various heating and flow effects in the CT tube based on current flight vector

                # First compute the conductivity cell flushing rate (u_f_v) and time (tau_f_v),
                # which depends on formation of boundary layers in the tube (ignoring the mouth)
                # Posielle flow regime at slow speeds, pipe flow at high.  CCE developed an eqn that moves between these based on measured rates

                # First calculate Posielle flow information
                # Speed of water at cell entrance depends on the attack angle of the glider (measured between 10 and .5 degrees)
                speed_at_ct_sensor_v = (
                    1.0296 - 0.0019311 * attack_angle_deg_v
                ) * speed_m_s_v  # 19 June 2006 mid-cell flume runs
                TraceArray.trace_array("speed_at_ct_%d" % loop, speed_at_ct_sensor_v)
                attack_angle_at_ct_sensor_v = (
                    -3.2632 + 0.577 * attack_angle_deg_v
                )  # 19 June 2006 mid-cell flume runs
                TraceArray.trace_array(
                    "attack_angle_at_ct_sensor_%d" % loop, attack_angle_at_ct_sensor_v
                )
                # compute cell drag based on cell geometry
                C_d_v = sbect_C_d0 * (
                    1 - 0.0074141 * attack_angle_at_ct_sensor_v / original_C_d0
                )
                TraceArray.trace_array("C_d_%d" % loop, C_d_v)

                # Now compute flow rate within the cell after the water attacks the opening
                # This is CCE's formula, eqn 35
                # When speed_at_ct_sensor_v is high, the second term vanishes and u_f => speed_at_ct_sensor_v (pipe)
                # When speed_at_ct_sensor_v is low, the second term dominates (it is the inverted Poiselle eqn) and the np exponent inverts it
                # In between, the np exponent blends the terms in accord with measurements
                nnp = 1.5  #  CCE's derived exponent parameter (3/2) that fits the measured data for flow rate in conductivity tube
                # ORDER .25m/s (roughly flight speed until we go slow)
                u_f_v = speed_at_ct_sensor_v * (
                    (
                        1
                        + (
                            16
                            * sbect_cell_length
                            * nu_v
                            / (sbect_r_n * sbect_r_n * C_d_v * speed_at_ct_sensor_v)
                        )
                        ** nnp
                    )
                    ** (-1 / nnp)
                )  # [m/s]

                # estimate temperature at entrance to narrow section of conductivity cell (temp_e_v)
                # first compute transit time lag from thermistor to cell mouth tau_1_v [s]
                flow_i_v = [
                    i
                    for i in range(r_sg_np)
                    if theta_rad_v[i] != 0.0 and r_vehicle_pitch_degrees_v[i] != 0.0
                ]  # where was water flowing?
                tau_1_v = np.zeros(r_sg_np)
                # TODO CCE why pitch and theta?  why not look for attack_angle_deg_v nonzero?
                # for the original CT on dives the thermistor hits the sampled water AFTER the conductivity tube
                # so the lag is positive on dives, negative on climbs (ORDER: .1-.2s)
                # NOTE this is last use of theta
                tau_1_v[flow_i_v] = (
                    (sbect_x_T + sbect_z_T / np.tan(r_vehicle_pitch_rad_v[flow_i_v]))
                    * np.sin(r_vehicle_pitch_rad_v[flow_i_v])
                    / (speed_m_s_v[flow_i_v] * np.sin(theta_rad_v[flow_i_v]))
                )
                bad_i_v = [i for i in range(r_sg_np) if not np.isfinite(tau_1_v[i])]
                tau_1_v[bad_i_v] = 0.0  # Assume no transit time lag where stalled...
            else:
                u_f_v = sbect_gpctd_u_f * cm2m * np.ones(r_sg_np)  # [m/s]
                tau_1_v = sbect_gpctd_tau_1 * np.ones(r_sg_np)

            TraceArray.trace_array("u_f_%d" % loop, u_f_v)
            TraceArray.trace_array("tau_1_%d" % loop, tau_1_v)
            tau_f_v = sbect_cell_length / u_f_v  # cell flushing time [s] (ORDER: ~.5s)
            TraceArray.trace_array("tau_f_%d" % loop, tau_f_v)

            # compute cell mouth to entrance of narrow (sample) section of cell lag [s]
            q_f_v = sbect_area_narrow * u_f_v  # cell flushing volume flux [m^3/s]
            vol_ec_v = cumtrapz(
                q_f_v, r_elapsed_time_s_v
            )  # volume history of flow entering cell [m^3] NOTE arg order reversed from matlab and this yeilds r_sg_np-1 entries
            vol_ec_v = np.insert(vol_ec_v, 0, 0.0)  # ensure equal length with r_sg_np
            TraceArray.trace_array("vol_ec_%d" % loop, vol_ec_v)

            # estimate average temperature within the cell narrow sample section (temp_a)
            # and average time at which water in sample section passed the thermistor (time_a),
            # assuming no cell wall heat exchange. Averages calculated by trapezoidal
            # rule approximation using nsegs segments

            nsegs = (
                5  # PARAMETER narrow section of CT broken into some number of segments
            )
            temp_a_v = np.zeros(r_sg_np)
            time_a_v = np.zeros(r_sg_np)

            for iseg in range(nsegs + 1):  # PSUEDO for iseg = 0:nsegs
                vol_iseg = sbect_vol_mouth_wide + sbect_vol_narrow * iseg / nsegs
                # volume of tube from mouth to current segment
                time_iseg_v = r_elapsed_time_s_v[0] * np.ones(r_sg_np)
                # time_iseg(ivcs) = interp1(vol_ec, time, vol_ec(ivcs) - vol_iseg, 'pchip');
                # This interpolation function was created above and vol_ec_v has not been changed
                vol_ok_i_v = [
                    i for i in range(r_sg_np) if vol_ec_v[i] > vol_iseg
                ]  # aka ivcs
                # The time (adjusted from elapsed_time) when this volume is in the tube
                time_iseg_v[vol_ok_i_v] = pchip(
                    vol_ec_v, r_elapsed_time_s_v, vol_ec_v[vol_ok_i_v] - vol_iseg
                )

                # offset entrance time of each vol seg according to geometry
                time_sampled_v = time_iseg_v - tau_1_v
                # any estimated time before we started dive or climb?
                too_early_i_v = [
                    i
                    for i in range(r_sg_np)
                    if time_sampled_v[i] < r_earliest_time_v[i]
                ]
                # if so, cap at start of dive or climb
                time_sampled_v[too_early_i_v] = r_earliest_time_v[too_early_i_v]

                temp_iseg_v = pchip(r_elapsed_time_s_v, r_temp_cor_v, time_sampled_v)
                seg_wt = (
                    0.5 / nsegs if iseg in (0, nsegs) else 1.0 / nsegs
                )  # first and last segment are not weighted as strongly
                temp_a_v += seg_wt * temp_iseg_v  # integrate weighted avg temp_a
                time_a_v += seg_wt * time_iseg_v  # integrate weighted avg time_a
                #     TraceArray.trace_array(
                #         "time_iseg_%d_%d" % (loop, iseg), time_iseg_v
                #     )
                #     TraceArray.trace_array(
                #         "time_sampled_%d_%d" % (loop, iseg), time_sampled_v
                #     )
                #     TraceArray.trace_array(
                #         "temp_iseg_%d_%d" % (loop, iseg), temp_iseg_v
                #     )
                #     TraceArray.trace_array("temp_a_%d_%d" % (loop, iseg), temp_a_v)
                #     TraceArray.trace_array("time_a_%d_%d" % (loop, iseg), time_a_v)

            # Find places where there was no apparently heating during time_a transient
            # interpolate assuming linear heating in that range
            diff_time_a_v = np.diff(time_a_v)
            itiv_v = [
                i for i in range(len(diff_time_a_v)) if diff_time_a_v[i] == 0.0
            ]  # find the places w/o heating
            len_itiv_v = len(itiv_v)
            if len_itiv_v:
                # If itiv is [1] this means points 1 and 2 are the same in time_a
                # we want to fix BOTH points so we need a point beyond this to calc
                # the slope.  And even if we wanted to just fix 2 we'd still need
                # that point.  time_a could be 0 at some points (negative tau_w?) whereas r_elapsed_time_s_v is
                # never zero so we interpolate using it.
                # BUG: if itiv == r_sg_np - 1 then this calc will fail since we will
                # look for time_a(r_sg_np + 1), which doesn't exist. (Dive 18
                # sg144/papa/2008.06)
                diff_itiv_v = np.diff(
                    itiv_v
                )  # where are the sections that have no time advance?
                breaks_i_v = [i for i in range(len(diff_itiv_v)) if diff_itiv_v[i] > 1]
                breaks_i_v.append(len_itiv_v - 1)  # add the final point
                last_i = 0
                for break_i in breaks_i_v:
                    interp_i_v = list(
                        range(itiv_v[last_i], min(itiv_v[break_i] + 2 + 1, r_sg_np))
                    )  # plus 1 for range
                    points_i_v = list(range(len(interp_i_v)))
                    coefficients = np.polyfit(
                        [points_i_v[0], points_i_v[-1]],
                        [time_a_v[interp_i_v[0]], time_a_v[interp_i_v[-1]]],
                        1,
                    )
                    time_a_v[interp_i_v] = np.polyval(coefficients, points_i_v)
                    last_i = break_i + 1

            TraceArray.trace_array("temp_a_%d" % loop, temp_a_v)
            TraceArray.trace_array("time_a_%d" % loop, time_a_v)
            # Apply thermal-inertia correction

            # Correct average temp_a_v for cell wall heating/cooling to get the final corrected temperature temp_c_v
            start_time = time.process_time()
            # TODO check with CCE on length, radius measurements for gun vs original CT
            # TODO things take a really long time with more points
            # in particular they scale as O(modes*mp_fine/1e4) seconds with uniform grid

            # We collect conductivity and temperature data on the r_elapsed_time_s_v grid
            # but the water in tube is offset and lagged and we need to know the interior temp_a and time_a of when it
            # also passed the thermistor.  That is what the volmetric calcuation does above.  We then compute
            # a corrected temp_c of that that temp_a water would have seen due to cell heating, etc.
            # and hence calculate a salin_c given the conductivity of that temp_a water.
            # We then (pchip) interpolate that salin_c at time_a to salin at the original time grid

            mode_time_s_v = r_elapsed_time_s_v
            # BUG shouldn't it be this?  mode_time_s_v = time_a_v
            mode_temp_a_v = temp_a_v
            # Map critical variables to a uniform fine time grid
            # NOTE: Force solution to 1s uniform grid. Solving using a non-uniform grid can cause ringing or extreme corrections
            # on scicon dives with ~1s sampling. See TestData/sg530_MISOBOB_Mar19 dives 83, 88, 95 etc.
            # m_dt = int(min_r_time_s)/2 # This is 5sec for papa
            # m_dt = max(r_dt,m_dt) # avoid 0 secs m_dt
            m_dt = 1  # Force match to CCE code - 1 second
            r_dt = m_dt  # For unsteady flight below
            m_time_fine_s_v = np.arange(
                int(mode_time_s_v[0]), int(mode_time_s_v[-1] + 1.0), m_dt
            )
            temp_a_fine_v = pchip(mode_time_s_v, mode_temp_a_v, m_time_fine_s_v)

            mp_fine = len(m_time_fine_s_v)
            tnp = (r_sg_np,)  # a tuple for interpolation reshape below
            log_debug(
                "%d: mode %d: %d pts at %.3fs" % (loop, modes, mp_fine, m_dt)
            )  # DEBUG

            # compute the derivative of temp_a_fine_v wrt m_time_fine_s_v
            dTadt_v = np.zeros(mp_fine)
            dTadt_v[0] = (temp_a_fine_v[1] - temp_a_fine_v[0]) / m_dt
            dTadt_v[-1] = (temp_a_fine_v[-1] - temp_a_fine_v[-2]) / m_dt
            dTadt_v[1:-1] = (temp_a_fine_v[2:] - temp_a_fine_v[0:-2]) / (2 * m_dt)
            TraceArray.trace_array("dTadt_v", dTadt_v)

            # Thermal boundary layer parameterization for large Prandtl number
            Pr = nu_v / kappa
            # Prandtl number

            # sbect_inlet_bl_factor default is 0.0, else 1.0
            # 0.0 implies base boundary layer growth on cell sample section length alone
            r = sbect_inlet_bl_factor * (sbect_x_w + sbect_x_m) / sbect_cell_length
            # inlet length to cell length ratio, scaled

            # Eqn 8a and 8b
            # The sqrt(L*nu/speed) term is a consequence of L/sqrt(Re) == L/sqrt(L*speed/nu) => sqrt(L*nu)/sqrt(speed)
            # The expressions in r following Pr^-1/3 are to encode the dependence of the BL on the leading geometry before the mouth
            # However, sbect_inlet_bl_factor above is forced to 0 and then, in both eqns, these expressions collapse to (2/3)
            # The sbect_Nu_0 factors scale the Nusselt number to account for unmodelled flow disruption inside and outside the tube

            # interior flow given cell flow Eqn 8a
            delta_T = (
                (1.0 / sbect_Nu_0i)
                * 1.73
                * (
                    (Pr ** (-1.0 / 3.0))
                    * (
                        (sbect_r_w / sbect_r_n - 1) * np.sqrt(r)
                        + (2.0 / 3.0) * ((1 + r) ** (1.5) - r ** (1.5))
                    )
                )
                * np.sqrt(sbect_cell_length * nu_v / u_f_v)
            )
            # outside (external) flow given glider spd (U) Eqn 8b
            delta_TU = (
                (1.0 / sbect_Nu_0e)
                * 1.73
                * (
                    (Pr ** (-1.0 / 3.0))
                    * (0 + (2.0 / 3.0) * ((1 + r) ** (1.5) - r ** (1.5)))
                )
                * np.sqrt(sbect_cell_length * nu_v / (r_speed_cm_s_v * cm2m))
            )

            # Compute thermal boundary layer column width [Schlicting 1955 eq 14.32-34]
            # cell volume averaged temperature weight applied to cell wall temperature
            # quadratic boundary layer temperature model
            bl_weight = np.ones(r_sg_np)
            np_i_v = np.arange(r_sg_np)  # for indexing

            # where does boundary layer intersect inside the tube?
            low_speed_i_v = [i for i in np_i_v if delta_T[i] > sbect_cell_length]
            # low speed, thick thermal boundary layer
            bl_weight[low_speed_i_v] = 1 - 0.5 * sbect_r_n / delta_T[low_speed_i_v]
            # where boundary layer does not intersect inside the tube
            high_speed_i_v = Utils.setdiff(np_i_v, low_speed_i_v)
            # high speed, thin thermal boundary later
            bl_weight[high_speed_i_v] = (2.0 / 3.0) * delta_T[
                high_speed_i_v
            ] / sbect_r_n - (1.0 / 6.0) * (delta_T[high_speed_i_v] ** 2) / (
                sbect_r_n * sbect_r_n
            )
            TraceArray.trace_array("bl_%d" % loop, bl_weight)

            # cell wall heating time constants & amplitudes estimated from model eqn 9a and 9b
            # Cell inner wall (r=1) Biot # Bi:
            Bi = (
                0.332
                * (2.0 / 3.0)
                * 1.73
                * thermal_cond_sw
                * sbect_r_n
                / (thermal_cond_glass * delta_T)
            )
            TraceArray.trace_array("Bi_%d" % loop, Bi)
            # Cell outer wall (r=b) Biot # Bo: eqn 9b
            Bo = (
                0.332
                * (2.0 / 3.0)
                * 1.73
                * thermal_cond_sw
                * sbect_r_n
                / (thermal_cond_polyurethane * delta_TU)
            )
            TraceArray.trace_array("Bo_%d" % loop, Bo)

            # ensure Biot numbers are always in range of tables
            # These maps cost about 1sec for 28K points
            Bi = [
                (Bim_max if Bn > Bim_max else (Bim_min if Bn < Bim_min else Bn))
                for Bn in Bi
            ]
            Bo = [
                (Bem_max if Bn > Bem_max else (Bem_min if Bn < Bem_min else Bn))
                for Bn in Bo
            ]

            temp_mode_v = np.zeros(mp_fine)  # individual mode contribution
            temp_modes_v = np.zeros(mp_fine)  # sum of modal contributions
            start_loop_time = time.process_time()  # DEBUG
            for mode in range(modes):  # get the contributions from each mode
                # interp2 using Bo and Bi
                # Can't just call the closures once on the Bi,Bo arrays
                # as that returns a matrix of the complete cross-product
                tau_f = mode_data[mode][0]
                tau_v = [tau_f(Bi[i], Bo[i]) for i in range(r_sg_np)]
                tau_v = np.reshape(np.array(tau_v), tnp)
                TraceArray.trace_array("mode_tau_%d_%d" % (loop, mode), tau_v)

                Ai_f = mode_data[mode][1]
                Ai_v = [Ai_f(Bi[i], Bo[i]) for i in range(r_sg_np)]
                Ai_v = np.reshape(np.array(Ai_v), tnp)
                TraceArray.trace_array("mode_A_%d_%d" % (loop, mode), Ai_v)

                # Expand tau and Ai to the fine-grained time grid
                # NOTE pchip can perform poor interpolations if extended...
                tau_v = pchip(mode_time_s_v, tau_v, m_time_fine_s_v)
                Ai_v = pchip(mode_time_s_v, Ai_v, m_time_fine_s_v)

                # Iteratively solve for thermal inertia wall heat anomaly
                temp_mode_v[
                    :
                ] = 0  # reset contrinution array and set temp_mode_v[0] = 0 as boundary condition
                # initialize the iterative computation
                prior_tau_v_i = tau_v[0]
                prior_tau_v_2 = 2 * prior_tau_v_i
                prior_temp_mode_v_i = 0  # Twaf[0]
                prior_Ai_dTadt = Ai_v[0] * dTadt_v[0]
                # Explicitly unroll the indexing loop using rotational variables for iterative solution
                for ii in range(1, mp_fine):
                    tau_v_i = tau_v[ii]
                    tau_v_2 = 2 * tau_v_i
                    Ai_dTadt = Ai_v[ii] * dTadt_v[ii]
                    # update for the next iteration
                    prior_temp_mode_v_i = (
                        prior_temp_mode_v_i
                        * tau_v_i
                        * (prior_tau_v_2 - m_dt)
                        / (prior_tau_v_i * (tau_v_2 + m_dt))
                    ) - (
                        m_dt * tau_v_i * (prior_Ai_dTadt + Ai_dTadt) / (tau_v_2 + m_dt)
                    )
                    temp_mode_v[ii] = prior_temp_mode_v_i  # record the anomaly
                    # rotate variables (prior_temp_mode_v_i is already 'rotated')
                    prior_tau_v_i = tau_v_i
                    prior_tau_v_2 = tau_v_2
                    prior_Ai_dTadt = Ai_dTadt

                TraceArray.trace_array("mode_temp_%d_%d" % (loop, mode), temp_mode_v)
                temp_modes_v = (
                    temp_modes_v + temp_mode_v
                )  # add this mode's contribution

            TraceArray.trace_array("modes_%d" % loop, temp_modes_v)
            # Compute the corrected temperature inside the conductivity tube
            # scaled by boundary layer
            # compute temperature at the cell wall back in the data time base
            temp_w_v = temp_a_fine_v + temp_modes_v
            # Return wall temperature to the original time grid
            temp_w_v = pchip(m_time_fine_s_v, temp_w_v, mode_time_s_v)
            TraceArray.trace_array("temp_w_%d" % loop, temp_w_v)

            # and finally the corrected temperature given the boundary layer size in time
            temp_c_v = temp_a_v + (temp_w_v - temp_a_v) * bl_weight
            TraceArray.trace_array("temp_c_%d" % loop, temp_c_v)
            # temperature at cond cell

            end_time = time.process_time()  # DEBUG
            max_temp_c_diff = max(abs(temp_c_v - temp_a_v))
            log_info(
                "%d: max temp_c diff: %.2fC TI time: %.3fs loop: %.3fs"
                % (
                    loop,
                    max_temp_c_diff,
                    (end_time - start_time),
                    (end_time - start_loop_time),
                )
            )  # DEBUG

            # then compute salinity from measured conductivity given corrected temperature of the lagged water
            # thus this is salinity of the actual water in the tube at effective time_a
            # but we want the salinity of the water outside at the thermistor
            # so we need to map it to measurement time below
            # M: salin_c = sw_salt(cond/c3515, temp_c, press);
            # salinity_v = array(map(lambda i: seawater.salt(r_cond_cor_v[i]/c3515, temp_c_v[i], r_pressure_v[i]), range(r_sg_np))) # aka salin_c
            if not base_opts.use_gsw:
                salin_c_v = seawater.salt(
                    r_cond_cor_v / c3515, temp_c_v, r_pressure_v
                )  # aka salin_c
            else:
                salin_c_v = gsw.SP_from_C(
                    r_cond_cor_v * 10.0, temp_c_v, r_pressure_v
                )  # aka salin_c
            TraceArray.trace_array("salin_salt_%d" % loop, salin_c_v)
            # Here is where we back calculate the salinity at the thermistor
            # M: find salinity at tip of thermistor salin (corresponds to corrected temperature temp)
            # M: salin = interp1(time_a, salin_c, time, 'pchip');
            r_salin_cor_v = pchip(time_a_v, salin_c_v, r_elapsed_time_s_v)  # aka salin
            # BUG time_a_v could end well before r_elapsed_time_s_v so when pchip extrapolates the points r_elapsed_time_s_v > max(time_a_v) it gives nonsense
            r_extrapolated_i_v = [
                i for i in range(r_sg_np) if r_elapsed_time_s_v[i] > time_a_v[-1]
            ]
            # DEAD r_extrapolated_i_v = [] # DISABLE
            r_salin_cor_v[r_extrapolated_i_v] = salin_init_cor_v[
                valid_i_v[r_extrapolated_i_v]
            ]  # a better guess often than pchip's
            TraceArray.trace_array("salin_pchip_%d" % loop, r_salin_cor_v)
            # always compute suspect points and interp_ts
            # but don't always interpolate
            if recompute_TS_interpolation:
                # compute the points, if any, then update
                # This is CCE's heuristic
                temp_corr_threshold = 0.075
                # PARAMETER threshold for deciding inertia correction was overdriven [degC]
                r_suspects_i_v = [
                    i
                    for i in range(r_sg_np)
                    if (abs(temp_c_v[i] - temp_a_v[i]) >= temp_corr_threshold)
                ]
                full_suspects_i_v = Utils.index_i(
                    valid_i_v, r_suspects_i_v
                )  # valid_i(r_suspects_i)
                # DEAD full_suspects_i_v = filter(lambda i: valid_i_v[0] <= i and valid_i_v[-1] >= i,full_suspects_i_v)
                if len(full_suspects_i_v):
                    salin_cor_v[
                        valid_i_v
                    ] = r_salin_cor_v  # make intermediate results available
                    # make interp_ts_i_v available so we can suggest below if need be
                    interp_ts_i_v = ts_interpolate(
                        temp_cor_v,
                        temp_cor_qc_v,
                        salin_cor_v,
                        salin_cor_qc_v,
                        full_suspects_i_v,
                        uncorrectable_i_v,
                        valid_i_v,
                        start_of_climb_i,
                        sbect_unpumped,
                        interpolate_extreme_tmc_points,
                        directives,
                        loop,
                    )
                    # reset this only when we finally recompute
                    recompute_TS_interpolation = False  # been here, done this

        else:  # no thermal_inertia correction
            if not base_opts.use_gsw:
                r_salin_cor_v = seawater.salt(
                    r_cond_cor_v / c3515, r_temp_cor_v, r_pressure_v
                )  # aka salin_c
            else:
                r_salin_cor_v = gsw.SP_from_C(
                    r_cond_cor_v * 10.0, r_temp_cor_v, r_pressure_v
                )  # aka salin_c
            r_extrapolated_i_v = []

        TraceArray.trace_array("salin_pre_interp_%d" % loop, r_salin_cor_v)
        salin_cor_v[
            valid_i_v
        ] = r_salin_cor_v  # ensure intermediate results are available and interpolate in full space
        # interpolate salinity here in full space
        interp_salin_i_v = QC.manual_qc(
            directives,
            "interp_salinity",
            "salin_QC_INTERPOLATED",
            QC.QC_INTERPOLATED,
            salin_cor_qc_v,
            "salinity",
        )
        # INTERPOLATE salinity AND temperature
        # cannot ensure temp is monotonically increasing or decreasing in interp_salin_i_v intervals
        # interpolate it first against time (or full_i??)
        QC.assert_qc(
            QC.QC_INTERPOLATED,
            temp_cor_qc_v,
            interp_salin_i_v,
            "TS temperature interpolation",
        )
        temp_cor_v, temp_cor_qc_v = QC.interpolate_data_qc(
            temp_cor_v,
            elapsed_time_s_v,
            interp_salin_i_v,
            "temperature",
            directives,
            temp_cor_qc_v,
            QC.QC_PROBABLY_BAD,
        )
        salin_cor_v, salin_cor_qc_v = QC.interpolate_data_qc(
            salin_cor_v,
            temp_cor_v,
            interp_salin_i_v,
            "salinity",
            directives,
            salin_cor_qc_v,
            QC.QC_PROBABLY_BAD,
        )
        r_salin_cor_v = salin_cor_v[
            valid_i_v
        ]  # update the reduced vector with interpolated results, if any

        TraceArray.trace_array("salin_post_interp_%d" % loop, r_salin_cor_v)

        # Corrected salinity now in r_salin_cor_v
        # Calculate buoyancy, and go back into the hydrodynamic model to
        # improve our estimate of velocity, this time as a function of buoyancy
        # and observed pitch.

        # Calculate Seaglider buoyancy, based on displaced volume, mass, and in situ density

        # CCE computes density and then density_insitu and uses insitu for bouyancy calc.
        # density = sw_dens0(salin_TS, temp);
        # NOTE: sw_dens0 is sw_dens with pressure (P) = 0
        # NOTE: Under matlab if r_salin_cor_v is negative dens (sw_dens0) returns an imaginary result but under Python it returns NaN.
        # This is also our potential density...we  use this to compute sigma_t below

        # Note that because of the isopycnal hull, we compute density as if pressure = 0
        if not base_opts.use_gsw:
            density_v = seawater.dens(
                r_salin_cor_v, r_temp_cor_v, np.zeros(r_salin_cor_v.size)
            )
        else:
            density_v = Utils.density(
                r_salin_cor_v,
                r_temp_cor_v,
                np.zeros(r_salin_cor_v.size),
                longitude,
                latitude,
            )
        TraceArray.trace_array("density_%d" % loop, density_v)
        # density_insitu = sw_dens(salin_TS, temp, press);
        # TODO should we return density_insitu_v instead of density_v?
        if not base_opts.use_gsw:
            density_insitu_v = seawater.dens(r_salin_cor_v, r_temp_cor_v, r_pressure_v)
        else:
            density_insitu_v = Utils.density(
                r_salin_cor_v, r_temp_cor_v, r_pressure_v, longitude, latitude
            )
        TraceArray.trace_array("density_insitu_%d" % loop, density_insitu_v)
        final_density_v[valid_i_v] = density_v
        final_density_insitu_v[valid_i_v] = density_insitu_v

        # bouyancy based on density (based on corrected salinty and temperature) and vehicle volume
        # We use insitu here, not uniform 0 pressure, to reflect density field we expect in stable water at measured T/S/P
        # NOTE: volume_v, from MakeDiveProfiles, includes the effect of compressee, if any
        buoyancy_v = kg2g * (
            density_insitu_v * r_volume_v * 1.0e-6 - mass
        )  # Inside parens is in kg; Buoyancy is in g
        TraceArray.trace_array("buoy_vehicle_%d" % loop, buoyancy_v)

        sigma_t_v = (
            density_v - 1000.0
        )  # BUG? why not density_insitu here to be uniform to the flight model?
        # Estimate buoyancy from flooded fairing (interstitial)
        # NOTE This will change w/ DG and the compressee
        interstitial_buoyancy_v = np.zeros(r_sg_np)
        if glider_interstitial_length > 0.0:  # estimate interstitial buoyancy
            # this assumes steady state fluid exchange of old fluid with new
            # and no mixing or rapid exchange (burping)
            # Compute u_en_v, nose hole entry speed [m/s]
            # Use the flushing eqns and logic above
            # CCE why do we think interstitial water between fairing and hull flows the same as the conductivity tube and the same exponent?
            # Won't this change with DG new fairings? (NO, if we always think of it as a tube with nothing interstitial given the tubes)
            nnp = 1.5  # PARAMETER? CCE's exponent parameter that fits the measured data for flow rate in glider nose
            # TODO Why not -1/nnp and use * ?
            u_en_v = (
                cm2m
                * r_speed_cm_s_v
                / (
                    (
                        1
                        + (
                            m2cm
                            * (
                                16
                                * nu_v
                                * glider_interstitial_length
                                / (glider_r_en * glider_r_en)
                            )
                            / r_speed_cm_s_v
                        )
                        ** nnp
                    )
                    ** (1 / nnp)
                )
            )
            q_en_v = (
                math.pi * glider_r_en * glider_r_en * u_en_v
            )  # nose entry volume flux [m^3/s]
            vol_en_v = cumtrapz(
                q_en_v, r_elapsed_time_s_v
            )  # volume history of flow entering nose [m^3]
            vol_en_v = np.insert(vol_en_v, 0, 0.0)  # ensure equal length with r_sg_np
            flushing_i_v = [
                i for i in range(r_sg_np) if vol_en_v[i] > glider_interstitial_volume
            ]  # indices of when the flow was flushing
            # t_en_v is the nose entry time of water currently exiting aft fairing [s]
            t_en_v = r_elapsed_time_s_v[0] * np.ones(r_sg_np)
            # M:t_en(iv) = interp1(vol_en, time, vol_en(iv) - vol_interstitial, 'pchip');
            t_en_v[flushing_i_v] = pchip(
                vol_en_v,
                r_elapsed_time_s_v,
                vol_en_v[flushing_i_v] - glider_interstitial_volume,
            )
            # M:sigma_t_ex = interp1(time, sigma_t, t_en, 'pchip'); % density of water exiting
            sigma_t_ex_v = pchip(
                r_elapsed_time_s_v, sigma_t_v, t_en_v
            )  # density of water exiting
            dmdt_v = q_en_v * (
                sigma_t_v - sigma_t_ex_v
            )  # interstitial mass change rate [kg/m^3/s]
            drhodt_v = Utils.ctr_1st_diff(
                sigma_t_v, r_elapsed_time_s_v
            )  # ambient density variation rate
            interstitial_buoyancy_v = -kg2g * cumtrapz(
                dmdt_v - drhodt_v * glider_interstitial_volume, r_elapsed_time_s_v
            )  # [g] TODO negative because?
            interstitial_buoyancy_v = np.insert(
                interstitial_buoyancy_v, 0, 0.0
            )  # ensure equal length with r_sg_np
            # TraceArray.trace_array("r_speed_%d" % loop, r_speed_cm_s_v)
            # TraceArray.trace_array("u_en_%d" % loop, u_en_v)
            # TraceArray.trace_array("vol_en_%d" % loop, vol_en_v)
            # TraceArray.trace_array("t_en_%d" % loop, t_en_v)
            # TraceArray.trace_array("sigma_t_ex_%d" % loop, sigma_t_ex_v)
            # TraceArray.trace_array("dmdt_%d" % loop, dmdt_v)
            # TraceArray.trace_array("drhodt_%d" % loop, drhodt_v)
            # TraceArray.trace_array(
            #     "buoy_interstitial_%d" % loop, interstitial_buoyancy_v
            # )

        # estimate buoyancy contribution from attached wake by filtering density
        wake_buoyancy_v = np.zeros(r_sg_np)
        if glider_wake_entry_thickness > 0.0:  # estimate wake buoyancy contribution
            wake_entry_area = math.pi * (
                (glider_r_fair + glider_wake_entry_thickness) ** 2 - glider_r_fair**2
            )  # [m^2]
            tau_wake_v = glider_vol_wake / (
                wake_entry_area * speed_m_s_v
            )  # wake density time constant [s]
            tau_wake_avg = np.mean(tau_wake_v)
            # M:sigma_t_fine = interp1(time, sigma_t, time_fine, 'pchip'); % interpolate to 1 s
            sigma_t_fine_v = pchip(
                r_elapsed_time_s_v, sigma_t_v, time_fine_s_v
            )  # interpolate to 1 s
            # BUG ensure fix(tau_wake_avg) is > 1.0
            tau_wake_avg = np.fix(
                max(tau_wake_avg, 1.0)
            )  # protect trifilt ANNOTATE THIS?
            sigma_t_fine_filt_v = trifilt(sigma_t_fine_v, tau_wake_avg)  # filter
            # M:sigma_t_wake = interp1(time_fine, sigma_t_fine_filt, time, 'pchip'); % decimate
            sigma_t_wake_v = pchip(
                time_fine_s_v, sigma_t_fine_filt_v, r_elapsed_time_s_v
            )  # decimate
            wake_buoyancy_v = (
                -kg2g * (sigma_t_wake_v - sigma_t_v) * glider_vol_wake
            )  # attached wake buoyancy [g]
            TraceArray.trace_array("buoy_wake_%d" % loop, wake_buoyancy_v)

        # Compute corrected buoyancy from dry buoyancy, interstitial and wake buoyancies
        buoyancy_corrected_v = buoyancy_v + interstitial_buoyancy_v + wake_buoyancy_v
        TraceArray.trace_array("buoy_final_%d" % loop, buoyancy_corrected_v)
        final_buoyancy_v[valid_i_v] = buoyancy_corrected_v  # make available for return

        # Employ hydrodynamic model with buoyancy and observed pitch to compute speed and glide angle
        # The model is contained in the function flightvec0, which solves the
        # unaccelerated flight equations iteratively for speed magnitude and glideangle
        # TODO don't the gaps in the data from bad samples, etc. cause artificial unsteady flight?

        # in CCE below this call
        # r_speed_cm_s_v aka spd_stdy
        # hdm_glide_angle_deg_v aka glideangle_stdy

        # First we solve the hydrodynamic eqns which assume NO acceleration (no changes in buoyancy)
        # so we get back a "steady" flight solution.  However, buoyancy is changing (internal waves) so we are accelerating
        # throughout the dive in small ways (exclusive of pumping and rolling). We approximate the true "unsteady" flight
        # solution by simulating the acceleration term as a small first-order lag process, rather than solving
        # a fuller set of flight eqns that incorporate acceleration terms.  This was found to be too slow for small effect gained.
        (
            hm_converged,
            hdm_speed_steady_cm_s_v,
            hdm_glide_angle_steady_rad_v,
            fv_stalled_i_v,
        ) = hydro_model(buoyancy_corrected_v, r_vehicle_pitch_degrees_v, calib_consts)
        if not hm_converged:
            log_warning(
                "Unable to converge during hydro-model calculations (%d)" % loop
            )

        # Ensure a reasonable model and determine the max residual speed from the last iteration
        # Smooth accelerations
        hdm_speed_unsteady_cm_s_v, hdm_glide_angle_unsteady_deg_v = filter_unsteady(
            tau_i,
            r_elapsed_time_s_v,
            time_fine_s_v,
            r_dt,
            hdm_speed_steady_cm_s_v,
            hdm_glide_angle_steady_rad_v,
        )
        # Per CCE we do not recompute stalls based on unsteady speed, only FV results
        # ensure these are set to zero as well
        hdm_speed_unsteady_cm_s_v[fv_stalled_i_v] = 0.0  # stalled
        hdm_glide_angle_unsteady_deg_v[
            fv_stalled_i_v
        ] = 0.0  # going nowhere... (not NaN, which leads to bad component velocities)

        # Compute the residual speed before we update r_speed_cm_s_v
        residual_speed_diff = abs(hdm_speed_unsteady_cm_s_v - r_speed_cm_s_v)
        max_residual_speed = max(residual_speed_diff)  # max(abs(spd_diff))
        log_debug("Max TSV speed residual %f" % max_residual_speed)

        TraceArray.trace_array("spd_stdy_%d" % loop, hdm_speed_steady_cm_s_v)
        TraceArray.trace_array(
            "glideangle_stdy_%d" % loop, np.degrees(hdm_glide_angle_steady_rad_v)
        )
        # convert to degrees
        TraceArray.trace_array("speed_unsteady_%d" % loop, hdm_speed_unsteady_cm_s_v)
        TraceArray.trace_array(
            "glideangle_unsteady_%d" % loop, hdm_glide_angle_unsteady_deg_v
        )
        TraceArray.trace_comment(
            "max_speed_residual_%d = %f" % (loop, max_residual_speed)
        )

        # update our speed for the next loop
        # if we are unpumped and there are stalls, we will eliminate them via reduction above
        # no need to average the speeds since this is our current best HDM guess
        if use_averaged_speeds:
            # CCE's original code
            # In the past if we don't converge then we do the whole thing again averaging speeeds to try to dampen
            # stiff system extrema.  But the new correction scheme is less prone to this than the old.  Is this DEAD code?
            # Update our speed and glide_angle estimate as the average of our previous estimate and the current estimate
            # we used to do this blend because sometimes the unsteady solution yields stalls and this causes instabilities in the solution
            # blending ensures a non-zero speed everywhere (since we ensure non-zero speed on our initial estimates)
            r_speed_cm_s_v = (r_speed_cm_s_v + hdm_speed_unsteady_cm_s_v) / 2.0
            r_glide_angle_deg_v = (
                r_glide_angle_deg_v + hdm_glide_angle_unsteady_deg_v
            ) / 2.0
        else:
            r_speed_cm_s_v = hdm_speed_unsteady_cm_s_v
            r_glide_angle_deg_v = hdm_glide_angle_unsteady_deg_v

        # map speed back to full so we can reduce properly above
        final_speed_cm_s_v[valid_i_v] = r_speed_cm_s_v
        final_glide_angle_deg_v[valid_i_v] = r_glide_angle_deg_v

        if len(fv_stalled_i_v):
            fv_stalled_i_v = Utils.index_i(
                valid_i_v, fv_stalled_i_v
            )  # map to full locations
            # by definition if we have more they are new and
            # by corrollary, once stalled, always stalled?...
            # succinct_elts adds +1 for matlab compat
            log_info(
                "TSV: %2d %d stalled points %s"
                % (
                    loop,
                    len(fv_stalled_i_v),
                    Utils.succinct_elts(np.array(fv_stalled_i_v)),
                )
            )

            # update the initial stalled points
            # sometimes removing points is not enough to ensure convergence
            # see papa/jun09/p1440368
            stalled_i_v = Utils.sort_i(
                Utils.unique(Utils.union(stalled_i_v, fv_stalled_i_v))
            )
            reduce = iterative_scheme  # possibly force this (again)

        # Did we converge on a consistent speed profile?
        if not iterative_scheme or max_residual_speed <= spd_diff_threshold:
            converged = True
            break

        if max_residual_speed > previous_max_residual_speed:
            log_debug(
                "New TSV residual %f worse than %f on iteration %d "
                % (max_residual_speed, previous_max_residual_speed, loop)
            )
        previous_max_residual_speed = max_residual_speed

    else:  # end of for loop
        big_residuals_i = [
            i for i in range(r_sg_np) if residual_speed_diff[i] > spd_diff_threshold
        ]
        log_info(
            "Unable to converge on TSV corrections at %s%s"
            % (
                Utils.succinct_elts(Utils.index_i(valid_i_v, big_residuals_i)),
                " using averaged speeds" if use_averaged_speeds else "",
            )
        )

    log_info("TSV exiting after %d iterations" % loop)
    if perform_thermal_inertia_correction:
        log_info("max_temp_c_diff = %.2fC" % max_temp_c_diff)
    if (
        max_temp_c_diff > 0.5
    ):  # did the final converged? loop have a large temp variance?  Likely ringing in maxtrix solutions to inversion
        # We test this at the end because the initial loops can have large variance that gets small (as stalls are removed)
        # See papa/jun09/p1440168

        # Likely because the sampling grid is very fine and the temperature changes are large as well
        # check min_r_time_s
        # See all the (scicon) dives in sg165_OKMC_Aug12
        log_warning(
            "Excessive thermal-inertia temperature variance (%.2fC) -- recomputing without thermal-inertia calculations"
            % max_temp_c_diff
        )
        directives.suggest(
            "no_correct_thermal_inertia_effects %% high temperature correction %.2fC"
            % max_temp_c_diff
        )

        return TSV_iterative(
            base_opts,
            elapsed_time_s_v,
            start_of_climb_i,
            # measurements, corrected
            temp_init_cor_v,
            temp_init_cor_qc_v,
            cond_init_cor_v,
            cond_init_cor_qc_v,
            salin_init_cor_v,
            salin_init_cor_qc_v,
            pressure_v,
            vehicle_pitch_degrees_v,
            # info about the glider and the instrument
            calib_consts,
            directives,
            volume_v,
            # how to make the calculations
            False,
            False,
            use_averaged_speeds,
            # initial guess about flight
            gsm_speed_cm_s_v,
            gsm_glide_angle_deg_v,
            longitude,
            latitude,
        )

    if len(r_extrapolated_i_v):
        QC.assert_qc(
            QC.QC_PROBABLY_BAD,
            salin_cor_qc_v,
            np.array(valid_i_v)[r_extrapolated_i_v],
            "TS bad extrapolation",
        )

    if sbect_unpumped:
        QC.assert_qc(
            QC.QC_PROBABLY_BAD,
            salin_cor_qc_v,
            stalled_i_v,
            "stalls avoid thermal-inertia salinity correction",
        )

    final_glide_angle_rad_v = np.radians(final_glide_angle_deg_v)

    if ~interpolate_extreme_tmc_points and len(interp_ts_i_v):
        diff_interp_ts_i_v = np.diff(interp_ts_i_v)
        breaks_i_v = [
            i for i in range(len(diff_interp_ts_i_v)) if diff_interp_ts_i_v[i] > 1
        ]
        breaks_i_v.append(len(interp_ts_i_v) - 1)  # add the final point
        last_i = 0
        for break_i in breaks_i_v:
            pre_index = interp_ts_i_v[last_i]
            post_index = interp_ts_i_v[break_i]
            ip_i_v = np.arange(pre_index, post_index + 1)  # before extension to anchors
            if len([i for i in ip_i_v if salin_cor_qc_v[i] == QC.QC_GOOD]):
                directives.suggest(
                    "interp_salinity data_points in_between %d %d %% suspect thermal-inertia points %s"
                    % (
                        pre_index + 1,
                        post_index + 1,
                        Utils.succinct_elts(Utils.intersect(ip_i_v, full_suspects_i_v)),
                    )
                )
            last_i = break_i + 1

    return (
        converged,
        temp_cor_v,
        temp_cor_qc_v,
        salin_cor_v,
        salin_cor_qc_v,
        final_density_v,
        final_density_insitu_v,
        # corrected glider properties based on seawater properties
        final_buoyancy_v,
        final_speed_cm_s_v,
        final_glide_angle_rad_v,
        speed_qc_v,
    )


# pylint: disable=unused-argument
# these are full arrays, not reduced
def ts_interpolate(
    temp_cor_v,
    temp_cor_qc_v,
    salin_cor_v,
    salin_cor_qc_v,
    full_suspects_i_v,
    uncorrectable_i_v,
    valid_i_v,
    start_of_climb_i,
    sbect_unpumped,
    interpolate_extreme_tmc_points,
    directives,
    loop,
):
    """Determine TS interpolation points given a list (full_suspects_i_v) of starting points.
    Returns results in updated QC tags and a list of 'stable' points that can be used as interpolation anchors
    Does NOT interpolate; caller is responsible for this.

    Input:
        temp_cor_v - corrected temperature
        temp_cor_qc_v - initial corrected temperature QC tags
        salin_cor_v - corrected salinity
        salin_cor_qc_v - initial corrected conductivity QC tags
        full_suspects_i_v - the initial locations where TMC corrections are suspect
        uncorrectable_i_v - locations of points that cannot be interpolated
        valid_i_v - locations of valid points within temp_cor_v and salin_cor_v
        start_of_climb_i - start of climb (2nd apogee pump)
        sbect_unpumped - whether the CT is unpumped
        interpolate_extreme_tmc_points - whether to interpolate
        directives - instance of ProfileDirectives for this profile
        loop - current iteration loop for trace_array and friends

    Output:
        interp_ts_i_v - what points should be interpolated to handle the full_suspects

    Raises:
      Any exceptions raised are considered critical errors and not expected

    """
    ts_threshold = 0.09  # PARAMETER [degC/psu] When was there a major move in TS space?

    # How to determine 'stable' points
    # Ratio of number of points between change and distance changed.  The larger the more stable.
    # generally we need several (at least 2 points) for the 'distance' in TS space traveled.
    # the number of points is normalized by the distance threshold
    adjacent_point_threshold = (
        1.5 / ts_threshold
    )  # PARAMETER: order 1>11 2>22 3>33, etc.

    sg_np = len(temp_cor_v)

    # TODO/BUG HACK? do we need to remove all asserted points so they aren't reduced on a subsequent round?
    # ensure suspects are only between the valid entries, since these are the
    # only points we can interpolate
    # NOTE caller did this already?
    full_suspects_i_v = Utils.index_i(
        full_suspects_i_v,
        [
            i
            for i in range(len(full_suspects_i_v))
            if (
                full_suspects_i_v[i]
                >= valid_i_v[0] & full_suspects_i_v[i]
                <= valid_i_v[-1]
            )
        ],
    )
    # we assert final set of points to interpolate below after expansion...
    num_full_suspects_i_v = len(full_suspects_i_v)
    if len(full_suspects_i_v):  # there are suspect locations that need to be dealt with
        # determine the segments we'll use to interpolate
        # determine these points to ensure interpolation at end points without crossing apogee
        # these are in full space.
        ts_end_points_i_v = [valid_i_v[0]]
        # We need to add the actual start and stop points, even if they are removed because of stalls
        # because, of course, we want to interpolate over stalls
        # NOTE pump_start to pump_end are NaN's in salinity so we declare the first non-NaN point before and after the range
        # This code assumes that QC_BAD points in salin_cor_v have been set to NaN
        # Alternative would be (salin_cor_qc_v[i] != QC_GOOD)
        ok_i_v = [i for i in range(sg_np) if np.isfinite(salin_cor_v[i])]
        l_ok_i_v = len(ok_i_v)
        ed_i = Utils.index_i(
            ok_i_v, [i for i in range(l_ok_i_v) if ok_i_v[i] < start_of_climb_i]
        )
        if len(ed_i):
            ts_end_points_i_v.append(ed_i[-1])
            sc_i = Utils.index_i(
                ok_i_v, [i for i in range(l_ok_i_v) if ok_i_v[i] >= start_of_climb_i]
            )
            if len(sc_i):
                ts_end_points_i_v.append(sc_i[0])
        ts_end_points_i_v.append(valid_i_v[-1])
        l_ts_end_points_i_v = len(ts_end_points_i_v)

        # determine points in TS space that change by a 'significant' amount
        # this code assumes that the TS data are trustworthy
        # enough to find plausible changes.  We determine stable changes below.

        # only use and count points that are in valid_i_v
        last_i = valid_i_v[0]
        ts_changes_i_v = [last_i]  # ensure apogee and end as well below
        ts_ts_dist_v = [1]  # avoid DivideByZero below
        ts_changes_num_points_v = [0]
        num_valid_points = 0

        s_last = salin_cor_v[last_i]
        t_last = temp_cor_v[last_i]
        for j in valid_i_v[1:]:  # this will skip the stalls etc.
            s_now = salin_cor_v[j]
            t_now = temp_cor_v[j]
            num_valid_points += 1
            delta_cs = s_now - s_last
            delta_ct = t_now - t_last
            dist = np.sqrt(delta_cs * delta_cs + delta_ct * delta_ct)
            if dist >= ts_threshold or [
                i for i in range(l_ts_end_points_i_v) if (ts_end_points_i_v[i] == j)
            ]:  # ensure end points are in list of changes
                ts_changes_i_v.append(j)
                ts_ts_dist_v.append(dist)
                ts_changes_num_points_v.append(num_valid_points)
                num_valid_points = 0  # reset
                last_i = j
                s_last = s_now
                t_last = t_now

        # We can stop at these points...
        stable_changes_i_v = [
            i
            for i in range(len(ts_changes_num_points_v))
            if (ts_changes_num_points_v[i] / ts_ts_dist_v[i] > adjacent_point_threshold)
        ]

        stable_i_v = Utils.index_i(
            ts_changes_i_v, stable_changes_i_v
        )  # over sg_np, not mpc
        # remove BAD points and ensure end_points are in the list...
        stable_i_v = Utils.sort_i(
            Utils.setdiff(stable_i_v, uncorrectable_i_v)
        )  # This can only happen if the user asserts it...DEAD?
        stable_i_v = Utils.sort_i(
            Utils.unique(Utils.union(ts_end_points_i_v, stable_i_v))
        )  # Ensure end points are on...regardless of commands
        ts_changes_i_v = Utils.sort_i(
            Utils.unique(Utils.union(ts_end_points_i_v, ts_changes_i_v))
        )  # ensure the end points are present
        # end of determining segments

        mpc = len(ts_changes_i_v)
        # report TS change and bend statistics
        log_debug(
            "TS changes: %d segments %f avg pts/segment, %d pts max"
            % (mpc, sg_np / mpc, max(np.diff(ts_changes_i_v)))
        )
        dive_changes_i_v = Utils.index_i(
            ts_changes_i_v,
            [i for i in range(mpc) if ts_changes_i_v[i] < start_of_climb_i],
        )
        climb_changes_i_v = Utils.index_i(
            ts_changes_i_v,
            [i for i in range(mpc) if ts_changes_i_v[i] >= start_of_climb_i],
        )
        # Figure out interpolation locations based on suspects and stable points
        interp_ts_i_v = []  # points in thermocline to interpolate
        # stable_v is true wherever we think the water mass is 'stable'
        # and we can use it to interpolate
        stable_v = np.zeros(sg_np)  # assume everyone is unstable
        stable_v[stable_i_v] = 1  # except these which are
        TraceArray.trace_array(
            "stable_i_%d" % loop, np.array(stable_i_v) + 1
        )  # +1 for matlab

        # TODO issue a warning if any anchor is NaN in salin??
        stable_suspects_i_v = stable_v[full_suspects_i_v]  # stability of the suspects
        stable_suspects_i_v = [
            i for i in range(len(stable_suspects_i_v)) if stable_suspects_i_v[i]
        ]
        if len(stable_suspects_i_v):  # any stable?
            suspects_l = len(full_suspects_i_v)
            log_debug(
                "TS: Ignoring %d of %d apparently stable points requiring correction"
                % (len(stable_suspects_i_v), suspects_l)
            )
            # remove these suspects
            full_suspects_i_v = Utils.index_i(
                full_suspects_i_v,
                Utils.setdiff(list(range(suspects_l)), stable_suspects_i_v),
            )

        TraceArray.trace_array(
            "suspects_i_%d" % loop, np.array(full_suspects_i_v) + 1
        )  # +1 for matlab
        # find interpolation segments given all this TS information...
        total_suspect_points_dropped = 0
        segment = 0
        last_seg_i_v = []  # what we last collected
        for suspect_i in full_suspects_i_v:
            try:
                last_seg_i_v.index(suspect_i)
                continue  # already absorbed in the previous segment
            except ValueError:
                pass  # not in previous segment, so start a new one

            # start of a new segment
            # for each new suspect that had large excess we want to grow a
            # 'shoulder' that stops when the excess is small when we can be
            # sure that we can interpolate between stable water masses

            # However, we only want to add points to the shoulder whose
            # error is too great AND whose density is changing in a
            # consistent direction in TS space.  For example, in the Lab Sea we have
            # Irminger Sea water incursions into Lab Sea water below the
            # mixed layer.  Here the density is increasing (nominally)
            # but the water masses have different T and S.  Even if these
            # points have small error we don't want to include them
            # as interpolant points--we want to interpolate Lab Sea
            # water with Lab Sea and Irminger Sea with Irminger Sea. And we
            # may not have stable points within the respective waters (end
            # points have too much error) so our interpolation will be
            # suspect itself (though will it be better than w/o it?).  The
            # density is changing too fast in both water masses and we could
            # be choosing points that are not representative of stable water.

            segment_report = ""
            segment = segment + 1
            this_seg_i_v = [suspect_i]
            # now expand the shoulders symmetrically

            # NOTE the suspect_i point could itelf be an anchor point
            # surounded by non-suspect points (papa jun09 70)
            # in this case we need to reject it by itself
            # for this reason we start from_by_to from
            # suspect_i itself, not +/- 1!
            # these points are over sg_npl
            from_by_to = [
                [suspect_i, -1, valid_i_v[0]],  # fore shoulder first valid point
                [suspect_i, 1, valid_i_v[-1]],
            ]  # aft shoulder last valid point
            n_stable_points = 0
            for ii in range(2):
                for j in range(
                    from_by_to[ii][0],
                    from_by_to[ii][2] + from_by_to[ii][1],
                    from_by_to[ii][1],
                ):  # +/-1 for range
                    if stable_v[j]:
                        n_stable_points = n_stable_points + 1
                        # don't include the stable point, interpolate_data will find this as an anchor
                        break  # stop..
                    this_seg_i_v.append(j)

            this_seg_i_v = Utils.sort_i(Utils.unique(this_seg_i_v))  # all the points
            TS_start_i = this_seg_i_v[0] - 1
            TS_end_i = this_seg_i_v[-1] + 1
            segment_report += "TS%2d: %2d %4d:%4d " % (
                segment,
                len(this_seg_i_v),
                TS_start_i + 1,
                TS_end_i + 1,
            )  # +1 for matlab

            segment_ok = True  # assume the best
            if n_stable_points < 2:
                segment_ok = False  # skip it!
                segment_report += " --  insufficient good points"

            TS_stable_i = [TS_start_i, TS_end_i]
            if (
                segment_ok
                and len(  # do this only after n_stable_points check...thus we know the end points are both stable
                    Utils.intersect(dive_changes_i_v, TS_stable_i)
                )
                != 2
                and len(Utils.intersect(climb_changes_i_v, TS_stable_i)) != 2
            ):
                # avoid interpolation across apogee
                # it is possible, because of directives (see wa/nov06/sg030 via noel)
                # for a segment to straddle dive and climb...which leads to odd interpolations
                segment_ok = False  # skip it
                segment_report += " -- straddles dive and climb"

            # copy now in case we skip below...
            last_seg_i_v = this_seg_i_v
            if segment_ok:
                log_debug(segment_report)
                # intern segment
                interp_ts_i_v.extend(this_seg_i_v)
            else:
                # not a good segment...
                # some subset of this segments points were marked as QC_INTERPOLATE...set these particular points as not-so-good
                QC.assert_qc(
                    QC.QC_PROBABLY_BAD,
                    salin_cor_qc_v,
                    Utils.intersect(full_suspects_i_v, this_seg_i_v),
                    "suspect thermal-inertia salinity",
                )
                skipped = len(Utils.intersect(this_seg_i_v, full_suspects_i_v))
                total_suspect_points_dropped += skipped
                segment_report += " %d pts skipped!" % skipped
                log_debug(segment_report)
                continue  # next point please

        # end for each suspect

        if total_suspect_points_dropped:
            log_info(
                "%d of %d stall and thermal-inertia suspect points skipped"
                % (total_suspect_points_dropped, num_full_suspects_i_v)
            )
        # now mark the final set of points we interpolated, if any
        if interpolate_extreme_tmc_points:
            QC.assert_qc(
                QC.QC_INTERPOLATED,
                salin_cor_qc_v,
                interp_ts_i_v,
                "TS salinity interpolation",
            )
        TraceArray.trace_array(
            "interp_ts_i_%d" % loop, np.array(interp_ts_i_v) + 1
        )  # +1 for matlab
    # end if len(full_suspects_i_v)

    return interp_ts_i_v


def init_speed_qc(sg_np, salin_cor_qc_v, vehicle_pitch_degrees_v):
    """Initialize speed QC vector
    Input:
      sg_np - number of points
      salin_cor_qc_v - initial salinity QC tags
      vehicle_pitch_degrees_v - measured vehicle pitch

    Returns:
      speed_qc_v - initial speed QC tags
      bad_speed_i_v - initial locations of bad QC tags
    Raises:
      Any exceptions raised are considered critical errors and not expected

    """
    speed_qc_v = QC.initialize_qc(sg_np, QC.QC_GOOD)
    QC.inherit_qc(salin_cor_qc_v, speed_qc_v, "corrected salin", "speed")
    # if the compass times out, it leaves NaN and we can't determine speed there
    # CONSIDER: test for abs(pitch) > 180 as well
    bad_pitch_i_v = [i for i in range(sg_np) if np.isnan(vehicle_pitch_degrees_v[i])]
    QC.assert_qc(QC.QC_BAD, speed_qc_v, bad_pitch_i_v, "pitch timeout")
    bad_speed_i_v = QC.bad_qc(speed_qc_v)
    return (speed_qc_v, bad_speed_i_v)
