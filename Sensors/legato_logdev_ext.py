#! /usr/bin/env python
# -*- python-fmt -*-

"""
RBR Legato logdev basestation sensor extension
"""
import enum
import struct

import BaseNetCDF
import Utils

from BaseLog import log_error, log_warning

# channel			flag
# -----------------------------------
# conductivity      0x01        1
# temperature       0x02        2
# pressure          0x04        4
# sea pressure      0x08        8
# depth             0x10        16
# salinity          0x20        32
# counts            0x40        64
# cond cell temp    0x80       128


# pylint: disable=invalid-name
class legato_bits(enum.IntEnum):
    """Bitfields defining what is in the payload
    Time is implicitly column 0
    """

    conduc = 0x1
    temp = 0x2
    pressure = 0x4
    sea_pressure = 0x8
    depth = 0x10
    salinity = 0x20
    counts = 0x40
    conducTemp = 0x80


legato_default_config = legato_bits.conduc + legato_bits.temp + legato_bits.pressure


def init_logger(module_name, init_dict=None):
    """
    init_loggers

    returns:
    -1 - error in processing
     0 - success (data found and processed)
    """
    # log_info("in rbr init_logger")
    if init_dict is None:
        log_error("No datafile supplied for init_loggers - version mismatch?")
        return -1

    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_legato_data_info,
        "legato_data_point",
        "legato_time",
        True,
        "legato",
    )
    # results are computed in MDP
    init_dict[module_name] = {
        "logger_prefix": "rb",
        "is_profile_ct": True,
        "eng_file_reader": eng_file_reader,
        "netcdf_metadata_adds": {
            "legato": [
                False,
                "c",
                {
                    "long_name": "RBR Legato",
                    "nodc_name": "thermosalinograph",
                    "make_model": "RBR Legato",
                },
                BaseNetCDF.nc_scalar,
            ],  # always scalar
            "log_RB_RECORDABOVE": [
                False,
                "d",
                {
                    "description": "Depth above above which data is recorded",
                    "units": "meters",
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RB_PROFILE": [
                False,
                "d",
                {
                    "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RB_XMITPROFILE": [
                False,
                "d",
                {
                    "description": "Which profile to transmit snippet file back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
                },
                BaseNetCDF.nc_scalar,
            ],
            "log_RB_INTERVAL": [
                False,
                "d",
                {"description": "Sampling rate (seconds)"},
                BaseNetCDF.nc_scalar,
            ],
            "legato_time": [
                True,
                "d",
                {
                    "standard_name": "time",
                    "units": "seconds since 1970-1-1 00:00:00",
                    "description": "CTD sample time in GMT epoch format",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_conductivity": [
                True,
                "d",
                {
                    "standard_name": "sea_water_electrical_conductivity",
                    "units": "mS/cm",
                    "description": "CTD reported conductivity",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_temperature": [
                True,
                "d",
                {
                    "standard_name": "sea_water_temperature",
                    "units": "degrees_Celsius",
                    "description": "CTD reported temperature",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_pressure": [
                True,
                "d",
                {
                    "standard_name": "pressure",
                    "units": "dbar",
                    "description": "CTD reported pressure",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_sea_pressure": [
                True,
                "d",
                {
                    "standard_name": "sea_water_pressure",
                    "units": "dbar",
                    "description": "CTD reported sea pressure",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_depth": [
                True,
                "d",
                {
                    "standard_name": "depth",
                    "units": "meters",
                    "description": "CTD reported depth",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_salinity": [
                True,
                "d",
                {
                    "standard_name": "salinity",
                    "units": "PSU",
                    "description": "CTD calculated salinity",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_counts": [
                True,
                "d",
                {
                    "standard_name": "counts",
                    "units": "counts",
                    "description": "CTD reported counts",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
            "legato_cond_cell_temp": [
                True,
                "d",
                {
                    "standard_name": "cond_cell_temp",
                    "units": "dbar",
                    "description": "CTD cell temperature",
                },
                (BaseNetCDF.nc_legato_data_info,),
            ],
        },
    }

    return 1


# pylint: disable=unused-argument
def process_data_files(
    base_opts,
    module_name,
    calib_consts,
    fc,
    processed_logger_eng_files,
    processed_logger_other_files,
):
    """Processes other files
    Input:
        base_opts - options object
        calib_conts - calibration consts dict
        fc - file code object for file being processed
        processed_logger_eng_files - list of eng files to add to
        processed_logger_other_files - list of other processed files to add to

    Returns:
        0 - success
        1 - failure
    """
    if fc.is_down_data() or fc.is_up_data():

        if "legato_sealevel" not in calib_consts:
            log_error("Missing legato_sealevel in sg_calib_constants - bailing out")
            return ([], {})
        else:
            sealevel = calib_consts["legato_sealevel"] / 1000.0

        if "legato_config" not in calib_consts:
            log_warning("No legato_config found in sg_calib constants - using default")
        else:
            try:
                legato_config = int(calib_consts["legato_config"])
            except ValueError:
                log_error("Bad value for legato_config - using default", "exc")

        if legato_config > [ii.value for ii in legato_bits][-1] << 1:
            log_warning(
                f"Legato config {legato_config} too large - use {legato_default_config}"
            )

        datfile = open(fc.mk_base_datfile_name(), "rb")
        engfile = open(fc.mk_base_engfile_name(), "w")

        engfile.write("%columns: legato.time")
        for ii in legato_bits:
            if legato_config & ii.value:
                engfile.write(f",legato.{ii.name}")

        engfile.write("\n%data:\n")

        while 1:
            legato_time = datfile.read(8)
            if len(legato_time) < 8:
                break
            legato_time = (
                struct.unpack("l", legato_time)[0] / 1000
            )  # convert to seconds
            engfile.write(f"{legato_time}")
            for ii in legato_bits:
                if legato_config & ii.value:
                    val = datfile.read(4)
                    if len(val) < 4:
                        break
                    val = struct.unpack("<f", val)[0]
                    if ii.name == "pressure":
                        val -= sealevel
                    engfile.write(f" {val:f}")
            engfile.write("\n")

        datfile.close()
        engfile.close()

        processed_logger_eng_files.append(fc.mk_base_engfile_name())
        return 0
    else:
        # These should be non-existent
        log_error("Don't know how to deal with RBR file (%s)" % fc.full_filename())
        return 1


# pytlint: disable=unused-argument
def eng_file_reader(eng_files, nc_info_d, calib_consts):
    """Reads the eng files"""

    if len(eng_files) > 1:
        log_error("Does not support down and up profile stiching")
        return ([], {})

    ret_list = []
    fn = eng_files[0]

    ef = Utils.read_eng_file(fn["file_name"])
    if not ef:
        log_error("Could not read %s - not using in profile" % fn["file_name"])
        return ([], {})

    for key, val in ef["data"].items():
        ret_list.append((key.replace(".", "_"), val))

    return (ret_list, {})
