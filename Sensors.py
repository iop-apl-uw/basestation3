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
# NOTE on Python debugging of Sensor debugging under pdb:
# after importing sys, issue (once per pdb session):
# sys.path.append('./Sensors')
# You can then add breakpoints etc. in the extension files w/o specifiying the path\

""" Support for loading and running Sensor extensions
"""

import collections
import os
import re
import shutil

import BaseNetCDF
import LogFile
import Utils

from BaseLog import log_error, log_debug, log_info, log_warning

known_logger_dict_keys = (
    "logger_prefix",
    "netcdf_metadata_adds",
    "known_files",
    "known_mailer_tags",
    "known_ftp_tags",
    "eng_file_reader",
    "strip_files",
)
known_sensor_dict_keys = ("logger_prefix", "netcdf_metadata_adds")


class SensorExtensions:
    """Object to manage calling sensor extensions"""

    def __init__(
        self,
        base_opts,
        sensor_extension_subdirectory="Sensors",
        sensor_extension_base_name=".sensors",
    ):
        self.__base_opts = base_opts
        self.__extension_file_name = None
        self.__extension_directory = None
        self.__se_dict = collections.OrderedDict()
        basestation_directory = base_opts.basestation_directory
        sensor_extension_directory = os.path.join(
            basestation_directory, sensor_extension_subdirectory
        )
        sensor_extension_file_name = os.path.join(
            sensor_extension_directory, sensor_extension_base_name
        )
        extension_file_name = os.path.abspath(
            os.path.expanduser(sensor_extension_file_name)
        )
        if not os.path.exists(extension_file_name):
            log_info(
                "No %s file found - skipping %s processing"
                % (extension_file_name, extension_file_name)
            )
            return
        if not os.path.exists(sensor_extension_directory):
            log_error("Sensor extension directory  %s not found")
            return

        self.__extension_file_name = extension_file_name
        self.__extension_directory = sensor_extension_directory

    def init_sensor_extensions(self):
        """Initializes the internal call structures
        - this may fail, so we run this outside the constructor

        Returns:
        dictionary of sensor descriptions
        success:
            0 - success
            1 - failure
        """
        ret_val = 0
        if self.__extension_file_name is None:
            log_info("Sensor extension not enabled - skipping processing")
            return (None, 0)

        log_debug(f"Starting processing on {self.__extension_file_name}")
        try:
            extension_file = open(self.__extension_file_name, "r")
        except IOError as exception:
            log_error(
                "Could not open %s (%s) - skipping processing"
                % (self.__extension_file_name, exception.args)
            )
            return (None, 1)
        else:
            ret_val = 0
            for extension_line in extension_file:
                extension_line = extension_line.rstrip()
                log_debug(f"extension file line = ({extension_line})")
                if extension_line == "":
                    continue
                if extension_line[0] != "#":
                    log_debug(
                        "Processing %s line (%s)"
                        % (self.__extension_file_name, extension_line)
                    )
                    extension_line.rstrip()
                    extension_elts = extension_line.split(",")
                    extension_module_name = os.path.join(
                        self.__extension_directory, extension_elts[0]
                    )
                    _, tail = os.path.splitext(extension_module_name)
                    temp_dict = {}
                    if tail == ".py":
                        extension_module = Utils.loadmodule(extension_module_name)
                        if extension_module is None:
                            log_error(
                                f"Error loading {extension_module_name} - skipping"
                            )
                            ret_val = 1
                        else:
                            for processing_func in extension_elts[1:]:
                                try:
                                    temp_dict[
                                        processing_func
                                    ] = extension_module.__dict__[processing_func]
                                except KeyError:
                                    log_warning(
                                        "Sensor extension %s does not contain function %s, but is configured to have it - skipping"
                                        % (extension_module_name, processing_func)
                                    )

                    elif tail == ".cnf":
                        # For .cnf file sensors, install the appropriate built in handler
                        # and for logdev sensors, pull out the prefix
                        for processing_func in extension_elts[1:]:
                            # Truth to tell, asc2eng and init_sensor are REQUIRED
                            if processing_func == "asc2eng":
                                temp_dict[processing_func] = conf_file_asc2eng
                            elif processing_func == "init_sensor":
                                temp_dict[processing_func] = conf_file_init_sensor
                            elif processing_func == "init_logger":
                                temp_dict[processing_func] = conf_file_init_logger
                            elif processing_func == "process_data_files":
                                temp_dict[
                                    processing_func
                                ] = conf_file_process_data_files
                            elif processing_func == "add_netcdf_meta":
                                temp_dict[processing_func] = conf_file_add_netcdf_meta
                            else:
                                log_error(
                                    "Unknown processing function %s for cnf file %s"
                                    % (processing_func, extension_module_name)
                                )
                                ret_val = 1

                    else:
                        log_error(
                            "Unknown extension %s - skipping %s"
                            % (tail, extension_module_name)
                        )
                        ret_val = 1
                        continue
                    # If we get here temp_dict is initialized as a logger or a sensor
                    # An extension can be for a logger or sensor - not both
                    if "init_logger" in temp_dict:
                        ttemp_dict = {}
                        extension_ret_val = temp_dict["init_logger"](
                            extension_module_name, ttemp_dict
                        )
                        if extension_ret_val < 0:
                            log_debug(
                                "Error running init_logger (%s) - return %d"
                                % (extension_module_name, extension_ret_val)
                            )
                            ret_val = 1
                        else:
                            for i in known_logger_dict_keys:
                                try:
                                    temp_dict[i] = ttemp_dict[extension_module_name][i]
                                except:
                                    pass

                    if "init_sensor" in temp_dict:
                        ttemp_dict = {}
                        extension_ret_val = temp_dict["init_sensor"](
                            extension_module_name, ttemp_dict
                        )
                        if extension_ret_val < 0:
                            log_error(
                                "Error running init_sensor (%s) - return %d"
                                % (extension_module_name, extension_ret_val)
                            )
                            ret_val = 1
                        else:
                            for i in known_sensor_dict_keys:
                                try:
                                    temp_dict[i] = ttemp_dict[extension_module_name][i]
                                except:
                                    pass
                    if "add_netcdf_meta" in temp_dict:
                        ttemp_dict = {}
                        extension_ret_val = temp_dict["add_netcdf_meta"](
                            extension_module_name, ttemp_dict
                        )
                        if extension_ret_val < 0:
                            log_error(
                                "Error running init_sensor (%s) - return %d"
                                % (extension_module_name, extension_ret_val)
                            )
                            ret_val = 1
                        else:
                            for i in known_sensor_dict_keys:
                                try:
                                    temp_dict[i] = ttemp_dict[extension_module_name][i]
                                except:
                                    pass
                    # set sensor extension dictionary
                    self.__se_dict[extension_module_name] = temp_dict

        log_debug(f"Finished processing on {self.__extension_file_name}")

        return (self.__se_dict, ret_val)

    def process_sensor_extensions(self, processing_func, *args):
        """Processes the instruments extension file - calling each extension configured for the
        processing function with the supplied arguments

        Returns:
            0 - success
            1 - failure
        """
        ret_val = 0
        for key in list(self.__se_dict.keys()):
            ext = self.__se_dict[key]
            if processing_func in ext:
                extension_ret_val = ext[processing_func](self.__base_opts, key, *args)
                if extension_ret_val is None:
                    log_warning(f"Extension returned None ({key},{processing_func})")
                    ret_val = 1
                elif extension_ret_val < 0:
                    log_debug(
                        "Error running %s(%s) - return %s"
                        % (key, processing_func, str(extension_ret_val))
                    )
                    ret_val = 1
        return ret_val

    def process_logger_func(self, logger_prefix, processing_func, *args):
        """Process a logger function

        Returns:
            -1 - logger does not support that function
            0 - success
            1 - failure

        """
        for key in list(self.__se_dict.keys()):
            d = self.__se_dict[key]
            if "logger_prefix" in d and d["logger_prefix"] == logger_prefix:
                if processing_func in d:
                    extension_ret_val = d[processing_func](self.__base_opts, key, *args)
                    if extension_ret_val < 0:
                        log_error(
                            "Error running %s(%s) - return %d"
                            % (key, processing_func, extension_ret_val)
                        )
                        return 1
                    else:
                        return 0
                else:
                    log_error(
                        "Logger %s does not support %s, but was called as if it did"
                        % (key, processing_func)
                    )
                    return -1
        return 0


# Helper routines
sensor_extensions = None


def init_extensions(base_opts):
    """Initializes sensor extensions"""
    global sensor_extensions  # pylint: disable=global-statement

    if sensor_extensions is not None:
        log_error("init_extensions already called - internal error")
        return (None, 1)

    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_trajectory_info,
        BaseNetCDF.nc_dim_trajectory_info,
        None,
        True,
        None,
    )  # trajectory is 'data', so it is removed when loading MDP info
    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_sg_data_info,
        BaseNetCDF.nc_dim_sg_data_point,
        BaseNetCDF.nc_sg_time_var,
        True,
        None,
    )  # lots of instruments
    # these are derived from raw data
    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_gps_info_info,
        BaseNetCDF.nc_dim_gps_info,
        "log_gps_time",
        False,
        None,
    )  # could be GPS model
    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_gc_event_info,
        BaseNetCDF.nc_dim_gc_event,
        "gc_st_secs",
        False,
        None,
    )
    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_gc_state_info,
        BaseNetCDF.nc_dim_gc_state,
        "gc_state_secs",
        False,
        None,
    )
    # Register all possible gc_msg dimensions
    for msg in LogFile.msg_gc_entries:
        BaseNetCDF.register_sensor_dim_info(
            f"{BaseNetCDF.nc_gc_msg_prefix}{msg}_info",
            f"{BaseNetCDF.nc_gc_msg_prefix}{msg}",
            f"{BaseNetCDF.nc_gc_msg_prefix}{msg}_secs",
            False,
            None,
        )

    BaseNetCDF.register_sensor_dim_info(
        BaseNetCDF.nc_ctd_results_info,
        BaseNetCDF.nc_dim_ctd_data_point,
        BaseNetCDF.nc_ctd_time_var,
        False,
        None,
    )

    sensor_extensions = SensorExtensions(base_opts)
    (init_dict, init_ret_val) = sensor_extensions.init_sensor_extensions()
    return (init_dict, init_ret_val)


def process_sensor_extensions(processing_func, *args):
    """Run a sensor extension function"""
    #    global sensor_extensions  # pylint: disable=global-statement

    if sensor_extensions is None:
        log_error("init_extensions not called - internal error")
        return 1
    else:
        return sensor_extensions.process_sensor_extensions(processing_func, *args)


def process_logger_func(logger_prefix, processing_func, *args):
    """Runs a logger function"""
    #    global sensor_extensions

    if sensor_extensions is None:
        log_error("init_extensions not called - internal error")
        return 1
    else:
        return sensor_extensions.process_logger_func(
            logger_prefix, processing_func, *args
        )


# These routines process configuration file based serdev and logdev sensors
# pylint: disable=unused-argument
def conf_file_asc2eng(base_opts, conf_file_name, datafile):
    """Configuration file asc2eng processor

    Returns:
    -1 - error in processing
     0 - success (data found, processed, and added to datafile)
     1 - no data found to process
    """
    cnf_dict, _ = Utils.read_cnf_file(conf_file_name)
    if cnf_dict is None:
        return -1

    try:
        prefix = cnf_dict["prefix"]
    except KeyError:
        prefix = (
            None  # BUG isn't this bad news since we'll use None as the prefix below
        )

    columns = collections.OrderedDict()
    try:
        for col in cnf_dict["column"]:
            if col.find("(") >= 0:
                m = re.match(r"(.*?)\((.*?)\,(.*?)\)", col)
                if m:
                    try:
                        scale = float(m.group(2))
                        offset = float(m.group(3))
                    except:
                        log_error(
                            "Processing line %s in %s - scale and offset must be floats"
                            % (col, conf_file_name)
                        )
                        return -1
                    else:
                        columns[m.group(1)] = (scale, offset)
                else:
                    log_error(
                        "Didn't understand the format of line %s in %s"
                        % (col, conf_file_name)
                    )
                    ret_val = -1
                    return ret_val
            else:
                columns[col] = (None, None)
    except KeyError:
        pass  # no columns!?

    # log_info("Column names = %s" % columns)
    ret_val = 1
    for col in list(columns.keys()):
        col_name = f"{prefix}.{col}"
        tmp_col = datafile.remove_col(col_name)
        if tmp_col is not None:
            ret_val = 0
            datafile.eng_cols.append(col_name)
            if columns[col][0] is not None:
                tmp_col = tmp_col / columns[col][0]
            if columns[col][1] is not None:
                tmp_col = tmp_col + columns[col][1]
            datafile.eng_dict[col_name] = tmp_col

    return ret_val


def conf_file_init_logger(conf_file_name, init_dict=None):
    """Configuration file logger (logdev) initialization

    Reads conf file for variable names and populates the init dictionary for later netCDF processing

    Returns:
    -1 - error in processing
     0 - success with additional in init_dict
    """

    log_debug(f"Starting processing on {conf_file_name}")

    ret_val = 0

    if init_dict is None:
        log_error("No init_dict supplied for init_loggers - version mismatch?")
        return -1
    try:
        init_dict[conf_file_name]
    except KeyError:
        init_dict[conf_file_name] = {}

    cnf_dict, cnf_nc_meta_dict = Utils.read_cnf_file(conf_file_name)
    if cnf_dict is None:
        return -1

    try:
        prefix = cnf_dict["prefix"]
    except KeyError:
        prefix = None

    if prefix:
        init_dict[conf_file_name]["logger_prefix"] = prefix
    else:
        log_error(f"Missing prefix in {conf_file_name}")
        ret_val = -1

    try:
        cmdprefix = cnf_dict["cmdprefix"]
    except KeyError:
        cmdprefix = None

    params = {}
    if cmdprefix:
        cmdprefix = cmdprefix[1:3]
        params["log_" + cmdprefix + "_RECORDABOVE"] = [
            False,
            "d",
            {
                "description": "Depth above above which data is recorded",
                "units": "meters",
            },
            BaseNetCDF.nc_scalar,
        ]
        params["log_" + cmdprefix + "_PROFILE"] = [
            False,
            "d",
            {
                "description": "Which part of the dive to record data for - 0 none, 1 dive, 2 climb, 3 both"
            },
            BaseNetCDF.nc_scalar,
        ]
        params["log_" + cmdprefix + "_XMITPROFILE"] = [
            False,
            "d",
            {
                "description": "Which profile to transmit back to the basestation - 0 none, 1 dive, 2 climb, 3 both"
            },
            BaseNetCDF.nc_scalar,
        ]
        params["log_" + cmdprefix + "_UPLOADMAX"] = [
            False,
            "d",
            {"description": "Maximum upload size"},
            BaseNetCDF.nc_scalar,
        ]
        params["log_" + cmdprefix + "_NDIVE"] = [
            False,
            "d",
            {"description": "Dive multiplier"},
            BaseNetCDF.nc_scalar,
        ]
        params["log_" + cmdprefix + "_STARTS"] = [
            False,
            "d",
            {"description": "Auto-incremented count of instrument starts"},
            BaseNetCDF.nc_scalar,
        ]

    files = []
    for v in ["x", "y", "z"]:
        try:
            file = cnf_dict["script-" + v]
        except:
            file = None

        if file:
            files.append(file)
            log_debug(f"script {file}")

        try:
            param = cnf_dict["param-" + v]
        except:
            param = None

        if param and cmdprefix:
            params["log_" + cmdprefix + "_" + param] = [
                False,
                "d",
                {"description": "Logger parameter (param-" + v + ")"},
                BaseNetCDF.nc_scalar,
            ]

    for v in ["0", "1", "2"]:
        try:
            param = cnf_dict["log-" + v]
        except:
            param = None

        if param and cmdprefix:
            params["log_" + cmdprefix + "_" + param] = [
                False,
                "d",
                {"description": "Logger log result (log-" + v + ")"},
                BaseNetCDF.nc_scalar,
            ]

    for k in list(cnf_nc_meta_dict.keys()):
        if k.startswith("register_sensor_dim_info"):
            try:
                BaseNetCDF.register_sensor_dim_info(*cnf_nc_meta_dict[k])
            except:
                log_error(
                    f"Failed to register dimension {k} {cnf_nc_meta_dict[k]}",
                    "exc",
                )
        else:
            params[k] = cnf_nc_meta_dict[k]

    if len(files) > 0:
        init_dict[conf_file_name]["known_files"] = files

    if len(params) > 0:
        init_dict[conf_file_name]["netcdf_metadata_adds"] = params

    return ret_val


def conf_file_init_sensor(conf_file_name, init_dict=None):
    """Configuration file sensor initialization

    Reads conf file for variable names and populates the init dictionary for later netCDF processing

    Returns:
    -1 - error in processing
     0 - success with additional in init_dict
    """

    if init_dict is None:
        log_error("No init_dict supplied for init_sensors - version mismatch?")
        return -1
    try:
        init_dict[conf_file_name]
    except KeyError:
        init_dict[conf_file_name] = {}

    cnf_dict, cnf_nc_meta_dict = Utils.read_cnf_file(conf_file_name)
    if cnf_dict is None:
        return -1

    # log_info("cnf_nc_meta_dict % s" % cnf_nc_meta_dict)
    # log_info(cnf_dict)
    log_debug(f"Starting processing on {conf_file_name}")
    try:
        prefix = cnf_dict["prefix"]
    except KeyError:
        prefix = None

    try:
        name = cnf_dict["name"]
    except KeyError:
        name = prefix

    columns = {}
    ret_val = 0  # assume the best
    try:
        for col in cnf_dict["column"]:
            if col.find("(") >= 0:
                m = re.match(r"(.*?)\((.*?)\,(.*?)\)", col)
                if m:
                    try:
                        scale = float(m.group(2))
                        offset = float(m.group(3))
                    except:
                        log_error(
                            "Processing line %s in %s - scale and offset must be floats"
                            % (col, conf_file_name)
                        )
                        return -1
                    else:
                        columns[m.group(1)] = (scale, offset)
                else:
                    log_error(
                        "Didn't understand the format of line %s in %s"
                        % (col, conf_file_name)
                    )
                    return -1
            else:
                columns[col] = (None, None)
    except KeyError:
        pass

    # log_info("Column names = %s" % columns)

    # NOTE: cnf files in the Sensors directory are for trunk eng_ files ONLY
    # scicon files embed the 'cnf' information in their headers and Sensors/scicon_ext.py
    # parses that info and prepares any missing nc meta declarations there.  That includes
    # their time variable and sensor info/data_point declarations.
    if prefix:
        init_dict[conf_file_name]["logger_prefix"] = prefix
        instrument_name = Utils.ensure_basename(
            name.lower()
        )  # ensure it looks like a variable name
        # log_info("instrument_name:%s" % instrument_name)
        nc_metadata = {}
        init_dict[conf_file_name]["netcdf_metadata_adds"] = nc_metadata

        # create an nc_data_info and register against nc_sg_time_var and an instrument
        nc_sensor_dim_info = instrument_name + "_info"
        nc_sensor_dim_name = instrument_name + "_data_point"
        if instrument_name not in BaseNetCDF.nc_var_metadata:
            # define the instrument variable
            BaseNetCDF.form_nc_metadata(
                instrument_name,
                False,
                "c",
                {"long_name": instrument_name, "make_model": instrument_name},
                BaseNetCDF.nc_scalar,
            )
        # TODO allow a data_kind tag in the cnf file to permit declaring the type of data the sensor
        # collects, e.g., biological, chemical, physical, acoustical, magnetometer, etc.
        # Pass this value rather than True below
        BaseNetCDF.register_sensor_dim_info(
            nc_sensor_dim_info,
            nc_sensor_dim_name,
            BaseNetCDF.nc_sg_time_var,
            True,
            instrument_name,
        )

        for col in list(columns.keys()):
            nc_var_name = "%s%s_%s" % (
                BaseNetCDF.nc_sg_eng_prefix,
                prefix,
                col,
            )  # NOTE: eng_ only!!
            # Unused: raw_nc_var_name = "%s_%s" % (prefix, col)
            if nc_var_name in BaseNetCDF.nc_var_metadata:
                continue  # already defined by hand
            elif nc_var_name in cnf_nc_meta_dict:
                # Included in comment in the .cnf file
                BaseNetCDF.form_nc_metadata(nc_var_name, *cnf_nc_meta_dict[nc_var_name])
            else:
                descr = instrument_name + " " + col
                # TODO Add 'As reported by instrument'?
                if columns[col][0] is not None:
                    descr = descr + " scaled by " + str(columns[col][0])
                if columns[col][1] is not None:
                    descr = descr + " offset by " + str(columns[col][1])
                # Include this raw data since we don't have an extension to process it into results yet
                BaseNetCDF.form_nc_metadata(
                    nc_var_name,
                    False,
                    "d",
                    {"description": descr},
                    (nc_sensor_dim_info,),
                )
    else:
        log_error(f"Missing prefix in {conf_file_name}")
        ret_val = -1

    return ret_val


# pytlint: disable=unused-argument
def conf_file_process_data_files(
    base_opts, module_name, fc, processed_eng_files, processed_other_files
):
    """Processes other files associated with a conf_file

    Returns:
        0 - success
        1 - failure
    """
    if fc.is_down_data() or fc.is_up_data() or fc.is_data():
        shutil.move(fc.full_filename(), fc.mk_base_datfile_name())
        processed_other_files.append(fc.mk_base_datfile_name())
        return 0
    else:
        # These should be non-existant
        log_error(f"Don't know how to deal with MIB file ({fc.full_filename()})")
        return 1


def conf_file_add_netcdf_meta(conf_file_name, init_dict=None):
    """Configuration file sensor initialization

    Reads conf file for variable names and populates the init dictionary for later netCDF processing

    This function is mainly for the scicion to add needed meta data for instruments that don't otherwise have
    sensor extensions to define metadata

    Returns:
    -1 - error in processing
     0 - success with additional in init_dict
    """

    # log_info("In conf_file_add_netcdf_meta")
    if init_dict is None:
        log_error("No init_dict supplied for init_sensors - version mismatch?")
        return -1
    try:
        init_dict[conf_file_name]
    except KeyError:
        init_dict[conf_file_name] = {}

    _, cnf_nc_meta_dict = Utils.read_cnf_file(conf_file_name)
    if cnf_nc_meta_dict is None:
        return -1

    # log_info("cnf_nc_meta_dict % s" % cnf_nc_meta_dict)
    log_debug(f"Starting processing on {conf_file_name}")

    nc_adds = {}

    for k in list(cnf_nc_meta_dict.keys()):
        if k.startswith("register_sensor_dim_info"):
            try:
                BaseNetCDF.register_sensor_dim_info(*cnf_nc_meta_dict[k])
            except:
                log_error(
                    f"Failed to register dimension {k} {cnf_nc_meta_dict[k]}",
                    "exc",
                )
        else:
            nc_adds[k] = cnf_nc_meta_dict[k]

    init_dict[conf_file_name]["netcdf_metadata_adds"] = nc_adds

    return 0
