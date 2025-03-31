# /usr/bin/env python
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

# fmt: off

""" Add selected data from per-dive netcdf file to the mission sqllite db
"""

import asyncio
import contextlib
import glob
import math
import os
import pdb
import sqlite3
import sys
import time
import traceback
import warnings
from pathlib import Path

import numpy
import pandas as pd

import BaseOpts
import BaseOptsType
import BasePlot
import CalibConst
import CommLog
import parms
import PlotUtils
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from CalibConst import getSGCalibrationConstants

DEBUG_PDB = False

slopeVars = [
                "batt_volts_10V",
                "batt_volts_24V",
                "log_IMPLIED_C_VBD",
                "implied_volmax",
                "implied_volmax_glider",
                "implied_volmax_fm",
                "batt_capacity_10V",
                "batt_capacity_24V",
            ]

def ddmm2dd(x):
    """Convert decimal degrees to degrees decimal minutes"""
    deg = int(x/100)
    mins = x - deg*100
    return deg + mins/60

def extractStr(nci_var):
    """ Very old netcdf files didn't generate char arrays for sring vars - instead,
    the string value was stored in the "value" attribute and the variable was left as a
    size one char
    """
    if nci_var.size == 1 and hasattr(nci_var, "value"):
        nci_str = nci_var.value
    else:
        nci_str = nci_var[:].tobytes().decode('utf-8')
    return nci_str


# fmt: on


def getVarNames(nci):
    """Collect var names from netcdf file - used only for debugging"""
    nc_vars = []

    for k in nci.variables:
        if (
            len(nci.variables[k].dimensions)
            and "_data_point" in nci.variables[k].dimensions[0]
        ):
            nc_vars.append({"var": k, "dim": nci.variables[k].dimensions[0]})

    return nc_vars


def addColumn(cur, col, db_type):
    try:
        cur.execute(f"ALTER TABLE dives ADD COLUMN {col} {db_type};")
    except sqlite3.OperationalError as er:
        if er.args[0].startswith("duplicate column name"):
            pass
        else:
            log_error(f"Error inserting column {col} - skipping", "exc")
            return False

    return True


# fmt: off
def insertColumn(dive, cur, col, val, db_type):
    """Insert the specified column"""
    if not addColumn(cur, col, db_type):
        return

    if db_type == "TEXT":
        cur.execute(f"UPDATE dives SET {col} = '{val}' WHERE dive={dive};")
    else:
        if math.isnan(val):
            val = 'NULL'
        cur.execute(f"UPDATE dives SET {col} = {val} WHERE dive={dive};")


def checkTableExists(cur, table):
    cur.execute(f"SELECT name FROM sqlite_master WHERE type='table' AND name='{table}'")
    return cur.fetchone() is not None

def processGC(dive, cur, nci):
    # cur.execute("CREATE TABLE IF NOT EXISTS gc(idx INTEGER PRIMARY KEY AUTOINCREMENT,dive INT,st_secs FLOAT,depth FLOAT,ob_vertv FLOAT,end_secs FLOAT,flags INT,pitch_ctl FLOAT,pitch_secs FLOAT,pitch_i FLOAT,pitch_ad FLOAT,pitch_rate FLOAT,roll_ctl FLOAT,roll_secs FLOAT,roll_i FLOAT,roll_ad FLOAT,roll_rate FLOAT,vbd_ctl FLOAT,vbd_secs FLOAT,vbd_i FLOAT,vbd_ad FLOAT,vbd_rate FLOAT,vbd_eff FLOAT,vbd_pot1_ad FLOAT,vbd_pot2_ad,pitch_errors INT,roll_errors INT,vbd_errors INT,pitch_volts FLOAT,roll_volts FLOAT,vbd_volts FLOAT);")

    cur.execute(f"DELETE FROM gc WHERE dive={dive};")
    # Really netcdf files use gc_time for the gc dimension
    if "gc_event" in  nci.dimensions:
        gc_dim = "gc_event"
    else:
        gc_dim = "gc_time"

    for i in range(0, nci.dimensions[gc_dim].size):
        roll_rate = 0
        pitch_rate = 0
        vbd_rate = 0
        vbd_eff = 0

        if nci.variables['gc_roll_secs'][i] > 0.5 and 'gc_roll_ad_start' in nci.variables:
            dAD = nci.variables['gc_roll_ad'][i] - nci.variables['gc_roll_ad_start'][i]
            if math.fabs(dAD) > 2:
                roll_rate = dAD / nci.variables['gc_roll_secs'][i]

        if nci.variables['gc_pitch_secs'][i] > 0.5 and 'gc_pitch_ad_start' in nci.variables:
            dAD = nci.variables['gc_pitch_ad'][i] - nci.variables['gc_pitch_ad_start'][i]
            if math.fabs(dAD) > 2:
                pitch_rate = dAD / nci.variables['gc_pitch_secs'][i]

        if nci.variables['gc_vbd_secs'][i] > 0.5 and "gc_vbd_ad_start" in nci.variables:
            dAD = nci.variables['gc_vbd_ad'][i] - nci.variables['gc_vbd_ad_start'][i]
            if math.fabs(dAD) > 2:
                vbd_rate = dAD / nci.variables['gc_vbd_secs'][i]
                rate = vbd_rate*nci.variables['log_VBD_CNV'].getValue()

                if rate > 0:
                    vbd_eff = 0.01*rate*nci.variables['gc_depth'][i]/nci.variables['gc_vbd_i'][i]/nci.variables['gc_vbd_volts'][i]

        # bigger thresholds for duration and move size
        # for meaningful efficiency on TT8
        elif math.fabs(nci.variables['gc_vbd_secs'][i]) > 0.5 and "gc_vbd_pot1_ad_start" in nci.variables and "gc_vbd_pot2_ad_start" in nci.variables:
            dAD = nci.variables['gc_vbd_ad'][i] - (nci.variables['gc_vbd_pot1_ad_start'][i] + nci.variables['gc_vbd_pot1_ad_start'][i])*0.5
            if math.fabs(dAD) > 10:
                vbd_rate = dAD / math.fabs(nci.variables['gc_vbd_secs'][i])
                rate = vbd_rate*nci.variables['log_VBD_CNV'].getValue()

                if rate > 0 and nci.variables['gc_vbd_secs'][i] > 10:
                    vbd_eff = 0.01*rate*nci.variables['gc_depth'][i]/nci.variables['gc_vbd_i'][i]/nci.variables['gc_vbd_volts'][i]
                    if vbd_eff > 1.0:
                        vbd_eff = 1.0 # this is a flag that something is wrong, but won't cause downstream plots to be way off

        if "gc_flags" in nci.variables:
            flag_val = f"{nci.variables['gc_flags'][i]},"
        else:
            flag_val = "NULL,"

        if "gc_roll_ctl" in nci.variables:
            gc_roll_ctl = f"{nci.variables['gc_roll_ctl'][i]},"
        else:
            gc_roll_ctl = "NULL,"

        insert_str = "INSERT INTO gc(dive," \
            "st_secs," \
            "depth," \
            "ob_vertv," \
            "end_secs," \
            "flags," \
            "pitch_ctl," \
            "pitch_secs," \
            "pitch_i," \
            "pitch_ad," \
            "pitch_rate," \
            "roll_ctl," \
            "roll_secs," \
            "roll_i," \
            "roll_ad," \
            "roll_rate," \
            "vbd_ctl," \
            "vbd_secs," \
            "vbd_i," \
            "vbd_ad," \
            "vbd_rate," \
            "vbd_eff" 

        val_str = f"VALUES({dive}," \
            f"{nci.variables['gc_st_secs'][i]}," \
            f"{nci.variables['gc_depth'][i]}," \
            f"{nci.variables['gc_ob_vertv'][i]}," \
            f"{nci.variables['gc_end_secs'][i]}," \
            f"{flag_val}" \
            f"{nci.variables['gc_pitch_ctl'][i]}," \
            f"{nci.variables['gc_pitch_secs'][i]}," \
            f"{nci.variables['gc_pitch_i'][i]}," \
            f"{nci.variables['gc_pitch_ad'][i]}," \
            f"{pitch_rate}," \
            f"{gc_roll_ctl}"\
            f"{nci.variables['gc_roll_secs'][i]}," \
            f"{nci.variables['gc_roll_i'][i]}," \
            f"{nci.variables['gc_roll_ad'][i]}," \
            f"{roll_rate}," \
            f"{nci.variables['gc_vbd_ctl'][i]}," \
            f"{nci.variables['gc_vbd_secs'][i]}," \
            f"{nci.variables['gc_vbd_i'][i]}," \
            f"{nci.variables['gc_vbd_ad'][i]}," \
            f"{vbd_rate}," \
            f"{vbd_eff}" 

        if 'gc_vbd_pot1_ad' in nci.variables:
            val_str += f",{nci.variables['gc_vbd_pot1_ad'][i]}," \
                f"{nci.variables['gc_vbd_pot2_ad'][i]}," \
                f"{nci.variables['gc_pitch_errors'][i]}," \
                f"{nci.variables['gc_roll_errors'][i]}," \
                f"{nci.variables['gc_vbd_errors'][i]}," \
                f"{nci.variables['gc_pitch_volts'][i]}," \
                f"{nci.variables['gc_roll_volts'][i]}," \
                f"{nci.variables['gc_vbd_volts'][i]});"
            
            insert_str += ",vbd_pot1_ad," \
                "vbd_pot2_ad," \
                "pitch_errors," \
                "roll_errors," \
                "vbd_errors," \
                "pitch_volts," \
                "roll_volts," \
                "vbd_volts)" 
        else:
            insert_str += ")"
            val_str += ");"
            
        cur.execute(insert_str + val_str)

def loadFileToDB(base_opts, cur, filename, con, run_dive_plots=False):
    """Process single netcdf file into the database"""
    gpsVars = [ "time", "lat", "lon", "magvar", "hdop", "first_fix_time", "final_fix_time" ]

    try:
        nci = Utils.open_netcdf_file(filename)
    except Exception:
        log_error(f"Could not open {filename} - bailing out", "exc")
        return

    dive = int(nci.variables["log_DIVE"].getValue())
    cur.execute(f"DELETE FROM dives WHERE dive={dive};")
    cur.execute(f"INSERT INTO dives(dive) VALUES({dive});")

    for v in list(nci.variables.keys()):
        if not nci.variables[v].dimensions:
            if not v.startswith("sg_cal"):
                # Old ncf files stored string variables in the "value" attribute and left the variable as a
                # zero dimension char array - skip these for now.
                try:
                    val = float(nci.variables[v].getValue())
                except ValueError:
                    continue
                insertColumn(dive, cur, v,val , "FLOAT")
        elif len(nci.variables[v].dimensions) == 1 and nci.variables[v].dimensions[0] == 'gps_info' and '_'.join(v.split('_')[2:]) in gpsVars:
            for i in range(0,nci.dimensions['gps_info'].size):
                if i in (0, 1):
                    name = v.replace('gps_', f'gps{i+1}_')
                else:
                    name = v

                insertColumn(dive, cur, name, nci.variables[v][i], "FLOAT")

    # this appears to do nothing
    if 'log_24V_AH' in nci.variables:
        nci.variables["log_24V_AH"][:].tobytes().decode("utf-8").split(",")

    if 'depth' in nci.variables:
        dep_mx = numpy.nanmax(nci.variables["depth"][:])
        insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")
    elif 'eng_depth' in nci.variables:
        dep_mx = numpy.nanmax(nci.variables["eng_depth"][:])/100
        insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")

    # Last state time is begin surface
    if "gc_state_secs" in nci.variables:
        insertColumn(
            dive,
            cur,
            "time_seconds_diving",
            nci.variables["gc_state_secs"][-1] - nci.start_time,
            "FLOAT",
        )
    if hasattr(nci, "start_time"):
        insertColumn(
            dive,
            cur,
            "time_seconds_on_surface",
            nci.start_time - nci.variables["log_gps_time"][0],
            "FLOAT",
        )

    if "start_of_climb_time" in nci.variables:
        insertColumn(dive, cur, "start_of_climb_time", nci.variables["start_of_climb_time"].getValue(), "FLOAT")
        i = numpy.where(
            nci.variables["eng_elaps_t"][:]
            < nci.variables["start_of_climb_time"].getValue()
        )
        pi_div = numpy.nanmean(nci.variables["eng_pitchAng"][i])
        # ro_div = numpy.nanmean(nci.variables["eng_rollAng"][i])

        i = numpy.where(
            nci.variables["eng_elaps_t"][:]
            > nci.variables["start_of_climb_time"].getValue()
        )
        pi_clm = numpy.nanmean(nci.variables["eng_pitchAng"][i])
        # ro_clm = numpy.nanmean(nci.variables["eng_rollAng"][i])
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
    elif len(errors_line) == 19:
            # RevE - note - pre rev3049, there was not GPS_line_timeout
            # last KHH version did not have pressure_timeouts
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
                logger_timeouts2,
                logger_timeouts3
            ] = errors_line
    elif len(errors_line) == 18:
            # RevE - note - pre rev3049, there was not GPS_line_timeout
            # last KHH version did not have pressure_timeouts
            [
                pitchErrors,
                rollErrors,
                vbdErrors,
                pitchRetries,
                rollRetries,
                vbdRetries,
                GPS_line_timeouts,
                compass_timeouts,
                sensor_timeouts0,
                sensor_timeouts1,
                sensor_timeouts2,
                sensor_timeouts3,
                sensor_timeouts4,
                sensor_timeouts5,
                logger_timeouts0,
                logger_timeouts1,
                logger_timeouts2,
                logger_timeouts3
            ] = errors_line

    errors = sum(list(map(int, extractStr(nci.variables["log_ERRORS"]).split(','))))
    insertColumn(dive, cur, "error_count", errors, "INTEGER")

    [minSpeed, maxSpeed] = list(
        map(float, extractStr(nci.variables["log_SPEED_LIMITS"]).split(","))
    )
    insertColumn(dive, cur, "log_speed_min", minSpeed, "FLOAT")
    insertColumn(dive, cur, "log_speed_max", maxSpeed, "FLOAT")

    insertColumn(dive, cur, "log_TGT_NAME", extractStr(nci.variables["log_TGT_NAME"]), "TEXT")

    [lat, lon] = list(
        map(float, extractStr(nci.variables["log_TGT_LATLONG"]).split(","))
    )
    insertColumn(dive, cur, "log_TGT_LAT", ddmm2dd(lat), "FLOAT")
    insertColumn(dive, cur, "log_TGT_LON", ddmm2dd(lon), "FLOAT")

    [v10, ah10] = list(
        map(float, extractStr(nci.variables["log_10V_AH"]).split(","))
    )

    # RevF has no log_24V_AH
    if 'log_24V_AH' in nci.variables:
        [v24, ah24] = list(
            map(float, extractStr(nci.variables["log_24V_AH"]).split(","))
        )
    else:
        v24 = 0
        ah24 = 0

    if 'log_AH0_24V' in nci.variables:
        if nci.variables["log_AH0_24V"].getValue() > 0:
            avail24 = 1 - ah24 / nci.variables["log_AH0_24V"].getValue()
        else:
            avail24 = 0
    else:
        avail24 = 0

    if nci.variables["log_AH0_10V"].getValue() > 0:
        avail10 = 1 - ah10 / nci.variables["log_AH0_10V"].getValue()
    else:
        avail10 = 0

    if "log_SDSIZE" in nci.variables:
        [sdcap, sdfree] = list(
            map(int, nci.variables["log_SDSIZE"][:].tobytes().decode("utf-8").split(","))
        )
        insertColumn(dive, cur, "SD_free", sdfree, "INTEGER")
    if "log_SDFILEDIR" in nci.variables:
        [sdfiles, sddirs] = list(
            map(int, nci.variables["log_SDFILEDIR"][:].tobytes().decode("utf-8").split(","))
        )
        insertColumn(dive, cur, "SD_files", sdfiles, "INTEGER")
        insertColumn(dive, cur, "SD_dirs", sddirs, "INTEGER")

    insertColumn(dive, cur, "batt_volts_10V", v10, "FLOAT")
    insertColumn(dive, cur, "batt_volts_24V", v24, "FLOAT")

    insertColumn(dive, cur, "batt_ah_10V", ah10, "FLOAT")
    insertColumn(dive, cur, "batt_ah_24V", ah24, "FLOAT")

    insertColumn(dive, cur, "batt_capacity_24V", avail24, "FLOAT")
    insertColumn(dive, cur, "batt_capacity_10V", avail10, "FLOAT")
    insertColumn(
        dive, cur, "batt_Ahr_cap_10V", nci.variables["log_AH0_10V"].getValue(), "FLOAT"
    )
    if "log_AH0_24V" in nci.variables:
        insertColumn(
            dive, cur, "batt_Ahr_cap_24V", nci.variables["log_AH0_24V"].getValue(), "FLOAT"
        )
    try:
        data = pd.read_sql_query(
                    f"SELECT dive,max_depth,GPS_north_displacement_m,GPS_east_displacement_m,log_speed_max,log_D_TGT,log_T_DIVE,log_TGT_LAT,log_TGT_LON,log_gps2_lat,log_gps2_lon,log_gps_lat,log_gps_lon FROM dives WHERE dive={dive} ORDER BY dive DESC LIMIT 1",
                    con,
                ).loc[0,:]

        dog = math.sqrt(math.pow(data['GPS_north_displacement_m'], 2) +
                        math.pow(data['GPS_east_displacement_m'], 2))

        bestDOG = data['max_depth']/data['log_D_TGT']*(data['log_T_DIVE']*60)*data['log_speed_max']
        dtg1 = Utils.haversine(data['log_gps2_lat'], data['log_gps2_lon'], data['log_TGT_LAT'], data['log_TGT_LON'])
        dtg2 = Utils.haversine(data['log_gps_lat'], data['log_gps_lon'], data['log_TGT_LAT'], data['log_TGT_LON'])

        dmg = dtg1 - dtg2
        dogEff = dmg/bestDOG
    except Exception:
        dmg = 0
        dog = 0
        dogEff = 0
        dtg2 = 0
        dtg1 = 0

    # print(f"{dive}: OG:{dog:.1f} MG:{dmg:.1f} TG:{dtg2:.1f} {dogEff}")

    insertColumn(dive, cur, "distance_over_ground", dog, "FLOAT")
    insertColumn(dive, cur, "distance_made_good", dmg, "FLOAT")
    insertColumn(dive, cur, "distance_to_goal", dtg2, "FLOAT")
    insertColumn(dive, cur, "dog_efficiency", dogEff, "FLOAT")

    batt_kJ_used_10V = 0.0
    batt_kJ_used_24V = 0.0
    batt_ah_used_10V = 0.0
    batt_ah_used_24V = 0.0

    if dive > 1:
        try:
            data = cur.execute(
                f"SELECT batt_ah_24V,batt_ah_10V from dives WHERE dive={dive-1}"
            ).fetchall()[0]
        except IndexError:
            log_debug(
                f"Failed to fetch batt_ah columns for dive {dive-1} - not generating ah/kj columns",
            )
        except Exception:
            log_error(
                f"Failed to fetch batt_ah columns for dive {dive-1} - not generating ah/kj columns",
                "exc",
            )

        else:
            batt_ah_used_10V = ah10 - data[1]
            batt_ah_used_24V = (ah24 if ah24 else ah10)  - data[0]
            batt_kJ_used_10V = batt_ah_used_10V * v10 * 3600.0 / 1000.0
            batt_kJ_used_24V = batt_ah_used_24V * (v24 if v24 else v10) * 3600.0 / 1000.0

    insertColumn(dive, cur, "batt_ah_used_10V", batt_ah_used_10V, "FLOAT")
    insertColumn(dive, cur, "batt_ah_used_24V", batt_ah_used_24V, "FLOAT")

    insertColumn(dive, cur, "batt_kJ_used_10V", batt_kJ_used_10V, "FLOAT")
    insertColumn(dive, cur, "batt_kJ_used_24V", batt_kJ_used_24V, "FLOAT")

    if "log_FG_AHR_10Vo" in nci.variables:
        if "log_AH0_24V" in nci.variables and nci.variables["log_AH0_24V"].getValue() == 0:
            fg_ah10 = (
                nci.variables["log_FG_AHR_24Vo"].getValue()
                + nci.variables["log_FG_AHR_10Vo"].getValue()
            )
            fg_ah24 = 0
        elif "log_FG_AHR_24Vo" in nci.variables and nci.variables["log_AH0_10V"].getValue() == 0:
            fg_ah24 = (
                nci.variables["log_FG_AHR_24Vo"].getValue()
                + nci.variables["log_FG_AHR_10Vo"].getValue()
            )
            fg_ah10 = 0
        else:
            fg_ah10 = nci.variables["log_FG_AHR_10Vo"].getValue()
            if "log_FG_AHR_24Vo" in nci.variables:
                fg_ah24 = nci.variables["log_FG_AHR_24Vo"].getValue()

        if "log_AH0_24V" in nci.variables:
            if nci.variables["log_AH0_24V"].getValue() > 0:
                fg_avail24 = 1 - fg_ah24 / nci.variables["log_AH0_24V"].getValue()
            else:
                fg_avail24 = 0
        else:
            fg_avail24 = 0

        if nci.variables["log_AH0_10V"].getValue() > 0:
            fg_avail10 = 1 - fg_ah10 / nci.variables["log_AH0_10V"].getValue()
        else:
            fg_avail10 = 0

        fg_10V_AH = (
            nci.variables["log_FG_AHR_10Vo"].getValue()
            - nci.variables["log_FG_AHR_10V"].getValue()
        )
        if "log_FG_AHR_24Vo" in nci.variables:
            fg_24V_AH = (
                nci.variables["log_FG_AHR_24Vo"].getValue()
                - nci.variables["log_FG_AHR_24V"].getValue()
            )
            insertColumn(dive, cur, "fg_ah_used_24V", fg_24V_AH, "FLOAT")
            
            fg_24V_kJ = fg_24V_AH * (v24 if v24 else v10) * 3600.0 / 1000.0
            insertColumn(dive, cur, "fg_kJ_used_24V", fg_24V_kJ, "FLOAT")
            insertColumn(dive, cur, "fg_batt_capacity_24V", fg_avail24, "FLOAT")

        insertColumn(dive, cur, "fg_ah_used_10V", fg_10V_AH, "FLOAT")

        insertColumn(dive, cur, "fg_batt_capacity_10V", fg_avail10, "FLOAT")

        fg_10V_kJ = fg_10V_AH * v10 * 3600.0 / 1000.0

        insertColumn(dive, cur, "fg_kJ_used_10V", fg_10V_kJ, "FLOAT")

    mhead_line = extractStr(nci.variables["log_MHEAD_RNG_PITCHd_Wd"]).split(",")

    if len(mhead_line) > 3:
        [mhead, rng, pitchd, wd] = list(map(float, mhead_line[:4]))
    # if len(mhead_line) > 4:
    #     theta = float(mhead_line[4])
    # if len(mhead_line) > 5:
    #     dbdw = float(mhead_line[5])

    # if len(mhead_line) > 6:
    #     pressureNoise = float(mhead_line[6])

    insertColumn(dive, cur, "mag_heading_to_target", mhead, "FLOAT")
    insertColumn(dive, cur, "meters_to_target", rng, "FLOAT")
    [tgt_la, tgt_lo] = list(
        map(
            float,
            extractStr(nci.variables["log_TGT_LATLONG"]).split(","),
        )
    )

    insertColumn(dive, cur, "target_lat", tgt_la, "FLOAT")
    insertColumn(dive, cur, "target_lon", tgt_lo, "FLOAT")

    nm = extractStr(nci.variables["log_TGT_NAME"])
    insertColumn(dive, cur, "target_name", nm, "TEXT")
    insertColumn(dive, cur, "log_SENSORS", extractStr(nci.variables["log_SENSORS"]), "TEXT")

    # Fails here
    try:
        for pwr_type in ("SENSOR", "DEVICE"):
            pwr_devices = (
                extractStr(nci.variables[f"log_{pwr_type}S"])
                .split(",")
            )
            pwr_devices_secs = [
                float(x)
                for x in extractStr(nci.variables[f"log_{pwr_type}_SECS"])
                .split(",")
            ]
            pwr_devices_mamps = [
                float(x)
                for x in extractStr(nci.variables[f"log_{pwr_type}_MAMPS"])
                .split(",")
            ]

            # Consolidate states

            # Load into db
            for ii, pwr_device in enumerate(pwr_devices):
                if pwr_device == "nil":
                    continue
                insertColumn(
                    dive,
                    cur,
                    f"{pwr_type.lower()}_{pwr_device}_secs",
                    pwr_devices_secs[ii],
                    "FLOAT",
                )
                insertColumn(
                    dive,
                    cur,
                    f"{pwr_type.lower()}_{pwr_device}_amps",
                    pwr_devices_mamps[ii] / 1000.0,
                    "FLOAT",
                )
                insertColumn(
                    dive,
                    cur,
                    f"{pwr_type.lower()}_{pwr_device}_joules",
                    v10 * (pwr_devices_mamps[ii] / 1000.0) * pwr_devices_secs[ii],
                    "FLOAT",
                )
        # Estimates for volmax
        if "log_IMPLIED_C_VBD" in nci.variables:
            glider_implied_c_vbd = int(
                nci.variables["log_IMPLIED_C_VBD"][:]
                .tobytes()
                .decode("utf-8")
                .split(",")[0]
            )
            mass = nci.variables["log_MASS"].getValue()
            vbd_min_cnts = nci.variables["log_VBD_MIN"].getValue()
            vbd_cnts_per_cc = nci.variables["log_VBD_CNV"].getValue()
            rho0 = nci.variables["log_RHO"].getValue()
            glider_implied_volmax = (
                mass / rho0 + (vbd_min_cnts - glider_implied_c_vbd) * vbd_cnts_per_cc
            )
            insertColumn(
                dive, cur, "log_IMPLIED_C_VBD", glider_implied_c_vbd, "FLOAT"
            )
            insertColumn(
                dive, cur, "implied_volmax_glider", glider_implied_volmax, "FLOAT"
            )

    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Failed to add SENSOR/DEVICE power use", "exc")

    processGC(dive, cur, nci)

    # calculate better per whole dive energy numbers for the motors
    data = pd.read_sql_query(f"SELECT vbd_i,vbd_secs,vbd_volts FROM gc WHERE dive={dive}", con)
    VBD_J = numpy.sum(data['vbd_i'][:] * data['vbd_volts'][:] * data['vbd_secs'][:])
    data = pd.read_sql_query(f"SELECT pitch_i,pitch_secs,pitch_volts FROM gc WHERE dive={dive}", con)
    pitch_J = numpy.sum(data['pitch_i'][:] * data['pitch_volts'][:] * data['pitch_secs'][:])
    data = pd.read_sql_query(f"SELECT roll_i,roll_secs,roll_volts FROM gc WHERE dive={dive}", con)
    roll_J = numpy.sum(data['roll_i'][:] * data['roll_volts'][:] * data['roll_secs'][:])

    insertColumn(dive, cur, "GC_pitch_joules", pitch_J, "FLOAT")
    insertColumn(dive, cur, "GC_VBD_joules", VBD_J, "FLOAT")
    insertColumn(dive, cur, "GC_roll_joules", roll_J, "FLOAT")

    updateDBFromFM(base_opts, [filename], cur)
    updateDBFromFileExistence(base_opts, [filename], con)
    updateDBFromPlots(base_opts, [filename], con, run_dive_plots=run_dive_plots)

    addSlopeValToDB(base_opts, dive, slopeVars, con)

def loadNetworkFileToDB(base_opts, cur, filename, con):
    """Process single network netcdf file into the database"""
    # gpsVars = [ "time", "lat", "lon", "hdop"]

    try:
        nci = Utils.open_netcdf_file(filename)
    except Exception:
        log_error(f"Could not open {filename} - bailing out", "exc")
        return

    if "log_DIVE" not in nci.variables:
        return 0
    dive = nci.variables["log_DIVE"].getValue()
    # Don't bother with dive 0 - almost nothing in there.
    if dive == 0:
        return
    
    cur.execute(f"DELETE FROM dives WHERE dive={dive};")
    cur.execute(f"INSERT INTO dives(dive) VALUES({dive});")
    for v in list(nci.variables.keys()):
        if not nci.variables[v].dimensions:
            insertColumn(dive, cur, v, nci.variables[v].getValue(), "FLOAT")

    if 'log_GC' in nci.variables:
        dep_mx = numpy.nanmax(nci.variables["log_GC"][:,1])
        insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")
    else:
        log_warning(f'no depth {filename}')

    # Last state time is begin surface
    if "log_GC_time" in nci.variables:
        insertColumn(
            dive,
            cur,
            "time_seconds_diving",
            nci.variables["log_GC_time"][-1] - nci.variables["start_time"].getValue(),
            "FLOAT",
        )
        insertColumn(dive, cur, "log_gps_time", nci.variables["log_GC_time"][-1], "FLOAT")
    else:
        log_warning(f'gc time not in {filename}')

    insertColumn(dive, cur, "log_start", nci.variables["start_time"].getValue(), "FLOAT")
    if "log_GPS" in nci.variables:
        insertColumn(dive, cur, "log_gps_lat", nci.variables["log_GPS"][1], "FLOAT")
        insertColumn(dive, cur, "log_gps_lon", nci.variables["log_GPS"][2], "FLOAT")
        insertColumn(dive, cur, "log_gps_hdop", nci.variables["log_GPS"][3], "FLOAT")
    else:
        log_warning(f'gps fixes not in {filename}')
        
    if 'log_TGT_NAME' in nci.variables:        
        insertColumn(dive, cur, "log_TGT_NAME", nci.variables["log_TGT_NAME"][:].tobytes().decode("utf-8"), "TEXT")

    if 'log_24V_AH' in nci.variables:
        v24 = nci.variables["log_24V_AH"][0]
        ah24 = nci.variables["log_24V_AH"][1]
    else:
        v24 = 0
        ah24 = 0

    if 'log_10V_AH' in nci.variables:
        v10 = nci.variables["log_10V_AH"][0]
        ah10 = nci.variables["log_10V_AH"][1]
    else:
        v10 = 0
        ah10 = 0

    # if "log_SDFILEDIR" in nci.variables:
    #     sdfiles = nci.variables["log_SDFILEDIR"][0]
    #     sddirs  = nci.variables["log_SDFILEDIR"][1]

    insertColumn(dive, cur, "batt_volts_10V", v10, "FLOAT")
    insertColumn(dive, cur, "batt_volts_24V", v24, "FLOAT")

    insertColumn(dive, cur, "batt_ah_10V", ah10, "FLOAT")
    insertColumn(dive, cur, "batt_ah_24V", ah24, "FLOAT")
    
    if "log_MHEAD_RNG_PITCHd_Wd" in nci.variables:
        mhead  = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][0]
        rng    = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][1]
        #pitchd = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][2]
        #wd     = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][3]
        #theta  = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][4]
        #dbdw   = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][5]
        #pressureNoise   = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][6]

        insertColumn(dive, cur, "mag_heading_to_target", mhead, "FLOAT")
        insertColumn(dive, cur, "meters_to_target", rng, "FLOAT")

    if 'log_TGT_NAME' in nci.variables:        
        nm = nci.variables["log_TGT_NAME"][:].tobytes().decode("utf-8")
        insertColumn(dive, cur, "target_name", nm, "TEXT")

    if "log_IMPLIED_C_VBD" in nci.variables:
        insertColumn(
            dive, cur, "log_IMPLIED_C_VBD", nci.variables["log_IMPLIED_C_VBD"][0], "FLOAT"
        )


def updateDBFromPlots(base_opts, ncfs, con, run_dive_plots=True):
    """Update the database with the output of plotting routines that generate db columns"""

    #base_opts.dive_plots = ["plot_vert_vel", "plot_pitch_roll"]
    if run_dive_plots:
        dive_plots_dict = BasePlot.get_dive_plots(base_opts)
        BasePlot.plot_dives(base_opts, dive_plots_dict, ncfs, generate_plots=False, dbcon=con)

    sg_calib_file_name = os.path.join(
        base_opts.mission_dir, "sg_calib_constants.m"
    )
    calib_consts = getSGCalibrationConstants(sg_calib_file_name, ignore_fm_tags=not base_opts.ignore_flight_model)
    mission_str = BasePlot.get_mission_str(base_opts, calib_consts)

    #base_opts.mission_plots = ["mission_energy", "mission_int_sensors"]
    mission_plots_dict = BasePlot.get_mission_plots(base_opts)

    for n in ncfs:
        dive = int(os.path.basename(n)[4:8])
        BasePlot.plot_mission(base_opts, mission_plots_dict, mission_str, dive=dive, generate_plots=False, dbcon=con)

def updateDBFromFileExistence(base_opts, ncfs, con):
    for n in ncfs:
        dv = int(os.path.basename(n)[4:8])

        capfile = f"{os.path.dirname(n)}/p{base_opts.instrument_id:03d}{dv:04d}.cap"
        critcount = 0
        if os.path.exists(capfile):
            cap = 1
            with open(capfile, 'rb') as file:
                blk = file.read().decode('utf-8', errors='ignore')
                for line in blk.splitlines():
                    pieces = line.split(',')
                    if len(pieces) >= 4 and pieces[2] == 'C':
                        critcount = critcount + 1
        else:
            cap = 0

        alertfile = f"{os.path.dirname(n)}/alert_message.html.{dv}"
        if os.path.exists(alertfile):
            alert = 1
        else:
            alert = 0

        addValToDB(base_opts, dv, "alerts", alert, con)
        addValToDB(base_opts, dv, "criticals", critcount, con)
        addValToDB(base_opts, dv, "capture", cap, con)

def updateDBFromFM(base_opts, ncfs, cur):
    """Update the database with the output of flight model"""

    flight_dir = os.path.join(base_opts.mission_dir, "flight")

    for ncf in ncfs:
        try:
            with contextlib.closing(Utils.open_netcdf_file(ncf)) as nci:
                fm_file = os.path.join(flight_dir, f"fm_{nci.dive_number:04d}.m")
                if not os.path.exists(fm_file):
                    continue
                fm_dict = CalibConst.getSGCalibrationConstants(
                    fm_file, suppress_required_error=True, ignore_fm_tags=False
                )
                if "volmax" in fm_dict and "vbdbias" in fm_dict:
                    fm_volmax = fm_dict["volmax"] - fm_dict["vbdbias"]
                    insertColumn(
                        nci.dive_number,
                        cur,
                        "implied_volmax_fm",
                        fm_volmax,
                        "FLOAT",
                    )
                if "hd_a" in fm_dict:
                    insertColumn(nci.dive_number, cur, "fm_implied_hd_a", fm_dict["hd_a"], "FLOAT")
                if "hd_b" in fm_dict:
                    insertColumn(nci.dive_number, cur, "fm_implied_hd_b", fm_dict["hd_b"], "FLOAT")
        except Exception:
            log_error(f"Problem opening FM data associated with {ncf}")

def prepCallsChangesFiles(base_opts, dbfile=None):
    dbfile = Utils.mission_database_filename(base_opts)
    con = sqlite3.connect(dbfile)

    cur = con.cursor()
    # createDivesTable(cur)
    cur.execute("DROP TABLE IF EXISTS changes;")
    cur.execute("DROP TABLE IF EXISTS calls;")
    cur.execute("DROP TABLE IF EXISTS files;")
    cur.execute("CREATE TABLE calls(dive INTEGER NOT NULL, cycle INTEGER NOT NULL, call INTEGER NOT NULL, connected FLOAT, lat FLOAT, lon FLOAT, epoch FLOAT, RH FLOAT, intP FLOAT, temp FLOAT, volts10 FLOAT, volts24 FLOAT, pitch FLOAT, depth FLOAT, pitchAD FLOAT, rollAD FLOAT, vbdAD FLOAT, sms INTEGER, iridLat FLOAT, iridLon FLOAT, irid_t FLOAT, PRIMARY KEY (dive,cycle,call));")
    cur.execute("CREATE TABLE changes(dive INTEGER NOT NULL, parm TEXT NOT NULL, oldval FLOAT, newval FLOAT, PRIMARY KEY (dive,parm));")
    cur.execute("CREATE TABLE files(dive INTEGER NOT NULL, cycle INTEGER, file TEXT NOT NULL, fullname TEXT NOT NULL, contents TEXT, PRIMARY KEY (dive,file));")

    cur.close()

    try:
        con.commit()
    except Exception as e:
        con.rollback()
        log_error(f"Failed commit, prepCallsChangesFiles {e}", "exc", alert="DB_LOCKED")

    log_info("prepCallsChangesFiles db closed")
    con.close()

# we enforce some minimum schema so that vis requests 
# can know that they will succeed

def createDivesTable(cur):
    if checkTableExists(cur, 'dives'):
        return

    cur.execute("CREATE TABLE dives(dive INT);")
    columns = [ 'log_glider', 'log_start','log_D_TGT','log_D_GRID','log__CALLS',
                'log_T_DIVE',
                'log__SM_DEPTHo','log__SM_ANGLEo','log_HUMID','log_TEMP',
                'log_INTERNAL_PRESSURE', 'log_INTERNAL_PRESSURE_slope',
                'log_HUMID_slope',
                'log_IMPLIED_C_VBD',
                'log_FG_AHR_10Vo', 'log_FG_AHR_24Vo',
                'log_gps_time',  'log_gps2_time', 'log_TGT_LAT', 'log_TGT_LON', 
                'log_gps_lat', 'log_gps_lon', 'log_gps_hdop',
                'log_gps2_lat', 'log_gps2_lon',
                'depth_avg_curr_east','depth_avg_curr_north',
                'max_depth',
                'pitch_dive','pitch_climb',
                'batt_volts_10V','batt_volts_24V',
                'batt_capacity_24V','batt_capacity_10V',
                'batt_Ahr_cap_10V', 'batt_Ahr_cap_24V',
                'total_flight_time_s',
                'avg_latitude','avg_longitude',
                'magnetic_variation','mag_heading_to_target',
                'meters_to_target',
                'GPS_north_displacement_m','GPS_east_displacement_m',
                'flight_avg_speed_east','flight_avg_speed_north',
                'distance_made_good', 'distance_to_goal', 'distance_over_ground',
                'dog_efficiency','alerts','criticals','capture','error_count',
                'energy_dives_remain_Modeled','energy_days_remain_Modeled', 'energy_days_total_Modeled',
                'energy_end_time_Modeled', 'implied_volmax_fm', 'implied_volmax_glider', 'implied_volmax',
                'implied_volmax_fm_slope', 'implied_volmax_glider_slope', 'implied_volmax_slope',
                "batt_kJ_used_10V", "batt_kJ_used_24V",
                "batt_ah_used_10V", "batt_ah_used_24V", "batt_ah_24V", "batt_ah_10V",
                "fg_kJ_used_10V", "fg_kJ_used_24V",
                "fg_batt_capacity_24V", "fg_batt_capacity_10V",
                "fg_ah_used_24V", "fg_ah_used_10V",
                "GC_pitch_joules", "GC_VBD_joules", "GC_roll_joules",
                "batt_volts_10V_slope", "batt_volts_24V_slope", 
                "batt_capacity_10V_slope", "batt_capacity_24V_slope",
                "time_seconds_on_surface","time_seconds_diving"]


    for c in columns:
        addColumn(cur, c, 'FLOAT')

    columns = [ 'target_name ']
    for c in columns:
        addColumn(cur, c, 'TEXT')
   
def prepDivesGC(base_opts):
    dbfile = Utils.mission_database_filename(base_opts)
    con = sqlite3.connect(dbfile)
    log_info("prepDivesGC db opened direct")

    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS dives;")
    cur.execute("DROP TABLE IF EXISTS gc;")
    createDivesTable(cur)
    cur.execute("CREATE TABLE gc(idx INTEGER PRIMARY KEY AUTOINCREMENT,dive INT,st_secs FLOAT,depth FLOAT,ob_vertv FLOAT,end_secs FLOAT,flags INT,pitch_ctl FLOAT,pitch_secs FLOAT,pitch_i FLOAT,pitch_ad FLOAT,pitch_rate FLOAT,roll_ctl FLOAT,roll_secs FLOAT,roll_i FLOAT,roll_ad FLOAT,roll_rate FLOAT,vbd_ctl FLOAT,vbd_secs FLOAT,vbd_i FLOAT,vbd_ad FLOAT,vbd_rate FLOAT,vbd_eff FLOAT,vbd_pot1_ad FLOAT,vbd_pot2_ad,pitch_errors INT,roll_errors INT,vbd_errors INT,pitch_volts FLOAT,roll_volts FLOAT,vbd_volts FLOAT);")

    cur.execute("CREATE TABLE IF NOT EXISTS chat(idx INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, user TEXT, message TEXT, attachment BLOB, mime TEXT);")

    cur.close()

    try:
        con.commit()
    except Exception as e:
        con.rollback()
        log_error(f"Failed commit, prepDivesGC {e}", "exc", alert="DB_LOCKED")

    con.close()

    log_info("prepDivesGC db closed")

currentSchemaVersion = 2

def checkSchema(base_opts, con):
    if con is None:
        # this has the potential to create a database from scratch
        mycon = Utils.open_mission_database(base_opts)
        if mycon is None:
            log_error("Failed to open mission db")
            return
        log_info("checkSchema db opened")
    else:
        mycon = con


    try:
        ver = mycon.cursor().execute('PRAGMA user_version').fetchone()[0]
        if ver == 0:
            log_info("version not set, checking table existence")
            tbls = [ x[0] for x in mycon.cursor().execute("SELECT name FROM sqlite_master where type='table';").fetchall() ]
            need = ['calls', 'changes', 'files', 'chat', 'dives', 'gc']
            if len([x for x in need if x in tbls]) != len(need) and con is None:
                log_info('database not initialized or created improperly, creating')
                mycon.close()   
                createDB(base_opts)
                return
       
        #  
        for i in range(ver, currentSchemaVersion):
            log_info(f"stepping DB schema from {i} to {i+1}")
            if i == 0: # step from 0 to 1, 7-Sep-2023, just adds a valid version number
                # belt and suspenders, don't add them and avoid exception handling
                # if somehow the schema versioning is out of sync
                cols = [ x[1] for x in mycon.cursor().execute('PRAGMA table_info(calls)').fetchall() ]
                if 'sms' not in cols:
                    mycon.cursor().execute("ALTER TABLE calls ADD COLUMN sms INTEGER;")
                if 'iridLat' not in cols:
                    mycon.cursor().execute("ALTER TABLE calls ADD COLUMN iridLat FLOAT;")
                if 'iridLon' not in cols:
                    mycon.cursor().execute("ALTER TABLE calls ADD COLUMN iridLon FLOAT;")
                if 'irid_t' not in cols:
                    mycon.cursor().execute("ALTER TABLE calls ADD COLUMN irid_t FLOAT;")
            elif i == 1: # step from 1 to 2
                cols = [ x[1] for x in mycon.cursor().execute('PRAGMA table_info(files)').fetchall() ]
                if 'cycle' not in cols:
                    mycon.cursor().execute("ALTER TABLE files ADD COLUMN cycle INTEGER;")
            # elif i == 2:
            # elif i == 3:
        
        mycon.cursor().execute(f'PRAGMA user_version = {currentSchemaVersion}')
    except Exception:
        log_error("could not check schema", "exc")

    if con is None:
        log_info("checkSchema db closed")
        mycon.close()

def createDB(base_opts):
    prepDivesGC(base_opts)
    prepCallsChangesFiles(base_opts)
    con = Utils.open_mission_database(base_opts)
    con.cursor().execute(f'PRAGMA user_version = {currentSchemaVersion}')
    con.close()
 
def rebuildDivesGC(base_opts, ext):
    """Rebuild the database tables from scratch"""
    prepDivesGC(base_opts)

    log_info(f"rebuilding database, ext={ext}")
    con = Utils.open_mission_database(base_opts)
    log_info("rebuildDivesGC db opened")

    cur = con.cursor()

    # patt = path + "/p%03d????.nc" % sg
    patt = os.path.join(
        base_opts.mission_dir, f"p{base_opts.instrument_id:03d}????.{ext}"
    )
    ncfs = []
    for filename in glob.glob(patt):
        ncfs.append(filename)
    ncfs = sorted(ncfs)
    for filename in ncfs:
        print(filename)
        if "ncdf" in filename:
            loadNetworkFileToDB(base_opts, cur, filename, con)
        else:
            loadFileToDB(base_opts, cur, filename, con, run_dive_plots=True)

    cur.close()

    try:
        con.commit()
    except Exception as e:
        con.rollback()
        log_error(f"Failed commit, rebuildDivesGC {e}", "exc", alert="DB_LOCKED")

    con.close()

    log_info("rebuildDivesGC db closed")

def loadDB(base_opts, filename, run_dive_plots=True):
    """Load a single netcdf file into the database"""
    con = Utils.open_mission_database(base_opts)
    log_info(f"loadDB db opened - adding:{filename}")

    # createDivesTable(cur)
    checkSchema(base_opts, con)

    cur = con.cursor()

    if "ncdf" in filename:
        loadNetworkFileToDB(base_opts, cur, filename, con)
    else:
        loadFileToDB(base_opts, cur, filename, con, run_dive_plots=run_dive_plots)

    cur.close()
    try:
        con.commit()
    except Exception as e:
        con.rollback()
        log_error(f"Failed commit, loadDB {e}", "exc", alert="DB_LOCKED")

    log_info("loadDB db closed")
    con.close()


def saveFlightDB(base_opts, mat_d, con=None):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        log_info("saveFlightDB db opened")
    else:
        mycon = con

    cur = mycon.cursor()
    cur.execute("CREATE TABLE IF NOT EXISTS flight (dive INTEGER PRIMARY KEY, pitch_d FLOAT, bottom_rho0 FLOAT, bottom_press FLOAT, hd_a FLOAT, hd_b FLOAT, vbdbias FLOAT, median_vbdbias FLOAT, abs_compress FLOAT, w_rms_vbdbias FLOAT);")
    for k in range(len(mat_d['dive_nums'])):

        cur.execute("INSERT INTO flight (dive, pitch_d, bottom_rho0, bottom_press, hd_a, hd_b, vbdbias, median_vbdbias, abs_compress, w_rms_vbdbias) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(dive) DO UPDATE SET pitch_d=?,bottom_rho0=?,bottom_press=?,hd_a=?,hd_b=?,vbdbias=?,median_vbdbias=?,abs_compress=?,w_rms_vbdvias=?",
                (mat_d['dive_nums'][k],
                 mat_d['dives_pitch_d'][k],
                 mat_d['dives_bottom_rho0'][k],
                 mat_d['dives_bottom_press'][k],
                 mat_d['dives_hd_a'][k],
                 mat_d['dives_hd_b'][k],
                 mat_d['dives_vbdbias'][k],
                 mat_d['dives_median_vbdbias'][k],
                 mat_d['dives_abs_compress'][k],
                 mat_d['dives_w_rms_vbdbias'][k],

                 mat_d['dives_pitch_d'][k],
                 mat_d['dives_bottom_rho0'][k],
                 mat_d['dives_bottom_press'][k],
                 mat_d['dives_hd_a'][k],
                 mat_d['dives_hd_b'][k],
                 mat_d['dives_vbdbias'][k],
                 mat_d['dives_median_vbdbias'][k],
                 mat_d['dives_abs_compress'][k],
                 mat_d['dives_w_rms_vbdbias'][k]
                ))
 
    cur.execute("COMMIT")
    cur.close()
    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollbacl()
            log_error(f"Failed commit, saveFlightDB {e}", "exc", alert="DB_LOCKED")

        mycon.close()
        log_info("saveFlightDB db closed")
    
def addValToDB(base_opts, dive_num, var_n, val, con=None):
    """Adds a single value to the dive database"""
    if isinstance(val, int):
        db_type = "INTEGER"
    elif isinstance(val, float):
        db_type = "FLOAT"
    else:
        log_error(f"Unknown db_type for {var_n}:{type(val)}")
        return 1

    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        log_info("addValToDB db opened")
    else:
        mycon = con

    status = 0

    try:
        cur = mycon.cursor()
        log_debug(f"Loading {var_n}:{val} dive:{dive_num} to db")
        insertColumn(dive_num, cur, var_n, val, db_type)
        cur.close()
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error(f"Failed to add {var_n} to dive {dive_num}", "exc")
        
        status = 1 

    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollback()
            log_error(f"Failed commit, addValToDB {e}", "exc", alert="DB_LOCKED")
            status = 1

        mycon.close()
        log_info("addValToDB db closed")

    return status 

def addSlopeValToDB(base_opts, dive_num, var, con=None):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        log_info("addSlopeValToDB db opened")
    else:
        mycon = con

    try:
        res = mycon.cursor().execute('PRAGMA table_info(dives)')
        vexist = []
        columns = [i[1] for i in res]
        for v in var:
            if v in columns:
                vexist.append(v)
        vstr = ','.join(vexist)
        q = f"SELECT dive,{vstr} FROM dives WHERE dive <= {dive_num} ORDER BY dive DESC LIMIT {base_opts.mission_trends_dives_back}"
        df = pd.read_sql_query(q, mycon).sort_values("dive")
    except Exception as e:
        log_error(f"{e} could not fetch {var} for slope calculation")
        return

    if len(df["dive"].to_numpy()) > 0:
        for v in vexist:
            if df[v].isnull().values.any():
                continue

            with warnings.catch_warnings():
                # For very small number of dives, we get
                # RankWarning: Polyfit may be poorly conditioned
                warnings.simplefilter('ignore', numpy.RankWarning) 
                m,_ = Utils.dive_var_trend(base_opts, df["dive"].to_numpy(), df[v].to_numpy())
            addValToDB(base_opts, dive_num, f"{v}_slope", m, con=mycon)

    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollbacl()
            log_error(f"Failed commit, addSlopeValToDB {e}", "exc", alert="DB_LOCKED")

        mycon.close()
        log_info("addSlopeValToDB db closed")

def logControlFile(base_opts, dive, cycle, filename, fullname, con=None):

    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        if mycon is None:
            log_error("Failed to open mission db")
            return
        log_info("logControlFile db opened")
    else:
        mycon = con

    checkSchema(base_opts, mycon)

#    try:
#        cur = mycon.cursor()
#        cur.execute("CREATE TABLE IF NOT EXISTS files(dive INTEGER NOT NULL, file TEXT NOT NULL, fullname TEXT NOT NULL, contents TEXT, PRIMARY KEY (dive,file));")
#    except Exception as e:
#        log_error("{e} could not create files table")
#        if con is None:
#            cur.close()
#            mycon.close()
#            log_info("logControlFile db closed")
#            
#        return

    cur = mycon.cursor()

    pathed = os.path.join(base_opts.mission_dir, fullname)
    if os.path.exists(pathed):

        if 'tgz' in filename:
            contents = ''
        else:
            try:
                with open(pathed, 'r') as f:
                    contents = f.read()
            except Exception as e:
                log_error(f'{e} reading control file for logging')
                contents = ''

        try:
            cur.execute("REPLACE INTO files(dive,cycle,file,fullname,contents) VALUES(?,?,?,?,?);", (dive, cycle, os.path.basename(filename), os.path.basename(fullname), contents))
        except Exception as e:
            log_error(f"{e} inserting file")

    cur.close()

    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollback()
            log_error(f"Failed commit, logControlFile {e}", "exc", alert="DB_LOCKED")
        mycon.close()
        log_info("logControlFile db closed")

def rebuildControlHistory(base_opts):
    con = Utils.open_mission_database(base_opts)
    log_info("rebuildControlHistory db opened")

    path = Path(base_opts.mission_dir)

    cur = con.cursor()
    try:
        cur.execute("SELECT dive FROM calls ORDER BY dive DESC LIMIT 1")
    except Exception:
        print("no dive info available")

    cur.close()

    for which in ['targets', 'science', 'scicon.sch', 'pdoscmds.bat', 'tcm2mat.cal', 'pdoslog']:
        if which == 'pdoslog':
            r = sorted(path.glob(f'p{base_opts.instrument_id:03d}????.???.pdos'))
        else:
            r = sorted(path.glob(f'{which}.????.????'))

        for f in r:
            if which == 'pdoslog':
                pcs = f.name.split('.')
                dv = int(pcs[0][4:8])
                cyc = int(pcs[1])
            else:
                pcs = f.name.split('.')
                dv = int(pcs[-2])
                cyc = int(pcs[-1])        

            logControlFile(base_opts, dv, cyc, which, f.name, con=con)

    try:
        con.commit()
    except Exception as e:
        con.rollback()
        log_error(f"Failed commit, rebuildControlHistory {e}", "exc", alert="DB_LOCKED")

    log_info("rebuildControlHistory db closed")
    con.close()

def logParameterChanges(base_opts, dive_num, cmdname, con=None):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        if mycon is None:
            log_error("Failed to open mission db")
            return
        log_info("logParameterChanges db opened")
    else:
        mycon = con

    checkSchema(base_opts, mycon)
    cur = mycon.cursor()

#    try:
#        cur = mycon.cursor()
#        cur.execute("CREATE TABLE IF NOT EXISTS changes(dive INTEGER NOT NULL, parm TEXT NOT NULL, oldval FLOAT, newval FLOAT, PRIMARY KEY (dive,parm));")
#    except Exception as e:
#        log_error("{e} could not create changes table")
#        if con is None:
#            mycon.close()
#            log_info("logParameterChanges db opened")
#
#        return

    logfile = os.path.join(base_opts.mission_dir, f'p{base_opts.instrument_id:03d}{dive_num:04d}.log')
    cmdfile = os.path.join(base_opts.mission_dir, cmdname) 
    changes = asyncio.run(parms.parameterChanges(dive_num, logfile, cmdfile))

    for d in changes:
        try:
            cur.execute("REPLACE INTO changes(dive,parm,oldval,newval) VALUES(:dive, :parm, :oldval, :newval);", d)
        except Exception as e:
            log_error(f"{e} inserting parameter changes")

    cur.close()

    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollback()
            log_error(f"Failed commit, logParameterChanges {e}", "exc", alert="DB_LOCKED")

        mycon.close()
        log_info("logParameterChanges db closed")

def addSession(base_opts, session, con=None, sms=0):
    if session is None:
        return

    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        if mycon is None:
            log_error("Failed to open mission db")
            return
        log_info("addSession db opened")
    else:
        mycon = con

    checkSchema(None, mycon)

    try:
        d = session.to_message_dict()
        d.update({ "sms": sms })
        cur = mycon.cursor()
        # cur.execute("CREATE TABLE IF NOT EXISTS calls(dive INTEGER NOT NULL, cycle INTEGER NOT NULL, call INTEGER NOT NULL, connected FLOAT, lat FLOAT, lon FLOAT, epoch FLOAT, RH FLOAT, intP FLOAT, temp FLOAT, volts10 FLOAT, volts24 FLOAT, pitch FLOAT, depth FLOAT, pitchAD FLOAT, rollAD FLOAT, vbdAD FLOAT, sms INTEGER, iridLat FLOAT, iridLon FLOAT, irid_t FLOAT, PRIMARY KEY (dive,cycle,call));")
        cur.execute("INSERT OR REPLACE INTO calls(dive,cycle,call,connected,lat,lon,epoch,RH,intP,temp,volts10,volts24,pitch,depth,pitchAD,rollAD,vbdAD,sms,iridLat,iridLon,irid_t) \
                     VALUES(:dive, :cycle, :call, :connected, :lat, :lon, :epoch, :RH, :intP, :temp, :volts10, :volts24, :pitch, :depth, :pitchAD, :rollAD, :vbdAD, :sms, :iridLat, :iridLon, :irid_t);", d)
        cur.close()
    except Exception as e:
        log_error(f"{e} inserting comm.log session")

    if con is None:
        try:
            mycon.commit()
        except Exception as e:
            mycon.rollback()
            log_error(f"Failed commit, addSession {e}", "exc", alert="DB_LOCKED")

        mycon.close()
        log_info("addSession db closed")


def main():
    """Command line interface for BaseDB"""
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation network file processing",
        additional_arguments={
            "netcdf_files": BaseOptsType.options_t(
                [],
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
            "dive_num": BaseOptsType.options_t(
                0,
                ("BaseDB",),
                ("dive_num",),
                int,
                {
                    "help": "Dive number to variable to",
                    "subparsers": ("addval",),
                },
            ),
            "value_name": BaseOptsType.options_t(
                "",
                ("BaseDB",),
                ("value_name",),
                str,
                {
                    "help": "Name of variable to add to db",
                    "subparsers": ("addval",),
                },
            ),
            "value": BaseOptsType.options_t(
                0,
                ("BaseDB",),
                ("value",),
                int,
                {
                    "help": "Value to add",
                    "subparsers": ("addval",),
                },
            ),
            "network": BaseOptsType.options_t(
                False,
                ("BaseDB",),
                ("--network",),
                bool,
                {
                    "help": "process network netcdf files",
                    "action": "store_true",
                },
            ),
            "schema": BaseOptsType.options_t(
                False,
                ("BaseDB",),
                ("--schema",),
                bool,
                {
                    "help": "check/update schema version",
                    "action": "store_true",
                },
            ),
            "init_db": BaseOptsType.options_t(
                False,
                ("BaseDB",),
                ("--init_db",),
                bool,
                {
                    "help": "initialize (erase) database",
                    "action": "store_true",
                },
            ),
            "rebuild_history": BaseOptsType.options_t(
                False,
                ("BaseDB",),
                ("--rebuild_history",),
                bool,
                {
                    "help": "rebuild control file history",
                    "action": "store_true",
                },
            ),

        },
    )
    BaseLogger(base_opts, include_time=True)
    
    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    if base_opts.schema:
        checkSchema(base_opts, None)
        return

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if not base_opts.instrument_id:
        (comm_log, _, _, _, _) = CommLog.process_comm_log(
            os.path.join(base_opts.mission_dir, "comm.log"),
            base_opts,
        )
        if comm_log:
            base_opts.instrument_id = comm_log.get_instrument_id()

    if not base_opts.instrument_id:
        _, tail = os.path.split(base_opts.mission_dir[:-1])
        if tail[-5:-3] != "sg":
            log_error("Can't figure out the instrument id - bailing out")
            return
        try:
            base_opts.instrument_id = int(tail[-3:])
        except Exception:
            log_error("Can't figure out the instrument id - bailing out")
            return

    if base_opts.init_db:
        createDB(base_opts)

    if base_opts.rebuild_history:
        rebuildControlHistory(base_opts)

    if PlotUtils.setup_plot_directory(base_opts):
        log_warning(
            "Could not setup plots directory - plotting contributions will not be added"
        )

    if base_opts.subparser_name == "addncfs":
        if base_opts.netcdf_files:
            for ncf in base_opts.netcdf_files:
                loadDB(base_opts, ncf)
        else:
            rebuildDivesGC(base_opts, "nc" if not base_opts.network else "ncdf")

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
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")
# fmt: on
