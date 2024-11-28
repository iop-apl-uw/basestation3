import pickle
import sys
import re
import json
import aiofiles
import asyncio
import os
from anyio import Path

async def read(path, logfile=None, cmdfile=None):

    async with aiofiles.open(sys.path[0] + "/parms.json", 'r') as f:
        o = await f.read()
    
    d = json.loads(o)

    groups = set([ d[k]['category'] for k in d])

    # roll = { k:v for k, v in d.items() if v['category'] == 'ROLL' }

    r = re.compile('\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')

    loggers = None
    sensors = None

    if logfile and await Path(os.path.join(path, logfile)).exists():
        try:
            async with aiofiles.open(os.path.join(path, logfile), 'r') as f:
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
                        sensors = line.strip().split(',')[1:7]
                        loggers = line.strip().split(',')[7:]
        except:
            pass

    if cmdfile and await Path(os.path.join(path, cmdfile)).exists():
        try:
            async with aiofiles.open(os.path.join(path, cmdfile), 'r') as f:
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

    if loggers and 'LOGGERS' in d:
        d['LOGGERS']['help'] = f'Logger devices enable/disable control (1: {loggers[0]}, 2: {loggers[1]}, 4: {loggers[2]}, 8: {loggers[3]})'
        d['LOGGERS']['bitfield'] = [{'value': 1, 'function': loggers[0]}, 
                                    {'value': 2, 'function': loggers[1]}, 
                                    {'value': 4, 'function': loggers[1]}, 
                                    {'value': 8, 'function': loggers[1]}];

    return d

if __name__ == "__main__":
    d = asyncio.run(read('./', logfile=sys.argv[1], cmdfile=sys.argv[2]))

    print(d)
