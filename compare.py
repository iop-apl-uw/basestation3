#!/usr/bin/python3

## Copyright (c) 2023  University of Washington.
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

import sys
import shutil
import os
from pathlib import Path
import re

def availableCanons():
    p  = Path(os.path.join(sys.path[0], "canonicals"))
    f = []
    for canonfile in p.glob('canon_*.log'):
        m = re.match(r'canon_([A-za-z0-9_]+).log', canonfile.name)
        f.append(m.group(1))

    return f

def compare(canonname, logname):
    try:
        log = open(logname, "rb")
    except IOError:
        print("could not open input file %s" % logname)
        return None

    try:
        canon = open(canonname)
    except:
        print("could not open canonical file %s" % canonname)
        return None

    canonmin = {}
    canonmax = {}
    canonopt = {}
    canonvars = {}
    logdata = {}

    line_count = 0
    for raw_line in log:
        line_count += 1
        try:
            line = raw_line.decode()
        except UnicodeDecodeError:
            # print("[error] Could not process line %d of %s" % (line_count, logname))
            continue

        columns = line.split(",")
        if len(columns) == 2 and columns[0].startswith('$') and not columns[0].startswith('$_') and columns[1].find('*') == -1:
            #print columns
            key = columns[0].lstrip('$')
            try:
                logdata[key] = float(columns[1])
            except ValueError:
                pass
        elif len(columns) == 5 and columns[3].startswith('$') and columns[4].find('*') == -1:
            key = columns[3].lstrip('$')
            try:
                logdata[key] = float(columns[4])
            except ValueError:
                print(f"Could not process line {line_count} - skipping")
                continue

    log.close()

    if len(logdata.keys()) == 0:
        print("no log data present")
        return None 

    opt = False

    for line in canon:
        if line[0] == '#':
            continue

        opt = False
        if line.startswith("opt"):
            columns = line.split(" ")[1].split(",")
            opt = True
        else:
            columns = line.split(",")

        key = columns[0].lstrip('$')

        try:
            canonmin[key] = float(columns[1])
            canonmax[key] = float(columns[2]) 
            canonopt[key] = opt
            canonvars[key] = {}
            if len(columns) > 3:
                for i in range(3,len(columns)):
                    v = columns[i].split('=')
                    canonvars[key][v[0]] = float(v[1])

        except IndexError:
            sys.stderr.write("Could not handle %s (%s)\n" %(key, columns))
     
    canon.close()

    critical = ["COMM_SEQ", "LOGGERS", "N_DIVES", "PRESSURE_SLOPE"]
    serious = ["D_TGT", "T_DIVE", "T_MISSION", "D_OFFGRID"]

    x = []

    keys = sorted(list(logdata.keys()))
    for key in keys:
        if key in canonmin:
            if logdata[key] < canonmin[key] or logdata[key] > canonmax[key]:
                if key in critical:
                    status = "crit"
                elif key in serious:
                    status = "sers"
                else:
                    status = "warn"

                x.append( { "param": key, "status": status, "value": logdata[key], "min": canonmin[key], "max": canonmax[key] } )
            elif canonvars[key]:
                found = False
                for k in canonvars[key]:
                    if abs((logdata[key] - canonvars[key][k])/canonvars[key][k]) < 0.01:
                        x.append( { "param": key, "status": "inf", "value": logdata[key], "set": k } )
                        found = True
                        break

                if not found:
                    x.append( { "param": key, "status": "inf", "value": logdata[key], "set": None } )


    for key in keys:
        if not key in canonmin:
            x.append( { "param": key, "status": "unknown", "missing":  "canon" } )

    keys = sorted(canonmin.keys())
    for key in keys:
        if not key in logdata and canonopt[key] == False:
            x.append( { "param": key, "status": "unknown", "missing": "log" } )

    return x

def renderTable(x, pcolors, rcolors):
    print("<table>")
    print("<tr><th></th><th>parameter</th><th>current</th><th>min</th><th>max</th></tr>")
    trow = 0
    for p in x:
        if p['status'] == 'inf':
            print('<tr style="background-color:%s;">' % rcolors[trow % 2])
            print('<td>[%s]</td>' % p['status'])
            print('<td><a href="../parms#%s">%s</a> &nbsp;</td>' % (p['param'], p['param']))
            print("<td>%s</td>" % p['value'])
            if p['set']:
                print("<td colspan=2>set for %s</td>" % p['set'])
            else:
                print("<td colspan=2>not a default value</td>" % p['set'])
            print("</tr>")
            trow = trow + 1

        elif p['status'] != 'unknown':
            print('<tr style="background-color:%s;">' % rcolors[trow % 2])
            print('<td style="background-color:%s;">[%s]</td>' % (pcolors[p['status']], p['status']))
            print('<td><a href="../parms#%s">%s</a> &nbsp;</td>' % (p['param'], p['param']))
            print("<td>%s</td>" % p['value'])
            print("<td>%s</td>" % p['min'])
            print("<td>%s</td>" % p['max'])
            print("</tr>")
            trow = trow + 1

    for p in x:
        if p['status'] == 'unknown':
            print('<tr style="background-color:%s;">' % rcolors[trow % 2])
            print('<td>[unknown]</td><td>%s</td>' % p['param'])
            if p['missing'] == 'log':
                print('<td colspan=3>canonical reference not found in input</td>')
            else:
                print('<td colspan=3>input not found in canonical reference</td>')
            print('</tr>')
            trow = trow + 1

    print("</table>")

if __name__ == "__main__":
    help_message = """
    usage: compare.py canonicalParameterSetName log_or_capture_or_parm_file 

    Compares parameters from a log, selftest capture, or launch parameter
    file with those in a canonical reference file. Parameters in the reference
    file are specified with a minimum and maximum value as $PARM,min,max. Any 
    parameter in the input file that is outside the bounds of the matching 
    parameter in the canonical file is called out. 
    """

    if len(sys.argv) != 3:
        print(help_message)
        sys.exit(1)

    logname = sys.argv[2]
    local_canon = os.path.join(os.path.dirname(logname), '.canonicals')

    if os.path.exists(local_canon):
        canonname = local_canon
    else:
        canonname = os.path.join(sys.path[0], "canonicals/canon_" + sys.argv[1] + ".log")

    f = availableCanons()
    print(f)
    print(f'canonical parameters: {os.path.basename(canonname)}')
    print(logname)
    x = compare(canonname, logname)
    if not x:
        sys.exit(1)
    
    for p in x: 
        if p['status'] == 'inf' and p['set']:
            print ("[inf] $%s,%f set for %s" % (p['param'], p['value'], p['set']))
        elif p['status'] == 'inf':
            print("[inf] $%s,%f not a default value" % (p['param'], p['value'] ) )
        elif p['status'] == 'unknown':
            if p['missing'] == 'log':
                print ("[unknown] $%s in canonical reference not found in input" % p['param'])
            else:
                print ("[unknown] $%s in input not found in canonical reference" % p['param'])
        else:
            print ("[%s] $%s,%f not between %f and %f (currently %f)" % (p['status'], p['param'], p['value'], p['min'], p['max'], p['value']))

