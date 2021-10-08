#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2021 by University of Washington.  All rights reserved.
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

# TODO Final pass - remove all command-line help from docstrings, check that all base_opts.members are covered, any required arguments are marked as sch

import argparse
import collections
import copy
import configparser
import inspect
import os
import pdb
import sys
import time
import traceback

from Globals import WhichHalf  # basestation_version


def generate_range_action(arg, min_val, max_val):
    """Creates an range checking action for argparse"""

    class RangeAction(argparse.Action):
        """Range checking action"""

        def __call__(self, parser, namespace, values, option_string=None):
            if not min_val <= values <= max_val:
                raise argparse.ArgumentError(
                    self, f"{values} not in range for argument [{arg}]"
                )
            setattr(namespace, self.dest, values)

    return RangeAction


def FullPath(x):
    """Expand user- and relative-paths"""
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
#
options_t = collections.namedtuple(
    "options_t", ("default_val", "group", "args", "var_type", "kwargs")
)

# TODO: change when we move to 3.9 or later for all booleans
# "action": argparse.BooleanOptionalAction,

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
    #
    "mission_dir": options_t(
        None,
        (
            "Base",
            "FTPPush",
            "FlightModel",
            "GliderEarlyGPS",
            "MakeDveProfiles",
            "MakeMissionProfile",
            "MakeMissionTimeSeries",
            "MakePlot",
            "MakePlot2",
            "MakePlot3",
            "MakePlot4",
            "MoveData",
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
                "FTPPush",
                "FlightModel",
                "GliderEarlyGPS",
                "MakeMissionProfile",
                "MakeMissionTimeSeries",
                "MoveData",
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
        None,
        ("Base", "MakeDiveProfiles"),
        ("--magcalfile",),
        FullPath,
        {
            "action": FullPathAction,
            "help": "compass cal file or search to use most recent version of tcm2mat.cal",
        },
    ),
    "auxmagcalfile": options_t(
        None,
        ("Base", "MakeDiveProfiles"),
        ("--auxmagcalfile",),
        FullPath,
        {
            "action": FullPathAction,
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
        ("Base", "MakeDiveProfiles", "MakeMissionProfile"),
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
        ("Base", "GliderEarlyGPS"),
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
        None,
        "b",
        ("--divetarballs",),
        int,
        {
            "help": "Creates per-dive tarballs of processed files - 0 don't create, -1 create, > create fragments of specified size",
        },
    ),
    "local": options_t(
        None,
        "b",
        ("--local",),
        bool,
        {
            "help": "Performs no remote operations (no .urls, .pagers, .mailer, etc.)",
            "action": "store_true",
        },
    ),
    "clean": options_t(
        None,
        "b",
        ("--clean",),
        bool,
        {
            "help": "Clean up (delete) intermediate files from working (mission) directory after processing.",
            "action": "store_true",
        },
    ),
    "reply_addr": options_t(
        None,
        "b",
        ("--reply_addr",),
        str,
        {
            "help": "Optional email address to be inserted into the reply to field email messages",
        },
    ),
    "domain_name": options_t(
        None,
        "b",
        ("--domain_name",),
        str,
        {
            "help": "Optional domain name to use for email messages",
        },
    ),
    "web_file_location": options_t(
        None,
        "b",
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
        (
            "Base",
            "MakeDiveProfiles",
        ),
        ("--reprocess",),
        bool,
        {
            "help": "Forces re-running of MakeDiveProfiles, regardless of file time stamps (generally used for debugging "
            "- normally --force is the right option)",
            "action": "store_true",
        },
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
        ("Base",),
        ("--make_mission_profile",),
        bool,
        {
            "help": "Create mission profile output file",
            "action": "store_true",
        },
    ),
    "make_mission_timeseries": options_t(
        None,
        ("Base", "MakeMissionTimeSeries"),
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
    "glider_home_dir_group": options_t(
        None,
        ("Commission",),
        ("--glider_home_dir_group",),
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
        str,
        {
            "help": "target directory, used by MoveData.py",
        },
    ),
    #
    "encrypt": options_t(
        None,
        "h",
        ("--encrypt",),
        bool,
        {
            "help": "encrypt the file",
            "action": "store_true",
        },
    ),
    "netcdf_filename": options_t(
        None,
        ("MakePlot", "MakePlot2", "MakePlot3", "MakePlot4"),
        ("netcdf_filename",),
        str,
        {
            "help": "Name of netCDF file to process (only honored when --mission_dir is not specified)",
            "nargs": "?",
            "action": FullPathAction,
        },
    ),
    # Plotting related
    "plot_raw": options_t(
        False,
        ("MakePlot",),
        ("--plot_raw",),
        bool,
        {
            "help": "Plot raw tmicl and pmar data,if available",
            "action": "store_true",
            "section": "makeplot",
        },
    ),
    "save_svg": options_t(
        False,
        (
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
        },
    ),
    "save_png": options_t(
        True,
        (
            "MakePlot3",
            "MakePlot4",
        ),
        ("--save_png",),
        bool,
        {
            "help": "Save PNG versions of plots (plotly output only)",
            "section": "makeplot",
            # TODO: change when we move to 3.9 or later
            # "action": argparse.BooleanOptionalAction,
            "action": "store_true",
        },
    ),
    "full_html": options_t(
        "darwin" in sys.platform,
        (
            "MakePlot3",
            "MakePlot4",
        ),
        ("--full_html",),
        bool,
        {
            "help": "Save stand alone html files (plotly output only)",
            "section": "makeplot",
            "action": "store_true",
        },
    ),
    "plot_freeze_pt": options_t(
        False,
        (
            "MakePlot",
            "MakePlot4",
        ),
        ("--plot_freeze_pt",),
        bool,
        {
            "help": "Plot the freezing point in TS diagrams",
            "section": "makeplot",
            "action": "store_true",
        },
    ),
    "plot_legato": options_t(
        False,
        ("MakePlot3",),
        ("--plot_legato",),
        bool,
        {
            "help": "Plot raw legato output",
            "section": "makeplot",
            "action": "store_true",
        },
    ),
    "plot_legato_use_glider_pressure": options_t(
        False,
        ("MakePlot3",),
        ("--plot_legato_use_glider_pressure",),
        bool,
        {
            "help": "Use glider pressure for legato debug plots",
            "section": "makeplot",
            "action": "store_true",
        },
    ),
    "plot_legato_compare": options_t(
        False,
        ("MakePlot3",),
        ("--plot_legato_compare",),
        bool,
        {
            "help": "Legato raw vs smoothed pressure compare",
            "section": "makeplot",
            "action": "store_true",
        },
    ),
    "plot_directory": options_t(
        None,
        ("MakePlot3",),
        ("--plot_directory",),
        str,
        {
            "help": "Override default plot directory location",
            "section": "makeplot",
            "action": FullPathAction,
        },
    ),
    "pmar_logavg_max": options_t(
        1e2,
        ("MakePlot", "MakePlot4"),
        ("--pmar_logavg_max",),
        float,
        {
            "help": "Maximum value for pmar logavg plots y-range",
            "section": "makeplot",
            "range": [0.0, 1e10],
        },
    ),
    "pmar_logavg_min": options_t(
        1e-4,
        ("MakePlot", "MakePlot4"),
        ("--pmar_logavg_min",),
        float,
        {
            "help": "Minimum value for pmar logavg plots y-range",
            "section": "makeplot",
            "range": [0.0, 1e10],
        },
    ),
}


class BaseOptions:

    """
    BaseOptions: for use by all basestation code and utilities.
       Defaults are trumped by options listed in configuration file;
       config file options are trumped by command-line arguments.
    """

    def __init__(self, additional_arguments=None):
        """
        Input:
            argv - raw argument string
            src - source program:
                    a - BattGuage.py
                    b - Base.py
                    c - Commission.py
                    d - MakeDiveProfiles.py
                    e - CommStats.py
                    f - DataFiles.py
                    g - MakePlot.py
                    h - BaseAES.py
                    i - BaseSMS.py
                    j - GliderJabber.py
                    k - MakeKML.py
                    l - LogFile.py
                    m - MoveData.py
                    n - BaseLogin.py
                    o - CommLog.py
                    r - Cap.py
                    p - MakeMissionProfile.py
                    q - Aquadopp.py
                    s - Strip1A.py
                    t - MakeMissionTimeSeries.py
                    u - Bogue.py
                    z - BaseGZip.py
            usage - use string
        """

        self._opts = None  # Retained for debugging
        self._ap = None  # Retailed for debugging

        calling_module = os.path.splitext(
            os.path.split(inspect.stack()[1].filename)[1]
        )[0]

        # Note: for python3.9, options_dict = options_dict | additional_arguments
        if additional_arguments is not None:
            options_dict = {**global_options_dict, **additional_arguments}
        else:
            options_dict = global_options_dict

        cp_default = {}
        for k, v in options_dict.items():
            setattr(self, k, v.default_val)  # Set the default for the object
            # cp_default[k] = v.default_val
            cp_default[k] = None

        basestation_directory, _ = os.path.split(
            os.path.abspath(os.path.expanduser(sys.argv[0]))
        )
        self.basestation_directory = basestation_directory  # make avaiable
        # add path to load common basestation modules from subdirectories
        sys.path.append(basestation_directory)

        cp = configparser.RawConfigParser(cp_default)

        ap = argparse.ArgumentParser()

        # Loop over potential arguments and add what is approriate
        for k, v in options_dict.items():
            if v.group is None or calling_module in v.group:
                kwargs = copy.deepcopy(v.kwargs)
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
                ap.add_argument(*arg_list, **kwargs)

        self._ap = ap

        # self._opts, self._args = ap.parse_known_args()
        self._opts = ap.parse_args()

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
                                    "range" in kwargs.keys()
                                    and isinstance(kwargs["range"], list)
                                    and len(kwargs["range"]) == 2
                                ):
                                    min_val = kwargs["range"][0]
                                    max_val = kwargs["range"][1]
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
            #     "bd",
            #     ("netcdf_filename",),
            #     str,
            #     {
            #         "help": "Name of netCDF file to process (only used if --mission_dir is not specified)",
            #         "nargs": "?",
            #     },
            # ),
            "port": options_t(
                1234,
                "bd",
                ("port",),
                int,
                {"help": "Network Port", "nargs": "?", "range": [0, 6000]},
            ),
        }
        base_opts = BaseOptions(additional_arguments=additional_args)
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
