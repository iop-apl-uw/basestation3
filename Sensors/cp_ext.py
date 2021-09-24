#! /usr/bin/env python

##
## Copyright (c) 2010, 2011, 2012, 2013, 2016, 2017, 2018, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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
Current Profiles (ADCP)  basestation sensor extension
"""

import sys
import os
import re
import time
import collections
import shutil
import traceback
import string, math
import array as arr
import Utils
from BaseLog import *
from BaseNetCDF import *
from scipy.io import loadmat
# Globals
cp_prefix = "cp"

nc_cp_data_info = 'cp_data_info' 
nc_cp_cell_info = 'cp_cell_info' 

def init_logger(module_name, init_dict=None):
    """
    init_logger
    Input:
         module_name - fully qualified path to the name of this module

    Returns:
        -1 - error in processing
        0 - success (data found and processed)
    """

    log_debug("module_name:%s" % module_name)

    if(init_dict == None):
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    register_sensor_dim_info(nc_cp_data_info, 'cp_data_point', None, True, None)
    register_sensor_dim_info(nc_cp_cell_info, 'cp_cell_data_point', None, True, None)
    
    init_dict[module_name] = {'logger_prefix' : cp_prefix,
                              'eng_file_reader' : eng_file_reader,
                              'known_files' : ['NCP_GO'],
                              'known_mailer_tags' : ['mat', "ad2cp"],
                              'netcdf_metadata_adds' : {
                                  'log_CP_RECORDABOVE': [False, 'd', {'description':'Depth above above which data is recorded', 'units':'meters'}, nc_scalar],
                                  'log_CP_PROFILE': [False, 'd', {'description':'Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
                                  'log_CP_XMITPROFILE': [False, 'd', {'description':'Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
                                  'log_CP_UPLOADMAX': [False, 'd', {'description':'Max size of file to upload'}, nc_scalar],
                                  'log_CP_FREE': [False, 'd', {'description':'Free diskspace on CP, in bytes'}, nc_scalar],
                                  'log_CP_STARTS': [False, 'd', {'description':''}, nc_scalar],
                                  'log_CP_NDIVE': [False, 'd', {'description':'Dive multiplier for CP'}, nc_scalar],
                                  'cp_pressure': [False, 'd', {'standard_name':'sea_water_pressure', 'units':'dbar', 'description':'Pressure as reported by the CP'}, (nc_cp_data_info,)],
                                  'cp_heading': [False, 'd', {'standard_name':'heading', 'units':'degrees', 'description':' '}, (nc_cp_data_info,)],
                                  'cp_pitch': [False, 'd', {'standard_name':'pitch', 'units':'degrees', 'description':' '}, (nc_cp_data_info,)],
                                  'cp_roll': [False, 'd', {'standard_name':'roll', 'units':'degrees', 'description':' '}, (nc_cp_data_info,)],
                                  'cp_temperature': [False, 'd', {'standard_name':'sea_water_temperature', 'units':'degrees_Celsius', 'description':'Termperature as reported by the CP'}, (nc_cp_data_info,)],
                                  'cp_magX': [False, 'd', {'units':'counts', 'description':'Magnetometer X'}, (nc_cp_data_info,)],
                                  'cp_magY': [False, 'd', {'units':'counts', 'description':'Magnetometer Y'}, (nc_cp_data_info,)],
                                  'cp_magZ': [False, 'd', {'units':'counts', 'description':'Magnetometer Z'}, (nc_cp_data_info,)],
                                  'cp_time': [False, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'CP time in GMT epoch format'}, (nc_cp_data_info,)],
                                  'cp_velX': [False, 'd', {'units':'???', 'description':'Velocity along X-axis'}, (nc_cp_data_info, nc_cp_cell_info)],
                                  'cp_velY': [False, 'd', {'units':'???', 'description':'Velocity along Y-axis'}, (nc_cp_data_info, nc_cp_cell_info)],
                                  'cp_velZ': [False, 'd', {'units':'???', 'description':'Velocity along Z-azis'}, (nc_cp_data_info, nc_cp_cell_info)],
                              }
    }
    
    return 0

def process_data_files(base_opts, module_name, fc, processed_logger_eng_files, processed_logger_other_files):
    """Processes other files 
    Input:
        base_opts - options object
        module_name - 
        fc - file code object for file being processed
        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    log_info("Processing %s to %s" % (fc.full_filename(), fc.mk_base_engfile_name()))
    if(fc.is_down_data() or fc.is_up_data()):
        # The uploaded file in this case is an actual Nortek file.
        # Copy to the correct extension
        ad2cpfile = fc.mk_base_engfile_name().replace(".eng", ".ad2cp")
        shutil.copy(fc.full_filename(), ad2cpfile)
        processed_logger_other_files.append(ad2cpfile)

        # Run the convertor to create a .mat file
        convertor = os.path.join(os.path.join(base_opts.basestation_directory, "Sensors"), "ad2cpMAT")
        if not os.path.isfile(convertor):
            log_error("Convertor %s does not exits - not processing %s" % (convertor, fc.full_filename()))
            return 1
        if not os.access(convertor, os.X_OK):
            log_error("Convertor (%s) is not marked as executable - not processing %s" % (convertor, fc.full_filename()))
            return 1
            
        matfile = fc.mk_base_engfile_name().replace(".eng", ".mat")
        
        cmdline = "%s %s %s" % (convertor, fc.full_filename(), matfile)
        log_info("Running %s" % cmdline)
        try:
            (sts, fo) = Utils.run_cmd_shell(cmdline)
        except:
            log_error("Error running %s" % cmdline, 'exc')
            return 1

        shutil.copy(matfile, fc.mk_base_engfile_name())
        processed_logger_eng_files.append(fc.mk_base_engfile_name())
        processed_logger_other_files.append(matfile)
    return 0

def eng_file_reader(eng_files, nc_info_d, calib_consts):
    """ Reads the eng files for adcp instruments

    Input:
        eng_files - list of eng_file that contain one class of file
        nc_info_d - netcdf dictionary
        calib_consts - calib conts dictionary

    Returns:
        ret_list - list of (variable,data) tuples
        netcdf_dict - dictionary of optional netcdf variable additions

    """
    netcdf_dict = {}
    ret_list = []


    for fn in eng_files:
        cast = fn['cast']
        filename = fn['file_name']

        try:
            mf = loadmat(filename)
        except:
            log_error("Unable to load %s" % filename, 'exc')
            continue

        for col_name in ('time', 'pressure', 'pitch', 'roll', 'heading', 'temperature', 'magX', 'magY', 'magZ'):
            nc_var_name = "cp_%s" % col_name
            if col_name not in mf:
                log_info("No column named %s in %s - skipping add to netcdf" % (col_name, filename))
                continue
            ret_list.append((nc_var_name, mf[col_name][:, 0]))
            try:
                md = nc_var_metadata[nc_var_name]
            except KeyError:
                log_info("Metadata for data %s was not pre-declared" % nc_var_name)
                # Since it is raw data and load_dive_profile_data() will create this info
                # as well, we let MMT and MMP handle it
                netcdf_dict[nc_var_name] = form_nc_metadata(None, False, 'd', {}, (nc_eng_file_mdp_info,))

        for col_name in ('velX', 'velY', 'velZ'):
            nc_var_name = "cp_%s" % col_name
            if col_name not in mf:
                log_info("No column named %s in %s - skipping add to netcdf" % (col_name, filename))
                continue
            data = mf[col_name].transpose()
            ret_list.append((nc_var_name, data ))
            assign_dim_info_size(nc_info_d, nc_cp_cell_info, data.shape[1])
            try:
                md = nc_var_metadata[nc_var_name]
            except KeyError:
                log_info("Metadata for data %s was not pre-declared" % nc_var_name)
                # Since it is raw data and load_dive_profile_data() will create this info
                # as well, we let MMT and MMP handle it
                netcdf_dict[nc_var_name] = form_nc_metadata(None, False, 'd', {}, (nc_eng_file_mdp_info,))
            
            # Assign the cell size here
            
            #assign_dim_info_size(nc_info_d,"%s_row_info" % nc_var_name,spectra.shape[0]) # rows

    return ret_list, netcdf_dict

