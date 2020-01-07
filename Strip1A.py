#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2012, 2020 by University of Washington.  All rights reserved.
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
Strip1A.py: Strips '1A's from files, called by basestation code
"""

import string
import sys
import os
import re
import shutil

import BaseOpts
from BaseLog import *

def strip1A(in_filename, out_filename, size=0):
    """strip1A makes a copy of source file, then truncates copy according to calling method.
    If source is a log files: caller must indicate size.
    If source is a data file: do not indicate size. strip1A will remove pairs of trailing 1As.

    Returns: 0 success, 1 for error

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    
    try:
        in_file = open(in_filename, 'r')
    except IOError as exception:
        log_error("Could not open %s for reading" % in_filename)
        return 1
    try:
        out_file = open(out_filename, 'w')
    except IOError as exception:
        log_error("Could not open %s for writing" % out_filename)
        return 1

    data = in_file.read()
    
    # Actual padding always comes in blocks of 128 bytes 
    # unless it is the last file in a series.  

    # For LOG FILES, the number of bytes can be odd or even.  In this case, we might
    # have, at worst, a singe 0x1a character at the end of the file.  You can deal with that
    # by passing the size parameter, in which case we copy up to that many bytes.
    # However, warn if we drop any non-padding bytes in the truncated tail.
    # (This can happen, e.g., if we pass a default fragment_size of 4kb but NFILEKB is set to 8kb).
    if size != 0:
        tail_size = len(data) - size;
        if (tail_size > 0):
            tail_padding_i_v = [i for i in range(size, len(data)) if data[i] == '\x1A']
            lost_data_size = tail_size - len(tail_padding_i_v)
            if (lost_data_size > 0): # if it isn't all padding, warn
                log_warning('Removing %d non-padding bytes from truncated %d-byte tail of %s' % (lost_data_size, tail_size, in_filename))
        # Write data as commanded
        out_file.write(data[0:size])

    # For DATA FILES we are guaranteed that the original file size is even (since the
    # data structures are and all the rest of the data are shorts).  Thus padding will
    # always be PAIRS of 0x1a characters.  And they will be at the end of the file.
    else:
        # The last place we saw non-padding chars
        strip1a_bytes = -1
        
        # Always look for pairs of 0x1a.
        # This prevents stripping valid singleton 0x1a chars in data blocks
        # which, yes, do happen with surprising regularity
        for i in range(0, len(data) - 1):
            if(data[i] == '\x1A' and data[i+1] == '\x1A'):
                if(strip1a_bytes < 0):
                    # Record the high water mark
                    strip1a_bytes = i
                else:
                    pass 
            else:
                # Reset the high water mark
                strip1a_bytes = -1

        if(strip1a_bytes < 0):
            # No bytes found to strip
            strip1a_bytes = len(data)
            
        log_debug("Len(%s) = 0x%x, strip size = 0x%x" % (in_filename, len(data), strip1a_bytes))
        out_file.write(data[0:strip1a_bytes])
        
    # Clean up
    out_file.close()
    in_file.close()
    return 0

if __name__ == "__main__":

    base_opts = BaseOpts.BaseOptions(sys.argv, 's',
                                     usage="%prog [Options] src_file, dst_file [size]")

    BaseLogger("Strip1A", base_opts) # initializes BaseLog
    args = BaseOpts.BaseOptions._args # positional arguments

    if (len(args)>2):
        strip1A(args[0], args[1], args[2])
    elif (len(args)==2):
        strip1A(args[0], args[1])
    else:
        log_error("Usage: Strip1A.py infile outfile [size] [options]")
        sys.exit(1)

    sys.exit(0)
