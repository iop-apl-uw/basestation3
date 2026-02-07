#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
##
## Redistribution and use in source and binary forms, with or without
## modification, are permitted provided that the following conditions are met:
##
## 1. Redistributions of source code must retain the above copyright notice, this
##    list of conditions and the following disclaimer.
##
## 2. Redistributions in binary form must reproduce the above copyright notice,
##    this list of conditions and the following disclaimer in the documentation
##    and/or other materials provided with the distribution.
##
## 3. Neither the name of the University of Washington nor the names of its
##    contributors may be used to endorse or promote products derived from this
##    software without specific prior written permission.
##
## THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
## IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
## DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
## GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
## HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
## LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
## OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Routines for creating KML files from netCDF data, comm.log and target files"""

import collections
import cProfile
import functools
import glob
import io
import math
import os
import pdb
import pstats
import re
import sys
import time
import traceback
import zipfile

# import importlib.util
# import importlib
import numpy as np
import pyarrow as pa

import BaseNetCDF
import BaseOpts
import CommLog
import FileMgr
import GPS
import LogFile
import MakeDiveProfiles
import Utils
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)
from CalibConst import getSGCalibrationConstants

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


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
    ["gps_fix_lon", "gps_fix_lat", "gps_fix_time", "dive_num", "call_cycle", "sms"],
)

m_per_deg = 111120.0

# Parquet files
# TODO - expand to include all the below fields to ensure .cfg file
# can't override what's needed here
kml_cfg_d = {
    "depth_avg_curr_east_gsm": "f",
    "depth_avg_curr_north_gsm": "f",
    "east_displacement": "f",
    "east_displacement_gsm": "f",
    "log_D_GRID": "f",
    "log_D_TGT": "f",
    "log_TGT_LATLONG": "c",
    "log_gps_lat": True,
    "log_gps_lon": True,
    "log_gps_time": True,
    "north_displacement": "f",
    "north_displacement_gsm": "f",
    "surface_curr_east": "f",
    "surface_curr_north": "f",
}

expected_schema = pa.schema(
    [
        pa.field("trajectory", pa.int32()),
        pa.field("ctd_depth", pa.float32()),
        pa.field("depth", pa.float32()),
        pa.field("depth_avg_curr_east", pa.float32()),
        pa.field("depth_avg_curr_east_gsm", pa.float32()),
        pa.field("depth_avg_curr_north", pa.float32()),
        pa.field("depth_avg_curr_north_gsm", pa.float32()),
        pa.field("east_displacement", pa.float32()),
        pa.field("east_displacement_gsm", pa.float32()),
        pa.field("latitude", pa.float32()),
        pa.field("latitude_gsm", pa.float32()),
        pa.field("log_D_GRID", pa.float32()),
        pa.field("log_D_TGT", pa.float32()),
        pa.field("log_TGT_LATLONG", pa.string()),
        pa.field("log_gps_lat", pa.float32()),
        pa.field("log_gps_lon", pa.float32()),
        pa.field("log_gps_time", pa.float64()),
        pa.field("longitude", pa.float32()),
        pa.field("longitude_gsm", pa.float32()),
        pa.field("north_displacement", pa.float32()),
        pa.field("north_displacement_gsm", pa.float32()),
        pa.field("surface_curr_east", pa.float32()),
        pa.field("surface_curr_north", pa.float32()),
        pa.field("time", pa.float64()),
        pa.field(BaseNetCDF.nc_ctd_time_var, pa.float64()),
    ]
)
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
    a_split = a.split(".")
    b_split = b.split(".")

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


def printDivePlacemark(
    name, description, lon, lat, depth, fo, hide_label, pairs=None, style=None
):
    """Places a seaglider marker on the map"""
    # Start dive place mark
    fo.write("    <Placemark>\n")
    fo.write(f"        <name>{name}</name>\n")

    if style:
        fo.write(f"        <styleUrl>{style}</styleUrl>\n")
    else:
        if hide_label:
            fo.write("        <styleUrl>#seagliderPosition</styleUrl>\n")
        else:
            fo.write("        <styleUrl>#seagliderPositionHighlightState</styleUrl>\n")

    fo.write(f"        <description>{description}</description>\n")
    if pairs:
        fo.write('        <Style><BalloonStyle><text><![CDATA[<div align="center">\n')
        fo.write('        <table width="400" bgcolor="white">\n')
        for pair in pairs:
            if pair[0] is None:
                fo.write('        </table><hr /><table width="400" bgcolor="white">\n')
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
    visible=True,
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
    if not visible:
        fo.write("        <visibility>0</visibility>\n")
    fo.write(f"        <description>{description}</description>\n")
    fo.write('        <Style><BalloonStyle><text><![CDATA[<div align="center">\n')
    fo.write('        <table width="400" bgcolor="white">\n')
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
        if not visible:
            fo.write("        <visibility>0</visibility>\n")
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


def printTargetLine(
    from_name, from_lat, from_lon, to_name, to_lat, to_lon, escape, fo, visible=True
):
    """Draws the line between to two targets"""
    fo.write("    <Placemark>\n")
    fo.write(f"        <name>{from_name} to {to_name}</name>\n")
    if not visible:
        fo.write("        <visibility>0</visibility>\n")
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
    hide_non_active_targets=False,
):
    """Proceses a target file"""
    try:
        target_file = open(target_file_name, "r")
    except Exception:
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
    line_count = 0
    for target_line in target_file:
        line_count += 1
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
                log_warning(
                    f"Could not split (pair) - bad format in targets file {target_file_name} (lineno:{line_count}?"
                )
                break
            if name == "lat":
                try:
                    lat = Utils.ddmm2dd(float(value))
                except ValueError as e:
                    log_warning(
                        f"Failed to convert lat={value} ({e}) (file:{target_file_name}, lineno:{line_count}"
                    )
                    break
            elif name == "lon":
                try:
                    lon = Utils.ddmm2dd(float(value))
                except ValueError as e:
                    log_warning(
                        f"Failed to convert lon={value} ({e}) (file:{target_file_name}, lineno:{line_count}"
                    )
                    break
            elif name == "radius":
                try:
                    radius = float(value)
                except ValueError as e:
                    log_warning(
                        f"Failed to convert radius={value} ({e}) (file:{target_file_name}, lineno:{line_count}"
                    )
                    break
            elif name == "goto":
                goto_targ = value
            elif name == "escape":
                pass
                # Need to fix this for escape routes
                # escape_targ = value
            elif name == "finish":
                try:
                    finish_line = float(value)
                except ValueError as e:
                    log_warning(
                        f"Failed to convert finish={value} ({e}) (file:{target_file_name}, lineno:{line_count}"
                    )
                    break
            # elif name == "depth":
            #    depth_limit = float(value)
        else:
            target_dict[target_name] = target_tuple(
                lat, lon, radius, finish_line, depth_target, goto_targ, escape_targ
            )

    if tgt_lat is not None and tgt_lon is not None:
        found_in_list = False
        for _, v in target_dict.items():
            if v.lat == tgt_lat and v.lon == tgt_lon:
                found_in_list = True

        if not found_in_list and active_target:
            if active_target in target_dict:
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

    for targ in target_dict:
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
                visible=not hide_non_active_targets,
            )

    # Draw course between targets
    # TODO - special case the loop back case - same target source and dest
    if not only_active_target:
        for targ in target_dict:
            if target_dict[targ].goto_target in target_dict:
                printTargetLine(
                    targ,
                    target_dict[targ].lat,
                    target_dict[targ].lon,
                    target_dict[targ].goto_target,
                    target_dict[target_dict[targ].goto_target].lat,
                    target_dict[target_dict[targ].goto_target].lon,
                    False,
                    fo,
                    visible=not hide_non_active_targets,
                )
            if target_dict[targ].escape_target in target_dict:
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
                    visible=not hide_non_active_targets,
                )
    fo.write("</Folder>\n")
    return None


def printDive(
    base_opts,
    nc_file_name_or_pq_df_c,
    instrument_id,
    dive_num,
    last_dive,
    fo,
    call_time=None,
):
    """Processes a dive
    Returns:

    Tuple
    (gps_lat_start, gps_lon_start, gps_time_start, gps_lat_end, gps_lon_end, gps_time_end, dive_num)
    If any measurements are not available, return None for that position
    """
    pq_df = None
    if isinstance(nc_file_name_or_pq_df_c, str):
        dive_nc_file_name = nc_file_name_or_pq_df_c

        err_curr_dive_position = dive_gps_position(
            None, None, None, None, None, None, None, None, None, None
        )
        try:
            nc = Utils.open_netcdf_file(dive_nc_file_name, "r")
        except Exception:
            log_error(f"Could not read {dive_nc_file_name}", "exc")
            log_info("Skipping...")
            return err_curr_dive_position
        with nc:
            log_debug(f"Processing {dive_nc_file_name}")
            gps_lat_start = gps_lon_start = gps_time_start = gps_lat_end = (
                gps_lon_end
            ) = gps_time_end = None

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
            except Exception:
                log_error(
                    f"Could not process {dive_nc_file_name} due to missing variables",
                    "exc",
                )
                return err_curr_dive_position

            for i in range(3):
                if (
                    np.isnan(nc.variables["log_gps_time"][i])
                    or np.isnan(nc.variables["log_gps_lat"][i])
                    or np.isnan(nc.variables["log_gps_lon"][i])
                ):
                    log_error(
                        f"Could not process {dive_nc_file_name} due to missing variables"
                    )
                    return err_curr_dive_position

            curr_dive_position = dive_gps_position(
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

            # if "processing_error" in nc.variables:
            #     log_warning(
            #         f"{dive_nc_file_name} is marked as having a processing error - skipping"
            #     )
            #     return curr_dive_position

            if "skipped_profile" in nc.variables:
                log_warning(
                    f"{dive_nc_file_name} is marked as a skipped_profile - skipping"
                )
                return curr_dive_position
            # Dive Track
            try:
                depth = nc.variables["ctd_depth"][:]
                lon = nc.variables["longitude"][:]
                lat = nc.variables["latitude"][:]
                time_vals = nc.variables[BaseNetCDF.nc_ctd_time_var][:]
                num_points = len(time_vals)
            except KeyError:
                # Check for GSM only versions
                try:
                    depth = nc.variables["depth"][:]
                    lon = nc.variables["longitude_gsm"][:]
                    lat = nc.variables["latitude_gsm"][:]
                    time_vals = nc.variables["time"][:]
                    num_points = len(time_vals)
                except KeyError as e:
                    log_warning(
                        f"Could not process {dive_nc_file_name} due to missing variables {e}"
                    )
                    log_info("Skipping this dive...")
                    return curr_dive_position
                else:
                    if len(lon) != num_points:
                        log_warning(
                            f"Could not process {dive_nc_file_name} due to mismatch in dimensions",
                        )
                        log_info("Skipping this dive...")
                        return curr_dive_position
            except Exception:
                log_warning(f"Could not process {dive_nc_file_name}", "exc")
                log_info("Skipping this dive...")
                return curr_dive_position
            latlong = nc.variables["log_TGT_LATLONG"][:].tobytes().decode("utf-8")
            try:
                nd = nc.variables["north_displacement"][:]
                ed = nc.variables["east_displacement"][:]
                f_disp_gsm = False
            except Exception:
                try:
                    nd = nc.variables["north_displacement_gsm"][:]
                    ed = nc.variables["east_displacement_gsm"][:]
                    f_disp_gsm = True
                except Exception:
                    log_error(
                        f"Could not find any displacements in {dive_nc_file_name} - skipping",
                        "exc",
                    )
                    nd = ed = None
            d_grid = nc.variables["log_D_GRID"].getValue()
            d_tgt = nc.variables["log_D_TGT"].getValue()
            surf_east = surf_north = None
            try:
                surf_east = nc.variables["surface_curr_east"].getValue()
                surf_north = nc.variables["surface_curr_north"].getValue()
            except KeyError:
                pass
            try:
                dac_east = nc.variables["depth_avg_curr_east"].getValue()
                dac_north = nc.variables["depth_avg_curr_north"].getValue()
                f_dac_gsm = False
            except KeyError:
                dac_east = nc.variables["depth_avg_curr_east_gsm"].getValue()
                dac_north = nc.variables["depth_avg_curr_north_gsm"].getValue()
                f_dac_gsm = True

        assert not nc._isopen
    else:
        # pq_df case
        pq_df_c = nc_file_name_or_pq_df_c
        pq_df = pq_df_c.find_first_col("log_gps_time")
        curr_dive_position = extractGPSPositions_df(pq_df, dive_num=dive_num)[dive_num]
        (
            gps_lat_one,
            gps_lon_one,
            gps_time_one,
            gps_lat_start,
            gps_lon_start,
            gps_time_start,
            gps_lat_end,
            gps_lon_end,
            gps_time_end,
            _,
        ) = curr_dive_position

        for dive_vars in (
            ["ctd_depth", "longitude", "latitude", BaseNetCDF.nc_ctd_time_var],
            ["depth", "longitude_gsm", "latitude_gsm", "time"],
        ):
            f_found_one = False
            for _, pq_df in pq_df_c.find_all_cols(dive_vars[1]).items():
                if all(ii in pq_df.columns for ii in dive_vars):
                    dive_track = pq_df.loc[pq_df["trajectory"] == dive_num][dive_vars]
                    if all(
                        dive_track[dive_vars[ii]][
                            dive_track[dive_vars[ii]].notna()
                        ].size
                        != 0
                        for ii in range(len(dive_vars))
                    ):
                        f_found_one = True
                        break
            if f_found_one:
                break
        else:
            log_warning(f"Could not process dive {dive_num}")
            log_info("Skipping this dive...")
            return curr_dive_position
        dive_track_vectors = tuple(
            dive_track[dive_vars[ii]][dive_track[dive_vars[ii]].notna()].to_numpy()
            for ii in range(len(dive_vars))
        )
        if not all(x.size for x in dive_track_vectors):
            log_error(f"Mismatch in columns {dive_vars} for dive {dive_num} - skipping")
            return curr_dive_position

        depth, lon, lat, time_vals = dive_track_vectors
        num_points = len(time_vals)

        pq_df = pq_df_c.find_first_col("log_TGT_LATLONG")
        latlong = (
            get_df_var(pq_df, dive_num, "log_TGT_LATLONG")
            .astype(bytes)
            .tobytes()
            .decode("utf-8")
        )

        try:
            pq_df = pq_df_c.find_first_col("north_displacement")
            nd = get_df_var(pq_df, dive_num, "north_displacement")
            ed = get_df_var(pq_df, dive_num, "east_displacement")
            f_disp_gsm = False
        except Exception:
            try:
                pq_df = pq_df_c.find_first_col("north_displacement_gsm")
                nd = get_df_var(pq_df, dive_num, "north_displacement_gsm")
                ed = get_df_var(pq_df, dive_num, "east_displacement_gsm")
                f_disp_gsm = True
            except KeyError as exception:
                log_warning(
                    f"Could not find [{exception}] in parquet output - skipping dive {dive_num}",
                )
                nd = ed = None
            except Exception:
                log_error(
                    "Could not find any displacements in parquet output for dive {dive_num} - skipping",
                    "exc",
                )
                nd = ed = None

        pq_df = pq_df_c.find_first_col("log_D_GRID")
        d_grid = get_df_single(pq_df, dive_num, "log_D_GRID")
        d_tgt = get_df_single(pq_df, dive_num, "log_D_TGT")
        surf_east = surf_north = None
        try:
            surf_east = get_df_single(pq_df, dive_num, "surface_curr_east")
            surf_north = get_df_single(pq_df, dive_num, "surface_curr_north")
        except KeyError:
            pass

        try:
            dac_east = get_df_single(pq_df, dive_num, "depth_avg_curr_east")
            dac_north = get_df_single(pq_df, dive_num, "depth_avg_curr_north")
            f_dac_gsm = False
        except KeyError:
            try:
                dac_east = get_df_single(pq_df, dive_num, "depth_avg_curr_east_gsm")
                dac_north = get_df_single(pq_df, dive_num, "depth_avg_curr_north_gsm")
                f_dac_gsm = True
            except KeyError:
                dac_east = dac_north = None

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
            "        <name>SG%03d Dive %03d Track</name>\n" % (instrument_id, dive_num)
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
                ) and ((i % base_opts.skip_points) == 0 or i == 0):
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
            "        <name>SG%03d Dive %03d Track</name>\n" % (instrument_id, dive_num)
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
            ) and ((i % base_opts.skip_points) == 0 or i == 0):
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

    try:
        dog, cog = Utils.bearing(gps_lat_start, gps_lon_start, gps_lat_end, gps_lon_end)
    except Exception:
        log_error(f"Could not process dog/cog from {dive_nc_file_name}", "exc")
        dog = cog = None

    try:
        tgt_lat, tgt_lon = latlong.split(",")
        tgt_lat = Utils.ddmm2dd(float(tgt_lat))
        tgt_lon = Utils.ddmm2dd(float(tgt_lon))
        dtg, ctg = Utils.bearing(gps_lat_end, gps_lon_end, tgt_lat, tgt_lon)
    except Exception:
        log_error(f"Could not process target lat/log from {dive_nc_file_name}", "exc")
        dtg = ctg = None

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

    surface_time = gps_time_start - gps_time_one
    if call_time and surface_time:
        log_debug(
            f"dive:{dive_num},surface_time:{surface_time},call_time:{call_time},diff:{surface_time-call_time:.1f}"
        )
    if surface_time:
        ballon_pairs.append(("Surface Time", f"{(surface_time)/60.0:.1f} minutes"))
    if call_time:
        ballon_pairs.append(("Call Time", f"{call_time / 60.0:.1f} minutes"))

    ballon_pairs.append((None, None))
    ballon_pairs.append(
        ("Dive length", "%d minutes" % ((time_vals[-1] - time_vals[0]) / 60.0))
    )
    ballon_pairs.append(("Depth achieved", "%d meters" % round(max(abs(depth)))))

    if not base_opts.simplified:
        ballon_pairs.append(
            (
                "Depth target",
                "%d meters" % min(d_grid, d_tgt),
            )
        )
        ballon_pairs.append((None, None))
        if cog is not None and dog is not None:
            ballon_pairs.append(("Course over ground", f"{cog:.2f} degrees"))
            ballon_pairs.append(("Distance over ground", f"{dog:.2f} km"))
        if dtw is not None and ctw is not None:
            ballon_pairs.append(
                (
                    f"Course through water{' (GSM)' if f_disp_gsm else ''}",
                    f"{ctw:.2f} degrees",
                )
            )
            ballon_pairs.append(
                (
                    f"Distance through water{' (GSM)' if f_disp_gsm else ''}",
                    f"{dtw:.2f} km",
                )
            )
        if dtg is not None and ctg is not None:
            ballon_pairs.append(("Course to go", f"{ctg:.2f} degrees"))
            ballon_pairs.append(("Distance to go", f"{dtg:.2f} km"))

        if dac_east is not None and dac_north is not None:
            DAC_mag = np.sqrt((dac_east * dac_east) + (dac_north * dac_north))
            try:
                dac_polar_rad = math.atan2(dac_north, dac_east)
                DAC_dir = 90.0 - math.degrees(dac_polar_rad)
            except ZeroDivisionError:  # atan2
                DAC_dir = 0.0
            if DAC_dir < 0.0:
                DAC_dir += 360.0

            ballon_pairs.append(
                (f"DAC dir{' (GSM)' if f_dac_gsm else ''}", f"{DAC_dir:.2f} degrees")
            )
            ballon_pairs.append(
                (f"DAC mag{' (GSM)' if f_dac_gsm else ''}", f"{DAC_mag:.3f} m/s")
            )

        if surf_east is not None:
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

    if hasattr(base_opts, "vis_base_url") and base_opts.vis_base_url:
        ballon_pairs.append(
            (
                "Dive page",
                f'<a href="{base_opts.vis_base_url}/{instrument_id}?dive={dive_num}">sg{dive_num:03d} plots</a>',
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

    return curr_dive_position


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


def extractGPSPositions(dive_nc_file_name, dive_num):
    """A hack - printDive does this and reads many more variables.  This needs to be expanded and
    printDive needs to work off the data structure this feeds OR it needs to be determined that we can have
    many (1000) netCDF files opened at once.
    """
    try:
        nc = Utils.open_netcdf_file(dive_nc_file_name, "r")
    except Exception:
        log_error(f"Could not read {dive_nc_file_name}", "exc")
        log_error("Skipping...")
        return None

    gps_lat_start = gps_lon_start = gps_time_start = gps_lat_end = gps_lon_end = (
        gps_time_end
    ) = None
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
    except Exception:
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


def extractGPSPositions_df(pq_df, dive_num=None):
    """This is parallel to the above 'hack', but from the dataframe"""

    gps_pos = {}
    try:
        for dive_n in np.unique(
            pq_df["trajectory"] if dive_num is None else (dive_num,)
        ):
            log_gps = pq_df.loc[pq_df["trajectory"] == dive_n][
                ["log_gps_lat", "log_gps_lon", "log_gps_time"]
            ]
            # log_gps = log_gps[log_gps.notna().all(axis=1)]
            # log_gps = log_gps[log_gps.notna().all(axis=1)]
            gps_pos[dive_n] = dive_gps_position(
                *(
                    log_gps[log_val].iloc[ii]
                    for ii in range(3)
                    for log_val in ("log_gps_lat", "log_gps_lon", "log_gps_time")
                ),
                dive_n,
            )
    except Exception:
        log_error("Failed to fetch data from parquet df", "exc")
    return gps_pos


def get_df_single(pq_df, dive_num, var_n):
    value = pq_df.loc[pq_df["trajectory"] == dive_num][var_n]
    if value[value.notna()].size != 1:
        raise KeyError(f"Failed to fetch {var_n}")
    return value[value.notna()].to_numpy()[0]


def get_df_var(pq_df, dive_num, var_n):
    value = pq_df.loc[pq_df["trajectory"] == dive_num][var_n]
    if value[value.notna()].size == 0:
        raise KeyError(f"Failed to fetch {var_n}")
    return value[value.notna()].to_numpy()


# pylint: disable=unused-argument
def main(
    base_opts,
    calib_consts,
    processed_other_files,
):
    """Command line app for creating kml/kmz files

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    if not base_opts:
        base_opts = BaseOpts.BaseOptions("Command line app for creating kml/kmz files")
    BaseLogger(base_opts, include_time=True)  # initializes BaseLog

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    processing_start_time = time.time()
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    zip_kml = base_opts.compress_output

    # Read sg_calib_constants file
    if not calib_consts:
        sg_calib_file_name = os.path.join(base_opts.mission_dir, "sg_calib_constants.m")
        calib_consts = getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_error(
            "Could not process %s - skipping creation of KML/KMZ file"
            % sg_calib_file_name
        )
        return 1

    #
    # A important note:
    # pq_df_c can be None - failed in processing the parquet data, or and empty dict - there was no data to process
    #
    # Beyond the initial check for of pq_df_c being None in the open, pq_df_c = None is a flag used to indicate parequet or
    # netcdf based processing
    #
    if base_opts.kml_use_parquet:
        if Utils.setup_parquet_directory(base_opts):
            log_error("Unable to setup/find parquet directory")
            return 1
        log_info(f"Loading files from {base_opts.parquet_directory}")
        pq_df_c = Utils.read_parquet_pd(base_opts.parquet_directory)
        if pq_df_c is None:
            log_error(
                "Requested parquet files, but unable to generate data frame - skipping KML/KMZ"
            )
        dive_nc_file_names = None
    else:
        dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        pq_df_c = None

    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        os.path.join(base_opts.mission_dir, "comm.log"), base_opts
    )
    if comm_log is None:
        log_warning("Could not process comm.log - surface positions not plotted")

    if (
        (pq_df_c is None or not pq_df_c)
        and (dive_nc_file_names is None or len(dive_nc_file_names) <= 0)
        and comm_log is None
    ):
        log_critical(
            "No matching netCDF files/parquet files or comm.log found - exiting"
        )
        return 1

    if not base_opts.instrument_id:
        if comm_log is not None:
            base_opts.instrument_id = comm_log.get_instrument_id()
        # TODO - need to figure out alternate approach if using parquet files
        if (
            (base_opts.instrument_id is None or base_opts.instrument_id < 0)
            and dive_nc_file_names
            and len(dive_nc_file_names) > 0
        ):
            base_opts.instrument_id = FileMgr.get_instrument_id(dive_nc_file_names[0])
        if base_opts.instrument_id is None or base_opts.instrument_id < 0:
            log_error("Could not get instrument id - bailing out")
            return 1

    mission_title = Utils.ensure_basename(calib_consts["mission_title"])
    mission_title_raw = calib_consts["mission_title"]

    if True:
        mission_kml_file_name_base = "sg%03d.kml" % (base_opts.instrument_id)
        # mission_kmz_file_name_base = "sg%03d.kmz" % (base_opts.instrument_id)
    else:
        mission_kml_file_name_base = "sg%03d_%s.kml" % (
            base_opts.instrument_id,
            mission_title,
        )
        # mission_kmz_file_name_base = "sg%03d_%s.kmz" % (
        #     base_opts.instrument_id,
        #     mission_title,
        # )

    mission_kml_name = os.path.join(base_opts.mission_dir, mission_kml_file_name_base)

    try:
        if base_opts.use_inmemory:
            fo = io.StringIO()
        else:
            fo = open(mission_kml_name, "w")
    except Exception:
        log_error(f"Could not open {mission_kml_name}", "exc")
        log_info("Bailing out...")
        return 1

    printHeader(
        "SG%03d %s" % (base_opts.instrument_id, mission_title_raw),
        "SG%03d %s" % (base_opts.instrument_id, mission_title_raw),
        base_opts.color,
        fo,
    )

    # Attempt to collect surfacing positions from comm.log
    # Do this here to get any dive0 entries
    surface_positions = []
    call_time = collections.defaultdict(int)
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
                        None,
                    )
                )
            if (
                session.connect_ts
                and session.disconnect_ts
                and session.dive_num is not None
            ):
                call_time[session.dive_num] += time.mktime(
                    session.disconnect_ts
                ) - time.mktime(session.connect_ts)

    # If there is a sms_message.log, process that
    sms_log_filename = os.path.join(base_opts.mission_dir, "sms_messages.log")
    if os.path.exists(sms_log_filename):
        try:
            with open(sms_log_filename, "r") as fi:
                for ll in fi.readlines():
                    try:
                        connect_ts = time.strptime(
                            re.search(r"^.*?UTC", ll).group(0),
                            "%H:%M:%S %d %b %Y UTC",
                        )
                    except Exception:
                        log_error(f"Could not process timestamp {ll}", "exc")
                        continue
                    try:
                        values = re.search(
                            r"\((?P<msg>.*?)\):\((?P<gliderid>.*?):\((?P<counter>.*?)\)",
                            ll,
                        )
                        if values and len(values.groupdict()) == 3:
                            iridium_splits = None
                            counter_line = values["counter"]
                            if "GPS" not in counter_line:
                                try:
                                    splits = counter_line.split()
                                    log_debug("splits = %s" % splits)
                                    if len(splits) >= 2:
                                        counter_line = "%s GPS,%s" % (
                                            splits[0],
                                            splits[1],
                                        )
                                        log_debug(
                                            "New counter line (%s)" % counter_line
                                        )
                                        iridium_splits = splits[2].split(",")
                                except Exception:
                                    log_warning(
                                        "counter line %s not an understood format"
                                        % (counter_line,),
                                        "exc",
                                    )
                            session = CommLog.ConnectSession(connect_ts, "")
                            try:
                                CommLog.crack_counter_line(
                                    base_opts,
                                    session,
                                    counter_line.split(),
                                    "Inbox SMS message",
                                    1,
                                    counter_line,
                                )
                            except Exception:
                                log_error(
                                    f"Could not crack counter line {counter_line}",
                                    "exc",
                                )
                                continue

                            # These fixes can come during selftest - its just a GPS fix w/o a counter
                            # so crack_counter_line returns an empty session.  Nothing to plot on the KML
                            # in that case
                            if (
                                session.gps_fix is None
                                or session.dive_num is None
                                or session.call_cycle is None
                            ):
                                continue

                            if (
                                session.gps_fix.hdop == 99.0
                                and iridium_splits
                                and len(iridium_splits) >= 4
                            ):
                                try:
                                    ts = time.strptime(
                                        f"{iridium_splits[0]} {iridium_splits[1]}",
                                        "%d%m%y %H%M",
                                    )
                                    surface_positions.append(
                                        surface_pos(
                                            Utils.ddmm2dd(float(iridium_splits[3])),
                                            Utils.ddmm2dd(float(iridium_splits[2])),
                                            time.mktime(ts),
                                            session.dive_num,
                                            session.call_cycle,
                                            "FixType:Iridium",
                                        )
                                    )
                                except Exception:
                                    log_error("Could not process iridium fix", "exc")
                            else:
                                # if session.gps_div
                                surface_positions.append(
                                    surface_pos(
                                        Utils.ddmm2dd(session.gps_fix.lon),
                                        Utils.ddmm2dd(session.gps_fix.lat),
                                        time.mktime(session.gps_fix.datetime),
                                        session.dive_num,
                                        session.call_cycle,
                                        "FixType:GPS",
                                    )
                                )
                    except Exception:
                        log_error(
                            f"Error processing {sms_log_filename} line {ll}", "exc"
                        )
        except Exception:
            log_error(f"Error processing {sms_log_filename}", "exc")

    # Sort by time
    surface_positions = sorted(
        surface_positions, key=lambda position: position.gps_fix_time
    )

    # Trim out everything prior to the most recent dive 0 (launch)
    if len(surface_positions):
        f_dive_0_seen = False
        first_dive_i = 0
        for ii in reversed(range(len(surface_positions))):
            # log_info(f"Index:{ii} dive_num:{surface_positions[ii].dive_num}")
            if not f_dive_0_seen:
                if surface_positions[ii].dive_num == 0:
                    f_dive_0_seen = True
            else:
                if surface_positions[ii].dive_num != 0:
                    first_dive_i = ii + 1
                    # log_info(f"first_dive_i:{first_dive_i}")
                    break

        surface_positions = surface_positions[first_dive_i:]

    # If the most recent dive is >= 1, trim out everthing prior to Dive 0:maxCycleDive0
    if len(surface_positions) and surface_positions[-1].dive_num != 0:
        first_dive_i = 0
        for ii in reversed(range(len(surface_positions))):
            # log_info(f"Index:{ii} dive_num:{surface_positions[ii].dive_num}")
            if surface_positions[ii].dive_num == 0:
                first_dive_i = ii
                # log_info(f"first_dive_i:{ii}")
                break
        surface_positions = surface_positions[first_dive_i:]

    last_surface_position = surface_positions[-1] if len(surface_positions) else None

    # We will see surface positions as heads of drift locations

    # Plot dives
    fo.write(
        '<Folder id="SG%0.3dDives">\n<name>SG%0.3d Dives</name>\n'
        % (base_opts.instrument_id, base_opts.instrument_id)
    )

    # Pull out the GPS positions
    if pq_df_c is not None:
        if pq_df_c:
            pq_df = pq_df_c.find_first_col("log_gps_time")
            dive_gps_positions = extractGPSPositions_df(pq_df)
        else:
            dive_gps_positions = {}
    else:
        dive_gps_positions = {}
        if dive_nc_file_names and len(dive_nc_file_names) > 0:
            dive_nc_file_names.sort()

            # GPS positions
            for dive_index in range(len(dive_nc_file_names)):
                # Stop processing if signaled
                try:
                    if (
                        hasattr(base_opts, "stop_processing_event")
                        and base_opts.stop_processing_event.is_set()
                    ):
                        log_warning(
                            "Caught SIGUSR1 perviously - stopping furhter MakeKML processing"
                        )
                        return 1
                except AttributeError:
                    pass

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
        fo.write(
            '    <Folder id="SG%03d dive %03d">\n' % (base_opts.instrument_id, dive_num)
        )
        fo.write(
            "    <name>SG%03d dive %03d</name>\n" % (base_opts.instrument_id, dive_num)
        )

        for position in dive0_positions:
            try:
                ballon_pairs = []
                ballon_pairs.append(("Seaglider", "SG%03d" % base_opts.instrument_id))
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
                if position.sms:
                    ballon_pairs.append(("ViaSMS", position.sms))
                printDivePlacemark(
                    "SG%03d %d:%d"
                    % (base_opts.instrument_id, position.dive_num, position.call_cycle),
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
            except Exception:
                DEBUG_PDB_F()
                log_error("Could not print surface position placemark", "exc")

        # Add the start of dive 1 into the mix, if available
        if 1 in dive_gps_positions:
            dive0_positions.append(
                surface_pos(
                    dive_gps_positions[1].gps_lon_start,
                    dive_gps_positions[1].gps_lat_start,
                    dive_gps_positions[1].gps_time_start,
                    0,
                    0,
                    None,
                )
            )

        if len(dive0_positions) > 1:
            fo.write("    <Placemark>\n")
            fo.write(
                "        <name>SG%03d Drift Track 0 </name>\n"
                % (base_opts.instrument_id,)
            )
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

    if (
        (dive_nc_file_names and len(dive_nc_file_names) > 0) or pq_df_c is not None
    ) and base_opts.plot_dives:
        if dive_nc_file_names and len(dive_nc_file_names) > 0:
            dive_nc_file_names.sort()
            dive_nums = []

            # Regular dives
            for dive_index in range(len(dive_nc_file_names)):
                # Stop processing if signaled
                try:
                    if (
                        hasattr(base_opts, "stop_processing_event")
                        and base_opts.stop_processing_event.is_set()
                    ):
                        log_warning(
                            "Caught SIGUSR1 perviously - stopping furhter MakeKML processing"
                        )
                        return 1
                except AttributeError:
                    pass

                dive_nc_file_name = dive_nc_file_names[dive_index]
                head, tail = os.path.split(
                    os.path.abspath(os.path.expanduser(dive_nc_file_name))
                )
                dive_nums.append(int(tail[4:8]))
        else:
            if pq_df_c:
                pq_df = pq_df_c.find_first_col("log_gps_time")
                dive_nums = np.unique(pq_df["trajectory"])
            else:
                dive_nums = []

        for ii, dive_num in enumerate(dive_nums):
            if dive_num not in dive_gps_positions:
                continue
            # Removed as this often is confusing with the last reported position
            # if((dive_index == len(dive_nc_file_names) - 1)):
            #    last_dive = True
            # else:
            #    last_dive = False

            fo.write(
                '    <Folder id="SG%03d dive %03d">\n'
                % (base_opts.instrument_id, dive_num)
            )
            fo.write(
                "    <name>SG%03d dive %03d</name>\n"
                % (base_opts.instrument_id, dive_num)
            )

            # To get the old behaviour, replace True with last_dive
            # dive_gps_positions[dive_num]
            printDive(
                base_opts,
                dive_nc_file_names[ii] if pq_df_c is None else pq_df_c,
                base_opts.instrument_id,
                dive_num,
                False,
                fo,
                call_time=call_time.get(dive_num - 1, None),
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
                    ballon_pairs.append(
                        ("Seaglider", "SG%03d" % base_opts.instrument_id)
                    )
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
                    if position.sms:
                        ballon_pairs.append(("ViaSMS", position.sms))
                    printDivePlacemark(
                        "SG%03d %d:%d"
                        % (
                            base_opts.instrument_id,
                            position.dive_num,
                            position.call_cycle,
                        ),
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
                except Exception:
                    DEBUG_PDB_F()
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
                    None,
                )

            # Drift track
            non_plotted_positions.append(
                surface_pos(
                    dive_gps_positions[dive_num].gps_lon_end,
                    dive_gps_positions[dive_num].gps_lat_end,
                    dive_gps_positions[dive_num].gps_time_end,
                    0,
                    0,
                    None,
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

            if dive_num + 1 in dive_gps_positions:
                non_plotted_positions.append(
                    surface_pos(
                        dive_gps_positions[dive_num + 1].gps_lon_start,
                        dive_gps_positions[dive_num + 1].gps_lat_start,
                        dive_gps_positions[dive_num + 1].gps_time_start,
                        0,
                        0,
                        None,
                    )
                )

            drift_positions = sorted(
                non_plotted_positions, key=lambda position: position.gps_fix_time
            )

            if len(drift_positions) > 1:
                fo.write("    <Placemark>\n")
                fo.write(
                    "        <name>SG%03d Drift Track %d </name>\n"
                    % (base_opts.instrument_id, dive_num)
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
                    '    <Folder id="SG%03d dive %03d">\n'
                    % (base_opts.instrument_id, dive_num)
                )
                fo.write(
                    "    <name>SG%03d dive %03d</name>\n"
                    % (base_opts.instrument_id, dive_num)
                )

                for position in non_plotted_positions:
                    try:
                        ballon_pairs = []
                        ballon_pairs.append(
                            ("Seaglider", "SG%03d" % base_opts.instrument_id)
                        )
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
                        if position.sms:
                            ballon_pairs.append(("ViaSMS", position.sms))
                        printDivePlacemark(
                            "SG%03d %d:%d"
                            % (
                                base_opts.instrument_id,
                                position.dive_num,
                                position.call_cycle,
                            ),
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
                    except Exception:
                        DEBUG_PDB_F()
                        log_error("Could not print surface position placemark", "exc")

                fo.write("    </Folder>\n")

                # Remove any positions associated with this (non-plotted) dive
                surface_positions = [
                    i for i in surface_positions if i.dive_num != dive_num
                ]

    # Close out dive folder
    fo.write("</Folder>\n")

    # Print the last known position outside the tree structure
    if last_surface_position and last_surface_position:
        try:
            ballon_pairs = []
            ballon_pairs.append(("Seaglider", "SG%03d" % base_opts.instrument_id))
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
            if last_surface_position.sms:
                ballon_pairs.append(("ViaSMS", position.sms))

            # printDivePlacemark("Last reported position SG%03d %d:%d"
            #                   % (base_opts.instrument_id, last_surface_position.dive_num, last_surface_position.call_cycle),
            printDivePlacemark(
                "SG%03d" % (base_opts.instrument_id),
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
        except Exception:
            DEBUG_PDB_F()
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

        if logfiles:
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
            except Exception:
                tgt_name = tgt_lat = tgt_lon = tgt_radius = None

        # Display targets
        targets = []
        for glob_expr in (
            "targets.[0-9]*",
            "targets.[0-9]*.[0-9]*",
        ):
            for match in glob.glob(os.path.join(base_opts.mission_dir, glob_expr)):
                targets.append(match)

        if targets and not base_opts.proposed_targets:
            targets = Utils.unique(targets)
            targets = sorted(targets, key=functools.cmp_to_key(cmp_function))
            printTargets(
                tgt_name,
                base_opts.targets == "current",
                targets[0],
                base_opts.instrument_id,
                base_opts.target_radius,
                fo,
                tgt_lon=tgt_lon,
                tgt_lat=tgt_lat,
                tgt_radius=tgt_radius,
                hide_non_active_targets=(base_opts.targets == "hide_non_active"),
            )
        else:
            target_file_name = os.path.join(base_opts.mission_dir, "targets")
            if os.path.exists(target_file_name):
                printTargets(
                    tgt_name,
                    base_opts.targets == "current",
                    target_file_name,
                    base_opts.instrument_id,
                    base_opts.target_radius,
                    fo,
                    tgt_lon=tgt_lon,
                    tgt_lat=tgt_lat,
                    tgt_radius=tgt_radius,
                )

    # Stop processing if signaled
    try:
        if (
            hasattr(base_opts, "stop_processing_event")
            and base_opts.stop_processing_event.is_set()
        ):
            log_warning(
                "Caught SIGUSR1 perviously - stopping furhter MakeKML processing"
            )
            return 1
    except AttributeError:
        pass

    # Add in the SSH file in, if it exists
    add_files = {}
    if base_opts.merge_ssh:
        ssh_file_name = os.path.join(
            base_opts.mission_dir, f"sg{base_opts.instrument_id:03d}_ssh.kmz"
        )

        if os.path.exists(ssh_file_name) and zip_kml:
            try:
                ssh_zip_file = zipfile.ZipFile(ssh_file_name, "r")
            except Exception:
                log_warning(f"Error opening {ssh_file_name} - skipping")
            else:
                with ssh_zip_file:
                    for ff in ssh_zip_file.filelist:
                        try:
                            if (
                                ff.filename
                                == f"sg{base_opts.instrument_id:03d}_ssh.kml"
                            ):
                                # This code makes some pretty hard assumptions about structure
                                # of the ssh file
                                contents = ssh_zip_file.read(ff)
                                fo.write('<Folder id="SSH">\n')
                                fo.write("<visibility>0</visibility>\n")
                                for ll in io.BytesIO(contents).readlines():
                                    ll = ll.decode()
                                    if (
                                        ll.startswith("<?xml")
                                        or ll.startswith("<kml")
                                        or ll.startswith("<Document>")
                                        or ll.startswith("</Document")
                                        or ll.startswith("</kml>")
                                    ):
                                        continue
                                    if "<Placemark>" in ll:
                                        ll = ll.replace(
                                            "<Placemark>",
                                            "<Placemark><visibility>0</visibility>",
                                        )
                                    if "<visibility>1" in ll:
                                        ll = ll.replace(
                                            "<visibility>1", "<visibility>0"
                                        )
                                    fo.write(ll)
                                    if "<Folder" in ll:
                                        fo.write("<visibility>0</visibility>\n")
                                fo.write("</Folder>\n")
                            else:
                                add_files[ff.filename] = os.path.join(
                                    base_opts.mission_dir, ff.filename
                                )
                                ssh_zip_file.extract(ff, base_opts.mission_dir)
                        except Exception:
                            log_error(f"Failed to handle {ff.filename}", "exc")

    if base_opts.add_kml:
        for f in base_opts.add_kml:
            log_info(f"processing extension {f}")
            try:
                [modname, funcname] = f.split(".")
                mod = Utils.loadmodule(modname + ".py")
                if not mod:
                    continue

                func = getattr(mod, funcname)
                add_files = add_files | func(base_opts, fo)
            except Exception as e:
                log_error(f"Failed to handle extension {f}, {e}")
                continue

    printFooter(fo)

    if base_opts.use_inmemory:
        fo.seek(0)
    else:
        fo.close()

    # Stop processing if signaled
    try:
        if (
            hasattr(base_opts, "stop_processing_event")
            and base_opts.stop_processing_event.is_set()
        ):
            log_warning(
                "Caught SIGUSR1 perviously - stopping furhter MakeKML processing"
            )
            return 1
    except AttributeError:
        pass

    # Zip the output file
    if zip_kml:
        head, _ = os.path.splitext(mission_kml_name)
        mission_kml_zip_name = head + ".kmz"
        try:
            if os.path.exists(mission_kml_zip_name):
                os.unlink(mission_kml_zip_name)
            mission_kml_zip_file = zipfile.ZipFile(
                mission_kml_zip_name, "w", zipfile.ZIP_DEFLATED
            )
            if base_opts.use_inmemory:
                mission_kml_zip_file.writestr(
                    mission_kml_file_name_base,
                    fo.read(),
                )
                fo.close()
                del fo
            else:
                mission_kml_zip_file.write(mission_kml_name, mission_kml_file_name_base)
            for k, v in add_files.items():
                mission_kml_zip_file.write(v, k)
            mission_kml_zip_file.close()
            if not base_opts.use_inmemory:
                os.remove(mission_kml_name)
        except Exception:
            if DEBUG_PDB:
                _, _, traceb = sys.exc_info()
                traceback.print_exc()
                pdb.post_mortem(traceb)
            log_error(f"Could not process {mission_kml_zip_name}", "exc")
            log_info("Bailing out...")
            return 1
        if processed_other_files is not None:
            processed_other_files.append(mission_kml_zip_name)
    else:
        if base_opts.use_inmemory:
            with open(mission_kml_name, "w") as mission_kml_file:
                mission_kml_file.write(fo.read())
        if processed_other_files is not None:
            processed_other_files.append(mission_kml_name)

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
            retval = main(None, None, [])
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
