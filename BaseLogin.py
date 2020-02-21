#! /usr/bin/env python

## 
## Copyright (c) 2011, 2012, 2015, 2016, 2020 by University of Washington.  All rights reserved.
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

"""Items to be done at glider login time
"""

import sys
import os
import time
import collections

import BaseOpts
import Sensors
from BaseLog import *
from Base import run_extension_script
from Base import process_extensions

def main(instrument_id=None, base_opts=None, sg_calib_file_name=None, dive_nc_file_names=None):
    """Basestation script invoked at glider login time

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    ret_val = 0

    if(base_opts is None):
        base_opts = BaseOpts.BaseOptions(sys.argv, 'n',
                                         usage="%prog [Options] ")
    BaseLogger("BaseLogin", base_opts) # initializes BaseLog

    args = BaseOpts.BaseOptions._args # positional arguments

    if(not base_opts.mission_dir):
        print((main.__doc__))
        return 1

    #log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    # Sensor extensions
    (init_dict, init_ret_val) = Sensors.init_extensions(base_opts)
    if(init_ret_val > 0):
        log_warning("Sensor initialization failed")

    # Run early enough to get into the upload list
    run_extension_script(os.path.join(base_opts.mission_dir, ".pre_login"), None)

    # Invoke extensions, if any
    process_extensions('.pre_extensions', base_opts,
                       None, None, None, None, None, None)

    existing_files = '{'
    base_files = {'targets':'T','science':'S', 'pdoscmds.bat':'P', 'tcm2mat.cal':'M'}
    for f in list(base_files.keys()):
        if(os.path.exists(os.path.join(base_opts.mission_dir, f))):
            existing_files = "%s%s" % (existing_files, base_files[f])

    # Now, the loggers
    for key in list(init_dict.keys()):
        d = init_dict[key]
        if('known_files' in d):
            for b in d['known_files']:
                if(os.path.exists(os.path.join(base_opts.mission_dir, b))):
                    existing_files = "%s,%s" % (existing_files, b)
                    
    existing_files = "%s}" % existing_files

    log_info("Existing files = %s" % existing_files)

    upload_files_name = os.path.join(base_opts.mission_dir, 'upload_files')


    try:
        fo = open(upload_files_name, "w")
    except:
        log_error("Unable to open %s for write" % upload_files_name)
        ret_val = 1
    else:
        fo.write("echo \"%s\"\n" % existing_files)
        fo.close()

    #log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))



    return ret_val

if __name__ == "__main__":
    os.environ['TZ'] = 'UTC'
    time.tzset()

    retval = main()
    sys.exit(retval)
    
