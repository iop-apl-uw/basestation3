#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

"""Basestation Extension for correcting drifting scicon clock"""

from __future__ import annotations

import calendar
import contextlib
import pdb
import sys
import time
import traceback

import numpy as np

import DataFiles
import LogFile
from BaseLog import log_error, log_info

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


def find_gc_state(gc_state_data: dict, start_time: float, state: int) -> float | None:
    if state in gc_state_data["state"]:
        if isinstance(gc_state_data["state"], list):
            ii = gc_state_data["state"].index(state)
        else:
            ii = np.squeeze(np.where(gc_state_data["state"] == state))
        return gc_state_data["secs"][ii]
    return None


def main(
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
    nc_dive_file_name: str | None = None,
    stats: None | int = None,
    globals_d: None | dict = None,
    log_f: None | LogFile.Logfile = None,
    eng_f: None | DataFiles.Datafile = None,
    results_d: None | dict = None,
):
    """Basestation extension to correct slow scicon clock

    This addresses the slow scicon clock on ssg265 M03JAN2026.

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    # Check that all keyword args are set
    if any(
        vv is None
        for vv in (
            base_opts,
            stats,
            globals_d,
            log_f,
            eng_f,
            results_d,
            nc_dive_file_name,
        )
    ):
        return 0

    ret_val = 0

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))} {nc_dive_file_name}"
    )
    # TODO "ad2cp_time" appears to have no gaps
    time_vars = ("depth_time", "aa4831_time", "legato_time")
    # Check for any of the known keys
    if not set(results_d.keys()) & set(time_vars):
        return 0

    # Preliminaries
    try:
        start_t = calendar.timegm(eng_f.start_ts)
        start_dive_t = find_gc_state(log_f.gc_state_data, start_t, 0)
        end_apogee_t = find_gc_state(log_f.gc_state_data, start_t, 5)
        start_climb_t = find_gc_state(log_f.gc_state_data, start_t, 2)
        start_surface_t = find_gc_state(log_f.gc_state_data, start_t, 14)

        for time_var_name in time_vars:
            if time_var_name in results_d:
                # There is a mismash stuff here.  Suspect that after identifying the gap in time (that is, the down and up profile)
                # we need to back out start time from the .eng file header, apply the scaling factor, then re-add in the
                # start time from the eng file header.  Issue is, we don't have that value here - it needs to get added to the
                # to the eng file reader as a distinct entity (like ontime, samples, etc) and add as pre-declared so it flows
                # through to the netcdf file and is available here.
                time_v = results_d[time_var_name].copy()
                if max(np.absolute(np.diff(time_v))) > 120.0:
                    log_info(f"Correcting {time_var_name} for {nc_dive_file_name}")

                    dive_end_i = np.squeeze(
                        np.argwhere(np.absolute(np.diff(time_v)) > 120.0)
                    )
                    if dive_end_i.size == 0:
                        continue

                    if dive_end_i.size > 1:
                        log_error(
                            f"Found multiple gaps in {time_var_name} for {nc_dive_file_name} - skipping"
                        )
                        continue

                    dive_start_t = climb_start_t = dive_end_t = climb_end_t = None

                    with contextlib.suppress(KeyError):
                        dive_start_t = results_d[
                            f"{time_var_name.split('_')[0]}_starttime_a"
                        ]
                    with contextlib.suppress(KeyError):
                        climb_start_t = results_d[
                            f"{time_var_name.split('_')[0]}_starttime_b"
                        ]

                    with contextlib.suppress(KeyError):
                        dive_end_t = results_d[
                            f"{time_var_name.split('_')[0]}_stoptime_a"
                        ]
                    with contextlib.suppress(KeyError):
                        climb_end_t = results_d[
                            f"{time_var_name.split('_')[0]}_stoptime_b"
                        ]

                    # Dive correction
                    if all(
                        vv is not None
                        for vv in (start_dive_t, end_apogee_t, dive_start_t, dive_end_t)
                    ):
                        # Assumes both traces start at zero
                        dive_corr = (end_apogee_t - start_dive_t) / (
                            dive_end_t - dive_start_t
                        )
                        # dive_corr = 3.0
                        log_info(
                            f"{time_var_name} Dive: {end_apogee_t - dive_end_t:7.2f} diff {dive_corr:.5f} corr"
                        )
                        time_v[: dive_end_i + 1] = (
                            dive_start_t
                            + (time_v[: dive_end_i + 1] - dive_start_t) * dive_corr
                        )

                    # Climb correction
                    if all(
                        vv is not None
                        for vv in (
                            start_surface_t,
                            start_climb_t,
                            climb_end_t,
                            start_climb_t,
                        )
                    ):
                        climb_corr = (start_surface_t - start_climb_t) / (
                            climb_end_t - start_climb_t
                        )
                        # climb_corr = 3.0
                        log_info(
                            f"{time_var_name} Climb: {start_surface_t - climb_end_t:7.2f} diff {climb_corr:.5f} corr"
                        )
                        time_v[dive_end_i + 1 :] = climb_start_t + (
                            (time_v[dive_end_i + 1 :] - climb_start_t) * climb_corr
                        )

                    results_d[time_var_name] = time_v

    except Exception:
        DEBUG_PDB_F()
        log_error("Failed CorrectSciconTime", "exc")
        ret_val = 1

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return ret_val
