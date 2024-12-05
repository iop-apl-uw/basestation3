import pickle
import sys
import re
import json
import aiofiles
import asyncio
import os
from anyio import Path

async def cmdfile(path, cmdfile):
    r = re.compile('\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')
    d = {}
    try:
        async with aiofiles.open(os.path.join(path, cmdfile), 'r') as f:
            async for line in f:
                if m := r.match(line):
                    p = m.groupdict()['param']
                    v = m.groupdict()['value']
                    d[p] = {}
                    if p in d:
                        if d[p]['type'] == 'INT':
                            n = int(v)
                        else:
                            n = float(v)
                        
                        if d[p]['current'] != n:
                            d[p]['waiting'] = n
    except:
        pass

    return d

async def update(d, path, logfile=None, cmdfile=None, capfile=None):
    if capfile and logfile == None:
        currfile = capfile
        r = re.compile('[0-9]+.[0-9]+,SUSR,N,\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')
    else:
        currfile = logfile
        r = re.compile('\$(?P<param>\w+),(?P<value>[+-]?([0-9]*[.])?[0-9]+)')
    if currfile and await Path(os.path.join(path, currfile)).exists():
        try:
            async with aiofiles.open(os.path.join(path, currfile), 'r') as f:
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

    if 'SENSORS' in d and d['SENSORS'] and 'LOGGERS' in d:
        loggers = d['SENSORS'][6:]
        d['LOGGERS']['help'] = f'Logger devices enable/disable control (1: {loggers[0]}, 2: {loggers[1]}, 4: {loggers[2]}, 8: {loggers[3]})'
        d['LOGGERS']['bitfield'] = [{'value': 1, 'function': loggers[0]}, 
                                    {'value': 2, 'function': loggers[1]}, 
                                    {'value': 4, 'function': loggers[1]}, 
                                    {'value': 8, 'function': loggers[1]}];
    
    return d
    
async def read(path, logfile=None, cmdfile=None, capfile=None):

    async with aiofiles.open(sys.path[0] + "/parms.json", 'r') as f:
        o = await f.read()
    
    d = json.loads(o)

    groups = set([ d[k]['category'] for k in d])

    # roll = { k:v for k, v in d.items() if v['category'] == 'ROLL' }


    return await update(d, path, logfile=logfile, cmdfile=cmdfile, capfile=capfile)

def readSync(path, logfile=None, cmdfile=None, capfile=None):
    loop = asyncio.get_event_loop()
    d = loop.run_until_complete(read(path, logfile=logfile, cmdfile=cmdfile, capfile=capfile))
    return d
 
if __name__ == "__main__":
    if '.cap' in sys.argv[1]:
        d = asyncio.run(read('./', capfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))
    else:
        d = asyncio.run(read('./', logfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))

    print(d)
