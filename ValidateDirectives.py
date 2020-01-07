#! /usr/bin/env python

## 
## Copyright (c) 2012, 2013, 2020 by University of Washington.  All rights reserved.
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
import os, os.path
import sys
import time
import getopt
import BaseOpts
from BaseLog import *
from QC import * # for directives support

if __name__ == "__main__":
    # We are called as a normal python script from the command line
    retval = 1
    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()
    usage_string = "usage: %s [-v] --mission_dir <path_to_directives>"
    base_opts = BaseOpts.BaseOptions([], '', usage="%prog")
    base_opts.verbose = True # force -v
    BaseLogger("ValidateDirectives", base_opts)

    directives = ProfileDirectives(base_opts.mission_dir, '*') 
    drv_file_name = os.path.join(base_opts.mission_dir, 'sg_directives.txt')
    log_info("Checking directives in %s" % drv_file_name)
    directives.parse_file(drv_file_name)

    dive_directives = directives.dump_string() # any directives?
    if (dive_directives == ''):
        log_info("No directives found in %s" % drv_file_name)
        sys.exit(0)

    # initialize typical lists available before testing any loaded directives
    # These just have to be defined since the evaluations don't have to succeed
    directives.dive_depth  = []
    directives.climb_depth = []
    directives.data_points = []
    directives.glider_data_points = []
    directives.depth = []
    directives.glider_depth = []
    directives.time = []
    
    try:
        for fn in directives.drv_predicates:
            directives.eval_function(fn)

        for fn in directives.drv_functions:
            directives.eval_function(fn)

    except Exception:
        log_critical("Unhandled exception in ValidateDirectives -- exiting")
    sys.exit(retval)
    
