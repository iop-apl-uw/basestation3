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


""" Add selected data from per-dive netcdf file to the mission sqllite db
"""

import glob
import os.path
import pdb
import sqlite3
import sys
import time
import traceback

import numpy

import BaseOpts
import CommLog
import Utils

from BaseLog import BaseLogger, log_info, log_critical, log_error, log_debug

DEBUG_PDB = "darwin" in sys.platform


def insertColumn(dive, cur, col, val, db_type):
    """Insert the specified column"""
    try:
        cur.execute(f"ALTER TABLE dives ADD COLUMN {col} {db_type};")
    except:
        pass

    if db_type == "TEXT":
        cur.execute(f"UPDATE dives SET {col} = '{val}' WHERE dive={dive};")
    else:
        cur.execute(f"UPDATE dives SET {col} = {val} WHERE dive={dive};")


def loadFileToDB(cur, filename):
    """Process single netcdf file into the database"""
    nci = Utils.open_netcdf_file(filename)
    dive = nci.variables["log_DIVE"].getValue()
    cur.execute(f"DELETE FROM dives WHERE dive={dive};")
    cur.execute(f"INSERT INTO dives(dive) VALUES({dive});")
    for v in list(nci.variables.keys()):
        if not nci.variables[v].dimensions:
            if not v.startswith("sg_cal"):
                insertColumn(dive, cur, v, nci.variables[v].getValue(), "FLOAT")

    dep_mx = numpy.nanmax(nci.variables["depth"][:])
    insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")

    i = numpy.where(
        nci.variables["eng_elaps_t"][:]
        < nci.variables["start_of_climb_time"].getValue()
    )
    pi_div = numpy.nanmean(nci.variables["eng_pitchAng"][i])
    ro_div = numpy.nanmean(nci.variables["eng_rollAng"][i])

    i = numpy.where(
        nci.variables["eng_elaps_t"][:]
        > nci.variables["start_of_climb_time"].getValue()
    )
    pi_clm = numpy.nanmean(nci.variables["eng_pitchAng"][i])
    ro_clm = numpy.nanmean(nci.variables["eng_rollAng"][i])
    insertColumn(dive, cur, "pitch_dive", pi_div, "FLOAT")
    insertColumn(dive, cur, "pitch_climb", pi_clm, "FLOAT")

    errors_line = nci.variables["log_ERRORS"][:].tobytes().decode("utf-8").split(",")
    if len(errors_line) == 16:
        # RevB
        [
            buffer_overruns,
            spurious_interrupts,
            cf8FileOpenErrors,
            cf8FileWriteErrors,
            cf8FileCloseErrors,
            cf8FileOpenRetries,
            cf8FileWriteRetries,
            cf8FileCloseRetries,
            pitchErrors,
            rollErrors,
            vbdErrors,
            pitchRetries,
            rollRetries,
            vbdRetries,
            GPS_line_timeouts,
            sensor_timeouts,
        ] = errors_line
    else:
        if len(errors_line) >= 18:
            # RevE - note - pre rev3049, there was not GPS_line_timeout
            [
                pitchErrors,
                rollErrors,
                vbdErrors,
                pitchRetries,
                rollRetries,
                vbdRetries,
                GPS_line_timeouts,
                compass_timeouts,
                pressure_timeouts,
                sensor_timeouts0,
                sensor_timeouts1,
                sensor_timeouts2,
                sensor_timeouts3,
                sensor_timeouts4,
                sensor_timeouts5,
                logger_timeouts0,
                logger_timeouts1,
                logger_timeouts3,
            ] = errors_line[:18]
        if len(errors_line) == 19:
            logger_timeouts4 = errors_line[18]

    [v10, ah10] = list(
        map(float, nci.variables["log_10V_AH"][:].tobytes().decode("utf-8").split(","))
    )
    [v24, ah24] = list(
        map(float, nci.variables["log_24V_AH"][:].tobytes().decode("utf-8").split(","))
    )
    if nci.variables["log_AH0_24V"].getValue() > 0:
        avail24 = 1 - ah24 / nci.variables["log_AH0_24V"].getValue()
    else:
        avail24 = 0

    if nci.variables["log_AH0_10V"].getValue() > 0:
        avail10 = 1 - ah10 / nci.variables["log_AH0_10V"].getValue()
    else:
        avail10 = 0

    insertColumn(dive, cur, "volts_10V", v10, "FLOAT")
    insertColumn(dive, cur, "volts_24V", v24, "FLOAT")
    insertColumn(dive, cur, "capacity_24V", avail24, "FLOAT")
    insertColumn(dive, cur, "capacity_10V", avail10, "FLOAT")

    mhead_line = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
    mhead_line = mhead_line.tobytes().decode("utf-8").split(",")

    [mhead, rng, pitchd, wd, theta, dbdw] = list(map(float, mhead_line[:6]))
    if len(mhead_line) > 6:
        pressureNoise = float(mhead_line[6])

    insertColumn(dive, cur, "mag_heading_to_target", mhead, "FLOAT")
    insertColumn(dive, cur, "meters_to_target", rng, "FLOAT")
    [tgt_la, tgt_lo] = list(
        map(
            float,
            nci.variables["log_TGT_LATLONG"][:].tobytes().decode("utf-8").split(","),
        )
    )

    insertColumn(dive, cur, "target_lat", tgt_la, "FLOAT")
    insertColumn(dive, cur, "target_lon", tgt_lo, "FLOAT")

    nm = nci.variables["log_TGT_NAME"][:].tobytes().decode("utf-8")
    insertColumn(dive, cur, "target_name", nm, "TEXT")


def rebuildDB(base_opts):
    """Rebuild the database from scratch"""
    # glider = os.path.basename()
    # sg = int(glider[2:])
    # db = path + "/" + glider + ".db"
    db = base_opts.mission_dir + f"sg{base_opts.instrument_id:03d}.db"
    log_info("rebuilding %s" % db)
    con = sqlite3.connect(db)
    with con:
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS dives;")
        cur.execute("CREATE TABLE dives(dive INT);")
        # patt = path + "/p%03d????.nc" % sg
        patt = base_opts.mission_dir + "/p%03d????.nc" % base_opts.instrument_id
        for filename in glob.glob(patt):
            loadFileToDB(cur, filename)
        cur.close()


def loadDB(base_opts, filename):
    """Load a single netcdf file into the database"""
    db = base_opts.mission_dir + f"/sg{base_opts.instrument_id:03d}.db"
    log_info("Loading %s to %s" % (filename, db))
    con = sqlite3.connect(db)
    with con:
        cur = con.cursor()
        loadFileToDB(cur, filename)
        cur.close()


def addValToDB(base_opts, dive_num, var_n, val):
    """Adds a single value to the dive database"""
    try:
        if isinstance(val, int):
            db_type = "INTEGER"
        elif isinstance(val, float):
            db_type = "FLOAT"
        else:
            log_error(f"Unknown db_type for {var_n}:{type(val)}")
            return 1
        db = base_opts.mission_dir + f"/sg{base_opts.instrument_id:03d}.db"
        if not os.path.exists(db):
            log_error(f"{db} does not exist - not updating {var_n}")
            return 1
        log_debug(f"Loading {var_n}:{val} dive:{dive_num} to {db}")
        con = sqlite3.connect(db)
        with con:
            cur = con.cursor()
            insertColumn(dive_num, cur, var_n, val, db_type)
            cur.close()
    except:
        log_error(f"Failed to add {var_n} to dive {dive_num}", "exc")
        return 1
    return 0


def main():
    """Command line interface for BaseDB"""
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation network file processing",
        additional_arguments={
            "netcdf_files": BaseOpts.options_t(
                None,
                ("BaseDB",),
                ("netcdf_files",),
                str,
                {
                    "help": "List of netcdf files to add to the db",
                    "nargs": "*",
                    "action": BaseOpts.FullPathAction,
                    "subparsers": ("addncfs",),
                },
            ),
            "dive_num": BaseOpts.options_t(
                None,
                ("BaseDB",),
                ("dive_num",),
                int,
                {
                    "help": "Dive number to variable to",
                    "subparsers": ("addval",),
                },
            ),
            "value_name": BaseOpts.options_t(
                None,
                ("BaseDB",),
                ("value_name",),
                str,
                {
                    "help": "Name of variable to add to db",
                    "subparsers": ("addval",),
                },
            ),
            "value": BaseOpts.options_t(
                None,
                ("BaseDB",),
                ("value",),
                int,
                {
                    "help": "Value to add",
                    "subparsers": ("addval",),
                },
            ),
        },
    )
    BaseLogger(base_opts, include_time=True)

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if not base_opts.instrument_id:
        (comm_log, _, _, _, _) = CommLog.process_comm_log(
            os.path.join(base_opts.mission_dir, "comm.log"),
            base_opts,
        )
        base_opts.instrument_id = comm_log.get_instrument_id()

    if not base_opts.instrument_id:
        _, tail = os.path.split(base_opts.mission_dir[:-1])
        if tail[-5:-3] != "sg":
            log_error("Can't figure out the instrument id - bailing out")
            return
        try:
            base_opts.instrument_id = int(tail[:-3])
        except:
            log_error("Can't figure out the instrument id - bailing out")
            return

    if base_opts.subparser_name == "addncfs":
        if base_opts.netcdf_files:
            for ncf in base_opts.netcdf_files:
                loadDB(base_opts, ncf)
        else:
            rebuildDB(base_opts)
    elif base_opts.subparser_name == "addval":
        addValToDB(base_opts, base_opts.dive_num, base_opts.value_name, base_opts.value)
    else:
        log_error(f"Unknown parser {base_opts.subparser_name}")

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        main()
    except SystemExit:
        pass
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")
