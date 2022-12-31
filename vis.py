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
import sanic_ext
from functools import wraps
import jwt
from passlib.hash import sha256_crypt
import threading
import uuid
from types import SimpleNamespace

lock = threading.Lock()

urlMessages = []

watchFiles = ['comm.log', 'cmdfile'] # rely on .urls vs '.completed']

d = { "missionTable": [] }
app = sanic.Sanic("SGpilot", ctx=SimpleNamespace(**d))
if 'SECRET' not in app.config:
    app.config.SECRET = "SECRET"
if 'MISSIONS_FILE' not in app.config:
    app.config.MISSIONS_FILE = "/home/seaglider/missions.dat"
if 'USERS_FILE' not in app.config:
    app.config.USERS_FILE = "/home/seaglider/users.dat"
if 'ROOTDIR' not in app.config:
    app.config.ROOTDIR = "/home/seaglider"

app.config.TEMPLATING_PATH_TO_TEMPLATES=f"{sys.path[0]}/html"

compress = sanic_gzip.Compress()

runMode = None

def checkToken(request, user):
    if not 'token' in request.cookies:
        return False

    try:
         token = jwt.decode(request.cookies.get("token"), request.app.config.SECRET, algorithms=["HS256"])
    except jwt.exceptions.InvalidTokenError:
        return False
    else:
        if 'user' in token and token['user'] == user:
            print(f'{user} authorized')
            return True

    print('rejected')
    return False

def checkGliderMission(request, glider, mission):
    if (len(request.app.ctx.missionTable) == 0):
        request.app.ctx.missionTable = buildMissionTable(app)
        print("built table")

    for m in request.app.ctx.missionTable:
        if m['glider'] == glider and m['mission'] == mission and m['auth'] is not None: 
            return checkToken(request, m['auth'])
        elif m['glider'] == glider and m['mission'] == mission:
            return True

    # no matching mission in table - do not allow access
    print(f'rejecting for {glider} {mission} for no mission entry')
    return False

def authorized(protections=None):
    def decorator(f):
        @wraps(f)
        async def decorated_function(request, *args, **kwargs):
            global runMode
            # run some method that checks the request
            # for the client's authorization status

            if protections and 'pilot' in protections and runMode == 'public':
                print("rejecting based on pilot")
                return sanic.response.text("Page not found: {}".format(request.path), status=404)
            elif protections and 'pilot' in protections: # we're running in pilot mode and this is pilot only 
                return await f(request, *args, **kwargs)
            
            glider = kwargs['glider'] if 'glider' in kwargs else None
            mission = request.args['mission'][0] if 'mission' in request.args else None
            
            # this will always fail and return not authorized if glider is None
            if checkGliderMission(request, glider, mission) == False:
                return sanic.response.text("authorization failed")
             
            # the user is authorized.
            # run the handler method and return the response
            response = await f(request, *args, **kwargs)
            return response
        return decorated_function
    return decorator

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
app.static('/script', f'{sys.path[0]}/scripts', name='script')
app.static('/script/images', f'{sys.path[0]}/scripts/images', name='script_images')

@app.exception(sanic.exceptions.NotFound)
def pageNotFound(request, exception):
    return sanic.response.text("Page not found: {}".format(request.path), status=404)

@app.post('/auth')
async def authHandler(request):
    username = request.json.get("username", None)
    password = request.json.get("password", None)

    with open(request.app.config.USERS_FILE, "r") as file:
        for line in file:
            if line[0] == '#':
                continue
            parts = line.split(' ')
            if len(parts) != 2:
                continue
            if parts[0] == username and sha256_crypt.verify(password, parts[1].strip()):
                token = jwt.encode({ "user": username }, request.app.config.SECRET)
                response = sanic.response.text("authorization ok")
                response.cookies["token"] = token
                return response

    return sanic.response.text('authorization failed') 

@app.route('/png/<which:str>/<glider:int>/<dive:int>/<image:str>')
@authorized()
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
@authorized()
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
       
# we don't protect this so they get a blank page with a login option even
# if not authorized
@app.route('/<glider:int>')
@app.ext.template("vis.html")
async def mainHandler(request, glider:int):
    # return await sanic_ext.render("vis.html", context={"runMode": runMode}, status=400)
    return {"runMode": runMode}

@app.route('/index')
@app.ext.template("index.html")
async def indexHandler(request):
    return {"runMode": runMode}

@app.route('/map/<glider:int>')
@authorized()
async def mapHandler(request, glider:int):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/map/<glider:int>/<extras:path>')
@authorized()
async def multimapHandler(request, glider:int, extras):
    filename = f'{sys.path[0]}/html/map.html'
    return await sanic.response.file(filename, mime_type='text/html')

@app.route('/kml/<glider:int>')
@authorized()
async def kmlHandler(request, glider:int):
    filename = f'{gliderPath(glider,request)}/sg{glider}.kmz'
    with open(filename, 'rb') as file:
        zip = ZipFile(BytesIO(file.read()))
        kml = zip.open(f'sg{glider}.kml', 'r').read()
        return sanic.response.raw(kml)

# do we need this for anything?? not yet
@app.route('/data/<file:str>')
@authorized(protections=['pilot'])
async def dataHandler(request, file:str):
    filename = f'{sys.path[0]}/data/{file}'
    return await sanic.response.file(filename)

@app.route('/proxy/<url:path>')
# This is not a great idea to leave this open as a public proxy server,
# but we need it for all layers to work with public maps t the moment.
# Need to evaluate what we lose if we turn proxy off or find another solution.
# Or limit the dictionary of what urls can be proxied ...
# NOAA forecast, NIC ice edges, iop SA list, opentopo GEBCO bathy
# @authorized(protections=['pilot'])
async def proxyHandler(request, url):
    if request.args and len(request.args) > 0:
        url = url + '?' + request.query_string
    async with aiohttp.ClientSession() as session:
        async with session.get(url) as response:
            if response.status == 200:
                body = await response.read()
                return sanic.response.raw(body)
    
@app.route('/plots/<glider:int>/<dive:int>')
@authorized()
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
@authorized()
async def logHandler(request, glider:int, dive:int):
    filename = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.log'
    s = LogHTML.captureTables(filename)
    return sanic.response.html(s)

@app.route('/file/<ext:str>/<glider:int>/<dive:int>')
@authorized()
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
@authorized()
async def alertsHandler(request, glider: int, dive: int):
    filename = f'{gliderPath(glider,request)}/alert_message.html.{dive:d}'
    if os.path.exists(filename):
        return await sanic.response.file(filename, mime_type='text/plain')
    else:
        return sanic.response.text('not found')
 
@app.route('/deltas/<glider:int>/<dive:int>')
@authorized()
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

@app.route('/missions/<mask:str>')
async def missionsHandler(request, mask:int):
    return sanic.response.json(buildAuthTable(request, mask))
 
@app.route('/summary/<glider:int>')
@authorized()
async def summaryHandler(request, glider:int):
    msg = summary.collectSummary(glider, gliderPath(glider,request))
    return sanic.response.json(msg)

# this does setup and might get called after .completed is touched
@app.route('/status/<glider:int>')
@authorized()
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
@authorized()
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

@app.route('/db/<glider:int>/<dive:int>')
@authorized()
async def dbHandler(request, glider:int, dive:int):
    dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
    if not os.path.exists(dbfile):
        return sanic.response.text('no db')

    q = "SELECT dive,log_start,log_D_TGT,log_D_GRID,log__CALLS,log__SM_DEPTHo,log__SM_ANGLEo,log_HUMID,log_TEMP,log_INTERNAL_PRESSURE,depth_avg_curr_east,depth_avg_curr_north,max_depth,pitch_dive,pitch_climb,batt_volts_10V,batt_volts_24V,batt_capacity_24V,batt_capacity_10V,total_flight_time_s,avg_latitude,avg_longitude,target_name,magnetic_variation,mag_heading_to_target,meters_to_target,GPS_north_displacement_m,GPS_east_displacement_m,flight_avg_speed_east,flight_avg_speed_north,dog_efficiency,alerts,criticals,capture,error_count FROM dives"

    if dive > -1:
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
@authorized()
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
@authorized()
async def provarsHandler(request, glider:int):
    ncfiles = glob.glob(f'{gliderPath(glider,request)}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = {}
        data['names'] = ExtractBinnedProfiles.getVarNames(ncfiles[0])
        return sanic.response.json(data)
    else: 
        return sanic.response.text('oops')

@app.route('/pro/<glider:int>/<which:str>/<first:int>/<last:int>/<stride:int>/<zStride:int>')
@authorized()
@compress.compress()
async def proHandler(request, glider:int, which:str, first:int, last:int, stride:int, zStride:int):
    ncfiles = glob.glob(f'{gliderPath(glider,request)}/sg{glider:03d}*profile.nc')
    if len(ncfiles):
        data = ExtractBinnedProfiles.extractVar(ncfiles[0], which, first, last, stride, zStride)
        return sanic.response.json(data)
    else:
        return sanic.response.text('oops')

@app.route('/timevars/<glider:int>/<dive:int>')
@authorized()
async def timeSeriesVarsHandler(request, glider:int,dive:int):
    ncfile = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.nc'
    if os.path.exists(ncfile):
        data = ExtractTimeseries.getVarNames(ncfile)
        return sanic.response.json(data)
    else: 
        return sanic.response.text('oops')

@app.route('/time/<glider:int>/<dive:int>/<which:str>')
@authorized()
@compress.compress()
async def timeSeriesHandler(request, glider:int, dive:int, which:str):
    ncfile = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.nc'
    if os.path.exists(ncfile):
        data = ExtractTimeseries.extractVars(ncfile, which.split(','))
        return sanic.response.json(data)
    else:
        return sanic.response.text('oops')

@app.route('/query/<glider:int>/<vars:str>')
@authorized()
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
@authorized(protections=['pilot'])
async def selftestHandler(request, glider:int):
    cmd = f"{sys.path[0]}/SelftestHTML.py {glider:03d}"
    output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    results = output.stdout
    return sanic.response.html(results)

#
# POST handler - to save files back to basestation
#

@app.post('/save/<glider:int>/<which:str>')
@authorized(protections=['pilot'])
async def saveHandler(request, glider:int, which:str):
    validator = {"cmdfile": "cmdedit", "science": "sciedit", "targets": "targedit"}

    message = request.json
    if 'file' not in message or message['file'] != which:
        return sanic.response.text('oops')

    path = gliderPath(glider, request)
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
    global urlMessages

    glider = int(request.args['instrument_name'][0][2:])
    dive   = int(request.args['dive'][0]) if 'dive' in request.args else None
    files  = request.args['files'][0] if 'files' in request.args else None
    status = request.args['status'][0] if 'status' in request.args else None
    gpsstr = request.args['gpsstr'][0] if 'gpsstr' in request.args else None

    if status:
        content = f"status={status}"
    elif gpsstr:
        content = f"gpsstr={gpsstr}"
    elif files:
        content = f"files={files}" 

    msg = { "glider": glider, "dive": dive, "content": content, "uuid": uuid.uuid4(), "time": time.time() }

    t = time.time() - 10
    lock.acquire()
    try:
        urlMessages = list(filter(lambda m: m['time'] < t, urlMessages))
        urlMessages.append(msg)
    except:
        pass
    lock.release()
             
    return sanic.response.text('ok')
 
def buildWatchList(request, glider):
    watchList = { "path": f'{gliderPath(glider,request)}' }

    for f in watchFiles: 
        filename = f'{gliderPath(glider,request)}/{f}' 
        if os.path.exists(filename):
            t = os.path.getmtime(filename)
            watchList.update({ f:t })

    return watchList

def checkFileMods(w):
    mod = []
    for f in watchFiles:
        filename = f"{w['path']}/{f}"
        if os.path.exists(filename): # could assume exists if it's in the dict
            t = os.path.getmtime(filename)
            if t > w[f]:
                mod.append(f)
                w[f] = t

    return mod

@app.websocket('/stream/<which:str>/<glider:int>')
@authorized()
async def streamHandler(request: sanic.Request, ws: sanic.Websocket, which:str, glider:int):
    global urlMessages

    filename = f'{gliderPath(glider,request)}/comm.log'
    if not os.path.exists(filename):
        await ws.send('no')
        return

    if runMode == 'pilot':
        commFile = open(filename, 'rb')
        if which == 'init':
            commFile.seek(-10000, 2)
            data = commFile.read().decode('utf-8', errors='ignore')
            if data:
                await ws.send(data)
        else:
            commFile.seek(0, 2)
       
    watchList = buildWatchList(request, glider) 
    prev_t = 0
    while True:
        modFiles = checkFileMods(watchList)
        if 'comm.log' in modFiles and runMode == 'pilot':
            data = commFile.read().decode('utf-8', errors='ignore')
            if data:
                await ws.send(data)
        elif 'cmdfile' in modFiles and runMode == 'pilot':
            filename = f'{gliderPath(glider,request)}/cmdfile'
            with open(filename, 'rb') as file:
                data = "CMDFILE=" + file.read().decode('utf-8', errors='ignore')
                await ws.send(data)
        elif 'cmdfile' in modFiles:
            filename = f'{gliderPath(glider,request)}/cmdfile'
            directive = summary.getCmdfileDirective(filename)
            await ws.send(f"CMDFILE={directive}")
        else:
            lock.acquire()
            msg = list(filter(lambda m: m['glider'] == glider and m['time'] > prev_t, urlMessages))
            lock.release()
            prev_t = time.time()
            for m in msg:
                await ws.send(f"NEW={glider},{m['dive']},{m['content']}")

        await asyncio.sleep(2)

# not protected by decorator - buildAuthTable only returns authorized missions
@app.websocket('/watch/<mask:str>')
# @authorized(protections=['pilot'])
async def watchHandler(request: sanic.Request, ws: sanic.Websocket, mask: str):
    global urlMessages

    opTable = buildAuthTable(request, mask)
    prev_t = 0 

    while True:
        for o in opTable:
            lock.acquire()
            msg = list(filter(lambda m: m['glider'] == o['glider'] and m['time'] > prev_t, urlMessages))
            lock.release()
            prev_t = time.time()
            for m in msg:
                await ws.send(f"NEW={o['glider']},{m['content']}")
                
            cmdfile = f"sg{o['glider']:03d}/cmdfile"
            t = os.path.getmtime(cmdfile)
            if o['cmdfile'] != None and t > o['cmdfile']:
                directive = summary.getCmdfileDirective(cmdfile)
                print(f"{o['glider']} cmdfile")
                await ws.send(f"NEW={o['glider']},cmdfile,{directive}")
                o['cmdfile'] = t

        await asyncio.sleep(2) 
#
#  other stuff (non-Sanic)
#

def buildMissionTable(app):

    missionTable = []
    with open(app.config.MISSIONS_FILE, "r") as file:
        for line in file:
            if line[0] == '#':
                continue

            pieces = line.split(' ')
            parts = pieces[0].split('/')
            if len(parts) == 1:
                mission = None
            else:
                mission = parts[1].strip()
 
            if len(pieces) == 2:
                user = pieces[1].strip()
            else:
                user = None
    
            glider = int(parts[0][2:])
            missionTable.append({ "glider": glider, "mission": mission, "auth": user})

    print(missionTable)
    return missionTable
 
def buildAuthTable(request, mask):
    if len(request.app.ctx.missionTable) == 0:
        request.app.ctx.missionTable = buildMissionTable(request.app)
        print("built table")

    opTable = []
    for m in request.app.ctx.missionTable:
        if checkGliderMission(request, m['glider'], m['mission']) == False:
            continue

        cmdfile = f"sg{m['glider']:03d}/cmdfile"
        if not os.path.exists(cmdfile):
            continue

        if m['mission'] == None:
            opTable.append({"mission": '', "glider": m['glider'], "cmdfile": os.path.getmtime(cmdfile)})
        else: 
            opTable.append({"mission": m['mission'], "glider": m['glider'], "cmdfile": None})

    return opTable

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
    os.chdir(app.config.ROOTDIR)

    if len(sys.argv) == 2:
        port = int(sys.argv[1])
    else:
        port = 20001

    if "vis.py" in sys.argv[0]:
        runMode = 'pilot'
    else:
        runMode = 'public'

    app.ctx.missionTable = buildMissionTable(app)

    if runMode == 'public':
        ssl = {
            "cert": "/etc/letsencrypt/live/www.seaglider.pub/fullchain.pem",
            "key": "/etc/letsencrypt/live/www.seaglider.pub/privkey.pem",
            # "password": "for encrypted privkey file",   # Optional
        }
        app.run(host="0.0.0.0", port=443, ssl=ssl, access_log=True, debug=False)
    else:
        app.run(host='0.0.0.0', port=port, access_log=True, debug=True)

