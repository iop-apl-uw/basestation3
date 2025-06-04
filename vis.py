#!/usr/bin/env python3.10
## Copyright (c) 2023, 2024, 2025  University of Washington.
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

# ruff: noqa: SIM910
# ruff: noqa: UP012

import asyncio
import calendar
import os
import os.path
import random
import sys
import time
from io import BytesIO
from zipfile import ZipFile

import aiofiles
import aiohttp
import aiosqlite
import asyncudp
from anyio import Path
from json2html import json2html
from orjson import dumps, loads
from parse import parse

if "darwin" not in sys.platform:
    import asyncinotify
import base64
import getopt
import hashlib
import hmac
import pprint
import re
import secrets
import zlib
from functools import partial, wraps
from types import SimpleNamespace

import jwt
import sanic
import sanic_ext
import sanic_gzip
import yaml
import zmq
import zmq.asyncio
from passlib.hash import sha256_crypt
from sanic.worker.manager import WorkerManager

import BaseCtrlFiles

# import urllib.parse 
import BaseOpts
import capture
import ExtractTimeseries
import LogHTML
import Magcal
import parms
import pilot
import rafos
import RegressVBD
import scicon
import SelftestHTML
import summary
import Utils
import Utils2
import validate
import visauth


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
PERM_ADMIN  = 3

MODE_PUBLIC  = 0
MODE_PILOT   = 1
MODE_PRIVATE = 2

AUTH_ENDPOINT = 1
AUTH_MISSION  = 2 

AUTH_TYPE_NONE = 0
AUTH_TYPE_BASIC = 1
AUTH_TYPE_ADVANCED = 2

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
                       "orgname", "orglink", "contact", "email", "alert",
                       "project", "link", "comment", "reason"} 

# which modes need full comm.log stream vs just change notices

def getTokenUser(request):
    if request.app.config.SINGLE_MISSION:
        return (request.app.config.USER, False, False, False)

    if 'token' not in request.cookies:
        return (False, False, False, False)

    try:
         token = jwt.decode(request.cookies.get("token"), request.app.config.SECRET, algorithms=["HS256"])
    except jwt.exceptions.InvalidTokenError:
        return (False, False, False, False)

    if 'user' in token and 'groups' in token and 'domain' in token and 'type' in token:
        return (token['user'], token['groups'], token['domain'], token['type'])

    return (False, False, False, False)

# checks whether the auth token authorizes a user or group in users, groups
def checkToken(request, users, groups, pilots, pilotgroups, admins, admingroups):
    if 'token' not in request.cookies:
        sanic.log.logger.info('no token')
        return PERM_REJECT

    (tokenUser, tokenGroups, tokenDomain, tokenType) = getTokenUser(request)
    if not tokenUser:
        sanic.log.logger.info('no user')
        return PERM_REJECT

    if tokenDomain != request.ctx.ctx.domain:
        sanic.log.logger.info('domain mismatch')
        return PERM_REJECT

    perm = PERM_REJECT

    if users and tokenUser in users:
        sanic.log.logger.info(f"{tokenUser} authorized [{request.path}]")
        perm = PERM_VIEW
    elif groups and tokenGroups and len(set(groups) & set(tokenGroups)) > 0:
        sanic.log.logger.info(f"{tokenUser} authorized based on group [{request.path}]")
        perm = PERM_VIEW

    if pilots and tokenUser in pilots and tokenType >= request.app.config.PILOT_AUTH_TYPE:
        perm = PERM_PILOT
        sanic.log.logger.info(f"{tokenUser} authorized to pilot [{request.path}]")
    elif pilotgroups and tokenGroups and len(set(pilotgroups) & set(tokenGroups)) > 0 and tokenType >= request.app.config.PILOT_AUTH_TYPE:
        sanic.log.logger.info(f"{tokenUser} authorized to pilot based on group [{request.path}]")
        perm = PERM_PILOT

    if admins and tokenUser in admins and tokenType >= request.app.config.PILOT_AUTH_TYPE:
        sanic.log.logger.info(f"{tokenUser} authorized as admin [{request.path}]")
        perm = PERM_ADMIN
    elif admingroups and tokenGroups and len(set(admingroups) & set(tokenGroups)) > 0 and tokenType >= request.app.config.PILOT_AUTH_TYPE:
        sanic.log.logger.info(f"{tokenUser} authorized as admin based on group [{request.path}]")
        perm = PERM_ADMIN 

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

            grant = checkToken(request, m['users'], m['groups'], m['pilotusers'], m['pilotgroups'], None, None)
            if m['users'] is None and m['groups'] is None and grant < PERM_VIEW:
                grant = PERM_VIEW

            return grant
        else:
            return perm
    
    # no matching mission in table - do not allow access
    sanic.log.logger.info(f'rejecting {glider} {mission} for no mission entry')
    return PERM_INVALID

def checkEndpoint(request, e):

    if 'users' in e or 'groups' in e:
        (tU, tG, tD) = getTokenUser(request)
        allowAccess = False

        if tU and 'users' in e and e['users'] and tU in e['users']:  # noqa: SIM114
            allowAccess = True
        elif tG and 'groups' in e and e['groups'] and len(set(tG) & set(e['groups'])) > 0:
            allowAccess = True

        if not allowAccess:
            sanic.log.logger.info(f"rejecting {request.path}: user auth required")
            return PERM_REJECT # so we respond "auth failed"

    return PERM_VIEW # don't make a distinction view/pilot at this level

def authorized(modes=None, check=3, requireLevel=PERM_VIEW): # check=3 both endpoint and mission checks applied
    def decorator(f):
        @wraps(f)
        async def decorated_function(request, *args, **kwargs):
            nonlocal modes
            nonlocal check
            nonlocal requireLevel

            ws = kwargs.get('ws', None)

            # url = request.server_path[1:].split('/')[0]
            url = request.path[1:].split('/')[0]
            if check & AUTH_ENDPOINT and url in request.ctx.ctx.endpoints:
                e = request.ctx.ctx.endpoints[url]
                status = checkEndpoint(request, e)
                if status == PERM_REJECT:
                    return sanic.response.text("endpoint 1 authorization failed")

                else:
                    if 'allow' in e and e['allow']:
                        response = await f(request, *args, **kwargs)
                        return response
                    if 'modes' in e and e['modes'] is not None:
                        modes = e['modes']
                    if 'level' in e and e['level'] is not None:
                        requireLevel = e['level']
                        
            runningMode = modeNames[request.app.config.RUNMODE]

            if check & AUTH_MISSION:
                defaultPerm = PERM_VIEW

                # on an open pilot server (typically a non-public server running 443) 
                # we require positive authentication as a pilot against mission specified 
                # list of allowed pilots (and pilotgroups). Access to missions without 
                # pilots: and/or pilotgroups: specs will be denied for all. 
                glider = kwargs.get('glider', None)
                mission = request.args['mission'][0] if 'mission' in request.args else None

                m = matchMission(glider, request, mission)
                if m is not None and 'allow' in m and m['allow']:
                    # allow in a mission overrides everything else
                    response = await f(request, *args, **kwargs)
                    return response

                if m is not None and 'endpoints' in m and m['endpoints'] is not None and url in m['endpoints']:
                    e = m['endpoints'][url]
                    status = checkEndpoint(request, e)
                    if status == PERM_REJECT:
                        return sanic.response.text("endpoint 2 authorization failed")
                    else:
                        if 'allow' in e and e['allow']:
                            response = await f(request, *args, **kwargs)
                            return response
                        if 'modes' in e and e['modes'] is not None:
                            modes = e['modes']
                        if 'level' in e and e['level'] is not None:
                            requireLevel = e['level']
                    
                # modes now has final possible value - so check for pilot restricted API in public run mode
                if modes is not None and runningMode not in modes:
                    sanic.log.logger.info(f"rejecting {url}: mode not allowed")
                    return sanic.response.text(f"Page not found: {format(request.path)}", status=404)
                    
                # if we're running a private instance of a pilot server then we only require authentication
                # as a pilot if the pilots/pilotgroups spec is given (similar to how users always work)
                # so our default (no spec) is to grant pilot access
                if requireLevel >= PERM_PILOT and request.app.config.RUNMODE == MODE_PRIVATE:
                    defaultPerm = PERM_PILOT 
                
                # this will always fail and return not authorized if glider is None
                status = checkGliderMission(request, glider, mission, perm=defaultPerm)
                if status <= PERM_REJECT or (status < requireLevel):
                    sanic.log.logger.info(f"{url} authorization failed {status}, {requireLevel} {request.ip}")
                    if ws is not None:
                        sanic.log.logger.info("closing invalid stream")
                        await ws.send("invalid")
                        await ws.close()

                    if status == PERM_INVALID:
                        return sanic.response.text("not found")
                    else: 
                        return sanic.response.text("authorization failed")
            
            # the following two else blocks only apply in rare cases of !AUTH_MISSION
            elif modes is not None and runningMode not in modes:
                # do the public / pilot mode check for AUTH_ENDPOINT only mode
                sanic.log.logger.info(f"rejecting {url}: mode not allowed")
                return sanic.response.text(f"Page not found: {format(request.path)}", status=404)
            # this will reject everything if the user has no token, so specify requireLevel=0 for truly wide open access
            else:
                status = checkToken(request, request.ctx.ctx.users, request.ctx.ctx.groups,
                                    request.ctx.ctx.pilotusers, request.ctx.ctx.pilotgroups,
                                    request.ctx.ctx.admins, request.ctx.ctx.admingroups)
                if status < requireLevel:
                    sanic.log.logger.info(f"{request.ctx.ctx.users}")
                    sanic.log.logger.info(f"{request.ctx.ctx.groups}")
                    sanic.log.logger.info(f"{request.ctx.ctx.pilotusers}")
                    sanic.log.logger.info(f"{request.ctx.ctx.pilotgroups}")
                    sanic.log.logger.info(f"rejecting {url}: not allowed {status} {requireLevel}")
                    return sanic.response.text("authorization failed")

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
    x = next(filter(lambda d: d['glider'] == gld and d['status'] == 'active',  request.ctx.ctx.missionTable), None)
    return x
 
def matchMission(gld, request, mission=None):
    if gld is None:
        return None

    if mission is None and \
       request and \
       'mission' in request.args and \
       len(request.args['mission'][0]) > 0:

        mission = request.args['mission'][0]

    x = next(filter(lambda d: d['glider'] == int(gld) and d['mission'] == mission,  request.ctx.ctx.missionTable), None)
    if x:
        return x

    if mission:
        return None

    x = next(filter(lambda d: d['glider'] == int(gld) and d['default'], request.ctx.ctx.missionTable), None)
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
        cmdline_args = f"-c {cnf_file} -m {mission_dir}".split(),
        calling_module=module_name,
    )

    return base_opts


async def getLatestCall(request, glider, conn=None, limit=1, path=None):
    if conn is None:
        if path is None:
            dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        else:
            dbfile = f'{path}/sg{glider:03d}.db'
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

    if conn is None:
        Utils.logDB(f'getLatestCall close {glider}')
        await myconn.close()

    return row

async def getLatestFile(glider, request, which, dive=None):
    p = Path(gliderPath(glider,request))
    latest = -1
    call = -1
    filename = None
    fmt = 0

    rx = [ re.compile(which + r'\.(?P<dive>[0-9]{4})\.(?P<cycle>[0-9]{4}?$)'),
           re.compile(which + r'\.(?P<dive>[0-9][0-9]?[0-9]?[0-9]?)\.(?P<cycle>[0-9][0-9]?[0-9]?[0-9]?$)'),
           re.compile(which + r'\.(?P<dive>[0-9][0-9]?[0-9]?[0-9]?$)') ]

    if dive:
        globs = [f'{which}.{dive:04d}.*', f'{which}.{dive}.*', f'{which}.{dive}*' ]
        for i in range(3):
            async for fpath in p.glob(globs[i]):
                if (m := rx[i].match(fpath.name)) and 'cycle' in m.groupdict() and int(m.group("cycle")) > call:
                    latest = int(m.group("dive"))
                    call = int(m.group("cycle"))
                elif m and int(m.group("dive")) == dive and i == 2:
                    latest = int(m.group("dive"))
                    call = -1

            # if we found anything new format, or dive.cycle format it miust be later than .dive 
            # format so we can return
            if latest > -1 and call > -1:
                if i == 0:
                    filename = f'{gliderPath(glider,request)}/{which}.{latest:04d}.{call:04d}'
                else:
                    filename = f'{gliderPath(glider,request)}/{which}.{latest}.{call}'

                return (filename, latest, call)

        if latest > -1:
            filename = f'{gliderPath(glider,request)}/{which}.{latest}'

    
    else:
        globstr = f'{which}.*'
        async for fpath in p.glob(globstr):

            for i in range(3):
                if (m := rx[i].match(fpath.name)):
                    if 'cycle' in m.groupdict():
                        if int(m.group("dive")) > latest:
                            latest = int(m.group("dive"))
                            call   = int(m.group("cycle"))
                            fmt = i
                        elif int(m.group("dive")) == latest and int(m.group("cycle")) > call:
                            call = int(m.group("cycle"))
                            fmt = i
                    elif int(m.group("dive")) > latest:
                        latest = int(m.group("dive"))
                        call = -1
                        fmt = i



    if latest > -1 and call > -1:
        if fmt == 0:
            filename = f'{gliderPath(glider,request)}/{which}.{latest:04d}.{call:04d}'
        else:
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
    app.static('/robots.txt', f'{sys.path[0]}/html/robots.txt', name='robots')
    app.static('/script/images', f'{sys.path[0]}/scripts/images', name='script_images')
    app.static('/manifest.json', f'{sys.path[0]}/scripts/manifest.json', name='manifest')

    if os.path.exists(app.config.STATIC_FILE):
        with open(app.config.STATIC_FILE) as f:
            d = f.read()
            try:
                x = yaml.safe_load(d)
            except Exception as e:
                sanic.log.logger.info(f"static parse error {e}")
                x = {}
    else:
        x = {}

    for route in list(x.keys()):
        if 'route' in x[route] and 'path' in x[route]:
            if 'index' in x[route]:
                app.static(x[route]['route'], x[route]['path'], name=route, index=x[route]['index'])
            else:
                app.static(x[route]['route'], x[route]['path'], name=route)

    
    @app.exception(sanic.exceptions.NotFound)
    def pageNotFound(request, exception):
        return sanic.response.text(f"Page not found: {format(request.path)}", status=404)

    @app.post('/auth')
    # description: user authorization 
    # payload: (JSON) username, password, optional MFA code
    # returns: none on success (sets cookie with authorization token)
    async def authHandler(request):
        username = request.json.get("username", None).lower()
        password = request.json.get("password", None)
        code     = request.json.get("code", None)

        authed = False
        sanic.log.logger.info(f'authenticating {username}')
        for user,prop in request.ctx.ctx.userTable.items():
            if user.lower() == username:
                if 'password' in prop:
                    sanic.log.logger.info("checking basic auth")
                    if sha256_crypt.verify(password, prop['password']):
                        sanic.log.logger.info(f'{username} basic authorized')
                        response = sanic.response.json({'status': 'authorized', 'msg': 'authorizoration ok'})
                        tokenType = 1
                        authed = True
                    else:
                        response = sanic.response.json({'status': 'error', 'msg': 'authorization failed'})
                else:
                    sanic.log.logger.info("checking advanced auth")
                    status = visauth.authorizeUser(request.app.config.AUTH_DB, username, request.ctx.ctx.domain, password, code)
                    response = sanic.response.json(status)
                    sanic.log.logger.info(status)     
                    if status and 'status' in status and status['status'] == 'authorized':
                        sanic.log.logger.info(f'{username} adv authorized')
                        tokenType = 2
                        authed = True
                    else:
                        sanic.log.logger.info('auth failed')

                if authed:
                    sanic.log.logger.info(f"{username} groups={prop['groups']}, domain={request.ctx.ctx.domain}")
                    token = jwt.encode({"type": tokenType, "user": username, "groups": prop['groups'], "domain": request.ctx.ctx.domain}, request.app.config.SECRET)

                    response.add_cookie(
                        "token", token,
                        max_age=86400,
                        samesite="Strict",
                        httponly=True
                    )
                
                return response

        return sanic.response.json({'status': 'error', 'msg': 'auth error'})

    @app.route('/user')
    # description: checks whether current session user is valid
    # returns: YES is user is valid
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
    async def userHandler(request):
        (tU, tG, tD, tT) = getTokenUser(request)
        return sanic.response.text('logged in' if tU else 'not logged in')

    @app.get("/setup")
    @authorized(modes=['pilot'], check=0, requireLevel=0)
    async def setupHandler(request):
        if 'url' in request.args:
            url = request.args['url'][0]
        else:
            url = "/"
        return await sanic_ext.render("setup.html", context={"mode": "setup", "body": "Finish setting up your account", "url": url}, status=400)

    @app.get("/change")
    @authorized(modes=['pilot'], check=AUTH_ENDPOINT, requireLevel=PERM_PILOT)
    async def changeHandler(request):
        return await sanic_ext.render("setup.html", context={"mode": "password", "body": "Change your password now", "url": "/login"}, status=400)

    @app.get("/logout")
    async def logoutHandler(request):
        response = sanic.response.text("logged out")
        response.delete_cookie("token")
        return response

    @app.get("/login")
    async def loginHandler(request):
        if 'url' in request.args:
            url = request.args['url'][0]
        else:
            url = "/"

        return await sanic_ext.render("login.html", context={"mode": "login", "body": "Enter your login credentials", "url": url}, status=400)

    @app.post("/password")
    @authorized(modes=['pilot'], check=AUTH_ENDPOINT, requireLevel=PERM_PILOT)
    async def passwordHandler(request):
        username    = request.json.get("username", None).lower()
        curPassword = request.json.get("curPassword", None)
        newPassword = request.json.get("newPassword", None)
        code        = request.json.get("code", None)

        if username and curPassword and newPassword and code:
            status = visauth.authorizeUser(request.app.config.AUTH_DB, username, request.ctx.ctx.domain, curPassword, code, new_password=newPassword)
            return sanic.response.json(status)
        else:
            return sanic.response.json({'status': 'error', 'msg': 'error'})

    @app.post("/register")
    @authorized(modes=['pilot'], check=0, requireLevel=0)
    async def registerHandler(request):
        username    = request.json.get("username", None).lower()
        curPassword = request.json.get("curPassword", None)
        newPassword = request.json.get("newPassword", None)
        code        = request.json.get("code", None)

        if username and curPassword and newPassword and code:
            status = visauth.setupUser(request.app.config.AUTH_DB, username, request.ctx.ctx.domain, curPassword, code, newPassword)
            return sanic.response.json(status)
        else:
            return sanic.response.json({'status': 'error', 'msg': 'error'})
 
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
                    # mission = missionFromRequest(request)
                    # mission = f"?mission={mission}" if mission else ''
                    # wrap = '?wrap=page' if mission == '' else '&wrap=page'

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
    # parameters: mission, plot (starting plot), dive (starting dive), order (plot ribbon order), x,y,z,first,last,step,top,bottom,bin,wholemission|divetimeseries,dives|climbs|both|combine (plot tool values), op (contour,profiles,plot,table,csv), sectionNumber (sort order for section numbers ( normal, reverse)), sectionSort (major sort key for sections (number, name))
    # returns: HTML page
    @app.ext.template("vis.html")
    async def mainHandler(request, glider:int):
        runMode = request.app.config.RUNMODE
        if runMode == MODE_PRIVATE:
            runMode = MODE_PILOT

        return {"runMode": modeNames[runMode], "noSave": request.app.config.NO_SAVE, "noChat": request.app.config.NO_CHAT, "alert": request.app.config.ALERT}

    @app.route('/dash')
    # description: dashboard (engineering diagnostic) view of index (all missions) page
    # parameters: plot (which plot to include in tiles, default=diveplot), mission (comma separated list), glider (comma separated list), status, auth
    # returns: HTML page
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
    @app.ext.template("index.html")
    async def dashHandler(request):
        return {"runMode": "pilot"}

    @app.route('/')
    # description: "public" index (all missions) page
    # parameters: plot (which plot to include in tiles, default=map), mission (comma separated list), glider (comma separated list), status, auth
    # returns: HTML page
    @app.ext.template("index.html")
    async def indexHandler(request):
        return {"runMode": "public"}

    @app.route('/map/<glider:int>')
    # description: map tool
    # parameters: mission, tail (number of dives back to show in glider track), also (additional gliders to plot), sa (URL for SA to load), ais, ship, 
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

        if len(request.ctx.ctx.routes):
            message['routes'] = request.ctx.ctx.routes

        if len(request.ctx.ctx.sa):
            message['sa'] = request.ctx.ctx.sa

        a_dicts = []
        for a in request.ctx.ctx.assets:
            d = request.ctx.ctx.assets[a]
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
        if mission:
            message = {}
            for k in ['sa', 'kml']:
                if k in mission:
                    message[k] = mission[k]

            grouped = []
            also = []
            if 'also' in mission and mission['also'] is not None:
                for i in reversed(range(len(mission['also']))):
                    a = mission['also'][i]
                    if 'asset' in a and a['asset'] in request.ctx.ctx.assets and 'type' in request.ctx.ctx.assets[a['asset']] and request.ctx.ctx.assets[a['asset']]['type'] == 'group' and 'assets' in request.ctx.ctx.assets[a['asset']]:
                        for item in request.ctx.ctx.assets[a['asset']]['assets']:
                            grouped.append( { 'asset': item } )

                        mission['also'].pop(i)

                mission['also'].extend(grouped)
 
                for a in mission['also']:
                    if 'mission' not in a:
                        a.update( { 'mission': mission['mission'] } )
                    if 'asset' in a:
                        if a['asset'] in request.ctx.ctx.assets:
                            # don't copy the whole dict because maybe we have local
                            # overrides in this per mission version
                            for k in request.ctx.ctx.assets[a['asset']]:
                                if k not in a:
                                    a.update({ k: request.ctx.ctx.assets[a['asset']][k] })
                        else:
                            continue

                    also.append(a)

            if len(also):
                message['also'] = also

            if len(request.ctx.ctx.routes):
                message['routes'] = request.ctx.ctx.routes

            #if 'assets' in mission:
            #    a_dicts = []
            #    for a in mission['assets']:
            #        if a in request.ctx.ctx.assets.keys():       
            #            d = request.ctx.ctx.assets[a]
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

    @app.route('/project/<mission:str>/<url:path>')
    async def projectHandler(request, mission:str, url):
        x = next(filter(lambda d: d['project'] == mission, request.ctx.ctx.missionTable), None)
        if x:
            glider = x['glider']
            url = getRequestURL(request).replace('GGG', f'{glider:03d}').replace(f'/project/{mission}', '')
            return sanic.response.redirect(url)

        return sanic.response.text('none')
         
    @app.route('/csv/<glider:int>')
    # description: get CSV file from glider directory (supports assets type: csv on maps)
    # parameters: mission, file
    # returns: json array of data
    @authorized()
    async def csvHandler(request, glider:int):
        if 'file' not in request.args:
            return sanic.response.json({'error': 'no file'})
        
        filename = request.args['file'][0]
        if re.match(r'[^0-9A-Za-z_]', filename):
            return sanic.response.json({'error': 'invalid file'})

        fullname = f'{gliderPath(glider,request)}/{filename}.csv'
            
        x = []
        try:
            async with aiofiles.open(fullname, 'r') as file:
                async for line in file:
                    try:
                        x.append([float(y) for y in line.split(',')])
                    except Exception:
                        continue
        except Exception:
            return sanic.response.json({'error': 'invalid file'})
 
        return sanic.response.json({'data': x})
            
         
    @app.route('/kml/<glider:int>')
    # description: get glider KML
    # parameters: mission, network, kmz
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
            except Exception:
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

    @app.route('/iabp/<bid:int>')
    # description: fetch latest IABP buoy data
    # parameters: tail (days)
    # returns: JSON
    async def iabpHandler(request, bid:int):
        if 'tail' in request.args:
            tail = int(request.args['tail'][0])
        else:
            tail = 4

        url = 'https://iabp.apl.washington.edu/download?bid=' + str(bid) + '&ndays=' + str(tail + 1)

        async with aiohttp.ClientSession() as session: # noqa: SIM117
            async with session.get(url, ssl=False) as response:
                if response.status == 200:
                    body = await response.read()
                    try:
                        lines = body.splitlines()
                        cols = lines[0].split(b',')
                        BPcol = cols.index(b'BP') if b'BP' in cols else -1
                        Tacol = cols.index(b'Ta') if b'Ta' in cols else -1
                        Tscol = cols.index(b'Ts') if b'Ts' in cols else -1
                        latest = lines[-1].split(b',')
                        d = []
                        for line in lines[1:]:
                            x = line.split(b',')
                            if float(x[5]) > float(latest[5]) - tail - 1.0/48.0 and x[2] == latest[2]:
                                t = calendar.timegm((int(x[1]),1,1,0,0,0,0,0,0)) + (float(x[5]) - 1)*86400.0
                                m = {'t': t, 'lat': float(x[6]), 'lon': float(x[7])}
                                if BPcol > -1: 
                                    m.update({'BP': float(x[BPcol])})
                                if Tacol > -1: 
                                    m.update({'Ta': float(x[Tacol])})
                                if Tscol > -1: 
                                    m.update({'Ts': float(x[Tscol])})
                                
                                d.append(m)

                        return sanic.response.json(d)
                    except Exception as e:
                        return sanic.response.json({'error': f'error {e}'})

            
     
    # returns: 
    @app.post('/post')
    # description: post version of proxy request handler for map tool
    # returns: contents from requested URL
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
    async def postHandler(request):
        allowed = [
                   'https://realtime.sikuliaq.alaska.edu/realtime/map',
                   'https://iopbase3.apl.washington.edu/pos/poll',
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

        if not found:
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
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
    async def proxyHandler(request, url):
        allowed = ['https://api.opentopodata.org/v1/gebco2020',
                   'https://marine.weather.gov/MapClick.php',
                   'https://iop.apl.washington.edu/', 
                   'https://usicecenter.gov/File/DownloadCurrent',
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

        if not found:
            return sanic.response.text(f"Page not found: {request.path}", status=404)
              
        if request.args and len(request.args) > 0:
            url = url + '?' + request.query_string

        async with aiohttp.ClientSession() as session:
            try:
                async with session.get(url) as response:
                    if response.status == 200:
                        body = await response.read()
                        return sanic.response.raw(body)
            except Exception:
                return sanic.response.html('empty')
        
    @app.route('/proxykmz/<url:path>')
    # description: proxy and unzip network KMZ sources
    # returns: KML from KMZ downloaded from requested URL
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
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

        if not found:
            return sanic.response.text(f"Page not found: {request.path}", status=404)

        kmz = None
              
        if request.args and len(request.args) > 0:
            url = url + '?' + request.query_string
        try:
            async with aiohttp.ClientSession() as session: # noqa: SIM117
                async with session.get(url) as response:
                    if response.status == 200:
                        kmz = await response.read()
        except Exception:
            pass

        if kmz is None:
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

        if nm is None:
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
                 and 'Password:]' not in line \
                 and 'no password: prompt' not in line \
                 and 'no shell prompt' not in line:
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
                (x, crits) = await capture.formatCaptureFile(filename, firstPlot=True)
                out = purgeSensitive(x)
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
                    elif line in ['\n', '\r\n'] and trace:
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
        msg = { "missions": table, "organization": request.ctx.ctx.organization }
        return sanic.response.json(msg)
    
    @app.route('/admin')
    @app.ext.template("admin.html")
    async def adminHandler(request):
        return {} 

    @app.route('/admin/data')
    @authorized(check=AUTH_ENDPOINT, modes=['private', 'pilot'], requireLevel=PERM_ADMIN)
    async def adminDataHandler(request):
        fields = {"glider",  "mission", "status", "path",
                  "started", "ended",   "planned",
                  "project", "comment", "reason"} 
        x = []
        for m in request.ctx.ctx.missionTable:
            dbfile = f"{m['path']}/sg{m['glider']:03d}.db"
            y = { "first": None, "last": None, "dives": None, "dog": None }             
            if await Path(dbfile).exists():
                async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
                    conn.row_factory = rowToDict
                    cur = await conn.cursor()
                    try:
                        await cur.execute("SELECT dive,log_start,distance_over_ground FROM dives ORDER BY dive ASC")
                        r = await cur.fetchall()
                        if r and len(r) >= 1:
                            dog = sum([ (z['distance_over_ground'] if z['distance_over_ground'] else 0) for z in r])
                            y = { "first": r[0]['log_start'], "last": r[-1]['log_start'], "dives": r[-1]['dive'], "dog": dog }             
                    except Exception as e:
                        sanic.log.logger.info(f"exception {e}, {m['glider']}, {m['mission']}")
                        pass

                await checkClose(conn)

            y.update({ k: m[k] for k in m.keys() & fields })
            x.append(y)
        return sanic.response.json(x)

    @app.route('/summary/<glider:int>')
    # description: summary status of glider
    # parameters: mission
    # returns: JSON formatted dict of glider engineering status variables
    @authorized()
    async def summaryHandler(request, glider:int):
        msg = await summary.collectSummary(glider, gliderPath(glider,request))
        # if not 'humidity' in msg:
        # use comm.log values to overwrite log file values where available
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
                msg['sm_pitch']   = call[0]['pitch']
                msg['sm_depth']   = call[0]['depth']
            except Exception as e:
                sanic.log.logger.info(f"summaryHandler: {e} {call[0]}")
                    
        msg['mission'] = filterMission(glider, request)
        return sanic.response.json(msg)

    @app.route('/parmdata/<glider:int>/<dive:int>')
    @authorized()
    async def parmdataHandler(request, glider:int, dive:int):
        logfile = f'{gliderPath(glider, request)}/p{glider:03d}{dive:04d}.log'
        cmdfile = f'{gliderPath(glider, request)}/cmdfile'
        dbfile = f'{gliderPath(glider, request)}/sg{glider:03d}.db'
        try:
            o = await parms.state(None, logfile=logfile, cmdfile=cmdfile, dbfile=dbfile)
        except Exception as e:
            print(e)
            return sanic.response.json({'error': f'no parms {e}'})
        else:
            return sanic.response.json(o)

    @app.route('/grep/<glider:int>/<file:str>/<dives:str>/<dive1:int>/<diveN:int>/<search:str>')
    @authorized()
    async def grepHandler(request, glider:int, file:str, dives:str, dive1:int, diveN:int, search:str):
        if file not in ['comm', 'log', 'eng', 'cap', 'pdoslog', 'pdosbat', 'cmdfile', 'baselog']:
            return sanic.response.text('invalid file')
        if dives not in ['selftest', 'all', 'range']:
            return sanic.response.text('invalid dives')

        showfile = 'showfile' in request.args
        showdive = 'showdive' in request.args

        if file == 'comm':
            files = [ f'{gliderPath(glider, request)}/comm.log' ]
        elif file == 'baselog':
            files = [ f'{gliderPath(glider, request)}/baselog.log' ]
        else:
            p = Path(gliderPath(glider, request))
            files = []
            if dives == 'selftest':
                pref = "pt"
            else:
                pref = "p"

            if file == 'pdoslog':
                glob = f"{pref}{glider:03d}????.*.pdos"
            elif file == 'cmdfile': 
                glob = "cmdfile.*.*"
            elif file == 'pdosbat':
                glob = "pdoscmds.bat.*.*"
            else:
                glob = f"{pref}{glider:03d}????.{file}"

            async for fpath in p.glob(glob):
                files.append(fpath)
              
            # files = sorted(files)

        if file in ['log', 'eng', 'cap']:
            pattern = re.compile(r'p(?P<glider>[0-9]{3})(?P<dive>[0-9]{4})\.[a-z]{3}')
        elif file == 'pdoslog':
            pattern = re.compile(r'p(?P<glider>[0-9]{3})(?P<dive>[0-9]{4})\.(?P<cycle>[0-9]{3})\.pdos')
        elif file == 'cmdfile':
            pattern = re.compile(r'cmdfile\.(?P<dive>[0-9]+).(?P<cycle>[0-9]+)')
        elif file == 'pdosbat':
            pattern = re.compile(r'pdoscmds\.bat\.(?P<dive>[0-9]+).(?P<cycle>[0-9]+)')
        else:
            pattern = None
 
        out = []
        for f in files:
            dv = None
            cy = None
            if pattern is not None:
                m = pattern.search(os.path.basename(f))    
                if m:
                    dv = int(m.group("dive"))
                    if dives == 'range' and (dv < dive1 or dv > diveN):
                        continue
                    if 'cycle' in m.groupdict():
                        cy = int(m.group("cycle"))

            async with aiofiles.open(f, 'r') as file:

                async for line in file:
                    add = ''
                    if search in line:
                        if showdive and dv is not None:
                            add = add + f"{dv:04d} "
                            if cy is not None:
                                add = add + f"{cy:04d} "
                        if showfile:
                            add = add + f"{os.path.basename(f)}: "

                        add = add + line.strip()
                        out.append(add)

        if len(files) > 1:
            out = sorted(out)
   
        return sanic.response.text("\n".join(out)) 
                     
    @app.route('/recs/<glider:int>')
    # description: pilot recommendations
    # parameters: mission
    # returns: JSON formatted dict of recommendations for centers
    @authorized()
    async def recsHandler(request, glider:int):
        p = f'{gliderPath(glider,request)}'
        (pitch, roll, vbd) = await pilot.pilotRecs(p, glider)
        x = { 'pitch': pitch, 'roll': roll, 'vbd': vbd }
        return sanic.response.json(x)
 
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
                except Exception:
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
        message['organization'] = request.ctx.ctx.organization
        
        message['mission'] = filterMission(glider, request) 
        return sanic.response.json(message)

    @app.route('/editlog/<glider:int>/<which:str>')
    # description: glider control files
    # parameters: mission
    # returns: latest cmdedit.log
    @authorized(modes=['private', 'pilot'], requireLevel=PERM_PILOT)
    async def cmdeditHandler(request, glider:int, which:str):
        if which not in [ 'cmdedit', 'sciedit', 'targedit' ]:
            return sanic.response.text('none')

        message = { 'file': f'{which}.log' }
        filename = f'{gliderPath(glider,request)}/{which}.log'

        if await aiofiles.os.path.exists(filename):
            async with aiofiles.open(filename, 'r') as file:
                message.update( { 'contents': await file.read() })
        else:
            message.update( { 'contents': '' } )
        
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

        if await aiofiles.os.path.exists(filename):
            async with aiofiles.open(filename, 'r') as file:
                message['contents']= await file.read() 

            if which == 'targets':
                message['data'] = await Utils.readTargetsFile(filename)
            elif which == 'science':
                message['data'] = await Utils.readScienceFile(filename)
        else:
            message['contents'] = ''
        
        return sanic.response.json(message)

    @app.route('/sources')
    @authorized(check=AUTH_ENDPOINT, requireLevel=0)
    async def sourcesHandler(request):
        
        if 'format' in request.args:
            format = request.args['format'][0]
        else:
            format = 'json'

        srcdb = f'{sys.path[0]}/data/sources.json'
        if not await aiofiles.os.path.exists(srcdb):
            return sanic.response.json({ 'error': 'no data' })

        async with aiofiles.open(srcdb, 'r') as file:
            d = loads(await file.read())

        if format == 'json':
            return sanic.response.json(d)
        else:
            return sanic.response.html(json2html.convert(json=d)) 

             
    @app.route('/rafos/<glider:int>')
    @authorized()
    async def rafosHandler(request, glider:int):
        path = gliderPath(glider, request)
        hits  = await rafos.hitsTable(path)
        out = ExtractTimeseries.dumps(hits) # need custom serializer for the numpy array

        if 'format' in request.args:
            format = request.args['format'][0]
        else:
            format = 'json'

        if format == 'json':
            return sanic.response.raw(out, headers={ 'Content-type': 'application/json' })
        else:
            return sanic.response.html(rafos.toHTML(hits))

    @app.route('/magcal/<glider:int>/<dives:str>')
    # description: run magcal over multiple dives
    # parameters: mission, ballast
    # returns: html of plotly results plot
    @authorized()
    async def magcalHandler(request, glider:int, dives:str):
        path = gliderPath(glider, request)

        softiron = 'softiron' in request.args
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

        ballast = 'ballast' in request.args
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

        html = "<style>@media print { .pagebreak { page-break-before: always; } }</style>\n<html>\n"
        html = html + "\n<div class=\"pagebreak\"></div>\n".join(plt)
        html = html + "\n</html>"
        return sanic.response.html(html)
    
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
        ncfilename = Utils2.get_mission_timeseries_name(None, gliderPath(glider,request))
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
        ncfilename = Utils2.get_mission_timeseries_name(None, gliderPath(glider,request))
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
        ncfilename = Utils2.get_mission_timeseries_name(None, gliderPath(glider,request))
        if not await aiofiles.os.path.exists(ncfilename):
            return sanic.response.json({'error': 'no db'})

        whichVars = which.split(',')
        dbVars = whichVars
        if 'time' in dbVars:
            dbVars.remove('time')

        data = ExtractTimeseries.extractVars(ncfilename, dbVars, dive if dive > 0 else 1, dive if dive > 0 else 100000)
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
            except Exception:
                Utils.logDB(f'query close (except) {glider}')
                return sanic.response.json({'error': 'db error'})

            d = await cur.fetchall()
            if format == 'json':
                data = {}
                for i in range(len(cur.description)):
                    data[cur.description[i][0]] = [ f[i] for f in d ]

                Utils.logDB(f'query close (return) {glider}')
                return sanic.response.json(data)
            else:
                txt = ''
                for f in d:
                    txt = txt + str(f).strip('()') + "\n"

                Utils.logDB(f'query close (else) {glider}')
                return sanic.response.text(txt)
                

    @app.route('/selftest/<glider:int>')
    # description: selftest review
    # parameters: mission, num
    # returns: HTML format summary of latest selftest results
    async def selftestHandler(request, glider:int):
        table = await buildAuthTable(request, None, glider=glider, mission=None, includePath=True)
        num = int(request.args['num'][0]) if 'num' in request.args else 0
        canon = request.args['canon'][0] if 'canon' in request.args else None
        html = await SelftestHTML.html(glider, gliderPath(glider, request), num, mission=missionFromRequest(request), missions=table, canon=canon)
        return sanic.response.html(purgeSensitive(html))

    #
    # POST handler - to save files back to basestation
    #

    # first the safety function
    def applyControls(c, text, filename):
        forbidden = ['shutdown', 'scuttle', 'wipe', 'reboot', 'pdos', 'del', 'rm', 'EXIT_TO_MENU']
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
                            break
                    if status:
                        for a in a2:
                            if a.search(line):
                                sanic.log.logger.info(f"{filename} allow {line} ({d})")
                                status = False
                                break

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
        if 'glider' not in res:
            return sanic.response.text('no')

        try:
            bo = baseOpts(glider, gliderPath(glider, request), 'BaseCtrlFiles')
        except Exception:
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
    @authorized(modes=['private', 'pilot'], requireLevel=PERM_PILOT)
    async def saveHandler(request, glider:int, which:str):
        # the no save command line flag allows one more layer
        # of protection
        if request.app.config.NO_SAVE:
            return sanic.response.text('not allowed')

        ok = ["cmdfile", "targets", "science", "scicon.sch", "tcm2mat.cal", "pdoscmds.bat", "sg_calib_constants.m"]

        logs = { "cmdfile": "cmdedit.log", "targets": "targedit.log", "science": "sciedit.log" }

        if which not in ok:
            return sanic.response.text("not allowed")

        message = request.json
        if 'file' not in message or message['file'] != which or 'contents' not in message:
            return sanic.response.text('oops')

        if applyControls(request.ctx.ctx.controls, message['contents'], which):
            return sanic.response.text('not allowed')

        expiry = message['expiry']
        if time.time() > int(expiry):
            return sanic.response.text('validation expired')

        salt = message['salt']
        sigProvided = message['signature']

        sigComputed = hmac.new((salt + expiry + request.app.config.VALIDATE_SECRET).encode('ascii'), 
                               (salt + expiry + message['contents']).encode('ascii'), 'md5').hexdigest()

        if not hmac.compare_digest(sigComputed, sigProvided):
            return sanic.response.text('validation not valid')

        if which in [ "cmdfile", "science", "targets", "scicon.sch" ]:
            if which.startswith("scicon"):
                (d, _, _, _) = await scicon.state(gliderPath(glider, request))
            else:
                dbfile = f'{gliderPath(glider, request)}/sg{glider:03d}.db'
                d = await parms.state(None, dbfile=dbfile)

            (res, err, warn) = validate.validate(which, message['contents'], parms=d)
        else:
            res = [ 'no validator available for this file type, new file automatically accepted' ]
            err = 0

        if err == 0:
            try:
                async with aiofiles.open(f'{gliderPath(glider, request)}/{which}', 'w') as file:
                    await file.write(message['contents'])

                res.append(f"{which} saved ok")

                (tU, _, _, _) = getTokenUser(request)
                date = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(time.time()))
                size = len(message['contents'])
                checksum = zlib.crc32(message['contents'].encode('utf-8'))

                logname = logs.get(which, 'pilot.log')

                async with aiofiles.open(f'{gliderPath(glider, request)}/{logname}', 'a') as log:
                    await log.write(f"\n### {tU} () {date}\n")
                    await log.write(f"+++ {which} ({size} bytes, {checksum} checksum)\n")
                    await log.write(message['contents'])
                    await log.write('\n'.join(res))

            except Exception as e:
                res.append(f"error saving {which}, {str(e)}")

        return sanic.response.text('\n'.join(res))


    @app.post('/validate/<glider:int>/<which:str>')
    # description: validate glider control file
    # args: which=cmdfile|targets|science|scicon.sch|tcm2mat.cal|pdoscmds.bat|sg_calib_constants.m
    # payload: (JSON) file, contents
    # parameters: mission
    # returns: validator results and/or error message  
    @authorized(modes=['private', 'pilot'])
    async def validateHandler(request, glider:int, which:str):

        ok = ["cmdfile", "targets", "science", 
              "scicon.sch", "tcm2mat.cal", "pdoscmds.bat", "sg_calib_constants.m"]

        if which not in ok:
            return sanic.response.text("not allowed")

        message = request.json
        if 'file' not in message or message['file'] != which or 'contents' not in message:
            return sanic.response.text('oops')

        if which in [ "cmdfile", "science", "targets", "scicon.sch" ]:
            if which.startswith("scicon"):
                (d, _, _, _) = await scicon.state(gliderPath(glider, request))
            else:
                dbfile = f'{gliderPath(glider, request)}/sg{glider:03d}.db'
                d = await parms.state(None, dbfile=dbfile)

            (res, err, warn) = validate.validate(which, message['contents'], parms=d)
        else:
            res = [ 'no validator available for this file type, new file automatically accepted' ]
            err = 0

        if err == 0:
            salt = f'{random.getrandbits(32):08x}'
            expiry = f'{int(time.time()) + 60}'
            signature = hmac.new((salt + expiry + request.app.config.VALIDATE_SECRET).encode('ascii'), 
                                 (salt + expiry + message['contents']).encode('ascii'), 'md5').hexdigest()
        
            msg = { 'results': '\n'.join(res), 'status': 'ok', 'salt': salt, 'signature': signature, 'expiry': expiry }
        else:
            msg = { 'results': '\n'.join(res), 'status': 'error' }

        return sanic.response.json(msg)


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

        synccmd = f'{gliderPath(glider,request)}/.vissync'
        if await aiofiles.os.path.exists(synccmd):
            proc = await asyncio.create_subprocess_shell(
                            synccmd,
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE
                        )
            out, err = await proc.communicate()

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
        except Exception:
            return sanic.response.text('error')
     
        return sanic.response.text('ok')

    async def getChatMessages(request, glider, t, conn=None):
        if conn is None:
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

        if conn is None:
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

        (tU, _, _, _) = getTokenUser(request)
        if not tU:
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
        (tU, _, _, _) = getTokenUser(request)
        if not tU:
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
                    q = "INSERT INTO chat(timestamp, user, message, attachment, mime) VALUES(?, ?, ?, ?, ?)"
                    values = (now, tU, msg, attach.body, attach.type)
                else:
                    q = "INSERT INTO chat(timestamp, user, message) VALUES(?, ?, ?)"
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

    @app.route('/missionsa/<glider:int>')
    # description: fetch mission SA file
    # parameters: mission
    # returns: json mission SA
    @authorized()
    async def missionsaHandler(request, glider:int):
        mission = matchMission(glider, request) 
        if 'sadata' not in mission:
            return sanic.response.json({'error': 'no data'})
        
        assets = []
        if await aiofiles.os.path.exists(mission['sadata']):
            async with aiofiles.open(mission['sadata'], 'r') as file:
                async for line in file:
                    try:
                        pieces = line.split(' ')
                        if len(pieces) >= 11:
                            lat = float(pieces[4]) + float(pieces[5])/60
                            if pieces[6] == 'S':
                                lat = -lat
                            lon = float(pieces[7]) + float(pieces[8])/60
                            if pieces[9] == 'W':
                                lon = -lon

                            assets.append( { 'class': pieces[0],
                                             'id': pieces[1],
                                             'date': pieces[2],
                                             'time': pieces[3],
                                             'lat': lat,
                                             'lon': lon,
                                             'subcat': int(pieces[10]),
                                           })
                    except Exception:
                        continue
            
        return sanic.response.json(assets)
 
    @app.route('/pos/sa/<glider:int>')
    # description: fetch SA position file
    # parameters: mission, t (signals send only if there is data newer than t), latest (signals send only positions newer than t)
    # returns: SA positions file
    @authorized()
    async def posSAHandler(request, glider:int):
        if 't' in request.args:
            try:
                newer_t = int(request.args['t'][0])
            except Exception:
                newer_t = 0
        else:
            newer_t = 0

        if 'recent' in request.args:
            recent = True
        else:
            recent = False
 
        filename = f'{gliderPath(glider, request)}/SG_{glider:03d}_positions.txt'
        if not recent and await aiofiles.os.path.exists(filename):
            if await aiofiles.os.path.getmtime(filename) > newer_t:
                return await sanic.response.file(filename, mime_type='text/plain')
            else:
                return sanic.response.text('nothing new')

        dbfile = f'{gliderPath(glider,request)}/sg{glider:03d}.db'
        async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
            try:
                conn.row_factory = rowToDict
                cur = await conn.cursor()
                if recent and newer_t > 0:
                    q = f"SELECT epoch,lat,lon FROM calls WHERE epoch > {newer_t} ORDER BY epoch ASC;"
                else: # we might need all of them
                    q = "SELECT epoch,lat,lon FROM calls ORDER BY epoch ASC;"
                await cur.execute(q)
                rows = await cur.fetchall()
    
                if not rows or len(rows) == 0 or (newer_t > rows[-1]['epoch']):
                    return sanic.response.text('nothing new')

                lines = []
                for r in rows:
                    line = f"{time.strftime('%Y-%m-%dT%H:%M:%SZ',time.gmtime(r['epoch']))},{r['lat']:.7f},{r['lon']:.7f},0"
                    lines.append(line)

                return sanic.response.text('\n'.join(lines))
            except Exception as e:
                return sanic.response.text(f'error {e}')

    @app.route('/pos/poll/<glider:str>')
    # description: get latest glider position
    # parameters: mission, format
    # returns: JSON dict of glider position
    async def posPollHandler(request: sanic.Request, glider:str):
        if ',' in glider:
            try:
                gliders = map(int, glider.split(','))
            except Exception:
                return sanic.response.json({'error': 'invalid'})
        else:
            try:
                gliders = [ int(glider) ]
            except Exception:
                return sanic.response.json({'error': 'invalid'})

        opTable = await buildAuthTable(request, None)


        if 'format' in request.args:
            format = request.args['format'][0]
        else:
            format = 'json'

        if 't' in request.args and len(request.args['t'][0]) > 0:
            try:
                t = int(request.args['t'][0])
            except ValueError:
                q = "SELECT * FROM calls ORDER BY epoch DESC LIMIT 1;"
            else:
                q = f"SELECT * FROM calls WHERE epoch > {t} ORDER BY epoch DESC LIMIT 1;"
        else:
            q = "SELECT * FROM calls ORDER BY epoch DESC LIMIT 1;"
                
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

        await ws.send("START") # send something to ack the connection opened

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
            except Exception:
                pass
        else:
            await ws.send('no comm.log\n')

        (tU, _, _, _) = getTokenUser(request)
        
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
                elif 'urls' in topic or 'proc-' in topic:
                    msg = loads(body)
                    msg.update({ "what": topic })
                    await ws.send(f"NEW={dumps(msg).decode('utf-8')}")
                elif 'file' in topic and request.app.config.RUNMODE > MODE_PUBLIC and 'km' not in topic:
                    m = loads(body) 
                    async with aiofiles.open(m['full'], 'rb') as file:
                        Utils.logDB(f'stream 3 open {glider}')
                        body = (await file.read()).decode('utf-8', errors='ignore')
                        m.update( { "body": body } )
                        if m['file'] == 'science':
                            m.update( { "data": await Utils.readScienceFile(m['full']) } )
                        elif m['file'] == 'targets':
                            m.update( { "data": await Utils.readTargetsFile(m['full']) } )
                        #elif m['file'] == 'cmdfile':
                        #    m.update( { "data": await parms.cmdfile(gliderPath(glider, request), 'cmdfile') } )
            
                        await ws.send(f"FILE={dumps(m).decode('utf-8')}")

                    Utils.logDB(f'stream 3 close {glider}')
                elif 'file-cmdfile' in topic:
                    cmdfilename = os.path.join(gliderPath(glider, request), 'cmdfile')
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
        await ws.send("START") # send something to ack the connection opened

        zsock = zmq.asyncio.Context().socket(zmq.SUB)
        zsock.setsockopt(zmq.LINGER, 0)
        zsock.connect(request.app.config.WATCH_IPC)
        zsock.setsockopt(zmq.SUBSCRIBE, b'')

        while True:
            try:
                msg = await zsock.recv_multipart()
                topic = msg[0].decode('utf-8')
                body  = msg[1].decode('utf-8')
               
                if '-chart-' in topic: 
                    await ws.send(body)
                elif '-urls-gpsstr' in topic or '-files' in topic:  
                    out = loads(body)
                    if ('glider' not in out) :
                        out.update( { 'glider': int(topic[0:3]) } )

                    if ('mission' not in out):
                        mission = activeMission(out['glider'], request)
                        out.update( { 'mission': mission['mission'] if mission else '' } )

                    await ws.send(f"{dumps(out).decode('utf-8')}")

            except BaseException as e: # websockets.exceptions.ConnectionClosed:
                sanic.log.logger.info(f'watch ws connection closed {e}')
                zsock.close()
                await ws.close()
                return

    @app.route('/image/<glider:int>/<name:str>/<fmt:str>')
    # description: download map overlay image
    async def imageHandler(request, glider:int, name:str, fmt: str):
        if re.match(r'[^0-9A-Za-z_]', name):
            return sanic.response.text('invalid')
        if fmt not in ['png', 'jpg']:
            return sanic.response.text('invalid')

        filename = f'{gliderPath(glider,request)}/images/{name}.{fmt}'
        if await aiofiles.os.path.exists(path):
            return await sanic.response.file(filename, mime_type=f"image/{fmt}")
        else:
            return sanic.response.text('not found', status=404)
         
    @app.route('/tile/<path:str>/<z:int>/<x:int>/<y:int>')
    # description: download map tile
    async def tileHandler(request, path:str, z:int, x:int, y:int):
        if re.match(r'[^0-9A-Za-z_]', path):
            return sanic.response.text('invalid')

        path = f'{sys.path[0]}/tiles/{path}/{z}/{x}/{y}.png'

        if await aiofiles.os.path.exists(path):
            return await sanic.response.file(path, mime_type='image/png')
        else:
            return sanic.response.text('not found', status=404)

    @app.route('/tile/asset/<path:str>/<z:int>/<x:int>/<y:int>')
    async def tileSetHandler(request, path:str, z:int, x:int, y:int):
        if re.match(r'[^0-9A-Za-z_]', path):
            return sanic.response.text('invalid')

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
        await ws.send("START") # send something to ack the connection opened

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

                if gliders and glider not in gliders:
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
                elif 'urls' in topic or 'proc-' in topic:
                    try:
                        msg = loads(body)
                        msg.update({ "what": topic })
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

        if hasattr(request.app.ctx, 'domains'):
            domain = request.headers.host.split('.')[0]
            if  domain in request.app.ctx.domains:
                request.ctx.ctx = request.app.ctx.domains[domain]
                return None

            domain = request.path[1:].split('/')[0]
            if domain in request.app.ctx.domains:
                newURL = getRequestURL(request).rstrip('/').replace(f'/{domain}', '').replace('//', '//' + domain + '.')
                return sanic.response.redirect(newURL)
    
            if not request.app.ctx.rootdomain or request.headers.host.split(':')[0] != request.app.ctx.rootdomain:
                print(request.app.ctx.rootdomain)
                print(request.headers.host)
                return sanic.response.text('Not Found', status=502)
                 
        request.ctx.ctx = request.app.ctx
 
        return None


#
#  setup / config file readers
#

async def buildUserTable(app, config=None):
    if config is None:
        config = app.config

    if await aiofiles.os.path.exists(config.USERS_FILE):
        async with aiofiles.open(config.USERS_FILE, "r") as f:
            d = await f.read()
            try:
                x = yaml.safe_load(d)
            except Exception as e:
                sanic.log.logger.info(f"users parse error {e}")
                x = {}
    else:
        sanic.log.logger.info(f'{config.USERS_FILE} does not exist')
        x = {}

    userDictKeys = [ "groups" ] # password is optional - if not spec'd user is in auth.db

    dflts = None
    for user in list(x.keys()):
        if user == 'default':
            dflts = x[user]
            del x[user]
            continue
        
        for uk in userDictKeys:
            if uk not in x[user]:
                x[user].update( { uk: dflts[uk] if dflts and uk in dflts else None } )

    if app:
        app.ctx.userTable = x

    return x

async def buildMissionTable(app, config=None):
    if config is None:
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
                    if not (x := yaml.safe_load(d)):
                        print('could not read yaml')
                        x = {}
                except Exception as e:
                    sanic.log.logger.info(f"mission file parse error {e}")
                    x = {}
        else:
            sanic.log.logger.info(f"{config['MISSIONS_FILE']} does not exist")
            x = {}

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
    if 'missiondefaults' not in x:
        x['missiondefaults'] = {}
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
    if 'sa' not in x: # toplevel sa for bare map
        x['sa'] = []
    if 'domain' not in x:
        x['domain'] = None
    if 'admins' not in x:
        x['admins'] = None
    if 'admingroups' not in x:
        x['admingroups'] = None
    if 'users' not in x:
        x['users'] = None       # not currently used, but allows blocking non-mission specific endpoints except to global users
    if 'groups' not in x:
        x['groups'] = None
    if 'pilotusers' not in x:
        x['pilotusers'] = None
    if 'pilotgroups' not in x:
        x['pilotgroups'] = None
    if 'autocomplete' not in x:
        x['autocomplete'] = 0

    if 'domains' in x:
        ikey = 'domains'
    elif 'includes' in x:
        ikey = 'includes'
    else:
        ikey = None

    if 'authdomain' not in x:
        x['authdomain'] = None

    domains = {}
    if ikey:
        missionTable = []
        if ikey == 'domains':
            rootdomain = None

        for domain in list(x[ikey].keys()):
            if domain == 'root':
                rootdomain = x[ikey][domain]
                continue

            mfile = x[ikey][domain]['missions']
            try:
                (tbl, xx, _) = await buildMissionTable(None, config={'MISSIONS_FILE': mfile, 'RUNMODE': config['RUNMODE']})
            except Exception:
                continue

            for k in tbl:
                if 'path' in k and k['path']:
                    k['path'] = x[ikey][domain]['root'] + '/' + k['path']
                else:
                    k['path'] = x[ikey][domain]['root'] + f"/sg{k['glider']:03d}"

            if ikey == 'domains':
                if 'users' in x[ikey][domain]:
                    ufile = x[ikey][domain]['users']
                    try:
                        userTbl = await buildUserTable(None, config=SimpleNamespace(USERS_FILE=ufile))
                        sanic.log.logger.info(f'building user table {domain}')
                        sanic.log.logger.info(userTbl)
                    except Exception as e:
                        sanic.log.logger.info(f'could not build user table {e}')
                        userTbl = {}
                else:
                    sanic.log.logger.info(f'no user file for {domain}')
                    ufile = None
                    userTbl = {}

                domains[domain] = SimpleNamespace( missionTable=tbl,
                                                   domain=domain,
                                                   userTable=userTbl,
                                                   organization=xx['organization'],
                                                   endpoints=xx['endpoints'],
                                                   controls=xx['controls'],
                                                   assets=xx['assets'],
                                                   routes=xx['routes'],
                                                   users=xx['users'],
                                                   groups=xx['groups'],
                                                   admins=xx['admins'],
                                                   admingroups=xx['admingroups'],
                                                   pilotusers=xx['pilotusers'],
                                                   pilotgroups=xx['pilotgroups'],
                                                   autocomplete=xx['autocomplete'],
                                                   missionsFile=mfile,
                                                   usersFile=ufile )

            missionTable = missionTable + tbl

        if app:
            if ikey == 'domains':
                app.ctx.domains = domains
                app.ctx.rootdomain = rootdomain

            app.ctx.missionTable = missionTable
            app.ctx.organization = x['organization']
            app.ctx.endpoints    = x['endpoints']
            app.ctx.controls     = x['controls']
            app.ctx.assets       = x['assets']
            app.ctx.routes       = x['routes']
            app.ctx.admins      = x['admins']
            app.ctx.admingroups = x['admingroups']
            app.ctx.pilotusers  = x['pilotusers']
            app.ctx.pilotgroups = x['pilotgroups']
            app.ctx.users       = x['users']
            app.ctx.groups      = x['groups']
            app.ctx.sa          = x['sa']
            app.ctx.autocomplete = x['autocomplete']
            app.ctx.missionsFile = config['MISSIONS_FILE']
            app.ctx.usersFile = config['USERS_FILE']

        return (missionTable, None, domains)
     
    orgDictKeys = ["orgname", "orglink", "text", "contact", "email"]
    for ok in orgDictKeys:
        if ok not in x['organization']:
            x['organization'].update( { ok: None } )


    missionDictKeys = [ "mission", "users", "pilotusers", "groups", "pilotgroups", 
                        "started", "ended", "planned", 
                        "orgname", "orglink", "contact", "email", 
                        "project", "link", "comment", "reason", "endpoints",
                        "sa", "also", "kml", "sadata", "alert"
                      ]
    
    dflts         = x['defaults']
    if 'RUNMODE' in config:
        mode_dflts    = x[modeNames[config['RUNMODE']] + 'defaults']
    else:
        mode_dflts = {}

    missions = []
    gliders  = []
    ids      = []
    actives  = []
    for m in x['missions']:

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

            m.update({ "default": (glider not in gliders) })
            gliders.append(glider)

            for mk in missionDictKeys:
                if mk not in m:
                    if 'mission' in m and m['mission'] and m['mission'] in x['missiondefaults'] and mk in x['missiondefaults'][m['mission']]:
                        m.update( { mk: x['missiondefaults'][m['mission']][mk] })
                    elif mode_dflts and mk in mode_dflts:
                        m.update( { mk: mode_dflts[mk] })
                    elif mk in x['organization']:
                        m.update( { mk: x['organization'][mk] })
                    elif dflts and mk in dflts:
                        m.update( { mk: dflts[mk] })
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
       
    endpointsDictKeys = [ "modes", "users", "groups", "level" ]
    dflts = None
    for k in list(x['endpoints'].keys()):
        if k == 'defaults':
            dflts = x['endpoints'][k]
            del x['endpoints'][k]
            continue    

        for ek in endpointsDictKeys:
            if ek not in x['endpoints'][k]:
                if dflts and ek in dflts:
                    x['endpoints'][k].update( { ek: dflts[ek] })
                else:
                    x['endpoints'][k].update( { ek: None } )
                    
    if dflts:
        for k in protectableRoutes:
            if k not in x['endpoints']:
                x['endpoints'][k] = dict.fromkeys(endpointsDictKeys)
                x['endpoints'][k].update( dflts )        

    for k in x['controls']:
        for da in x['controls'][k]:
            for index,exp in enumerate(x['controls'][k][da]):
                x['controls'][k][da][index] = re.compile(re.escape(exp), re.IGNORECASE)

    if app:
        app.ctx.missionTable = missions
        app.ctx.organization = x['organization']
        app.ctx.endpoints = x['endpoints']
        app.ctx.controls = x['controls']
        app.ctx.assets = x['assets']
        app.ctx.routes = x['routes']
        app.ctx.domain = x['authdomain']
        app.ctx.admins      = x['admins']
        app.ctx.admingroups = x['admingroups']
        app.ctx.pilotusers  = x['pilotusers']
        app.ctx.pilotgroups = x['pilotgroups']
        app.ctx.users       = x['users']
        app.ctx.groups      = x['groups']
        app.ctx.sa          = x['sa']
        app.ctx.autocomplete = x['autocomplete']
        app.ctx.missionsFile = config['MISSIONS_FILE']
        app.ctx.usersFile = config['USERS_FILE']

    return (missions, x, domains)
 
async def buildAuthTable(request, defaultPath, glider=None, mission=None, includePath=False):
    opTable = []
    for m in request.ctx.ctx.missionTable:
        status = checkGliderMission(request, m['glider'], m['mission'])
        if status == PERM_REJECT:
            continue

        path        = m['path'] if m['path'] else defaultPath
        missionName = m['mission'] if m['mission'] else ""
        project     = m['project'] if m['project'] else ""

        if (glider is None or glider == m['glider']) and (mission is None or mission == m['mission']):
            note = None
            if request.ctx.ctx.autocomplete > 0 and m['status'] == 'active':
                call = await getLatestCall(request, m['glider'], limit=1, path=m['path'])
                if call:
                    t = call[0]['epoch']
                    if time.time() > call[0]['epoch'] + request.ctx.ctx.autocomplete*86400:
                        m['status'] = 'complete'
                        note = 'auto complete by last call time' 
                else:
                    try:
                        t = await aiofiles.os.path.getmtime(m['path'])
                        if time.time() > t + request.ctx.ctx.autocomplete*86400:
                            m['status'] = 'complete'
                            note = 'auto complete by last directory activity'
                    except Exception:
                        pass

            x = { "mission": missionName, "glider": m['glider'], "default": m['default'], "status": m['status'], "project": project }
            if note:
                x.update({ "note": note })

            if includePath:
                x.update({ "path": path })

            opTable.append(x)

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
# background tasks
#

# this is per app config file watcher - each app must listen on its
# own so that it can update its own tables. This watches for published
# modification notices on the watch socket. The main process
# watchMonitorPublish does the actual inotify file watching

async def configWatcher(app):
    zsock = zmq.asyncio.Context().socket(zmq.SUB)
    zsock.setsockopt(zmq.LINGER, 0)
    zsock.connect(app.config.WATCH_IPC)
    sanic.log.logger.info('opened context for configWatcher')
    zsock.setsockopt(zmq.SUBSCRIBE, b"000-file-")
    while True:
        try:
            msg = await zsock.recv_multipart()
            sanic.log.logger.info(msg[1])
            topic = msg[0].decode('utf-8')
            if app.config['MISSIONS_FILE'] in topic:
                await buildMissionTable(app)
            elif app.config['USERS_FILE'] in topic:
                await buildUserTable(app)

        except BaseException: # websockets.exceptions.ConnectionClosed:
            zsock.close()
            return

        # app.m.name.restart() 

async def buildFilesWatchList(config):
    (missions, _, domains) = await buildMissionTable(None, config=config)
    files = { }
    if "darwin" in sys.platform:
        return (None, None)

    watcher = asyncinotify.Inotify()

    if not config.SINGLE_MISSION:
        for f in [ config['MISSIONS_FILE'], config['USERS_FILE'] ]:
            if f and await aiofiles.os.path.exists(f):
                sz = await aiofiles.os.path.getsize(f)
                files[f] = { 'glider': 0, 'file': f, 'size': sz, 'delta': 0, 'mission': '', 'config': True }
                watcher.add_watch(f, mask=asyncinotify.Mask.CLOSE_WRITE)

        for d in list(domains.keys()):
            for f in [ domains[d].missionsFile, domains[d].usersFile ]:
                if f and await aiofiles.os.path.exists(f):
                    sz = await aiofiles.os.path.getsize(f)
                    files[f] = { 'glider': 0, 
                                 'file': config['MISSIONS_FILE'] if f == domains[d].missionsFile else config['USERS_FILE'], 
                                 'size': sz, 
                                 'delta': 0, 
                                 'mission': '', 
                                 'config': True }
                    watcher.add_watch(f, mask=asyncinotify.Mask.CLOSE_WRITE)
                
    for m in missions:
        if m['status'] == 'active':
            if m['path']:
                fname = f"{m['path']}"
            else:
                fname = f"sg{m['glider']:03d}" 

            if await aiofiles.os.path.exists(fname):
                watcher.add_watch(fname, asyncinotify.Mask.CLOSE_WRITE)

                for f in ["comm.log", "cmdfile", "science", "targets", "scicon.sch", "tcm2mat.cal", "sg_calib_constants.m", "pdoscmds.bat", f"sg{m['glider']:03d}.kmz", "cmdedit.log", "sciedit.log", "targedit.log"]:
                    if m['path']:
                        fname = f"{m['path']}/{f}"
                    else:
                        fname = f"sg{m['glider']:03d}/{f}" 

                    if await aiofiles.os.path.exists(fname):
                        sz = await aiofiles.os.path.getsize(fname)
                    else:
                        sz = 0

                    files[fname] = { "glider": m['glider'], "file": f, "full": fname, "size": sz, "delta": 0, 'config': False, "mission": m['mission'] if m['mission'] else "" } 



    return (watcher, files)

async def fileWatch(watcher, files):
    while True:
        e = await watcher.get()
        if e.name:
            f = str(e.watch.path.joinpath(e.name))
        else:
            f = str(e.watch.path)
        if f in files:
            return (f, files[f]['config'])

# quick wrapper so we get a coroutine vs a Future (which we can't name when we create_task below)
async def messagingSocketWatch(sock):
    return await sock.recv_multipart()

async def watchMonitorPublish(config):
    msk = os.umask(0o000)
    ctx = zmq.asyncio.Context()
    zsock = ctx.socket(zmq.PUB)
    zsock.bind(config.WATCH_IPC)
    zsock.setsockopt(zmq.SNDTIMEO, 1000)
    zsock.setsockopt(zmq.LINGER, 0)

    #configWatchSocket = ctx.socket(zmq.SUB)
    #configWatchSocket.setsockopt(zmq.LINGER, 0)
    #configWatchSocket.connect(config.WATCH_IPC)
    #configWatchSocket.setsockopt(zmq.SUBSCRIBE, (f"000-file-").encode('utf-8'))

    inbound = ctx.socket(zmq.PULL)
    inbound.bind(config.NOTIFY_IPC)
    os.umask(msk)

    (watcher, files) = await buildFilesWatchList(config)

    # read the yml file that controls the data sources that we relay over web socket for the
    # map when its running in chart mode
    chart = None
    if config.CHART is not None and await aiofiles.os.path.exists(config.CHART):
        async with aiofiles.open(config.CHART, "r") as f:
            d = await f.read()
            try:
                chart = yaml.safe_load(d)
            except Exception as e:
                sanic.log.logger.info(f"chart parse error {e}")
                chart = None

    chartSock = []
    if chart and 'data' in chart:
        for v in chart['data']:
            if 'udp' in chart['data'][v] and ('regex' in chart['data'][v] or 'format' in chart['data'][v]):
                if 'regex' in chart['data'][v]:
                    rx = re.compile(chart['data'][v]['regex'])
                else:
                    rx = None

                chartSock.append( { 'sock': await asyncudp.create_socket(local_addr=('0.0.0.0', 
                                                                                   int(chart['data'][v]['udp'])), 
                                                                       packets_queue_max_size=1024, reuse_port=True),
                                  'id': v,
                                  'regex': rx, 'format': chart['data'][v].get('format') } )
        # todo - handle serial and json
                                  
    # varRE    = re.compile('[0-9]{2}-[0-9]{2}-[0-9]{4} [0-9]{2}:[0-9]{2}:[0-9]{2}[ ]+([^,]+)')

    try:
        while True:
            aws = [ asyncio.create_task(messagingSocketWatch(inbound), name='inbound') ]
                    # asyncio.create_task(messagingSocketWatch(configWatchSocket, name='config'),
            if watcher:
                aws.append(asyncio.create_task(fileWatch(watcher, files), name='files'))

            for s in chartSock:
                aws.append(asyncio.create_task(s['sock'].recvfrom(), name=s['id']))

            done, pend = await asyncio.wait(aws, return_when=asyncio.FIRST_COMPLETED)

            for task in done:
                name = task.get_name()
                # sanic.log.logger.info(name)
                r = task.result()
                if name == 'inbound': # r is multipart message
                    d = loads(r[1])
                    if 'when' not in d:
                        d.update({"when": "socket"})

                    r[1] = dumps(d)
                    sanic.log.logger.info("notifier got {r[0].decode('utf-8')}")
                    await zsock.send_multipart(r)
    #
    #            elif name == 'config':
    #                
    #                topic = r[0].decode('utf-8')
    #                if config['MISSIONS_FILE'] in topic:
    #                    watcher.close()
    #                    (watcher, files) = await buildFilesWatchList(config)
    #
                elif name == 'files':
                    fname = r[0]
                    if r[1] and watcher:             # r is tuple (name, config boolean)
                        watcher.close()
                        print('rebuilding list')
                        (watcher, files) = await buildFilesWatchList(config)
                        # rebuild the watch list, but re-reading the tables is a per app thing
                        # so relies on this notification going out and then configWatcher
                        # picking it up
                    if 'comm.log' in fname:
                        sz = await aiofiles.os.path.getsize(fname)
                        if sz > files[fname]['size']:
                            files[fname]['delta'] = sz - files[fname]['size']
                        else:
                            files[fname]['delta'] = sz

                        files[fname]['size']  = sz
                    else:
                        sz = 0

                    msg = [(f"{files[fname]['glider']:03d}-file-{files[fname]['file']}").encode('utf-8'), dumps(files[fname])]
                    sanic.log.logger.info(f"{files[fname]['glider']:03d}-file-{files[fname]['file']}, {sz}")
                    await zsock.send_multipart(msg)

                elif len(chartSock):
                    for v in chartSock:
                        if name == v['id']:
                            if v['format'] == 'nmea':
                                try:
                                    data = r
                                    if data:
                                        sentences = data[0].decode()
                                        msg = { 'ship': v['id'], 'time': time.time() }
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

                                        await zsock.send_multipart([f"000-chart-{v['id']}".encode('utf-8'), dumps(msg)])
                                except Exception:
                                    pass
                            elif v['regex']:
                                try:
                                    if m := v['regex'].match(r[0].decode()):
                                        msg = { 'time': time.time(), v['id']: [ float(x.strip()) for x in m.groups() ] }
                                        await zsock.send_multipart([f"000-chart-{v['id']}".encode('utf-8'), dumps(msg)])
                                except Exception:
                                    pass

            if len(pend) > 0:
                for task in pend:
                    task.cancel()

                await asyncio.wait(pend)

    finally:
        zsock.close()
        inbound.close()
        ctx.term() 

                
def backgroundWatcher(config):
    loop = asyncio.get_event_loop()
    loop.create_task(watchMonitorPublish(config))
    loop.run_forever()

async def mainProcessReady(app):
    print('main process ready')
    app.manager.manage("backgroundWatcher", backgroundWatcher, { "config": app.config })

async def mainProcessStop(app):
    os.remove(app.config.WATCH_IPC[6:])
    os.remove(app.config.NOTIFY_IPC[6:])

def createApp(overrides: dict, test=False) -> sanic.Sanic:

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
    if 'VALIDATE_SECRET' not in app.config:
        app.config.VALIDATE_SECRET = secrets.token_hex()
    if 'MISSIONS_FILE' not in app.config:
        app.config.MISSIONS_FILE = "missions.yml"
    if 'USERS_FILE' not in app.config:
        app.config.USERS_FILE = "users.yml"
    if 'STATIC_FILE' not in app.config:
        app.config.STATIC_FILE = "static.yml"
    if 'FQDN' not in app.config:
        app.config.FQDN = None
    if 'USER' not in app.config:
        app.config.USER = os.getlogin()
    if 'SINGLE_MISSION' not in app.config:
        app.config.SINGLE_MISSION = None
    if 'WEATHERMAP_APPID' not in app.config:
        app.config.WEATHERMAP_APPID = ''
    if 'CHART' not in app.config:
        app.config.CHART = None
    if 'AUTH_DB' not in app.config:
        app.config.AUTH_DB = "auth.db"
    if 'ALERT' not in app.config:
        app.config.ALERT = 'ping'
    if 'PILOT_AUTH_TYPE' not in app.config:
        app.config.PILOT_AUTH_TYPE = AUTH_TYPE_ADVANCED

    if isinstance(app.config.PILOT_AUTH_TYPE, str):
        app.config.PILOT_AUTH_TYPE = int(app.config.PILOT_AUTH_TYPE)

    app.config.TEMPLATING_PATH_TO_TEMPLATES=f"{sys.path[0]}/html"

    if test:
        return app

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
    print("  --staticfile=|-w   static.yml file (default ROOT/static.yml)")
    print("  --certs=|-c        certificate file for SSL")
    print("  --ssl|-s           boolean: enable SSL")
    print("  --inspector|-i     boolean: enable SANIC inspector")
    print("  --alert|-b         alert sound (bell, ping, chime, beep)")
    print("  --nochat           boolean: run without chat support")
    print("  --nosave           boolean: run without save support")
    print("  --test|-t          yml confidg syntax test mode")
    print("  -z                 cleanup zombie sockets and exit")
    print()
    print("  Environment variables: ")
    print("    SANIC_CERTPATH, SANIC_ROOTDIR, SANIC_SECRET, ")
    print("    SANIC_MISSIONS_FILE, SANIC_USERS_FILE, SANIC_FQDN, ")
    print("    SANIC_USER, SANIC_SINGLE_MISSION, SANIC_ALERT")

if __name__ == '__main__':

    root = os.getenv('SANIC_ROOTDIR')
    if os.getuid() > 0:
        runMode = MODE_PRIVATE
    else:
        runMode = MODE_PUBLIC

    port = 20001
    ssl = False
    certPath = os.getenv("SANIC_CERTPATH") 
    noSave = False
    noChat = False
    test = False

    overrides = {}

    try:
        opts, args = getopt.getopt(sys.argv[1:], 'a:b:m:p:o:r:d:f:u:c:w:tsihz', ["auth", "alert=", "mission=", "port=", "mode=", "root=", "domain=", "missionsfile=", "usersfile=", "certs=", "staticfile=", "test", "ssl", "inspector", "help", "nosave", "nochat", "chart=" ])
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
        elif o in ['-b', '--alert']:
            overrides['ALERT'] = a
        elif o in ['-w', '--staticfile']:
            overrides['STATIC_FILE'] = a
        elif o in ['--chart']:
            overrides['CHART'] = a
        elif o in ['--nosave']:
            noSave = True
        elif o in ['--nochat']:
            noChat = True
        elif o in ['-c', '--certs']:
            certPath = a
        elif o in ['-s', '--ssl']:
            ssl = True
        elif o in ['-t', '--test']:
            test = True
        elif o in ['-i', '--inspector']:
            overrides['INSPECTOR'] = True
        elif o in ['-a', '--auth']:
            overrides['AUTH_DB'] = a
        elif o in ['-m', '--mission']:
            overrides['SINGLE_MISSION'] = a
            pieces = a.split(':')
            if len(pieces) != 2:
                print("-m sgNNN:/abs/mission/path")
                sys.exit(1)
        elif o in ['-z']:
            Utils.cleanupZombieVisSockets()
            sys.exit(1)
        elif o in ['-h', '--help']:
            usage()
            sys.exit(1)
                 
    if root is None and 'SINGLE_MISSION' not in overrides:
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
    if "VALIDATE_SECRET" not in os.environ:
        overrides["VALIDATE_SECRET"] = secrets.token_hex()

    if test:
        app = createApp(overrides, test=True)
        (tbl, _, _) = asyncio.run(buildMissionTable(app))
        pprint.pp(tbl)
        users = asyncio.run(buildUserTable(app))
        pprint.pp(users)
        sys.exit(0) 
 
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
        # app.prepare(host="0.0.0.0", port=port, access_log=True, debug=False, fast=True)
        app.prepare(host="0.0.0.0", port=port, access_log=True, debug=False, fast=True)
        sanic.Sanic.serve(primary=app, app_loader=loader)
        # app.run(host='0.0.0.0', port=port, access_log=True, debug=True, fast=True)
