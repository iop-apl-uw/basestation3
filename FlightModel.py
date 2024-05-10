#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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

# pylint: disable=fixme
# TODO - remove fix/reduce use of global when not needed
# pylint: disable=global-variable-not-assigned
# pylint: disable=missing-function-docstring


""" An attempt to turn 'experimental' regress_vbd.m into a Maytag washer, an automatic reliable appliance"""

import cProfile
import pstats
import sys
import os
import shutil
import time
import copy  # must be after numpy (and flight_data) import, since numpy has its own 'copy'
import stat
import pdb
import traceback
import pickle

import numpy as np
import seawater
import scipy.io as sio  # for savemat
import scipy.optimize  # fminbound

import BaseOpts
import MakeDiveProfiles  # for collect_nc_perdive_files() compressee_density(), compute_displacements(), compute_dac() etc
import Utils
import Globals  # versions, esp basestation_version
import QC
from CalibConst import getSGCalibrationConstants
from HydroModel import hydro_model
from Globals import flight_variables
from BaseLog import (
    BaseLogger,
    log_info,
    log_error,
    log_debug,
    log_warning,
    log_critical,
)

# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

# If you change
# - the format of the flight_data class (which see),
# - the structure of the flight_dive_data_d,
# - the assumption_variables,
# - the size or values of the ab search grids or what is stored in ab_grid_cache
# change this number so we rebuild everything
fm_version = 1.11

# Glider types
SEAGLIDER = 0
DEEPGLIDER = 1
OCULUS = 2
SGX_MASS = 60  # kg that distinguishes an SGX from a smaller, original SG

# These variables are assumed constant for glider type and deployment
# If any of them change, we need to recompute vbdbias and a/b
header_variables = [
    "fm_version",
    "glider",
    "glider_type",
    "glider_type_string",
    "has_gpctd",
    "compare_velo",
    "deck_dives",
    "last_updated",
    "mission_title",
    "history",
    "hd_s_scale",
]
# All computations are based on the stated mass and mass_comp and stall assumptions
assumption_variables = [
    "mass",
    "mass_comp",  # from ballasting and expected apogee etc.
    "max_stall_speed",
    "min_stall_speed",
    "min_stall_angle",  # for hydro_model
]
# variables needed for w_rms_func()


# see load_dive_data() these are the vectors we collect for each dive to compute various flight model parameters
# deliberately NOT vol_comp, vol_comp_ref, and therm_expan_term, which are computed and cached
# if compare_velo is non-zero we add 'velo_speed' to this list below
dive_data_vector_names = [
    "w",
    "pressure",
    "temperature",
    "density_insitu",
    "density",
    "displaced_volume",
    "pitch",
]

# CONTROL PARAMETERS

# Moved to option enable_reprocessing_dives = (
#    True  # CONTROL Normally True but if False we don't spend time updating the dives
# )
old_basestation = False  # assume the best
force_alerts = False  # CONTROL test alert code for each 'new' dive
# What should be tested, if velo is available, IN ADDITION to w vs. w_stdy (hdm_speed*sin(glide_angle))
compare_velo = 3  # CONTROL 0 - ignore, even if present (default); 1 - use it and test velo vs. hdm_speed; 2 - use it and test w vs. velo*sin(glide_angle) 3 - method 1 and 2 combined
acceptable_w_rms = 5  # PARAMETER w_rms (cm/s) must be less than this to accept solution
grid_dive_sets = []  # special sets of dives to solve a/b grids (for debugging and other analysis; see rva_solve_ab.m)
# Analysis of velocometer data suggests that the w-only solutions under-estimate hd_b by 20%
# This parameter can be used to scale the solved predicted_hd_b just before it is delivered to MDP
# We do it this way for several reasons:
# 1. We want a self-consistent set of solutions of the flight parameters under the data we measured (FM ignores whatever is in the nc file)
# 2. It is not clear how scale *during* the operation and shift the w_rms contours in ab grids etc.
# 3. The grid itself might not fall on the scaling factor so we would have to do 2D interpolation of some sort
# TODO: eventually we will make this glider type dependent and compare_velo dependent (should always be 1.0)
predicted_hd_a_scale = 1.0  # No change
predicted_hd_b_scale = 1.0  # No change (1.2 increases hd_b by 20%)

generate_figures = True  # CONTROL requires matplot etc.
# add 2nd axis on vbdbias plot for current implied C_VBD wrt to show_implied_c_vbd
show_implied_c_vbd = 0  # PARAMETER what the pilot declared is a good C_VBD at the start of the deployment
fig_markersize = 7  # PARAMETER size of the markers in the eng plots
show_previous_ab_solution = (
    True  # CONTROL show previous 0.2 cm/s and minimum ab solution contour if available
)
copy_figures_to_plots = (
    True  # CONTROL add our figures to the plots subdir so IOP can see them
)
generate_dac_figures = (
    False  # CONTROL show impact of different a/b values on DAC for a dive (expensive)
)

checkpoint_flight_dive_data = False  # CONTROL incrementally checkpoint the flight db (and mat file) per processed dive
dump_checkpoint_data_matfiles = (
    False  # CONTROL dump matlab readable checkpoint files for debugging
)
dump_fm_files = True  # CONTROL dump individual .m files?

flush_ab_grid_cache_entries = []  # DEBUG which dives to flush and force recomputation?
# flush_ab_grid_cache_entries = [47]

# PARAMTERS that control the operation of FlightModel calculations:

# A note on volmax/vbdbias and our initial estimates MakeDiveProfiles() uses
# volmax with an associated vbdbias to compute buoyancy forcing We take over
# this system by ignoring the user's volmax guess (and rho0) and compute our own
# based on the given mass and a *fixed* plausible oceananic density
# (1027.5kg/m^3).  All the parameters will scale to this so the choice of density
# is largely irrelevant.  Based on that initial guess we compute a per-dive
# vbdbias required to redice the w_rms signal.  Over the first
# early_volmax_adjust dives we adjust our volmax estimate such that the mean
# vbdbias for those dives is near zero.

# NOTE: This is for convenience only; the buoyancy forcing does not change.
# Once set we can then look at large relative changes in recent vbdbias values
# to report biofouling however we expect some variation because of
# temperature-related volume changes not covered by the hull and thermal
# expansion terms, notably the temperature oil volume change.  In any case,
# before we update volmax to its final value the computed buoyancies and a/b are
# accurate at all times.

# The more dives we specify the more dives need reprocessing in a batch after we do the final adjustment
# reduce them but if C_VBD hasn't been adjusted we might not be close
# At the minimum we could wait 0 dives since vbdbias is adjusted wrt to whatever value we set
# however we should skip the first actual dive since bubbles and like need to be eliminated
# Thus the minimum adjustment is 1 (so we if we start at 1 we'll adjust using dive 2)

# NOTE: if you expect to set/override these parameters in a cnf file they must be all lower-case!!
early_volmax_adjust = 10  # PARAMETER number of dives: adjust volmax and re-tare vbdbias values over the 'first' N dives (was 10)
FM_default_rho0 = 1027.5  # assume constant for all missions; the scales velocity in hydro_model().  Matches MDP

sg_hd_s = (
    -0.25
)  # CONSTANT how drag scales by shape for the Seaglider shape (Hubbard, 1990)
hd_s_assumed_q = 40  # PARAMETER typical mean speed of a glider along track (cm/s) (between 10 and 150cmn/s)
vbdbias_search_range = 1000  # PARAMETER +/- cc range around (initial) volmax estimate to search for vbdbias
max_w_rms_vbdbias = 10  # if min w_rms for the vbdbias search is greater than this, the dive is ratty (pressure sensor noise) and we shouldn't trust it
vbdbias_tolerance = 20  # PARAMETER cc of vbdbias change between nc and new value that triggers reprocessing
vbdbias_filter = 15  # PARAMETER how many dives to filter median vbdbias

# abs_compress is complicated
# we want to be able to search for it (like vbdbias) on a per-dive basis (see solve_vbdbias_abs_compress)
# however, given the current structure of w_rms_func, when we are doing the grid search we can only apply one abs_compress
# (because we can't apply and cache the final vol?) and we pre-apply vbdbias to displaced_volume
abs_compress_tolerance = 0.05  # PARAMETER fraction difference of abs_compress between nc and new value that triggers reprocessing (5%)
ac_min_start = 1e-6  # most squishy
ac_max_start = 8e-6  # most stiff

# PARAMETERS used to filter which dives are used in grid regressions
# Maintain a ring buffer of different sizes depending on how many dives have been processed so far
# Thus we compute early and often during the early part of the mission but lengthen as the mission progresses
# Constraints: The grid_spacing values must always increase with later dives
grid_spacing_d = {1: 4, 16: 8, 40: 16}  # mapping of dive -> grid_spacing size
# more frequent earlier or for short deployments: grid_spacing_d = {1: 4, 32: 8, 40: 16} # mapping of dive -> grid_spacing size
# DEBUG grid_spacing_d = {1: 15} # disable expanding grid_spacing and use fixed stride
grid_spacing_keys = None

# we decide to commit to a new a/b over a previous a/b if the *prior* RMS at the *new* a/b point exceeds this tolerance
# otherwise the new a/b value was acceptable according to the prior calculation so don't change a/b
force_ab_report = (
    False  # CONTROL control chattiness to help determine ab_tolerance threshold
)
ab_tolerance = 0.2  # PARAMETER RMS change (cm/s) that indicates hd_a/hd_b should change
biofouling_scale = (
    1.5  # what factor of the default hd_b is required to warn of biofouling?
)

# PARAMETERS for validation
w_rms_func_bad = np.nan  # 'normal'
w_rms_func_bad = 1000  # tried inf but that failed
# PARAMETERS used to filter which data are used in regressions
# for shallow 200m dives this is about 20 pts during the dive and climb
data_density_max_depth = 9  # PARAMETER final 'good' points should not be separated by more that N meters (higher is more permissive)
decimation = 0
# DEAD debugging code for data_density_max_depth
# raw temp and salinity will have NaN for timeout and unsampled points
# if we want to eliminate flare, apo, spike and anomoly points, etc, then we need to use corrected salinity qc (but NOT the salinity values)
ignore_salinity_qc = (
    False  # DEAD? PARAMETER whether to ignore salinity qc results in nc file
)

required_fraction_good = 0.5  # PARAMETER how many of the dive's good points remain after eliminating extreme pumps, rolls and pitches?
non_stalled_percent = 0.8  # PARAMETER after fitting with given parameters, what fraction of the good points predict good (non-stalled) velocities

# if 0, use all original valid points else limit the points to just the 'still water' with acceleration <dw/dt>)n_dives_grid_spacing less than value cm/s2
limit_to_still_water = 0.01  # PARAMETER cm/s2 nominally 0.01 but higher if there is pressure sensor noise (TERIFIC) test mean(mdwdt) > limit_to_still_water
max_speed = 200  # cm/s (deal with pressure sensor spikes?)
# Avoid acceleration because of pumping and bleeding and big rolls
vbddiffmax = 0.5  # PARAMETRER cc/s
# We seem to be able to fit steep,low power dives experienced at target turns.  See PAPA Jun09
# Values for deciding if we are excessively rolled or pitched, which might violate steady flight assumptions
# include rolls between rollmin and rollmax
rollmin = 0  # PARAMETER degrees
# if greater than this, we are rolled (port or stbd) too much
rollmax = 90  # PARAMETER degrees
# include pitches between pitchmin and pitchmax
pitchmin = 0  # PARAMETER degrees
# if greater than this, we are pitched (up or down) too much (typically flare)
pitchmax = 60  # PARAMETER degrees
# include points that are between and including the min an max values below
# Avoid shallow points (for flare, surface) or below thermocline if you are trying to eliminate thermal compression effects
pressmin = 10  # PARAMETER minimum pressure for which records are considered (avoid flare and surface maneuvers)
pressmax = 6000  # PARAMETER maximum pressure for which records are considered

max_pitch_d = 50  # PARAMETER (was 25) avoid using extremely steep dives to estimate a/b as we are not 'flying' in the typical flight regime
min_pitch_diff = 7  # combined dives need at least 7 degrees of pitches


def trusted_drag(pitch_diff):
    global compare_velo, min_pitch_diff
    return compare_velo or pitch_diff > min_pitch_diff


angles = None  # Eventually a set of bins for each angle

# Various constants
cm_per_m = 100.0
m_per_cm = 1 / cm_per_m
g_per_kg = 1000.0
kg_per_g = 1 / g_per_kg

# various globals
flight_directory = None
plots_directory = None
flight_dive_data_filename = None
# eventually a dict: dive -> <flight_data>, 'mass', etc. assumptions
flight_dive_data_d = None

mission_directory = None
# set once in main()
nc_path_format = None
compress_cnf = None
# an updated copy of prevailing flight constants from flight_dive_data_d, etc. required by hydro_model()
flight_consts_d = {}

HIST = []  # w_rms_func() calculation history for debugging

# global pointers to entries in flight_dive_data_d structures we use
glider_type = None
flight_dive_nums = None
hd_a_grid = None
hd_b_grid = None
ab_grid_cache_d = None
restart_cache_d = None

if generate_figures:
    import matplotlib

    matplotlib.interactive(False)
    matplotlib.use("agg")
    # matplotlib.use('svg')
    matplotlib.rc("xtick", labelsize=9)
    matplotlib.rc("ytick", labelsize=9)
    matplotlib.rc("axes", labelsize="x-small")
    # matplotlib.rc('axes', grid=True)
    matplotlib.rc("figure", dpi=100)
    # matplotlib.rc('figure',  figsize=[11.0,9.0]) #Per the IOP site standard
    matplotlib.rc("figure", figsize=[10.58, 8.94])  # Per the IOP site standard
    matplotlib.rcParams["mathtext.default"] = "regular"

    # from pylab import *
    from matplotlib.font_manager import FontProperties
    import matplotlib.pyplot as plt


class flight_data:  # deliberately no (object) so we can pickle these puppies
    """Per-dive flight related data"""

    def __init__(self, dive_num):
        self.dive_num = dive_num
        self.last_updated = (
            0  # seconds since Jan 1, 1970 when nc file was created/updated
        )
        self.start_time = 0  # seconds since Jan 1, 1970 when dive started
        self.pitch_d = (
            0  # the absolute value of the integer pitch desired for this dive
        )
        # assumed min and max pitch attained for 'most' of the dive (to deal with auto pitch adjust)
        self.min_pitch = None
        self.max_pitch = None
        self.bottom_rho0 = np.nan  # the bottom density recorded for this dive
        self.bottom_press = np.nan  # the bottom pressure recorded for this dive
        self.dive_data_ok = None  # unknown; else True, the data is available or False, there was some issue (see load_dive_data())
        self.n_valid = 0  # how many valid points will this dive provide
        # values of parameters from nc file
        # these could come from many places, initially sg_calib_constants.  but we don't care.
        # what we do care about is whether we they differ from our estimates in which case we trigger reprocessing
        # which should update the nc files to our calculations
        self.nc_volmax = 0
        # if a/b change we need to recompute vbdbias and abs_compress, otherwise skip it
        self.recompute_vbdbias_abs_compress = True
        self.nc_vbdbias = np.nan
        self.nc_hd_a = 0
        self.nc_hd_b = 0
        self.nc_abs_compress = np.nan

        # what was onboard for estimating flight parameters for this dive
        self.log_HD_A = 0
        self.log_HD_B = 0
        self.log_HD_C = 0

        # estimated parameters for this dive from FlightModel.py
        self.hd_ab_trusted = (
            False  # whether the a/b values come from a trusted or untrusted estimate
        )
        self.hd_a = 0
        self.hd_b = 0
        self.volmax = np.nan
        self.vbdbias = np.nan  # critical for this to start as nan
        self.median_vbdbias = np.nan
        self.abs_compress = np.nan
        self.w_rms_vbdbias = np.nan  # w_rms at vbdbias (and abs_compress)

    def __repr__(self):
        return (
            "<Dive %d pitch_d: %.1f p: %.1fdbar vbias: %.1fcc (%.1fcc) abs_compress=%g RMS%s=%5.4fcm/s>"
            % (
                self.dive_num,
                self.pitch_d,
                self.bottom_press,
                self.vbdbias,
                self.nc_vbdbias,
                self.abs_compress,
                "t" if self.hd_ab_trusted else "",
                self.w_rms_vbdbias,
            )
        )


def estimate_volmax(mass, density, vbd_adjust=660):
    # Estimate of volmax given mass of the vehicle and an insitu density measurement or estimate
    # This estimate just has to get us within +/-1000cc; we'll adjust it based on vbdbias calculations per dive later
    # cm_per_m**3 == cc_per_m3 == 1e6
    # Optionally adjust using a rough guess about VBD volume at max pump (vbd_min_cnts vs c_vbd)
    # - (vbd_neutral + eng_vbd_cc[max_density_i])
    # eng_vbd_cc is typically -200cc and vbd_neutral is (2000 - 150)/(1/-0.25) ~= -460 (540 for DG)
    # so - (-200 + -460) ~= - -660 -> + 660cc
    return (mass / density) * (cm_per_m**3) + vbd_adjust


# Known bug: Since the FM code is run before MakePlot, the plots subdirectory might not exist
# but after the first dive is complete it does exist.  So the initial dive (and its figures)
# will not appear in plots...
def write_figure(basename, delete=False):
    global flight_directory, plots_directory
    figure_output_name = os.path.join(flight_directory, basename)
    if delete:
        if os.path.exists(figure_output_name):
            os.remove(figure_output_name)
    else:
        plt.savefig(figure_output_name, format="webp")
    if plots_directory:
        plots_figure_output_name = os.path.join(plots_directory, basename)
        if delete:
            try:
                if os.path.exists(plots_figure_output_name):
                    os.remove(plots_figure_output_name)
            except:
                log_warning(f"Failed to remove {plots_figure_output_name}", "exc")
        else:
            try:
                shutil.copyfile(figure_output_name, plots_figure_output_name)
            except:
                log_warning(
                    f"Failed to copy {figure_output_name} to {plots_figure_output_name}"
                )


# The memory burden of the various caches can grow large, especially when we were caching results from load_dive_data()
# This function, which knows about the types we typically use in the program
# returns the deep memory burden, in bytes, of an object d, while avoiding double counting
# def deep_getsizeof(d, ids=set()):
def deep_getsizeof(d, ids):
    id_d = id(d)
    if id_d in ids:
        return 0
    ids.add(id_d)  # we've see this top level guy now and update by side-effect
    t = type(d)
    if t in (int, float, np.int64, np.float64, str, object):
        return sys.getsizeof(d)
    # Various container and mapping classes we know about
    ssum = sys.getsizeof(d)  # get overhead and any 'spine'
    if t in (list, set, tuple):
        for x in d:
            ssum += deep_getsizeof(x, ids)
    elif t is dict:
        for k, v in list(d.items()):
            ssum += deep_getsizeof(k, ids)
            ssum += deep_getsizeof(v, ids)
    elif isinstance(d, flight_data):  # flight_data
        ssum += deep_getsizeof(d.__dict__, ids)
    elif t is np.ndarray:
        # numpy array, assume of float64s
        ssum += np.prod(d.shape) * sys.getsizeof(np.float64(1.0))
    return ssum


def pfdd(verbose=False):
    """print flight_dive_data_d status"""
    if verbose:
        print(
            (
                "Flight database as of %s:"
                % time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            )
        )
    for fv in header_variables:
        if fv == "history":
            continue
        print(f"{fv}: {str(flight_dive_data_d[fv])}")
    for fv in assumption_variables:
        print(f"{fv}: {flight_dive_data_d[fv]:g}")
    for fv in flight_variables:
        print(f"{fv}: {flight_dive_data_d[fv]:g}")
    print(f"{len(flight_dive_data_d['dives'])} dives")
    if verbose:
        for dive_num in flight_dive_data_d["dives"]:
            print(f" {flight_dive_data_d[dive_num]}")


def load_flight_database(
    base_opts, sg_calib_constants_d, verify=False, create_db=False
):
    """Load or create a flight database.  Recreate if assumptions have changed.
    Returns True or False whether the database was (re)initialized
    Side-effects: Sets several globals, including flight_dive_data_d and possibly the db filename
    """

    global \
        flight_dive_data_d, \
        flight_directory, \
        flight_dive_data_filename, \
        ab_grid_cache_d, \
        restart_cache_d
    if flight_dive_data_d is not None:
        return False

    flight_directory = os.path.join(base_opts.mission_dir, "flight")
    flight_directory_ok = os.path.exists(flight_directory)
    if not flight_directory_ok and create_db:
        try:
            os.mkdir(flight_directory)
            # Ensure that MoveData can move it as pilot if not run as the glider account
            os.chmod(
                flight_directory,
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IWGRP
                | stat.S_IROTH
                | stat.S_IXOTH,
            )
            flight_directory_ok = True
        except:
            log_error(f"Could not create {flight_directory}", "exc")
            # fall though

    if flight_directory_ok:
        # this file either exists or can be created so set this global
        flight_dive_data_filename = os.path.join(flight_directory, "flight.pkl")
        try:
            fh = open(flight_dive_data_filename, "rb")
            (flight_dive_data_d) = pickle.load(fh)  # reload
            fh.close()
        except:
            pass  # file corrupt or doesn't exist

    if flight_dive_data_d is not None:  # prior version exists?
        rebuild = flight_dive_data_d["fm_version"] != fm_version
        if verify:  # have we filled sg_calib_constants_d with defaults for the assumption_variables?
            rebuild = (
                rebuild
                or len(
                    list(
                        filter(
                            lambda variable: (
                                getattr(sg_calib_constants_d, variable, False)
                                and flight_dive_data_d[variable]
                                != sg_calib_constants_d[variable]
                            ),
                            assumption_variables,
                        )
                    )
                )
                > 0
            )

        if rebuild:
            # assumptions differ somehow...
            log_warning("Assumptions changed; rebuilding flight data base.")
            flight_dive_data_d = None  # rebuild this from scratch

    if flight_dive_data_d is not None:
        # We have acceptable data from last time
        # DEBUG remove flush_ab_grid_cache_entries to force recomputation
        ab_grid_cache_d = flight_dive_data_d["ab_grid_cache"]
        for dive_num in flush_ab_grid_cache_entries:
            try:
                del ab_grid_cache_d[dive_num]
            except KeyError:
                pass
        return False

    if not create_db:
        # this is likely a call from get_flight_parameters()
        # current db is None; make it look like we just created it, always
        return True

    # if we get here create or restart db
    flight_dive_data_d = {}
    flight_dive_data_d.update(
        {
            "fm_version": fm_version,
            "last_updated": time.time(),
            "dives": [],  # what dives have instances, in order
            "glider": int(sg_calib_constants_d["id_str"]),
            "mission_title": sg_calib_constants_d["mission_title"],
            "history": "",  # accumulated processing history for all runs
            "hd_s_scale": 1,  # how to scale hd_b for vehicles not using s=-1/4
            "ab_grid_cache": {},  # a map from max dive -> (tared RMS grid,ia,ib,min_misfit,dive_set,pitch_diff)
            "restart_cache": {},  # a map from a dive -> (<data required to restart the process_dive() loop from dive>)
            # Other entries:
            # for determining glider type:
            # (these are not defined until we load the first nc dive data)
            #   'GLIDER_TYPE' for glider type
            #   'has_gpctd'
            # The a/b search grid to use
            # all 'global' assumption_variables, e.g,
            #   'mass','mass_comp': <sgc values>
            # vehicle-specific FM estimated values
            #   'volmax': estimated from the first 20 dives or so from bottom density, mass, and per-dive vbdbias corrections
            #   'rho0': max of all bottom insitu-densities
            #   'abs_compress': mean of our per-dive estimates
            # vehicle-type assumed values
            #   'hd_a': <type value>
            #   'hd_b': <type value>
            #   'hd_c': <type value>
            #   'hd_s': <type value>
            #   'glider_length': <type value>
            #    etc.
            # the FM per-dive results instances
            #   1: <flight_data dive 1>: vbdbias, hd_a, hd_b
            # TODO
            # cache the a and b grid values given type
        }
    )
    if verify:
        # initialize assumptions by copy from sgc
        for fv in assumption_variables:
            flight_dive_data_d[fv] = sg_calib_constants_d[fv]
    return True


# Make a copy of sg_calib_constants.m and comment out any lines referencing a flight variable
# def cleanse_sg_calib_constants(sg_calib_file_name):
#     global flight_directory
#     save_sg_calib_file_name = '%s.orig' % sg_calib_file_name
#     if os.path.exists(save_sg_calib_file_name):
#         return
#     shutil.copyfile(sg_calib_file_name, save_sg_calib_file_name) # back it up
#     changed_lines = 0

#     comment = re.compile(r"%.*")  # % and anything after it, to a newline

#     # See if anything needs changing
#     fi = open(sg_calib_file_name, "r")
#     for sg_line in fi:
#         if not sg_line.find(ignore_tag) >= 0: # not already ignored (from past version)
#             # Make sure we are not flagging something in a comment
#             if comment.search(sg_line):
#                 sg_line, _ = comment.split(sg_line)
#             for tag in ignore_tags:
#                 if sg_line.find(tag) >= 0:
#                     changed_lines += 1
#                     break
#     fi.close()
#     if changed_lines == 0:
#         # No lines need changing - proceed
#         log_info("%s needs no cleaning" % sg_calib_file_name)
#         return

#     log_info("%s contains lines needing to cleansed" % sg_calib_file_name)
#     changed_lines = 0
#     if not os.access(sg_calib_file_name, os.W_OK):
#         log_error("No write access to %s - fix permissions" % sg_calib_file_name)

#     changed_lines = 0
#     try:
#         fh1 = open(save_sg_calib_file_name, "r")
#         fh2 = open(sg_calib_file_name, "w")
#         for sg_line in fh1:
#             if not sg_line.find(ignore_tag) >= 0: # not already ignored (from past version)
#                 for tag in ignore_tags:
#                     if sg_line.find(tag) >= 0:
#                         sg_line = '%% %s %s' % (ignore_tag, sg_line)
#                         changed_lines += 1
#                         break
#             fh2.write(sg_line)
#         if False:
#             fh2.write('sbect_modes = 1;') # speed up reprocessing
#         fh2.close()
#         fh1.close()
#         if changed_lines:
#             changed_lines = 'FlightModel commented out %d lines in sg_calib_constants.m' % changed_lines
#             log_warning(changed_lines, alert='SGC') # use SGC rather than FM since we might have other FM alerts
#     except:
#         # Typically we are running as the glider and it might not have write access
#         # to sg_calib_constants.m (unlike pilot) if it is owned by pilot:gliders, but no g+w or even a+w prives.
#         # We cannot run FM unless sg_calib_constants is cleansed since our ideas will be overwritten by sgc
#         # An alternative would be to force flush any explicit flight variables in sgc before we set ours
#         # but eventually the files would be accompanied by a poisoning sgc...

#         # Put this in the log file to make things abundently clear
#         log_error("Failed to cleanse sg_calib_constants - trying fallback strategy", 'exc')

#         try:
#             os.remove(save_sg_calib_file_name)
#         except:
#             log_error("Unable to remove %s" % save_sg_calib_file_name, 'exc')

#         if flight_directory is not None: # this should always be True since this fn is called only after reinitialization
#             log_warning("Falling back on removing %s and starting from scratch" % flight_directory)
#             try:
#                 # force the system to restart and try overwriting sg_calib_constants.m again
#                 shutil.rmtree(flight_directory)
#             except:
#                 log_error("Unable to remove %s" % flight_directory, 'exc')
#             else:
#                 # Subsequent code assumes this directory already exists
#                 os.mkdir(flight_directory)
#         alert = 'Unable to cleanse sg_calib_constants.m; if owned by pilot, change protections to g+w'
#         log_error(alert, alert='FM_CALIBCONSTS')
#         #raise RuntimeError, alert
#         return


# Dump/checkpoint the flight database by pickling
# pylint: disable=unused-argument
def save_flight_database(base_opts, dump_mat=False):
    global flight_dive_data_d, flight_dive_data_filename, flight_dive_nums
    if flight_dive_data_filename is not None and flight_dive_data_d is not None:
        flight_dive_data_d["last_updated"] = time.time()

        processing_log = BaseLogger.self.stopStringCapture()
        flight_dive_data_d["history"] = flight_dive_data_d["history"] + processing_log
        BaseLogger.self.startStringCapture()  # restart string capture

        try:
            fh = open(flight_dive_data_filename, "wb")
            pickle.dump((flight_dive_data_d), fh)
            fh.close()
        except:
            log_warning(f"Unable to rebuild {flight_dive_data_filename}!")

        dump_mat = dump_mat or dump_checkpoint_data_matfiles
        if dump_mat:
            mat_d = {}
            for fv in header_variables:
                mat_d[fv] = flight_dive_data_d[fv]
            for fv in assumption_variables:
                mat_d[fv] = flight_dive_data_d[fv]
            for fv in flight_variables:
                mat_d[fv] = flight_dive_data_d[fv]
            for fv in ["hd_a_grid", "hd_b_grid"]:
                mat_d[fv] = flight_dive_data_d[fv]

            if flight_dive_nums is not None:
                dds = [flight_dive_data_d[d] for d in flight_dive_nums]
                mat_d["dive_nums"] = flight_dive_nums
                mat_d["dives_pitch_d"] = [dd.pitch_d for dd in dds]
                mat_d["dives_start_time"] = [dd.start_time for dd in dds]
                mat_d["dives_bottom_rho0"] = [dd.bottom_rho0 for dd in dds]
                mat_d["dives_bottom_press"] = [dd.bottom_press for dd in dds]
                mat_d["dives_hd_a"] = [dd.hd_a for dd in dds]
                mat_d["dives_hd_b"] = [dd.hd_b for dd in dds]
                mat_d["dives_vbdbias"] = [dd.vbdbias for dd in dds]
                mat_d["dives_median_vbdbias"] = [dd.median_vbdbias for dd in dds]
                mat_d["dives_abs_compress"] = [dd.abs_compress for dd in dds]
                mat_d["dives_w_rms_vbdbias"] = [dd.w_rms_vbdbias for dd in dds]
            # dump the ab_grid_cache values and arrays
            ab_grid_cache_d = flight_dive_data_d["ab_grid_cache"]
            dives = list(ab_grid_cache_d.keys())
            if len(dives):
                dives.sort()
                n_dives = len(dives)
                mat_d["rms_dive_nums"] = dives
                cache_entry = ab_grid_cache_d[dives[0]]
                W_misfit_RMS, ia, ib, min_misfit, dive_set, pitch_d_diff = cache_entry
                RMS_shape = W_misfit_RMS.shape
                RMS_shape = RMS_shape + (n_dives,)
                RMS_array = np.zeros(RMS_shape, np.float64)
                dives_ia = []
                dives_ib = []
                dives_misfit = []
                dives_pitch_d_diff = []
                for d_n, i in zip(dives, list(range(n_dives))):
                    (
                        W_misfit_RMS,
                        ia,
                        ib,
                        min_misfit,
                        dive_set,
                        pitch_d_diff,
                    ) = ab_grid_cache_d[d_n]
                    RMS_array[:, :, i] = W_misfit_RMS
                    dives_ia.append(ia + 1)  # matlab indexing
                    dives_ib.append(ib + 1)  # matlab indexing
                    dives_misfit.append(min_misfit)
                    dives_pitch_d_diff.append(pitch_d_diff)
                mat_d["rms_grids"] = RMS_array
                mat_d["rms_ia"] = dives_ia
                mat_d["rms_ib"] = dives_ib
                mat_d["rms_min_misfit"] = dives_misfit
                mat_d["rms_pitch_d_diff"] = dives_pitch_d_diff
            mat_filename = f"{flight_dive_data_filename}.mat"
            sio.savemat(mat_filename, {"flight_dive_data": mat_d})
        if checkpoint_flight_dive_data and flight_dive_nums is not None:
            global flight_directory
            # tag = time.strftime("%d%b%Y_%H%M%S", time.gmtime(time.time()))
            output_basename = os.path.join(
                flight_directory, "fdd_%04d" % max(flight_dive_nums)
            )
            shutil.copyfile(flight_dive_data_filename, f"{output_basename}.pkl")
            if dump_mat:
                shutil.copyfile(mat_filename, f"{output_basename}.mat")
    else:
        log_error("Unable to save flight database!")


# called from MakeDiveProfile to update sg_calib_constants_d parameters for the dive
def get_flight_parameters(dive_num, base_opts, sg_calib_constants_d):
    global \
        flight_dive_data_d, \
        flight_dive_nums, \
        predicted_hd_a_scale, \
        predicted_hd_b_scale

    # load or reinitialize; doesn't matter
    initialized = load_flight_database(
        base_opts, sg_calib_constants_d, verify=False, create_db=False
    )
    if initialized:
        # BUG we have possible sequencing problem
        # at the beginning MDP will try to process the first dive and there is no flight db so we come here
        # MDP then processes the dive with the given sgc constants, from a mix of user and MDP defaults
        # but if the user estimates volmax incorrectly the dive can fail to process because the dive and/or
        # climb will stall and all of salinity will be bad, etc.
        # the nc file will have the raw data but perhaps not all the bits we want
        # should we avoid processing error or not?

        return  # we have no vehicle specific data (yet)
    flight_dive_nums = flight_dive_data_d["dives"]
    log_debug(f"flight_dive_nums : {flight_dive_nums}")

    # Find the dive_data that is most-recent to the given dive_num (since this might be a new dive)
    d_n = None
    if len(flight_dive_nums):
        # Three cases: It is present directly, there was a gap and we are filling it, or we are extending the dive set
        # this handles all
        d_n_i = np.where(np.array(flight_dive_nums) <= dive_num)[0]
        if len(d_n_i) > 0:
            d_n = flight_dive_nums[d_n_i[-1]]  # the most-recent dive

    # first ALWAYS fill out all variables EXPLICITLY with our prevailing defaults (including current abs_compress and volmax)
    # This must happen because we cleansed sg_calib_constants.m so the variables have to come from somewhere...
    for fv in flight_variables:
        sg_calib_constants_d[fv] = flight_dive_data_d[fv]
    if d_n is not None:
        dive_data = flight_dive_data_d[d_n]
        if ~np.isnan(dive_data.vbdbias):
            log_info(
                "Updating FM parameters using per-dive estimations for dive %d (%.2f,%.2f)"
                % (d_n, predicted_hd_a_scale, predicted_hd_b_scale)
            )
            # override with per-dive data
            # See note about scaling above...
            sg_calib_constants_d["hd_a"] = dive_data.hd_a * predicted_hd_a_scale
            sg_calib_constants_d["hd_b"] = dive_data.hd_b * predicted_hd_b_scale
            sg_calib_constants_d["vbdbias"] = dive_data.vbdbias
            sg_calib_constants_d["abs_compress"] = dive_data.abs_compress

    # otherwise no specific dive data so let subsequent call get_FM_defaults() by MDP (in sg_config_constants()) fill in possible defaults


# def get_FM_defaults(consts_d={}, glider_type=None):
def get_FM_defaults(consts_d, glider_type=None):
    # TODO change parms.c to reflect new defaults
    # update/override variables in consts_d according to glider_type
    # Must supply a value for each of the flight_variables

    if glider_type is None:
        try:
            if "sg_configuration" not in consts_d:
                raise RuntimeError("Internal Error - sg_configuration not specified")

            # MDP:sg_config_constants() calls with sg_configuration included
            glider_type = {
                0: SEAGLIDER,
                1: SEAGLIDER,
                2: DEEPGLIDER,
                3: SEAGLIDER,
                4: OCULUS,
            }[consts_d["sg_configuration"]]
        except KeyError as exc:
            raise RuntimeError(
                "Unknown sg_configuration type %d!" % consts_d["sg_configuration"]
            ) from exc

    consts_d["rho0"] = FM_default_rho0
    consts_d["vbdbias"] = 0.0
    try:
        # MDP:sg_config_constants() calls with mass passed as does the initialization call below
        mass = consts_d["mass"]
        consts_d["volmax"] = estimate_volmax(mass, FM_default_rho0)
    except KeyError:
        log_warning("How can mass be missing?")

    if "mass_comp" not in consts_d:
        consts_d["mass_comp"] = 0

    # Set the 'constant' values for flight model searches per vehicle type
    consts_d["hd_c"] = 5.7e-6  # induced drag (constant for all vehicles)
    # BAD consts_d['hd_c'] = 5.0e-5 # induced drag (constant for all vehicles) CCE 1/2019 from PAPA Jun09 steep low-thrust dives
    # This constant is used aboard for all glider types; while it just serves to scale drag, we need to match the value used aboard
    consts_d["glider_length"] = 1.8
    consts_d["temp_ref"] = 15.0

    # The precision of the hd_a/hd_b values below are spurious...they are just the values from the hd_a/b grid I happened to search
    if glider_type == SEAGLIDER:
        consts_d["hd_a"] = 0.003548133892336
        consts_d["hd_b"] = 0.011220184543020  # from rva experiments (hd_b_grid)
        consts_d["hd_s"] = sg_hd_s  # how the drag scales by shape
        # thermal expansion of the hull
        consts_d["therm_expan"] = 7.05e-5  # m^3/degree
        # % compressibility of the hull per dbar
        consts_d[
            "abs_compress"
        ] = 4.1e-6  # m^3/dbar (slightly less than the compressibility of SW)
        if consts_d["mass"] > SGX_MASS:
            # An SGX, which are massive vehicles
            log_info("FM:Assuming this is an SGX vehicle", max_count=1)
            consts_d["hd_a"] = 0.003548133892336
            consts_d["hd_b"] = 0.015848931924611  # a little more drag than even DGs
            consts_d[
                "hd_s"
            ] = sg_hd_s # 0.0  # how the drag scales by shape (0 for the more standard shape of DG per Eriksen)

    elif glider_type == DEEPGLIDER:
        # TODO change these defaults since we now use hd_s = 0
        # TODO can we use hd_c = 5.7e-6 now that hd_s = 0?
        consts_d["hd_a"] = 0.003548133892336
        consts_d["hd_b"] = 0.014125375446228  # should be sligthly higher
        consts_d["hd_c"] = 2.5e-6  # DG037 53 and 55 stall with higher value
        # consts_d['hd_c']    =   5.7e-6 # increased c to deal with high pitch dives DG046 BATS May19 after dive 70?
        # Lucas experiment consts_d['hd_c']    =   2.5e-5 # DG037 53 and 55 stall with higher value
        consts_d[
            "hd_s"
        ] = 0.0  # how the drag scales by shape (0 for the more standard shape of DG per Eriksen)
        # 9/6/2019: On all DG vehicles we found that FMS underestimated the speeds on both dive and climb for steep dives (> 25 degreees)
        # attempts to deal with c failed but s made a big difference. -0.25 (SG) was ok, -0.30 was better, -0.35 overestimated dive speeds
        # consts_d['hd_s']    =   -0.20 # how the drag scales by shape
        # thermal expansion of the hull
        consts_d["therm_expan"] = 6.214e-5  # m^3/degree Boeing hull
        # % compressibility of the hull per dbar (DG037/39 off Abaco Aug18)
        consts_d["abs_compress"] = 2.10111e-6  # m^3/dbar Boeing hull

    elif glider_type == OCULUS:
        consts_d["hd_a"] = 0.007079457843841  # much higher lift
        consts_d["hd_b"] = 0.014125375446228  # like DG
        consts_d[
            "hd_s"
        ] = 0.0  # how the drag scales by shape (0 for the more standard shape of Oculus per Eriksen)
        # thermal expansion of the hull
        consts_d["therm_expan"] = 7.05e-5  # m^3/degree
        # % compressibility of the hull per dbar
        # NOTE: because of the different VBD system, the piston collapses under pressure
        # which means that the 'compressibility' of the vehicle is very squishy and not constant
        # We force a plausible 'constant' here since there will be little pressure effect over 200m, the Oculus max depth
        # and we avoid estimating abs_compress below
        consts_d["abs_compress"] = 2.45e-6  # m^3/dbar
    return glider_type


def dump_fm_values(dive_data):
    # For anxious pilots who want to see the solutions for each dive, dump in a format they can abuse into sg_calib_constants.m if desired
    # TOOD eventually eliminate the per-dive option and only dump the data if the entire missions looks 'stable'
    # then just dump fm.m and only use flight_dive_data_d values
    global dump_fm_files, flight_dive_data_d, flight_directory, glider_mission_string
    if not dump_fm_files:
        return
    fm_filename = os.path.join(flight_directory, "fm_%04d.m" % dive_data.dive_num)
    try:
        fh = open(fm_filename, "w")
        fh.write(
            "%% Dive %d as of %s\n"
            % (
                dive_data.dive_num,
                time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time())),
            )
        )
        fh.write(f"% {glider_mission_string}\n")
        fh.write(f"volmax = {flight_dive_data_d['volmax']:g};\n")
        fh.write(
            "vbdbias = %g; %% vbdbias w rms = %.2f cm/s\n"
            % (dive_data.vbdbias, dive_data.w_rms_vbdbias)
        )
        volmax_biased = flight_dive_data_d["volmax"] - dive_data.vbdbias
        fh.write(f"volmax_biased = {volmax_biased:g};\n")
        fh.write(f"abs_compress = {dive_data.abs_compress:g};\n")
        fh.write(f"hd_a = {dive_data.hd_a:g};\n")
        fh.write(f"hd_b = {dive_data.hd_b:g};\n")
        hd_s = flight_dive_data_d["hd_s"]
        if hd_s == 0:
            fh.write(
                "%% hd_b scaled for glider operation: $HD_B,%g\n"
                % (dive_data.hd_b * flight_dive_data_d["hd_s_scale"])
            )
        # from vehicle defaults
        fh.write(f"hd_c = {flight_dive_data_d['hd_c']:g};\n")
        fh.write(f"hd_s = {hd_s:g};\n")
        fh.write(
            "therm_expan = %g;\ntemp_ref = %g;\n"
            % (flight_dive_data_d["therm_expan"], flight_dive_data_d["temp_ref"])
        )

        # rho0? glider_length?
        fh.close()
    except:
        log_error(f"Unable to write {fm_filename}", "exc")


# Given a dive_data instance, open the nc file and load the vectors and other data we need for regression processing
# make if data is ok and avoid loading again if known bad
def load_dive_data(base_opts, dive_data):
    global \
        nc_path_format, \
        angles, \
        compare_velo, \
        mission_directory, \
        ignore_salinity_qc, \
        max_speed
    global decimation, data_density_max_depth
    data_d = None
    if dive_data.dive_data_ok is False:
        # tried this before and it failed
        return data_d
    # either we don't know (None) or it has worked in the past (True but we were called anyway)
    dive_data.dive_data_ok = False  # assume the worst
    dive_num = dive_data.dive_num

    dive_nc_file_name = nc_path_format % dive_num
    try:
        dive_nc_file = Utils.open_netcdf_file(dive_nc_file_name, "r")
    except:
        log_error(f"Unable to open {dive_nc_file_name}", "exc")
        return data_d

    try:
        # Check for skipped first, which will also have a processing error noted
        if "skipped_profile" in dive_nc_file.variables:
            log_warning("Dive %d is marked as a skipped_profile" % dive_num)
            raise RuntimeError

        if "processing_error" in dive_nc_file.variables:
            log_warning("Dive %d is marked as having a processing error" % dive_num)
            raise RuntimeError

        start_time = getattr(
            dive_nc_file, "start_time", None
        )  # protected against malformed files
        if start_time is None:
            log_warning("Dive %d no start time?" % dive_num)
            raise RuntimeError

        dive_data.start_time = start_time
        # SG eng time base
        eng_time = dive_nc_file.variables["time"][:] - start_time
        ctd_time = dive_nc_file.variables["ctd_time"][:] - start_time
        num_pts = len(ctd_time)
        if num_pts == 0:
            log_warning("No data for dive %d" % dive_num)
            raise RuntimeError  # close the file handle below

        pitch_d = float(
            dive_nc_file.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
            .tobytes()
            .decode("utf-8")
            .split(",")[2]
        )
        dive_data.pitch_d = abs(int(pitch_d))  # update pitch_d to nearest degree

        # These values *might* have come from sg_calib_constants but they could also have come from FlightModel
        # Wherever, those values are cached in the sgc_ variables in the nc file
        # It is possible for the values to be the defaults, in which case there are no explicit values in the nc file
        # provide defaults in that case
        for sgc_var, fdd_var, nc_var in zip(
            [
                "sg_cal_hd_a",
                "sg_cal_hd_b",
                "sg_cal_volmax",
                "sg_cal_vbdbias",
                "sg_cal_abs_compress",
            ],
            ["hd_a", "hd_b", "volmax", "vbdbias", "abs_compress"],
            ["nc_hd_a", "nc_hd_b", "nc_volmax", "nc_vbdbias", "nc_abs_compress"],
        ):
            try:
                value = dive_nc_file.variables[sgc_var].getValue()
            except KeyError:
                # was not explicity set in nc file;
                # assume our prevailing default (from get_FM_defaults() via sg_config_constants())
                # DEAD value = flight_dive_data_d[fdd_var]
                # This happens only once since we explicitly set all FM variables using FM code
                # As we reprocess the FM code below explicitly sets/updates all these values so we should not be in this path more than once
                # so even as processing occurs and fdd values drift from the defaults, those are explicitly set and recorded in the nc
                value = np.nan  # we have no idea (could be default)
            setattr(dive_data, nc_var, value)
        for log_var in ["log_HD_A", "log_HD_B", "log_HD_C"]:
            try:
                value = dive_nc_file.variables[log_var].getValue()
            except KeyError:
                log_error("Missing %s for dive %d!?" % (log_var, dive_num))
            setattr(dive_data, log_var, value)

        # DEAD log_info('ldd: %d %g %g' % (dive_data.dive_num, dive_data.hd_a,dive_data.hd_b)) # DEBUG
        # TODO - pitchbias and - rollbias
        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_roll_ang = dive_nc_file.variables["eng_rollAng"][:]
        eng_vbd_cc = dive_nc_file.variables["eng_vbdCC"][:]
        press = dive_nc_file.variables["pressure"][:]
        if len(ctd_time) != len(eng_time):
            # interpolate pitch/roll/vbd/press/depth to ctd_time
            eng_pitch_ang = Utils.interp1d(
                eng_time, eng_pitch_ang, ctd_time, kind="linear"
            )
            eng_roll_ang = Utils.interp1d(
                eng_time, eng_roll_ang, ctd_time, kind="linear"
            )
            eng_vbd_cc = Utils.interp1d(eng_time, eng_vbd_cc, ctd_time, kind="linear")
            press = Utils.interp1d(eng_time, press, ctd_time, kind="linear")

        depth = dive_nc_file.variables["ctd_depth"][:]
        w = Utils.ctr_1st_diff(-depth * cm_per_m, ctd_time)
        # if the pressure sensor is noisy then we can get poor results when looking for still water
        w = Utils.medfilt1(w, L=min(num_pts, vbdbias_filter))
        abs_w = abs(w)
        if limit_to_still_water:
            dwdt = abs(Utils.ctr_1st_diff(w, ctd_time))
            mdwdt = Utils.medfilt1(dwdt, L=min(num_pts, vbdbias_filter))
        else:
            mdwdt = np.zeros(num_pts, np.float64)  # assert everywhere is still
        # SG227 SODA Aug19 post dive 70 had intermittent pressure sensor issues so wildly bad w's
        # Consider adding tests to eliminate points that are driven by that noise (like limiting abs(dwdt) < 2cm/s^2
        # Thus we look for both quiet locations and actively expunge anti-quiet locations
        temperature_raw = dive_nc_file.variables["temperature_raw"][:]
        salinity_raw = dive_nc_file.variables["salinity_raw"][:]

        # TODO - GBS 2022/10/14 - SG243, AMOS2022 had an inital dive with negative salinities - consider changing
        # to something like the below, but move up/refactor this code to handle the reduced vector size.

        # good_pts = np.logical_not(np.logical_or(salinity_raw < 0.0, np.logical_or(np.np.isnan(salinity_raw), np.isnan(temperature_raw))))
        # temperature_raw = temperature_raw[good_pts]
        # salinity_raw = salinity_raw[good_pts]
        # press = press[good_pts]
        # ctd_time = ctd_time[good_pts]

        # Protect against dives with bad values in the temperature_raw and salinity_raw columns
        try:
            if not base_opts.use_gsw:
                density_insitu = seawater.dens(salinity_raw, temperature_raw, press)
                density = seawater.pden(salinity_raw, temperature_raw, press, 0)
            else:
                if "avg_longitude" in dive_nc_file.variables:
                    avg_longitude = dive_nc_file.variables["avg_longitude"].getValue()
                else:
                    # Older basestations didn't calcuate this value
                    avg_longitude = MakeDiveProfiles.avg_longitude(
                        dive_nc_file.variables["log_gps_lon"][1],
                        dive_nc_file.variables["log_gps_lon"][2],
                    )
                density_insitu = Utils.density(
                    salinity_raw,
                    temperature_raw,
                    press,
                    avg_longitude,
                    dive_nc_file.variables["avg_latitude"].getValue(),
                )
                density = Utils.pdensity(
                    salinity_raw,
                    temperature_raw,
                    press,
                    avg_longitude,
                    dive_nc_file.variables["avg_latitude"].getValue(),
                )
        except:
            log_error(f"Failed density calculation for {dive_num} - skipping", "exc")
            return None

        # use the values in the log file, not the pilot's fiction in sg_calib_constants.h
        # this is what the glider used
        vbd_min_cnts = dive_nc_file.variables["log_VBD_MIN"].getValue()
        vbd_cnts_per_cc = 1.0 / dive_nc_file.variables["log_VBD_CNV"].getValue()
        c_vbd = dive_nc_file.variables["log_C_VBD"].getValue()
        vbd_neutral = (c_vbd - vbd_min_cnts) / vbd_cnts_per_cc
        volmax = flight_dive_data_d["volmax"]
        # Need to eliminate flare, apogee+loiter, surface maneuver, anomalies, etc. where our model won't work
        # We use salinity_qc, which reflects those decisons, but also reflects addition decisions
        # based on speed and stalls, which in turn depends on our work here.
        # so just because there are no good points the first time(s) around, doesn't mean we can't
        # find flight constants that permit a good estimate of speeds later
        # ALTERNATIVE: just rely on w, a measured quantify, below for 'motion'
        ignore_speed_gsm = True  # Originally False
        speed_gsm = dive_nc_file.variables["speed_gsm"][:]
        n_velo = 0
        correct_aoa_velo = True  # whether speed needs angle of attack correction
        if compare_velo:
            try:
                velo_speed = dive_nc_file.variables["velo_speed"][:]
                n_velo = len(
                    np.where(np.isfinite(velo_speed))[0]
                )  # will be nonzero only when compare_velo and data was recorded
            except KeyError:
                # no velo data in the nc file (from onboard data
                # see of there is a velo mat file (from tracking range)
                velo_pathname = os.path.join(
                    mission_directory, "velo_%d.mat" % dive_num
                )
                try:
                    velo_data_d = sio.loadmat(velo_pathname)
                    velo_speed = velo_data_d["velo_speed"]
                    velo_speed = np.reshape(velo_speed, num_pts, 1)
                    correct_aoa_velo = False  # externally measured
                except:
                    pass
                else:
                    n_velo = len(
                        np.where(np.isfinite(velo_speed))[0]
                    )  # will be nonzero only when compare_velo and data was recorded

        # TODO real(density_insitu)
        # Find where data was apparently good
        good_pts = np.zeros(num_pts)
        good_pts_i_v = list(
            filter(
                lambda i: np.isfinite(temperature_raw[i])
                and np.isfinite(salinity_raw[i])
                and (pressmin <= press[i] <= pressmax)
                and (not n_velo or np.isfinite(velo_speed[i]))
                and mdwdt[i] <= limit_to_still_water
                and abs_w[i] <= max_speed,
                range(num_pts),
            )
        )
        if len(good_pts_i_v) == 0:
            log_warning(
                "Dive %d has no good points; pressure sensor noise? (mean: %f min: %f)"
                % (dive_num, np.mean(mdwdt), min(mdwdt))
            )
            return data_d

        if not ignore_salinity_qc:
            # if we have a mis-estimate of the flight model parameters, notably volmax/vbdbias, etc
            # then we will have stalled speed_hdm solutions and hence QC_PROBABLY_BAD marks in salinity_qc
            # avoid those in the hope our searches find a better set of parameters
            # Cannot be salinity_raw_qc because apogee, surface, are not removed
            # NOTE BUG: if solve_flare_apogee_speed is set in sg_calib_constants when flare/apogee/climb pump speeds
            # are computed using the momentum balance eqns and the points we want to remove are set to QC_PROBABLY_GOOD
            # and we include those accelerations in the good points. But the HDM code, which we rely upon, doesn't
            # solve for those points well do we can get messed up.
            # Need to mark those points separately in anpther vector showing accelerations? and use that here?
            # Mark as VBD/pitch/roll flags per point.
            # Have HDM solve during those points?
            salinity_qc = QC.decode_qc(dive_nc_file.variables["salinity_qc"])
            good_qc_i_v = list(
                filter(
                    lambda i: salinity_qc[i] not in [QC.QC_BAD, QC.QC_UNSAMPLED],
                    range(num_pts),
                )
            )
            good_pts_i_v = np.intersect1d(good_pts_i_v, good_qc_i_v)

        # TODO?
        # directives = ProfileDirectives(base_opts.mission_dir,dive_num)
        # indicies_v_i = directives.eval_function('flight_model_restriction')
        # then intersect any indicies with good_pts
        # what about 'flight_model_force' to ensure points are added anyway?
        # Add these directives to QC.py:drv_functions and ensure data (depth, etc.) is asserted to directives for eval

        npts = len(good_pts_i_v)
        if data_density_max_depth:
            tmp = abs(np.diff(depth[good_pts_i_v]))
            if not tmp.size:
                log_warning(f"Dive {dive_num} has no good depth data")
                raise RuntimeError
            mdd = np.mean(tmp)
            if mdd > data_density_max_depth:
                log_warning(
                    "Dive %d mean data density too sparse: %d pts %.1fm "
                    % (dive_num, npts, mdd)
                )
                raise RuntimeError

        if npts == 0:
            n_valid = 0
            fraction_good = 0
        else:
            if decimation:  # DEBUG -- code to determine minimum data point density that yield good results
                # experimentally reduce good points and see impact on results
                good_pts_i_v = good_pts_i_v[range(0, npts, decimation)]
                npts = len(good_pts_i_v)
                log_info(
                    "Dive %d decimated %d/%d %.2fm "
                    % (
                        dive_num,
                        decimation,
                        npts,
                        np.mean(abs(np.diff(depth[good_pts_i_v]))),
                    )
                )

            good_pts[good_pts_i_v] = 1
            # reduce to valid points and place in data_d = {} if good
            aroll = abs(eng_roll_ang)
            apitch = abs(eng_pitch_ang)
            delta_t = np.zeros(num_pts, np.float64)
            delta_t[0 : num_pts - 1] = ctd_time[1:num_pts] - ctd_time[0 : num_pts - 1]
            delta_t[-1] = delta_t[-2]
            vbddiff = np.zeros(num_pts, np.float64)
            vbddiff[1:num_pts] = np.diff(eng_vbd_cc) / delta_t[1:num_pts]
            avbddiff = abs(np.fix(vbddiff))
            # TODO replace this with intersect1d calls for speed
            valid_i = [
                i
                for i in range(num_pts)
                if (
                    (ignore_speed_gsm or speed_gsm[i] > 0)
                    and
                    # np.isfinite(temperature_raw[i]) and np.isfinite(salinity_raw[i]) and (pressmin <= press[i] <= pressmax) and
                    good_pts[i]
                    and (avbddiff[i] < vbddiffmax)
                    and (rollmin <= aroll[i] <= rollmax)
                    and (pitchmin <= apitch[i] <= pitchmax)
                )
            ]
            n_valid = len(valid_i)
            fraction_good = float(n_valid) / npts

        if n_valid < 10 or fraction_good < required_fraction_good:  # PARAMETER!
            log_warning(
                "Too few valid points for dive %d (%d, %.1f%%)"
                % (dive_num, n_valid, fraction_good * 100.0)
            )
        else:
            pitch = eng_pitch_ang[valid_i]
            apitch = abs(pitch)

            # verify that pitch from the compass looks good (not too noisy) in the still water portions
            #
            # some pitch noise reports come from a bad compass: see sg221 ORBIS Jan18 dives 107:109
            # some come from under-ice operation as the vehicle might bump along the ice roof
            # some can happen if we hit bottom and there is a current so we don't NO_VV for a while (so points before apogee)
            # if there lots of pitch maneuvers (auto pitch adjust) we can see higher apparent noise with this heuristic
            # in any case, we don't trust the pitch represents flight and we don't trust this entire dive even if the later case is ok?
            # the problem is if we assume things are ok and we mix these 'partially suspect' dives with others for a/b testing
            # we get untrustworthy results.
            vpitch = [p for p in apitch if p < 45]
            pitch_noise = np.nanstd(np.diff(vpitch))
            if (
                pitch_noise > 5
            ):  # PARAMETER (typically differences between readings are small and #apogee points is small)
                log_warning(
                    "Noisy pitch from compass on dive %d (std=%.2fdeg)"
                    % (dive_num, pitch_noise)
                )
                raise RuntimeError  # too much compass pitch noise

            data_d = {}  # we are returning data
            dive_data.n_valid = n_valid
            data_d["pitch"] = pitch

            (counts, edges) = np.histogram(apitch, angles)  # 45 counts, 46 edges
            thresh = np.mean(counts) + 1.5 * np.std(
                counts
            )  # > 67% of the pitches fall on these pitches CONSIDER 2*std?
            pitches = [
                a for a in angles[0:-1] if counts[int(a)] >= thresh
            ]  # what are the frequent pitches?
            dive_data.min_pitch = min(pitches)
            dive_data.max_pitch = max(pitches)

            data_d["w"] = w[valid_i]  # what we optimize against
            press = press[valid_i]
            data_d["pressure"] = press  # for compression and compressee
            dive_data.bottom_press = max(press)  # max valid bottom pressure
            # UNNEEDED dive_data.bottom_pressure = max(data_d['pressure']) # Actual bottom press
            data_d["temperature"] = temperature_raw[
                valid_i
            ]  # for compressee and hull thermal expansion
            density_insitu = density_insitu[valid_i]
            data_d[
                "density_insitu"
            ] = density_insitu  # for buoyancy calculations (kg/m^3)
            dive_data.bottom_temp = min(data_d["temperature"])

            density = density[valid_i]
            data_d["density"] = density  # for buoyancy calculations (kg/m^3)
            # deliberately over the valid points
            dive_data.bottom_rho0 = max(density_insitu)
            dive_data.bottom_pden = max(density)

            eng_vbd_cc = eng_vbd_cc[valid_i]
            if compare_velo:
                if n_velo:
                    n_velo = len(valid_i)
                    data_d["velo_speed"] = velo_speed[valid_i]
                else:
                    data_d["velo_speed"] = np.array([])
                data_d["n_velo"] = n_velo
                data_d["correct_aoa_velo"] = correct_aoa_velo

            vbd0 = volmax + vbd_neutral  # [cc] volume when at neutral
            # deliberately no vbdbias here!! see calls to w_rms_func() and updates in solve_ab_grid()
            displaced_volume = (
                vbd0 + eng_vbd_cc
            )  # [cc] measured displaced volume of glider as it varies by VBD adjustments
            data_d["displaced_volume"] = displaced_volume  # for buoyancy calculations
            # Record these for possible display of C_VBD adjustment on vbdbias plot
            data_d["C_VBD"] = c_vbd
            data_d["VBD_CNV"] = vbd_cnts_per_cc

            dive_data.dive_data_ok = True  # data available
    except KeyError:
        log_error("Could not get required data for dive %d" % dive_num)
        data_d = None
    except RuntimeError:
        data_d = None  # error or warning issued above
    dive_nc_file.close()
    return data_d


# Used by w_rms_func() and solve_ab_DAC()
def compute_buoyancy(
    base_opts,
    vbdbias,
    abs_compress,  # these variables can be varied by various FM search routines
    dive_data_d,
):
    # compute buoyancy using given vbdbias (and, implicitly, the computed volmax)
    vbdc = dive_data_d["displaced_volume"] - vbdbias  # apply vbdbias
    press = dive_data_d["pressure"]

    # CURRY: can precompute and cache compressee volume change and therm_expan term since pressure, temperature, and temp_ref don't change
    # However, can't include the abs_compress term since that can vary in our regressions
    try:
        # fetch cached pre-calculated values
        vol_comp = dive_data_d["vol_comp"]
        vol_comp_ref = dive_data_d["vol_comp_ref"]
        therm_expan_term = dive_data_d["therm_expan_term"]
    except KeyError:
        temperature = dive_data_d["temperature"]
        temp_ref = flight_consts_d["temp_ref"]
        therm_expan_term = flight_consts_d["therm_expan"] * (temperature - temp_ref)
        vol_comp = 0
        vol_comp_ref = 0
        mass_comp = flight_consts_d["mass_comp"]
        if mass_comp:
            global compress_cnf
            vol_comp_ref = (
                g_per_kg
                * mass_comp
                / MakeDiveProfiles.compressee_density(
                    np.array([temp_ref]), np.array([0]), compress_cnf
                )
            )
            vol_comp = (
                g_per_kg
                * mass_comp
                / MakeDiveProfiles.compressee_density(temperature, press, compress_cnf)
            )
        # cache these constant values for subsequent calls
        dive_data_d["vol_comp"] = vol_comp
        dive_data_d["vol_comp_ref"] = vol_comp_ref
        dive_data_d["therm_expan_term"] = therm_expan_term

    # compute volume using given abs_compress (and therm_expand) impact on hull only
    # CEE points out that volmax (+ eng_vbd_cc) includes vol_comp to match overall neutral density
    # However, abs compression and thermal expansion only apply to the hull volume not the compressee fluid
    # so remove vol_comp to compute that effect and then add vol_comp to get total volume
    # We use vol_comp_ref since we want the assumed volume of the uncompressed hull on the reference surface
    vol_hull = vbdc - vol_comp_ref
    vol = vol_hull
    if not base_opts.fm_isopycnal:
        vol *= np.exp(-abs_compress * press + therm_expan_term)
    if dump_checkpoint_data_matfiles:
        dive_data_d["vol_hull"] = vol_hull
        dive_data_d["vol_hull_compress"] = vol
    vol = vol + vol_comp
    if base_opts.fm_isopycnal:
        density_insitu = dive_data_d["density"]
    else:
        density_insitu = dive_data_d["density_insitu"]

    buoyancy = g_per_kg * (
        density_insitu * vol * (m_per_cm**3) - flight_consts_d["mass"]
    )
    pitch = dive_data_d["pitch"]
    w = dive_data_d["w"]

    return buoyancy, pitch, w, vol


# Compute the RMS difference between observed and predicted 'w' given a set of flight constants
# returns w_rms_func_bad when hydro_model fails to converge or there are too many points stalled or otherwise bad
def w_rms_func(
    base_opts,
    vbdbias,
    a,
    b,
    abs_compress,  # these variables can be varied by various FM search routines
    dive_data_d,
    return_components=False,
):
    global flight_consts_d, HIST, compare_velo
    # override from our current search variables
    flight_consts_d["hd_a"] = a
    flight_consts_d["hd_b"] = b
    buoyancy, pitch, w, vol = compute_buoyancy(
        base_opts, vbdbias, abs_compress, dive_data_d
    )
    hm_converged, hdm_speed_cm_s_v, hdm_glide_angle_rad_v, fv_stalled_i_v = hydro_model(
        buoyancy, pitch, flight_consts_d
    )
    hdm_w_speed_cm_s_v = hdm_speed_cm_s_v * np.sin(
        hdm_glide_angle_rad_v
    )  # could delay this until we see if enough valid points are around
    if (
        dump_checkpoint_data_matfiles
    ):  # DEBUG for dumping solve_ab mat files of combined data
        dive_data_d["vol"] = vol
        dive_data_d["buoyancy"] = buoyancy
        dive_data_d["w_stdy"] = hdm_w_speed_cm_s_v
        dive_data_d["glide_angle_rad_stdy"] = hdm_glide_angle_rad_v
        dive_data_d["speed_stdy"] = hdm_speed_cm_s_v

    w_rms = w_rms_func_bad  # assume stalled everywhere
    w_rms_components = []
    num_pts = len(w)
    valid_i = Utils.setdiff(list(range(num_pts)), fv_stalled_i_v)
    valid_pts = float(len(valid_i))
    # TODO really we should record dive and climb profile numbers and ensure so fraction of both for each dive number are solved
    if hm_converged and valid_pts > 0 and valid_pts / num_pts > non_stalled_percent:

        def rms(x):
            return np.sqrt(np.nanmean(x**2))

        # compute rms of w (cm/s) over valid points
        w_rms = rms(w[valid_i] - hdm_w_speed_cm_s_v[valid_i])
        w_rms_components.append(w_rms)
        if (
            compare_velo and dive_data_d["n_velo"]
        ):  # there is velo data at all valid points?
            # the velocimeter is oriented along the axis of the vehicle but NOT along the glide angle
            # Adjust velo_speed by predicted attack angle
            # velo_speed_measured = velo_speed_true*cos(aoa), so velo_speed_true = velo_speed_measured/cos(aoa)
            # aoa is typicaly 2-3 degrees so 1/cos(aoa) ~ 1.0008 increase
            velo_speed = copy.copy(
                dive_data_d["velo_speed"]
            )  # don't update velo speed data
            if dive_data_d["correct_aoa_velo"]:
                aoa_radians_v = hdm_glide_angle_rad_v[valid_i] - np.radians(
                    pitch[valid_i]
                )
                velo_speed[valid_i] *= 1 / np.cos(aoa_radians_v)
            if compare_velo in (1, 3):
                # The velocometer operates like an ADCP with 3 sensors that integrate directional water speeds so no off axis issue
                v_rms = rms(velo_speed[valid_i] - hdm_speed_cm_s_v[valid_i])
                w_rms_components.append(v_rms)
                w_rms += v_rms
            if compare_velo in (2, 3):
                velo_w = velo_speed * np.sin(
                    hdm_glide_angle_rad_v
                )  # mixed model (glide angle) and data
                v_rms = rms(w[valid_i] - velo_w[valid_i])
                w_rms_components.append(v_rms)
                w_rms += v_rms
    HIST.append((vbdbias, a, b, abs_compress, w_rms))  # DEBUG
    if return_components:
        return w_rms, w_rms_components
    else:
        return w_rms


# A note on oil thermal-inertia below from past ideas.
# However we assume that getting volmax+vbdbias is good enough for flight matters.

# As the glider descends into typically colder water the oil in the
# reservoir and the bladder shrinks in volume. On the dive, this is
# apparent via the VBD pots moving without a commanded VBD move; the
# shrinkage looks like a pump; vice versa on the climb.  We can only
# measure the change using the VBD AD pots but in fact the oil
# outside in the bladder is also changing volume.  On the dive it
# appears that we pump according to VBD_cc but in fact there is no
# motion to the outside to change volume and the outside volume is
# shrinking so actually it really is like an additional 'bleed' in
# terms of vehicle dynamics.

#  We could account for the incorrectly stated VBD and actual oil
# shrinkage for buoyancy calculations using a thermal response model
# of the oil.  There is a thermal lag before the ocean temperature
# is transferred to the internal oil (empirically ~10m).
# Presummably the lag for the external oil is shorter (since the
# bladder is in direct contact with the ocean) but we use the same
# lag until we can measure that lag directly.


# Also there is thermal hysteresis between dives that we don't see,
# and which depends on how long the glider bathes in the warm water
# on the surface.  We assume that the temperature of the oil never
# exceeds the internal temperature reported by the compass at the
# end of the dive and apply it retroactively to the start of this
# dive.
def solve_vbdbias_abs_compress(base_opts, dive_data):
    """given a dive data instance, with updated a/b, sovle for this die's vbdbias (over prevailing volmax)
    and abs_compress"""
    global flight_dive_data_d, HIST, glider_type, max_w_rms_vbdbias
    if not dive_data.recompute_vbdbias_abs_compress:
        return True  # solved before and no reason to do it again
    dive_data_d = load_dive_data(base_opts, dive_data)
    if dive_data_d is None:
        return False
    # copy these to local variables so code below is succinct
    # TODO hd_a = predicted_hd_a etc.
    hd_a = dive_data.hd_a
    hd_b = dive_data.hd_b
    # this could have come from the mean abs_compress or the default or a previous computation
    abs_compress = dive_data.abs_compress

    # compute the dive's actual vbdbias and abs_compress using a constant a/b
    # perform linear coarse search, then fine search
    # TODO for vbdbias and abs_compress, call a bin_min_search(lambda,min,max) => (min_value,min_w_rms)
    min_w_rms_vbdbias = None
    min_w_rms = None

    # number of steps for linspace for coarse search
    coarse_step = 100  # PARAMETER divide the expected range into 100 (or fewer) steps
    # Unpack each time since we (USED TO) reset the variables for fine search
    vmin = flight_dive_data_d["vbdbias_min"]
    vmax = flight_dive_data_d["vbdbias_max"]

    vbdbias_increment = (vmax - vmin) / coarse_step
    # TODO after volmax estimate is stabilized, we don't expect volume (hence vbdbias) to change by
    # more than +/-200cc (and typically less that +/-40 unless biofouled)
    # so we could just skip the coarse search and use the fine-grained fminbound
    # TODO better would be to perform a binary search in spite of the large bound
    # see Jason's code in trunk/matlab/diveplot_func for bias_buoy
    # except he uses mean(w - w_stdy) vs. sqrt(sum((w-w_std)**2)/|w|)
    # what about nan values as well?  nan < 0 is false in matlab
    # on the other hand, he searches 20 times between -450 and 450 and this code searches
    # 20 times between -1000 and 1000 (2000/100) so no real time savings
    HIST = []
    for vbdbias in np.linspace(vmin, vmax, coarse_step + 1):
        w_rms = w_rms_func(base_opts, vbdbias, hd_a, hd_b, abs_compress, dive_data_d)
        # DEBUG print "%d %.2f" % (vbdbias,w_rms) # DEBUG (see HIST)
        if w_rms is not w_rms_func_bad:
            if min_w_rms is None or w_rms < min_w_rms:
                min_w_rms_vbdbias = vbdbias
                min_w_rms = w_rms

    if min_w_rms_vbdbias is not None:
        HIST = []
        # fine search
        # A NOTE on fminbound(): This function finds minimum locations that are just slightly different from matlab
        # so comparisons are difficult after this point.
        # But see the BUG in fminbound() outlined below!
        vmin = min_w_rms_vbdbias - 2 * vbdbias_increment
        vmax = min_w_rms_vbdbias + 2 * vbdbias_increment
        vbdbias = scipy.optimize.fminbound(
            lambda vbdbias: w_rms_func(
                base_opts, vbdbias, hd_a, hd_b, abs_compress, dive_data_d
            ),
            vmin,
            vmax,
            xtol=1,
        )  # 1cc tolerance
        min_w_rms_vbdbias = w_rms_func(
            base_opts, vbdbias, hd_a, hd_b, abs_compress, dive_data_d
        )
        if min_w_rms_vbdbias <= max_w_rms_vbdbias:
            dive_data.vbdbias = vbdbias
            dive_data.median_vbdbias = vbdbias  # updated below
            dive_data.w_rms_vbdbias = min_w_rms_vbdbias
        else:
            log_warning(
                "High w_rms for dive %d (%.2f cm/s)"
                % (dive_data.dive_num, min_w_rms_vbdbias)
            )
            min_w_rms_vbdbias = None

    if min_w_rms_vbdbias is None:
        # assume default??
        log_warning("Unable to determine vbdbias for dive %d" % dive_data.dive_num)
        return False  # unable to compute vbdbias! skip abs_compress calculation

    # Search for a good abs_compress for this dive and vehicle
    # However Oculus vehicles have a VBD system that changes volume under pressure so looks extremely squishy
    # so just stick with the assumed constant for that type
    if glider_type is not OCULUS:  #  and dive_data.bottom_press >= ac_min_press:
        # The per-dive abs_compress value is never used directly but contributes to the ongoing mean value for deep dives below

        # sadly there is a bug in fminbound such that if there is no gradient (e.g., all the results are w_rms_func_bad)
        # then it searches in one direction and avoids values at below ac_min + .38*(ac_max - ac_min), where it might be good
        # /Users/jsb/Seaglider/TestData/DAC_pairs/DG037_Abaco_040717/subset/p0370040, etc.
        # So we must implement a coarse search like vbd above and then use fminbound where there is a gradient
        ac_min = flight_dive_data_d["ac_min"]
        ac_max = flight_dive_data_d["ac_max"]
        ac_increment = (ac_max - ac_min) / coarse_step
        HIST = []
        min_w_rms_ac = None
        min_w_rms = None
        for ac in np.linspace(ac_min, ac_max, coarse_step + 1):
            w_rms = w_rms_func(base_opts, vbdbias, hd_a, hd_b, ac, dive_data_d)
            if w_rms is not w_rms_func_bad:
                if min_w_rms is None or w_rms < min_w_rms:
                    min_w_rms_ac = ac
                    min_w_rms = w_rms

        if min_w_rms_ac is not None:
            HIST = []
            ac_min = min_w_rms_ac - 2 * ac_increment
            ac_max = min_w_rms_ac + 2 * ac_increment
            abs_compress = scipy.optimize.fminbound(
                lambda ac: w_rms_func(base_opts, vbdbias, hd_a, hd_b, ac, dive_data_d),
                ac_min,
                ac_max,
                xtol=ac_increment / 10,
            )
    dive_data.abs_compress = abs_compress  # default or updated
    min_w_rms_abs_compress = w_rms_func(
        base_opts, vbdbias, hd_a, hd_b, abs_compress, dive_data_d
    )
    dive_data.w_rms_vbdbias = (
        min_w_rms_abs_compress  # reflect min of both vbdbias and abs_compress
    )
    dive_data.recompute_vbdbias_abs_compress = False  # done for this a/b combination
    return True


def solve_ab_grid(base_opts, dive_set, reprocess_count, dive_num=None):
    """returns the w_rms grid for a set of dives and the min a/b"""
    # CONSIDER: for speed, pass tared prior W_misfit_RMS array, if any, and restrict search
    # to prior values of .3 or so
    global HIST, flight_dive_data_d, dive_data_vector_names, hd_a_grid, hd_b_grid
    HIST = []
    if dive_num is None:
        dive_num = max(dive_set)
    abs_compress = np.array([], np.float64)
    # combine the data from the dives in the dive_set
    combined_data_d = {}
    for vector_name in dive_data_vector_names:
        combined_data_d[vector_name] = []
    n_velo = True
    correct_aoa_velo = False
    for dive_set_num in dive_set:
        dd = flight_dive_data_d[dive_set_num]
        # NOTE we used to cache this data in a dive_cache_d but not really worth it?
        dive_data_d = load_dive_data(base_opts, dd)  # load data
        if dd.dive_data_ok is False:
            log_error(
                "Dive %d is marked as not okay - skipping grid solution!"
                % dive_set_num,
                alert="FM_GRID_SOLUTION",
            )
            return (None, None, None)
        if not dive_data_d:
            log_error(
                "Failed to load dive %d data - skipping grid solution!" % dive_set_num,
                alert="FM Grid Solution",
            )
            return (None, None, None)
        if compare_velo and not dive_data_d["n_velo"]:
            n_velo = False  # a dive is missing velo points
            correct_aoa_velo = dive_data_d["correct_aoa_velo"]
        abs_compress = np.concatenate(
            (abs_compress, dd.abs_compress * np.ones(dd.n_valid))
        )
        for vector_name in dive_data_vector_names:
            data_vector = copy.copy(dive_data_d[vector_name])
            if vector_name == "displaced_volume":
                data_vector -= (
                    dd.vbdbias
                )  # apply per-dive vbdbias to copy so any cache is not poisoned
            combined_data_d[vector_name].extend(data_vector)
    combined_data_d[
        "n_velo"
    ] = n_velo  # A boolean about whether velo data is available for all valid points for all dives
    combined_data_d[
        "correct_aoa_velo"
    ] = correct_aoa_velo  # A boolean about whether velo data needs aoa correction for all dives

    # convert to numpy arrays
    for vector_name in dive_data_vector_names:
        combined_data_d[vector_name] = np.array(combined_data_d[vector_name])

    na = len(hd_a_grid)
    nb = len(hd_b_grid)
    start_time = time.time()
    W_misfit_RMS = np.zeros((nb, na), np.float64)
    min_w_rms = 1000  # w_rms_func_bad
    min_ia = 0
    min_ib = 0
    for grid_a, ia in zip(hd_a_grid, list(range(na))):
        for grid_b, ib in zip(hd_b_grid, list(range(nb))):
            # explicitly zero vbdbias since the dive-by-dive vbdbias has already been applied to combined_data_d
            w_rms = w_rms_func(
                base_opts, 0, grid_a, grid_b, abs_compress, combined_data_d
            )
            W_misfit_RMS[ib, ia] = w_rms
            if w_rms is not w_rms_func_bad and w_rms < min_w_rms:
                min_w_rms = w_rms
                min_ia = ia
                min_ib = ib
    end_time = time.time()
    # log_debug
    log_info(
        "%d n=%d/%s %.fs hd_a=%6.5f(%d) hd_b=%6.5f(%d) %f"
        % (
            dive_num,
            len(combined_data_d["w"]),
            n_velo,
            end_time - start_time,
            hd_a_grid[min_ia],
            min_ia,
            hd_b_grid[min_ib],
            min_ib,
            W_misfit_RMS[min_ib, min_ia],
        )
    )
    if dump_checkpoint_data_matfiles:
        global flight_directory
        # solve this at the min location to update any saved buoyancy/w_stdy/etc. in combined_data_d
        w_rms = w_rms_func(
            base_opts,
            0,
            hd_a_grid[min_ia],
            hd_b_grid[min_ib],
            abs_compress,
            combined_data_d,
        )
        mat_d = {}
        mat_d["dive_num"] = dive_num
        mat_d["dive_set"] = np.array(dive_set)
        mat_d["abs_compress"] = abs_compress
        mat_d["min_ia"] = min_ia
        mat_d["min_ib"] = min_ib
        mat_d["hd_a_grid"] = hd_a_grid
        mat_d["hd_b_grid"] = hd_b_grid
        mat_d["W_misfit_RMS"] = W_misfit_RMS
        mat_d["w_rms"] = w_rms
        mat_filename = os.path.join(
            flight_directory, "solve_ab_%04d_%d" % (dive_num, reprocess_count)
        )
        sio.savemat(
            mat_filename,
            {
                "solve_ab": mat_d,
                "combined_data": combined_data_d,
                "flight_consts": flight_consts_d,
            },
        )

    return W_misfit_RMS, min_ia, min_ib


# Support for DAC variance reports
# Different from load_dive_data() above: no update the dive_data, no valid_i calculation, etc
# We want all of the dive data so we can compute full displacements, etc.
def load_dive_data_DAC(base_opts, dive_data):
    global nc_path_format
    data_d = None
    if dive_data.dive_data_ok is False:
        # tried this before and it failed
        return data_d
    # So far so good
    dive_num = dive_data.dive_num
    dive_nc_file_name = nc_path_format % dive_num
    try:
        dive_nc_file = Utils.open_netcdf_file(dive_nc_file_name, "r")
    except:
        log_error(f"Unable to open {dive_nc_file_name}", "exc")
        return data_d
    try:
        basestation_v = getattr(
            dive_nc_file, "base_station_version", "2.11"
        )  # Assume it is old if missing
        if Utils.normalize_version(basestation_v) < Utils.normalize_version("2.12"):
            # We started to save displacements, etc. only with 2.12
            # be silent about this particular problem
            # Since we can reprocess files this file could be brought up to more recent level
            raise RuntimeError

        start_time = dive_data.start_time
        # SG eng time base
        eng_time = dive_nc_file.variables["time"][:] - start_time
        ctd_time = dive_nc_file.variables["ctd_time"][:] - start_time
        eng_pitch_ang = dive_nc_file.variables["eng_pitchAng"][:]
        eng_vbd_cc = dive_nc_file.variables["eng_vbdCC"][:]
        press = dive_nc_file.variables["pressure"][:]
        if len(ctd_time) != len(eng_time):
            # interpolate pitch/roll/vbd/press/depth to ctd_time
            eng_pitch_ang = Utils.interp1d(
                eng_time, eng_pitch_ang, ctd_time, kind="linear"
            )
            eng_vbd_cc = Utils.interp1d(eng_time, eng_vbd_cc, ctd_time, kind="linear")
            press = Utils.interp1d(eng_time, press, ctd_time, kind="linear")

        depth = dive_nc_file.variables["ctd_depth"][:]
        w = Utils.ctr_1st_diff(
            -depth * cm_per_m, ctd_time
        )  # compute_buoyancy() looks for this to return

        temperature_raw = dive_nc_file.variables["temperature_raw"][:]
        salinity_raw = dive_nc_file.variables["salinity_raw"][:]
        if not base_opts.use_gsw:
            density_insitu = seawater.dens(salinity_raw, temperature_raw, press)
            density = seawater.pden(salinity_raw, temperature_raw, press, 0)
        else:
            density_insitu = Utils.density(
                salinity_raw,
                temperature_raw,
                press,
                dive_nc_file.variables["avg_longitude"].getValue(),
                dive_nc_file.variables["avg_latitude"].getValue(),
            )
            density = Utils.pdensity(
                salinity_raw,
                temperature_raw,
                press,
                dive_nc_file.variables["avg_longitude"].getValue(),
                dive_nc_file.variables["avg_latitude"].getValue(),
            )

        # use the values in the log file, not the pilot's fiction in sg_calib_constants.h
        # this is what the glider used
        vbd_min_cnts = dive_nc_file.variables["log_VBD_MIN"].getValue()
        vbd_cnts_per_cc = 1.0 / dive_nc_file.variables["log_VBD_CNV"].getValue()
        c_vbd = dive_nc_file.variables["log_C_VBD"].getValue()
        vbd_neutral = (c_vbd - vbd_min_cnts) / vbd_cnts_per_cc

        data_d = {}  # we are returning data
        # if we can get these values then it means GPS, etc, was ok
        # if we can't then either DAC_qc was BAD, etc. OR it was processed on an old basestation that doesn't emit these guys
        # TODO alternatively we could probe to see if these are not present and recompute them
        # in which case, separate the code in MDP from inline to a function so both can call
        data_d["delta_time_s"] = dive_nc_file.variables["delta_time_s"][:]
        data_d["polar_heading"] = dive_nc_file.variables["polar_heading"][:]
        data_d["GPS_east_displacement_m"] = dive_nc_file.variables[
            "GPS_east_displacement_m"
        ].getValue()
        data_d["GPS_north_displacement_m"] = dive_nc_file.variables[
            "GPS_north_displacement_m"
        ].getValue()
        data_d["total_flight_time_s"] = dive_nc_file.variables[
            "total_flight_time_s"
        ].getValue()

        data_d["pitch"] = eng_pitch_ang
        data_d["w"] = w  # what we optimize against
        data_d["pressure"] = press  # for compression and compressee
        data_d[
            "temperature"
        ] = temperature_raw  # for compressee and hull thermal expansion
        data_d["density_insitu"] = density_insitu  # for buoyancy calculations (kg/m^3)
        data_d["density"] = density  # for buoyancy calculations (kg/m^3)

        volmax = flight_dive_data_d["volmax"]  # assume this is already calculated
        vbd0 = volmax + vbd_neutral  # [cc] volume when at neutral
        # deliberately no vbdbias here!! see calls to w_rms_func() and updates in solve_ab_grid()
        displaced_volume = (
            vbd0 + eng_vbd_cc
        )  # [cc] measured displaced volume of glider as it varies by VBD adjustments
        data_d["displaced_volume"] = displaced_volume  # for buoyancy calculations

    except KeyError:
        log_error("Could not get required DAC data for dive %d" % dive_num)
        data_d = None
    except RuntimeError:
        data_d = None  # error or warning issued above
    dive_nc_file.close()
    return data_d


# Call this after a call to solve_ab_grid()
# pass (tared) W_misfit_RMS and min_ia,min_ib, dd and dive_data_d
# call only of dd.DAC_ok is True
# Note that the DAC exploration does NOT make use of the velo data or compare_velo
# we assume the min_ia, min_ib reflects that if engaged
def solve_ab_DAC(base_opts, dive_num, W_misfit_RMS, min_ia, min_ib, min_misfit):
    global hd_a_grid, hd_b_grid
    global \
        generate_figures, \
        font, \
        HD_A, \
        HD_B, \
        w_misfit_rms_levels, \
        glider_mission_string

    dd = flight_dive_data_d[dive_num]
    dive_data_d = load_dive_data_DAC(base_opts, dd)
    if dive_data_d is None:
        return False  # no good for DAC calcs
    vbdbias = dd.vbdbias
    abs_compress = dd.abs_compress  # else use mean?
    # do this once...
    buoyancy, pitch, w, vol = compute_buoyancy(
        base_opts, vbdbias, abs_compress, dive_data_d
    )

    # load_dive_data_DAC() ensures these are present
    ctd_delta_time_s_v = dive_data_d["delta_time_s"]
    head_polar_rad_v = dive_data_d["polar_heading"]
    dive_delta_GPS_lat_m = dive_data_d["GPS_north_displacement_m"]
    dive_delta_GPS_lon_m = dive_data_d["GPS_east_displacement_m"]
    total_flight_and_SM_time_s = dive_data_d["total_flight_time_s"]

    na = len(hd_a_grid)
    nb = len(hd_b_grid)
    DAC_u = np.zeros((nb, na), np.float64)  # east
    DAC_v = np.zeros((nb, na), np.float64)  # north
    # Assume the worst
    DAC_u[:, :] = np.nan
    DAC_v[:, :] = np.nan

    start_time = time.time()
    for grid_a, ia in zip(hd_a_grid, list(range(na))):
        for grid_b, ib in zip(hd_b_grid, list(range(nb))):
            flight_consts_d["hd_a"] = grid_a
            flight_consts_d["hd_b"] = grid_b
            (
                hm_converged,
                hdm_speed_cm_s_v,
                hdm_glide_angle_rad_v,
                fv_stalled_i_v,
            ) = hydro_model(buoyancy, pitch, flight_consts_d)
            if not hm_converged:
                pass  # ignore ... this is the best we can do
            hdm_horizontal_speed_cm_s_v = hdm_speed_cm_s_v * np.cos(
                hdm_glide_angle_rad_v
            )
            (
                hdm_east_displacement_m_v,
                hdm_north_displacement_m_v,
                hdm_east_displacement_m,
                hdm_north_displacement_m,
                hdm_east_average_speed_m_s,
                hdm_north_average_speed_m_s,
            ) = MakeDiveProfiles.compute_displacements(
                "FM",
                hdm_horizontal_speed_cm_s_v,
                ctd_delta_time_s_v,
                total_flight_and_SM_time_s,
                head_polar_rad_v,
            )
            (
                hdm_dac_east_speed_m_s,
                hdm_dac_north_speed_m_s,
            ) = MakeDiveProfiles.compute_dac(
                hdm_north_displacement_m_v,
                hdm_east_displacement_m_v,
                hdm_north_displacement_m,
                hdm_east_displacement_m,
                dive_delta_GPS_lat_m,
                dive_delta_GPS_lon_m,
                total_flight_and_SM_time_s,
            )
            DAC_u[ib, ia] = hdm_dac_east_speed_m_s
            DAC_v[ib, ia] = hdm_dac_north_speed_m_s

    end_time = time.time()
    log_debug("%d: DAC grid time %.1fs" % (dive_num, end_time - start_time))  # DEBUG

    DACum = DAC_u[min_ib, min_ia]
    DACvm = DAC_v[min_ib, min_ia]
    DACmm = np.sqrt(DACum**2 + DACvm**2)  # DAC magnitude of minimum a/b

    # now subtract the min's east and north to get DAC residuals
    DAC_u[:, :] = DAC_u[:, :] - DACum  # assume DAC at min w_rms is correct
    DAC_v[:, :] = DAC_v[:, :] - DACvm  # assume DAC at min w_rms is correct
    # compute DAC residual magnitudes
    DACm = np.sqrt(DAC_u[:, :] ** 2 + DAC_v[:, :] ** 2)

    # TODO map over various ab_tolerances of w_rms and compute the nanmean/nanmax DACm differences (min will always be zero)
    # this will tell us, over a large number of dives, what ab_tolerances yield, on average, what DAC variances
    # which will tell us, for that empirical thresold, for each W_misfit_RMS how 'ambiguous' an a/b grid solution is
    # that is, how many 'equivalent' a/b solutions will yield an acceptable DAC

    # This should always True given the calling sequence
    if generate_figures:
        hd_a_c = hd_a_grid[min_ia]
        hd_b_c = hd_b_grid[min_ib]

        # Display DAC differences in terms of factors (ratios) of the min a/b
        # that is, if, say, b were 2x what would be the *change* in DAC over the minimum
        # this is not the same as whether the DAC at minimum w_rms is accurate!
        pHD_A = HD_A / hd_a_c
        pHD_B = HD_B / hd_b_c

        timelabel = (
            "%s\n"
            r"${vol}_{max}$=%.0f"
            "\nc = %.4g; s = %.4g;\n"
            r"$\kappa$ = %.4g; $\alpha$ = %.4g;"
            "\nl = %.4g; press=%d/%d"
        )
        timelabel = timelabel % (
            time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time())),
            flight_dive_data_d["volmax"],
            flight_consts_d["hd_c"],
            flight_consts_d["hd_s"],
            flight_dive_data_d["abs_compress"],
            flight_consts_d["therm_expan"],
            flight_consts_d["glider_length"],
            pressmin,
            pressmax,
        )
        mass_comp = flight_consts_d["mass_comp"]
        if mass_comp:
            timelabel += r"; ${mass}_{comp}$ = %.2fkg" % mass_comp

        plt.xlabel("Lift (a) ratio to best")
        plt.ylabel("Drag (b) ratio to best")
        titlestring = (
            "%s\nDive %d " + r"${w}_{rms}=%.2fcm/s$" "(%d) a=%.6g b=%.6g %.2fcm/s"
        )
        titlestring = titlestring % (
            glider_mission_string,
            dive_num,
            min_misfit,
            compare_velo,
            hd_a_c,
            hd_b_c,
            DACmm * cm_per_m,
        )
        plt.suptitle(titlestring)
        plt.figtext(0.08, 0.02, timelabel, fontproperties=font)  # was 0.4 for y

        # Show ratios between 1/2x and 1.5x of min a/b
        plt.xlim(xmin=0.5, xmax=1.5)
        plt.ylim(ymin=0.5, ymax=1.5)
        # eliminate very large DAC values so the quiver values scale nicely
        DAC_limit = 7  # PARAMETER cm/s
        DAC_limit_cm_s = DAC_limit / cm_per_m
        too_big_i = np.where(DACm > DAC_limit_cm_s)
        DAC_u[too_big_i[0], too_big_i[1]] = np.nan
        DAC_v[too_big_i[0], too_big_i[1]] = np.nan
        p_q = plt.quiver(
            pHD_A, pHD_B, DAC_u, DAC_v, color="b", angles="xy"
        )  # angles='uv'?
        plt.quiverkey(
            p_q,
            0.9,
            0.9,
            DAC_limit_cm_s,
            "%d cm/s" % DAC_limit,
            labelpos="E",
            fontproperties={"size": "xx-small"},
        )

        Cd = plt.contour(
            pHD_A,
            pHD_B,
            DACm * cm_per_m,
            np.array([0, 0.005, 0.01, 0.02, 0.03, 0.04]) * cm_per_m,
            colors="c",
            linewidths=1.0,
            linestyles="solid",
        )
        plt.clabel(
            Cd, inline=True, inline_spacing=-1, fontsize=9, fmt="%2.1f", colors="c"
        )
        dacm_h, _ = Cd.legend_elements()

        Cd = plt.contour(
            pHD_A,
            pHD_B,
            W_misfit_RMS,
            w_misfit_rms_levels,
            colors="m",
            linewidths=1.0,
            linestyles="solid",
        )
        plt.clabel(
            Cd, inline=True, inline_spacing=-1, fontsize=9, fmt="%2.1f", colors="m"
        )
        wrms_h, _ = Cd.legend_elements()

        (p_b,) = plt.plot(
            hd_a_c / hd_a_c, hd_b_c / hd_b_c, "g*", markersize=fig_markersize
        )  # 1,1

        lg = plt.legend(
            [dacm_h[0], wrms_h[0], p_b],
            [
                "DAC difference magnitude (cm/s)",
                r"${w}_{rms}$ difference from min (cm/s)",
                r"Best fit ${w}_{rms}$",
            ],
            loc="upper right",
            fancybox=True,
            prop=font,
            numpoints=1,
        )
        lg.get_frame().set_alpha(0.5)
        write_figure("dv%04d_DAC.webp" % dive_num)
        plt.clf()
    return True


# If dive_num was used in any grid search, flush those entries so those grids are recomputed
def flush_ab_grid_cache(dive_num, ab_grid_cache_d):
    for ab_grid_cache_dive, cache_entry in list(ab_grid_cache_d.items()):
        # If this is not a reprocessed dive then we need only flush cached results that involve the dive
        W_misfit_RMS, ia, ib, min_misfit, prev_dive_set, prev_pitch_d_diff = cache_entry
        if dive_num in prev_dive_set:
            del ab_grid_cache_d[ab_grid_cache_dive]
            write_figure("dv%04d_ab.webp" % ab_grid_cache_dive, delete=True)


def update_restart_cache(
    dive_num,
    mr_dives_pitches,
    mr_index,
    mr_n_inserted,
    last_W_misfit_RMS_dive_num,
    last_ab_committed_dive_num,
    predicted_hd_a,
    predicted_hd_b,
    predicted_hd_ab_trusted,
):
    global restart_cache_d
    mr_dives_pitches = np.array(
        mr_dives_pitches, copy=True
    )  # ensure we have a copy so we don't see subsequent updates
    restart_cache_d[dive_num] = (
        mr_dives_pitches,
        mr_index,
        mr_n_inserted,
        last_W_misfit_RMS_dive_num,
        last_ab_committed_dive_num,
        predicted_hd_a,
        predicted_hd_b,
        predicted_hd_ab_trusted,
    )


# static globals for generate_figures
font = None
HD_A = None
HD_B = None
w_misfit_rms_levels = None
prev_w_misfit_rms_levels = None
glider_mission_string = None


# Process a (possible) single new dive into the flight data base
# and update any existing dives in the flight data base if they have (or come to have) time stamp entries in updated_dives_d
# tne new dive must have an entry in updated_dives_d
# WARNING: In the following there is a main loop that maps over *all* known dives
# the local variable dive_num MUST be maintained as the prevailing dive number
# if you loop over other dives use d_n as the iterator variable
def process_dive(
    base_opts,
    new_dive_num,
    updated_dives_d,
    nc_files_created,
    alert_dive_num=None,
    exit_event=None,
):
    global \
        flight_dive_data_d, \
        flight_directory, \
        mission_directory, \
        nc_path_format, \
        flight_consts_d, \
        angles, \
        HIST, \
        generate_dac_figures
    global \
        glider_type, \
        compare_velo, \
        acceptable_w_rms, \
        flight_dive_nums, \
        hd_a_grid, \
        hd_b_grid, \
        ab_grid_cache_d, \
        restart_cache_d
    global \
        font, \
        HD_A, \
        HD_B, \
        w_misfit_rms_levels, \
        prev_w_misfit_rms_levels, \
        glider_mission_string, \
        generate_figures, \
        show_implied_c_vbd

    # unpack some operational constants
    ac_min_press = flight_dive_data_d["ac_min_press"]
    mass_comp = flight_dive_data_d["mass_comp"]

    if generate_figures and font is None:
        # compute these variables once
        font = FontProperties(size="x-small")
        (HD_A, HD_B) = np.meshgrid(hd_a_grid, hd_b_grid)
        w_misfit_rms_levels = ab_tolerance * np.array(
            [1.0, 2.0, 3.0, 4.0]
        )  # reduce clutter
        prev_w_misfit_rms_levels = [ab_tolerance]  # the previous good level
        glider_mission_string = "%s%03d %s" % (
            flight_dive_data_d["glider_type_string"],
            flight_dive_data_d["glider"],
            flight_dive_data_d["mission_title"],
        )

    log_info(f"Started FM cycle {new_dive_num}")
    if False:  # DEBUG
        log_info(
            "memory: fdd=%d restart=%d, grid=%d"
            % (
                deep_getsizeof(flight_dive_data_d, set()),
                deep_getsizeof(restart_cache_d, set()),
                deep_getsizeof(ab_grid_cache_d, set()),
            )
        )

    dives_reprocessed = True  # force one loop
    reprocess_count = 0
    alerts = ""
    aflight_dive_nums = np.array(
        flight_dive_nums
    )  # for use by where, etc for this call

    if new_dive_num is not None:
        # Verify we really haven't seen it and we have the time data we need
        if new_dive_num in flight_dive_nums or new_dive_num not in list(
            updated_dives_d.keys()
        ):
            log_error("HOW CAN THIS BE?")
            return 1
        dive_data = flight_data(new_dive_num)
        abs_compress = flight_dive_data_d[
            "abs_compress"
        ]  # assume prevailing (default or mean) value
        if len(flight_dive_nums):
            # Need to find the dive just before new_dive_num in case of out of order dives
            d_n_i = np.where(aflight_dive_nums < new_dive_num)[0]
            restart_from_dive_num = flight_dive_nums[d_n_i[-1]]
            # restore predicted ab and trust from restart_from_dive_num
            log_debug(restart_cache_d.keys())
            if restart_from_dive_num in restart_cache_d.keys():
                (
                    mr_dives_pitches,
                    mr_index,
                    mr_n_inserted,
                    last_W_misfit_RMS_dive_num,
                    last_ab_committed_dive_num,
                    predicted_hd_a,
                    predicted_hd_b,
                    predicted_hd_ab_trusted,
                ) = restart_cache_d[restart_from_dive_num]
            else:
                log_error(
                    "Internal error - dive %d not in restart_cache_d - skipping FM"
                    % restart_from_dive_num
                )
                return 1
        else:
            # No dives yet so start with the defaults on this initial dive
            restart_from_dive_num = 0  # for debug below
            predicted_hd_a = flight_dive_data_d["hd_a"]
            predicted_hd_b = flight_dive_data_d["hd_b"]
            predicted_hd_ab_trusted = flight_dive_data_d["hd_ab_trusted"]

        log_info(
            "New dive %d restarting from dive %d (%g,%g)"
            % (new_dive_num, restart_from_dive_num, predicted_hd_a, predicted_hd_b)
        )  # DEBUG
        # The nc_ values are set/updated below when we call load_dive_data() and we read the data from the nc file
        dive_data.hd_a = predicted_hd_a
        dive_data.hd_b = predicted_hd_b
        dive_data.hd_ab_trusted = predicted_hd_ab_trusted
        # DEBUG log_info('pd new: %d %g %g' % (dive_data.dive_num, dive_data.hd_a,dive_data.hd_b)) # DEBUG
        dive_data.volmax = flight_dive_data_d["volmax"]
        dive_data.vbdbias = np.nan
        dive_data.abs_compress = abs_compress

        # Add to the database and to the list of dive numbers
        flight_dive_data_d[new_dive_num] = dive_data
        flight_dive_nums.append(new_dive_num)
        flight_dive_nums.sort()  # in place update
        # log_info("updated flight_dive_nums:%s" % flight_dive_nums)
        aflight_dive_nums = np.array(
            flight_dive_nums
        )  # update aflight_dive_nums for this call (append not seen by array)
    else:
        if len(flight_dive_nums) == 0:
            # No dives seen and no new dives?  Nothing to do!!
            return 1

    # determine the list of (updated) dives we are going to deal with on this
    # call, including any new_dive_num, within flight_dive_nums find the first
    # and last updated_dive in the list and map over all those dives inclusive
    # after loading cached flight parameter values of running vars associated
    # with the dive, if any, just before the first updated dive

    while dives_reprocessed:
        reprocess_count += 1
        if (
            reprocess_count > 6
        ):  # HACK in case we don't get the termination conditions stable
            log_error("Potential infinite loop?")
            # map over any dives in flight_dive_nums that have an entry in updated_dives_d
            # and update their updated time and remove from updated without processing
            # DO NOT MAP over updated_dives_d.keys() because there will be 'future' dives we haven't processed yet and so not in flight_dive_nums
            for dive_num in flight_dive_nums:
                try:
                    dive_nc_file_time = updated_dives_d[dive_num]
                    del updated_dives_d[dive_num]
                    dive_data = flight_dive_data_d[dive_num]
                    dive_data.last_updated = dive_nc_file_time
                    load_dive_data(
                        base_opts, dive_data
                    )  # update our db object with current values from updated nc file by side effect
                except KeyError:
                    pass
            save_flight_database(
                base_opts
            )  # record this issue and updated filetimes in history
            return 1

        log_debug(
            "Started FM processing %d at %s"
            % (
                reprocess_count,
                time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())),
            )
        )

        log_debug(f"updated_dives:{updated_dives_d.keys()}")
        log_debug(f"flight_dive_nums:{flight_dive_nums}")
        dives_to_update = sorted(
            np.intersect1d(list(updated_dives_d.keys()), flight_dive_nums)
        )
        dives_to_update.sort()  # ensure in order
        log_info(f"dives_to_update:{dives_to_update}")
        if not dives_to_update:
            log_error("No dives_to_update - bailing out of process_dive")
            return 1
        first_dive_to_update = dives_to_update[0]
        d_n_i = np.where(aflight_dive_nums < first_dive_to_update)[0]
        if len(d_n_i):  # there was a dive before the earliest dive to update
            restart_from_dive_num = flight_dive_nums[d_n_i[-1]]
            # restore from restart_from_dive_num
            (
                mr_dives_pitches,
                mr_index,
                mr_n_inserted,
                last_W_misfit_RMS_dive_num,
                last_ab_committed_dive_num,
                predicted_hd_a,
                predicted_hd_b,
                predicted_hd_ab_trusted,
            ) = restart_cache_d[restart_from_dive_num]
            # CRITICAL to copy since we want to preserve the stored version (until updated)
            # and because we want to update this copy as we go
            mr_dives_pitches = np.array(mr_dives_pitches, copy=True)

            # restore W_misfit_RMS (ignore the rest)
            try:
                (
                    last_W_misfit_RMS,
                    ia,
                    ib,
                    min_misfit,
                    prev_dive_set,
                    prev_pitch_diff,
                ) = ab_grid_cache_d[last_W_misfit_RMS_dive_num]
            except KeyError:
                last_W_misfit_RMS = None  # ensure
            d_n_i = np.where(aflight_dive_nums >= first_dive_to_update)[0]
            update_flight_dive_nums = aflight_dive_nums[d_n_i]
        else:
            # start from scratch
            # Initialize ring buffer that tracks the min and max pitches of the trailing n_dives_grid_spacing dives
            # ensure it is as large as the largest stride possible
            n_dives_grid_spacing = max(grid_spacing_d.values())
            mr_dives_pitches = np.zeros(
                (n_dives_grid_spacing, 3), int
            )  # dive numbers and min/max pitches are integers
            mr_dives_pitches[:, 1] = 90  # min
            # mr_dives_pitches[:,2] =  0 # max
            mr_index = 0  # where to insert the next dive
            mr_n_inserted = 0  # how many dives inserted since last ab grid computation

            last_W_misfit_RMS = None
            last_W_misfit_RMS_dive_num = (
                0  # the dive_set id associated with our current (last_)W_misfit_RMS
            )
            last_ab_committed_dive_num = (
                0  # the dive_set id through which we have committed to an ab pair
            )
            if len(flight_dive_nums):
                last_ab_committed_dive_num = flight_dive_nums[0] - 1

            predicted_hd_a = flight_dive_data_d["hd_a"]
            predicted_hd_b = flight_dive_data_d["hd_b"]
            predicted_hd_ab_trusted = flight_dive_data_d["hd_ab_trusted"]
            update_flight_dive_nums = flight_dive_nums
            update_restart_cache(
                new_dive_num,
                mr_dives_pitches,
                mr_index,
                mr_n_inserted,
                last_W_misfit_RMS_dive_num,
                last_ab_committed_dive_num,
                predicted_hd_a,
                predicted_hd_b,
                predicted_hd_ab_trusted,
            )

        # We will map over all the available dives (again) and update their values
        reprocess_dives = []  # what dives should be reprocessed this round
        dives_reprocessed = (
            False  # assume we are done after this loop (no further reprocessing needed)
        )
        alerts = ""  # reset

        # BREAK -- this is the main processing loop
        # We process in order from the currently earliest updated dive
        # (which is typically the most recent but not always, esepcially after we reprocess dives)
        # we have restored the search state from restart_cache from the die just before the first updated dive
        for dive_num in update_flight_dive_nums:
            if exit_event and exit_event.is_set():
                log_info("Exit requested")
                break

            dive_data = flight_dive_data_d[dive_num]

            bx_keys = [k for k in grid_spacing_keys if k <= dive_num]
            n_dives_grid_spacing = grid_spacing_d[bx_keys[-1]]
            log_debug(
                "%d grid_spacing %d" % (dive_num, n_dives_grid_spacing)
            )  # DEBUG report change of grid_spacing stride

            # checkpoint restart cache in case the dive is no good somehow: data not ok, unable to find vbdbias, pitch_d is too large, etc.
            update_restart_cache(
                dive_num,
                mr_dives_pitches,
                mr_index,
                mr_n_inserted,
                last_W_misfit_RMS_dive_num,
                last_ab_committed_dive_num,
                predicted_hd_a,
                predicted_hd_b,
                predicted_hd_ab_trusted,
            )

            try:
                dive_nc_file_time = updated_dives_d[dive_num]
                # If we get here dive_num's data needs updating

                del updated_dives_d[dive_num]  # We are taking care of this updated dive
                dive_data.last_updated = dive_nc_file_time
                if (
                    dive_data.recompute_vbdbias_abs_compress
                    and dive_data.dive_data_ok is False
                ):
                    dive_data.dive_data_ok = (
                        None  # could be ok now (None marks unknown)
                    )

                if not solve_vbdbias_abs_compress(base_opts, dive_data):
                    continue  # unable to solve so don't add

                # We make an initial estimate of volmax from the 'first' dive's bottom density and mass
                # but this is likely off by perhaps 100s of ccs.  So we collect an early set of dives
                # after the 'first' dive and make a 2nd estimate that attempts to move vbdbias values close to zero
                # NOTE: this is for plotting convenience only...it really makes no difference to the estimates of w the way we do it.
                # We could avoid this (and the reprocessing it typically implies) without loss of accuracy.
                if not flight_dive_data_d.get(
                    "final_volmax_found", False
                ):  # use get in case we access old dbs
                    early_vbdbias = []
                    early_vbdbias_d_n = []
                    for d_n in flight_dive_nums:
                        if d_n == 1:
                            # Skip the actual first dive to take care of bubbles and compressee adjustment for DG
                            continue
                        try:
                            dd = flight_dive_data_d[d_n]
                            # TODO - consider additional criteria
                            # and ~np.isnan(dd.bottom_press) and dd.bottom_press > 90.0:
                            if ~np.isnan(dd.vbdbias):
                                early_vbdbias.append(dd.vbdbias)
                        except KeyError:
                            pass  # not done yet or missing
                        else:
                            early_vbdbias_d_n.append(d_n)
                    if len(early_vbdbias) >= early_volmax_adjust:  # sufficient dives?
                        early_vbdbias = np.mean(early_vbdbias)
                        flight_dive_data_d["volmax"] -= early_vbdbias
                        new_volmax = flight_dive_data_d["volmax"]
                        log_info(
                            "Final volmax estimate: %.0fcc from dives %s (adjusting previous dives by %.2fcc)"
                            % (new_volmax, early_vbdbias_d_n, -early_vbdbias)
                        )
                        # Adjust all existing volmax and vbdbias values wrt the new assumed volmax
                        # Below we will see that both values changed from the nc files and force reprocessing
                        avg_volmax = []
                        for d_n in flight_dive_nums:
                            dd = flight_dive_data_d[d_n]
                            if ~np.isnan(dd.vbdbias):
                                dd.vbdbias -= early_vbdbias
                                dd.volmax = new_volmax
                                avg_volmax.append(dd.volmax - dd.vbdbias)
                                dump_fm_values(dd)
                                data_d = load_dive_data(base_opts, dd)
                                if data_d is not None:
                                    # Update the C_VBD over the first few dives, latching the final version
                                    flight_dive_data_d["C_VBD"] = data_d["C_VBD"]
                                    flight_dive_data_d["VBD_CNV"] = data_d["VBD_CNV"]
                        flight_dive_data_d["final_volmax_found"] = True
                        log_info(
                            f"New avg volmax (bias included) {np.nanmean(avg_volmax):.2f}"
                        )
                    else:
                        log_info(f"Early bias dives so far {early_vbdbias_d_n}")

                log_info(f"{dive_data}")
                dump_fm_values(dive_data)
                # Here we compute an aggregate mean abs_compress
                # The value will depend on how many individual samples we include
                # If you run an entire deployment in one batch you will get them all
                # if you do it incrementally you should converge on that same number.
                # But you don't, by a little bit, because in the incremental case
                # the vbdbiases are recomputed with incremental abs_compress values
                # and the threshold for recomputation prohibits getting the same
                # values as batch as we commit early.  Is this a problem?
                # TODO Should we write the code to process one dive at a time even for batch?

                # if the value of abs_compress drifts around it distorts local a/b:
                # /Users/jsb/Seaglider/TestData/deployments/CCE/labrador/sep04/sg014
                # (Pdb) dive_set
                # [262, 263, 264, 265, 266]
                # jsb = solve_ab_grid(dive_set,4.4e-6)
                # INFO: FlightModel.py(822): n=6210 16s hd_a=0.00501(24) hd_b=0.00739(1) 0.843835
                # (Pdb) jsb = solve_ab_grid(dive_set,4.1e-6)
                # INFO: FlightModel.py(822): n=6210 16s hd_a=0.00355(21) hd_b=0.01014(3) 0.823073
                # (Pdb) jsb = solve_ab_grid(dive_set,4.0e-6)
                # INFO: FlightModel.py(822): n=6210 16s hd_a=0.00316(20) hd_b=0.01189(4) 0.818947
                # (Pdb) jsb = solve_ab_grid(dive_set,3.9e-6)
                # INFO: FlightModel.py(822): n=6210 16s hd_a=0.00282(19) hd_b=0.01631(6) 0.813645
                # (Pdb) jsb = solve_ab_grid(dive_set,3.5e-6)
                # INFO: FlightModel.py(822): n=6210 16s hd_a=0.00251(18) hd_b=0.03600(11) 0.802993
                if True:  # TODO eliminate this if per-dive abs_compress works; move to a median like with vbdbias
                    abs_compress_values = []
                    for ac_dive_num in flight_dive_nums:
                        dd = flight_dive_data_d[ac_dive_num]  # ensured
                        if dd.dive_data_ok and dd.bottom_press >= ac_min_press:
                            # TODO use predicted_abs_compress
                            abs_compress_values.append(dd.abs_compress)
                    if len(abs_compress_values):
                        old_abs_compress = flight_dive_data_d[
                            "abs_compress"
                        ]  # for debugging only
                        new_abs_compress = np.mean(abs_compress_values)
                        flight_dive_data_d["abs_compress"] = new_abs_compress
                        log_info(
                            "New mean abs_compress = %g (%.3f,%d)"
                            % (
                                new_abs_compress,
                                (1 - abs(new_abs_compress / old_abs_compress)),
                                len(abs_compress_values),
                            )
                        )

                # At this point we have a new or updated dive.
                save_flight_database(base_opts)  # checkpoint updated dive data
                # if dives come in out of order (comms problems, yoyo dives, under ice, etc)
                # we need to flush grid cache entries involving this reprocessed dive, if any, to recompute the grids going forward
                flush_ab_grid_cache(dive_num, ab_grid_cache_d)

            except KeyError:
                # no update required
                pass

            # BREAK compute groups of dives to solve for ab grid Having computed
            # vbdbias for the dive under a volmax/mass assumption we now try to
            # combine groups of dives as the deployment advances and
            # compute/update how hd_a and hd_b change (if at all) as things
            # progress.

            if not dive_data.dive_data_ok or np.isnan(dive_data.vbdbias):
                continue  # don't add to the dive set

            # Add the new dive to the possible dive_set and see if it is time to solve the ab grid again
            # if not, continue assuming predicted_a/b apply.  When we discover they don't we'll change previous dives as needed.
            pitch_d = dive_data.pitch_d
            if pitch_d > max_pitch_d:
                continue  # ignore this dive when computing ab grid (so it can never be in a dive_set)
            # Add information to pitch ring buffer
            mr_dives_pitches[mr_index, 0] = dive_num
            mr_dives_pitches[mr_index, 1] = dive_data.min_pitch
            mr_dives_pitches[mr_index, 2] = dive_data.max_pitch
            mr_index = (mr_index + 1) % n_dives_grid_spacing
            # This is number of dives added since the last TRUSTED grid
            mr_n_inserted += 1  # This can (and often does) exceed n_dives_grid_spacing on long transects
            # checkpoint current assumptions
            update_restart_cache(
                dive_num,
                mr_dives_pitches,
                mr_index,
                mr_n_inserted,
                last_W_misfit_RMS_dive_num,
                last_ab_committed_dive_num,
                predicted_hd_a,
                predicted_hd_b,
                predicted_hd_ab_trusted,
            )
            grid_compute_ok = False
            grid_spacing_i = list(range(n_dives_grid_spacing))
            if mr_n_inserted >= n_dives_grid_spacing:
                min_a = min(
                    mr_dives_pitches[grid_spacing_i, 1]
                )  # min of the min angles
                max_a = max(
                    mr_dives_pitches[grid_spacing_i, 2]
                )  # max of the max angles
                pitch_diff = max_a - min_a
                if pitch_diff > min_pitch_diff:
                    grid_compute_ok = True  # trusted
                    # reset counter since we will have a new trusted grid solution
                    mr_n_inserted = 0
                    min_i = np.argsort(mr_dives_pitches[grid_spacing_i, 1])
                    max_i = np.argsort(mr_dives_pitches[grid_spacing_i, 2])
                elif mr_n_inserted % n_dives_grid_spacing == 0:
                    grid_compute_ok = True  # untrusted
                    # ensure we get some dives up the the limit of the number points
                    min_i = grid_spacing_i
                    max_i = min_i

            if grid_compute_ok:
                # we can and should compute a new grid solution
                if (
                    dive_num == alert_dive_num
                    and mr_n_inserted == 2 * n_dives_grid_spacing
                ):  # PARAMETER (and we use == to alert this once)
                    # ALERT:
                    alerts += (
                        "Insufficiently different recent pitches (%d:%d degrees) to constrain drag parameter; consider a steep dive.\n"
                        % (min_a, max_a)
                    )

                dive_set = set()  # add uniquely
                n_valid_points = 0
                max_n_valid_points = 10000  # PARAMETER
                min_ii = 0
                max_ii = n_dives_grid_spacing - 1
                # We try to add a max and min pitch dive to the dive set
                # and not exceed 10K pts to keep the computational costs down
                # However we always get at least 2 dives
                # But there are screw cases:
                # With scicon (or DG), a single dive might have > 10K pts
                # It could be that a single dive covers both the min and max (that is ok)
                while True:
                    d_n = mr_dives_pitches[min_i[min_ii], 0]
                    if not d_n or d_n in dive_set:
                        break
                    dive_set.add(d_n)
                    dd = flight_dive_data_d[d_n]
                    n_valid_points += dd.n_valid
                    min_ii += 1

                    d_n = mr_dives_pitches[max_i[max_ii], 0]
                    if not d_n or d_n in dive_set:
                        break
                    dive_set.add(d_n)
                    dd = flight_dive_data_d[d_n]
                    n_valid_points += dd.n_valid
                    max_ii -= 1

                    if n_valid_points >= max_n_valid_points:
                        break
                # NOTE: it is possible that dive_set will NOT include dive_num
                # since dive_num triggered the search for a set but we use the set of dives with the widest pitches
                # available and those could have been earlier and not include dive_num
                dive_set = sorted(dive_set)
            else:
                # Not enough pitch difference to provide a well-constrained ab grid solution or not time for a non-trusted computation
                # because we can get out-of-order dives we might have plotted previously a grid triggered on dive_num
                # but now we don't think that is a good idea and will choose another dive_num
                # flush old result we won't use again (unless another out of order dive thinks better of it)
                if dive_num in list(ab_grid_cache_d.keys()):
                    flush_ab_grid_cache(dive_num, ab_grid_cache_d)
                continue  # not yet time to compute a new grid solution

            # if we make it here we (might) need to recompute the ab rms grid using dive_set; check against cache first

            # use dive_num as a key in cache of rms grid values
            # since we update dive_sets only with new, increasing dive numbers this is a unique key to each dive set
            try:
                (
                    W_misfit_RMS,
                    ia,
                    ib,
                    min_misfit,
                    prev_dive_set,
                    prev_pitch_diff,
                ) = ab_grid_cache_d[dive_num]
                trusted_ab = trusted_drag(prev_pitch_diff)
                compute_ab_grid = not (
                    dive_set == prev_dive_set
                )  # different dives with the same max dive_num forces recomputation
            except KeyError:
                compute_ab_grid = True

            if exit_event and exit_event.is_set():
                log_info("Exit requested")
                compute_ab_grid = False

            if compute_ab_grid:
                trusted_ab = trusted_drag(pitch_diff)
                flight_dive_data_d["any_hd_ab_trusted"] = (
                    flight_dive_data_d["any_hd_ab_trusted"] or trusted_ab
                )
                # Now we have a set of dives to run 'regress_vbd' on over a fixed grid for cross-group and mission comparison
                # compute a new ab grid solution
                W_misfit_RMS, ia, ib = solve_ab_grid(
                    base_opts, dive_set, reprocess_count, dive_num
                )
                if W_misfit_RMS is None:
                    log_warning("Grid solution failed - ignoring!")
                    continue
                min_misfit = W_misfit_RMS[ib, ia]
                if min_misfit > acceptable_w_rms:
                    # This could happen if we have some poisoned dive (bad CT, etc.) that stalls all solutions, for example
                    log_warning(f"Ignoring bad grid solution over {dive_set}!")
                    continue
                W_misfit_RMS = W_misfit_RMS - min_misfit
                if compare_velo == 0:
                    # Unless compare_velo is non-zero (e.g., velocimeter) hd_a
                    # is not well constrained even if trusted (really about b)
                    # so most values of hd_a 'work' above 0.003.  However,
                    # certain mixtures of dives might cause the solution set to
                    # prefer an apparently high hd_a (0.01) even though there are
                    # smaller values are equally acceptable. See SG236 NANOOS
                    # Sep20 dives 27, 28 grid

                    # Don't change too much away from existing a (typically the
                    # default) except to move away from small values.
                    # predicted_hd_a is prevailing value before adoptiong new grid value

                    # pylint: disable=cell-var-from-loop
                    x_a_i = list(
                        filter(
                            lambda a: W_misfit_RMS[ib, a] <= ab_tolerance
                            and hd_a_grid[a] >= predicted_hd_a,
                            range(len(hd_a_grid)),
                        )
                    )

                    if len(x_a_i):
                        x_a_i = x_a_i[0]
                        if x_a_i != ia:
                            log_info(
                                "Assuming hd_a=%.4g rather than %.4g"
                                % (hd_a_grid[x_a_i], hd_a_grid[ia])
                            )
                            ia = x_a_i

                # cache to avoid this expensive calculation next time
                ab_grid_cache_d[dive_num] = (
                    W_misfit_RMS,
                    ia,
                    ib,
                    min_misfit,
                    dive_set,
                    pitch_diff,
                )

            # NOTE you might be tempted to move this contour plotting code below the test for ab change
            # but that is a mistake since we want to show, if possible, the old last_W_misfit_RMS contour before we change it
            # so be careful if you move this code
            if (
                generate_figures and compute_ab_grid
            ):  # only generate this plot when we have a new grid solution
                hd_a_c = hd_a_grid[ia]
                hd_b_c = hd_b_grid[ib]
                # make sure all uses of \n are in normal, not r'' strings
                timelabel = (
                    "%s\n"
                    r"${vol}_{max}$=%.0f"
                    "\nc = %.4g; s = %.4g;\n"
                    r"$\kappa$ = %.4g; $\alpha$ = %.4g;"
                    "\nl = %.4g; press=%d/%d"
                )
                timelabel = timelabel % (
                    time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time())),
                    flight_dive_data_d["volmax"],
                    flight_consts_d["hd_c"],
                    flight_consts_d["hd_s"],
                    flight_dive_data_d["abs_compress"],
                    flight_consts_d["therm_expan"],
                    flight_consts_d["glider_length"],
                    pressmin,
                    pressmax,
                )
                if mass_comp:
                    timelabel += r"; ${mass}_{comp}$ = %.2fkg" % mass_comp

                # fig_c = figure implicit
                # hold on
                plt.xlabel("Lift (a)")
                plt.ylabel("Drag (b)")

                titlestring = (
                    "%s\n"
                    r"${w}_{rms}=%.2fcm/s$"
                    " [%s](%d)"
                    r" %d$\circ$"
                    "\na=%.6g b=%.6g"
                )
                titlestring = titlestring % (
                    glider_mission_string,
                    min_misfit,
                    Utils.succinct_elts(dive_set, matlab_offset=0),
                    compare_velo,
                    pitch_diff,
                    hd_a_c,
                    hd_b_c,
                )
                plt.suptitle(titlestring)
                # axis(view_bounds)
                plt.xlim(xmin=hd_a_grid[0], xmax=hd_a_grid[-1])
                plt.ylim(ymin=hd_b_grid[0], ymax=hd_b_grid[-1])
                plt.figtext(0.08, 0.02, timelabel, fontproperties=font)  # was 0.4 for y

                plt.plot(HD_A, HD_B, "k.", markersize=3)  # show (small) grid marks
                Cd = plt.contour(
                    HD_A,
                    HD_B,
                    W_misfit_RMS,
                    w_misfit_rms_levels,
                    colors="b",
                    linewidths=1.0,
                    linestyles="solid",
                )
                plt.clabel(
                    Cd,
                    inline=True,
                    inline_spacing=-1,
                    fontsize=9,
                    fmt="%2.1f",
                    colors="k",
                )

                if show_previous_ab_solution and last_W_misfit_RMS is not None:
                    # show what the previous 'good' values were; if they overlap around the current min, no change needed
                    Cd = plt.contour(
                        HD_A,
                        HD_B,
                        last_W_misfit_RMS,
                        prev_w_misfit_rms_levels,
                        colors="c",
                        linewidths=1.0,
                        linestyles="solid",
                    )
                    # Would be nice to change color to show if it exceeded tolerance but that code is below
                    # and it resets last_W_misfit_RMS in the process so we won't show the change
                    plt.plot(
                        flight_dive_data_d["hd_a"],
                        flight_dive_data_d["hd_b"],
                        "mo",
                        markersize=fig_markersize,
                    )  # show current assumed value

                current_tag = "g*"
                plt.plot(
                    hd_a_grid[ia], hd_b_grid[ib], current_tag, markersize=fig_markersize
                )  # show new min location
                if True:
                    # show errorbar locations used below to show 'span' of currently acceptable a/b
                    x_a_i = np.where(W_misfit_RMS[ib, :] <= ab_tolerance)[0]
                    x_b_i = np.where(W_misfit_RMS[:, ia] <= ab_tolerance)[0]
                    # show hd_a span with xerr
                    plt.errorbar(
                        hd_a_c,
                        hd_b_c,
                        None,
                        np.array(
                            [
                                [hd_a_c - hd_a_grid[x_a_i[0]]],
                                [hd_a_grid[x_a_i[-1]] - hd_a_c],
                            ]
                        ),
                        current_tag,
                        elinewidth=0.5,
                        ecolor="b",
                        capsize=5,
                        capthick=0.5,
                    )  # these line colors match FM_ab_dives below
                    plt.errorbar(
                        hd_a_c,
                        hd_b_c,
                        np.array(
                            [
                                [hd_b_c - hd_b_grid[x_b_i[0]]],
                                [hd_b_grid[x_b_i[-1]] - hd_b_c],
                            ]
                        ),
                        None,
                        current_tag,
                        elinewidth=0.5,
                        ecolor="r",
                        capsize=5,
                        capthick=0.5,
                    )  # these line colors match FM_ab_dives below
                if True:
                    # Mark stall (no solution) points
                    stall_value = w_rms_func_bad - min_misfit
                    x_i = np.where(W_misfit_RMS == stall_value)
                    for a_i, b_i in zip(x_i[1], x_i[0]):
                        plt.plot(
                            hd_a_grid[a_i],
                            hd_b_grid[b_i],
                            "kx",
                            markersize=fig_markersize,
                        )

                # Add pitch_diff as an indication of constraint?
                write_figure("dv%04d_ab.webp" % dive_num)
                plt.clf()

                # BUG: we compute DAC for dives in the dive set under the assumption that the current ia/ib will be their minimum
                # but this could be false if we assign the dive to the previous min a/b below
                if (
                    generate_dac_figures
                ):  # implicitly generate_figures and compute_ab_grid
                    for d_n in dive_set:
                        solve_ab_DAC(base_opts, d_n, W_misfit_RMS, ia, ib, min_misfit)

            # Determine if predicted_a/b need updating
            if last_W_misfit_RMS is None:
                last_ab_value = (
                    2 * ab_tolerance
                )  # To cover the initial dive_set case: force adoption of newly discovered a/b
            else:  # unless we have actual history
                last_ab_value = last_W_misfit_RMS[ib, ia]

            # update predicted hd_a/b etc.
            prior_hd_b = predicted_hd_b
            predicted_hd_a = hd_a_grid[ia]
            predicted_hd_b = hd_b_grid[ib]
            predicted_hd_ab_trusted = trusted_ab
            # update for future, unseen dives (via get_flight_parameters()): this is our current best estimate
            flight_dive_data_d["hd_a"] = predicted_hd_a
            flight_dive_data_d["hd_b"] = predicted_hd_b
            flight_dive_data_d["hd_ab_trusted"] = predicted_hd_ab_trusted
            # DEAD ignored flight_dive_data_d['vbdbias'] = 0 # BUG REALLY?  Not most recent?
            if force_ab_report or compute_ab_grid:
                log_info(
                    " %s: (%f,%d, %d:%.2f) new hd_a=%6.5f hd_b=%6.5f"
                    % (
                        dive_set,
                        min_misfit,
                        pitch_diff,
                        last_W_misfit_RMS_dive_num,
                        last_ab_value,
                        predicted_hd_a,
                        predicted_hd_b,
                    )
                )

            if trusted_ab and dive_num == alert_dive_num:  # during a deployment
                if predicted_hd_b > prior_hd_b:
                    if last_W_misfit_RMS is None:
                        # ALERT: The prior hd_b is our default value asserted above
                        alerts += "Initial vehicle drag larger than expected; additional sensors installed?\n"
                        # TODO update hd_b_biofouled around this new hd_b?
                        flight_dive_data_d["hd_b_biofouled"] = (
                            biofouling_scale * predicted_hd_b
                        )
                    else:
                        # ALERT: possible biofouling
                        # TODO compute time from dive 1 to most_recent_dive
                        # if less than 2 weeks, unlikely biofouling??  Even in Oman?
                        # This could be just stabilization
                        # TODO test if USE_ICE and suggest ice accumulation?
                        # TODO use mean SST to enable biofouling?  Time on sfc?
                        if predicted_hd_b > flight_dive_data_d["hd_b_biofouled"]:
                            alerts += "Vehicle drag has increased substantially; possible biofouling?\n"

                acceptable_precision = 0.8e-7  # TT8 has single-precision floats
                dive_data = flight_dive_data_d[
                    dive_num
                ]  # ensure most recent dive log data
                log_hd_a = flight_dive_data_d["hd_a"]
                # In the case of DG/OG we might use a different hd_s but the glider code assumes s=-1/4
                log_hd_b = flight_dive_data_d["hd_b"] * flight_dive_data_d["hd_s_scale"]
                log_hd_c = flight_dive_data_d["hd_c"]
                if not np.allclose(
                    [
                        log_hd_a / dive_data.log_HD_A,
                        log_hd_b / dive_data.log_HD_B,
                        log_hd_c / dive_data.log_HD_C,
                    ],
                    [1.0, 1.0, 1.0],
                    atol=acceptable_precision,
                ):
                    # ALERT: Report all $HD_x parameters, even if a subset are the same
                    glider_parm_format = "Update glider parameters:\n$HD_A,%.6g\n$HD_B,%.6g\n$HD_C,%.6g\n$RHO,%.6g\n"
                    alerts += glider_parm_format % (
                        log_hd_a,
                        log_hd_b,
                        log_hd_c,
                        flight_dive_data_d["rho0"] / 1000.0,
                    )  # convert rho0 to g/cc

            last_W_misfit_RMS = (
                W_misfit_RMS  # update our new best estimates for changes to hd_a/b
            )
            last_W_misfit_RMS_dive_num = dive_num

            # Somewhere between this dive_num and the last time we checked the ab grid
            # something changed.  Assume it started immediately after the last ab committed dive
            # ensure the current predicted_hd_a/b are propagated to intervening dives, even if no change
            for d_n in range(last_ab_committed_dive_num + 1, dive_num + 1):
                try:
                    dd = flight_dive_data_d[d_n]
                    if not dd.dive_data_ok:
                        continue  # can't do anything
                    if dd.hd_a == predicted_hd_a and dd.hd_b == predicted_hd_b:
                        continue  # nothing to do
                except KeyError:
                    # there could be a missing dive in the xrange sequence
                    # see SG529_NASCAR_040116_increasing_drag dive 495 missing
                    continue
                # Possible different hd_a/b
                # Make a copy of the dive_data, install the new possible a/b and see if there is any w_rms improvement
                # if so, make the copy the new dive_data instamce
                # TODO if there was no previous last_W_misfit_RMS then force all to predicted_hd_a/b
                ddc = copy.deepcopy(
                    dd
                )  # use deepcopy in case we decide to store dicts or arrays on elemnts
                ddc.hd_a = predicted_hd_a
                ddc.hd_b = predicted_hd_b
                ddc.hd_ab_trusted = predicted_hd_ab_trusted
                ddc.recompute_vbdbias_abs_compress = True  # permit recomputation
                if solve_vbdbias_abs_compress(base_opts, ddc):
                    # DEBUG log_info("Dive %d RMS=%5.4f -> %5.4f" % (d_n,dd.w_rms_vbdbias,ddc.w_rms_vbdbias)) # DEBUG
                    if ddc.w_rms_vbdbias < dd.w_rms_vbdbias:
                        flight_dive_data_d[d_n] = ddc
                        log_info(
                            "up: Dive %d RMS=%5.4f -> %5.4f%s"
                            % (
                                d_n,
                                dd.w_rms_vbdbias,
                                ddc.w_rms_vbdbias,
                                "t" if predicted_hd_ab_trusted else "",
                            )
                        )
                        dump_fm_values(ddc)

            last_ab_committed_dive_num = dive_num
            update_restart_cache(
                dive_num,
                mr_dives_pitches,
                mr_index,
                mr_n_inserted,
                last_W_misfit_RMS_dive_num,
                last_ab_committed_dive_num,
                predicted_hd_a,
                predicted_hd_b,
                predicted_hd_ab_trusted,
            )

            # save any updated ab_grid_cache and dive_data values (make available for possible reprocess below)
            save_flight_database(base_opts)
            # continue the main for loop for each dive number in update_flight_dive_nums

        # Done processing all known dives

        # Now update median_vbdbias over all know dives
        median_vbdbias_flight_dive_nums = []  # those dives for which we were able to calculate a vbdbias
        median_vbdbias = []
        for d_n in flight_dive_nums:
            dd = flight_dive_data_d[d_n]
            vbdbias = dd.vbdbias
            if not dd.dive_data_ok or np.isnan(vbdbias):
                continue
            median_vbdbias_flight_dive_nums.append(d_n)
            median_vbdbias.append(vbdbias)

        if len(median_vbdbias_flight_dive_nums) > 1:
            # Recompute the median vbdbias when there is new or possibly changed vbdbias information
            # and we have enough data to perform the filter
            # compute the median filter version of all vbdbias values
            median_vbdbias = Utils.medfilt1(
                median_vbdbias, L=min(len(median_vbdbias), vbdbias_filter)
            )
            for vbd_dive_num, dive_median_vbdbias in zip(
                median_vbdbias_flight_dive_nums, median_vbdbias
            ):
                dd = flight_dive_data_d[vbd_dive_num]  # ensured
                # update dive_data with median value (to be used when computing grid)
                dd.median_vbdbias = dive_median_vbdbias
            save_flight_database(base_opts)

        # rebuild summary plots
        if (
            generate_figures and len(flight_dive_nums) > 1
        ):  # wait until you have 2 dives so xlim/ylim don't complain
            timestamp = time.strftime("%d %b %Y %H:%M:%S", time.gmtime(time.time()))

            aflight_dive_nums = np.array(flight_dive_nums)
            n_dives = len(aflight_dive_nums)

            dds = np.array([flight_dive_data_d[d_n] for d_n in aflight_dive_nums])

            # vbdbias figure
            dives_vbdbias = np.array([dd.vbdbias for dd in dds])
            dives_median_vbdbias = np.array([dd.median_vbdbias for dd in dds])
            dives_w_rms_vbdbias = np.array([dd.w_rms_vbdbias for dd in dds])

            timelabel = f"{timestamp}\nmass = {flight_dive_data_d['mass']:.2f}kg"
            if mass_comp:
                timelabel += r"; ${mass}_{comp}$ = %.2fkg" % mass_comp

            plt.xlabel("Dive")
            plt.ylabel(
                f"Volume decrease (cc) from {flight_dive_data_d['volmax']:.2f}cc"
            )
            plt.suptitle(glider_mission_string)
            plt.figtext(0.08, 0.02, timelabel, fontproperties=font)  # was 0.4 for y

            # TODO set limit on vbdbias scale??

            (p_v,) = plt.plot(
                aflight_dive_nums, dives_vbdbias, "b.", markersize=fig_markersize
            )
            (p_mv,) = plt.plot(
                aflight_dive_nums, dives_median_vbdbias, "r.", markersize=fig_markersize
            )
            (p_w_rms,) = plt.plot(
                aflight_dive_nums,
                dives_w_rms_vbdbias * 10,
                "c.",
                markersize=fig_markersize,
            )
            no_soln_i = np.where(np.isnan(dives_vbdbias))[0]
            n_no_soln = len(no_soln_i)
            if n_no_soln:
                plt.plot(
                    aflight_dive_nums[no_soln_i],
                    np.zeros(n_no_soln, np.float64),
                    "xk",
                    markersize=fig_markersize,
                )
                dives_vbdbias[no_soln_i] = 0  # avoid nan in scaling below
            lg = plt.legend(
                [p_v, p_mv, p_w_rms],
                [
                    "Per-dive volume change (%d bad)" % n_no_soln,
                    "Median volume change (%d dives)" % vbdbias_filter,
                    r"min ${w}_{rms}$*10 (cm/s)",
                ],
                loc="lower right",
                fancybox=True,
                prop=font,
                numpoints=1,
            )
            lg.get_frame().set_alpha(0.5)
            # TODO warning from matplotlib when there is only one dive so xmin/xmax are the same
            # TODO see below as well
            plt.xlim(xmin=aflight_dive_nums[0], xmax=aflight_dive_nums[-1])
            # We expect most of the vbdbias figures to be greater than zero if our estimated volmax is close
            # but things can happen like sg221/ORBIS with sloughing ice, etc.
            delta_vbdbias = abs(dives_vbdbias)
            # ALT: vbdbias_scale = round(max(delta_vbdbias),-1) + 10 # round to the nearest 10
            for vbdbias_scale in range(100, 1000, 100):
                n_bad = len(np.where(delta_vbdbias > vbdbias_scale)[0])
                if n_bad < 0.1 * n_dives:
                    break
            plt.ylim(ymin=-vbdbias_scale, ymax=vbdbias_scale)
            ax = plt.gca()
            ax.grid(True)

            # An attempt to estimate implied C_VBD given apparent volume changes
            # via vbdbias To a first approximation, assuming C_VBD is tuned
            # properly for apogee in the first early_volmax_adjust dives then
            # vbdbias changes after that must reflect effects that need
            # compensation.  However, if you are not running at your nominal
            # service density (because you haven't gone deep or you are
            # transiting, etc) then C_VBD might not yet be set properly.  So we
            # tare the reference C_VBD prematurely and our recommendations are
            # off. See DG046 BATS 2019 where it took several 10's of dives
            # before we started going deep.  So we probably need to track bottom
            # densities and large changes imply re-taring the reference C_VBD.
            if show_implied_c_vbd and flight_dive_data_d["VBD_CNV"] is not None:
                # DEAD c_vbd = flight_dive_data_d['C_VBD'] # our inital C_VBD
                c_vbd = show_implied_c_vbd
                # given vbdbias_scale compute AD range on 2nd axis
                vbdbias_scale_AD = (
                    vbdbias_scale * flight_dive_data_d["VBD_CNV"]
                )  # AD counts
                ax2 = plt.twinx()  # 2nd y axis that shares the same x axis (dives)
                ax2.yaxis.set_major_locator(plt.MultipleLocator(50.0))  # AD counts
                # Applies to the prevailing y axis, hence ax2
                plt.ylim(c_vbd - vbdbias_scale_AD, c_vbd + vbdbias_scale_AD)
                plt.ylabel("Implied C_VBD (AD counts)")

            write_figure("eng_FM_vbdbias.webp")
            plt.clf()

            if glider_type is not OCULUS:  # No reason to plot this figure for OCULUS
                # abs_compress figure
                dives_bottom_press = np.array([dd.bottom_press for dd in dds])
                dives_abs_compress = np.array([dd.abs_compress for dd in dds])
                mean_abs_compress = flight_dive_data_d["abs_compress"]
                timelabel = f"{timestamp}\n$\\kappa$ = {mean_abs_compress:.4g}"

                plt.xlabel("Dive")
                plt.ylabel("Compressibility (1/dbar)")
                plt.suptitle(glider_mission_string)
                plt.figtext(0.08, 0.02, timelabel, fontproperties=font)  # was 0.4 for y
                (p_ac,) = plt.plot(
                    aflight_dive_nums,
                    dives_abs_compress,
                    "b.",
                    markersize=fig_markersize,
                )
                deep_dives_i = [
                    i
                    for i in range(len(aflight_dive_nums))
                    if dives_bottom_press[i] > ac_min_press
                ]
                (p_dac,) = plt.plot(
                    aflight_dive_nums[deep_dives_i],
                    dives_abs_compress[deep_dives_i],
                    "kx",
                    markersize=fig_markersize,
                )
                (p_mac,) = plt.plot(
                    [aflight_dive_nums[0], aflight_dive_nums[-1]],
                    [mean_abs_compress, mean_abs_compress],
                    "r-",
                    markersize=fig_markersize,
                )
                lg = plt.legend(
                    [p_ac, p_dac, p_mac],
                    [
                        "Raw abs_compress",
                        f"Deep (>{ac_min_press:.0f}psi) abs_compress",
                        "Mean (deep) abs_compress",
                    ],
                    loc="upper right",
                    fancybox=True,
                    prop=font,
                    numpoints=1,
                )
                lg.get_frame().set_alpha(0.5)
                plt.xlim(xmin=aflight_dive_nums[0], xmax=aflight_dive_nums[-1])
                plt.ylim(
                    ymin=flight_dive_data_d["ac_min"], ymax=flight_dive_data_d["ac_max"]
                )
                ax = plt.gca()
                ax.grid(True)

                write_figure("eng_FM_abs_compress.webp")
                plt.clf()

            # a/b history figure based on ab_grid_cache entries
            # trusted and untrusted display
            plt.xlabel("Dive")
            # Explicitly NO ylabel
            plt.suptitle(glider_mission_string)
            plt.figtext(0.08, 0.02, timestamp, fontproperties=font)  # was 0.4 for y
            # Use diamonds to distinguish the grid solution at a dive (with error bars) from the selected solution
            # a is never 'trusted' (unless we use a velocometer but then aren't all grids trusted?) so always display those as c
            display_trusted_a = False  # CONTROL
            if display_trusted_a:
                trusted_colors = ("b", "r", "b.", "r.", "bd", "rd")
            else:
                trusted_colors = ("c", "r", "c.", "r.", "cd", "rd")
            untrusted_colors = ("c", "m", "c.", "m.", "cd", "md")
            # generate handles
            lg_handles = []
            d_n = flight_dive_nums[0]
            dd = flight_dive_data_d[d_n]
            # Setup legend display using the first dive; its hd_a/b values will be overwritten with the proper narker below
            (
                a_color,
                b_color,
                a_marker,
                b_marker,
                a_grid_marker,
                b_grid_marker,
            ) = untrusted_colors
            (p_a,) = plt.plot(d_n, dd.hd_a * 10, a_marker, markersize=fig_markersize)
            lg_handles.append(p_a)
            (p_b,) = plt.plot(d_n, dd.hd_b, b_marker, markersize=fig_markersize)
            lg_handles.append(p_b)
            display_legend = ["a*10", "b"]
            if flight_dive_data_d["any_hd_ab_trusted"]:
                if display_trusted_a:
                    (
                        a_color,
                        b_color,
                        a_marker,
                        b_marker,
                        a_grid_marker,
                        b_grid_marker,
                    ) = trusted_colors
                    (p_a,) = plt.plot(
                        d_n, dd.hd_a * 10, a_marker, markersize=fig_markersize
                    )
                    lg_handles.append(p_a)
                    (p_b,) = plt.plot(d_n, dd.hd_b, b_marker, markersize=fig_markersize)
                    lg_handles.append(p_b)
                    display_legend.extend(["Trusted a*10", "Trusted b"])
                else:
                    (
                        a_color,
                        b_color,
                        a_marker,
                        b_marker,
                        a_grid_marker,
                        b_grid_marker,
                    ) = trusted_colors
                    (p_b,) = plt.plot(d_n, dd.hd_b, b_marker, markersize=fig_markersize)
                    lg_handles.append(p_b)
                    display_legend.extend(["Trusted b"])

            for d_n in flight_dive_nums:
                try:
                    (
                        W_misfit_RMS,
                        ia,
                        ib,
                        min_misfit,
                        prev_dive_set,
                        prev_pitch_diff,
                    ) = ab_grid_cache_d[d_n]
                    # We performed a grid solution at this point
                    (
                        a_color,
                        b_color,
                        a_marker,
                        b_marker,
                        a_grid_marker,
                        b_grid_marker,
                    ) = (
                        trusted_colors
                        if trusted_drag(prev_pitch_diff)
                        else untrusted_colors
                    )
                    hd_a = hd_a_grid[ia]
                    hd_b = hd_b_grid[ib]
                    # show extent of tolerable a and b around the computed value (BUT NOT the committed value)
                    x_a_i = np.where(W_misfit_RMS[ib, :] <= ab_tolerance)[0]
                    x_b_i = np.where(W_misfit_RMS[:, ia] <= ab_tolerance)[0]
                    p_a = plt.errorbar(
                        d_n,
                        hd_a * 10,
                        np.array(
                            [
                                [(hd_a - hd_a_grid[x_a_i[0]]) * 10],
                                [(hd_a_grid[x_a_i[-1]] - hd_a) * 10],
                            ]
                        ),
                        None,
                        a_grid_marker,
                        elinewidth=0.5,
                        ecolor=a_color,
                        capsize=5,
                        capthick=0.5,
                    )
                    p_b = plt.errorbar(
                        d_n,
                        hd_b,
                        np.array(
                            [
                                [(hd_b - hd_b_grid[x_b_i[0]])],
                                [(hd_b_grid[x_b_i[-1]] - hd_b)],
                            ]
                        ),
                        None,
                        b_grid_marker,
                        elinewidth=0.5,
                        ecolor=b_color,
                        capsize=5,
                        capthick=0.5,
                    )
                except KeyError:
                    pass
                dd = flight_dive_data_d[d_n]  # ensured
                a_color, b_color, a_marker, b_marker, a_grid_marker, b_grid_marker = (
                    trusted_colors if dd.hd_ab_trusted else untrusted_colors
                )
                (p_a,) = plt.plot(
                    d_n, dd.hd_a * 10, a_marker, markersize=fig_markersize
                )
                (p_b,) = plt.plot(d_n, dd.hd_b, b_marker, markersize=fig_markersize)

            lg = plt.legend(
                lg_handles,
                display_legend,
                loc="upper right",
                fancybox=True,
                prop=font,
                numpoints=1,
            )
            lg.get_frame().set_alpha(0.5)
            plt.xlim(xmin=aflight_dive_nums[0], xmax=aflight_dive_nums[-1])
            plt.ylim(
                ymin=min(hd_a_grid[0] * 10, hd_b_grid[0]),
                ymax=max(hd_a_grid[-1] * 10, hd_b_grid[-1]),
            )
            ax = plt.gca()
            ax.grid(True)

            write_figure("eng_FM_ab_dives.webp")
            plt.clf()

        # Determine which dives need to be reprocessed because of flight parameter changes
        # EXPLICITLY not update_flight_dive_nums because we might have updated dives back to last_ab_committed_dive_num
        for d_n in flight_dive_nums:
            dd = flight_dive_data_d[d_n]
            dd_vbdbias = dd.vbdbias
            if np.isnan(dd_vbdbias):
                continue  # could not resolve vbdbias
            abs_compress = dd.abs_compress

            compare = (
                (dd.hd_a * predicted_hd_a_scale != dd.nc_hd_a),
                (dd.hd_b * predicted_hd_b_scale != dd.nc_hd_b),
                (dd.volmax != dd.nc_volmax),
                # There are always very small changes to abs_compress and vbdbias if recomputed
                # for abs_compress as the number of deep dives accumulate the mean stabilizes
                # but early it fluctuates more.  So the first 20-50 dives might see a lot
                # of reprocessing.
                abs(dd_vbdbias - dd.nc_vbdbias) > vbdbias_tolerance,
                abs(1.0 - (abs_compress / dd.nc_abs_compress))
                > abs_compress_tolerance,  # try a 5% change
            )

            if exit_event and exit_event.is_set():
                log_info("Exit requested")
                compare = [False]

            if dd.dive_data_ok and any(compare):
                log_info(" Reprocess dive %d: %s" % (d_n, compare))
                log_info(
                    "  v: %.2f [%.2f %.2f] ac: %.3f [%g %g]"
                    % (
                        abs(dd_vbdbias - dd.nc_vbdbias),
                        dd_vbdbias,
                        dd.nc_vbdbias,
                        abs(1.0 - (abs_compress / dd.nc_abs_compress)),
                        abs_compress,
                        dd.nc_abs_compress,
                    )
                )  # DEBUG
                # if a or b change, force volmax recomputation
                if compare[0] or compare[1]:
                    dd.recompute_vbdbias_abs_compress = True
                reprocess_dives.append(d_n)
        save_flight_database(
            base_opts, dump_mat=True
        )  # save any updated data before reprocessing
        reprocess_dives = sorted(Utils.unique(reprocess_dives))
        # A note on reprocessing.  We can really only do this with coupled changes in MDP that request the FM data
        # via get_flight_parameters() above.  For older basestations in order to reprocess dives we would have to
        # rewrite sg_calib_costants.m *for each dive*, reprocess that one dive, etc. and then restore sgc to some
        # default state that reflects our current best guess for any new dives.  But if the pilot was editing sgc
        # for any other reason (sensor coefficient values, etc.) we'd have to lock that version, etc. etc.  Complicated fast.
        # And worse, even if we did do this if the pilot or later oceaographers needed to reprocess the files
        # they would have to have a special sgc that has no FM variables in it so we don't override the per-dive FM values
        # that are stored there (and each run would complain it was missing values for the FM variables!!).
        # Running against a new basestation takes care of all these things.
        # You can still run this code against an old basestation and see if it is a normal deployment.  If so you can
        # use its results to update the master sgc and reprocess the dives to use the same set of FM parameters for all dives.
        # If the deployment is not normal, you'll have to process subsets of dives, at best.
        if len(reprocess_dives) > 0:
            # update all 'changed/changing' dives with their new values as though we had reprocessed and reloaded them
            # if not base_opts.fm_reprocess_dives then we won't reload and reprocess them and they won't retrigger the update loop
            for d_n in reprocess_dives:
                dd = flight_dive_data_d[d_n]
                dd.nc_hd_a = dd.hd_a
                dd.nc_hd_b = dd.hd_b
                dd.nc_volmax = dd.volmax
                dd.nc_vbdbias = dd.vbdbias
                dd.nc_abs_compress = dd.abs_compress
            save_flight_database(
                base_opts, dump_mat=False
            )  # save any updated data before reprocessing

            if base_opts.fm_reprocess_dives:
                log_info(f"Reprocess dives: {reprocess_dives}")

                dives = ""
                for d_n in reprocess_dives:
                    dives += " %d" % d_n
                # Because the output of Reprocess is large we must redirect stdout/stderr to a file
                # so os.waitpid does not hang.  Even using Popen.communicate() would have this problem
                # plus we want to have a record of the output...which we save to the flight subdirectory
                # time.strftime("%d%b%Y_%H%M%S", time.gmtime(time.time()))

                # TODO - need to evaluate the merit of a launch vs direct invokation
                reprocess_log = os.path.join(
                    flight_directory,
                    "Reprocess_%04d_%.f.log" % (max(flight_dive_nums), time.time()),
                )
                Utils.run_cmd_shell(
                    "%s %s --force -v --called_from_fm --mission_dir %s --nice %d %s  > %s 2>&1"
                    % (
                        sys.executable,
                        os.path.join(base_opts.basestation_directory, "Reprocess.py"),
                        mission_directory,
                        base_opts.nice,
                        dives,
                        reprocess_log,
                    )
                )

                log_info(f"Back from Reprocess.py - see {reprocess_log} for details")
                # update updated_dives_d with any new times for the next FM cycle
                for d_n in reprocess_dives:
                    dd = flight_dive_data_d[d_n]
                    dive_nc_file_name = nc_path_format % d_n
                    reprocess_error = None
                    if os.path.exists(dive_nc_file_name):
                        nc_time = os.path.getmtime(dive_nc_file_name)
                        if nc_time > dd.last_updated:
                            # what we expected....
                            # force both reprocessing and scanning of this dive again
                            dives_reprocessed = True
                            updated_dives_d[d_n] = nc_time
                            log_info(f"Dive {d_n} sucesfully processed")
                            nc_files_created.append(dive_nc_file_name)
                        else:
                            reprocess_error = (
                                "Dive %d reprocessed but nc file was not updated?"
                            )
                    else:
                        reprocess_error = "Dive %d reprocessed but nc file now missing?"

                    if reprocess_error is not None:
                        log_error(reprocess_error % d_n)
                        log_error(f"Consult {reprocess_log} for futher details")
                        base_opts.fm_reprocess_dives = False  # don't do this again...
                        dd.dive_data_ok = False  # skip this dive until it is reprocessed by someone else
                save_flight_database(
                    base_opts, dump_mat=False
                )  # save any updated data after reprocessing

    # BREAK done with reprocessing dives
    # at this point we have updated vbdbias and ab for all dives
    # see if there are trends worth reporting
    if len(alerts) > 0:
        # log_alert(
        #    "FM", alerts
        # )  # this replaces any previous alerts with the most-recent
        log_info(
            f"FMS_ALERT: {alerts}", alert="FMS"
        )  # DEBUG so you can grep in any log files
    # DEBUG pfdd(True) # DEBUG
    log_debug(
        "Finished FM processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    return 0


# Called as an extension or via cmdline_main() below
def main(
    base_opts,
    sg_calib_file_name,
    nc_files_created,
    exit_event=None,
):
    """Basestation support for evaluating flight model parameters from dive data

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    global \
        flight_dive_data_d, \
        flight_directory, \
        mission_directory, \
        plots_directory, \
        nc_path_format, \
        flight_consts_d, \
        compress_cnf, \
        generate_dac_figures
    global \
        dump_fm_files, \
        old_basestation, \
        glider_type, \
        compare_velo, \
        acceptable_w_rms, \
        flight_dive_nums, \
        hd_a_grid, \
        hd_b_grid, \
        sg_hd_s, \
        hd_s_assumed_q
    global \
        ab_grid_cache_d, \
        restart_cache_d, \
        angles, \
        grid_spacing_keys, \
        grid_dive_sets, \
        dump_checkpoint_data_matfiles

    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(
            "Basestation support for evaluating flight model parameters from dive data"
        )
    BaseLogger(base_opts)  # initializes BaseLog

    Utils.check_versions()

    if exit_event:
        log_info(f"Exit is {exit_event.is_set()}")

    if not mission_directory:
        mission_directory = base_opts.mission_dir

    if not mission_directory:
        log_error("mission directory not set - bailing out")
        return 1

    # update global variables from cnf file(s)
    import configparser

    cnf_file = "flight_model.cnf"
    # Important NOTE:
    # all the names (but NOT the values) in the name,value pairs are coerced to lowercase!
    # build from globals_d and declarations
    files = []
    cp = configparser.RawConfigParser({})
    try:
        files = cp.read(
            [
                os.path.join(base_opts.basestation_directory, cnf_file),
                os.path.join(mission_directory, cnf_file),
            ]
        )
    except:
        # One way to get here is to have continuation lines on an entry
        # that are not indented by a single space AND have a colon somewhere in the line
        # In this case you'll get a complaint about an unknown global variable with that phrase in lower case
        # NOTE: if there is a continuation but no space and no colon the parser skips it without complaint
        log_warning(f"Problems reading information from {cnf_file}")  # problems...
    else:
        globs = globals()  # we will update globals() as a side effect below
        for pair in cp.items("FlightModel"):  # keys are stored as lowercase!!
            name, value = pair
            try:
                ovalue = globs[name]
            except KeyError:
                log_error(f"Unknown parameter {name}")
                continue
            try:
                evalue = eval(value)  # can't use = in expressions to eval
            except:
                log_error(f" Unable to interpret {value} as a value for {name}")
                continue
            log_info(f" Updating {name} from {ovalue} to {evalue}")  # echo to log file
            globs[name] = evalue

    # At this point all global parameters are updated so derive things from them
    grid_spacing_keys = sorted(list(grid_spacing_d.keys()))
    angles = np.linspace(0, pitchmax, pitchmax + 1)  # integral angle bins

    if Utils.normalize_version(Globals.basestation_version) < Utils.normalize_version(
        "2.12"
    ):
        log_warning(
            "Reprocessing disabled because basestation version %s too early"
            % Globals.basestation_version
        )
        base_opts.fm_reprocess_dives = False
        old_basestation = True
        dump_fm_files = True  # let the pilot know what values we find, per-dive

    sg_calib_constants_d = getSGCalibrationConstants(sg_calib_file_name)
    if not sg_calib_constants_d or "id_str" not in sg_calib_constants_d:
        log_error(f"Could not process {sg_calib_file_name}")
        return 1

    if not base_opts.fm_reprocess_dives:
        generate_dac_figures = (
            False  # need DAC input data from updated FM variables saved by v2.12
        )

    # Collect up all the possible files and process from scatch against our dive db
    # we deliberately ignore dive_nc_filenames and nc_files_created that we are passed
    # TODO only emit alerts if nc_file_created is not None and it contains the most recent dive
    # hence likely called during an active deployment so alerts will have a chance of influencing the pilot
    # otherwise it is moot.
    dive_nc_file_names = sorted(MakeDiveProfiles.collect_nc_perdive_files(base_opts))
    if len(dive_nc_file_names) == 0:
        log_error("No dive profiles to process")
        return 1

    # In case there is non-zero mass_comp
    if compress_cnf is None:
        if not old_basestation:
            compress_cnf, _ = Utils.read_cnf_file(
                "compress.cnf",
                mission_dir=mission_directory,
                encode_list=False,
                lower=False,
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

    BaseLogger.self.startStringCapture()  # start recording processing history

    # We need to supply missing defaults to sg_calib_constants_d, which depend on the type of vehicle, etc.
    # we use either stored assumptions from a past analysis or discover them from the first 1
    nc_path_format = os.path.join(
        mission_directory, "p%03d%%04d.nc" % int(sg_calib_constants_d["id_str"])
    )
    load_flight_database(
        base_opts, sg_calib_constants_d, verify=False, create_db=False
    )  # load the db, if any

    if generate_figures and copy_figures_to_plots:
        plots_directory = os.path.join(mission_directory, "plots")
        if not os.path.exists(plots_directory):
            plots_directory = None

    glider_type = None  # assumed not yet determined
    deck_dives = False
    max_density = None
    if flight_dive_data_d is not None:
        try:
            has_gpctd = flight_dive_data_d["has_gpctd"]
            compare_velo = flight_dive_data_d["compare_velo"]
            deck_dives = flight_dive_data_d["deck_dives"]
            # fetch this last!
            glider_type = flight_dive_data_d["glider_type"]
        except KeyError:
            pass
        if deck_dives:
            # TODO eliminate this complaint since we said it once on creation?
            log_error("Unable to run flight model on deck dives!")
            return 1

    if glider_type is None:
        # db was (re)initialized
        # We need to get some additional assumptions about the glider before creating the flight db
        dive_nc_file_name = dive_nc_file_names[0]  # open first found filename
        try:
            dive_nc_file = Utils.open_netcdf_file(dive_nc_file_name, "r")
        except:
            log_error(f"Unable to open {dive_nc_file_name} to establish glider type")
            return 1
        try:
            log_deepglider = dive_nc_file.variables["log_DEEPGLIDER"].getValue()
        except KeyError:
            log_deepglider = SEAGLIDER  # assume SG (0)
        try:
            sim_w = dive_nc_file.variables["log_SIM_W"].getValue()
        except KeyError:
            sim_w = 0  # assume normal dive
        if sim_w:
            deck_dives = True
        has_gpctd = False  # for the moment, since they are rare
        if compare_velo < 0:
            compare_velo = abs(compare_velo)  # trust but don't verify
        elif compare_velo and not "velo_speed" in dive_nc_file.variables:
            # if data is present then use default CONTROL value in main globals declaration
            # otherwise disable velo comparison
            compare_velo = 0
        try:
            density_insitu = dive_nc_file.variables["density_insitu"][:]
            max_density = np.nanmax(density_insitu)
        except KeyError:
            # must have had a processing error on the initial dive or something
            max_density = FM_default_rho0
        dive_nc_file.close()

        if old_basestation:
            MakeDiveProfiles.sg_config_constants(
                base_opts, sg_calib_constants_d, None, {}
            )
            glider_type = get_FM_defaults(sg_calib_constants_d)
        else:
            # the new sg_config_constants calls  get_FM_defaults recursively and returns glider_type
            glider_type = MakeDiveProfiles.sg_config_constants(
                base_opts, sg_calib_constants_d, log_deepglider, has_gpctd
            )

    # (re)load or create the flight model db and ensure the assumptions of sg_calib_constants_d haven't changed
    flight_dive_data_d = None  # reset and try loading again
    reinitialized = load_flight_database(
        base_opts, sg_calib_constants_d, verify=True, create_db=True
    )
    # update in DB for later
    flight_dive_data_d["glider_type"] = glider_type
    flight_dive_data_d["has_gpctd"] = has_gpctd
    flight_dive_data_d["compare_velo"] = compare_velo
    flight_dive_data_d["deck_dives"] = deck_dives

    if compare_velo:
        if compare_velo in (1, 2):
            acceptable_w_rms *= (
                2  # we combine w_rms with one other velocimeter estimate
            )
        else:  # compare_velo == 3
            acceptable_w_rms *= (
                3  # we combine w_rms with two other velocimeter estimates
            )
        dive_data_vector_names.append("velo_speed")
    if deck_dives:
        base_opts.fm_reprocess_dives = False

    if reinitialized:
        # 2023/03/15 GBS - we now handle the sg_calib_constants.m file by filter out flight variables
        # see Globals.py for the list - see CalibConsts.m for the filter code.  Default logic is to
        # filter out the variables (issuing warnings/alerts) (unless the user appends a comment containing
        # FM_ignore.

        # if enable_reprocessing_dives:
        # since we can reprocess on a per-dive basis, rewrite sgc so it don't pollute/override FM parameters
        # but allow the pilot to then edit the file to update other (i.e., sensor) parameters without issue.
        # Otherwise don't touch the file
        # BUG you can get into trouble if you delete the flight subdir and then reprocess with a non-cleansed sgc
        # since then those (subset) values will overwrite the FM values stored in the nc file
        # So perhaps the better part of valour is to always rewrite the sgc file?
        # NO: In order to get into this state they must be running FM under an old basestation so we couldn't
        # rewrite with FM data per dive anyway, even if they reprocess by hand.
        # cleanse_sg_calib_constants(sg_calib_file_name)

        # Override whatever the pilot might have provided for FM parameters with our defaults
        # do this once when the db is being created and cache in flight_dive_data_d
        # but do this after loading the users sg_calib_constants (to get mass, id_str, etc.)
        get_FM_defaults(flight_dive_data_d, glider_type=glider_type)
        # Now Add additional defaults for the flight data base

        # Verify expected range of mass/mass_comp
        mass_alerts = ""
        mass = flight_dive_data_d["mass"]
        if mass > 100:  # SGX and DG are typically 80kg
            mass_alerts += (
                "Correcting mass of vehicle from sg_calib_constants (%.1f) to kg\n"
                % mass
            )
            flight_dive_data_d["mass"] = mass = mass / g_per_kg
        mass_comp = flight_dive_data_d["mass_comp"]
        if (
            mass_comp > 20
        ):  # typically no more that 12kg but could be more with dodecamethylpentasiloxane
            mass_alerts += (
                "Correcting compressee mass of vehicle from sg_calib_constants (%.1f) to kg\n"
                % mass_comp
            )
            flight_dive_data_d["mass_comp"] = mass_comp / g_per_kg
        if len(mass_alerts) > 0:
            log_alert("FM_mass", mass_alerts)
            log_warning(mass_alerts)

        # Initial estimate of volmax
        # TODO when we compute a better global guess, restate any cached displaced_volume
        volmax = estimate_volmax(mass, max_density)
        flight_dive_data_d["volmax"] = volmax
        flight_dive_data_d["vbdbias"] = 0
        log_info(f"Initial volmax estimate: {volmax:.0f}cc")

        flight_dive_data_d["final_volmax_found"] = False
        # An initial C_VBD value and vehicle conversion factor
        flight_dive_data_d["C_VBD"] = None
        flight_dive_data_d["VBD_CNV"] = None
        flight_dive_data_d["hd_ab_trusted"] = False  # don't trust the defaults
        flight_dive_data_d["any_hd_ab_trusted"] = False  # haven't found a trusted b yet
        flight_dive_data_d["hd_b_biofouled"] = (
            biofouling_scale * flight_dive_data_d["hd_b"]
        )
        # NOTE these grids are log, not linear with more points toward lower values, which concentrates on the usual location of a/b
        # DEAD # log10hd_a_grid = np.linspace(-3.0,-1.3,35)
        # DEAD # log10hd_a_grid = np.linspace(-3.0,-2.2,17)
        log10hd_a_grid = np.linspace(-3.5, -2.0, 31)

        # DEAD log10hd_b_grid = np.linspace(-2.5,-1.0,31)  # very wide
        log10hd_b_grid = np.linspace(-2.5, -1.5, 21)  # 0.003162 0.031623
        log10hd_b_grid = np.linspace(
            -2.1, -1.4, 15
        )  # 0.007943 0.039811 # raise the window to avoid computing impossible too fast speeds but increase possible drag regimes
        # log10hd_b_grid = np.linspace(-2.1,-1.2,15) # 0.007943 0.063100 (better for DG?)
        log10hd_b_grid = np.linspace(
            -2.2, -1.4, 17
        )  # 0.007943 0.039811 # raise the window to avoid computing impossible too fast speeds but increase possible drag regimes
        log10hd_b_grid = np.linspace(
            -2.2, -1.1, 17
        )  # 0.007943 0.079400 # raise the window to avoid computing impossible too fast speeds but increase possible drag regimes

        if glider_type == SEAGLIDER:
            flight_dive_data_d["glider_type_string"] = "SG"
            if mass > SGX_MASS:
                flight_dive_data_d["glider_type_string"] = "SGX"
                # Apparently substantially lower drag.
                # NOTE this sets the drag grid directly, not log10hd_b_grid
                # NOTE start the grid at 0.001 to avoid feeding a hd_b of zero into hydro_model
                hd_b_grid = np.linspace(0.001, 0.030, 25)

        elif glider_type == DEEPGLIDER:
            flight_dive_data_d["glider_type_string"] = "DG"
            # log10hd_b_grid = np.linspace(-2.6,-1.4,17) # wider (and lower!) b range: 0.00398 0.0398
            log10hd_b_grid = np.linspace(
                -2.7, -1.4, 15
            )  # wider (and lower!) b range: 0.00200 0.0398
            log10hd_b_grid = np.linspace(
                -2.7, -1.1, 15
            )  # wider (and lower!) b range: 0.00200 0.0794

        # TODO verify these ranges
        elif glider_type == OCULUS:
            flight_dive_data_d["glider_type_string"] = "OG"
            if False:
                log10hd_a_grid = np.linspace(-3.5, -2.0, 31)  # wider a range
                log10hd_b_grid = np.linspace(-2.5, -1.0, 31)  # wider b range

        else:
            raise RuntimeError("Unknown glider type %d from $DEEPGLIDER!" % glider_type)

        if hd_a_grid is None:
            hd_a_grid = 10**log10hd_a_grid
        if hd_b_grid is None:
            hd_b_grid = 10**log10hd_b_grid

        flight_dive_data_d["hd_a_grid"] = hd_a_grid
        flight_dive_data_d["hd_b_grid"] = hd_b_grid
        if flight_dive_data_d["hd_s"] != sg_hd_s:
            # In the case of DG/OG we might use a different hd_s but the glider code assumes s=-1/4
            # thus we need to compute our HD_b from our found b according to:
            # bq^s = HD_Bq^(-1/4) where we just assume a q between 10 and 150cms/s
            # Often we take a mean value of 40cm/s along track
            # For s = 0, hd_s_scale = 1/40**(-.25) == 2.5149
            flight_dive_data_d["hd_s_scale"] = (
                hd_s_assumed_q ** flight_dive_data_d["hd_s"]
            ) / (hd_s_assumed_q**sg_hd_s)

        # limit the bounds for vbdbias search
        # at the beginning we search over 2K cc for vbdbias in case our volmax estimation is wildly off
        flight_dive_data_d["vbdbias_min"] = -vbdbias_search_range
        flight_dive_data_d["vbdbias_max"] = vbdbias_search_range

        # limit the bounds for abs_compress search
        flight_dive_data_d["ac_min"] = ac_min_start
        flight_dive_data_d["ac_max"] = ac_max_start
        flight_dive_data_d[
            "ac_min_press"
        ] = 500  # [dbar] this is where we can start seeing the impact, otherwise use the default
        # DEBUG pfdd(True) #  display initial defaults in the log file
        save_flight_database(base_opts)

    if deck_dives:  # test this after the DB is saved
        log_error("Unable to run flight model on deck dives!")
        return 1

    # setup flight_consts_d for use with hydromodel once since we either override hd_a/b or we ignore values for vbdbias and abs_compress
    flight_consts_d = {}
    # unpack the assumed constants for this glider type from our flight_dive_data_d global assumptions
    for fv in assumption_variables:
        flight_consts_d[fv] = flight_dive_data_d[fv]
    for fv in flight_variables:
        flight_consts_d[fv] = flight_dive_data_d[fv]

    # unpack flight_dive_data_d structures into globals
    ab_grid_cache_d = flight_dive_data_d["ab_grid_cache"]  # updated by side-effect
    restart_cache_d = flight_dive_data_d["restart_cache"]
    hd_a_grid = flight_dive_data_d["hd_a_grid"]
    hd_b_grid = flight_dive_data_d["hd_b_grid"]
    flight_dive_nums = flight_dive_data_d["dives"]  # updated by side-effect
    log_debug(f"flight_dive_nums : {flight_dive_nums}")

    if reinitialized:
        log_info(
            "Flight model version: %.2f; glider_type=%d" % (fm_version, glider_type)
        )
        log_info(
            "CONTROL: reprocessing=%s compare_velo=%d hd_a_scale=%.2f hd_b_scale=%.2f"
            % (
                base_opts.fm_reprocess_dives,
                compare_velo,
                predicted_hd_a_scale,
                predicted_hd_b_scale,
            )
        )

    # Ensure that the hd_b_grid contains no zero values - those cause
    # the hydro model to blow up and slows down all processing for no useful purpose
    hd_b_grid[hd_b_grid == 0.0] = 0.001

    ## Main processing loop
    # Scan to see what files need to be worked on
    new_dive_nums = []
    updated_dives_d = {}
    for dive_nc_file_name in dive_nc_file_names:
        _, tail = os.path.split(dive_nc_file_name)
        dive_num = int(tail[4:8])
        dive_nc_file_time = os.path.getmtime(dive_nc_file_name)
        try:
            dd = flight_dive_data_d[dive_num]
            if dive_nc_file_time != dd.last_updated:  # typically >
                updated_dives_d[dive_num] = dive_nc_file_time
        except KeyError:
            new_dive_nums.append(dive_num)
            updated_dives_d[dive_num] = dive_nc_file_time

    # Now, as a heuristic, if we are within a few days of the dive_num's START TIME assume we are during a live deployment
    # Avoid relying on the reprocess file modified time, which can be updated by reprocess and FM itself
    dd = flight_data(
        dive_num
    )  # make up a temporary dive data instance but don't intern into flight_dive_data_d
    data_d = load_dive_data(base_opts, dd)  # ignore result
    alert_dive_num = None
    # Deepgliders can take 2 days down and back
    # if the load_dive_data fails to update start_time, the value is 0 and we don't set alert_dive_num
    if (time.time() - dd.start_time) < 3 * 86400:  # PARAMETER
        alert_dive_num = dive_num

    # simulate adding one dive at a time to the FDD as if this were a deployment
    ret_val = 0
    log_debug("Starting main loop")
    for new_dive_num in new_dive_nums:
        if exit_event and exit_event.is_set():
            log_info("Exit requested")
            ret_val = 1
            break
        log_debug("Main loop dive %d" % new_dive_num)
        if force_alerts:  # for debugging alerts
            alert_dive_num = new_dive_num
        ret_val = process_dive(
            base_opts,
            new_dive_num,
            updated_dives_d,
            nc_files_created,
            alert_dive_num,
            exit_event=exit_event,
        )
        if ret_val:
            log_error("process_dive returned %d - bailing out" % ret_val)
            break
    log_debug("Main loop ended")
    if not ret_val:
        # recompute the keys() in case the process_dive() calls removed them by side-effect
        if len(list(updated_dives_d.keys())) > 0:  # any residual updated files
            # in case there are no new dives but some dives were updated (via external reprocessing)
            log_debug(f"Processing remaining dives {list(updated_dives_d.keys())}")
            ret_val = process_dive(
                base_opts,
                None,
                updated_dives_d,
                nc_files_created,
                alert_dive_num,
                exit_event=exit_event,
            )
            log_debug("Done processing remaining dives")

    save_flight_database(
        base_opts
    )  # save any updated history, ab_grid_cache, and dive_data values

    if not ret_val and len(grid_dive_sets):
        # now that everything is buttoned up try solving these grids the user is interested in
        dump_checkpoint_data_matfiles = True
        for dive_set in grid_dive_sets:
            if all(map(lambda d: d in flight_dive_data_d, dive_set)):
                log_info(f"Solving a/b grid for {dive_set}")
                solve_ab_grid(base_opts, dive_set, 99)
    return ret_val


def cmdline_main():
    """Command line driver for updateing flight model data

    Note:
        sg_calib_constants must be in the same directory as the file(s) being processed

    Returns:
        0 - success
        1 - failure
    """
    global mission_directory
    base_opts = BaseOpts.BaseOptions(
        "Command line driver for updateing flight model data"
    )

    BaseLogger(base_opts, include_time=True)  # initializes BaseLog

    mission_directory = base_opts.mission_dir

    return process_directory(base_opts)


def process_directory(base_opts):
    """Can be called from multiprocessing scheme"""
    nc_files_created = []
    sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
    sg_calib_constants_d = getSGCalibrationConstants(sg_calib_file_name)
    if not sg_calib_constants_d:
        log_error(f"Could not process {sg_calib_file_name}")
        return 1

    try:
        instrument_id = int(sg_calib_constants_d["id_str"])
    except:
        # base_opts always supplies a default (0)
        instrument_id = int(base_opts.instrument_id)
    if instrument_id == 0:
        log_warning("Unable to determine instrument id; assuming 0")
    try:
        # run like an extension
        return main(
            base_opts,
            sg_calib_file_name,
            nc_files_created,
        )
    except KeyboardInterrupt:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_error("Keyboard interrupt - breaking out")
        return 1

    except RuntimeError as exception:
        log_error(exception.args[0])
        return 1


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    np.seterr(divide="raise", invalid="raise")

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
            retval = cProfile.run("cmdline_main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = cmdline_main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, tracebb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tracebb)

        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
