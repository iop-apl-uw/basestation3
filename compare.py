#!/usr/bin/python3

## 
## Copyright (c) 2006, 2007 by the AUTHORS.  All rights reserved.
## 
## This file contains proprietary information and remains the 
## unpublished property of the AUTHORS. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the AUTHORS.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

import sys
import shutil
import os

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
canonname = sys.path[0] + "/canonicals/canon_" + sys.argv[1] + ".log"
try:
    log = open(logname, "rb")
except IOError:
    print("could not open input file %s" % logname)
    sys.exit(1)

try:
    canon = open(canonname)
except:
    print("could not open canonical file %s" % canonname)
    sys.exit(1)

canonmin = {}
canonmax = {}
canonopt = {}
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

opt = False

for line in canon:
    if line[0] == '#':
        continue

    if line.startswith("opt"):
        columns = line.split(" ")[1].split(",")
        opt = True
    else:
        columns = line.split(",")
        opt = False

    key = columns[0].lstrip('$')
    try:
        canonmin[key] = float(columns[1])
        canonmax[key] = float(columns[2]) 
        canonopt[key] = opt
    except IndexError:
        sys.stderr.write("Could not handle %s (%s)\n" %(key, columns))
 
canon.close()

critical = ["COMM_SEQ", "LOGGERS", "N_DIVES", "PRESSURE_SLOPE"]
serious = ["D_TGT", "T_DIVE", "T_MISSION", "D_OFFGRID"]

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

            print ("[%s] $%s,%f not between %f and %f (currently %f)" % (status, key, logdata[key], canonmin[key], canonmax[key], logdata[key]))

for key in keys:
    if not key in canonmin:
        print ("[unknown] $%s in input not found in canonical reference" % key)

keys = sorted(canonmin.keys())
for key in keys:
    if not key in logdata and canonopt[key] == False:
        print ("[unknown] $%s in canonical reference not found in input" % key)
