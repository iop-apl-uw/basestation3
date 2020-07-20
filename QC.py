#! /usr/bin/env python

## 
## Copyright (c) 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020 by University of Washington.  All rights reserved.
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
## CONTRACT, STRICT LIABILITgY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##
import os
import string
import sys
import re
import math
import pickle
from types import *
from BaseLog import *
from numpy import *
import Utils
from TraceArray import * # REMOVE use only if we are tracing...

f_qclog = None

# Ugh...ARGO stores QC variables as character string representations, rather than as integers
# We maintain all the QC vectors internally as arrays of integers (and originally wrote as such)
# Here we declare how we want to read and write QC variables to netCDF.
# Use 'i' for original integer method, else use 'Q' which is a flag to
# BaseNetCDF.create_nc_var() and MakeDiveProfiles.load_dive_profile_data() to pack and unpack strings appropriately
# God what a hack...
nc_qc_type = 'Q' # the alternative is 'i'
nc_qc_character_base = ord('0')


## For QC indications
# flags used by ARGO
QC_NO_CHANGE     = 0 # no QC performed
QC_GOOD          = 1 # ok
QC_PROBABLY_GOOD = 2 # ...
QC_PROBABLY_BAD  = 3 # potentially correctable
QC_BAD           = 4 # untrustworthy and irreperable
QC_CHANGED       = 5 # explicit manual change
QC_UNSAMPLED     = 6 # explicitly not sampled (vs. expected but missing)
QC_INTERPOLATED  = 8 # interpolated value
QC_MISSING       = 9 # value missing -- instrument timed out

only_good_qc_values = [QC_GOOD, QC_PROBABLY_GOOD, QC_CHANGED]
good_qc_values = [QC_GOOD, QC_PROBABLY_GOOD, QC_CHANGED, QC_INTERPOLATED]
bad_qc_values  = [QC_BAD, QC_PROBABLY_BAD, QC_UNSAMPLED]

qc_name_d = {
    QC_NO_CHANGE: 'QC_NO_CHANGE',
    QC_GOOD: 'QC_GOOD',
    QC_PROBABLY_GOOD: 'QC_PROBABLY_GOOD',
    QC_PROBABLY_BAD: 'QC_PROBABLY_BAD',
    QC_BAD: 'QC_BAD',
    QC_CHANGED: 'QC_CHANGED',
    QC_UNSAMPLED: 'QC_UNSAMPLED',
    QC_INTERPOLATED: 'QC_INTERPOLATED',
    QC_MISSING: 'QC_MISSING',
}

# Initialize QC_flag_meanings and QC_flag_values for metadata use
sorted_QC_keys = sort(list(qc_name_d.keys()))
# prepare as though nc_qc_type == 'Q'
QC_flag_meanings = ""
QC_flag_values = ""
prefix = "";
for key in sorted_QC_keys:
    QC_flag_meanings = QC_flag_meanings + prefix + qc_name_d[key]
    # Spec says flag_values should be a LIST of actual values with the proper type
    # But (BUG in netcdf package) if we encode flags as characters (Q) we create a list of characters
    # e.g., ['1','2',...] which is written as a string '123...' by the netcdf package...
    # So, here and below we write as a string of blank-sparated character values
    # TODO? Avoid the bug by making all qc vectors of type byte 'b'?  Then there is no
    # character encoding and the values are values up to 255.
    QC_flag_values = QC_flag_values + prefix + chr(int(key) + nc_qc_character_base)
    prefix = " " # blank-separated meanings

# Strictly speaking this should ALWAYS be used, whatever the encoding
if (nc_qc_type != 'Q'): # encoding QC values as integers?
    QC_flag_values = sorted_QC_keys; # array of (integer) values


def initialize_qc(length,qc_tag=QC_GOOD):
    '''Create a QC vector of the given length
    '''
    return qc_tag*ones(length)

def trump_qc(qc):
    '''Determine what qc existing values would trump (and hence not change) qc
    '''
    # Implement QC preference rules
    # If an existing qc value is already set to a trump value, don't override it
    trump_qc_v = [] # no trump
    if (qc == QC_INTERPOLATED):
        trump_qc_v = [QC_PROBABLY_BAD, QC_BAD, QC_UNSAMPLED]
    elif (qc == QC_PROBABLY_BAD):
        trump_qc_v = [QC_BAD, QC_UNSAMPLED]
    elif (qc in [QC_GOOD, QC_PROBABLY_GOOD, QC_BAD, QC_UNSAMPLED]):
        pass # these QC values always override
    elif (qc == QC_NO_CHANGE):
        trump_qc_v = list(qc_name_d.keys()) # all values trump NO_CHANGE
    else:
        log_error("No QC preference order for %s!" % qc_name_d[qc])
    trump_qc_v.append(qc) # we can skip those already set
    return trump_qc_v

def update_qc(qc,previous_qc=QC_NO_CHANGE):
    '''Update a scalar QC value, respecting preference order.
    '''
    return previous_qc if previous_qc in trump_qc(qc) else qc
    
def assert_qc(qc, qc_v, indices_v, reason):
    '''Assert qc into the associated qc vector at given indices
    Inputs:
    qc         - the qc value
    qc_v       - the qc array
    indices_v - where to update
    reason     - why the change is made

    Returns:
    None
    
    Side effects:
    qc_v possibly updated at indices_v

    Raises:
    None
    '''
    if (qc == QC_NO_CHANGE):
        return # nothing to do...
    trump_qc_v = trump_qc(qc)
    already_set_i_v = [i for i in indices_v if qc_v[i] in trump_qc_v]
    changed_i_v = Utils.sort_i(Utils.setdiff(indices_v, already_set_i_v))
    if (len(changed_i_v)):
        qc_log((reason, qc, changed_i_v))
        qc_v[changed_i_v] = qc
        trace_array("QC %s -> %d" % (reason, qc), array(changed_i_v)+1) # +1 for matlab
        # succinct_elts adds +1 for matlab to the string result
        elts = Utils.succinct_elts(changed_i_v)
        log_debug("Changed (%d/%d) %s to %s because %s" % (len(changed_i_v), len(qc_v), elts, qc_name_d[qc], reason), loc='parent')
        # be more succinct about QC reports; truncate string if too long
        max_length = 50
        if (len(elts) > max_length):
            for i in range(max_length-3-1, len(elts)):
                if (elts[i] == ' '):
                    elts = '%s ...' % elts[0:i]
                    break;
        log_info("Changed (%d/%d) %s to %s because %s" % (len(changed_i_v), len(qc_v), elts, qc_name_d[qc], reason), loc='parent')
        # log_info("Changed %d of %d points to %s because %s" % (len(changed_i_v),len(qc_v),qc_name_d[qc],reason),loc='parent')

def report_qc(tag, qc_v):
    '''Debugging report on the state of a QC variable
    '''
    return # disable
    np = len(qc_v)
    qc_tags = Utils.sort_i(Utils.unique(qc_v))
    for qc_tag in qc_tags: 
        qc_i_v = [i for i in range(np) if qc_v[i] == qc_tag]
        log_info("QC: %s %d/%d %s %s" % (tag, len(qc_i_v), len(qc_v), qc_name_d[qc_tag], Utils.succinct_elts(qc_i_v)), loc='parent')
    

# An important note about the programmatic use of qc values
# Essesntially there are two phases in the life of a QC tag in a vector
# The first is 'imperative' wherein the code decides something is, say, QC_BAD
# or needs to be QC_INTERPOATED.  The value is asserted and then a later bit of code
# looks at the tags and does something to the associated value (sets it to NaN or
# actually does the interpolation).
# The second is 'declarative' where a change in one variable implies a change in another.
# The classic example is interpolating temp spikes will cause a change in some temp values
# which implies a change in the corresponding derived salinity value. 
# Of course, at the end, you want to declare that salinity was interpolated
# but you don't want to mark it (for) interpolation during the iperative phase.
# For this reason, use inherit_qc after all the calculations are settled down
# based on the imperative phases.
# If you don't, then you will be double interpolating in salinity!!
def inherit_qc(from_qc_v, to_qc_v, from_data_type, to_data_type):
    '''Inherit QC flags from one qc vector to another, handling qc level priority
    Inputs:
    from_qc_v - initial QC vector
    to_qc_v   - inheriting QC vector
    from_data_type - type of initial QC data
    to_data_type - type of inheriting QC data

    Returns:
    None
    
    Side effects:
    tp_qc_v possibly updated

    Raises:
    None
    '''
    np = len(from_qc_v)
    reason = "changed %s implies changed %s" % (from_data_type, to_data_type)
    # NOTE we inherit only non-QC_GOOD tags in this version
    different_i_v = [i for i in range(np) if from_qc_v[i] != QC_GOOD]
    qc_tags = Utils.sort_i(Utils.unique(from_qc_v[different_i_v]))
    for qc_tag in qc_tags: 
        qc_i_v = [i for i in range(np) if from_qc_v[i] == qc_tag]
        assert_qc(qc_tag, to_qc_v, qc_i_v, reason)

def manual_qc(directives, fn, assertion, qc, qc_v, data_type):
    '''Determine if there are any manual updates to the qc vector
    Inputs:
    directives - the dive directives
    fn         - the directive function to evaluate
    assertion  - the attribute to record results on directives
    qc         - the qc value to test and set
    qc_v       - the qc array
    data_type  - the type of measurement data being checked

    Returns:
    indices_i_v - final locations where qv_v is qc
    
    Side effects:
    qc_v possibly updated

    Raises:
    None
    '''
    o_indices_i_v = [i for i in range(len(qc_v)) if qc_v[i] == qc]
    setattr(directives, assertion, o_indices_i_v) # set the new
    indices_i_v = directives.eval_function(fn) # see if the scientist had any input on this matter
    # make (and report) changes
    changed_i_v = Utils.setdiff(o_indices_i_v, indices_i_v)
    if (changed_i_v):
        # the scientist used no_<X> directive on some points, we reset those to QC_GOOD
        assert_qc(QC_GOOD, qc_v, changed_i_v, "%s QC reset manually" % data_type)
    changed_i_v = Utils.setdiff(indices_i_v, o_indices_i_v)
    if (changed_i_v):
        assert_qc(qc, qc_v, changed_i_v, "%s QC set manually" % data_type)
    setattr(directives, assertion, indices_i_v) # update the results (report)
    return indices_i_v

def find_qc(qc_v, qc_values, mask=False):
    '''Find the location (or provide a mask) of entries in qc_v with the given qc values
    Inputs:
    qc_v       - the qc array
    qc_values  - the qc values you are interested in
    mask       - whether you want a mask (True) or a set of indicies (False)

    Returns:
    indices_v  - location (or mask) of those qc values
    '''
    #indices = (map if mask else filter )(lambda i: qc_v[i] in qc_values, list(range(len(qc_v))))
    if mask:
        indices_v = list(map(lambda i: qc_v[i] in qc_values, list(range(len(qc_v)))))
    else:
        # In Python3 filter is a generator - this will screw up downstream consumers
        # who expect the return of this function to look like an array
        indices_v = list(filter(lambda i: qc_v[i] in qc_values, list(range(len(qc_v)))))
    return indices_v

def bad_qc(qc_v, mask=False):
    '''By default return location (or mask) of all "bad" qc values
    Inputs:
    qc_v       - the qc array

    Returns:
    indices_v  - location of "bad" values
    '''
    return find_qc(qc_v, bad_qc_values, mask=mask)

def good_qc(qc_v, mask=False):
    '''By default return location (or mask) of all "good" qc values
    Inputs:
    qc_v       - the qc array

    Returns:
    indices_v  - location of "good" values
    '''
    return find_qc(qc_v, good_qc_values, mask=mask)

def qc_checks_indices(qc_v, ctd_depth_m_v):
    '''Compute indices of good points for qc_checks() below
    Inputs:
    qc_v - array of QC tags corresonding to some data vector to check
    ctd_depth_m_v - the corresponding depths of those data points

    Outputs:
    Various index arrays...
    '''
    # Restrict tests to apparently good points
    bad_i_v = bad_qc(qc_v)
    ia_v = array(Utils.setdiff(arange(0, len(qc_v)), bad_i_v)) # indices to all non-bad points
    gp = len(ia_v)
        # for mapping over triples
    im_v = array(ia_v[0:gp-2]) # indices for gradients/spikes
    ic_v = array(ia_v[1:gp-1])
    ip_v = array(ia_v[2:gp+0])
    if gp:
        diff_depth_m_v = abs((ctd_depth_m_v[ip_v] - ctd_depth_m_v[im_v])/2.0)
        bad_d_i = [i for i in range(gp-2) if diff_depth_m_v[i] == 0.0]
        diff_depth_m_v[bad_d_i] = 0.001 # avoid divide by zero below
    else:
        diff_depth_m_v = []
    return (ia_v, im_v, ic_v, ip_v, len(ic_v), diff_depth_m_v)

def qc_noise(data_v, window_size=15, std_band=3):
    '''Handle scicon CT noise (electronic) at high sample speeds
    By detrending the signal and removing points that are unlikely to be valid
    Inputs:
    data_v -- a data array
    window_size -- number of points to use during detrending; 0 disables
    std_band -- number of standard deviations permitted before rejecting point
    
    Returns:
    bad_i_v -- location of noise points
    '''
    if window_size == 0:
        return [] # disabled, nothing bad

    if window_size > len(data_v):
        window_size = len(data_v)
        
    data_filtered_v = Utils.medfilt1(data_v, window_size) # how do we compute the proper window size?
    diff_data_v = data_v - data_filtered_v # compute detrended data
    noise_floor = std_band*std(diff_data_v) # good chance of being spurious
    diff_data_v = abs(diff_data_v)
    bad_i_v = [i for i in range(len(data_v)) if diff_data_v[i] > noise_floor]
    return bad_i_v

# CONSIDER arguments temp=[],temp_qc=[],...
# you can call this with [] as values and qc pair and it will skip the associated tests. thus
# qc_checks([],[],[],[],salin_TS,QC_GOOD*ones(mp,1),ctd_depth_m) checks only salinity
# NOTE: in python, the _qc vectors are updated by side-effect so return values are not strictly needed
# CONSIDER making high-frequency noise filter available via a QC declaration? QC_temp_noise, QC_cond_noise, etc. Default is 0, no.
def qc_checks(temp_v,temp_qc_v,cond_v,cond_qc_v,salin_v,salin_qc_v,ctd_depth_m_v,calib_consts,qc_bound_action,qc_spike_action,tag='',perform_scicon_noise_filter=False):
    '''Performs standard (ARGO) quality control checks on temp_v, cond_v, and salinity
    Inputs:
    temp_v     - array of temperatures (or [])
    temp_qc_v  - array of initial temperature QC tags (or [])
    cond_v     - array of conductivities (or [])
    cond_qc_v  - array of initial conductivities QC tags (or [])
    salin_v    - array of salinities (or [])
    salin_qc_v - array of initial salinity QC tags (or [])
    ctd_depth_m_v - depth of CT sensor [m]
    calib_consts - calibration constants, including QC bounds below
    qc_bound_action - what QC flag to use on bound violations
    qc_spike_action - what QC flag to use on spike detections
    tag - a distinguishing tag, with trailing space if provided
    perform_scicon_noise_filter -- whether to apply SCICON noise filter to C and T data
    Returns:
    temp_qc_v  - array of modified temperature QC tags (or [])
    cond_qc_v  - array of modified conductivities QC tags (or [])
    salin_qc_v - array of modified salinity QC tags (or [])

    Raises:
    None
    '''
    perform_cond_bounds_check = False # was True
    if perform_scicon_noise_filter:
        try:
            perform_scicon_noise_filter = calib_consts['QC_high_freq_noise']
        except KeyError:
            perform_scicon_noise_filter = 15 # should never get here; this is the default in MDP:sg_config_constants()
    # Spread parameters that control the basic QC tests
    QC_temp_min = calib_consts['QC_temp_min']
    QC_temp_max = calib_consts['QC_temp_max']
    
    QC_temp_spike_depth = calib_consts['QC_temp_spike_depth']
    QC_temp_spike_shallow = calib_consts['QC_temp_spike_shallow']
    QC_temp_spike_deep = calib_consts['QC_temp_spike_deep']

    if perform_cond_bounds_check:
        QC_cond_min = calib_consts['QC_cond_min'] # DEAD
        QC_cond_max = calib_consts['QC_cond_max'] # DEAD
    
    QC_cond_spike_depth = calib_consts['QC_cond_spike_depth']
    QC_cond_spike_shallow = calib_consts['QC_cond_spike_shallow']
    QC_cond_spike_deep = calib_consts['QC_cond_spike_deep']
    
    QC_salin_min = calib_consts['QC_salin_min']
    QC_salin_max = calib_consts['QC_salin_max']

    QC_overall_ctd_percentage = calib_consts['QC_overall_ctd_percentage']
        
    np = len(ctd_depth_m_v)
    if (np <= 3):
        return (temp_qc_v, cond_qc_v, salin_qc_v) # no checks, no change

    # Determine which checks we should perform -- who supplied data of any sort?
    do_temp_checks =  (len(temp_v)  == np)
    do_cond_checks =  (len(cond_v)  == np)
    do_salin_checks = (len(salin_v) == np)
    

    # Note on the spike detector;
    # We have three points, m,c,p for minus, center, and positive points
    # we want to know if the center point is a spike wrt to the linear trend between minus and positive points
    # so we estimate ((center_observed - average_between_minus_and_positive) - observed_difference_between_minus_positive)
    # thus we estimate the variance from the expected midpoint between the minus and the positive point
    # scaled by the average depth difference between the minus and positive points (see above)

    
    # TODO Depths (pressures) change monotonically start of dive to apogee and apogee to end of climb??
    # TODO Density inversions? (sigma0) change monotonically start of dive to apogee and apogee to end of climb??
    # TODO Impossible speed tests (w and/or u?)
    # NOTE: Carnes has a too slow speed of 5cm/s and uses averaged speed data, 3cm/s in ranges, etc. (STALLS for unpumped)
    # nails salin_qc_v
    if (do_temp_checks):
        ia_v, im_v, ic_v, ip_v, ncp, diff_depth_m_v = qc_checks_indices(temp_qc_v, ctd_depth_m_v)
        if ncp:
            # Temperature bounds test (5.1.2)
            bad_i_v = [i for i in ia_v if (temp_v[i] < QC_temp_min or temp_v[i] > QC_temp_max)]
            assert_qc(qc_bound_action, temp_qc_v, bad_i_v, "%stemperature bounds" % tag)
        
            # TODO: regional test.  if GPS2/GPS are ok, use avg_lat/lon 
            if (False):
                # bounding region and ranges (lat/long)
                # Our solution: The PI puts the new ranges in sg_calib_constants if in these (or other) regions
                # red_sea = [[10 -40],[20 -50],[30,-30],[10,-40]] # T = 21.7 to 40, S = 2 to 41
                # med_sea = [[30   6],[30 -40],[40,-35],[30,  6]] # T = 10.0 to 40, S = 2 to 40
                pass

            # no GDEM climatology yet (5.1.3)
            # Temperature spike test (5.1.4)
            if (QC_temp_spike_depth): # are we enabled?
                temp_spike = (abs(temp_v[ic_v] - (temp_v[ip_v] + temp_v[im_v])/2) - abs((temp_v[ip_v] - temp_v[im_v])/2))/diff_depth_m_v
                bads_i_v = [i for i in range(ncp) if (ctd_depth_m_v[ic_v[i]] <  QC_temp_spike_depth) and (temp_spike[i] > QC_temp_spike_shallow)]
                badd_i_v = [i for i in range(ncp) if (ctd_depth_m_v[ic_v[i]] >= QC_temp_spike_depth) and (temp_spike[i] > QC_temp_spike_deep)]
                bad_s_i_v = Utils.union(bads_i_v, badd_i_v)
                badts_i_v = ic_v[bad_s_i_v] # mark the middle points
                assert_qc(qc_spike_action, temp_qc_v, badts_i_v, "%stemperature spikes" % tag)

            if (perform_scicon_noise_filter):
                bad_i_v = qc_noise(temp_v[ia_v], perform_scicon_noise_filter)
                bad_i_v = ia_v[bad_i_v];
                assert_qc(qc_spike_action, temp_qc_v, bad_i_v, "%stemperature noise spikes" % tag)
            
    if (do_salin_checks):
        ia_v, im_v, ic_v, ip_v, ncp, diff_depth_m_v = qc_checks_indices(salin_qc_v, ctd_depth_m_v)
        if ncp:
            # Salinity bounds test (5.1.9)
            bad_il_v = [i for i in ia_v if (salin_v[i] < QC_salin_min)]
            assert_qc(qc_bound_action, salin_qc_v, bad_il_v, "%ssalinity below bound" % tag)
            bad_iu_v = [i for i in ia_v if (salin_v[i] > QC_salin_max)]
            assert_qc(qc_bound_action, salin_qc_v, bad_iu_v, "%ssalinity exceeds bound" % tag)

            # the cond values fluctuate too much by temp and pressure to give a meaningful bound
            # but salinity does not.  so if salinity goes bad, if not temp it must be cond
            if do_cond_checks and not perform_cond_bounds_check:
                bad_b_i_v = Utils.union(bad_il_v, bad_iu_v);
                if do_temp_checks:
                    badt_i_v = bad_qc(temp_qc_v)
                    bad_b_i_v = Utils.setdiff(bad_b_i_v, badt_i_v); # if already bad temp, skip
                assert_qc(qc_bound_action, cond_qc_v, bad_b_i_v, "bad %ssalinity indicates %sconductivity issues" % (tag, tag))
                    
    if (do_cond_checks):
        ia_v, im_v, ic_v, ip_v, ncp, diff_depth_m_v = qc_checks_indices(cond_qc_v, ctd_depth_m_v)
        if ncp:
            # NOTE: ARGO has no conductivity tests
            # Conductivity bounds test
            # the cond values fluctuate too much by temp and pressure to give a meaningful bound
            if perform_cond_bounds_check:
                bad_i_v = [i for i in ia_v if (cond_v[i] < QC_cond_min or cond_v[i] > QC_cond_max)]
                assert_qc(qc_bound_action, cond_qc_v, bad_i_v, "%sconductivity bounds" % tag)


            # Conductivity spike test (5.1.6)
            if (QC_cond_spike_depth):
                cond_spike = (abs(cond_v[ic_v] - (cond_v[ip_v] + cond_v[im_v])/2) - abs((cond_v[ip_v] - cond_v[im_v])/2))/diff_depth_m_v
                bads_i_v = [i for i in range(ncp) if (ctd_depth_m_v[ic_v[i]] <  QC_cond_spike_depth) and (cond_spike[i] > QC_cond_spike_shallow)]
                badd_i_v = [i for i in range(ncp) if (ctd_depth_m_v[ic_v[i]] >= QC_cond_spike_depth) and (cond_spike[i] > QC_cond_spike_deep)]
                bad_s_i_v = Utils.union(bads_i_v, badd_i_v)
                badcs_i_v = ic_v[bad_s_i_v] # mark the middle points
                assert_qc(qc_spike_action, cond_qc_v, badcs_i_v, "%sconductivity spikes" % tag)

            if (perform_scicon_noise_filter):
                bad_i_v = qc_noise(cond_v[ia_v], perform_scicon_noise_filter)
                bad_i_v = ia_v[bad_i_v];
                assert_qc(qc_spike_action, cond_qc_v, bad_i_v, "%sconductivity noise spikes" % tag)

    return (temp_qc_v, cond_qc_v, salin_qc_v)

def ensure_increasing_time(time_v, time_name, sg_epoch_start_time_s):
    '''Ensure the time vector (elapsed or epoch) is increasing by interpolation if needed
    Inputs:
    time_v -- the time vector, in epoch time
    time_name -- a description of the time vector
    sg_epoch_start_time_s -- when the glider started taking data

    Returns:
    corrected_time_v -- the possibly corrected time vector
    bad_time_i_v -- the points where time stood still or went backwards
    '''
    corrected_time_v = time_v
    diff_time_v = diff(time_v)
    bad_time_i_v = [i for i in range(len(diff_time_v)) if diff_time_v[i] <= 0]

    if (len(bad_time_i_v)):
        log_error("%d bad time points in %s" % (len(bad_time_i_v), time_name))
        # Reconstitute time with small time offset
        # This is incorrect if this is from scicon and the RTC has failed
        # If this is the case the bad point is between the end of the a and the start of the b cast (apogee)
        # and the correction should be the length of apogee 
        diff_time_v[bad_time_i_v] = 0.001;
        corrected_time_v[1:] = time_v[1] + cumsum(diff_time_v)
            
    if (len(time_v) == 0):
        log_error("No time points in %s" % time_name)
        return (corrected_time_v, bad_time_i_v)

    if (len(corrected_time_v) <= 1):
        log_warning("Time vector only one point long")
        return (corrected_time_v, bad_time_i_v)
    
    offset_s = corrected_time_v[1] - sg_epoch_start_time_s
    # Original problem was clocks on STM32 loggers wildly incorrect due to the RTC not holding time (generally,
    # the coin cell battery had failed).  Now the glider transmists the time to the STM32 loggers, so the logger
    # it does this correction itself.
    #
    # The correction code (commented out below) fails for a logger that is only reporting the upcast
    if (abs(offset_s) > 600): 
        log_warning("%s different from SG clock by %f seconds" % (time_name, offset_s))
        #corrected_time_v = corrected_time_v - offset_s
    else:
        log_debug("%s off from SG clock by %f seconds; continuing without correction." % (time_name, offset_s))
            
    return (corrected_time_v, bad_time_i_v)

def interpolate_data_qc(y_v, x_v, interp_points_i_v, type, directives, qc_v, qc_tag):
    '''Returns possibly linearly interpolated y_v wrt x_v at regions defined by interp_points_i_v
    Anchors are given by interp_anchors_i_v, if any
    qc_v vector possibly updated if interpolation is not possible
    
    Inputs:
    y_v - initial y float values
    x_v - initial x float values
    interp_points_i_v  - locations to interpolate
    type   - string indicating type of data
    directives - the dive directives
    qc_v     - qc values for y_v
    qc_tag - qc tag to use if we fail to interpolate

    Returns:
    y_interp_v - possibly interpolated y_v
    qc_v       - possibly modified qc_v values for y_v (also by side effect)
    
    Raises:
    None
    '''
    y_interp_v = array(y_v) # initialize with a copy
    if (len(interp_points_i_v)): # or len(interp_points_i_v)
        diff_interp_points_i_v = diff(interp_points_i_v)
        breaks_i_v = [i for i in range(len(diff_interp_points_i_v)) if diff_interp_points_i_v[i] > 1]
        breaks_i_v.append(len(interp_points_i_v)-1) # add the final point
        np = len(y_v)-1 # for range below
        last_i = 0
        for break_i in breaks_i_v:
            pre_index = interp_points_i_v[last_i]
            post_index = interp_points_i_v[break_i]
            ip_i_v = arange(pre_index, post_index+1) # before extension to anchors
            pre_index = max(pre_index - 1, 0)
            post_index = min(post_index + 1, np)
            interp_i_v = arange(pre_index, post_index+1) # which points to recompute
            anchors_i_v = array([pre_index, post_index])
            bad_anchors_i_v = bad_qc(qc_v[anchors_i_v])
            if (len(bad_anchors_i_v)):
                if (any([i for i in ip_i_v if qc_v[i] == QC_INTERPOLATED])):
                    # only suggest this if there were points that needed work (they could all be BAD)
                    reason = 'bad interpolation anchors'
                    assert_qc(qc_tag, qc_v, ip_i_v, reason)
                    directives.suggest("bad_%s data_points in_between %d %d %% %s" % (type, pre_index, post_index, reason))
            else:
                coefficents = polyfit(x_v[anchors_i_v], y_v[anchors_i_v], 1) # linear fit amongst the anchors
                if (any(isnan(coefficents)) or any(isinf(coefficents))):
                    reason = 'unable to interpolate (NaN/Inf)'
                    assert_qc(qc_tag, qc_v, ip_i_v, reason)
                    directives.suggest("bad_%s data_points in_between %d %d %% %s" % (type, pre_index, post_index, reason))
                else:
                    y_interp_v[interp_i_v] = polyval(coefficents, x_v[interp_i_v]) # actually interpolate
            last_i = break_i+1
    return (y_interp_v, qc_v)

def encode_to_str(x):
    ret_val = ''
    for v in x:
        ret_val += chr(int(v) + nc_qc_character_base)
    return(ret_val)

def encode_qc(qc_v):
    '''Ensure qc vector is encoded for writing to netCDF based on nc_qc_type'''
    type_qc = type(qc_v)
    if type_qc in ScalarType:
        scalar = True
    else:
        scalar = False
        type_qc = type(qc_v[0].item()) # get equivalent python scalar type
    if nc_qc_type == 'Q':
        if type_qc is float or type_qc is int:
            if scalar:
                qc_v = chr(int(qc_v) + nc_qc_character_base)
            else: # array
                # For Python3, tostring is not an string, but an array of bytes that is the underlying
                # in-memory representation
                # qc_v = array([chr(int(v) + nc_qc_character_base) for v in qc_v]).tostring()
                qc_v = encode_to_str(qc_v)
        elif type_qc is str:
            pass
    else: # must be 'i'
        if type_qc is float or type_qc is int:
            pass # netcdf will coerce 
        elif type_qc is str:
            qc_v = decode_qc(qc_v)
    return qc_v

def decode_qc(qc_v):
    '''Ensure qc vector is a vector of floats'''
    type_qc = type(qc_v)
    if type_qc in ScalarType:
        scalar = True
    else:
        scalar = False
        type_qc = type(qc_v[0].item()) # get equivalent python scalar type
    if nc_qc_type == 'Q':
        if type_qc is float or type_qc is int:
            return qc_v
        elif type_qc is str:
            pass # decode below
    else: # must be 'i'
        if type_qc is float or type_qc is int:
            return qc_v # netcdf will coerce 
        elif type_qc is str:
            pass # must be from a previous setting of encode? decode below
    # if we get here, type_qv is str
    if scalar:
        qc_v = float(ord(qc_v[0])) - nc_qc_character_base
    else: # array
        qc_v = array(list(map(ord, qc_v)), float64) - nc_qc_character_base
    return qc_v

class ProfileDirectives(object):
    comment = re.compile(r'%.*') # % and anything after it, to a newline
    no_prefix = 'no_'
    drv_functions = ['bad_temperature', 'interp_temperature',
                     'bad_conductivity', 'interp_conductivity',
                     'bad_salinity', 'interp_salinity']
    drv_predicates = ['skip_profile',
                      # TODO consider echoing these comments in the global comment field of the nc file (after any NODC.cnf contributions)
                      'comment', # ignored but good for commenting on a dive w/o other directives present
                      'reviewed',
                      'interp_gc_temperatures',
                      'correct_thermal_inertia_effects',
                      'interp_suspect_thermal_inertia_salinities',
                      'detect_conductivity_anomalies',
                      'bad_gps1', 'bad_gps2', 'bad_gps3',
                      ]

    def __init__(self,mission_dir,dive_num,filename=None):
        self.dive_num = dive_num # functions apply to this dive only
        self.functions = [] # tokenized function lines w/o comments
        self.lines = [] # the valid lines with comments for this dive
        self.comments = [] # the comments preceding an applicable function
        self.suggestions_filename = os.path.join(mission_dir, 'sg_directives_suggestions.txt')
        if (filename):
            self.parse_file(filename)

    def __str__(self):
        return ("<%d edit functions for dive %d>" % (len(self.functions), self.dive_num))

    def parse(self, line):
        '''Tokenize line for use in eval function
        Retain only if it applies to this dive
        Retain comments as well
        '''
        # should we save comments and original line if successful?
        # accumulate comment lines before the successful lines as well?
        line = line.rstrip()
        line = line.replace('\t', ' ')
        statement = line
        if self.comment.search(line):
            statement, after = self.comment.split(line)
        if (statement in ['', '\n']): # empty?
            return None
        values = statement.split(' ')
        values = [v for v in values if v != '']
        dive_spec = values[0]
        try:
            if (dive_spec != '*'): # applies to all dives or this dive?
                spec_strs = dive_spec.split(':', 1)
                if (len(spec_strs) == 2):
                    start_num = int(spec_strs[0])
                    end_num = int(spec_strs[1])
                else:
                    start_num = int(dive_spec)
                    end_num = start_num
                if (self.dive_num != '*' and (self.dive_num < start_num or self.dive_num > end_num)):
                    self.comments = [] # reset
                    return None # This line does not apply
        except ValueError:
            log_warning("Unknown dive specifier '%s' in '%s'" % (dive_spec, line))
            
        # this function applies to all or this dive_number
        function_tag = values[1]
        f = function_tag
        l_no = len(self.no_prefix)
        if (len(f) > l_no):
            if (f[0:l_no] == self.no_prefix):
                f = f[l_no:]
        if (not (f in self.drv_functions or f in self.drv_predicates)):
            log_warning("Unknown directive '%s' in '%s'" % (function_tag, line))

        function = [dive_spec, function_tag]
        for arg in values[2:]:
            if (arg == ''):
                continue; # skip empties
            # validate non-integers?
            function.append(arg)
        self.functions.append(function)
        self.lines.extend(self.comments)
        self.comments = [] # reset
        self.lines.append(line)
        return function

    # print all functions in a single string (for dumping to nc file)
    # just append the saved strings AND their comments?
    def dump_string(self):
        '''Form composite string of comments and functions for this instance
        '''
        string = ''
        for line in self.lines:
            string += line + '\n'
        return string
    
    def parse_string(self, string):
        '''Parse comments and functions from string
        This could be the output of dump_string(), which see
        '''
        self.comments = [] # reset
        for line in string.split('\n'):
            self.parse(line)
        return None

    def parse_file(self, filename):
        '''Parse comments and functions from filename
        '''

        try:
            file = open(filename)
        except:
            log_error("Unable to open %s" % filename)
            return None
        self.comments = [] # reset
        for line in file.readlines():
            self.parse(line) # update functions by side-effect
        file.close() # needed?
        return None
    
    def eval_function(self, function_tag, absent_predicate_value=False):
        '''Evaluate and return the indices for a specific function
        '''

        indices = []
        f = function_tag
        l_no = len(self.no_prefix)
        if (len(f) > l_no):
            if (f[0:l_no] == self.no_prefix):
                f = f[l_no:]
        if (f in self.drv_functions):
            indices = self.eval_set(f, indices)
        elif (f in self.drv_predicates):
            indices = self.eval_predicate(f, absent_predicate_value)
        else:
            # this is a function called from basestation code that we can't eval
            log_error("Unknown directive in basestation code  '%s'" % function_tag)
        return indices

    def eval_arg(self, arg):
        try:
            value = eval('self.' + arg)
        except:
            try:
                value = int(arg) # try for a number
            except ValueError:
                log_warning("Unknown directive argument '%s' ignored" % arg)
                value = 0
        return value

    def eval_set(self,function_tag,indices=[]):
        statements = []
        no_statements = []
        no_function_tag = self.no_prefix + function_tag
        for function in self.functions:
            fn = function[1]
            if (fn == function_tag):
                statements.append(function)
            elif (fn == no_function_tag):
                no_statements.append(function)
        # Add these indices
        for statement in statements:
            sub_i_v = self.eval_range(statement)
            indices = Utils.sort_i(Utils.union(indices, sub_i_v))
        # Remove these indices
        for statement in no_statements:
            sub_i_v = self.eval_range(statement)
            indices = Utils.sort_i(Utils.setdiff(indices, sub_i_v))
        return indices

    def eval_range(self, statement):
        args = statement[2:]
        if (len(args) >= 1):
            index_name = args[0]
            try:
                values = eval('self.' + index_name)
                args = args[1:] # strip the specifier
            except:
                log_warning("Missing a location in '%s'; assuming 'data_points'" % string.join(statement))
                values = self.data_points
            l_values = len(values)
            if (len(args) >= 1):
                # We have a restriction
                arg = args[0]
                if (arg == 'between'):
                    first_v = self.eval_arg(args[1])
                    last_v = self.eval_arg(args[2])
                    if (first_v < last_v):
                        indices = [i for i in range(l_values) if values[i] >= first_v and values[i] <= last_v]
                    else:
                        indices = [i for i in range(l_values) if values[i] >= last_v and values[i] <= first_v]
                elif (arg == 'in_between'):
                    first_v = self.eval_arg(args[1])
                    last_v = self.eval_arg(args[2])
                    if (first_v < last_v):
                        indices = [i for i in range(l_values) if values[i] >= first_v+1 and values[i] <= last_v-1]
                    else:
                        indices = [i for i in range(l_values) if values[i] >= last_v+1  and values[i] <= first_v-1]
                elif (arg in ['below', 'less_than', 'before']):
                    first_v = self.eval_arg(args[1])
                    indices = [i for i in range(l_values) if values[i] < first_v]
                elif (arg in ['above', 'greater_than', 'after']):
                    first_v = self.eval_arg(args[1])
                    indices = [i for i in range(l_values) if values[i] > first_v]
                else: # must be 'at'
                    if (arg == 'at'): # equal
                        args = args[1:]
                    else:
                        log_warning("Missing 'at' in '%s'" % string.join(statement))
                    indices = []
                    for arg in args:
                        try:
                            # Explicitly not self.eval_arg(arg) -- we expect numbers of all kinds
                            farg = float(arg) # this also matches integers...
                            i_v = [i for i in range(l_values) if values[i] == farg]
                            indices.extend(i_v)
                        except ValueError:
                            log_error("%s not a number in '%s'" % (arg, string.join(statement)))
            else:
                indices = values # values should be indices
        else:
            indices = [0]
        return Utils.sort_i(Utils.unique(indices))
        

    def eval_predicate(self, function_tag, absent_predicate_value):
        '''Returns True if function_tag is bound, False if no_function_tag is bound else False
        Used for boolean control tags like skip_profile, etc.
        '''
        # BUG if you have x and no_x, the final value depends on the order!
        # at the moment, specific directives from a sg_directive.txt file
        # dominate any default directive. first-come first-served.
        # This is not the same as set behavior.  and if there are two or more
        # specific statements, again, the first wins
        predicate = -1 # not assigned yet
        try:
            value = eval('self.' + function_tag)
        except:
            value = absent_predicate_value # default
        no_function_tag = self.no_prefix + function_tag
        for function in self.functions:
            fn = function[1]
            if (fn == function_tag):
                if (predicate == -1):
                    predicate = 1
                elif (predicate == 0):
                    #DEBUG log_warning("Mixed predicate assertions for %s, assuming %d" % (function_tag,predicate))
                    pass
            elif (fn == no_function_tag):
                if (predicate == -1):
                    predicate = 0
                elif (predicate == 1):
                    #DBEUG log_warning("Mixed predicate assertions for %s, assuming %d" % (function_tag,predicate))
                    pass
        if (predicate == 1):
            return True
        elif (predicate == 0):
            return False
        else: # -1
            return value

    def suggest(self, suggestion):
        '''Emits a suggestion
        '''
        if (not self.reviewed):
            if (self.dive_num):
                suggestion = "%d %s" % (self.dive_num, suggestion)
            log_info("SUGGESTION: %s" % suggestion, loc='parent')
            if (True):
                try:
                    so = open(self.suggestions_filename, 'a')
                    so.write("%s\n" % suggestion)
                    so.close()
                except: # unable to open or close file?
                    pass

def qc_log_start(file_name):
    global f_qclog
    f_qclog = open(file_name, "w")
    return

def qc_log_stop():
    global f_qclog
    if f_qclog:
        f_qclog.close()
    return
    
def qc_log(value):
    global f_qclog
    if f_qclog:
        pickle.dump(value, f_qclog)
    return
