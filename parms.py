## Copyright (c) 2023, 2025  University of Washington.
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

import asyncio
import re
import sys

import aiofiles
import aiofiles.os
import aiosqlite

import parmdata


def rowToDict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

async def state(d, logfile=None, cmdfile=None, capfile=None, dbfile=None):
    if not d:
        d = parmdata.parms

    if capfile and logfile is None:
        currfile = capfile
        r = re.compile(r'[0-9]+.[0-9]+,SUSR,N,\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')
    else:
        currfile = logfile
        r = re.compile(r'\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')

    if currfile and await aiofiles.os.path.exists(currfile):
        try:
            async with aiofiles.open(currfile, 'r') as f:
                async for line in f:
                    if m := r.match(line):
                        p = m.groupdict()['param']
                        v = m.groupdict()['value']
                        if p in d:
                            if d[p]['type'] == 'INT':
                                d[p]['current'] = int(v)
                            else:
                                d[p]['current'] = float(v)
                    elif line.startswith('$SENSORS'):
                        sensors = line.strip().split(',')[1:]
                        d['SENSORS'] = sensors
                    elif line.startswith('$TGT_NAME'):
                        d['TGT_NAME'] = line.strip().split(',')[1]
        except Exception:
            pass

    elif dbfile and await aiofiles.os.path.exists(dbfile):
        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            conn.row_factory = rowToDict
            cur = await conn.cursor()
            try:
                await cur.execute('SELECT * FROM dives ORDER BY dive DESC LIMIT 1')
                latest = await cur.fetchone() 
                for p in d:
                    if 'log_' + p in latest:
                        d[p]['current'] = latest['log_' + p]

                if 'log_SENSORS' in latest:
                    d['SENSORS'] = latest['log_SENSORS'].split(',')
                if 'log_TGT_NAME' in latest:
                    d['TGT_NAME'] = latest['log_TGT_NAME']
            except Exception:
                pass
    
    if cmdfile and await aiofiles.os.path.exists(cmdfile):
        try:
            async with aiofiles.open(cmdfile, 'r') as f:
                async for line in f:
                    if m := r.match(line):
                        p = m.groupdict()['param']
                        v = m.groupdict()['value']
                        if p in d:
                            if d[p]['type'] == 'INT':
                                try:
                                    n = int(v)
                                except Exception:
                                    continue
                            else:
                                try:
                                    n = float(v)
                                except Exception:
                                    continue
 
                            if f"{d[p]['current']}" != f"{n}":
                                print(f"changing {p} {d[p]['current']} to {n}")
                                d[p]['waiting'] = n
        except Exception:
            pass

    if 'SENSORS' in d and d['SENSORS'] and 'LOGGERS' in d:
        loggers = d['SENSORS'][6:]
        d['LOGGERS']['help'] = f'Logger devices enable/disable control (1: {loggers[0]}, 2: {loggers[1]}, 4: {loggers[2]}, 8: {loggers[3]})'
        d['LOGGERS']['bitfield'] = [{'value': 1, 'function': loggers[0]}, 
                                    {'value': 2, 'function': loggers[1]}, 
                                    {'value': 4, 'function': loggers[1]}, 
                                    {'value': 8, 'function': loggers[1]}]
    
    return d
  
async def parameterChanges(dive, logname, cmdname):

    p = await state(None, logfile=logname, cmdfile=cmdname)

    changes = []
    for x in p:
        if 'waiting' in p[x]:
            changes.append(  { "dive": dive, "parm": x, "oldval": p[x]['current'], "newval": p[x]['waiting'] } )

    return changes


if __name__ == "__main__":
    if '.cap' in sys.argv[1]:
        d = asyncio.run(state(None, capfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))
    else:
        d = asyncio.run(state(None, logfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))

    print(d)
