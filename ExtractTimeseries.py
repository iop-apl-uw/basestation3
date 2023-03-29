#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
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
"""Routines for extracting profiles from dive timeseries files
"""

import sys
import json
from json import JSONEncoder
import Globals

import numpy
from scipy.io import netcdf_file
import scipy.interpolate

import Utils

def binData(d, x, bins):
    data_binned = scipy.stats.binned_statistic(d, x, statistic='mean', bins=bins)
    return numpy.transpose(data_binned.statistic)

class NumpyArrayEncoder(JSONEncoder):
    def default(self, obj):
        if isinstance(obj, numpy.ndarray):
            return obj.tolist()

        return JSONEncoder.default(self, obj)    
   
def dumps(d):
    return json.dumps(d, cls=NumpyArrayEncoder)
 
def timeSeriesToProfile(var, which, 
                        diveStart, diveStop, diveStride, 
                        binStart, binStop, binSize, ncfilename, nci=None, x=None):

    if nci == None:
        try:
            nci = Utils.open_netcdf_file(ncfilename, "r")
        except:
            print(f"Unable to open {ncfilename}")
            return None

    message = {}
    message[var] = []
    message['dive'] = []
    message['which'] = []

    bins = [ *range(binStart, binStop + int(binSize/2), binSize) ]
    dives = range(diveStart, diveStop + 1, diveStride)

    if which == Globals.WhichHalf.both:
        arr = numpy.zeros((len(bins) - 1, len(dives)*2))
    else:
        arr = numpy.zeros((len(bins) - 1, len(dives)))
  
    if x == None:
        x = extractProfileVars(None, ['ctd_time', 'ctd_depth', var], nci=nci)

    nan = numpy.empty((len(bins) - 1, ))
    nan[:] = numpy.nan

    i = 0
    for p in dives:

        t0 = nci.variables['start_time'][p-1]
        t1 = nci.variables['deepest_sample_time'][p-1]
        t2 = nci.variables['end_time'][p-1]
    
        if which in (Globals.WhichHalf.down, Globals.WhichHalf.both):
            ixs = (x['ctd_time'] > t0) &(x['ctd_time'] < t1)
            if sum(1 for x in ixs if x) > 0:
                d = scipy.stats.binned_statistic(x['ctd_depth'][ixs],
                                             x[var][ixs], statistic='mean', bins=bins).statistic

                if d is not None:
                    arr[:,i] = d.T
                else:
                    arr[:,i] = nan

                message['dive'].append(p + 0.25)
                message['which'].append(1)
                i = i + 1

        if which in (Globals.WhichHalf.up, Globals.WhichHalf.both):
            ixs = (x['ctd_time'] > t1) & (x['ctd_time'] < t2)
            if sum(1 for x in ixs if x) > 0:
                d = scipy.stats.binned_statistic(x['ctd_depth'][ixs],
                                             x[var][ixs], statistic='mean', bins=bins).statistic

                if d is not None:
                    arr[:,i] = d.T
                else:
                    arr[:,i] = nan

                message['dive'].append(p + 0.75)
                message['which'].append(2)
                i = i + 1

        if which == Globals.WhichHalf.combine:
            ixs = (x['ctd_time'] > t0) & (x['ctd_time'] < t2)
            if sum(1 for x in ixs if x) > 0:
                d = scipy.stats.binned_statistic(x['ctd_depth'][ixs],
                                             x[var][ixs], statistic='mean', bins=bins).statistic
            
                if d is not None:
                    arr[:,i] = d.T
                else:
                    arr[:,i] = nan

                message['dive'].append(p + 0.5)
                message['which'].append(4)
                i = i + 1

    message['depth'] = bins
    message[var] = arr[:,0:i]

    return (message, x)

def getVarNames(nc_filename, nc_file=None):

    if nc_file == None:
        try:
            nc_file = Utils.open_netcdf_file(nc_filename, "r")
        except:
            print(f"Unable to open {nc_filename}")
            return None

    vars = []

    for k in nc_file.variables.keys():
        if len(nc_file.variables[k].dimensions) and '_data_point' in nc_file.variables[k].dimensions[0] and '_dive_number' not in k:
            vars.append({'var': k, 'dim': nc_file.variables[k].dimensions[0]})
            
    nc_file.close()

    return vars

def extractVars(nc_filename, varNames, dive1, diveN, nci=None):
    if nci == None:
        try:
            nci = Utils.open_netcdf_file(nc_filename, "r")
        except:
            print(f"Unable to open {nc_filename}")
            return None

    t0 = nci.variables['start_time'][dive1-1]
    t2 = nci.variables['end_time'][diveN-1]
    base_t = None
    base_t_len = 0
    base_p = None

    x = {}
    for p in varNames:
        x[p] = {}

        var = nci.variables[p][:]
        dim = nci.variables[p].dimensions[0]

        var_t = []
        if 'time' in varNames[-4:]:
            var_t = var
        else:
            for k in nci.variables.keys():
                if 'time' in k[-4:] and len(nci.variables[k].dimensions) and '_data_point' in nci.variables[k].dimensions[0] and dim == nci.variables[k].dimensions[0]:
                    var_t = nci.variables[k][:]
                    break 

        if len(var_t):
            ixs = (var_t > t0) & (var_t < t2)
            x[p]['t'] = var_t[ixs]
            x[p]['value'] = var[ixs]

        if len(var_t[ixs]) > base_t_len:
            base_t = var_t[ixs]
            base_p = p

    message = {}
    message['epoch'] = base_t.tolist()
    message['time']  = (base_t - base_t[0]).tolist()
    message[base_p] = x[p]['value'].tolist()
    for p in varNames:
        if p == base_p:
            continue

        message[p] = numpy.interp(base_t, x[p]['t'], x[p]['value']).tolist()

    return message

def extractProfileVars(nc_filename, plot_vars, nci=None):
    if nci == None:
        try:
            nci = Utils.open_netcdf_file(nc_filename, "r")
        except:
            print(f"Unable to open {nc_filename}")
            return None

    message = {}

    for p in plot_vars:
        try:
            var = nci.variables[p][:]
            dim = nci.variables[p].dimensions[0]
            if dim != 'ctd_data_point':
                for k in nci.variables.keys():
                    var_t = []
                    if 'time' in k[-4:] and len(nci.variables[k].dimensions) and '_data_point' in nci.variables[k].dimensions[0] and dim == nci.variables[k].dimensions[0]:
                        var_t = nci.variables[k][:]
                        break

                if len(var_t):
                    f = scipy.interpolate.interp1d(
                        var_t, var, kind="linear", bounds_error=False, fill_value="extrapolate"
                    )
                    var = f(nci.variables['ctd_time'][:])
                else:
                    print(f'no t found for {p}({dim})');
                    var = []

            message[p] = var
        except:
            print(f"Could not extract variable {p}")

    return message

if __name__ == "__main__":


    # print(getVarNames(sys.argv[1]))

    #msg = timeSeriesToProfile('temperature', 4, 1, 859, 1, 0, 990, 5, 'sg249_NANOOS_Jul-2022_timeseries.nc')
    #out = dumps(msg).encode('utf-8')
    msg = extractVars('sg249_NANOOS_Jul-2022_timeseries.nc', ['temperature'], 10, 10)
    print(msg)
    sys.exit(0)
