# /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2023 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
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
import subprocess
import glob
import os

def parameterChanges(dive, logname, cmdname):

    if not os.path.exists(logname) or not os.path.exists(cmdname):
        return []
    
    cmd = f"/usr/local/bin/validate {logname} -c {cmdname}"

    proc = subprocess.Popen(
          cmd,
          shell=True,
          stdout=subprocess.PIPE,
          stderr=subprocess.PIPE
    )
    out, err = proc.communicate()
    results = out.decode('utf-8', errors='ignore')

    changes = []
    for line in results.splitlines():
        if "will change" in line:
            pieces = line.split(' ')
            logvar = pieces[2]
            oldval = pieces[6]
            newval = pieces[8]
            changes.append(  { "dive": dive, "parm": logvar, "oldval": oldval, "newval": newval } )

    return changes

if __name__ == "__main__":
    if len(sys.argv < 2):
        sys.exit(1)
    
    glider = int(sys.argv[1])

    if len(sys.argv) >= 3:
        first = int(sys.argv[2])
    else:
        first = 1
     
    if len(sys.argv) == 4:
        last = int(sys.argv[3])
    else:
        last = first

    path = './'

    c = cmdHistory(path, glider, first, last)

    print(c)
