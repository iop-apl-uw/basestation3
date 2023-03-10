import time
import os.path
from parse import parse
import aiosqlite
from datetime import datetime
import math
import Utils
import aiofiles
import CommLog
import sys
import asyncio
import aiofiles.os

async def getCmdfileDirective(cmdfile):
    cmdfileDirective = 'unknown'
    possibleDirectives = ["GO", "QUIT", "RESUME", "EXIT_TO_MENU"]

    if cmdfile is not None and os.path.exists(cmdfile):
        async with aiofiles.open(cmdfile, 'rb') as file:
            async for line in file:
                line = line.decode('utf-8', errors='ignore').strip()[1:].split(
',')[0]
                if line in possibleDirectives:
                    cmdfileDirective = line
        
    return cmdfileDirective

def rowToDict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

async def collectSummary(glider, path):
    import CalibConst

    commlogfile = f'{path}/comm.log'
    dbfile      = f'{path}/sg{glider:03d}.db'
    cmdfile     = f'{path}/cmdfile'
    calibfile   = f'{path}/sg_calib_constants.m'

    try:
        statinfo = await aiofiles.os.stat(commlogfile)
        if statinfo.st_size < 10000:
            start = 0
        else:
            start = statinfo.st_size - 10000
    except Exception as e:
        print(e)
        return {}

    processor = aiofiles.os.wrap(CommLog.process_comm_log)
    (commlog, commlog_pos, ongoing_session, _, _) = await processor(commlogfile, {}, start_pos=start)
    if len(commlog.sessions) == 0:
        session = None
    else:
        i = len(commlog.sessions) - 1
        while i >= 0 and commlog.sessions[i].gps_fix is None: 
            i = i - 1;

        session = commlog.sessions[i]
   
    if ongoing_session and ongoing_session.connect_ts:
        connected    = time.mktime(ongoing_session.connect_ts)
    elif session and session.connect_ts:
        connected    = time.mktime(session.connect_ts)
    
    if ongoing_session and ongoing_session.disconnect_ts:
        disconnected = time.mktime(ongoing_session.disconnect_ts)
    elif ongoing_session:
        disconnected = 0
    elif session and session.disconnect_ts:
        disconnected = time.mktime(session.disconnect_ts)

    if ongoing_session and ongoing_session.gps_fix:
        last_GPS     = ongoing_session.gps_fix
    elif session and session.gps_fix:
        last_GPS     = session.gps_fix
    
    if ongoing_session and ongoing_session.cmd_directive:
        directive    = ongoing_session.cmd_directive
    elif session and session.cmd_directive:
        directive    = session.cmd_directive
    else:
        directive = 'unknown'

    if ongoing_session and ongoing_session.calls_made:
        calls   = ongoing_session.calls_made
    elif session and session.cmd_directive:
        calls   = session.calls_made
    else:
        calls = 0

    logout = False
    shutdown = False
    if ongoing_session:
        logout = ongoing_session.logout_seen
        shutdown = ongoing_session.shutdown_seen
    elif session:
        logout = session.logout_seen
        shutdown = session.shutdown_seen

    if ongoing_session and ongoing_session.recov_code:
        recovery    = ongoing_session.recov_code
    elif session and session.cmd_directive:
        recovery    = session.recov_code
    else:
        recovery = None
     
    mtime = await aiofiles.os.path.getctime(commlogfile) 

    async with aiosqlite.connect(dbfile) as conn:
        conn.row_factory = rowToDict
        cur = await conn.cursor()

        try:
            await cur.execute(
                "SELECT dive,log_glider,batt_volts_10V,batt_volts_24V,batt_capacity_10V,batt_capacity_24V,total_flight_time_s,log_gps_time,error_count,max_depth,log_D_GRID,meters_to_target,log_D_TGT,log_T_DIVE,log_TGT_LAT,log_TGT_LON,energy_dives_remain_Modeled,energy_days_remain_Modeled,energy_end_time_Modeled,log_INTERNAL_PRESSURE,log_INTERNAL_PRESSURE_slope,log_HUMID,log_HUMID_slope,implied_volmax,implied_volmax_slope,capture,criticals,alerts,distance_made_good,distance_to_goal,dog_efficiency,distance_over_ground FROM dives ORDER BY dive DESC LIMIT 1"
            )
            data = await cur.fetchone()
            data = dict(map(lambda x: (x[0], x[1] if x[1] is not None else 0), data.items()))

            await cur.execute(
                f"SELECT pitch_volts,roll_volts,vbd_volts,vbd_eff FROM gc WHERE dive={int(data['dive'])} ORDER BY vbd_eff DESC LIMIT 1",
            )
            gc = await cur.fetchone()

            await cur.execute(
                "SELECT log_gps2_time FROM dives WHERE dive=1",
            )
            start = await cur.fetchone()
        except Exception as e:
            print(e)
            return {}

    cmdfileDirective = await getCmdfileDirective(cmdfile)

    out = {}
    out['name'] = int(data['log_glider'])
    out['dive'] = int(data['dive'])
    out['length'] = int(data['total_flight_time_s'])
    out['end']  = data['log_gps_time']
    out['next'] = data['log_gps_time'] + data['total_flight_time_s']

    out['dmg'] = data['distance_made_good']
    out['dog'] = data['distance_over_ground']
    out['dtg'] = data['distance_to_goal']
    out['dogEfficiency'] = data['dog_efficiency']

    out['vbdEfficiency'] = gc['vbd_eff']
    out['vbdVolts'] = gc['vbd_volts']

    out['mtime']    = mtime
    out['connect']  = connected
    out['disconnect']  = disconnected
    out['logout']   = logout
    out['shutdown'] = shutdown
    out['calls']    = calls
    out['depth']    = data['max_depth']
    out['grid']     = data['log_D_GRID']
    out['fix']      = time.mktime(last_GPS.datetime)
    out['lat']      = Utils.ddmm2dd(last_GPS.lat)
    out['lon']      = Utils.ddmm2dd(last_GPS.lon)
    out['volts']    = [ data['batt_volts_10V'], data['batt_volts_24V'] ] 
    out['capacity'] = [ data['batt_capacity_10V'], data['batt_capacity_24V'] ]
    out['errors']   = data['error_count']
    out['commDirective'] = directive
    out['cmdfileDirective'] = cmdfileDirective
    out['recovery'] = recovery

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
    try:
        out['missionStart'] = start['log_gps2_time']
    except:
        out['missionStart'] = 0
 
    return out

if __name__ == "__main__":
    msg = asyncio.run(collectSummary(249, '/home/seaglider/sg249'))
    print(msg)
