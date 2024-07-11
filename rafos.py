import sys
import datetime
import Utils
import Utils2
import ExtractTimeseries
import scipy
import asyncio
import aiofiles
from anyio import Path
import json

async def hitsTable(path):
    p = Path(path)
    minDive = 100000
    maxDive = 0
    hits = {}
    async for fpath in p.glob('p???????.log'):
        async with aiofiles.open(fpath, 'rb') as f:
            data = (await f.read()).decode('utf-8', errors='ignore')
            for line in data.splitlines():
                
                line = line.strip()
                if line.startswith('$DIVE'):
                    pcs = line.split(',')
                    dive = int(pcs[1])
                    if dive > maxDive:
                        maxDive = dive
                    if dive < minDive:
                        minDive = dive
                elif line.startswith('$ID'):
                    pcs = line.split(',')
                    glider = int(pcs[1])
                elif line.startswith('$MODEM,'):
                    pcs = line.split(',')
                    if len(pcs) != 7:
                        continue
                    
                    src = int(pcs[1])
                    arrival_t = int(pcs[2])
                    srcLat = float(pcs[3])
                    srcLon = float(pcs[4])
                    travel = float(pcs[5])
                    dist   = float(pcs[6])
                    if arrival_t in hits:
                        hits[arrival_t].update({ 'srcLat': srcLat, 'srcLon': srcLon, 'travel': travel, 'range': dist, 'src': src, 'dive': dive, 'glider': glider})
                    else:
                        hits[arrival_t] = { 'srcLat': srcLat, 'srcLon': srcLon, 'travel': travel, 'range': dist, 'src': src, 'dive': dive, 'glider': glider}
                elif line.startswith('$MODEM_MSG,CACST'):
                    pcs = line.split(',')
                    yyyymmddhhmmss = pcs[4]    
                    mfd = pcs[6]

                    year = int(yyyymmddhhmmss[0:4])
                    mo   = int(yyyymmddhhmmss[4:6])
                    day  = int(yyyymmddhhmmss[6:8])
                    hour = int(yyyymmddhhmmss[8:10])
                    minu = int(yyyymmddhhmmss[10:12])
                    sec  = float(yyyymmddhhmmss[12:])
                   
                    epoch_t = int(datetime.datetime(year, mo, day, hour, minu, int(sec)).timestamp())
                    if epoch_t in hits:
                        hits[epoch_t].update({ 'CACST': ','.join(pcs[2:]), 'mfd': mfd, 'dive': dive })
                    else:
                        hits[epoch_t] = { 'CACST': ','.join(pcs[2:]), 'mfd': mfd, 'dive': dive } 


    hits = [ (lambda d: d.update(epoch=k) or d)(v) for (k,v) in hits.items() ]
    hits = sorted(hits, key=lambda x: x['epoch'])

    ncfilename = Utils2.get_mission_timeseries_name(None, path)

    print(minDive, maxDive)
    whichVars = ['latitude', 'longitude', 'depth']
    data = ExtractTimeseries.extractVars(ncfilename, whichVars, minDive, maxDive)
    del(data['time'])

    fla = scipy.interpolate.interp1d(data['epoch'], data['latitude'], bounds_error=False, fill_value=0.0)
    flo = scipy.interpolate.interp1d(data['epoch'], data['longitude'], bounds_error=False, fill_value=0.0)
    fde = scipy.interpolate.interp1d(data['epoch'], data['depth'], bounds_error=False, fill_value=0.0)
    for h in hits:
        gliderLat = fla(h['epoch'])[()]
        gliderLon = flo(h['epoch'])[()]
        gliderDep = fde(h['epoch'])[()]
        rng = Utils.haversine(gliderLat, gliderLon, h['srcLat'], h['srcLon'])
        h.update({'gliderLat': gliderLat, 'gliderLon': gliderLon, 'trueRange': rng, 'depth': gliderDep})

    print(hits)
    return hits

if __name__ == "__main__":
    hits = asyncio.run(hitsTable('./'))
    print(json.dumps(hits, indent=2))
