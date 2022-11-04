#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006-2022 by University of Washington.  All rights reserved.
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

"""Routines for creating Navy data products
"""
import math

import numpy as np

import Utils

from BaseLog import log_debug, log_warning

#  Constants
FEET_PER_METER = 3.2808

#
# Main entry functions
#


def kkyy(logfile, depth_v, tempc_v, salin_v, climb, n_points, kkyy_file):
    """Reduces the data and populates the KKYY file

    Input:
        depth_v, tempc_v, salin_v - depth, temperature and salinity data
        climb - True to select the climb portion of the profile, False to select the dive portion of the profile
        n_points - number of points to reduce the data set to
        kkyy_file - file object, opened for write
    """
    log_debug("n_points = %d" % n_points)

    depth_reduced_v, tempc_reduced_v, salin_reduced_v = reduce_data(
        depth_v, tempc_v, salin_v, climb, n_points, False
    )
    print_kkyy(
        logfile, depth_reduced_v, tempc_reduced_v, salin_reduced_v, climb, kkyy_file
    )


#
# Format specific functions
#


def print_kkyy(
    logfile, depth_reduced_v, tempc_reduced_v, salin_reduced_v, climb, kkyy_file
):
    """Populates a KKYY file

    Input:
        logfile - logfile object
        depth_reduced_v, tempc_reduced_v, salin_reduced_v - arrays with a reduced number of observations
        climb - Tree if data came from the climb or False if the data came from the dive portion of the profile
        kkyy_file - output file, already opened for write

    Output:
        None
    """

    if climb:
        timestamp = logfile.data["$GPS"].datetime
        ddlat = Utils.ddmm2dd(logfile.data["$GPS"].lat)
        ddlon = Utils.ddmm2dd(logfile.data["$GPS"].lon)
    else:
        timestamp = logfile.data["$GPS2"].datetime
        ddlat = Utils.ddmm2dd(logfile.data["$GPS2"].lat)
        ddlon = Utils.ddmm2dd(logfile.data["$GPS2"].lon)

    kkyy_file.write(
        "KKYY %02d%02d%1d %02d%02d%1s %1d%05ld %06ld 888%1s%1s %03d%02d\n"
        % (
            timestamp.tm_mday,
            timestamp.tm_mon,
            timestamp.tm_year % 10,
            timestamp.tm_hour,
            timestamp.tm_min,
            "/",  # Encode in metric (meters/degC)
            WMO_3333(ddlat, ddlon),  # quadrant encoding
            int(math.fabs(ddlat * 1000)),  # GPS is this accurate
            int(math.fabs(ddlon * 1000)),
            "7",  # Values at significant depths (code table 2262)
            "2",  # in-situ sensor, accuracy less tahn 0.02 PSU (code table 2263)
            830,  # WMO 1770 instrument type 'CTD'
            99,  # WMO 4770 recorder code 'inconnu'
        )
    )

    size = len(depth_reduced_v)

    # Section 2 data
    for i in range(size):
        # Depth in meters (only when changing?)
        depth = depth_reduced_v[i]

        # Navy wants temp in 100'ths of degree C, and rounded
        tempc = math.floor(tempc_reduced_v[i] * 100.0)

        # For negative temperatures, 5000 shall be added to the absolute value of the
        # temperature in hundredths of a degree Celsius
        if tempc < 0.0:
            tempc = math.fabs(tempc) + 5000.0

        # Salin 100'th of PSU
        salin = salin_reduced_v[i] * 100.0

        try:
            kkyy_file.write(
                "2%04d 3%04d 4%04d\n" % (int(depth), int(tempc), int(salin))
            )
        except ValueError:
            log_warning(
                "Error writing KKYY output (%s %s %s) - skipping"
                % (depth, tempc, salin)
            )

    # TODO What about hitting the bottom? write_jjvv_field("00000")?

    # Section 3 data
    # NONE

    # Section 4 data
    # call sign -- encode hull number
    kkyy_file.write("SG%03d\n" % int(logfile.data["$ID"]))


#
# Untility functions
#


def WMO_3333(lat, lon):
    """Enncode quadrant of globe

    Input:
        lat,lon - latitude and longitude in dd

    Output:
        Encoding
    """
    if lat > 0:
        if lon > 0:
            # NE
            return 1
        else:
            # NW
            return 7
    else:
        if lon > 0:
            # SE
            return 3
        else:
            # SW
            return 5


def reduce_data(depth_v, tempc_v, salin_v, climb, n_points, english):
    """Reduces data columns to fit the Navy format

    Input:
         depth_v, tempc_v, salin_v - data columns to be reduced
         climb - False to select the diving data, True to select climbing data
         n_points - number of points to reduce data to
         english - False, leave units as is. True, convert to english units

    Output:
        depth_reduced_v, tempc_reduced_v, salin_reduced_v - arrays of n_points containing the
        reduced data
    """

    size = len(depth_v)
    skip_points = int(size / n_points)
    if skip_points == 0:
        skip_points = 1

    # Assume all depths are in meters and temps are in degC
    if english:
        # The Navy wants Fahrenheit
        tempc_v = (9.0 / 5.0) * tempc_v + 32.0
        depth_v = depth_v * FEET_PER_METER

    # TODO do we have to ensure the first point is at 0m?
    # For NITES II: "The second group after 88888 should be the first depth/temp pairing,
    # and should be for 0 depth."!
    last_depth = -1  # Above the surface to force the first point out
    reported_point = 0  # None so far
    depth_reduced = []
    tempc_reduced = []
    salin_reduced = []

    log_debug("skip_points = %s, size = %d" % (skip_points, size))

    i = 0
    while i < size:
        if climb:
            index = size - 1 - i
        else:
            index = i
        log_debug("i = %d, index = %d " % (i, index))
        depth = depth_v[index]

        temp = tempc_v[index]

        salin = salin_v[index]

        this_depth = math.floor(depth)
        if this_depth > last_depth:  # only show increasing depths
            # Record the last depth we emitted
            # push(@reduced_data,[$depth,$svel,$temp,$salin]);
            depth_reduced.append(depth)
            tempc_reduced.append(temp)
            salin_reduced.append(salin)
            last_depth = this_depth
            reported_point = reported_point + 1
            # last if ($reported_point >= $n_points);
            if reported_point >= n_points:
                break
        i = i + skip_points

    depth_reduced_v = np.array(depth_reduced)
    tempc_reduced_v = np.array(tempc_reduced)
    salin_reduced_v = np.array(salin_reduced)
    return [depth_reduced_v, tempc_reduced_v, salin_reduced_v]
