#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2020 by University of Washington.  All rights reserved.
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
Common set of pathnames and constants for python basestation code
"""

import os

# Version 65
raw_data_file_prefix = 'A'
raw_gzip_file_prefix = 'Y'
archived_data_file_prefix = 'Z' # results of bogue.pl
processed_prefix     = 'p'
processed_data_file_extension = '.asc'
GPS_prefix       = 'GPS'
encoded_GPS_prefix = 'G'
FLASH_basename   = 'FLASH'
FLASH_gz_basename= 'FLASH.gz'
PARMS_basename   = 'parms'
PARMS_gz_basename= 'parms.gz'

logfiles         = 'logfiles'
comm_log	  = 'comm.log'
convert_log      = 'convert.log'
this_convert_log = 'this_convert.log'
convert_lock     = '.convert_lock' 

gliders_group = 'Gliders' 

# ONLY LINUX/UNIX SUPPORT, NO WIN32!

src_dir = os.path.dirname(__file__) # ASSUMES this module is in the source directory
bin_dir = "/usr/local/bin"
python_exe = "/usr/local/bin/env python"
intermediate_prefix = "a"
delcmd = "rm -f"
copycmd = "cp -f"
GET = "/usr/bin/GET" 
temp_dir = "/usr/local/tmp"

binasc  = bin_dir + "/binasc" # The new universal elixir
strip1a = bin_dir + "/strip1a"
glunzipcmd = bin_dir + "/glzip /d" # Glider unzip code, based on the glider code and handles explicit output filenames
glzipcmd = bin_dir + "/glzip /c" # Glider zip code, based on the glider code and handles explicit output filenames
md5cmd = bin_dir + "/glmd5" # compute md5 signature

# TODO: list only python modules as they become available
convert   = python_exe + src_dir + "/Convert.py";
expunge = src_dir + "/ExpungeSecrets.py";
# asc2eng = perl_exe  + src_dir + "/asc2eng.pl";
# bogue   = perl_exe  + src_dir + "/bogue.pl";
# create_logfiles = perl_exe  + src_dir + "/logfile_cache.pl";
# fix_24V_amps = perl_exe + src_dir + "/fix_24V_amps.pl";
# expand_dat = perl_exe  + $src_dir + "/expand_dat.pl";

# Setup globals for processing a basename
#sub set_instrument_id_and_dive_tag {
#    my ($basename) = @_;
#    # All file names are in the form [A|Y]XXXDDDD.*
#    $gzipped = (substr($basename,0,1) eq $raw_gzip_file_prefix);
#    $_ = $instrument_id = substr($basename,1,3); # XXX (set globally)
#    return 0 unless /\d\d\d/; # Ensure XXX
#    $dive_tag = substr($basename,4,4); # DDDD
#    $_ = $dive_tag;
#    return 0 unless /\d\d\d\d/; # Ensure DDDD
#
#    $dive_number = $dive_tag;
#    $dive_number =~ s/^0*//g;	# Avoid octal problems
#    $dive_number = 0 if $dive_number eq '';
#    $actual_dive_number = $dive_number; # What we copy to (assume the same)
#    return 1;
#}
#1;


