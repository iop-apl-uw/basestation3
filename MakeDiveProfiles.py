#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025  University of Washington.
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

## Issues:
## - .cnf based sensors need to include descriptions, units and flag for inclusion in whole mission data fields for all columns
##

"""Routines for creating dive profiles from a Seaglider's eng and log files"""

import contextlib
import copy
import cProfile
import glob
import math
import os
import pdb
import pstats
import re
import sys
import time
import traceback

import gsw
import netCDF4
import numpy as np
import scipy.integrate
import seawater

import BaseDotFiles
import BaseGZip
import BaseMagCal
import BaseNetCDF
import BaseOpts
import BaseOptsType
import CalibConst
import DataFiles
import FileMgr
import FlightModel
import Globals
import GPS
import LegatoCorrections
import LogFile
import NetCDFUtils
import QC
import Sensors
import TraceArray

# from TraceArray import *  # REMOVE use this only only if we are tracing/comparing computations w/ matlab
import Utils
import Utils2
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from HydroModel import glide_slope, hydro_model
from TempSalinityVelocity import TSV_iterative, load_thermal_inertia_modes

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


kg2g = 1000.0
L2cc = 1000.0  # cc per liter
cm2m = 0.01
m2cm = 100.0
f0 = 1000.0  # Base frequency [hz] for conductivity conversion

m_per_deg = 111319.9  # at the equator
m_per_nm = 1852.0
seconds_per_day = 86400.0
Kelvin_offset = 273.15  # for 0 deg C
c3515 = 4.2914  # Conductivity at S=35, T=15, P=0, S/m
dbar_per_psi = 1.0 / 1.4503774
# Conversion factor used on the glider to convert pressure to depth
# must match value in glider/constants.h
psi_per_meter = 1.0 / 0.685

# This is temp diff between two time measurements...but perhaps we should look at dT/dZ instead?
thermocline_temp_diff = 0.034  # PARAMETER definition of thermocline temp difference


ARGO_sample_interval_m = 25  # [m] 1000m/40 samples, or 2000m/70 samples  (28.57m)

# flight_variables = [
#     "volmax",
#     "vbdbias",
#     "hd_a",
#     "hd_b",
#     "hd_c",
#     "hd_s",
#     "abs_compress",
#     "therm_expan",
#     "temp_ref",
#     "glider_length",
#     "rho0",
# ]

sb_ct_type_map = {
    0: "original Seabird unpumped CTD",
    1: "gun-style Seabird unpumped CTD",
    2: "pumped Seabird GPCTD",
    3: "gun-style Seabird unpumped SAILCT",
    4: "unpumped RBR Legato",
}

# This are all overwritten in sg_config_constants via the exec call - these
# are here to satisfy static linters
sg_ct_type = None
sg_vehicle_geometry = None
sg_sensor_geometry = None
sg_ct_geometry = None


def sg_config_constants(base_opts, calib_consts, log_deepglider=0, has_gpctd=False):
    """Update, by side effect, critical calibration and control constants
    with default values if not supplied
    Input:
    calib_consts - the initial constants from an actual sg_calib_constants.m file
    has_gpctd - whether there is a gpctd onboard

    Returns:
    calib_consts - updated with additional parameters
    """

    # the set of default configuration constants for different versions of
    # the Seaglider and Deepglider

    # First, an overall configuration parameter is set from which a cascade of
    # definitions can flow by default.  These definitions are broken into
    # various sections, each with their own grouping parameter.  This permits
    # easy mix-and-match and targetted override to the individiaul parameter
    # basis.  These overrides should be defined in the sg_calib_constants
    # file.
    def update_calib_consts(config, assert_in_globals=False):
        for var, default_value in list(config.items()):
            try:
                previous_value = calib_consts[var]  # override?
                if var not in Globals.flight_variables and var not in ["mass_comp"]:  # noqa: SIM102 We report these separately below
                    if previous_value != default_value:
                        log_info(
                            "Overriding %s=%s (default: %s)"
                            % (var, previous_value, default_value),
                            max_count=5,
                        )
                default_value = previous_value  # in case we are asserting below
            except KeyError:
                calib_consts[var] = default_value
            if assert_in_globals:
                # This use of exec is ok since the values are small integers and precision is irrelevant
                exec("%s = %g" % (var, default_value), locals(), globals())

    sbect_r_n = 0.002  # radius of narrow portion of cell [m]
    # Note: SBE9 u_f is 1.75m/s (see Morison d'Asaro)
    # gpctd_pump_speed = 0.9151*m2cm # pump flow speed [cm/s] for continuous pumped CTD (personal communication w/ SBE)
    # 0.7957747154594769m/s 10ml/s = 1e-5m^3/s from Janzen and Creed, 2011
    gpctd_pump_speed = (
        (1e-5 / (math.pi * (sbect_r_n**2))) * m2cm
    )  # pump flow speed [cm/s] for continuous pumped CTD (10ml/s through a 0.002m radius glass tube)
    # there are no 'octal' problems parsing '019' as 19 under python
    sg_id_num = int(calib_consts["id_str"])  # ensured to be defined by caller
    try:
        mass = calib_consts["mass"]
    except KeyError:
        log_error("No mass declared in sg_calib_constants.m; required!!")

    # Setting this variable should provide a set of defaults for all others
    try:
        sg_configuration = calib_consts["sg_configuration"]
    except KeyError:
        # Assume your stock, old style, Seaglider
        sg_configuration = 0
        if 104 <= sg_id_num < 400:
            # when SFC started at 100, all gliders post 105 have been gun-style
            # the hull numbers for SFC can run to 499 (500+ are iRobot numbers?)
            # CCE's original SG's ran to 23, then started to purchase from SFC starting at 100
            # DG's started at 30.  30-32 were SG fairing style DGs w/ aft compressee
            # 33+ are cylinderical DGs with fwd and aft compressee
            # all DGs use gun-style CTs
            # Assume stock Seaglider with new gun-style CT
            sg_configuration = 1
        if 30 <= sg_id_num < 50 or log_deepglider == 1:
            sg_configuration = 2  # DG
        if 400 <= sg_id_num < 500 or log_deepglider == 2:
            sg_configuration = 4  # Oculus
        if has_gpctd:
            sg_configuration = 3

    if sg_configuration not in [0, 1, 2, 3, 4]:
        log_warning(
            "Unknown Seaglider configuration %d; assuming stock SG with original CT mount"
            % sg_configuration
        )
        sg_configuration = 0

    calib_consts["sg_configuration"] = sg_configuration  # intern
    config = {
        0: {  # stock SG with original CT
            "sg_ct_type": 0,
            "sg_vehicle_geometry": 0,
            "sg_sensor_geometry": 0,
            "sg_ct_geometry": 0,
        },
        1: {  # stock SG new gun style CT
            "sg_ct_type": 1,
            "sg_vehicle_geometry": 0,
            "sg_sensor_geometry": 1,
            "sg_ct_geometry": 1,
        },
        2: {  # DG
            "sg_ct_type": 1,
            "sg_vehicle_geometry": 1,
            "sg_sensor_geometry": 2,
            "sg_ct_geometry": 1,
        },
        3: {  # stock SG with pumped GPCTD
            "sg_ct_type": 2,
            "sg_vehicle_geometry": 0,
            "sg_sensor_geometry": 3,
            "sg_ct_geometry": 0,  # irrelevant (we test sbect_unpumped)
        },
        4: {  # Oculus
            "sg_ct_type": 1,
            "sg_vehicle_geometry": 2,
            "sg_sensor_geometry": 2,
            "sg_ct_geometry": 1,
        },
    }[sg_configuration]
    # install overall configuration parameters
    update_calib_consts(config, assert_in_globals=True)

    config = {
        0: {  # std Seabird unpumped CTD
            "sbect_unpumped": 1,
            "sbect_inlet_bl_factor": 0.0,  # Scale factor for inlet boundary layer formation
            "sbect_Nu_0i": 1.0,  # Scale factor for unmodeled flow disruption to interior flow Biot number
            "sbect_Nu_0e": 1.0,  # Scale factor for unmodeled flow disruption to exterior flow Biot number
        },
        1: {  # gun-style  Seabird unpumped CTD
            "sbect_unpumped": 1,
            "sbect_inlet_bl_factor": 0.0,  # Scale factor for inlet boundary layer formation
            "sbect_Nu_0i": 1.0,  # Scale factor for unmodeled flow disruption to interior flow Biot number
            "sbect_Nu_0e": 1.0,  # Scale factor for unmodeled flow disruption to exterior flow Biot number
        },
        2: {  # pumped Seabird GPCTD
            "sbect_unpumped": 0,
            # An important note on the pumped CTD:
            # We treat it as an unpumped CTD with a known pump rate below.  This is unlikely to be correct (but better than nothing)
            # because there is internal plumbing (ducting) that shunts water from the thermistor location to the head of the
            # conductivity tube.  This ducting is order the length of the tube itself, is made of plastic (not glass/expoxy), and has
            # bends.  All this serves to lengthen and distort the boundary layer flow and hence heat exchange with the surrounding
            # medium before it enters the tube so our temp_a estimate and hence salin_c estimates are likely incorrect.
            "sbect_gpctd_u_f": gpctd_pump_speed,  # tube flow speed [cm/s] for continuous pumped (scaled flow)
            # the thermistor sting sits proud in the intake which is ~30mm vertical and ~10mm forward from the start of the tube, so tube is ~4cm removed from thermistor in all orientations
            "sbect_gpctd_tau_1": 4.0
            / gpctd_pump_speed,  # time delay [s] between thermistor and mouth of conductivity tube
            "sbect_inlet_bl_factor": 0.0,  # Scale factor for inlet boundary layer formation
            "sbect_Nu_0i": 1.0,  # Scale factor for unmodeled flow disruption to interior flow Biot number
            "sbect_Nu_0e": 1.0,  # Scale factor for unmodeled flow disruption to exterior flow Biot number
        },
        3: {  # unpumped Seabird SAILCT
            "sbect_unpumped": 1,  # assume we have an unpumped SBE41
        },
        4: {  # unpumped RBR Legatto
            "sbect_unpumped": 1,
        },
    }[sg_ct_type]

    # Number of modes to use for thermal-inertia correction (must be 1, 3, or 5)
    # modes = 5 # what CCE prefers (~10x time of mode 0) changes by .01degrees over mode = 1?
    # modes = 3 # quicker than 5
    # modes = 1 # similar to but much better than original code and pretty close to mode=3/5 in results
    # modes = 0 # disable but really should disable via the following directive in sg_directives.txt:
    #  * no_correct_thermal_inertia_effects
    # Post analysis of by Luc Rainville: mode of 1 sufficient and fast for most purposes
    config.update({"sbect_modes": 1})
    # install default sbect_unpumped, etc.
    update_calib_consts(config)
    sbect_unpumped = calib_consts["sbect_unpumped"]

    # Accumulate possible default values in config according to configrations
    config = {
        # Per Jason: assume but verify that tau_T applies to ALL CTDs from SBE, including the GPCTD
        # Since SBE existing SW is required to interp the data, Jason assumes it requires this factor
        "sbect_tau_T": 0.6,  # thermistor response[s] from SBE
        "cpcor": -9.5700e-08,  # nominal bulk compressibility of glass CT tube
        "ctcor": 3.2500e-06,  # thermal coefficient of expansion for glass CT tube
        # various biases, offsets, and control parameters
        "solve_flare_apogee_speed": 0,  # whether to solve unsteady flight during flare and apogee/climb pump
        "vbdbias": 0.0,  # [cc]
        "sbe_temp_freq_offset": 0,  # temp frequency offset
        "temp_bias": 0,  #  [deg]
        "sbe_cond_freq_offset": 0,  # cond frequency offset
        "cond_bias": 0,  #  [S/m]  conductivity bias
        "pitchbias": 0,  # [deg] pitch sensor bias
        "rollbias": 0,  # [deg] pitch sensor bias
        "depth_bias": 0,  #  [m] depth bias (in meters) because of a flakey or mis-tared pressure sensor
        "depth_slope_correction": 1.0,  # correction factor to apply to truck depth to compensate for data with incorrect pressure slope
        # setting to non-zero often helps catch the vehicle slowing down into a stall and accelerating to flight
        # it also helps with sitting on the bottom bouncing around...
        "min_stall_speed": 1.0,  # [cm/s] stalled if speed below this
        # faroes/jun08/sg005 dive 135 attained 1.2m/s speeds in upwelling
        "max_stall_speed": 100.0,  # [cm/s] stalled if speed above this and pitch less than min_stall_angle
        "min_stall_angle": 5.0,  # [degreees] stalled if np.abs(pitch) is less than stall angle (0.0 defeats this check)
        # Parameters that control the basic QC tests
        "QC_bound_action": QC.QC_BAD,
        "QC_spike_action": QC.QC_INTERPOLATED,
        # Carnes, M 'Lager Manual, Version 1.0', July 2008
        # Schmid, C, et al. 'The Real-Time Data Management System for Argo Profiling Float Observations', JAOT v24 1608ff Sept 2007
        "QC_temp_min": -2.5,  # [degC] Carnes, compare global Schmid -2.5 (labsea?) MDP -4.0
        "QC_temp_max": 43.0,  # [degC] Carnes, compare global Schmid 40.0
        "QC_temp_spike_depth": 500.0,  # [m] Carnes, ditto Schmid (db)
        #  permit faster temperature changes in the upper 500m due to thermoclines (world-wide)
        "QC_temp_spike_shallow": 0.05,  # 1.25/ARGO_sample_interval_m, # [degC/m] Carnes 2.0 (0.08), Schmid 6.0 (0.24)
        "QC_temp_spike_deep": 0.01,  # 0.25/ARGO_sample_interval_m, # [degC/m] Carnes 1.0 (0.04), Schmid 2.0 (0.08)
        # ARGO has no conductivity tests
        "QC_cond_min": 0.0,  # [S/ml]
        "QC_cond_max": 10.0,  # [S/ml] - was 40
        "QC_cond_spike_depth": 500.0,  # [m] Carnes
        # conductivity anomaly theory tells us the value should be 10x lower than temp bounds from Schmid
        "QC_cond_spike_shallow": 0.006,  # 0.15/ARGO_sample_interval_m, # [S/ml/m] Carnes 0.02
        "QC_cond_spike_deep": 0.001,  # 0.025/ARGO_sample_interval_m, # [S/ml/m] Carnes 0.01
        "QC_salin_min": 19.0,  # [PSU] was 2.0 per Carnes; ditto Schmid but we can't fly in waters that fresh
        "QC_salin_max": 45.0,  # [PSU] Carnes, compare global Schmid 41.0
        "QC_overall_ctd_percentage": 0.3,  # Carnes 30%
        "QC_overall_speed_percentage": 0.2,  # Must have at least 80% of good speeds to trust hdm speeds as good
        "QC_high_freq_noise": 15,  # number of samples; variable defined in Sensors/scicon_ext.py
        "GPS_position_error": 100,  # [meters]; see analysis in Bennett and Stahr, 2014
        "use_auxpressure": 1,  # Use aux pressure over truck pressure (if present)
        "use_auxcompass": 0,  # Use aux compass over truck compass (if present)
        "use_adcppressure": 0,  # Use adcp pressure over truck pressure (if present)
        # CONSIDER add tau_i, the unsteady delay [s] used by TSV (default 20, 0 for IOP)
    }

    # CT type (sg_ct_type) and construction (sg_ct_geometry)
    if sg_ct_type == 4:
        config.update(
            {
                "legato_time_lag": -0.8,
                "legato_alpha": 0.08,
                "legato_tau": 10.0,
                "legato_ctcoeff": 0.0,
                "legato_use_truck_pressure": 0,
                "legato_cond_press_correction": 1,
            }
        )
    elif sbect_unpumped:
        config.update(
            {
                ## all these constants apply to the unpumped SBE41 for its corrections
                "sbect_x_m": 0.0087,  # length of mouth portion of cell [m]
                "sbect_r_m": 0.0081,  # radius of mouth portion of cell [m]
                "sbect_cell_length": 0.09,  # combined length of 2 narrow (sample) portions of cell [m]
                "sbect_x_w": 0.0386,  # length of wide portion of cell [m]
                "sbect_r_w": 0.0035,  # radius of wide portion of cell [m]
                "sbect_r_n": sbect_r_n,  # radius of narrow portion of cell [m]
            }
        )
        # Define the (variable) geometry of the CT sail components that affect the T/S corrections
        config.update(
            {
                0: {  # original CT sail
                    "sbect_x_T": -0.014,  # cell mouth to thermistor x offset[m]
                    "sbect_z_T": -0.015,  # cell mouth to thermistor z offset[m]
                    "sbect_C_d0": 1.2,  # cell mouth drag coefficient
                },
                1: {  # gun CT sail
                    "sbect_x_T": -0.011,  # cell mouth to thermistor x offset[m]
                    "sbect_z_T": -0.030,  # cell mouth to thermistor z offset[m]
                    "sbect_C_d0": 2.4,  # cell drag mouth coefficient
                },
            }[sg_ct_geometry]
        )
    else:  # GPCTD
        config.update(
            {
                # TODO verify these numbers, measurements, which are copies of SBE41 above and likely incorrect
                "sbect_x_m": 0.0087,  # length of mouth portion of cell [m]
                "sbect_r_m": 0.0081,  # radius of mouth portion of cell [m]
                "sbect_cell_length": 0.09,  # combined length of 2 narrow (sample) portions of cell [m]
                "sbect_x_w": 0.0386,  # length of wide portion of cell [m]
                "sbect_r_w": 0.0035,  # radius of wide portion of cell [m]
                "sbect_r_n": sbect_r_n,  # radius of narrow portion of cell [m]
                "sbect_x_T": 0.0,  # cell mouth to thermistor x offset[m] (they are inline)
                "sbect_z_T": -0.020,  # cell mouth to thermistor z offset[m] (from intake to thermistor 20mm)
                "sbect_C_d0": 1.2,  # cell mouth drag coefficient
            }
        )

    # overall vehicle geometery (sg_vehicle_geometry)
    fm_consts = {
        "sg_configuration": sg_configuration,
        "mass": mass,
    }  # mass in case it is an SGX
    glider_type = FlightModel.get_FM_defaults(fm_consts)
    if base_opts.ignore_flight_model:
        user_supplied_vals = ["volmax", "rho0", "hd_a", "hd_b", "hd_c"]
        user_optional_vals = [
            "glider_length",
            "hd_s",
            "abs_compress",
            "therm_expan",
            "temp_ref",
        ]
        for val in user_supplied_vals:
            if val in fm_consts:
                del fm_consts[val]
        for val in user_optional_vals:
            if val in calib_consts:
                del fm_consts[val]

    config.update(fm_consts)

    config.update(
        {
            0: {  # stock SG
                "mass_comp": 0.0,  # mass of compressess [kg]
                # Define parameters that influence buoyancy
                # set this to 0 to disable interstitial calculations
                "glider_interstitial_length": 0.2,  # [m]
                "glider_interstitial_volume": 12e-3,  # [m3] 12 liters
                "glider_r_en": 0.00635,  # entry radius [m]
                "glider_wake_entry_thickness": 0.0,  # wake entry region thickness [m]
                "glider_vol_wake": 18e-3,  # attached wake volume [m^3] 18 liters
                "glider_r_fair": 0.3,  # fairing radius [m]
            },
            1: {  # 'std' DG
                "mass_comp": 0.0,  # mass of compressess [kg]
                # DG has no flow-through volume to speak of...
                "glider_interstitial_length": 0.0,  # [m]
                "glider_interstitial_volume": 0,  # [m3]
                "glider_r_en": 0.00635,  # entry radius [m]
                "glider_wake_entry_thickness": 0.0,  # wake entry region thickness [m]
                "glider_vol_wake": 18e-3,  # attached wake volume [m^3]
                "glider_r_fair": 0.3,  # fairing radius [m]
            },
            2: {  # 'std' Oculus
                "mass_comp": 0.0,  # mass of compressess [kg]
                # DG has no flow-through volume to speak of...
                "glider_interstitial_length": 0.0,  # [m]
                "glider_interstitial_volume": 0,  # [m3]
                "glider_r_en": 0.00635,  # entry radius [m]
                "glider_wake_entry_thickness": 0.0,  # wake entry region thickness [m]
                "glider_vol_wake": 18e-3,  # attached wake volume [m^3]
                "glider_r_fair": 0.3,  # fairing radius [m]
            },
        }[sg_vehicle_geometry]
    )

    # TODO these values need to be set for the GPCTD in final configuration
    # TODO add a new sg_sensor_geometry for GPCTD on SG, esp w/ ogive aft fairing...
    # vehicle sensor geometry (sg_sensor_geometry)
    config.update(
        {
            0:  # original SG pressure location and CT sail
            # JSB 9/9/9 zP -0.125 on SG(!);
            {
                "glider_xT": -1.1800,  # glider x coord of thermistor tip [m]
                "glider_zT": 0.1700,  # glider z coord of thermistor tip [m]
                "glider_xP": -0.6870,  # glider x coord of pressure gauge [m]
                "glider_zP": -0.0254,  # glider z coord of pressure gauge [m]
            },
            1:  # original SG pressure location with new gun CT sail
            # Gun measurements assume the stalk location for the old and new CT are the same
            # JSB 9/9/9 Gun: xT thermistor 0.07m further aft than SG
            # JSB 9/9/9 zP: -0.125 on SG(!);
            {
                "glider_xT": -1.2500,  # glider x coord of thermistor tip [m]
                "glider_zT": 0.1650,  # glider z coord of thermistor tip [m]
                "glider_xP": -0.6870,  # glider x coord of pressure gauge [m]
                "glider_zP": -0.0254,  # glider z coord of pressure gauge [m]
            },
            2:  # DG pressure location with new gun CT sail (35-39)
            # The gun style sail is mounted forward and the pressure sensor is in
            # the nose of the end cap behind the ogive fwd fairing
            {
                "glider_xT": -0.3000,  # glider x coord of thermistor tip [m]
                "glider_zT": 0.1840,  # glider z coord of thermistor tip [m]
                "glider_xP": -0.2280,  # glider x coord of pressure gauge [m]
                "glider_zP": -0.0000,  # glider z coord of pressure gauge [m]
                # for 40++ the pressure sensor port location changes see below
            },
            3:  # stock SG with pumped GPCTD
            # We use the GPCTD pressure sensor, not the vehicle sensor
            # Use locaton of pressure sensor as 0
            # The Z distances are estimated from the GPCTD spec sheet; VERIFY
            {
                "glider_xT": 0.0000,  # GPCTD x coord of thermistor tip [m]
                "glider_zT": 0.0748
                + 0.020
                + 0.040,  # GPCTD z coord of thermistor tip [m] (can + intake + offset from center)
                "glider_xP": 0.0000,  # GPCTD x coord of pressure gauge [m]
                "glider_zP": 0.0748 / 2
                + 0.040,  # GPCTD z coord of pressure gauge [m] (can/2 + offset from center)
            },
        }[sg_sensor_geometry]
    )

    if sg_configuration == 2 and sg_id_num >= 40:
        # for DG040++ the pressure sensor port in fwd end-cap changed, offset and back from center
        config.update(
            {
                "glider_xP": -0.2340,  # glider x coord of pressure gauge [m]
                "glider_zP": -0.0700,  # glider z coord of pressure gauge [m]
            }
        )

    # install defaults unless already present in calib_consts
    update_calib_consts(config)
    return glider_type


# stuff for anomaly detection
# coded this way so MATLAB transliteration is straightforward

# TODO we need to look for thermoclines over the whole record and estimate the salinity change from these changes
# then we can estimate the expected return of snot when it clears to include the change in salinity as well
surface_bubble_factor = 3.0  # PARAMETER depth of dflare or dsurf to look for bubbles
allowable_cond_anomaly_distance = 50  # PARAMETER depth difference over which we are willing to interpolate anomalous conductivity signals [m]


def cond_anomaly(
    cond_v,
    cond_qc_v,
    temp_v,
    temp_qc_v,
    elapsed_time_s_v,
    ct_depth_m_v,
    dflare,
    dsurf,
    start_of_climb_i,
    test_tank_dive,
):
    """Detects and handles conductivity anomalies in the datastream

    Input:
      cond_v - measured conductivity
      cond_qc_v - associated conductivity qc
      temp_v - measured temperature
      temp_qc_v - associated temperature qc
      elapsed_time_s_v - elapsed time of observations
      ct_depth_m_v - recorded depth of observations at CT
      dflare - depth (m) of flare maneuver
      dsurf - depth (m) of surface maneuver
      start_of_climb_i - start of climb (2nd apogee pump)
      test_tank_dive - whether this happened in the tank

    Returns:
      good_anomalies_v - a list of anomaly instances that we should deal with
      suspect_anomalies_v - a list of anomaly instances that the scientist should look at for directives

    Raises:
      Any exceptions raised are considered critical errors and not expected
    """
    # BUBBLES and SNOT (flotsom)
    # Detecting bubbles and other conductivity anomalies:

    # Normally the conductivity tube is filled with seawater but near
    # the surface air bubbles from breaking waves, storms, or the
    # vehicle broaching on ascent can enter the tune.  More rarely at
    # depth small biological particle (squid, etc.)  can enter as
    # well; this is referred to as 'snot'.  Eventually these anomalies
    # are flushed water moves through the tube.  However, both air and
    # biologicals are, as a rule, less salty than sea water so we see
    # these events as major drops, then returns, in conductivity.

    # Using the sw_cndr() routine in MATLAB we can estimate the
    # expected range of conductivity changes given a change of
    # temperature over expected salinity values and detect excursions
    # beyond those expected bounds.  Consider seawater with salinity =
    # 35psu and temp = 15degC at the surface (P 0=dbar); this C3515
    # point (see above) has a defined conductivity ratio of 1.  For
    # 14degC water at 35psu/0dbar the ratio is 0.9772, a difference
    # from C3515 of 0.0228.  Converting to conductivity 0.0228*4.2914
    # (the conductivity of c3515 water) yields 0.0980.  Thus we find
    # that a 1degC temperature difference yields a ~.1 difference in
    # conductivity, so we expect the np.abs(10*dC/dt - dT/dt) to be less
    # than .2.

    # It turns out the scale factor (10 in the above example) varies
    # largely by temperature and little by pressure over typical ocean
    # salinities (21 to 37).  Over those temperature specific scale
    # factors we find the expected excursion is +/- 0.24, so much
    # beyond it suggests anomalous conductivity (salinity) events.
    # Sea air is much less salty than biologicals.  Empirical
    # observations show bubbles generate differences > 1.5 while
    # biologicals create differences > .3 There seems to be no problem
    # w/ air bubble detection because the anomaly is so great. Snot at
    # depth is our issue.

    # Now the practicalities:

    # It is completely possible for anomaly to start (go negative),
    # then get worse, then slowly better over several disjointed
    # points.  And near the surface we might see the start of an
    # anomaly but never sample when it clears until the start of the
    # next dive.

    # If you get snot near the surface on a climb, it could not clear,
    # like a bubble.  No problem for that dive under the current alg.
    # However, if it has not cleared by the time the next dive starts,
    # it could clear later, perhaps during that dive, leading to a
    # positive transition w/o corresponding negative.  So we won't
    # correct to the start of the dive. (sg144 jun09 dive 149?)

    # Thermoclines are "skipped" as sources of conductivity anomalies
    # as a rule.  But if you happen to get snot in that layer once
    # again we have a masked negative transition and a later positive
    # transition.

    # Our approach: Find conductivity anomalies not accompanied by
    # large temperature excursions. Look for air bubbles at the start
    # and end of dives within some multiple of dflare and dsurf
    # respectively.  Over the remainder of the dive look for snot
    # excursions as groups of negative, then positive transitions that
    # roughly balance one another.  But there will be spurious
    # excursions that need to be either discarded or assigned to the
    # dive/climb bubble boundary.  This is because the thresholds are
    # somewhat permissive to find gradually increasing anomalies so
    # some 'normal' events are found.

    # MATLAB code to generate the scale factor table below
    # P=[0:100].*100; % go to 10k dbar for DG
    # for T = -5:37
    #   scales_v = [];  maxd = 0; mind = 50.0;
    #   for p=P
    #     delta_v = [];
    #     for S = 21:37
    #       delta_v = [delta_v ; sw_cndr(S,T,p) - sw_cndr(S,T-1,p)]; % cond diffs for a 1degC change in T against constant S/P
    #     end
    #     delta_v = delta_v.*4.2914; % scale diffs to C3515
    #     avg = mean(delta_v);
    #     scale = 1/avg;
    #     scales_v = [scales_v ; scale];
    #     maxd = max(maxd,scale*(max(delta_v) - avg)); % the max variance
    #     mind = min(mind,scale*(min(delta_v) - avg)); % the min variance
    #   end
    #   scale = mean(scales_v); % the average scale for this temp over a range of P and S
    #   fprintf(1, '        %.2f: %.2f, # %.2f %.2f\n', T, scale, mind, maxd);
    # end

    # This is slightly quadratic over the temp range below so we just use the values directly
    # these factors were computed over a 6k dbar pressure range and a salinity range from 21 to 37psu
    # This maps from degC to scale factor (average)
    dc_scale_factors = {
        -5.00: 14.65,  # -0.25 0.24
        -4.00: 14.48,  # -0.25 0.24
        -3.00: 14.31,  # -0.25 0.24
        -2.00: 14.15,  # -0.25 0.24
        -1.00: 13.99,  # -0.25 0.24
        0.00: 13.84,  # -0.25 0.24
        1.00: 13.70,  # -0.25 0.24
        2.00: 13.56,  # -0.25 0.24
        3.00: 13.43,  # -0.25 0.24
        4.00: 13.30,  # -0.25 0.24
        5.00: 13.17,  # -0.25 0.24
        6.00: 13.05,  # -0.25 0.24
        7.00: 12.93,  # -0.25 0.24
        8.00: 12.82,  # -0.25 0.24
        9.00: 12.71,  # -0.25 0.24
        10.00: 12.61,  # -0.25 0.24
        11.00: 12.51,  # -0.25 0.24
        12.00: 12.41,  # -0.25 0.24
        13.00: 12.32,  # -0.25 0.24
        14.00: 12.22,  # -0.25 0.24
        15.00: 12.14,  # -0.25 0.24
        16.00: 12.05,  # -0.25 0.24
        17.00: 11.97,  # -0.25 0.24
        18.00: 11.89,  # -0.25 0.24
        19.00: 11.82,  # -0.25 0.24
        20.00: 11.74,  # -0.25 0.24
        21.00: 11.67,  # -0.25 0.24
        22.00: 11.61,  # -0.25 0.24
        23.00: 11.54,  # -0.25 0.24
        24.00: 11.48,  # -0.25 0.24
        25.00: 11.42,  # -0.25 0.24
        26.00: 11.36,  # -0.25 0.24
        27.00: 11.30,  # -0.25 0.24
        28.00: 11.25,  # -0.25 0.24
        29.00: 11.20,  # -0.25 0.24
        30.00: 11.15,  # -0.25 0.24
        31.00: 11.10,  # -0.25 0.24
        32.00: 11.05,  # -0.25 0.24
        33.00: 11.01,  # -0.25 0.24
        34.00: 10.97,  # -0.25 0.24
        35.00: 10.93,  # -0.25 0.24
        36.00: 10.89,  # -0.25 0.24
        37.00: 10.85,  # -0.25 0.24
    }
    min_sf_temp = min(dc_scale_factors.keys())
    max_sf_temp = max(dc_scale_factors.keys())
    # We need a low threshold for anomalies because snot can start small and build up
    # detection versus spike confirmation threshold, based on min/max values for each temp value above
    anomaly_diff_factor = 0.25  # PARAMETER over the range of scale factors for the the min/max of excursions

    # Moved to global
    # This is temp diff between two time measurements...but perhaps we should look at dT/dZ instead?
    # thermocline_temp_diff = 0.034  # PARAMETER definition of thermocline temp difference

    # When we compute depth we should use the max of dsurf/dflare times the factor

    bubble_depth = (
        0.01 if test_tank_dive else surface_bubble_factor * max(dflare, dsurf)
    )  # [m]
    acceptable_anomaly_threshold = 0.7  # PARAMETER the accumulated conductivity excursion required for detection (was 0.9)
    suspect_snot = 1.2  # PARAMETER if max_excursion is less than this, issue as suspect
    # DEAD suspect_snot = 100 # this forces all to suspect
    nearby_snot_distance = (
        20  # PARAMETER vertical traveled distance to permit accumulation of snot
    )
    air_bubble_threshold = acceptable_anomaly_threshold  # PARAMETER expected variance for air bubbles (very much larger than anomaly_diff_factor) use .8 instead? was 1.5

    good_anomalies_v = []
    suspect_anomalies_v = []

    # Remove any bad points and remap apogee points into valid space
    sg_np = len(temp_v)
    bad_i_v = Utils.union(QC.bad_qc(temp_qc_v), QC.bad_qc(cond_qc_v))
    bad_i_v = Utils.union(
        bad_i_v, [i for i in range(sg_np) if np.isnan(temp_v[i]) or np.isnan(cond_v[i])]
    )
    valid_i_v = Utils.setdiff(np.arange(sg_np), bad_i_v)
    valid_i_v = np.array(valid_i_v)  # so we can index properly below
    sg_np = len(valid_i_v)
    if sg_np < 3:  # not enough data
        return good_anomalies_v, suspect_anomalies_v

    temp_v = temp_v[valid_i_v]
    cond_v = cond_v[valid_i_v]
    elapsed_time_s_v = elapsed_time_s_v[valid_i_v]
    # do not reduce ct_depth_m; we map points to valid entries below...

    # the conductivity anomaly detector only cares about relative change of temp and conductivity, not rate
    temp_diff_v = np.zeros(sg_np)
    temp_diff_v[1:] = np.diff(temp_v)
    dTdt_v = np.zeros(sg_np)
    dTdt_v[1:] = temp_diff_v[1:] / np.diff(
        elapsed_time_s_v
    )  # but we do need to detect thermoclines, so compute dTdt

    itemp_v = np.fix(temp_v)
    too_cold_i = [i for i in range(sg_np) if itemp_v[i] < min_sf_temp]
    if len(too_cold_i):
        log_warning(
            "Missing conductivity anomaly scale factors for cold temperatures: %s"
            % Utils.unique(itemp_v[too_cold_i])
        )
        itemp_v[too_cold_i] = min_sf_temp
        # cap it

    too_hot_i = [i for i in range(sg_np) if itemp_v[i] > max_sf_temp]
    if len(too_hot_i):
        log_warning(
            "Missing conductivity anomaly scale factors for warm temperatures: %s"
            % Utils.unique(itemp_v[too_hot_i])
        )
        itemp_v[too_hot_i] = max_sf_temp
        # cap it

    scale_factors_v = [dc_scale_factors[t] for t in itemp_v]
    cond_diff_v = np.zeros(sg_np)
    cond_diff_v[1:] = scale_factors_v[:-1] * np.diff(cond_v)  # use leading temperature
    # TODO consider renaming variables: c_bubble... -> c_anomaly_
    ca_diff_v = (
        cond_diff_v - temp_diff_v
    )  # This should be close to zero unless there is some anomaly or thermocline

    cond_dominates_i_v = [
        i for i in range(sg_np) if (np.abs(cond_diff_v[i]) > np.abs(temp_diff_v[i]))
    ]  # major contribution was from conductivity change, not temp change
    bubbles_i_v = [
        i for i in range(sg_np) if (np.abs(ca_diff_v[i]) > air_bubble_threshold)
    ]  # we have a bubble (regardless of temp diff)
    spikes_i_v = [
        i for i in range(sg_np) if (np.abs(ca_diff_v[i]) > anomaly_diff_factor)
    ]  # we have an conductivity variance from expected
    not_thermocline_i_v = [
        i for i in range(sg_np) if (np.abs(dTdt_v[i]) < thermocline_temp_diff)
    ]  # we haven't detected a thermocline

    ca_issues_i_v = Utils.intersect(
        cond_dominates_i_v,
        Utils.union(bubbles_i_v, Utils.intersect(spikes_i_v, not_thermocline_i_v)),
    )
    ca_issues_i_v = Utils.sort_i(ca_issues_i_v)

    if len(ca_issues_i_v):
        bubbles_i_v = Utils.intersect(bubbles_i_v, ca_issues_i_v)
        if len(bubbles_i_v):
            bubbles_i_v = Utils.sort_i(bubbles_i_v)
            handled_bubbles_i_v = []
            dive_bubble = Anomaly()
            climb_bubble = Anomaly()
            for i in bubbles_i_v:
                iv = valid_i_v[i]
                if ct_depth_m_v[iv] < bubble_depth:
                    anomaly = ca_diff_v[i]
                    # Mark what kind of bubble and ensure it extends to shallowest point
                    # Had this nice idea to just interpolate bubbles if they stopped and started
                    # but really there is just so much mess at the top of dive the interplations were a mess
                    if iv < start_of_climb_i:
                        dive_bubble.add_anomaly_point(iv, anomaly)
                    else:
                        climb_bubble.add_anomaly_point(iv, anomaly)
                    handled_bubbles_i_v.append(i)
                else:
                    # NOTE: This is typically caused by electrical noise in the C (and likely T) signal (see sg144_ps_022613/p1440003)
                    # We hold on to these points for normal CA processing below, collecting adjacent points if possible
                    # Otherwise the parameters used by qc_checks() will find this as a single conductivity spike
                    log_debug(
                        "Skipping apparent bubble point (%d) too deep (%.1fm)!"
                        % (iv, ct_depth_m_v[iv])
                    )

            if len(dive_bubble.points()):
                dive_bubble.add_anomaly_point(valid_i_v[0], 0)  # add the start of dive
                dive_bubble.finalize(
                    "conductivity bubble on dive", ct_depth_m_v, QC.QC_BAD
                )
                good_anomalies_v.append(dive_bubble)  # emit

            if len(climb_bubble.points()):
                climb_bubble.add_anomaly_point(
                    valid_i_v[sg_np - 1], 0
                )  # add the end of the climb
                climb_bubble.finalize(
                    "conductivity bubble on climb", ct_depth_m_v, QC.QC_BAD
                )
                good_anomalies_v.append(climb_bubble)  # emit

            # After dealing with bubbles, drop whatever points were dealt with
            ca_issues_i_v = Utils.setdiff(ca_issues_i_v, handled_bubbles_i_v)
            if len(ca_issues_i_v) == 0:
                return good_anomalies_v, suspect_anomalies_v

        # Now try to find snot at depth
        # This is where all the tricks come into play
        # The basic idea is to collect and pair negative and positive excursions into starts and stops of anomalies
        a = Anomaly()  # start one up
        for i in ca_issues_i_v:
            iv = valid_i_v[i]
            anomaly = ca_diff_v[i]
            if a.collecting():  # are we collecting? (have we seen a negative start?)
                if anomaly > 0.0:  # a step toward recovery...
                    a.add_anomaly_point(iv, anomaly)
                    # Have we recovered from the anomaly? PARAMETER
                    if (
                        a.anomaly_positive_sum > np.abs(a.anomaly_negative_sum)
                        or np.abs(a.anomaly_sum) / a.max_excursion() < 0.10
                    ):  # or are we close enough
                        if a.max_excursion() > acceptable_anomaly_threshold:
                            a.finalize(
                                "conductivity anomaly", ct_depth_m_v, None
                            )  # snot at depth
                            if a.max_excursion() < suspect_snot:
                                suspect_anomalies_v.append(a)  # emit for suggestion
                            else:
                                good_anomalies_v.append(a)  # emit
                        else:
                            a.finalize(
                                "SUSPECT weak conductivity anomaly", ct_depth_m_v, None
                            )
                            vertical_anomaly_distance = a.extent()
                            if vertical_anomaly_distance < nearby_snot_distance:
                                suspect_anomalies_v.append(a)  # % emit for suggestion
                            else:
                                log_warning("Weak resolved anomaly skipped: %s" % a)
                        a = Anomaly()  # regardless, start a new one
                else:  # another negative
                    # what about if we have seen a positive?  terminate?
                    # what if we see another negative but the distance has been too great since the last one?
                    vertical_anomaly_distance = sum(
                        np.abs(
                            np.diff(ct_depth_m_v[a.last_point() : min(iv + 1, sg_np)])
                        )
                    )  # from last point up to and including this point
                    if (
                        np.abs(a.anomaly_negative_sum + anomaly)
                        > acceptable_anomaly_threshold
                        and vertical_anomaly_distance  # is it a weak start?
                        > nearby_snot_distance
                    ):  # and distant?
                        # +1 for matlab compat
                        log_warning(
                            "Restarting anomaly after %.2fm: %.4f at %.2fm (%d)"
                            % (
                                vertical_anomaly_distance,
                                anomaly,
                                ct_depth_m_v[iv],
                                iv + 1,
                            )
                        )
                        a = Anomaly()
                        # start a new one
                    a.add_anomaly_point(iv, anomaly)
            else:  # not accumulating yet
                if anomaly > 0.0:
                    # positive transition
                    if anomaly > acceptable_anomaly_threshold:
                        # too deep or clearly not an air bubble
                        # likely snot from start of dive to here....eliminate
                        # +1 for matlab compat
                        log_warning(
                            "Large unexplained positive conductivity anomaly %.4f at %.2f m (%d)"
                            % (anomaly, ct_depth_m_v[iv], iv + 1)
                        )
                else:  # negative transition
                    a.add_anomaly_point(iv, anomaly)

        if a.collecting():  # noqa: SIM102 # we had an active anomaly when we ran out
            # we added negative excursion(s) without sufficient positive return excursion(s)
            # if we have signficant excursion under development, warn about that
            if a.max_excursion() > acceptable_anomaly_threshold:
                # some kind of big snot
                vertical_anomaly_distance = a.extent()
                if vertical_anomaly_distance < nearby_snot_distance:
                    a.finalize(
                        "SUSPECT unresolved strong conductivity anomaly",
                        ct_depth_m_v,
                        None,
                    )
                    suspect_anomalies_v.append(a)  # emit for suggestion
                else:
                    log_warning(
                        "Unresolved strong conductivity anomaly skipped: %s" % a
                    )

    return good_anomalies_v, suspect_anomalies_v


class Anomaly:
    def __init__(self):
        self.anomaly_v = []
        # the current working anomaly points
        self.anomaly_negative_sum = 0
        # total excusion in negative (start) direction
        self.anomaly_positive_sum = 0
        # total excusion in positive (recovery) direction
        self.anomaly_sum = 0
        # total excursion
        self.extent_m = 0
        # number of meters the anomaly extends vertically
        self.points_i_v = []
        # the full set of indices
        self.description = "anomaly"
        self.qc_tag = QC.QC_NO_CHANGE

    def __str__(self):
        if self.collecting():
            # If you report indices, don't forget +1 for matlab compat
            return "<%d pt %s n:%.2f p:%.2f>" % (
                len(self.points_i_v),
                self.description,
                self.anomaly_negative_sum,
                self.anomaly_positive_sum,
            )
        else:
            return "<empty anomaly>"

    def finalize(self, descr, depth_v, qc_tag=None):
        self.extent_m = sum(np.abs(np.diff(depth_v[self.points()])))
        if qc_tag is None:
            qc_tag = (
                QC.QC_BAD
                if (self.extent_m > allowable_cond_anomaly_distance)
                else QC.QC_INTERPOLATED
            )
        self.qc_tag = qc_tag
        tag = "uncorrectable " if qc_tag == QC.QC_BAD else ""
        self.description = "%s%.1fm %s" % (tag, self.extent_m, descr)

    def qc(self):
        return self.qc_tag

    def descr(self):
        return self.description

    def extent(self):
        return self.extent_m

    def max_excursion(self):
        return max(self.anomaly_positive_sum, np.abs(self.anomaly_negative_sum))

    def collecting(self):
        return len(self.anomaly_v) > 0

    def last_point(self):
        return self.anomaly_v[-1]

    def first_point(self):
        return self.anomaly_v[0]

    def points(self):
        return self.points_i_v

    def add_anomaly_point(self, i, anomaly):
        # i should be valid indices only, not reduced
        a_v = self.anomaly_v
        a_v.append(i)
        a_v = np.sort(a_v)  # ensure they are in ascending order
        self.anomaly_v = a_v.tolist()
        if anomaly < 0.0:
            self.anomaly_negative_sum += anomaly
        else:
            self.anomaly_positive_sum += anomaly
        self.anomaly_sum += anomaly
        if len(self.anomaly_v) == 1:
            self.points_i_v = [i]
        else:
            self.points_i_v = list(range(self.first_point(), self.last_point() + 1))
        return self.anomaly_sum


def compressee_density(temperature, pressure, fit):
    """Compute the density of compressee

    Input:
    temperature - insitu temperature [degC]
    pressure    - insitu pressure [dbar]
    fit         - a dict of fluid equation of state fit parameters

    Returns:
    density     - density [g/cc]

    Raises:
      Any exceptions raised are considered critical errors and not expected
    """
    A = fit["A"]
    B = fit["B"]
    T = fit["T"]
    P = fit["P"]
    last = np.ones(len(temperature))
    Tx = [last]  # the zeroth entry
    for _ in range(T):
        last = last * temperature
        Tx.append(last)

    last = np.ones(len(pressure))
    Px = [last]  # the zeroth entry
    for _ in range(P + 1):
        last = last * pressure
        Px.append(last)

    rho0 = np.polyval(A, temperature)

    drho = np.zeros(len(pressure))
    b = 0
    for n in range(P + 1):
        for m in range(T + 1):
            # compute rho along our grid using analytic integration B*(T^m)*((1/n)*P^(n+1))
            drho = drho + (B[b] / (n + 1)) * Tx[m] * Px[n + 1]
            b = b + 1
    rho = rho0 + drho  # compressee density [kg/m^3]
    rho = rho / 1000  # [g/cc]  (1E3 g/kg)/(1E6 cc/m^3)
    return rho


def compute_displacements(
    tag, horizontal_speed_cm_s_v, delta_time_s_v, total_dive_time_s, head_polar_rad_v
):
    """Given an estimate of horizontal speeds, elapsed times, and headings compute northward and eastward displacements
    Input:
    tag - string indicating the source of horizontal speeds
    horizontal_speed_cm_s_v - speed estimate
    delta_time_s_v - time between estimates (could be zero if stationary)
    total_dive_time_s - total flight time
    head_polar_rad_v - headings in radians

    Returns:
    east_displacement_m_v, north_displacement_m_v -- individual displacements
    east_displacement_m, north_displacement_m -- integrated (total) displacements
    east_average_speed_m_s, north_average_speed_m_s -- average flight model speeds

    Raises:
    None
    """
    z_horizontal_speed_cm_s_v = np.array(horizontal_speed_cm_s_v)  # make copy
    unkn_i_v = [
        i
        for i in range(len(z_horizontal_speed_cm_s_v))
        if np.isnan(z_horizontal_speed_cm_s_v[i])
    ]
    z_horizontal_speed_cm_s_v[unkn_i_v] = 0.0
    # see comment in make_dive_profile() about headings in polar coordinates
    # in this case cos() gets the east (U) component; sin() get the north (V) component of speeds
    east_speed_cm_s_v = z_horizontal_speed_cm_s_v * np.cos(head_polar_rad_v)
    north_speed_cm_s_v = z_horizontal_speed_cm_s_v * np.sin(head_polar_rad_v)

    # Compute the vehicle displacement through the water, based on the hydro model horizontal speed and hydro model glide angle
    east_displacement_m_v = cm2m * east_speed_cm_s_v * delta_time_s_v
    north_displacement_m_v = cm2m * north_speed_cm_s_v * delta_time_s_v
    east_displacement_m = sum(east_displacement_m_v)
    north_displacement_m = sum(north_displacement_m_v)
    displacement_m = sum(
        np.sqrt(east_displacement_m_v**2 + north_displacement_m_v**2)
    )  # total displacement
    log_debug(
        "%s: north_displacement_m = %f, east_displacement_m = %f"
        % (tag, north_displacement_m, east_displacement_m)
    )
    log_debug("%s: displacement_m = %f" % (tag, displacement_m))

    east_average_speed_m_s = east_displacement_m / total_dive_time_s
    north_average_speed_m_s = north_displacement_m / total_dive_time_s
    # if False:  # DEBUG
    #     try:
    #         average_horizontal_bearing_deg = 90.0 - math.degrees(
    #             math.atan2(north_average_speed_m_s, east_average_speed_m_s)
    #         )
    #     except ZeroDivisionError:  # atan2
    #         average_horizontal_bearing_deg = 0.0
    #     if average_horizontal_bearing_deg < 0:
    #         average_horizontal_bearing_deg = average_horizontal_bearing_deg + 360.0
    #     average_horizontal_speed_m_s = np.sqrt(
    #         east_average_speed_m_s * east_average_speed_m_s
    #         + north_average_speed_m_s * north_average_speed_m_s
    #     )
    #     log_debug(
    #         "%s: average_horizontal_bearing_deg = %f"
    #         % (tag, average_horizontal_bearing_deg)
    #     )
    #     log_debug(
    #         "%s: average_horizontal_speed_m_s = %f"
    #         % (tag, average_horizontal_speed_m_s)
    #     )
    #     # return these? average_horizontal_speed_m_s, average_horizontal_bearing_deg

    return (
        east_displacement_m_v,
        north_displacement_m_v,
        east_displacement_m,
        north_displacement_m,
        east_average_speed_m_s,
        north_average_speed_m_s,
    )


# pylint: disable=unused-argument
def compute_dac(
    north_displacement_m_v,
    east_displacement_m_v,
    north_displacement_m,
    east_displacement_m,
    dive_delta_GPS_lat_m,
    dive_delta_GPS_lon_m,
    total_flight_and_SM_time_s,
):
    # We assume a local co-ordinate system with the origin GPS2
    # Then calculate the diff between GPS_last lat/lon (in m) and model east/north (in m)
    # depth-averaged current is this displacment divided by the dive time

    dac_north_displacement_m = dive_delta_GPS_lat_m - north_displacement_m
    dac_east_displacement_m = dive_delta_GPS_lon_m - east_displacement_m
    dac_north_speed_m_s = dac_north_displacement_m / total_flight_and_SM_time_s
    dac_east_speed_m_s = dac_east_displacement_m / total_flight_and_SM_time_s

    # if False:  # DEBUG
    #     dac_north_speed_cm_s = m2cm * dac_north_speed_m_s
    #     dac_east_speed_cm_s = m2cm * dac_east_speed_m_s
    #     dac_speed_cm_s = (
    #         m2cm
    #         * math.sqrt(
    #             dac_north_displacement_m * dac_north_displacement_m
    #             + dac_east_displacement_m * dac_east_displacement_m
    #         )
    #         / total_flight_and_SM_time_s
    #     )
    #     try:
    #         dac_polar_rad = math.atan2(
    #             dac_north_displacement_m, dac_east_displacement_m
    #         )
    #         dac_current_direction_deg = 90.0 - math.degrees(dac_polar_rad)
    #     except ZeroDivisionError:  # atan2
    #         dac_current_direction_deg = 0.0

    #     if dac_current_direction_deg < 0:
    #         dac_current_direction_deg = dac_current_direction_deg + 360.0

    #     log_debug(
    #         "dac_speed_cm_s = %f, dac_current_direction_deg = %f"
    #         % (dac_speed_cm_s, dac_current_direction_deg)
    #     )
    #     log_debug("dac_polar_rad = %f" % dac_polar_rad)
    #     log_debug(
    #         "dac_north_displacement_m = %f, dac_east_displacement_m = %f"
    #         % (dac_north_displacement_m, dac_east_displacement_m)
    #     )
    #     log_debug(
    #         "dac_north_speed_cm_s = %f, dac_east_speed_cm_s = %f"
    #         % (dac_north_speed_cm_s, dac_east_speed_cm_s)
    #     )

    return (dac_east_speed_m_s, dac_north_speed_m_s)


def compute_lat_lon(
    dac_east_speed_m_s,
    dac_north_speed_m_s,
    GPS2_lat_dd,
    GPS2_lon_dd,
    east_displacement_m_v,
    north_displacement_m_v,
    delta_time_s_v,
    dive_mean_lat_factor,
):
    # Calculate the lat/lon for each sample

    # Convert the DAC to polar co-ords to get the magntitude and direction
    # For each sample point, add the model displacement and the DAC displacement to get the adjusted displacement
    # Then run through the updated displacements and produce the lat/lon, with a running current position - final value should be GPS last

    north_corr_displacement_m_v = north_displacement_m_v + (
        dac_north_speed_m_s * delta_time_s_v
    )
    east_corr_displacement_m_v = east_displacement_m_v + (
        dac_east_speed_m_s * delta_time_s_v
    )
    # Use incremental trapezoidal integration of displacements to compute lat/lon dive positions from base location
    north_corr_displacement_m_v = scipy.integrate.cumulative_trapezoid(
        north_corr_displacement_m_v, initial=0.0
    )
    east_corr_displacement_m_v = scipy.integrate.cumulative_trapezoid(
        east_corr_displacement_m_v, initial=0.0
    )

    dive_pos_lat_dd_v = GPS2_lat_dd + (north_corr_displacement_m_v / m_per_deg)
    dive_pos_lon_dd_v = GPS2_lon_dd + (
        east_corr_displacement_m_v / (m_per_deg * dive_mean_lat_factor)
    )
    lon_np = len(dive_pos_lon_dd_v)
    # Moving from western hemisphere to eastern hemisphere?
    hemi_i_v = [i for i in range(lon_np) if dive_pos_lon_dd_v[i] > 180.0]
    dive_pos_lon_dd_v[hemi_i_v] -= 360.0
    # Moving from eastern hemisphere to western hemisphere?
    hemi_i_v = [i for i in range(lon_np) if dive_pos_lon_dd_v[i] < -180.0]
    dive_pos_lon_dd_v[hemi_i_v] += 360.0

    return (dive_pos_lat_dd_v, dive_pos_lon_dd_v)


def compute_kistler_pressure(kistler_cnf, log_f, counts_v, temp_v):
    """Compute pressure [psi] based on counts, the ADC details, and the prevailing temperature
    using a quadratic Kistler calibration. Do not attempt to tare to sealevel; responsibility of caller
    """
    # Set up default values for truck ADC, which the cnf might supply as an override
    default_values = {
        "internal_gain": 1.0,
        "AD_counts": 16777215.0,
        "glider_refV": 2.495,
        "cal_temperature": 25.0,
    }

    for var, default_value in list(default_values.items()):
        try:
            default_value = kistler_cnf[var]  # override?
        except KeyError:
            kistler_cnf[var] = default_value  # missing so assert default
    # Compute ADC counts_per_mVpV, since the Kistler calibration converts mV to psi
    try:
        counts_per_mVpV = kistler_cnf["counts_per_mVpV"]
    except KeyError:
        try:
            glider_V_supply = 5.0
            # [V]
            kistler_V_supply = 10.0
            # [V]
            V_per_mV = 1.0 / 1000.0

            gain = kistler_cnf["internal_gain"] * float(log_f.data["$AD7714Ch0Gain"])
            cnts_per_volt = kistler_cnf["AD_counts"] / kistler_cnf["glider_refV"]
            counts_per_mVpV = (
                gain
                * (glider_V_supply / kistler_V_supply)
                * cnts_per_volt
                * V_per_mV
                * kistler_V_supply
            )  # [counts/(mV/V)] (sensor output is in mV/V)
            kistler_cnf["counts_per_mVpV"] = counts_per_mVpV  # cache it
        except KeyError as e:
            raise RuntimeError(
                "Unable to compute counts per mV for Kistler conversion"
            ) from e

    x = counts_v / counts_per_mVpV  # mV
    x2 = x * x
    temp_diff = temp_v - kistler_cnf["cal_temperature"]
    temp_diff2 = temp_diff * temp_diff
    try:
        press_v = (
            kistler_cnf["A1"]
            + kistler_cnf["A2"] * x
            + kistler_cnf["A3"] * x2
            + kistler_cnf["A4"] * temp_diff
            + kistler_cnf["A5"] * x * temp_diff
            + kistler_cnf["A6"] * x2 * temp_diff
            + kistler_cnf["A7"] * temp_diff2
            + kistler_cnf["A8"] * x * temp_diff2
            + kistler_cnf["A9"] * x2 * temp_diff2
        )
    except KeyError:
        try:
            # Old style conversion from calsheet (prior to 2016)
            # assumes you always supply p_span as 1500 or 10000 depending on the model (DG, or not)
            xo_T = (
                kistler_cnf["x_o_ref"]
                + kistler_cnf["xot1"] * temp_diff
                + kistler_cnf["xot2"] * temp_diff2
            )
            xs_T = (
                kistler_cnf["x_s_ref"]
                + kistler_cnf["xst1"] * temp_diff
                + kistler_cnf["xst2"] * temp_diff2
            )
            press_linear_psi = kistler_cnf["p_span"] * (x - xo_T) / (xs_T - xo_T)
            press_quad_psi = kistler_cnf["x2"] * (x2 + xo_T * xs_T + x * (xo_T + xs_T))
            press_v = press_linear_psi + press_quad_psi
            # psi
        except KeyError as e:
            raise RuntimeError(
                "Unable to find conversion parameters for Kistler conversion"
            ) from e

    # deliberately NOT adding PRESSURE_YINT
    return press_v  # [psi]


def correct_heading(
    compass_name,
    globals_d,
    magcal_filename,
    magcal_variable,
    magcalfile_root_name,
    mission_dir,
    Mx,
    My,
    Mz,
    head,
    pitch,
    roll,
    pitchAD,
):
    """corrects compass heading based on mag data

    Input:
        magcal_filename
        magcal_variable
        Mx, My, Mz, pitch, roll
        pitchAD
    Output:
        new_head - Updated headings, None if update could not be performed
                   Note: None is not an error condition - the logfile should be consulted for any actual processing
                   errors
    SideEffects:
        Modifies globals_d with new contents of the magacal_filename, if appropriate
    """

    contents = new_contents = abc = pqrc = None

    # Since we have the original mag xyz data and head was derived using the previous cal coefficients
    # we are free to update stored headings with our new guess.

    # Look up any old contents to recompute if we didn't save the results
    try:
        contents = globals_d[magcal_variable]  # old version?
    except KeyError:
        pass
    else:
        (abc, pqrc) = BaseMagCal.parseMagCal(contents)
        if abc is None or pqrc is None:
            log_warning(
                "Previously stored contents not parseable - ignoring", alert="MAGCAL"
            )  # parseMagCal already complained about parsing
            globals_d[magcal_variable] = None
            contents = abc = pqrc = None

    # Search for a recently uploaded version?

    if magcal_filename and magcal_filename.lower() == "search":
        magcal_filename = Utils.find_recent_basestation_file(
            mission_dir, magcalfile_root_name, True
        )

    # correction requested - override
    if magcal_filename:  # they want to supply or override any contents
        if not os.path.exists(magcal_filename):
            log_warning(
                "MagCalFile %s does not exist" % magcal_filename, alert="MAGCAL"
            )
        else:
            new_contents = BaseMagCal.readMagCalFile(magcal_filename)
            if new_contents is not None:
                (new_abc, new_pqrc) = BaseMagCal.parseMagCal(new_contents)
                if new_abc is None or new_pqrc is None:
                    log_warning(
                        "Ignoring contents of %s" % magcal_filename, alert="MAGCAL"
                    )
                    new_contents = None
                else:
                    globals_d[magcal_variable] = new_contents
                    abc = new_abc
                    pqrc = new_pqrc

    if new_contents is not None:
        log_info("Using contents of %s to correct heading" % magcal_filename)
    elif contents is not None:
        log_info(
            "Correcting heading using previously-stored %s calibration data"
            % compass_name
        )
    else:
        log_warning("Not correcting %s heading" % compass_name)
        return None

    np_pts = len(Mx)

    # In case this is a DG, get the pitchAD info
    new_head = np.zeros(np_pts)
    for ii in range(np):
        new_head[ii] = BaseMagCal.compassTransform(
            abc,
            pqrc,
            pitchAD[ii] if pitchAD is not None else None,
            roll[ii],
            pitch[ii],
            (Mx[ii], My[ii], Mz[ii]),
        )
        # sys.stdout.write("%.2f %.2f\n" % (heading[i], new_head[i]))
    if new_contents is not None:
        # report RMS value only when the cal data changed
        delta_head_v = head - new_head
        hemi_i_v = [i for i in range(np_pts) if delta_head_v[i] > 180.0]
        delta_head_v[hemi_i_v] -= 360.0
        hemi_i_v = [i for i in range(np_pts) if delta_head_v[i] < -180.0]
        delta_head_v[hemi_i_v] += 360.0
        rms = np.sqrt(np.mean(delta_head_v**2))
        log_info(
            "Reported %s heading vs corrected heading RMS: %f" % (compass_name, rms)
        )
        # SyntaxError: "can not delete variable 'delta_head_v' referenced in nested scope"
        # del hemi_i_v, delta_head_v
        del hemi_i_v

    return new_head


# TODO:
# If any of the NODC.cnf files are changed, the globals could be out of date
# We don't have a mode where we simply update the files for that reason
# but perhaps the future NODC.py system that ships data will handle that bit
# In the meantime, --force is your friend
def load_dive_profile_data(
    base_opts,
    ignore_existing_netcdf,
    nc_dive_file_name,
    eng_file_name=None,
    log_file_name=None,
    sg_calib_file_name=None,
    logger_eng_files=None,
    apply_sg_config_constants=True,
):
    """Load most-recent data from the appropriate sounrces, if possible

    Input:
    base_opts - the base options structure
    ignore_existing_netcdf - if the netCDF file exists, its contents will be ignored
    nc_dive_file_name - fully qualifed path to NetCDF file (required)
    eng_file_name - fully qualifed path to eng file (optional)
    log_file_name - fully qualifed path to log file (optional)
    sg_calib_file_name - fully qualified path to sg_calib_file (optional)
    logger_eng_files - a list of files to read for logger eng files, if any (WHY?)
    apply_sg_config_constants - whether to add the defaults to calib_consts[]

    Returns:
    Status - 0 - needed raw data unavailable, 1 - all raw data and results up-to-date, 2 - some raw data updated; results need updating
    globals_d - a dictionary of globals, always scalar
    log_f - a log structure
    eng_f - an eng structure
    calib_consts - calibration constants dictionary
    results_d - a dictionary of derived results, or None if needs recomputation
    directives - an instance of ProfileDirectives appropriate for this dive
    nc_info_d - information on dimension names and sizes
    instruments_d - information on instruments used for each vector variable, if any

    Raises:
    None
    """
    # set up logging

    log_debug(
        "load_dive_profile_data,ignore_existing_netcdf:%s,nc_dive_file_name:%s,eng_file_name:%s,log_file_name:%s,sg_calib_file_name:%s,logger_eng_files:%s"
        % (
            nc_dive_file_name,
            ignore_existing_netcdf,
            eng_file_name,
            log_file_name,
            sg_calib_file_name,
            logger_eng_files,
        )
    )

    log_debug("Processing %s" % nc_dive_file_name)

    status = 0  # assume we have issues loading data
    drv_file_name = os.path.join(base_opts.mission_dir, "sg_directives.txt")
    # make these file entries look like they came from Sensors
    file_table = {
        "ncf": [[{"file_name": nc_dive_file_name}], True, 0, None, False],
        "log": [[{"file_name": log_file_name}], True, 0, None, True],
        "eng": [[{"file_name": eng_file_name}], True, 0, None, True],
        "sgc": [[{"file_name": sg_calib_file_name}], True, 0, None, True],
        "drv": [[{"file_name": drv_file_name}], True, 0, None, False],
    }
    # BUG: If for some reason you have scicon or tmicl or other sensor data (in the nc file)
    # but you don't have the original eng files locally we don't get those in the logger_eng_files
    # list, obviously.  But if you happen to have the eng, log, and sgc files above
    # we think there is nothing else needed.  And then if you ignore_existing_netcdf then
    # we think we can get all the data from those files only and then lose later, typically
    # because there is no CT data.  This happens if you --force MakeDiveProfiles
    # MORAL: Make sure you don't have that partial set of raw files around...
    if logger_eng_files:
        for lf in logger_eng_files:
            try:
                eng_file_reader = lf["eng_file_reader"]
                for sensor in list(lf["eng_files"].keys()):
                    # file_table[sensor] = [lf['eng_files'][sensor], True, 0, eng_file_reader,True]
                    file_table["%s_%s" % (lf["logger_prefix"], sensor)] = [
                        lf["eng_files"][sensor],
                        True,
                        0,
                        eng_file_reader,
                        True,
                    ]
            except KeyError:
                pass  # no files or no reader

    missing_files = []  # files required for reload
    for file_type, file_info in list(file_table.items()):
        (
            file_names,
            file_exists,
            file_time,
            eng_file_reader,
            required_for_reload,
        ) = file_info
        for file_entry in file_names:
            file_name = file_entry["file_name"]
            if file_name:
                file_exists = file_exists and os.path.exists(file_name)
                if file_exists:
                    file_time = max(file_time, os.path.getmtime(file_name))
                else:
                    if required_for_reload:
                        missing_files.append(file_name)
            else:
                file_exists = False
        file_table[file_type] = [
            file_names,
            file_exists,
            file_time,
            eng_file_reader,
            required_for_reload,
        ]

    _, drv_file_exists, drv_file_time, _, _ = file_table["drv"]
    _, eng_file_exists, eng_file_time, _, _ = file_table["eng"]
    _, log_file_exists, log_file_time, _, _ = file_table["log"]
    _, sgc_file_exists, sgc_file_time, _, _ = file_table["sgc"]
    _, ncf_file_exists, ncf_file_time, _, _ = file_table["ncf"]

    try:  # RuntimeError
        load_from_nc = True
        if ignore_existing_netcdf:
            # If all the original files are available, skip nc file rebuild from originals only.  Else recompute from nc and whatever files are around.
            if len(missing_files):
                # raise RuntimeError, "Missing files to ignore_existing_netcdf %s - skipping %s" % (missing_files, nc_dive_file_name)
                log_warning(
                    "Missing %s; rebuilding from data in %s"
                    % (missing_files, nc_dive_file_name)
                )
            else:
                ncf_file_exists = (
                    False  # ignore the file -- force reload from raw files
                )

        if not ncf_file_exists:
            load_from_nc = False  # skip loading from an NC file
            ncf_file_time = 0  # ensure we load from other files
            if len(missing_files):
                # we could have been called with just an nc file to load
                # and all/some other files None, which is not an error per se
                log_error("Missing data files: %s - bailing out" % missing_files)
                raise RuntimeError(True)

            log_info("Loading data from original files")

        # If we get here we think we can load data from variaus sources
        log_f = None
        calib_consts = {}
        globals_d = {}
        results_d = {}
        nc_info_d = {}
        instruments_d = {}
        dive_num = FileMgr.get_dive(
            nc_dive_file_name if ncf_file_exists else log_file_name
        )
        directives = QC.ProfileDirectives(base_opts.mission_dir, dive_num)
        if ncf_file_exists and load_from_nc:
            nc_file_parsable = True  # assume the best
            try:
                dive_nc_file = Utils.open_netcdf_file(nc_dive_file_name, "r")
                # When handling type mismatches (see nc_var_convert code below), we need to create a new
                # temporary nc_var.  netCDF3 from scipy, allowed this to be done in a file opened read-ony - for
                # netCDF4, we use a diskless dataset and create it here because netCDF4 does not allow multiple diskless
                # files of the same name to be opened.
                dive_nc_file_temp = netCDF4.Dataset(
                    nc_dive_file_name, "w", diskless=True
                )
                try:
                    version = dive_nc_file.file_version
                except Exception:
                    version = 1.0
                if isinstance(version, bytes):
                    version = version.decode("utf-8")
                if not isinstance(version, str):
                    # Old file; convert to string
                    version = "%.02f" % version
                if Utils.normalize_version(version) < Utils.normalize_version(
                    Globals.required_nc_fileversion
                ):
                    log_error(
                        "%s is a version %s netCDF file - this basestation requires %s or later"
                        % (
                            nc_dive_file_name,
                            version,
                            Globals.required_nc_fileversion,
                        )
                    )
                    dive_nc_file.close()  # close the file
                    nc_file_parsable = False  # can't really trust our inversion scheme so re-read from raw files
                    status = 0  # unable to read
                if Utils.normalize_version(version) < Utils.normalize_version(
                    Globals.mission_per_dive_nc_fileversion
                ):
                    log_info(
                        "%s is a version %s netCDF file - requires updating to %s"
                        % (
                            nc_dive_file_name,
                            version,
                            Globals.mission_per_dive_nc_fileversion,
                        )
                    )
                    status = 2  # requires update
                else:
                    status = 1  # looks up-to-date
            except Exception:  # can't open file
                log_error("Unable to open %s" % nc_dive_file_name, "exc")
                nc_file_parsable = False
                ncf_file_exists = False
                ncf_file_time = 0

            if nc_file_parsable:
                log_debug("Reloading data from %s" % nc_dive_file_name)
                # reload and initialize from nc file
                # this will contain the last gc and gps arrays
                log_f = LogFile.LogFile()
                log_f.data = {}
                log_f.gc_data = {}
                log_f.tc_data = {}
                # Initialize in case this is an old version nc file
                log_f.gc_state_data = {"secs": [], "state": [], "eop_code": []}
                eng_f = DataFiles.DataFile("eng", None)
                eng_cols = []
                eng_data = []

                sgc_var = re.compile("^%s" % BaseNetCDF.nc_sg_cal_prefix)
                log_var = re.compile("^%s" % BaseNetCDF.nc_sg_log_prefix)
                eng_var = re.compile("^%s" % BaseNetCDF.nc_sg_eng_prefix)
                gc_var = re.compile("^%s" % BaseNetCDF.nc_gc_prefix)
                gc_state_var = re.compile("^%s" % BaseNetCDF.nc_gc_state_prefix)
                gc_msg_var = re.compile("^%s" % BaseNetCDF.nc_gc_msg_prefix)
                tc_var = re.compile("^%s" % BaseNetCDF.nc_tc_prefix)

                for global_var in list(
                    BaseNetCDF.nc_global_variables.keys()
                ):  # see comment in BaseNetCDF.py about dir(dive_nc_file):
                    try:
                        globals_d[global_var] = getattr(dive_nc_file, global_var)
                    except Exception:
                        pass  # optional variable
                    else:
                        if isinstance(globals_d[global_var], bytes):
                            globals_d[global_var] = globals_d[global_var].decode(
                                "utf-8"
                            )

                # Reconstitute the header information from globals
                # these globals are always available on later versions
                start_ts = globals_d["start_time"]
                eng_f.start_ts = time.gmtime(start_ts)
                log_f.start_ts = eng_f.start_ts
                log_f.version = globals_d["seaglider_software_version"]
                eng_f.version = log_f.version
                log_f.mission = globals_d["mission"]
                eng_f.mission = log_f.mission
                log_f.glider = globals_d["glider"]
                eng_f.glider = log_f.glider
                log_f.dive = globals_d["dive_number"]
                eng_f.dive = log_f.dive

                # IMPORTANT NOTE: if we don't .copy() all vectors then when we (re)open the nc file for write below
                # the underlying data is mapped out and crashes python and the debugger!
                # (This is critical for raw data that is retained by the caller; not so much for results, etc. that are rebuilt)
                for dive_nc_varname, nc_var in list(dive_nc_file.variables.items()):
                    # Deal with timeouts from the truck eng file
                    if dive_nc_varname.endswith("timeouts_times_truck"):
                        cls = dive_nc_varname.split("_", 1)[0]
                        eng_f.timeouts_times[cls] = nc_var[:].tobytes().decode("utf-8")
                        continue
                    if dive_nc_varname.endswith("timeouts_truck"):
                        cls = dive_nc_varname.split("_", 1)[0]
                        eng_f.timeouts[cls] = nc_var[0]
                        continue

                    # scipy version: nc_typecode = nc_var.typecode()
                    nc_typecode = NetCDFUtils.typecode_mapper(nc_var.dtype)
                    nc_string = nc_typecode == "c"
                    nc_is_scalar = len(nc_var.shape) == 0  # treat strings as scalars
                    nc_dims = (
                        nc_var.dimensions
                    )  # tuple of dim_names ('sg_data_point',) or ()
                    l_nc_dims = len(nc_dims)
                    try:
                        md = BaseNetCDF.nc_var_metadata[dive_nc_varname]
                    except KeyError:
                        # This variable/data came from a prior version of the basestation
                        # where the metadata was created at least once before, perhaps in the dim past.
                        # Preserve any attributes.  At worst complain under debug that a variable wasn't predeclared before
                        # but that could be because a sensor cnf, extension, or scicon eng file isn't available locally.
                        # We also preserve the data and pass it along without complaint.
                        attributes = {}
                        # pylint: disable=protected-access
                        if getattr(nc_var, "_attributes", False):
                            for key, value in list(nc_var._attributes.items()):
                                attributes[key] = value
                        # pylint: enable=protected-access
                        if nc_is_scalar or nc_string:
                            # Let caller complain if they can't handle this scalar...
                            # This often happens with sg_cal variables.  We provide a default entry
                            # NOTE: create_nc_var makes a similar complaint but also writes them.
                            log_debug(
                                "Undeclared scalar variable %s of type %s"
                                % (dive_nc_varname, nc_typecode)
                            )
                            # this will add it to the appropriate datastructure below depending on prefix
                            md = BaseNetCDF.form_nc_metadata(
                                None,
                                nc_data_type=nc_typecode,
                                meta_data_d=attributes,
                            )  # treat as a scalar
                        else:
                            log_debug(
                                "Metadata for variable %s%s was not pre-declared"
                                % (dive_nc_varname, nc_dims)
                            )
                            nc_dim_infos = ()
                            for nc_sensor_mdp_dim in nc_dims:
                                if nc_sensor_mdp_dim in list(
                                    BaseNetCDF.nc_mdp_data_info.values()
                                ):
                                    # find the associated info for this dimension
                                    for info, dim in list(
                                        BaseNetCDF.nc_mdp_data_info.items()
                                    ):
                                        if nc_sensor_mdp_dim == dim:
                                            nc_sensor_mdp_info = info
                                            break
                                else:
                                    # make one up and register it...this can happen if you are reading an nc file
                                    # and the dimension was created on the fly from a sensor that needed to look at its eng file
                                    nc_sensor_mdp_info = "%s_info" % nc_sensor_mdp_dim
                                    log_debug(
                                        "%s: %s assigned to %s"
                                        % (
                                            dive_nc_varname,
                                            nc_sensor_mdp_dim,
                                            nc_sensor_mdp_info,
                                        )
                                    )
                                    BaseNetCDF.register_sensor_dim_info(
                                        nc_sensor_mdp_info,
                                        nc_sensor_mdp_dim,
                                        None,
                                        True,
                                        None,
                                    )  # No clue about time var
                                nc_dim_infos = nc_dim_infos + (nc_sensor_mdp_info,)
                            # Don't include in MMT/MMP
                            md = BaseNetCDF.form_nc_metadata(
                                None, False, nc_typecode, attributes, nc_dim_infos
                            )
                        # if we make it here, intern the created md, which will silence on write
                        BaseNetCDF.nc_var_metadata[dive_nc_varname] = md

                    (
                        _,
                        nc_data_type,
                        _,
                        mdp_dim_info,
                    ) = md
                    log_debug(
                        "Processing %s%s (%s)" % (dive_nc_varname, nc_dims, nc_typecode)
                    )
                    # NOTE: Every time we skip a variable below it is lost if we rewrite the nc file.  If it is a bit of raw data
                    # this violates the stricture that all raw data is preserved.  The only recourse is to rebuild from the original files
                    # with an updated basestation
                    if nc_typecode != nc_data_type:
                        if (
                            (nc_data_type == "Q" and nc_typecode == "c")
                            or (  # QC vectors are encoded as strings
                                nc_data_type == "d" and nc_typecode == "i"
                            )
                        ):  # netcdf/numpy handles i to d conversion (e.g., gc_pitch_ad was i, now d)
                            pass
                        else:
                            # We have an expected type mismatch we can't deal with easily...
                            # When we 'upgrade' a log parameters (e.g., $MEM) from a double to a string because of extra members, we need to convert types
                            # Also, if we define new log parameters but don't declare them, they are saved as strings and later we may need to convert them
                            # This works for scalars only...
                            nc_var_convert = None
                            if len(mdp_dim_info) == 0:  # scalar?
                                if nc_typecode == "c" and nc_data_type in [
                                    "d",
                                    "i",
                                ]:  # convert string to single scalar
                                    try:
                                        nc_dims = mdp_dim_info
                                        nc_var_convert = (
                                            dive_nc_file_temp.createVariable(
                                                dive_nc_varname,
                                                nc_data_type,
                                                nc_dims,
                                            )
                                        )
                                        convert_f = (
                                            float if nc_data_type == "d" else int
                                        )
                                        # this can fail if you have a string like '1234,5678,9012' etc.
                                        nc_var_convert.assignValue(
                                            convert_f(
                                                nc_var[:].tobytes().decode("utf-8")
                                            )
                                        )
                                        log_debug(
                                            "Converted %s from '%s' to '%s'"
                                            % (
                                                dive_nc_varname,
                                                nc_typecode,
                                                nc_data_type,
                                            )
                                        )
                                    except Exception:
                                        log_error(
                                            "Failed to convert %s from string '%s' to type '%s'"
                                            % (
                                                dive_nc_varname,
                                                nc_var[:].tostring(),
                                                nc_data_type,
                                            ),
                                            "exc",
                                        )
                                        nc_var_convert = None  # oh well...

                                elif (
                                    nc_typecode in ["d", "i"] and nc_data_type == "c"
                                ):  # convert a scalar to a string
                                    try:
                                        value_string = "%g" % nc_var.getValue().item()
                                        l_value_string = len(value_string)
                                        dim_name = "__%s_convert" % dive_nc_varname
                                        nc_dims = (dim_name,)
                                        dive_nc_file_temp.createDimension(
                                            dim_name, l_value_string
                                        )
                                        nc_var_convert = (
                                            dive_nc_file_temp.createVariable(
                                                dive_nc_varname,
                                                nc_data_type,
                                                nc_dims,
                                            )
                                        )
                                        nc_var_convert[:] = value_string
                                        log_debug(
                                            "Converted %s from type '%s' to a string"
                                            % (dive_nc_varname, nc_typecode)
                                        )
                                    except Exception:
                                        log_error(
                                            "Failed to convert %s from %g to a string"
                                            % (
                                                dive_nc_varname,
                                                nc_var.getValue().item(),
                                            ),
                                            "exc",
                                        )
                                        nc_var_convert = None  # oh well...

                            # Need to compare against None because netCDF4 singletons do not have a len() attribute
                            if (
                                nc_var_convert is not None
                            ):  # were we able to coerce to a new variable?
                                # reset these variables to reflect the new variable
                                nc_typecode = nc_data_type
                                nc_string = nc_typecode == "c"
                                l_nc_dims = len(nc_dims)
                                nc_var = nc_var_convert  # use this new nc_var below
                            else:
                                # Must rebuild the file from the original log/eng files
                                log_error(
                                    "Expecting %s as type for %s but got %s -- skipping"
                                    % (nc_data_type, dive_nc_varname, nc_typecode)
                                )
                                continue  # drop it

                    if mdp_dim_info:
                        # Special case - if this an array of strings, eliminate the string
                        # dimension and proceed
                        if l_nc_dims > 1 and nc_dims[1].startswith("string_"):
                            nc_dims = (nc_dims[0],)
                            l_nc_dims -= 1

                        if l_nc_dims != len(mdp_dim_info):
                            log_error(
                                "Expecting %s as dimensions for %s but got %s -- skipping"
                                % (mdp_dim_info, dive_nc_varname, nc_dims)
                            )
                            continue  # drop it

                        # NOTE: this dim name could be different from what was registered (pre-declared)
                        # because, e.g., some scicon data was not pre-declared, we wrote with made up dim_names
                        # then later it was pre-declared and now we are reading that old nc file, which wasn't re-made
                        # The problem is the order in which variables are presented from the nc file is random
                        # so there is no way to know which given nc dim name from the file is the 'right' one to use
                        # FIX: If it is a data info we can see if the name matches and if not, use the default instead?? else punt
                        for dim in range(l_nc_dims):
                            # likely neeeds .size method
                            this_dim = nc_dims[dim]
                            this_mdi = mdp_dim_info[dim]
                            if this_mdi in BaseNetCDF.nc_data_infos:
                                default_dim = BaseNetCDF.nc_mdp_data_info[this_mdi]
                                if this_dim != default_dim:
                                    log_warning(
                                        "Reassigning %s dimension from %s to %s"
                                        % (dive_nc_varname, this_dim, default_dim)
                                    )
                                    this_dim = default_dim
                                    status = (
                                        2  # force reconstruction with new dim names
                                    )
                            else:
                                pass  # punt (warn?)
                            BaseNetCDF.assign_dim_info_dim_name(
                                nc_info_d, this_mdi, this_dim
                            )
                            BaseNetCDF.assign_dim_info_size(
                                nc_info_d,
                                this_mdi,
                                dive_nc_file.dimensions[this_dim].size,
                            )
                    elif l_nc_dims:  # expecting no array (BaseNetCDF.nc_scalar) but we have an array...
                        if nc_data_type not in ["c", "Q"]:  # ignore strings
                            log_error(
                                "Expecting a scalar for %s but got %s -- skipping"
                                % (dive_nc_varname, nc_dims)
                            )
                            continue  # drop it

                    if sgc_var.search(dive_nc_varname):
                        _, variable = sgc_var.split(dive_nc_varname)
                        if nc_is_scalar:
                            calib_consts[variable] = nc_var.getValue().item()
                        else:  # nc_string
                            calib_consts[variable] = (
                                nc_var[:].tobytes().decode("utf-8")
                            )  # string comments

                    elif log_var.search(dive_nc_varname):
                        if dive_nc_varname in [
                            "log_gps_lat",
                            "log_gps_lon",
                            "log_gps_time",
                            "log_gps_first_fix_time",
                            "log_gps_final_fix_time",
                            "log_gps_hdop",
                            "log_gps_magvar",
                            "log_gps_driftspeed",
                            "log_gps_driftheading",
                            "log_gps_n_satellites",
                            "log_gps_hpe",
                            "log_gps_qc",
                        ]:
                            # move these arrays to results_d, not log_f
                            results_d[dive_nc_varname] = nc_var[
                                :
                            ].copy()  # always an array
                            continue
                        # Restore log_f.table
                        elif any(
                            [ii.search(dive_nc_varname) for ii in LogFile.table_vars]
                        ):
                            for ss in LogFile.table_vars:
                                param_name = ss.pattern[1:]
                                if dive_nc_varname.startswith(param_name):
                                    col_name_i = (
                                        dive_nc_varname.find(param_name)
                                        + len(param_name)
                                        + 1
                                    )
                                    col_name = dive_nc_varname[col_name_i:]
                                    if len(nc_var.shape) > 1 and nc_var.dimensions[
                                        1
                                    ].startswith("string_"):
                                        log_f.tables[param_name][col_name] = (
                                            netCDF4.chartostring(nc_var[:])
                                        )
                                    else:
                                        log_f.tables[param_name][col_name] = nc_var[
                                            :
                                        ].copy()
                                    break
                            continue
                        _, variable = log_var.split(dive_nc_varname)
                        variable = "$" + variable  # restore leading parameter character
                        # log_info(variable) # DEBUG when unknown variables fail to load
                        if nc_data_type == "c" or nc_string:
                            value = nc_var[:].tobytes().decode("utf-8")
                            # deal w/ GPS strings
                            if variable in ["$GPS1", "$GPS2", "$GPS"]:
                                value = GPS.GPSFix(
                                    value,
                                    start_date_str=time.strftime(
                                        "%m %d %y", eng_f.start_ts
                                    ),
                                )
                        else:  # 'd' or 'i'
                            try:
                                value = nc_var.getValue().item()
                            except Exception:
                                DEBUG_PDB_F()
                                log_error(
                                    f"Problem retrieving {dive_nc_varname}", "exc"
                                )
                                continue
                        log_f.data[variable] = value

                    # Parse for gc_state_ vars before gc_ vars since they share a prefix
                    elif gc_state_var.search(dive_nc_varname):
                        _, col_name = gc_state_var.split(dive_nc_varname)
                        log_f.gc_state_data[col_name] = nc_var[
                            :
                        ].copy()  # always an array

                    elif gc_msg_var.search(dive_nc_varname):
                        _, msg_col_name = gc_msg_var.split(dive_nc_varname)
                        msg, col_name = msg_col_name.split("_", 1)
                        if msg not in log_f.gc_msg_dict:
                            log_f.gc_msg_dict[msg] = {}
                        log_f.gc_msg_dict[msg][col_name] = nc_var[
                            :
                        ].copy()  # always an array

                    elif gc_var.search(dive_nc_varname):
                        _, col_name = gc_var.split(dive_nc_varname)
                        log_f.gc_data[col_name] = nc_var[:].copy()  # always an array

                    elif tc_var.search(dive_nc_varname):
                        _, col_name = tc_var.split(dive_nc_varname)
                        log_f.tc_data[col_name] = nc_var[:].copy()  # always an array

                    elif eng_var.search(dive_nc_varname):
                        # CONSIDER change eng reader to build columns as it goes and make a dictionary
                        _, col_name = eng_var.split(dive_nc_varname)
                        eng_cols.append(col_name)
                        eng_data.append(nc_var[:].copy())  # always an array
                        with contextlib.suppress(Exception):
                            instruments_d[dive_nc_varname] = nc_var.instrument.decode(
                                "utf-8"
                            )

                    else:
                        # must be another array or scalar
                        # put it on results
                        if nc_data_type == "Q":  # Handle QC encoding
                            # verify nc_typecode == 'c'
                            qc_v = nc_var[:]  # get the characters
                            results_d[dive_nc_varname] = QC.decode_qc(qc_v)
                            continue  # move on...

                        if dive_nc_varname == "directives":
                            directives.parse_string(nc_var[:].tobytes().decode("utf-8"))
                            continue

                        if nc_data_type == "c" or nc_string:
                            results_d[dive_nc_varname] = (
                                nc_var[:].tobytes().decode("utf-8")
                            )
                        elif nc_is_scalar:
                            results_d[dive_nc_varname] = nc_var.getValue().item()
                        else:
                            results_d[dive_nc_varname] = nc_var[:].copy()
                            with contextlib.suppress(Exception):
                                instruments_d[dive_nc_varname] = (
                                    nc_var.instrument.decode("utf-8")
                                )

                dive_nc_file.close()
                num_rows = len(eng_data)
                sg_np = len(eng_data[0])
                data = np.zeros((sg_np, num_rows), float)
                for i in range(num_rows):
                    for j in range(sg_np):
                        data[j][i] = eng_data[i][j]  # transpose
                # column order doesn't actually matter as long as they are in sync with data
                eng_f.data = data
                eng_f.columns = eng_cols
                # all done with these vars
                del data, eng_cols, eng_data
                # now see if we need to update the nc data from raw files

        # reload from original data or update nc data
        if sgc_file_exists and sgc_file_time > ncf_file_time:
            if ncf_file_time:
                log_debug("Updating variables from %s" % sg_calib_file_name)
            local_calib_consts = CalibConst.getSGCalibrationConstants(
                sg_calib_file_name,
                suppress_required_error=True,
                ignore_fm_tags=not base_opts.ignore_flight_model,
            )
            if not local_calib_consts:
                log_error("Could not process %s - bailing out " % sg_calib_file_name)
                raise RuntimeError(True)
            # Update non-None values from local into calib_consts from any nc file
            # None values occur as default values for required_keys but if we read values
            # for an nc file this permits using those values in the presence of a nearly-empty
            # sg_calib_constants.m file (e.g., it only has id_str, etc.)
            # The better alternative is to run write_sg_calib_constants_nc.m to prepare
            # an sg_calib_constants.m file from an nc file if you don't have one
            # This code shouldn't require it but sometimes old matlab code does require one
            for key, value in list(local_calib_consts.items()):
                if value is not None:
                    calib_consts[key] = value
            status = 2  # raw data changed; results need updating

        if log_file_exists and log_file_time > ncf_file_time:
            if ncf_file_time:
                log_debug("Updating data from %s" % log_file_name)
            log_f = LogFile.parse_log_file(log_file_name)
            if not log_f:
                log_error("Could not parse %s - bailing out" % log_file_name)
                raise RuntimeError(True)
            if "st_secs" not in log_f.gc_data:
                log_error("Could not find GC table in %s - bailing out" % log_file_name)
                raise RuntimeError(True)

            BaseNetCDF.assign_dim_info_size(
                nc_info_d, BaseNetCDF.nc_gc_event_info, len(log_f.gc_data["st_secs"])
            )

            # Any turn controller data?
            if log_f.tc_data:
                # TODO - replace with tc_time - not headingErr
                BaseNetCDF.assign_dim_info_size(
                    nc_info_d,
                    BaseNetCDF.nc_tc_event_info,
                    len(log_f.tc_data["rollDeg"]),
                )
            # Any table data?
            for param_name, col_values in log_f.tables.items():
                cols = list(col_values.keys())
                BaseNetCDF.assign_dim_info_size(
                    nc_info_d,
                    f"{BaseNetCDF.nc_sg_log_prefix}{param_name[1:]}_info",
                    len(log_f.tables[param_name][cols[0]]),
                )
            # any STATE data?
            if len(log_f.gc_state_data["secs"]) > 0:
                BaseNetCDF.assign_dim_info_size(
                    nc_info_d,
                    BaseNetCDF.nc_gc_state_info,
                    len(log_f.gc_state_data["secs"]),
                )
            if log_f.gc_msg_dict:  # Dimension any gc messages
                for msgtype, data_dict in log_f.gc_msg_dict.items():
                    nc_gc_message_dim_info = (
                        BaseNetCDF.nc_gc_msg_prefix + msgtype + "_info"
                    )
                    BaseNetCDF.assign_dim_info_size(
                        nc_info_d,
                        nc_gc_message_dim_info,
                        len(next(iter(data_dict.items()))[1]),
                    )

            BaseNetCDF.assign_dim_info_size(nc_info_d, BaseNetCDF.nc_gps_info_info, 3)
            # Add defaults only after possibly updating sg_calib_constants data
            status = 2  # raw data changed; results need updating

        if not log_f:
            # In the case of a corrupted nc file and no original files we won't have a log_f structure
            # at this point.  Unable to continue
            status = 0  # let caller know the bad news...
            log_error(
                "Could not determine log info for %s - bailing out" % nc_dive_file_name
            )
            raise RuntimeError(True)

        # At this point calib_consts[] contains just the explicitly set/stored variables from (past) sg_calib_constants.m files
        # Do this patch for old files and then see if we want to add the default values.
        try:
            # Older versions of the SBE43 corrections used PCor == 0 to signal the use of newer style correction
            # Don't bother using or reporting this variable to netcdf file.
            # Normally this check would be in Sensors/sbe43_ext.py but
            # we do this here just in case we die below we don't complain about missing metadata
            if calib_consts["PCor"] == 0:
                del calib_consts["PCor"]
        except KeyError:
            pass

        # NOTE: MDP does this step later on a copy of the explicit variables used for saving
        if apply_sg_config_constants:
            sg_config_constants(
                base_opts,
                calib_consts,
                getattr(log_f.data, "$DEEPGLIDER", 0),
                ("gpctd_time" in results_d),
            )  # supply defaults, calib_consts updated by side effect

        if eng_file_exists and eng_file_time > ncf_file_time:
            if ncf_file_time:
                log_debug("Updating data from %s" % eng_file_name)
            eng_f = DataFiles.process_data_file(eng_file_name, "eng", calib_consts)
            if not eng_f:
                log_error("Could not parse %s - bailing out" % eng_file_name)
                raise RuntimeError(True)
            status = 2  # raw data changed; results need updating
        else:
            # If the eng_f object was created before the calib_consts was reconstructed, apply it here
            # before the call to remap_engfile_columns
            eng_f.calib_consts = calib_consts

        # Write out timeouts
        # Note: the _obs are not written out as the time for the timeouts is
        for cls, timeouts in eng_f.timeouts.items():
            results_d[f"{cls}_timeouts_truck"] = timeouts
        for cls, times in eng_f.timeouts_times.items():
            results_d[f"{cls}_timeouts_times_truck"] = times

        # regardless of source, remap these column names
        eng_f.remap_engfile_columns()

        sg_np = len(eng_f.get_col(eng_f.columns[0]))
        BaseNetCDF.assign_dim_info_size(nc_info_d, BaseNetCDF.nc_sg_data_info, sg_np)
        for column in eng_f.columns:
            nc_var_name = BaseNetCDF.nc_sg_eng_prefix + column
            try:
                md = BaseNetCDF.nc_var_metadata[nc_var_name]
            except KeyError:
                log_error("Unknown nc metadata for %s in eng file" % column)
                continue  # skip!
            _, nc_data_type, _, mdp_dim_info = md
            # support different dimensions for different instruments (e.g., magnetomoter) in eng file
            # and assign the same size to each
            # We know eng file data only have a single dimension
            if mdp_dim_info[0] not in nc_info_d:
                BaseNetCDF.assign_dim_info_size(nc_info_d, mdp_dim_info[0], sg_np)

        if drv_file_exists and drv_file_time > ncf_file_time:
            if ncf_file_time:
                log_debug("Updating directives from %s" % drv_file_name)
            directives = QC.ProfileDirectives(
                base_opts.mission_dir, dive_num
            )  # reset!! don't append here
            directives.parse_file(drv_file_name)
            status = 2  # directives changed; results need updating

        eng_file_start_time = time.mktime(eng_f.start_ts)  # secs since the epoch
        for file_type, file_info in list(file_table.items()):
            (
                file_names,
                file_exists,
                file_time,
                eng_file_reader,
                required_for_reload,
            ) = file_info
            if eng_file_reader and file_time > ncf_file_time:
                if ncf_file_time:
                    log_info("Updating logger data from %s" % file_type)
                try:
                    eng_data, nc_data = eng_file_reader(
                        file_names, nc_info_d, calib_consts
                    )
                except Exception:
                    log_error(
                        "Could not process %s - not including in the profile"
                        % file_type,
                        "exc",
                    )
                    continue
                ###log_info("nc_info_d = %s" % nc_info_d)
                if nc_data is None:
                    log_error(
                        "Could not process %s - not including in the profile"
                        % file_type,
                        "exc",
                    )
                    continue

                for var, nc_entry in list(nc_data.items()):
                    if var not in BaseNetCDF.nc_var_metadata:
                        BaseNetCDF.nc_var_metadata[var] = nc_entry

                for data_entry in eng_data:
                    var_name, values = data_entry
                    if values is not None:  # could be None, in which case, skip
                        try:
                            md = BaseNetCDF.nc_var_metadata[var_name]
                        except KeyError:
                            log_error(
                                "Unknown nc variable %s from logger file type %s -- skipping "
                                % (var_name, file_type)
                            )
                            continue
                        (
                            _,
                            nc_data_type,
                            _,
                            mdp_dim_info,
                        ) = md
                        log_debug("var_name =%s md = (%s)" % (var_name, md))
                        # BUG: For scicon, assuming you have the Nixon-era bug, doing the time correction
                        # here rather than in the scicon reader means that the b cast times, which are post-apogee,
                        # don't reflect the restart time after apogee.
                        # Thus the climb points are offset earlier by often several minutes.
                        if var_name in list(BaseNetCDF.nc_mdp_time_vars.values()):
                            try:
                                (values, _) = QC.ensure_increasing_time(
                                    values, var_name, eng_file_start_time
                                )
                            except Exception:
                                log_error("Could not process %s" % var_name, "exc")
                                continue
                        if mdp_dim_info:
                            sizes = values.shape
                            for dim in range(len(mdp_dim_info)):
                                this_mdi = mdp_dim_info[dim]
                                this_size = sizes[dim]
                                BaseNetCDF.assign_dim_info_size(
                                    nc_info_d, this_mdi, this_size
                                )
                            results_d[var_name] = values
                        else:
                            if (
                                (nc_data_type == "i" and isinstance(values, int))
                                or (nc_data_type == "d" and isinstance(values, float))
                                or (nc_data_type == "c" and isinstance(values, str))
                            ):
                                results_d[var_name] = values
                            else:
                                log_error(
                                    "Scalar nc variable %s from logger file type %s expecting %s but got %s -- skipping "
                                    % (var_name, file_type, nc_data_type, type(values))
                                )

                status = 2  # reloaded some logger data; results need updating

        return (
            status,
            globals_d,
            log_f,
            eng_f,
            calib_consts,
            results_d,
            directives,
            nc_info_d,
            instruments_d,
        )

    except RuntimeError:
        # log_error(exception.args[0], "exc")
        return (0, None, None, None, None, None, None, None, None)
    except Exception:
        # Typically because a reader died
        # Seen when reading old-style nc files where the format of a variable has changed from version to version
        log_critical("Exception when reading data files: %s" % sys.exc_info()[0])
        return (0, None, None, None, None, None, None, None, None)  # indicate we lost


SBECT_mismatch_reported = {}  # if we are reprocessing several profiles don't complain on subsequent profiles


def SBECT_coefficents(sbect_type, calib_consts, log_f, sgc_vars, log_vars):
    """Fetch SBE CT coefficients, comparing log to sgc versions
    Complain if different.  Return values and vars used.
    """
    sgc_vars_used = ""
    sgc_values = []
    missing_sgc_vars = []
    for sgc_var in sgc_vars:
        if sgc_var in calib_consts:
            sgc_values.append(calib_consts[sgc_var])
            sgc_vars_used = sgc_vars_used + "sg_cal_" + sgc_var + " "
        else:
            missing_sgc_vars.append(sgc_var)

    if missing_sgc_vars:
        sgc_values = []
        sgc_vars_used = None

    log_vars_used = ""
    log_values = []
    try:
        for log_var in log_vars:
            log_values.append(log_f.data[log_var])
            log_vars_used = log_vars_used + "log_" + log_var[1:] + " "
    except KeyError:
        log_values = []
        log_vars_used = None

    if sgc_vars_used is None:
        if log_vars_used is None:
            log_error(
                f"SBECT data found but {sbect_type} calibration constant(s) missing - bailing out"
            )
            raise RuntimeError(True)
        log_error(
            f"Missing {missing_sgc_vars} from sg_calib_constants.m - using CT {sbect_type} calibration constants from log file",
            alert="MISSING_SEABIRD_CAL",
        )
        log_values.append(log_vars_used)
        return tuple(log_values)
    else:
        if log_vars_used is not None:
            acceptable_precision = 0.8e-7  # TT8 has single-precision floats
            if sbect_type not in SBECT_mismatch_reported:
                # mismatch_alert = False
                for var_values in zip(
                    sgc_vars, sgc_values, log_vars, log_values, strict=True
                ):
                    sgc_value = var_values[1]
                    log_value = var_values[3]
                    if np.isclose([sgc_value], [0.0], atol=acceptable_precision):
                        # Likely a bench test dive; don't bother with mismatch_alert
                        SBECT_mismatch_reported[sbect_type] = True
                        log_warning(
                            "%s coefficient %s (%f) is zero"
                            % (sbect_type, var_values[0], sgc_value)
                        )
                    else:
                        if not np.isclose(
                            [log_value / sgc_value], [1.0], atol=acceptable_precision
                        ):
                            # mismatch_alert = True
                            SBECT_mismatch_reported[sbect_type] = True
                            log_warning(
                                "SBECT %s coefficient %s (%g) differs from %s (%g) in log file (dive %d) -- using %g."
                                % (
                                    sbect_type,
                                    var_values[0],
                                    sgc_value,
                                    var_values[2],
                                    log_value,
                                    log_f.dive,
                                    sgc_value,
                                ),
                                alert="SBECT_COEFFICIENT",
                            )
                # if mismatch_alert:
                #     log_alert(
                #         "SBECT",
                #         "SBECT %s coefficient(s) are mismatched between sgc and log (dive %d)!"
                #         % (sbect_type, log_f.dive),
                #     )
        sgc_values.append(sgc_vars_used)
        return tuple(sgc_values)


def avg_longitude(lon1, lon2):
    """Assumes the fixes are close"""
    if math.fabs(lon1) > 179.0 or math.fabs(lon2) > 179.0:
        avg_lon = ((lon1 % 360.0) + (lon2 % 360.0)) / 2.0
        return ((avg_lon + 180.0) % 360.0) - 180.0
    else:
        return (lon1 + lon2) / 2.0


def compute_GSM_simple(
    vehicle_heading_mag_degrees_v,
    vehicle_pitch_rad_v,
    sg_depth_m_v,
    elapsed_time_s_v,
    GPS1,
    GPS2,
    GPSE,
    calib_consts,
    nc_info_d,
    results_d,
):
    """In the event the CTD data fails to load/initial process, this routine calculates
    the GSM displacements and estimated lat/lons, along with a number of additional
    caclculations that are helpful for piloting.

    All variables here are assumed to be on truck's time grid.

    This is clearly a hack (as it just duplicates code from MDP) and MDP
    should be refactored/reorganized to hoist the non-CTD
    dependent parts up earlier as well as handling the possible non-CTD time base

    No QC is currently asserted.
    """
    dive_mean_lat_factor = math.cos(math.radians((GPS2.lat_dd + GPSE.lat_dd) / 2.0))

    head_true_deg_v = vehicle_heading_mag_degrees_v + GPS2.magvar
    head_true_deg_v = 90.0 - head_true_deg_v
    bad_deg_i_v = np.nonzero(head_true_deg_v >= 360.0)
    head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] - 360.0
    bad_deg_i_v = np.nonzero(head_true_deg_v < 0.0)
    head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] + 360.0
    head_polar_rad_v = np.radians(head_true_deg_v)

    sg_np = len(elapsed_time_s_v)

    BaseNetCDF.assign_dim_info_dim_name(
        nc_info_d,
        BaseNetCDF.nc_ctd_results_info,
        BaseNetCDF.nc_dim_sg_data_point,
    )
    BaseNetCDF.assign_dim_info_size(nc_info_d, BaseNetCDF.nc_ctd_results_info, sg_np)

    delta_time_s_v = np.zeros(sg_np, np.float64)
    delta_time_s_v[1:] = np.diff(elapsed_time_s_v)  # time increments

    gps_dive_time_s = GPSE.time_s - GPS2.time_s
    SM_time_s = gps_dive_time_s - elapsed_time_s_v[-1]  # time of surface maneuver

    # NB: this will be the same as ctd_elapsed_time_s_v if no bottom time
    flight_time_v = np.cumsum(delta_time_s_v)  # actual elapsed times flying
    # NOTE do not include gps_drift_time_s because we compute DAC between GPS2 and final GPS, ignoring surface current
    # We report that separately
    total_flight_and_SM_time_s = (
        flight_time_v[-1] + SM_time_s
    )  # final elapsed time flying and drifting
    log_info(
        "Estimated total flight and drift time: %.1fs (SM: %.1fs)"
        % (total_flight_and_SM_time_s, SM_time_s)
    )

    # Calculate the displacements between GPS2 and final GPS positions
    dive_delta_GPS_lat_dd = GPSE.lat_dd - GPS2.lat_dd
    dive_delta_GPS_lon_dd = GPSE.lon_dd - GPS2.lon_dd
    if np.fabs(dive_delta_GPS_lon_dd) > 180.0:
        # We have crossed the international dateline
        dive_delta_GPS_lon_dd = 360.0 - np.fabs(dive_delta_GPS_lon_dd)
        if GPS2.lon_dd < GPSE.lon_dd:
            # If the start is less then the final, then we crossed western hemisphere to eastern hemisphere,
            # so the "direction" should be negative
            dive_delta_GPS_lon_dd = -dive_delta_GPS_lon_dd

    dive_delta_GPS_lat_m = dive_delta_GPS_lat_dd * m_per_deg
    dive_delta_GPS_lon_m = dive_delta_GPS_lon_dd * m_per_deg * dive_mean_lat_factor

    # Save intermediate calculations that went into displacement and DAC calculations
    results_d.update(
        {
            "delta_time_s": delta_time_s_v,
            "polar_heading": head_polar_rad_v,
            "GPS_north_displacement_m": dive_delta_GPS_lat_m,
            "GPS_east_displacement_m": dive_delta_GPS_lon_m,
            "total_flight_time_s": total_flight_and_SM_time_s,
        }
    )

    good_depth_pts = np.logical_not(np.isnan(sg_depth_m_v))
    try:
        w_cm_s_v = Utils.ctr_1st_diff(
            -sg_depth_m_v[good_depth_pts] * m2cm, elapsed_time_s_v[good_depth_pts]
        )
    except Exception:
        log_error("Failed calculating dz/dt - skipping profile", "exc")
        return

    converged, gsm_speed_cm_s_v, gsm_glide_angle_rad_v, _ = glide_slope(
        w_cm_s_v, vehicle_pitch_rad_v, calib_consts
    )
    if not converged:
        log_warning("Unable to converge during initial glide-slope speed calculations")
    # gsm_glide_angle_deg_v is used in call to TSV below (rather than gsm_glide_angle_rad_v)
    gsm_glide_angle_deg_v = np.degrees(gsm_glide_angle_rad_v)
    gsm_horizontal_speed_cm_s_v = gsm_speed_cm_s_v * np.cos(gsm_glide_angle_rad_v)
    gsm_w_speed_cm_s_v = gsm_speed_cm_s_v * np.sin(gsm_glide_angle_rad_v)
    results_d.update(
        {
            "speed_gsm": gsm_speed_cm_s_v,
            "glide_angle_gsm": gsm_glide_angle_deg_v,
            "horz_speed_gsm": gsm_horizontal_speed_cm_s_v,
            "vert_speed_gsm": gsm_w_speed_cm_s_v,
        }
    )
    (
        gsm_east_displacement_m_v,
        gsm_north_displacement_m_v,
        gsm_east_displacement_m,
        gsm_north_displacement_m,
        gsm_east_average_speed_m_s,
        gsm_north_average_speed_m_s,
    ) = compute_displacements(
        "gsm",
        gsm_horizontal_speed_cm_s_v,
        delta_time_s_v,
        total_flight_and_SM_time_s,
        head_polar_rad_v,
    )
    results_d.update(
        {
            "flight_avg_speed_east_gsm": gsm_east_average_speed_m_s,
            "flight_avg_speed_north_gsm": gsm_north_average_speed_m_s,
            "east_displacement_gsm": gsm_east_displacement_m_v,
            "north_displacement_gsm": gsm_north_displacement_m_v,
        }
    )

    gsm_dac_east_speed_m_s, gsm_dac_north_speed_m_s = compute_dac(
        gsm_north_displacement_m_v,
        gsm_east_displacement_m_v,
        gsm_north_displacement_m,
        gsm_east_displacement_m,
        dive_delta_GPS_lat_m,
        dive_delta_GPS_lon_m,
        total_flight_and_SM_time_s,
    )
    results_d.update(
        {
            "depth_avg_curr_east_gsm": gsm_dac_east_speed_m_s,
            "depth_avg_curr_north_gsm": gsm_dac_north_speed_m_s,
        }
    )
    gsm_lat_dd_v, gsm_lon_dd_v = compute_lat_lon(
        gsm_dac_east_speed_m_s,
        gsm_dac_north_speed_m_s,
        GPS2.lat_dd,
        GPS2.lon_dd,
        gsm_east_displacement_m_v,
        gsm_north_displacement_m_v,
        delta_time_s_v,
        dive_mean_lat_factor,
    )
    results_d.update(
        {
            "latitude_gsm": gsm_lat_dd_v,
            "longitude_gsm": gsm_lon_dd_v,
        }
    )
    # Calculate the drift speed and direction between GPS1 and GPS2
    gps_drift_time_s = GPS2.time_s - GPS1.time_s
    log_debug("gps_drift_time_s = %f" % gps_drift_time_s)

    surface_GPS_mean_lat_dd = (GPS1.lat_dd + GPS2.lat_dd) / 2.0
    surface_mean_lat_factor = math.cos(math.radians(surface_GPS_mean_lat_dd))

    surface_delta_GPS_lat_dd = GPS2.lat_dd - GPS1.lat_dd
    surface_delta_GPS_lon_dd = GPS2.lon_dd - GPS1.lon_dd

    surface_delta_GPS_lat_m = surface_delta_GPS_lat_dd * m_per_deg
    surface_delta_GPS_lon_m = (
        surface_delta_GPS_lon_dd * m_per_deg * surface_mean_lat_factor
    )

    log_debug(
        "surface_delta_GPS_lat_m = %f, surface_delta_GPS_lon_m = %f"
        % (surface_delta_GPS_lat_m, surface_delta_GPS_lon_m)
    )

    surface_current_drift_cm_s = (
        m2cm
        * math.sqrt(
            surface_delta_GPS_lat_m * surface_delta_GPS_lat_m
            + surface_delta_GPS_lon_m * surface_delta_GPS_lon_m
        )
        / gps_drift_time_s
    )
    try:
        # compute polar (not compass!) angle of surface current
        # convert to degrees to handle bounds checking below
        surface_current_set_deg = math.degrees(
            math.atan2(surface_delta_GPS_lat_m, surface_delta_GPS_lon_m)
        )
    except ZeroDivisionError:  #  atan2
        surface_current_set_deg = 0.0

    if surface_current_set_deg < 0:
        surface_current_set_deg = surface_current_set_deg + 360.0

    surface_current_set_rad = math.radians(surface_current_set_deg)

    # given polar (not compass) angle cos() gets the east (U) component; sin() get the north (V) component of drift speed
    surface_curr_east = surface_current_drift_cm_s * np.cos(surface_current_set_rad)
    surface_curr_north = surface_current_drift_cm_s * np.sin(surface_current_set_rad)

    log_debug(
        "surface_current_drift_cm_s = %f, polar surface_current_set_deg = %f"
        % (surface_current_drift_cm_s, surface_current_set_deg)
    )
    surface_curr_error = (GPS1.error + GPS2.error) / gps_drift_time_s  # [m/s]
    results_d.update(
        {
            "surface_curr_east": surface_curr_east,
            "surface_curr_north": surface_curr_north,
            "surface_curr_error": surface_curr_error,
        }
    )


# TODO add None for eng_file_name, log_file_name, sg_calib_file_name
# TODO config_file_name -- is this actually used by by anyone in this path?  it is passed around but not parsed..
def make_dive_profile(
    ignore_existing_netcdf,
    dive_num,
    eng_file_name,
    log_file_name,
    sg_calib_file_name,
    base_opts,
    nc_dive_file_name=None,
    logger_eng_files=None,  # List of logger eng files for inclusion in netCDF output
):
    """Creates a dive profile from an eng and log file

    Input:
        ignore_existing_netcdf - ignores the contents of an already existing netcdf file
        dive_num = integer value for the current dive
            NOTE: dive_num is used strictly for NetCDF metadata - no other assumptions should be built upon this value
        eng_file_name - fully qualifed path to eng file (optional)
        log_file_name - fully qualifed path to log file (optional)
        sg_calib_file_name - fully qualified path to sg_calib_file (optional)
        base_opts - command-line options structure
        nc_dive_file_name - fully qualifed path to NetCDF output file (optional)

    Returns:
        tuple(ret_val, nc_dive_file_name)
        ret_val
            0 - success
            1 - failure
            2 - dive 0 skipped
        nc_dive_file_name - None for no netcdf creation,
                            Name of create netcdf file

    Raises:
      Any exceptions not explicitly raised are considered critical errors and not expected
    """

    if dive_num == 0:
        log_info("Skipping dive 0 netcdf creation")
        return (2, None)

    BaseNetCDF.reset_nc_char_dims()

    # set up logging
    # str() prints 'None' for None rather than ''
    log_debug(
        "Eng file = %s, Log file = %s, sg_calib_file_name = %s, nc_dive_file_name = %s, "
        % (
            str(eng_file_name),
            str(log_file_name),
            str(sg_calib_file_name),
            str(nc_dive_file_name),
        )
    )
    log_debug("logger_eng_files = %s" % logger_eng_files)

    processing_history = ""  # nothing yet

    head, _ = os.path.splitext(log_file_name)  # fully qualified name
    path, dive_tag = os.path.split(head)

    (
        status,
        globals_d,
        log_f,
        eng_f,
        explicit_calib_consts,
        results_d,
        directives,
        nc_info_d,
        instruments_d,
    ) = load_dive_profile_data(
        base_opts,
        ignore_existing_netcdf,
        nc_dive_file_name,
        eng_file_name,
        log_file_name,
        sg_calib_file_name,
        logger_eng_files,
        apply_sg_config_constants=True,
    )

    if status == 0:
        log_error("Unable to load data; nothing done")
        return (1, None)
    elif status == 1 and not (base_opts.force or base_opts.reprocess):
        log_info("Files up-to-date; nothing to do")
        return (0, None)
    else:  # status == 2 or we are forced
        if base_opts.force:
            log_info("Reprocessing - forcing recreation of netCDF file")
        if "history" in globals_d and not base_opts.force:
            processing_history = globals_d["history"]  # append to previous history
        if "processing_error" in results_d:
            del results_d[
                "processing_error"
            ]  # flush old errors and see if they come back

    BaseLogger.self.startStringCapture()

    # Fix up the TC events start and end times
    if (
        log_f.tc_data
        and "start_time_est" in log_f.tc_data
        and "start_time" not in log_f.tc_data
    ):
        Utils.fix_TC_times(log_f, eng_f)

    # Ask FlightModel for its ideas on flight model values
    if not base_opts.ignore_flight_model:
        FlightModel.get_flight_parameters(dive_num, base_opts, explicit_calib_consts)

    # if False:  # DEBUG
    #     # See if there is an fm.m and read it (was used for matlab hill climbing via reprocessing)
    #     file_name = os.path.join(base_opts.mission_dir, "fm.m")
    #     if os.path.exists(file_name):
    #         fm_calib_consts = CalibConst.getSGCalibrationConstants(
    #             file_name, suppress_required_error=True
    #         )
    #         if fm_calib_consts is not None:  # otherwise can't open it for seom reason
    #             # override...
    #             log_info("Overriding FM parameters using %s" % file_name)
    #             for key, value in list(fm_calib_consts.items()):
    #                 # NOTE: CalibConst.getSGCalibrationConstants suuplies None for id_str,mission_title,mass
    #                 if value is not None:
    #                     explicit_calib_consts[key] = value

    calib_consts = (
        explicit_calib_consts.copy()
    )  # copy the explicit constants, which we write below

    if base_opts.ignore_flight_model:
        if "mass" not in calib_consts:
            calib_consts["mass"] = log_f.data.get("$MASS", 0) / 1000
        if "rho0" not in calib_consts:
            calib_consts["rho0"] = log_f.data.get("$RHO", 1.0275) * 1000
        if "hd_a" not in calib_consts:
            calib_consts["hd_a"] = log_f.data.get("$HD_A", 0)
        if "hd_b" not in calib_consts:
            calib_consts["hd_b"] = log_f.data.get("$HD_B", 0)
        if "hd_c" not in calib_consts:
            calib_consts["hd_c"] = log_f.data.get("$HD_C", 0)
        if "volmax" not in calib_consts:
            calib_consts["volmax"] = log_f.data.get("$MASS", 0) / log_f.data.get(
                "$RHO", 1.0275
            ) + (
                log_f.data.get("$VBD_MIN", 500) - log_f.data.get("$C_VBD", 3000)
            ) * log_f.data.get("$VBD_CNV", -0.245)

    sg_config_constants(
        base_opts,
        calib_consts,
        log_f.data.get("$DEEPGLIDER", 0),
        ("gpctd_time" in results_d),
    )  # update copy with defaults

    for fv in Globals.flight_variables:
        src_tag = "SGC" if base_opts.ignore_flight_model else "FM"
        log_info("%s: %s=%g" % (src_tag, fv, calib_consts[fv]))

    auxcompass_present = auxpressure_present = False

    if "auxCompass_pressureCounts" in results_d:
        auxpressure_name = "auxCompass"
        auxpressure_present = True

    if "auxB_pressureCounts" in results_d:
        auxpressure_name = "auxB"
        auxpressure_present = True

    if (
        "auxCompass_hdg" in results_d
        and "auxCompass_pit" in results_d
        and "auxCompass_rol" in results_d
        and "auxCompass_time" in results_d
    ):
        auxcompass_present = True

    log_info(
        "auxcompass data%s present, auxPressure data%s present"
        % ("" if auxcompass_present else " not", "" if auxpressure_present else " not")
    )
    use_auxpressure = calib_consts["use_auxpressure"] and auxpressure_present
    use_auxcompass = calib_consts["use_auxcompass"] and auxcompass_present

    if use_auxcompass and not use_auxpressure:
        log_warning("Using auxcompass data requires auxpressure data")
        use_auxcompass = False

    # Set deck_dive global
    deck_dive = False
    try:
        if log_f.data["$SIM_W"]:
            deck_dive = True
            # ensure we use the SIM modified pressure on the truck
            use_auxpressure = False
            use_auxcompass = False
            results_d.update({"deck_dive": deck_dive})  # assert only if true
            log_info("Assuming this is a deck dive")
            # if not "$SIM_PITCH" in log_f.data:
            #    log_f.data["$SIM_PITCH"] = 15
            # If running the legato, use the truck simulated pressure
            if calib_consts["sg_ct_type"] == 4:
                calib_consts["legato_use_truck_pressure"] = 1

    except KeyError:
        pass

    if auxpressure_present:
        aux_pressure_slope = aux_pressure_offset = None
        auxPress_counts_v = results_d[f"{auxpressure_name}_pressureCounts"]
        aux_epoch_time_s_v = results_d[f"{auxpressure_name}_time"]
        # Test for bad auxPressure
        if np.abs(np.mean(auxPress_counts_v)) < 10.0:
            log_error(
                "dive%04d: %s has a mean value of %f - probably misconfigured - not using auxPressure or auxCompass data"
                % (
                    dive_num,
                    f"{auxpressure_name}_pressureCounts",
                    np.mean(auxPress_counts_v),
                ),
                alert="BAD_AUXPRESSURE",
            )
            use_auxpressure = use_auxcompass = False

        if auxpressure_name == "auxB":
            # AuxB is a serial read - same as the glider, so use the glider's slope and y-int to deal with the conversion
            auxCompass_pressure_v = None
            try:
                aux_pressure_slope = float(log_f.data["$PRESSURE_SLOPE"])
                aux_pressure_offset = float(log_f.data["$PRESSURE_YINT"])
                auxCompass_pressure_v = (
                    (auxPress_counts_v * aux_pressure_slope) + aux_pressure_offset
                ) * dbar_per_psi
            except Exception:
                log_error("Could not create auxB_pressure", "exc")
        else:
            # Look for pressure field in auxCompass header
            # The assumption here is that if the pressure field is present, it must be used as the $PRESSURE_YINT
            # for the gliders compass does no apply (new purple compass boards)
            if "auxCompass_pressure" in results_d:
                try:
                    aux_pressure_slope, aux_pressure_offset = results_d[
                        "auxCompass_pressure"
                    ][:].split()
                    aux_pressure_slope = float(aux_pressure_slope)
                    aux_pressure_offset = float(aux_pressure_offset)
                except Exception:
                    log_error(
                        "Poorly formed auxCompass_pressure - not using auxCompassor auxPressure data",
                        "exc",
                        alert="AUXCOMPASS",
                    )
                    use_auxpressure = use_auxcompass = False

            # Convert pressure counts to pressure
            if aux_pressure_slope is not None and aux_pressure_offset is not None:
                auxCompass_pressure_v = (
                    (auxPress_counts_v - aux_pressure_offset)
                    * aux_pressure_slope
                    * dbar_per_psi
                )
                log_info(
                    "auxCompass_pressure_offset = %f, auxCompass_pressure_slope = %f"
                    % (aux_pressure_offset, aux_pressure_slope)
                )
            else:
                auxPress_v = auxPress_counts_v * log_f.data["$PRESSURE_SLOPE"]  # [psi]

                # TODO - GBS 2021/08/16 Needs to be re-enabled after kistler_cnf is defined earlier in the processing

                # if kistler_cnf is None:
                #     auxPress_v = auxPress_counts_v * log_f.data['$PRESSURE_SLOPE'] # [psi]
                # else:
                #     aux_temp_v = Utils.interp1d(ctd_epoch_time_s_v, temp_raw_v, aux_epoch_time_s_v, kind='linear')
                #     auxPress_v = compute_kistler_pressure(kistler_cnf, log_f, auxPress_counts_v, aux_temp_v) # [psi]

                sg_epoch_time_s_v = time.mktime(eng_f.start_ts) + eng_f.get_col(
                    "elaps_t"
                )
                sg_press_v = (
                    (
                        eng_f.get_col("depth")
                        * cm2m
                        * calib_consts["depth_slope_correction"]
                        - calib_consts["depth_bias"]
                    )
                    * psi_per_meter
                    * dbar_per_psi
                )

                # Why not simply + log_f.data['$PRESSURE_YINT'] to get final pressure?
                # Because while we trust the conversion slope of the sensor to be independent of sampling scheme,
                # the log value of yint encodes information about the AD7714, etc.  We need to see how the
                # aux AD is offset from that and compute an implied yint. So...
                # Convert glider pressure to PSI and interpolate to aux time grid
                glider_press_v = Utils.interp1d(
                    sg_epoch_time_s_v,
                    sg_press_v / dbar_per_psi,
                    aux_epoch_time_s_v,
                    kind="linear",
                )  # [psi]
                # Adjust for yint based on truck values
                # Note - this will go very wrong if you only have a half profile
                auxPress_yint = -np.mean(auxPress_v - glider_press_v)
                log_info(
                    "auxPress_yint = %f, $PRESSURE_YINT = %f (%f psi)"
                    % (
                        auxPress_yint,
                        log_f.data["$PRESSURE_YINT"],
                        (auxPress_yint - log_f.data["$PRESSURE_YINT"]),
                    )
                )

                auxCompass_pressure_v = (
                    auxPress_v + auxPress_yint
                ) * dbar_per_psi  # [dbar]
                del auxPress_v, sg_epoch_time_s_v, sg_press_v, glider_press_v

            # if False:
            #     # This hack is to handle bad truck pressure, but to auxcompass pressure
            #     log_warning(
            #         "Re-writing truck pressure and depth from auxCompass pressure"
            #     )
            #     sg_press_v = Utils.interp1d(
            #         aux_epoch_time_s_v,
            #         auxCompass_pressure_v,
            #         sg_epoch_time_s_v,
            #         kind="linear",
            #     )
            #     if not base_opts.use_gsw:
            #         sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
            #     else:
            #         sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)
            #     results_d.update(
            #         {
            #             "pressure": sg_press_v,
            #             "depth": sg_depth_m_v,
            #         }
            #     )

    log_info(
        "%s auxcompass %s auxPressure"
        % (
            "Using" if use_auxcompass else "Not using",
            "Using" if use_auxpressure else "Not using",
        )
    )

    # keep any vector (no scalars) in results that are raw data
    for var in list(results_d.keys()):
        try:
            md = BaseNetCDF.nc_var_metadata[var]
            _, _, meta_data_d, mdp_dim_info = md
            all_dims_data = True
            for mdi in mdp_dim_info:
                if mdi not in BaseNetCDF.nc_data_infos:
                    all_dims_data = False
                    break
            if all_dims_data:
                continue  # save this one
        except KeyError:
            log_error("Unknown results variable %s -- dropped" % var)
        # if we fall through we show drop the variable
        # it is a scalar (mdp_dim_info is BaseNetCDF.nc_scalar) or it is a result array
        del results_d[var]

    # Setup for tracing
    TraceArray.trace_results_stop()
    # In case we exited strangely DEAD
    QC.qc_log_stop()
    TraceArray.trace_disable()
    # simple way of disabling all the trace world (comment out to trace)
    TraceArray.trace_results(
        os.path.join(
            path, "trace_%d%s_new.ptrc" % (dive_num, ("_nc" if status == 1 else ""))
        ),
        "Tracing tsv run for dive %d" % (dive_num),
    )

    QC.qc_log_stop()
    # QC.qc_log_start(os.path.join(path, "qclog_%d.pckl" % (dive_num,)))

    dive_directives = (
        directives.dump_string()
    )  # just the specific directives for this profile
    if dive_directives != "":
        results_d.update({"directives": dive_directives})

    sg_ct_type = calib_consts["sg_ct_type"]

    # now add the default rules
    default_directives = [
        "* no_interp_gc_temperatures",
        "* correct_thermal_inertia_effects",
        "* no_interp_suspect_thermal_inertia_salinities",
        "* bad_temperature temp_QC_BAD",
        "* interp_temperature temp_QC_INTERPOLATED",
        "* detect_conductivity_anomalies",
        "* bad_conductivity cond_QC_BAD",
        "* interp_conductivity cond_QC_INTERPOLATED",
        "* bad_salinity salin_QC_BAD",
        "* interp_salinity salin_QC_INTERPOLATED",
    ]

    if sg_ct_type == 4:
        default_directives += ["* no_detect_vbd_bleed", "* no_detect_slow_apogee_flow"]
    else:
        default_directives += ["* detect_vbd_bleed", "* detect_slow_apogee_flow"]

    for default_directive in default_directives:
        directives.parse_string(default_directive)

    def eval_directive(function, report=True):
        state = directives.eval_function(function)
        if report:
            log_info("Directive: %s" % (function if state else "no_%s" % function))
        return state

    directives.reviewed = 0  # not reviewed until they specifically say so... (could be a default rule '* no_reviewed' since first-come first-served)
    directives.reviewed = reviewed = eval_directive("reviewed", report=False)
    directives.correct_thermal_inertia_effects = perform_thermal_inertia_correction = (
        eval_directive("correct_thermal_inertia_effects")
    )
    # For the legato, this correction is never the correct choice
    if sg_ct_type == 4:
        perform_thermal_inertia_correction = False
    directives.detect_conductivity_anomalies = perform_cond_anomaly_check = (
        eval_directive("detect_conductivity_anomalies")
    )
    directives.interp_gc_temperatures = interpolate_gc_temperatures = eval_directive(
        "interp_gc_temperatures"
    )
    directives.interp_suspect_thermal_inertia_salinities = (
        interpolate_extreme_tmc_points
    ) = eval_directive("interp_suspect_thermal_inertia_salinities")

    directives.detect_vbd_bleed = detect_vbd_bleed = eval_directive("detect_vbd_bleed")
    directives.detect_slow_apogee_flow = detect_slow_apogee_flow = eval_directive(
        "detect_slow_apogee_flow"
    )

    # RBR TODO - Reset these based on the sb_ct_type

    # Don't use True and False here -- written to nc file as integers
    processing_error = 0  # assume all is well
    skipped_profile = 0  # assume not skipped
    try:
        id_str = calib_consts["id_str"]
        mission_title = calib_consts["mission_title"]
        log_debug("id_str = %s, mission_title = %s" % (id_str, mission_title))
        log_debug(
            "Engfile start time = %s"
            % time.strftime(
                "%H:%M:%S %d %b %Y %Z", time.gmtime(time.mktime(eng_f.start_ts))
            )
        )

        # Setup these variables early so available for nc writing in case of error
        # global variable
        eng_file_start_time = time.mktime(eng_f.start_ts)  # secs since the epoch
        i_eng_file_start_time = int(eng_file_start_time)  # integer version for GC work
        elapsed_time_s_v = eng_f.get_col(
            "elaps_t"
        )  # When pressure sample was taken; other measurements occur sometime slightly later
        # ARGO computes JULD as fraction of days since a reference date (1950-01-01 00:00:00 UTC)
        # The value below is seconds since a reference date (1970-01-01 00:00:00 UTC)
        # The ARGO encoding is closer (but not the same as) the matlab serial date number
        # matlab references to (1900-01-01 00:00:00 UTC)
        # ODV wants Date (as YYYY-MM-YY) and Time (HH:MM)
        sg_epoch_time_s_v = eng_file_start_time + elapsed_time_s_v

        results_d.update({BaseNetCDF.nc_sg_time_var: sg_epoch_time_s_v})
        globals_d["time_coverage_start"] = BaseNetCDF.nc_ISO8601_date(
            min(sg_epoch_time_s_v)
        )
        globals_d["time_coverage_end"] = BaseNetCDF.nc_ISO8601_date(
            max(sg_epoch_time_s_v)
        )

        # dimension values
        sg_np = len(elapsed_time_s_v)

        rho0 = calib_consts["rho0"]
        if rho0 < 1.1:
            # sg_calib_constants.m provides rho0, expressed in g/m^3
            # The glider parameter (and log file) provide $RHO, in g/cc
            # It can sometimes happen (SG524 under GPCTD tests) that the sg_calib_constant value
            # is expressed in g/cc, as though copied from $RHO.
            log_warning("Correcting rho0, which is %g and less than 1000 g/m^3" % rho0)
            calib_consts["rho0"] = rho0 = rho0 * 1000

        # In the beginning, all is darkness.  We have only time, depth
        # (pressure actually), temperature frequency, conductivity
        # frequency, and observed vehicle pitch angle.

        # The order of battle is as follows.

        # First, compute location of vehicle and the times of various events
        # (flare, apogee, start of climb, etc.) using GC records.

        # Next, compute w = dz/dt.  From observed w and vehicle pitch, compute,
        # via glide_slope(), a first approximation to the glide angle and hence
        # the vehicle total speed w/sin(glide angle) and vehicle horizontal
        # speed w/tan(glider angle).  Using those speeds as an initial guess,
        # use the full hydrodynamic model to solve for an improved speed and
        # glide angle estimate as a function of buoyancy and pitch.

        # To determine buoyancy, first determine raw temperature and
        # conductivity values. If unpumped, convert raw temperatures and
        # conductivities from frequencies, using the SeaBird equations and
        # calibration coefficients.  Determine a raw salinity and perform some
        # quality control checks.

        # Next, correct the T and C using biases and anomaly
        # detection.  From the corrected T and C, (iteratively)
        # compute salinity, then density, then speed.  This is used to
        # compute depth-averaged current, etc.

        # Once we have correected T, S, and density profiles, we can
        # add in profiles from any other sensors available (O2, BB2F,
        # etc.)  and that will finish the "best-effort" profile
        # creation.

        # We maintain parallel quality-control (QC) arrays that mark the
        # corresponding data points good, bad, interpolated, etc. During
        # the computations described above, we maintain full-length arrays
        # (but see TempSalinityVelocity()).

        CTD_qc = QC.QC_GOOD  # assume we got good CTD data
        hdm_qc = QC.QC_GOOD  # and good hdm speeds
        DAC_qc = QC.QC_GOOD  # and hence good DAC

        # CCE reports that the Kalman filter, if it runs for a long time, gets hosed and computes
        # ridiculous desired pitches (less than 10 degrees).  This will cause the glider to flat spin and stall
        # We detect that early by looking for nonsensical speed estimates

        # TODO move this parameter to sg_config_constants
        # NOTE with the new ogive hull shape and length, DG has less drag so L/D is higher and it can fly at shallower angles
        # thus this needs to be adjusted down for DG (to 8.0 at least?)
        minimum_pitch_desired = (
            10.0  # PARAMETER minimum pitch desired for typical missions
        )
        mhead_rng_pitchd_wd = log_f.data["$MHEAD_RNG_PITCHd_Wd"]
        if mhead_rng_pitchd_wd:
            values_v = mhead_rng_pitchd_wd.split(",")
            if len(values_v) > 2:
                pitch_desired = float(values_v[2])
                if pitch_desired > minimum_pitch_desired:  # not pitched down enough?
                    log_warning(
                        "Suspicious pitch desired (%.2f degrees) in %s? Check $MHEAD_RNG_PITCHd_Wd"
                        % (pitch_desired, log_file_name)
                    )
                    directives.suggest("skip_profile % Bad pitch desired")

        GPS1 = log_f.data["$GPS1"]
        GPS1.ok = True
        GPS2 = log_f.data["$GPS2"]
        GPS2.ok = True
        try:
            # Do we have an old-style dataset?
            # We always assume we have $GPS1 and $GPS2 (and that their formats are 'modern')
            GPSE = log_f.data["$GPS"]
            GPSE.ok = True  # GPS end
        except KeyError:
            log_warning("Couldn't find $GPS in %s" % log_file_name.args)
            # Set a default...no worse than GPS acquisition issues...
            GPSE = copy.copy(GPS2)  # no need to deepcopy
            GPSE.ok = False

        # These are used to control DAC computations below
        GPS12_ok = True  # both GPS1 and GPS2 look valid
        GPS2E_ok = True  # both GPS2 and GPS (end) look valid

        # Automatically detecting bad fixes (bad times, bad lat/lon, etc.) is very problematic,
        # especially on a single dive basis.  Allow the scientist to declare specific fixes bad.
        # Remember, a bad_gps3 should be paired with a bad_gps1 on the subsequent dive.
        # faroes/jun07/sg101 dive 13 bad_gps3 and hence dive 14 bad_gps1

        # GPS_bad = directives.eval_function("bad_gps1", absent_predicate_value=None)
        # if GPS_bad is not None:
        #     GPS1.ok = False if GPS_bad else True
        # GPS_bad = directives.eval_function("bad_gps2", absent_predicate_value=None)
        # if GPS_bad is not None:
        #     GPS2.ok = False if GPS_bad else True
        # GPS_bad = directives.eval_function("bad_gps3", absent_predicate_value=None)
        # if GPS_bad is not None:
        #     GPSE.ok = False if GPS_bad else True
        # TODO GBS 2022/09/21 - verify that this simplificaiton works
        GPS1.ok = not directives.eval_function("bad_gps1", absent_predicate_value=None)
        GPS2.ok = not directives.eval_function("bad_gps2", absent_predicate_value=None)
        GPSE.ok = not directives.eval_function("bad_gps3", absent_predicate_value=None)

        # Investigations of Aug 2014 showed that GPS fixes prior to this date
        # were likely accurate to only 100m, regardless of hdop value (see Bennett & Stahr, 2014)
        std_gps_error = calib_consts["GPS_position_error"]
        GPS1.error = GPS1.HPE if GPS1.HPE > 0 else std_gps_error
        GPS2.error = GPS2.HPE if GPS2.HPE > 0 else std_gps_error
        GPSE.error = GPSE.HPE if GPSE.HPE > 0 else std_gps_error

        GPS1.ok = GPS1.ok and GPS1.isvalid and GPS1.error <= std_gps_error
        GPS2.ok = GPS2.ok and GPS2.isvalid and GPS2.error <= std_gps_error
        GPSE.ok = GPSE.ok and GPSE.isvalid and GPSE.error <= std_gps_error

        GPS1.time_s = time.mktime(GPS1.datetime)
        GPS2.time_s = time.mktime(GPS2.datetime)
        GPSE.time_s = time.mktime(GPSE.datetime)
        log_debug(
            "GPS1 time = %f, GPS2 time = %f, GPSE time = %f"
            % (GPS1.time_s, GPS2.time_s, GPSE.time_s)
        )

        gps_drift_time_s = GPS2.time_s - GPS1.time_s
        GPS12_ok = (
            GPS1.ok and GPS2.ok and gps_drift_time_s > 0
        )  # time advanced during drift?
        gps_dive_time_s = GPSE.time_s - GPS2.time_s
        GPS2E_ok = (
            GPS2.ok and GPSE.ok and gps_dive_time_s > 0
        )  # time advanced during dive?
        GPS2E_gpsfix = (
            GPS2.hdop < 99.0 and GPSE.hdop < 99.0
        )  # Is this actually a GPS fix (vs. a RAFOS or Iridium fix or no fix)
        try:
            # In the case of yoyo dives either GPS2 is latched (as the last in the series)
            # or GPSE is latched (for the first in the series) or both (in the middle)
            if log_f.data["$N_NOSURFACE"] != 0:
                log_info("Subsurface dive: skipping DAC computation")
                GPS2E_ok = False
        except KeyError:
            pass  # not a yoyo dive
        # CONSIDER: same test as N_NOSURFACE but for under-ice use $SURFACE_URGENCY nonzero or $RAFOS_DEVICE not -1 or both
        # map individual GPS health to qc values
        GPS1.qc = QC.QC_GOOD if GPS1.ok else QC.QC_BAD
        GPS2.qc = QC.QC_GOOD if GPS2.ok else QC.QC_BAD
        GPSE.qc = QC.QC_GOOD if GPSE.ok else QC.QC_BAD

        test_tank_dive = False
        # The extra-special, super-secret location in APL, on land, but really probably OSB
        if GPS1.lat == 4739.36 and GPS1.lon == -12219.03:
            test_tank_dive = True
            log_info("Assuming this is a tank dive!")
            # Dusable these checks -- these are propagated to the netcdf file!
            calib_consts["QC_temp_spike_depth"] = 0
            calib_consts["QC_cond_spike_depth"] = 0
            results_d.update({"test_tank_dive": test_tank_dive})

        GPS1.lat_dd = Utils.ddmm2dd(GPS1.lat)
        GPS2.lat_dd = Utils.ddmm2dd(GPS2.lat)
        GPSE.lat_dd = Utils.ddmm2dd(GPSE.lat)
        GPS1.lon_dd = Utils.ddmm2dd(GPS1.lon)
        GPS2.lon_dd = Utils.ddmm2dd(GPS2.lon)
        GPSE.lon_dd = Utils.ddmm2dd(GPSE.lon)
        log_debug("GPS1 lat = %f, lon = %f" % (GPS1.lat_dd, GPS1.lon_dd))
        log_debug("GPS2 lat = %f, lon = %f" % (GPS2.lat_dd, GPS2.lon_dd))
        log_debug("GPSE lat = %f, lon = %f" % (GPSE.lat_dd, GPSE.lon_dd))

        # Compute average latitude for the dive for various pressure corrections
        # Latitude will be the mean of the start and end latitude of the dive, in decimal degrees
        # if USE_ICE then GPS hdop is 99 and we should use something else in the RAFOS category?
        if GPS2E_ok and GPS2E_gpsfix:  # during the dive
            latitude = (GPS2.lat_dd + GPSE.lat_dd) / 2.0
            longitude = avg_longitude(GPS2.lon_dd, GPSE.lon_dd)
            # This is a good initial guess in case we can't do DAC below
            globals_d["geospatial_lat_min"] = min(GPS2.lat_dd, GPSE.lat_dd)
            globals_d["geospatial_lat_max"] = max(GPS2.lat_dd, GPSE.lat_dd)
            globals_d["geospatial_lon_min"] = min(GPS2.lon_dd, GPSE.lon_dd)
            globals_d["geospatial_lon_max"] = max(GPS2.lon_dd, GPSE.lon_dd)
        else:
            DAC_qc = QC.QC_BAD  # We can't tell actual displacements
            if GPS12_ok:  # during the drift?
                log_warning("Determining average latitude using GPS1 and GPS2")
                latitude = (GPS1.lat_dd + GPS2.lat_dd) / 2.0
                longitude = avg_longitude(GPS1.lon_dd, GPS2.lon_dd)
            else:
                # could have a bum GPS unit or yoyo dive
                # in these cases assume a plausible latitude was latched
                latitude = (GPS2.lat_dd + GPSE.lat_dd) / 2.0
                longitude = avg_longitude(GPS2.lon_dd, GPSE.lon_dd)
                log_warning(
                    "No trustworthy GPS values; assuming average latitude of %.1f degrees"
                    % latitude
                )

        # the headings in the 'head' column of the *.eng file are magnetic.
        mag_var_deg = GPS2.magvar
        if not GPS2.ok:
            # even if GPS unit is busted we latch the last magvar, which is better than nothing (or zero)
            log_warning(
                "$GPS2 untrustworthy; assuming magnetic variance of %.1f degrees"
                % mag_var_deg
            )

        TraceArray.trace_comment("average_lat = %f" % latitude)
        log_debug("Latitude = %f" % latitude)
        results_d.update(
            {
                "GPS1_qc": GPS1.qc,
                "GPS2_qc": GPS2.qc,
                "GPSE_qc": GPSE.qc,
                "avg_latitude": latitude,
                "avg_longitude": longitude,
                "magnetic_variation": mag_var_deg,
            }
        )

        if auxpressure_present:
            # auxCompass_depth_v = sewater.dpth(auxCompass_pressure_v, latitude)
            if not base_opts.use_gsw:
                auxCompass_depth_v = seawater.dpth(auxCompass_pressure_v, latitude)
            else:
                auxCompass_depth_v = -1.0 * gsw.z_from_p(
                    auxCompass_pressure_v, latitude, 0.0, 0.0
                )
            results_d.update(
                {
                    f"{auxpressure_name}_press": auxCompass_pressure_v,
                    f"{auxpressure_name}_depth": auxCompass_depth_v,
                }
            )

        if directives.eval_function("skip_profile"):
            skipped_profile = 1
            results_d.update({"skipped_profile": skipped_profile})
            log_info("Skipping profile as directed")
            raise RuntimeError(False)

        # Fetch dflare and dsurf for bubble calculations below
        try:
            dflare = log_f.data["$D_FLARE"]  # [m]
        except Exception:
            dflare = 3  # meters
            log_warning("$D_FLARE missing from log; assuming %d meters" % dflare)

        # look for bubbles below dsurf
        try:
            dsurf = log_f.data["$D_SURF"]  # [m]
        except KeyError:
            log_warning("$D_SURF missing from log; using $DFLARE")
            dsurf = dflare

        try:
            dfinish = log_f.data["$D_FINISH"]  # [m]
        except KeyError:
            dfinish = dflare

        dsurf = max(dsurf, dfinish)  # Use the deepest

        # try:
        # in the case of yoyo dives, use this value?
        # the problem is that we don't know, without parsing $STATE, if this dive ended subsurface or surface...
        # since we use surface_bubble_factor to expand dsurf range below we often win but really this is a bug
        # NOT_YET dsurf = log_f.data['$D_FINISH'] # [m]
        #    pass
        # except KeyError:
        #    pass

        # Determine when various events occured during the dive and climb using the GC record
        gc_st_secs = np.array(log_f.gc_data["st_secs"])
        gc_end_secs = np.array(log_f.gc_data["end_secs"])
        gc_vbd_secs = np.array(log_f.gc_data["vbd_secs"])
        # TODO Move to the new payload sent to extensions
        gc_vbd_ctl = np.array(log_f.gc_data["vbd_ctl"])
        gc_pitch_secs = np.array(log_f.gc_data["pitch_secs"])  # How long any pitch ran
        gc_roll_secs = np.array(log_f.gc_data["roll_secs"])  # How long any roll ran
        num_gc_events = len(gc_st_secs)

        # For RevE, look through the start and ending pot positions to determine if the VBD move was a bleed,
        # and if so, make the vbd_secs negative like the RevB code
        if log_f.version >= 67.0:
            vbd_ad_start = np.array(log_f.gc_data["vbd_ad_start"])
            vbd_ad_end = np.array(log_f.gc_data["vbd_ad"])
            for ii in range(num_gc_events):
                if gc_vbd_secs[ii] > 0 and vbd_ad_end[ii] > vbd_ad_start[ii]:
                    gc_vbd_secs[ii] *= -1.0

        # Find various apogee and climb pump times and the total time spend
        # between apogee pump and the end of the climb pump.  These points
        # are not in steady flight (can even be drifting) and so TSV can't
        # trust those speeds to correct salinity.
        apogee_pump_start_time = None  # elapsed secs when apogee GC started
        apo_gc_i = None  # index of the apogee pump gc, if any due to recovery
        start_of_climb_time = None  # elapsed seconds when the first climb pump started
        climb_pump_gc_i = None  # index of the climb pump gc, if any due to recovery
        apogee_climb_pump_end_time = None  # elapsed secs when the full 'apogee+liter+climb_pump' manuever finished

        if num_gc_events:
            # Find the GCs where we both pump and change pitch.
            # The first is the apogee pitch and pump (since we only bleed, at best, during dive)
            # The second is the climb pump is the move to pitch desired and the initial pump
            # In between there could be some non-zero time 'loitering'
            # This could be explicit $T_LOITER (conditioned on $N_LOITER) or just delays because
            # of logger devices stopping the 'a' profile and starting the 'b' profile
            apo_cp_gc_i = list(
                filter(
                    lambda gc_i: gc_pitch_secs[gc_i] > 0 and gc_vbd_secs[gc_i] > 0,
                    range(1, num_gc_events),
                )
            )
            if len(apo_cp_gc_i) > 0:
                apo_gc_i = apo_cp_gc_i[0]
                apogee_pump_start_time = gc_st_secs[apo_gc_i] - i_eng_file_start_time
                apogee_pump_vbd_end_time = (
                    apogee_pump_start_time
                    + gc_pitch_secs[apo_gc_i]
                    + gc_vbd_secs[apo_gc_i]
                )
                apogee_climb_pump_end_time = (
                    gc_end_secs[apo_gc_i] - i_eng_file_start_time
                )
                if len(apo_cp_gc_i) > 1:
                    climb_pump_gc_i = apo_cp_gc_i[1]
                    start_of_climb_time = (
                        gc_st_secs[climb_pump_gc_i] - i_eng_file_start_time
                    )
                    apogee_climb_pump_end_time = (
                        gc_end_secs[climb_pump_gc_i] - i_eng_file_start_time
                    )
                else:
                    log_warning("Can't find the climb pump!")
            else:
                log_warning("Can't find the apogee pump!")
        else:
            directives.suggest(
                "skip_profile%% Missing $GC records; truncated log file?"
            )
            log_error("No $GC records; truncated dive? - bailing out")
            raise RuntimeError(True)

        if auxcompass_present and (
            base_opts.auxmagcalfile or "auxmagcalfile_contents" in globals_d
        ):
            # Now see if we can actually correct headings
            try:
                try:
                    Mx = results_d["auxCompass_Mx"]
                    My = results_d["auxCompass_My"]
                    Mz = results_d["auxCompass_Mz"]
                except:
                    log_error(
                        "auxCompass correction requested, but magnetometer data missing - skipping corrections",
                        "exc",
                    )
                    raise
                try:
                    head = results_d["auxCompass_hdg"]
                    pitch = results_d["auxCompass_pit"]
                    roll = results_d["auxCompass_rol"]
                except:
                    log_error(
                        "auxCompass correction requested, but pitch/roll missing - skpping corrections",
                        "exc",
                    )
                    raise
            except Exception:
                pass
            else:
                pitch_ctl = eng_f.get_col("pitchCtl")
                if pitch_ctl is None:
                    # TODO For RevE and DG - this column will need to be created
                    pitchAD_interp = None
                else:
                    # For DG - interpolate onto the compass time grid
                    pitchAD = np.fix(
                        pitch_ctl * log_f.data["$PITCH_CNV"] + log_f.data["$C_PITCH"]
                    )
                    pitchAD_interp = Utils.interp1d(
                        sg_epoch_time_s_v,
                        pitchAD,
                        results_d["auxCompass_time"],
                        kind="linear",
                    )

                new_head = correct_heading(
                    "Aux compass",
                    globals_d,
                    base_opts.auxmagcalfile,
                    "auxmagcalfile_contents",
                    "scicon.tcm",
                    base_opts.mission_dir,
                    Mx,
                    My,
                    Mz,
                    head,
                    pitch,
                    roll,
                    pitchAD_interp,
                )
                if new_head is not None:
                    results_d["auxCompass_hdg"] = new_head

        # Assumptions on auxCompass and auxPressure
        #
        # auxPressure may be present without auxCompass data.
        #
        # If both auxPressure and auxCompass are present, they are always on the same time grid
        # There may be cases where we choose to fall back on the gliders compass (sparton of otherwise) even if the auxCompass is present
        #
        vehicle_heading_mag_degrees_v = vehicle_pitch_degrees_v = (
            vehicle_roll_degrees_v
        ) = None
        if use_auxcompass:
            vehicle_heading_mag_degrees_v = results_d["auxCompass_hdg"]
            vehicle_pitch_degrees_v = results_d["auxCompass_pit"]
            vehicle_roll_degrees_v = results_d["auxCompass_rol"]
            bad_i_v = [
                i
                for i in range(len(vehicle_pitch_degrees_v))
                if np.isnan(vehicle_pitch_degrees_v[i])
            ]
            if len(bad_i_v):
                log_warning(
                    "auxcompass invalid out for %d of %d points - interpolating bad points"
                    % (len(bad_i_v), len(vehicle_pitch_degrees_v))
                )
                nans, x = Utils.nan_helper(vehicle_heading_mag_degrees_v)
                vehicle_heading_mag_degrees_v[nans] = np.interp(
                    x(nans), x(~nans), vehicle_heading_mag_degrees_v[~nans]
                )

                nans, x = Utils.nan_helper(vehicle_pitch_degrees_v)
                vehicle_pitch_degrees_v[nans] = np.interp(
                    x(nans), x(~nans), vehicle_pitch_degrees_v[~nans]
                )

                nans, x = Utils.nan_helper(vehicle_roll_degrees_v)
                vehicle_roll_degrees_v[nans] = np.interp(
                    x(nans), x(~nans), vehicle_roll_degrees_v[~nans]
                )

                # vehicle_heading_mag_degrees_v = vehicle_pitch_degrees_v = vehicle_roll_degrees_v = None
            compass_time = results_d["auxCompass_time"]
        else:
            compass_time = sg_epoch_time_s_v
            vehicle_heading_mag_degrees_v = eng_f.get_col("head")
            vehicle_pitch_degrees_v = eng_f.get_col("pitchAng")
            vehicle_roll_degrees_v = eng_f.get_col("rollAng")
            bad_i_v = [i for i in range(sg_np) if np.isnan(vehicle_pitch_degrees_v[i])]
            if len(bad_i_v):
                log_warning(
                    "Compass invalid out for %d of %d points - interpolating bad points"
                    % (len(bad_i_v), sg_np)
                )
                try:
                    nans, x = Utils.nan_helper(vehicle_heading_mag_degrees_v)
                    if vehicle_heading_mag_degrees_v[~nans].size == 0:
                        log_error("No valid compass points found - unable to proceed")
                        return (1, None)

                    vehicle_heading_mag_degrees_v[nans] = np.interp(
                        x(nans), x(~nans), vehicle_heading_mag_degrees_v[~nans]
                    )

                    nans, x = Utils.nan_helper(vehicle_pitch_degrees_v)
                    vehicle_pitch_degrees_v[nans] = np.interp(
                        x(nans), x(~nans), vehicle_pitch_degrees_v[~nans]
                    )

                    nans, x = Utils.nan_helper(vehicle_roll_degrees_v)
                    vehicle_roll_degrees_v[nans] = np.interp(
                        x(nans), x(~nans), vehicle_roll_degrees_v[~nans]
                    )
                except Exception as exception:
                    log_error(
                        f"Failed interpolating bad compass points - [{exception}]"
                    )
                    return (1, None)
            try:
                # The pitch roll calibration applied to the Sparton compass from 2005 to mid-2012
                # distorted the true pitch, which has implications for the speed of the vehicle,
                # hence other corrections.  It turns out the that native compass measurement, based
                # on the accelerometers, was quite good.  Invert the corrected pitch and use the
                # compass measured value instead
                pitch_coef0 = calib_consts["sparton_pitch0"]
                pitch_coef1 = calib_consts["sparton_pitch1"]
                pitch_coef2 = calib_consts["sparton_pitch2"]
                pitch_coef3 = calib_consts["sparton_pitch3"]
                log_info("Reverting to measured compass pitch")
                vehicle_pitch_degrees_v = Utils.invert_sparton_correction(
                    vehicle_pitch_degrees_v,
                    vehicle_roll_degrees_v,
                    pitch_coef0,
                    pitch_coef1,
                    pitch_coef2,
                    pitch_coef3,
                )
                # If, for some reason you wanted to correct roll, here is the expression, takes the (now)
                # measured pitch and the roll coefficients, which you'll need to unpack as above
                # vehicle_roll_degrees_v  = Utils.invert_sparton_correction(vehicle_roll_degrees_v, vehicle_pitch_degrees_v, roll_coef0, roll_coef1, roll_coef2, roll_coef3)

                # What about headings? While we could have the change in pitch and roll from above, we don't know the magnitude of the
                # field vector we rotated in the first place to get the XY projection for heaing.  Without the field magnitudes recorded
                # we can't estimate the (lost) Z component of that vector, so heading is underdetermined.
                # TODO This might be possible if we knew the declination and mag at the lat of the samples.  Could get this
                # from the NOAA IGRF site, for example.
            except KeyError:
                pass  # no correction requested

        # In the case of assembly error, the compass can sometimes be rotated by increments of 45 degrees, yielding rolls with a bias (sg215 PS 030414)
        vehicle_roll_degrees_v = vehicle_roll_degrees_v - calib_consts["rollbias"]
        # if False:  # Expose this code to restate the raw roll data into the nc file
        #     eng_f.data[
        #         :, eng_f.columns.index("rollAng")
        #     ] = vehicle_roll_degrees_v  # restate the original data

        # NOTE: labsea/sep04/sg015 had pitch sensor issues dives 331:end
        # Eleanor regressed a replacement pitch based on pitch_control based on the initial dives
        # this would require code here to restate pitch = <gain>*eng_f.get_col('pitchCtl') - calib_consts['pitchbias']
        vehicle_pitch_degrees_v = vehicle_pitch_degrees_v - calib_consts["pitchbias"]
        # Convert observed vehicle pitch from degrees to radians
        vehicle_pitch_rad_v = np.radians(vehicle_pitch_degrees_v)

        # if deck_dive and log_f.data["$SIM_PITCH"] > 0:
        #    log_warning("$SIM_PITCH set incorrectly; inverting pitch values")
        #    vehicle_pitch_rad_v = np.negative(vehicle_pitch_rad_v)
        #    vehicle_pitch_degrees_v = np.negative(vehicle_pitch_degrees_v)

        # Correct the heading?
        if base_opts.magcalfile or ("magcalfile_contents" in globals_d):
            Mx = eng_f.get_col("mag_x")
            My = eng_f.get_col("mag_y")
            Mz = eng_f.get_col("mag_z")
            if Mx is None or My is None or Mz is None:
                log_error(
                    "Could not find magnetometer data - skipping heading corrections"
                )
            else:
                pitch_ctl = eng_f.get_col("pitchCtl")
                if pitch_ctl is None:
                    pitchAD = None
                else:
                    pitchAD = np.fix(
                        pitch_ctl * log_f.data["$PITCH_CNV"] + log_f.data["$C_PITCH"]
                    )

                new_head = correct_heading(
                    "Truck compass",
                    globals_d,
                    base_opts.magcalfile,
                    "magcalfile_contents",
                    "tcm2mat.cal",
                    base_opts.mission_dir,
                    Mx,
                    My,
                    Mz,
                    vehicle_heading_mag_degrees_v,
                    vehicle_pitch_degrees_v,
                    vehicle_roll_degrees_v,
                    pitchAD,
                )
                if new_head is not None:
                    vehicle_heading_mag_degrees_v = new_head
                    head_index = eng_f.columns.index("head")
                    eng_f.data[:, head_index] = (
                        new_head  # Update heading with the improved version of heading
                    )

        vbdCC_v = eng_f.get_col("vbdCC")
        if vbdCC_v is None:
            # For version 67.00 and later, the vbdCC needs to be derived from the gc table in the log file

            # A note on pitch and roll: If we ever decide to drop pitchCtl and
            # rollCtl from the asc/eng files and recompute their position ala
            # VBD be aware that with the TTI mass-shifter there is a tendency
            # for the pitch mass to 'jitter' in the direction of gravity often
            # if the vehicle rolls.  Also, there was a timing bug in reporting
            # the GC pitch start AD that misreported by ~1000 AD the actual
            # position.  Old dives might exhibit problems here.

            # Now, back to recapturing VBD positions:

            # You might think that a nearest interpolation is fast and good enough but, well, not quite.
            # A 1% error is ~8cc, we'd like ~1+/-0cc for buoyancy and speed calculationss.
            # Ignoring the first bleed, sg189 sep12 SPURS dives:
            #   - simple nearest interpolation yields 2+/-10cc
            #   - the following code yields ~0.1+/-1.5cc.

            # These values depend completely on how many VBD moves there are
            # (this is were nearest is most incorrect)--fewer on average for
            # longer, well-tuned deployments.

            # During VBD moves we need to interpolate changing CC. And sometimes
            # between GCs the vbd system 'relaxes' so we need to linearly
            # interpolate within and between each GC with its starting and
            # ending AD in order to reduce the nominal error.

            # We need to be careful about when the VBD system actually moves,
            # which is NOT the start and end times of the GC but depends on the
            # sequence of motor moves for that GC.

            # And, finally, in old files, we have to guess about the starting AD
            # for the dive since it isn't recorded in the log.

            # Respecting all these observations, we actually get quite close
            # (<<1CC except for old dives during first bleed GC only).  Any thus
            # we can feel confident in providing the eng_vbdCC variable
            gc_roll_ad = np.array(
                log_f.gc_data["roll_ad"]
            )  # Where the roll system was at the end of a GC

            # Map over each GC and determine the starting and ending AD and the starting and ending time of the VBD move, if any
            n_gc = num_gc_events * 2
            gc_vbd_times_v = np.zeros(n_gc, np.float64)
            gc_ad_v = np.zeros(n_gc, np.float64)
            if "vbd_pot1_ad_start" in log_f.gc_data:  # new style log file?
                gc_start_vbd_ad_available = True
                try:
                    vbd_lp_ignore = log_f.data["$VBD_LP_IGNORE"]
                except KeyError:
                    vbd_lp_ignore = 0  # both available

                # compute VBD move start and end; don't trust gc_vbd_ad as ending point
                if vbd_lp_ignore == 0:
                    gc_start_vbd_ad_v = (
                        np.array(log_f.gc_data["vbd_pot1_ad_start"])
                        + np.array(log_f.gc_data["vbd_pot2_ad_start"])
                    ) / 2
                    gc_vbd_ad = (
                        np.array(log_f.gc_data["vbd_pot1_ad"])
                        + np.array(log_f.gc_data["vbd_pot2_ad"])
                    ) / 2
                elif vbd_lp_ignore == 1:  # ignore pot1?
                    gc_start_vbd_ad_v = np.array(log_f.gc_data["vbd_pot2_ad_start"])
                    gc_vbd_ad = np.array(log_f.gc_data["vbd_pot2_ad"])
                elif vbd_lp_ignore == 2:  # ignore pot2?
                    gc_start_vbd_ad_v = np.array(log_f.gc_data["vbd_pot1_ad_start"])
                    gc_vbd_ad = np.array(log_f.gc_data["vbd_pot1_ad"])
                else:
                    log_error(
                        "Unknown value for $VBD_LP_IGNORE: %d - bailing out"
                        % log_f.data["$VBD_LP_IGNORE"]
                    )
                    raise RuntimeError(True)
            else:
                gc_start_vbd_ad_available = False
                gc_start_vbd_ad_v = None
                gc_vbd_ad = np.array(
                    log_f.gc_data["vbd_ad"]
                )  # Where the VBD system was at the end of a GC

            for gc in range(0, num_gc_events):
                st_i = 2 * gc + 0
                en_i = 2 * gc + 1

                # Initially assume the start and stop AD are valid at the start and stop time of the GC (correct if no VBD move)
                gc_vbd_times_v[st_i] = gc_st_secs[gc]
                gc_vbd_times_v[en_i] = gc_end_secs[gc]
                # But if we had a VBD move we need to adjust the start and stop times
                vbd_secs = np.abs(gc_vbd_secs[gc])
                if vbd_secs > 0:
                    # Motor move order tells us when the VBD ran:
                    # If 'rollback' the move order is ROLL, PITCH, VBD
                    # Else the move order is PITCH, VBD, ROLL
                    # Look at (final) roll_ad: if near zero (dive/climb) and there were roll_secs, then we rolled back
                    rollback = False
                    if gc_roll_secs[gc] > 0:  # We rolled during this GC...was it back?
                        # An alternative to this calculation is a toggling flag that starts at rollback=False at start of dive
                        # and toggles ON EACH ROLL.  And then reset at the first pump, assumed apogee,
                        # where rollback is forced without recording any gc_roll_secs
                        # This code has the virtue of only looking for rollbacks where we bleed and pump
                        if (
                            start_of_climb_time is None
                            or gc_st_secs[gc] - i_eng_file_start_time
                            < start_of_climb_time
                        ):
                            roll_center = log_f.data["$C_ROLL_DIVE"]
                        else:
                            roll_center = log_f.data["$C_ROLL_CLIMB"]
                        if (
                            np.abs(gc_roll_ad[gc] - roll_center) < 100
                        ):  # PARAMETER we generally get near center
                            rollback = True
                    if rollback:
                        gc_vbd_times_v[st_i] = (
                            gc_st_secs[gc] + gc_roll_secs[gc] + gc_pitch_secs[gc]
                        )
                    else:
                        gc_vbd_times_v[st_i] = gc_st_secs[gc] + gc_pitch_secs[gc]
                    gc_vbd_times_v[en_i] = (
                        gc_vbd_times_v[st_i] + vbd_secs
                    )  # end time of VBD move

                # We always know where the AD finished (which may have drifted since last actual move)
                gc_ad_v[en_i] = gc_vbd_ad[gc]  # ending AD

                # What we don't always know is where we started...
                if gc_start_vbd_ad_available:
                    gc_ad_v[st_i] = gc_start_vbd_ad_v[gc]
                else:  # Old system.
                    if gc == 0:
                        pass  # handle first bleed below...
                    else:
                        gc_ad_v[st_i] = gc_vbd_ad[
                            gc - 1
                        ]  # assume starting AD is where the last one ended (could have 'relaxed')

            if not gc_start_vbd_ad_available:
                # Need to estimate starting AD during the first bleed for an old data set...
                # If we knew where SM_CC of the last dive ended we could plug that in as very start AD but no...
                if (
                    num_gc_events > 1 and gc_vbd_secs[1] < 0
                ):  # do we have a second bleed GC?
                    # estimate the bleed rate from it
                    coefficients = np.polyfit(gc_vbd_times_v[2:4], gc_ad_v[2:4], 1)
                    bleed_rate = np.abs(coefficients[0])
                else:
                    try:
                        # VBD_BLEED_AD_RATE is a (typically) low bound for error triggering... guess a scale factor
                        bleed_rate = 3 * log_f.data["$VBD_BLEED_AD_RATE"]  # PARAMETER
                    except KeyError:
                        bleed_rate = 30.0  # PARAMETER -- nominal
                gc_ad_v[0] = gc_ad_v[1] - bleed_rate * np.abs(
                    gc_vbd_secs[1]
                )  # estimate the starting AD
                # Generally we pump back up to where we started at least, if not more (handles small estimated bleed rates)
                # But ensure we go no lower than the vbd min
                gc_ad_v[0] = max(
                    min(min(gc_vbd_ad), gc_ad_v[0]), log_f.data["$VBD_MIN"]
                )

            # Convert these AD values to CC
            gc_vbdcc_v = (gc_ad_v - log_f.data["$C_VBD"]) * log_f.data[
                "$VBD_CNV"
            ]  # convert ad to cc relative to center

            # Map over successive pairs of start and ending points and interpolate onto impacted sg_epoch_time_s_v points
            # Coded to be a linear pass
            vbdCC_v = np.zeros(sg_np, np.float64)
            last_gc_i = 0
            for st_i in range(0, n_gc - 1):
                en_i = st_i + 1
                # Too expensive:
                # DEAD sg_i_v = list(filter(lambda i:sg_epoch_time_s_v[i] >= gc_vbd_times_v[st_i] and sg_epoch_time_s_v[i] <= gc_vbd_times_v[en_i], xrange(last_gc_i,sg_np)))
                # Open-code instead to make linear
                sg_i_v = []
                for i in range(last_gc_i, sg_np):
                    if sg_epoch_time_s_v[i] > gc_vbd_times_v[en_i]:
                        break  # found all the sg points during this segment
                    sg_i_v.append(i)

                if len(sg_i_v):  # anything to interpolate?
                    coefficents = np.polyfit(
                        gc_vbd_times_v[st_i : en_i + 1], gc_vbdcc_v[st_i : en_i + 1], 1
                    )  # linear fit
                    vbdCC_v[sg_i_v] = np.polyval(coefficents, sg_epoch_time_s_v[sg_i_v])
                    last_gc_i = sg_i_v[-1] + 1  # restart search for next time bunch
            # Finally, extend any tail...
            if last_gc_i < sg_np:
                vbdCC_v[last_gc_i:] = gc_vbdcc_v[-1]

            # HACK: Cache these results to the netcdf file as though it came on the eng file
            # This supports many matlab scripts that assume it is there
            results_d.update(
                {"eng_vbdCC": np.copy(vbdCC_v)}
            )  # copy since we modify vbdCC_v below

            # Done with these intermediates
            del gc_vbdcc_v, gc_ad_v, gc_vbd_times_v

        vbdCC_v -= calib_consts["vbdbias"]

        # In the absence of a CT (because on scicon and files not yet received etc.)
        # CONSIDER computing gsm velocities, start of dive, DAC based on gsm, displacements, etc.
        # and conditioning sensors to check of CT available....basically not a fatal error
        # at least the pilot can see via diveplot how the vehicle flew, trim etc.

        # --- compute CT and start QC ---
        # Prepare to record different QC levels

        # Decisions about 'QC_BAD' samples incorporates two things: truly
        # unbelievable data and, more often, data that we can't trust to
        # base our salinity and velocity recovery calculations upon.  This
        # is because the recovery (TSV) code relies on a hydrodynamic flow
        # model of both the vehicle and CTD tube that assumes
        # unaccelerated and steady flight.  So we try to find places where
        # those assumptions are unlikey and remove them.  Some places are
        # obvious: when we are accelerating away from the surface before
        # flaring, when we are pumping at the apogee of the dive, and when
        # we inevitably slow down at the top of the climb.  These are
        # complicated things that could compromise the conductivity and
        # temperature readings (bubbles, GC maneuvers, snot), some of
        # which we might be able to interpolate over and others we need to
        # simply remove.  The reduced set of points is passed to TSV to
        # find a consistent temperature/salinity and (via the implied sea
        # water density and vehicle buoyancy) a vehicle velocity solution.

        # To this end, there are several instruments aboard that we trust
        # more than others: the timing clock, the pressure sensor and the
        # thermistor.  Not that these instruments don't have their
        # problems (hysteresis effects, electrical noise, esp during GC)
        # but these are rare.  They have known error ranges and they are
        # small (TODO what are they?).  The conductivity sensor is prone
        # to getting clogged sometimes so we try to detect and handle
        # these situations.

        # We also assume the compass info for headings and pitch/roll is
        # reasonably accurate for purposes of underwater navigation and
        # reconstruction of key flight parameters (notably pitch) in the
        # derived buoyancy field so we can recover flight velocities and
        # hence geostrophic velocities.

        #
        # Sources for C and T
        #
        # With the advent of new CT sensors, there are two places to get CT data from:
        # 1) The Seaglider eng file
        # 2) A logger device that is sampling CT - in which case, the data will need to be gridded onto
        #    the vehicle science grid to perform the downstream calculations
        #

        # We want to reference T/S to the thermistor tip....
        # Adjust the depths and pressures according pressure at CT sensor, not pressure sensor
        # Compute depth difference between pressure sensor and CT depending on observered vehicle pitch (not glide angle?)
        # TODO: If we come to trust the auxCompass, use its higher frequency pitch values to compute this...
        ct_delta_x = calib_consts["glider_xT"] - calib_consts["glider_xP"]  # [m]
        ct_delta_z = calib_consts["glider_zT"] - calib_consts["glider_zP"]  # [m]
        zTP = ct_delta_x * np.sin(vehicle_pitch_rad_v) + ct_delta_z * np.cos(
            vehicle_pitch_rad_v
        )  # [m]

        ctd_ancillary_variables = ""

        log_info("ct_type:%s" % sb_ct_type_map[sg_ct_type])
        # Not checking every combination, but catch a common case in the
        # Seabird to legato migration
        if sg_ct_type in (0, 1) and (
            any([x.startswith("legato_") for x in results_d])
            or any([x.startswith("rbr_") for x in results_d])
        ):
            log_error(
                f"sg_ct_type={sg_ct_type}, but found legato data.  Set sg_ct_type=4; in sg_calib_constants.m to correct",
                alert="INCORRECT_CT",
            )

        sbect_unpumped = calib_consts["sbect_unpumped"]
        have_scicon_ct = False

        # Overritten by rbr on the truck, otherwise set below
        salin_raw_qc_v = None
        salin_raw_v = None

        ### Begin CTD init

        try:
            if sg_ct_type == 4:
                ## UnPumped RBR Legato data ##
                rbr_good_press_i_v = None
                if set(
                    ("legato_pressure", "legato_temp", "legato_conduc", "legato_time")
                ) <= set(results_d):
                    # Scicon case
                    try:
                        tmp_press_v = results_d["legato_pressure"]
                        ctd_temp_v = results_d["legato_temp"]
                        ctd_cond_v = results_d["legato_conduc"] / 10.0
                        ctd_condtemp_v = results_d["legato_conducTemp"]
                        ctd_epoch_time_s_v = results_d["legato_time"]
                    except KeyError as e:
                        log_error(
                            f"Legato CT scicon data found, but had problems loading {e} - bailing out"
                        )
                        raise RuntimeError(True) from e

                    ctd_np = len(ctd_epoch_time_s_v)
                    ctd_temp_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_cond_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_salin_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_press_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                else:
                    # Truck case
                    ctd_temp_v = eng_f.get_col("rbr_temp")
                    ctd_cond_v = eng_f.get_col("rbr_conduc")
                    ctd_condtemp_v = eng_f.get_col("rbr_conducTemp")
                    if ctd_cond_v is not None:
                        ctd_cond_v /= 10.0
                    ctd_epoch_time_s_v = sg_epoch_time_s_v.copy()
                    if (
                        ctd_temp_v is None
                        or ctd_cond_v is None
                        or ctd_condtemp_v is None
                        or ctd_epoch_time_s_v is None
                    ):
                        log_error(
                            "Legato CT data specified, but no data found for scicon or truck - bailing out"
                        )
                        raise RuntimeError(True)

                    ctd_np = len(ctd_epoch_time_s_v)
                    ctd_temp_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_cond_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_salin_qc = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_press_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)

                    tmp_press_v = eng_f.get_col("rbr_pressure")
                    rbr_good_press_i_v = np.logical_not(np.isnan(tmp_press_v))
                    # Smooth through the unsampled/bad points for remaining calcs
                    if len(np.squeeze(np.nonzero(rbr_good_press_i_v))) < 2:
                        log_warning("No non-nan rbr_pressure - skipping interpolation")
                        rbr_good_press_i_v = None
                    else:
                        tmp_press_v = Utils.interp1d(
                            eng_f.get_col("elaps_t")[rbr_good_press_i_v],
                            eng_f.get_col("rbr_pressure")[rbr_good_press_i_v],
                            eng_f.get_col("elaps_t"),
                            kind="linear",
                        )
                        # Defer QC update until after the decision on using the truck pressure sensor

                    # Note: this marks both unsampled and timeouts as "Legato unsampled"
                    unsampled_i = np.nonzero(np.isnan(ctd_temp_v))[0]
                    QC.assert_qc(
                        QC.QC_UNSAMPLED, ctd_temp_qc, unsampled_i, "Legato unsampled"
                    )
                    QC.assert_qc(
                        QC.QC_UNSAMPLED, ctd_cond_qc, unsampled_i, "Legato unsampled"
                    )
                    QC.assert_qc(
                        QC.QC_UNSAMPLED, ctd_salin_qc, unsampled_i, "Legato unsampled"
                    )

                # CONSIDER: should we support kistler cnf files in case?
                sg_press_v = (
                    eng_f.get_col("depth")
                    * cm2m
                    * calib_consts["depth_slope_correction"]
                    - calib_consts["depth_bias"]
                ) * psi_per_meter
                sg_press_v *= dbar_per_psi  # convert to dbar
                if not base_opts.use_gsw:
                    sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
                else:
                    sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)

                results_d.update(
                    {
                        "pressure": sg_press_v,
                        "depth": sg_depth_m_v,
                    }
                )

                # Handle pressure spikes in legato pressure signal
                if tmp_press_v is None or calib_consts["legato_use_truck_pressure"]:
                    # Reset QC here because of new source
                    # TODO - when sg_press_v_qc is added - propagate that from there to here
                    ctd_press_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                    ctd_press_v = Utils.interp1d(
                        sg_epoch_time_s_v, sg_press_v, ctd_epoch_time_s_v, kind="linear"
                    )
                    if calib_consts["legato_use_truck_pressure"]:
                        log_info(
                            "Using Truck pressure sensor instead of legato pressure sensor"
                        )
                        # TODO - Need a ztp correction for this case
                        pass
                    results_d.update({"ctd_pressure_qc": ctd_press_qc_v})
                else:
                    if rbr_good_press_i_v is not None:
                        # From rbr on the truck
                        QC.assert_qc(
                            QC.QC_UNSAMPLED,
                            ctd_press_qc_v,
                            np.nonzero(np.logical_not(rbr_good_press_i_v))[0],
                            "Legato interpolated",
                        )

                    ctd_press_v, bad_points = QC.smooth_legato_pressure(
                        tmp_press_v, ctd_epoch_time_s_v
                    )
                    QC.assert_qc(
                        QC.QC_INTERPOLATED,
                        ctd_press_qc_v,
                        bad_points,
                        "despiked pressure",
                    )
                    results_d.update({"ctd_pressure_qc": ctd_press_qc_v})

                if not base_opts.use_gsw:
                    ctd_salin_v = seawater.salt(
                        ctd_cond_v / c3515, ctd_temp_v, ctd_press_v
                    )  # temporary, not the real salinity raw
                    ctd_depth_m_v = seawater.dpth(
                        ctd_press_v, latitude
                    )  # initial depth estimate
                else:
                    ctd_salin_v = gsw.SP_from_C(
                        ctd_cond_v * 10.0, ctd_temp_v, ctd_press_v
                    )  # temporary, not the real salinity raw
                    ctd_depth_m_v = -1.0 * gsw.z_from_p(
                        ctd_press_v, latitude, 0.0, 0.0
                    )  # initial depth estimate

                # CONSIDER - this may not be entirely correct for legato
                temp_raw_qc_v, cond_raw_qc_v, salin_raw_qc_v = QC.qc_checks(
                    ctd_temp_v,
                    ctd_temp_qc,
                    ctd_cond_v,
                    ctd_cond_qc,
                    ctd_salin_v,
                    ctd_salin_qc,
                    ctd_depth_m_v,
                    calib_consts,
                    QC.QC_BAD,
                    QC.QC_NO_CHANGE,
                    "raw legato ",
                )
                # Map to names used in rest of code
                temp_raw_v = ctd_temp_v.copy()
                cond_raw_v = ctd_cond_v.copy()
                salin_raw_v = ctd_salin_v.copy()

                ctd_results_dim = BaseNetCDF.nc_mdp_data_info[
                    BaseNetCDF.nc_legato_data_info
                ]

                # For Legato we don't correct their pressure sensor so we just take it as is
                # and assume the pressure/depth is wrt thermistor already. So no zTP correction here

                # Done w/ these vars...
                del ctd_temp_v, ctd_cond_v, ctd_salin_v

                ## End Legatto ##

            elif sbect_unpumped:
                ## Regular sbect sensor ##

                # First - see if we have scicon data...
                # Why not eng file first you ask?  Read and weep below...
                try:
                    # scicon unpumped SBECT
                    ctd_epoch_time_s_v = results_d["sbect_time"]
                    tempFreq_v = results_d["sbect_tempFreq"]
                    condFreq_v = results_d["sbect_condFreq"]
                    have_scicon_ct = True
                    # CONSIDER use scicon 'depth_depth', converted to 'sbect_time' as the ctd_depth??

                    ctd_results_dim = BaseNetCDF.nc_mdp_data_info[
                        BaseNetCDF.nc_sbect_data_info
                    ]
                except KeyError as e:
                    # Next, try for the glider eng file
                    (_, tempFreq_v) = eng_f.find_col(
                        ["tempFreq", "sbect_tempFreq", "sailct_tempFreq"]
                    )
                    (_, condFreq_v) = eng_f.find_col(
                        ["condFreq", "sbect_condFreq", "sailct_condFreq"]
                    )
                    if tempFreq_v is None and condFreq_v is None:
                        log_error("No CT data found - bailing out")
                        raise RuntimeError(True) from e
                    ctd_results_dim = BaseNetCDF.nc_mdp_data_info[
                        BaseNetCDF.nc_sg_data_info
                    ]
                    ctd_epoch_time_s_v = sg_epoch_time_s_v
                # TODO: ensure sg_epoch_time_s_v and ctd_epoch_time_s_v overlap substantially (SG189 'test' dive 99 in hibay)
                # MDP automatically asserts instrument when writing
                # DEAD results_d['sbe41'] = 'unpumped Seabird SBE41' # record the instrument used for CTD
                ctd_np = len(ctd_epoch_time_s_v)

                # Initially all is well...
                temp_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                cond_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)

                # Adjust temp and cond freq, if any
                if calib_consts["sbe_temp_freq_offset"]:
                    tempFreq_v = tempFreq_v + calib_consts["sbe_temp_freq_offset"]
                    ctd_ancillary_variables = (
                        ctd_ancillary_variables + " sg_cal_sbe_temp_freq_offset"
                    )

                bad_i_v = [i for i in range(ctd_np) if np.isnan(tempFreq_v[i])]
                QC.assert_qc(
                    QC.QC_UNSAMPLED, temp_raw_qc_v, bad_i_v, "unsampled temperature"
                )

                # Warn on attemped use of old temp freq limit types
                try:
                    if (
                        calib_consts["sbe_temp_freq_min"]
                        or calib_consts["sbe_temp_freq_max"]
                    ):
                        log_warning(
                            "Ignoring temperature frequency limits - use QC_temp_min and QC_temp_max instead."
                        )
                except KeyError:
                    pass

                bad_i_v = [i for i in range(ctd_np) if np.isnan(condFreq_v[i])]
                QC.assert_qc(
                    QC.QC_UNSAMPLED, cond_raw_qc_v, bad_i_v, "unsampled conductivity"
                )

                # Warn on attemped use of old cond freq limit types
                try:
                    if (
                        calib_consts["sbe_cond_freq_min"]
                        or calib_consts["sbe_cond_freq_max"]
                    ):
                        # or QC_salin_min/max (PSU)
                        log_warning(
                            "Ignoring conductivity frequency limits - use QC_cond_min and QC_cond_max instead."
                        )
                except KeyError:
                    pass

                # Convert temperature and conductivity frequenceies to initial temperatures and conductivities
                # before applying first-order lag and thermal-inertia corrections below
                # Compute temperature first so we can compute pressure properly before computing conductivity

                # pylint: disable=unbalanced-tuple-unpacking
                t_g, t_h, t_i, t_j, vars_used = SBECT_coefficents(
                    "temperature",
                    calib_consts,
                    log_f,
                    ["t_g", "t_h", "t_i", "t_j"],
                    ["$SEABIRD_T_G", "$SEABIRD_T_H", "$SEABIRD_T_I", "$SEABIRD_T_J"],
                )
                # pylint: enable=unbalanced-tuple-unpacking
                ctd_ancillary_variables = ctd_ancillary_variables + vars_used

                LogTempFreqScaled_v = np.log(f0 / tempFreq_v)
                temp_raw_v = (
                    1.0
                    / (
                        t_g
                        + (
                            t_h
                            + (t_i + t_j * LogTempFreqScaled_v) * LogTempFreqScaled_v
                        )
                        * LogTempFreqScaled_v
                    )
                ) - Kelvin_offset

                # Hack to pull in the optode temperature - used for sg562
                # on the NorEMSO_Iceland 2021 deployment.  Note - assumes
                # optode and CTD are on the truck
                # if False:
                #     # if id_str == "562":
                #     from scipy.interpolate import InterpolatedUnivariateSpline

                #     temp_raw_v = eng_f.get_col("aa4330_Temp")
                #     if False:
                #         # sg_depth = eng_f.get_col("depth")
                #         # temp_raw_v = InterpolatedUnivariateSpline(sg_depth, optode_temp)
                #         elapsed_t = eng_f.get_col("elaps_t")
                #         good_i_v = [i for i in range(ctd_np) if not np.isnan(temp_raw_v[i])]
                #         f = InterpolatedUnivariateSpline(
                #             elapsed_t[good_i_v], temp_raw_v[good_i_v]
                #         )
                #         bad_i_v = [i for i in range(ctd_np) if np.isnan(temp_raw_v[i])]
                #         temp_raw_v[bad_i_v] = f(elapsed_t[bad_i_v])

                #     temp_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                #     bad_i_v = [i for i in range(ctd_np) if np.isnan(temp_raw_v[i])]
                #     QC.assert_qc(
                #         QC.QC_UNSAMPLED, temp_raw_qc_v, bad_i_v, "unsampled temperature"
                #     )

                # The Kistler pressure sensor, used on DGs and some SGs, responds quadratically in pressure and temperature
                # The glider code encodes depth (counts) using a linear transformation.  If we have the proper fit in sgc
                # we invert

                # What if we are using scicon?  We need to know if it was passed through from the glider or separate.
                # We need to know the gain and the (linear) transform used to get pressure from counts

                # With the GPCTD we must use pressure as given

                # eng.depth is psuedo-depth in meters, as computed onboard by SG
                # using pressure gauge and linear conversion.  These values
                # were used for control purposes.

                # The glider code misrepresents depth for a number of reasons related to
                # oversimplification of the hydrostatic relationship, principally because,
                # in decreasing order of importance:

                # 1) the density of seawater @ standard T & S (0 deg C & 35) varies with
                #    pressure (by 2.6% between the surface & 6000 dbar)
                # 2) gravity increases by over 0.5 % between the equator and poles and
                # 3) gravity increases with depth by ~0.1% between the sea surface and 6000 m depth.

                # Because of these variations, using a fixed constant (0.685 m/psi) to estimate depth
                # from pressure can't do better than ~1% in accuracy over the depth range
                # of a Deepglider dive cycle to the ocean floor, considerably worse than
                # the 0.04% accuracy quoted for the Druck 4020 pressure sensor on sg033
                # itself.

                # NOTE: CCE observed that while sw_dpth.m converts from pressure using the
                # accepted equation of state & gravity models, the routine sw_pres
                # simplifies the behavior to a quadratic one between depth and pressure so
                # sw_pres(sw_dpth(pressure, latitude), latitude) returns something that
                # differs by up to 0.4 dbar from pressure from the surface to 6000 dbar.
                press_counts_v = eng_f.get_col(
                    "press_counts"
                )  # returns None if not present
                # Try reading a possibly updated kistler.cnf file; returns None if not present
                kistler_cnf, _ = Utils2.read_cnf_file(
                    "kistler.cnf",
                    mission_dir=base_opts.mission_dir,
                    encode_list=False,
                    lower=False,
                    results_d=results_d,
                )
                sg_temp_raw_v = temp_raw_v
                if kistler_cnf and ctd_np is not sg_np:
                    sg_temp_raw_v = Utils.interp1d(
                        ctd_epoch_time_s_v, temp_raw_v, sg_epoch_time_s_v, kind="linear"
                    )

                if press_counts_v is None:
                    # Recover the depth the SG used onboard (in cm) and recorded at elapsed_time_s_v
                    # Recover sg measured pressure [dbar] from the depth record using any depth bias
                    # First convert from psuedo-meters to psi
                    sg_press_v = (
                        eng_f.get_col("depth")
                        * cm2m
                        * calib_consts["depth_slope_correction"]
                        - calib_consts["depth_bias"]
                    ) * psi_per_meter
                    if kistler_cnf:
                        # Old mission without a kistler.cnf but calibration constructed afterwards
                        press_counts_v = (
                            sg_press_v - log_f.data["$PRESSURE_YINT"]
                        ) / log_f.data["$PRESSURE_SLOPE"]
                        sg_press_v = compute_kistler_pressure(
                            kistler_cnf, log_f, press_counts_v, sg_temp_raw_v
                        )
                        # We can't use the YINT on board (since it was computed wrt to PRESSURE_SLOPE)
                        # TODO compute likely psi at surface and tare to it
                        # We know at the beginning of the dive she is mostly just under water w/ the shoe just exposed
                        # Use surface angle and distance to pressure sensor to compute a new yint for this kistler.cnf (and this dive)
                        shoe_to_pressure_sensor = 1.5  # [m] approximate distance from antenna shoe for all vehicles
                        bleed_time = (
                            60  # takes roughly a minute to bleed and leave the surface
                        )
                        # TODO should ensure it is before time of flare
                        sfc_i = [
                            i for i in range(sg_np) if elapsed_time_s_v[i] <= bleed_time
                        ]
                        computed_yint = (
                            np.mean(sg_press_v[sfc_i])
                            - shoe_to_pressure_sensor
                            * np.sin(np.mean(np.abs(vehicle_pitch_rad_v[sfc_i])))
                            * psi_per_meter
                        )
                        sg_press_v -= computed_yint
                    else:
                        # Original code...take sg_press as-is
                        pass
                else:
                    if kistler_cnf is None:
                        # used kistler onboard but not overriding it here
                        # use pressure that was computed onboard with CT temp with log_f.data['$PRESSURE_YINT']
                        sg_press_v = eng_f.get_col("pressure")
                    else:
                        sg_press_v = compute_kistler_pressure(
                            kistler_cnf, log_f, press_counts_v, sg_temp_raw_v
                        )
                        sg_press_v += log_f.data["$PRESSURE_YINT"]

                sg_press_v *= dbar_per_psi  # convert to dbar
                # Done with these variables
                del press_counts_v, sg_temp_raw_v
                # DEBUG ONLY
                try:
                    prev_sg_press_v = results_d["pressure"]
                    diff_max = max(sg_press_v) - max(prev_sg_press_v)
                    if np.abs(diff_max) > 10:
                        log_info(
                            "Max pressure since last processing changed by %.2f psi"
                            % diff_max
                        )
                    prev_sg_press_v = None
                except KeyError:
                    pass

                # TODO? Argo tests for monotonically increasing (and then, for us, decreasing) pressures
                # They have a sg_press_qc_v and mark QC_BAD any data points that reverse direction
                # Any bad points propagate to T/C/S
                # but since we can stall and even fly down if we want, we avoid this QC test

                # This is the latitude corrected depth given the measure pressure
                # The force of gravity varies by latitude given the oblate spheroid shape and unequal mass distributions in the Earth
                if not base_opts.use_gsw:
                    sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
                else:
                    sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)
                results_d.update(
                    {
                        "pressure": sg_press_v,
                        "depth": sg_depth_m_v,
                    }
                )

                # There are two other possible 'depth' measurements from scicon
                # Both are based on the same pressure sensor used by the glider.

                # The first is 'depth_depth', which is the depth reported from the
                # glider via the logger interface and hence it comes from the AD7714
                # circuit and reflects the slope and yint and conversion factors
                # used by the truck.  In fact, it is an exact copy (well, subset) of
                # truck depth recorded in the depth.dat file just slightly later,
                # using the scicon clock.  Thus, we use sg_depth_m in preference.

                # The second comes from the (optional) so-called 'auxCompass' board
                # attached to the scicon.  This auxillary board can support an
                # auxillary compass and can sample the glider's pressure sensor
                # directly using a different A-to-D circuit. Pressure counts from
                # the sensor are recorded at typically higher frequency than the
                # truck.  For CT processing we use this auxillary pressure (and
                # derived depth, hence ctd_depth), if available, in preference to
                # the truck depth.

                # TestData/Sg187_NANOOS_Jun15 dives 182:788

                ###            # TODO - hoist this out from here
                ###            # Always create auxPressure_press and auxPressure_depth vectors
                ###            if(auxpressure_present):
                ###                auxPress_counts_v = results_d[f'{auxpressure_name}_pressureCounts']
                ###                aux_epoch_time_s_v = results_d[f'{auxpressure_name}_time']
                ###
                ###                # Convert pressure counts to pressure
                ###                if aux_pressure_slope is not None and  aux_pressure_offset is not None:
                ###                    auxCompass_pressure_v = (auxPress_counts_v - aux_pressure_offset) * aux_pressure_slope * dbar_per_psi
                ###                    log_info("auxCompass_pressure_offset = %f, auxCompass_pressure_slope = %f" %
                ###                             (aux_pressure_offset, aux_pressure_slope))
                ###                else:
                ###                    if kistler_cnf is None:
                ###                        auxPress_v = auxPress_counts_v * log_f.data['$PRESSURE_SLOPE'] # [psi]
                ###                    else:
                ###                        aux_temp_v = Utils.interp1d(ctd_epoch_time_s_v, temp_raw_v, aux_epoch_time_s_v, kind='linear')
                ###                        auxPress_v = compute_kistler_pressure(kistler_cnf, log_f, auxPress_counts_v, aux_temp_v) # [psi]
                ###
                ###                    # Why not simply + log_f.data['$PRESSURE_YINT'] to get final pressure?
                ###                    # Because while we trust the conversion slope of the sensor to be independent of sampling scheme,
                ###                    # the log value of yint encodes information about the AD7714, etc.  We need to see how the
                ###                    # aux AD is offset from that and compute an implied yint. So...
                ###                    # Convert glider pressure to PSI and interpolate to aux time grid
                ###                    glider_press_v = Utils.interp1d(sg_epoch_time_s_v, sg_press_v / dbar_per_psi, aux_epoch_time_s_v, kind='linear') # [psi]
                ###                    # Adjust for yint based on truck values
                ###                    # Note - this will go very wrong if you only have a half profile
                ###                    auxPress_yint = -np.mean(auxPress_v - glider_press_v)
                ###                    log_info("auxPress_yint = %f, $PRESSURE_YINT = %f (%f psi)" %
                ###                             (auxPress_yint, log_f.data['$PRESSURE_YINT'], (auxPress_yint - log_f.data['$PRESSURE_YINT'])))
                ###
                ###                    auxCompass_pressure_v = (auxPress_v + auxPress_yint)*dbar_per_psi # [dbar]
                ###                    aux_temp_v = None
                ###                    auxPress_v = None
                ###
                ###                if False:
                ###                    # This hack is to handle bad truck pressure, but to auxcompass pressure
                ###                    log_warning("Re-writing truck pressure and depth from auxCompass pressure")
                ###                    sg_press_v = Utils.interp1d(aux_epoch_time_s_v, auxCompass_pressure_v, sg_epoch_time_s_v, kind='linear')
                ###                    if not base_opts.use_gsw:
                ###                        sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
                ###                    else:
                ###                        sg_depth_m_v = -1. * gsw.z_from_p(sg_press_v, latitude, 0., 0.)
                ###
                ###                #auxCompass_depth_v = sewater.dpth(auxCompass_pressure_v, latitude)
                ###                auxCompass_depth_v = -1. * gsw.z_from_p(auxCompass_pressure_v, latitude, 0., 0.)
                ###                results_d.update({f'{auxpressure_name}_press' : auxCompass_pressure_v,
                ###                                  f'{auxpressure_name}_depth' : auxCompass_depth_v})

                adcp_time = None
                adcp_pressure = None

                if calib_consts["use_adcppressure"]:
                    if all(x in results_d for x in ["cp_time", "cp_pressure"]):
                        adcp_time = "cp_time"
                        adcp_pressure = "cp_pressure"
                    elif all(x in results_d for x in ["ad2cp_time", "ad2cp_pressure"]):
                        adcp_time = "ad2cp_time"
                        adcp_pressure = "ad2cp_pressure"
                    else:
                        log_error(
                            "use_adcppressure specified in sg_calib_constants, but no adcp pressure found"
                        )

                if use_auxpressure:
                    ctd_press_v = Utils.interp1d(
                        aux_epoch_time_s_v,
                        auxCompass_pressure_v,
                        ctd_epoch_time_s_v,
                        kind="linear",
                    )  # [dbar]
                    # Map pressure and depth signals to thermistor location
                    zTP = Utils.interp1d(
                        compass_time, zTP, ctd_epoch_time_s_v, kind="linear"
                    )
                    # BUG: Really we should get pressure_sensor_depth from corrected pressure via sw_depth()
                    # then subtract zTP to get ctd_depth and the use a sw_press() routine to get ctd_press
                    # This might be close though...
                    # Negative because the CT sail is above the pressure sensor so is shallower
                    ctd_press_v = (
                        ctd_press_v - zTP * psi_per_meter * dbar_per_psi
                    )  # [dbar]
                    if not base_opts.use_gsw:
                        ctd_depth_m_v = (
                            seawater.dpth(ctd_press_v, latitude) - zTP
                        )  # [m]
                    else:
                        ctd_depth_m_v = (
                            -1.0 * gsw.z_from_p(ctd_press_v, latitude, 0.0, 0.0) - zTP
                        )  # [m]
                elif adcp_time:
                    ctd_press_v = Utils.interp1d(
                        results_d[adcp_time],
                        results_d[adcp_pressure],
                        ctd_epoch_time_s_v,
                        kind="linear",
                    )  # [dbar]
                    # TODO - Map pressure and depth signals to thermistor location
                    # zTP = Utils.interp1d(
                    #    compass_time, zTP, ctd_epoch_time_s_v, kind="linear"
                    # )
                    zTP = np.zeros(len(ctd_epoch_time_s_v))
                    # BUG: Really we should get pressure_sensor_depth from corrected pressure via sw_depth()
                    # then subtract zTP to get ctd_depth and the use a sw_press() routine to get ctd_press
                    # This might be close though...
                    # Negative because the CT sail is above the pressure sensor so is shallower
                    ctd_press_v = (
                        ctd_press_v - zTP * psi_per_meter * dbar_per_psi
                    )  # [dbar]
                    if not base_opts.use_gsw:
                        ctd_depth_m_v = (
                            seawater.dpth(ctd_press_v, latitude) - zTP
                        )  # [m]
                    else:
                        ctd_depth_m_v = (
                            -1.0 * gsw.z_from_p(ctd_press_v, latitude, 0.0, 0.0) - zTP
                        )  # [m]
                else:
                    # Truck pressure and depth
                    # Really we should get pressure_sensor_depth from corrected pressure via sw_depth()
                    # then subtract zTP to get ctd_depth and the use a sw_press() routine to get ctd_press
                    # This might be close though...
                    # Negative because the CT sail is above the pressure sensor so is shallower
                    ctd_depth_m_v = sg_depth_m_v - zTP  # [m]
                    ctd_press_v = (
                        sg_press_v - zTP * psi_per_meter * dbar_per_psi
                    )  # [dbar]
                    if ctd_results_dim != nc_info_d[BaseNetCDF.nc_sg_data_info]:
                        # need these for freq to measurement below
                        ctd_depth_m_v = Utils.interp1d(
                            sg_epoch_time_s_v,
                            ctd_depth_m_v,
                            ctd_epoch_time_s_v,
                            kind="linear",
                        )
                        ctd_press_v = Utils.interp1d(
                            sg_epoch_time_s_v,
                            ctd_press_v,
                            ctd_epoch_time_s_v,
                            kind="linear",
                        )

                # Done with this vector (if created)
                # del auxCompass_pressure_v

                # Conductivity calculation from SBE4 data sheet
                # Open-coded version of water_properties.m

                # pylint: disable=unbalanced-tuple-unpacking
                c_g, c_h, c_i, c_j, vars_used = SBECT_coefficents(
                    "conductivity",
                    calib_consts,
                    log_f,
                    ["c_g", "c_h", "c_i", "c_j"],
                    ["$SEABIRD_C_G", "$SEABIRD_C_H", "$SEABIRD_C_I", "$SEABIRD_C_J"],
                )
                # pylint: enable=unbalanced-tuple-unpacking
                ctd_ancillary_variables = ctd_ancillary_variables + vars_used
                cpcor = calib_consts["cpcor"]
                ctcor = calib_consts["ctcor"]

                CondFreqHz_v = condFreq_v / f0
                if calib_consts["sbe_cond_freq_offset"]:
                    CondFreqHz_v = CondFreqHz_v + calib_consts["sbe_cond_freq_offset"]
                    ctd_ancillary_variables = (
                        ctd_ancillary_variables + " sg_cal_sbe_cond_freq_offset"
                    )

                # Correct conductivity at the ctd_press_v, where the data was taken
                cond_raw_v = (
                    c_g
                    + (c_h + (c_i + c_j * CondFreqHz_v) * CondFreqHz_v)
                    * CondFreqHz_v
                    * CondFreqHz_v
                ) / (10.0 * (1.0 + ctcor * temp_raw_v + cpcor * ctd_press_v))
                ctd_metadata_d = BaseNetCDF.fetch_instrument_metadata(
                    BaseNetCDF.nc_sbect_data_info
                )
                ctd_metadata_d["ancillary_variables"] = ctd_ancillary_variables
            else:
                ## Pumped (GPCTD) data
                try:
                    # the timestamps can be off between the glider and the GPCTD by ~1s tops.  Ignore it.
                    ctd_epoch_time_s_v = results_d["gpctd_time"]
                    ctd_press_v = results_d["gpctd_pressure"]
                    ctd_temp_v = results_d["gpctd_temperature"]
                    ctd_cond_v = results_d["gpctd_conductivity"]
                except KeyError as e:
                    log_error(f"No pumped CT data found {e} - bailing out")
                    raise RuntimeError(True) from e

                # CONSIDER: should we support kistler cnf files in this branch?
                # UPDATE_PRESS
                sg_press_v = (
                    eng_f.get_col("depth")
                    * cm2m
                    * calib_consts["depth_slope_correction"]
                    - calib_consts["depth_bias"]
                ) * psi_per_meter
                sg_press_v *= dbar_per_psi  # convert to dbar
                if not base_opts.use_gsw:
                    sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
                else:
                    sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)
                results_d.update(
                    {
                        "pressure": sg_press_v,
                        "depth": sg_depth_m_v,
                    }
                )

                # MDP automatically asserts instrument when writing
                # DEAD results_d['gpctd'] = 'pumped Seabird SBE41 (gpctd)' # record the instrument used for CTD
                ctd_np = len(ctd_epoch_time_s_v)

                if not base_opts.use_gsw:
                    ctd_salin_v = seawater.salt(
                        ctd_cond_v / c3515, ctd_temp_v, ctd_press_v
                    )  # temporary, not the real salinity raw
                    ctd_depth_m_v = seawater.dpth(
                        ctd_press_v, latitude
                    )  # initial depth estimate
                else:
                    ctd_salin_v = gsw.SP_from_C(
                        ctd_cond_v * 10.0, ctd_temp_v, ctd_press_v
                    )  # temporary, not the real salinity raw
                    ctd_depth_m_v = -1.0 * gsw.z_from_p(
                        ctd_press_v, latitude, 0.0, 0.0
                    )  # initial depth estimate

                # GPCTD dumps invalid values at the end of each record; use QC.qc_checks() to discover them...
                # but disable spike detection (using QC.QC_NO_CHANGE)
                ctd_temp_qc_v, ctd_cond_qc_v, ctd_salin_qc_v = QC.qc_checks(
                    ctd_temp_v,
                    QC.initialize_qc(ctd_np, QC.QC_GOOD),
                    ctd_cond_v,
                    QC.initialize_qc(ctd_np, QC.QC_GOOD),
                    ctd_salin_v,
                    QC.initialize_qc(ctd_np, QC.QC_GOOD),
                    ctd_depth_m_v,
                    calib_consts,
                    QC.QC_BAD,
                    QC.QC_NO_CHANGE,
                    "raw gpctd ",
                )
                # Find the valid GPCTD data
                # The last several points in each profile are junk. Pressures are typically 0 or 'full-scale', which likely varies with instrument.
                # Geoff reports: Due to the way their firmware works, the last N samples of each cast are garbage.
                # We can bound the limit of bad points - 18 when you have CTP and O2, 22 when you have CTP.
                # The number of points are independent of timing.  They basically are dumping data in units of a buffer, and the tail of the buffer contains garbage.
                bad_gpctd_i_v = [
                    i
                    for i in range(ctd_np)
                    if (ctd_press_v[i] == 0.0) or (ctd_press_v[i] > 10000.0)
                ]
                # The timestamps should be off between the glider and the GPCTD by ~1s tops if they respond to the logger commands properly.
                # Trust but verify?
                # if False:
                #     # DEAD We use apogee as an event that both vehicle and GPCTD can agree on...
                #     # This doesn't work out well since we stop the GPCTD at apogee but the truck keeps reading depths
                #     # and we falsely think the deepest the GPCTD got is the same as the deepest point the vehicle recorded,
                #     # which could been 10s of seconds later
                #     max_sg_depth_i = sg_press_v.argmax()
                #     # We need to avoid the bad pressure points found above...
                #     valid_gpctd_i_v = Utils.setdiff(list(range(ctd_np)), bad_gpctd_i_v)
                #     max_gp_depth_i = valid_gpctd_i_v[ctd_press_v[valid_gpctd_i_v].argmax()]
                #     delta_t_s = (
                #         ctd_epoch_time_s_v[max_gp_depth_i]
                #         - sg_epoch_time_s_v[max_sg_depth_i]
                #     )
                #     if np.abs(delta_t_s) > 1.0:
                #         log_info(
                #             "GPCTD time off by %.2f seconds from vehicle time" % delta_t_s
                #         )
                #         # if delta_t_s is negative, GPCTD looks early; retard the time difference to align apogee
                #         ctd_epoch_time_s_v -= delta_t_s

                bad_gpctd_i_v.extend(QC.bad_qc(ctd_temp_qc_v))
                bad_gpctd_i_v.extend(QC.bad_qc(ctd_cond_qc_v))
                bad_gpctd_i_v.extend(QC.bad_qc(ctd_salin_qc_v))

                # Check for bad GPCTD clock in header of eng file
                if not [
                    i
                    for i in range(ctd_np)
                    if (ctd_epoch_time_s_v[i] >= sg_epoch_time_s_v[0])
                    and (ctd_epoch_time_s_v[i] <= sg_epoch_time_s_v[-1])
                ]:
                    # The following is to address the case seen on sg654 where the GPCTD clock
                    # was not being set by the Seaglider at the start of the profile, but was
                    # running while the GPCTD was on and the clock was latched over the power off/on
                    #
                    # If all the GPCTD payload data times are outside the time range of the glider's
                    # dive time range, all the GPCTD times are adjusted so the first GPCTD time is the
                    # start of the glider's dive time. This correction won't work (or work very well)
                    # if only the up profile is being sampled and it is dependent on what looks like
                    # the way the Kongsberg Seaglider code works - to run the GPCTD through the dive,
                    # apogee and up to the start of the climb.
                    if (
                        "gpctd_align_start_time" in calib_consts
                        and calib_consts["gpctd_align_start_time"]
                    ):
                        gpctd_t_corr = sg_epoch_time_s_v[0] - ctd_epoch_time_s_v[0]
                        ctd_epoch_time_s_v += gpctd_t_corr
                    else:
                        log_error(
                            "All GPCTD data time is outside of glider data time - possible bad clock data on GPCTD",
                            alert="BAD_GPCTD_CLOCK",
                        )

                # Turns out the gpctd can be left running a while after the glider takes it last data point (during surfacing); remove those points
                bad_gpctd_i_v.extend(
                    [
                        i
                        for i in range(ctd_np)
                        if (ctd_epoch_time_s_v[i] < sg_epoch_time_s_v[0])
                        or (ctd_epoch_time_s_v[i] > sg_epoch_time_s_v[-1])
                    ]
                )

                valid_gpctd_i_v = Utils.setdiff(list(range(ctd_np)), bad_gpctd_i_v)
                if not valid_gpctd_i_v:
                    log_error("No valid GPCTD data found - bailing out")
                    raise RuntimeError(True)

                # Reduce the data
                ctd_epoch_time_s_v = ctd_epoch_time_s_v[valid_gpctd_i_v]
                temp_raw_v = ctd_temp_v[valid_gpctd_i_v]
                cond_raw_v = ctd_cond_v[valid_gpctd_i_v]
                ctd_press_v = ctd_press_v[valid_gpctd_i_v]
                ctd_depth_m_v = ctd_depth_m_v[valid_gpctd_i_v]
                # pylint: disable=possibly-unused-variable
                if "gpctd_oxygen" in results_d:
                    # See code in sbe43_ext.py
                    valid_gpctd_oxygen_v = results_d["gpctd_oxygen"][valid_gpctd_i_v]
                # pylint: enable=possibly-unused-variable

                # For GPCTD we don't know how to correct their Kistler sensor so we just take it as is
                # and assume the pressure/depth is wrt thermistor already. So no zTP correction here

                ctd_results_dim = BaseNetCDF.nc_mdp_data_info[
                    BaseNetCDF.nc_gpctd_data_info
                ]
                ctd_np = len(ctd_epoch_time_s_v)

                # Initially all is well...
                temp_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
                cond_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)

                # Done w/ these vars...
                del (
                    ctd_temp_v,
                    ctd_temp_qc_v,
                    ctd_cond_v,
                    ctd_cond_qc_v,
                    ctd_salin_v,
                    ctd_salin_qc_v,
                )

                # NOTYET ctd_metadata_d = fetch_instrument_metadata(nc_gpctd_data_info)
                # No ancillary_variables to add yet (all internal to the GPCTD unit)
                ## End GPDCTD

        except RuntimeError as e:
            # In the event the CTD is not present, or its init doesn't work, calculate a GSM estimate
            # for velocity and displacement, so there is something to go on for the pilot

            try:
                sg_press_v = (
                    eng_f.get_col("depth")
                    * cm2m
                    * calib_consts["depth_slope_correction"]
                    - calib_consts["depth_bias"]
                ) * psi_per_meter
                sg_press_v *= dbar_per_psi  # convert to dbar
                if not base_opts.use_gsw:
                    sg_depth_m_v = seawater.dpth(sg_press_v, latitude)
                else:
                    sg_depth_m_v = -1.0 * gsw.z_from_p(sg_press_v, latitude, 0.0, 0.0)

                results_d.update(
                    {
                        "pressure": sg_press_v,
                        "depth": sg_depth_m_v,
                    }
                )

                compute_GSM_simple(
                    vehicle_heading_mag_degrees_v,
                    vehicle_pitch_rad_v,
                    sg_depth_m_v,
                    elapsed_time_s_v,
                    GPS1,
                    GPS2,
                    GPSE,
                    calib_consts,
                    nc_info_d,
                    results_d,
                )
            except Exception:
                DEBUG_PDB_F()
                log_error("Failed to generate GSM estimates", "exc")

            raise RuntimeError(True) from e

        ### End CTD init

        del zTP  # Done with this variable

        # At this point we have:
        # temp_raw_v, cond_raw_v plus qc vectors
        # ctd_press and ctd_depth_m
        # ctd_np, ctd_epoch_time_s_v

        if deck_dive and max(cond_raw_v) < 1.0:
            # a deck dive in air
            log_warning(
                "Deck dive CT saw air; adjusting conductivity values to report 30PSU"
            )
            # We need to compute a conductivity at the measured temperature such
            # that the ratio of it with C3515 is the proper ratio to give a
            # nominal salinity, here 30PSU.  (In the past we implicitly used 1.0
            # but that assumed (via S=35PSU, T=15C) the deck dive temperatures
            # were around 15C and in any case above roughly 6C so we didn't run
            # afoul of the QC_salin_max value. But on cold winter days...) Normally
            # we would use sw_cndr(30,t,0) to compute the proper ratio but
            # sw_cndr() is not available in the seawater package.  Here we
            # approximate the results of that function as a linear function of
            # temperature over oceanographic ranges.
            # We discard any mesured conductivities
            # cond_raw_v = (0.0176*temp_raw_v + 0.4811)*c3515 # 25PSU
            cond_raw_v = (0.0206 * temp_raw_v + 0.5685) * c3515  # 30PSU

        # In tsv_f we use the sparse routines to invert matricies to perform the TMC
        # If it were not for that it would require space O(n^2) at the least
        # and we would hang running out of memory or thrashing...
        # Attempts to develop a sinple backsubstitute mechanism are hard because the coefficients
        # tend to be small and pivot order becomes important.
        # So, instead, if sparse is not available, reduce the number of points to solve

        # Test cases:
        # ak/aug04/p0160394 4742 data points
        # ak/aug04/p0160395 4848 data points
        # ak/nov03/p0100032 2704 data points
        # ak/nov03/p0100142 4154 data points
        # ak/nov03/p0100147 3083 data points
        # ak/nov03/p0100158 4130 data points
        # and most any scicon mission

        if ctd_results_dim != nc_info_d[BaseNetCDF.nc_sg_data_info]:
            # Note that Utils.interp1 handles the cases where the CTD starts after the start of or stops before the end of sg time grid
            ctd_results_dim = BaseNetCDF.nc_dim_ctd_data_point
            ctd_elapsed_time_s_v = ctd_epoch_time_s_v - ctd_epoch_time_s_v[0]

            ctd_vehicle_pitch_degrees_v = Utils.interp1d(
                compass_time, vehicle_pitch_degrees_v, ctd_epoch_time_s_v, kind="linear"
            )
            ctd_vehicle_pitch_rad_v = Utils.interp1d(
                compass_time, vehicle_pitch_rad_v, ctd_epoch_time_s_v, kind="linear"
            )
            ctd_heading_v = Utils.interp1d(
                compass_time,
                vehicle_heading_mag_degrees_v,
                ctd_epoch_time_s_v,
                kind="linear",
            )

            ctd_vbd_cc_v = Utils.interp1d(
                sg_epoch_time_s_v, vbdCC_v, ctd_epoch_time_s_v, kind="linear"
            )
            ctd_sg_press_v = Utils.interp1d(
                sg_epoch_time_s_v, sg_press_v, ctd_epoch_time_s_v, kind="linear"
            )
            ctd_sg_depth_m_v = Utils.interp1d(
                sg_epoch_time_s_v, sg_depth_m_v, ctd_epoch_time_s_v, kind="linear"
            )  # for weed_hacker support only
        else:
            ctd_elapsed_time_s_v = elapsed_time_s_v
            ctd_vehicle_pitch_degrees_v = vehicle_pitch_degrees_v
            ctd_vehicle_pitch_rad_v = vehicle_pitch_rad_v
            ctd_heading_v = vehicle_heading_mag_degrees_v
            ctd_vbd_cc_v = vbdCC_v
            ctd_sg_press_v = sg_press_v
            ctd_sg_depth_m_v = sg_depth_m_v  # for weed_hacker support only

        BaseNetCDF.assign_dim_info_dim_name(
            nc_info_d, BaseNetCDF.nc_ctd_results_info, ctd_results_dim
        )
        BaseNetCDF.assign_dim_info_size(
            nc_info_d, BaseNetCDF.nc_ctd_results_info, ctd_np
        )

        # Adjust these offsets regardless of CT source
        temp_raw_v -= calib_consts["temp_bias"]  # remove bias [degC]
        cond_raw_v -= calib_consts["cond_bias"]  # remove bias [S/m]
        if salin_raw_v is None:
            # Compute salinity based on raw data, w/o modification
            if not base_opts.use_gsw:
                salin_raw_v = seawater.salt(cond_raw_v / c3515, temp_raw_v, ctd_press_v)
            else:
                salin_raw_v = gsw.SP_from_C(cond_raw_v * 10.0, temp_raw_v, ctd_press_v)

        # elapsed time is recorded as eng_elaps_t

        # This are stored earlier, so they are always in the netcdf file,
        # even if CT processing fails

        # results_d.update(
        #    {
        #        nc_sg_time_var: sg_epoch_time_s_v,
        #        "pressure": sg_press_v,
        #        "depth": sg_depth_m_v,
        #    }
        # )

        # globals_d["time_coverage_start"] = nc_ISO8601_date(min(sg_epoch_time_s_v))
        # globals_d["time_coverage_end"] = nc_ISO8601_date(max(sg_epoch_time_s_v))

        # see discussion in BaseNetCDF about resolution vs accuracy
        # TODO some instruments have much better resolution than 1 secs and
        # even the glider doesn't have resolution finer than 2.5 secs nominally...so what is this saying?
        globals_d["time_coverage_resolution"] = (
            "PT1S"  # ISO 8601 duration: Period Time 1 second
        )

        globals_d["geospatial_vertical_min"] = min(sg_depth_m_v)
        globals_d["geospatial_vertical_max"] = max(sg_depth_m_v)
        globals_d["geospatial_vertical_units"] = "meter"
        # see discussion in BaseNetCDF about resolution vs accuracy
        globals_d["geospatial_vertical_resolution"] = (
            "centimeter"  # TODO for MMP this should be 'N meter binned'
        )
        globals_d["geospatial_vertical_positive"] = "no"

        # compute time increments for DAC use below
        delta_time_s_v = np.zeros(sg_np, np.float64)
        delta_time_s_v[1:] = np.diff(sg_epoch_time_s_v)  # time increments
        ctd_delta_time_s_v = np.zeros(ctd_np, np.float64)
        ctd_delta_time_s_v[1:] = np.diff(ctd_epoch_time_s_v)  # time increments

        # Compute these times wrt ctd_elapsed_time_s_v
        # OKMC/Nov11/sg168/p1680008 Recovery (D_ABORT) during first apogee pump.  start_time+vbd_secs exceeds last data point
        last_data_time = ctd_elapsed_time_s_v[-1]
        start_of_climb_time = (
            last_data_time
            if start_of_climb_time is None
            else min(start_of_climb_time, last_data_time)
        )
        apogee_pump_start_time = (
            last_data_time
            if apogee_pump_start_time is None
            else min(apogee_pump_start_time, last_data_time)
        )
        apogee_climb_pump_end_time = (
            last_data_time
            if apogee_climb_pump_end_time is None
            else min(apogee_climb_pump_end_time, last_data_time)
        )
        apogee_climb_pump_time = (
            apogee_climb_pump_end_time - apogee_pump_start_time
        )  # elapsed time loitering and turning around...

        apogee_climb_pump_i_v = list(
            filter(
                lambda i: ctd_elapsed_time_s_v[i] >= apogee_pump_start_time
                and ctd_elapsed_time_s_v[i] <= apogee_climb_pump_end_time,
                range(ctd_np),
            )
        )
        # Compute the loiter time points (that should include $T_LOITER if honored)
        # Actually if there is a logger delay on starting the b profile we won't see this because the GC doesn't tell you when the pitch move actually started
        # Could be 20 secs or so for ADCPs. See SG653 Dabob Bay Sep 2018.  You'd have to guess about the truck sampling time and see if the first data point
        # took longer than that to show up.
        try:
            loiter_i_v = list(
                filter(
                    lambda i: ctd_elapsed_time_s_v[i] >= apogee_pump_vbd_end_time
                    and ctd_elapsed_time_s_v[i] <= start_of_climb_time,
                    range(ctd_np),
                )
            )
        except NameError:
            loiter_i_v = []
        apo_loiter_s = 0
        if len(loiter_i_v):
            apo_loiter_s = (
                ctd_elapsed_time_s_v[loiter_i_v[-1]]
                - ctd_elapsed_time_s_v[loiter_i_v[0]]
            )

        # Setup important indices for later processing
        start_of_climb_i = [
            i for i in range(ctd_np) if ctd_elapsed_time_s_v[i] >= start_of_climb_time
        ]
        start_of_climb_i = start_of_climb_i[0]  # 'first',1
        directives.start_of_climb = start_of_climb_i + 1  # matlab convention
        results_d.update(
            {
                "start_of_climb_time": start_of_climb_time,
            }
        )

        dive_i_v = list(range(0, start_of_climb_i))  # NOT start of apogee!
        climb_i_v = list(range(start_of_climb_i, ctd_np))

        depth_mask_v = np.zeros(ctd_np, np.float64)
        depth_mask_v[:] = BaseNetCDF.nc_nan
        depth_mask_v[dive_i_v] = ctd_sg_depth_m_v[dive_i_v]
        directives.dive_depth = depth_mask_v  # dive_weed_hacker support
        depth_mask_v = np.zeros(ctd_np, np.float64)  # don't reuse the array
        depth_mask_v[:] = BaseNetCDF.nc_nan
        depth_mask_v[climb_i_v] = ctd_sg_depth_m_v[climb_i_v]
        directives.climb_depth = depth_mask_v  # climb_weed_hacker support
        del depth_mask_v

        head_true_deg_v = ctd_heading_v + mag_var_deg
        # headings are reported from the compass in degrees from the north (positive y-axis) clockwise
        # compute heading as polar degrees in radians, which are measured from the east (positive x-axis) counterclockwise
        head_true_deg_v = 90.0 - head_true_deg_v
        bad_deg_i_v = np.nonzero(head_true_deg_v >= 360.0)
        head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] - 360.0
        bad_deg_i_v = np.nonzero(head_true_deg_v < 0.0)
        head_true_deg_v[bad_deg_i_v] = head_true_deg_v[bad_deg_i_v] + 360.0
        head_polar_rad_v = np.radians(head_true_deg_v)

        # in matlab ctd_np_i, the index of the last data point, is the same as the length ctd_np
        # in python, with 0-based indexing, ctd_np_i is off by one...
        ctd_np_i = ctd_np - 1
        directives.data_points = list(
            range(1, ctd_np + 1)
        )  # deal with matlab convention
        directives.glider_data_points = list(
            range(1, sg_np + 1)
        )  # deal with matlab convention
        directives.depth = ctd_depth_m_v
        directives.glider_depth = sg_depth_m_v
        directives.time = elapsed_time_s_v

        # Compute vehicle measured vertical velocity w_cm_s_v, which is used to estimate initial speed and glide angle.
        # Compute w = dz/dt using depth from pressure and latitude

        # Handle missing pressure observations
        good_depth_pts = np.logical_not(np.isnan(sg_depth_m_v))
        try:
            w_cm_s_v = Utils.ctr_1st_diff(
                -sg_depth_m_v[good_depth_pts] * m2cm, elapsed_time_s_v[good_depth_pts]
            )
        except Exception:
            log_error("Failed calculating dz/dt - skipping profile", "exc")
            return (2, None)

        # Map to ctd times and compute gsm results at that dimension
        # BUG? This is what the matlab code does so we can use gsm values as initial start values for tsv
        # The alternative is to save them in sg_data_point space and just interpolate
        # before tsv but not record that...If we do this, remove them from the ctd coordinates
        ctd_w_cm_s_v = Utils.interp1d(
            sg_epoch_time_s_v[good_depth_pts],
            w_cm_s_v,
            ctd_epoch_time_s_v,
            kind="linear",
        )
        # Compute an intiial guess for glide angles and glider speed:
        # Use a version of the hydrodynamic model that assumes constant bouyancy throughout the dive
        # based on assumed deepest density encountered (rho0) and measured pitch (vehicle_pitch_rad_v) and vertical speed (w_cm_s_v)
        # See note on rho0 values in HydroModel
        converged, gsm_speed_cm_s_v, gsm_glide_angle_rad_v, _ = glide_slope(
            ctd_w_cm_s_v, ctd_vehicle_pitch_rad_v, calib_consts
        )
        if not converged:
            log_warning(
                "Unable to converge during initial glide-slope speed calculations"
            )
        # gsm_glide_angle_deg_v is used in call to TSV below (rather than gsm_glide_angle_rad_v)
        gsm_glide_angle_deg_v = np.degrees(gsm_glide_angle_rad_v)
        gsm_horizontal_speed_cm_s_v = gsm_speed_cm_s_v * np.cos(gsm_glide_angle_rad_v)
        gsm_w_speed_cm_s_v = gsm_speed_cm_s_v * np.sin(gsm_glide_angle_rad_v)
        results_d.update(
            {
                "speed_gsm": gsm_speed_cm_s_v,
                "glide_angle_gsm": gsm_glide_angle_deg_v,
                "horz_speed_gsm": gsm_horizontal_speed_cm_s_v,
                "vert_speed_gsm": gsm_w_speed_cm_s_v,
            }
        )
        ctd_gsm_speed_cm_s_v = gsm_speed_cm_s_v
        ctd_gsm_horizontal_speed_cm_s_v = gsm_horizontal_speed_cm_s_v
        ctd_gsm_glide_angle_deg_v = gsm_glide_angle_deg_v

        # we use ctd_depth_m_v to determine whether the sensor is submerged
        # (in practice it nearly always is unless we have strong seas, where
        # we will see bubbles, below, or the sensor is not tared to surface pressure
        # properly).

        ctd_depth_threshold = (
            0.5  # PARAMETER meters submerged (this caps early sampling at the surface)
        )
        ctd_underwater_i_v = [
            i for i in range(ctd_np) if ctd_depth_m_v[i] > ctd_depth_threshold
        ]
        if len(ctd_underwater_i_v):
            dive_start_i = ctd_underwater_i_v[0]  # start here for everyone
            ctd_underwater_i_v = None  # done w/ this var
        else:
            # ak/oct03/p0090005 applied/rimpac/p0190001 (probably initial ballasting and centering issues)
            # If USE_ICE could be stuck under ice (and raised above water level)
            log_error("Glider never dove? - bailing out")
            raise RuntimeError(True)

        max_ctd_depth_i = ctd_depth_m_v.argmax()
        max_ctd_depth_m = ctd_depth_m_v[max_ctd_depth_i]

        # compute against ctd_depth_m since we just care only CT is plausibly out of the water
        # especially on the climb the nose might have come out of the water but not the CT sensor....test this.
        # NOTE: Compute this before the bubble detector so we get both reports and the QC vectors
        # will update for the different reasons. If we do it the other way, the OOW, which looks like a bubble,
        # is masked by the bubble report from cond_anomaly()
        # UNUSED min_depth_m = 0.10  # PARAMETER [m] use this reading if flying...
        out_of_the_water_i_v = [i for i in range(ctd_np) if ctd_depth_m_v[i] < 0]
        if len(out_of_the_water_i_v):
            # we can trust the thermistor but conductivity, hence salinity (see below), will be bad
            QC.assert_qc(
                QC.QC_BAD,
                cond_raw_qc_v,
                out_of_the_water_i_v,
                "CT out of water",
            )  # so we drop these

            # Most likely the pressure sensor was not well zero'd at the start of mission
            # Alternatively it could be hysteresis on the sensor itself over the mission
            # or really really rough weather...
            # wa/jan04 sg002 dive 1
            # faroes/jun09/sg105 dives 3,5,6,...lots (broaching)
            out_i_v = Utils.intersect(
                out_of_the_water_i_v, list(range(max_ctd_depth_i))
            )
            if len(out_i_v):
                log_warning(
                    "CTD out of the water before dive (%.3fm)"
                    % max(np.abs(ctd_depth_m_v[out_i_v]))
                )

            out_i_v = Utils.intersect(
                out_of_the_water_i_v, list(range(max_ctd_depth_i, ctd_np))
            )
            if len(out_i_v):
                log_warning(
                    "CTD out of the water after climb (%.3fm)"
                    % max(np.abs(ctd_depth_m_v[out_i_v]))
                )

        # Make copies of these arrays before any qc_checks
        # WHY? because we repeat the call to qc_checks below with possibly different actions for bound and spikes
        # but we want to preserve any QC.QC_UNSAMPLED and QC_BAD marks we determined when processing CT data
        # The tests above (unsampled, freq bounds, and out of water) we want to apply to both raw and corrected T/C/S
        temp_cor_v = np.array(temp_raw_v)
        temp_cor_qc_v = np.array(temp_raw_qc_v)
        cond_cor_v = np.array(cond_raw_v)
        cond_cor_qc_v = np.array(cond_raw_qc_v)
        if salin_raw_qc_v is None:
            salin_raw_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)

        # Perform basic QC checks on raw data
        # NOTE mark spikes as QC_PROBABLY_BAD

        # CONSIDER: For Legato - is this the correct thing?
        #  1) Should perform_scicon_noise_filter=True be passed? (No I think)
        #  2) Should spike detection be enabled?
        (temp_raw_qc_v, cond_raw_qc_v, salin_raw_qc_v) = QC.qc_checks(
            temp_raw_v,
            temp_raw_qc_v,
            cond_raw_v,
            cond_raw_qc_v,
            salin_raw_v,
            salin_raw_qc_v,
            ctd_depth_m_v,
            calib_consts,
            QC.QC_BAD,
            QC.QC_PROBABLY_BAD,
            "raw ",
            have_scicon_ct,
        )
        # Assume there are no anomalies
        good_anomalies_v = []
        suspect_anomalies_v = []
        if perform_cond_anomaly_check:
            # Handle bubble and snot in remaining good raw data
            # We do this after QC.qc_checks() because we don't want spikes looking like (suspect) anomalies
            # which can happen during high-frequency sampling on the CT
            # On the other hand, quite often bubbles look like spikes as she goes in an out of the water
            # so we nail parts of the bubble in QC.qc_checks() and any remaining excursions are filled in
            # with the bubble logic in CA
            good_anomalies_v, suspect_anomalies_v = cond_anomaly(
                cond_raw_v,
                cond_raw_qc_v,
                temp_raw_v,
                temp_raw_qc_v,
                ctd_elapsed_time_s_v,
                ctd_depth_m_v,
                dflare,
                dsurf,
                start_of_climb_i,
                test_tank_dive,
            )

            for a in good_anomalies_v:
                # NOTE treat these as bad...we deal with interpolation below
                descr = a.descr()
                descr = descr.replace("conductivity", "raw conductivity")
                QC.assert_qc(QC.QC_BAD, cond_raw_qc_v, a.points(), descr)
            # suspect_anomalies_v are ignored

        QC.inherit_qc(temp_raw_qc_v, salin_raw_qc_v, "raw temp", "raw salinity")
        QC.inherit_qc(cond_raw_qc_v, salin_raw_qc_v, "raw cond", "raw salinity")

        TraceArray.trace_array("temp_raw_qc", temp_raw_qc_v)
        TraceArray.trace_array("cond_raw_qc", cond_raw_qc_v)
        TraceArray.trace_array("salin_raw_qc", salin_raw_qc_v)

        QC.report_qc("temp_raw_qc", temp_raw_qc_v)
        QC.report_qc("cond_raw_qc", cond_raw_qc_v)
        QC.report_qc("salin_raw_qc", salin_raw_qc_v)

        # Match the order of matlab script
        TraceArray.trace_array("GSM_speed_guess", gsm_speed_cm_s_v)
        TraceArray.trace_array("GSM_glideangle_guess", gsm_glide_angle_deg_v)
        results_d.update(
            {
                "ctd_time": ctd_epoch_time_s_v,
                "ctd_depth": ctd_depth_m_v,
                "ctd_pressure": ctd_press_v,
                # Raw water column observations
                "temperature_raw": temp_raw_v,
                "temperature_raw_qc": temp_raw_qc_v,
                "conductivity_raw": cond_raw_v,
                "conductivity_raw_qc": cond_raw_qc_v,
                "salinity_raw": salin_raw_v,
                "salinity_raw_qc": salin_raw_qc_v,
            }
        )

        ## Start adjustments here to get corrected temp, cond and salinity
        TraceArray.trace_array("temp_pre_interp", temp_cor_v)
        TraceArray.trace_array("cond_pre_interp", cond_cor_v)

        # We ignore the results of salinity tests here because we redo them below
        # but we do them because they impact cond_qc (see qc_checks)
        # We start salin_cor_v and salin_cor_qc_v below (and in tsv_iter)
        # Typically bound check marks QC_BAD and spike checks mark QC_INTERPOLATED (not QC_PROBABLY_BAD)
        temp_cor_qc_v, cond_cor_qc_v, _ = QC.qc_checks(
            temp_cor_v,
            temp_cor_qc_v,
            cond_cor_v,
            cond_cor_qc_v,
            salin_raw_v,
            QC.initialize_qc(ctd_np, QC.QC_GOOD),
            ctd_depth_m_v,
            calib_consts,
            calib_consts["QC_bound_action"],
            calib_consts["QC_spike_action"],
            "",
            have_scicon_ct,
        )
        # reassert any good CAs for corrected world as QC_BAD or QC_INTERPOLATED
        for a in good_anomalies_v:
            QC.assert_qc(a.qc(), cond_cor_qc_v, a.points(), a.descr())

        # the inheritance of qc from temp and cond to salinity occurs below, after more checks

        # CCE observed that temperatures sometimes spiked during (active) GCs.
        # All TSV corrections assume a good thermistor and good temp readings, so we can correct salinity wrt to it and hence calc correct buoyancy
        # Find times of *all* GCs and linearly interpolate temperatures over those regions
        # Do this before removing bad samples in order to avoid edge conditions of possible partial GC records at start and finish of filtered data
        # Excessive thermistor noise or bad instrument (as with SG105 June 2009 offshore the Faroes) must be dealt with manually

        # CONSIDER - this should probably not applied to the Legato?
        if interpolate_gc_temperatures:
            interpolate_GC_temp_i = []
            # find temperature records just before gc start and just after end times (or the beginning/end of the time series)
            # linearly interpolate temperature between those points
            # NOTE: if we get here num_gc_events is non-zero
            for gc in range(
                1, num_gc_events
            ):  # Skip the first GC since it is the flare maneuver
                start_time = gc_st_secs[gc] - i_eng_file_start_time
                end_time = gc_end_secs[gc] - i_eng_file_start_time
                gc_i_v = [
                    i
                    for i in range(ctd_np)
                    if ctd_elapsed_time_s_v[i] >= start_time
                    and ctd_elapsed_time_s_v[i] <= end_time
                ]
                if len(gc_i_v):
                    pre_index = gc_i_v[0]
                    post_index = gc_i_v[-1]
                    # TODO possible that GC times (indices) would overlap (see p1440003 from Jun 08)
                    pre_index = max(pre_index - 1, 0)
                    post_index = min(post_index + 1, ctd_np - 1)

                    temp_pre = temp_raw_v[pre_index]
                    time_pre = ctd_elapsed_time_s_v[pre_index]
                    temp_post = temp_raw_v[post_index]
                    time_post = ctd_elapsed_time_s_v[post_index]
                    slope = np.abs((temp_post - temp_pre) / (time_post - time_pre))
                    # If there is a large thermocline, we can't tell if heating is occuring, so skip
                    if slope < thermocline_temp_diff:
                        # BUG this should be only for sbect_unpumped!! since we think it is caused by an interaction between the CT and the mainboard/motors
                        interpolate_GC_temp_i.append(gc_i_v.tolist())

                QC.assert_qc(
                    QC.QC_INTERPOLATED,
                    temp_cor_qc_v,
                    interpolate_GC_temp_i,
                    "GC temperature increases",
                )  # mark for interpolation

        # faroes/jun08/sg016 400:end (esp. 416) and faroes/jun08/sg005 340:end
        # sg170_OKMC_Apr12 141 142 during dive

        # For some deployments we observe salinity 'feet' during dive and apogee in which salinity spikes (to the fresh)
        # are observed after a pitch up (e.g., second pump) until sometime when the vehicle moves
        # Charlie conjectured it is from trapped warmer water in the aft fairing being burped at depth
        # and wafting up to the thermistor. The water eventually is left behind as the vehicle starts moving.
        # This should also impact pumped systems.

        # Two phases:
        # First, extend apogee if needed until the vehicle is flying again (original faroes cases)
        # Then look at dive for places where pitch is up (and are likely stalled). Mark as BAD
        # through those locations until flying again.

        # So: for unpumped systems mark first part of GC bad
        # for both systems mark the second part of GC bad until we are moving at speed (see flare logic)
        speedthreshold = 10.0  # PARAMETER [cm/s] vehicle is finally moving
        slow_apogee_climb_pump_i_v = []
        # CONSIDER: Legato?
        if sbect_unpumped:
            slow_apogee_climb_pump_i_v = apogee_climb_pump_i_v
            # original (covers first pump)

        # detect wafting warm water trapped in fairing detected by thermistor
        # can apply to all CTDs but not with compressee present (no interstitial volume)
        # even if we are pitched up and the GSM says we are flying fast we might be trimmed heavy and actually
        # descending, in which case we have the wafting issue (faroes/jun08:sg016 345 413)

        # typically sg_calib_constants supplies the values for mass and mass_comp
        try:
            mass = calib_consts["mass"]
            # [kg]
            if mass > 100:
                log_warning(
                    "Correcting mass of vehicle in sg_calib_constants (%.1f) to kg"
                    % mass
                )
                calib_consts["mass"] = mass = mass / kg2g
            mass = mass * kg2g  # [g]
            if np.abs(mass - log_f.data["$MASS"]) > 1:  # [g]
                log_warning(
                    "Mass of vehicle in sg_calib_constants (%.1f) does not match $MASS in log file (%.1f); using sg_calib_constants.  (See notes in html/AlertsReferenceManual.html)"
                    % (mass, log_f.data["$MASS"]),
                    alert="MASS_MISMATCH",
                )
        except KeyError:
            pass

        # if mass_comp not present, the default constant is 0 for SG, 10 for DG
        # but if it is suppled in the log file and different WARN
        mass_comp = calib_consts["mass_comp"]
        # [kg] ensured to be present
        if (
            mass_comp > 20
        ):  # typically no more that 12kg but could be more with dodecamethylpentasiloxane
            log_warning(
                "Correcting compressee mass of vehicle from sg_calib_constants (%.1f) to kg"
                % mass_comp
            )
            calib_consts["mass_comp"] = mass_comp / kg2g
        mass_comp = mass_comp * kg2g  # [g]
        try:
            # Yes, it is grams aboard and kg in sg_calib_constants.
            if np.abs(mass_comp - log_f.data["$MASS_COMP"]) > 1:  # [g]
                log_warning(
                    "Mass of compressee in sg_calib_constants (%.1fg) does not match $MASS_COMP in log file (%.1fg); using sg_calib_constants"
                    % (mass_comp, log_f.data["$MASS_COMP"])
                )
        except KeyError:
            pass
        # BUG? SG can now have compressee aft but there is trapped water in the fwd fairing
        # Is this (part of) the water that can waft or is it largely from aft with the big hole
        # for the CT mount?
        if mass_comp == 0:  # there is interstitial volume
            # Phase 1:
            min_vertical_speed_cm_s = (
                4.0  # PARAMETER min vertical speed cm/s for climb start or dive restart
            )
            start_of_climb_flying_i = [
                i
                for i in range(ctd_np)
                if (
                    ctd_elapsed_time_s_v[i] >= start_of_climb_time
                    and ctd_gsm_speed_cm_s_v[i] >= speedthreshold
                    and ctd_w_cm_s_v[i] > min_vertical_speed_cm_s
                )
            ]
            if len(start_of_climb_flying_i):
                slow_apogee_climb_pump_i_v.extend(
                    range(start_of_climb_i, start_of_climb_flying_i[0] + 1)
                )
                # could be overlap with apogee_pump_i
                slow_apogee_climb_pump_i_v = Utils.sort_i(
                    Utils.unique(slow_apogee_climb_pump_i_v)
                )
            # Phase 2:
            dive_wafting_i_v = [
                i
                for i in dive_i_v
                if (ctd_vehicle_pitch_degrees_v[i] > -calib_consts["min_stall_angle"])
            ]
            dive_wafting_i_v = Utils.setdiff(
                dive_wafting_i_v, slow_apogee_climb_pump_i_v
            )  # no sense double counting
            if len(dive_wafting_i_v):
                # to a first approximation, these points are toast
                # actually, since we are on a dive, the first point before us should be warmer than the last
                # and any points in the region that are as warm or warmer than the first point are likely from the trapped water
                # of course ther ecould be temperature inversions...
                diff_waft_i_v = np.diff(dive_wafting_i_v)
                breaks_i_v = [
                    i for i in range(len(diff_waft_i_v)) if diff_waft_i_v[i] > 1
                ]
                breaks_i_v.append(len(dive_wafting_i_v) - 1)  # add the final point
                last_i = 0
                for break_i in breaks_i_v:
                    pre_index = dive_wafting_i_v[last_i]
                    post_index = dive_wafting_i_v[break_i]
                    start_temp = temp_raw_v[pre_index]
                    # CONSIDER: compute np.diff(temp_raw_v) in the region and look for upticks greater than a threshold
                    # which would indicate starts of pulses.  Require them but the number of points, like cond anomalies,
                    # could be considerably more
                    warmer_points_i_v = [
                        i
                        for i in range(pre_index, post_index)
                        if temp_raw_v[i] > start_temp
                    ]
                    if len(warmer_points_i_v):
                        # If we were going to find the points, we need to do something like cond_anomaly above:
                        # track start and stop of major changes in temperature to the warm and then back again
                        # in between the temp can look 'stable' (at a warmer temp) so all the intervening points have to be nailed.
                        directives.suggest(
                            "bad_temperature data_points between %d %d %% possible wafting warm water on dive at %d points"
                            % (pre_index, post_index, len(warmer_points_i_v))
                        )  # Utils.succinct_elts(warmer_points_i_v) too chatty
                        # TOO AGGRESSIVE: QC.assert_qc(QC.QC_BAD,temp_cor_qc_v,warmer_points_i_v,'possible wafting warm water on dive')
                    last_i = break_i  # move along

        # TODO - Need a unified check here for this correction for legato
        if detect_slow_apogee_flow:
            QC.assert_qc(
                QC.QC_BAD,
                cond_cor_qc_v,
                slow_apogee_climb_pump_i_v,
                "slow apogee CT flow",
            )
        # DEAD apogee_climb_pump_i_v = None # done with this intermediate (but not slow_apogee_climb_pump_i_v)

        # look for points where we might have been stuck on the bottom
        stuck_i_v = []
        bottom_depth = log_f.data[
            "$D_TGT"
        ]  # add a little since we back off to accomodate apogee?
        try:
            bottom_ping = log_f.data["$ALTIM_BOTTOM_PING"]  # depth of ping, range
            bottom_depth = 0
            for v in bottom_ping.split(","):
                bottom_depth += float(v)
        except KeyError:
            pass  # D_TGT is good enough
        if (
            max_ctd_depth_m < bottom_depth
            and ctd_elapsed_time_s_v[max_ctd_depth_i]
            < log_f.data["$T_MISSION"] * 60 / 2
        ):
            near_bottom = (
                0.01 if test_tank_dive else 5
            )  # PARAMETER [m] depth off the "putative" bottom the vehicle can bounce and still be considered stuck
            bounce_distance_allowed = (
                0.4  # PARAMETER [m] depth change allowed for a bounce
            )
            # we might be on the bottom because we didn"t make it to our target depth and we didn"t time out
            # find places where we are "near the putative bottom"
            bottom_i_v = [
                i
                for i in range(ctd_np)
                if ctd_depth_m_v[i] > max_ctd_depth_m - near_bottom
            ]
            # and of those places where did we not bounce around too much off the bottom?
            # CONSIDER: add these to stall points above
            dZdt_v = np.abs(np.diff(ctd_depth_m_v[bottom_i_v]))
            on_bottom_i_v = [
                i for i in range(len(dZdt_v)) if dZdt_v[i] < bounce_distance_allowed
            ]
            bottom_i_v = np.array(bottom_i_v)  # so we can index nicely
            stuck_i_v = bottom_i_v[on_bottom_i_v]
            stuck_time = sum(
                ctd_delta_time_s_v[stuck_i_v]
            )  # don"t assume consecutive times
            if stuck_time > apogee_climb_pump_time:  # report if really long
                log_info(
                    "On the bottom at %.1fm for %.1f minutes."
                    % (max_ctd_depth_m, stuck_time / 60.0)
                )
            ctd_delta_time_s_v[stuck_i_v] = (
                0  # not flying here so no flight elapsed time (see DAC below)
            )
            if sbect_unpumped and sg_ct_type != 4:
                # TODO really? like apogee, salin might tbe ok if we aren't in a thermocline
                # CONSIDER drop this
                # However, still should declare that the hdm speeds are 0 and hence bad here for DAC
                QC.assert_qc(QC.QC_BAD, cond_cor_qc_v, stuck_i_v, "stuck on the bottom")

        ## Common for all CTDs
        # NOTE: dropped dive/climb_data_weed_hacker
        # replace with 'bad_cond dive_depth less_than X'
        # dive_depth and climb_depth set for this purpose
        interp_temp_i_v = QC.manual_qc(
            directives,
            "interp_temperature",
            "temp_QC_INTERPOLATED",
            QC.QC_INTERPOLATED,
            temp_cor_qc_v,
            "temperature",
        )
        temp_cor_v, temp_cor_qc_v = QC.interpolate_data_qc(
            temp_cor_v,
            ctd_elapsed_time_s_v,
            interp_temp_i_v,
            "temperature",
            directives,
            temp_cor_qc_v,
            QC.QC_PROBABLY_BAD,
        )
        TraceArray.trace_array("temp_post_interp", temp_cor_v)

        if sg_ct_type != 4:
            # Applies to all SBE CTs...
            # Do this correction here, after possible temp interpolation
            # We want the dTdt gradient to reflect any interpolation
            dTemp_dt_v = Utils.ctr_1st_diff(temp_cor_v, ctd_elapsed_time_s_v)
            # if there were unsampled points these will be NaN (mocha/2010.07.sanjuan/sg033 dive 30)
            # in that case the ctr1stdiffderiv will propagate NaNs adjacent locations in dTdt and hence into temp
            bad_dTdt_i_v = [i for i in range(ctd_np) if np.isnan(dTemp_dt_v[i])]
            dTemp_dt_v[bad_dTdt_i_v] = 0  # % no 1st order lag here
            del bad_dTdt_i_v  # done with this intermediate

            temp_cor_v += (
                calib_consts["sbect_tau_T"] * dTemp_dt_v
            )  # correct for 1st order time lag

        ## mark bad temperature points
        bad_temp_i_v = QC.manual_qc(
            directives,
            "bad_temperature",
            "temp_QC_BAD",
            QC.QC_BAD,
            temp_cor_qc_v,
            "temperature",
        )
        bad_temp_i_v = QC.bad_qc(temp_cor_qc_v)
        temp_cor_v[bad_temp_i_v] = BaseNetCDF.nc_nan  # MARK BAD

        # Eliminate points at the start, apogee, and end of the dive for different reasons
        # eliminate the start of dive until we start flying or get below dflare, whichever is deeper
        # use glide_slope speed to find a start point in addition to dflare

        # NOTE min depth might not be zero (in fact isn't ever zero at surface) because of pressure sensor issues but also because it is underwater by ~.3m
        # and we don't take a point at the surface before we start the dive....
        # In addition the sensor might be off if it had an electrical bias (early SG005?) or a hysteresis factor that needs correcting over the initial dives,etc.

        # When leaving the surface and before flare our compass measurements
        # are not terribly good and we are accelerating as we gain speed and then
        # flare.  The flight model doesn't do very well in this non-steady regime
        # so we excise these points, both from speed and TS calcs

        # BUG sg120 jun09 dive 53: much bouncing about near the surface (going to 3 then up to 2 then down...
        # BUG and estimated speeds have some early stall points so it looks like we are flying but we aren't...
        # We estimate point 4 as where we fly but in reality it is point 14

        # in the unpumped case, the top of dive and climb and apogee are known places where
        # we aren"t moving fast enough (stalled) so thermal inertia corrections aren't good
        # however, the tube has been sitting in the water and equilibriated during drift
        # so unless there is strong mixing it is likely to be an ok reading.
        # CONSIDER retaining points below 2m or so
        # but discard through flare and then if flying fast enough
        flying_i_v = [i for i in dive_i_v if ctd_gsm_speed_cm_s_v[i] >= speedthreshold]
        if len(flying_i_v):
            flying_i = flying_i_v[0]
        else:
            log_error("Glider never started flying? - bailing out")
            raise RuntimeError(True)

        flare_i = 0  # where flare depth achieved
        # CONSIDER - probably not correct for Legato
        if sbect_unpumped:
            # Ensure the glider is moving, the CT is under water, we are clear of bubbles
            # (see above 'good_anomlies') and after flare depth

            # We care when the CTD is below flare, which is close to where the
            # glider flared but pressure sensor is below the CTD generally and
            # the vehicle flared *after* this depth.

            # We use dflare as a first-order proxy for moving fast but there are
            # deployments where dflare is set quite shallow (1m) to deliberately
            # get the glider to sample in the upper part of the water column and
            # the speeds are likely too small for good TI corrections if there
            # is a thermocline. See Port_Susan_ADCP/sg577_gpctd

            # In this case the speedthreshold (10cm/s) should take care of this
            # problem.

            flare_i_v = [i for i in dive_i_v if ctd_depth_m_v[i] >= dflare]
            if len(flare_i_v):
                flare_i = flare_i_v[0]
            else:
                # If USE_ICE could be stuck under ice and held there unable to break free
                # APL/sgs141_DavisStrait_Feb11_ICE dives 87ff
                log_error("Glider never flared? - bailing out")
                raise RuntimeError(True)

            dive_start_i = max([flare_i, flying_i, dive_start_i])

        bleed_start_i = 0
        # if False:
        #     # In the case of T_SLOITER the bleed doesn't start immediately so
        #     # preserve all those points. We assume the CT is underwater. Thus for TSV
        #     # and thermal inertia purposes these points are valid.  However, other
        #     # instruments might be out of the water (like the optode on the mast) so
        #     # they might want to treat these points with care.
        #     #
        #     # Note however that TSV removes these points anyway because we eventually see the vehicle as 'stalled'
        #     # Changed (12/417) 1:12 to QC_PROBABLY_BAD because stalls avoid thermal-inertia salinity correction
        #     before_bleed_start_i = [
        #         i for i in dive_i_v if ctd_epoch_time_s_v[i] < gc_st_secs[0]
        #     ]
        #     if len(before_bleed_start_i):
        #         bleed_start_i = before_bleed_start_i[-1] + 1
        #     bleed_start_i = min(bleed_start_i, dive_start_i)

        if detect_vbd_bleed:
            QC.assert_qc(
                QC.QC_BAD,
                cond_cor_qc_v,
                list(range(bleed_start_i, dive_start_i)),
                "during VBD bleed",
            )  # mark bad up to but not including dive_start_i
        # Now truth to tell we could have a slow bleed and reach D_FLARE before the bleed is complete (taking two GC cycles)
        # So strictly we are accelerating during this second GC as well but we ignore it.

        # Find end of climb phase
        # Eliminate points at the end of the climb where we might have broached or bubbles might have formed
        # Note, however, if there was a deep bubble we would stop prematurely (this could still happen in the current case for short dives)
        # TODO: why are we not symmetrical and end the dive when we last fall below speedthreshold like dive?
        climb_dsurf_depth = surface_bubble_factor * dsurf
        # find points after apogee pump end that are shallower than climb_dsurf_depth
        # We have already marked points above ctd_depth_threshold as bad so don't need to use this here
        climb_dsurf_i_v = [
            i
            for i in climb_i_v
            if ctd_elapsed_time_s_v[i] > start_of_climb_time
            and ctd_depth_m_v[i] < climb_dsurf_depth
        ]
        climb_end_i = ctd_np_i + 1  # initialize
        if len(climb_dsurf_i_v):  # do we have a climb tail?
            if sbect_unpumped:  # when unpumped we care about bobbling around...
                # Now try to find where the dive ended and remove those points, if any
                pitch_end_v = ctd_vehicle_pitch_degrees_v[climb_dsurf_i_v]
                pend_i_v = [
                    i for i in range(len(climb_dsurf_i_v)) if pitch_end_v[i] > 0
                ]  # pitched up at all
                if len(pend_i_v):
                    # If we are bobbing on the surface we could see pitch oscillate around 0
                    # NOTE We could also see, but rarely, our pitch wobble around if we are struck by a whale at depth.  This would stop the dive prematurely
                    # Find the first index where we went to pitch <= 0 for more than 1 sample (which is where we first start bobbing)
                    diff_pend_i_v = np.diff(pend_i_v)
                    # Looks for gaps which indicate bobbling around
                    idpend_i_v = [
                        i for i in range(len(diff_pend_i_v)) if diff_pend_i_v[i] > 1
                    ]  # if we bob, we'll have gaps in the pitchup record
                    if len(idpend_i_v) > 0:
                        # We bobbed so truncate pend_i_v after the first gap, which starts from 0
                        pend_i_v = list(range(0, idpend_i_v[0] + 1))

                    # these are the indices where the CT tube is above climb_dsurf_depth and pitched up
                    climb_dsurf_i_v = np.array(climb_dsurf_i_v)[pend_i_v]
                    # Find where in this head of the climb (pend_i_v) both pressure went minimum and we are still pitched up
                    press_end_v = ctd_sg_press_v[climb_dsurf_i_v]
                    pmin_end = min(
                        press_end_v
                    )  # [dbar] What was min pressure before we went flat?
                    # Find the point of pmin_end in the full dive record
                    climb_end_i_v = [
                        i
                        for i in range(len(climb_dsurf_i_v))
                        if press_end_v[i] == pmin_end
                    ]
                    if not len(climb_end_i_v):
                        # probably because of a truncated dive (we never pitched up) ala sg144 jun09 dive 286
                        # could also be very stormy conditions that toss us around deeply sg120 jun09 dive dive 65, below the dsurf layer
                        log_warning(
                            "Can't find low pressure and pitched up condition for climb in %s; turbulent or truncated dive?"
                            % (eng_file_name)
                        )
                        DAC_qc = QC.update_qc(
                            QC.QC_PROBABLY_BAD, DAC_qc
                        )  # can't tell where flight stopped
                        # fall through w/ climb_end_i at end of dive
                    else:
                        # Assume climb ended where we first reached min pressure but were still pitched up
                        # We try to update (deepen) this point by looking for bubbles in the code below
                        climb_end_i = climb_dsurf_i_v[climb_end_i_v[0]]
                        climb_end_i = (
                            climb_end_i + 1
                        )  # climb_end_i was the last VALID point so move beyond this
                else:
                    # not pitched up within the normal surfacing depth...
                    # was never pitched up? OKMC Jun11 sg167 dives 31 and 32
                    # CONSIDER skip_profile % not pitched up on climb?
                    # could also mean we went into surface mode before $D_SURF?
                    # It is possible, e.g., faroes/nov06/sg101 dive 83 etc., to not have enough samples
                    # in the top climb_dsurf_depth m to catch her flipping from pitch up to down (so all we see is down)
                    # In this case we should only complain if any points are below actual D_SURF
                    # We already know all the points in climb_dsurf_i_v are pitched down; any below D_SURF?
                    pend_i_v = [i for i in climb_dsurf_i_v if ctd_depth_m_v[i] > dsurf]
                    if len(pend_i_v):
                        log_warning(
                            "Pitched down during climb below %.2f meters? - continuing but skipping DAC computation"
                            % dsurf
                        )
                        DAC_qc = QC.QC_BAD  # bad flight....

                # Done with these intermediate arrays
                # del pitch_end_v, pend_i_v, diff_pend_i_v, press_end_v, climb_dsurf_i_v
                for vv in (
                    "pitch_end_v",
                    "pend_i_v",
                    "diff_pend_i_v",
                    "press_end_v",
                    "climb_dsurf_i_v",
                ):
                    if vv in locals():
                        del locals()[vv]
        else:
            # If the data stops at pressures below climb_dsurf_depth, don't remove anything...
            # But see if we were truncated before we got near the surface
            # At this point we know the last data point was < climb_dsurf_depth
            # But if we are sampling very slowly or ascending very fast our last data point
            # might be just before hitting dsurf...
            predicted_last_sample_depth = (
                ctd_depth_m_v[-1] + np.diff(ctd_depth_m_v[-2:])
                if len(climb_i_v) > 1
                else ctd_depth_m_v[-1]
            )
            if predicted_last_sample_depth > dsurf:  # CONSIDER 5*dsurf?
                log_warning(
                    "Engineering data ends at %.2f meters; truncated dive? - continuing"
                    % ctd_depth_m_v[-1]
                )
                DAC_qc = QC.update_qc(
                    QC.QC_PROBABLY_BAD, DAC_qc
                )  # can't tell where flight stopped but if not too deep could be ok

        if climb_end_i <= ctd_np_i:  # anything to eliminate?
            climb_end_i = climb_end_i - 1
            QC.assert_qc(
                QC.QC_BAD,
                cond_cor_qc_v,
                list(range(climb_end_i, ctd_np)),
                "end of climb",
            )
        else:
            climb_end_i = ctd_np_i  # fo rebuilding climb_i_v below

        # order makes a differnce here!!
        ## mark bad conductivity points
        bad_cond_i_v = QC.manual_qc(
            directives,
            "bad_conductivity",
            "cond_QC_BAD",
            QC.QC_BAD,
            cond_cor_qc_v,
            "conductivity",
        )
        bad_cond_i_v = QC.bad_qc(cond_cor_qc_v)
        cond_cor_v[bad_cond_i_v] = BaseNetCDF.nc_nan  # MARK BAD

        interp_cond_i_v = QC.manual_qc(
            directives,
            "interp_conductivity",
            "cond_QC_INTERPOLATED",
            QC.QC_INTERPOLATED,
            cond_cor_qc_v,
            "conductivity",
        )
        cond_cor_v, cond_cor_qc_v = QC.interpolate_data_qc(
            cond_cor_v,
            ctd_elapsed_time_s_v,
            interp_cond_i_v,
            "conductivity",
            directives,
            cond_cor_qc_v,
            QC.QC_PROBABLY_BAD,
        )
        TraceArray.trace_array("cond_post_interp", cond_cor_v)

        for a in suspect_anomalies_v:
            still_good_i_v = [i for i in a.points() if cond_cor_qc_v[i] == QC.QC_GOOD]
            if len(still_good_i_v):
                directives.suggest(
                    "%s_conductivity data_points between %d %d %% %s"
                    % (
                        "bad" if a.qc() == QC.QC_BAD else "interp",
                        a.first_point() + 1,
                        a.last_point() + 1,
                        a.descr(),
                    )
                )

        # Now estimate an initial adjusted salinity based on adjusted temp and cond
        if not base_opts.use_gsw:
            salin_cor_v = seawater.salt(cond_cor_v / c3515, temp_cor_v, ctd_press_v)
        else:
            salin_cor_v = gsw.SP_from_C(cond_cor_v * 10.0, temp_cor_v, ctd_press_v)
        salin_cor_qc_v = QC.initialize_qc(ctd_np, QC.QC_GOOD)
        tc_bad_i_v = Utils.sort_i(
            Utils.union(bad_temp_i_v, bad_cond_i_v)
        )  # order for assert output
        salin_cor_v[tc_bad_i_v] = BaseNetCDF.nc_nan
        QC.assert_qc(
            QC.QC_BAD,
            salin_cor_qc_v,
            tc_bad_i_v,
            "bad corrected temperature and conductivity suggests bad salinity",
        )

        # rebuild dive_i_v and climb_i_v; DO NOT reset directives
        dive_i_v = list(
            range(dive_start_i, start_of_climb_i)
        )  # up to but not including the dive end
        climb_i_v = list(range(start_of_climb_i, climb_end_i + 1))

        # DEAD?  But consider that virtual mooring and D_NO_BLEED also causes slow down and fast up....
        # measured_average_dive_w_cm_s = np.abs(np.mean(ctd_w_cm_s_v[dive_i_v]))
        # measured_average_climb_w_cm_s = np.abs(np.mean(ctd_w_cm_s_v[climb_i_v]))
        # max_avg_w = max(measured_average_dive_w_cm_s, measured_average_climb_w_cm_s)
        # untrimmed_w_ratio = (
        #    1.0 - 0.2
        # )  # PARAMETER UNUSED ratio of dive to climb average w to detect untrimmed vehicle velocities (20% difference)
        # if False and (
        #     measured_average_dive_w_cm_s / max_avg_w < untrimmed_w_ratio
        #     or measured_average_climb_w_cm_s / max_avg_w < untrimmed_w_ratio
        # ):  # Turn this off unless we use it for something
        #     log_warning(
        #         "Dive %d: Untrimmed vehicle? Dive: %.2f cm/s Climb %.2f cm/s"
        #         % (
        #             dive_num,
        #             measured_average_dive_w_cm_s,
        #             measured_average_climb_w_cm_s,
        #         )
        #     )

        # Verify that we have enough data to create a profile
        # bad_samples = union1d(np.where(temp_cor_qc_v == QC.QC_BAD)[0],union1d(np.where(cond_cor_qc_v == QC.QC_BAD)[0],np.where(salin_cor_qc_v == QC.QC_BAD)[0]))
        bad_samples = [
            i
            for i in range(ctd_np)
            if QC.QC_BAD
            in (
                temp_cor_qc_v[i],
                cond_cor_qc_v[i],
                salin_cor_qc_v[i],
            )
        ]
        num_bad_samples = len(bad_samples)
        num_good_samples = ctd_np - num_bad_samples

        if not base_opts.allow_insufficient_dives and num_good_samples < 2:
            log_error(
                "Insufficient samples (%d of %d) to continue with CT corrections - bailing out"
                % (num_good_samples, ctd_np)
            )
            raise RuntimeError(True)

        # Setup to solve, perhaps iteratively, salinity and hydrodynamic speeds and angles
        # based on buoyancy forcing.  This could involve thermal-mass corrections.

        # Calculate Seaglider displaced volume
        volmax = calib_consts["volmax"]
        # use the values in the log file, not the pilot's fiction in sg_calib_constants.h
        # this is what the glider used

        vbd_min_cnts = log_f.data["$VBD_MIN"]
        vbd_cnts_per_cc = 1.0 / log_f.data["$VBD_CNV"]
        c_vbd = log_f.data["$C_VBD"]
        vbd0 = (
            volmax + (c_vbd - vbd_min_cnts) / vbd_cnts_per_cc
        )  # [cc] Minimum displaced volume achievable by Seaglider
        displaced_volume_v = (
            vbd0 + ctd_vbd_cc_v
        )  # [cc] measured displaced volume of glider as it varies by VBD adjustments

        therm_expan = calib_consts["therm_expan"]
        temp_ref = calib_consts["temp_ref"]  # typical temperature where ballasted (OSB)
        abs_compress = calib_consts["abs_compress"]

        vol_comp_v = 0
        vol_comp_ref = 0
        if mass_comp:
            # TODO modifiy this to be called once per set of dives and cached in a local
            compress_cnf, _ = Utils2.read_cnf_file(
                "compress.cnf",
                mission_dir=base_opts.mission_dir,
                encode_list=False,
                lower=False,
                results_d=results_d,
            )
            if compress_cnf:
                # T and P are already floats; convert A and B strings to lists of floats
                for tag in ["A", "B"]:
                    compress_cnf[tag] = [float(s) for s in compress_cnf[tag].split(",")]
            else:
                # Default compressee: hexamethyldisiloxane density based on T2P2 PTV SV and env_chamber data for red 1/2013
                # see matlab/cml_dens.m
                compress_cnf = {
                    "A": [-1.11368512753634, 796.461657048578],
                    "B": [
                        0.0102052829145449,
                        8.52182108882249e-05,
                        4.34927182961885e-07,
                        -1.30186206661706e-06,
                        -3.03705760249538e-08,
                        2.88293344499584e-10,
                        9.52846703487369e-11,
                        4.45151822732093e-12,
                        -1.00703879876029e-13,
                    ],
                    "T": 2,
                    "P": 2,
                }

            # adjust volume because of compressee at depth
            # vol [cc] = mass[g]/dens[g/cc]
            vol_comp_ref = mass_comp / compressee_density(
                np.array([temp_ref]), np.array([0]), compress_cnf
            )  # where we were ballasted
            vol_comp_v = mass_comp / compressee_density(
                temp_cor_v, ctd_press_v, compress_cnf
            )
            TraceArray.trace_array("vol_comp", temp_raw_qc_v)

        # TODO Account for hull volume compression with temp and presure
        # CCE reports that (all types of?) oil in the VBD unit changes volume by temperature
        # We have no term for this effect
        # 9/2015: Large changes (60AD = ~17cc) in VBD volume noted on deep DG dives into cold water off Bermuda
        # Estimated oil thermal expansion coefficient at 0.0004*(5/9) (1/degC) == 0.00022222
        # We have ~1000cc of oil so a temp change from 27C to 2C (25C) = 1000 * 0.000222 * 25 = 5.5cc
        # (For 17.5cc we need coefficient of 0.0007/C or 0.00126/F)

        # CCE points out that volmax (+ eng_vbd_cc) includes vol_comp to match overall neutral density
        # However, abs compression and thermal expansion only apply to the hull volume not the compressee fluid
        # so remove vol_comp to compute that effect and then add vol_comp to get total volume
        # We use vol_comp_ref since we want the assumed volume of the uncompressed hull on the reference surface
        # The abs_compress and therm_expan numbers are very small.  Even with DG at 6Km, the exp term is small (~1e-3)
        # so the exp term is approximately linear, i.e., 1+<term>.
        if base_opts.fm_isopycnal:
            volume_v = displaced_volume_v
        else:
            volume_hull_v = displaced_volume_v - vol_comp_ref
            volume_v = volume_hull_v * np.exp(
                -abs_compress * ctd_sg_press_v + therm_expan * (temp_cor_v - temp_ref)
            )
            volume_v = volume_v + vol_comp_v

        TraceArray.trace_array("vol", volume_v)
        # if False:
        #     log_info(
        #         "displaced_volume_v min:%f, max:%f, mean:%f"
        #         % (
        #             nanmin(displaced_volume_v),
        #             nanmax(displaced_volume_v),
        #             nanmean(displaced_volume_v),
        #         )
        #     )
        #     log_info(
        #         "volume_v min:%f, max:%f, mean:%f"
        #         % (nanmin(volume_v), nanmax(volume_v), nanmean(volume_v))
        #     )
        #     log_info("diff:%f" % nanmean(volume_v - displaced_volume_v))

        # TSV_f = TSV_iterative  # the only choice now; used to have two versions
        use_averaged_speeds = False

        modes = int(calib_consts["sbect_modes"])  # ensure integer
        explicit_calib_consts["sbect_modes"] = modes
        if modes not in [0, 1, 3, 5]:
            log_error(
                "Unknown number of thermal inertia modes: %d - bailing out" % modes
            )
            raise RuntimeError(True)

        if perform_thermal_inertia_correction:
            log_info("Using %d-mode thermal-inertia correction." % modes)
        elif sg_ct_type == 4:
            log_info("Skipping TSV based thermal-inertia correction for Legatto.")
        else:
            if perform_thermal_inertia_correction:
                log_info("Using %d-mode thermal-inertia correction." % modes)
            elif calib_consts["sg_ct_type"] == 4:
                # Issue no notification since legato corrections will happen later
                pass
            else:
                log_info("Not performing thermal-inertia correction.")

        load_thermal_inertia_modes(base_opts, num_modes=modes)

        # Compute consistent lag corrected temperature, salinity and flight speeds assuming still water
        # We bind some of the results to tmc_ vars in case we need to call TSV_f again
        # We don't want to make the second call with the bad results from the first
        (
            converged,
            tmc_temp_cor_v,
            tmc_temp_cor_qc_v,
            tmc_salin_cor_v,
            tmc_salin_cor_qc_v,
            density_v,
            density_insitu_v,
            buoyancy_v,
            hdm_speed_cm_s_v,
            hdm_glide_angle_rad_v,
            speed_qc_v,
        ) = TSV_iterative(
            base_opts,
            ctd_elapsed_time_s_v,
            start_of_climb_i,
            temp_cor_v,
            temp_cor_qc_v,
            cond_cor_v,
            cond_cor_qc_v,
            salin_cor_v,
            salin_cor_qc_v,
            ctd_press_v,
            ctd_vehicle_pitch_degrees_v,
            calib_consts,
            directives,
            volume_v,
            perform_thermal_inertia_correction,
            interpolate_extreme_tmc_points,
            use_averaged_speeds,
            ctd_gsm_speed_cm_s_v,
            ctd_gsm_glide_angle_deg_v,
            longitude,
            latitude,
        )  # BREAK
        if not converged and not use_averaged_speeds:
            # Sometimes averaging the velocities converges....
            (
                converged,
                tmc_temp_cor_v,
                tmc_temp_cor_qc_v,
                tmc_salin_cor_v,
                tmc_salin_cor_qc_v,
                density_v,
                density_insitu_v,
                buoyancy_v,
                hdm_speed_cm_s_v,
                hdm_glide_angle_rad_v,
                speed_qc_v,
            ) = TSV_iterative(
                base_opts,
                ctd_elapsed_time_s_v,
                start_of_climb_i,
                temp_cor_v,
                temp_cor_qc_v,
                cond_cor_v,
                cond_cor_qc_v,
                salin_cor_v,
                salin_cor_qc_v,
                ctd_press_v,
                ctd_vehicle_pitch_degrees_v,
                calib_consts,
                directives,
                volume_v,
                perform_thermal_inertia_correction,
                interpolate_extreme_tmc_points,
                True,  # force averaging and hope
                ctd_gsm_speed_cm_s_v,
                ctd_gsm_glide_angle_deg_v,
                longitude,
                latitude,
            )

            if converged:
                log_info("TSV correction converged using averaged speeds")
        if not converged:
            log_warning("TSV correction unable to converge")
            directives.suggest("skip_profile % nonconverged")

        if sg_ct_type == 4:
            (
                _,
                corr_temperature,
                corr_temperature_qc,
                corr_salinity,
                corr_salinity_qc,
                _,
                _,
                _,
            ) = LegatoCorrections.legato_correct_ct(
                base_opts,
                calib_consts,
                ctd_epoch_time_s_v,
                ctd_press_v,
                temp_cor_v,
                temp_cor_qc_v,
                cond_cor_v,
                cond_cor_qc_v,
                salin_cor_v,
                salin_cor_qc_v,
                ctd_condtemp_v,
            )
            # CONDSIDER: Add corr_salinity_lag_only, corr_conductivity and corr_pressure to netcdf file
            temp_cor_v = corr_temperature
            temp_cor_qc_v = corr_temperature_qc
            salin_cor_v = corr_salinity
            salin_cor_qc_v = corr_salinity_qc
        else:
            # Rebind these to our corrected versions
            temp_cor_v = tmc_temp_cor_v
            temp_cor_qc_v = tmc_temp_cor_qc_v
            salin_cor_v = tmc_salin_cor_v
            salin_cor_qc_v = tmc_salin_cor_qc_v

        # finally, after all adjustments, update final salinity qc
        # no change to temp or cond expected but salin is corrected
        _, _, salin_cor_qc_v = QC.qc_checks(
            [],
            [],
            [],
            [],
            salin_cor_v,
            salin_cor_qc_v,
            ctd_depth_m_v,
            calib_consts,
            calib_consts["QC_bound_action"],
            calib_consts["QC_spike_action"],
        )
        # If we check temp again (for spikes introducted by halocline interpolation)
        # then we need to inherit to salinity?  qc_checks does this...
        # by inheritance, any place we interpolated for temp_cor or cond_cor we interpolated for salinity
        QC.inherit_qc(
            temp_cor_qc_v, salin_cor_qc_v, "corrected temp", "corrected salinity"
        )

        # TODO? ARGO implements a density inversion QC check
        # They look for monotonically increasing (and then decreasing) densities over the profile
        # Any reversals are marked QC_BAD in temperature and salinity
        # We would supply a density_qc_v and use it for all derived products

        bad_salin_i_v = QC.manual_qc(
            directives,
            "bad_salinity",
            "salin_QC_BAD",
            QC.QC_BAD,
            salin_cor_qc_v,
            "salinity",
        )
        bad_salin_i_v = QC.bad_qc(salin_cor_qc_v)
        salin_cor_v[bad_salin_i_v] = BaseNetCDF.nc_nan  # MARK BAD
        # All done with salinity, so mark the inherited bits (declarative)
        QC.inherit_qc(
            temp_cor_qc_v, salin_cor_qc_v, "corrected temp", "corrected salinity"
        )
        QC.inherit_qc(
            cond_cor_qc_v, salin_cor_qc_v, "corrected cond", "corrected salinity"
        )
        # len(np.where(salin_cor_qc_v != QC.QC_GOOD)[0])
        if len([i for i in range(ctd_np) if salin_cor_qc_v[i] != QC.QC_GOOD]) > int(
            calib_consts["QC_overall_ctd_percentage"] * ctd_np
        ):
            CTD_qc = QC.QC_BAD  # too many points bad

        if not converged:
            log_warning(
                "Unable to find consistent solutions for HDM velocity and salinity!"
            )
            CTD_qc = QC.QC_BAD
            hdm_qc = QC.QC_BAD

        sfc_drift_interval_i = None
        if calib_consts["solve_flare_apogee_speed"] and (hdm_qc == QC.QC_GOOD):
            # Unsteady flight

            # During pumps and bleeds the VBD system on all vehicles is moving
            # linearly so the buoyancy forcing is changing linearly,
            # accelerating the vehicle.  The more-general momentum balance
            # equations of the flight model apply to unsteady flight in this
            # regime.  We solve them for U and W numerically via integration
            # from estimated starting velocities.

            # Perform these fits after TSV since that only deals with steady
            # flight and assumes the accelerations can be ignored.  Perhaps we
            # should adjust salinity using these speeds and trust the initial
            # speeds anyway but that is for later.  However TSV will see slow
            # speeds and declare stalled soon enough with no gain so we'll have
            # to 'patch' salinity and salinity_qc here--if acceleration model is
            # on, patch things? At the moment, just ignore it.

            # Unpack these once in this scope
            hd_a = calib_consts["hd_a"]
            hd_b = calib_consts["hd_b"]
            hd_c = calib_consts["hd_c"]
            hd_s = calib_consts["hd_s"]
            rho0 = calib_consts["rho0"]
            glider_length = calib_consts["glider_length"]
            mass_kg = calib_consts["mass"]  # critical to have this in kg
            gravity = 9.82  # m/s2
            rhoxl2_2m = (rho0 * glider_length * glider_length) / (2 * mass_kg)
            if base_opts.fm_isopycnal:
                dens_raw_v = seawater.pden(salin_raw_v, temp_raw_v, ctd_press_v)
            else:
                dens_raw_v = seawater.dens(salin_raw_v, temp_raw_v, ctd_press_v)
            buoy_v = kg2g * (dens_raw_v * volume_v * 1e-6 - mass_kg)  # [g]

            # The sampling grid is often not aligned with motor moves
            # For the purposes of determining speeds we need to know when the motors move
            # and whay the values of pitch and buoyancy were at the start and finish
            # An expedient is to duplicate and adjust copies of the time grid of when samples were taken
            # to align with the motor.  The sampled data thenselves are largely unchanged (see flare).
            # These times and data are then interpolated onto a fine-grained time-grid for integration.
            pitch_time_v = np.copy(ctd_elapsed_time_s_v)
            buoy_time_v = np.copy(ctd_elapsed_time_s_v)

            def adjust_pitch_vbd_times(gc_i):
                pitch_secs = gc_pitch_secs[gc_i]
                roll_secs = gc_roll_secs[gc_i]
                vbd_secs = np.abs(gc_vbd_secs[gc_i])
                elapsed_st_secs = gc_st_secs[gc_i] - ctd_epoch_time_s_v[0]
                # in all moves assume the sequence is pitch/roll/vbd
                if pitch_secs:
                    move_time = elapsed_st_secs + 0
                    # DabobBayURIData p6530023 pitch data not recorded until 2nd GC started
                    # in thee cases, no motion is possible or required
                    try:
                        i = np.where(pitch_time_v <= move_time)[0][-1]  # just before
                        pitch_time_v[i] = move_time
                        # log_debug('Pitch st %d: %d to %.2fs' % (gc_i,i,move_time))
                    except IndexError:
                        pass
                    move_time = elapsed_st_secs + pitch_secs
                    try:
                        i = np.where(pitch_time_v >= move_time)[0][0]  # just after
                        pitch_time_v[i] = move_time
                        # log_debug('Pitch ed %d: %d to %.2fs' % (gc_i,i,move_time))
                    except IndexError:
                        pass
                if vbd_secs:
                    move_time = elapsed_st_secs + pitch_secs + roll_secs + 0
                    try:
                        i = np.where(buoy_time_v <= move_time)[0][-1]  # just before
                        buoy_time_v[i] = move_time
                        # log_debug('VBD st %d: %d to %.2fs' % (gc_i,i,move_time))
                    except IndexError:
                        pass
                    move_time = elapsed_st_secs + pitch_secs + roll_secs + vbd_secs
                    try:
                        i = np.where(buoy_time_v >= move_time)[0][0]  # just after
                        buoy_time_v[i] = move_time
                        # log_debug('VBD ed %d: %d to %.2fs' % (gc_i,i,move_time))
                    except IndexError:
                        pass

            # Flare interval
            flare_gc_i = 1  # the flare GC is always the 2nd GC
            pitch_oscillation_s = (
                30  # PARAMETER typically 30s to dampen after the flare pitch up
            )
            end_flare_s = (
                gc_st_secs[flare_gc_i]
                + gc_pitch_secs[flare_gc_i]
                + np.abs(gc_vbd_secs[flare_gc_i])
                + pitch_oscillation_s
            )  # epoch_secs
            ed_flare_i = list(
                filter(
                    lambda t_i: ctd_epoch_time_s_v[t_i] >= end_flare_s
                    and speed_qc_v[t_i] == QC.QC_GOOD,
                    range(ctd_np),
                )
            )
            ed_flare_i = ed_flare_i[0]
            underwater_i = np.where(buoy_v <= 0)[0][0]
            flare_i = underwater_i  # start flare here for DAC
            sfc_drift_interval_i = range(0, underwater_i + 1)
            # See how much of apogee and climb we can find
            apogee_ok = False
            if apo_gc_i is not None:
                apo_pump_st_time = (
                    apogee_pump_start_time + i_eng_file_start_time
                )  # back to epoch time
                apo_pump_ed_time = (
                    apo_pump_st_time + gc_pitch_secs[apo_gc_i] + gc_vbd_secs[apo_gc_i]
                )
                st_apo_i = list(
                    filter(
                        lambda t_i: ctd_epoch_time_s_v[t_i] <= apo_pump_st_time
                        and speed_qc_v[t_i] == QC.QC_GOOD,
                        range(ctd_np),
                    )
                )
                if len(st_apo_i):
                    st_apo_i = st_apo_i[-1]  # last good point
                    ed_apo_i = np.where(ctd_epoch_time_s_v >= apo_pump_ed_time)[0][0]
                    # UNUSED apogee_start_speed = hdm_speed_cm_s_v[st_apo_i]
                    apogee_ok = True
                else:
                    log_warning("Unable to compute acceleration during flare")

            # Climb interval
            # climb starts with first pump after apogee pump and LOITER (which could involve pumps and bleeds)
            climb_pump_ok = False
            if climb_pump_gc_i is not None:
                adjust_pitch_vbd_times(climb_pump_gc_i)
                # UNUSED climb_pump_st_time = gc_st_secs[climb_pump_gc_i]
                # UNUSED st_climb_pump_i = np.where(ctd_epoch_time_s_v >= climb_pump_st_time)[0][0]
                # ed_climb_pump_i = np.where(ctd_epoch_time_s_v >= gc_end_secs[climb_gc_i] and speed_qc_v == QC.QC_GOOD)[0][0]
                ed_climb_pump_i = list(
                    filter(
                        lambda t_i: ctd_epoch_time_s_v[t_i]
                        >= gc_end_secs[climb_pump_gc_i]
                        and speed_qc_v[t_i] == QC.QC_GOOD,
                        range(ctd_np),
                    )
                )
                # could have a bad climb sg179_Shilshole_05Aug28_base2/p1790001 where something went wrong so speed_qc is bad
                if len(ed_climb_pump_i):
                    ed_climb_pump_i = ed_climb_pump_i[0]
                    # UNUSED climb_pump_end_speed = hdm_speed_cm_s_v[ed_climb_pump_i]
                    climb_pump_ok = True
                else:
                    log_warning("Unable to compute acceleration during climb pump")

            def fit_unsteady_flight(
                interval_i_v, acceleration_type, buoyancy_threshold=0
            ):
                interval_i_v = np.array(interval_i_v)
                n_pts = len(interval_i_v)
                if n_pts < 2:
                    log_warning("No detectable %s?" % acceleration_type)
                    return  # unable to do anything
                # Find where we will start the integration and map the results back to on the original time grid
                us_flying_i = np.where(buoy_v[interval_i_v] <= buoyancy_threshold)[0][0]
                under_interval_i_v = interval_i_v[us_flying_i:]  # original grid indices

                # Now form a finer time grid for the integration
                etime = ctd_elapsed_time_s_v[interval_i_v]
                # interpolate (valid) buoyancy and pitch in the interval to a new time grid
                dt = min(
                    int(np.mean(np.diff(etime))), 5
                )  # PARAMETER 5 secs is good..some vbd motion
                et = np.arange(etime[0], etime[-1] + 1, dt)
                n_pts = len(et)  # length of new grid

                valid_i_v = filter(lambda i: not np.isnan(buoy_v[i]), interval_i)
                # Assume that pitch and buoyancy motion is linear between data points
                bu = Utils.interp1d(buoy_time_v[valid_i_v], buoy_v[valid_i_v], et)
                phd = Utils.interp1d(
                    pitch_time_v[interval_i], vehicle_pitch_degrees_v[interval_i_v], et
                )
                # if False:  # DEBUG
                #     log_debug("%s time: %s" % (acceleration_type, et))
                #     log_debug("%s buoy: %s" % (acceleration_type, bu))
                #     log_debug("%s pitch: %s" % (acceleration_type, phd))

                # Find the starting speeds for the integration on the fine grid
                # Here is the rub: we need good starting speeds for W and U so we use the hydro_model
                # to find the speeds where buoyancy/pitch is good (here 'underwater_i')
                # This works for the start of flare (after buoyancy goes negative) and apogee (where it is negative)
                # but if we thought to split apogee and climb because there is a long loiter then we don't know the
                # starting speeds to assume on the pump.  At the moment we integrate across the loiter with whatever
                # densities were recorded (if really long, e.g., sg128_NASCAR_Jan18_loiter/p1280620, then
                # frequenty there is NO data taken while asleep)
                _, umag, th, _ = hydro_model(
                    bu, phd, calib_consts
                )  # hydro takes buoyancy in [g]
                # find where to start the integration in the fine grid
                us_flying_i = np.where(bu <= buoyancy_threshold)[0][0]
                th_start = th[us_flying_i]
                umag_start = umag[us_flying_i]
                umag_start = max(umag_start, 0.002)  # avoid DBZ in unsteady_flight
                Us, Ws = Utils.pol2cart(th_start, umag_start / m2cm)
                bu *= (
                    gravity / kg2g
                )  # Convert bu from [g] to [N] for use in unsteady_flight()

                # function to compute the derivates of U and W that solve_ivp integrates
                def unsteady_flight(t, u):
                    st_i = np.where(et <= t)[0][-1]  # always succeeds
                    ed_i = np.where(et >= t)[0]
                    ed_i = st_i if len(ed_i) == 0 else ed_i[0]
                    if st_i != ed_i:
                        B = Utils.interp1d(
                            [et[st_i], et[ed_i]], [bu[st_i], bu[ed_i]], [t]
                        )[0]
                        phdi = Utils.interp1d(
                            [et[st_i], et[ed_i]], [phd[st_i], phd[ed_i]], [t]
                        )[0]
                    else:
                        B = bu[st_i]
                        phdi = phd[st_i]
                    U = u[0]
                    W = u[1]
                    th, V = Utils.cart2pol(U, W)
                    thd = math.degrees(th)
                    ald = phdi - thd
                    q = 0.5 * rho0 * V * V
                    # From lift drag momentum balance equations given our typical quadratic flight model in q
                    dUdt = rhoxl2_2m * (
                        -hd_a * ald * W * V
                        - (hd_b * q**hd_s + hd_c * ald * ald) * U * V
                    )
                    dWdt = B / mass_kg + rhoxl2_2m * (
                        hd_a * ald * U * V - (hd_b * q**hd_s + hd_c * ald * ald) * W * V
                    )
                    # log_debug('UF: %.2f %s %.3f %.3f %.2f %.2f' %(t,u,dUdt,dWdt,B,phdi))
                    return [dUdt, dWdt]

                sol = scipy.integrate.solve_ivp(
                    unsteady_flight, [et[us_flying_i], et[-1]], [Us, Ws], "RK45"
                )
                # map back to original times and indices (even if no valid densities?)
                th, vv = Utils.cart2pol(
                    Utils.interp1d(
                        sol.t, sol.y[0, :], ctd_elapsed_time_s_v[under_interval_i_v]
                    ),
                    Utils.interp1d(
                        sol.t, sol.y[1, :], ctd_elapsed_time_s_v[under_interval_i_v]
                    ),
                )
                hdm_speed_cm_s_v[under_interval_i_v] = vv * m2cm
                hdm_glide_angle_rad_v[under_interval_i_v] = th
                QC.assert_qc(
                    QC.QC_PROBABLY_GOOD,
                    speed_qc_v,
                    under_interval_i_v,
                    acceleration_type,
                )

            # Compute flare accelerations
            interval_i = range(0, ed_flare_i + 1)
            fit_unsteady_flight(interval_i, "flare acceleration")

            # We compute apogee/loiter/climb pump in one long integration
            ed_i = None
            if apogee_ok:
                ed_i = ed_apo_i

            if climb_pump_ok:
                ed_i = ed_climb_pump_i
            if ed_i:
                interval_i = range(st_apo_i, ed_i + 1)
                fit_unsteady_flight(
                    interval_i, "apogee deceleration and climb acceleration"
                )
                # not going slow here when computing DAC etc. but consider loiter suspect
                slow_apogee_climb_pump_i_v = Utils.setdiff(
                    slow_apogee_climb_pump_i_v, Utils.setdiff(interval_i, loiter_i_v)
                )

        if hdm_qc == QC.QC_GOOD:
            # check for stalled or stuck on bottom points
            # if there are a lot of them, then the overall hdm quality is bad
            # we can get lots of 'stalled' points if we are, for example, pitched up and descending
            unsampled_i_v = np.nonzero(salin_cor_qc_v == QC.QC_UNSAMPLED)[
                0
            ]  # in the case of T_TURN_SAMPINT,-n for example
            hdm_bad_i_v = Utils.setdiff(
                bad_i_v, unsampled_i_v
            )  # unsampled points don't count
            hdm_bad_i_v = Utils.setdiff(
                hdm_bad_i_v, slow_apogee_climb_pump_i_v
            )  # apogee and LOITER points don't count
            hdm_bad_i_v = Utils.union(
                hdm_bad_i_v, stuck_i_v
            )  # add any points where we are stuck on the bottom before or after apogee
            n_bad = len(hdm_bad_i_v)
            # hdm_stalled_i_v = np.where(hdm_speed_cm_s_v == 0.0)[0]
            hdm_stalled_i_v = [i for i in range(ctd_np) if hdm_speed_cm_s_v[i] == 0.0]
            n_stalled = len(hdm_stalled_i_v)
            log_info(
                "%d (%.2f%%) HDM speeds are QC_BAD; %d (%.2f%%) are stalled (%d)"
                % (
                    n_bad,
                    (float(n_bad) / ctd_np) * 100.0,
                    n_stalled,
                    (float(n_stalled) / ctd_np) * 100.0,
                    ctd_np,
                )
            )
            # Ignore stalled points (it is still a good estimate even if stalled and DAC still works
            # as long as we aren't stuck on the bottom; regressions might want to filter dives where
            # happen however)
            # DEAD hdm_bad_i_v = Utils.union(hdm_bad_i_v,hdm_stalled_i_v)
            fraction_bad = float(len(hdm_bad_i_v)) / ctd_np
            if fraction_bad > calib_consts["QC_overall_speed_percentage"]:
                log_warning("Declaring overall speed qc as QC_BAD!")
                hdm_qc = QC.QC_BAD

        # DEAD? just in case temperature was interpolated
        QC.inherit_qc(temp_cor_qc_v, speed_qc_v, "corrected temp", "speed")
        bad_speed_i_v = QC.bad_qc(speed_qc_v)
        hdm_horizontal_speed_cm_s_v = hdm_speed_cm_s_v * np.cos(hdm_glide_angle_rad_v)
        hdm_w_speed_cm_s_v = hdm_speed_cm_s_v * np.sin(hdm_glide_angle_rad_v)
        hdm_glide_angle_deg_v = np.degrees(hdm_glide_angle_rad_v)
        # if False:  # DEAD?  informational only at present.  Add a result variable?
        #     z_speed_cm_s = np.array(hdm_speed_cm_s_v)  # copy
        #     z_speed_cm_s[bad_speed_i_v] = 0
        #     average_estimated_speed_cm_s = np.average(fabs(z_speed_cm_s))
        #     log_info(
        #         "Average estimated final speed: %.2f cm/s"
        #         % average_estimated_speed_cm_s
        #     )
        #     z_speed_cm_s = hdm_w_speed_cm_s_v - ctd_w_cm_s_v
        #     z_speed_cm_s[bad_speed_i_v] = 0
        #     log_info(
        #         "RMS observed vs. computed w: %.2f cm/s"
        #         % np.sqrt(np.mean(z_speed_cm_s**2))
        #     )
        #     z_speed_cm_s = None  # done w/ intermediate

        results_d.update(
            {
                # Adjusted water column observations
                "temperature": temp_cor_v,
                "temperature_qc": temp_cor_qc_v,
                "conductivity": cond_cor_v,
                "conductivity_qc": cond_cor_qc_v,
                "salinity": salin_cor_v,
                "salinity_qc": salin_cor_qc_v,
                "buoyancy": buoyancy_v,
                # Computed flight parameters based on hydromodel
                "speed": hdm_speed_cm_s_v,
                "glide_angle": hdm_glide_angle_deg_v,
                "horz_speed": hdm_horizontal_speed_cm_s_v,
                "vert_speed": hdm_w_speed_cm_s_v,
                "speed_qc": speed_qc_v,
                # scalars
                "CTD_qc": CTD_qc,
                "hdm_qc": hdm_qc,
            }
        )

        TraceArray.trace_array("temp_cor_qc", temp_cor_qc_v)
        TraceArray.trace_array("cond_cor_qc", cond_cor_qc_v)
        TraceArray.trace_array("salin_cor_qc", salin_cor_qc_v)
        TraceArray.trace_array("speed_qc", speed_qc_v)
        QC.report_qc("temp_cor_qc", temp_cor_qc_v)
        QC.report_qc("cond_cor_qc", cond_cor_qc_v)
        QC.report_qc("salin_cor_qc", salin_cor_qc_v)
        QC.report_qc("speed_qc", speed_qc_v)

        if not base_opts.use_gsw:
            # sigma_t_v AKA density_v - 1000
            sigma_t_v = (
                seawater.dens(salin_cor_v, temp_cor_v, np.zeros(salin_cor_v.size))
                - 1000.0
            )
            temp_cor_pot_v = seawater.ptmp(
                salin_cor_v, temp_cor_v, ctd_sg_press_v, pr=0.0
            )
            sigma_theta_v = (
                seawater.dens(salin_cor_v, temp_cor_pot_v, np.zeros(salin_cor_v.size))
                - 1000.0
            )  # defn: (potential density at P=0) - 1000
            sound_vel_v = seawater.svel(salin_cor_v, temp_cor_v, ctd_sg_press_v)
        else:
            sigma_t_v = (
                Utils.density(
                    salin_cor_v,
                    temp_cor_v,
                    np.zeros(salin_cor_v.size),
                    longitude,
                    latitude,
                )
                - 1000.0
            )
            temp_cor_pot_v = Utils.ptemp(
                salin_cor_v, temp_cor_v, ctd_sg_press_v, longitude, latitude, pref=0.0
            )
            sigma_theta_v = (
                Utils.density(
                    salin_cor_v,
                    temp_cor_pot_v,
                    np.zeros(salin_cor_v.size),
                    longitude,
                    latitude,
                )
                - 1000.0
            )  # defn: (potential density at P=0) - 1000
            sound_vel_v = Utils.svel(
                salin_cor_v, temp_cor_v, ctd_sg_press_v, longitude, latitude
            )

        [oxygen_sat_seawater_v, _, _] = Utils.compute_oxygen_saturation(
            temp_cor_v, salin_cor_v
        )
        results_d.update(
            {
                "sigma_t": sigma_t_v,  # CF sea_water_sigma_t g/L
                "theta": temp_cor_pot_v,
                "density": density_v,  # CF: (potential) sea_water_density g/L
                "density_insitu": density_insitu_v,  # insitu sea_water_density g/L
                "sigma_theta": sigma_theta_v,  # CF: sea_water_sigma_theta g/L
                "sound_velocity": sound_vel_v,
                "dissolved_oxygen_sat": oxygen_sat_seawater_v,  # oxygen solubility in seawater (uM/kg)
            }
        )
        try:
            if log_f.data["$DEEPGLIDER"] == 1:
                # regardless of depth achieved since we might add to MMT, etc.
                if not base_opts.use_gsw:
                    sigma_theta3_v = (
                        seawater.dens(
                            salin_cor_v,
                            temp_cor_pot_v,
                            np.zeros(salin_cor_v.size) + 3000.0,
                        )
                        - 1000
                    )  # defn: (potential density at P=3000m) - 1000
                    sigma_theta4_v = (
                        seawater.dens(
                            salin_cor_v,
                            temp_cor_pot_v,
                            np.zeros(salin_cor_v.size) + 4000.0,
                        )
                        - 1000
                    )  # defn: (potential density at P=4000m) - 1000
                else:
                    sigma_theta3_v = (
                        Utils.density(
                            salin_cor_v,
                            temp_cor_pot_v,
                            np.zeros(salin_cor_v.size) + 3000.0,
                            longitude,
                            latitude,
                        )
                        - 1000.0
                    )  # defn: (potential density at P=3000m) - 1000
                    sigma_theta4_v = (
                        Utils.density(
                            salin_cor_v,
                            temp_cor_pot_v,
                            np.zeros(salin_cor_v.size) + 4000.0,
                            longitude,
                            latitude,
                        )
                        - 1000.0
                    )  # defn: (potential density at P=4000m) - 1000
                results_d.update(
                    {
                        "sigma3": sigma_theta3_v,
                        "sigma4": sigma_theta4_v,
                    }
                )
        except KeyError:
            pass

        #
        # Displacement calculations - common calculations
        #

        # Basic conversions and quantities for displacement calculations

        # Estimate surface currents (set and drift)
        # to calculate the DAC we need to account for two effects: the time it
        # took to do the surface maneuver (a stalled drift, not part of the time
        # record of flight) and any time we were stuck on the bottom, which
        # stops our sampling of the DAC.  See the stuck calculation above.

        if hdm_qc == QC.QC_BAD:
            # we depend on a good set of HDM flight speed values below
            # if we don't have them, we can't compute DAC
            DAC_qc = QC.QC_BAD

        SM_time_s = 0  # [s] assume SM takes no time
        if GPS2E_ok:
            # the actual surface maneuver starts after the last eng data is taken
            # not, e.g., when last CT was taken (since that could be via GPCTD or scicon)
            SM_time_s = (
                gps_dive_time_s - elapsed_time_s_v[-1]
            )  # time of surface maneuver

        # NB: this will be the same as ctd_elapsed_time_s_v if no bottom time
        flight_time_v = np.cumsum(ctd_delta_time_s_v)  # actual elapsed times flying
        # NOTE do not include gps_drift_time_s because we compute DAC between GPS2 and final GPS, ignoring surface current
        # We report that separately
        total_flight_and_SM_time_s = (
            flight_time_v[-1] + SM_time_s
        )  # final elapsed time flying and drifting
        log_info(
            "Estimated total flight and drift time: %.1fs (SM: %.1fs)"
            % (total_flight_and_SM_time_s, SM_time_s)
        )

        if DAC_qc != QC.QC_BAD:
            if total_flight_and_SM_time_s <= 0:
                log_warning(
                    "No flight and surface maneuver time! - possible corrupted log file?"
                )
                DAC_qc = QC.QC_BAD

            # The flight model, whether GSM or HDM, does not do well if we are not flying
            # Compute an estimate of the amount of time unmodelled and if it is sufficiently large
            # percentage of the dive, scrub DAC confidence.  This will often kill PS dives though the
            # basic signal is in the right direction.
            substantial_untrusted_model_time = (
                0.20  # more than 20% of the dive time without a model? don't trust DAC
            )
            untrusted_model_time = SM_time_s  # unpowered surface time
            if (
                len(slow_apogee_climb_pump_i_v) > 0
            ):  # apogee is decelerating and accelerating
                untrusted_model_time += (
                    ctd_elapsed_time_s_v[slow_apogee_climb_pump_i_v[-1]]
                    - ctd_elapsed_time_s_v[slow_apogee_climb_pump_i_v[0]]
                )
            if flare_i:  # before flare is accelerating
                untrusted_model_time += ctd_elapsed_time_s_v[flare_i]
            untrusted_fraction = untrusted_model_time / total_flight_and_SM_time_s
            if untrusted_fraction > substantial_untrusted_model_time:
                log_warning(
                    "Substantial unmodeled flight time (%.1f%% of total time); DAC is bad."
                    % (untrusted_fraction * 100)
                )
                # TODO or should this be QC_PROBABLY_BAD?
                DAC_qc = QC.QC_BAD

            # In addition to bottom time (see above), CCE recalls on later faroes
            # missions that there were dives where substantial upwelling just balanced
            # the downward flight of the glider so obs w was zero even though the
            # glider was flying.  In these cases we actually triggered T_NO_W at 5
            # minutes!!  Although we are flying we are making no progress so we
            # count the DAC as suspect.
            # NOTE: hdm_w_speed_cm_s_v can sometimes have nan's and so will diff_w after a warning but
            # the ratio calculation handles the result fine--nan's are ignored.
            diff_w = np.abs(ctd_w_cm_s_v - hdm_w_speed_cm_s_v)
            large_up_down_welling_speeds = 5  # PARAMETER [cm/s] difference between observed and calculated w to suggest big heaving
            ratio_upwelling = 0.1  # PARAMETER ratio of data points where there are big excursions (more than this is an issue)
            # large_w_diff_i_v = np.where(diff_w > large_up_down_welling_speeds)[0]
            large_w_diff_i_v = [
                i
                for i in range(len(diff_w))
                if diff_w[i] > large_up_down_welling_speeds
            ]
            if float(len(large_w_diff_i_v)) / ctd_np > ratio_upwelling:
                log_warning(
                    "Large mis-match between predicted and observed w; significant up/downwelling or poor flight model. DAC suspect."
                )
                DAC_qc = QC.update_qc(
                    QC.QC_PROBABLY_BAD, DAC_qc
                )  # can't really trust the result

            sfc_loiter_s = log_f.data.get("$T_SLOITER", 0)
            # If the pilot used T_LOITER at bottom of dive we are oversampling that depth.
            # Same thing for T_SLOITER on the surface.
            # If the combined time is > 10% of the dive time, consider it suspect
            loiter_time_s = apo_loiter_s + sfc_loiter_s
            # TODO - need to check the state gc table to see if the glider actually is loitering
            if loiter_time_s > np.abs(total_flight_and_SM_time_s) / 10:
                log_warning(
                    "Glider loitered for %d seconds; DAC suspect." % loiter_time_s
                )
                DAC_qc = QC.update_qc(
                    QC.QC_PROBABLY_BAD, DAC_qc
                )  # can't really trust the result

        if hdm_qc != QC.QC_BAD:  # if not obviously QC_BAD compute displacements
            z_hdm_horizontal_speed_cm_s_v = np.array(hdm_horizontal_speed_cm_s_v)
            z_hdm_horizontal_speed_cm_s_v[bad_speed_i_v] = 0
            z_displacement_m = (
                sum(z_hdm_horizontal_speed_cm_s_v * ctd_delta_time_s_v) / m2cm
            )
            TraceArray.trace_array("z_hspd", z_hdm_horizontal_speed_cm_s_v)
            TraceArray.trace_comment("z_displacement = %f" % z_displacement_m)

            # TODO CCE suggests that since hspd can vary that we find each gap and interpolate then average n/e components of local hspd
            avg_speed_dive = np.mean(
                z_hdm_horizontal_speed_cm_s_v[Utils.setdiff(dive_i_v, bad_speed_i_v)]
            )
            z_hdm_horizontal_speed_cm_s_v[Utils.intersect(bad_speed_i_v, dive_i_v)] = (
                avg_speed_dive
            )
            avg_speed_climb = np.mean(
                z_hdm_horizontal_speed_cm_s_v[Utils.setdiff(climb_i_v, bad_speed_i_v)]
            )
            z_hdm_horizontal_speed_cm_s_v[Utils.intersect(bad_speed_i_v, climb_i_v)] = (
                avg_speed_climb
            )
            z_hdm_horizontal_speed_cm_s_v[slow_apogee_climb_pump_i_v] = 0
            avg_displacement_m = (
                sum(z_hdm_horizontal_speed_cm_s_v * ctd_delta_time_s_v) / m2cm
            )
            TraceArray.trace_array("avg_hspd", z_hdm_horizontal_speed_cm_s_v)
            TraceArray.trace_comment("avg_displacement = %f" % avg_displacement_m)

            percent_error = (1.0 - z_displacement_m / avg_displacement_m) * 100.0
            if percent_error > 10:  # PARAMETER more than 10% error?
                log_warning(
                    "Displacements under-estimate likely positions by %.1f%%; DAC suspect"
                    % percent_error
                )
                DAC_qc = QC.QC_BAD
            del (
                z_hdm_horizontal_speed_cm_s_v,
                avg_speed_dive,
                avg_speed_climb,
                avg_displacement_m,
            )

        # Calculate the drift speed and direction between GPS1 and GPS2
        surface_drift_qc = QC.QC_GOOD
        if GPS12_ok:
            log_debug("gps_drift_time_s = %f" % gps_drift_time_s)

            surface_GPS_mean_lat_dd = (GPS1.lat_dd + GPS2.lat_dd) / 2.0
            surface_mean_lat_factor = math.cos(math.radians(surface_GPS_mean_lat_dd))

            surface_delta_GPS_lat_dd = GPS2.lat_dd - GPS1.lat_dd
            surface_delta_GPS_lon_dd = GPS2.lon_dd - GPS1.lon_dd

            surface_delta_GPS_lat_m = surface_delta_GPS_lat_dd * m_per_deg
            surface_delta_GPS_lon_m = (
                surface_delta_GPS_lon_dd * m_per_deg * surface_mean_lat_factor
            )

            log_debug(
                "surface_delta_GPS_lat_m = %f, surface_delta_GPS_lon_m = %f"
                % (surface_delta_GPS_lat_m, surface_delta_GPS_lon_m)
            )

            surface_current_drift_cm_s = (
                m2cm
                * math.sqrt(
                    surface_delta_GPS_lat_m * surface_delta_GPS_lat_m
                    + surface_delta_GPS_lon_m * surface_delta_GPS_lon_m
                )
                / gps_drift_time_s
            )
            try:
                # compute polar (not compass!) angle of surface current
                # convert to degrees to handle bounds checking below
                surface_current_set_deg = math.degrees(
                    math.atan2(surface_delta_GPS_lat_m, surface_delta_GPS_lon_m)
                )
            except ZeroDivisionError:  #  atan2
                surface_current_set_deg = 0.0

            if surface_current_set_deg < 0:
                surface_current_set_deg = surface_current_set_deg + 360.0

            surface_current_set_rad = math.radians(surface_current_set_deg)

            # given polar (not compass) angle cos() gets the east (U) component; sin() get the north (V) component of drift speed
            surface_curr_east = surface_current_drift_cm_s * np.cos(
                surface_current_set_rad
            )
            surface_curr_north = surface_current_drift_cm_s * np.sin(
                surface_current_set_rad
            )

            log_debug(
                "surface_current_drift_cm_s = %f, polar surface_current_set_deg = %f"
                % (surface_current_drift_cm_s, surface_current_set_deg)
            )
            surface_curr_error = (GPS1.error + GPS2.error) / gps_drift_time_s  # [m/s]
            results_d.update(
                {
                    "surface_curr_east": surface_curr_east,
                    "surface_curr_north": surface_curr_north,
                    "surface_curr_error": surface_curr_error,
                }
            )
            if sfc_drift_interval_i is not None:
                # Before going below the sfc we are in the thrall of any sfc current
                # replace the speeds and direction where for DAC and displacement calculations
                ctd_gsm_horizontal_speed_cm_s_v[sfc_drift_interval_i] = (
                    surface_current_drift_cm_s
                )
                hdm_horizontal_speed_cm_s_v[sfc_drift_interval_i] = (
                    surface_current_drift_cm_s
                )
                head_polar_rad_v[sfc_drift_interval_i] = surface_current_set_rad
                sfc_east_displacement_drift_m_v = (
                    cm2m * surface_curr_east * ctd_delta_time_s_v[sfc_drift_interval_i]
                )
                sfc_north_displacemnt_drift_m_v = (
                    cm2m * surface_curr_north * ctd_delta_time_s_v[sfc_drift_interval_i]
                )
                # HACK this defeats both adding sfc speeds to DAC and prevents DAC from being added to sfc drift!
                ctd_delta_time_s_v[sfc_drift_interval_i] = 0
            del surface_current_set_deg, surface_current_set_rad  # unused below
        else:
            log_warning("Unable to determine surface drift")
            results_d.update(
                {
                    "surface_curr_east": BaseNetCDF.nc_nan,
                    "surface_curr_north": BaseNetCDF.nc_nan,
                }
            )
            surface_drift_qc = QC.QC_BAD
        results_d.update(
            {
                "surface_curr_qc": surface_drift_qc,
            }
        )

        #
        # Calculate vehicle displacement and DAC
        #

        # Compute the vehicle displacement through the water, based on the glide slope and observed w model
        (
            gsm_east_displacement_m_v,
            gsm_north_displacement_m_v,
            gsm_east_displacement_m,
            gsm_north_displacement_m,
            gsm_east_average_speed_m_s,
            gsm_north_average_speed_m_s,
        ) = compute_displacements(
            "gsm",
            ctd_gsm_horizontal_speed_cm_s_v,
            ctd_delta_time_s_v,
            total_flight_and_SM_time_s,
            head_polar_rad_v,
        )
        results_d.update(
            {
                "flight_avg_speed_east_gsm": gsm_east_average_speed_m_s,
                "flight_avg_speed_north_gsm": gsm_north_average_speed_m_s,
                "east_displacement_gsm": gsm_east_displacement_m_v,
                "north_displacement_gsm": gsm_north_displacement_m_v,
            }
        )
        # Compute the vehicle displacement through the water, based on the hydrodynamic model
        (
            hdm_east_displacement_m_v,
            hdm_north_displacement_m_v,
            hdm_east_displacement_m,
            hdm_north_displacement_m,
            hdm_east_average_speed_m_s,
            hdm_north_average_speed_m_s,
        ) = compute_displacements(
            "hdm",
            hdm_horizontal_speed_cm_s_v,
            ctd_delta_time_s_v,
            total_flight_and_SM_time_s,
            head_polar_rad_v,
        )
        results_d.update(
            {
                "flight_avg_speed_east": hdm_east_average_speed_m_s,
                "flight_avg_speed_north": hdm_north_average_speed_m_s,
                "east_displacement": hdm_east_displacement_m_v,
                "north_displacement": hdm_north_displacement_m_v,
            }
        )

        dive_mean_lat_factor = math.cos(math.radians(latitude))

        # Estimate depth-averaged current from the difference between the
        # estimated (model-based) displacement and the actual (GPS-difference) displacement.

        # gbs suggests computing DAC even if hdm fails to converge (assuming GPS2_ok of course)
        # This may make sense now that we have so many other QC checks to get rid of the obvious places
        # where hdm would have failed so now the likely reason is that your abc's are off.
        # Under these assumptions, we move from the conservative don't-bother to the liberal what-the-hell model
        # Check for under-ice or irridium fixes

        compute_DAC = (
            GPS2E_ok and GPS2E_gpsfix and hdm_qc != QC.QC_BAD and DAC_qc != QC.QC_BAD
        )  # conservative
        compute_DAC = GPS2E_ok and GPS2E_gpsfix  # liberal
        if DAC_qc != QC.QC_GOOD:
            # Give them a heads up
            if compute_DAC:
                log_info("Computing %s depth-average current." % QC.qc_name_d[DAC_qc])
            # If we get here we are not computing DAC; how come?
            elif not GPS2E_gpsfix:
                log_info(
                    "RAFOS or Iridium fix: Not computing %s depth-average current."
                    % QC.qc_name_d[DAC_qc]
                )
            elif not GPS2E_ok:
                log_info("Bad GPS2 or GPSE; unable to compute depth-average current.")
            else:  # some other reason...
                log_info(
                    "Not computing %s depth-average current." % QC.qc_name_d[DAC_qc]
                )
        else:
            pass  # all is well with DAC; do it quietly

        if compute_DAC:
            # Calculate the displacements between GPS2 and final GPS positions
            dive_delta_GPS_lat_dd = GPSE.lat_dd - GPS2.lat_dd
            dive_delta_GPS_lon_dd = GPSE.lon_dd - GPS2.lon_dd
            if np.fabs(dive_delta_GPS_lon_dd) > 180.0:
                # We have crossed the international dateline
                dive_delta_GPS_lon_dd = 360.0 - np.fabs(dive_delta_GPS_lon_dd)
                if GPS2.lon_dd < GPSE.lon_dd:
                    # If the start is less then the final, then we crossed western hemisphere to eastern hemisphere,
                    # so the "direction" should be negative
                    dive_delta_GPS_lon_dd = -dive_delta_GPS_lon_dd

            dive_delta_GPS_lat_m = dive_delta_GPS_lat_dd * m_per_deg
            dive_delta_GPS_lon_m = (
                dive_delta_GPS_lon_dd * m_per_deg * dive_mean_lat_factor
            )

            # Save intermediate calculations that went into displacement and DAC calculations
            results_d.update(
                {
                    "delta_time_s": ctd_delta_time_s_v,
                    "polar_heading": head_polar_rad_v,
                    "GPS_north_displacement_m": dive_delta_GPS_lat_m,
                    "GPS_east_displacement_m": dive_delta_GPS_lon_m,
                    "total_flight_time_s": total_flight_and_SM_time_s,
                }
            )

            gsm_dac_east_speed_m_s, gsm_dac_north_speed_m_s = compute_dac(
                gsm_north_displacement_m_v,
                gsm_east_displacement_m_v,
                gsm_north_displacement_m,
                gsm_east_displacement_m,
                dive_delta_GPS_lat_m,
                dive_delta_GPS_lon_m,
                total_flight_and_SM_time_s,
            )
            results_d.update(
                {
                    "depth_avg_curr_east_gsm": gsm_dac_east_speed_m_s,
                    "depth_avg_curr_north_gsm": gsm_dac_north_speed_m_s,
                }
            )

            hdm_dac_east_speed_m_s, hdm_dac_north_speed_m_s = compute_dac(
                hdm_north_displacement_m_v,
                hdm_east_displacement_m_v,
                hdm_north_displacement_m,
                hdm_east_displacement_m,
                dive_delta_GPS_lat_m,
                dive_delta_GPS_lon_m,
                total_flight_and_SM_time_s,
            )

            depth_avg_curr_error = (GPS2.error + GPSE.error) / gps_dive_time_s  # [m/s]
            dac_magnitude = np.sqrt(
                hdm_dac_east_speed_m_s * hdm_dac_east_speed_m_s
                + hdm_dac_north_speed_m_s * hdm_dac_north_speed_m_s
            )
            if dac_magnitude < depth_avg_curr_error:
                log_warning(
                    "Estimated DAC magnitude %.1fcm/s below resolution of %.1fcm/s"
                    % (dac_magnitude * m2cm, depth_avg_curr_error * m2cm)
                )
                DAC_qc = QC.update_qc(QC.QC_PROBABLY_BAD, DAC_qc)
            log_info(
                "DAC east: %.2f cm/s DAC north: %.2f cm/s"
                % (hdm_dac_east_speed_m_s * 100, hdm_dac_north_speed_m_s * 100)
            )
            results_d.update(
                {
                    "depth_avg_curr_east": hdm_dac_east_speed_m_s,
                    "depth_avg_curr_north": hdm_dac_north_speed_m_s,
                    "depth_avg_curr_error": depth_avg_curr_error,
                }
            )

        else:
            # Can't perform DAC computation
            log_debug("Skipping DAC computation.")

            # Write in NaNs to the NC file
            results_d.update(
                {
                    "depth_avg_curr_east_gsm": BaseNetCDF.nc_nan,
                    "depth_avg_curr_north_gsm": BaseNetCDF.nc_nan,
                    "depth_avg_curr_east": BaseNetCDF.nc_nan,
                    "depth_avg_curr_north": BaseNetCDF.nc_nan,
                }
            )

            # Set these for lat/lon calc below but don't write to nc file
            gsm_dac_east_speed_m_s = 0
            gsm_dac_north_speed_m_s = 0
            hdm_dac_east_speed_m_s = 0
            hdm_dac_north_speed_m_s = 0

        results_d.update(
            {
                "depth_avg_curr_qc": DAC_qc,
            }
        )
        # TODO nowhere do we calculate and save the speed that includes DAC
        # or the adjusted displacements (just the lat/lon)

        # We think the lat/longs are good if we have good GPS2 and DAC is plausible
        latlong_qc = QC.QC_GOOD if GPS2.ok else QC.QC_BAD
        latlong_qc = QC.update_qc(DAC_qc, latlong_qc)

        # Above we have eliminated the intial sfc drift from the DAC calculations
        # Update the initial drift displacment values before computing lat/lon (critical only in short dives).
        # We could use the same sfc speed assumption for the final surfacing drift (better than 0?)
        # but (TODO) we could have FMS compute *both* these drift values and cache them, then access them on reprocess.
        # The final drift is already accounted for because it is the GPSE lat/lon.
        if sfc_drift_interval_i is not None:
            # Update the initial displacement only!!
            # This updates the vectors directly so the adjusted values are written as displacements from GPS2 not 0,0
            gsm_east_displacement_m_v[sfc_drift_interval_i] = (
                sfc_east_displacement_drift_m_v
            )
            gsm_north_displacement_m_v[sfc_drift_interval_i] = (
                sfc_north_displacemnt_drift_m_v
            )
            hdm_east_displacement_m_v[sfc_drift_interval_i] = (
                sfc_east_displacement_drift_m_v
            )
            hdm_north_displacement_m_v[sfc_drift_interval_i] = (
                sfc_north_displacemnt_drift_m_v
            )

        gsm_lat_dd_v, gsm_lon_dd_v = compute_lat_lon(
            gsm_dac_east_speed_m_s,
            gsm_dac_north_speed_m_s,
            GPS2.lat_dd,
            GPS2.lon_dd,
            gsm_east_displacement_m_v,
            gsm_north_displacement_m_v,
            ctd_delta_time_s_v,
            dive_mean_lat_factor,
        )
        results_d.update(
            {
                "latitude_gsm": gsm_lat_dd_v,
                "longitude_gsm": gsm_lon_dd_v,
            }
        )

        hdm_lat_dd_v, hdm_lon_dd_v = compute_lat_lon(
            hdm_dac_east_speed_m_s,
            hdm_dac_north_speed_m_s,
            GPS2.lat_dd,
            GPS2.lon_dd,
            hdm_east_displacement_m_v,
            hdm_north_displacement_m_v,
            ctd_delta_time_s_v,
            dive_mean_lat_factor,
        )
        results_d.update(
            {
                "latitude": hdm_lat_dd_v,
                "longitude": hdm_lon_dd_v,
                "latlong_qc": latlong_qc,
            }
        )

        # update in case of excursions out of GPS2E bounding box
        globals_d["geospatial_lat_min"] = min(hdm_lat_dd_v)
        globals_d["geospatial_lat_max"] = max(hdm_lat_dd_v)
        globals_d["geospatial_lon_min"] = min(hdm_lon_dd_v)
        globals_d["geospatial_lon_max"] = max(hdm_lon_dd_v)
        try:
            # for convenience, compute these two fundamental values from the new TEOS-10 standard
            absolute_salinity_v = gsw.SA_from_SP(
                salin_cor_v, ctd_press_v, hdm_lon_dd_v, hdm_lat_dd_v
            )
            conservative_temperature_v = gsw.CT_from_t(
                absolute_salinity_v, temp_cor_v, ctd_press_v
            )
            # regardless of depth achieved since we might add to MMT, etc.
            sigma_theta0_v = gsw.sigma0(absolute_salinity_v, conservative_temperature_v)
            sigma_theta3_v = gsw.sigma3(absolute_salinity_v, conservative_temperature_v)
            sigma_theta4_v = gsw.sigma4(absolute_salinity_v, conservative_temperature_v)
            results_d.update(
                {
                    "conservative_temperature": conservative_temperature_v,
                    "absolute_salinity": absolute_salinity_v,
                    "gsw_sigma0": sigma_theta0_v,
                    "gsw_sigma3": sigma_theta3_v,
                    "gsw_sigma4": sigma_theta4_v,
                }
            )
        except Exception:
            log_warning("Failed to calc TEOS-10 variables", "exc")

        ## Correct other instruments after we know salinity, etc.
        # Call the sensor extensions for sensor specific processing after DAC etc computations
        log_info("Starting sensor extensions data processing")
        Sensors.process_sensor_extensions(
            "sensor_data_processing", locals(), eng_f, calib_consts
        )
        log_info("Finished sensor extensions data processing")

    except RuntimeError as exception:
        if exception.args[0]:  # True argument
            processing_error = 1  # Had an error of some sort
            results_d.update({"processing_error": "processing_error"})
            results_d["processing_error"] = processing_error
            # log_error(exception.args[1], "exc")
        else:
            # log_info(exception.args[1], "exc")
            pass

    # Fall through and write the nc file with whatever data is available
    results_d.update(
        {
            "reviewed": reviewed,
        }
    )
    processing_log = BaseLogger.self.stopStringCapture()
    # processing history contains timestamps
    processing_history = "%sProcessing start:\n%s" % (
        processing_history,
        processing_log,
    )
    TraceArray.trace_results_stop()
    QC.qc_log_stop()

    globals_d["id"] = "%s_%s" % (
        dive_tag,
        time.strftime("%Y%m%d", time.gmtime(eng_file_start_time)),
    )
    platform_id = globals_d["platform_id"] = "SG%03d" % int(calib_consts["id_str"])
    platform_type = "Seaglider"
    if calib_consts["sg_configuration"] == 2:
        platform_type = "Deepglider"
    vessel_description = "%s %s" % (platform_type, platform_id)
    # value looks like 'Seaglider SG005'
    globals_d["source"] = vessel_description
    platform_var = "glider"  # NODC requirement: name of a variable with attributes describing the glider
    globals_d["platform"] = platform_var  # NODC requirement: declare the variable

    globals_d["summary"] = "%s %s" % (
        platform_id,
        mission_title,
    )  # Short version for plots
    # DEAD globals_d['title'] = globals_d['summary'] # recomputed below
    globals_d["project"] = calib_consts["mission_title"]
    globals_d["history"] = processing_history
    if reviewed:
        # update the issued date
        globals_d["date_issued"] = BaseNetCDF.nc_ISO8601_date(time.time())

    globals_d["dive_number"] = int(dive_num)  # AKA eng_f.dive
    globals_d["glider"] = eng_f.glider
    globals_d["mission"] = eng_f.mission
    globals_d["seaglider_software_version"] = log_f.version
    globals_d["file_version"] = Globals.mission_profile_nc_fileversion
    # Tried just writing the epoch time in secs but the normal precision for global floats was insufficient
    globals_d["start_time"] = np.float64(eng_file_start_time)  # epoch time
    if "geospatial_lat_min" in globals_d:
        globals_d["geospatial_lat_units"] = "degrees"  # degrees_north
        globals_d["geospatial_lat_resolution"] = "seconds"  # better than this...
        globals_d["geospatial_lon_units"] = "degrees"  # degrees_east
        globals_d["geospatial_lon_resolution"] = "seconds"  # better than this...

    #
    # Output Results
    #

    # NetCDF dive file creation

    if nc_dive_file_name:  # BREAK
        # Create the dive file
        try:
            nc_dive_file = Utils.open_netcdf_file(nc_dive_file_name, "w")
        except Exception:
            log_error("Unable to open %s for writing" % nc_dive_file_name, "exc")
            return (1, None)

        # Create *all* dimensions based on nc_info_d
        # Add the trajectory dimension for CF compliance
        BaseNetCDF.assign_dim_info_dim_name(
            nc_info_d, BaseNetCDF.nc_trajectory_info, BaseNetCDF.nc_dim_trajectory_info
        )
        BaseNetCDF.assign_dim_info_size(nc_info_d, BaseNetCDF.nc_trajectory_info, 1)

        created_dims = []
        for _, nc_dim_name in list(BaseNetCDF.nc_mdp_data_info.items()):
            if (
                nc_dim_name
                and nc_dim_name in nc_info_d
                and nc_dim_name not in created_dims
            ):  # any registered?  normally only data infos are but see ctd_results_info
                log_debug(
                    "Creating dimension %s (%s)" % (nc_dim_name, nc_info_d[nc_dim_name])
                )
                nc_dive_file.createDimension(nc_dim_name, nc_info_d[nc_dim_name])
                created_dims.append(nc_dim_name)  # Do this once

        # if False:
        #     # attempt to dump a byte array as an alternative for QC vectors
        #     # this writes an nc file but ncdump does not read it (invalid argument)
        #     # and python dies with
        #     # 19:06:48 30 Nov 2012 UTC: ERROR: MakeDiveProfiles.py(1330): Unable to open /Users/jsb/Seaglider/TestData/sg189_SPURS_Sep12/p1890036.nc
        #     # 19:06:48 30 Nov 2012 UTC: CRITICAL: Exception when reading data files: <type 'exceptions.UnboundLocalError'>:
        #     # when writing the file, there are no complaints and nc_var looks good and values are correct.
        #     bdt = dtype("b")
        #     qc_values = np.array([0, 1, 3, 4, 5, 6, 7, 8, 9], dtype=bdt)
        #     nc_data_type = "b"  # byte
        #     nc_dive_file.createDimension("qc_test_dim", len(qc_values))
        #     nc_var = nc_dive_file.createVariable(
        #         "qc_test_var", nc_data_type, ("qc_test_dim",)
        #     )
        #     nc_var[:] = qc_values

        nodc_globals_d = {}
        BaseNetCDF.update_globals_from_nodc(base_opts, nodc_globals_d)

        #
        # Add the explicit sg_calib_constants
        #
        for key, value in list(explicit_calib_consts.items()):
            BaseNetCDF.create_nc_var(
                nc_dive_file,
                BaseNetCDF.nc_sg_cal_prefix + key,
                BaseNetCDF.nc_scalar,
                False,
                value,
            )

        #
        # Add the log file
        #

        # Header
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "version",
            BaseNetCDF.nc_scalar,
            False,
            log_f.version,
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "glider",
            BaseNetCDF.nc_scalar,
            False,
            log_f.glider,
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "mission",
            BaseNetCDF.nc_scalar,
            False,
            log_f.mission,
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "dive",
            BaseNetCDF.nc_scalar,
            False,
            log_f.dive,
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "start",
            BaseNetCDF.nc_scalar,
            False,
            time.mktime(log_f.start_ts),
        )

        # Data
        for key, value in list(log_f.data.items()):
            log_debug("Processing %s (%s)" % (key, value))
            # Check for repeated log file tags and handle separately
            if key in ("$GPS", "$GPS1", "$GPS2"):
                # Handled in GPS section below
                continue
            elif key == "$GCHEAD":
                # All these fields have been converted to gc_XXX arrays...no need to save
                continue
            nc_var_name = BaseNetCDF.nc_sg_log_prefix + key.lstrip("$")
            BaseNetCDF.create_nc_var(
                nc_dive_file, nc_var_name, BaseNetCDF.nc_scalar, False, value
            )  # dump the value

        # Handle GC arrays
        # Create the GC dimension
        for gc_var, gc_values in list(log_f.gc_data.items()):
            BaseNetCDF.create_nc_var(
                nc_dive_file,
                BaseNetCDF.nc_gc_prefix + gc_var,
                (BaseNetCDF.nc_dim_gc_event,),
                False,
                gc_values,
            )
        # Create GC state, if any
        if len(log_f.gc_state_data["secs"]) > 0:
            for gc_state_var, gc_state_values in list(log_f.gc_state_data.items()):
                BaseNetCDF.create_nc_var(
                    nc_dive_file,
                    BaseNetCDF.nc_gc_state_prefix + gc_state_var,
                    (BaseNetCDF.nc_dim_gc_state,),
                    False,
                    gc_state_values,
                )
        # Create GC message variables
        if log_f.gc_msg_dict:
            for msgtype, data_dict in log_f.gc_msg_dict.items():
                nc_dim_msg_state = BaseNetCDF.nc_gc_msg_prefix + msgtype
                for data_name, data in data_dict.items():
                    nc_msg_name = (
                        BaseNetCDF.nc_gc_msg_prefix + msgtype + "_" + data_name
                    )
                    log_debug(f"Creating {nc_msg_name}")
                    BaseNetCDF.create_nc_var(
                        nc_dive_file,
                        nc_msg_name,
                        (nc_dim_msg_state,),
                        False,
                        data,
                    )
        # Turn controller table
        for tc_var, tc_values in list(log_f.tc_data.items()):
            BaseNetCDF.create_nc_var(
                nc_dive_file,
                BaseNetCDF.nc_tc_prefix + tc_var,
                (BaseNetCDF.nc_dim_tc_event,),
                False,
                tc_values,
            )

        # Table data
        for param_name, col_values in log_f.tables.items():
            cols = list(col_values.keys())
            for col in cols:
                BaseNetCDF.create_nc_var(
                    nc_dive_file,
                    f"{BaseNetCDF.nc_sg_log_prefix}{param_name[1:]}__{col}",
                    (f"{BaseNetCDF.nc_sg_log_prefix}{param_name[1:]}",),
                    False,
                    log_f.tables[param_name][col],
                )

        # First record the actual GPS lines for future processing
        for gps_string in ["$GPS1", "$GPS2", "$GPS"]:
            gps = log_f.data[gps_string]
            BaseNetCDF.create_nc_var(
                nc_dive_file,
                BaseNetCDF.nc_sg_log_prefix + gps_string.lstrip("$"),
                BaseNetCDF.nc_scalar,
                False,
                gps.raw_line,
            )

        # GPS - second record the fixes in a table
        # NOTE: Strings are saved separately
        gps_time = []
        gps_lat = []
        gps_lon = []
        gps_first_fix_time = []
        gps_final_fix_time = []
        gps_hdop = []
        gps_magvar = []
        gps_driftspeed = []
        gps_driftheading = []
        gps_n_satellites = []
        gps_hpe = []

        for gps_name in ["$GPS1", "$GPS2", "$GPS"]:
            gps_fix = log_f.data[gps_name]
            gps_time.append(time.mktime(gps_fix.datetime))
            gps_lat.append(Utils.ddmm2dd(gps_fix.lat))
            gps_lon.append(Utils.ddmm2dd(gps_fix.lon))
            gps_first_fix_time.append(gps_fix.first_fix_time)
            gps_final_fix_time.append(gps_fix.final_fix_time)
            gps_hdop.append(gps_fix.hdop)
            gps_magvar.append(gps_fix.magvar)
            gps_driftspeed.append(gps_fix.drift_speed)
            gps_driftheading.append(gps_fix.drift_heading)
            gps_n_satellites.append(gps_fix.n_satellites)
            gps_hpe.append(gps_fix.HPE)

        log_gps_qc_v = np.array((GPS1.ok, GPS2.ok, GPSE.ok), int)

        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_time",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_time, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_lat",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_lat, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_lon",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_lon, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_first_fix_time",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_first_fix_time, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_final_fix_time",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_final_fix_time, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_hdop",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_hdop, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_magvar",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_magvar, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_driftspeed",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_driftspeed, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_driftheading",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_driftheading, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_n_satellites",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_n_satellites, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_hpe",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            np.array(gps_hpe, np.float64),
        )
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            BaseNetCDF.nc_sg_log_prefix + "gps_qc",
            (BaseNetCDF.nc_dim_gps_info,),
            False,
            log_gps_qc_v,
        )

        #
        # Add engineering data (dimensioned)
        #

        # Add in the Eng file contents (always sg_dat_point long)
        for column in eng_f.columns:
            if eng_f.removed_col(column):
                continue  # skip this dropped column
            column_v = eng_f.get_col(column)
            # Move all eng data onto results_d so we process them uniformly
            # this permits eng file data to have different dim_infos (e.g., magnetometer)
            nc_var_name = BaseNetCDF.nc_sg_eng_prefix + column
            results_d[nc_var_name] = np.array(column_v, np.float64)
            # Some data vectors in the eng file explicitly list their instruments
            # find any in use for this file and add to instruments_d
            # We add platform attr below....
            try:
                md = BaseNetCDF.nc_var_metadata[nc_var_name]
                _, _, meta_data_d, mdp_dim_info = md
                # We know eng file data is a single dimension vector
                if (
                    mdp_dim_info and mdp_dim_info[0] == BaseNetCDF.nc_sg_data_info
                ):  # a vector?
                    try:
                        instrument_var = meta_data_d[
                            "instrument"
                        ]  # explicitly declared instrument?
                        instruments_d[nc_var_name] = instrument_var
                    except KeyError:
                        pass  # no problem
            except KeyError:
                pass  # complain below

        # Add dervived (results) variables
        for nc_var, value in list(results_d.items()):
            try:
                md = BaseNetCDF.nc_var_metadata[nc_var]
                _, _, meta_data_d, mdp_dim_info = md
                dim_names = BaseNetCDF.nc_scalar  # assume scalar
                instrument_info = {}
                if mdp_dim_info:
                    for mdi in mdp_dim_info:
                        dim_name = nc_info_d[mdi]
                        dim_names = dim_names + (dim_name,)
                        # always add the platform here
                        instrument_info.update({"platform": platform_var})
                        if mdi in BaseNetCDF.nc_mdp_instrument_vars:
                            instrument_var = BaseNetCDF.nc_mdp_instrument_vars[mdi]
                            instruments_d[nc_var] = instrument_var
                            instrument_info.update(
                                {"instrument": instrument_var}
                            )  # implicitly declared instrument
                log_debug(
                    "result_d: %s%s (%s)"
                    % (nc_var, dim_names, np.shape(value) if dim_names else value)
                )
                # nc_dive_file.sync()
                BaseNetCDF.create_nc_var(
                    nc_dive_file, nc_var, dim_names, False, value, instrument_info
                )
            except KeyError:
                DEBUG_PDB_F()
                log_error("Unknown result variable %s -- dropped" % nc_var)

        # add the trajectory variable (array of length 1)
        # avoid adding platform or instruments
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            "trajectory",
            (BaseNetCDF.nc_dim_trajectory_info,),
            False,
            [int(dive_num)],
        )

        # add the platform variable
        platform_d = {"call_sign": platform_id, "long_name": platform_type.lower()}
        try:
            # WMO lore via Fritz and Dana 1/2015:
            # There are a block of WHO codes available for gliders.  See http://www.wmo.int/pages/prog/amp/mmop/wmo-number-rules.html
            # However, according to Dana you need a new one for *every deployment*, not every glider.
            # For example, when a float is recovered and then redeployed they need to assign a new WHO number
            # They request 1000 numbers in a block and then dole them out as floats are deployed.
            # Each float fab center does their own and contacts their local WMO representative for more.
            # So we can't just ask for 1K and then assign a WHO number to each glider and be done with it....
            # WMO numbers are typically assigned by operating region and tagged in the leading digit about that location.
            # Doesn't always make sense for a glider but ask for a number where the leading digit encodes where initially deployed.
            # In any case, we allow an intrepid pilot to get a WMO number if they want and then they can put it in sg_calib_constants.m as a string, e.g.,
            # wmo_id = '98334557';
            # This is recorded in the attributes of the platform per spec, along with call_sign, etc.
            # Mechanism available to those who want to, for example, put nc data up on GTS, which requires WMO numbers.
            wmo_id = calib_consts["wmo_id"]
            platform_d["wmo_id"] = wmo_id
            globals_d["wmo_id"] = wmo_id  # Also add to globals
        except KeyError:
            pass
        BaseNetCDF.create_nc_var(
            nc_dive_file,
            platform_var,
            BaseNetCDF.nc_scalar,
            False,
            vessel_description,
            platform_d,
        )

        # add all the instrument variables used by any data variables and declare them in the instrument globals
        instrument_vars = Utils.unique(list(instruments_d.values()))
        for instrument_var in instrument_vars:
            BaseNetCDF.create_nc_var(
                nc_dive_file,
                instrument_var,
                BaseNetCDF.nc_scalar,
                False,
                instrument_var,
            )
        # NOTE: used to add platform_var here but NODC does not want the glider as an instrument
        # Why not just the results of string.join()?  Because if instrument_vars is empty (scicon, etc.)
        # then so is that string and empty strings (always?) give netcdf.py gas when writing values
        globals_d["instrument"] = "%s " % " ".join(instrument_vars)

        # print(instrument_vars)
        # instruments = ''
        # for v in instrument_vars:
        #     if v is not None and v:
        #         instruments += "%s " % v
        # globals_d['instrument'] = "%s " % instruments

        # Form NODC compliant title from various bits and bobs
        globals_d["title"] = BaseNetCDF.form_NODC_title(
            instrument_vars, nodc_globals_d, globals_d, mission_title
        )

        #
        # Write the netCDF global attributes (header)
        #
        BaseNetCDF.write_nc_globals(nc_dive_file, globals_d, base_opts)
        nc_dive_file.sync()  # force write to file
        nc_dive_file.close()  # close file

        BaseDotFiles.process_extensions(
            ("postnetcdf",),
            base_opts,
            sg_calib_file_name=sg_calib_file_name,
            nc_files_created=[nc_dive_file_name],
        )

        # Generate parquet files

        nc_dive_file_name_gz = "%s.gz" % nc_dive_file_name
        if base_opts.gzip_netcdf:
            log_info("Compressing %s to %s" % (nc_dive_file_name, nc_dive_file_name_gz))
            if BaseGZip.compress(nc_dive_file_name, nc_dive_file_name_gz):
                log_warning("Failed to compress %s" % nc_dive_file_name)
        else:
            if os.path.exists(nc_dive_file_name_gz):
                try:
                    os.remove(nc_dive_file_name_gz)
                except Exception:
                    log_error("Couldn't remove %s" % nc_dive_file_name_gz)

    return (processing_error, nc_dive_file_name)


def collect_nc_perdive_files(base_opts):
    """Builds a list of all per-dive netCDF files in the mission dir
    If there are two files for the same dive (one gzipped, one not), then the file
    with the newer timestamp is selected

    Returns: list of fully qualified files
    """
    dive_nc_file_names = []

    glob_expr = "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc"
    for match in glob.glob(os.path.join(base_opts.mission_dir, glob_expr)):
        dive_nc_file_names.append(match)
        log_debug("Found dive nc file %s" % match)

    dive_nc_file_names.sort()
    return dive_nc_file_names


def main():
    """Command line driver for creating per-dive netCDF files

    Returns:
        0 - success
        1 - failure

    Raises:
        Any exceptions raised are considered critical errors and not expected

    """
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for creating per-dive netCDF files",
        additional_arguments={
            "basename": BaseOptsType.options_t(
                None,
                ("MakeDiveProfiles",),
                ("basename",),
                str,
                {
                    "help": "Basename for netcdf file to process/create (pXXXYYYY where XXX is sd_id, YYYY is dive number) Use this or --mission-dir",
                    "action": BaseOpts.FullPathAction,
                    "nargs": "?",
                },
            ),
        },
    )

    BaseLogger(base_opts)  # initializes BaseLog

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    Utils.check_versions()

    # Reset priority
    if base_opts.nice:
        try:
            os.nice(base_opts.nice)
        except Exception:
            log_error("Setting nice to %d failed" % base_opts.nice)

    ret_val = 0

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if base_opts.mission_dir:
        base_path = base_opts.mission_dir
    elif base_opts.basename:
        # they gave us a basename, e.g., p5400003 so expand it assuming current (code?) directory
        # make it look like it came via --mission_dir
        base_path = base_opts.basename + "/"  # ensure trailing '/'
        base_opts.mission_dir = base_path
    else:
        log_error("Neither mission_dir or basename provided")
        return 1

    dive_list = []
    if os.path.isdir(base_path):
        log_info("Making profiles for all dives in %s" % base_path)
        # Include only valid dive files
        glob_expr = (
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].log",
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].eng",
            "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc",
            # "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].nc.gz"
        )
        for g in glob_expr:
            for match in glob.glob(os.path.join(base_path, g)):
                log_debug("Found dive file %s" % match)
                # match = match.replace('.nc.gz', '.nc')
                head, _ = os.path.splitext(os.path.abspath(match))
                dive_list.append(head)
        dive_list = sorted(Utils.unique(dive_list))
    else:
        # We were probably given <mission_dir>/pXXXDDDD to work on one dive
        # Set mission_dir properly. No need to expanduser here--already done by BaseOpts
        # Since there was a trailing / tacked onto the mission_dir, the split must remove that
        if base_path[-1] == "/":
            base_path = base_path[:-1]
        mission_dir, base_name = os.path.split(base_path)
        if not os.path.isdir(mission_dir):
            log_error("Directory %s does not exist -- exiting" % mission_dir)
            return 1
        base_opts.mission_dir = mission_dir + "/"  # ensure trailing '/'
        # rebuild path
        base_path = os.path.join(base_opts.mission_dir, base_name)
        log_info("Making profile for: %s" % base_path)
        dive_list.append(base_path)

    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
    calib_consts = CalibConst.getSGCalibrationConstants(
        sg_calib_file_name, ignore_fm_tags=not base_opts.ignore_flight_model
    )
    if not calib_consts:
        log_warning("Could not process %s" % sg_calib_file_name)
        return 1

    try:
        instrument_id = int(calib_consts["id_str"])
    except Exception:
        # base_opts always supplies a default (0)
        instrument_id = int(base_opts.instrument_id)
    if instrument_id == 0:
        log_warning("Unable to determine instrument id; assuming 0")

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if init_ret_val > 0:
        log_warning("Sensor initialization failed")

    # Initialize the FileMgr with data on the installed loggers
    FileMgr.logger_init(init_dict)

    # Any initialization from the extensions
    BaseDotFiles.process_extensions(("init_extension",), base_opts, init_dict=init_dict)

    # Initialze the netCDF tables
    BaseNetCDF.init_tables(init_dict)

    # Find any associated logger eng files for each dive in dive_list
    logger_eng_files = FileMgr.find_dive_logger_eng_files(
        dive_list, base_opts, instrument_id, init_dict
    )

    dives_processed = []
    dives_not_processed = []
    # Now, create the profiles
    for dive_path in dive_list:
        log_debug("Processing %s" % dive_path)
        head, _ = os.path.splitext(os.path.abspath(dive_path))
        if base_opts.target_dir:
            _, base = os.path.split(os.path.abspath(dive_path))
            outhead = os.path.join(base_opts.target_dir, base)
        else:
            outhead = head

        log_info("Head = %s" % head)

        eng_file_name = head + ".eng"
        log_file_name = head + ".log"

        base_opts.make_dive_profiles = True

        if base_opts.make_dive_profiles:
            nc_dive_file_name = outhead + ".nc"
        else:
            nc_dive_file_name = None

        sg_calib_file_name, _ = os.path.split(os.path.abspath(dive_path))
        sg_calib_file_name = os.path.join(sg_calib_file_name, "sg_calib_constants.m")
        dive_num = FileMgr.get_dive(eng_file_name)

        log_info("Dive number = %d" % dive_num)

        log_debug("logger_eng_files = %s" % logger_eng_files[dive_path])

        try:
            (temp_ret_val, _) = make_dive_profile(
                base_opts.force,
                dive_num,
                eng_file_name,
                log_file_name,
                sg_calib_file_name,
                base_opts,
                nc_dive_file_name,
                logger_eng_files=logger_eng_files[dive_path],
            )
        except KeyboardInterrupt:
            log_info("Interrupted by user - bailing out")
            ret_val = 1
            break
        except Exception:
            if DEBUG_PDB:
                _, _, tb = sys.exc_info()
                traceback.print_exc()
                pdb.post_mortem(tb)

            log_error("Error processing dive %d - skipping" % dive_num, "exc")
            temp_ret_val = True

        TraceArray.trace_results_stop()  # Just in case we bailed out...no harm if closed
        QC.qc_log_stop()
        if temp_ret_val == 1:
            ret_val = 1
            log_warning("Problems writing auxillary files")
            dives_not_processed.append(dive_num)
        elif temp_ret_val == 2:
            log_info("Skipped processing dive %d" % dive_num)
        else:
            dives_processed.append(dive_num)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info("Dives processed = %s" % dives_processed)
    log_info("Dives failed to process = %s" % dives_not_processed)
    return ret_val


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
