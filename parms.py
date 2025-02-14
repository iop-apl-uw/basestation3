import pickle
import sys
import re
import json
import aiofiles
import aiofiles.os
import asyncio
from anyio import Path
import parmdata
import aiosqlite

def rowToDict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

async def state(d, logfile=None, cmdfile=None, capfile=None, dbfile=None):
    if not d:
        d = parmdata.parms

    if capfile and logfile == None:
        currfile = capfile
        r = re.compile('[0-9]+.[0-9]+,SUSR,N,\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')
    else:
        currfile = logfile
        r = re.compile('\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')

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
                        d['SENSORS'] = sensors;
        except:
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
            except:
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
                                n = int(v)
                            else:
                                n = float(v)
                            
                            if d[p]['current'] != n:
                                d[p]['waiting'] = n
        except:
            pass

    if 'SENSORS' in d and d['SENSORS'] and 'LOGGERS' in d:
        loggers = d['SENSORS'][6:]
        d['LOGGERS']['help'] = f'Logger devices enable/disable control (1: {loggers[0]}, 2: {loggers[1]}, 4: {loggers[2]}, 8: {loggers[3]})'
        d['LOGGERS']['bitfield'] = [{'value': 1, 'function': loggers[0]}, 
                                    {'value': 2, 'function': loggers[1]}, 
                                    {'value': 4, 'function': loggers[1]}, 
                                    {'value': 8, 'function': loggers[1]}];
    
    return d
    
if __name__ == "__main__":
    if '.cap' in sys.argv[1]:
        d = asyncio.run(state(None, capfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))
    else:
        d = asyncio.run(state(None, logfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))

    print(d)
