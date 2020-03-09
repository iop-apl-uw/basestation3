#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2008, 2009, 2011, 2012, 2014, 2015, 2018, 2019, 2020 by University of Washington.  All rights reserved.
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

"""
CalibConst.py: seaglider calibration constants (matlab file) parser
"""

import string
import sys

import re

import BaseOpts
from BaseLog import *
from BaseNetCDF import *
from Const import *
import Utils


def getSGCalibrationConstants(calib_filename, suppress_required_error=False) :
    """ Parses a matlab .m file for name = value pairs
    Returns a dictionary of the constant names and values
    """


    # helpers

    def rangeCheck(key, value):
        """ Checks to see whether value lies in min/max range for given key.
        Ranges are hardcoded.
        Returns given key, value pair if within check; key value=None otherwise.
    
        Called by getSGCalibrationConstants, expects error(msg) to be defined.
        """
        if key == "example_key" :
            if value < 0 : # min
                log_error(str(key) + ":" + str(value) + " is below minimum value")
                return None
            elif value > 10 : # max
                log_error(str(key) + ":" + str(value) + " is above maximum value")
                return None
        
        return value

       
    # constants
    required_keys = [ 'id_str',
                      'mission_title',
                      'mass',
                      ]
    
    calib_consts = {} # initialize calib_consts to include empty values for required keys
    for i in required_keys:
        calib_consts[i] = None

    eq = re.compile(r'^([^=]+)=(.*)')
    comment = re.compile(r'%.*') # % and anything after it, to a newline
    bracket = re.compile(r'\[.*'); # a bracket
    override = re.compile(r'override\..*'); # e.g., override.RHO

    # open filename
    try:
        calib_file = open(calib_filename, "r")
    except:
        log_error("Unable to open file: " + calib_filename)
        return None
        
    # parse file : expect .m with  "name = value; %comment \n" lines
    eval_locals = {} # local results from evaluating key = value lines
    for line in calib_file.readlines():
        #log_debug("parsing: " + line)

        # remove line comments

        if comment.search(line):
            line, after = comment.split(line)
            #log_debug("skipping comment: " + after)

        # Handle lines like hd_a = 4.3e-3; hd_b = 2.4e-5; hd_c = 5.7e-6;
        for expr in line.split(';'):
            # handle name=value pairs

            if eq.search(expr):
                #log_debug("found pair: " + expr)
                left, key, value, right = eq.split(expr)
                key = key.strip() # remove whitespace
                if override.search(key):
                    # this skips any override struct assignments used for IOP
                    continue
                key = key.replace('.', '_') # CF1.4: Avoid invalid variable names from sg_calib_constants
                value = value.strip()
                value = value.strip('\'\"') # remove quotes from edges
                value.strip()
                if bracket.search(value):
                    # this skips even unbalanced []'s deliberately
                    # log_debug("skipping [] expression: " + expr)
                    continue

                nc_var_name = nc_sg_cal_prefix + key
                try:
                    md = nc_var_metadata[nc_var_name]
                    include_in_mission_profile, nc_data_type, meta_data_d, mdp_dim_info = md
                except KeyError:
                    # Unknown variable but be silent here; complain when writing
                    nc_data_type = None
                if nc_data_type == 'c':
                    pass # Known string is just fine
                else:
                    try:
                        # We take all numerics, declared or not...
                        value = float(eval(value, None, eval_locals))
                    except:
                        # Non-numeric value of an unknown variable
                        log_debug("Assuming %s is a string" % key) 
                    # Sometimes simple variables are defined that are used in later expressions in the M file...handle them
                    eval_locals[key] = value

                value = rangeCheck(key, value) # value will be None if fails range check
                calib_consts[key] = value

    calib_file.close()
    
    # Log an error if any of the required keys is missing
    
    missingKeys = None

    for key in required_keys:
        if calib_consts[key] is None:
            if missingKeys is None:
                missingKeys = []
            missingKeys.append(key)

    if missingKeys is not None and suppress_required_error is False:
        log_error("The following calibration constants are missing from %s: %s" % (calib_filename, str(missingKeys)))
    
    return calib_consts

def dump(in_filename, fo):
    """Dumps out the calib_consts dictionary constructed from a calibration constants matlab file 
    """
    print("Calibration constants extracted from: %s" % (in_filename), file=fo)
    
    calib_consts = getSGCalibrationConstants(in_filename)

    if calib_consts:
        for key, value in calib_consts.items():
            print("%s = %s (%s)" % (key, value, type(value)), file=fo)

if __name__ == "__main__":
    base_opts = BaseOpts.BaseOptions(sys.argv, 'a') # 'a' is temporary
    BaseLogger("CalibConst", base_opts) # initializes BaseLog
    args = base_opts.get_args()

    if (len(args)>0):
        dump(args[0], sys.stdout)
    else:
        print("Usage: CalibConst.py infile [options]")
        sys.exit(1)

    sys.exit(0)
