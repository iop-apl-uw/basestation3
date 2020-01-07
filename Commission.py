#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2012, 2013, 2015 by University of Washington.  All rights reserved.
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
Commission.py: Sets up a new glider account on a basestation.

**NOTES**
- You must run as root

"""

import os
import subprocess
import sys
import shutil
import BaseOpts
from BaseLog import *

def syscall(command):
    print("Executing %s" % command)
    try:
        retcode = subprocess.call(command, shell=True)
        if retcode < 0:
            print("Child %s was terminated by signal %d" % (command, -retcode), file=sys.stderr)
        elif retcode > 0:
            print("Child %s returned %d" % (command, retcode), file=sys.stderr)
    except OSError as e:
        print("Execution failed:", e, file=sys.stderr)

def generate_password(glider_id):
    if(glider_id % 2):
        pwd_template = "135791"
    else:
        pwd_template = "024680"
    glider_id_str = "%d" % glider_id
    password = "%s%s" % (glider_id_str, pwd_template[len(glider_id_str):6])
    return password

def main():
    """ Creates the user accounts and populates home directories for new gliders

    useage: Commission.py [options] glider_id
    
    where:
        glider_id - three digit glider id

    options:
        --version             show program's version number and exit
        -h, --help            show this help message and exit
        -c CONFIG, --config=CONFIG
                                      script configuration file
         --base_log=BASE_LOG   basestation log file, records all levels of notifications
         -v, --verbose         print status messages to stdout
         -q, --quiet           don't print status messages to stdout
         --debug               log/display debug messages
         --home_dir=HOME_DIR   home directory base, used by Commission.py
         --glider_password=GLIDER_PASSWORD
             glider password, used by Commission.py
         --glider_group=GLIDER_GROUP
             glider group, used by Commission.py
         --home_dir_group=HOME_DIR_GROUP
             group owner for glider home directory, used by Commission.py
    notes:
        You must be root to run this script

    returns:
        0 for success
        1 for failure
        
    raises:
        Any exceptions raised are considered critical errors and not expected
        
    """
    
    # Get options
    base_opts = BaseOpts.BaseOptions(sys.argv, 'c',
                                     usage="%prog [Options] <glider_id>"
                                     )
    BaseLogger("Commission", base_opts) # initializes BaseLog
    args = BaseOpts.BaseOptions._args # positional arguments

    if(len(args) < 1 or not args[0].isdigit()):
        print(main.__doc__)
        return 1

    glider_id = int(args[0])

    if (base_opts.home_dir is None): 
        glider_home_dir = "/home"
    else:
        glider_home_dir = base_opts.home_dir

    if (base_opts.glider_group is None):
        glider_group = "gliders"
    else:   
        glider_group = base_opts.glider_group
 
    sg000 = "sg000"

    if (base_opts.glider_password is None):
        pwd = generate_password(glider_id)
    else:
        pwd = base_opts.glider_password

    glider = "sg%03d" % glider_id

    glider_path = "%s/%s" % (glider_home_dir, glider)
    sg000_path  = "%s/%s" % (glider_home_dir, sg000)
    initial_files = (".login", ".logout", ".cshrc", ".pagers", ".urls", "cmdfile", "sg_calib_constants.m", ".hushlogin", ".extensions");
        
    # Adding "-g <group> -G <group>" forces the initial group (lowercase g) to 
    # be gliders rather than letting useradd create a new unique group
    syscall("/usr/sbin/useradd -d %s -c \"Seaglider %s\" -g %s -G %s -m -k %s %s" %
            (glider_path, glider_id, glider_group, glider_group, sg000_path, glider))
    syscall("chmod g+rwx,o+rx %s" % glider_path) # Let group members have full privies, read-only otherwise

    if (base_opts.home_dir_group is None):
        syscall("chgrp %s %s" % (glider_group, glider_path))
    else:
        syscall("chgrp %s %s" % (base_opts.home_dir_group, glider_path))

    for file_name in initial_files:
        full_file_name = os.path.join(sg000_path, file_name)
        full_dst_file_name = os.path.join(glider_path, file_name)
        shutil.copyfile(full_file_name, full_dst_file_name)
        syscall("chown %s %s" % (glider, full_dst_file_name))
    syscall("chown pilot %s/cmdfile" % glider_path)
    #syscall("echo %s | passwd %s --stdin" % (pwd, glider))
    syscall("echo %s:%s | chpasswd" % (glider, pwd))
    syscall("chsh -s /bin/csh %s" % glider)
    print("Account %s created in %s with password %s" % (glider, glider_path, pwd))
    return 0

if __name__ == "__main__":
    import time
    retval = 1
    
    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")
       
    sys.exit(retval)
