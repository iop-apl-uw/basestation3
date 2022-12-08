#!/usr/bin/env python3.9

import json
import time
import os
import os.path
from parse import parse
import glob
import _thread
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import sqlite3
import tempfile
import subprocess
import sys
import LogHTML
import ExtractBinnedProfiles
from zipfile import ZipFile
from io import BytesIO
import sanic
import aiofiles
import asyncio
import aiohttp
import sanic_gzip

modifiedFile = {}
newDive = {}
newFile = {}
commFile = {}
watchThread = {}

app = sanic.Sanic("SGpilot")            
compress = sanic_gzip.Compress()

def rowToDict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

#
# GET handlers - most of the API
#

@app.exception(sanic.exceptions.NotFound)
def pageNotFound(request, exception):
    return sanic.response.text("Page not found: {}".format(request.path), status=404)

@app.route('/png/<glider:int>/<dive:int>/<image:str>')
async def pngHandler(request, glider: int, dive: int, image: str):
    filename = f'sg{glider:03d}/plots/dv{dive:04d}_{image}.png'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='image/png')
    else:
        return sanic.response.text('not found', status=404)
        

@app.route('/div/<glider:int>/<dive:int>/<image:str>')
async def divHandler(request, glider: int, dive: int, image: str):
    filename = f'sg{glider:03d}/plots/dv{dive:04d}_{image}.div'
    
    if os.path.exists(filename):
        resp = '<script src="/script/plotly-latest.min.js"></script><html><head><title>%03d-%d-%s</title></head><body>' % (glider, dive, image)
        resp = resp + f'<a href="/div/{glider}/{dive-1}/{image}">prev</a> * <a href="/div/{glider}/{dive+1}/{image}">next</a>'

        async with aiofiles.open(filename, 'r') as file:
            div = await file.read() 

        resp = resp + div + '</body></html>'
        return sanic.response.html(resp)
    else:
        return sanic.response.text('not found', status=404)
        

@app.route('/eng/<glider:int>/<image:str>')
async def engHandler(request, glider:int, image:str):
    filename = f'sg{glider:03d}/plots/eng_{image}.png'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='image/png')
    else:
        return sanic.response.text('not found', status=404)

@app.route('/section/<glider:int>/<image:str>')
async def sectionHandler(request, glider:int, image:str):
    filename = f'sg{glider:03d}/plots/sg_{image}.png'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='image/png')
    else:
        return sanic.response.text('not found', status=404)

@app.route('/script/<script:str>')
async def scriptHandler(request, script:str):
    filename = f'{sys.path[0]}/scripts/{script}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/html')
    else:
        return sanic.response.text('not found', status=404)

@app.route('/script/images/<image:str>')
async def scriptImageHandler(request, image:str):
    filename = f'{sys.path[0]}/scripts/images/{image}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='image/png')
    else:
        return sanic.response.text('not found', status=404)

@app.route('/favicon.ico')
async def faviconHandler(request):
    filename = f'{sys.path[0]}/html/favicon.ico'
    return await sanic.response.file(filename, mime_type='image/x-icon')

@app.route('/<glider:int>')
async def mainHandler(request, glider:int):
    filename = f'sg{glider}/comm.log'
    if os.path.exists(filename):
        if glider not in watchThread:
            watchThread[glider] = _thread.start_new_thread(watchFilesystem, (glider,))

        filename = f'{sys.path[0]}/html/vis.html'
        return await sanic.response.file(filename, mime_type='text/html')
    else:
        return sanic.response.text("oops")             

@app.route('/<glider:int>/<dive:int>')
async def main2Handler(request, glider:int, dive:int):
    return await mainHandler(request, glider)

@app.route('/<glider:int>/order/<order:str>')
async def main3Handler(request, glider:int, order:str):
    return await mainHandler(request, glider)

@app.route('/map/<glider:int>')
async def mapHandler(request, glider:int):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/map/<glider:int>/<extras:path>')
async def multimapHandler(request, glider:int, extras):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/parms')
async def parmsHandler(request):
    filename = f'{sys.path[0]}/html/Parameter_Reference_Manual.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/kml/<glider:int>')
async def kmlHandler(request, glider:int):
    filename = f'sg{glider}/sg{glider}.kmz'
    with open(filename, 'rb') as file:
        zip = ZipFile(BytesIO(file.read()))
        kml = zip.open(f'sg{glider}.kml', 'r').read()
        return sanic.response.raw(kml)

# do we need this for anything?? not yet
@app.route('/data/<file:str>')
async def dataHandler(request, file:str):
    filename = f'{sys.path[0]}/data/{file}'
    return await sanic.response.file(filename)

@app.route('/proxy/<url:path>')
async def proxyHandler(request, url):
    if request.args and len(request.args) > 0:
        url = url + '?' + request.query_string
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                body = await response.read()
                return sanic.response.raw(body)
    
@app.route('/plots/<glider:int>/<dive:int>')
async def plotsHandler(request, glider:int, dive:int):
    (dvplots, plotlyplots) = buildPlotsList(glider, dive)
    message = {}
    message['glider']      = f'SG{glider:03d}'
    message['dive']        = dive
    message['dvplots']     = dvplots
    message['plotlyplots'] = plotlyplots
    # message['engplots']    = engplots
    
    return sanic.response.json(message)

@app.route('/log/<glider:int>/<dive:int>')
async def logHandler(request, glider:int, dive:int):
    filename = f'sg{glider:03d}/p{glider:03d}{dive:04d}.log'
    s = LogHTML.captureTables(filename)
    return sanic.response.html(s)

@app.route('/logfile/<glider:int>/<dive:int>')
async def logfileHandler(request, glider: int, dive: int):
    filename = f'sg{glider:03d}/p{glider:03d}{dive:04d}.log'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/plain')
    else:
        return sanic.response.text('not found', status=404)
       
@app.route('/alerts/<glider:int>/<dive:int>')
async def alertsHandler(request, glider: int, dive: int):
    filename = f'sg{glider:03d}/alert_message.html.{dive:d}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/plain')
    else:
        return sanic.response.text('not found')
 
@app.route('/deltas/<glider:int>/<dive:int>')
async def deltasHandler(request, glider: int, dive: int):
    cmdfile = f'sg{glider:03d}/cmdfile.{dive:d}'
    logfile = f'sg{glider:03d}/p{glider:03d}{dive:04d}.log'
    if not os.path.exists(cmdfile) or not os.path.exists(logfile):
        return sanic.response.text('not found')

    cmd = f"/usr/local/bin/validate {logfile} -c {cmdfile}"
    output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    results = output.stdout
    err = output.stderr

    message = {}
    message['dive'] = dive
    message['parm'] = []    
    for line in results.splitlines():
        if "will change" in line:         
            pieces = line.split(' ')
            logvar = pieces[2]
            oldval = pieces[6]
            newval = pieces[8]
            message['parm'].append(f'{logvar},{oldval},{newval}')

    message['file'] = []

    files = ["science", "targets", "scicon.sch", "tcm2mat.cal", "pdoscmds.bat"]
    for f in files:
        filename = f'sg{glider:03d}/{f}.{dive}'

        if os.path.exists(filename):
            with open(filename, 'r') as file:
                c = file.read() 

            message['file'].append({ "file": f, "contents":c }) 

    return sanic.response.json(message)
 
@app.route('/status/<glider:int>')
async def statusHandler(request, glider:int):
    if glider in commFile and commFile[glider]:
        commFile[glider].close()
        commFile[glider] = None

    print('comm.log opened')
    commFile[glider] = open(f'sg{glider:03d}/comm.log', 'rb')
    commFile[glider].seek(-10000, 2)
    # modifiedFile[glider] = "comm.log" # do we need this to trigger initial send??

    (maxdv, dvplots, engplots, sgplots, plotlyplots) = buildFileList(glider)

    message = {}
    message['glider'] = f'SG{glider:03d}'
    message['dive'] = maxdv
    message['engplots'] = engplots
    message['sgplots'] = sgplots
    # message['dvplots'] = dvplots
    # message['plotlyplots'] = plotlyplots
    print(message)
    return sanic.response.json(message)

@app.route('/control/<glider:int>/<which:str>')
async def controlHandler(request, glider:int, which:str):
    ok = ["cmdfile", "targets", "science", "scicon.sch", "tcm2mat.cal", "pdoscmds.bat", "sg_calib_constants.m"]

    if which not in ok:
        return sanic.response.text("oops")

    message = {}

    message['file'] = 'none'
    filename = f'sg{glider:03d}/{which}'

    if os.path.exists(filename):
        message['file'] = which
        message['dive'] = -1
    else:
        versions = glob.glob(f'sg{glider:03d}/{which}.*')
        latest = -1
        call = -1;
        for v in versions:
            try:
                j = parse('%s.{:d}.{:d}' % which, v.split('/')[1])
                if j and hasattr(j, 'fixed') and len(j.fixed) == 2 and j.fixed[0] > latest and j.fixed[1] > call:
                    latest = j.fixed[0]
                    call = j.fixed[1]
                else:
                    j = parse('%s.{:d}' % which, v.split('/')[1])
                    if j and hasattr(j, 'fixed') and len(j.fixed) == 1 and j.fixed[0] > latest:
                        latest = j.fixed[0]
                        call = -1
            except Exception as e:
                print(str(e))
                continue

        if latest > -1:
            message['file'] = which
            message['dive'] = latest
            if call > -1:
                filename = f'{filename}.{latest}.{call}'
                message['call'] = call
            else:
                filename = f'{filename}.{latest}'
                message['call'] = -1

    if message['file'] == "none":
        return sanic.response.text("none")

    async with aiofiles.open(filename, 'r') as file:
        message['contents']= await file.read() 

    return sanic.response.json(message)

@app.route('/db/<args:path>')
async def dbHandler(request, args):
    q = "SELECT dive,log_start,log_D_TGT,log_D_GRID,log__CALLS,log__SM_DEPTHo,log__SM_ANGLEo,log_HUMID,log_TEMP,log_INTERNAL_PRESSURE,depth_avg_curr_east,depth_avg_curr_north,max_depth,pitch_dive,pitch_climb,batt_volts_10V,batt_volts_24V,batt_capacity_24V,batt_capacity_10V,total_flight_time_s,avg_latitude,avg_longitude,target_name,magnetic_variation,mag_heading_to_target,meters_to_target,GPS_north_displacement_m,GPS_east_displacement_m,flight_avg_speed_east,flight_avg_speed_north FROM dives"
    pieces = args.split('/')
    if len(pieces) == 0 or len(pieces) > 2:
        return sanic.response.text("oops")

    try:
        glider = int(pieces[0])
    except:
        return sanic.response.text("oops")

    if len(pieces) == 2:
        dive = int(pieces[1])
        q = q + f" WHERE dive={dive};"
    else:
        q = q + " ORDER BY dive ASC;"

    with sqlite3.connect(f'sg{glider:03d}/sg{glider:03d}.db') as conn:
        conn.row_factory = rowToDict
        cur = conn.cursor()
        cur.execute(q)
        data = cur.fetchall()
        return sanic.response.json(data)

@app.route('/dbvars/<glider:int>')
async def dbvarsHandler(request, glider:int):
    with sqlite3.connect(f'sg{glider:03d}/sg{glider:03d}.db') as conn:
        cur = conn.execute('select * from dives')
        names = list(map(lambda x: x[0], cur.description))
        data = {}
        data['names'] = names
        return sanic.response.json(data)

@app.route('/provars/<glider:int>')
async def provarsHandler(request, glider:int):
    ncfiles = glob.glob(f'sg{glider:03d}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = {}
        data['names'] = ExtractBinnedProfiles.getVarNames(ncfiles[0])
        return sanic.response.json(data)
    else: 
        return sanic.response.text('oops')

@app.route('/pro/<glider:int>/<which:str>/<first:int>/<last:int>/<stride:int>/<zStride:int>')
@compress.compress()
async def proHandler(request, glider:int, which:str, first:int, last:int, stride:int, zStride:int):
    ncfiles = glob.glob(f'sg{glider:03d}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = ExtractBinnedProfiles.extractVar(ncfiles[0], which, first, last, stride, zStride)
        return sanic.response.json(data)
    else:
        return sanic.response.text('oops')

@app.route('/query/<glider:int>/<vars:str>')
async def queryHandler(request, glider, vars):
    pieces = vars.split(',')
    if pieces[0] == 'dive':
        q = f"SELECT {vars} FROM DIVES ORDER BY dive ASC"
    else:
        q = f"SELECT {vars} FROM DIVES"

    with sqlite3.connect(f'sg{glider:03d}/sg{glider:03d}.db') as conn:
        conn.row_factory = rowToDict
        cur = conn.cursor()
        cur.execute(q)
        data = cur.fetchall()
        return sanic.response.json(data)

@app.route('/selftest/<glider:int>')
async def selftestHandler(request, glider:int):
    cmd = f"{sys.path[0]}/SelftestHTML.py {glider:03d}"
    output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    results = output.stdout
    return sanic.response.html(results)

#
# POST handler - to save files back to basestation
#

@app.post('/save/<glider:int>/<which:str>')
async def saveHandler(request, glider:int, which:str):
    validator = {"cmdfile": "cmdedit", "science": "sciedit", "targets": "targedit"}

    message = request.json
    if 'file' not in message or message['file'] != which:
        return sanic.response.text('oops')

    path = f'sg{glider:03d}'
    if which in validator:
        tempfile.tempdir = path
        tmp = tempfile.mktemp()
        with open(tmp, 'w') as file:
            file.write(message['contents'])
            file.close()
            print(message['contents'])
            print("saved to %s" % tmp)

            if 'force' in message and message['force'] == 1:
                cmd = f"{sys.path[0]}/{validator[which]} -d {path} -q -i -f {tmp}"
            else:
                cmd = f"{sys.path[0]}/{validator[which]} -d {path} -q -f {tmp}"
            print(cmd)
            output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            results = output.stdout
            err = output.stderr

        return sanic.response.text(results)

    else: # no validator for this file type
        try:
            with open(f'{path}/{which}', 'w') as file:
                file.write(message['contents'])
            return sanic.response.text(f"{which} saved ok")
        except Exception as e:
            return sanic.response.text(f"error saving {which}, {str(e)}")
            
#
# web socket (real-time streams)
#

@app.websocket('/stream/<glider:int>')
async def streamHandler(request: sanic.Request, ws: sanic.Websocket, glider:int):
    global commFile
    global modifiedFile
    global newFile
    global newDive

    if glider in commFile and commFile[glider]:
        # data = commFile[glider].read().decode('utf-8').encode('unicode_escape')
        data = commFile[glider].read().decode('utf-8', errors='ignore')
        if data:
            await ws.send(data)

    while True:
        if glider in modifiedFile and modifiedFile[glider]:
            if modifiedFile[glider] == "comm.log" and glider in commFile and commFile[glider]:
                modifiedFile[glider] = False
                data = commFile[glider].read().decode('utf-8', errors='ignore')
                if data:
                    await ws.send(data)
            elif modifiedFile[glider] == "cmdfile":
                modifiedFile[glider] = False
                filename = f'sg{glider:03d}/cmdfile'
                with open(filename, 'rb') as file:
                    data = "CMDFILE=" + file.read().decode('utf-8', errors='ignore')
                    await ws.send(data)

        if glider in newDive and newDive[glider]:
            newDive[glider] = False
            await ws.send('NEW=' + newFile[glider])

        await asyncio.sleep(1)
      
#
#  other stuff (non-Sanic)
#
 
def buildPlotsList(glider, dive):
    dvplots = []
    plotlyplots = []
    for fullFile in glob.glob('sg%03d/plots/dv%04d_*.png' % (glider, dive)):
        file = os.path.basename(fullFile)
        if file.startswith('dv'):
            x = parse('dv{}_{}.png', file)
            plot = x[1] 
            dvplots.append(plot)
            if os.path.exists(fullFile.replace("png", "div")):
                plotlyplots.append(plot)

    return (dvplots, plotlyplots)
 
def buildFileList(glider):
    maxdv = -1
    dvplots = []
    engplots = []
    sgplots = []
    plotlyplots = []
    for fullFile in glob.glob(f'sg{glider:03d}/plots/*.png'):
        file = os.path.basename(fullFile)
        if file.startswith('dv'):
            x = parse('dv{}_{}.png', file)
            try:
                dv = int(x[0])
                plot = x[1] 
                if dv > maxdv:
                    maxdv = dv
                if plot not in dvplots:
                    dvplots.append(plot)

                divFile = fullFile.replace("png", "div")
                if os.path.exists(divFile):     
                    plotlyplots.append(plot)           
            except:
                pass

        elif file.startswith('eng'):
            pieces = file.split('.')
            engplots.append('_'.join(pieces[0].split('_')[1:]))
        elif file.startswith('sg') and "section" not in file:
            pieces = file.split('.')
            sgplots.append('_'.join(pieces[0].split('_')[1:]))

    return (maxdv, dvplots, engplots, sgplots, plotlyplots)

def watchFilesystem(glider):
    print("watching")
    ignore_patterns = None
    ignore_directories = True
    case_sensitive = True

    patterns = [f"./sg{glider:03d}/comm.log"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, f"./sg{glider:03d}", recursive=False)
    observer.start()

    patterns = [f"./sg{glider:03d}/plots/dv*png"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, f"./sg{glider:03d}/plots", recursive=False)
    observer.start()

    patterns = [f"./sg{glider:03d}/cmdfile"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, f"./sg{glider:03d}", recursive=False)
    observer.start()

    while True:
        time.sleep(1)

def onCreated(evt):
    global newDive
    global newFile
    print("created %s" % evt.src_path)
    path = os.path.basename(evt.src_path)
    if path.startswith('dv'):
        try:
            glider = int(os.path.dirname(evt.src_path).split('/')[1][2:])
            newDive[glider] = True
            newFile[glider] = path
        except:
            pass

def onModified(evt):
    global modifiedFile

    print("modified %s" % evt.src_path)
    path = os.path.basename(evt.src_path)
    if path == "comm.log" or path == "cmdfile":
        try:
            glider = int(os.path.dirname(evt.src_path).split('/')[1][2:])
            # print(f"marking {glider} {path} as modified")
            modifiedFile[glider] = path
        except:
            pass

 
if __name__ == '__main__':
    os.chdir("/home/seaglider")

    if len(sys.argv) == 2:
        port = int(sys.argv[1])
    else:
        port = 20001

    app.run(host='0.0.0.0', port=port, access_log=True, debug=True)
