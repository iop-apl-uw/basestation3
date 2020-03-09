#! /usr/bin/env python

## 
## Copyright (c) 2018, 2019, 2020 by University of Washington.  All rights reserved.
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

from numpy import *
import time

# Plotting configuration
make_plot_section = 'makeplot'
make_plot_default_dict = {'plot_raw' : [0, 0, 1],
                          'save_svg' : [0, 0, 1],
                          'full_html' : [0, 0, 1],
                          'plot_directory' : [None, None, None]
}

#
# Utility Routines
#
def get_mission_dive(dive_nc_file):
    """ Gets common information for all plot headers

    Input:
         dive_nc_file - netcdf file object

    Returns: 
         String containing the mission title
    """
    log_id = 0
    log_dive = 0
    mission_title = ''
    if('log_ID' in dive_nc_file.variables):
        log_id = dive_nc_file.variables['log_ID'].getValue()
    if('log_DIVE' in dive_nc_file.variables):
        log_dive = dive_nc_file.variables['log_DIVE'].getValue()
    if('sg_cal_mission_title' in dive_nc_file.variables):
        mission_title = dive_nc_file.variables['sg_cal_mission_title'][:].tostring().decode('utf-8')

    if hasattr(dive_nc_file, 'start_time'):
        start_time = time.strftime("%d-%b-%Y %H:%M:%S ", time.gmtime(dive_nc_file.start_time))
    else:
        start_time = '(No start time found)'

    return "SG%03d %s Dive %d Started %s" % (log_id, mission_title, log_dive, start_time)

def get_mission_str(dive_nc_file):
    """ Gets common information for all plot headers
    """
    log_id = None
    mission_title = ''
    if('log_ID' in dive_nc_file.variables):
        log_id = dive_nc_file.variables['log_ID'].getValue()
    if('sg_cal_mission_title' in dive_nc_file.variables):
        mission_title = dive_nc_file.variables['sg_cal_mission_title'][:].tostring().decode('utf-8')
    return "SG%s %s" % ('%03d' % (log_id if log_id else '???', ), mission_title)

def get_mission_str_comm_log(comm_log, calib_constants):
    """ Gets common information for all plot headers
    """
    log_id = None
    mission_title = ''
    if('sg_cal_mission_title' in dive_nc_file.variables):
        mission_title = dive_nc_file.variables['sg_cal_mission_title'][:].tostring().decode('utf-8')
    for s in comm_log.sessions:
        if(s._sg_id is not None):
            log_id = s._sg_id
            break
    return "SG%s %s" % ('%03d' % log_id if log_id else '???', mission_title)

    
