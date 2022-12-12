#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2018, 2019, 2020, 2021, 2022 by University of Washington.  All rights reserved.
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

""" Utility functions for plotting routines
"""

import os
import time
import stat
import sys

import BaseOpts
from BaseLog import log_error

# Plotting configuration
# make_plot_section = "makeplot"
# make_plot_default_dict = {
#     "plot_raw": [0, 0, 1],
#     "save_svg": [0, 0, 1],
#     "save_png": [1, 0, 1],
#     "full_html": [1 if "darwin" in sys.platform else 0, 0, 1],
#     "plot_directory": [None, None, None],
#     "plot_freeze_pt": [0, 0, 1],
#     "pmar_logavg_max": [1e2, 0.0, 1e10],
#     "pmar_logavg_min": [1e-4, 0.0, 1e10],
#     # MakePlot3 related
#     # Legato debug plot
#     "plot_legato": [0, 0, 1],
#     # For the legato debug plot, use the glider's pressure signal instead of the sensors
#     "plot_legato_use_glider_pressure": [0, 0, 1],
#     # Legato raw vs smoothed pressure compare
#     "plot_legato_compare": [0, 0, 1],
# }

#
# Utility Routines
#
def get_mission_dive(dive_nc_file):
    """Gets common information for all plot headers

    Input:
         dive_nc_file - netcdf file object

    Returns:
         String containing the mission title
    """
    glider_id = 0
    dive_num = 0
    mission_title = ""
    if hasattr(dive_nc_file, "glider"):
        glider_id = getattr(dive_nc_file, "glider")
    elif "log_ID" in dive_nc_file.variables:
        glider_id = dive_nc_file.variables["log_ID"].getValue()
    if hasattr(dive_nc_file, "dive_number"):
        dive_num = getattr(dive_nc_file, "dive_number")
    elif "log_DIVE" in dive_nc_file.variables:
        dive_num = dive_nc_file.variables["log_DIVE"].getValue()
    if hasattr(dive_nc_file, "project"):
        mission_title = getattr(dive_nc_file, "project").decode("utf-8")
    elif "sg_cal_mission_title" in dive_nc_file.variables:
        mission_title = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )

    if hasattr(dive_nc_file, "start_time"):
        start_time = time.strftime(
            "%d-%b-%Y %H:%M:%S ", time.gmtime(dive_nc_file.start_time)
        )
    else:
        start_time = "(No start time found)"

    return f"SG{glider_id:03d} {mission_title} Dive {dive_num:d} Started {start_time}"


def get_mission_str(dive_nc_file):
    """Gets common information for all plot headers"""
    log_id = None
    mission_title = ""
    if "log_ID" in dive_nc_file.variables:
        log_id = int(dive_nc_file.variables["log_ID"].getValue())
    if "sg_cal_mission_title" in dive_nc_file.variables:
        mission_title = (
            dive_nc_file.variables["sg_cal_mission_title"][:].tobytes().decode("utf-8")
        )
    return f"SG{'%03d' % (log_id if log_id else 0,)} {mission_title}"


def get_mission_str_comm_log(comm_log, mission_title):
    """Gets common information for all plot headers"""
    log_id = None
    for s in comm_log.sessions:
        if s.sg_id is not None:
            log_id = s.sg_id
            break
    return f"SG{'%03d' % log_id if log_id else 0} {mission_title}"


def setup_plot_directory(base_opts: BaseOpts.BaseOptions) -> int:
    """Ensures plot_directory is set in base_opts and creates it if needed

    Returns:
        0 for success
        1 for failure

    """
    if base_opts.plot_directory is None:
        base_opts.plot_directory = os.path.join(base_opts.mission_dir, "plots")

    if not os.path.exists(base_opts.plot_directory):
        try:
            os.mkdir(base_opts.plot_directory)
            # Ensure that MoveData can move it as pilot if not run as the glider account
            os.chmod(
                base_opts.plot_directory,
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IWGRP
                | stat.S_IROTH
                | stat.S_IXOTH,
            )
        except:
            log_error(f"Could not create {base_opts.plot_directory}", "exc")
            return 1
    return 0
