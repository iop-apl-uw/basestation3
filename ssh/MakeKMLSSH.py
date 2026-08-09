#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2024, 2026 by University of Washington.  All rights reserved.
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


"""Routines for creating SSH KML files from aviso data"""

import argparse
import datetime
import os
import pdb
import sys
import time
import traceback
import warnings
import zipfile

import numpy as np
import scipy
from skimage import measure

with warnings.catch_warnings():
    warnings.simplefilter("ignore")
    import matplotlib

    matplotlib.use("Agg")
    matplotlib.interactive(False)
    import matplotlib.pyplot as plt
    from matplotlib.font_manager import FontProperties

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
import AvisoUtils

import BaseOpts
import BaseOptsType
import CalibConst
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = False


def islast(o):
    """Iterator wrapper that returns a boolean indicating if the items is the
    last item
    """
    it = o.__iter__()
    e = next(it)
    while True:
        try:
            nxt = next(it)
            yield (False, e)
            e = nxt
        except StopIteration:
            yield (True, e)
            break


def daterange(start_date, end_date):
    """Iterator for range of dates, both ends included"""
    for n in range(int((end_date - start_date).days) + 1):
        yield start_date + datetime.timedelta(n)


kml_color_limits = None
kml_colors = [
    "6414E7FF",
    "6414DEFF",
    "6414D5FF",
    "6414CCFF",
    "6414C3FF",
    "6414BAFF",
    "6414B1FF",
    "6414A8FF",
    "6414A0FF",
    "641497FF",
    "64148EFF",
    "641485FF",
    "64147CFF",
    "641473FF",
    "64146AFF",
    "641461FF",
    "641458FF",
    "641447FF",
    "64142CFF",
    "641411FF",
]
ssh_intervals = 0.02


def make_kml(
    data_dir,
    kml_output_dir,
    sg_plot_constants,
    instrument_id=None,
    kml_name=None,
    start_time=None,
    end_time=None,
    fetch_ssh=False,
):
    plot_constants = CalibConst.getSGCalibrationConstants(
        sg_plot_constants, suppress_required_error=True
    )

    if plot_constants is None:
        log_error(f"Failed processing {sg_plot_constants} - bailing out")
        return None

    log_info("Processing %s %s %s" % (data_dir, kml_output_dir, sg_plot_constants))
    try:
        lon_min = plot_constants["ssh_lon_min"]
        lon_max = plot_constants["ssh_lon_max"]
        lat_min = plot_constants["ssh_lat_min"]
        lat_max = plot_constants["ssh_lat_max"]
    except KeyError as e:
        log_info("Missing %s from %s - skipping" % (e, sg_plot_constants))
        return None

    if lon_min >= lon_max:
        log_warning(
            "%s ssh_lon_min %f >= ssh_lon_max %f - reversing"
            % (sg_plot_constants, lon_min, lon_max)
        )
        tmp = lon_min
        lon_min = lon_max
        lon_max = tmp
    if lat_min >= lat_max:
        log_warning(
            "%s ssh_lat_min %f >= ssh_lat_max %f - reversing"
            % (sg_plot_constants, lat_min, lat_max)
        )
        tmp = lat_min
        lat_min = lat_max
        lat_max = tmp

    log_info(
        "lon_min:%f lon_max:%f lat_min:%f lat:max%f"
        % (lon_min, lon_max, lat_min, lat_max)
    )

    # Write out the countour
    if kml_name:
        ssh_kml_name_base = kml_name
    elif instrument_id:
        ssh_kml_name_base = "sg%03d_ssh.kml" % instrument_id
    else:
        ssh_kml_name_base = "ssh.kml"
    ssh_kml_overlay_name_base = "data_overlay.png"

    ssh_kml_name = os.path.join(kml_output_dir, ssh_kml_name_base)
    ssh_kml_overlay_name = os.path.join(kml_output_dir, ssh_kml_overlay_name_base)
    ssh_kml_zip_name = ssh_kml_name.replace(".kml", ".kmz")

    try:
        fo = open(ssh_kml_name, "w")
    except Exception:
        log_error("Could not open %s" % ssh_kml_name, "exc")
        log_info("Bailing out...")
        return None

    # header
    fo.write('<?xml version="1.0" encoding="UTF-8"?>\n')
    fo.write(
        '<kml xmlns="http://www.opengis.net/kml/2.2" xmlns:gx="http://www.google.com/kml/ext/2.2" xmlns:kml="http://www.opengis.net/kml/2.2" xmlns:atom="http://www.w3.org/2005/Atom">\n'
    )
    fo.write("<Document>\n")

    if not start_time and not end_time:
        display_screenoverlay = True
        write_times = False
        start_t = datetime.datetime.today()
        end_t = datetime.datetime.today()
        fo.write("<name>SSH contours %s</name>\n" % start_t.strftime("%Y%m%d"))
    else:
        display_screenoverlay = False
        write_times = True
        if start_time:
            start_t = datetime.datetime.strptime(start_time, "%Y%m%d")
        else:
            start_t = datetime.datetime.today()

        if end_time:
            end_t = datetime.datetime.strptime(end_time, "%Y%m%d")
        else:
            end_t = datetime.datetime.today()

        fo.write(
            "<name>SSH contours %s - %s</name>\n"
            % (start_t.strftime("%Y%m%d"), end_t.strftime("%Y%m%d"))
        )

    contour_value = None

    fo.write('<Folder id="SSHContours">\n')
    fo.write("<name>SSH Contours</name>\n")

    f_last_folder_written = False
    for is_last, curr_date in islast(daterange(start_t, end_t)):
        stime = curr_date.strftime("%Y%m%d")

        # Grab the latest data
        if fetch_ssh:
            AvisoUtils.fetch_aviso_nrt(stime, data_dir)

        ret_val = AvisoUtils.read_aviso(
            stime, lon_min, lon_max, lat_min, lat_max, data_dir
        )
        if ret_val is None:
            continue
        lon, lat, ssh, u_v, v_v, f_date_line = ret_val
        if np.all(np.isnan(ssh)):
            log_warning(
                f"No ssh values for {stime}, {lon_min}, {lon_max}, {lat_min}, {lat_max} - skipping"
            )
            continue
        # Only generate this for the first contour
        if contour_value is None:
            # Countour the data
            min_val = np.floor(np.nanmin(ssh) / ssh_intervals) * ssh_intervals
            max_val = np.ceil(np.nanmax(ssh) / ssh_intervals) * ssh_intervals

            contour_value = np.linspace(
                min_val,
                max_val,
                num=int((max_val - min_val) / ssh_intervals),
                endpoint=False,
            )

            if kml_color_limits:
                color_limits = kml_color_limits
            else:
                color_limits = (
                    np.floor(np.nanmin(ssh) / ssh_intervals) * ssh_intervals,
                    np.ceil(np.nanmax(ssh) / ssh_intervals) * ssh_intervals,
                )

            contour_color = np.round(
                (contour_value - color_limits[0])
                / (color_limits[1] - color_limits[0])
                * len(kml_colors)
            )

            contour_color[contour_color < 0] = 0
            contour_color[contour_color >= len(kml_colors)] = len(kml_colors) - 1

            # print(contour_color)
            # print(kml_colors)

        for color_number in range(len(contour_color)):
            fo.write('  <Style id="c%s">\n' % contour_color[color_number])
            fo.write("    <LineStyle>\n")
            fo.write(
                "      <color>%s</color>" % kml_colors[int(contour_color[color_number])]
            )
            fo.write("      <width>1</width>")
            fo.write("    </LineStyle>\n")
            fo.write("  </Style>\n")
            fo.write('  <Style id="cc%s">\n' % contour_color[color_number])
            fo.write("    <LineStyle>\n")
            fo.write(
                "      <color>%s</color>" % kml_colors[int(contour_color[color_number])]
            )
            fo.write("      <width>2</width>")
            fo.write("    </LineStyle>\n")
            fo.write("  </Style>\n")

        n_lon, n_lat = np.shape(ssh)
        f_lon = scipy.interpolate.interp1d(np.arange(n_lon), lon, kind="linear")
        f_lat = scipy.interpolate.interp1d(np.arange(n_lat), lat, kind="linear")

        for ci in range(len(contour_value)):
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                # From https://stackoverflow.com/questions/5666056/matplotlib-extracting-data-from-contour-lines
                # Alternative with scikit-image https://scikit-image.org/docs/dev/auto_examples/edges/plot_contours.html
                try:
                    # cs = plt.contour(
                    #     lon,
                    #     lat,
                    #     ssh.transpose(),
                    #     (contour_value[ci],),
                    # )
                    contours = measure.find_contours(ssh.transpose(), contour_value[ci])
                except TypeError:
                    log_error("Failed for %s:%f" % (stime, contour_value[ci]))
                    continue
                else:
                    log_debug("Success for %s:%f" % (stime, contour_value[ci]))
            #            for path in cs.collections[0].get_paths():
            #                c_lon = path.vertices[:, 0]
            #                # Deal with shifted lon to handle dateline
            #                c_lon[np.squeeze(np.nonzero(c_lon < -180.0))] += 360.0
            #                c_lat = path.vertices[:, 1]
            for contour in contours:
                c_lon = f_lon(contour[:, 1])
                # Deal with shifted lon to handle dateline
                c_lon[np.squeeze(np.nonzero(c_lon < -180.0))] += 360.0
                c_lat = f_lat(contour[:, 0])
                fo.write("  <Placemark>\n")
                # thick contours
                if np.remainder(contour_value[ci], 0.5) == 0:
                    fo.write("   <styleUrl>#cc%s</styleUrl>\n" % contour_color[ci])
                else:
                    fo.write("   <styleUrl>#c%s</styleUrl>\n" % contour_color[ci])

                fo.write("   <LineString>\n")
                fo.write("    <coordinates>\n")
                for kk in range(len(c_lon)):
                    fo.write("     %.4f,%.4f\n" % (c_lon[kk], c_lat[kk]))
                fo.write("    </coordinates>\n")
                fo.write("   </LineString>\n")
                # Place time range here
                if write_times:
                    st = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(
                            time.mktime(time.strptime(stime, "%Y%m%d")) - (12 * 3600)
                        ),
                    )
                    et = time.strftime(
                        "%Y-%m-%dT%H:%M:%SZ",
                        time.gmtime(
                            time.mktime(time.strptime(stime, "%Y%m%d")) + (12 * 3600)
                        ),
                    )
                    fo.write(
                        "        <TimeSpan><begin>%s</begin><end>%s</end></TimeSpan>\n"
                        % (st, et)
                    )
                    # <begin>2019-03-31T12:00:00</begin>
                    # <end>2019-04-01T12:00:00</end>
                fo.write("  </Placemark>\n")

        if is_last:
            f_last_folder_written = True
            fo.write("</Folder>\n")
            id_cnt = 0
            color = "7fffffff"
            legand_color = "7fff0000"

            def scaled_vel(velocity):
                if velocity > 0.5:
                    return 2.0
                else:
                    return velocity * 2.0 / 0.5

            fo.write('<Folder id="SSHVectors">\n')
            fo.write("<name>SSH Vectors</name>")
            start_i = 0
            for ii in range(len(lon)):
                start_i += 1
                for jj in range(start_i % 2, len(lat), 2):
                    ## Note - this code assumes a masked array as returned by netCDF4
                    # if u_v.mask[ii, jj] or v_v.mask[ii, jj]:
                    #    continue
                    if np.isnan(u_v[ii, jj]) or np.isnan(v_v[ii, jj]):
                        continue
                    velocity = np.sqrt(
                        u_v[ii, jj] * u_v[ii, jj] + v_v[ii, jj] * v_v[ii, jj]
                    )
                    try:
                        polar_rad = np.arctan2(v_v[ii, jj], u_v[ii, jj])
                        direction_deg = 90.0 - np.degrees(polar_rad)
                    except ZeroDivisionError:  # atan2
                        direction_deg = 0.0
                    if direction_deg < 0:
                        direction_deg = direction_deg + 360.0

                    # print(lon[ii],lat[jj],u_v[ii,jj],v_v[ii,jj], velocity, direction_deg)
                    fo.write(
                        '  <Style id="vel_%d"><IconStyle><Icon><href>arrow_narrow.png</href></Icon><heading>%.0f</heading><scale>%.1f</scale><color>%s</color></IconStyle></Style>\n'
                        % (id_cnt, direction_deg[0], scaled_vel(velocity[0]), color)
                    )
                    # fo.write("    <Placemark><styleUrl>#vel_%d</styleUrl><Point><coordinates>%.4f,%.4f,0</coordinates></Point>" % (id_cnt, lon[ii], lat[jj]))
                    fo.write(
                        "    <Placemark><styleUrl>#vel_%d</styleUrl><Point><coordinates>%.4f,%.4f,0</coordinates></Point>"
                        % (
                            id_cnt,
                            # lon[ii] if lon[ii] > 0.0 else lon[ii] + 360.0,
                            lon[ii] if lon[ii] > -180.0 else lon[ii] + 360.0,
                            lat[jj],
                        )
                    )
                    if write_times:
                        st = time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(
                                time.mktime(time.strptime(stime, "%Y%m%d"))
                                - (12 * 3600)
                            ),
                        )
                        et = time.strftime(
                            "%Y-%m-%dT%H:%M:%SZ",
                            time.gmtime(
                                time.mktime(time.strptime(stime, "%Y%m%d"))
                                + (12 * 3600)
                            ),
                        )
                        fo.write(
                            "<TimeSpan><begin>%s</begin><end>%s</end></TimeSpan>\n"
                            % (st, et)
                        )
                    fo.write("</Placemark>\n")

                    id_cnt += 1

            # Legand Vector
            fo.write(
                '  <Style id="vel_%d"><IconStyle><Icon><href>arrow_narrow.png</href></Icon><heading>%.0f</heading><scale>%.1f</scale><color>%s</color></IconStyle></Style>\n'
                % (id_cnt, 90.0, scaled_vel(0.5), legand_color)
            )
            # fo.write("    <Placemark><styleUrl>#vel_%d</styleUrl><name>0.5 m/s</name><Point><coordinates>%.4f,%.4f,0</coordinates></Point>"% (id_cnt, lon[0], lat[0]))
            fo.write(
                "    <Placemark><styleUrl>#vel_%d</styleUrl><name>0.5 m/s</name><Point><coordinates>%.4f,%.4f,0</coordinates></Point>"
                # % (id_cnt, lon[ii] if lon[ii] > 0.0 else lon[ii] + 360.0, lat[0])
                % (id_cnt, lon[ii] if lon[ii] > -180.0 else lon[ii] + 360.0, lat[0])
            )
            if write_times:
                st = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(
                        time.mktime(time.strptime(stime, "%Y%m%d")) - (12 * 3600)
                    ),
                )
                et = time.strftime(
                    "%Y-%m-%dT%H:%M:%SZ",
                    time.gmtime(
                        time.mktime(time.strptime(stime, "%Y%m%d")) + (12 * 3600)
                    ),
                )
                fo.write(
                    "<TimeSpan><begin>%s</begin><end>%s</end></TimeSpan>\n" % (st, et)
                )
            fo.write("</Placemark>\n")
            fo.write("</Folder>\n")

    if not f_last_folder_written:
        fo.write("</Folder>\n")

    if display_screenoverlay:
        # Screen overlay for ssh data
        fo.write("<ScreenOverlay>\n")
        fo.write(
            "    <name>Absolute Positioning: Bottom left</name><visibility>1</visibility><color>6bffffff</color><Icon><href>%s</href></Icon>\n"
            % ssh_kml_overlay_name_base
        )
        fo.write('    <overlayXY x="0" y="-1" xunits="fraction" yunits="fraction"/>\n')
        fo.write('    <screenXY x="0" y="0" xunits="fraction" yunits="fraction"/>\n')
        fo.write('    <rotationXY x="0" y="0" xunits="fraction" yunits="fraction"/>\n')
        fo.write('    <size x="0" y="0" xunits="fraction" yunits="fraction"/>\n')
        fo.write("  </ScreenOverlay>\n")

    fo.write("</Document>\n")
    fo.write("</kml>\n")
    fo.close()

    if display_screenoverlay:
        # Overlay jpg
        plt.figure(figsize=(2.0, 0.3), dpi=100)
        font = FontProperties(size="small")
        plt.figtext(
            0.5,
            0.5,
            "Aviso Data Time:%s" % stime,
            fontproperties=font,
            horizontalalignment="center",
            verticalalignment="center",
        )
        plt.savefig(ssh_kml_overlay_name, dpi=100)

    if os.path.exists(ssh_kml_zip_name):
        os.remove(ssh_kml_zip_name)

    ssh_kml_zip_file = zipfile.ZipFile(ssh_kml_zip_name, "w", zipfile.ZIP_DEFLATED)
    ssh_kml_zip_file.write(ssh_kml_name, ssh_kml_name_base)
    # head, _ = os.path.split(sys.argv[0])
    ssh_kml_zip_file.write(
        os.path.join(data_dir, "arrow_narrow.png"),
        "arrow_narrow.png",
    )
    if display_screenoverlay:
        ssh_kml_zip_file.write(ssh_kml_overlay_name, "%s" % ssh_kml_overlay_name_base)
    ssh_kml_zip_file.close()
    os.remove(ssh_kml_name)
    if display_screenoverlay:
        os.remove(ssh_kml_overlay_name)

    return ssh_kml_zip_name


def main(instrument_id=None, base_opts=None):
    """Command line app for creating kml/kmz files of ssh contours

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(
            "Command line app for creating kml/kmz files of ssh contours",
            additional_arguments={
                "fetch_ssh": BaseOptsType.options_t(
                    False,
                    ("MakeKMLSSH",),
                    ("--fetch_ssh",),
                    bool,
                    {
                        "help": "Fetch the most recent ssh data",
                        "action": argparse.BooleanOptionalAction,
                    },
                ),
                "data_dir": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSH",),
                    ("data_dir",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Location of Aviso data",
                    },
                ),
                "kml_output_dir": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSH",),
                    ("kml_output_dir",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Location to put generated kml files",
                    },
                ),
                "plot_constants": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSH",),
                    ("plot_constants",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Location for the plot constants file",
                    },
                ),
                "kml_file_name": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSH",),
                    ("kml_file_name",),
                    str,
                    {
                        "help": "Name of the output KML file",
                        "nargs": "?",
                    },
                ),
                "start_time": BaseOptsType.options_t(
                    None,
                    ("MakeKMLSSH",),
                    ("start_time",),
                    str,
                    {
                        "help": "Earliest accepted data",
                        "nargs": "?",
                    },
                ),
            },
        )

    BaseLogger(base_opts, include_time=True)

    processing_start_time = time.time()

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if not os.path.exists(base_opts.plot_constants):
        log_error(f"{base_opts.plot_constants} does not exist")
        return 1

    make_kml(
        base_opts.data_dir,
        base_opts.kml_output_dir,
        base_opts.plot_constants,
        instrument_id=instrument_id,
        kml_name=base_opts.kml_file_name,
        start_time=base_opts.start_time,
        fetch_ssh=base_opts.fetch_ssh,
    )

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
        retval = main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
