#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2020, 2021, 2022, 2024, 2025 by University of Washington.  All rights reserved.
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
TMICL basestation sensor extension
"""

# Add time column to processed .eng file
# Add other eng files to netCDF - and deal with the overlap in time vectors, or duplicate them

import array as arr
import collections
import math
import os
import re

import numpy as np

import BaseNetCDF
import FileMgr
import Utils
from BaseLog import log_debug, log_error, log_info, log_warning

# Globals
tmicl_prefix = "tm"


def calc_center_freqs(rate, nfft, logmap):
    """Returns a list of center frequencies, based on the
    rate, nfft and logmap
    """
    if rate is None or nfft is None or logmap is None:
        return None
    if len(logmap.rstrip()) == 0:
        return None
    rate = float(rate)
    nfft = float(nfft)
    nfreqs = int(nfft / 2.0)
    freqs = np.linspace(rate / nfft, rate / 2.0, num=nfreqs)
    buckets = logmap.split(",")
    center_freqs = np.zeros(len(buckets), np.float64)
    for j in range(len(buckets)):
        a, b = buckets[j].split("-")
        a = int(a)
        b = int(b)
        total = count = 0.0
        for i in range(a, b + 1):
            total += freqs[i]
            count += 1
        center_freqs[j] = total / count
    return center_freqs


def init_logger(module_name, init_dict=None):
    """
    init_logger

    Returns:
        -1 - error in processing
        0 - success (data found and processed)
    """

    if init_dict is None:
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    init_dict[module_name] = {
        "logger_prefix": tmicl_prefix,
        "strip_files": True,
        "eng_file_reader": eng_file_reader,
        "known_files": ["tmicl.cnf"],
        "netcdf_metadata_adds": {
            "log_TM_RECORDABOVE": [
                False,
                "d",
                {
                    "description": "Depth above above which data is recorded",
                    "units": "meters",
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_PROFILE": [
                False,
                "d",
                {
                    "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_XMITPROFILE": [
                False,
                "d",
                {
                    "description": "Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_LOGSAMPLE": [
                False,
                "d",
                {
                    "description": "Interrogate tmicl each glider sample for the most recent reading."
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_XMITRAW": [
                False,
                "d",
                {
                    "description": "Which part of the dive data to transmit - 0 none, 1 dive, 2 climb, 3 both."
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_FREEKB": [
                False,
                "d",
                {"description": "Free diskspace on TMICL, in kBytes"},
                BaseNetCDF.nc_scalar,
            ],
            "log_TM_NDIVE": [
                False,
                "d",
                {"description": "Dive multiplier for TMICL"},
                BaseNetCDF.nc_scalar,
            ],
            # From here down are per channel
            # ch 0
            "tmicl_nfft_ch0": [
                False,
                "i",
                {"description": "Size of FFT"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_navg_ch0": [
                False,
                "i",
                {"description": "Number of overlapping FFTs averaged"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_osc_ch0": [
                False,
                "i",
                {"description": "Oscillator setting"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_nlog_ch0": [
                False,
                "i",
                {"description": "Number of log averaged spectra bins"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_logmap_ch0": [
                False,
                "c",
                {
                    "description": "Array describing the mapping from frequency to log averaged"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_container_ch0": [
                False,
                "c",
                {"description": "Name of the containing directory"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_comment_ch0": [
                False,
                "c",
                {"description": "Comment field"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_despikethreshold_ch0": [
                False,
                "d",
                {
                    "description": "Threshold (in stddev) for the despiker to work on the raw signal"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_noiseintersect_ch0": [
                False,
                "d",
                {"description": "Y-intersect of the noise cutoff"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_noiseslope_ch0": [
                False,
                "d",
                {"description": "Slope of the noise cutoff"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_fmin_ch0": [
                False,
                "d",
                {"description": "Frequency cut off for integration"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_GD_ch0": [False, "d", {"description": "Gain"}, BaseNetCDF.nc_scalar],
            "tmicl_S_ch0": [
                False,
                "d",
                {"description": "Shear sensitivity"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_channels_ch0": [
                False,
                "i",
                {
                    "description": "Channel map - 1 channel 1, 2 channel 2, 3 channel 0 and 1"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_serialnum_ch0": [
                False,
                "c",
                {"description": "serial number of tmicl board"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_samplerate_ch0": [
                False,
                "i",
                {"description": "Per channel sample requested rate in Hz"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_effectivesamplerate_ch0": [
                False,
                "d",
                {"description": "Per channel sample effective rate in Hz"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_motordroppedblocks_ch0": [
                False,
                "i",
                {"description": "Number of blocks dropped due to motor moves"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_goodblocks_ch0": [
                False,
                "i",
                {"description": "Number of good blocks"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_totaldespike_ch0": [
                False,
                "i",
                {"description": "Total number of samples despiked"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_samplesprocessed_ch0": [
                False,
                "i",
                {
                    "description": "Total number of samples processed (always a multiple of nfft/2)"
                },
                BaseNetCDF.nc_scalar,
            ],
            # ch1
            "tmicl_nfft_ch1": [
                False,
                "i",
                {"description": "Size of FFT"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_navg_ch1": [
                False,
                "i",
                {"description": "Number of overlapping FFTs averaged"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_osc_ch1": [
                False,
                "i",
                {"description": "Oscillator setting"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_nlog_ch1": [
                False,
                "i",
                {"description": "Number of log averaged spectra bins"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_logmap_ch1": [
                False,
                "c",
                {
                    "description": "Array describing the mapping from frequency to log averaged"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_container_ch1": [
                False,
                "c",
                {"description": "Name of the containing directory"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_comment_ch1": [
                False,
                "c",
                {"description": "Comment field"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_despikethreshold_ch1": [
                False,
                "d",
                {
                    "description": "Threshold (in stddev) for the despiker to work on the raw signal"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_noiseintersect_ch1": [
                False,
                "d",
                {"description": "Y-intersect of the noise cutoff"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_noiseslope_ch1": [
                False,
                "d",
                {"description": "Slope of the noise cutoff"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_fmin_ch1": [
                False,
                "d",
                {"description": "Frequency cut off for integration"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_GD_ch1": [False, "d", {"description": "Gain"}, BaseNetCDF.nc_scalar],
            "tmicl_S_ch1": [
                False,
                "d",
                {"description": "Shear sensitivity"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_channels_ch1": [
                False,
                "i",
                {
                    "description": "Channel map - 1 channel 1, 2 channel 2, 3 channel 0 and 1"
                },
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_serialnum_ch1": [
                False,
                "c",
                {"description": "serial number of tmicl board"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_samplerate_ch1": [
                False,
                "i",
                {"description": "Per channel sample requested rate in Hz"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_effectivesamplerate_ch1": [
                False,
                "d",
                {"description": "Per channel sample effective rate in Hz"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_motordroppedblocks_ch1": [
                False,
                "i",
                {"description": "Number of blocks dropped due to motor moves"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_goodblocks_ch1": [
                False,
                "i",
                {"description": "Number of good blocks"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_totaldespike_ch1": [
                False,
                "i",
                {"description": "Total number of samples despiked"},
                BaseNetCDF.nc_scalar,
            ],
            "tmicl_samplesprocessed_ch1": [
                False,
                "i",
                {
                    "description": "Total number of samples processed (always a multiple of nfft/2)"
                },
                BaseNetCDF.nc_scalar,
            ],
        },
    }

    for name in ("temp", "shear", "temp0", "temp1", "ch0", "ch1"):
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_nfft_%s" % name] = [
            False,
            "i",
            {"description": "Size of FFT"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_navg_%s" % name] = [
            False,
            "i",
            {"description": "Number of overlapping FFTs averaged"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_osc_%s" % name] = [
            False,
            "i",
            {"description": "Oscillator setting"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_nlog_%s" % name] = [
            False,
            "i",
            {"description": "Number of log averaged spectra bins"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_logmap_%s" % name] = [
            False,
            "c",
            {
                "description": "Array describing the mapping from frequency to log averaged"
            },
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_container_%s" % name] = [
            False,
            "c",
            {"description": "Name of the containing directory"},
            BaseNetCDF.nc_scalar,
        ]
        # Don't change this format with adjusting the code below
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_comment0_%s" % name] = [
            False,
            "c",
            {"description": "Comment field"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_comment1_%s" % name] = [
            False,
            "c",
            {"description": "Comment field"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_comment2_%s" % name] = [
            False,
            "c",
            {"description": "Comment field"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_comment3_%s" % name] = [
            False,
            "c",
            {"description": "Comment field"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"][
            "tmicl_despikethreshold_%s" % name
        ] = [
            False,
            "d",
            {
                "description": "Threshold (in stddev) for the despiker to work on the raw signal"
            },
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"][
            "tmicl_noiseintersect_%s" % name
        ] = [
            False,
            "d",
            {"description": "Y-intersect of the noise cutoff"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_noiseslope_%s" % name] = [
            False,
            "d",
            {"description": "Slope of the noise cutoff"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_fmin_%s" % name] = [
            False,
            "d",
            {"description": "Frequency cut off for integration"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_GD_%s" % name] = [
            False,
            "d",
            {"description": "Gain"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_S_%s" % name] = [
            False,
            "d",
            {"description": "Shear sensitivity"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_channels_%s" % name] = [
            False,
            "i",
            {
                "description": "Channel map - 1 channel 1, 2 channel 2, 3 channel 0 and 1"
            },
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_serialnum_%s" % name] = [
            False,
            "c",
            {"description": "serial number of tmicl board"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"]["tmicl_samplerate_%s" % name] = [
            False,
            "i",
            {"description": "Per channel sample requested rate in Hz"},
            BaseNetCDF.nc_scalar,
        ]
        init_dict[module_name]["netcdf_metadata_adds"][
            "tmicl_effectivesamplerate_%s" % name
        ] = [
            False,
            "d",
            {"description": "Per channel sample effective rate in Hz"},
            BaseNetCDF.nc_scalar,
        ]

    # Predeclare the possible dimensions for non-base files
    for ec in ("logavg", "dvdt", "specavg"):
        for ch in ("ch0", "ch1", "temp", "shear", "temp0", "temp1"):
            for cast, descr in FileMgr.cast_descr:
                row_dim = "tmicl_%s_%s_%s_row" % (ec, ch, cast)
                row_info = "%s_info" % row_dim
                col_dim = "tmicl_%s_%s_%s_col" % (ec, ch, cast)
                col_info = "%s_info" % col_dim
                var_dim = "tmicl_%s_%s_%s" % (ec, ch, cast)
                description = "Tmicl %s %s %s" % (ec, ch, f"{descr} profile")
                BaseNetCDF.register_sensor_dim_info(
                    row_info, row_dim, None, True, None
                )  # CONSIDER True -> 'microstructure'
                BaseNetCDF.register_sensor_dim_info(
                    col_info, col_dim, None, True, None
                )  # CONSIDER True -> 'microstructure'
                init_dict[module_name]["netcdf_metadata_adds"][var_dim] = (
                    BaseNetCDF.form_nc_metadata(
                        None,
                        False,
                        "d",
                        {"description": description},
                        (
                            row_info,
                            col_info,
                        ),
                    )
                )
    return 0


# pylint: disable=unused-argument
def process_tar_members(
    base_opts,
    module_name,
    fc,
    tmicl_file_list,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes files uploaded in the tarball, converting them to .eng files
    Practically, this is a rename, unless the files is in binary, in which case it is a conversion

    Returns:
    0 for success
    1 for error
    """
    column_pattern = r"(?P<name>.*?)\((?P<scale>[-\d\.]*?),(?P<offset>[-\d\.]*?)\)"
    scaleoff_pattern = r"\((?P<scale>[-\d\.]*?),(?P<offset>[-\d\.]*?)\)"
    ret_val = 0

    base_name = None

    for tmicl_file in tmicl_file_list:
        if base_name is None:
            head, tail = os.path.split(tmicl_file)
            base_name = "%s/p%s%03d%04d%s" % (
                head,
                tmicl_prefix,
                fc.instrument_id(),
                fc.dive_number(),
                fc.up_down_data(),
            )
            log_debug("Processing data for %s" % base_name)

        try:
            head, tail = os.path.splitext(tmicl_file)
            if tail.lower() == ".eng":
                _, tail = os.path.split(tmicl_file)
                head, tail = os.path.splitext(tail)
                splits = head.split("_")
                # Name format = base_name, class (base, logavg, dvdt, motors), instance (channel)
                if len(splits) < 3:
                    output_file = "%s_base_%s.eng" % (base_name, splits[1])
                    class_name = "base"
                else:
                    output_file = "%s_%s_%s.eng" % (base_name, splits[2], splits[1])
                    class_name = splits[2]

                ef, _ = extract_file_metadata(tmicl_file, splits[1])

                # 2021/12/30 Bug - motor files have no column header
                if class_name == "motors" and "columns" not in ef:
                    ef["columns"] = "onoff sample"

                log_debug("Output file %s" % output_file)

                ed = extract_file_data(tmicl_file)
                # print(ed)
                if ef is None or ed is None:
                    log_error("Could not process %s - skipping" % (tmicl_file))
                    continue

                # At this point, columns may be scaled and/or offset - correct that
                if (
                    os.path.split(output_file)[1].split("_")[1] in ("base",)
                    and "columns" in ef
                ):
                    scale_off = []
                    columns = ""
                    prev_val = []
                    # Look for scale and offset in header
                    for col in ef["columns"].split():
                        values = re.search(column_pattern, col)
                        if values and len(values.groupdict()) == 3:
                            v = values.groupdict()
                            scale_off.append((float(v["scale"]), float(v["offset"])))
                            columns = "%s %s" % (columns, v["name"])
                            prev_val.append(np.nan)
                    ef["columns"] = columns
                    if len(scale_off) > 0 and int(ef["binaryoutput"]) == 0:
                        for row in range(np.shape(ed)[1]):
                            # log_info("pre_val: %s" % prev_val)
                            for col in range(np.shape(ed)[0]):
                                if np.isnan(prev_val[col]):
                                    prev_val[col] = ed[col][row]
                                else:
                                    prev_val[col] = ed[col][row] = (
                                        prev_val[col] + ed[col][row]
                                    )
                                ed[col][row] = (
                                    ed[col][row] / scale_off[col][0] + scale_off[col][1]
                                )
                                if ef["columns"].split()[col] == "sigvarlog10":
                                    ed[col][row] = pow(10.0, ed[col][row])
                    ef["columns"] = ef["columns"].replace("sigvarlog10", "sigvar")

                elif (
                    os.path.split(output_file)[1].split("_")[1] == "logavg"
                    and "scaleoff" in ef
                ):
                    log_info("Scaling output")
                    values = re.search(scaleoff_pattern, ef["scaleoff"])
                    scale_off = None
                    if values and len(values.groupdict()) == 2:
                        v = values.groupdict()
                        scale_off = (float(v["scale"]), float(v["offset"]))
                        for row in range(np.shape(ed)[1]):
                            for col in range(np.shape(ed)[0]):
                                tmp = float(ed[col][row]) / scale_off[0] + scale_off[1]
                                # sys.stdout.write("%d (%f) (%g)" % (ed[col][row], tmp, pow(10.0, tmp)))
                                ed[col][row] = pow(10.0, tmp)
                            # sys.stdout.write("\n" % ed[col][row])
                    del ef["scaleoff"]

                # print(ed)
                try:
                    fo = open(output_file, "w")
                except OSError:
                    log_error(
                        "Could not open %s for output - skipping %s"
                        % (output_file, tmicl_file),
                        "exc",
                    )
                    ret_val = 1
                    continue
                if "binaryoutput" in ef:
                    ef["binaryoutput"] = 0
                # Add time column
                if "columns" in ef:
                    ef["columns"] = "%s %s" % ("time", ef["columns"])

                ## NYI                if(ef['channels'] == 1 or ef['channels'] == 2 and 'effectivesamplerate' not in ef):
                ## NYI                    # Try to map common settings
                ## NYI                    if(ef['samplerate'] == 400):
                ## NYI                        ef['effectivesamplerate'] = 393.5
                ## NYI                    elif(ef['samplerate'] == 300):
                ## NYI                        ef['effectivesamplerate'] = 297.6
                ## NYI                    elif(ef['samplerate'] == 200):
                ## NYI                        ef['effectivesamplerate'] = 198.41

                # Hack to deal with common case of setting sample rate, but not setting effectivesamplerate
                if "effectivesamplerate" in ef and (
                    float(ef["samplerate"]) == 400
                    and float(ef["effectivesamplerate"]) == 98
                ):
                    log_warning(
                        "Samplerate = %f, Effectivesamplerate = %f - looks wrong to me, using Effectivesamplerate = %f instead"
                        % (ef["samplerate"], ef["effectivesamplerate"], 393.085)
                    )
                    ef["effectivesamplerate"] = 393.085

                write_file_header(ef, fo)

                if "effectivesamplerate" in ef:
                    rate = ef["effectivesamplerate"]
                else:
                    rate = float(ef["samplerate"])

                log_debug(
                    "samplerate %.3f, effectivesamplerate %.3f"
                    % (ef["samplerate"], rate)
                )

                time_step = float(ef["nfft"]) * float(ef["navg"]) / rate
                # start time
                t = ef["start"] + (
                    float(ef["nfft"]) * (float(ef["navg"]) / 2.0 + 0.5) / rate
                )
                log_debug(
                    "Nfft:%d, Navg:%d Start:%.3f, time_step:%.3f, steps:%d, Integration:%.3f, Stop:%.3f"
                    % (
                        ef["nfft"],
                        ef["navg"],
                        ef["start"],
                        time_step,
                        np.shape(ed)[1],
                        t + np.shape(ed)[1] * time_step,
                        ef["stop"],
                    )
                )
                for row in range(np.shape(ed)[1]):
                    if class_name == "motors":
                        # Motor files calculate time based on sample number
                        motor_t = ef["start"] + (
                            ed[ef["columns"].split().index("sample") - 1][row] / rate
                        )
                        fo.write("%.3f " % motor_t)
                    else:
                        fo.write("%.3f " % t)
                    t = t + time_step
                    for col in range(np.shape(ed)[0]):
                        if class_name in ("motors", "base"):
                            fo.write("%d " % ed[col][row])
                        else:
                            fo.write("%g " % ed[col][row])
                    fo.write("\n")

                if "stop" in ef:
                    fo.write("%%stop: %s\n" % Utils.format_time(ef["stop"]))
                    if t - time_step > ef["stop"]:
                        log_error(
                            "Last time %.3f greater then stop time %.3f (%.3f sec diff) in %s"
                            % (
                                t - time_step,
                                ef["stop"],
                                t - time_step - ef["stop"],
                                base_name,
                            )
                        )
                fo.close()
                processed_logger_eng_files.append(output_file)
        except Exception:
            log_error("Failed to process %s" % tmicl_file, "exc")
            ret_val = 1

    return ret_val


def extract_file_metadata(inp_file_name, channel):
    """
    Extracts the meta data from a dat file
    Returns:
    None - failure
    Dictionary of meta data
    """
    try:
        inp_file = open(inp_file_name, "rb")
    except Exception:
        log_error("Unable to open %s" % inp_file_name)
        return None

    eng_file_meta = collections.OrderedDict()

    ret_list = []

    line_count = 0
    for raw_line in inp_file:
        line_count += 1
        try:
            raw_line = raw_line.decode("utf-8")
        except UnicodeDecodeError:
            log_debug(f"Could not decode {inp_file_name} line {line_count} - skipping")
            continue
        if raw_line[0] == "%":
            raw_strs = raw_line.split(":", 1)
            raw_strs[0] = raw_strs[0].replace("% ", "%")
            if raw_strs[0] == "%columns":
                eng_file_meta["columns"] = raw_strs[1].rstrip().lstrip()
                continue
            elif raw_strs[0] == "%logmap":
                logmap = raw_strs[1].rstrip().lstrip()
                # Fix for broken log map writer in tmicl of the form
                # %logmap: 0-0,1-1,2-2,3-5,6-10,11-17,18-29,30-49,50-83,84-138,139-231,232-385386-511
                split_lm = logmap.split(",")
                if len(split_lm[-1].split("-")) > 2:
                    # Trim the end
                    right = logmap.rindex("-")
                    left = logmap.rindex("-", 0, right) + 1
                    new_end = left + int(np.floor(float(right - left) / 2.0))
                    new_logmap = logmap[:new_end]
                    log_info("Changing logmap from %s to %s" % (logmap, new_logmap))
                    logmap = new_logmap

                eng_file_meta["logmap"] = logmap
                ret_list.append(("tmicl_logmap_%s" % channel, eng_file_meta["logmap"]))
                continue
            elif raw_strs[0] == "%start":
                eng_file_meta["start"] = Utils.parse_time(raw_strs[1])
            elif raw_strs[0] == "%stop":
                eng_file_meta["stop"] = Utils.parse_time(raw_strs[1])
                continue
            elif raw_strs[0] == "%comment":
                comment_list = []
                for vv in ret_list:
                    if "comment" in vv[0]:
                        comment_list.append(vv[0])
                comment_num = -1
                if comment_list:
                    comment_list.sort()
                    comment_num = int(comment_list[-1][13:14])
                comment_num += 1
                comment_name = "tmicl_comment%d_%s" % (comment_num, channel)
                eng_file_meta[comment_name] = raw_strs[1].rstrip().lstrip()
                ret_list.append((comment_name, eng_file_meta[comment_name]))
                continue
            else:
                # Comments from processed files
                class MultiBreak(Exception):
                    """Break out from nested loops"""

                try:
                    for ii in range(4):
                        for tt in ("temp", "shear", "temp0", "temp1"):
                            comment_name = "tmicl_comment%s_%s" % (ii, tt)
                            if raw_strs[0] == "%%%s" % (comment_name):
                                eng_file_meta[comment_name] = (
                                    raw_strs[1].rstrip().lstrip()
                                )
                                ret_list.append(
                                    (comment_name, eng_file_meta[comment_name])
                                )
                                raise MultiBreak
                except MultiBreak:
                    continue

                # string values
                for i in ("container", "scaleoff", "serialnum"):
                    if raw_strs[0] == "%%%s" % (i):
                        eng_file_meta[i] = raw_strs[1].rstrip().lstrip()
                        ret_list.append(
                            ("tmicl_%s_%s" % (i, channel), eng_file_meta[i])
                        )
                        continue
                # Int values
                for i in (
                    "binaryoutput",
                    "osc",
                    "nfft",
                    "navg",
                    "channels",
                    "samplerate",
                    "nlog",
                ):
                    if raw_strs[0] == "%%%s" % (i):
                        eng_file_meta[i] = int(raw_strs[1].rstrip().lstrip())
                        if i != "binaryoutput":
                            ret_list.append(
                                ("tmicl_%s_%s" % (i, channel), eng_file_meta[i])
                            )
                        continue
                # float values
                for i in (
                    "noiseintersect",
                    "noiseslope",
                    "fmin",
                    "GD",
                    "S",
                    "effectivesamplerate",
                    "despikethreshold",
                ):
                    if raw_strs[0] == "%%%s" % (i):
                        try:
                            eng_file_meta[i] = float(raw_strs[1].rstrip().lstrip())
                            ret_list.append(
                                ("tmicl_%s_%s" % (i, channel), eng_file_meta[i])
                            )
                        except Exception:
                            log_error(
                                "Could not process %s %s %s"
                                % (inp_file_name, raw_strs[0], raw_strs[1]),
                                "exc",
                            )
                        continue

    return (eng_file_meta, ret_list)


def write_file_header(ef, fo):
    """Writes out header block to eng file"""
    for i in list(ef.keys()):
        if i in ("start", "stop"):
            continue
        fo.write("%%%s: %s\n" % (i, ef[i]))

    if "start" in ef:
        fo.write("%%start: %s\n" % Utils.format_time(ef["start"]))

    return None


def extract_file_data(inp_file_name):
    """
    Reads the data/eng file and returns columns of data

    Returns:
    None - error
    List of data vectors - success
    """
    try:
        inp_file = open(inp_file_name, "rb")
    except Exception:
        log_error("Unable to open %s" % inp_file_name)
        return None

    buffer = inp_file.read()
    inp_file.close()

    # Figure out what type of engfile
    _, tail = os.path.split(inp_file_name)
    head, _ = os.path.splitext(tail)

    s = head.split("_")
    if len(s) < 3:
        eng_file_class = "base"
    else:
        eng_file_class = s[2]

    rows = []
    binaryoutput = False
    nlog = 0
    scaleoff = False
    columns = []
    line_count = 0

    # Process the data
    for inp_line in buffer.splitlines():
        line_count += 1
        try:
            inp_line = inp_line.decode("utf-8")
        except UnicodeDecodeError:
            # Lots of reasons for this - mixed binary and text files a leading cause
            log_debug(f"Could not decode {inp_file_name} line {line_count} - skipping")
            continue
        inp_line = inp_line.rstrip().rstrip()
        if inp_line == "":
            continue
        elif inp_line[0] == "%":
            # All comments here
            raw_strs = inp_line.split(":", 1)
            if raw_strs[0] == "%binaryoutput":
                binaryoutput = bool(int(raw_strs[1].rstrip().lstrip()))
                # 2016/07/20 Bug - motor files being stamped as binary
                if eng_file_class in ("motors", "base"):
                    binaryoutput = False
            elif raw_strs[0] == "%columns":
                columns = raw_strs[1].split()
            elif raw_strs[0] == "%nlog":
                nlog = int(raw_strs[1].rstrip().lstrip())
            elif (raw_strs[0] == "%logmap") and (nlog == 0):
                nlog = len(raw_strs[1].split(","))
                # log_info("nlog from logmap %d" % nlog)
            elif raw_strs[0] == "%scaleoff":
                scaleoff = True
            elif (raw_strs[0] == "%start") and binaryoutput:
                # Binary - handled this below
                break
            continue

        # Data line
        raw_strs = inp_line.split()
        row = []
        for i in range(len(raw_strs)):
            try:
                row.append(np.float64(raw_strs[i]))
            except Exception:
                log_error(
                    "Problems converting [%s] to float from line [%s] (%s, line %d)"
                    % (raw_strs[i], inp_line, inp_file_name, line_count)
                )
                continue

        rows.append(row)

    # Handle the binary case
    if binaryoutput:
        data_start = buffer.find(b"%start")
        data_start = buffer.find(b"\n", data_start) + 1
        data_end = buffer.find(b"\n%stop")

        # How many cols?
        if eng_file_class == "base":
            cols = len(columns)
        elif eng_file_class == "logavg":
            if columns:
                cols = len(columns)
            else:
                cols = nlog
        else:
            log_error("Reading binary output from eng_file %s NYI" % inp_file_name)
            return None

        if scaleoff:
            tmp = arr.array("B")
            tmp.frombytes(buffer[data_start:data_end])
            data = np.array(tmp).astype(np.float64)
            # data = arr.array("f")
            # data.frombytes(list(map(float, tmp)))
        else:
            data = arr.array("f")
            data.frombytes(buffer[data_start:data_end])

        rows = len(data) // cols

        data = np.reshape(data, (rows, cols), order="C")

        return np.transpose(data)

    else:
        if not rows:
            return None

        tmp = np.array(rows, np.float64)
        data = []
        for i in range(len(rows[0])):
            data.append(tmp[:, i])

        return data


def eng_file_reader(eng_files, nc_info_d, calib_consts):
    """Reads the eng files for tmicl instruments

    Input:
        eng_files - list of eng_file that contain one class of file
        nc_info_d - netcdf dictionary
        calib_consts - calib conts dictionary

    Returns:
        ret_list - list of (variable,data) tuples
        netcdf_dict - dictionary of optional netcdf variable additions

    """
    netcdf_dict = {}
    ret_list = []

    for fn in eng_files:
        # Figure out what type of engfile
        filename = fn["file_name"]
        _, tail = os.path.split(filename)
        head, _ = os.path.splitext(tail)
        tmp = head.split("_")
        eng_file_class = tmp[1]
        eng_file_channel = tmp[2]  # channel

        if eng_file_class in ("base", "motors"):
            eng_file_meta, ef_ret_list = extract_file_metadata(
                filename, eng_file_channel
            )
            if eng_file_meta is None:
                log_error("%s contains no metadata - not using in profile" % filename)
                continue

            if ef_ret_list is None:
                log_error(
                    "%s contains no netcdf data - not adding to profile" % filename
                )
            else:
                for r in ef_ret_list:
                    ret_list.append(r)

            data = extract_file_data(filename)
            if not data:
                log_debug("%s contains no data - not using in profile" % filename)
                continue

            # Remap column header names
            data_column_headers = []
            # 2021/12/30 Bug - motor files have no column header
            if eng_file_class == "motors" and "columns" not in eng_file_meta:
                columns = ["time", "onoff", "sample"]
            else:
                columns = eng_file_meta["columns"].split()
            for column_name in columns:
                data_column_headers.append(column_name.replace(".", "_"))

            # Form the dimension and info for the data in this file
            nc_eng_file_mdp_dim = "tmicl_%s_%s_%s_data_point" % (
                eng_file_class,
                eng_file_channel,
                FileMgr.cast_code[fn["cast"]],
            )
            log_debug("Creating dimension %s" % nc_eng_file_mdp_dim)
            nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
            if nc_eng_file_mdp_info not in BaseNetCDF.nc_mdp_data_info:
                BaseNetCDF.register_sensor_dim_info(
                    nc_eng_file_mdp_info, nc_eng_file_mdp_dim, None, True, None
                )

            for i in range(len(columns)):
                if eng_file_class == "motors":
                    nc_var_name = "tmicl_motors_%s_%s_%s" % (
                        data_column_headers[i],
                        eng_file_channel,
                        FileMgr.cast_code[fn["cast"]],
                    )
                else:
                    nc_var_name = "tmicl_%s_%s_%s" % (
                        data_column_headers[i],
                        eng_file_channel,
                        FileMgr.cast_code[fn["cast"]],
                    )
                log_debug("%s(%s)" % (nc_var_name, nc_eng_file_mdp_dim))
                ret_list.append((nc_var_name, data[i]))
                # Predeclare metadata for these variables in other sensor extension files when possible.
                # If not, this will allow the data to be written with complaint
                # load_dive_profile_data() will reload such data also with complaint
                # If you write files with constructed dim info and later declare it
                # then when the nc file is rebuilt it will use the new, declared dim name
                if nc_var_name not in BaseNetCDF.nc_var_metadata:
                    log_debug(
                        "Metadata for tmicl data %s was not pre-declared" % nc_var_name
                    )
                    # Since it is raw data and load_dive_profile_data() will create this info
                    # as well, we let MMT and MMP handle it
                    netcdf_dict[nc_var_name] = BaseNetCDF.form_nc_metadata(
                        None, False, "d", {}, (nc_eng_file_mdp_info,)
                    )

        elif eng_file_class in ("logavg", "dvdt", "specavg"):
            try:
                fi = open(filename, "r")
            except Exception:
                log_error("Unable to open %s" % filename)
                continue

            nfft = None
            rate = None
            effectiverate = None
            logmap = None
            columns = None
            for l_line in fi:
                if l_line.startswith("%columns:"):
                    columns = l_line.split()[1:]
                if l_line.startswith("%nfft: "):
                    nfft = int(l_line.split(" ", 1)[1].rstrip().lstrip())
                if l_line.startswith("%samplerate: "):
                    rate = int(l_line.split(" ", 1)[1].rstrip().lstrip())
                if l_line.startswith("%effectivesamplerate: "):
                    effectiverate = float(l_line.split(" ", 1)[1].rstrip().lstrip())

                if l_line.startswith("%logmap: "):
                    logmap = l_line.split(" ", 1)[1]
                    # Fix for broken log map writer in tmicl of the form
                    # %logmap: 0-0,1-1,2-2,3-5,6-10,11-17,18-29,30-49,50-83,84-138,139-231,232-385386-511
                    split_lm = logmap.split(",")
                    if len(split_lm[-1].split("-")) > 2:
                        # Trim the end
                        right = logmap.rindex("-")
                        left = logmap.rindex("-", 0, right) + 1
                        new_end = left + int(math.floor(float(right - left) / 2.0))
                        new_logmap = logmap[:new_end]
                        # log_info("Changing logmap from %s to %s" % (logmap, new_logmap))
                        logmap = new_logmap
            fi.close()

            center_freqs = calc_center_freqs(
                effectiverate if effectiverate is not None else rate, nfft, logmap
            )

            try:
                data = np.genfromtxt(filename, comments="%")
            except Exception:
                log_error("Error processing %s - skipping" % filename, "exc")
                continue

            data = data.transpose()

            # Strip off the time
            time_col = data[0, :]
            spectra = data[1:, :]

            if columns and columns[1] == "sigvar":
                sig_var = spectra[0, :]
                spectra = spectra[1:, :]
                nc_eng_file_mdp_dim = "tmicl_%s_%s_%s_data_point" % (
                    eng_file_class,
                    eng_file_channel,
                    FileMgr.cast_code[fn["cast"]],
                )
                log_debug("Creating dimension %s" % nc_eng_file_mdp_dim)
                nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
                if nc_eng_file_mdp_info not in BaseNetCDF.nc_mdp_data_info:
                    BaseNetCDF.register_sensor_dim_info(
                        nc_eng_file_mdp_info, nc_eng_file_mdp_dim, None, True, None
                    )

                nc_var_name = "tmicl_%s_%s_%s" % (
                    "sigvar",
                    eng_file_channel,
                    FileMgr.cast_code[fn["cast"]],
                )
                log_debug("%s(%s)" % (nc_var_name, nc_eng_file_mdp_dim))
                ret_list.append((nc_var_name, sig_var))
                if nc_var_name not in BaseNetCDF.nc_var_metadata:
                    log_debug(
                        "Metadata for tmicl data %s was not pre-declared" % nc_var_name
                    )
                    netcdf_dict[nc_var_name] = BaseNetCDF.form_nc_metadata(
                        None, False, "d", {}, (nc_eng_file_mdp_info,)
                    )

            # The time portion
            nc_var_name = "tmicl_%s_%s_%s_%s" % (
                eng_file_class,
                eng_file_channel,
                FileMgr.cast_code[fn["cast"]],
                "time",
            )
            ret_list.append((nc_var_name, time_col))
            if nc_var_name not in BaseNetCDF.nc_var_metadata:
                nc_eng_file_mdp_dim = "%s_data_point" % nc_var_name
                nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
                if nc_eng_file_mdp_info not in BaseNetCDF.nc_mdp_data_info:
                    BaseNetCDF.register_sensor_dim_info(
                        nc_eng_file_mdp_info, nc_eng_file_mdp_dim, None, True, None
                    )  # CONSIDER True -> 'microstructure'
                netcdf_dict[nc_var_name] = BaseNetCDF.form_nc_metadata(
                    None, False, "d", {}, (nc_eng_file_mdp_info,)
                )

            spectra = spectra.transpose()

            # Center freqs
            if eng_file_class == "logavg":
                # log_info("center_freqs:%s" % (center_freqs))
                if center_freqs is None:
                    # No spectral data
                    pass
                elif len(center_freqs) != len(spectra[0, :]):
                    log_error(
                        "len(center_freqs) %d != len(logavg) %d"
                        % (len(center_freqs), spectra[0, :])
                    )
                else:
                    nc_var_name = "tmicl_%s_%s_%s_%s" % (
                        eng_file_class,
                        eng_file_channel,
                        FileMgr.cast_code[fn["cast"]],
                        "center_freqs",
                    )
                    ret_list.append((nc_var_name, center_freqs))
                    if nc_var_name not in BaseNetCDF.nc_var_metadata:
                        nc_eng_file_mdp_dim = "%s_data_point" % nc_var_name
                        nc_eng_file_mdp_info = "%s_info" % nc_eng_file_mdp_dim
                        if nc_eng_file_mdp_info not in BaseNetCDF.nc_mdp_data_info:
                            BaseNetCDF.register_sensor_dim_info(
                                nc_eng_file_mdp_info,
                                nc_eng_file_mdp_dim,
                                None,
                                True,
                                None,
                            )  # CONSIDER True -> 'microstructure'
                        netcdf_dict[nc_var_name] = BaseNetCDF.form_nc_metadata(
                            None, False, "d", {}, (nc_eng_file_mdp_info,)
                        )

            # The data part
            nc_var_name = "tmicl_%s_%s_%s" % (
                eng_file_class,
                eng_file_channel,
                FileMgr.cast_code[fn["cast"]],
            )
            ret_list.append((nc_var_name, spectra))

            # The nc metadata for nc_var_name was created in init_logger() above
            # including the multi-dimensional row and coluumn info and dimensions
            # Here we are able to assert the dimension sizes
            BaseNetCDF.assign_dim_info_size(
                nc_info_d, "%s_row_info" % nc_var_name, spectra.shape[0]
            )  # rows
            BaseNetCDF.assign_dim_info_size(
                nc_info_d, "%s_col_info" % nc_var_name, spectra.shape[1]
            )  # columns

        # elif eng_file_class == "motors":
        #    log_info("Not adding %s to netcdf file" % filename)
        else:
            log_warning(
                "Unknown class %s of tmicl file %s -- skipping"
                % (eng_file_class, filename)
            )

    return ret_list, netcdf_dict
