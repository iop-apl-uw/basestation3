#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2022 by University of Washington.  All rights reserved.
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

"""
  Common set of options for all basestation processing
  Default values supplemented by option processing, both config file and command line
"""

# TODO Review help strings - mark all extensions as extensions not command line
# TODO Review option_t.group for all options (make sure there are module names in them)
# TODO Final pass - remove all command-line help from docstrings, check that all base_opts.members are covered, any required arguments are marked as sch
# TODO Compare Base.py help vs help output
# TODO Write a script to generate all the help output into files in help directory
# TODO Figure out how to show defaults in option help (https://stackoverflow.com/questions/12151306/argparse-way-to-include-default-values-in-help)

import argparse

# import collections
import copy
import configparser
import dataclasses
import inspect
import os
import pdb
import sys
import time
import typing
import traceback

from Globals import WhichHalf  # basestation_version


def generate_range_action(arg, min_val, max_val):
    """Creates an range checking action for argparse"""

    class RangeAction(argparse.Action):
        """Range checking action"""

        def __call__(self, parser, namespace, values, option_string=None):
            if values is None:
                raise argparse.ArgumentError(
                    self, f"None is not valid for argument [{arg}]"
                )

            if not min_val <= values <= max_val:
                raise argparse.ArgumentError(
                    self, f"{values} not in range for argument [{arg}]"
                )
            setattr(namespace, self.dest, values)

    return RangeAction


def FullPath(x):
    """Expand user- and relative-paths"""
    if isinstance(x, list):
        return list(map(lambda y: os.path.abspath(os.path.expanduser(y)), x))
    else:
        return os.path.abspath(os.path.expanduser(x))


def FullPathTrailingSlash(x):
    """Expand user- and relative-paths and include the trailing slash"""
    return FullPath(x) + "/"


class FullPathAction(argparse.Action):
    """Expand user- and relative-paths"""

    def __call__(self, parser, namespace, values, option_string=None):
        if values is not None:
            setattr(namespace, self.dest, FullPath(values))
        else:
            setattr(namespace, self.dest, values)


class FullPathTrailingSlashAction(argparse.Action):
    """Expand user- and relative-paths and include the trailing slash"""

    def __call__(self, parser, namespace, values, option_string=None):
        if values is not None:
            setattr(
                namespace, self.dest, os.path.abspath(os.path.expanduser(values)) + "/"
            )
        else:
            setattr(namespace, self.dest, values)


# The kwargs in this type is overloaded.  Everything that is legit for argparse is allowed.
# Additionally, there is:
#
# range:list - two element list of the min and max allowed for an argument (inclusive).
# section:str - name of the section where the argument is loaded in the config file
# option_group:str - name of the option group to include the option in (for help)
# required:list of str - modules names for which thie option is required.  Also implies the option
#                        group "required"
# subparsers: list of str - list of sub-commands this argument belongs to
#
# options_t = collections.namedtuple(
#    "options_t", ("default_val", "group", "args", "var_type", "kwargs")
# )
@dataclasses.dataclass
class options_t:
    """Data that drives options processing"""

    default_val: typing.Any
    group: set
    args: tuple
    var_type: typing.Any
    kwargs: dict

    def __post_init__(self):
        """Type conversions"""
        if not isinstance(self.args, tuple):
            raise ValueError("args is not a tuple")
        if self.group is not None and not isinstance(self.group, set):
            self.group = set(self.group)
        if not isinstance(self.kwargs, dict):
            raise ValueError("kwargs is not a dict")


# TODO: convert all booleans - "action": argparse.BooleanOptionalAction,

global_options_dict = {
    "config_file_name": options_t(
        None,
        None,
        ("--config", "-c"),
        FullPath,
        {"help": "script configuration file", "action": FullPathAction},
    ),
    "base_log": options_t(
        None,
        None,
        ("--base_log",),
        str,
        {
            "help": "basestation log file, records all levels of notifications",
        },
    ),
    "debug": options_t(
        False,
        None,
        ("--debug",),
        bool,
        {
            "action": "store_true",
            "help": "log/display debug messages",
        },
    ),
    "verbose": options_t(
        False,
        None,
        (
            "--verbose",
            "-v",
        ),
        bool,
        {
            "action": "store_true",
            "help": "print status messages to stdout",
        },
    ),
    "quiet": options_t(
        False,
        None,
        (
            "--quiet",
            "-q",
        ),
        bool,
        {"action": "store_false", "help": "don't print status messages to stdout"},
    ),
    "basestation_etc": options_t(
        None,  # Updated below
        None,
        ("--basestation_etc",),
        FullPathTrailingSlash,
        {
            "help": "Basestation etc dirctory (master config)",
            "action": FullPathTrailingSlashAction,
        },
    ),
    #
    "mission_dir": options_t(
        None,
        (
            "Base",
            "BaseDotFiles",
            "BaseLogin",
            "BaseSMS",
            "FTPPush",
            "FlightModel",
            "GliderDAC",
            "GliderEarlyGPS",
            "GliderTrack",
            "MakeDiveProfiles",
            "MakeKML",
            "MakeMissionEngPlots",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "MakePositions",
            "MakePlot",
            "MakePlot2",
            "MakePlot3",
            "MakePlot4",
            "MakePlotMission",
            "MoveData",
            "Reprocess",
            "SimpleNetCDF",
            "ValidateDirectives",
            "Ver65",
            "WindRain",
        ),
        (
            "-m",
            "--mission_dir",
        ),
        FullPathTrailingSlash,
        {
            "help": "glider mission directory",
            "action": FullPathTrailingSlashAction,
            "required": (
                "Base",
                "BaseDotFiles",
                "BaseSMS",
                "BaseLogin",
                "FTPPush",
                "FlightModel",
                "GliderTrack",
                "MakeKML",
                "MakeMissionEngPlots",
                "MakeMissionProfile",
                "MakeMissionTimeSeries",
                "MakePositions",
                "MoveData",
                "MakePlotMission",
                "Reprocess",
                "ValidateDirectives",
                "Ver65",
            ),
        },
    ),
    "python": options_t(
        "python 3.9",
        ("FlightModel",),
        ("--python",),
        str,
        {
            "help": "path to python executable",
        },
    ),
    "delete_upload_files": options_t(
        False,
        ("Base",),
        ("--delete_upload_files",),
        bool,
        {
            "action": "store_true",
            "help": "Delete any successfully uploaded input files",
        },
    ),
    #
    "magcalfile": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
            "Reprocess",
        ),
        ("--magcalfile",),
        str,
        {
            "help": "compass cal file or search to use most recent version of tcm2mat.cal",
        },
    ),
    "auxmagcalfile": options_t(
        None,
        ("Base", "MakeDiveProfiles"),
        ("--auxmagcalfile",),
        str,
        {
            "help": "compass cal file or search to use most recent version of scicon.tcm",
        },
    ),
    #
    "instrument_id": options_t(
        0,
        (
            "Base",
            "FligthModel",
            "MakeDiveProfiles",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
        ),
        (
            "-i",
            "--instrument_id",
        ),
        int,
        {"help": "force instrument (glider) id"},
    ),
    "nice": options_t(
        0,
        (
            "Base",
            "FligthModel",
            "MakeDiveProfiles",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "Reprocess",
        ),
        ("--nice",),
        int,
        {"help": "processing priority level (niceness)"},
    ),
    "gzip_netcdf": options_t(
        False,
        (
            "Base",
            "MakeDiveProfiles",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "Reprocess",
        ),
        ("--gzip_netcdf",),
        bool,
        {
            "action": "store_true",
            "help": "gzip netcdf files",
        },
    ),
    #
    "profile": options_t(
        False,
        "bdkpt",
        ("--profile",),
        bool,
        {"action": "store_true", "help": "Profiles time to process"},
    ),
    #
    "ver_65": options_t(
        False,
        "bm",
        ("--ver_65",),
        bool,
        {
            "action": "store_true",
            "help": "Processes Version 65 glider format",
        },
    ),
    "bin_width": options_t(
        1.0,
        (
            "Base",
            "MakeDiveProfiles",
            "MakeMissionProfile",
        ),
        ("--bin_width",),
        float,
        {
            "help": "Width of bins",
        },
    ),
    "which_half": options_t(
        WhichHalf(3),
        ("Base", "MakeDiveProfiles", "MakeMissionProfile"),
        ("--which_half",),
        WhichHalf,
        {
            "help": "Which half of the profile to use - 1 down, 2 up, 3 both, 4 combine down and up",
        },
    ),
    "interval": options_t(
        0,
        "i",
        ("--interval",),
        int,
        {
            "help": "Interval in seconds between checks",
        },
    ),
    "daemon": options_t(
        None,
        ("Base", "GliderEarlyGPS", "GliderTrack"),
        ("--daemon",),
        bool,
        {"help": "Launch conversion as a daemon process", "action": "store_true"},
    ),
    "csh_pid": options_t(
        0,
        ("GliderEarlyGPS",),
        ("--csh_pid",),
        int,
        {
            "help": "PID of the login shell",
        },
    ),
    "ignore_lock": options_t(
        None,
        "bgij",
        ("--ignore_lock",),
        bool,
        {
            "help": "Ignore the lock file, if present",
            "action": "store_true",
        },
    ),
    "divetarballs": options_t(
        0,
        ("Base",),
        ("--divetarballs",),
        int,
        {
            "help": "Creates per-dive tarballs of processed files - 0 don't create, -1 create, > create fragments of specified size",
        },
    ),
    "local": options_t(
        None,
        ("Base",),
        ("--local",),
        bool,
        {
            "help": "Performs no remote operations (no .urls, .pagers, .mailer, etc.)",
            "action": "store_true",
        },
    ),
    "clean": options_t(
        None,
        ("Base",),
        ("--clean",),
        bool,
        {
            "help": "Clean up (delete) intermediate files from working (mission) directory after processing.",
            "action": "store_true",
        },
    ),
    "reply_addr": options_t(
        None,
        ("Base",),
        ("--reply_addr",),
        str,
        {
            "help": "Optional email address to be inserted into the reply to field email messages",
        },
    ),
    "domain_name": options_t(
        None,
        ("Base",),
        ("--domain_name",),
        str,
        {
            "help": "Optional domain name to use for email messages",
        },
    ),
    "web_file_location": options_t(
        None,
        ("Base",),
        ("--web_file_location",),
        str,
        {
            "help": "Optional location to prefix file locations in comp email messages",
        },
    ),
    #
    "force": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
            "Reprocess",
        ),
        ("--force",),
        bool,
        {
            "help": "Forces conversion of all dives",
            "action": "store_true",
        },
    ),
    "reprocess": options_t(
        None,
        ("Base",),
        ("--reprocess",),
        int,
        {"help": "Forces reprocessing of a specific dive number "},
    ),
    "make_dive_profiles": options_t(
        None,
        ("Base",),
        ("--make_dive_profiles",),
        bool,
        {
            "help": "Create the common profile data products",
            "action": "store_true",
        },
    ),
    "make_dive_pro": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
            "Reprocess",
        ),
        ("--make_dive_pro",),
        bool,
        {
            "help": "Create the dive profile in text format",
            "action": "store_true",
        },
    ),
    "make_dive_bpo": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
            "Reprocess",
        ),
        ("--make_dive_bpo",),
        bool,
        {
            "help": "Create the dive binned profile in text format",
            "action": "store_true",
        },
    ),
    "make_dive_netCDF": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
        ),
        ("--make_dive_netCDF",),
        bool,
        {
            "help": "Create the dive netCDF output file",
            "action": "store_true",
        },
    ),
    "make_mission_profile": options_t(
        None,
        (
            "Base",
            "Reprocess",
        ),
        ("--make_mission_profile",),
        bool,
        {
            "help": "Create mission profile output file",
            "action": "store_true",
        },
    ),
    "make_mission_timeseries": options_t(
        None,
        ("Base", "Reprocess"),
        ("--make_mission_timeseries",),
        bool,
        {
            "help": "Create mission timeseries output file",
            "action": "store_true",
        },
    ),
    "make_dive_kkyy": options_t(
        None,
        (
            "Base",
            "MakeDiveProfiles",
        ),
        ("--make_dive_kkyy",),
        bool,
        {
            "help": "Create the dive kkyy output files",
            "action": "store_true",
        },
    ),
    "skip_flight_model": options_t(
        None,
        ("Base",),
        ("--skip_flight_model",),
        bool,
        {
            "help": "Skip running flight model system (FMS)",
            "action": "store_true",
        },
    ),
    #
    "reprocess_plots": options_t(
        None,
        ("Reprocess",),
        ("--reprocess_plots",),
        bool,
        {
            "help": "Force reprocessing of plots (Reprocess.py only)",
            "action": "store_true",
        },
    ),
    "reprocess_flight": options_t(
        None,
        ("Reprocess",),
        ("--reprocess_flight",),
        bool,
        {
            "help": "Force reprocessing of flight (Reprocess.py only)",
            "action": "store_true",
        },
    ),
    #
    "home_dir": options_t(
        None,
        ("Commission",),
        ("--home_dir",),
        str,
        {
            "help": "home directory base, used by Commission.py",
        },
    ),
    "glider_password": options_t(
        None,
        ("Commission",),
        ("--glider_password",),
        str,
        {
            "help": "glider password, used by Commission.py",
        },
    ),
    "glider_group": options_t(
        None,
        ("Commission",),
        ("--glider_group",),
        str,
        {
            "help": "glider group, used by Commission.py",
        },
    ),
    "home_dir_group": options_t(
        None,
        ("Commission",),
        ("--home_dir_group",),
        str,
        {
            "help": "home dir group, used by Commission.py",
        },
    ),
    #
    "target_dir": options_t(
        None,
        ("MoveData",),
        ("--target_dir", "-t"),
        FullPath,
        {
            "help": "target directory, used by MoveData.py",
            "action": FullPathAction,
            "required": ("MoveData",),
        },
    ),
    #
    "encrypt": options_t(
        None,
        ("Base",),
        ("--encrypt",),
        bool,
        {
            "help": "encrypt the file",
            "action": "store_true",
        },
    ),
    # This is an option, but is now handled in code in each extension
    # Note - converting to this requires careful review to see how this would interfere
    # with other groups used to help command line help output
    # group = parser.add_mutually_exclusive_group(required=True)
    # group.add_argument('--mission_dir', )
    "netcdf_filename": options_t(
        None,
        (
            "GliderDAC",
            "MakePlot",
            "MakePlot2",
            "MakePlot3",
            "MakePlot4",
            "SimpleNetCDF",
            "StripNetCDF",
            "WindRain",
        ),
        ("netcdf_filename",),
        FullPath,
        {
            "help": "Name of netCDF file to process (only honored when --mission_dir is not specified)",
            "nargs": "?",
            "action": FullPathAction,
        },
    ),
    # Plotting related
    "plot_raw": options_t(
        False,
        (
            "Base",
            "MakePlot",
        ),
        ("--plot_raw",),
        bool,
        {
            "help": "Plot raw tmicl and pmar data,if available",
            "action": "store_true",
            "section": "makeplot",
            "option_group": "plotting",
        },
    ),
    "save_svg": options_t(
        False,
        (
            "Base",
            "MakePlot",
            "MakePlot2",
            "MakeMissionEngPlot",
        ),
        ("--save_svg",),
        bool,
        {
            "help": "Save SVG versions of plots (matplotlib output only)",
            "section": "makeplot",
            "action": "store_true",
            "option_group": "plotting",
        },
    ),
    "save_png": options_t(
        True,
        (
            "Base",
            "MakePlot3",
            "MakePlot4",
        ),
        ("--save_png",),
        bool,
        {
            "help": "Save PNG versions of plots (plotly output only)",
            "section": "makeplot",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "full_html": options_t(
        "darwin" in sys.platform,
        (
            "Base",
            "MakePlot3",
            "MakePlot4",
        ),
        ("--full_html",),
        bool,
        {
            "help": "Save stand alone html files (plotly output only)",
            "section": "makeplot",
            "action": "store_true",
            "option_group": "plotting",
        },
    ),
    "plot_freeze_pt": options_t(
        False,
        (
            "Base",
            "MakePlot",
            "MakePlot4",
        ),
        ("--plot_freeze_pt",),
        bool,
        {
            "help": "Plot the freezing point in TS diagrams",
            "section": "makeplot",
            "option_group": "plotting",
            "action": "store_true",
        },
    ),
    "plot_legato_use_glider_pressure": options_t(
        False,
        (
            "Base",
            "MakePlot3",
        ),
        ("--plot_legato_use_glider_pressure",),
        bool,
        {
            "help": "Use glider pressure for legato debug plots",
            "section": "makeplot",
            "action": "store_true",
            "option_group": "plotting",
        },
    ),
    "plot_directory": options_t(
        None,
        (
            "Base",
            "MakePlot",
            "MakePlot2",
            "MakePlot3",
            "MakePlot4",
            "MakeMissionEngPlots",
        ),
        ("--plot_directory",),
        FullPath,
        {
            "help": "Override default plot directory location",
            "section": "makeplot",
            "action": FullPathAction,
            "option_group": "plotting",
        },
    ),
    "pmar_logavg_max": options_t(
        1e2,
        ("Base", "MakePlot", "MakePlot4"),
        ("--pmar_logavg_max",),
        float,
        {
            "help": "Maximum value for pmar logavg plots y-range",
            "section": "makeplot",
            "range": [0.0, 1e10],
            "option_group": "plotting",
        },
    ),
    "pmar_logavg_min": options_t(
        1e-4,
        ("Base", "MakePlot", "MakePlot4"),
        ("--pmar_logavg_min",),
        float,
        {
            "help": "Minimum value for pmar logavg plots y-range",
            "section": "makeplot",
            "range": [0.0, 1e10],
            "option_group": "plotting",
        },
    ),
    "strip_list": options_t(
        None,
        ("StripNetCDF",),
        ("--strip_list",),
        str,
        {"help": "Prefixes of dimensions and variables to strip", "nargs": "+"},
    ),
    # KML related
    "paam_data_directory": options_t(
        None,
        (
            "Base",
            "MakeKML",
        ),
        ("--paam_data_directory",),
        FullPath,
        {
            "help": "Directory with PAAM whale detections",
            "action": FullPathAction,
            "section": "makekml",
            "option_group": "kml generation",
        },
    ),
    "paam_ici_percentage": options_t(
        0.25,
        (
            "Base",
            "MakeKML",
        ),
        ("--paam_ici_percentage",),
        float,
        {
            "help": "Threshold for displaying a detection in paam data",
            "range": [0.0, 1.0],
            "section": "makekml",
            "option_group": "kml generation",
        },
    ),
    "skip_points": options_t(
        10,
        (
            "Base",
            "MakeKML",
        ),
        ("--skip_points",),
        float,
        {
            "help": "Number of points to skip from gliders through the water track",
            "range": [0, 100],
            "section": "makekml",
            "option_group": "kml generation",
        },
    ),
    "color": options_t(
        "00ffff",
        (
            "Base",
            "MakeKML",
        ),
        ("--color",),
        str,
        {
            "help": "KML color string for color track",
            "section": "makekml",
            "option_group": "kml generation",
        },
    ),
    "targets": options_t(
        "all",
        (
            "Base",
            "MakeKML",
        ),
        ("--targets",),
        str,
        {
            "help": "What targets to plot",
            "choices": ["all", "current", "none"],
            "section": "makekml",
            "option_group": "kml generation",
        },
    ),
    "surface_track": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--surface_track",),
        bool,
        {
            "help": "Plot the gliders course as a surface track",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "subsurface_track": options_t(
        False,
        (
            "Base",
            "MakeKML",
        ),
        ("--subsurface_track",),
        bool,
        {
            "help": "Plot the gliders course as a subsurface track",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "drift_track": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--drift_track",),
        bool,
        {
            "help": "Plot the gliders drift track",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "proposed_targets": options_t(
        False,
        (
            "Base",
            "MakeKML",
        ),
        ("--proposed_targets",),
        bool,
        {
            "help": "Use the targets file instead of searching for the latest backup targets file",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "target_radius": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--target_radius",),
        bool,
        {
            "help": "Plot radius circle around targets",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "compress_output": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--compress_output",),
        bool,
        {
            "help": "Create KMZ output",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "plot_dives": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--plot_dives",),
        bool,
        {
            "help": "Plot data from per-dive netcdf files",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "simplified": options_t(
        False,
        (
            "Base",
            "MakeKML",
        ),
        ("--simplified",),
        bool,
        {
            "help": "Produces a slightly simplified version of the dive track",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "use_glider_target": options_t(
        True,
        (
            "Base",
            "MakeKML",
        ),
        ("--use_glider_target",),
        bool,
        {
            "help": "Use the glider's TGT_LAT/TGT_LON/TGT_RADIUS",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    "gliderdac_base_config": options_t(
        None,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_base_config",),
        FullPath,
        {
            "help": "GliderDAC base configuration JSON file - common for all Seagliders",
            "section": "gliderdac",
            "action": FullPathAction,
        },
    ),
    "gliderdac_project_config": options_t(
        None,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_project_config",),
        FullPath,
        {
            "help": "GliderDAC project configuration JSON file - common for single study area",
            "section": "gliderdac",
            "action": FullPathAction,
        },
    ),
    "gliderdac_deployment_config": options_t(
        None,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_deployment_config",),
        FullPath,
        {
            "help": "GliderDAC deployoment configuration JSON file - specific to the current glider deoployment",
            "section": "gliderdac",
            "action": FullPathAction,
        },
    ),
    "gliderdac_directory": options_t(
        None,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_directory",),
        FullPath,
        {
            "help": "Directory to place output files in",
            "section": "gliderdac",
            "action": FullPathAction,
        },
    ),
    "delayed_submission": options_t(
        False,
        (
            "Base",
            "GliderDAC",
        ),
        ("--delayed_submission",),
        FullPath,
        {
            "help": "Generated files for delayed submission",
            "section": "gliderdac",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    "gliderdac_bin_width": options_t(
        0.0,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_bin_width",),
        float,
        {
            "help": "Width of bins for GliderDAC file (0.0 indicates timeseries)",
            "section": "gliderdac",
        },
    ),
    "simplencf_bin_width": options_t(
        None,
        ("SimpleNetCDF",),
        ("--simplencf_bin_width",),
        float,
        {
            "help": "Bin SimpleNetCDF output to this size",
            "section": "simplenetcdf",
        },
    ),
    "simplencf_compress_output": options_t(
        None,
        ("SimpleNetCDF",),
        ("--simplencf_compress_output",),
        bool,
        {
            "help": "Compress the simple netcdf file",
            "action": "store_true",
        },
    ),
}

# Note: All option_group kwargs listed above must have an entry in this dictionary
option_group_description = {
    "required named arguments": None,
    "plotting": "Basestation plotting extension options",
    "kml generation": "Basestation KML extension options",
}


class BaseOptions:

    """
    BaseOptions: for use by all basestation code and utilities.
       Defaults are trumped by options listed in configuration file;
       config file options are trumped by command-line arguments.
    """

    def __init__(
        self,
        description,
        additional_arguments=None,
        alt_cmdline=None,
        add_arguments=None,
    ):
        """
        Input:
            additional_arguments - dictionay of additional arguments - sepcific
                                   to a single module
            alt_cmdline - alternate command line - this is a string of options
                          equivilent to sys.argv[1:]
            add_arguments - adds the calling_module to the list of .group set of that option
        """

        self._opts = None  # Retained for debugging
        self._ap = None  # Retailed for debugging

        self._subparsers = {}
        self._subparser = None

        calling_module = os.path.splitext(
            os.path.split(inspect.stack()[1].filename)[1]
        )[0]

        if additional_arguments is not None:
            # pre python 3.9    options_dict = {**global_options_dict, **additional_arguments}
            options_dict = global_options_dict | additional_arguments
        else:
            options_dict = global_options_dict

        if add_arguments is not None:
            for add_arg in add_arguments:
                options_dict[add_arg].group.add(calling_module)

        basestation_directory, _ = os.path.split(
            os.path.abspath(os.path.expanduser(sys.argv[0]))
        )
        self.basestation_directory = basestation_directory  # make avaiable
        # add path to load common basestation modules from subdirectories
        sys.path.append(basestation_directory)

        # Update default config location
        options_dict["basestation_etc"] = dataclasses.replace(
            options_dict["basestation_etc"],
            **{
                "default_val": FullPathTrailingSlash(
                    os.path.join(self.basestation_directory, "etc")
                ),
            },
        )
        cp_default = {}
        for k, v in options_dict.items():
            setattr(self, k, v.default_val)  # Set the default for the object
            # cp_default[k] = v.default_val
            cp_default[k] = None

        cp = configparser.RawConfigParser(cp_default)

        ap = argparse.ArgumentParser(description=description)

        # Build up group dictionary
        option_group_set = set()
        for k, v in options_dict.items():
            if v.group is None or calling_module in v.group:
                if "option_group" in v.kwargs.keys():
                    option_group_set.add(v.kwargs["option_group"])
                if (
                    "required" in v.kwargs.keys()
                    and isinstance(v.kwargs["required"], tuple)
                    and calling_module in v.kwargs["required"]
                ):
                    option_group_set.add("required named arguments")

        option_group_dict = {}
        for gg in option_group_set:
            option_group_dict[gg] = ap.add_argument_group(
                gg, option_group_description[gg]
            )

        # Loop over potential arguments and add what is approriate
        parser = None
        for k, v in options_dict.items():
            if v.group is None or calling_module in v.group:
                kwargs_tmp = copy.deepcopy(v.kwargs)

                if "subparsers" in kwargs_tmp.keys():
                    parsers = []
                    if not self._subparser:
                        self._subparser = ap.add_subparsers(
                            help="sub-command help", dest="subparser_name"
                        )
                    for subparser in kwargs_tmp["subparsers"]:
                        if subparser not in self._subparsers:
                            self._subparsers[subparser] = self._subparser.add_parser(
                                subparser
                            )
                        parsers.append(self._subparsers[subparser])
                    del kwargs_tmp["subparsers"]
                else:
                    parsers = [ap]

                for parser in parsers:
                    kwargs = copy.deepcopy(kwargs_tmp)
                    if not (v.var_type == bool and "action" in v.kwargs.keys()):
                        kwargs["type"] = v.var_type
                    if v.args and v.args[0].startswith("-"):
                        kwargs["dest"] = k
                    kwargs["default"] = None
                    if "section" in kwargs.keys():
                        del kwargs["section"]
                    if "required" in kwargs.keys() and isinstance(
                        kwargs["required"], tuple
                    ):
                        kwargs["required"] = calling_module in kwargs["required"]
                    if (
                        "range" in kwargs.keys()
                        and isinstance(kwargs["range"], list)
                        and len(kwargs["range"]) == 2
                    ):
                        min_val = kwargs["range"][0]
                        max_val = kwargs["range"][1]
                        kwargs["action"] = generate_range_action(k, min_val, max_val)
                        del kwargs["range"]
                        kwargs["metavar"] = f"{{{min_val}..{max_val}}}"

                    arg_list = v.args
                    if "option_group" in kwargs.keys():
                        og = kwargs["option_group"]
                        del kwargs["option_group"]
                        option_group_dict[og].add_argument(*arg_list, **kwargs)
                    elif "required" in kwargs and kwargs["required"]:
                        option_group_dict["required named arguments"].add_argument(
                            *arg_list, **kwargs
                        )
                    else:
                        parser.add_argument(*arg_list, **kwargs)
                    del kwargs

        self._ap = ap

        # self._opts, self._args = ap.parse_known_args()
        if alt_cmdline is not None:
            self._opts = ap.parse_args(alt_cmdline.split())
        else:
            self._opts = ap.parse_args()

        if "subparser_name" in self._opts:
            self.subparser_name = self._opts.subparser_name

        # handle the config file first, then see if any args trump them
        if self._opts.config_file_name is not None:
            try:
                cp.read(self._opts.config_file_name)
            except Exception as exc:
                raise RuntimeError(
                    f"ERROR parsing {self._opts.config_file_name}"
                ) from exc
            else:
                for k, v in options_dict.items():
                    if k == "config_file_name":
                        continue
                    if v.group is None or calling_module in v.group:
                        try:
                            if "section" in v.kwargs:
                                section_name = v.kwargs["section"]
                            else:
                                section_name = "base"
                            value = cp.get(section_name, k)
                            # if value == v.default_val:
                            if value is None:
                                continue
                        except:
                            pass
                        else:
                            try:
                                val = v.var_type(value)
                            except ValueError as exc:
                                raise "Could not convert %s from %s to requested type" % (
                                    k,
                                    self.config_file_name,
                                ) from exc
                            else:
                                if (
                                    "range" in v.kwargs.keys()
                                    and isinstance(v.kwargs["range"], list)
                                    and len(v.kwargs["range"]) == 2
                                ):
                                    min_val = v.kwargs["range"][0]
                                    max_val = v.kwargs["range"][1]
                                    if not min_val <= val <= max_val:
                                        raise f"{val} outside of range {min_val} {max_val}"

                                setattr(self, k, val)

        # Anything set on the command line trumps
        for opt in dir(self._opts):
            if opt in options_dict.keys() and getattr(self._opts, opt) is not None:
                setattr(self, opt, getattr(self._opts, opt))

        # A bit of a hack
        if self.make_dive_profiles:
            self.make_dive_netCDF = True


if __name__ == "__main__":
    return_val = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        additional_args = {
            # "netcdf_filename": options_t(
            #     None,
            #     ("BaseOpts",),
            #     ("netcdf_filename",),
            #     str,
            #     {
            #         "help": "Name of netCDF file to process (only used if --mission_dir is not specified)",
            #         "nargs": "?",
            #     },
            # ),
            "port": options_t(
                1234,
                ("BaseOpts",),
                ("port",),
                int,
                {"help": "Network Port", "nargs": "?", "range": [0, 6000]},
            ),
        }
        base_opts = BaseOptions(
            "Basestation Options Test", additional_arguments=additional_args
        )
    except SystemExit:
        pass
    except:
        _, _, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)
    else:
        print("Quiet value ", base_opts.quiet)
        print("Verbose value ", base_opts.verbose)
        # print("netcdf_filename ", base_opts.netcdf_filename)
        print("port", base_opts.port)
