#! /usr/bin/env python

## 
## Copyright (c) 2018, 2019 by University of Washington.  All rights reserved.
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
AEM1-G-ZR (velo) basestation sensor extension
"""

import sys
from QC import *
from BaseNetCDF import *
from BaseLog import *
import numpy as np
from MakeDiveProfiles import compute_displacements, compute_dac
from TraceArray import * # REMOVE use only if we are tracing...
nc_velo_data_info = 'velo_data_info' # from eng/scicon

nc_velo_results_info = 'velo_results_info'
nc_dim_velo_results = 'velo_result_data_point'
nc_velo_time_var = 'velo_results_time'

def init_sensor(module_name, init_dict=None):
    """
    init_sensor

    Returns:
        -1 - error in processing
         0 - success (data found and processed)
    """

    if(init_dict is None):
        log_error("No datafile supplied for init_sensors - version mismatch?")
        return -1

    register_sensor_dim_info(nc_velo_data_info, 'velo_data_point', 'velo_time', 'physical', 'velo')
    register_sensor_dim_info(nc_velo_results_info, nc_dim_velo_results, nc_velo_time_var, False, 'velo') # could be scicon or eng
    init_dict[module_name] = {
        'netcdf_metadata_adds' : {
            'velo': [False, 'c', {'long_name':'speed measurement','make_model':'AEM1-G-ZR'}, nc_scalar], # always scalar
            'sg_cal_velo_A': [False, 'd', {}, nc_scalar],
            'sg_cal_velo_B': [False, 'd', {}, nc_scalar],

            'eng_velo_c0': [True, 'd', {'_FillValue':nc_nan, 'units':'counts', 'description':'Counts', 'instrument':'velo'}, (nc_sg_data_info,)],
            'eng_velo_c1': [True, 'd', {'_FillValue':nc_nan, 'units':'counts', 'description':'Counts', 'instrument':'velo'}, (nc_sg_data_info,)],
            'eng_velo_c2': [True, 'd', {'_FillValue':nc_nan, 'units':'counts', 'description':'Counts', 'instrument':'velo'}, (nc_sg_data_info,)],
            'eng_velo_c3': [True, 'd', {'_FillValue':nc_nan, 'units':'counts', 'description':'Counts', 'instrument':'velo'}, (nc_sg_data_info,)],
            'velo_time': [True, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'Velo time in GMT epoch format'}, (nc_velo_data_info,)],
            # derived results
            nc_velo_time_var: [True, 'd', {'standard_name':'time', 'units':'seconds since 1970-1-1 00:00:00', 'description':'time for AEM velocometer in GMT epoch format'}, (nc_velo_results_info,)],
            'velo_speed': [True, 'd', {'_FillValue':nc_nan, 'standard_name':'speed', 'units':'cm/s', 'description':'Mean raw speed of vehicle along its axis'}, (nc_velo_results_info,)],
            'velo_speed_std': [True, 'd', {'_FillValue':nc_nan, 'units':'cm/s', 'description':'Standard deviation of raw speeds of vehicle along its axis'}, (nc_velo_results_info,)],

            'horz_speed_velo': [False, 'd', {'description':'Vehicle horizontal speed based on velo', 'units':'cm/s'}, (nc_velo_results_info,)],
            'vert_speed_velo': [False, 'd', {'description':'Vehicle vertical speed based on velo', 'units':'cm/s'}, (nc_velo_results_info,)],
            'flight_avg_speed_east_velo': [False, 'd', {'units':'m/s', 'description':'Eastward component of flight average speed based on velo'}, nc_scalar],
            'flight_avg_speed_north_velo': [False, 'd', {'units':'m/s', 'description':'Northward component of flight average speed based on velo'}, nc_scalar],
            'north_displacement_velo': [False, 'd', {'description':'Northward displacement from velo' , 'units':'meters'}, (nc_velo_results_info,)],
            'east_displacement_velo': [False, 'd', {'description':'Eastward displacement from velo', 'units':'meters'}, (nc_velo_results_info,)],
            'depth_avg_curr_east_velo': [False, 'd', {'units':'m/s', 'description':'Eastward component of depth-average current based on velo'}, nc_scalar],
            'depth_avg_curr_north_velo': [False, 'd', {'units':'m/s', 'description':'Northward component of depth-average current based on velo'}, nc_scalar],
            }
        }
    return 0


def sensor_data_processing(base_opts, module, l=None, eng_f=None, calib_consts=None):
    """
    Called from MakeDiveProfiles.py to do sensor specific processing

    Arguments:
    l - MakeDiveProfiles locals() dictionary
    eng_f - engineering file
    calib_constants - sg_calib_constants object

    Returns:
    -1 - error in processing
     0 - data found and processed
     1 - no appropriate data found
    """

    if(l is None or eng_f is None or calib_consts is None or 'results_d' not in l):
        log_error("Missing arguments for sensor_data_processing - version mismatch?")
        return -1

    velo_instrument_metadata_d = fetch_instrument_metadata(nc_velo_data_info)
    if 'ancillary_variables' in velo_instrument_metadata_d:
        del velo_instrument_metadata_d['ancillary_variables'] # eliminate
        
    required_vars_present = True
    try:
        results_d = l['results_d']
        sg_epoch_time_s_v = l['sg_epoch_time_s_v']
        nc_info_d = l['nc_info_d']
        # vehicle_pitch_degrees_v = eng_f.get_col('pitchAng')
    except KeyError:
        required_vars_present = False

    # if you have one you'll have them all or none
    (eng_velo_present, velo_c0_v) = eng_f.find_col(['velo_c0'])
    (eng_velo_present, velo_c1_v) = eng_f.find_col(['velo_c1'])
    (eng_velo_present, velo_c2_v) = eng_f.find_col(['velo_c2'])
    (eng_velo_present, velo_c3_v) = eng_f.find_col(['velo_c3'])
    if eng_velo_present:
        if not required_vars_present:
            log_error("Missing variables for velo eng conversion - bailing out", 'exc')
            return -1
        velo_time_s_v = sg_epoch_time_s_v
        velo_results_dim = nc_mdp_data_info[nc_sg_data_info]
        try:
            velo_A = calib_consts['velo_A'] # intercept
            velo_B = calib_consts['velo_B'] # slope
            ancillary_variables = 'velo_A velo_B'
        except KeyError:
            log_warning("Velo data found but velo_A and velo_B calibration constant(s) missing - skipping velocity conversion")
            return 1
        else:
            velo_counts_v = np.array([velo_c0_v, velo_c1_v, velo_c2_v, velo_c3_v])
            speeds_v = velo_B*velo_counts_v + velo_A
            # compute std as well for each point?
            speed_cm_s_v = np.mean(speeds_v, axis=0)
            std_v = np.std(speeds_v, axis=0)
            # save the results
            velo_instrument_metadata_d['ancillary_variables'] = ancillary_variables # update
            velo_np = len(velo_time_s_v)
            assign_dim_info_dim_name(nc_info_d, nc_velo_results_info, velo_results_dim)
            assign_dim_info_size(nc_info_d, nc_velo_results_info, velo_np)
            results_d.update({
                nc_velo_time_var: velo_time_s_v,
                'velo_speed': speed_cm_s_v,
                'velo_speed_std': std_v,
                })


            try:
                vehicle_pitch_rad_v = l['vehicle_pitch_rad_v']
                gsm_glide_angle_rad_v = l['gsm_glide_angle_rad_v']
                hdm_glide_angle_rad_v = l['hdm_glide_angle_rad_v']
                total_flight_and_SM_time_s = l['total_flight_and_SM_time_s']
                head_polar_rad_v = l['head_polar_rad_v']
                ctd_delta_time_s_v = l['ctd_delta_time_s_v']
                compute_DAC = l['compute_DAC']
            except KeyError:
                log_warning("Unable to compute displacements and DAC from velo data.")
            else:
                # we use the modeled glide angle which includes pitch and attack angle
                # and we use hdm (pitch/buoyancy) rather than gsm
                pitch_rad_v = hdm_glide_angle_rad_v # choose which angle to use...
                horizontal_speed_cm_s_v = speed_cm_s_v*cos(pitch_rad_v)
                vertical_speed_cm_s_v = speed_cm_s_v*sin(pitch_rad_v)
                east_displacement_m_v, north_displacement_m_v, east_displacement_m, north_displacement_m, east_average_speed_m_s, north_average_speed_m_s = \
                                       compute_displacements('velo', horizontal_speed_cm_s_v, ctd_delta_time_s_v, total_flight_and_SM_time_s, head_polar_rad_v)
                results_d.update({
                    'horz_speed_velo': horizontal_speed_cm_s_v,
                    'vert_speed_velo': vertical_speed_cm_s_v,
                    'flight_avg_speed_east_velo': east_average_speed_m_s,
                    'flight_avg_speed_north_velo': north_average_speed_m_s,
                    'east_displacement_velo': east_displacement_m_v,
                    'north_displacement_velo': north_displacement_m_v,
                    })

                if compute_DAC:
                    try:
                        dive_delta_GPS_lat_m = l['dive_delta_GPS_lat_m']
                        dive_delta_GPS_lon_m = l['dive_delta_GPS_lon_m']

                        dac_east_speed_m_s, dac_north_speed_m_s = \
                                                               compute_dac(north_displacement_m_v, east_displacement_m_v,
                                                                           north_displacement_m, east_displacement_m,
                                                                           dive_delta_GPS_lat_m, dive_delta_GPS_lon_m,
                                                                           total_flight_and_SM_time_s)
                        
                        results_d.update({
                            'depth_avg_curr_east_velo': dac_east_speed_m_s,
                            'depth_avg_curr_north_velo': dac_north_speed_m_s,
                            })
                    except KeyError:
                        log_warning("Unable to compute DAC from velo data.\n")
                    
                    

                
            return 0
    else:
        return 1 # No data to process

