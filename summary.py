## Copyright (c) 2023  University of Washington.
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
import sys

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
            async with aiofiles.open(commlogfile, 'rb') as f:
                await f.seek(-10000, 2)
                cont = await f.read()
                idx = cont.decode('utf-8', errors='ignore').find('Connected')
                if idx > -1:
                    start = start + idx

    except Exception as e:
        print(e)
        return {}

    processor = aiofiles.os.wrap(CommLog.process_comm_log)
    (commlog, commlog_pos, ongoing_session, _, _) = await processor(commlogfile, None, start_pos=start)

    if not commlog or not hasattr(commlog, 'sessions'):
        return {}

    if hasattr(commlog, 'sessions') and len(commlog.sessions) == 0:
        session = None
    elif hasattr(commlog, 'sessions'):
        i = len(commlog.sessions) - 1
        while i >= 0 and commlog.sessions[i].gps_fix is None: 
            i = i - 1;

        session = commlog.sessions[i]
   
    if ongoing_session and ongoing_session.connect_ts:
        connected    = time.mktime(ongoing_session.connect_ts)
    elif session and session.connect_ts:
        connected    = time.mktime(session.connect_ts)
    else:
        connected = None
    
    if ongoing_session and ongoing_session.disconnect_ts:
        disconnected = time.mktime(ongoing_session.disconnect_ts)
    elif ongoing_session:
        disconnected = 0
    elif session and session.disconnect_ts:
        disconnected = time.mktime(session.disconnect_ts)
    else:
        disconnected = None 

    if ongoing_session and ongoing_session.gps_fix:
        last_GPS     = ongoing_session.gps_fix
    elif session and session.gps_fix:
        last_GPS     = session.gps_fix
    else:
        last_GPS = None
    
    if ongoing_session and ongoing_session.cmd_directive:
        directive    = ongoing_session.cmd_directive
    elif session and session.cmd_directive:
        directive    = session.cmd_directive
    else:
        directive = 'unknown'

    if ongoing_session and ongoing_session.calls_made:
        calls   = ongoing_session.calls_made
    elif session and session.calls_made:
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
    elif session and session.recov_code:
        recovery    = session.recov_code
    else:
        recovery = None
     
    try:
        mtime = await aiofiles.os.path.getctime(commlogfile) 
    except:
        mtime = 0

    out = {}

    try:
        cmdfileDirective = await getCmdfileDirective(cmdfile)
    except:
        cmdfileDirective = 'unknown'

    try:
        out['mtime']            = mtime
        out['calls']            = calls
        out['commDirective']    = directive
        out['cmdfileDirective'] = cmdfileDirective
        out['logout']   = logout
        out['shutdown'] = shutdown
        out['recovery'] = recovery
        if connected is not None:
            out['connect']  = connected
        if disconnected is not None: 
            out['disconnect']  = disconnected

        if last_GPS is not None:
            out['fix']      = time.mktime(last_GPS.datetime)
            out['lat']      = Utils.ddmm2dd(last_GPS.lat)
            out['lon']      = Utils.ddmm2dd(last_GPS.lon)
    except Exception as e:
        print(e)
        
    try:
        conn = await aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True)
        Utils.logDB(f"summary open {glider}")
    except Exception as e:
        print(e)
        return out

    try:
        conn.row_factory = rowToDict
        cur = await conn.cursor()
    
        await cur.execute(
            "select dive,log_glider,batt_volts_10v,batt_volts_24v,batt_capacity_10v,batt_capacity_24v,log_start,total_flight_time_s,log_gps_time,error_count,max_depth,log_d_grid,meters_to_target,log_d_tgt,log_t_dive,log_tgt_lat,log_tgt_lon,energy_dives_remain_modeled,energy_days_remain_modeled,energy_end_time_modeled,log_internal_pressure,log_internal_pressure_slope,log_humid,log_humid_slope,implied_volmax,implied_volmax_slope,capture,criticals,alerts,distance_made_good,distance_to_goal,dog_efficiency,distance_over_ground from dives order by dive desc limit 1"
        )
        data = await cur.fetchone()
        # data = {k:v for k,v in data.items() if v is not None}
        if data:
            data = dict(map(lambda x: (x[0], x[1] if x[1] is not None else 0), data.items()))

        await cur.execute(
            f"select pitch_volts,roll_volts,vbd_volts,vbd_eff from gc where dive={int(data['dive'])} order by vbd_eff desc limit 1",
        )
        gc = await cur.fetchone()

        await cur.execute(
            "SELECT log_gps2_time FROM dives WHERE dive=1",
        )
        start = await cur.fetchone()
    except Exception as e:
        print(f'database error {dbfile} {e}')
        Utils.logDB(f"summary close (except) {glider}")
        await conn.close()
        return out

    Utils.logDB(f"summary close {glider}")
    await conn.close()

    out['name'] = int(data['log_glider'])
    out['dive'] = int(data['dive'])
    out['length'] = int(data['log_gps_time']) - int(data['log_start'])
    out['end']  = int(data['log_gps_time'])
    out['next'] = int(data['log_gps_time']) + out['length'] # + (int(data['log_gps2_time']) - int(data['log_gps1_time]'))

    out['dmg'] = data['distance_made_good']
    out['dog'] = data['distance_over_ground']
    out['dtg'] = data['distance_to_goal']
    out['dogEfficiency'] = data['dog_efficiency']

    if gc:
        out['vbdEfficiency'] = gc['vbd_eff']
        out['vbdVolts'] = gc['vbd_volts']
    else:
        out['vbdEfficiency'] = 0
        out['vbdVolts'] = 0

    out['depth']    = data['max_depth']
    out['grid']     = data['log_D_GRID']
    out['volts']    = [ data['batt_volts_10V'], data['batt_volts_24V'] ] 
    out['capacity'] = [ data['batt_capacity_10V'], data['batt_capacity_24V'] ]
    out['errors']   = data['error_count']

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
    msg = asyncio.run(collectSummary(int(sys.argv[1]), sys.argv[2]))
    print(msg)
