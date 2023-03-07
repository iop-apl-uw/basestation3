#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2023 by University of Washington.  All rights reserved.
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

# fmt: off

""" Add selected data from per-dive netcdf file to the mission sqllite db
"""

import contextlib
import glob
import os.path
import pdb
import sqlite3
import sys
import time
import traceback
import math
import warnings

import numpy
import pandas as pd

import BaseOpts
import BasePlot
import CalibConst
import CommLog
import PlotUtils
import Utils
from CalibConst import getSGCalibrationConstants

from BaseLog import (
    BaseLogger,
    log_info,
    log_critical,
    log_error,
    log_debug,
    log_warning,
)

DEBUG_PDB = "darwin" in sys.platform

slopeVars = [
                "batt_volts_10V",
                "batt_volts_24V",
                "log_IMPLIED_C_VBD",
                "implied_volmax_glider",
                "batt_capacity_10V",
                "batt_capacity_24V",
            ]

def ddmm2dd(x):
    """Convert decimal degrees to degrees decimal minutes"""
    deg = int(x/100)
    mins = x - deg*100
    return deg + mins/60

# fmt: on


def getVarNames(nci):
    """Collect var names from netcdf file - not used for debugging"""
    nc_vars = []

    for k in nci.variables.keys():
        if (
            len(nci.variables[k].dimensions)
            and "_data_point" in nci.variables[k].dimensions[0]
        ):
            nc_vars.append({"var": k, "dim": nci.variables[k].dimensions[0]})

    return nc_vars


# legato_time
# legato_conduc
# legato_temp
# legato_pressure
# legato_conducTemp
# ctd_pressure_qc
# speed_gsm
# glide_angle_gsm
# horz_speed_gsm
# vert_speed_gsm
# ctd_time
# ctd_depth
# ctd_pressure
# temperature_raw
# temperature_raw_qc
# conductivity_raw
# conductivity_raw_qc
# salinity_raw
# salinity_raw_qc
# temperature
# temperature_qc
# conductivity
# conductivity_qc
# salinity
# salinity_qc
# buoyancy
# speed
# glide_angle
# horz_speed
# vert_speed
# speed_qc
# sigma_t
# theta
# density
# density_insitu
# sigma_theta
# sound_velocity
# dissolved_oxygen_sat
# east_displacement_gsm
# north_displacement_gsm
# east_displacement
# north_displacement
# delta_time_s
# polar_heading
# latitude_gsm
# longitude_gsm
# latitude
# longitude
# conservative_temperature
# absolute_salinity
# gsw_sigma0
# gsw_sigma3
# gsw_sigma4
# time
# eng_vbdCC
# pressure
# depth
# eng_elaps_t_0000
# eng_elaps_t
# eng_depth
# eng_head
# eng_pitchAng
# eng_rollAng
# eng_rec
# eng_mag_x
# eng_mag_y
# eng_mag_z
# depth_time
# depth_depth

# Mapping from name to arbitrary ordinal
time_series_variables = {
    0: "temperature_raw",
    1: "temperature_raw_qc",
    2: "conductivity_raw",
    3: "conductivity_raw_qc",
    4: "salinity_raw",
    5: "salinity_raw_qc",
    6: "temperature",
    7: "temperature_qc",
    8: "conductivity",
    9: "conductivity_qc",
    10: "salinity",
    11: "salinity_qc",
}


def processTimeSeries(dive, cur, nci):
    """Inserts timeseries data into db"""

    cur.execute("COMMIT")

    cur.execute(
        "CREATE TABLE IF NOT EXISTS observation_type(observation_id INTEGER PRIMARY KEY, observation_name TEXT);"
    )

    res = cur.execute("SELECT observation_name FROM observation_type")
    if res.fetchone() is None:
        for obs_id, name in time_series_variables.items():
            cur.execute(
                "INSERT INTO observation_type (observation_id, observation_name) VALUES (?,?)",
                (obs_id, name),
            )

    cur.execute(
        "CREATE TABLE IF NOT EXISTS observations(idx INTEGER PRIMARY KEY AUTOINCREMENT,"
        "dive INTEGER, observation FLOAT, observation_time FLOAT, obs_type INTEGER,"
        "FOREIGN KEY(obs_type) REFERENCES observation_type(observation_id))"
    )

    cur.execute(f"DELETE FROM observations WHERE dive={dive};")

    for obs_idx, tv in time_series_variables.items():
        if tv not in nci.variables:
            continue
        try:
            nc_var = nci.variables[tv][:]
            nc_dim = nci.variables[tv].dimensions[0]
            for k, v in nci.variables.items():
                var_t = []
                if (
                    "time" in k[-4:]
                    and len(nci.variables[k].dimensions)
                    and "_data_point" in nci.variables[k].dimensions[0]
                    and nc_dim == nci.variables[k].dimensions[0]
                ):
                    var_t = nci.variables[k][:]
                    break

            if len(var_t):
                for ii in range(numpy.size(var_t)):
                    cur.execute(
                        "INSERT INTO observations(dive, observation, observation_time, obs_type) VALUES (?,?,?,?)",
                        (dive, nc_var[ii], var_t[ii], obs_idx),
                    )
            else:
                log_error(f"no time variable found for {tv}({nc_dim})")
        except:
            log_error(f"Problems processing {nc_var}", "exc")

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
    cur.execute("CREATE TABLE IF NOT EXISTS gc(idx INTEGER PRIMARY KEY AUTOINCREMENT,dive INT,st_secs FLOAT,depth FLOAT,ob_vertv FLOAT,end_secs FLOAT,flags INT,pitch_ctl FLOAT,pitch_secs FLOAT,pitch_i FLOAT,pitch_ad FLOAT,pitch_rate FLOAT,roll_ctl FLOAT,roll_secs FLOAT,roll_i FLOAT,roll_ad FLOAT,roll_rate FLOAT,vbd_ctl FLOAT,vbd_secs FLOAT,vbd_i FLOAT,vbd_ad FLOAT,vbd_rate FLOAT,vbd_eff FLOAT,vbd_pot1_ad FLOAT,vbd_pot2_ad,pitch_errors INT,roll_errors INT,vbd_errors INT,pitch_volts FLOAT,roll_volts FLOAT,vbd_volts FLOAT);")

    cur.execute(f"DELETE FROM gc WHERE dive={dive};")

    for i in range(0, nci.dimensions['gc_event']):
        roll_rate = 0
        pitch_rate = 0
        vbd_rate = 0
        vbd_eff = 0

        if nci.variables['gc_roll_secs'][i] > 0.5:
            dAD = nci.variables['gc_roll_ad'][i] - nci.variables['gc_roll_ad_start'][i]
            if math.fabs(dAD) > 2:
                roll_rate = dAD / nci.variables['gc_roll_secs'][i]

        if nci.variables['gc_pitch_secs'][i] > 0.5:
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

        if "gc_flags" in nci.variables:
            flag_val = f"{nci.variables['gc_flags'][i]},"
        else:
            flag_val = "NULL,"

        if "gc_roll_ctl" in nci.variables:
            gc_roll_ctl = f"{nci.variables['gc_roll_ctl'][i]},"
        else:
            gc_roll_ctl = "NULL,"

        cur.execute("INSERT INTO gc(dive," \
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
                                     "vbd_eff," \
                                     "vbd_pot1_ad," \
                                     "vbd_pot2_ad," \
                                     "pitch_errors," \
                                     "roll_errors," \
                                     "vbd_errors," \
                                     "pitch_volts," \
                                     "roll_volts," \
                                     "vbd_volts) " \
                              f"VALUES({dive}," \
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
                                     f"{vbd_eff}," \
                                     f"{nci.variables['gc_vbd_pot1_ad'][i]}," \
                                     f"{nci.variables['gc_vbd_pot2_ad'][i]}," \
                                     f"{nci.variables['gc_pitch_errors'][i]}," \
                                     f"{nci.variables['gc_roll_errors'][i]}," \
                                     f"{nci.variables['gc_vbd_errors'][i]}," \
                                     f"{nci.variables['gc_pitch_volts'][i]}," \
                                     f"{nci.variables['gc_roll_volts'][i]}," \
                                     f"{nci.variables['gc_vbd_volts'][i]});")

def loadFileToDB(base_opts, cur, filename, con):
    """Process single netcdf file into the database"""
    gpsVars = [ "time", "lat", "lon", "magvar", "hdop", "first_fix_time", "final_fix_time" ]

    try:
        nci = Utils.open_netcdf_file(filename)
    except:
        log_error(f"Could not open {filename} - bailing out", "exc")
        return

    dive = nci.variables["log_DIVE"].getValue()
    cur.execute(f"DELETE FROM dives WHERE dive={dive};")
    cur.execute(f"INSERT INTO dives(dive) VALUES({dive});")
    for v in list(nci.variables.keys()):
        if not nci.variables[v].dimensions:
            if not v.startswith("sg_cal"):
                insertColumn(dive, cur, v, nci.variables[v].getValue(), "FLOAT")
        elif len(nci.variables[v].dimensions) == 1 and nci.variables[v].dimensions[0] == 'gps_info' and '_'.join(v.split('_')[2:]) in gpsVars:
            for i in range(0,nci.dimensions['gps_info']):
                if i in (0, 1):
                    name = v.replace('gps_', f'gps{i+1}_')
                else:
                    name = v

                insertColumn(dive, cur, name, nci.variables[v][i], "FLOAT")

    nci.variables["log_24V_AH"][:].tobytes().decode("utf-8").split(",")

    if 'depth' in nci.variables:
        dep_mx = numpy.nanmax(nci.variables["depth"][:])
        insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")
    elif 'eng_depth' in nci.variables:
        dep_mx = numpy.nanmax(nci.variables["eng_depth"][:])/100
        insertColumn(dive, cur, "max_depth", dep_mx, "FLOAT")
        print(f'using eng for depth {filename}')
    else:
        print(f'no depth {filename}')

    # Last state time is begin surface
    insertColumn(
        dive,
        cur,
        "time_seconds_diving",
        nci.variables["gc_state_secs"][-1] - nci.start_time,
        "FLOAT",
    )
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

    errors = sum(list(map(int, nci.variables["log_ERRORS"][:].tobytes().decode('utf-8').split(','))))
    insertColumn(dive, cur, "error_count", errors, "INTEGER")

    [minSpeed, maxSpeed] = list(
        map(float, nci.variables["log_SPEED_LIMITS"][:].tobytes().decode("utf-8").split(","))
    )
    insertColumn(dive, cur, "log_speed_min", minSpeed, "FLOAT")
    insertColumn(dive, cur, "log_speed_max", maxSpeed, "FLOAT")

    insertColumn(dive, cur, "log_TGT_NAME", nci.variables["log_TGT_NAME"][:].tobytes().decode("utf-8"), "TEXT")

    [lat, lon] = list(
        map(float, nci.variables["log_TGT_LATLONG"][:].tobytes().decode("utf-8").split(","))
    )
    insertColumn(dive, cur, "log_TGT_LAT", ddmm2dd(lat), "FLOAT")
    insertColumn(dive, cur, "log_TGT_LON", ddmm2dd(lon), "FLOAT")

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
    except:
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
        except:
            log_error(
                f"Failed to fetch batt_ah columns for dive {dive-1} - not generating ah/kj columns",
                "exc",
            )

        else:
            batt_ah_used_10V = ah10 - data[1]
            batt_ah_used_24V = ah24 - data[0]
            batt_kJ_used_10V = batt_ah_used_10V * v10 * 3600.0 / 1000.0
            batt_kJ_used_24V = batt_ah_used_24V * v10 * 3600.0 / 1000.0

    insertColumn(dive, cur, "batt_ah_used_10V", batt_ah_used_10V, "FLOAT")
    insertColumn(dive, cur, "batt_ah_used_24V", batt_ah_used_24V, "FLOAT")

    insertColumn(dive, cur, "batt_kJ_used_10V", batt_kJ_used_10V, "FLOAT")
    insertColumn(dive, cur, "batt_kJ_used_24V", batt_kJ_used_24V, "FLOAT")

    if "log_FG_AHR_10Vo" in nci.variables:
        if nci.variables["log_AH0_24V"].getValue() == 0:
            fg_ah10 = (
                nci.variables["log_FG_AHR_24Vo"].getValue()
                + nci.variables["log_FG_AHR_10Vo"].getValue()
            )
            fg_ah24 = 0
        elif nci.variables["log_AH0_10V"].getValue() == 0:
            fg_ah24 = (
                nci.variables["log_FG_AHR_24Vo"].getValue()
                + nci.variables["log_FG_AHR_10Vo"].getValue()
            )
            fg_ah10 = 0
        else:
            fg_ah10 = nci.variables["log_FG_AHR_10Vo"].getValue()
            fg_ah24 = nci.variables["log_FG_AHR_24Vo"].getValue()

        if nci.variables["log_AH0_24V"].getValue() > 0:
            fg_avail24 = 1 - fg_ah24 / nci.variables["log_AH0_24V"].getValue()
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
        fg_24V_AH = (
            nci.variables["log_FG_AHR_24Vo"].getValue()
            - nci.variables["log_FG_AHR_24V"].getValue()
        )

        insertColumn(dive, cur, "fg_ah_used_10V", fg_10V_AH, "FLOAT")
        insertColumn(dive, cur, "fg_ah_used_24V", fg_24V_AH, "FLOAT")

        insertColumn(dive, cur, "fg_batt_capacity_10V", fg_avail10, "FLOAT")
        insertColumn(dive, cur, "fg_batt_capacity_24V", fg_avail24, "FLOAT")

        fg_10V_kJ = fg_10V_AH * v10 * 3600.0 / 1000.0
        fg_24V_kJ = fg_24V_AH * v24 * 3600.0 / 1000.0

        insertColumn(dive, cur, "fg_kJ_used_10V", fg_10V_kJ, "FLOAT")
        insertColumn(dive, cur, "fg_kJ_used_24V", fg_24V_kJ, "FLOAT")

    mhead_line = nci.variables["log_MHEAD_RNG_PITCHd_Wd"][:]
    mhead_line = mhead_line.tobytes().decode("utf-8").split(",")

    if len(mhead_line) > 4:
        [mhead, rng, pitchd, wd, theta] = list(map(float, mhead_line[:5]))
    if len(mhead_line) > 5:
       dbdw = float(mhead_line[5])

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

    try:
        for pwr_type in ("SENSOR", "DEVICE"):
            pwr_devices = (
                nci.variables[f"log_{pwr_type}S"][:]
                .tobytes()
                .decode("utf-8")
                .split(",")
            )
            pwr_devices_secs = [
                float(x)
                for x in nci.variables[f"log_{pwr_type}_SECS"][:]
                .tobytes()
                .decode("utf-8")
                .split(",")
            ]
            pwr_devices_mamps = [
                float(x)
                for x in nci.variables[f"log_{pwr_type}_MAMPS"][:]
                .tobytes()
                .decode("utf-8")
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

    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error("Failed to add SENSOR/DEVICE power use", "exc")

    processGC(dive, cur, nci)

    processTimeSeries(dive, cur, nci)

    addSlopeValToDB(base_opts, dive, slopeVars, con)

def updateDBFromPlots(base_opts, ncfs, run_dive_plots=True):
    """Update the database with the output of plotting routines that generate db columns"""

    #base_opts.dive_plots = ["plot_vert_vel", "plot_pitch_roll"]
    if run_dive_plots:
        dive_plots_dict = BasePlot.get_dive_plots(base_opts)
        BasePlot.plot_dives(base_opts, dive_plots_dict, ncfs, generate_plots=False)

    sg_calib_file_name = os.path.join(
        base_opts.mission_dir, "sg_calib_constants.m"
    )
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    mission_str = BasePlot.get_mission_str(base_opts, calib_consts)

    #base_opts.mission_plots = ["mission_energy", "mission_int_sensors"]
    mission_plots_dict = BasePlot.get_mission_plots(base_opts)

    for n in ncfs:
        dive = int(os.path.basename(n)[4:8])
        BasePlot.plot_mission(base_opts, mission_plots_dict, mission_str, dive=dive, generate_plots=False)

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

def updateDBFromFM(base_opts, ncfs, con):
    """Update the database with the output of flight model"""

    flight_dir = os.path.join(base_opts.mission_dir, "flight")
    with con:
        cur = con.cursor()

        for ncf in ncfs:
            try:
                with contextlib.closing(Utils.open_netcdf_file(ncf)) as nci:
                    fm_file = os.path.join(flight_dir, f"fm_{nci.dive_number:04d}.m")
                    if not os.path.exists(fm_file):
                        continue
                    fm_dict = CalibConst.getSGCalibrationConstants(
                        fm_file, suppress_required_error=True
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
                        addSlopeValToDB(base_opts, nci.dive_number, ["implied_volmax_fm"], con)
            except:
                log_error(f"Problem opening FM data associated with {ncf}")

        cur.close()

# we enforce some minimum schema so that vis requests 
# can know that they will succeed

def createDivesTable(cur):
    if checkTableExists(cur, 'dives'):
        return

    cur.execute("CREATE TABLE dives(dive INT);")
    columns = [ 'log_start','log_D_TGT','log_D_GRID','log__CALLS',
                'log__SM_DEPTHo','log__SM_ANGLEo','log_HUMID','log_TEMP',
                'log_INTERNAL_PRESSURE', 
                'depth_avg_curr_east','depth_avg_curr_north',
                'max_depth',
                'pitch_dive','pitch_climb',
                'batt_volts_10V','batt_volts_24V',
                'batt_capacity_24V','batt_capacity_10V',
                'total_flight_time_s',
                'avg_latitude','avg_longitude',
                'magnetic_variation','mag_heading_to_target',
                'meters_to_target',
                'GPS_north_displacement_m','GPS_east_displacement_m',
                'flight_avg_speed_east','flight_avg_speed_north',
                'dog_efficiency','alerts','criticals','capture','error_count',
                'energy_dives_remain_Modeled','energy_days_remain_Modeled',
                'energy_end_time_Modeled' ]

    for c in columns:
        addColumn(cur, c, 'FLOAT');

    columns = [ 'target_name ']
    for c in columns:
        addColumn(cur, c, 'TEXT');
    
 
def rebuildDB(base_opts):
    """Rebuild the database from scratch"""
    log_info("rebuilding database")
    con = Utils.open_mission_database(base_opts)
    cur = con.cursor()
    cur.execute("DROP TABLE IF EXISTS dives;")
    cur.execute("DROP TABLE IF EXISTS gc;")
    createDivesTable(cur)
    cur.execute("CREATE TABLE gc(idx INTEGER PRIMARY KEY AUTOINCREMENT,dive INT,st_secs FLOAT,depth FLOAT,ob_vertv FLOAT,end_secs FLOAT,flags INT,pitch_ctl FLOAT,pitch_secs FLOAT,pitch_i FLOAT,pitch_ad FLOAT,pitch_rate FLOAT,roll_ctl FLOAT,roll_secs FLOAT,roll_i FLOAT,roll_ad FLOAT,roll_rate FLOAT,vbd_ctl FLOAT,vbd_secs FLOAT,vbd_i FLOAT,vbd_ad FLOAT,vbd_rate FLOAT,vbd_eff FLOAT,vbd_pot1_ad FLOAT,vbd_pot2_ad,pitch_errors INT,roll_errors INT,vbd_errors INT,pitch_volts FLOAT,roll_volts FLOAT,vbd_volts FLOAT);")

    # patt = path + "/p%03d????.nc" % sg
    patt = os.path.join(
        base_opts.mission_dir, f"p{base_opts.instrument_id:03d}????.nc"
    )
    ncfs = []
    for filename in glob.glob(patt):
        ncfs.append(filename)
    ncfs = sorted(ncfs)
    for filename in ncfs:
        loadFileToDB(base_opts, cur, filename, con)
    cur.close()
    updateDBFromFM(base_opts, ncfs, con)
    updateDBFromFileExistence(base_opts, ncfs, con)
    con.close()
    updateDBFromPlots(base_opts, ncfs)


def loadDB(base_opts, filename, run_dive_plots=True):
    """Load a single netcdf file into the database"""
    con = Utils.open_mission_database(base_opts)
    cur = con.cursor()
    createDivesTable(cur)
    loadFileToDB(base_opts, cur, filename, con)
    cur.close()
    updateDBFromFM(base_opts, [filename], con)
    updateDBFromFileExistence(base_opts, [filename], con)
    con.close()
    updateDBFromPlots(base_opts, [filename], run_dive_plots=run_dive_plots)    

def prepDB(base_opts, dbfile=None):
    if dbfile is None:
        con = Utils.open_mission_database(base_opts)
    else:
        con = sqlite3.connect(dbfile)

    cur = con.cursor()
    createDivesTable(cur)
    cur.execute("CREATE TABLE IF NOT EXISTS chat(idx INTEGER PRIMARY KEY AUTOINCREMENT, timestamp REAL, user TEXT, message TEXT, attachment BLOB, mime TEXT);")
    cur.execute("CREATE TABLE IF NOT EXISTS calls(dive INTEGER NOT NULL, cycle INTEGER NOT NULL, call INTEGER NOT NULL, connected FLOAT, lat FLOAT, lon FLOAT, epoch FLOAT, RH FLOAT, intP FLOAT, temp FLOAT, volts10 FLOAT, volts24 FLOAT, pitch FLOAT, depth FLOAT, pitchAD FLOAT, rollAD FLOAT, vbdAD FLOAT, PRIMARY KEY (dive,cycle,call));")
    cur.close()

    con.close()

def saveFlightDB(base_opts, mat_d, con=None):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
    else:
        mycon = con

    cur = mycon.cursor()
    cur.execute("DROP TABLE IF EXISTS flight;")
    cur.execute("CREATE TABLE flight (idx INTEGER PRIMARY KEY AUTOINCREMENT, dive INTEGER, pitch_d FLOAT, bottom_rho0 FLOAT, bottom_press FLOAT, hd_a FLOAT, hd_b FLOAT, vbdbias FLOAT, median_vbdbias FLOAT, abs_compress FLOAT, w_rms_vbdbias FLOAT);")
    for k, val in enumerate(mat_d['dive_nums']):
        cur.execute("INSERT INTO flight (dive, pitch_d, bottom_rho0, bottom_press, hd_a, hd_b, vbdbias, median_vbdbias, abs_compress, w_rms_vbdbias) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)", 
                mat_d['dive_nums'],
                mat_d['dives_pitch_d'],
                mat_d['dives_bottom_rho0'],
                mat_d['dives_bottom_press'],
                mat_d['dives_hd_a'],
                mat_d['dives_hd_b'],
                mat_d['dives_vbdbias'],
                mat_d['dives_median_vbdbias'],
                mat_d['dives_abs_compress'],
                mat_d['dives_w_rms_vbdbias'])
 
    if con is None:
        cur.close()
        mycon.close()
    
def addValToDB(base_opts, dive_num, var_n, val, con=None):
    """Adds a single value to the dive database"""
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
    else:
        mycon = con

    try:
        if isinstance(val, int):
            db_type = "INTEGER"
        elif isinstance(val, float):
            db_type = "FLOAT"
        else:
            log_error(f"Unknown db_type for {var_n}:{type(val)}")
            return 1

        cur = mycon.cursor()
        log_debug(f"Loading {var_n}:{val} dive:{dive_num} to db")
        insertColumn(dive_num, cur, var_n, val, db_type)
        mycon.commit()

        if con is None:
            cur.close()
            mycon.close()
    except:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_error(f"Failed to add {var_n} to dive {dive_num}", "exc")
        print(f"Failed to add {var_n} to dive {dive_num}", "exc")
        return 1
    return 0

def addSlopeValToDB(base_opts, dive_num, var, con):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
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
        mycon.close()

def addSession(base_opts, session, con=None):
    if con is None:
        mycon = Utils.open_mission_database(base_opts)
        if mycon is None:
            log_error("Failed to open mission db")
            return
    else:
        mycon = con

    try:
        cur = mycon.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS calls(dive INTEGER NOT NULL, cycle INTEGER NOT NULL, call INTEGER NOT NULL, connected FLOAT, lat FLOAT, lon FLOAT, epoch FLOAT, RH FLOAT, intP FLOAT, temp FLOAT, volts10 FLOAT, volts24 FLOAT, pitch FLOAT, depth FLOAT, pitchAD FLOAT, rollAD FLOAT, vbdAD FLOAT, PRIMARY KEY (dive,cycle,call));")
        cur.execute("INSERT OR IGNORE INTO calls(dive,cycle,call,connected,lat,lon,epoch,RH,intP,temp,volts10,volts24,pitch,depth,pitchAD,rollAD,vbdAD) \
                     VALUES(:dive, :cycle, :call, :connected, :lat, :lon, :epoch, :RH, :intP, :temp, :volts10, :volts24, :pitch, :depth, :pitchAD, :rollAD, :vbdAD);",
                    session.to_message_dict())
        mycon.commit()
    except Exception as e:
        log_error(f"{e} inserting comm.log session")

    if con is None:
        mycon.close()

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

    if PlotUtils.setup_plot_directory(base_opts):
        log_warning(
            "Could not setup plots directory - plotting contributions will not be added"
        )

    prepDB(base_opts)

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
# fmt: on
