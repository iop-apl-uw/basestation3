#! /usr/bin/env python

##
## Copyright (c) 2010, 2011, 2012, 2013, 2015, 2017, 2018, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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

# Time sig to have millis broken outx
# Need to add netCDF metadata for scicon instruments - all is going to be from .cnf files

"""
SCICON basestation sensor extension
"""

import sys
from numpy import *
import os
import re
import time
import collections
import shutil
import scipy.interpolate
import Utils
from BaseLog import *
from BaseNetCDF import *
import DataFiles
import Sensors
from scipy.io import loadmat

import pdb

# Globals
scicon_prefix = "sc"
nc_depth_data_info = 'depth_data_info' # scicon pressure data from the glider
nc_auxcompass_data_info = 'auxCompass_data_info' # scicon
nc_auxb_data_info = 'auxB_data_info' # scicon

# adcp on the scicon
ad2cp_base = "ad2cp"
nc_ad2cp_data_info = '%s_data_info' % ad2cp_base
nc_ad2cp_data_dim = '%s_data_data_point' % ad2cp_base
nc_ad2cp_cell_info = '%s_cell_info' % ad2cp_base
nc_ad2cp_cell_dim = '%s_cell_data_point' % ad2cp_base

ad2cp_single_dim = ('time', 'pressure', 'pitch', 'roll', 'heading', 'temperature', 'battery')
ad2cp_multi_dim = ('velX', 'velY', 'velZ')
ad2cp_single_value = ('blanking', 'cellSize', 'soundspeed')

# Tuples
data_file_metadata =  collections.namedtuple('data_file_metadata', ['start_time', 'stop_time', 'samples', 'instrument', 'columns', 'scale_off', 'container', 'comment', 'sealevel'])
instrument_type = collections.namedtuple('instrument_type', ['instr_instance', 'instr_class'])
scale_off_type = collections.namedtuple('scale_off_type', ['scale', 'offset'])

def process_adcp_dat(base_opts, scicon_file, scicon_eng_file, processed_logger_eng_files, processed_logger_other_files):
    """Processes other files
    Input:
        base_opts - options object

        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    matfile = scicon_eng_file.replace(".eng", ".mat")
    # Run the convertor
    convertor = os.path.join(os.path.join(base_opts.basestation_directory, "Sensors"), "sc2mat")
    if not os.path.isfile(convertor):
        log_error("Convertor %s does not exits - not processing %s" % (convertor, scicon_file))
        return 1
    if not os.access(convertor, os.X_OK):
        log_error("Convertor (%s) is not marked as executable - not processing %s" % (convertor, scicon_file))
        return 1

    cmdline = "%s %s %s" % (convertor, scicon_file, matfile)
    log_info("Running %s" % cmdline)
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout = 10)
    except:
        log_error("Error running %s" % cmdline, 'exc')
        return 1

    if sts is None:
        log_error("Error running %s - timeout" % cmdline, 'exc', alert='CONVERSION_TIMEOUT')
        return 1

    shutil.copy(matfile, scicon_eng_file)
    processed_logger_eng_files.append(scicon_eng_file)
    processed_logger_other_files.append(matfile)
    return 0

def process_camfb_dat(base_opts, scicon_file, scicon_eng_file, processed_logger_eng_files, processed_logger_other_files):
    """Processes camfb data files
    Input:
        base_opts - options object

        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    nemafile = scicon_eng_file.replace(".eng", ".nema")
    fi = open(scicon_file, "r")
    fo = open(nemafile, "w")
    line_num = 0
    for ll in fi.readlines():
        line_num += 1
        if len(ll) < 2:
            continue
        if ll.startswith("% start:"):
            _, time_parts_str = ll.split(":", 1)
            time_parts = time_parts_str.split()

            if(int(time_parts[2]) - 100 < 0):
                year_part = int(time_parts[2])
            else:
                year_part = int(time_parts[2]) - 100

            sec_parts = time_parts[5].split('.')
            sec_part = sec_parts[0]
            if(len(sec_parts) == 2):
                _, dec_sec_part = math.modf(float(time_parts[5]))
            else:
                dec_sec_part = 0.0

            time_string = "%s %s %02d %s %s %s" % (time_parts[0], time_parts[1], year_part,
                                                   time_parts[3], time_parts[4], sec_part)
            start_time = time.mktime(Utils.fix_gps_rollover(time.strptime(time_string, "%m %d %y %H %M %S"))) + dec_sec_part
            continue
        elif ll.startswith("%"):
            continue
        else:
            splits = ll.split(' ', 1)
            try:
                tt = start_time + float(splits[0].rstrip().lstrip()) / 1000.
            except ValueError:
                log_error(f"Could not process {scicon_file} line {line_num} {ll}")
            else:
                fo.write("%.3f %s\n" % (tt, splits[1].rstrip()))

    processed_logger_other_files.append(nemafile)

    return 0

def process_ctx3_dat(base_opts, scicon_file, output_file, processed_logger_other_files):
    """Processes ctx3 compressed  data file
    Input:
        base_opts - options object

        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """

    convertor = os.path.join(os.path.join(base_opts.basestation_directory, "Sensors"), "x3decode_ts")
    if not os.path.isfile(convertor):
        log_error("Convertor %s does not exits - not processing %s" % (convertor, scicon_file))
        return 1
    if not os.access(convertor, os.X_OK):
        log_error("Convertor (%s) is not marked as executable - not processing %s" % (convertor, scicon_file))
        return 1

    cmdline = "%s -i %s -o %s" % (convertor, scicon_file, output_file)
    log_info("Running %s" % cmdline)
    try:
        (sts, fo) = Utils.run_cmd_shell(cmdline, timeout = 10)
    except:
        log_error("Error running %s" % cmdline, 'exc')
        return 1

    if sts is None:
        log_error("Error running %s - timeout" % cmdline, 'exc', alert='CONVERSION_TIMEOUT')
        return 1

    processed_logger_other_files.append(output_file)
    return 0

def init_logger(module_name, init_dict=None):
    """
    init_logger

    Returns:
        -1 - error in processing
        0 - success (data found and processed)
    """

    if(init_dict == None):
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    #register_sensor_dim_info(nc_depth_data_info, 'depth_data_point', 'depth_time', True, None)

    register_sensor_dim_info(nc_auxb_data_info, 'auxB_data_point', 'auxB_time', True, None)
    register_sensor_dim_info(nc_auxcompass_data_info, 'auxCompass_data_point', 'auxCompass_time', True, None)
    
    register_sensor_dim_info(nc_ad2cp_data_info, nc_ad2cp_data_dim, None, True, None)
    register_sensor_dim_info(nc_ad2cp_cell_info, nc_ad2cp_cell_dim, None, True, None)

    scicon_metadata_adds = {
        'log_SC_RECORDABOVE': [False, 'd', {'description':'Depth above above which data is recorded', 'units':'meters'}, nc_scalar],
        'log_SC_PROFILE': [False, 'd', {'description':'Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
        'log_SC_XMITPROFILE': [False, 'd', {'description':'Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
        'log_SC_FREEKB': [False, 'd', {'description':'Free diskspace on Scicon, in kBytes'}, nc_scalar],
        'log_SC_NDIVE': [False, 'd', {'description':'Dive multiplier for Scicon'}, nc_scalar],
        'sg_cal_QC_high_freq_noise': [False, 'i', {'description':'The smoothing window width (in samples) for QC noise on scicon'}, nc_scalar],

        # scicon supplies it's own pressure sensor readings
        # NOTE these are not presently included in MMT/MMP because their length isn't sg_np
        'depth_time': [True, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'Pressure sensor time in GMT epoch format'}, (nc_depth_data_info,)],
        'depth_depth': [False, 'd', {'standard_name':'depth', 'positive':'down', 'units':'cm', 'description':'Measured vertical distance below the surface'}, (nc_depth_data_info,)],
        'depth_ontime_a': [False, 'd', {'description':'depth total time turned on dive', 'units' : 'secs'}, nc_scalar],
        'depth_samples_a': [False, 'i', {'description':'depth total number of samples taken dive'}, nc_scalar],
        'depth_timeouts_a': [False, 'i', {'description':'depth total number of timeouts on dive'}, nc_scalar],
        'depth_ontime_b': [False, 'd', {'description':'depth total time turned on climb', 'units' : 'secs'}, nc_scalar],
        'depth_samples_b': [False, 'i', {'description':'depth total number of samples taken climb'}, nc_scalar],
        'depth_timeouts_b': [False, 'i', {'description':'depth total number of timeouts on climb'}, nc_scalar],

        # adcp on scicon
        'ad2cp_pressure': [False, 'd', {'standard_name':'sea_water_pressure', 'units':'dbar', 'description':'Pressure as reported by the CP'}, (nc_ad2cp_data_info,)],
        'ad2cp_heading': [False, 'd', {'standard_name':'heading', 'units':'degrees', 'description':' '}, (nc_ad2cp_data_info,)],
        'ad2cp_pitch': [False, 'd', {'standard_name':'pitch', 'units':'degrees', 'description':' '}, (nc_ad2cp_data_info,)],
        'ad2cp_roll': [False, 'd', {'standard_name':'roll', 'units':'degrees', 'description':' '}, (nc_ad2cp_data_info,)],
        'ad2cp_temperature': [False, 'd', {'standard_name':'sea_water_temperature', 'units':'degrees_Celsius', 'description':'Termperature as reported by the CP'}, (nc_ad2cp_data_info,)],
        'ad2cp_time': [False, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'CP time in GMT epoch format'}, (nc_ad2cp_data_info,)],
        'ad2cp_battery': [False, 'd', {'standard_name':'voltage', 'units':'volts', 'description':'Obverved average battery volgate'}, (nc_ad2cp_data_info,)],
        'ad2cp_velX': [False, 'd', {'units':'m/s', 'description':'Velocity along X-axis'}, (nc_ad2cp_data_info, nc_ad2cp_cell_info)],
        'ad2cp_velY': [False, 'd', {'units':'m/s', 'description':'Velocity along Y-axis'}, (nc_ad2cp_data_info, nc_ad2cp_cell_info)],
        'ad2cp_velZ': [False, 'd', {'units':'m/s', 'description':'Velocity along Z-azis'}, (nc_ad2cp_data_info, nc_ad2cp_cell_info)],
        'ad2cp_blanking': [False, 'd', {'description':'Blanking distance', 'units':'cm'}, nc_scalar],
        'ad2cp_cellSize': [False, 'd', {'description':'Size of cells', 'units':'mm'}, nc_scalar],
        'ad2cp_soundspeed': [False, 'd', {'description':'Assumed sound speed', 'units':'m/s'}, nc_scalar],
    }

    # Aux compass/pressure sensor
    for auxname, aux_data_info in (('auxCompass', nc_auxcompass_data_info), ('auxB', nc_auxb_data_info)):
        scicon_metadata_adds[f'{auxname}_hdg'] = [True, 'd', {'standard_name':'heading', 'units':'degrees', 'description':' '}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_pit'] = [True, 'd', {'standard_name':'pitch', 'units':'degrees', 'description':' '}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_rol'] = [True, 'd', {'standard_name':'roll', 'units':'degrees', 'description':' '}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_Mx'] = [False, 'd', {'units':'counts', 'description':'Magnetometer X'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_My'] = [False, 'd', {'units':'counts', 'description':'Magnetometer Y'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_Mz'] = [False, 'd', {'units':'counts', 'description':'Magnetometer Z'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_Ax'] = [False, 'd', {'units':'counts', 'description':'Accelerometer X'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_Ay'] = [False, 'd', {'units':'counts', 'description':'Accelerometer Y'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_Az'] = [False, 'd', {'units':'counts', 'description':'Accelerometer Z'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_pressureCounts'] = [False, 'd', {'units':'counts', 'description':'Uncorrected sea-water pressure in instruments counts'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_press'] = [True, 'd', {'standard_name':'sea_water_pressure', 'units':'dbar', 'description':'Uncorrected sea-water pressure'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_depth'] = [True, 'd', {'standard_name':'depth', 'axis':'Z', 'units':'meters', 'positive':'down', 'description':'Depth below the surface, corrected for average latitude'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_time'] = [True, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'Pressure sensor time in GMT epoch format'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_xform'] = [False, 'c', {'description':f'{auxname} Accelerometer scaling matrix and offset '}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_tcm2mat'] = [False, 'c', {'description':f'{auxname} Pitch/Roll coefficients, Magnetometer scaling matrix and offset'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_pressure'] = [False, 'c', {'description':f'{auxname} sea-level slope (psi/AD) and offset (counts)'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_pressureTemp'] = [False, 'c', {'description':f'{auxname} pressure sensor temperature', 'units' : 'degrees_Celsius'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_internalTemp'] = [False, 'c', {'description':f'{auxname} interernal temperature', 'units' : 'degrees_Celsius'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_temperature'] = [False, 'c', {'description':f'{auxname} interernal temperature', 'units' : 'degrees_Celsius'}, (aux_data_info,)]
        scicon_metadata_adds[f'{auxname}_ontime_a'] = [False, 'd', {'description':f'{auxname} total time turned on dive', 'units' : 'secs'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_samples_a'] = [False, 'i', {'description':f'{auxname} total number of samples taken dive'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_timeouts_a'] = [False, 'i', {'description':f'{auxname} total time turned samples timedout on dive', 'units' : 'secs'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_ontime_b'] = [False, 'd', {'description':f'{auxname} total time turned on climb', 'units' : 'secs'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_samples_b'] = [False, 'i', {'description':f'{auxname} total number of samples taken climb'}, nc_scalar]
        scicon_metadata_adds[f'{auxname}_timeouts_b'] = [False, 'i', {'description':f'{auxname} total time turned samples timedout on climb', 'units' : 'secs'}, nc_scalar]
        scicon_metadata_adds[f'sg_cal_{auxname}_coeffhex'] = [False, 'c', {'description':f'{auxname} coefficients'}, nc_scalar]
        scicon_metadata_adds[f'sg_cal_{auxname}_abc'] = [False, 'c', {'description':f'{auxname} soft-iron correction'}, nc_scalar]
        scicon_metadata_adds[f'sg_cal_{auxname}_pqr'] = [False, 'c', {'description':f'{auxname} hard-iron correction'}, nc_scalar]
        

    init_dict[module_name] = {'logger_prefix' : scicon_prefix,
                              'strip_files' : True,
                              'eng_file_reader' : eng_file_reader,
                              'known_files' : ['scicon.sch', 'scicon.ins', 'scicon.att', 'scicon.tcm'],
                              'netcdf_metadata_adds' : scicon_metadata_adds,
                              }

    return 0

def process_tar_members(base_opts, module_name, fc, scicon_file_list, processed_logger_eng_files, processed_logger_other_files):
    """Processes files uploaded in the tarball

    Returns:
    0 for success
    1 for error
    """
    ret_val = 0

    base_name = None

    for scicon_file in scicon_file_list:
        if(base_name == None):
            head, tail = os.path.split(scicon_file)
            base_name = "%s/p%s%03d%04d%s" % (head, scicon_prefix, fc._instrument_id, fc.dive_number(), fc.up_down_data())
            log_info("Processing data for %s" % base_name)

        _, tail = os.path.split(scicon_file)
        if tail == "ctx3.dat":
            # If this ends up coming from a RBR, we'll need more data in the
            # .dat file
            if(process_ctx3_dat(base_opts, scicon_file, f"{base_name}_sbect_ts.profile", processed_logger_other_files)):
                log_error("Error processing %s" % scicon_file)
                ret_val = 1
            continue

        head, tail = os.path.splitext(scicon_file)
        if(tail.lower() == '.dat'):
            df_meta, _ = extract_file_metadata(scicon_file)
            if(df_meta == None or df_meta.instrument == None):
                log_error("Could not process %s - skipping" % scicon_file)
                ret_val = 1
                continue

            if(df_meta.instrument.instr_class == None or df_meta.instrument.instr_instance == None):
                log_error("Could not process %s due to missing instrument class or instrument instance field - skipping" % scicon_file)
                ret_val = 1
                continue

            scicon_eng_file = "%s_%s_%s.eng" % (base_name, df_meta.instrument.instr_class, df_meta.instrument.instr_instance)

            _, ttail = os.path.split(scicon_file)
            hhead, _ = os.path.splitext(ttail)
            if(hhead == 'ad2cp'):
                if(process_adcp_dat(base_opts, scicon_file, scicon_eng_file, processed_logger_eng_files, processed_logger_other_files)):
                    log_error("Error converting %s to %s" % (scicon_file, scicon_eng_file))
                    ret_val = 1
                    continue
            elif hhead == "camfb":
                if(process_camfb_dat(base_opts, scicon_file, scicon_eng_file, processed_logger_eng_files, processed_logger_other_files)):
                    log_error("Error processing %s" % scicon_file)
                    ret_val = 1
                    continue
            else:
                if(ConvertDatToEng(scicon_file, scicon_eng_file, df_meta, base_opts)):
                    log_error("Error converting %s to %s" % (scicon_file, scicon_eng_file))
                    ret_val = 1
                    continue
                processed_logger_eng_files.append(scicon_eng_file)

    return ret_val

def extract_file_metadata(inp_file_name):
    """
    Extracts the meta data from a dat file
    Returns:
        Success:
            Dictionary of meta data
            list of (variable,data) tuples for netcdf adds of non-standard data found in the header
        Failure:
            None,None

    """
    try:
        inp_file = open(inp_file_name, "rb")
    except:
        log_error("Unable to open %s" % inp_file_name)
        return None, None

    column_pattern = r"(?P<name>.*?)\((?P<scale>[-\d]*?),(?P<offset>[-\d]*?)\)"
    n_groups = 3

    first_line = True

    start_time = None
    stop_time = None
    samples = None
    instrument = None
    columns = None
    scale_off = None
    container = None
    comment = None
    sealevel = None

    ret_list = []

    line_count = 0
    for raw_line in inp_file:
        line_count += 1
        try:
            raw_line = raw_line.decode('utf-8')
        except UnicodeDecodeError:
            # Lots of reasons for this - mixed binary and text files a leading cause
            log_debug(f"Could not decode {inp_file_name} line {line_count} - skipping")
            continue

        if(raw_line[0] == '%'):
            raw_strs = raw_line.split(":", 1)
            raw_strs[0] = raw_strs[0].replace('% ', '%')
            if(raw_strs[0] == '%instrument'):
                parts = raw_strs[1].split()
                instrument = instrument_type(parts[0], parts[1])
            elif(raw_strs[0] == '%columns'):
                scale_off = []
                columns = ''
                # This could be a .dat or .eng format - try dat
                for col in raw_strs[1].split():
                    values = re.search(column_pattern, col)
                    if(values and len(values.groupdict()) == n_groups):
                        v = values.groupdict()
                        scale_off.append(scale_off_type(float(v['scale']), float(v['offset'])))
                        columns = "%s %s" % (columns, v['name'])
                    else:
                        # Eng format
                        columns = raw_strs[1].rstrip().lstrip()
                        break
            if(raw_strs[0] == '%container'):
                container = raw_strs[1].rstrip().lstrip()
            if(raw_strs[0] == '%comment'):
                comment = raw_strs[1].rstrip().lstrip()
            if(raw_strs[0] == '%samples'):
                samples = int(raw_strs[1])
            if(raw_strs[0] == '%sealevel'):
                sealevel = int(raw_strs[1])
            if(raw_strs[0] == '%xform' or raw_strs[0] == '%tcm2mat' or raw_strs[0] == '%pressure'):
                ret_list.append(('auxCompass_%s' % raw_strs[0][1:], raw_strs[1].strip()))
            elif(raw_strs[0] == "%start" or raw_strs[0] == "%stop"):
                time_parts = raw_strs[1].split()
                if(int(time_parts[2]) - 100 < 0):
                    year_part = int(time_parts[2])
                else:
                    year_part = int(time_parts[2]) - 100

                sec_parts = time_parts[5].split('.')
                sec_part = sec_parts[0]
                if(len(sec_parts) == 2):
                    _, dec_sec_part = math.modf(float(time_parts[5]))
                else:
                    dec_sec_part = 0.0

                time_string = "%s %s %02d %s %s %s" % (time_parts[0], time_parts[1], year_part,
                                                       time_parts[3], time_parts[4], sec_part)

                if(raw_strs[0] == "%start"):
                    start_time = time.mktime(Utils.fix_gps_rollover(time.strptime(time_string, "%m %d %y %H %M %S"))) + dec_sec_part
                else:
                    stop_time = time.mktime(Utils.fix_gps_rollover(time.strptime(time_string, "%m %d %y %H %M %S"))) + dec_sec_part
            elif raw_strs[0] == '%ontime':
                if not Utils.is_float(raw_strs[1].strip()):
                    log_warning("Could not convert %s to float - skipping" % raw_strs[1].strip())
                else:
                    if container is not None and (container[-1] in ('a', 'b')):
                        instrument_name = [instrument.instr_class]
                        Sensors.process_sensor_extensions('remap_instrument_names', instrument_name)
                        ret_list.append(('%s_%s_%s' % (instrument_name[0], raw_strs[0][1:], container[-1]), float(raw_strs[1].strip()) / 1000.))
                    else:
                        log_warning("Can't extract dive value from cotainer (%s)" % container)
            elif raw_strs[0] == '%samples' or raw_strs[0] == '%timeouts' or raw_strs[0] == '%errors':
                if not Utils.is_integer(raw_strs[1].strip()):
                    log_warning("Could not convert %s to int - skipping" % raw_strs[1].strip())
                else:
                    if container is not None and (container[-1] in ('a', 'b')):
                        instrument_name = [instrument.instr_class]
                        Sensors.process_sensor_extensions('remap_instrument_names', instrument_name)
                        ret_list.append(('%s_%s_%s' % (instrument_name[0], raw_strs[0][1:], container[-1]), int(raw_strs[1].strip())))
                    else:
                        log_warning("Can't extract dive value from cotainer (%s)" % container)

    # Create the output tuple
    return data_file_metadata(start_time, stop_time, samples, instrument, columns, scale_off, container, comment, sealevel), ret_list

def extract_file_data(inp_file_name):
    """
    Reads the data/eng file and returns columns of data

    Returns:
    None - error
    List of data vectors - success
    """
    try:
        inp_file = open(inp_file_name, "r")
    except:
        log_error("Unable to open %s" % inp_file_name)
        return None

    rows = []
    # Process the data
    for inp_line in inp_file:
        inp_line = inp_line.rstrip().rstrip()
        if(inp_line == "" or inp_line[0] == '%'):
            continue
        raw_strs = inp_line.split()
        row = []
        for i in range(len(raw_strs)):
            try:
                row.append(float64(raw_strs[i]))
            except:
                log_error("Problems converting [%s] to float from line [%s] (%s, line %d)"
                               % (raw_strs[i], inp_line, eng_filename, line_count))
                continue

        rows.append(row)

    if(not rows):
        return None

    tmp = array(rows, float64)
    data = []
    for i in range(len(rows[0])):
        data.append(tmp[:, i])

    inp_file.close()
    return data

def ConvertDatToEng(inp_file_name, out_file_name, df_meta, base_opts):
    """
    Converts a data file to a eng file
    """
    try:
        inp_file = open(inp_file_name, "rb")
    except:
        log_error("Unable to open %s" % inp_file_name)
        return 1
    try:
        out_file = open(out_file_name, "w")
    except:
        log_error("Unable to open %s" % out_file_name)
        return 1

    first_line = True
    timeout_count = 0
    if 'legato' in df_meta.instrument.instr_class.lower():
        #log_info("match")
        legato_error_count = 0
    else:
        legato_error_count = None

    if(df_meta.scale_off == None):
        log_error("No %%column seen in %s - unable to proceed" % inp_file_name)
        return 1
    if(df_meta.start_time == None):
        log_error("No %%start_time seen in %s - unable to proceed" % inp_file_name)
        return 1

    auxcompass_accelcoeff = auxcompass_abc = auxcompass_pqr = prev_err = aux_cols = None
    # Check for aux compass and compass correction data in sg_calib_constants.m file
    auxname = None
    if df_meta.instrument.instr_class == "auxCompass":
       auxname = "auxCompass"
    if df_meta.instrument.instr_class == "auxB":
        auxname = "auxB"
    if auxname:
        aux_cols = df_meta.columns.split()
        from CalibConst import getSGCalibrationConstants
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
        calib_consts = getSGCalibrationConstants(sg_calib_file_name)
        if(calib_consts and f'{auxname}_coeffhex' in calib_consts):
            try:
                sg_auxcompass_coeffhex = calib_consts[f'{auxname}_coeffhex']
                sg_auxcompass_abc = calib_consts[f'{auxname}_abc']
                sg_auxcompass_pqr = calib_consts[f'{auxname}_pqr']

                auxcompass_accelcoeff = []
                splits = sg_auxcompass_coeffhex.split()
                for i in range(len(splits)):
                    tmp = int(splits[i], 16)
                    if tmp > 0x800000:
                        tmp = tmp - 0x1000000
                    auxcompass_accelcoeff.append(float32(tmp) / (1e9 if i < 9 else 1e8))

                auxcompass_abc = []
                for s in sg_auxcompass_abc.split():
                    auxcompass_abc.append(float32(s))

                auxcompass_pqr = []
                for s in sg_auxcompass_pqr.split():
                    auxcompass_pqr.append(float32(s))

            except:
                log_error(f"Problems processing {auxname} calibration values", 'exc')
                auxcompass_accelcoeff = auxcompass_abc = auxcompass_pqr = None
            else:
                log_info(f"Found {auxname} values in sg_calib_constants.m - using those to correct auxcompass")
                t = f"{auxname}_accelcoeff "
                for c in auxcompass_accelcoeff:
                    t = "%s%g " % (t, c)
                log_debug(t)

                t = f"{auxname}_abc "
                for c in auxcompass_abc:
                    t = "%s%g " % (t, c)
                log_debug(t)

                t = f"{auxname}_pqr "
                for c in auxcompass_pqr:
                    t = "%s%g " % (t, c)
                prev_err = geterr()
                seterr(invalid='raise')


    pressure_col_index = None
    if(df_meta.sealevel and  'pressure' in df_meta.columns.split()):
        pressure_col_index = df_meta.columns.split().index('pressure')

    line_count = 0
    for raw_line in inp_file:
        line_count += 1
        try:
            raw_line = raw_line.decode('utf-8')
        except UnicodeDecodeError:
            # Lots of reasons for this - mixed binary and text files a leading cause
            log_debug(f"Could not decode {inp_file_name} line {line_count} - skipping")
            continue

        out_cols = None

        if(raw_line[0] == '%'):
            # Header line

            # Legato lines that did not get parsed on-board appear as commented lines
            m1 = re.search(r'%(?P<time>.*?) scanned.*{Ready:(?P<data>.*?)}', raw_line)
            m2 = re.findall(r'Error-[\d]*', raw_line)
            if m1 is not None:
                out_cols = [df_meta.start_time + float(m1.groupdict()['time']) / 1000.]
                for val in m1.groupdict()['data'].split(',')[1:]:
                    out_cols.append(float(val.rstrip().lstrip()))
                log_debug("New legato line:%s" % out_cols)
            elif m2 is not None and len(m2) > 0:
                #if legato_error_count is None:
                #    log_info(raw_line)
                legato_error_count += len(m2)
            else:
                raw_strs = raw_line.split(":", 1)
                if(raw_strs[0] == "% columns"):
                    out_file.write("%%columns: %s.time " % df_meta.instrument.instr_class)
                    for c in df_meta.columns.split()[1:]:
                        out_file.write("%s.%s " % (df_meta.instrument.instr_class, c.rstrip().lstrip()))
                    out_file.write("\n")
                else:
                    out_file.write(raw_line.replace('% ', '%'))
                parts = raw_line.split(' ')
                # Timeout lines of the form:
                #% 32500 T-O {}
                #% 32500 TimeOut {}
                if len(parts) >= 3 and (parts[2] == 'T-O' or parts[2] == 'TimeOut'):
                    timeout_count += 1
        else:
            # Data line
            parts = raw_line.split()
            if(first_line):
                cols = []
                num_cols = len(parts)
                if(not df_meta.start_time):
                    log_error("Start time not seen before data -  bailing out")
                    return 1
                for p in range(num_cols):
                    cols.append(int(parts[p]))
                first_line = False
            else:
                for i in range(num_cols):
                    cols[i] = cols[i] + int(parts[i])

            # Time is special in that we are accumulating milli seconds, but report
            # in epoch time
            out_cols =[(df_meta.start_time + (((float(cols[0]) / df_meta.scale_off[0].scale) + df_meta.scale_off[0].offset)/1000.0))]
            for i in range(1, len(cols)):
                if i == pressure_col_index:
                    out_cols.append((((cols[i] - df_meta.sealevel)/ df_meta.scale_off[i].scale) + df_meta.scale_off[i].offset))
                else:
                    out_cols.append(((cols[i] / df_meta.scale_off[i].scale) + df_meta.scale_off[i].offset))

            if(auxcompass_accelcoeff is not None):
                compass_output = []
                mag = []
                accel = []
                for c in ('x', 'y', 'z'):
                    mag.append(float32(out_cols[aux_cols.index("M%c" % c)]))
                    accel.append(float32(out_cols[aux_cols.index("A%c" % c)]))

                outputs = ('hdg', 'pit', 'rol')
                try:
                    trans = compassTransform(mag, accel, auxcompass_accelcoeff, auxcompass_abc, auxcompass_pqr)
                except:
                    log_warning("Error processing %s - listing as NaN" % (out_cols, ))
                    for ii in range(3):
                        out_cols[aux_cols.index(outputs[ii])] = nan
                else:
                    tmp_str = ""
                    for ii in range(3):
                        tmp_str = "%s%f %f (%f) " % (tmp_str, out_cols[aux_cols.index(outputs[ii])], trans[ii], out_cols[aux_cols.index(outputs[ii])] - trans[ii])
                        out_cols[aux_cols.index(outputs[ii])] = trans[ii]
                    #log_info(tmp_str)

            if(df_meta.instrument.instr_class == "auxCompass" and 'pressureCounts' in aux_cols):
                if out_cols[aux_cols.index('pressureCounts')] < 0:
                    out_cols[aux_cols.index('pressureCounts')] += 16777216

        if out_cols is not None:
            for i in range(len(out_cols)):
                out_file.write("%.3f " % out_cols[i])
            out_file.write("\n")

    out_file.write("%%timeouts: %d\n" % timeout_count)
    if timeout_count > 0 :
        log_warning("%d timeout(s) seen in %s" % (timeout_count, inp_file_name), alert='TIMEOUT')
    if legato_error_count is not None:
        out_file.write("%%errors: %d\n" % legato_error_count)

    if(prev_err is not None):
        seterr(invalid=prev_err['invalid'])

    return 0

def eng_file_reader(eng_files, nc_info_d):
    """ Reads the eng files for scicon instruments

    eng_files - list of eng_file

    Returns
    None,None - error

    """
    log_debug("%s" % eng_files)

    df_meta = {}
    data = {}
    netcdf_dict = {}
    sensor_md = None # last df_meta seen when reading
    ret_list = []

    # Filter out adcp files, as they are not actually eng files at all
    adcp_list = []

    for fn in eng_files:
        if 'ad2cp' in os.path.split(fn['file_name'])[1]:
            adcp_list.append(fn)
        else:
            df_meta[fn['cast']], ef_ret_list = extract_file_metadata(fn['file_name'])
            sensor_md = df_meta[fn['cast']]
            data[fn['cast']] = extract_file_data(fn['file_name'])
            if(not df_meta[fn['cast']]):
                log_error("%s contains no metadata - not using in profile" % fn['file_name'])
                continue

            if(not data[fn['cast']]):
                log_info("%s contains no data - not using in profile" % fn['file_name'])
                continue

            if(ef_ret_list != None):
                for r in ef_ret_list:
                    ret_list.append(r)

    # Process adcp data if any
    data_cols = {}
    if adcp_list:
        adcp_list = sorted(adcp_list, key=lambda x : x['cast'])
        log_debug(adcp_list)
        for fn in adcp_list:
            try:
                mf = loadmat(fn['file_name'])
            except:
                log_error("Unable to load %s" % fn['file_name'], 'exc')
                continue

            for col_name in ad2cp_single_value:
                data_cols[col_name] = float(mf[col_name][0][0])

            for col_name in ad2cp_single_dim:
                if col_name in list(data_cols.keys()):
                    data_cols[col_name] = append(data_cols[col_name], mf[col_name][:, 0], axis=0)
                else:
                    data_cols[col_name] = mf[col_name][:, 0]

            try:
                for col_name in ad2cp_multi_dim:
                    if col_name in list(data_cols.keys()):
                        data_cols[col_name] = append(data_cols[col_name], mf[col_name].transpose(), axis=0)
                    else:
                        data_cols[col_name] = mf[col_name].transpose()
            except:
                log_error("Problem processing multi-dim adcp data", 'exc')
                #data_cols.pop(col_name, None)

        # Single value
        for col_name in ad2cp_single_value:
            ret_list.append(("%s_%s" % (ad2cp_base, col_name), data_cols[col_name]))

        # Single dim
        for col_name in ad2cp_single_dim:
            ret_list.append(("%s_%s" % (ad2cp_base, col_name), data_cols[col_name]))

        # Multi-dimensional data
        for col_name in ad2cp_multi_dim:
            assign_dim_info_size(nc_info_d, nc_ad2cp_cell_info, data_cols[col_name].shape[1])
            ret_list.append(("%s_%s" % (ad2cp_base, col_name), data_cols[col_name]))

    if(df_meta == {} or data == {}):
        if ret_list:
            return ret_list, netcdf_dict
        else:
            log_error("Could no data read - bailing out")
            return None, None

    # Process non-adcp data
    casts = sorted(df_meta.keys())

    eng_f = DataFiles.DataFile('eng', None)
    # assume the column names are uniform between casts
    eng_f.columns = df_meta[casts[0]].columns.split()
    eng_f.remap_engfile_columns()
    data_column_headers = eng_f.columns
    del eng_f
    num_columns = len(data_column_headers)
    #log_info("Casts %s, num_columns = %d" % (casts, num_columns))

    #print type(data[1][0]), type(data[2][0])

    # Create one profile
    data_vectors = []
    for i in range(num_columns):
        data_vectors.append(None)

    for c in casts:
        for i in range(num_columns):
            #print c, i
            #print data[c][i]
            if(data[c] == None):
                continue
            if(data_vectors[i] is None):
                data_vectors[i] = data[c][i]
            else:
                data_vectors[i] = concatenate((data_vectors[i], data[c][i]))

    nc_sensor_mdp_info = None
    for i in range(num_columns):
        ret_list.append((data_column_headers[i], data_vectors[i]))
        # Predeclare metadata for these variables in other sensor extension files when possible.
        # If not, this will allow the data to be written with complaint
        # load_dive_profile_data() will reload such data also with complaint
        # If you write files with constructed dim info and later declare it
        # then when the nc file is rebuilt it will use the new, declared dim name
        nc_var_name = data_column_headers[i]
        try:
            md = nc_var_metadata[nc_var_name]
        except KeyError:
            if not nc_sensor_mdp_info:
                if sensor_md:
                    sensor_tag = "scicon_%s_%s" % (sensor_md.instrument.instr_instance, sensor_md.instrument.instr_class)
                    nc_sensor_mdp_dim  = "%s_data_point" % sensor_tag
                    nc_sensor_mdp_info = "%s_info" % nc_sensor_mdp_dim
                    register_sensor_dim_info(nc_sensor_mdp_info, nc_sensor_mdp_dim, None, True, None) # No clue about time var or instrument
            log_warning("NOTE: Metadata for scicon data %s was not pre-declared by an extension; assuming 'd'" % nc_var_name)
            # Since it is raw data and load_dive_profile_data() will create this info as well, we let MMT and MMP handle it
            netcdf_dict[nc_var_name] = form_nc_metadata(None, False, 'd', {}, (nc_sensor_mdp_info,))
            log_debug("nc_var_name:%s - %s" % (nc_var_name, netcdf_dict[nc_var_name]))
        else:
            log_debug("nc_var_name:%s - %s" % (nc_var_name, nc_var_metadata[nc_var_name]))


    return ret_list, netcdf_dict

# SP3003D (and thus glider) convention is X forward, Y right, and Z down.
# On the Sparton this means that Ax is -1 when X is pointing up,
# Ay is -1 when Y is up, etc. Mx is positive when pointing north,
# My is positive north, etc.
#
# The LSM303DLHC convention is X fwd, y left and z up, with Ax reporting
# +1G when pointing up, Ay +1G when up, etc. So Ax comes out backward
# relative to SP3003, but Ay and Az work out to be same relative to SP3003.
# Mx is positive when pointing N, same as SP3003. My and Mz, likewise,
# but because they are directed opposite the SP3003 Y and Z axes, their
# signs must be flipped. Finally, note that the LSM303DLHC mag
# result registers (and thus the auxp boards M: output) comes out
# Mx Mz My (z before y)
#
# We don't change accels here so anything downstream using them or
# expecting same frame as glider must be aware. This lets us use
# a consistent right-handed coordinate system for the accel cal data
# and then this same data to compute accel components for the
# pitch-roll transformation below.
def compassTransform(m, a, accelCoeff, abc, pqr):
    """
    Inputs:
        m - three element magnatometer output
        a - three element accelerometer output
        accelCoeff - twelve element acceleration coefficents - 9 scale, followed by three offset
                     nominally [0.001, 0., 0., 0., 0.001, 0., 0., 0., 0.001, 0., 0., 0.]
        abc - nine element soft iron correction matrix
        pqr - three element hard iron correction vector
    """
    # Locals
    A = [float32(0.)] * 3
    m_pqr = [float32(0.)] * 3
    p = [float32(0.)] * 3
    #cp = 0., cr = 0., sr = 0., sp = 0.
    #heading = 0., pitch = 0., roll = 0.
    #magX = 0., magY = 0.

    #m[1] = -m[1];  # flip signs to get into same sign
    #m[2] = -m[2];  # convention as standard glider SP3003D

    for i in range(3):
        A[i] = 0;
        for j in range(3):
            A[i] += a[j]*accelCoeff[i*3 + j]
        A[i] += accelCoeff[9 + i]

    #if(A[0] < -1.):
    #    A[0] = -1.

    #sys.stdout.write("%g %g %g\n" % (A[0], A[1], A[2]))
    #pitch = float32(arcsin(A[0]))
    #roll = float32(arcsin(A[1]/float32(cos(pitch))))
    pitch = float32(arctan2(A[0], float32(sqrt(A[1]*A[1] + A[2]*A[2]))))
    roll = float32(arctan2(A[1], A[2]))

    m[1] = -m[1]   # cal equations are based on -Y and -Z field values
    m[2] = -m[2]   # i.e., the native right-hand coordinate system of
                    # the LSM303
    for j in range(3):
        m_pqr[j] = m[j] - pqr[j]

    for i in range(3):
        p[i] = 0.0
        for j in range(3):
            p[i] += m_pqr[j]*abc[i*3 + j]

    cp = float32(cos(pitch))
    cr = float32(cos(roll))
    sp = float32(sin(pitch))
    sr = float32(sin(roll))
    magX = p[0]*cp - p[1]*sp*sr - p[2]*sp*cr
    magY = p[1]*cr - p[2]*sr

    heading = float32(arctan2(magY, magX))
    if (heading < 0):
        heading += 2. * pi

    #data[0] = heading*180/M_PI;
    #data[1] = pitch*180/M_PI;
    #data[2] = roll*180/M_PI;

    return (float32(heading * 180. / pi), float32(pitch * 180./pi), float32(roll * 180. / pi))
