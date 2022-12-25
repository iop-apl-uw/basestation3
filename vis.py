#!/usr/bin/env python3.9

import json
import time
import os
import os.path
from parse import parse
import glob
#import _thread
#from watchdog.observers import Observer
#from watchdog.events import PatternMatchingEventHandler
import sqlite3
import tempfile
import subprocess
import sys
import LogHTML
import summary
import ExtractBinnedProfiles
import ExtractTimeseries
from zipfile import ZipFile
from io import BytesIO
import sanic
import aiofiles
import asyncio
import aiohttp
import sanic_gzip

commFile = {}
watchList = {}
baseStatus = {}
baseTrigger = {}
opTable = []

watchFiles = ['comm.log', 'cmdfile', '.completed']

app = sanic.Sanic("SGpilot")            
compress = sanic_gzip.Compress()

def rowToDict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

def gliderPath(glider, request):
    if 'mission' in request.args and request.args['mission'] != 'current' and len(request.args['mission']) > 0:
        mission = request.args['mission'][0]
        return f'sg{glider:03d}/{mission}'
    else:
        return f'sg{glider:03d}'

#
# GET handlers - most of the API
#

app.static('/favicon.ico', f'{sys.path[0]}/html/favicon.ico', name='favicon.ico')
app.static('/parms', f'{sys.path[0]}/html/Parameter_Reference_Manual.html', name='parms')
app.static('/index', f'{sys.path[0]}/html/index.html', name='index')
app.static('/script', f'{sys.path[0]}/scripts', name='script')
app.static('/script/images', f'{sys.path[0]}/scripts/images', name='script_images')

@app.exception(sanic.exceptions.NotFound)
def pageNotFound(request, exception):
    return sanic.response.text("Page not found: {}".format(request.path), status=404)

@app.route('/png/<which:str>/<glider:int>/<dive:int>/<image:str>')
async def pngHandler(request, which:str, glider: int, dive: int, image: str):
    if which == 'dv':
        filename = f'{gliderPath(glider,request)}/plots/dv{dive:04d}_{image}.png'
    elif which == 'eng':
        filename = f'{gliderPath(glider,request)}/plots/eng_{image}.png'
    elif which == 'section':
        filename = f'{gliderPath(glider,request)}/plots/sg_{image}.png'
    else:
        return sanic.response.text('not found', status=404)

    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='image/png')
    else:
        return sanic.response.text('not found', status=404)
        

@app.route('/div/<which:str>/<glider:int>/<dive:int>/<image:str>')
async def divHandler(request, which: str, glider: int, dive: int, image: str):
    if which == 'dv':
        filename = f'{gliderPath(glider,request)}/plots/dv{dive:04d}_{image}.div'
    elif which == 'eng':
        filename = f'{gliderPath(glider,request)}/plots/eng_{image}.div'
    elif which == 'section':
        filename = f'{gliderPath(glider,request)}/plots/sg_{image}.div'
    else:
        return sanic.response.text('not found', status=404)

    if os.path.exists(filename):
        resp = '<script src="/script/plotly-latest.min.js"></script><html><head><title>%03d-%d-%s</title></head><body>' % (glider, dive, image)
        if which == 'dv':
            resp = resp + f'<a href="/div/{which}/{glider}/{dive-1}/{image}"style="text-decoration:none; font-size:32px;">&larr;</a><span style="font-size:32px;"> &#9863; </span> <a href="/div/{which}/{glider}/{dive+1}/{image}" style="text-decoration:none; font-size:32px;">&rarr;</a>'

        async with aiofiles.open(filename, 'r') as file:
            div = await file.read() 

        resp = resp + div + '</body></html>'
        return sanic.response.html(resp)
    else:
        return sanic.response.text('not found', status=404)
       
@app.route('/<glider:int>')
async def mainHandler(request, glider:int):
    global watchList

    filename = f'{gliderPath(glider,request)}/comm.log'
    if os.path.exists(filename):
        if glider not in watchList:
            watchList[glider] = { "path": f'{gliderPath(glider,request)}' }

            for f in watchFiles: 
                filename = f'{gliderPath(glider,request)}/{f}' 
                if os.path.exists(filename):
                    t = os.path.getmtime(filename)
                else:
                    t = 0

                watchList[glider].update({ f:t })

        filename = f'{sys.path[0]}/html/vis.html'
        return await sanic.response.file(filename, mime_type='text/html')
    else:
        return sanic.response.text("oops")             

@app.route('/map/<glider:int>')
async def mapHandler(request, glider:int):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/map/<glider:int>/<extras:path>')
async def multimapHandler(request, glider:int, extras):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/kml/<glider:int>')
async def kmlHandler(request, glider:int):
    filename = f'{gliderPath(glider,request)}/sg{glider}.kmz'
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
    (dvplots, plotlyplots) = buildPlotsList(gliderPath(glider,request), dive)
    message = {}
    message['glider']      = f'SG{glider:03d}'
    message['dive']        = dive
    message['dvplots']     = dvplots
    message['plotlyplots'] = plotlyplots
    # message['engplots']    = engplots
    
    return sanic.response.json(message)

@app.route('/log/<glider:int>/<dive:int>')
async def logHandler(request, glider:int, dive:int):
    filename = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.log'
    s = LogHTML.captureTables(filename)
    return sanic.response.html(s)

@app.route('/file/<ext:str>/<glider:int>/<dive:int>')
async def logengcapFileHandler(request, ext:str, glider: int, dive: int):
    filename = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.{ext}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/plain')
    else:
        if ext == 'cap':
            return sanic.response.text('none')
        else:
            return sanic.response.text('not found', status=404)
       
@app.route('/alerts/<glider:int>/<dive:int>')
async def alertsHandler(request, glider: int, dive: int):
    filename = f'{gliderPath(glider,request)}/alert_message.html.{dive:d}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/plain')
    else:
        return sanic.response.text('not found')
 
@app.route('/deltas/<glider:int>/<dive:int>')
async def deltasHandler(request, glider: int, dive: int):
    cmdfile = f'{gliderPath(glider,request)}/cmdfile.{dive:d}'
    logfile = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.log'
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
        filename = f'{gliderPath(glider,request)}/{f}.{dive}'

        if os.path.exists(filename):
            with open(filename, 'r') as file:
                c = file.read() 

            message['file'].append({ "file": f, "contents":c }) 

    return sanic.response.json(message)

@app.route('/optable/<mask:int>')
async def optableHandler(request, mask:int):
    global opTable

    opTable = []
    with open('ops.dat', 'r') as file:
        for line in file:
            pieces = line.strip().split('/')
            glider = int(pieces[0][2:])
            if len(pieces) == 1:
                cmdfile = f"sg{glider:03d}/cmdfile"
                opTable.append({"mission": '', "glider": glider, "cmdfile": os.path.getmtime(cmdfile)})
            else: 
                opTable.append({"mission": pieces[1], "glider": glider, "cmdfile": None})

    return sanic.response.json(opTable)
 
@app.route('/summary/<glider:int>')
async def summaryHandler(request, glider:int):
    msg = summary.collectSummary(glider, gliderPath(glider,request))
    return sanic.response.json(msg)

# this does setup and might get called after .completed is touched
@app.route('/status/<glider:int>')
async def statusHandler(request, glider:int):
    (maxdv, dvplots, engplots, sgplots, plotlyplots, engplotly, sgplotly) = buildFileList(gliderPath(glider, request))

    message = {}
    message['glider'] = f'SG{glider:03d}'
    message['dive'] = maxdv
    message['engplots'] = engplots
    message['sgplots'] = sgplots
    message['engplotly'] = engplotly;
    message['sgplotly'] = sgplotly;
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
    filename = f'{gliderPath(glider,request)}/{which}'

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
    pieces = args.split('/')
    if len(pieces) == 0 or len(pieces) > 2:
        return sanic.response.text("oops")

    try:
        glider = int(pieces[0])
    except:
        return sanic.response.text("oops")

    dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
    if not os.path.exists(dbfile):
        return sanic.response.text('no db')

    q = "SELECT dive,log_start,log_D_TGT,log_D_GRID,log__CALLS,log__SM_DEPTHo,log__SM_ANGLEo,log_HUMID,log_TEMP,log_INTERNAL_PRESSURE,depth_avg_curr_east,depth_avg_curr_north,max_depth,pitch_dive,pitch_climb,batt_volts_10V,batt_volts_24V,batt_capacity_24V,batt_capacity_10V,total_flight_time_s,avg_latitude,avg_longitude,target_name,magnetic_variation,mag_heading_to_target,meters_to_target,GPS_north_displacement_m,GPS_east_displacement_m,flight_avg_speed_east,flight_avg_speed_north FROM dives"

    if len(pieces) == 2:
        dive = int(pieces[1])
        q = q + f" WHERE dive={dive};"
    else:
        q = q + " ORDER BY dive ASC;"

    print(dbfile)
    with sqlite3.connect(dbfile) as conn:
        conn.row_factory = rowToDict
        cur = conn.cursor()
        try:
            cur.execute(q)
        except sqlite3.OperationalError:
            return sanic.response.text('no table')

        data = cur.fetchall()
        return sanic.response.json(data)

@app.route('/dbvars/<glider:int>')
async def dbvarsHandler(request, glider:int):
    dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
    dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
    if not os.path.exists(dbfile):
        return sanic.response.text('no db')

    print(dbfile)
    with sqlite3.connect(dbfile) as conn:
        try:
            cur = conn.execute('select * from dives')
        except sqlite3.OperationalError:
            return sanic.response.text('no table')
        names = list(map(lambda x: x[0], cur.description))
        data = {}
        data['names'] = names
        return sanic.response.json(data)

@app.route('/provars/<glider:int>')
async def provarsHandler(request, glider:int):
    ncfiles = glob.glob(f'{gliderPath(glider,request)}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = {}
        data['names'] = ExtractBinnedProfiles.getVarNames(ncfiles[0])
        return sanic.response.json(data)
    else: 
        return sanic.response.text('oops')

@app.route('/pro/<glider:int>/<which:str>/<first:int>/<last:int>/<stride:int>/<zStride:int>')
@compress.compress()
async def proHandler(request, glider:int, which:str, first:int, last:int, stride:int, zStride:int):
    ncfiles = glob.glob(f'{gliderPath(glider,request)}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = ExtractBinnedProfiles.extractVar(ncfiles[0], which, first, last, stride, zStride)
        return sanic.response.json(data)
    else:
        return sanic.response.text('oops')

@app.route('/timevars/<glider:int>/<dive:int>')
async def timeSeriesVarsHandler(request, glider:int,dive:int):
    ncfile = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.nc'
    if os.path.exists(ncfile):
        data = ExtractTimeseries.getVarNames(ncfile)
        return sanic.response.json(data)
    else: 
        return sanic.response.text('oops')

@app.route('/time/<glider:int>/<dive:int>/<which:str>')
@compress.compress()
async def timeSeriesHandler(request, glider:int, dive:int, which:str):
    ncfile = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.nc'
    if os.path.exists(ncfile):
        data = ExtractTimeseries.extractVars(ncfile, which.split(','))
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

    with sqlite3.connect(f'{gliderPath(glider,request)}/sg{glider:03d}.db') as conn:
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

    path = gliderPath(glide, request)
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
# web socket (real-time streams), including the get handler for notifications
# from the basestation
#

@app.route('/url')
async def urlHandler(request):
    glider = int(request.args['instrument_name'][0][2:])
    dive   = int(request.args['dive'][0]) if 'dive' in request.args else None
    files  = request.args['files'][0] if 'files' in request.args else None
    status = request.args['status'][0] if 'status' in request.args else None
    gpsstr = request.args['gpsstr'][0] if 'gpsstr' in request.args else None
  
    if status:
        baseStatus[glider] = f"status={status}"
    elif gpsstr:
        baseStatus[glider] = f"gpsstr={gpsstr}"

    if files:
        baseTrigger[glider] = {"which": files, "dive": dive}

    return sanic.response.text('ok')
 

def checkFileMods(w):
    mod = []
    for g in w.keys():
        for f in watchFiles:
            filename = f"{w[g]['path']}/{f}"
            if os.path.exists(filename):
                t = os.path.getmtime(filename)
                if t > w[g][f]:
                    mod.append(f)
                    w[g][f] = t

    return mod

@app.websocket('/stream/<glider:int>')
async def streamHandler(request: sanic.Request, ws: sanic.Websocket, glider:int):
    global commFile
    global watchList
    global baseTrigger

    filename = f'{gliderPath(glider,request)}/comm.log'
    if not os.path.exists(filename):
        await ws.send('no')
        return

    if glider not in commFile:
        commFile[glider] = open(filename, 'rb')
        commFile[glider].seek(-10000, 2)
        data = commFile[glider].read().decode('utf-8', errors='ignore')
        watchList[glider]['comm.log'] = os.path.getmtime(f"{watchList[glider]['path']}/comm.log")
        if data:
            await ws.send(data)

    while True:
        modFiles = checkFileMods(watchList)
        if 'comm.log' in modFiles and glider in commFile and commFile[glider]:
            data = commFile[glider].read().decode('utf-8', errors='ignore')
            if data:
                await ws.send(data)
        elif 'cmdfile' in modFiles:
            filename = f'{gliderPath(glider,request)}/cmdfile'
            with open(filename, 'rb') as file:
                data = "CMDFILE=" + file.read().decode('utf-8', errors='ignore')
                await ws.send(data)
        elif glider in baseTrigger:
            await ws.send(f"NEW={glider},{baseTrigger[glider]['dive']},{baseTrigger[glider]['which']}")
            del baseTrigger[glider]

        await asyncio.sleep(2)

@app.websocket('/watch')
async def watchHandler(request: sanic.Request, ws: sanic.Websocket):
    global baseStatus
    global opTable
     
    while True:
        for o in opTable:
            if o['glider'] in baseStatus:
                print(f"{o['glider']} baseStatus")
                await ws.send(f"NEW={o['glider']},{baseStatus[o['glider']]}")
                del baseStatus[o['glider']]
                
            t = os.path.getmtime(f"sg{o['glider']:03d}/cmdfile")
            if o['cmdfile'] != None and t > o['cmdfile']:
                print(f"{o['glider']} cmdfile")
                await ws.send(f"NEW={o['glider']},cmdfile")
                o['cmdfile'] = t

        await asyncio.sleep(2) 
#
#  other stuff (non-Sanic)
#
 
def buildPlotsList(path, dive):
    dvplots = []
    plotlyplots = []
    for fullFile in glob.glob('%s/plots/dv%04d_*.png' % (path, dive)):
        file = os.path.basename(fullFile)
        if file.startswith('dv'):
            x = parse('dv{}_{}.png', file)
            plot = x[1] 
            dvplots.append(plot)
            if os.path.exists(fullFile.replace("png", "div")):
                plotlyplots.append(plot)

    return (dvplots, plotlyplots)
 
def buildFileList(path):
    maxdv = -1
    dvplots = []
    engplots = []
    sgplots = []
    plotlyplots = []
    engplotly = []
    sgplotly = []
    for fullFile in glob.glob(f'{path}/plots/*.png'):
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
            plot = '_'.join(pieces[0].split('_')[1:])
            engplots.append(plot)
            divFile = fullFile.replace("png", "div")
            if os.path.exists(divFile):
                engplotly.append(plot)

        elif file.startswith('sg') and "section" not in file:
            pieces = file.split('.')
            plot = '_'.join(pieces[0].split('_')[1:])
            sgplots.append(plot)
            divFile = fullFile.replace("png", "div")
            if os.path.exists(divFile):
                sgplotly.append(plot)

    return (maxdv, dvplots, engplots, sgplots, plotlyplots, engplotly, sgplotly)

if __name__ == '__main__':
    os.chdir("/home/seaglider")

    if len(sys.argv) == 2:
        port = int(sys.argv[1])
    else:
        port = 20001

    app.run(host='0.0.0.0', port=port, access_log=True, debug=True)
