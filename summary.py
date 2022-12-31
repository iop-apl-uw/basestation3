import time
import os.path
from parse import parse
import sqlite3
from datetime import datetime
import math
import pandas as pd
import Utils


def getCmdfileDirective(cmdfile):
    cmdfileDirective = 'unknown'
    possibleDirectives = ["GO", "QUIT", "RESUME", "EXIT_TO_MENU"]

    if cmdfile is not None and os.path.exists(cmdfile):
        with open(cmdfile, 'rb') as file:
            for line in file:
                line = line.decode('utf-8', errors='ignore').strip()[1:].split(
',')[0]
                if line in possibleDirectives:
                    cmdfileDirective = line
        

        file.close()

    return cmdfileDirective

def rowToDict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

def collectSummary(glider, path):
    import CalibConst

    commlog = f'{path}/comm.log'
    dbfile  = f'{path}/sg{glider:03d}.db'
    cmdfile = f'{path}/cmdfile'
    calibfile = f'{path}/sg_calib_constants.m'

     
    with open(commlog, 'rb') as file:
        file.seek(-10000, 2)
        last_GPS = ''
        directive  = ''
        connected = ''
        for line in file:
            line = line.decode('utf-8', errors='ignore').strip()
            if 'GPS' in line:
                last_GPS = line[line.find('GPS'):]
            elif 'Parsed' in line:
                directive = line.split(' ')[1]
            elif 'Connected at' in line:
                connected = ' '.join(line.split(' ')[3:])
 
        file.close()

    try:
        connect_t = datetime.strptime(connected.strip(), '%b %d %H:%M:%S %Z %Y').timestamp()
    except Exception as e:
        print(f"weird date: [{connected}]")
        connect_t = 0

    mtime = os.path.getmtime(commlog) 

    last_GPS = ','.join(last_GPS.split(',')[0:5])
    p = parse("GPS,{:2d}{:2d}{:2d},{:2d}{:2d}{:2d},{:f},{:f}", last_GPS)
    (day,mon,year,hour,min,sec,lat,lon) = p.fixed

    lat_deg = int(lat / 100)
    lon_deg = int(lon / 100)
    lat_min = lat - lat_deg*100
    lon_min = lon - lon_deg*100

    pos_stamp = datetime.strptime(f"{year+2000}-{mon:02d}-{day:02d}T{hour:02d}:{min:02d}:{sec:02d}Z", "%Y-%m-%dT%H:%M:%S%z").timestamp()

    with sqlite3.connect(dbfile) as conn:
        try:
            data = pd.read_sql_query(
                "SELECT dive,log_glider,batt_volts_10V,batt_volts_24V,batt_capacity_10V,batt_capacity_24V,total_flight_time_s,log_gps_time,error_count,max_depth,log_D_GRID,meters_to_target,log_D_TGT,log_T_DIVE,log_TGT_LAT,log_TGT_LON,energy_dives_remain_Modeled,energy_days_remain_Modeled,energy_end_time_Modeled,log_INTERNAL_PRESSURE,log_INTERNAL_PRESSURE_slope,log_HUMID,log_HUMID_slope,implied_volmax,implied_volmax_slope,capture,criticals,alerts,distance_made_good,distance_to_goal,dog_efficiency,distance_over_ground FROM dives ORDER BY dive DESC LIMIT 1",
                conn,
            ).loc[0,:]

            gc = pd.read_sql_query(
                f"SELECT pitch_volts,roll_volts,vbd_volts,vbd_eff FROM gc WHERE dive={int(data['dive'])} ORDER BY vbd_eff DESC LIMIT 1",
                conn,
            ).loc[0,:]

            start = pd.read_sql_query(
                "SELECT log_gps2_time FROM dives WHERE dive=1",
                conn,
            ).loc[0,:]
        except Exception as e:
            print(e)
            return {}

    cmdfileDirective = getCmdfileDirective(cmdfile)

    end_t = 0
    cal_constants = CalibConst.getSGCalibrationConstants(calibfile)
    if 'end_date' in cal_constants:
        end_t = datetime.strptime(cal_constants['end_date'], "%Y-%m-%d").timestamp()

    out = {}
    out['name'] = int(data['log_glider'])
    out['dive'] = int(data['dive'])
    out['end']  = data['log_gps_time']
    out['next'] = data['log_gps_time'] + data['total_flight_time_s']

    out['dmg'] = data['distance_made_good']
    out['dog'] = data['distance_over_ground']
    out['dtg'] = data['distance_to_goal']
    out['dogEfficiency'] = data['dog_efficiency']

    out['vbdEfficiency'] = gc['vbd_eff']
    out['vbdVolts'] = gc['vbd_volts']

    out['mtime']    = mtime
    out['connect']  = connect_t
    out['depth']    = data['max_depth']
    out['grid']     = data['log_D_GRID']
    out['fix']      = pos_stamp
    out['lat']      = lat_deg + lat_min/60
    out['lon']      = lon_deg + lon_min/60
    out['volts']    = [ data['batt_volts_10V'], data['batt_volts_24V'] ] 
    out['capacity'] = [ data['batt_capacity_10V'], data['batt_capacity_24V'] ]
    out['errors']   = data['error_count']
    out['commDirective'] = directive
    out['cmdfileDirective'] = cmdfileDirective

    out['humidity'] = data['log_HUMID']
    out['humiditySlope'] = data['log_HUMID_slope']
    out['internalPressure'] = data['log_INTERNAL_PRESSURE']
    out['internalPressureSlope'] = data['log_INTERNAL_PRESSURE_slope']

    out['impliedVolmax'] = data['implied_volmax']
    out['impliedVolmaxSlope'] = data['implied_volmax_slope']

    out['cap']   = data['capture']
    out['alert'] = data['alerts']
    out['crits']  = data['criticals']

    out['enduranceBasis'] = 'model'
    out['enduranceEndT'] = data['log_gps_time'] + data['energy_days_remain_Modeled']*86400;
    out['enduranceDays'] = data['energy_days_remain_Modeled']
    out['enduranceDives'] = data['energy_dives_remain_Modeled']
    out['missionStart'] = start['log_gps2_time']
    out['missionEnd'] = end_t
    
    return out

if __name__ == "__main__":
    msg = collectSummary('/home/seaglider/sg249/sg249.db', '/home/seaglider/sg249/comm.log', '/home/seaglider/sg249/cmdfile')
    print(msg)
