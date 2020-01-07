#! /usr/bin/env python

## 
## Copyright (c) 2013, 2014, 2017, 2018 by University of Washington.  All rights reserved.
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
import math
from numpy import *
import traceback
from BaseLog import *

def readMagCalFile(mag_cal_filename):
    try:
        fi = open(mag_cal_filename, 'r')
        contents = "%s" % fi.readline().replace('\"', '') # tag line
        contents = "%s%s" % (contents, fi.readline()) # Roll coeffs
        contents = "%s%s" % (contents, fi.readline()) # Pitch coeffs
        contents = "%s%s" % (contents, fi.readline()) # abc/pqr coeffs
        # NOTE: for DG, add the next lines; if there are no lines readline() returns ''
        contents = "%s%s" % (contents, fi.readline()) #  pitch mass PQR adjustment (required for DG)
        contents = "%s%s" % (contents, fi.readline()) #  HV pack signature for testing HV Hi drift (DG)
        fi.close()
        return contents
    except:
        # Trouble with open or close; readline never complains
        log_error("Could not process %s" % mag_cal_filename, 'exc')
        return None

def parseMagCal(contents):
    lines = contents.split('\n');
    # line 0 is tag line
    # line 1 is the roll coeff line
    # line 2 is the pitch coeff line
    # line 3 is the abc_pqr line
    # for DG, optional line 4 contains pitchAD PQR scaling information
    # and line 5 contains HV pack info
    abc_pqr = lines[3].split()
    if(len(abc_pqr) < 12):
        log_error("Failed to parse '%s' - not enough values on abc/pqr line" % abc_pqr)
        return (None, None)

    abc = zeros(9)
    pqr = zeros(3)
    try:
        for i in range(9):
            abc[i] = float(abc_pqr[i])
        for i in range(3):
            pqr[i] = float(abc_pqr[i+9])
        # Create the stock closure that ignores pitchAD values
        pqrc = lambda p: pqr
        
        # DG correction has five lines exactly.  SG with second compass
        # has a second compass definition right after the first
        if len(lines) == 5 and len(lines[4]) > 2: 
            try:
                dg = lines[4].split()
                if (len(dg) != 10):
                    log_error("Could not parse hard-iron scale coefficients in '%s'" % lines[4])
                    # fall through and use default closure
                else:
                    pitch_ref = float(dg[0])
                    Pc = zeros(3)
                    for i in range(3):
                        Pc[i] = float(dg[i+1])
                    Qc = zeros(3)
                    for i in range(3):
                        Qc[i] = float(dg[i+1+3])
                    Rc = zeros(3)
                    for i in range(3):
                        Rc[i] = float(dg[i+1+3+3])
                    cP = polyval(Pc, pitch_ref)
                    cQ = polyval(Qc, pitch_ref)
                    cR = polyval(Rc, pitch_ref)
                    pqrc = lambda p:(polyval(Pc, p) - cP + pqr[0],
                                     polyval(Qc, p) - cQ + pqr[1],
                                     polyval(Rc, p) - cR + pqr[2])
            except:
                log_error("Could not parse hard-iron scale coefficients in '%s'" % lines[4], 'exc')
                # fall through - use the default closure
        return (abc, pqrc)
    except:
        log_error("Could not parse %s as abc/pqr line" % abc_pqr)
        return (None, None)

def compassTransform(abc, pqrc, pitchAD, roll_deg, pitch_deg, mag):
    """
    Tranforms mag to heading
    """
    m_pqr = zeros(3)
    p = zeros(3)
    m = zeros(3)

    roll = radians(roll_deg)
    pitch = radians(pitch_deg)
    
    # now we negate for to get into cal space convention
    m[0] = mag[0]    # cal equations are based on -Y and -Z field values
    m[1] = -mag[1]
    m[2] = -mag[2];

    # pqrc passed in is a closure that generates a pqr given pitchAD
    pqr = pqrc(pitchAD)
    for j in range(3):
        m_pqr[j] = m[j] - pqr[j]

    for i in range(3):
        p[i] = 0.0
        for j in range(3):
            p[i] += m_pqr[j]*abc[i*3 + j]

    cp = cos(pitch)
    cr = cos(roll)
    sp = sin(pitch)
    sr = sin(roll)
    magX = p[0]*cp - p[1]*sp*sr - p[2]*sp*cr
    magY = p[1]*cr - p[2]*sr

    heading = arctan2(magY, magX)
    if (heading < 0):
        heading += 2*pi

    return math.degrees(heading)
