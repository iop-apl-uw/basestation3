#!/usr/bin/env python3

from http.server import HTTPServer, BaseHTTPRequestHandler
from http import HTTPStatus
import json
import time
# import socket
import _thread
from socketserver import ThreadingMixIn
import base64
import os
import os.path
from parse import parse
import glob
from watchdog.observers import Observer
from watchdog.events import PatternMatchingEventHandler
import sqlite3
import tempfile
import subprocess
import sys
import LogHTML
from zipfile import ZipFile
from io import BytesIO

modifiedFile = {}
newDive = {}
newFile = {}
commFile = {}
watchThread = {}

def serveFile(wfile, filename):
    print("serving " + '%s/%s' % (sys.path[0], filename))
    with open('%s/%s' % (sys.path[0], filename), 'rb') as file:
        wfile.write(file.read())
    
def serveScript(wfile, script):
    if script.find('..') > -1 or script.find('/') > -1:
        return

    serveFile(wfile, 'scripts/%s' % script)
            
def streamData(wfile, data):
    try:
        wfile.write(b'data: ')
        wfile.write(data)
        wfile.write(b'\n\n')
        wfile.flush()
    except:
        pass


def rowToDict(cursor: sqlite3.Cursor, row: sqlite3.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

class _RequestHandler(BaseHTTPRequestHandler):
    # Borrowing from https://gist.github.com/nitaku/10d0662536f37a087e1b

    def do_GET(self):
        global commFile
        global modifiedFile
        global newFile
        global newDive

        pieces = self.path.split('/')
        if pieces[1] == 'stream':
            glider = pieces[2]
            print("detecting stream")
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'text/event-stream')
            self.send_header('Cache-Control', 'no-cache');
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(b'retry: 30000\n');

            if glider in commFile and commFile[glider]:
                # data = commFile[glider].read().decode('utf-8').encode('unicode_escape')
                data = commFile[glider].read().decode('utf-8')
                data = data.replace("\n", "<br>")
                data = data.encode('utf-8')
                if data:
                    streamData(self.wfile, data)
                    data = data

            while True:
                if glider in modifiedFile and modifiedFile[glider]:
                    if modifiedFile[glider] == "comm.log" and glider in commFile and commFile[glider]:
                        modifiedFile[glider] = False
                        data = commFile[glider].read().decode('utf-8', errors='ignore')
                        print(data)
                        data = data.replace("\n", "<br>")
                        data = data.encode('utf-8', errors='ignore')
                        if data:
                            streamData(self.wfile, data)
                    elif modifiedFile[glider] == "cmdfile":
                        modifiedFile[glider] = False
                        filename = 'sg' + glider + '/cmdfile'
                        print("sending new cmdfile")
                        with open(filename, 'rb') as file:
                            data = "CMDFILE=" + file.read().decode('utf-8', errors='ignore').replace("\n", "<br>")
                            streamData(self.wfile, data.encode('utf-8', errors='ignore'))

                if glider in newDive and newDive[glider]:
                    newDive[glider] = False
                    streamData(self.wfile, bytes('NEW=' + newFile[glider], 'utf-8'))

                time.sleep(0.5)

            # self.close_connection()
        elif pieces[1] == 'status':
            glider = pieces[2]
            if glider in commFile and commFile[glider]:
                commFile[glider].close()
                commFile[glider] = None

            commFile[glider] = open('sg' + glider + '/comm.log', 'rb')
            commFile[glider].seek(-10000, 2)
            # modifiedFile[glider] = "comm.log" # do we need this to trigger initial send??

            (maxdv, dvplots, engplots, sgplots, plotlyplots) = buildFileList(glider)

            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            message = {}
            message['glider'] = 'SG' + glider
            message['dive'] = maxdv
            # message['dvplots'] = dvplots
            message['engplots'] = engplots
            # message['sgplots'] = sgplots
            # message['plotlyplots'] = plotlyplots
            self.wfile.write(json.dumps(message).encode('utf-8'))

        elif pieces[1] == 'db':
            glider = pieces[2]
            q = "SELECT dive,log_start,log_D_TGT,log_D_GRID,log__CALLS,log__SM_DEPTHo,log__SM_ANGLEo,log_HUMID,log_TEMP,log_INTERNAL_PRESSURE,depth_avg_curr_east,depth_avg_curr_north,max_depth,pitch_dive,pitch_climb,volts_10V,volts_24V,capacity_24V,capacity_10V,total_flight_time_s,avg_latitude,avg_longitude,target_name,magnetic_variation,mag_heading_to_target,meters_to_target,GPS_north_displacement_m,GPS_east_displacement_m,flight_avg_speed_east,flight_avg_speed_north FROM dives"
            if len(pieces) == 4:
                dive = int(pieces[3])
                q = q + f" WHERE dive={dive};"
            else:
                q = q + " ORDER BY dive ASC;"

            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            with sqlite3.connect('sg' + glider + '/sg' + glider + '.db') as conn:
                conn.row_factory = rowToDict
                cur = conn.cursor()
                cur.execute(q)
                data = cur.fetchall()
                self.wfile.write(json.dumps(data).encode('utf-8'))
                 
        elif pieces[1] == 'selftest':
            glider = pieces[2]
            cmd = "%s/SelftestHTML.py %s" % (sys.path[0], glider)
            output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            results = output.stdout
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(bytes(results, 'utf-8')) 

        elif pieces[1] == 'script':
            print(pieces)
            if pieces[2] == 'images':
                self.send_response(HTTPStatus.OK.value)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                filename = sys.path[0] + '/scripts/images/' + pieces[3]
                with open(filename, 'rb') as file:
                    self.wfile.write(file.read())
            else:
                # do we need headers? Yes
                self.send_response(HTTPStatus.OK.value)
                self.send_header('Content-type', 'text/html')
                self.end_headers()
                serveScript(self.wfile, pieces[2])

        elif pieces[1] == 'plots':
            glider = pieces[2]
            dive = pieces[3]
            (dvplots, plotlyplots) = buildPlotsList(int(glider), int(dive))
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            message = {}
            message['glider'] = 'SG' + glider
            message['dive'] = dive
            message['dvplots'] = dvplots
            message['plotlyplots'] = plotlyplots
            # message['engplots'] = engplots
            self.wfile.write(json.dumps(message).encode('utf-8'))

        elif pieces[1] == 'cmdfile':
            glider = pieces[2]
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            filename = 'sg' + glider + '/cmdfile'
            message = {}
            message['file'] = 'cmdfile'
            with open(filename, 'rb') as file:
                message['contents'] = file.read().decode('utf-8')
            self.wfile.write(json.dumps(message).encode('utf-8'))

        elif pieces[1] == 'eng':
            glider = int(pieces[2])
            image = pieces[3]
            filename = 'sg%03d/plots/eng_%s.png' % (glider, image)
            # print(f"sending {filename}")
            if not os.path.exists(filename):
                self.send_response(HTTPStatus.NOT_FOUND.value)
            else:
                self.send_response(HTTPStatus.OK.value)
                self.send_header('Content-type', 'image/png')
                self.end_headers()
                with open(filename, 'rb') as file:
                    self.wfile.write(file.read())

        elif pieces[1] == 'log':
            glider = int(pieces[2])
            dive  = int(pieces[3])
            filename = 'sg%03d/p%03d%04d.log' % (glider, glider, dive)
            s = LogHTML.captureTables(filename)
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            self.wfile.write(s.encode('utf-8', errors='ignore'))

        elif pieces[1] == 'png' or pieces[1] == 'div':
            glider = int(pieces[2])
            dive  = int(pieces[3])
            image = pieces[4]
            filename = 'sg%03d/plots/dv%04d_%s.%s' % (glider, dive, image, pieces[1])
            if not os.path.exists(filename):
                self.send_response(HTTPStatus.NOT_FOUND.value)
            else:
                self.send_response(HTTPStatus.OK.value)
                if pieces[1] == 'png':
                    self.send_header('Content-type', 'image/png')
                    self.end_headers()
                elif pieces[1] == 'div':
                    self.send_header('Content-type', 'text/html')
                    self.end_headers()
                    self.wfile.write(b'<script src="https://cdn.plot.ly/plotly-latest.min.js"></script>')
                    self.wfile.write(b'<html>')
                    title = "<head><title>%03d-%d-%s</title></head>" % (glider, dive, image)
                    self.wfile.write(bytes(title, 'utf-8'))
                    self.wfile.write(b'<body>')

                with open(filename, 'rb') as file:
                    self.wfile.write(file.read())
            
                if pieces[1] == 'div':
                    self.wfile.write(b'</body></html>')  
        elif pieces[1] == 'map':
            # glider is included but map.html figures it out from
            # the URL that gets passed in the location bar...
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'text/html')
            self.end_headers()
            serveFile(self.wfile, 'html/map.html')

        elif pieces[1] == 'kml':
            glider = pieces[2]
            self.send_response(HTTPStatus.OK.value)
            self.send_header('Content-type', 'application/vnd.google-earth.kml')
            self.end_headers()
            filename = 'sg' + glider + '/sg' + glider + '.kmz'
            with open(filename, 'rb') as file:
                zip = ZipFile(BytesIO(file.read()))
                self.wfile.write(zip.open('sg' + glider + '.kml').read())

        else:
            glider = pieces[1]
            filename = 'sg' + glider + '/comm.log'
            if os.path.exists(filename):
                self.send_response(HTTPStatus.OK.value)
                self.send_header('Content-type', 'text/html')
                self.send_header('Access-Control-Allow-Origin', '*')
                self.end_headers()

                serveFile(self.wfile, 'html/vis.html')
                if not glider in watchThread:
                    watchThread[glider] = _thread.start_new_thread(watchFilesystem, (glider,))
            else:
                self.send_response(HTTPStatus.NOT_FOUND.value)
                self.send_header('Content-type', 'text/html');
                self.end_headers()
                self.wfile.write(b'invalid glider')
                
    def do_POST(self):

        pieces = self.path.split('/')
        length = int(self.headers.get('content-length'))
        message = json.loads(self.rfile.read(length).decode())
        if pieces[1] == 'save':
            path = 'sg' + pieces[2]
            tempfile.tempdir = path
            tmp = tempfile.mktemp()
            with open(tmp, 'w') as file:
                file.write(message['contents'])
                file.close()
                print(message['contents'])
                print("saved to %s" % tmp)
                #p = subprocess.Popen(
                #    ["/usr/local/basestation3/cmdedit", "-d", path, "-q", "-f", tmp],
                #    stdin=subprocess.PIPE,
                #    stdout=subprocess.PIPE,
                #    stderr=subprocess.PIPE,
                #    close_fds=True,
                #)
                #results, err = p.communicate()
                if 'force' in message and message['force'] == 1:
                    cmd = f"{sys.path[0]}/cmdedit -d {path} -q -i -f {tmp}"
                else:
                    cmd = f"{sys.path[0]}/cmdedit -d {path} -q -f {tmp}"
                print(cmd)
                output = subprocess.run(cmd, shell=True, text=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
                results = output.stdout
                err = output.stderr
                print("results")
                print(results)
                print("err")
                print(err)
                self.send_response(HTTPStatus.OK.value)
                self.send_header('Content-type', 'text/plain')
                self.end_headers()
                self.wfile.write(bytes(results, 'utf-8')) 

    def do_OPTIONS(self):
        # Send allow-origin header for preflight POST XHRs.
        self.send_response(HTTPStatus.NO_CONTENT.value)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST')
        self.send_header('Access-Control-Allow-Headers', 'content-type,cache-control')
        self.end_headers()

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    """Handle requests in a separate thread."""

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
    for fullFile in glob.glob('sg' + glider + '/plots/*.png'):
        file = os.path.basename(fullFile)
        if file.startswith('dv'):
            x = parse('dv{}_{}.png', file)
            try:
                dv = int(x[0])
                plot = x[1] 
                if dv > maxdv:
                    maxdv = dv
                if not plot in dvplots:
                    dvplots.append(plot)

                divFile = fullFile.replace("png", "div")
                if os.path.exists(divFile):     
                    plotlyplots.append(plot)           
            except:
                pass

        elif file.startswith('eng'):
            pieces = file.split('.')
            engplots.append('_'.join(pieces[0].split('_')[1:]))
        elif file.startswith('sg'):
            pieces = file.split('.')
            sgplots.append(pieces[0]) 

    return (maxdv, dvplots, engplots, sgplots, plotlyplots)

def watchFilesystem(glider):
    print("watching")
    ignore_patterns = None
    ignore_directories = True
    case_sensitive = True

    patterns = ["./sg" + glider + "/comm.log"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, "./sg" + glider, recursive=False)
    observer.start()

    patterns = ["./sg" + glider + "/plots/dv*png"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, "./sg" + glider + "/plots", recursive=False)
    observer.start()

    patterns = ["./sg" + glider + "/cmdfile"]
    eventHandler = PatternMatchingEventHandler(patterns, ignore_patterns, ignore_directories, case_sensitive)
    eventHandler.on_created = onCreated
    eventHandler.on_modified = onModified

    observer = Observer()
    observer.schedule(eventHandler, "./sg" + glider, recursive=False)
    observer.start()

    while True:
        time.sleep(1)

def onCreated(evt):
    global newDive
    global newFile
    print("created %s" % evt.src_path)
    path = os.path.basename(evt.src_path)
    if path.startswith('dv'):
        glider = os.path.dirname(evt.src_path).split('/')[1][2:]
        newDive[glider] = True
        newFile[glider] = path


def onModified(evt):
    global modifiedFile

    print("modified %s" % evt.src_path)
    path = os.path.basename(evt.src_path)
    if path == "comm.log" or path == "cmdfile":
        glider = os.path.dirname(evt.src_path).split('/')[1][2:]
        # print(f"marking {glider} {path} as modified")
        modifiedFile[glider] = path

def run_server(port):
    server_address = ('', port)
    httpd = ThreadedHTTPServer(server_address, _RequestHandler)
    print('serving at %s:%d' % server_address)
    httpd.serve_forever()

 
if __name__ == '__main__':
    os.chdir("/home/seaglider")

    if len(sys.argv) == 2:
        port = int(sys.argv[1])
    else:
        port = 20001

    run_server(port)
