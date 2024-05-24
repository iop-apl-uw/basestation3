#!/usr/bin/env python3.10
## Copyright (c) 2023, 2024  University of Washington.
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


from orjson import dumps,loads
import time
import os
import os.path
from parse import parse
import sys
from zipfile import ZipFile
from io import BytesIO
from anyio import Path
import websockets
import aiosqlite
import aiofiles
import asyncio
import aiohttp
import sanic
import sanic_gzip
import sanic_ext
from functools import wraps,partial
import jwt
from passlib.hash import sha256_crypt
from types import SimpleNamespace
import hashlib
import hmac
import yaml
import LogHTML
import summary
import multiprocessing
import getopt
import base64
import re
import zmq
import zmq.asyncio
# import urllib.parse 
import BaseOpts
import Utils
import secrets
import ExtractTimeseries
import socket
import rafos
from sanic.worker.manager import WorkerManager
import RegressVBD
import Magcal
import BaseCtrlFiles

#from contextlib import asynccontextmanager
#
#@asynccontextmanager
#async def aclosing(thing):
#    try:
#        yield thing
#    finally:
#        try:
#            await thing.close()
#            Utils.logDB("CLOSED")
#        except ValueError:
#            pass
#

async def checkClose(conn):
    try:
        await conn.close()
        Utils.logDB("CLOSED")
    except ValueError:
        pass

PERM_INVALID = -1
PERM_REJECT = 0
PERM_VIEW   = 1
PERM_PILOT  = 2

MODE_PUBLIC  = 0
MODE_PILOT   = 1
MODE_PRIVATE = 2

AUTH_ENDPOINT = 1
AUTH_MISSION  = 2 

runModes = { 'public': MODE_PUBLIC, 'pilot': MODE_PILOT, 'private': MODE_PRIVATE }
modeNames = ['public', 'pilot', 'private']

protectableRoutes = [
                        'plot',     # dive plot webp/div file
                        'map',      # leafly map page
                        'kml',      # glider mission KML
                        'data',     # unused - data download?
                        'proxy',    # mini proxy server (for map pages)
                        'plots',    # get list of plots for a dive
                        'log',      # get log summary 
                        'file',     # get log, eng, cap file
                        'baselog',  # get baselog_yymmddhhmmss file
                        'alerts',   # get alerts
                        'deltas',   # get changes (parameters and files) between dives
                        'changes',  # get parameter changes
                        'summary',  # get mission summary for a glider
                        'status',   # get basic mission staus (current dive) and eng plot list
                        'control',  # get a control file (cmdfile, etc.)
                        'db',       # get data for glider mission table
                        'dbvars',   # get list of per dive mission variables
                        'pro',      # get profiles
                        'provars',  # get list of profile variables
                        'time',     # get dive time series
                        'timevars', # get list of dive time series variables
                        'query',    # get select per dive data for interactive plots and tables
                        'selftest', # get latest selftest
                        'save',     # save control file
                        'stream',   # web socket stream for glider app page in pilot mode
                        'watch',    # web socket stream for live updates of mission and index pages
                        'chat',     # post a message to chat
                    ]

    # unprotectable: /auth, /, /GLIDERNUM, /missions
    # but /GLIDERNUM could probably be protected if we wanted to?
    # credentials at the dash level via the Credentials link?

compress = sanic_gzip.Compress()

# making this a dict makes a set intersection simple when
# we use it in filterMission
publicMissionFields = {"glider", "mission", "status",
                       "started", "ended", "planned",
                       "orgname", "orglink", "contact", "email",
                       "project", "link", "comment", "reason"} 

# which modes need full comm.log stream vs just change notices

def getTokenUser(request):
    if request.app.config.SINGLE_MISSION:
        return (request.app.config.USER, False)

    if not 'token' in request.cookies:
        return (False, False)

    try:
         token = jwt.decode(request.cookies.get("token"), request.app.config.SECRET, algorithms=["HS256"])
    except jwt.exceptions.InvalidTokenError:
        return (False, False)

    if 'user' in token and 'groups' in token:
        return (token['user'], token['groups'])

    return (False, False)

# checks whether the auth token authorizes a user or group in users, groups
def checkToken(request, users, groups, pilots, pilotgroups):
    if not 'token' in request.cookies:
        return PERM_REJECT

    (tokenUser, tokenGroups) = getTokenUser(request)
    if not tokenUser:
        return PERM_REJECT

    perm = PERM_REJECT

    if users and tokenUser in users:
        sanic.log.logger.info(f"{tokenUser} authorized [{request.path}]")
        perm = PERM_VIEW
    elif groups and tokenGroups and len(set(groups) & set(tokenGroups)) > 0:
        sanic.log.logger.info(f"{tokenUser} authorized based on group [{request.path}]")
        perm = PERM_VIEW

    if pilots and tokenUser in pilots:
        perm = PERM_PILOT
        sanic.log.logger.info(f"{tokenUser} authorized to pilot [{request.path}]")
    elif pilotgroups and tokenGroups and len(set(pilotgroups) & set(tokenGroups)) > 0:
        sanic.log.logger.info(f"{tokenUser} authorized to pilot based on group [{request.path}]")
        perm = PERM_PILOT

    return perm

# checks whether access is authorized for the glider,mission
def checkGliderMission(request, glider, mission, perm=PERM_VIEW):

    # find the entry in the table matching glider+mission (mission could be None)
    m = matchMission(glider, request, mission)
    if m:
        # if there are any user/group/pilot restrictions associated with
        # the matched mission, check the token
        if (m['users'] is not None or \
            m['groups'] is not None or \
            m['pilotusers'] is not None or \
            m['pilotgroups'] is not None): 

            grant = checkToken(request, m['users'], m['groups'], m['pilotusers'], m['pilotgroups'])
            if m['users'] is None and m['groups'] is None and grant < PERM_VIEW:
                grant = PERM_VIEW

            return grant
        else:
            return perm
    
    # no matching mission in table - do not allow access
    sanic.log.logger.info(f'rejecting {glider} {mission} for no mission entry')
    return PERM_INVALID

def checkEndpoint(request, e):

    if e['users'] is not None or e['groups'] is not None:
        (tU, tG) = getTokenUser(request)
        allowAccess = False

        if tU and e['users'] and tU in e['users']:
            allowAccess = True
        elif tG and e['groups'] and len(set(tG) & set(e['groups'])) > 0:
            allowAccess = True

        if not allowAccess:
            sanic.log.logger.info(f"rejecting {request.path}: user auth required")
            return PERM_REJECT # so we respond "auth failed"

    return PERM_VIEW # don't make a distinction view/pilot at this level

def authorized(modes=None, check=3, requirePilot=False): # check=3 both endpoint and mission checks applied
    def decorator(f):
        @wraps(f)
        async def decorated_function(request, *args, **kwargs):
            nonlocal modes
            nonlocal check
            nonlocal requirePilot

            url = request.server_path[1:].split('/')[0]
            if check & AUTH_ENDPOINT:
                if url in request.app.ctx.endpoints:
                    e = request.app.ctx.endpoints[url]
                    status = checkEndpoint(request, e)
                    if status == PERM_INVALID:
                        return sanic.response.text("Page not found: {}".format(request.path), status=404)
                    elif status == PERM_REJECT:
                        return sanic.response.text("authorization failed")
                    else:
                        if 'modes' in e and e['modes'] is not None:
                            modes = e['modes']
                        if 'requirepilot' in e and e['requirepilot'] is not None:
                            requirePilot = e['requirepilot']

            runningMode = modeNames[request.app.config.RUNMODE]

            if check & AUTH_MISSION:
                defaultPerm = PERM_VIEW

                # on an open pilot server (typically a non-public server running 443) 
                # we require positive authentication as a pilot against mission specified 
                # list of allowed pilots (and pilotgroups). Access to missions without 
                # pilots: and/or pilotgroups: specs will be denied for all. 
                glider = kwargs['glider'] if 'glider' in kwargs else None
                mission = request.args['mission'][0] if 'mission' in request.args else None

                m = next(filter(lambda d: d['glider'] == glider and d['mission'] == mission, request.app.ctx.missionTable), None)
                if m is not None and 'endpoints' in m and m['endpoints'] is not None and url in m['endpoints']:
                    e = m['endpoints'][url]
                    status = checkEndpoint(request, e)
                    if status == PERM_INVALID:
                        return sanic.response.text("Page not found: {}".format(request.path), status=404)
                    elif status == PERM_REJECT:
                        return sanic.response.text("authorization failed")
                    else:
                        if 'modes' in e and e['modes'] is not None:
                            modes = e['modes']
                        if 'requirepilot' in e and e['requirepilot'] is not None:
                            requirePilot = e['requirepilot']
                    
                # modes now has final possible value - so check for pilot restricted API in public run mode
                if modes is not None and runningMode not in modes:
                    sanic.log.logger.info(f"rejecting {url}: mode not allowed")
                    return sanic.response.text("Page not found: {}".format(request.path), status=404)
                    
                # if we're running a private instance of a pilot server then we only require authentication
                # as a pilot if the pilots/pilotgroups spec is given (similar to how users always work)
                # so our default (no spec) is to grant pilot access
                if requirePilot and request.app.config.RUNMODE == MODE_PRIVATE:
                    defaultPerm = PERM_PILOT 
                
                # this will always fail and return not authorized if glider is None
                status = checkGliderMission(request, glider, mission, perm=defaultPerm)
                if status <= PERM_REJECT or (requirePilot and status < PERM_PILOT):
                    sanic.log.logger.info(f"{url} authorization failed {status}, {requirePilot}")
                    if status == PERM_INVALID:
                        return sanic.response.text("not found")
                    else: 
                        return sanic.response.text("authorization failed")

            elif modes is not None and runningMode not in modes:
                # do the public / pilot mode check for AUTH_ENDPOINT only mode
                sanic.log.logger.info(f"rejecting {url}: mode not allowed")
                return sanic.response.text("Page not found: {}".format(request.path), status=404)

            # the user is authorized.
            # run the handler method and return the response
            response = await f(request, *args, **kwargs)
            return response
        return decorated_function
    return decorator


def rowToDict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

def missionFromRequest(request):
    if request and 'mission' in request.args and len(request.args['mission']) > 0 and request.args['mission'][0] != 'current':
        return request.args['mission'][0]

    return None

def activeMission(gld, request):
    x = next(filter(lambda d: d['glider'] == gld and d['status'] == 'active',  request.app.ctx.missionTable), None)
    return x
 
def matchMission(gld, request, mission=None):
    if mission == None and \
       request and \
       'mission' in request.args and \
       len(request.args['mission'][0]) > 0:

        mission = request.args['mission'][0]

    x = next(filter(lambda d: d['glider'] == int(gld) and d['mission'] == mission,  request.app.ctx.missionTable), None)
    if x:
        return x

    if mission:
        return None

    x = next(filter(lambda d: d['glider'] == int(gld) and d['default'] == True, request.app.ctx.missionTable), None)
    return x 

def filterMission(gld, request, mission=None):
    m = matchMission(gld, request, mission)    
    return { k: m[k] for k in m.keys() & publicMissionFields } if m else None

def gliderPath(glider, request, mission=None):
    m = matchMission(glider, request, mission)
    if m and 'path' in m and m['path']:
        return m['path']
    else:
        return f'sg{glider:03d}'


def baseOpts(instrument_id, mission_dir, module_name):
    cnf_file = os.path.join(mission_dir, f'sg{instrument_id:03d}.conf')
 
    base_opts = BaseOpts.BaseOptions(
        "",
        alt_cmdline = f"-c {cnf_file} -m {mission_dir}",
        calling_module=module_name,
    )

    return base_opts

async def getLatestFile(glider, request, which, dive=None):
    p = Path(gliderPath(glider,request))
    latest = -1
    call = -1;
    filename = None
    if dive:
        globstr = f'{which}.{dive}*'
    else:
        globstr = f'{which}.*'

    async for fpath in p.glob(globstr):
        try:
            j = parse('%s.{:d}.{:d}' % which, fpath.name)
            if dive:
                if j and hasattr(j, 'fixed') and len(j.fixed) == 2 and j.fixed[0] == dive and j.fixed[1] > call:
                    latest = j.fixed[0]
                    call = j.fixed[1]
                else:
                    j = parse('%s.{:d}' % which, fpath.name)
                    if j and hasattr(j, 'fixed') and len(j.fixed) == 1 and j.fixed[0] == dive and call == -1:
                        latest = j.fixed[0]
            else:
                if j and hasattr(j, 'fixed') and len(j.fixed) == 2:
                    if  j.fixed[0] > latest:
                        latest = j.fixed[0]
                        call = j.fixed[1]
                    elif j.fixed[0] == latest and j.fixed[1] > call:
                        call = j.fixed[1]
                else:
                    j = parse('%s.{:d}' % which, fpath.name)
                    if j and hasattr(j, 'fixed') and len(j.fixed) == 1 and j.fixed[0] > latest:
                        latest = j.fixed[0]
        except Exception as e:
            sanic.log.logger.info(f"getLatestFile: {e}")
            continue

    if latest > -1:
        if call > -1:
            filename = f'{gliderPath(glider,request)}/{which}.{latest}.{call}'
        else:
            filename = f'{gliderPath(glider,request)}/{which}.{latest}'

    return (filename, latest, call)

#
# GET handlers - most of the API
#

def attachHandlers(app: sanic.Sanic):

    # consider whether any of these need to be protectable?? parms??
    app.static('/favicon.ico', f'{sys.path[0]}/html/favicon.ico', name='favicon.ico')
    app.static('/parms', f'{sys.path[0]}/html/Parameter_Reference_Manual.html', name='parms')
    app.static('/alerthelp', f'{sys.path[0]}/html/AlertsReferenceManual.html', name='alerts')
    app.static('/ballast', f'{sys.path[0]}/html/ballast.html', name='ballast')
    app.static('/script', f'{sys.path[0]}/scripts', name='script')
    app.static('/help', f'{sys.path[0]}/html/help.html', name='help')
    app.static('/script/images', f'{sys.path[0]}/scripts/images', name='script_images')
    app.static('/manifest.json', f'{sys.path[0]}/scripts/manifest.json', name='manifest')

    @app.exception(sanic.exceptions.NotFound)
    def pageNotFound(request, exception):
        return sanic.response.text("Page not found: {}".format(request.path), status=404)

    @app.post('/auth')
    # description: user authorization 
    # payload: (JSON) username, password
    # returns: none on success (sets cookie with authorization token)
    async def authHandler(request):
        username = request.json.get("username", None).lower()
        password = request.json.get("password", None)

        for user,prop in request.app.ctx.userTable.items():
            if user.lower() == username and sha256_crypt.verify(password, prop['password']):
                token = jwt.encode({ "user": user, "groups": prop['groups']}, request.app.config.SECRET)
                response = sanic.response.text("authorization ok")
                response.cookies["token"] = token
                response.cookies["token"]["max-age"] = 86400
                response.cookies["token"]["samesite"] = "Strict"
                response.cookies["token"]["httponly"] = True
                return response

        return sanic.response.text('authorization failed') 

    @app.route('/user')
    # description: checks whether current session user is valid
    # returns: YES is user is valid
    @authorized(modes=['pilot','private'], check=AUTH_ENDPOINT)
    async def userHandler(request):
        (tU, tG) = getTokenUser(request)
        return sanic.response.text('YES' if tU else 'NO')
 
    @app.route('/plot/<fmt:str>/<which:str>/<glider:int>/<dive:int>/<image:str>')
    # description: get a plot image
    # args: fmt=png|webp|div, which=dv|eng|sg
    # returns: image data (webp, png or plotly div)
    # parameters: mission
    @authorized()
    async def plotHandler(request, fmt:str, which: str, glider: int, dive: int, image: str):
        if fmt not in ['png', 'webp', 'div']:
            return sanic.response.text('not found', status=404)

        direc = int(request.args['dir'][0]) if 'dir' in request.args else 0

        if which == 'dv':
            filename = f'{gliderPath(glider,request)}/plots/dv{dive:04d}_{image}.{fmt}'
            if direc != 0 and not await aiofiles.os.path.exists(filename):
                dive = await findNextPlot(gliderPath(glider, request), f'{image}.{fmt}', dive, direc) 
                if dive == -1:
                    return sanic.response.text('not found', status=404)
               
                return sanic.response.text(f'not found, next={dive}')

        elif which == 'eng':
            filename = f'{gliderPath(glider,request)}/plots/eng_{image}.{fmt}'
        elif which == 'section':
            filename = f'{gliderPath(glider,request)}/plots/sg_{image}.{fmt}'
        else:
            return sanic.response.text('not found', status=404)


        filenames = [ filename ]
        if 'fallback' in request.args:
            filenames.append(f'{gliderPath(glider,request)}/plots/dv{dive:04d}_diveplot.{fmt}')
            filenames.append(f'{gliderPath(glider,request)}/plots/dv{dive:04d}_reduced_ctd.{fmt}')
            filenames.append(f'{gliderPath(glider,request)}/plots/eng_mission_map.{fmt}')

        for filename in filenames:
            if await aiofiles.os.path.exists(filename):
                if 'wrap' in request.args and request.args['wrap'][0] == 'page':
                    mission = missionFromRequest(request)
                    mission = f"?mission={mission}" if mission else ''
                    wrap = '?wrap=page' if mission == '' else '&wrap=page'

                    filename = f'{sys.path[0]}/html/wrap.html'
                    return await sanic.response.file(filename, mime_type='text/html')
                else:
                    if fmt == 'div':
                        async with aiofiles.open(filename, 'rb') as f:
                            cont = await f.read()
                       
                        return sanic.response.raw(cont, headers={'Content-type': 'text/html', 'Content-Encoding': 'br'})
                    else:
                        return await sanic.response.file(filename, mime_type=f"image/{fmt}")

        return sanic.response.text('not found', status=404)
           
    # we don't protect this so they get a blank page with a login option even
    # if not authorized
    @app.route('/<glider:int>')
    # description: main page for glider
    # parameters: mission, plot (starting plot), dive (starting dive), order (plot ribbon order), plot tool values: x,y,z,first,last,step,top,bottom,bin,wholemission|divetimeseries,dives|climbs|both|combine, op (contour,profiles,plot,table,csv)
    # returns: HTML page
    @app.ext.template("vis.html")
    async def mainHandler(request, glider:int):
        runMode = request.app.config.RUNMODE
        if runMode == MODE_PRIVATE:
            runMode = MODE_PILOT

        return {"runMode": modeNames[runMode], "noSave": request.app.config.NO_SAVE, "noChat": request.app.config.NO_CHAT}

    @app.route('/dash')
    # description: dashboard (engineering diagnostic) view of index (all missions) page
    # parameters: plot (which plot to include in tiles, default=diveplot)
    # returns: HTML page
    @authorized(check=AUTH_ENDPOINT)
    @app.ext.template("index.html")
    async def dashHandler(request):
        return {"runMode": "pilot"}

    @app.route('/')
    # description: "public" index (all missions) page
    # parameters: plot (which plot to include in tiles, default=map)
    # returns: HTML page
    @app.ext.template("index.html")
    async def indexHandler(request):
        return {"runMode": "public"}

    @app.route('/map/<glider:int>')
    # description: map tool
    # parameters: mission, tail (number of dives back to show in glider track), also (additional gliders to plot), sa (URL for SA to load)
    # returns: HTML page
    @authorized()
    @app.ext.template("map.html")
    async def mapHandler(request, glider:int):
        # filename = f'{sys.path[0]}/html/map.html'
        # return await sanic.response.file(filename, mime_type='text/html')
        return { "weathermapAppID": request.app.config.WEATHERMAP_APPID }

    @app.route('/map')
    @app.ext.template("map.html")
    async def mapBareHandler(request):
        return { "weathermapAppID": request.app.config.WEATHERMAP_APPID }

    @app.route('/mapdata')
    async def mapdataBareHandler(request):
        message = {}

        if len(request.app.ctx.routes):
            message['routes'] = request.app.ctx.routes;

        a_dicts = []
        for a in request.app.ctx.assets.keys():
            d = request.app.ctx.assets[a]
            d.update( { 'asset': a } )
            a_dicts.append(d)

        if len(a_dicts):
            message['assets'] = a_dicts

        return sanic.response.json(message)


    @app.route('/mapdata/<glider:int>')
    # description: get map configation (also, sa, kml from missions.yml)
    # parameters: mission
    # returns: JSON dict with configuration variables
    @authorized()
    async def mapdataHandler(request, glider:int):
        mission = matchMission(glider, request) 
        print(mission)
        if mission:
            message = {}
            for k in ['sa', 'kml', 'also']:
                if k in mission:
                    message[k] = mission[k]

            if 'also' in message and message['also'] is not None:
                for a in message['also']:
                    if not 'mission' in a:
                        a.update( { 'mission': mission['mission'] } )
                    if 'asset' in a:
                        if a['asset'] in request.app.ctx.assets.keys():
                            # don't copy the whole dict because maybe we have local
                            # overrides in this per mission version
                            for k in request.app.ctx.assets[a['asset']].keys():
                                if not k in a.keys():
                                    a.update({ k: request.app.ctx.assets[a['asset']][k] })
                        else:
                            a.pop('asset')     

            if len(request.app.ctx.routes):
                message['routes'] = request.app.ctx.routes;

            #if 'assets' in mission:
            #    a_dicts = []
            #    for a in mission['assets']:
            #        if a in request.app.ctx.assets.keys():       
            #            d = request.app.ctx.assets[a]
            #            d.update( { 'name': a } )
            #            a_dicts.append(d)
            #
            #    if len(a_dicts):
            #        message['assets'] = a_dicts

            return sanic.response.json(message)

        else:
            return sanic.response.json({'error': 'not found'})

    # this requires that a reverse proxy provides an x-request-uri header
    # Apache: RequestHeader add "X-REQUEST-URI" expr=%{REQUEST_SCHEME}://%{HTTP_HOST}%{REQUEST_URI}?%{QUERY_STRING}
    # nginx: proxy_set_header X-REQUEST-URI "$scheme://$proxy_host$request_uri";
    def getRequestURL(request):
        fwdHost = request.headers.get('x-forwarded-host')
        if not fwdHost:
            return request.url
     
        return request.headers.get('x-request-uri') 
        # f = furl.furl(request.url)
        # f.scheme = 'https'
        # f.host = fwdHost
        # f.port = None
        # return f.tostr()
        
    @app.route('/kml/<glider:int>')
    # description: get glider KML
    # parameters: mission
    # returns: KML
    @authorized()
    async def kmlHandler(request, glider:int):
        if 'network' in request.args:
            
            # link = urllib.parse.quote(getRequestURL(request).replace('network', 'kmz'))
            link = getRequestURL(request).replace('network', 'kmz')
            t =   '<?xml version="1.0" encoding="UTF-8"?>\n'
            t +=  '<kml xmlns="http://earth.google.com/kml/2.2">\n'
            t +=  '<NetworkLink>\n'
            t += f'  <name>SG{glider:03d} Track</name>\n'
            t +=  '  <Url>\n'
            t += f'    <href>{link}</href>\n'
            t +=  '    <refreshMode>onInterval</refreshMode>\n'
            t +=  '    <refreshInterval>120</refreshInterval>\n'
            t +=  '  </Url>\n'
            t +=  '</NetworkLink>\n'
            t +=  '</kml>\n'
            return sanic.response.text(t, content_type='application/vnd.google-earth.kml')
        elif 'kmz' in request.args:
            filename = f'sg{glider:03d}.kmz'
            fullname = f'{gliderPath(glider,request)}/{filename}'
            return await sanic.response.file(fullname, filename=filename, mime_type='application/vnd.google-earth.kmz')
        else:
            filename = f'{gliderPath(glider,request)}/sg{glider:03d}.kmz'
            try:
                async with aiofiles.open(filename, 'rb') as file:
                    zip = ZipFile(BytesIO(await file.read()))
                    kml = zip.open(f'sg{glider}.kml', 'r').read()
                    return sanic.response.raw(kml)
            except:
                return sanic.response.text('no file')

    # Not currently linked on a public facing page, but available.
    # Protect at the mission level (which protects that mission at 
    # all endpoints) or at the endpoint level with something like
    # users: [download] or groups: [download] and build
    # users.yml appropriately
    #
    # curl -c cookies.txt -X POST http://myhost/auth \
    # -H "Content-type: application/json" \
    # -d '{"username": "joeuser", "password": "abc123"}'
    #
    # curl -b cookies.txt http://myhost/data/nc/237/12 \
    # --output p2370012.nc
    #
    @app.route('/data/<which:str>/<glider:int>/<dive:int>')
    # description: download raw data
    # parameters: mission
    # returns: netCDF file
    @authorized()
    async def dataHandler(request, which:str, glider:int, dive:int):
        path = gliderPath(glider,request)

        if which == 'nc' or which == 'ncfb' or which == 'ncf' or which == 'ncdf':
            filename = f'p{glider:03d}{dive:04d}.{which}'
        else:
            sanic.log.logger.info(f'invalid filetype requested {which}')
            return sanic.response.text('not found', status=404)

        fullname = f"{path}/{filename}"           
        if await aiofiles.os.path.exists(fullname):
            return await sanic.response.file(fullname, filename=filename, mime_type='application/x-netcdf4')
        else:
            sanic.log.logger.info(f'{fullname} not found')
            return sanic.response.text('not found', status=404)

    @app.post('/post')
    # description: post version of proxy request handler for map tool
    # returns: contents from requested URL
    @authorized(check=AUTH_ENDPOINT)
    async def postHandler(request):
        allowed = [
                   'https://realtime.sikuliaq.alaska.edu/realtime/map',
                  ]

        url = request.json.get('url', None)
        found = False
        if url.startswith('http:/') and not url.startswith('http://'):
            url = re.sub('http:/', 'http://', url)
        elif url.startswith('https:/') and not url.startswith('https://'):
            url = re.sub('https:/', 'https://', url)
 
        for x in allowed:
            if url.startswith(x):
                found = True
                break

        if found == False:
            return sanic.response.text(f"Page not found: {request.path}", status=404)
              
        user     = request.json.get('user', None) 
        password = request.json.get('password', None)
        ssl      = request.json.get('ssl', True)

        async with aiohttp.ClientSession() as session:
            if user is not None and password is not None:
                async with session.get(url, auth=aiohttp.BasicAuth(user, password), ssl=ssl) as response:
                    if response.status == 200:
                        body = await response.read()
                        return sanic.response.raw(body)
            else:
                async with session.get(url, ssl=ssl) as response:
                    if response.status == 200:
                        body = await response.read()
                        return sanic.response.raw(body)

    # This is not a great idea to leave this open as a public proxy server,
    # but we need it for all layers to work with public maps at the moment.
    # Need to evaluate what we lose if we turn proxy off or find another solution.
    # Or limit the dictionary of what urls can be proxied ...
    # NOAA forecast, NIC ice edges, iop SA list, opentopo GEBCO bathy
    @app.route('/proxy/<url:path>')
    # description: proxy requests for map tool
    # returns: contents from requested URL
    @authorized(check=AUTH_ENDPOINT)
    async def proxyHandler(request, url):
        allowed = ['https://api.opentopodata.org/v1/gebco2020',
                   'https://marine.weather.gov/MapClick.php',
                   'https://iop.apl.washington.edu/', 
                   'https://usicecenter.gov/File/DownloadCurrent',
                   'https://raw.githubusercontent.com/rwev/leaflet-reticle/master/src',
                  ]

        found = False
        if url.startswith('http:/') and not url.startswith('http://'):
            url = re.sub('http:/', 'http://', url)
        elif url.startswith('https:/') and not url.startswith('https://'):
            url = re.sub('https:/', 'https://', url)
 
        for x in allowed:
            if url.startswith(x):
                found = True
                break

        if found == False:
            return sanic.response.text(f"Page not found: {request.path}", status=404)
              
        if request.args and len(request.args) > 0:
            url = url + '?' + request.query_string

        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    body = await response.read()
                    return sanic.response.raw(body)
        
    @app.route('/proxykmz/<url:path>')
    # description: proxy and unzip network KMZ sources
    # returns: KML from KMZ downloaded from requested URL
    @authorized(check=AUTH_ENDPOINT)
    async def proxykmzHandler(request, url):
        allowed = [
                   'https://usicecenter.gov/File/DownloadCurrent',
                   'https://iop.apl.washington.edu/seaglider_ssh',
                  ]

        found = False
        if url.startswith('http:/') and not url.startswith('http://'):
            url = re.sub('http:/', 'http://', url)
        elif url.startswith('https:/') and not url.startswith('https://'):
            url = re.sub('https:/', 'https://', url)
 
        for x in allowed:
            if url.startswith(x):
                found = True
                break

        if found == False:
            return sanic.response.text(f"Page not found: {request.path}", status=404)

        kmz = None
              
        if request.args and len(request.args) > 0:
            url = url + '?' + request.query_string
        async with aiohttp.ClientSession() as session:
            async with session.get(url) as response:
                if response.status == 200:
                    kmz = await response.read()

        if kmz == None:
            return sanic.response.text(f"Page not found: {request.path}", status=404)

        nm = None
        try:
            zip = ZipFile(BytesIO(kmz))
            print(zip.namelist())
            for x in zip.namelist():
                if '.kml' in x:
                    nm = x
                    break
        except Exception as e:
            print(f'exception {e}')
            pass

        if nm == None:
            return sanic.response.text('not found')
 
        kml = zip.open(nm).read()
        return sanic.response.raw(kml)

    @app.route('/plots/<glider:int>/<dive:int>')
    # description: list of plots available for dive
    # parameters: mission
    # returns: JSON dict of available plots, sorted by type
    @authorized()
    async def plotsHandler(request, glider:int, dive:int):
        (dvplots, plotlyplots) = await buildDivePlotList(gliderPath(glider,request), dive)
        message = {}
        message['glider']      = f'SG{glider:03d}'
        message['dive']        = dive
        message['dvplots']     = dvplots
        message['plotlyplots'] = plotlyplots
        # message['engplots']    = engplots
        
        return sanic.response.json(message)

    @app.route('/log/<glider:int>/<dive:int>')
    # description: formatted glider log 
    # parameters: mission
    # returns: summary version of log file in HTML format
    @authorized()
    async def logHandler(request, glider:int, dive:int):
        filename = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.log'
        s = await LogHTML.captureTables(filename)
        return sanic.response.html(s)

    def purgeSensitive(text):
        out = ''
        prior = False
        for line in text.splitlines():
            if 'password = ' in line: 
                line = re.sub(r"password = .*?[^<]*", "password = ----", line)
                sanic.log.logger.info("purging known password")
            elif 'Current password is' in line:
                line = re.sub(r"Current password is .*?[^<]*", "Current password is ----", line)
                sanic.log.logger.info("purging known password")
            elif 'Changing password to' in line:
                line = re.sub(r"Changing password to .*?[^<]*", "Changing password to ----", line)
                sanic.log.logger.info("purging known password change")
            elif 'sent [' in line and prior:
                line = re.sub(r"sent \[.*\]", "sent [----]", line)
                prior = False
                sanic.log.logger.info("purging sent password debugging")
            elif 'sending password [' in line:
                line = re.sub(r"sending password \[.*\]", "sending password [----]", line)
                sanic.log.logger.info("purging known password debugging")
                prior = True
            elif 'assword' in line \
                 and not 'Password:]' in line \
                 and not 'no password: prompt' in line \
                 and not 'no shell prompt' in line:
                line = '---- deleted ----'
                sanic.log.logger.info("purging unknown password")
            else:
                prior = False

            out = out + line + '\n'

        return out


    @app.route('/file/<ext:str>/<glider:int>/<dive:int>')
    # description: processed glider basestation files
    # args: ext=eng|log|cap
    # parameters: mission
    # returns: raw eng, log, or cap file
    @authorized()
    async def logengcapFileHandler(request, ext:str, glider: int, dive: int):
        if ext not in ['log', 'eng', 'cap']:
            return sanic.response.text('not found', status=404)
            
        filename = f'{gliderPath(glider,request)}/p{glider:03d}{dive:04d}.{ext}'
        if await aiofiles.os.path.exists(filename):
            if ext in ['log', 'eng']:
                return await sanic.response.file(filename, mime_type='text/plain')
            else:
                async with aiofiles.open(filename, 'rb') as file:
                    out = purgeSensitive((await file.read()).decode('utf-8', errors="ignore"))
                    return sanic.response.text(out)
        else:
            if ext == 'cap':
                return sanic.response.text('none')
            else:
                return sanic.response.text('not found', status=404)
           
    @app.route('/baselog/<glider:int>/<timestamp:str>')
    # description: basestation baselog file
    # parameters: mission
    # returns: raw baselog file from basestation (txt)
    @authorized()
    async def baselogHandler(request, glider: int, timestamp: str):
        filename = f'{gliderPath(glider,request)}/baselog_{timestamp}'
        if await aiofiles.os.path.exists(filename):
            baseout = '<html>\n'
            trace = False
            async with aiofiles.open(filename, 'r') as file:
                async for line in file:
                    if 'ERROR' in line:
                        line = re.sub('ERROR', '<b>ERROR</b>', line)
                    elif 'WARNING' in line:
                        line = re.sub('WARNING', '<span style="color:blue;">WARNING</span>', line)
                    elif line.startswith('Traceback'):
                        baseout = baseout + '<b>\n'
                        trace = True
                    elif line in ['\n', '\r\n'] and trace == True:
                        baseout = baseout + '</b>\n'
                        trace = False 

                    baseout = baseout + line.strip() + '<br>'
    
            baseout = baseout + '</html>\n'
            # return await sanic.response.file(filename, mime_type='text/plain')
            return sanic.response.html(baseout)
        else:
            return sanic.response.text('not found')
    
    @app.route('/alerts/<glider:int>/<dive:int>')
    # description: basestation alerts file
    # parameters: mission
    # returns: alerts file (with re-written links) from basestation (HTML format)
    @authorized()
    async def alertsHandler(request, glider: int, dive: int):
        mission = missionFromRequest(request)
        if mission:
            mission = f'?mission={mission}'
        else:
            mission = ''

        alerts = 'none'

        (filename, dive, call) = await getLatestFile(glider, request, 'alert_message.html', dive=dive)
        if filename and await aiofiles.os.path.exists(filename):
            async with aiofiles.open(filename, 'r') as file:
                alerts = await file.read() 

            t = re.search(r"BASELOG=\d+", alerts)
            if t:
                timestamp = t[0].split('=')[1]
                alerts = re.sub('BASELOGREF', f'baselog/{glider}/{timestamp}{mission}', alerts)
           
            return sanic.response.text(alerts)

        return sanic.response.text('not found')
     
    @app.route('/deltas/<glider:int>/<dive:int>')
    # description: list of changes between dives
    # parameters: mission
    # returns: JSON formatted dict of control file changes
    @authorized()
    async def deltasHandler(request, glider: int, dive: int):
        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        message = { 'dive': dive, 'parm': [], 'file': [] }
        if await Path(dbfile).exists():
            async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                Utils.logDB(f'deltas open {glider}')
                conn.row_factory = rowToDict # not async but called from async fetchall
                cur = await conn.cursor()
                try:
                    await cur.execute(f"SELECT * FROM changes WHERE dive={dive} ORDER BY parm ASC;")
                except aiosqlite.OperationalError as e:
                    Utils.logDB(f'deltas close (exception) {glider}')
                    return sanic.response.json({'error': f'db error {e}'})

                message['parm'] = await cur.fetchall()

                try:
                    await cur.execute(f"SELECT * FROM files WHERE dive={dive} ORDER BY file ASC;")
                except aiosqlite.OperationalError as e:
                    Utils.logDB(f'deltas close (exception 2) {glider}')
                    return sanic.response.json({'error': f'db error {e}'})

                message['file'] = await cur.fetchall()
                Utils.logDB(f'deltas close {glider}')

            await checkClose(conn)

        return sanic.response.json(message)

    @app.route('/missions/<mask:str>')
    # description: list of missions
    # args: mask is unused
    # returns: JSON formatted dict of missions and mission config
    async def missionsHandler(request, mask:int):
        table = await buildAuthTable(request, "")
        msg = { "missions": table, "organization": request.app.ctx.organization }
        return sanic.response.json(msg)
     
    @app.route('/summary/<glider:int>')
    # description: summary status of glider
    # parameters: mission
    # returns: JSON formatted dict of glider engineering status variables
    @authorized()
    async def summaryHandler(request, glider:int):
        msg = await summary.collectSummary(glider, gliderPath(glider,request))
        if not 'humidity' in msg:
            call = await getLatestCall(request, glider)
            if call is not None and len(call) >= 1:
                try:
                    msg['lat']    = call[0]['lat']
                    msg['lon']    = call[0]['lon']
                    msg['dive']   = call[0]['dive']
                    msg['calls']  = call[0]['call']
                    msg['end']    = call[0]['connected']
                    msg['volts']  = [ call[0]['volts10'], call[0]['volts24'] ]
                    msg['humidity'] = call[0]['RH']
                    msg['internalPressure'] = call[0]['intP']
                except Exception as e:
                    sanic.log.logger.info(f"summaryHandler: {e} {call[0]}")
                    
        msg['mission'] = filterMission(glider, request)
        return sanic.response.json(msg)

    # this does setup and is generally only called once at page load
    @app.route('/status/<glider:int>')
    # description: glider latest dive number and visualization config (mission.dat variables, mission plots)
    # parameters: mission
    # returns: JSON formatted dict of configuration
    @authorized()
    async def statusHandler(request, glider:int):
        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if await Path(dbfile).exists():
            async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                Utils.logDB(f'status open {glider}')
                cur = await conn.cursor()
                try:
                    await cur.execute("SELECT dive FROM dives ORDER BY dive DESC LIMIT 1")
                except aiosqlite.OperationalError as e:
                    Utils.logDB(f'status close (exception) {glider}')
                    return sanic.response.json({'error': f'no table {e}'})

                try:
                    maxdv = (await cur.fetchone())[0]
                except:
                    maxdv = 0

                Utils.logDB(f'status close {glider}')
            await checkClose(conn)
            
        else:
            return sanic.response.json({'error': 'file not found'})

        (engplots, sgplots, engplotly, sgplotly) = await buildMissionPlotList(gliderPath(glider, request))

        message = {}
        message['glider'] = f'{glider:03d}'
        message['dive'] = maxdv
        message['engplots'] = engplots
        message['sgplots'] = sgplots
        message['engplotly'] = engplotly
        message['sgplotly'] = sgplotly
        message['organization'] = request.app.ctx.organization
        
        message['mission'] = filterMission(glider, request) 
        return sanic.response.json(message)

    @app.route('/control/<glider:int>/<which:str>')
    # description: glider control files
    # args: which=cmdfile|targets|science|scicon.sch|tcm2mat.cal|pdoscmds.bat|sg_calib_constants.m
    # parameters: mission
    # returns: latest version of glider control file
    @authorized()
    async def controlHandler(request, glider:int, which:str):
        ok = ["cmdfile", "targets", "science", "scicon.sch", "tcm2mat.cal", "pdoscmds.bat", "sg_calib_constants.m"]

        if which not in ok:
            return sanic.response.json({'error': "oops"})

        message = {}

        message['file'] = 'none'
        filename = f'{gliderPath(glider,request)}/{which}'

        if await aiofiles.os.path.exists(filename):
            message['file'] = which
            message['dive'] = -1
            message['call'] = -1
        else:
            (filename, dive, call) = await getLatestFile(glider, request, which)
            if filename:
                message['file'] = which
                message['dive'] = dive
                message['call'] = call


        if message['file'] == "none":
            return sanic.response.json({'error': "none"})

        async with aiofiles.open(filename, 'r') as file:
            message['contents']= await file.read() 

        return sanic.response.json(message)

    @app.route('/rafos/<glider:int>')
    @authorized()
    async def rafosHandler(request, glider:int):
        path = gliderPath(glider, request)
        hits  = await rafos.hitsTable(path)
        out = ExtractTimeseries.dumps(hits) # need custom serializer for the numpy array
        return sanic.response.raw(out, headers={ 'Content-type': 'application/json' })

    @app.route('/magcal/<glider:int>/<dives:str>')
    # description: run magcal over multiple dives
    # parameters: mission, ballast
    # returns: html of plotly results plot
    @authorized()
    async def magcalHandler(request, glider:int, dives:str):
        path = gliderPath(glider, request)

        softiron = True if 'softiron' in request.args else False
        dives = RegressVBD.parseRangeList(dives)

        hard, soft, cover, circ, plt = Magcal.magcal(path, glider, dives, softiron, 'html')

        return sanic.response.html((f'<html>hard0="{hard[0]:.1f} {hard[1]:.1f} {hard[2]:.1f}"<br>'
                                    f'soft0="{soft[0][0]:.3f} {soft[0][1]:.3f} {soft[0][2]:.3f} '
                                    f'{soft[1][0]:.3f} {soft[1][1]:.3f} {soft[1][2]:.3f}'
                                    f'{soft[2][0]:.3f} {soft[2][1]:.3f} {soft[2][2]:.3f}"'
                                    '<p>') + plt) 

    @app.route('/regress/<glider:int>/<dives:str>/<depth1:float>/<depth2:float>/<initBias:float>')
    # description: run VBD regression over multiple dives
    # parameters: mission, ballast
    # returns: html of plotly results plot
    @authorized()
    async def regressHandler(request, glider:int, dives:str,
                             depth1:float, depth2:float, initBias:float):
        path = gliderPath(glider, request)

        ballast = True if 'ballast' in request.args else False
        print(ballast)

        dives = RegressVBD.parseRangeList(dives)

        mass = float(request.args['mass'][0]) if 'mass' in request.args else None
        
        bias, hd, vel, rms, log, plt, figs = RegressVBD.regress(path, glider, dives, [depth1, depth2], initBias, mass, 'html', True)
        if rms[1] == 0:
            return sanic.response.html("did not converge")

        if ballast:
            
            log['thrust'] = request.args['thrust'][0] if 'thrust' in request.args else -250
            log['density'] = request.args['density'][0] if 'density' in request.args else 1.0275
           
            async with aiofiles.open(f'{sys.path[0]}/html/ballast.html', 'r') as file:
                ballastHTML = await file.read()
           
            ballastHTML = ballastHTML + \
                          """
                          <script>
                          $('mass').value = {MASS};
                          $('volmax').value = {implied_volmax:.1f};
                          $('min_counts').value = {VBD_MIN};
                          $('max_counts').value = {VBD_MAX};
                          $('thrust').value = {thrust};
                          $('target_density').value = {density};
                          calculate();
                          </script>
                          """.format(**log)

            plt.insert(0, ballastHTML)

        return sanic.response.html("<br>".join(plt))
    
    @app.route('/db/<glider:int>/<dive:int>')
    # description: query database for common engineering variables
    # args: dive=-1 returns whole mission
    # parameters: mission
    # returns: JSON dict of engineering variables
    @authorized()
    async def dbHandler(request, glider:int, dive:int):
        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if not await aiofiles.os.path.exists(dbfile):
            return sanic.response.text('no db')

        q = "SELECT dive,log_start,log_gps_time,time_seconds_diving,log_D_TGT,log_D_GRID,log__CALLS,log__SM_DEPTHo,log__SM_ANGLEo,log_HUMID,log_TEMP,log_INTERNAL_PRESSURE,depth_avg_curr_east,depth_avg_curr_north,max_depth,pitch_dive,pitch_climb,batt_volts_10V,batt_volts_24V,batt_capacity_24V,batt_capacity_10V,total_flight_time_s,avg_latitude,avg_longitude,target_name,magnetic_variation,mag_heading_to_target,meters_to_target,GPS_north_displacement_m,GPS_east_displacement_m,flight_avg_speed_east,flight_avg_speed_north,dog_efficiency,alerts,criticals,capture,error_count,(SELECT COUNT(dive) FROM changes where changes.dive=dives.dive) as changes, (SELECT COUNT(dive) FROM files where files.dive=dives.dive) as files FROM dives"

        if dive > -1:
            q = q + f" WHERE dive={dive};"
        else:
            q = q + " ORDER BY dive ASC;"

        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            Utils.logDB(f'db open {glider}')
            conn.row_factory = rowToDict # not async but called from async fetchall
            cur = await conn.cursor()
            try:
                await cur.execute(q)
            except aiosqlite.OperationalError as e:
                Utils.logDB(f'db close (exception) {glider}')
                return sanic.response.json({'error': f'no table {e}'})

            data = await cur.fetchall()
            # r = [dict((cur.description[i][0], value) \
            #       for i, value in enumerate(row)) for row in data]

            Utils.logDB(f'db close {glider}')

        await checkClose(conn)

        return sanic.response.json(data)

    @app.route('/changes/<glider:int>/<dive:int>/<which:str>/<sort:str>')
    # description: query database for parameter or control file changes
    # args: dive=-1 returns entire history, which=parms|files, sort=dive|parm|file
    # parameters: mission
    # returns: JSON dict of changes [{(dive,parm,oldval,newval}] or [{dive,file,fullname,contents}]
    async def changesHandler(request, glider:int, dive:int, which:str, sort:str):
        if (which not in ['parms', 'files']) or (sort not in ['dive', 'file', 'parm']):
            return sanic.response.json({'error': 'no db'})
           
        db   = { 'parms': 'changes', 'files': 'files' } 
        col2 = which[0:-1]

        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if not await aiofiles.os.path.exists(dbfile):
            return sanic.response.json({'error': 'no db'})

        q = f"SELECT * FROM {db[which]}"

        if dive > -1:
            q = q + f" WHERE dive={dive} ORDER BY {col2} ASC;"
        elif sort  == 'dive':
            q = q + f" ORDER BY dive,{col2} ASC;"
        else:
            q = q + f" ORDER BY {col2},dive ASC;"

        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            Utils.logDB(f'changes open {glider}')
            conn.row_factory = rowToDict # not async but called from async fetchall
            cur = await conn.cursor()
            try:
                await cur.execute(q)
            except aiosqlite.OperationalError as e:
                Utils.logDB(f'changes close (exception) {glider}')
                return sanic.response.json({'error': f'no table {e}'})

            data = await cur.fetchall()
            Utils.logDB(f'changes close {glider}')

        await checkClose(conn)
        return sanic.response.json(data)


    @app.route('/dbvars/<glider:int>')
    # description: list of per dive database variables
    # parameters: mission
    # returns: JSON list of variable names
    @authorized()
    async def dbvarsHandler(request, glider:int):
        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if not await aiofiles.os.path.exists(dbfile):
            return sanic.response.json({'error': 'no db'})

        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            Utils.logDB(f'dbvars open {glider}')
            cur = await conn.cursor()
            try:
                await cur.execute('select * from dives')
            except aiosqlite.OperationalError as e:
                Utils.logDB(f'dbvars close (exception) {glider}')
                return sanic.response.json({'error': f'no table {e}'})
            names = list(map(lambda x: x[0], cur.description))
            data = {}
            data['names'] = names

            Utils.logDB(f'dbvars close {glider}')
        await checkClose(conn)
        return sanic.response.json(data)

    @app.route('/pro/<glider:int>/<whichVar:str>/<whichProfiles:int>/<first:int>/<last:int>/<stride:int>/<top:int>/<bot:int>/<binSize:int>')
    # description: extract bin averaged profiles
    # args: whichProfiles=1(dives)|2(climbs)|3(both)|4(combine)
    # parameters: mission
    # returns: compressed JSON dict of binned profiles
    @authorized()
    @compress.compress()
    async def proHandler(request, glider:int, whichVar:str, whichProfiles:int, first:int, last:int, stride:int, top:int, bot:int, binSize:int):
        ncfilename = Utils.get_mission_timeseries_name(None, gliderPath(glider,request))
        if not await aiofiles.os.path.exists(ncfilename):
            return sanic.response.text('no db')

        data = ExtractTimeseries.timeSeriesToProfile(whichVar, whichProfiles, first, last, stride, top, bot, binSize, ncfilename)
        out = ExtractTimeseries.dumps(data[0]) # need custom serializer for the numpy array
        return sanic.response.raw(out, headers={ 'Content-type': 'application/json' })


    @app.route('/timevars/<glider:int>')
    # description: list of timeseries variables
    # parameters: mission
    # returns: JSON list of variable names
    @authorized()
    async def timeSeriesVarsHandler(request, glider:int):
        ncfilename = Utils.get_mission_timeseries_name(None, gliderPath(glider,request))
        if not await aiofiles.os.path.exists(ncfilename):
            return sanic.response.json({'error': 'no db'})

        names = ExtractTimeseries.getVarNames(ncfilename)
        names = sorted([ f['var'] for f in names ])
        return sanic.response.json(names)
        
    @app.route('/time/<glider:int>/<dive:int>/<which:str>')
    # description: extract timeseries data from netCDF
    # parameters: mission
    # returns: compressed JSON dict of timeseries data
    @authorized()
    @compress.compress()
    async def timeSeriesHandler(request, glider:int, dive:int, which:str):
        ncfilename = Utils.get_mission_timeseries_name(None, gliderPath(glider,request))
        if not await aiofiles.os.path.exists(ncfilename):
            return sanic.response.json({'error': 'no db'})

        whichVars = which.split(',')
        dbVars = whichVars
        if 'time' in dbVars:
            dbVars.remove('time')

        data = ExtractTimeseries.extractVars(ncfilename, dbVars, dive, dive)
        return sanic.response.json(data)

    @app.route('/query/<glider:int>/<queryVars:str>')
    # description: query per dive database for arbitrary variables
    # args: queryVars=comma separated list
    # parameters: mission, format, limit
    # returns: JSON dict of query results
    @authorized()
    async def queryHandler(request, glider, queryVars):
        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if not await aiofiles.os.path.exists(dbfile):
            return sanic.response.json({'error': 'no db'})

        if 'format' in request.args:
            format = request.args['format'][0]
        else:
            format = 'json'

        if 'limit' in request.args:
            limit = request.args['limit'][0]
        else:
            limit = False
 
        queryVars = queryVars.rstrip(',')
        pieces = queryVars.split(',')
        if limit:
            q = f"SELECT {queryVars} FROM dives ORDER BY {pieces[0]} DESC LIMIT {limit}"
        elif pieces[0] == 'dive':
            q = f"SELECT {queryVars} FROM dives ORDER BY dive ASC"
        else:
            q = f"SELECT {queryVars} FROM dives"

        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            # conn.row_factory = rowToDict
            Utils.logDB(f'query open {glider}')
            cur = await conn.cursor()
            try:
                await cur.execute(q)
            except:
                Utils.logDB(f'query close (except) {glider}')
                return sanic.response.json({'error': 'db error'})

            d = await cur.fetchall()
            if format == 'json':
                data = {}
                print(cur.description)
                for i in range(len(cur.description)):
                    data[cur.description[i][0]] = [ f[i] for f in d ]

                Utils.logDB(f'query close (return) {glider}')
                return sanic.response.json(data)
            else:
                str = ''
                Utils.logDB(f'query close (else) {glider}')
                return sanic.response.json({'error': 'db error'})
                

    @app.route('/selftest/<glider:int>')
    # description: selftest review
    # parameters: mission
    # returns: HTML format summary of latest selftest results
    async def selftestHandler(request, glider:int):
        cmd = f"{sys.path[0]}/SelftestHTML.py"
        proc = await asyncio.create_subprocess_exec(
            cmd, f"{glider:03d}", gliderPath(glider, request), 
            stdout=asyncio.subprocess.PIPE, 
            stderr=asyncio.subprocess.PIPE
        )
        results, err = await proc.communicate()
        return sanic.response.html(purgeSensitive(results.decode('utf-8', errors='ignore')))

    #
    # POST handler - to save files back to basestation
    #

    # first the safety function
    def applyControls(c, text, filename):
        forbidden = ['shutdown', 'scuttle', 'wipe', 'reboot', 'pdos']
        for nono in forbidden:
            if nono in text.lower():
                sanic.log.logger.info(f"{nono} is a nono")
                return True

        d1 = c['global']['deny'] if 'global' in c and 'deny' in c['global'] else []
        d2 = c[filename]['deny'] if filename in c and 'deny' in c[filename] else []
        a1 = c['global']['allow'] if 'global' in c and 'allow' in c['global'] else []
        a2 = c[filename]['allow'] if filename in c and 'allow' in c[filename] else []

        status = False
        for line in text.splitlines():
            for d in d1:
                if d.search(line):
                    status = True
                    sanic.log.logger.info(f"global deny {line} ({d})")
                    for a in a1:
                        if a.search(line):
                            sanic.log.logger.info(f"global allow {line} ({d})")
                            status = False
                            break;
                    if status:
                        for a in a2:
                            if a.search(line):
                                sanic.log.logger.info(f"{filename} allow {line} ({d})")
                                status = False
                                break;

                    if status:
                        return status

            for d in d2:
                if d.search(line):
                    status = True
                    sanic.log.logger.info(f"{filename} deny {line} ({d})")
                    for a in a2:
                        if a.search(line):
                            sanic.log.logger.info(f"{filename} allow {line} ({d})")
                            status = False
                            break

                    if status:
                        return status
    
        return False

    @app.post('/upload/<glider:int>')
    # description: upload files to glider home directory
    # parameters: mission
    # returns: 
    @authorized()
    async def uploadHandler(request, glider: int):
       
        if 'UPLOAD_SECRET' not in app.config:
            return sanic.response.text('no')

        signature = request.headers.get('x-signature')
        timestamp = request.headers.get('x-timestamp')
        if abs(time.time() - float(timestamp)) > 30:
            return sanic.response.text('no')

        payload = request.body.decode('utf-8', errors='ignore')
        secret = request.app.config.UPLOAD_SECRET

        sig_string = 'v0:' + timestamp + ':' + payload
        sig = 'v0=' + hmac.new(bytes(secret, 'utf-8'),
                               msg=bytes(sig_string, 'utf-8'),
                               digestmod=hashlib.sha256).hexdigest()

        if not hmac.compare_digest(sig, signature):
            return sanic.response.text('no')
        
        res = request.json
        if not 'glider' in res:
            return sanic.response.text('no')

        try:
            bo = baseOpts(glider, gliderPath(glider, request), 'BaseCtrlFiles')
        except:
            bo = None

        if 'body' in res and 'file' in res:
            try:
                f = open(f"{gliderPath(glider,request)}/{res['file']}_{timestamp}", 'wb')
                f.write(base64.b64decode(bytes(res['body'], 'utf-8')))
                f.close()
                if bo:
                    msg = f"file uploaded {res['file']}"
                    BaseCtrlFiles.process_pagers_yml(bo, glider, ("upload",), upload_message=msg)

                return sanic.response.text('success') 
            except Exception as e:
                return sanic.response.text(f'error {e}')
        elif 'event' in res:
            try:
                f = open(f"{gliderPath(glider,request)}/events.log", 'a')
                f.write(res['event'])
                f.close()
                if bo:
                    BaseCtrlFiles.process_pagers_yml(bo, glider, ("upload",), upload_message=res['event'])

                return sanic.response.text('success') 
            except Exception as e:
                return sanic.response.text(f'error {e}')
                
        return sanic.response.text('error') 

    @app.post('/save/<glider:int>/<which:str>')
    # description: save glider control file
    # args: which=cmdfile|targets|science|scicon.sch|tcm2mat.cal|pdoscmds.bat|sg_calib_constants.m
    # payload: (JSON) file, contents
    # parameters: mission
    # returns: validator results and/or error message  
    @authorized(modes=['private', 'pilot'], requirePilot=True)
    async def saveHandler(request, glider:int, which:str):
        # the no save command line flag allows one more layer
        # of protection
        if request.app.config.NO_SAVE:
            return sanic.response.text('not allowed')

        validator = {"cmdfile": "cmdedit", "science": "sciedit", "targets": "targedit"}

        message = request.json
        if 'file' not in message or message['file'] != which:
            return sanic.response.text('oops')

        if applyControls(request.app.ctx.controls, message['contents'], which) == True:
            return sanic.response.text('not allowed')
         
        path = gliderPath(glider, request)
        if which in validator:
            try:
                async with aiofiles.tempfile.NamedTemporaryFile('w', delete=False) as file:
                    await file.write(message['contents'])
                    await file.close()
                    sanic.log.logger.debug("saved to %s" % file.name)

                    (tU, _) = getTokenUser(request)

                    if 'force' in message and message['force'] == 1:
                        cmd = f"{sys.path[0]}/{validator[which]} -d {path} -q -i -f {file.name} -u {tU}"
                    else:
                        cmd = f"{sys.path[0]}/{validator[which]} -d {path} -q -f {file.name} -u {tU}"
            
                    proc = await asyncio.create_subprocess_shell(
                        cmd, 
                        stdout=asyncio.subprocess.PIPE, 
                        stderr=asyncio.subprocess.PIPE
                    )
                    out, err = await proc.communicate()
                    results = out.decode('utf-8', errors='ignore') 
                    await aiofiles.os.remove(file.name)
            except Exception as e:
                results = f"error saving {which}, {str(e)}"

            return sanic.response.text(results)

        else: # no validator for this file type
            try:
                async with aiofiles.open(f'{path}/{which}', 'w') as file:
                    await file.write(message['contents'])
                return sanic.response.text(f"{which} saved ok")
            except Exception as e:
                return sanic.response.text(f"error saving {which}, {str(e)}")
                
    # The get handler for http POST based notifications from the basestation.
    # Run a route to receive notifications remotely. Typically only used 
    # when running vis on a server different from the basestation proper
    @app.post('/url')
    # description: .urls notification handler (used when vis server is different from basestation server)
    # parameters: instrument_name, dive, files (), status (), gpsstr ()
    # returns: 'ok' or 'error'
    async def urlHandler(request):
        if 'instrument_name' not in request.args:
            return sanic.response.text('error')

        glider = int(request.args['instrument_name'][0][2:])
        dive   = int(request.args['dive'][0]) if 'dive' in request.args else None
        files  = request.args['files'][0] if 'files' in request.args else None
        status = request.args['status'][0] if 'status' in request.args else None
        gpsstr = request.args['gpsstr'][0] if 'gpsstr' in request.args else None

        mission = activeMission(glider, request)

        if status:
            content = f"status={status}"
            topic = 'status'
            msg = { "glider": glider, "dive": dive, "content": content, "time": time.time(), "mission": mission }
        elif gpsstr:
            topic = 'gpsstr'
            try: 
                msg = request.json
                msg.update({"mission": mission})
            except Exception as e:
                sanic.log.logger.info(f"gpsstr body: {e}")
                msg = {}
        elif files:
            content = f"files={files}" 
            topic = 'files'
            if hasattr(request, 'json') and request.json:
                msg = request.json
                msg.update({ "time": time.time(), "mission": mission } )
                if 'when' not in msg:
                    msg.update({ "when": "urls" } )
                sanic.log.logger.info(f"URLS payload {msg}")
            else:
                msg = { "glider": glider, "dive": dive, "content": content, "time": time.time(), "when": "urls", "mission": mission }

        # consider whether this should go to all instances (Utils.notifyVisAsync)
        try:
            zsock = zmq.asyncio.Context().socket(zmq.PUSH)
            zsock.connect(request.app.config.NOTIFY_IPC)
            zsock.setsockopt(zmq.SNDTIMEO, 200)
            zsock.setsockopt(zmq.LINGER, 0)
            # these two log lines are critical - the socket send
            # does not go out without them ....  ¯\_(ツ)_/¯
            sanic.log.logger.info(f"sending {glider:03d}-urls-{topic}")
            sanic.log.logger.info(f"msg={msg}")
            await zsock.send_multipart([(f"{glider:03d}-urls-{topic}").encode('utf-8'), dumps(msg)]) 
            zsock.close()
        except:
            return sanic.response.text('error')
     
        return sanic.response.text('ok')

    async def getChatMessages(request, glider, t, conn=None):
        if conn == None:
            dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
            if not await aiofiles.os.path.exists(dbfile):
                return (None, time.time())

            myconn = await aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True)
            Utils.logDB(f'getChatMessages open {glider}')
            myconn.row_factory = rowToDict
        else:
            myconn = conn
    
        try:
            cur = await myconn.cursor()
            q = f"SELECT * FROM chat WHERE timestamp > {t} ORDER BY timestamp;" #  DESC LIMIT 20;"
            await cur.execute(q)
            rows = await cur.fetchall()
            await cur.close()
        except Exception as e:
            sanic.log.logger.info(e)
            rows = None

        if conn == None:
            await myconn.close()
            Utils.logDB(f'getChatMessages close {glider}')

        if rows:
            for r in rows:
                if 'attachment' in r and r['attachment'] is not None:
                    b = r['attachment']
                    r['attachment'] = base64.b64encode(b).decode('utf-8')

            return (rows, rows[-1]['timestamp'])

        return (None, time.time())

    @app.route('/chat/history/<glider:int>')
    # description: chat history from database
    # parameters: mission
    # returns: JSON dict of chat history
    @authorized(modes=['private', 'pilot'])
    async def chatHistoryHandler(request, glider:int):
        if request.app.config.NO_CHAT:
            return sanic.response.json({'error': 'not allowed'})

        (tU, _) = getTokenUser(request)
        if tU == False:
            return sanic.response.json({'error': 'authorization failed'})

        (rows, _) = await getChatMessages(request, glider, 0)
        return sanic.response.json(rows)

    @app.post('/chat/send/<glider:int>')
    # description: POST a message to chat
    # parameters: mission
    # payload: (form) attachment, message
    # returns: JSON dict of chat history
    @authorized(modes=['private', 'pilot'])
    async def chatHandler(request, glider:int):
        if request.app.config.NO_CHAT:
            return sanic.response.text('not allowed')

        # we could have gotten here by virtue of no restrictions specified for this glider/mission,
        # but chat only worked if someone is logged in, so we check that we have a user
        (tU, _) = getTokenUser(request)
        if tU == False:
            return sanic.response.text('authorization failed')

        attach = None
        if 'attachment' in request.files:
            attach = request.files['attachment'][0]
 
        msg = None
        if 'message' in request.form:
            msg = request.form['message'][0]

        if not msg and not attach:
            return sanic.response.text('oops')

        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        if not await aiofiles.os.path.exists(dbfile):
            return sanic.response.text('no db')

        now = time.time()
 
        async with aiosqlite.connect(dbfile) as conn:
            Utils.logDB(f'chat open {glider}')
            cur = await conn.cursor()
            cur.execute("PRAGMA busy_timeout=200;")

            try:
                if attach:
                    q = f"INSERT INTO chat(timestamp, user, message, attachment, mime) VALUES(?, ?, ?, ?, ?)"
                    values = (now, tU, msg, attach.body, attach.type)
                else:
                    q = f"INSERT INTO chat(timestamp, user, message) VALUES(?, ?, ?)"
                    values = ( now, tU, msg )
                await cur.execute(q, values)
                await conn.commit()

                await Utils.notifyVisAsync(glider, 'chat', f"{now}:{'attachment' if attach else 'none'}:{msg}")
                Utils.logDB(f'chat close {glider}')
                return sanic.response.text('SENT')
            except aiosqlite.OperationalError as e:
                sanic.log.logger.info(e)
                Utils.logDB(f'chat close (except) {glider}')
                return sanic.response.text('oops')


    @app.route('/pos/<glider:int>')
    # description: position display
    # parameters: mission
    # returns: HTML page with position display
    @authorized()
    async def posHandler(request, glider:int):
        filename = f'{sys.path[0]}/html/pos.html'
        return await sanic.response.file(filename, mime_type='text/html')

    @app.route('/pos/poll/<glider:str>')
    # description: get latest glider position
    # parameters: mission
    # returns: JSON dict of glider position
    async def posPollHandler(request: sanic.Request, glider:str):
        if ',' in glider:
            try:
                gliders = map(int, glider.split(','))
            except:
                return sanic.response.json({'error': 'invalid'})
        else:
            try:
                gliders = [ int(glider) ]
            except:
                return sanic.response.json({'error': 'invalid'})

        opTable = await buildAuthTable(request, None)


        if 'format' in request.args:
            format = request.args['format'][0]
        else:
            format = 'json'

        if 't' in request.args and len(request.args['t'][0]) > 0:
            t = int(request.args['t'][0])
            q = f"SELECT * FROM calls WHERE epoch > {t} ORDER BY epoch DESC LIMIT 1;"
        else:
            q = f"SELECT * FROM calls ORDER BY epoch DESC LIMIT 1;"
                
        # xurvey uses this but nothing else - easy enough to add
        # nmea = 'format' in request.args and request.args['format'][0] == 'nmea'

        out = []
        outs = ''
        for glider in gliders:
            m = next(filter(lambda d: d['glider'] == glider and d['status'] == 'active', opTable), None)
            if m is None: # must not be authorized
                continue

            dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
            if not await aiofiles.os.path.exists(dbfile):
                continue

            async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                Utils.logDB(f'posPoll open {glider}')
                try:
                    conn.row_factory = rowToDict
                    cur = await conn.cursor()
                    await cur.execute(q)
                    row = await cur.fetchone()
                    if row:
                        if format == 'json':
                            Utils.logDB(f'posPoll close 1 {glider}')
                            row.update({"glider": glider})
                            out.append(row)
                        elif format == 'csv':
                            Utils.logDB(f'posPoll close 2 {glider}')
                            outs = outs + f"{row['epoch']},{row['lat']},{row['lon']}\n"
                    else:
                        Utils.logDB(f'posPoll close 3 {glider}')
                        # return sanic.response.text('none')
                except Exception as e:
                    sanic.log.logger.info(e)
                    Utils.logDB(f'posPoll close oops {glider}')
                    return sanic.response.json({'error': 'oops'})

        if format == 'csv':
            return sanic.response.text(outs)
        else:
            if len(out) == 0: 
                 return sanic.response.json({'error': 'none'})
            elif len(out) == 1:    
                return sanic.response.json(out[0])
            else:
                return sanic.response.json(out)
           
    async def getLatestCall(request, glider, conn=None, limit=1):
        if conn == None:
            dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
            sanic.log.logger.info(dbfile)
            if not await aiofiles.os.path.exists(dbfile):
                return None

            myconn = await aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True)
            Utils.logDB(f'getLatestCall open {glider}')
            myconn.row_factory = rowToDict
        else:
            myconn = conn

        row = None
        try:
            cur = await myconn.cursor()
            q = f"SELECT * FROM calls ORDER BY epoch DESC LIMIT {limit};"
            sanic.log.logger.info(q)
            await cur.execute(q)
            row = await cur.fetchall()
            await cur.close()
        except Exception as e:
            sanic.log.logger.info(e)

        if conn == None:
            Utils.logDB(f'getLatestCall close {glider}')
            await myconn.close()

        return row
 
    #
    # web socket (real-time streams), 
    #

    @app.websocket('/pos/stream/<glider:int>')
    # description: stream real-time position updates
    # parameters: mission
    @authorized()
    async def posStreamHandler(request: sanic.Request, ws: sanic.Websocket, glider:int):
        zsock = zmq.asyncio.Context().socket(zmq.SUB)
        zsock.setsockopt(zmq.LINGER, 0)
        zsock.connect(request.app.config.WATCH_IPC)
        zsock.setsockopt(zmq.SUBSCRIBE, (f"{glider:03d}-urls-gpsstr").encode('utf-8'))

        # we get the first fix out of the db so the user gets the latest 
        # position if we're between calls

        sanic.log.logger.info('posStream ws opened')
        row = await getLatestCall(request, glider)
        if row:
            await ws.send(dumps(row[0]).decode('utf-8'))

        # after that we rely on the notification payload because if we're
        # running as a remote instance the database won't be synced until
        # much later
        while True:
            try:
                msg = await zsock.recv_multipart()
                # sanic.log.logger.info(f"got msg={msg[1]}")
                await ws.send(msg[1].decode('utf-8'))
                # sanic.log.logger.info("ws sent")
            except BaseException as e: # websockets.exceptions.ConnectionClosed:
                sanic.log.logger.info(f'posStream ws connection closed {e}')
                await ws.close()
                zsock.close()
                return
 
    @app.websocket('/stream/<which:str>/<glider:int>')
    # description: stream real-time glider information (comm.log, chat, cmdfile changed, glider calling, etc.)
    # parameters: mission
    @authorized()
    async def streamHandler(request: sanic.Request, ws: sanic.Websocket, which:str, glider:int):
        m = matchMission(glider, request)
        if m['status'] != 'active':
            return sanic.response.text('inactive')

        filename = f'{gliderPath(glider,request)}/comm.log'

        await ws.send(f"START") # send something to ack the connection opened

        sanic.log.logger.debug(f"streamHandler start {filename}")

        commFile = None
        commTell = 0
        if request.app.config.RUNMODE > MODE_PUBLIC and await aiofiles.os.path.exists(filename):
            statinfo = await aiofiles.os.stat(filename)
            if statinfo.st_size < 10000:
                start = 0
            else:
                start = statinfo.st_size - 10000

            commFile = await aiofiles.open(filename, 'rb')
            if which == 'init':
                await commFile.seek(start, 0)
                data = await commFile.read()
                if data:
                    await ws.send(data.decode('utf-8', errors='ignore'))
            else:
                await commFile.seek(0, 2)
         
            commTell = await commFile.tell()
 
            try:
                row = await getLatestCall(request, glider, limit=3)
                for i in range(len(row)-1, -1, -1):
                    await ws.send(f"NEW={dumps(row[i]).decode('utf-8')}")
            except:
                pass
        else:
            await ws.send('no comm.log\n')

        (tU, _) = getTokenUser(request)
        
        prev_db_t = time.time()
        conn = None

        if tU and request.app.config.RUNMODE > MODE_PUBLIC:
            dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
            if (which == 'history' or which == 'init') and await aiofiles.os.path.exists(dbfile):
                async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                    Utils.logDB(f'stream 1 open {glider}')
                    conn.row_factory = rowToDict 
                    (rows, prev_db_t) = await getChatMessages(request, glider, 0, conn)
                    if rows:
                        await ws.send(f"CHAT={dumps(rows).decode('utf-8')}")

                    Utils.logDB(f'stream 1 close {glider}')
                await checkClose(conn)
        zsock = zmq.asyncio.Context().socket(zmq.SUB)
        zsock.setsockopt(zmq.LINGER, 0)
        zsock.connect(request.app.config.WATCH_IPC)
        zsock.setsockopt(zmq.SUBSCRIBE, (f"{glider:03d}-").encode('utf-8'))
        sanic.log.logger.info(f"subscribing to {glider:03d}-")

        
        prev = ""
        while True:
            try:
                msg = await zsock.recv_multipart()
                topic = msg[0].decode('utf-8')
                body  = msg[1].decode('utf-8')
                sanic.log.logger.info(f"topic {topic}")

                if 'chat' in topic and tU and request.app.config.RUNMODE > MODE_PUBLIC:
                    if await aiofiles.os.path.exists(dbfile):
                        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                            Utils.logDB(f'stream 2 open {glider}')
                            conn.row_factory = rowToDict 
                        
                            (rows, prev_db_t) = await getChatMessages(request, glider, prev_db_t, conn)
                            if rows:
                                await ws.send(f"CHAT={dumps(rows).decode('utf-8')}")

                            Utils.logDB(f'stream 2 close {glider}')
                        await checkClose(conn)
                elif 'comm.log' in topic and request.app.config.RUNMODE > MODE_PUBLIC:
                    sanic.log.logger.info('comm.log notified')
                    if not commFile:
                        commFile = await aiofiles.open(filename, 'rb')
                        sanic.log.logger.info('comm.log opened')
                    elif os.stat(filename).st_ino != os.fstat(commFile.fileno()).st_ino: # if comm.log has changed out from under us
                        sanic.log.logger.info('comm.log inode changed')
                        if await aiofiles.os.path.exists(filename):
                            if commFile:
                                commFile.close()
                            commFile = await aiofiles.open(filename, 'rb')
                            await commFile.seek(commTell, 0)
                            sanic.log.logger.info(f"comm.log re-opened, seek to {commTell}") 

                    if commFile:
                        sanic.log.logger.info(f"before read, position = {commTell}")
                        data = (await commFile.read()).decode('utf-8', errors='ignore')
                        commTell = await commFile.tell()
                        sanic.log.logger.info(f"comm.log read, position = {commTell}")
                        if data:
                            await ws.send(data)
                elif 'urls' in topic:
                    # m = loads(body)
                    await ws.send(f"NEW={body}")
                elif 'file' in topic and request.app.config.RUNMODE > MODE_PUBLIC:
                    m = loads(body) 
                    
                    async with aiofiles.open(m['full'], 'rb') as file:
                        Utils.logDB(f'stream 3 open {glider}')
                        body = (await file.read()).decode('utf-8', errors='ignore')
                        m.update( { "body": body } )
                        await ws.send(f"FILE={dumps(m).decode('utf-8')}")

                    Utils.logDB(f'stream 3 close {glider}')
                elif 'file-cmdfile' in topic:
                    directive = await summary.getCmdfileDirective(cmdfilename)
                    await ws.send(f"CMDFILE={directive}")
                else:
                    sanic.log.logger.info(f"unhandled topic {topic}")

            except BaseException as e: # websockets.exceptions.ConnectionClosed:
                sanic.log.logger.info(f'stream ws connection closed {e}')

                await ws.close()
                zsock.close()
                return

    
    @app.websocket('/map/stream')
    async def mapStreamHandler(request: sanic.Request, ws: sanic.Websocket):
        await ws.send(f"START") # send something to ack the connection opened

        zsock = zmq.asyncio.Context().socket(zmq.SUB)
        zsock.setsockopt(zmq.LINGER, 0)
        zsock.connect(request.app.config.WATCH_IPC)
        zsock.setsockopt(zmq.SUBSCRIBE, b'')

        while True:
            try:
                msg = await zsock.recv_multipart()
                topic = msg[0].decode('utf-8')
                body  = msg[1].decode('utf-8')
                if '-ship-' in topic: 
                    await ws.send(body)
                elif '-urls-gpsstr' in topic or '-files' in topic:  
                    out = loads(body)
                    if (not 'glider' in out) :
                        out.update( { 'glider': int(topic[0:3]) } )

                    if (not 'mission' in out):
                        mission = activeMission(out['glider'], request)
                        out.update( { 'mission': mission['mission'] if mission else '' } )

                    await ws.send(f"{dumps(out).decode('utf-8')}")

            except BaseException as e: # websockets.exceptions.ConnectionClosed:
                sanic.log.logger.info(f'watch ws connection closed {e}')
                zsock.close()
                await ws.close()
                return

    @app.route('/tile/<path:str>/<z:int>/<x:int>/<y:int>')
    # description: download map tile
    async def tileHandler(request, path:str, z:int, x:int, y:int):
        path = f'{sys.path[0]}/tiles/{path}/{z}/{x}/{y}.png'
        if await aiofiles.os.path.exists(path):
            return await sanic.response.file(path, mime_type='image/png')
        else:
            return sanic.response.text('not found', status=404)

    @app.route('/tile/asset/<path:str>/<z:int>/<x:int>/<y:int>')
    async def tileSetHandler(request, path:str, z:int, x:int, y:int):
        path = f'{sys.path[0]}/tiles/assets/{path}/{z}/{x}/{y}.png'
        if await aiofiles.os.path.exists(path):
            return await sanic.response.file(path, mime_type='image/png')
        else:
            return sanic.response.text('not found', status=404)


    # not protected by decorator - buildAuthTable only returns authorized missions
    @app.websocket('/watch')
    # description: stream real-time glider summary state (call status, cmdfile directive)
    # parameters: mission, gliders
    ## @authorized(protections=['pilot'])
    async def watchHandler(request: sanic.Request, ws: sanic.Websocket):

        gliders = list(map(int, request.args['gliders'][0].split(','))) if 'gliders' in request.args else None

        sanic.log.logger.info("watchHandler start")
        opTable = await buildAuthTable(request, None)
        await ws.send(f"START") # send something to ack the connection opened

        zsock = zmq.asyncio.Context().socket(zmq.SUB)
        zsock.setsockopt(zmq.LINGER, 0)
        zsock.connect(request.app.config.WATCH_IPC)
        zsock.setsockopt(zmq.SUBSCRIBE, b'')
        sanic.log.logger.info('context opened')

        while True:
            try:
                msg = await zsock.recv_multipart()
                topic = msg[0].decode('utf-8')
                body  = msg[1].decode('utf-8')

                pieces = topic.split('-', maxsplit=1)
                glider = int(pieces[0])
                topic  = pieces[1]

                m = next(filter(lambda d: d['glider'] == glider and d['status'] == 'active', opTable), None)
                if m is None: # must not be authorized
                    continue

                if gliders and not glider in gliders:
                    continue
 
                if 'cmdfile' in topic:
                    cmdfile = f"{gliderPath(glider,request,mission=m['mission'])}/cmdfile"
                    directive = await summary.getCmdfileDirective(cmdfile)
                    sanic.log.logger.debug(f"watch {glider} cmdfile modified")
                    out = {
                            "glider": glider, 
                            "mission": m['mission'] if m['mission'] else '', 
                            "what": "cmdfile",
                            "directive": directive
                          }
                            
                    await ws.send(f"{dumps(out).decode('utf-8')}")
                elif 'comm.log' in topic and request.app.config.RUNMODE > MODE_PUBLIC:
                    msg = loads(body)
                    filename = f"{gliderPath(glider,request,mission=m['mission'])}/comm.log"
                    commFile = await aiofiles.open(filename, 'rb')
                    await commFile.seek(-min([msg['delta'], 1000]), 2)
                    data = (await commFile.read()).decode('utf-8', errors='ignore')
                    await commFile.close()
                    if data:
                        out = { 
                                "glider": glider, 
                                "mission": m['mission'] if m['mission'] else '', 
                                "what": "comm.log",
                                "content": data
                              }
                        await ws.send(f"{dumps(out).decode('utf-8')}")
                elif 'urls' in topic:
                    try:
                        msg = loads(body)
                        msg.update({ "what": "urls" })
                        if 'glider' not in msg:
                            msg.update({ "glider": glider} ) # in case it's not in the payload (session), watch payloads must always include it
                        if 'mission' not in msg:
                            msg.update({ "mission": m['mission'] if m['mission'] else ""} ) #
            
                        await ws.send(f"{dumps(msg).decode('utf-8')}")
                    except Exception as e:
                        sanic.log.logger.info(f"watchHandler {e}")
            except BaseException as e: # websockets.exceptions.ConnectionClosed:
                sanic.log.logger.info(f'watch ws connection closed {e}')
                await ws.close()
                zsock.close()
                return

    @app.listener("after_server_start")
    async def initApp(app, loop):
        await buildMissionTable(app)
        await buildUserTable(app)

        sanic.log.logger.info(f'STARTING runMode {modeNames[app.config.RUNMODE]}')

    

    @app.middleware('request')
    async def checkRequest(request):
        
        if request.app.config.RUNMODE != MODE_PRIVATE and ('FQDN' in request.app.config and request.app.config.FQDN and request.app.config.FQDN != '' and request.app.config.FQDN not in request.headers['host']):
            sanic.log.logger.info(f"request for {request.headers['host']} blocked for lack of FQDN {request.app.config.FQDN}")
            return sanic.response.text('not found', status=502)
        if request.app.config.FORWARDED_SECRET and not request.forwarded:
            return sanic.response.text('Not Found', status=502)
       
        if 'secret' in request.forwarded:
            del request.forwarded['secret']

        return None


#
#  setup / config file readers
#

async def buildUserTable(app):

    if await aiofiles.os.path.exists(app.config.USERS_FILE):
        async with aiofiles.open(app.config.USERS_FILE, "r") as f:
            d = await f.read()
            try:
                x = yaml.safe_load(d)
            except Exception as e:
                sanic.log.logger.info(f"users parse error {e}")
                x = {}
    else:
        x = {}

    userDictKeys = [ "groups", "password" ]

    dflts = None
    for user in list(x.keys()):
        if user == 'default':
            dflts = x[user]
            del x[user]
            continue
        
        for uk in userDictKeys:
            if uk not in x[user].keys():
                x[user].update( { uk: dflts[uk] if dflts and uk in dflts else None } )

    app.ctx.userTable = x
    return x

async def buildMissionTable(app, config=None):
    if config == None:
        config = app.config

    if 'SINGLE_MISSION' in config and config.SINGLE_MISSION:
        sanic.log.logger.info(f'building table for single mission {config.SINGLE_MISSION}')
        pieces = config.SINGLE_MISSION.split(':')
        glider = pieces[0].replace('sg', '').replace('SG', '')
        x = { 'missions': [ {'glider': int(glider), 'path': pieces[1], 'status': 'active' } ] }
    else: 
        if await aiofiles.os.path.exists(config['MISSIONS_FILE']):
            async with aiofiles.open(config['MISSIONS_FILE'], "r") as f:
                d = await f.read()
                try:
                    x = yaml.safe_load(d)
                except Exception as e:
                    sanic.log.logger.info(f"mission file parse error {e}")
                    x = {}
        else:
            x = {}

    if 'includes' in x:
        missionTable = []
        if 'organization' in x and app:
            app.ctx.organization = x['organization']

        for group in list(x['includes'].keys()):     
            c = { 'MISSIONS_FILE': x['includes'][group]['missions'] }
            tbl = await buildMissionTable(None, config=c)
            for k in tbl:
                if 'path' in k and k['path']:
                    k['path'] = x['includes'][group]['root'] + '/' + k['path']
                else:
                    k['path'] = x['includes'][group]['root'] + f"/sg{k['glider']:03d}"

            missionTable = missionTable + tbl

        if app:
            app.ctx.missionTable = missionTable

        print(missionTable)
        return missionTable

    if 'organization' not in x:
        x['organization'] = {}
    if 'missions' not in x:
        x['missions'] = {}
    if 'endpoints' not in x:
        x['endpoints'] = {}
    if 'controls' not in x:
        x['controls'] = {}
    if 'defaults' not in x:
        x['defaults'] = {}
    if 'pilotdefaults' not in x:
        x['pilotdefaults'] = {}
    if 'privatedefaults' not in x:
        x['privatedefaults'] = {}
    if 'publicdefaults' not in x:
        x['publicdefaults'] = {}
    if 'assets' not in x:
        x['assets'] = {}
    if 'routes' not in x:
        x['routes'] = []

    orgDictKeys = ["orgname", "orglink", "text", "contact", "email"]
    for ok in orgDictKeys:
        if ok not in x['organization'].keys():
            x['organization'].update( { ok: None } )


    missionDictKeys = [ "mission", "users", "pilotusers", "groups", "pilotgroups", 
                        "started", "ended", "planned", 
                        "orgname", "orglink", "contact", "email", 
                        "project", "link", "comment", "reason", "endpoints",
                        "sa", "also", "kml", 
                      ]
    
    dflts         = x['defaults']
    mode_dflts    = x[modeNames[config.RUNMODE] + 'defaults']
    missions = []
    gliders  = []
    ids      = []
    actives  = []
    for n, m in enumerate(x['missions']):

        if 'glider' not in m:
            sanic.log.logger.info('skipping {m}')
            continue

        try:
            glider = int(m['glider'])

            if 'path' not in m:
                m.update({ "path": None })

            if 'status' not in m:
                m.update( {'status': 'active'} )

            if m['status'] == 'active':
                if glider in actives:
                    sanic.log.logger.info(f'{glider} already has an active mission')
                    continue
                else:
                    actives.append(glider)

            m.update({ "default": (not glider in gliders) })
            gliders.append(glider)

            for mk in missionDictKeys:
                if mk not in m:
                    if mode_dflts and mk in mode_dflts:
                        m.update( { mk: mode_dflts[mk] })
                    elif dflts and mk in dflts:
                        m.update( { mk: dflts[mk] })
                    elif mk in x['organization']:
                        m.update( { mk: x['organization'][mk] })
                    else:
                        m.update( { mk: None })

            # the following identifier must be unique (mission can be none, but only once)
            missionid = f"{glider:03d}-{m['mission']}"
            if missionid not in ids:
                ids.append(missionid)
                missions.append(m)
            else:
                sanic.log.logger.info(f'skipping duplicate {missionid}')

        except Exception as e:
            sanic.log.logger.info(f"error on glider {glider}, {e}")
            continue 
       
    endpointsDictKeys = [ "modes", "users", "groups", "requirepilot" ]
    dflts = None
    for k in list(x['endpoints'].keys()):
        if k == 'defaults':
            dflts = x['endpoints'][k]
            del x['endpoints'][k]
            continue    

        for ek in endpointsDictKeys:
            if ek not in x['endpoints'][k].keys():
                if dflts and ek in dflts:
                    x['endpoints'][k].update( { ek: dflts[ek] })
                else:
                    x['endpoints'][k].update( { ek: None } )
                    
    if dflts:
        for k in protectableRoutes:
            if k not in x['endpoints'].keys():
                x['endpoints'][k] = dict.fromkeys(endpointsDictKeys)
                x['endpoints'][k].update( dflts )        

    for k in x['controls'].keys():
        for da in x['controls'][k].keys():
            for index,exp in enumerate(x['controls'][k][da]):
                x['controls'][k][da][index] = re.compile(exp, re.IGNORECASE)

    if app:
        app.ctx.missionTable = missions
        app.ctx.organization = x['organization']
        app.ctx.endpoints = x['endpoints']
        app.ctx.controls = x['controls']
        app.ctx.assets = x['assets']
        app.ctx.routes = x['routes']

    return missions
 
async def buildAuthTable(request, defaultPath):
    opTable = []
    for m in request.app.ctx.missionTable:
        status = checkGliderMission(request, m['glider'], m['mission'])
        if status == PERM_REJECT:
            continue

        path    = m['path'] if m['path'] else defaultPath
        mission = m['mission'] if m['mission'] else defaultPath
        opTable.append({ "mission": mission, "glider": m['glider'], "path": path, "default": m['default'], "status": m['status'] })

    return opTable

async def buildDivePlotList(path, dive):
    exts = [".webp", ".div"] 
    plots = { ".webp": [], ".div": [] }
    p = Path(path)
    p = p / 'plots' 
    
    async for fpath in p.glob(f"dv{dive:04d}_*.*"):
        if fpath.suffix in exts:
            x = parse('dv{}_{}.{}', fpath.name)
            plot = x[1] 
            plots[fpath.suffix].append(plot)
    
    return (plots[".webp"], plots[".div"])

async def findNextPlot(path, plot, dive, direc):
    p = Path(path)
    p = p / 'plots'
    dives = []
    async for fpath in p.glob(f"dv????_{plot}"):
        x = parse('dv{}_{}.{}', fpath.name)
        dives.append(int(x[0]))

    if direc == 1:
        x = min([v for v in dives if v >= dive] or [max(dives)])
    else:
        x = max([v for v in dives if v <= dive] or [min(dives)])

    return x

async def buildMissionPlotList(path):
    plots = { "eng": { ".webp": [], ".div": [] }, "sg": { ".webp": [], ".div": [] } }
    maxdv = -1
    p = Path(path)
    p = p / 'plots' 
    exts = ['.div', '.webp']
    for prefix in ['eng', 'sg']:
        async for fpath in p.glob(f"{prefix}_*.*"):
            # if prefix == 'sg' and '_section_' in fpath.name:
            #    continue

            if fpath.suffix in exts:
                plot = '_'.join(fpath.stem.split('_')[1:])
                plots[prefix][fpath.suffix].append(plot)

    return (plots['eng']['.webp'], plots['sg']['.webp'], plots['eng']['.div'], plots['sg']['.div'])

#
# background main task 
#

async def checkFilesystemChanges(files):
    mods = []
    for f in files:
        if await aiofiles.os.path.exists(f['full']):
            n = await aiofiles.os.path.getctime(f['full'])
            if n > f['ctime']:
                f['ctime'] = n
                sz = await aiofiles.os.path.getsize(f['full'])
                if sz > f['size']:
                    f['delta'] = sz - f['size']
                else:
                    f['delta'] = sz

                f['size'] = sz
                mods.append(f)

    return mods

async def configWatcher(app):
    zsock = zmq.asyncio.Context().socket(zmq.SUB)
    zsock.setsockopt(zmq.LINGER, 0)
    zsock.connect(app.config.WATCH_IPC)
    sanic.log.logger.info('opened context for configWatcher')
    zsock.setsockopt(zmq.SUBSCRIBE, (f"000-file-").encode('utf-8'))
    while True:
        try:
            msg = await zsock.recv_multipart()
            sanic.log.logger.info(msg[1])
            topic = msg[0].decode('utf-8')
            if app.config['MISSIONS_FILE'] in topic:
                await buildMissionTable(app)
            elif app.config['USERS_FILE'] in topic:
                await buildUserTable(app)

        except BaseException as e: # websockets.exceptions.ConnectionClosed:
            zsock.close()
            return

        # app.m.name.restart() 

async def buildFilesWatchList(config):
    missions = await buildMissionTable(None, config=config)
    files = [ ]
    if not config.SINGLE_MISSION:
        for f in [ config['MISSIONS_FILE'], config['USERS_FILE'] ]:
            files.append( { 'glider': 0, 'full': f, 'file': f, 'ctime': 0, 'size': 0, 'delta': 0, 'mission': '' } )

    for m in missions:
        if m['status'] == 'active':
            for f in ["comm.log", "cmdfile", "science", "targets", "scicon.sch", "tcm2mat.cal", "sg_calib_constants.m", "pdoscmds.bat", f"sg{m['glider']:03d}.kmz"]:
                if m['path']:
                    fname = f"{m['path']}/{f}"
                else:
                    fname = f"sg{m['glider']:03d}/{f}" 
                files.append( { "glider": m['glider'], "full": fname, "file": f, "ctime": 0, "size": 0, "delta": 0, "mission": m['mission'] if m['mission'] else "" } )

    await checkFilesystemChanges(files) # load initial mod times

    return files

async def notifier(config):
    msk = os.umask(0o000)
    ctx = zmq.asyncio.Context()
    zsock = ctx.socket(zmq.PUB)
    zsock.bind(config.WATCH_IPC)
    zsock.setsockopt(zmq.SNDTIMEO, 1000)
    zsock.setsockopt(zmq.LINGER, 0)

    configWatchSocket = ctx.socket(zmq.SUB)
    configWatchSocket.setsockopt(zmq.LINGER, 0)
    configWatchSocket.connect(config.WATCH_IPC)
    configWatchSocket.setsockopt(zmq.SUBSCRIBE, (f"000-file-").encode('utf-8'))

    inbound = ctx.socket(zmq.PULL)
    inbound.bind(config.NOTIFY_IPC)
    os.umask(msk)

    files = await buildFilesWatchList(config)

    if config.SHIP_UDP is not None:
        udpSock = socket.socket(family=socket.AF_INET, type=socket.SOCK_DGRAM)
        udpSock.setblocking(0)
        udpSock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
        udpSock.bind(('', int(config.SHIP_UDP)))
    else:
        udpSock = None

    while True:
        stat = await inbound.poll(200)
        if stat:
            r = await inbound.recv_multipart()
            d = loads(r[1])
            if 'when' not in d:
                d.update({"when": "socket"})

            r[1] = dumps(d)
            sanic.log.logger.info("notifier got {r[0].decode('utf-8')}")
            await zsock.send_multipart(r)

        stat = await configWatchSocket.poll(200)
        if stat:
            msg = await configWatchSocket.recv_multipart()
            topic = msg[0].decode('utf-8')
            if config['MISSIONS_FILE'] in topic:
                files = await buildFilesWatchList(config)

        mods = await checkFilesystemChanges(files)
        sanic.log.logger.info(mods)
        for f in mods:
            msg = [(f"{f['glider']:03d}-file-{f['file']}").encode('utf-8'), dumps(f)]
            sanic.log.logger.info(f"{f['glider']:03d}-file-{f['file']}")
            await zsock.send_multipart(msg)

        if udpSock:
            try:
                data = udpSock.recvfrom(1024)
                sanic.log.logger.info(data)
                if data:
                    sentences = data[0].decode()
                    msg = { 'ship': 'shipname', 'time': time.time() }
                    for line in sentences.splitlines():
                        if 'GGA' in line:
                            pieces = line.split(',')
                            msg['hhmmss'] = float(pieces[1])
                            msg['lat'] = float(pieces[2])
                            msg['lon'] = float(pieces[4])
                            if (pieces[3] == 'S'):
                                msg['lat'] = -msg['lat']
                            if (pieces[5] == 'W'):
                                msg['lon'] = -msg['lon']

                        elif 'HDT' in line:
                            pieces = line.split(',')
                            msg['hdt'] = float(pieces[1])
                        elif 'VTG' in line:
                            pieces = line.split(',')
                            msg['cog'] = float(pieces[1])
                            msg['sog'] = float(pieces[5])
                        elif 'ZDA' in line:
                            pieces = line.split(',')
                            msg['yyyymmdd'] = int(pieces[4] + pieces[3] + pieces[2])

                    await zsock.send_multipart(["000-ship-shipname".encode('utf-8'), dumps(msg)])
            except:
                pass

                
def backgroundWatcher(config):
    loop = asyncio.get_event_loop()
    loop.create_task(notifier(config))
    loop.run_forever()

async def mainProcessReady(app):
    print('main process ready')
    app.manager.manage("backgroundWatcher", backgroundWatcher, { "config": app.config })

async def mainProcessStop(app):
    os.remove(app.config.WATCH_IPC[6:])
    os.remove(app.config.NOTIFY_IPC[6:])

def createApp(overrides: dict) -> sanic.Sanic:

    d = { "missionTable": [],   # list of missions (each a dict)
          "userTable": {},      # dict (keyed by username) of dict
          "organization": {},
          "endpoints": {},   # dict of url level protections (keyed by url name)
        }

    app = sanic.Sanic("SGpilot", ctx=SimpleNamespace(**d), dumps=dumps)

    # config values loaded from SANIC_ environment variables first
    # then get overridden by anything from command line
    # then get filled in by hard coded defaults as below if
    # not previously provided
    app.config.update(overrides)

    if 'SECRET' not in app.config:
        app.config.SECRET = secrets.token_hex()
    if 'MISSIONS_FILE' not in app.config:
        app.config.MISSIONS_FILE = "missions.yml"
    if 'USERS_FILE' not in app.config:
        app.config.USERS_FILE = "users.yml"
    if 'FQDN' not in app.config:
        app.config.FQDN = None;
    if 'USER' not in app.config:
        app.config.USER = os.getlogin()
    if 'SINGLE_MISSION' not in app.config:
        app.config.SINGLE_MISSION = None
    if 'WEATHERMAP_APPID' not in app.config:
        app.config.WEATHERMAP_APPID = ''
    if 'SHIP_UDP' not in app.config:
        print('default UDP None')
        app.config.SHIP_UDP = None;

    app.config.TEMPLATING_PATH_TO_TEMPLATES=f"{sys.path[0]}/html"

    attachHandlers(app)

    app.add_task(configWatcher)

    return app

def usage():
    print("vis.py glider mission visualization server")
    print("  --mission=|-m      [sgNNN:/abs/mission/path] run in single mission mode")
    print("  --mode=|-o         private|pilot|public")
    print("  --port=|-p         portNumber (ex. 20000)")
    print("  --root=|-r         baseDirectory (ex. /home/seaglider)")
    print("  --domain=|-d       fully-qualified-domain-name (optional)")
    print("  --missionsfile=|-f missions.yml file (default ROOT/missions.yml)")
    print("  --usersfile=|-u    users.yml file (default ROOT/users.yml)")
    print("  --certs=|-c        certificate file for SSL")
    print("  --ssl|-s           boolean enable SSL")
    print("  --inspector|-i     boolean enable SANIC inspector")
    print("  --nochat           boolean run without chat support")
    print("  --nosave           boolean run without save support")
    print()
    print("  Environment variables: ")
    print("    SANIC_CERTPATH, SANIC_ROOTDIR, SANIC_SECRET, ")
    print("    SANIC_MISSIONS_FILE, SANIC_USERS_FILE, SANIC_FQDN, ")
    print("    SANIC_USER, SANIC_SINGLE_MISSION")

if __name__ == '__main__':

    root = os.getenv('SANIC_ROOTDIR')
    runMode = MODE_PRIVATE
    port = 20001
    ssl = False
    certPath = os.getenv("SANIC_CERTPATH") 
    noSave = False
    noChat = False

    overrides = {}

    try:
        opts, args = getopt.getopt(sys.argv[1:], 'm:p:o:r:d:f:u:c:sih', ["mission=", "port=", "mode=", "root=", "domain=", "missionsfile=", "usersfile=", "certs=", "ssl", "inspector", "help", "nosave", "nochat", "shipudp="])
    except getopt.GetoptError as err:
        print(err)
        sys.exit(1)

    for o,a in opts:
        if o in ['-p', '--port']:
            port = int(a)
        elif o in ['-o', '--mode']:
            runMode = runModes[a]
        elif o in ['-r', '--root']:
            root = a
        elif o in ['-d', '--domain']:
            overrides['FQDN'] = a
        elif o in ['-f', '--missionsfile']:
            overrides['MISSIONS_FILE'] = a
        elif o in ['-u', '--usersfile']:
            overrides['USERS_FILE'] = a
        elif o in ['--shipudp']:
            overrides['SHIP_UDP'] = a
            print(f'UDP {a}')
        elif o in ['--shipjson']:
            override['SHIP_JSON'] = a
        elif o in ['--nosave']:
            noSave = True
        elif o in ['--nochat']:
            noChat = True
        elif o in ['-c', '--certs']:
            certPath = a
        elif o in ['-s', '--ssl']:
            ssl = True
        elif o in ['-i', '--inspector']:
            overrides['INSPECTOR'] = True
        elif o in ['-m', '--mission']:
            overrides['SINGLE_MISSION'] = a
            pieces = a.split(':')
            if len(pieces) != 2:
                print("-m sgNNN:/abs/mission/path")
                sys.exit(1)
        elif o in ['-h', '--help']:
            usage()
            sys.exit(1)
                 
    if root is None and not 'SINGLE_MISSION' in overrides:
        root = '/home/seaglider'

    if root is not None:
        os.chdir(os.path.expanduser(root))

    # we always load RUNMODE based on startup conditions
    overrides['RUNMODE'] = runMode
    overrides['NO_SAVE'] = noSave
    overrides['NO_CHAT'] = noChat

    overrides['NOTIFY_IPC'] = f"ipc:///tmp/sanic-{os.getpid()}-notify.ipc" 
    overrides['WATCH_IPC']  = f"ipc:///tmp/sanic-{os.getpid()}-watch.ipc" 

    # set a random SECRET here to be shared by all instances
    # running on this main process. Restarting the process will
    # mean all session tokens are invalidated 
    # use an environment variable SANIC_SECRET to 
    # make sessions persist across processes
    if "SANIC_SECRET" not in os.environ:
        overrides["SECRET"] = secrets.token_hex()

    WorkerManager.THRESHOLD = 600 # 60 seconds up from default 30

    loader = sanic.worker.loader.AppLoader(factory=partial(createApp, overrides))
    app = loader.load()
    app.register_listener(mainProcessReady, "main_process_ready")
    app.register_listener(mainProcessStop, "main_process_stop")

    if ssl:
        certs = {
            "cert": f"{certPath}/fullchain.pem",
            "key": f"{certPath}/privkey.pem",
            # "password": "for encrypted privkey file",   # Optional
        }
        app.prepare(host="0.0.0.0", port=port, ssl=certs, access_log=True, debug=False, fast=True)

        sanic.Sanic.serve(primary=app, app_loader=loader)
        #app.run(host="0.0.0.0", port=443, ssl=ssl, access_log=True, debug=False)
    else:
        app.prepare(host="0.0.0.0", port=port, access_log=True, debug=False, fast=True)
        sanic.Sanic.serve(primary=app, app_loader=loader)
        # app.run(host='0.0.0.0', port=port, access_log=True, debug=True, fast=True)
