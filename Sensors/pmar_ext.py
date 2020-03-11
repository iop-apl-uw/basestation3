#! /usr/bin/env python

##
## Copyright (c) 2010, 2011, 2012, 2013, 2016, 2017, 2018, 2019, 2020 by University of Washington.  All rights reserved.
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
PMAR basestation sensor extension
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
# Globals
pmar_prefix = "pm"

def parse_time(ts):
    time_parts = ts.split()
    if(int(time_parts[2]) - 100 < 0):
        year_part = int(time_parts[2])
    else:
        year_part = int(time_parts[2]) - 100

    time_string = "%s %s %02d %s %s %s" % (time_parts[0], time_parts[1], year_part,
                                           time_parts[3], time_parts[4], time_parts[5])
    return  time.mktime(time.strptime(time_string, "%m %d %y %H %M %S")) + (float(time_parts[6]) / 1000.)

def format_time(t):
    milli, sec = math.modf(t)
    st = time.localtime(sec)

    year_part = st.tm_year - 1900

    time_string = "%d %d %d %d %d %d %d" % (st.tm_mon, st.tm_mday, st.tm_year - 1900,
                                           st.tm_hour, st.tm_min, st.tm_sec, milli * 1000.)
    return time_string

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

    init_dict[module_name] = {'logger_prefix' : pmar_prefix,
                              'strip_files' : True,
                              'eng_file_reader' : eng_file_reader,
                              'known_files' : ['pmar.cnf', 'pmar.tgz'],
                              'netcdf_metadata_adds' : {
                                  'log_PM_RECORDABOVE': [False, 'd', {'description':'Depth above above which data is recorded', 'units':'meters'}, nc_scalar],
                                  'log_PM_PROFILE': [False, 'd', {'description':'Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
                                  'log_PM_XMITPROFILE': [False, 'd', {'description':'Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both'}, nc_scalar],
                                  'log_PM_XMITRAW': [False, 'd', {'description':'Which part of the dive data to transmit - 0 none, 1 dive, 2 climb, 3 both.'}, nc_scalar],
                                  'log_PM_FREEKB': [False, 'd', {'description':'Free diskspace on PMAR, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_00': [False, 'd', {'description':'Free diskspace on PMAR disk 00, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_01': [False, 'd', {'description':'Free diskspace on PMAR disk 01, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_02': [False, 'd', {'description':'Free diskspace on PMAR disk 02, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_03': [False, 'd', {'description':'Free diskspace on PMAR disk 03, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_04': [False, 'd', {'description':'Free diskspace on PMAR disk 04, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_05': [False, 'd', {'description':'Free diskspace on PMAR disk 05, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_06': [False, 'd', {'description':'Free diskspace on PMAR disk 06, in kBytes'}, nc_scalar],
                                  'log_PM_FREEKB_07': [False, 'd', {'description':'Free diskspace on PMAR disk 07, in kBytes'}, nc_scalar],
                                  'log_PM_ACTIVECARD': [False, 'd', {'description':'Currently active card'}, nc_scalar],
                                  'log_PM_MOTORS': [False, 'd', {'description':'Send motor notifacations to PMAR'}, nc_scalar],
                                  'log_PM_SENDDEPTH': [False, 'd', {'description':'Send depth notifacations to PMAR'}, nc_scalar],
                                  'log_PM_NDIVE': [False, 'd', {'description':'Dive multiplier for PMAR'}, nc_scalar],
                                  'pmar_nfft': [False, 'i', {'description':'Size of FFT'}, nc_scalar],
                                  'pmar_navg': [False, 'i', {'description':'Number of blocks per ensemble'}, nc_scalar],
                                  'pmar_samplerate': [False, 'd', {'description':'Actual sample rate'}, nc_scalar],
                                  'pmar_container': [False, 'c', {'description':'Name of the containing directory'}, nc_scalar],
                                  'pmar_comment': [False, 'c', {'description':'Comment field'}, nc_scalar],
                                  'pmar_serialnum': [False, 'c', {'description':'PMAR boards serial number'}, nc_scalar],
                                  'pmar_osc': [False, 'i', {'description':'Oscillator setting'}, nc_scalar],
                                  'pmar_datawindow': [False, 'd', {'description':'Size in seconds of the signal stats window'}, nc_scalar],
                                  'pmar_clipmin': [False, 'i', {'description':'Signal value below which a negative clip is counted'}, nc_scalar],
                                  'pmar_clipmax': [False, 'i', {'description':'Signal value above which a postivie clip is counted'}, nc_scalar],
                                  'pmar_maxclipcount': [False, 'i', {'description':'Max number of clips allowed in a block'}, nc_scalar],
                                  'pmar_minblocksensemble': [False, 'i', {'description':'Minimum number of blocks contained in an ensemble'}, nc_scalar],
                                  'pmar_num_blocks': [False, 'i', {'description':'Number of blocks included in the ensemble'}, nc_scalar],
                                  'pmar_logmap': [False, 'c', {'description':'Array describing the mapping from frequency to log averaged'}, nc_scalar],
                                  'pmar_gain': [False, 'd', {'description':'Gain setting for recording (0 - 4)'}, nc_scalar],
                                  'pmar_despikethreshold': [False, 'd', {'description':'Threshold for despiking in standard deviations'}, nc_scalar],
                                  'pmar_despikepasses': [False, 'd', {'description':'Number of times data depiker has been run'}, nc_scalar],
                                  
                                  'pmar_motordroppedblocks_a': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_a': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_a': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_a': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_a': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_a': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_a': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_a': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_a': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_a': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],

                                  'pmar_motordroppedblocks_b': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_b': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_b': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_b': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_b': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_b': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_b': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_b': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_b': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_b': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],


                                  'pmar_nfft_ch00': [False, 'i', {'description':'Size of FFT'}, nc_scalar],
                                  'pmar_navg_ch00': [False, 'i', {'description':'Number of blocks per ensemble'}, nc_scalar],
                                  'pmar_samplerate_ch00': [False, 'd', {'description':'Actual sample rate'}, nc_scalar],
                                  'pmar_container_ch00': [False, 'c', {'description':'Name of the containing directory'}, nc_scalar],
                                  'pmar_comment_ch00': [False, 'c', {'description':'Comment field'}, nc_scalar],
                                  'pmar_serialnum_ch00': [False, 'c', {'description':'PMAR boards serial number'}, nc_scalar],
                                  'pmar_osc_ch00': [False, 'i', {'description':'Oscillator setting'}, nc_scalar],
                                  'pmar_datawindow_ch00': [False, 'd', {'description':'Size in seconds of the signal stats window'}, nc_scalar],
                                  'pmar_clipmin_ch00': [False, 'i', {'description':'Signal value below which a negative clip is counted'}, nc_scalar],
                                  'pmar_clipmax_ch00': [False, 'i', {'description':'Signal value above which a postivie clip is counted'}, nc_scalar],
                                  'pmar_maxclipcount_ch00': [False, 'i', {'description':'Max number of clips allowed in a block'}, nc_scalar],
                                  'pmar_minblocksensemble_ch00': [False, 'i', {'description':'Minimum number of blocks contained in an ensemble'}, nc_scalar],
                                  'pmar_num_blocks_ch00': [False, 'i', {'description':'Number of blocks included in the ensemble'}, nc_scalar],
                                  'pmar_logmap_ch00': [False, 'c', {'description':'Array describing the mapping from frequency to log averaged'}, nc_scalar],
                                  'pmar_gain_ch00': [False, 'd', {'description':'Gain setting for recording (0 - 4)'}, nc_scalar],
                                  'pmar_gain0_ch00': [False, 'd', {'description':'Setting gain stage 0 in dB'}, nc_scalar],
                                  'pmar_gain1_ch00': [False, 'd', {'description':'Setting gain stage 1 in dB'}, nc_scalar],
                                  'pmar_cutoff_ch00': [False, 'd', {'description':'Low pass frequency in Hz'}, nc_scalar],                                  
                                  'pmar_despikethreshold_ch00': [False, 'd', {'description':'Threshold for despiking in standard deviations'}, nc_scalar],
                                  'pmar_despikepasses_ch00': [False, 'd', {'description':'Number of times data depiker has been run'}, nc_scalar],
                                  
                                  'pmar_motordroppedblocks_a_ch00': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_a_ch00': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_a_ch00': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_a_ch00': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_a_ch00': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_a_ch00': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_a_ch00': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_a_ch00': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_a_ch00': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_a_ch00': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],


                                  'pmar_motordroppedblocks_b_ch00': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_b_ch00': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_b_ch00': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_b_ch00': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_b_ch00': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_b_ch00': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_b_ch00': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_b_ch00': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_b_ch00': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_b_ch00': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],


                                  'pmar_nfft_ch01': [False, 'i', {'description':'Size of FFT'}, nc_scalar],
                                  'pmar_navg_ch01': [False, 'i', {'description':'Number of blocks per ensemble'}, nc_scalar],
                                  'pmar_samplerate_ch01': [False, 'd', {'description':'Actual sample rate'}, nc_scalar],
                                  'pmar_container_ch01': [False, 'c', {'description':'Name of the containing directory'}, nc_scalar],
                                  'pmar_comment_ch01': [False, 'c', {'description':'Comment field'}, nc_scalar],
                                  'pmar_serialnum_ch01': [False, 'c', {'description':'PMAR boards serial number'}, nc_scalar],
                                  'pmar_osc_ch01': [False, 'i', {'description':'Oscillator setting'}, nc_scalar],
                                  'pmar_datawindow_ch01': [False, 'd', {'description':'Size in seconds of the signal stats window'}, nc_scalar],
                                  'pmar_clipmin_ch01': [False, 'i', {'description':'Signal value below which a negative clip is counted'}, nc_scalar],
                                  'pmar_clipmax_ch01': [False, 'i', {'description':'Signal value above which a postivie clip is counted'}, nc_scalar],
                                  'pmar_maxclipcount_ch01': [False, 'i', {'description':'Max number of clips allowed in a block'}, nc_scalar],
                                  'pmar_minblocksensemble_ch01': [False, 'i', {'description':'Minimum number of blocks contained in an ensemble'}, nc_scalar],
                                  'pmar_num_blocks_ch01': [False, 'i', {'description':'Number of blocks included in the ensemble'}, nc_scalar],
                                  'pmar_logmap_ch01': [False, 'c', {'description':'Array describing the mapping from frequency to log averaged'}, nc_scalar],
                                  'pmar_gain_ch01': [False, 'd', {'description':'Gain setting for recording (0 - 4)'}, nc_scalar],
                                  'pmar_gain0_ch01': [False, 'd', {'description':'Setting gain stage 0 in dB'}, nc_scalar],
                                  'pmar_gain1_ch01': [False, 'd', {'description':'Setting gain stage 1 in dB'}, nc_scalar],
                                  'pmar_cutoff_ch01': [False, 'd', {'description':'Low pass frequency in Hz'}, nc_scalar],

                                  'pmar_despikethreshold_ch01': [False, 'd', {'description':'Threshold for despiking in standard deviations'}, nc_scalar],
                                  'pmar_despikepasses_ch01': [False, 'd', {'description':'Number of times data depiker has been run'}, nc_scalar],
                                  
                                  'pmar_motordroppedblocks_a_ch01': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_a_ch01': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_a_ch01': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_a_ch01': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_a_ch01': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_a_ch01': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_a_ch01': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_a_ch01': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_a_ch01': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_a_ch01': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],


                                  'pmar_motordroppedblocks_b_ch01': [False, 'i', {'description':'Number of blocks dropped due to motor moves'}, nc_scalar],
                                  'pmar_clipdroppedblocks_b_ch01': [False, 'i', {'description':'Number of blocks dropped due to clipping'}, nc_scalar],
                                  'pmar_goodblocks_b_ch01': [False, 'i', {'description':'Number of good blocks'}, nc_scalar],
                                  'pmar_totalclip_b_ch01': [False, 'i', {'description':'Total number of samples clipped'}, nc_scalar],
                                  'pmar_totaldespike_b_ch01': [False, 'i', {'description':'Total number of samples despiked'}, nc_scalar],
                                  'pmar_samplesprocessed_b_ch01': [False, 'i', {'description':'Total number of samples processed (always a multiple of nfft/2)'}, nc_scalar],
                                  'pmar_writeerrors_b_ch01': [False, 'i', {'description':'Total number of file write errors'}, nc_scalar],
                                  'pmar_bufferfull_b_ch01': [False, 'i', {'description':'Total number of samples dropped due to buffer overflow'}, nc_scalar],
                                  'pmar_datafiles_b_ch01': [False, 'i', {'description':'Total number of data files created'}, nc_scalar],
                                  'pmar_datafailedfiles_b_ch01': [False, 'i', {'description':'Total number of data files that failed'}, nc_scalar],

                              }
    }
    

    # Predeclare the possible dimensions for non-base files
    for ch_tag in ("", "_ch00", "_ch01"):
        for cast in ('a', 'b'):
            row_dim = "pmar_logavg%s_%s_row" % (ch_tag, cast)
            row_info = "%s_info" % row_dim
            col_dim = "pmar_logavg%s_%s_col" % (ch_tag, cast)
            col_info = "%s_info" % col_dim
            var_name = "pmar_logavg%s_%s" % (ch_tag, cast)
            var_name_qc = "pmar_logavg%s_%s_qc" % (ch_tag, cast)
            description = "PMAR logavg spectra %s" % "down profile" if cast == 'a' else "up profile"
            description_qc = "Whether to trust the PMAR logavg spectra"
            register_sensor_dim_info(row_info, row_dim, None, True, None)
            register_sensor_dim_info(col_info, col_dim, None, True, None)
            init_dict[module_name]['netcdf_metadata_adds'][var_name] = form_nc_metadata(None, False, 'd', {'description' : description, 'units' : 'units of variance/Hertz'}, (row_info, col_info,))
            init_dict[module_name]['netcdf_metadata_adds'][var_name_qc] = form_nc_metadata(None, False, nc_qc_type, {'units': 'qc_flag', 'description' : description_qc}, (row_info, ))
        #'sbe43_dissolved_oxygen_qc' : [False, nc_qc_type, {'units':'qc_flag', 'description':'Whether to trust each SBE43 dissolved oxygen value'}, (nc_sbe43_results_info,)],
    return 0

def process_tar_members(base_opts, module_name, fc, pmar_file_list, processed_logger_eng_files, processed_logger_other_files):
    """Processes files uploaded in the tarball, converting them to .eng files
    Practically, this is a rename, unless the files is in binary, in which case it is a conversion

    Returns:
    0 for success
    1 for error
    """
    ret_val = 0

    base_name = None

    for pmar_file in pmar_file_list:

        if(base_name == None):
            head, _ = os.path.split(pmar_file)
            base_name = "%s/p%s%03d%04d%s" % (head, pmar_prefix, fc._instrument_id, fc.dive_number(), fc.up_down_data())
            log_info("base_name %s" % base_name)

        log_info("Processing %s" % pmar_file)
        try:
            _, tail = os.path.splitext(pmar_file)
            head, _ = os.path.split(tail)
            s = head.split(_)
            if(len(s[-1]) == 4 and s[0:2] == "ch"):
                channel = s[-1]
                channel_tag = "_%s" % channel
            else:
                channel = "ch00"
                channel_tag = ""

            ef, _ = extract_file_metadata(pmar_file, fc.up_down_data(), channel_tag)
            ed = extract_file_data(pmar_file)
            log_debug("%s %s" % (ef, ed))
            if(ef == None or ed == None):
                log_error("Could not process %s - skipping" % (pmar_file))
                continue

            _, tail = os.path.split(pmar_file)
            for ch_tag in ("", "_ch00", "_ch01"):
                if(tail == "pm%s.eng" % ch_tag):
                    output_file = ("%s_base%s.eng" % (base_name, ch_tag))

                    log_debug("Output file %s" % output_file)
                    try:
                        fo = open(output_file, "w")
                    except IOError:
                        log_error("Could not open %s for output - skipping %s" % (output_file, pmar_file), 'exc')
                        ret_val = 1
                        continue
                    # Process the files, dealing with time
                    time_col = -1
                    if('columns' in ef):
                        if('time' in ef['columns']):
                            time_col = ef['columns'].index('time')
                        else:
                            ef['columns'] = "%s %s" % ("time", ef['columns'])
                    write_file_header(ef, fo)
                    if(time_col > -1):
                        # For pmar eng files with time included
                        time_accum = None
                        for row in range(shape(ed)[1]):
                            #fo.write("%.1f " % t)
                            #t = t + time_step
                            for col in range(shape(ed)[0]):
                                if(col == time_col):
                                    if(time_accum is None):
                                        time_accum = ed[col][row]
                                    else:
                                        time_accum += ed[col][row]
                                    fo.write("%.3f " % (ef['start'] + time_accum / 1000., ))
                                else:
                                    fo.write("%.2f " % ed[col][row])
                            fo.write("\n")
                    else:
                        time_step = float(ef['datawindow'])
                        t = ef['start'] + time_step  # Use the center point for time
                        for row in range(shape(ed)[1]):
                            fo.write("%.1f " % t)
                            t = t + time_step
                            for col in range(shape(ed)[0]):
                                fo.write("%d " % ed[col][row])
                            fo.write("\n")
                    write_file_footer(ef, fo)
                    fo.close()
                    processed_logger_eng_files.append(output_file)
                if(tail == "pm_logavg%s.eng" % ch_tag):
                    output_file = ("%s_logavg%s.eng" % (base_name, ch_tag))

                    log_info("Output file %s" % output_file)
                    try:
                        fo = open(output_file, "w")
                    except IOError:
                        log_error("Could not open %s for output - skipping %s" % (output_file, pmar_file), 'exc')
                        ret_val = 1
                        continue
                    write_file_header(ef, fo)
                    # First to columns are center first diff - the rest goes as is
                    time_accum = None
                    num_block_accum = None
                    clip_count_accum = None
                    dropped_points_accum = None
                    if 'columns' in ef and 'dropped_points' in ef['columns']:
                        start_spec = 4
                    elif 'columns' in ef and 'clipcount' in ef['columns']:
                        start_spec = 3
                    else:
                        start_spec = 2
                    for row in range(shape(ed)[1]):
                        if(time_accum is None):
                            time_accum = ed[0][row]
                        else:
                            time_accum += ed[0][row]
                        if(num_block_accum is None):
                            num_block_accum = ed[1][row]
                        else:
                            num_block_accum += ed[1][row]
                        fo.write("%.3f %d" % (ef['start'] + time_accum / 1000., num_block_accum))
                        if(start_spec >= 3):
                            if(clip_count_accum is None):
                                clip_count_accum = ed[2][row]
                            else:
                                clip_count_accum += ed[2][row]
                            fo.write(" %d" % clip_count_accum)
                        if(start_spec >= 4):
                            if(dropped_points_accum is None):
                                dropped_points_accum = ed[3][row]
                            else:
                                dropped_points_accum += ed[3][row]
                            fo.write(" %d" % dropped_points_accum)
                        for col in range(start_spec, shape(ed)[0]):
                            fo.write(" %g" % ed[col][row])
                        fo.write("\n")
                    write_file_footer(ef, fo)                    
                    fo.close()
                    processed_logger_eng_files.append(output_file)
                elif(tail == "upload.eng"):
                    output_file = ("%s_upload.eng" % (base_name,))

                    # File is a sample - convert to .wav?
                    log_info("Conversion to wav NYI")
        except:
            log_error("Failed to process %s" % pmar_file)
            log_error(traceback.format_exc())
            ret_val = 1

    return ret_val

def extract_file_metadata(inp_file_name, cast, channel):
    """
    Extracts the meta data from a dat file
    Returns:
    None - failure
    Dictionary of meta data
    """
    try:
        inp_file = open(inp_file_name, "r")
    except:
        log_error("Unable to open %s" % inp_file_name)
        return None

    first_line = True

    eng_file_meta = collections.OrderedDict()

    ret_list = []

    log_info("Processing %s" % inp_file_name)

    for raw_line in inp_file:
        if(raw_line[0] == '%'):
            raw_strs = raw_line.split(":", 1)
            raw_strs[0] = raw_strs[0].replace('% ', '%')
            if(raw_strs[0] == '%columns'):
                eng_file_meta['columns'] = raw_strs[1].rstrip().lstrip()
                continue
            elif(raw_strs[0] == "%logmap"):
                logmap = raw_strs[1].rstrip().lstrip()

                eng_file_meta['logmap'] = logmap
                ret_list.append(('pmar_logmap%s' % channel, eng_file_meta['logmap']))
                continue
            elif(raw_strs[0] == "%start"):
                eng_file_meta['start'] = parse_time(raw_strs[1])
                ##ret_list.append(('pmar_start' % i, eng_file_meta[i]))
                continue
            elif(raw_strs[0] == "%stop"):
                eng_file_meta['stop'] = parse_time(raw_strs[1])
                continue
            else:
                # string values
                for i in ('container', 'comment', 'serialnum'):
                    if(raw_strs[0] == "%%%s" % (i)):
                        if(len(raw_strs[1].rstrip().lstrip()) > 0):
                            eng_file_meta[i] =  raw_strs[1].rstrip().lstrip()
                            ret_list.append(('pmar_%s%s' % (i, channel), eng_file_meta[i]))
                        continue

                # Int values
                for i in ('binaryoutput', 'osc', 'clipmax', 'clipmin', 'maxclipcount', 'minblocksensemble', 'nfft', 'navg'):
                    if(raw_strs[0] == "%%%s" % (i)):
                        #log_info("Match %s" % i)
                        eng_file_meta[i] =  int(raw_strs[1].rstrip().lstrip())
                        if(i != 'binaryoutput'):
                            ret_list.append(('pmar_%s%s' % (i, channel), eng_file_meta[i]))
                        continue

                # Int values - profile specific
                for i in ('motordroppedblocks', 'clipdroppedblocks', 'goodblocks', 'totalclip', 'totaldespike', 'samplesprocessed',
                          'writeerrors', 'bufferfull', 'datafiles', 'datafailedfiles'):
                    if(raw_strs[0] == "%%%s" % (i)):
                        #log_info("Match %s" % i)
                        eng_file_meta[i] =  int(raw_strs[1].rstrip().lstrip())
                        #log_info(('pmar_%c_%s' % (cast, i), eng_file_meta[i]))
                        ret_list.append(('pmar_%s_%s%s' % (i, cast, channel), eng_file_meta[i]))
                        continue
                    
                # float values
                for i in ('datawindow', 'savesize', 'samplerate', "gain", "gain0", "gain1", "cutoff", "despikethreshold", "despikepasses"):
                    if(raw_strs[0] == "%%%s" % (i)):
                        eng_file_meta[i] =  float(raw_strs[1].rstrip().lstrip())
                        ret_list.append(('pmar_%s%s' % (i, channel), eng_file_meta[i]))
                        continue

    return (eng_file_meta, ret_list)

def write_file_header(ef, fo):
    for i in list(ef.keys()):
        if(i == 'start'):
            break
        fo.write("%%%s: %s\n"% (i, ef[i]))

    if('start' in ef):
        fo.write("%%start: %s\n" % format_time(ef['start']))

    return None

def write_file_footer(ef, fo):
    # Find the tail
    in_footer = False
    for i in list(ef.keys()):
        if(i == 'stop'):
            in_footer = True
            fo.write("%%stop: %s\n" % format_time(ef['stop']))
            continue
        if in_footer:
            fo.write("%%%s: %s\n"% (i, ef[i]))

    return None

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

    buffer = inp_file.read()
    inp_file.close()


    rows = []
    nfreqs = 0
    nlog = 0
    columns = []
    _, tail = os.path.split(inp_file_name)
    if(tail == "upload.eng"):
        binaryoutput = 1
    else:
        binaryoutput = 0
    #log_info("binaryoutput: %d" % binaryoutput)
    line_count = -1
    # Process the data
    for inp_line in buffer.splitlines():
        inp_line = inp_line.rstrip().rstrip()
        line_count += 1
        if(inp_line == ""):
            continue
        elif(inp_line[0] == '%'):
            raw_strs = inp_line.split(":", 1)
            if(raw_strs[0] == '%binaryoutput'):
                binaryoutput = int(raw_strs[1].rstrip().lstrip())
            if(raw_strs[0] == '%columns'):
                columns = raw_strs[1].split()
            elif(raw_strs[0] == '%start'):
                #log_info("Found start")
                if(binaryoutput):
                    # Handle this below
                    break

        else:
            raw_strs = inp_line.split()
            row = []
            for i in range(len(raw_strs)):
                try:
                    row.append(float64(raw_strs[i]))
                except:
                    log_error("Problems converting [%s] to float from line [%s] (%s, line %d)"
                                   % (raw_strs[i], inp_line, inp_file_name, line_count))
                    continue
            log_debug("%s" % row)
            rows.append(row)

    # Handle the binary case
    if(binaryoutput):
        data_start = buffer.find('%start')
        data_start = buffer.find('\n', data_start) + 1
        data_end = buffer.find('\n%stop')

        data = arr.array('H')
        data.fromstring(buffer[data_start:data_end])

        return data

    else:
        if(not rows):
            return None

        tmp = array(rows, float64)
        data = []
        for i in range(len(rows[0])):
            data.append(tmp[:, i])

        return data

def eng_file_reader(eng_files, nc_info_d):
    """ Reads the eng files for pmar instruments

    eng_files - list of eng_file that contain one class of file

    Returns
    ret_list - list of (variable,data) tuples
    netcdf_dict - dictionary of optional netcdf variable additions

    """
    netcdf_dict = {}
    ret_list = []

    for fn in eng_files:
        # Figure out what type of engfile
        filename = fn['file_name']
        _, tail = os.path.split(filename)
        head, _ = os.path.splitext(tail)
        tmp = head.split('_')
        eng_file_class = tmp[1]

        if(len(tmp[-1]) == 4 and tmp[-1].startswith("ch")):
            channel = tmp[-1]
            channel_tag = "_%s" % channel
        else:
            channel = "ch00"
            channel_tag = ""

        if(eng_file_class == 'base' or eng_file_class == 'logavg'):
            cast = fn['cast']
            eng_file_meta, ef_ret_list = extract_file_metadata(filename, ("a" if cast == 1 else "b"), channel_tag)

            if(eng_file_meta == None):
                log_error("%s contains no metadata - not using in profile" % filename)
                continue

            if(ef_ret_list == None):
                log_error("%s contains no netcdf data - not adding to profile" % filename)
            else:
                for r in ef_ret_list:
                    ret_list.append(r)

            data = extract_file_data(filename)
            if(not data):
                log_debug("%s contains no data - not using in profile" % filename)
                continue

            # Remap column header names
            data_column_headers = []
            columns = eng_file_meta['columns'].split()
            for column_name in columns:
                data_column_headers.append(column_name.replace(".", "_"))

            # Form the dimension and info for the data in this file
            nc_eng_file_mdp_dim  = "pmar_%s%s_%s_data_point" % (eng_file_class, channel_tag, "a" if cast == 1 else "b")
            log_debug("Creating dimension %s" % nc_eng_file_mdp_dim)
            nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
            if nc_eng_file_mdp_info not in nc_mdp_data_info:
                register_sensor_dim_info(nc_eng_file_mdp_info, nc_eng_file_mdp_dim, None, True, None)

            if(eng_file_class == 'logavg'):
                if('dropped_points' in columns):
                    col_fixed_end = 4
                elif('clipcount' in columns):
                    col_fixed_end = 3
                else:
                    col_fixed_end = 2
            else:
                col_fixed_end = len(columns)

            # Common for base and logavg
            for i in range(col_fixed_end):
                nc_var_name = "pmar_%s_%s%s_%s" % (eng_file_class, data_column_headers[i], channel_tag, "a" if cast == 1 else "b")
                log_debug("%s(%s)" % (nc_var_name, nc_eng_file_mdp_dim))
                ret_list.append((nc_var_name, data[i]))
                try:
                    md = nc_var_metadata[nc_var_name]
                except KeyError:
                    log_debug("Metadata for pmar data %s was not pre-declared" % nc_var_name)
                    # Since it is raw data and load_dive_profile_data() will create this info
                    # as well, we let MMT and MMP handle it
                    netcdf_dict[nc_var_name] = form_nc_metadata(None, False, 'd', {}, (nc_eng_file_mdp_info,))

            if(eng_file_class == 'logavg'):
                # Center freqs
                cfs = columns[col_fixed_end:]
                center_freqs = []
                log_debug("cfs %s" % cfs)
                for cc in cfs:
                    center_freqs.append(float(cc.split('_')[1]))
                center_freqs = array(center_freqs)
                nc_var_name = "pmar_%s%s_%s_%s" % (eng_file_class, channel_tag, 'a' if fn['cast'] == 1 else 'b', 'center_freqs')
                ret_list.append((nc_var_name, center_freqs))
                try:
                    md = nc_var_metadata[nc_var_name]
                except KeyError:
                    nc_eng_file_mdp_dim  = "%s_data_point" % nc_var_name
                    nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
                    if nc_eng_file_mdp_info not in nc_mdp_data_info:
                        register_sensor_dim_info(nc_eng_file_mdp_info, nc_eng_file_mdp_dim, None, True, None)
                    netcdf_dict[nc_var_name] = form_nc_metadata(None, False, 'd', {}, (nc_eng_file_mdp_info,))

                # The spectra
                # Strip off the time and other leading columns
                spectra = array(data)[col_fixed_end:,:]
                spectra = spectra.transpose()
                # The data part
                nc_var_name = "pmar_%s%s_%s" % (eng_file_class, channel_tag, 'a' if fn['cast'] == 1 else 'b')
                ret_list.append((nc_var_name, spectra))

                # The nc metadata for nc_var_name was created in init_logger() above
                # including the multi-dimensional row and coluumn info and dimensions
                # Here we are able to assert the dimension sizes
                assign_dim_info_size(nc_info_d, "%s_row_info" % nc_var_name, spectra.shape[0]) # rows
                assign_dim_info_size(nc_info_d, "%s_col_info" % nc_var_name, spectra.shape[1]) # columns

        elif(eng_file_class in ('upload')):
            try:
                fi = open(filename, "r")
            except:
                log_error("Unable to open %s" % filename)
                continue

            log_info("Processing for %s NYI" % (filename,))

        else:
            log_warning("Unknown class %s of pmar file %s -- skipping" % (eng_file_class, filename))

    return ret_list, netcdf_dict

def sensor_data_processing(base_opts, module, l=None, eng_f=None, calib_consts=None):
    """
    Called from MakeDiveProfiles.py to do sensor specific processing

    Arguments:
    l - MakeDiveProfiles locals() dictionary
    eng_f - engineering file
    calib_constants - sg_calib_constants object

    Returns:
     0 - match found and processed
     1 - no match found
    -1 - error during processing
    """

    if(l == None or eng_f==None or calib_consts==None or 'results_d' not in l or 'nc_info_d' not in l):
        log_error("Missing arguments for sensor_data_processing - version mismatch?")
        return -1

    results_d = l['results_d']
    nc_info_d = l['nc_info_d']

    try:
        gc_st_secs = l['gc_st_secs']
        gc_end_secs = l['gc_end_secs']
        gc_vbd_secs = l['gc_vbd_secs']
        gc_vbd_ctl = l['gc_vbd_ctl']
    except:
        log_error("Unable to extract needed variables", 'exc')
        return -1

    for ch, ch_tag in ((None, ""), (0, "_ch00"), (1, "_ch01")):
        for cast in ('a', 'b'):
            time_var_name = "pmar_logavg_time%s_%c" % (ch_tag, cast)
            if time_var_name in results_d and 'pmar_logavg%s_%c' % (ch_tag, cast) in results_d:
                try:
                    pmar_samplerate = results_d['pmar_samplerate%s' % ch_tag]
                    pmar_nfft = results_d['pmar_nfft%s' % ch_tag]
                    pmar_navg = results_d['pmar_navg%s' % ch_tag]
                except:
                    log_error("Unable to get variables for cast %c%s" % (cast, "" if ch is None else " channel %d" % ch), 'exc')
                    continue
                ensemble_duration = (float(pmar_nfft) * (float(pmar_navg) / 2.0)) / float(pmar_samplerate)
                log_debug("ensemble_duration = %f" % ensemble_duration)

                apogee_pump_start_time = None # and the first time it started moving

                climb_pump_start_time = climb_pump_end_time = None

                for gc in range(1, len(gc_st_secs)): # Skip the first GC since it is the flare maneuver
                    vbd_secs   = gc_vbd_secs[gc]
                    vbd_ctl    = gc_vbd_ctl[gc]

                    # Looking for the second VBD pump

                    if (vbd_ctl >= 0 and vbd_secs > 0):
                        if (apogee_pump_start_time is not None): # first positive pump
                            climb_pump_start_time = gc_st_secs[gc]
                            climb_pump_end_time = gc_st_secs[gc]+ vbd_secs
                            break

                        if (apogee_pump_start_time is None): # First pump (assumed to neutral--check against pitch_ctl?)
                            apogee_pump_start_time = gc_st_secs[gc]
                            continue # next GC

                if(climb_pump_start_time):
                    log_debug("climb_pump_start_time:%f climb_pump_end_time:%f" % (climb_pump_start_time, climb_pump_end_time))

                    ensemble_st_time = results_d[time_var_name]
                    ensemble_st_time_np = len(ensemble_st_time)

                    logavg_qc_v = initialize_qc(ensemble_st_time_np, QC_GOOD)

                    bad_qc = []

                    for ii in range(len(ensemble_st_time)):
                        # Old method - flag every GC
                        # for jj in range(len(gc_st_secs)):
                        #     if( not ((gc_st_secs[jj] < ensemble_st_time[ii] and gc_end_secs[jj] < ensemble_st_time[ii])
                        #              or (ensemble_st_time[ii] + ensemble_duration < gc_st_secs[jj] and ensemble_st_time[ii] + ensemble_duration < gc_end_secs[jj]))):
                        #         bad_qc.append(ii)
                        #         log_info("Cast %c - gc_st:%.3f gc_end:%.3f ens_st:%.3f ens_end:%.3f"
                        #                  % (cast, gc_st_secs[jj], gc_end_secs[jj], ensemble_st_time[ii], ensemble_st_time[ii] + ensemble_duration))

                        if( not ((climb_pump_start_time < ensemble_st_time[ii] and climb_pump_end_time < ensemble_st_time[ii])
                                 or (ensemble_st_time[ii] + ensemble_duration < climb_pump_start_time and ensemble_st_time[ii] + ensemble_duration < climb_pump_end_time))):
                            bad_qc.append(ii)
                            log_debug("Cast %c - gc_st:%.3f gc_end:%.3f ens_st:%.3f ens_end:%.3f"
                                     % (cast, climb_pump_start_time, climb_pump_end_time, ensemble_st_time[ii], ensemble_st_time[ii] + ensemble_duration))
                    log_debug("bad_qc = %s" % bad_qc)
                    assert_qc(QC_BAD, logavg_qc_v, bad_qc, 'ensembles overlap with motor on time')
                    results_d.update({
                        'pmar_logavg%s_%c_qc' % (ch_tag, cast): logavg_qc_v,
                        })
                else:
                    log_warning("Did not find the climb pump")

    return 0
