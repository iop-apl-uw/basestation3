#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2008, 2011, 2012, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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

"""Ver65.py: contains classes for handling version 65 files in a glider home
   directory
"""

import glob
import os
import BaseOpts
from BaseLog import *
import Utils
import re
import string
import shutil
import stat

def ver_65_to_ver_66_filename(f_name):
    o_name = None
    
    # TODO - Leaving A and X out for the moment - this works for the basestation files only
    # Need to fix A and X files - A1330001.DSK is the test case
        
    if(f_name[0:1] == "Y" or f_name[0:1] == "Z"):
        compress_char = "z"
    elif(f_name[0:1] == "A"):
        compress_char = "u"
    else:
        #log_debug("Unknown file char [%s] - skipping" % f_name[0:1])
        return o_name

    log_debug("Processing %s" % f_name)

    if(f_name[9:10] == "L"):
        type_char = "l"
    elif(f_name[9:10] == "D"):
        type_char = "d"
    elif(f_name[9:10] == "K"):
        type_char = "k"
    elif(f_name[9:10] == "T"):
        if(f_name[0:1] == "Y" or f_name[0:1] == "X"):
            compress_char = "g"
        else:
            compress_char = "t"
        type_char = "k" # We don't really know what we are dealing with here
                        # so this is as good as any
    else:
        log_error("Don't know what the type is for %s - skipping" % fname)
        return o_name

    dive_num = int(f_name[4:8])

    if(f_name[10:12].isdigit()):
        counter_num = int(f_name[10:12])
        o_name = "sg%04d%c%c.x%02d" % (dive_num, type_char, compress_char, counter_num)
    else:
        o_name = "sg%04d%c%c.x00" % (dive_num, type_char, compress_char)

    return o_name
    
def get_ver_65_conv_file_names(homedir):
    """Builds a list of all version 65 files in a given directory
       that are suiteable for conversion
    """
    #for match in glob.glob(os.path.join(homedir, "sg[0-9][0-9][0-9][0-9][ldkp][uztg].[xar]??")): # seaglider
    ver_65_conv_file_names = []
    for match in glob.glob(os.path.join(homedir, "[AZY][0-9][0-9][0-9][0-9][0-9][0-9][0-9].[LDTK]??")): # seaglider
            ver_65_conv_file_names.append(match)
    if(ver_65_conv_file_names):
        ver_65_conv_file_names.sort()
    return ver_65_conv_file_names

def select_basestation_files(file_names):
    """Given a list of files, weed out the Y versions if there is a Z version in the list
       This is done for the case where the files are coming not directly from a glider, but from
       an older basestation, which would back up the transmitted files to a Z form, before stripping
       and Bogue processing the Y version - thus changing it.
    """
    new_file_names = list(file_names)
    for i in range(len(file_names)):
        path, f_name = os.path.split(file_names[i])
        if(f_name[0:1] == "Z"):
            y_name = "%c%s" % ("Y", f_name[1:12])
            y_full_name = os.path.join(path, y_name)
            if(new_file_names.count(y_full_name)):
               log_debug("Removing %s from list" % y_full_name)
               new_file_names.remove(y_full_name)

    return new_file_names
            
            
def conv_ver_65_files(destdir, file_names):
    
    # Copy files to new name
    for file_name in file_names:
        f_name = os.path.basename(file_name)
        log_debug("Processing %s" % f_name)

        o_name = ver_65_to_ver_66_filename(f_name)
        if o_name is None: # eg, file is "G*", v66 doesn't care about this kind of file
             #o_name = f_name
             log_info("%s is the same as %s - skipping" % (o_name, f_name))
             return
            
        out_name = os.path.join(destdir, o_name)
        # The test for "Z" is for running against home directories that have been previously converted
        # by the old basestation code.  See comment above for further details
        if(not os.path.exists(out_name) or (os.path.getmtime(file_name) >= os.path.getmtime(out_name))):
            log_info("Copying %s to %s" % (file_name, out_name))
            shutil.copyfile(file_name, out_name)
            os.chmod(out_name, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
            os.utime(out_name, None)
        

def main():
    """ main - main entry point
    """
    base_opts = BaseOpts.BaseOptions(sys.argv)
    BaseLogger(base_opts) # initializes BaseLog

    file_names = get_ver_65_conv_file_names(base_opts.mission_dir)
    if(file_names):
        for i in file_names:
            log_debug("File = %s" % i)
    else:
        log_warning("No version 65 files found")
        return 0

    file_names = select_basestation_files(file_names)
    for i in file_names:
        log_debug("File = %s" % i)
    
    conv_ver_65_files(base_opts.mission_dir, file_names)
    
    return 0

if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
