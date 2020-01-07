#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2009, 2012, 2013, 2015, 2016, 2018 by University of Washington.  All rights reserved.
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

"""Routines for dumping netCDF files produced by Basestation2
"""

#TODO - check SigmaT against website

import sys
import os
import Utils
from scipy.io import netcdf
from numpy import *
import time
import glob
import BaseOpts
from BaseLog import *
import FileMgr
import MakeDiveProfiles
import BaseGZip

def main(instrument_id=None, base_opts=None, sg_calib_file_name=None, dive_nc_file_names=None, nc_files_created=None,
         processed_other_files=None, known_mailer_tags=None, known_ftp_tags=None):
    """Basestation extension for creating simplified netCDF files

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if(base_opts is None):
        base_opts = BaseOpts.BaseOptions(sys.argv, 'g',
                                         usage="%prog [Options] ")
    BaseLogger("SimpleNetCDF", base_opts) # initializes BaseLog

    args = BaseOpts.BaseOptions._args # positional arguments

    log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    if(not base_opts.mission_dir and len(args) == 1):
        dive_nc_file_names = [os.path.expanduser(args[0])]
    else:
        if(nc_files_created is not None):
            dive_nc_file_names = nc_files_created
        elif(not dive_nc_file_names):
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)

        netcdf_in_filename = dive_nc_file_name
        head, tail = os.path.splitext(netcdf_in_filename)
        netcdf_out_filename = "%s.ncf" % (head)

        log_info("Output file = %s" % netcdf_out_filename)

        if(not os.path.exists(netcdf_in_filename)):
            sys.stderr.write("File %s does not exists\n" % netcdf_in_filename)
            return 1

        nci = Utils.open_netcdf_file(netcdf_in_filename, 'r', mmap=False)
        nco = Utils.open_netcdf_file(netcdf_out_filename, 'w', mmap=False)

        nc_vars = ('temperature_qc', 'temperature',
                   'salinity_qc', 'salinity',
                   'ctd_depth', 'ctd_time', 'longitude', 'latitude',
                   'aa4831_O2', 'aa4831_time', 'aanderaa4831_dissolved_oxygen',
                   'ocr504i_chan1', 'ocr504i_chan2', 'ocr504i_chan3', 'ocr504i_chan4', 'ocr504i_time',
                   'wlbb2fl_sig470nm_adjusted', 'wlbb2fl_sig700nm_adjusted', 'wlbb2fl_sig695nm_adjusted', 'wlbb2fl_time',
                   'time', 'eng_rollAng', 'eng_pitchAng')
        nc_dims = ('ctd_data_point', 'aa4831_data_point', 'scicon_irrad_ocr504i_data_point', 'wlbb2fl_data_point', 'sg_data_point')

        for d in nc_dims:
            nco.createDimension(d, nci.dimensions[d])

        for v in nc_vars:
            nco.variables[v] =  nci.variables[v]

        # Copy all the attributes
        for a in list(nci._attributes.keys()):
            nco.__setattr__(a, nci._attributes[a])

        nci.close()
        nco.sync()
        nco.close()

        if(processed_other_files is not None):
           processed_other_files.append(netcdf_out_filename)

    log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
    return 0

if __name__ == "__main__":
    retval = main()
    sys.exit(retval)
