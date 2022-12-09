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
import gsw
import json

import numpy as np
from scipy.io import netcdf_file
import scipy.interpolate

import Utils

def getVarNames(nc_filename):
    try:
        nc_file = Utils.open_netcdf_file(nc_filename, "r")
    except:
        print(f"Unable to open {nc_filename}")
        return None

    vars = []

    for k in nc_file.variables.keys():
        if len(nc_file.variables[k].dimensions) and '_data_point' in nc_file.variables[k].dimensions[0]:
            vars.append({'var': k, 'dim': nc_file.variables[k].dimensions[0]})
            
    nc_file.close()

    return vars


def extractVars(nc_filename, plot_vars):
    try:
        nc_file = Utils.open_netcdf_file(nc_filename, "r")
    except:
        print(f"Unable to open {nc_filename}")
        return None

    message = {}
    for p in plot_vars:
        try:
            var = nc_file.variables[p][:]
            dim = nc_file.variables[p].dimensions[0]
            if dim != 'ctd_time':
                for k in nc_file.variables.keys():
                    var_t = []
                    if 'time' in k[-4:] and len(nc_file.variables[k].dimensions) and '_data_point' in nc_file.variables[k].dimensions[0] and dim == nc_file.variables[k].dimensions[0]:
                        var_t = nc_file.variables[k][:]
                        break

                if len(var_t):
                    f = scipy.interpolate.interp1d(
                        var_t, var, kind="linear", bounds_error=False, fill_value="extrapolate"
                    )
                    var = f(nc_file.variables['ctd_time'][:])
                else:
                    print(f'no t found for {p}({dim})');
                    var = []

            if 'time' in p and len(var) > 0:
                var = var - var[0]            

            if len(var):
                message[p] = var.tolist()
        except:
            print(f"Could not extract variable {p}")

    nc_file.close()

    return message

if __name__ == "__main__":


    # print(getVarNames(sys.argv[1]))

    msg = extractVars(sys.argv[1], ['time']) # , 'depth', 'glide_angle'])
    out = json.dumps(msg).encode('utf-8')
    print(out)
    sys.exit(0)
