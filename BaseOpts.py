#/! /usr/bin/env python
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

"""
  Common set of options for all basestation processing
  Default values supplemented by option processing, both config file and command line
"""

# TODO Review help strings - mark all extensions as extensions not command line
# TODO Final pass - remove all command-line help from docstrings, check that all base_opts.members are covered, any required arguments are marked as sch
# TODO Compare Base.py help vs help output
# TODO Write a script to generate all the help output into files in help directory
# TODO Figure out how to show defaults in option help (https://stackoverflow.com/questions/12151306/argparse-way-to-include-default-values-in-help)

import argparse
import collections
import configparser
import copy
import dataclasses
import inspect
import os
import pdb
import sys
import time
import traceback
import typing

import Plotting
from Globals import WhichHalf  # basestation_version

# Populate default plots with every plot registered in Plotting
dive_plot_list = list(Plotting.dive_plot_funcs.keys())
mission_plot_list = list(Plotting.mission_plot_funcs.keys())


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
    # This catches the case for a nargs=? argument that is FullPath type and the argument
    # is not specified on the command line.  In this case, the default value is returned,
    # but since our default is and empty stirng, it gets run through this helper and converted
    # - so, don't do that.
    if x == "":
        return x

    if isinstance(x, list):
        return list(map(lambda y: os.path.abspath(os.path.expanduser(y)), x))
    else:
        return os.path.abspath(os.path.expanduser(x))


def FullPathTrailingSlash(x):
    """Expand user- and relative-paths and include the trailing slash"""
    if x == "":
        return x

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


def generate_sample_conf_file(options_dict, calling_module):
    """Generates a sample .conf file (to stdout)"""
    sort_options_dict = dict(
        sorted(
            options_dict.items(),
            key=lambda x: x[1].kwargs["section"] if "section" in x[1].kwargs else "",
        )
    )

    seen_sections = set()

    print(f"#\n# Sample conf file for {calling_module}.py\n#")
    print(f"# Generated with python {calling_module}.py --generate_sample_conf\n#")
    print("[base]")

    for opt_n, opt_v in sort_options_dict.items():
        if opt_n in ("config_file_name", "generate_sample_conf"):
            continue
        if opt_v.group is None or calling_module in opt_v.group:
            section_name = opt_v.kwargs["section"] if "section" in opt_v.kwargs else ""
            if section_name not in seen_sections and section_name:
                print(f"#\n[{section_name}]")
                seen_sections.add(section_name)
            print(f"#\n# {opt_v.kwargs['help']}")
            # pdb.set_trace()
            print(f"#{opt_n} = ", end="")
            if opt_v.var_type is bool:
                print(f"{int(opt_v.default_val)}")
            elif opt_v.var_type is FullPath:
                print("<path_to_file>")
            elif opt_v.var_type is FullPathTrailingSlash:
                print("<path_to_directory>")
            elif isinstance(opt_v.default_val, list):
                # or isinstance(
                #     opt_v.default_val, collections.abc.KeysView
                # ):
                for itm in opt_v.default_val:
                    print(f"{itm},", end="")
                print("")
            else:
                print(f"{opt_v.default_val}")


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


global_options_dict = {
    "generate_sample_conf": options_t(
        False,
        None,
        ("--generate_sample_conf",),
        bool,
        {
            "help": "Generates a sample conf file to stdout",
            "action": "store_true",
        },
    ),
    "config_file_name": options_t(
        None,  # Okay to be None - this is never added to the options object, just used by the argparse
        None,
        ("--config", "-c"),
        FullPath,
        {"help": "script configuration file", "action": FullPathAction},
    ),
    "base_log": options_t(
        "",
        None,
        ("--base_log",),
        FullPath,
        {
            "help": "basestation log file, records all levels of notifications",
            "action": FullPathAction,
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
    "group_etc": options_t(
        None,  # Updated below
        None,
        ("--group_etc",),
        FullPathTrailingSlash,
        {
            "help": "etc dirctory for a collection of Seagliders",
            "action": FullPathTrailingSlashAction,
        },
    ),
    "add_sqlite": options_t(
        True,
        ("Base",),
        ("--add_sqlite",),
        bool,
        {
            "help": "Add netcdf files to mission sqlite db",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    "run_bogue": options_t(
        False,
        ("Base",),
        ("--run_bogue",),
        bool,
        {
            "help": "Run Bogue processing on files transferred via XMODEM",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    #
    "mission_dir": options_t(
        "",
        (
            "Base",
            "BaseCtrlFiles",
            "BaseDB",
            "BaseDotFiles",
            "BaseLogin",
            "BasePlot",
            "BaseSMS",
            "CommLog",
            "FTPPush",
            "FlightModel",
            "GliderDAC",
            "GliderEarlyGPS",
            "GliderTrack",
            "KKYY",
            "MakeDiveProfiles",
            "MakeKML",
            "MakeMissionEngPlots",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "MakePositions",
            "MakePlotMission",
            "MoveData",
            "Reprocess",
            "SimpleNetCDF",
            "ValidateDirectives",
            "Ver65",
            "WindRain",
            "RegressVBD",
            "Magcal",
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
                "BaseCtrlFiles",
                "BaseDB",
                "BaseDotFiles",
                "BasePlot",
                "BaseSMS",
                "BaseLogin",
                "CommLog",
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
                "RegressVBD",
                "Magcal",
            ),
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
        "",
        (
            "Base",
            "MakeDiveProfiles",
            "Reprocess",
        ),
        ("--magcalfile",),
        FullPath,
        {
            "help": "compass cal file or search to use most recent version of tcm2mat.cal",
            "action": FullPathAction,
        },
    ),
    "auxmagcalfile": options_t(
        "",
        ("Base", "MakeDiveProfiles", "Reprocess"),
        ("--auxmagcalfile",),
        FullPath,
        {
            "help": "compass cal file or search to use most recent version of scicon.tcm",
            "action": FullPathAction,
        },
    ),
    #
    "instrument_id": options_t(
        0,
        (
            "Base",
            "BaseDB",
            "BasePlot",
            "CommLog",
            "GliderEarlyGPS",
            "FligthModel",
            "MakeDiveProfiles",
            "MakeKML",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "MakePlotMission",
            "MoveData",
            "NewMission",
            "Reprocess",
            "RegressVBD",
            "Magcal",
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
            "BasePlot",
            "FlightModel",
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
        None,
        ("--profile",),
        bool,
        {"action": "store_true", "help": "Profiles time to process"},
    ),
    #
    "ver_65": options_t(
        False,
        None,
        ("--ver_65",),
        bool,
        {
            "action": "store_true",
            "help": "Processes Version 65 glider format",
        },
    ),
    "bin_width": options_t(
        1.0,
        ("Base", "MakeMissionProfile", "MakePlotMission"),
        ("--bin_width",),
        float,
        {
            "help": "Width of bins",
        },
    ),
    "which_half": options_t(
        WhichHalf(3),
        ("Base", "MakeMissionProfile", "MakePlotMission"),
        ("--which_half",),
        WhichHalf,
        {
            "help": "Which half of the profile to use - 1 down, 2 up, 3 both, 4 combine down and up",
        },
    ),
    "daemon": options_t(
        False,
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
        False,
        ("Base", "BaseRunner", "GliderEarlyGPS"),
        ("--ignore_lock",),
        bool,
        {
            "help": "Ignore the lock file, if present",
            "action": "store_true",
        },
    ),
    "use_gsw": options_t(
        True,
        ("Base", "BasePlot", "FlightModel", "MakeDiveProfiles", "Reprocess"),
        ("--use_gsw",),
        bool,
        {
            "help": "Uses the GSW toolbox for all oceanographic calculations.  False uses the seawater toolkit",
            "action": argparse.BooleanOptionalAction,
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
        False,
        ("Base",),
        ("--local",),
        bool,
        {
            "help": "Performs no remote operations (no .urls, .pagers, .mailer, etc.)",
            "action": "store_true",
        },
    ),
    "clean": options_t(
        False,
        ("Base",),
        ("--clean",),
        bool,
        {
            "help": "Clean up (delete) intermediate files from working (mission) directory after processing.",
            "action": "store_true",
        },
    ),
    "reply_addr": options_t(
        "",
        (
            "Base",
            "BaseCtrlFiles",
            "BaseDotFiles",
            "BaseSMS",
            "BaseSMS_IMAP",
            "GliderEarlyGPS",
        ),
        ("--reply_addr",),
        str,
        {
            "help": "Optional email address to be inserted into the reply to field email messages",
        },
    ),
    "domain_name": options_t(
        "",
        (
            "Base",
            "BaseCtrlFiles",
            "BaseDotFiles",
            "BaseSMS",
            "BaseSMS_IMAP",
            "GliderEarlyGPS",
        ),
        ("--domain_name",),
        str,
        {
            "help": "Optional domain name to use for email messages",
        },
    ),
    "vis_base_url": options_t(
        "",
        ("Base", "Reprocess", "MakeKML", "BaseCtrlFiles", "CommLog", "GliderEarlyGPS"),
        ("--vis_base_url",),
        str,
        {
            "help": "Base URL of visualization server for building links in KML and notifications",
        },
    ),
    #
    "force": options_t(
        False,
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
        False,
        ("Base", "MakeDiveProfiles", "Reprocess"),
        ("--reprocess",),
        int,
        {"help": "Forces reprocessing of a specific dive number "},
    ),
    "make_dive_profiles": options_t(
        True,
        ("Base",),
        ("--make_dive_profiles",),
        bool,
        {
            "help": "Create the common profile data products",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    "make_mission_profile": options_t(
        False,
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
        False,
        ("Base", "Reprocess"),
        ("--make_mission_timeseries",),
        bool,
        {
            "help": "Create mission timeseries output file",
            "action": "store_true",
        },
    ),
    # DOC Skips running the flight model system.  FMS is still consulted for flight
    # DOC values such as volmax hd_a, hd_b, hd_c etc. - if there is a previous previous estimates
    # DOC in flight, those are used - otherwise the system defaults are used.  Normally, this option
    # DOC is used when calling Reprocess.py or MakeDiveProfiles.py during post pocessing to regenerated
    # DOC netcdf files with already generated data in the flight directory
    "skip_flight_model": options_t(
        False,
        ("Base", "FlightModel", "Reprocess"),
        ("--skip_flight_model",),
        bool,
        {
            "help": "Skip running flight model system (FMS) - honor all sg_calib_constants.m variables",
            "action": "store_true",
        },
    ),
    # DOC FMS is not consulted for flight variables.  The user must supply
    # DOC volmax, vbdbias, hd_a, hd_b, hd_c and optionally hd_s, rho0, abs_compress, therm_expan, temp_ref
    # DOC in sg_calib_constants.m.
    "ignore_flight_model": options_t(
        False,
        (
            "Base",
            "BasePlot",
            "FlightModel",
            "MakeDiveProfiles",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "Reprocess",
            "BaseDB",
        ),
        ("--ignore_flight_model",),
        bool,
        {
            "help": "Ignore values derived from FlightModel - honor all sg_calib_constants.m variables.  Setting this option implies --skip_flight_model",
            "action": "store_true",
        },
    ),
    # DOC Used in re-processing glider test missions for the purpose of generating a volmax compatible with previous
    # DOC regression scripts.
    "fm_isopycnal": options_t(
        False,
        ("Base", "Reprocess", "FlightModel"),
        ("--fm_isopycnal",),
        bool,
        {
            "help": "Run flight model using potential density (instead of in-situ) and ignore compressibilty and thermal effects",
            "action": "store_true",
        },
    ),
    # DOC Moving the flight directory out of the way initiates a clean slate for subsequent processing
    "backup_flight": options_t(
        False,
        ("Base", "Reprocess"),
        ("--backup_flight",),
        bool,
        {
            "help": "Back up flight directory prior to run",
            "action": "store_true",
        },
    ),
    "fm_reprocess_dives": options_t(
        True,
        ("Base", "FlightModel", "Reprocess"),
        ("--fm_reprocess_dives",),
        bool,
        {
            "help": "Allow FlightModel to reprocess dives when it calculates new parameters",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    "skip_kml": options_t(
        False,
        ("Base", "Reprocess"),
        ("--skip_kml",),
        bool,
        {
            "help": "Skip generation of the KML output",
            "action": "store_true",
        },
    ),
    #
    "reprocess_plots": options_t(
        False,
        ("Reprocess",),
        ("--reprocess_plots",),
        bool,
        {
            "help": "Force reprocessing of plots",
            "action": "store_true",
        },
    ),
    #
    "target_dir": options_t(
        "",
        ("MoveData", "MakeDiveProfiles", "Reprocess"),
        ("--target_dir", "-t"),
        FullPath,
        {
            "help": "target directory, used by MoveData.py",
            "action": FullPathAction,
            "required": ("MoveData",),
        },
    ),
    # This is an option, but is now handled in code in each extension
    # Note - converting to this requires careful review to see how this would interfere
    # with other groups used to help command line help output
    # group = parser.add_mutually_exclusive_group(required=True)
    # group.add_argument('--mission_dir', )
    "netcdf_filename": options_t(
        "",
        (
            "Base",
            "GliderDAC",
            "KKYY",
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
        ("Base", "BasePlot", "Reprocess"),
        ("--plot_raw",),
        bool,
        {
            "help": "Plot raw tmicl and pmar data,if available",
            "action": "store_true",
            "section": "plotting",
            "option_group": "plotting",
        },
    ),
    "save_svg": options_t(
        False,
        (
            "Base",
            "BasePlot",
            "Reprocess",
            "MakeMissionEngPlot",
            "MakePlotTSProfile",
        ),
        ("--save_svg",),
        bool,
        {
            "help": "Save SVG versions of plots (matplotlib output only)",
            "section": "plotting",
            "action": "store_true",
            "option_group": "plotting",
        },
    ),
    "save_png": options_t(
        False,
        (
            "Base",
            "BasePlot",
            "MakePlotTSProfile",
            "Reprocess",
        ),
        ("--save_png",),
        bool,
        {
            "help": "Save PNG versions of plots (plotly output only)",
            "section": "plotting",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "save_jpg": options_t(
        False,
        ("Base", "BasePlot", "MakePlotTSProfile", "Reprocess"),
        ("--save_jpg",),
        bool,
        {
            "help": "Save JPEG versions of plots (plotly output only)",
            "section": "plotting",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "save_webp": options_t(
        True,
        ("Base", "BasePlot", "MakePlotTSProfile", "Reprocess"),
        ("--save_webp",),
        bool,
        {
            "help": "Save  versions of plots (plotly output only)",
            "section": "plotting",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "compress_div": options_t(
        True,
        ("Base", "BasePlot", "MakePlotTSProfile", "Reprocess"),
        ("--compress_div",),
        bool,
        {
            "help": "Save stand alone html files (plotly output only)",
            "section": "plotting",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "full_html": options_t(
        # "darwin" in sys.platform,
        False,
        (
            "Base",
            "BasePlot",
            "MakePlotTSProfile",
            "Reprocess",
        ),
        ("--full_html",),
        bool,
        {
            "help": "Save stand alone html files (plotly output only)",
            "section": "plotting",
            "action": argparse.BooleanOptionalAction,
            "option_group": "plotting",
        },
    ),
    "plot_freeze_pt": options_t(
        False,
        ("Base", "BasePlot", "Reprocess"),
        ("--plot_freeze_pt",),
        bool,
        {
            "help": "Plot the freezing point in TS diagrams",
            "section": "plotting",
            "option_group": "plotting",
            "action": "store_true",
        },
    ),
    "plot_legato_use_glider_pressure": options_t(
        False,
        ("Base", "BasePlot", "Reprocess"),
        ("--plot_legato_use_glider_pressure",),
        bool,
        {
            "help": "Use glider pressure for legato debug plots",
            "section": "plotting",
            "action": "store_true",
            "option_group": "plotting",
        },
    ),
    "plot_directory": options_t(
        "",
        (
            "Base",
            "BaseDB",
            "BasePlot",
            "MakeMissionEngPlots",
            "MakePlotTSProfile",
            "Reprocess",
        ),
        ("--plot_directory",),
        FullPath,
        {
            "help": "Override default plot directory location",
            "section": "plotting",
            "action": FullPathAction,
            "option_group": "plotting",
        },
    ),
    "pmar_logavg_max": options_t(
        1e2,
        ("Base", "BasePlot", "Reprocess"),
        ("--pmar_logavg_max",),
        float,
        {
            "help": "Maximum value for pmar logavg plots y-range",
            "section": "plotting",
            "range": [0.0, 1e10],
            "option_group": "plotting",
        },
    ),
    "pmar_logavg_min": options_t(
        1e-4,
        ("Base", "BasePlot", "Reprocess"),
        ("--pmar_logavg_min",),
        float,
        {
            "help": "Minimum value for pmar logavg plots y-range",
            "section": "plotting",
            "range": [0.0, 1e10],
            "option_group": "plotting",
        },
    ),
    "flip_ad2cp": options_t(
        True,
        ("Base", "BasePlot", "Reprocess"),
        ("--flip_ad2cp",),
        bool,
        {
            "help": "Rotate the pitch/roll/heading for the adc2p compass output plot",
            "section": "plotting",
            "option_group": "plotting",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    # Core plotting routines
    "dive_plots": options_t(
        dive_plot_list,
        (
            "Base",
            "BaseDB",
            "BasePlot",
            "Reprocess",
        ),
        ("--dive_plots",),
        str,
        {
            "help": "Which dive plots to produce",
            "nargs": "*",
            "section": "plotting",
            "choices": list(Plotting.dive_plot_funcs.keys()),
            "option_group": "plotting",
        },
    ),
    "mission_plots": options_t(
        mission_plot_list,
        ("Base", "BaseDB", "BasePlot", "Reprocess"),
        ("--mission_plots",),
        str,
        {
            "help": "Which mission plots to produce",
            "nargs": "*",
            "section": "plotting",
            "choices": list(Plotting.mission_plot_funcs.keys()),
            "option_group": "plotting",
        },
    ),
    "plot_types": options_t(
        [
            "dives",
            "mission",
        ],
        ("Base", "BasePlot", "Reprocess"),
        ("--plot_types",),
        str,
        {
            "help": "Which type of plots to generate",
            "option_group": "plotting",
            "section": "plotting",
            "nargs": "+",
            "choices": ["none", "dives", "mission"],
        },
    ),
    "mission_energy_reserve_percent": options_t(
        0.15,
        ("Base", "BaseDB", "BasePlot", "Reprocess"),
        ("--mission_energy_reserve_percent",),
        float,
        {
            "help": "For Mission Energy projection, what is the battery reserve",
            "option_group": "plotting",
        },
    ),
    "mission_energy_dives_back": options_t(
        10,
        ("Base", "BaseDB", "BasePlot", "Reprocess"),
        ("--mission_energy_dives_back",),
        int,
        {
            "help": "For Mission Energy projection, how many dives back to fit",
            "option_group": "plotting",
        },
    ),
    "mission_trends_dives_back": options_t(
        10,
        ("Base", "BaseDB", "BasePlot", "Reprocess"),
        ("--mission_trends_dives_back",),
        int,
        {
            "help": "For diagnostic change detectors (int P, volmax), ..., how many dives back to fit",
            "option_group": "plotting",
        },
    ),
    # End plotting related
    "strip_list": options_t(
        ["tmicl_", "pmar_"],
        ("StripNetCDF",),
        ("--strip_list",),
        str,
        {"help": "Prefixes of dimensions and variables to strip", "nargs": "+"},
    ),
    # MakeKML related
    "skip_points": options_t(
        10,
        (
            "Base",
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
            "Reprocess",
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
        False,
        (
            "Base",
            "Reprocess",
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
    "add_kml": options_t(
        "",
        (
            "MakeKML",
        ),
        ("--add_kml",),
        str,
        {
            "help": "list of python module.func that provide additional KML",
            "nargs": "*",
            "section": "makekml",
        },
    ),
    "merge_ssh": options_t(
        True,
        (
            "Base",
            "Reprocess",
            "MakeKML",
        ),
        ("--merge_ssh",),
        bool,
        {
            "help": "Merge in glider SSH kmz",
            "section": "makekml",
            "action": argparse.BooleanOptionalAction,
            "option_group": "kml generation",
        },
    ),
    # End MakeKML
    "gliderdac_base_config": options_t(
        "",
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
        "",
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
        "",
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
        "",
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
    "gliderdac_reduce_output": options_t(
        True,
        (
            "Base",
            "GliderDAC",
        ),
        ("--gliderdac_reduce",),
        bool,
        {
            "help": "Reduce the output to only non-nan observations (not useful with non-CT data)",
            "section": "gliderdac",
            "action": argparse.BooleanOptionalAction,
        },
    ),
    "simplencf_bin_width": options_t(
        0.0,
        (
            "Base",
            "SimpleNetCDF",
        ),
        ("--simplencf_bin_width",),
        float,
        {
            "help": "Bin SimpleNetCDF output to this size",
            "section": "simplenetcdf",
        },
    ),
    "simplencf_compress_output": options_t(
        False,
        (
            "Base",
            "SimpleNetCDF",
        ),
        ("--simplencf_compress_output",),
        bool,
        {
            "help": "Compress the simple netcdf file",
            "action": "store_true",
        },
    ),
    "network_log_decompressor": options_t(
        "",
        (
            "Base",
            "BaseNetwork",
            "NetworkWatch",
        ),
        ("--network_log_decompressor",),
        FullPath,
        {
            "help": "Compressed logfile decompressor path",
            "section": "network",
            "action": FullPathAction,
        },
    ),
}

# Note: All option_group kwargs listed above must have an entry in this dictionary
option_group_description = {
    "required named arguments": None,
    "plotting": "Basestation plotting extension options",
    "kml generation": "Basestation KML extension options",
}


class CustomFormatter(
    argparse.ArgumentDefaultsHelpFormatter, argparse.RawDescriptionHelpFormatter
):
    """Allow for multiple formatters for help"""


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
        calling_module=None,
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

        if calling_module is None:
            calling_module = os.path.splitext(
                os.path.split(inspect.stack()[1].filename)[1]
            )[0]

        if additional_arguments is not None:
            # pre python 3.9    options_dict = {**global_options_dict, **additional_arguments}
            options_dict = global_options_dict | additional_arguments
        else:
            options_dict = global_options_dict

        if "--generate_sample_conf" in sys.argv:
            # Generate a sample conf file and exit
            generate_sample_conf_file(options_dict, calling_module)
            sys.exit(0)

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
        # options_dict["group_etc"] = dataclasses.replace(
        #     options_dict["group_etc"],
        #     **{
        #         "default_val": FullPathTrailingSlash(
        #             os.path.join(self.basestation_directory, "etc")
        #         ),
        #     },
        # )
        cp_default = {}
        for k, v in options_dict.items():
            if v.group is None or calling_module in v.group:
                setattr(self, k, v.default_val)  # Set the default for the object
            # cp_default[k] = v.default_val
            cp_default[k] = None

        cp = configparser.RawConfigParser(cp_default)

        ap = argparse.ArgumentParser(
            description=description, formatter_class=CustomFormatter
        )

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
                    # GBS 2022/12/12 Added in the default value to the --help output would look
                    # appropriate.
                    #
                    # kwargs["default"] = None
                    kwargs["default"] = v.default_val
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

            if self._subparsers:
                sub_cmd_help_list = "sub-commands usage:\n"
                for _, sb in self._subparsers.items():
                    sub_cmd_help_list += f"  {sb.format_usage()[7:]}"
                ap.epilog = sub_cmd_help_list

        self._ap = ap

        if alt_cmdline is not None:
            self._opts = ap.parse_args(alt_cmdline.split())
        else:
            self._opts = ap.parse_args()

        if "subparser_name" in self._opts:
            self.subparser_name = self._opts.subparser_name

        # Change from previous - config file trumps command line
        # Two reasons:
        # 1) Change to display default values in the --help messages by setting the default value
        #    means there is now way to determine if a option was a default or explictly set.  Thus
        #    the config file values would be overridden in the event there was a non-None default value
        # 2) In practical terms, current useage is - set a master set of command line options for all gliders
        #    on a basestation, but customize with the config file in each glider directory.  Given the previous
        #    setup, this is not possible to override a global command line option.

        # Initialize the object with the results of the command line parse
        for opt in dir(self._opts):
            if opt in options_dict.keys():
                setattr(self, opt, getattr(self._opts, opt))

        # Process the config file, updating the object
        if self._opts.config_file_name is not None:
            if not os.path.exists(self._opts.config_file_name):
                setattr(self, "config_file_not_found", True)
                # raise FileNotFoundError(
                #    f"Config file {self._opts.config_file_name} does not exist"
                # )
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
                            if v.var_type == bool:
                                try:
                                    value = cp.getboolean(section_name, k)
                                except ValueError as exc:
                                    raise "Could not convert %s from %s to boolean" % (
                                        k,
                                        self._opts.config_file_name,
                                    ) from exc
                            else:
                                value = cp.get(section_name, k)
                                if isinstance(v.default_val, list):
                                    try:
                                        value = [
                                            x.rstrip().lstrip()
                                            for x in value.split(",")
                                        ]
                                    except Exception as exc:
                                        raise (
                                            "Could not convert %s from %s to a list"
                                            % (
                                                k,
                                                self._opts.config_file_name,
                                            )
                                        ) from exc
                                elif v.var_type is FullPath:
                                    value = FullPath(value)
                                elif v.var_type is FullPathTrailingSlash:
                                    value = FullPathTrailingSlash(value)
                            # if value == v.default_val:
                            if value is None:
                                continue
                        except Exception:
                            pass
                        else:
                            if isinstance(v.default_val, list):
                                # Code above has converted list types into an appropriate list
                                setattr(self, k, value)
                            else:
                                try:
                                    val = v.var_type(value)
                                except ValueError as exc:
                                    # raise f"Could not convert {k} from {self._opts.config_file_name} to requested type" from exc
                                    raise ValueError(
                                        f"Could not convert {k} from {self._opts.config_file_name} to requested type"
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

        # Update any options that affect other options
        if (
            hasattr(self, "ignore_flight_model")
            and hasattr(self, "skip_flight_model")
            and self.ignore_flight_model
        ):
            self.skip_flight_model = True

        # Previous version anything set on the command line or via default value trumps config file
        # for opt in dir(self._opts):
        #    if opt in options_dict.keys() and getattr(self._opts, opt) is not None:
        #        setattr(self, opt, getattr(self._opts, opt))

        # DEBUG - dump the objects contents
        # for opt in dir(self):
        #     if opt in options_dict.keys():
        #         value = getattr(self, opt)
        #         print(f"{opt}:{value}")


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
    except Exception:
        _, _, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)
    else:
        print("Quiet value ", base_opts.quiet)
        print("Verbose value ", base_opts.verbose)
        # print("netcdf_filename ", base_opts.netcdf_filename)
        print("port", base_opts.port)
