#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2010, 2011, 2022 by the AUTHORS.  All rights reserved.
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
usage: compare.py canonical_parameter_file log_or_capture_or_parm_file 

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
canonname = sys.argv[1]

try:
    log = open(logname, "rb")
except IOError:
    print(("could not open input file %s" % logname))
    sys.exit(1)

try:
    canon = open(canonname)
except:
    print(("could not open canonical file %s" % canonname))
    sys.exit(1)

canonmin = {}
canonmax = {}
logdata = {}

line_count = 0
for raw_line in log:
    line_count += 1
    try:
        line = raw_line.decode()
    except UnicodeDecodeError:
        print("Could not process line %d of %s" % (line_count, logname))
        continue

    columns = line.split(",")
    if len(columns) == 2 and columns[0].startswith('$') and not columns[0].startswith('$_'):
        #print columns
        key = columns[0].lstrip('$')
        try:
            logdata[key] = float(columns[1])
        except ValueError:
            pass
    elif len(columns) == 5 and columns[3].startswith('$'):
        key = columns[3].lstrip('$')
        logdata[key] = float(columns[4])

log.close()

for line in canon:
    if(line[0] == '#'):
        continue
    columns = line.split(",")
    key = columns[0].lstrip('$')
    try:
        canonmin[key] = float(columns[1])
        canonmax[key] = float(columns[2])
    except IndexError:
        sys.stderr.write("Could not handle %s (%s)\n" %(key, columns))

canon.close()

keys = sorted(list(logdata.keys()))

for key in keys:
    if key in canonmin:
        if logdata[key] < canonmin[key] or logdata[key] > canonmax[key]:
            print(("$%s,%f not between %f and %f (currently %f)" % (key, logdata[key], canonmin[key], canonmax[key], logdata[key])))
    else:
        print(("$%s in input not found in canonical reference" % key))

keys = sorted(canonmin.keys())

for key in keys:
    if key not in logdata:
        print(("$%s in canonical reference not found in input" % key))
