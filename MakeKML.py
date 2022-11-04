#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2012, 2013, 2015, 2017, 2018, 2020, 2021, 2022 by University of Washington.  All rights reserved.
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

"""Routines for creating KML files from netCDF data, comm.log and target files
"""

import cProfile
import collections
import functools
import glob
import math
import os
import pstats
import sys
import time
import zipfile

import numpy as np

import BaseNetCDF
import BaseOpts
from BaseLog import (
    BaseLogger,
    log_warning,
    log_info,
    log_error,
    log_debug,
    log_critical,
)
import FileMgr
from CalibConst import getSGCalibrationConstants
import MakeDiveProfiles

import CommLog
import Utils
import LogFile

make_kml_conf = None

dive_gps_position = collections.namedtuple(
    "dive_gps_position",
    [
        "gps_lat_one",
        "gps_lon_one",
        "gps_time_one",
        "gps_lat_start",
        "gps_lon_start",
        "gps_time_start",
        "gps_lat_end",
        "gps_lon_end",
        "gps_time_end",
        "dive_num",
    ],
)
surface_pos = collections.namedtuple(
    "surface_pos",
    ["gps_fix_lon", "gps_fix_lat", "gps_fix_time", "dive_num", "call_cycle"],
)

m_per_deg = 111120.0

# TODO

# - Color line options - depth, temp or salinity (at sample points)
# - User option on generated kml to hide end of dive
#
# - How do you convert HDOP to fix radius?
# - How to do playback/route tracing?  (Have dives and fixes show up as they occur)


def cmp_function(a, b):
    """Compares two archived targets files, sorting in reverse chronilogical order (most recent one first)"""
    a_dive = None
    b_dive = None
    a_counter = None
    b_counter = None
    a_is_plain = ".plain" in a
    _, a_base = os.path.split(a.replace(".plain", ""))
    b_is_plain = ".plain" in b
    _, b_base = os.path.split(b.replace(".plain", ""))
    a_split = a_base.split(".")
    b_split = b_base.split(".")

    a_dive = int(a_split[1])
    b_dive = int(b_split[1])
    if len(a_split) > 2:
        a_counter = int(a_split[2])
    else:
        a_counter = 0

    if len(b_split) > 2:
        b_counter = int(b_split[2])
    else:
        b_counter = 0

    if a_dive > b_dive:
        return -1
    elif a_dive < b_dive:
        return 1
    else:
        if a_counter > b_counter:
            return -1
        elif a_counter < b_counter:
            return 1
        else:
            if a_is_plain and not b_is_plain:
                return -1
            elif not a_is_plain and b_is_plain:
                return 1
            else:
                return 0


def printHeader(name, description, glider_color, fo):
    """Prints out the KML header format and global styles"""
    fo.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    fo.write('<kml xmlns="http://earth.google.com/kml/2.1">\n')
    fo.write("<Document>\n")
    fo.write(f"    <name>{name}</name>\n")
    fo.write(f"    <description>{description}</description>\n")
    fo.write('    <Style id="SeagliderTrackPoly">\n')
    fo.write("        <LineStyle>\n")
    fo.write(f"            <color>7f{glider_color}</color>\n")
    fo.write("            <width>1</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("        <PolyStyle>\n")
    fo.write(f"            <color>7f{glider_color}</color>\n")
    fo.write("        </PolyStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="SeagliderDriftTrackPoly">\n')
    fo.write("        <LineStyle>\n")
    #    fo.write("            <color>bd%s</color>\n" % glider_color)
    fo.write(f"            <color>ff{glider_color}</color>\n")
    fo.write("            <width>1</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("        <PolyStyle>\n")
    fo.write(f"            <color>7f{glider_color}</color>\n")
    fo.write("        </PolyStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="targetPosition">\n')
    fo.write("        <IconStyle>\n")
    fo.write("            <scale>0.5</scale>\n")
    fo.write("            <Icon>\n")
    fo.write(
        "                <href>https://iop.apl.washington.edu/images/Target.png</href>\n"
    )
    fo.write("            </Icon>\n")
    fo.write("         </IconStyle>\n")
    fo.write("        <LineStyle>\n")
    fo.write("            <color>7f00ff00</color>\n")
    fo.write("            <width>2</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="activeTargetPosition">\n')
    fo.write("        <IconStyle>\n")
    fo.write("            <scale>0.75</scale>\n")
    fo.write("            <Icon>\n")
    fo.write(
        "                <href>https://iop.apl.washington.edu/images/Target.png</href>\n"
    )
    fo.write("            </Icon>\n")
    fo.write("         </IconStyle>\n")
    fo.write("        <LineStyle>\n")
    fo.write("            <color>7f00ff00</color>\n")
    fo.write("            <width>2</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="targetLine">\n')
    fo.write("        <LineStyle>\n")
    fo.write("            <color>7f00ff00</color>\n")
    fo.write("            <width>2</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="escapeLine">\n')
    fo.write("        <LineStyle>\n")
    fo.write("            <color>7f0000ff</color>\n")
    fo.write("            <width>2</width>\n")
    fo.write("        </LineStyle>\n")
    fo.write("    </Style>\n")

    fo.write('    <Style id="seagliderPositionNormalState">\n')
    fo.write("        <IconStyle>\n")
    fo.write("             <scale>0.2</scale>\n")
    fo.write(f"             <color>99{glider_color}</color>\n")
    fo.write(
        "             <Icon><href>https://maps.google.com/mapfiles/kml/shapes/shaded_dot.png</href></Icon>\n"
    )
    fo.write("         </IconStyle>\n")
    fo.write("        <LabelStyle>\n")
    fo.write("            <color>000000c0</color>\n")  # Hide the text
    fo.write("        </LabelStyle>\n")
    fo.write("    </Style>\n")
    fo.write('    <Style id="seagliderPositionHighlightState">\n')
    fo.write("        <IconStyle>\n")
    fo.write("            <scale>1.0</scale>\n")
    fo.write("            <Icon>\n")
    fo.write(
        "                <href>https://iop.apl.washington.edu/images/SeagliderYellowIcon.png</href>\n"
    )
    fo.write("            </Icon>\n")
    fo.write("        </IconStyle>\n")
    fo.write("    </Style>\n")
    fo.write('    <StyleMap id="seagliderPosition">\n')
    fo.write("        <Pair>\n")
    fo.write("            <key>normal</key>\n")
    fo.write("            <styleUrl>#seagliderPositionNormalState</styleUrl>\n")
    fo.write("        </Pair>\n")
    fo.write("        <Pair>\n")
    fo.write("            <key>highlight</key>\n")
    fo.write("            <styleUrl>#seagliderPositionHighlightState</styleUrl>\n")
    fo.write("         </Pair>\n")
    fo.write("    </StyleMap>\n")

    fo.write('    <Style id="paamDetectionNormalState">\n')
    fo.write("        <IconStyle>\n")
    fo.write("            <scale>0.3</scale>\n")
    fo.write("            <Icon>\n")
    fo.write(
        "                <href>https://iop.apl.washington.edu/images/Cuviers.png</href>\n"
    )
    fo.write("            </Icon>\n")
    fo.write("         </IconStyle>\n")
    fo.write("        <LabelStyle>\n")
    fo.write("            <color>000000c0</color>\n")  # Hide the text
    fo.write("        </LabelStyle>\n")
    fo.write("    </Style>\n")
    fo.write('    <Style id="paamDetectionHighlightState">\n')
    fo.write("        <IconStyle>\n")
    fo.write("            <scale>0.5</scale>\n")
    fo.write("            <Icon>\n")
    fo.write(
        "                <href>https://iop.apl.washington.edu/images/Cuviers.png</href>\n"
    )
    fo.write("            </Icon>\n")
    fo.write("        </IconStyle>\n")
    fo.write("    </Style>\n")
    fo.write('    <StyleMap id="paamDetection">\n')
    fo.write("        <Pair>\n")
    fo.write("            <key>normal</key>\n")
    fo.write("            <styleUrl>#paamDetectionNormalState</styleUrl>\n")
    fo.write("        </Pair>\n")
    fo.write("        <Pair>\n")
    fo.write("            <key>highlight</key>\n")
    fo.write("            <styleUrl>#paamDetectionHighlightState</styleUrl>\n")
    fo.write("         </Pair>\n")
    fo.write("    </StyleMap>\n")


def printDivePlacemark(name, description, lon, lat, depth, fo, hide_label, pairs=None):
    """Places a seaglider marker on the map"""
    # Start dive place mark
    fo.write("    <Placemark>\n")
    fo.write(f"        <name>{name}</name>\n")
    if hide_label:
        fo.write("        <styleUrl>#seagliderPosition</styleUrl>\n")
    else:
        fo.write("        <styleUrl>#seagliderPositionHighlightState</styleUrl>\n")
    fo.write(f"        <description>{description}</description>\n")
    if pairs:
        fo.write('        <Style><BalloonStyle><text><![CDATA[<div align="center">\n')
        fo.write('        <table width="300" bgcolor="white">\n')
        for pair in pairs:
            if pair[0] is None:
                fo.write('        </table><hr /><table width="300" bgcolor="white">\n')
            else:
                fo.write(
                    '        <tr><th width="200" align="right">%s</th><td width="200">%s</td></tr>\n'
                    % (pair[0], pair[1])
                )
        fo.write("</table></div>]]></text></BalloonStyle></Style>\n")
    fo.write("        <Point>\n")
    fo.write("        <altitudeMode>clampToGround</altitudeMode>\n")
    fo.write(f"        <coordinates>{lon:f},{lat:f},{depth:f}</coordinates>\n")
    fo.write("        </Point>\n")
    fo.write("    </Placemark>\n")


def printTarget(
    active_target,
    name,
    lat,
    lon,
    radius,
    finish_line,
    depth_target,
    instrument_id,
    print_radius,
    fo,
):
    """Prints out a target"""

    if lat is None or lon is None:
        log_warning(f"Bad target: {name} {lat} {lon}")
        return

    if active_target:
        description = "Current Target SG%0.3d" % (instrument_id)
    else:
        description = "Target SG%0.3d" % (instrument_id)

    pairs = []
    if active_target:
        pairs.append(("Target Name (current)", name))
    else:
        pairs.append(("Target Name", name))
    pairs.append(("Seaglider", "SG%03d" % instrument_id))
    pairs.append(("lat", f"{lat:.4f}"))
    pairs.append(("lon", f"{lon:.4f}"))
    if radius:
        pairs.append(("radius", f"{radius:.2f} meters"))
    if finish_line:
        pairs.append(("finish line", f"{finish_line:.1f} degrees"))
    if depth_target:
        pairs.append(("depth target", f"{depth_target:.1f} meters"))

    # Start dive place mark
    fo.write("    <Placemark>\n")
    fo.write(f"        <name>{name}</name>\n")
    fo.write(f"        <description>{description}</description>\n")
    fo.write('        <Style><BalloonStyle><text><![CDATA[<div align="center">\n')
    fo.write('        <table width="300" bgcolor="white">\n')
    for pair in pairs:
        fo.write(
            '        <tr><th width="200" align="right">%s</th><td width="200">%s</td></tr>\n'
            % (pair[0], pair[1])
        )
    fo.write("</table></div>]]></text></BalloonStyle></Style>\n")

    if active_target:
        fo.write("        <styleUrl>#activeTargetPosition</styleUrl>\n")
    else:
        fo.write("        <styleUrl>#targetPosition</styleUrl>\n")
    fo.write("        <Point>\n")
    fo.write("            <altitudeMode>clampToGround</altitudeMode>\n")
    fo.write(f"            <coordinates>{lon:f},{lat:f},0.0</coordinates>\n")
    fo.write("        </Point>\n")
    fo.write("    </Placemark>\n")
    # Draw the target radius, if so supplied
    if radius and print_radius:
        fo.write("    <Placemark>\n")
        fo.write("        <styleUrl>#targetLine</styleUrl>\n")
        fo.write("        <LineString>\n")
        fo.write("            <extrude>0</extrude>\n")
        fo.write("            <altitudeMode>absolute</altitudeMode>\n")
        fo.write("            <coordinates>\n")
        lon_fac = math.cos(math.radians(lat))
        for step in range(360):
            x = math.sin(math.radians(step)) * radius
            y = math.cos(math.radians(step)) * radius
            fo.write(
                "                %f,%f,0.0 \n"
                % ((lon + (y / (m_per_deg * lon_fac))), lat + (x / m_per_deg))
            )
        fo.write("            </coordinates>\n")
        fo.write("        </LineString>\n")
        fo.write("    </Placemark>\n")
    # TODO - draw finish line here
    # TODO - add depth target as comment


def printTargetLine(from_name, from_lat, from_lon, to_name, to_lat, to_lon, escape, fo):
    """Draws the line between to two targets"""
    fo.write("    <Placemark>\n")
    fo.write(f"        <name>{from_name} to {to_name}</name>\n")
    if escape:
        fo.write(
            "        <description>Escape route from target %s to target %s</description>\n"
            % (from_name, to_name)
        )
    else:
        fo.write(
            "        <description>Course from target %s to target %s</description>\n"
            % (from_name, to_name)
        )
    # TODO - better color
    if escape:
        fo.write("        <styleUrl>#escapeLine</styleUrl>\n")
    else:
        fo.write("        <styleUrl>#targetLine</styleUrl>\n")
    # TODO - replace this with a an arrow
    fo.write("        <LineString>\n")
    fo.write("            <extrude>0</extrude>\n")
    fo.write("            <altitudeMode>clampToGround</altitudeMode>\n")
    fo.write("            <coordinates>\n")
    fo.write(f"                {from_lon:f},{from_lat:f},0.0 \n")
    fo.write(f"                {to_lon:f},{to_lat:f},0.0 \n")
    fo.write("            </coordinates>\n")
    fo.write("        </LineString>\n")
    fo.write("    </Placemark>\n")


target_tuple = collections.namedtuple(
    "target",
    [
        "lat",
        "lon",
        "radius",
        "finish_line",
        "depth_target",
        "goto_target",
        "escape_target",
    ],
)


def printTargets(
    active_target,
    only_active_target,
    target_file_name,
    instrument_id,
    print_radius,
    fo,
    tgt_lon=None,
    tgt_lat=None,
    tgt_radius=None,
):
    """Proceses a target file"""
    try:
        target_file = open(target_file_name, "r")
    except:
        log_error(
            f"Could not open {target_file_name} - skipping target processing", "exc"
        )
        return None
    else:
        log_info(f"Opened {target_file_name} for processing")

    fo.write(
        '<Folder id="SG%0.3dTargets">\n<name>SG%0.3d Targets</name>\n'
        % (instrument_id, instrument_id)
    )

    target_dict = {}
    for target_line in target_file:
        if target_line[0] == "/":
            continue
        target_split = target_line.split()
        if len(target_split) < 2:
            continue
        log_info(target_split)
        target_name = target_split[0]
        lat = lon = radius = goto_targ = escape_targ = finish_line = depth_target = None
        for pair in target_split[1:]:
            # log_info(pair)
            try:
                name, value = pair.split("=")
            except ValueError:
                log_error(
                    "Could not split (%s) - bad format in targets file %s?"
                    % (pair, target_file_name)
                )
                break
            if name == "lat":
                lat = Utils.ddmm2dd(float(value))
            elif name == "lon":
                lon = Utils.ddmm2dd(float(value))
            elif name == "radius":
                radius = float(value)
            elif name == "goto":
                goto_targ = value
            elif name == "escape":
                pass
                # Need to fix this for escape routes
                # escape_targ = value
            elif name == "finish":
                finish_line = float(value)
            elif name == "depth":
                depth_limit = float(value)
        target_dict[target_name] = target_tuple(
            lat, lon, radius, finish_line, depth_target, goto_targ, escape_targ
        )

    if tgt_lat is not None and tgt_lon is not None:
        found_in_list = False
        for _, v in target_dict.items():
            if v.lat == tgt_lat and v.lon == tgt_lon:
                found_in_list = True

        if not found_in_list and active_target:
            if active_target in target_dict.keys():
                curr = target_dict[active_target]
                target_dict[active_target] = target_tuple(
                    tgt_lat,
                    tgt_lon,
                    tgt_radius,
                    curr.finish_line,
                    curr.depth_target,
                    curr.goto_target,
                    curr.escape_target,
                )
            else:
                target_dict[active_target] = target_tuple(
                    tgt_lat,
                    tgt_lon,
                    tgt_radius,
                    None,
                    None,
                    None,
                    None,
                )

    for targ in target_dict.keys():
        if targ == active_target:
            printTarget(
                True,
                targ,
                target_dict[targ].lat,
                target_dict[targ].lon,
                target_dict[targ].radius,
                target_dict[targ].finish_line,
                target_dict[targ].depth_target,
                instrument_id,
                print_radius,
                fo,
            )
        elif not only_active_target:
            printTarget(
                False,
                targ,
                target_dict[targ].lat,
                target_dict[targ].lon,
                target_dict[targ].radius,
                target_dict[targ].finish_line,
                target_dict[targ].depth_target,
                instrument_id,
                print_radius,
                fo,
            )

    # Draw course between targets
    # TODO - special case the loop back case - same target source and dest
    if not only_active_target:
        for targ in list(target_dict.keys()):
            if target_dict[targ].goto_target in list(target_dict.keys()):
                printTargetLine(
                    targ,
                    target_dict[targ].lat,
                    target_dict[targ].lon,
                    target_dict[targ].goto_target,
                    target_dict[target_dict[targ].goto_target].lat,
                    target_dict[target_dict[targ].goto_target].lon,
                    False,
                    fo,
                )
            if target_dict[targ].escape_target in list(target_dict.keys()):
                log_info(f"Escape route {targ} to {target_dict[targ].escape_target}")
                printTargetLine(
                    targ,
                    target_dict[targ].lat,
                    target_dict[targ].lon,
                    target_dict[targ].escape_target,
                    target_dict[target_dict[targ].escape_target].lat,
                    target_dict[target_dict[targ].escape_target].lon,
                    True,
                    fo,
                )
    fo.write("</Folder>\n")
    return None


def printDive(
    base_opts,
    dive_nc_file_name,
    instrument_id,
    dive_num,
    last_dive,
    paam_dict,
    fo,
):
    """Processes a dive
    Returns:

    Tuple
    (gps_lat_start, gps_lon_start, gps_time_start, gps_lat_end, gps_lon_end, gps_time_end, dive_num)
    If any measurements are not available, return None for that position
    """
    try:
        nc = Utils.open_netcdf_file(dive_nc_file_name, "r", mmap=False)
    except:
        log_error(f"Could not read {dive_nc_file_name}", "exc")
        log_info("Skipping...")
        return dive_gps_position(
            None, None, None, None, None, None, None, None, None, None
        )

    log_debug(f"Processing {dive_nc_file_name}")
    gps_lat_start = (
        gps_lon_start
    ) = gps_time_start = gps_lat_end = gps_lon_end = gps_time_end = None

    try:
        gps_lat_one = nc.variables["log_gps_lat"][0]
        gps_lon_one = nc.variables["log_gps_lon"][0]
        gps_time_one = nc.variables["log_gps_time"][0]
        gps_lat_start = nc.variables["log_gps_lat"][1]
        gps_lon_start = nc.variables["log_gps_lon"][1]
        gps_time_start = nc.variables["log_gps_time"][1]
        gps_lat_end = nc.variables["log_gps_lat"][2]
        gps_lon_end = nc.variables["log_gps_lon"][2]
        gps_time_end = nc.variables["log_gps_time"][2]
    except:
        log_error(
            f"Could not process {dive_nc_file_name} due to missing variables", "exc"
        )
        return None

    for i in range(3):
        if (
            np.isnan(nc.variables["log_gps_time"][i])
            or np.isnan(nc.variables["log_gps_lat"][i])
            or np.isnan(nc.variables["log_gps_lon"][i])
        ):
            log_error(f"Could not process {dive_nc_file_name} due to missing variables")
            return None

    if "processing_error" in nc.variables:
        log_warning(
            f"{dive_nc_file_name} is marked as having a processing error - skipping"
        )
        return dive_gps_position(
            gps_lat_one,
            gps_lon_one,
            gps_time_one,
            gps_lat_start,
            gps_lon_start,
            gps_time_start,
            gps_lat_end,
            gps_lon_end,
            gps_time_end,
            dive_num,
        )

    if "skipped_profile" in nc.variables:
        log_warning(f"{dive_nc_file_name} is marked as a skipped_profile - skipping")
        return dive_gps_position(
            gps_lat_one,
            gps_lon_one,
            gps_time_one,
            gps_lat_start,
            gps_lon_start,
            gps_time_start,
            gps_lat_end,
            gps_lon_end,
            gps_time_end,
            dive_num,
        )

    try:
        # Dive Track
        depth = nc.variables["ctd_depth"][:]
        lon = nc.variables["longitude"][:]
        lat = nc.variables["latitude"][:]
        time_vals = nc.variables[BaseNetCDF.nc_ctd_time_var][:]
        num_points = len(time_vals)
    except:
        log_warning(
            f"Could not process {dive_nc_file_name} due to missing variables", "exc"
        )
        log_info("Skipping this dive...")
        return dive_gps_position(
            gps_lat_one,
            gps_lon_one,
            gps_time_one,
            gps_lat_start,
            gps_lon_start,
            gps_time_start,
            gps_lat_end,
            gps_lon_end,
            gps_time_end,
            dive_num,
        )

    # Start placemark - this is quite distracting in a large deployment
    # ballon_pairs = []
    # ballon_pairs.append(('Seaglider', "SG%03d" % instrument_id))
    # ballon_pairs.append(('Dive', "%d" % dive_num))
    # ballon_pairs.append(('Start time', time.strftime("%H:%M:%S %m/%d/%y %Z",time.gmtime(gps_time_start))))
    # ballon_pairs.append(('Lat', "%.4f" % gps_lat_start))
    # ballon_pairs.append(('Lon', "%.4f" % gps_lon_start))
    # printDivePlacemark("SG%03d dive %03d start" % (instrument_id, dive_num),

    if base_opts.surface_track:
        fo.write("    <Placemark>\n")
        fo.write(
            "        <name>SG%03d Dive %03d Surface Track</name>\n"
            % (instrument_id, dive_num)
        )
        fo.write(
            "        <description>Dive started %s</description>\n"
            % time.strftime("%H:%M:%S %m/%d/%y %Z", time.gmtime(gps_time_start))
        )

        fo.write("        <styleUrl>#SeagliderTrackPoly</styleUrl>\n")
        fo.write("        <LineString>\n")
        fo.write("            <extrude>0</extrude>\n")
        fo.write("            <altitudeMode>absolute</altitudeMode>\n")
        fo.write("            <coordinates>\n")
        if base_opts.simplified:
            fo.write(
                "                %f,%f,%f \n"
                % (float(gps_lon_start), float(gps_lat_start), 0.0)
            )
            fo.write(
                "                %f,%f,%f \n"
                % (float(gps_lon_end), float(gps_lat_end), 0.0)
            )
        else:
            for i in range(num_points):
                if (
                    depth[i] < 6000.0
                    and lat[i] <= 90.0
                    and lat[i] >= -90.0
                    and lon[i] >= -180.0
                    and lon[i] <= 180.0
                ):
                    if (i % base_opts.skip_points) == 0 or i == 0:
                        if base_opts.surface_track:
                            fo.write(
                                "                %f,%f,%f \n"
                                % (float(lon[i]), float(lat[i]), 0.0)
                            )
                        else:
                            fo.write(
                                "                %f,%f,%f \n"
                                % (float(lon[i]), float(lat[i]), -float(depth[i]))
                            )
        # Connect the last to the GPS fix
        fo.write(
            f"                {float(gps_lon_end):f},{float(gps_lat_end):f},{0.0:f} \n"
        )
        fo.write("            </coordinates>\n")
        fo.write("        </LineString>\n")
        fo.write("    </Placemark>\n")

    # Now deal with the regular dive
    if base_opts.subsurface_track:
        fo.write("    <Placemark>\n")
        fo.write(
            "        <name>SG%03d Dive %03d Subsurface Track</name>\n"
            % (instrument_id, dive_num)
        )
        fo.write(
            "        <description>Dive started %s</description>\n"
            % time.strftime("%H:%M:%S %m/%d/%y %Z", time.gmtime(gps_time_start))
        )
        fo.write("        <styleUrl>#SeagliderTrackPoly</styleUrl>\n")
        fo.write("        <LineString>\n")
        fo.write("            <extrude>1</extrude>\n")
        fo.write("            <altitudeMode>absolute</altitudeMode>\n")
        fo.write("            <coordinates>\n")
        for i in range(num_points):
            if (
                depth[i] < 6000.0
                and lat[i] <= 90.0
                and lat[i] >= -90.0
                and lon[i] >= -180.0
                and lon[i] <= 180.0
            ):
                if (i % base_opts.skip_points) == 0 or i == 0:
                    fo.write(
                        "                %f,%f,%f \n"
                        % (float(lon[i]), float(lat[i]), -float(depth[i]))
                    )
        # Connect the last to the GPS fix
        fo.write(
            f"                {float(gps_lon_end):f},{float(gps_lat_end):f},{0.0:f} \n"
        )
        fo.write("            </coordinates>\n")
        fo.write("        </LineString>\n")
        fo.write("    </Placemark>\n")

    # Plot the PAAM data
    if paam_dict:
        for p in list(paam_dict.keys()):
            for t_index in range(len(time_vals) - 1):
                if p >= time_vals[t_index] and p <= time_vals[t_index + 1]:
                    if paam_dict[p][1] < 9999.0:
                        if (paam_dict[p][1] / float(depth[t_index])) < 0.95 or (
                            paam_dict[p][1] / float(depth[t_index]) > 1.05
                        ):
                            log_warning(
                                "PAAM depth more then 5%% different (%.2f:%.2f)"
                                % (paam_dict[p][1], float(depth[t_index]))
                            )
                    fo.write("    <Placemark>\n")
                    fo.write(
                        "        <name>Detection:%s %.2fm</name>\n"
                        % (paam_dict[p][0], paam_dict[p][1])
                    )
                    fo.write("        <styleUrl>#paamDetection</styleUrl>\n")
                    fo.write(
                        "        <description>Detect time:%s\nDive:%03d</description>\n"
                        % (paam_dict[p][2], dive_num)
                    )
                    fo.write("        <Point>\n")
                    fo.write("        <altitudeMode>absolute</altitudeMode>\n")
                    fo.write(
                        "        <coordinates>%f,%f,%f</coordinates>\n"
                        % (
                            float(lon[t_index]),
                            float(lat[t_index]),
                            -float(depth[t_index]),
                        )
                    )
                    fo.write("        </Point>\n")
                    fo.write("    </Placemark>\n")
                    break

    try:
        dog, cog = Utils.bearing(gps_lat_start, gps_lon_start, gps_lat_end, gps_lon_end)
    except:
        log_error(f"Could not process dog/cog from {dive_nc_file_name}", "exc")
        dog = cog = None

    try:
        latlong = nc.variables["log_TGT_LATLONG"][:].tobytes().decode("utf-8")
        tgt_lat, tgt_lon = latlong.split(",")
        tgt_lat = Utils.ddmm2dd(float(tgt_lat))
        tgt_lon = Utils.ddmm2dd(float(tgt_lon))
        dtg, ctg = Utils.bearing(gps_lat_end, gps_lon_end, tgt_lat, tgt_lon)
    except:
        log_error(f"Could not process target lat/log from {dive_nc_file_name}", "exc")
        dtg = ctg = None

    try:
        nd = nc.variables["north_displacement_hdm"][:]
        ed = nc.variables["east_displacement_hdm"][:]
    except:
        try:
            nd = nc.variables["north_displacement_gsm"][:]
            ed = nc.variables["east_displacement_gsm"][:]
        except:
            log_error(
                f"Could not find any displacements in {dive_nc_file_name} - skipping",
                "exc",
            )
            nd = ed = None

    if nd is not None and ed is not None:
        north_disp = sum(nd)
        east_disp = sum(ed)
        dtw = math.sqrt(north_disp * north_disp + east_disp * east_disp) / 1000.0
        ctw = (
            math.atan2(north_disp, east_disp) * 57.29578
        )  # radians to degrees (180./acos(-1.)) 180./3.14159265

        if ctw > 360.0:
            ctw = math.fmod(ctw, 360.0)
        if ctw < 0.0:
            ctw = math.fmod(ctw, 360.0) + 360.0
    else:
        ctw = dtw = None

    # Add: batt volts, kj % cap, errors, retries

    ballon_pairs = []
    if base_opts.simplified:
        ballon_pairs.append(("Serial Number", "Seaglider SG%03d" % instrument_id))
    else:
        ballon_pairs.append(("Seaglider", "SG%03d" % instrument_id))
    ballon_pairs.append(("Dive", "%d" % dive_num))
    ballon_pairs.append(
        (
            "Start time",
            time.strftime("%H:%M:%S %m/%d/%y %Z", time.gmtime(gps_time_start)),
        )
    )
    ballon_pairs.append(
        ("End time", time.strftime("%H:%M:%S %m/%d/%y %Z", time.gmtime(gps_time_end)))
    )
    ballon_pairs.append(("Start Lat", f"{gps_lat_start:.4f}"))
    ballon_pairs.append(("Start Lon", f"{gps_lon_start:.4f}"))
    ballon_pairs.append(("End Lat", f"{gps_lat_end:.4f}"))
    ballon_pairs.append(("End Lon", f"{gps_lon_end:.4f}"))
    ballon_pairs.append((None, None))
    ballon_pairs.append(
        ("Dive length", "%d minutes" % ((time_vals[-1] - time_vals[0]) / 60.0))
    )
    ballon_pairs.append(("Depth achieved", "%d meters" % round(max(abs(depth)))))

    if not base_opts.simplified:
        ballon_pairs.append(
            (
                "Depth target",
                "%d meters"
                % min(
                    nc.variables["log_D_GRID"].getValue(),
                    nc.variables["log_D_TGT"].getValue(),
                ),
            )
        )
        ballon_pairs.append((None, None))
        if cog is not None and dog is not None:
            ballon_pairs.append(("Course over ground", f"{cog:.2f} degrees"))
            ballon_pairs.append(("Distance over ground", f"{dog:.2f} km"))
        if dtw is not None and ctw is not None:
            ballon_pairs.append(("Course through water", f"{dtw:.2f} degrees"))
            ballon_pairs.append(("Distance through water", f"{ctw:.2f} km"))
        if dtg is not None and ctg is not None:
            ballon_pairs.append(("Course to go", f"{ctg:.2f} degrees"))
            ballon_pairs.append(("Distance to go", f"{dtg:.2f} km"))

        dac_east = nc.variables["depth_avg_curr_east"].getValue()
        dac_north = nc.variables["depth_avg_curr_north"].getValue()
        DAC_mag = np.sqrt((dac_east * dac_east) + (dac_north * dac_north))
        try:
            dac_polar_rad = math.atan2(dac_north, dac_east)
            DAC_dir = 90.0 - math.degrees(dac_polar_rad)
        except ZeroDivisionError:  # atan2
            DAC_dir = 0.0
        if DAC_dir < 0.0:
            DAC_dir += 360.0

        ballon_pairs.append(("DAC dir", f"{DAC_dir:.2f} degrees"))
        ballon_pairs.append(("DAC mag", f"{DAC_mag:.3f} m/s"))

        if "surface_curr_east" in nc.variables and "surface_curr_north" in nc.variables:
            surf_east = nc.variables["surface_curr_east"].getValue()
            surf_north = nc.variables["surface_curr_north"].getValue()
            surf_mag = (
                np.sqrt((surf_east * surf_east) + (surf_north * surf_north)) / 100.0
            )
            try:
                surf_polar_rad = math.atan2(surf_north, surf_east)
                surf_dir = 90.0 - math.degrees(surf_polar_rad)
            except ZeroDivisionError:  # atan2
                surf_dir = 0.0
            if surf_dir < 0.0:
                surf_dir += 360.0

            ballon_pairs.append(("Surface current dir", f"{surf_dir:.2f} degrees"))
            ballon_pairs.append(("Surface current mag", f"{surf_mag:.3f} m/s"))

    ballon_pairs.append(
        (
            "Dive page",
            '<a href="https://iop.apl.washington.edu/seaglider/divegallery.php?dive=%d&glider=%d">sg%03d plots</a>'
            % (dive_num, instrument_id, instrument_id),
        )
    )

    printDivePlacemark(
        "SG%03d dive %03d end" % (instrument_id, dive_num),
        "Dive finished %s"
        % time.strftime("%H:%M:%S %m/%d/%y %Z", time.gmtime(gps_time_end)),
        gps_lon_end,
        gps_lat_end,
        0.0,
        fo,
        not last_dive,
        ballon_pairs,
    )

    return dive_gps_position(
        gps_lat_one,
        gps_lon_one,
        gps_time_one,
        gps_lat_start,
        gps_lon_start,
        gps_time_start,
        gps_lat_end,
        gps_lon_end,
        gps_time_end,
        dive_num,
    )


def printFooter(fo):
    """Prints out the KML footer data"""
    fo.write("</Document>\n")
    fo.write("</kml>\n")


def writeNetworkKML(fo, name, url):
    """Wries out the net work kml file (pointer to the main file)"""
    fo.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    fo.write('<kml xmlns="http://earth.google.com/kml/2.2">\n')
    fo.write("    <NetworkLink>\n")
    fo.write(f"        <name>{name}</name>\n")
    fo.write("        <Url>\n")
    fo.write(f"            <href>{url}</href>\n")
    fo.write("            <refreshMode>onInterval</refreshMode>\n")
    fo.write("            <refreshInterval>120</refreshInterval>\n")
    fo.write("        </Url>\n")
    fo.write("    </NetworkLink>\n")
    fo.write("</kml>\n")


def process_paam_data(paam_data_directory, percent_ici):
    """Collect data from PAAM stats files"""
    paam_compare_dict = {}
    if os.path.exists(paam_data_directory):
        for g in ("%s/data?/dive???/compare.stats", "%s/dive???/compare.stats"):
            for m in glob.glob(g % (paam_data_directory)):
                log_debug(f"Processing {m}")
                try:
                    fi = open(m, "r")
                except:
                    log_error(f"Could not read {m} = skiping")
                else:
                    root, _ = os.path.split(m)
                    _, dive = os.path.split(root)
                    dive_num = int(dive[4:7])
                    paam_compare_dict[dive_num] = {}

                    for line in fi:
                        log_debug(f"Processing {m}:({line})")
                        splits = line.split(",")
                        time_split = splits[0].split("_")
                        start_time = time.mktime(
                            time.strptime(
                                f"{time_split[1]}{time_split[2]}", "%y%m%d%H%M%S"
                            )
                        )
                        try:
                            if (float(splits[1]) != 0.0) and (
                                (float(splits[2]) / float(splits[1])) > percent_ici
                            ):
                                text = "%.2f%% ICI (%d total)" % (
                                    (float(splits[2]) / float(splits[1]) * 100.0),
                                    int(splits[1]),
                                )
                                paam_compare_dict[dive_num][start_time] = (
                                    text,
                                    float(splits[7]),
                                    f"{time_split[1]}_{time_split[2]} UTC",
                                )
                        except:
                            log_info(f"Could not process {m}:({line}) - skipping")
                    fi.close()

    return paam_compare_dict


def extractGPSPositions(dive_nc_file_name, dive_num):
    """A hack - printDive does this and reads many more variables.  This needs to be expanded and
    printDive needs to work off the data structure this feeds OR it needs to be determined that we can have
    many (1000) netCDF files opened at once.
    """
    try:
        nc = Utils.open_netcdf_file(dive_nc_file_name, "r")
    except:
        log_error(f"Could not read {dive_nc_file_name}", "exc")
        log_error("Skipping...")
        return None

    gps_lat_start = (
        gps_lon_start
    ) = gps_time_start = gps_lat_end = gps_lon_end = gps_time_end = None
    try:
        gps_lat_one = nc.variables["log_gps_lat"][0]
        gps_lon_one = nc.variables["log_gps_lon"][0]
        gps_time_one = nc.variables["log_gps_time"][0]
        gps_lat_start = nc.variables["log_gps_lat"][1]
        gps_lon_start = nc.variables["log_gps_lon"][1]
        gps_time_start = nc.variables["log_gps_time"][1]
        gps_lat_end = nc.variables["log_gps_lat"][2]
        gps_lon_end = nc.variables["log_gps_lon"][2]
        gps_time_end = nc.variables["log_gps_time"][2]
    except:
        log_error(
            f"Could not process {dive_nc_file_name} due to missing variables", "exc"
        )
        return None

    return dive_gps_position(
        gps_lat_one,
        gps_lon_one,
        gps_time_one,
        gps_lat_start,
        gps_lon_start,
        gps_time_start,
        gps_lat_end,
        gps_lon_end,
        gps_time_end,
        dive_num,
    )


# pylint: disable=unused-argument
def main(
    instrument_id=None,
    base_opts=None,
    sg_calib_file_name=None,
    dive_nc_file_names=None,
    nc_files_created=None,
    processed_other_files=None,
    known_mailer_tags=None,
    known_ftp_tags=None,
    processed_file_names=None,
):
    """Command line app for creating kml/kmz files

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions("Command line app for creating kml/kmz files")
    BaseLogger(base_opts)  # initializes BaseLog

    if known_mailer_tags is not None:
        known_mailer_tags.append("kml")
        known_mailer_tags.append("kmz")

    if known_ftp_tags is not None:
        known_ftp_tags.append("kml")
        known_ftp_tags.append("kmz")

    processing_start_time = time.time()
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info(f"Config name = {base_opts.config_file_name}")

    if sg_calib_file_name is None:
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")

    paam_compare_dict = {}

    # Collect the paam data, if available
    if base_opts.paam_data_directory:
        log_info("Processing PAAM data")
        base_opts.paam_data_directory = os.path.abspath(
            os.path.expanduser(base_opts.paam_data_directory)
        )
        paam_compare_dict = process_paam_data(
            base_opts.paam_data_directory, base_opts.paam_ici_percentage
        )

    zip_kml = base_opts.compress_output

    # Read sg_calib_constants file
    calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_error(
            "Could not process %s - skipping creation of KML/KMZ file"
            % sg_calib_file_name
        )
        return 1

    if not dive_nc_file_names:
        dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"), base_opts
    )
    if comm_log is None:
        log_warning("Could not process comm.log - surface positions not plotted")

    if (
        dive_nc_file_names is None or len(dive_nc_file_names) <= 0
    ) and comm_log is None:
        log_critical("No matching netCDF files or comm.log found - exiting")
        return 1

    if instrument_id is None:
        if comm_log is not None:
            instrument_id = comm_log.get_instrument_id()
        if (
            (instrument_id is None or instrument_id < 0)
            and dive_nc_file_names
            and len(dive_nc_file_names) > 0
        ):
            instrument_id = FileMgr.get_instrument_id(dive_nc_file_names[0])
        if instrument_id is None or instrument_id < 0:
            log_error("Could not get instrument id - bailing out")
            return 1

    mission_title = Utils.ensure_basename(calib_consts["mission_title"])
    mission_title_raw = calib_consts["mission_title"]

    if True:
        mission_kml_file_name_base = "sg%03d.kml" % (instrument_id)
        mission_kmz_file_name_base = "sg%03d.kmz" % (instrument_id)
    else:
        mission_kml_file_name_base = "sg%03d_%s.kml" % (instrument_id, mission_title)
        mission_kmz_file_name_base = "sg%03d_%s.kmz" % (instrument_id, mission_title)

    mission_kml_name = os.path.join(base_opts.mission_dir, mission_kml_file_name_base)

    try:
        fo = open(mission_kml_name, "w")
    except:
        log_error(f"Could not open {mission_kml_name}", "exc")
        log_info("Bailing out...")
        return 1

    printHeader(
        "SG%03d %s" % (instrument_id, mission_title_raw),
        "SG%03d %s" % (instrument_id, mission_title_raw),
        base_opts.color,
        fo,
    )

    # Attempt to collect surfacing positions from comm.log
    # Do this here to get any dive0 entries
    surface_positions = []
    if comm_log is not None:
        for session in comm_log.sessions:
            if session.gps_fix is not None and session.gps_fix.isvalid:
                surface_positions.append(
                    surface_pos(
                        Utils.ddmm2dd(session.gps_fix.lon),
                        Utils.ddmm2dd(session.gps_fix.lat),
                        time.mktime(session.gps_fix.datetime),
                        session.dive_num,
                        session.call_cycle,
                    )
                )

    # Sort by time
    surface_positions = sorted(
        surface_positions, key=lambda position: position.gps_fix_time
    )
    last_surface_position = surface_positions[-1] if len(surface_positions) else None
    # We will see surface positions as heads of drift locations

    # Plot dives
    dive_gps_positions = {}
    fo.write(
        '<Folder id="SG%0.3dDives">\n<name>SG%0.3d Dives</name>\n'
        % (instrument_id, instrument_id)
    )

    # Pull out the GPS positions
    if dive_nc_file_names and len(dive_nc_file_names) > 0:
        dive_nc_file_names.sort()

        # GPS positions
        for dive_index in range(len(dive_nc_file_names)):
            dive_nc_file_name = dive_nc_file_names[dive_index]
            head, tail = os.path.split(
                os.path.abspath(os.path.expanduser(dive_nc_file_name))
            )
            dive_num = int(tail[4:8])
            gps_pos = extractGPSPositions(dive_nc_file_name, dive_num)
            if gps_pos is not None:
                dive_gps_positions[dive_num] = gps_pos

    # Deal with Dive 0
    # Add any non-plotted surface positions
    dive0_positions = [i for i in surface_positions if i.dive_num == 0]
    if len(dive0_positions):
        dive_num = 0
        fo.write('    <Folder id="SG%03d dive %03d">\n' % (instrument_id, dive_num))
        fo.write("    <name>SG%03d dive %03d</name>\n" % (instrument_id, dive_num))

        for position in dive0_positions:
            try:
                ballon_pairs = []
                ballon_pairs.append(("Seaglider", "SG%03d" % instrument_id))
                ballon_pairs.append(
                    (
                        "Dive/CallCycle",
                        "%d:%d" % (position.dive_num, position.call_cycle),
                    )
                )
                ballon_pairs.append(
                    (
                        "Fix time",
                        time.strftime(
                            "%H:%M:%S %m/%d/%y %Z", time.gmtime(position.gps_fix_time)
                        ),
                    )
                )
                ballon_pairs.append(("Lat", f"{position.gps_fix_lat:.4f}"))
                ballon_pairs.append(("Lon", f"{position.gps_fix_lon:.4f}"))
                printDivePlacemark(
                    "SG%03d %d:%d"
                    % (instrument_id, position.dive_num, position.call_cycle),
                    "GPS fix at %s"
                    % (
                        time.strftime(
                            "%H:%M:%S %m/%d/%y %Z", time.gmtime(position.gps_fix_time)
                        )
                    ),
                    position.gps_fix_lon,
                    position.gps_fix_lat,
                    0.0,
                    fo,
                    True,
                    ballon_pairs,
                )
            except:
                log_error("Could not print surface position placemark", "exc")

        # Add the start of dive 1 into the mix, if available
        if 1 in list(dive_gps_positions.keys()):
            dive0_positions.append(
                surface_pos(
                    dive_gps_positions[1].gps_lon_start,
                    dive_gps_positions[1].gps_lat_start,
                    dive_gps_positions[1].gps_time_start,
                    0,
                    0,
                )
            )

        if len(dive0_positions) > 1:
            fo.write("    <Placemark>\n")
            fo.write("        <name>SG%03d Drift Track 0 </name>\n" % (instrument_id,))
            fo.write("        <styleUrl>#SeagliderDriftTrackPoly</styleUrl>\n")
            fo.write("        <LineString>\n")
            fo.write("            <extrude>0</extrude>\n")
            fo.write("            <altitudeMode>absolute</altitudeMode>\n")
            fo.write("            <coordinates>\n")
            for position in dive0_positions:
                fo.write(
                    "               %f,%f,0\n"
                    % (position.gps_fix_lon, position.gps_fix_lat)
                )
            fo.write("            </coordinates>\n")
            fo.write("        </LineString>\n")
            fo.write("    </Placemark>\n")

        fo.write("    </Folder>\n")

    # Remove any dive 0 related positions and resort
    surface_positions = [i for i in surface_positions if i.dive_num != 0]

    if dive_nc_file_names and len(dive_nc_file_names) > 0 and base_opts.plot_dives:
        dive_nc_file_names.sort()

        # Regular dives
        for dive_index in range(len(dive_nc_file_names)):
            dive_nc_file_name = dive_nc_file_names[dive_index]
            head, tail = os.path.split(
                os.path.abspath(os.path.expanduser(dive_nc_file_name))
            )
            dive_num = int(tail[4:8])
            if dive_num not in dive_gps_positions:
                continue
            # Removed as this often is confusing with the last reported position
            # if((dive_index == len(dive_nc_file_names) - 1)):
            #    last_dive = True
            # else:
            #    last_dive = False
            try:
                paam_dict = paam_compare_dict[dive_num]
            except:
                paam_dict = None

            fo.write('    <Folder id="SG%03d dive %03d">\n' % (instrument_id, dive_num))
            fo.write("    <name>SG%03d dive %03d</name>\n" % (instrument_id, dive_num))

            # To get the old behaviour, replace True with last_dive
            # dive_gps_positions[dive_num]
            printDive(
                base_opts,
                dive_nc_file_name,
                instrument_id,
                dive_num,
                False,
                paam_dict,
                fo,
            )

            # Add any non-plotted surface positions and drift tracks here
            non_plotted_positions = [
                i
                for i in surface_positions
                if i.dive_num == dive_num
                and i.gps_fix_time != dive_gps_positions[dive_num].gps_time_start
                and i.gps_fix_time != dive_gps_positions[dive_num].gps_time_end
            ]

            for position in non_plotted_positions:
                try:
                    ballon_pairs = []
                    ballon_pairs.append(("Seaglider", "SG%03d" % instrument_id))
                    ballon_pairs.append(
                        (
                            "Dive/CallCycle",
                            "%d:%d" % (position.dive_num, position.call_cycle),
                        )
                    )
                    ballon_pairs.append(
                        (
                            "Fix time",
                            time.strftime(
                                "%H:%M:%S %m/%d/%y %Z",
                                time.gmtime(position.gps_fix_time),
                            ),
                        )
                    )
                    ballon_pairs.append(("Lat", f"{position.gps_fix_lat:.4f}"))
                    ballon_pairs.append(("Lon", f"{position.gps_fix_lon:.4f}"))
                    printDivePlacemark(
                        "SG%03d %d:%d"
                        % (instrument_id, position.dive_num, position.call_cycle),
                        "GPS fix at %s"
                        % (
                            time.strftime(
                                "%H:%M:%S %m/%d/%y %Z",
                                time.gmtime(position.gps_fix_time),
                            )
                        ),
                        position.gps_fix_lon,
                        position.gps_fix_lat,
                        0.0,
                        fo,
                        True,
                        ballon_pairs,
                    )
                except:
                    log_error("Could not print surface position placemark", "exc")

            if len(surface_positions) == 0 and dive_num in dive_gps_positions:
                # Couldn't find surface positions from comm.log
                # Make one up for this dive in case last...
                last_surface_position = surface_pos(
                    dive_gps_positions[dive_num].gps_lon_end,
                    dive_gps_positions[dive_num].gps_lat_end,
                    dive_gps_positions[dive_num].gps_time_end,
                    dive_num,
                    0,
                )

            # Drift track
            non_plotted_positions.append(
                surface_pos(
                    dive_gps_positions[dive_num].gps_lon_end,
                    dive_gps_positions[dive_num].gps_lat_end,
                    dive_gps_positions[dive_num].gps_time_end,
                    0,
                    0,
                )
            )

            # non_plotted_positions.append(
            #     surface_pos(
            #         dive_gps_positions[dive_num].gps_lon_start,
            #         dive_gps_positions[dive_num].gps_lat_start,
            #         dive_gps_positions[dive_num].gps_time_start,
            #         0,
            #         0,
            #     )
            # )
            # non_plotted_positions.append(
            #     surface_pos(
            #         dive_gps_positions[dive_num].gps_lon_one,
            #         dive_gps_positions[dive_num].gps_lat_one,
            #         dive_gps_positions[dive_num].gps_time_one,
            #         0,
            #         0,
            #     )
            # )

            if dive_num + 1 in list(dive_gps_positions.keys()):
                non_plotted_positions.append(
                    surface_pos(
                        dive_gps_positions[dive_num + 1].gps_lon_start,
                        dive_gps_positions[dive_num + 1].gps_lat_start,
                        dive_gps_positions[dive_num + 1].gps_time_start,
                        0,
                        0,
                    )
                )

            drift_positions = sorted(
                non_plotted_positions, key=lambda position: position.gps_fix_time
            )

            if len(drift_positions) > 1:
                fo.write("    <Placemark>\n")
                fo.write(
                    "        <name>SG%03d Drift Track %d </name>\n"
                    % (instrument_id, dive_num)
                )
                fo.write("        <styleUrl>#SeagliderDriftTrackPoly</styleUrl>\n")
                fo.write("        <LineString>\n")
                fo.write("            <extrude>0</extrude>\n")
                fo.write("            <altitudeMode>absolute</altitudeMode>\n")
                fo.write("            <coordinates>\n")
                for position in drift_positions:
                    fo.write(
                        "               %f,%f,0\n"
                        % (position.gps_fix_lon, position.gps_fix_lat)
                    )
                fo.write("            </coordinates>\n")
                fo.write("        </LineString>\n")
                fo.write("    </Placemark>\n")

            fo.write("    </Folder>\n")

            # Remove any positions associated with this dive
            surface_positions = [i for i in surface_positions if i.dive_num != dive_num]

        # At this point, we have a potential collection of surface positions from dives that
        # have not processed for whatever reason
        if len(surface_positions):
            non_processed_dives = []
            # Build collection of dives
            for i in surface_positions:
                if i.dive_num not in non_processed_dives:
                    non_processed_dives.append(i.dive_num)

            for dive_num in non_processed_dives:
                non_plotted_positions = [
                    i for i in surface_positions if i.dive_num == dive_num
                ]
                fo.write(
                    '    <Folder id="SG%03d dive %03d">\n' % (instrument_id, dive_num)
                )
                fo.write(
                    "    <name>SG%03d dive %03d</name>\n" % (instrument_id, dive_num)
                )

                for position in non_plotted_positions:
                    try:
                        ballon_pairs = []
                        ballon_pairs.append(("Seaglider", "SG%03d" % instrument_id))
                        ballon_pairs.append(
                            (
                                "Dive/CallCycle",
                                "%d:%d" % (position.dive_num, position.call_cycle),
                            )
                        )
                        ballon_pairs.append(
                            (
                                "Fix time",
                                time.strftime(
                                    "%H:%M:%S %m/%d/%y %Z",
                                    time.gmtime(position.gps_fix_time),
                                ),
                            )
                        )
                        ballon_pairs.append(("Lat", f"{position.gps_fix_lat:.4f}"))
                        ballon_pairs.append(("Lon", f"{position.gps_fix_lon:.4f}"))
                        printDivePlacemark(
                            "SG%03d %d:%d"
                            % (instrument_id, position.dive_num, position.call_cycle),
                            "GPS fix at %s"
                            % (
                                time.strftime(
                                    "%H:%M:%S %m/%d/%y %Z",
                                    time.gmtime(position.gps_fix_time),
                                )
                            ),
                            position.gps_fix_lon,
                            position.gps_fix_lat,
                            0.0,
                            fo,
                            True,
                            ballon_pairs,
                        )
                    except:
                        log_error("Could not print surface position placemark", "exc")

                fo.write("    </Folder>\n")

                # Remove any positions associated with this (non-plotted) dive
                surface_positions = [
                    i for i in surface_positions if i.dive_num != dive_num
                ]

    # Close out dive folder
    fo.write("</Folder>\n")

    # Print the last known position outside the tree structure
    if last_surface_position:
        if last_surface_position:
            try:
                ballon_pairs = []
                ballon_pairs.append(("Seaglider", "SG%03d" % instrument_id))
                ballon_pairs.append(
                    (
                        "Dive/CallCycle",
                        "%d:%d"
                        % (
                            last_surface_position.dive_num,
                            last_surface_position.call_cycle,
                        ),
                    )
                )
                ballon_pairs.append(
                    (
                        "Fix time",
                        time.strftime(
                            "%H:%M:%S %m/%d/%y %Z",
                            time.gmtime(last_surface_position.gps_fix_time),
                        ),
                    )
                )
                ballon_pairs.append(("Lat", f"{last_surface_position.gps_fix_lat:.4f}"))
                ballon_pairs.append(("Lon", f"{last_surface_position.gps_fix_lon:.4f}"))
                # printDivePlacemark("Last reported position SG%03d %d:%d"
                #                   % (instrument_id, last_surface_position.dive_num, last_surface_position.call_cycle),
                printDivePlacemark(
                    "SG%03d" % (instrument_id),
                    "Last GPS fix at %s"
                    % (
                        time.strftime(
                            "%H:%M:%S %m/%d/%y %Z",
                            time.gmtime(last_surface_position.gps_fix_time),
                        )
                    ),
                    last_surface_position.gps_fix_lon,
                    last_surface_position.gps_fix_lat,
                    0.0,
                    fo,
                    False,
                    ballon_pairs,
                )
            except:
                log_error("Could not print surface position placemark", "exc")

    # Targets file processing

    # Find the current target
    if base_opts.targets != "none":

        tgt_name = tgt_lat = tgt_lon = tgt_radius = None

        # TODO - this needs to be replaced with processing the .nc files
        logfiles = []
        glob_expr = "p[0-9][0-9][0-9][0-9][0-9][0-9][0-9].log"
        for match in glob.glob(os.path.join(base_opts.mission_dir, glob_expr)):
            logfiles.append(match)

        tgt_name = None

        if logfiles != []:
            logfiles = Utils.unique(logfiles)
            logfiles = sorted(logfiles)
            log_file = LogFile.parse_log_file(logfiles[-1])
            try:
                tgt_name = log_file.data["$TGT_NAME"]

                if base_opts.use_glider_target:
                    latlong = log_file.data["$TGT_LATLONG"]
                    tgt_lat, tgt_lon = latlong.split(",")
                    tgt_lat = Utils.ddmm2dd(float(tgt_lat))
                    tgt_lon = Utils.ddmm2dd(float(tgt_lon))
                    tgt_radius = float(log_file.data["$TGT_RADIUS"])
            except:
                tgt_name = tgt_lat = tgt_lon = tgt_radius = None

        # Display targets
        targets = []
        for glob_expr in (
            "targets.[0-9]*",
            "targets.[0-9]*.[0-9]*",
            "targets.plain.[0-9]*",
            "targets.plain.[0-9]*.[0-9]*",
        ):
            for match in glob.glob(os.path.join(base_opts.mission_dir, glob_expr)):
                targets.append(match)

        if targets != [] and not base_opts.proposed_targets:
            targets = Utils.unique(targets)
            targets = sorted(targets, key=functools.cmp_to_key(cmp_function))
            printTargets(
                tgt_name,
                base_opts.targets == "current",
                targets[0],
                instrument_id,
                base_opts.target_radius,
                fo,
                tgt_lon=tgt_lon,
                tgt_lat=tgt_lat,
                tgt_radius=tgt_radius,
            )
        else:
            target_file_name = os.path.join(base_opts.mission_dir, "targets")
            if os.path.exists(target_file_name):
                printTargets(
                    tgt_name,
                    base_opts.targets == "current",
                    target_file_name,
                    instrument_id,
                    base_opts.target_radius,
                    fo,
                    tgt_lon=tgt_lon,
                    tgt_lat=tgt_lat,
                    tgt_radius=tgt_radius,
                )

    printFooter(fo)

    fo.close()

    # Zip the output file
    if zip_kml:
        head, _ = os.path.splitext(mission_kml_name)
        mission_kml_zip_name = head + ".kmz"
        try:
            mission_kml_zip_file = zipfile.ZipFile(
                mission_kml_zip_name, "w", zipfile.ZIP_DEFLATED
            )
            mission_kml_zip_file.write(mission_kml_name, mission_kml_file_name_base)
            mission_kml_zip_file.close()
            os.remove(mission_kml_name)
        except:
            log_error(f"Could not process {mission_kml_zip_name}", "exc")
            log_info("Bailing out...")
            return 1
        if processed_other_files is not None:
            processed_other_files.append(mission_kml_zip_name)
    else:
        if processed_other_files is not None:
            processed_other_files.append(mission_kml_name)

    # Write out the network link file
    if base_opts.web_file_location:
        networklink_kml_name = os.path.join(
            base_opts.mission_dir, "sg%03d_network.kml" % instrument_id
        )
        try:
            fo = open(networklink_kml_name, "w")
        except:
            log_error(f"Could not open {networklink_kml_name}", "exc")
            log_info("Skipping...")
        else:
            if zip_kml:
                url = os.path.join(
                    base_opts.web_file_location, mission_kmz_file_name_base
                )
            else:
                url = os.path.join(
                    base_opts.web_file_location, mission_kml_file_name_base
                )
            writeNetworkKML(fo, "SG%03d Track" % instrument_id, url)
            fo.close()

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info("Run time %f seconds" % (time.time() - processing_start_time))
    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            retval = main()
    except SystemExit:
        pass
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
