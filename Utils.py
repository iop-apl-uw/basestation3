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

""" Misc utility routines
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import bz2
import collections
import errno
import functools
import glob
import importlib
import math
import os
import pickle
import re
import signal
import subprocess
import sqlite3
import sys
import time
import typing
import zmq

import gsw
import seawater

import numpy as np
import scipy

import Globals
import BaseNetCDF

# Avoid circular input for type checking
if typing.TYPE_CHECKING:
    import BaseOpts

from BaseLog import log_debug, log_error, log_warning, log_info, log_critical


def open_netcdf_file(
    filename: str, mode="r", version=1
) -> scipy.io._netcdf.netcdf_file:
    """A wrapper to handle the fact that mmap does not work on Mac OSX
    Running under Darwin sometimes yields 'Error 24: Too many open files', which is nonsense
    mmap=None says use mmap if you can
    """
    # return netcdf.netcdf_file(filename,mode,mmap=False if sys.platform == 'darwin' else mmap, version=version)
    # pylint: disable=protected-access
    return scipy.io._netcdf.netcdf_file(filename, mode, mmap=False, version=version)


col_ncmeta_map_type = collections.namedtuple(
    "col_ncmeta_map_type", ["nc_var_name", "nc_meta_str"]
)


def read_cnf_file(
    conf_file_name,
    encode_list=True,
    ensure_list=None,
    lower=True,
    mission_dir=None,
    results_d=None,
):
    """Open and read a glider cnf file, returning parameter=value results as a dict.
    (NOTE: These files have a different format from cnf files parsed by ConfigParser)
    Returns None if no file.
    Multiple entries for a property are encoded as lists of values if encode_list is True,
    otherwise the last value is returned.
    If property is member of ensure_list, even a singleton will be returned as a list.
    Values are parsed as integers or floats, else they are recorded as strings.
    If lower is True property names are coerced to lower-case.
    If results_d is a dict, save and restore the file contents (as a string) to it; assert metadata if needed
    Return any parameter metadata (in the case this is a sensor cnf file from scicon)
    """
    if ensure_list is None:
        ensure_list = ["column"]
    nc_conf_file_name = conf_file_name.replace(".", "_")
    cnf_file_contents = None
    filename = conf_file_name
    if mission_dir is not None:
        filename = os.path.join(mission_dir, conf_file_name)
    if os.path.exists(filename):
        try:
            cnf_file = open(filename, "r")
        except IOError as exception:
            log_debug("Could not open %s (%s)" % (filename, exception.args))
            # fallthrough
        else:
            cnf_file_contents = []
            for conf_line in cnf_file:
                conf_line = (
                    conf_line.rstrip()
                )  # what about .rstrip(chr(0x1a)) for files uploaded from glider?
                if conf_line == "":
                    continue
                # keep comment lines, etc.
                cnf_file_contents.append(conf_line)
            cnf_file.close()
            cnf_file_contents = "\n".join(cnf_file_contents)

    if cnf_file_contents is not None:
        if results_d is not None:
            try:
                BaseNetCDF.nc_var_metadata[nc_conf_file_name]
            except KeyError:
                BaseNetCDF.form_nc_metadata(nc_conf_file_name, False, "c")
            results_d[
                nc_conf_file_name
            ] = cnf_file_contents  # save/update cnf file contents
    else:
        if results_d is not None:
            try:
                cnf_file_contents = results_d[nc_conf_file_name]  # any saved version?
            except KeyError:
                return (None, None)  # nope
        else:
            return (None, None)  # neither saved nor file

    cnf_dict = {}
    nc_meta_dict = collections.OrderedDict()
    for conf_line in cnf_file_contents.split("\n"):
        log_debug("Processing %s line (%s)" % (conf_file_name, conf_line))
        if conf_line[0] == "#":
            cl = conf_line[1:].rstrip().lstrip()
            if cl.startswith("(") and cl.endswith(")"):
                # nc meta data adds are potentially included as comments
                # Looks like dimension register - just stash the line
                cnf_eval_dict = {
                    "nc_nan": BaseNetCDF.nc_nan,
                    "nc_scalar": BaseNetCDF.nc_scalar,
                    "nc_sg_data_info": BaseNetCDF.nc_sg_data_info,
                }
                try:
                    # pylint: disable=eval-used
                    tmp = col_ncmeta_map_type(*eval(cl, cnf_eval_dict))
                except:
                    log_error(
                        "Error processing nc meta data in %s (%s)"
                        % (conf_file_name, conf_line),
                        "exc",
                    )
                else:
                    # Confirm format
                    if tmp.nc_var_name.startswith("register_sensor_dim_info") or (
                        (
                            len(tmp.nc_meta_str) == 4
                            and isinstance(tmp.nc_meta_str[0], bool)
                            and isinstance(tmp.nc_meta_str[1], str)
                            and isinstance(tmp.nc_meta_str[2], dict)
                            and isinstance(tmp.nc_meta_str[3], tuple)
                        )
                    ):
                        nc_meta_dict[tmp.nc_var_name] = tmp.nc_meta_str
                    else:
                        log_error(
                            "netcdf meta data in %s (%s) is not formed correctly"
                            % (conf_file_name, conf_line)
                        )
            continue  # next line
        # parameter=value line
        conf_elts = conf_line.split("=")
        prop = conf_elts[0]
        if lower:
            prop = prop.lower()  # Convert to lower case
        value = conf_elts[1]
        try:
            value = int(value)
        except:
            try:
                value = float(value)
            except:
                # TODO? If string is enclosed in "", remove them?
                pass  # encode as-is, a string
        try:
            values = cnf_dict[prop]
        except KeyError:
            if prop in ensure_list:
                values = [value]
            else:
                values = value
        else:
            if encode_list:
                if not isinstance(values, list):
                    values = [values]
                values.append(value)
            else:
                values = value  # use most recent value
        cnf_dict[prop] = values  # update

    return (cnf_dict, nc_meta_dict)


def unique(s):
    """Return a list of the elements in s, but without duplicates."""
    return list(set(s))


# def unique(s):
#     """Return a list of the elements in s, but without duplicates.

#     For example, unique([1,2,3,1,2,3]) is some permutation of [1,2,3],
#     unique("abcabc") some permutation of ["a", "b", "c"], and
#     unique(([1, 2], [2, 3], [1, 2])) some permutation of
#     [[2, 3], [1, 2]].

#     For best speed, all sequence elements should be hashable.  Then
#     unique() will usually work in linear time.

#     If not possible, the sequence elements should enjoy a total
#     ordering, and if list(s).sort() doesn't raise TypeError it's
#     assumed that they do enjoy a total ordering.  Then unique() will
#     usually work in O(N*log2(N)) time.

#     If that's not possible either, the sequence elements must support
#     equality-testing.  Then unique() will usually work in quadratic
#     time.
#     """

#     n = len(s)
#     if n == 0:
#         return []

#     # Try using a dict first, as that's the fastest and will usually
#     # work.  If it doesn't work, it will usually fail quickly, so it
#     # usually doesn't cost much to *try* it.  It requires that all the
#     # sequence elements be hashable, and support equality comparison.
#     u = {}
#     try:
#         for x in s:
#             u[x] = 1
#     except TypeError:
#         del u  # move on to the next method
#     else:
#         return list(u.keys())  # NOTE This does not preserve sorted order

#     # We can't hash all the elements.  Second fastest is to sort,
#     # which brings the equal elements together; then duplicates are
#     # easy to weed out in a single pass.
#     # NOTE:  Python's list.sort() was designed to be efficient in the
#     # presence of many duplicate elements.  This isn't true of all
#     # sort functions in all languages or libraries, so this approach
#     # is more effective in Python than it may be elsewhere.
#     try:
#         t = sorted(s)
#     except TypeError:
#         del t  # move on to the next method
#     else:
#         assert n > 0
#         last = t[0]
#         lasti = i = 1
#         while i < n:
#             if t[i] != last:
#                 t[lasti] = last = t[i]
#                 lasti += 1
#             i += 1
#         return t[:lasti]

#     # Brute force is all that's left. O(n^2)  TODO Is this ever used?
#     u = []
#     for x in s:
#         if x not in u:
#             u.append(x)
#     return u


def flatten(inlist, ltype=(list, tuple), maxint=sys.maxsize):
    """Flatten out a list."""
    try:
        # for every possible index
        for ind in range(maxint):
            # while that index currently holds a list
            while isinstance(inlist[ind], ltype):
                # expand that list into the index (and subsequent indices)
                inlist[ind : ind + 1] = list(inlist[ind])
                # ind = ind+1
    except IndexError:
        pass
    return inlist

def haversine(lat0, lon0, lat1, lon1):
    R = 6378137.0
    lat0 = lat0*math.pi/180
    lat1 = lat1*math.pi/180
    lon0 = lon0*math.pi/180
    lon1 = lon1*math.pi/180

    sdlat_2 = math.sin(0.5*(lat0 - lat1))
    sdlon_2 = math.sin(0.5*(lon0 - lon1))

    a = sdlat_2*sdlat_2 + math.cos(lat0)*math.cos(lat1)*sdlon_2*sdlon_2
    if a >= 1 or a <= 0:
        return 0

    return 2.0*R*math.asin(math.sqrt(a))

def ddmm2dd(x):
    """Converts a lat/long from ddmm.mmm to dd.dddd

    Input: x - float in ddmm.mm format

    Returns: dd.ddd format of input

    Raises:
    """
    return float(int(x / 100.0) + math.fmod(x, 100.0) / 60.0)


def dd2ddmm(x):
    """Converts a lat/long from dd.dddd to ddmm.mmm

    Input: x - float in dd.ddd format

    Returns: ddmm.mm format of input

    Raises:
    """
    dd = int(x)
    return dd * 100.0 + (x - dd) * 60.0


def format_lat_lon_dd(lat_lon_dd, fmt, is_lat):
    """Formats a dd.dd lat or lon to a better output format"""
    return format_lat_lon(dd2ddmm(lat_lon_dd), fmt, is_lat)


def format_lat_lon(lat_lon, fmt, is_lat):
    """Formats a ddmm.mm lat or lon to a better output format"""
    if is_lat:
        prefix = "N" if lat_lon > 0 else "S"
    else:
        prefix = "E" if lat_lon > 0 else "W"

    if fmt.lower() == "ddmm":
        # DD MM.MM
        degrees = int(math.fabs(lat_lon / 100.0))
        minutes, _ = math.modf(math.fabs(lat_lon) / 100.0)
        minutes = minutes * 100.0
        return "%s%d %.4f" % (prefix, degrees, minutes)
    elif fmt.lower() == "nmea":
        degrees = int(math.fabs(lat_lon / 100.0))
        minutes, _ = math.modf(math.fabs(lat_lon) / 100.0)
        minutes = minutes * 100.0
        if is_lat:
            return "%02d%.4f,%s" % (degrees, minutes, prefix)
        else:
            return "%03d%.4f,%s" % (degrees, minutes, prefix)
    elif fmt.lower() == "ddmmss":
        # DD MM MM.SS
        degrees = int(math.fabs(lat_lon / 100.0))
        minutes, _ = math.modf(math.fabs(lat_lon) / 100.0)
        seconds, minutes = math.modf(minutes * 100.0)
        seconds = math.fmod(seconds * 60.0, 100.0)
        minutes = int(minutes)
        return "%s%d %d %.2f" % (prefix, degrees, minutes, seconds)
    elif fmt.lower() == "dd":
        # DD.DD
        return "%s%.6f" % (prefix, math.fabs(ddmm2dd(lat_lon)))
    else:
        return "%.4f" % lat_lon


#
# Lock file primitives
#
def create_lock_file(base_opts, base_lockfile_name):
    """Creates a lock file, with the process id as the contents

    Returns:
        0 - success
        -1 - failure
    Raises:
        No exceptions are raised
    """
    lock_file_name = os.path.expanduser(
        os.path.join(base_opts.mission_dir, base_lockfile_name)
    )
    try:
        fo = open(lock_file_name, "w")
        fo.write("%d" % os.getpid())
        fo.close()
    except:
        log_error("Could not create %s" % lock_file_name, "exc")
        return -1
    else:
        return 0


def cleanup_lock_file(base_opts, base_lockfile_name):
    """Removes the lock file

    Returns:
        0 - success
        -1 - failure

    Raises:
        No excpetions are raised
    """
    lock_file_name = os.path.expanduser(
        os.path.join(base_opts.mission_dir, base_lockfile_name)
    )
    try:
        os.remove(lock_file_name)
    except:
        log_error("Could not remove %s" % lock_file_name, "exc")
        return -1
    else:
        return 0


def check_for_pid(pid):
    """Checks for a pid on the system

    Returns:
        True - PID exists
        False - PID does not exist
    """
    try:
        os.kill(pid, 0)
        return True
    except OSError as err:
        return err.errno == errno.EPERM


def wait_for_pid(pid, timeout):
    """Waits for a pid to disappear from the system, bounded by the timeout

    Returns:
        True - PID still exists at the end of the timeout
        False - PID does not exist at or before the end of the timeout
    """
    time_quit = time.time() + timeout + 1
    # print time.time(), time_quit
    while time.time() < time_quit:
        if not check_for_pid(pid):
            return False
        time.sleep(1)

    return True


def check_lock_file(base_opts, base_lockfile_name):
    """Check the lock files contents and if exists, check to see if the pid in the lockfile still exists in the system

    Returns:
        0 - lock file did not exist, or lock file is orphaned
        -1 - there was an error accessing the lock file
        >0 - the process id found in the lock file
    """
    if base_opts.ignore_lock:
        log_warning("Lock file check ignored due to user options")
        return 0
    else:
        lock_file_name = os.path.expanduser(
            os.path.join(base_opts.mission_dir, base_lockfile_name)
        )
        if os.path.exists(lock_file_name):
            try:
                fi = open(lock_file_name, "r")
            except:
                log_error(
                    "Could not open the log file to check PID - ignoring PID check"
                )
                # Try to clean it up anyway
                return cleanup_lock_file(base_opts, base_lockfile_name)
            else:
                try:
                    previous_pid = int(fi.read())
                except:
                    log_error("Error fetching pid from lockfile", "exc")
                    cleanup_lock_file(base_opts, base_lockfile_name)
                    return -1
                if check_for_pid(previous_pid):
                    return previous_pid
                else:
                    log_error(
                        "Previous conversion (pid: %d) went away without cleaning lock file - eliminating lock file and continuing"
                        % previous_pid
                    )
                    return cleanup_lock_file(base_opts, base_lockfile_name)
        else:
            return 0


def bzip_decompress(input_file_name, output_file_name):
    """Decompess the input name to the output name
    Return 0 for success, 1 for failure
    """
    try:
        input_file = open(input_file_name, "rb")
    except IOError as exception:
        log_error("Could not open %s (%s)" % (input_file_name, exception.args))
        return 1

    try:
        output_file = open(output_file_name, "wb")
    except IOError as exception:
        log_error("Could not open %s (%s)" % (output_file_name, exception.args))
        return 1

    try:
        data = input_file.read()
    except IOError as exception:
        log_error("Could not read %s (%s)" % (input_file_name, exception.args))
        return 1

    try:
        data_out = bz2.decompress(data)
    except:
        log_error("Could not decompress %s (%s)" % (input_file_name, exception.args))
        return 1

    try:
        output_file.write(data_out)
    except:
        log_error("Could not write to %s (%s)" % (output_file_name, exception.args))
        return 1

    input_file.close()
    output_file.close()
    return 0


class Timeout(Exception):
    """Defines an exception for timeout to system call"""


def _timeout(x, y):
    """Raises the timeout exception"""
    raise Timeout()


def which(program):
    """Searches PATH for a program"""

    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, _ = os.path.split(program)
    if fpath:
        if is_exe(program):
            return program
    else:
        for path in os.environ["PATH"].split(os.pathsep):
            exe_file = os.path.join(path, program)
            if is_exe(exe_file):
                return exe_file

    return None


def check_call(cmd, use_shell=False):
    """Wrapper for check_call in subproccess"""
    if not use_shell:
        cmd = cmd.split()
        cmd[0] = which(cmd[0])
    try:
        subprocess.check_call(cmd, shell=use_shell)
    except subprocess.CalledProcessError as grepexc:
        #  print "error code", grepexc.returncode, grepexc.output
        return grepexc.returncode
    else:
        return 0


def run_cmd_shell(cmd, timeout=None, shell=True):
    """Runs a program with arguments in a shell context"""
    if not shell:
        cmd = cmd.split()
        cmd[0] = which(cmd[0])

    p = subprocess.Popen(
        cmd,
        shell=shell,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        close_fds=True,
    )
    if timeout is None:
        # sts >> 8 to get return code
        _, sts = os.waitpid(p.pid, 0)
    else:
        handler = signal.signal(signal.SIGALRM, _timeout)
        try:
            signal.alarm(timeout)
            _, sts = os.waitpid(p.pid, 0)
        except:
            log_error("Timeout running (%s)" % cmd, "exc")
            sts = None
        finally:
            signal.signal(signal.SIGALRM, handler)
            signal.alarm(0)

    return (sts, p.stdout)


def read_eng_file(eng_file_name):
    """Reads and eng file, returning the column headers and data in a dictionary

    Returns:
        Dictionary with eng file headers and data if successful
        None if failed to parse eng file
    """
    # Change this to look specifically for the %columns: format

    # columns_header_pattern = re.compile("^%(?P<header>.*?):(?P<value>.*)")
    columns_header_pattern = re.compile(r"^%columns:\s*(?P<value>.*)")

    try:
        eng_file = open(eng_file_name, "r")
    except IOError:
        log_error("Could not open %s for reading" % (eng_file_name))
        return None

    line_count = 0
    rows = []
    data_column_headers = []
    file_header = []
    while True:
        eng_line_temp = eng_file.readline()
        # log_debug("[%s]" % eng_line_temp)
        if eng_line_temp == "":
            break
        eng_line = eng_line_temp.rstrip().rstrip()
        line_count = line_count + 1
        if eng_line.find("%data") != -1:
            break

        # Record the file header lines
        file_header.append(eng_line)

        # Look for the data column headers line
        m = columns_header_pattern.match(eng_line)
        if m:
            for col_head in m.group("value").rstrip().lstrip().split(","):
                data_column_headers.append(col_head)

    if not data_column_headers:
        return None

    # Process the data
    while True:
        eng_line_temp = eng_file.readline()
        # log_debug("[%s]" % eng_line_temp)
        if eng_line_temp == "":  # EOF?
            break
        eng_line = eng_line_temp.rstrip()
        line_count = line_count + 1
        if eng_line[0] == "%":
            continue
        raw_strs = eng_line.split()
        row = []
        for i in range(len(raw_strs)):
            if (raw_strs[i])[0:1] == "N":
                row.append(np.nan)
            else:
                try:
                    row.append(np.float64(raw_strs[i]))
                except:
                    log_error(
                        "Problems converting [%s] to float from line [%s] (%s, line %d)"
                        % (raw_strs[i], eng_line, eng_file_name, line_count)
                    )
                    continue

        rows.append(row)

    if not rows:
        return None

    tmp = np.array(rows, np.float64)
    data = {}
    for i in range(len(data_column_headers)):
        data[data_column_headers[i]] = tmp[:, i]

    eng_file.close()
    # log_info("Eng file col headers %s" % data.keys())
    return {"file_header": file_header, "data": data}


def ctr_1st_diff(y, x):
    """Compute centered first-difference approximation to the
    first derivative of y with respect to x.

    Usage: ctr_1st_diff(y, x)

    Input: two scalar arrays of equal length

    Returns: dy/dx

    Raises:
      Any exceptions raised are considered critical errors and not expected
    Note:
      This was called ctr1stdiffderiv in the original MATLAB code
    """

    # Check for equal length of scalar arrays
    if len(y) != len(x):
        log_error("Lengths of scalar arrays are unequal -- bailing out of ctr_1st_diff")
        return 1

    dydx = np.array(np.zeros(len(y)), float)
    end = len(x) - 1
    dydx[1:end] = (y[2:] - y[0 : end - 1]) / (x[2:] - x[0 : end - 1])
    dydx[0] = (y[1] - y[0]) / (x[1] - x[0])
    dydx[end] = (y[end] - y[end - 1]) / (x[end] - x[end - 1])
    return dydx


def pol2cart(theta, r):
    """theta in radians"""
    z = r * np.exp(1j * theta)  # convert to complex
    return np.real(z), np.imag(z)


def cart2pol(x, y):
    """returns theta (radians), r"""
    z = x + 1j * y  # convert to complex
    return np.angle(z), np.abs(z)


# http://staff.washington.edu/bdjwww/medfilt.py
def medfilt1(x=None, L=None):
    """
    A simple median filter for 1d numpy arrays.

    Performs a discrete one-dimensional median filter with window
    length L to input vector x. produces a vector the same size
    as x. Boundaries handled by shrinking L at edges; no data
    outside of x used in producing the median filtered output.
    (upon error or exception, returns None.)

    inputs:
        x, Python 1d list or tuple or Numpy array
        L, median filter window length
    output:
        xout, Numpy 1d array of median filtered result; same size as x

    bdj, 5-jun-2009
    """

    # input checks and adjustments --------------------------------------------
    try:
        N = len(x)
        if N < 2:
            log_error("Input sequence too short: length = %d" % N)
            return None
        elif L < 2:
            log_error("Input filter window length too short: L = %d" % L)
            return None
        elif L > N:
            log_error(
                "Input filter window length too long: L = %d, len(x) = %d" % (L, N)
            )
            return None
    except:
        log_error("Input data must be a sequence", "exc")
        return None

    xin = np.array(x)
    if xin.ndim != 1:
        log_error("Input sequence has to be 1d: ndim = %d" % xin.ndim)
        return None

    xout = np.zeros(xin.size)

    # ensure L is odd integer so median requires no interpolation
    L = int(L)
    if L % 2 == 0:  # if even, make odd
        L += 1
    else:  # already odd
        pass
    Lwing = (L - 1) // 2

    # body --------------------------------------------------------------------

    for i, _ in enumerate(xin):

        # left boundary (Lwing terms)
        if i < Lwing:
            xout[i] = np.median(xin[0 : i + Lwing + 1])  # (0 to i+Lwing)

        # right boundary (Lwing terms)
        elif i >= N - Lwing:
            xout[i] = np.median(xin[i - Lwing : N])  # (i-Lwing to N-1)

        # middle (N - 2*Lwing terms; input vector and filter window overlap completely)
        else:
            xout[i] = np.median(xin[i - Lwing : i + Lwing + 1])  # (i-Lwing to i+Lwing)

    return xout


def intersect(list1, list2):
    """Return the intersection of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set intersection

    Raises:
    None
    """
    return np.intersect1d(np.array(list1, object), np.array(list2, object)).tolist()


def union(list1, list2):
    """Return the union of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set union

    Raises:
    None
    """
    # ensures unique()
    return np.union1d(np.array(list1, object), np.array(list2, object)).tolist()
    # return union1d(array(list1), array(list2)).tolist()


def setdiff(list1, list2):
    """Return the set difference of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set difference

    Raises:
    None
    """
    return np.setdiff1d(np.array(list1, object), np.array(list2, object)).tolist()


def sort_i(list1):
    """Sort a list of indices, returning a list
    Handles arrays

    Inputs:
    list1 - the list or array

    Returns:
    a list, sorted ascending

    Raises:
    None
    """
    list1 = np.sort(list1)
    return list1.tolist()


def index_i(list1, list_i):
    """Return a list of elements of list1 selected by indicices in list_i
    E.g., under numpy list1[list_i] but handles lists and returns lists...

    Inputs:
    list1 - the list or array
    list_i - the list or array of indices

    Returns:
    a list of elements

    Raises:
    None
    """
    return np.array(list1)[list_i].tolist()


def succinct_elts(elts, matlab_offset=1):
    """Return a string of elts, succinctly showing runs of consecutive values, if any
    Inputs:
    elts - a set of integers
    matlab_offset - offset to use if these are NOT indices

    Returns:
    selts - a succinct string

    Raises:
    None
    """
    elts = np.sort(unique(elts))
    elts = elts + matlab_offset
    selts = ""
    prefix = ""
    num_elts = len(elts)
    if num_elts:
        diff_elts = np.diff(elts)
        breaks_i_v = [i for i in range(len(diff_elts)) if diff_elts[i] > 1]
        breaks_i_v.append(len(elts) - 1)  # add the final point
        last_i = 0
        for break_i in breaks_i_v:
            nelts = elts[break_i] - elts[last_i]
            if nelts == 0:
                selts = "%s%s%d" % (selts, prefix, elts[break_i])
            elif nelts == 1:
                selts = "%s%s%d %d" % (selts, prefix, elts[last_i], elts[break_i])
            else:
                selts = "%s%s%d:%d" % (selts, prefix, elts[last_i], elts[break_i])
            last_i = break_i + 1
            prefix = " "
    return selts


def get_key(dict_d, key, default=None):
    """Looks for key in dict_d, returns that value otherwise returns default (like getattr but for dicts)"""
    try:
        return dict_d[key]
    except KeyError:
        return default


def Oxford_comma(strings, connector="and"):
    """Returns a string of string elements, in given order, serial comma-separated according to the Oxford rule."""
    n = len(strings)
    if n == 0:
        return ""
    elif n == 1:
        return strings[0]
    elif n == 2:
        return "%s and %s" % (strings[0], strings[1])
    else:
        string = ""
        for i in range(n):
            string = "%s%s, " % (string, strings[i])
            if i == n - 2:
                string = "%s%s %s" % (string, connector, strings[i + 1])
                break
        return string


def ensure_basename(basename):
    """Returns basename with problematic filename characters replaced

    Inputs:
    basename - string

    Returns:
    basename possibly modified

    Raises:
    None
    """
    return (
        basename.replace(" ", "_").replace(",", "_").replace("/", "_").replace("&", "_")
    )


def check_versions():
    """Checks and reports versions of various libraries"""

    log_info(
        "Basestation version: %s; QC version: %s"
        % (Globals.basestation_version, Globals.quality_control_version)
    )

    # Check python version
    log_info(
        "Python version %d.%d.%d"
        % (sys.version_info[0], sys.version_info[1], sys.version_info[2])
    )
    if sys.version_info < Globals.required_python_version:
        msg = "python %s or greater required" % str(Globals.required_python_version)
        log_critical(msg)
        raise RuntimeError(msg)
    if sys.version_info < Globals.recommended_python_version:
        log_warning(
            "python %s or greater recomemnded" % str(Globals.recommended_python_version)
        )

    # Check numpy version
    log_info("Numpy version %s" % np.__version__)
    if normalize_version(np.__version__) < normalize_version(
        Globals.required_numpy_version
    ):
        msg = "Numpy %s or greater required" % Globals.required_numpy_version
        log_critical(msg)
        raise RuntimeError(msg)
    if normalize_version(np.__version__) < normalize_version(
        Globals.recommended_numpy_version
    ):
        log_warning(
            "Numpy %s or greater recomemnded" % Globals.recommended_numpy_version
        )

    # Check scipy version
    log_info("Scipy version %s" % scipy.__version__)
    if normalize_version(scipy.__version__) < normalize_version(
        Globals.required_scipy_version
    ):
        msg = "Scipy %s or greater required" % Globals.required_scipy_version
        log_critical(msg)
        raise RuntimeError(msg)
    if normalize_version(scipy.__version__) < normalize_version(
        Globals.recommended_scipy_version
    ):
        log_warning(
            "SciPy %s or greater recomemnded" % Globals.recommended_scipy_version
        )

    # Check seawater version
    if hasattr(seawater, "__version__"):
        seawater_version = seawater.__version__
    else:
        seawater_version = "1.1.0"

    log_info("seawater version %s" % seawater_version)
    if normalize_version(seawater_version) < normalize_version(
        Globals.required_seawater_version
    ):
        msg = (
            "Seawater version %s or greater required"
            % Globals.required_seawater_version
        )
        log_critical(msg)
        raise RuntimeError(msg)

    # TODO - deal with "post" in gsw version
    # Check GSW Toolkit Version
    # log_info("gsw version %s" % gsw.__version__)
    # if normalize_version(gsw.__version__) < normalize_version(
    #     Globals.required_gsw_version
    # ):
    #     msg = "gsw version %s or greater required" % Globals.required_gsw_version
    #     log_critical(msg)
    #     raise RuntimeError(msg)


def normalize_version(v):
    """Normalizes version stamps"""
    if not isinstance(v, str):
        v = str(
            v
        )  # very old versions of base_station_version for example were stored as floats
    return [int(x) for x in re.sub(r"(\.0+)*$", "", v).split(".")]


def is_integer(s):
    """Test a string to see if converts to an integer"""
    try:
        int(s)
        return True
    except ValueError:
        return False


def is_float(s):
    """Test a string to see if converts to an float"""
    try:
        float(s)
        return True
    except:
        return False


def remap_column_names(replace_dict, column_names=None):
    """
    Called from various sensor extensions to remap column headers from older .eng files to
    current naming standards for netCDF output.  Updates column_names by side-effect and
    preserves order of names.

    Returns:
    0 - at least one column name replaced
    1 - no replacements made
    """
    if column_names is None:
        log_error(
            "No column names supplied for remap_engfile_columns_netcdf conversion - version mismatch?"
        )
        return -1  # return 1?
    ret_val = 1
    for old_name, new_name in list(replace_dict.items()):
        if old_name in column_names:
            log_debug("Replacing %s with %s" % (old_name, new_name))
            column_names[column_names.index(old_name)] = new_name
            ret_val = 0
    return ret_val


def remap_dict_from_sg_calib(calib_consts, remap_str):
    """
    Retries a remap dictionary from the sg_calib_constants.m variable remap_eng_cols.
    This variable is of the form remap_eng_cols='oldname:newname,oldname,newname';
    """
    if remap_str in calib_consts:
        remap_dict = {}
        try:
            splits = calib_consts[remap_str].split(",")
            for s in splits:
                k, v = s.split(":")
                remap_dict[k.strip()] = v.strip()
            return remap_dict
        except:
            log_error(
                "Could not process remap_eng_cols from sg_calib_contants.m (%s)", "exc"
            )
            return None
    return None


def nearest_indices(first_values_v, second_values_v):
    """For each entry in first_values_v, find the index of the nearest second_values_v
    Assumes both values_v arrays increase monotonically
    NOTE: It is possible for indices to be duplicated; return indices where that occurred
    """
    first_np = len(first_values_v)
    second_np = len(second_values_v)
    indices_v = []
    duplicates_v = []  # location of any duplicated indices
    last_i = 0  # (re)start here
    for first_i in range(first_np):
        first_time = first_values_v[first_i]
        idx = last_i
        while idx < second_np - 1:  # ensure we never return an index > second_np
            second_time = second_values_v[idx]
            if second_time >= first_time:
                break
            idx += 1  # move along
        if last_i and last_i == idx:
            duplicates_v.append(
                first_i
            )  # this value in the first has a duplicate index from the second
        last_i = idx  # restart search here
        indices_v.append(idx)
    return indices_v, duplicates_v


def interp1d(first_epoch_time_s_v, data_v, second_epoch_time_s_v, kind="linear"):
    """For each data point data_v at first_epoch_time_s_v, determine the value at second_epoch_time_s_v
    Interpolate according to type
    Assumes both epoch_time_s_v arrays increase monotonically
    Ensures first_epoch_time_s_v and data_v cover second_epoch_time_s_v using 'nearest' values
    """
    # add 'nearest' data item to the ends of data and first_epoch_time_s_v
    if second_epoch_time_s_v[0] < first_epoch_time_s_v[0]:
        # Copy the first value below the interpolation range
        data_v = np.append(np.array([data_v[0]]), data_v)
        first_epoch_time_s_v = np.append(
            np.array([second_epoch_time_s_v[0]]), first_epoch_time_s_v
        )

    if second_epoch_time_s_v[-1] > first_epoch_time_s_v[-1]:
        # Copy the last value above the interpolation range
        data_v = np.append(data_v, np.array([data_v[-1]]))
        first_epoch_time_s_v = np.append(
            first_epoch_time_s_v, np.array([second_epoch_time_s_v[-1]])
        )

    interp_data_v = scipy.interpolate.interp1d(first_epoch_time_s_v, data_v, kind=kind)(
        second_epoch_time_s_v
    )
    return interp_data_v


def invert_sparton_correction(
    corrected_angle_degrees_v, prc_degrees_v, coef0, coef1, coef2, coef3
):
    """Given corrected angles (pitch or roll) and the alternative (roll or pitch)
    corrected angles, plus the correction coefficients (for pitch or roll)
    compute the originally measured angles from the compass
    """
    # Newton-Raphson on our pitch/roll eqn
    corrected_angle_radians_v = np.radians(corrected_angle_degrees_v)
    prc_radians_v = np.radians(prc_degrees_v)
    const = coef0 + coef3 * np.sin(prc_radians_v) - corrected_angle_radians_v
    measured = corrected_angle_radians_v  # this is a good starting guess
    threshold = math.radians(0.001)  # compute to the nearest 1/100th of a degree
    diff = np.array([1.0])  # at least one loop
    while max(abs(diff)) > threshold:
        # derivative of our correction eqn
        diff = (const + coef1 * measured + coef2 * np.sin(measured)) / (
            coef1 + coef2 * np.cos(measured)
        )
        measured = measured - diff
    return np.degrees(measured)


# TODO rename this function oxygen_solubility_air?  and the doc on the nc variable
def compute_oxygen_saturation(temp_cor_v, salin_cor_v):
    """Compute (max) oxygen saturation (solubility) (uM/L)
    at standard air and pressure (1013hPa) for fresh and seawater at given temperature and salinity

    Garcia and Gordon, 'Oxygen solubility in seawater: Better fitting equations'
    Limnol. Oceanogr. 37(6), 1992 1307-1312
    Equation (8) page 1310
    """
    # Constants for calculation of Oxygen saturation,
    # which depends on temperature and salinity only

    # Note: Argo uses the Benson and Krause constants (first column, Table 1)
    # SBE43 documentation also uses the Benson and Krause constants.
    # Only Aanderaa uses the 'combined fit' constants.
    # if False:
    #     # 'combined fit'
    #     A = [2.00856, 3.22400, 3.99063, 4.80299, 0.978188, 1.71096]
    #     B = [6.24097e-3, 6.93498e-3, 6.90358e-3, 4.29155e-3]
    #     C0 = -3.11680e-7
    #     # Utils.compute_oxygen_saturation(array([10]),array([35])) # = [array([ 440.40191284]), array([ 352.59215692]), array([ 1.24904058])]
    # else:

    # Benson & Krause constants, which Argo prefers, and which Garcia and Gordon recommend (last para)
    A = [2.009070, 3.220140, 4.050100, 4.944570, -0.256847, 3.887670]
    B = [-6.24523e-3, -7.37614e-3, -1.0341e-2, -8.17083e-3]
    C0 = -4.88682e-7
    # 282.0149 is 6.318*44.6596, where 6.318 is the check value in G&G
    # Utils.compute_oxygen_saturation(array([10.0]), array([35.0])) # = [array([ 282.01498073]), array([ 352.75484586]), array([ 0.79946451])]

    A.reverse()  # fliplr()
    B.reverse()  # fliplr()

    Kelvin_offset = 273.15  # for 0 deg C

    with np.errstate(invalid="ignore"):
        temp_cor_K_scaled_v = np.log(
            ((Kelvin_offset + 25.0) - temp_cor_v) / (Kelvin_offset + temp_cor_v)
        )

    oxygen_sat_fresh_water_v = np.exp(np.polyval(A, temp_cor_K_scaled_v))
    # [ml/L] based only on temperature
    oxygen_sat_salinity_adjustment_v = np.exp(
        salin_cor_v * np.polyval(B, temp_cor_K_scaled_v)
        + C0 * salin_cor_v * salin_cor_v
    )  # adjustment factor
    oxygen_sat_seawater_v = (
        oxygen_sat_salinity_adjustment_v * oxygen_sat_fresh_water_v
    )  # [ml/L]

    # NOTE: SBE43 corrections use 44.6596, which is the real gas constant.
    # Aanderaa used 44.6145, the ideal gas constant, (as shown in several of their older manuals)
    # but have gone to the real constant as of 11/2013.
    # Thierry et. al, 2011 report: The value of 44.6596 is derived from the molar volume of the oxygen gas,
    # 22.3916 L/mole, at standard temperature and pressure (0C, 1 atmosphere; e.g., Garcia and Gordon, 1992).
    # so 1/22.3916 = 0.446596 M/L
    o2_molar_mass = 44.6596
    #  uM/L of oxygen at standard pressure and temperature
    # relative_sat_v = measured_molar_oxygen_concentration_v/oxygen_sat_v * 100 # relative O2 saturation (percent)
    return [
        oxygen_sat_seawater_v * o2_molar_mass,  # uM/L
        oxygen_sat_fresh_water_v * o2_molar_mass,  # uM/L
        oxygen_sat_salinity_adjustment_v,
    ]  # scale factor


def nan_helper(y):
    """Helper to handle indices and logical indices of NaNs.

    Input:
        - y, 1d numpy array with possible NaNs
    Output:
        - nans, logical indices of NaNs
        - index, a function, with signature indices= index(logical_indices),
          to convert logical indices of NaNs to 'equivalent' indices
    Example:
        >>> # linear interpolation of NaNs
        >>> nans, x= nan_helper(y)
        >>> y[nans]= np.interp(x(nans), x(~nans), y[~nans])
    """
    return np.isnan(y), lambda z: z.nonzero()[0]


def basestation_cmp_function(a, b):
    """Compares two archived targets files, sorting in reverse chronilogical order (most recent one first)
    based on standard basesation back command file naming convention

    Input:
       a, b - strings containing basestation back input file names
              Note: these name must contain at least the dive postfix

    Returns:
        -1 if a > b
        0 if a == b
        1 if a < b
    """

    def find_dive_counter(file_name):
        """
        Input:
            filename of the form base.XXX or base.XXX.YYY where XXX and YYY are digits
        Return:
            key_value = dive_num * 1000 + counter

        """
        _, base = os.path.split(file_name)
        splits = base.split(".")
        if len(splits) >= 2 and splits[-1].isdigit() and splits[-2].isdigit():
            return (int(splits[-2]) * 1000) + int(splits[-1])
        elif splits[-1].isdigit():
            return int(splits[-1]) * 1000
        else:
            # Note - should never get here as the root file is handled at the outter call
            return 0

    a_key = find_dive_counter(a)
    b_key = find_dive_counter(b)

    if a_key > b_key:
        return -1
    elif a_key < b_key:
        return 1
    else:
        return 0


def find_recent_basestation_file(mission_dir, root_name, root_first=False):
    """
    Finds the most recent input file, using the basestations back file naming convention

    Input:
        mission_dir - directory to search
        root_name - root patterns to look for - cmdfile for example
        root_first - Flag to indicate if the root_name should be first or last

    Returns:
        Fully qualified file name, or None
    """

    def find_root(mission_dir, root_name):
        file_name = os.path.join(mission_dir, root_name)
        if os.path.exists(file_name):
            return file_name
        else:
            return None

    if root_first:
        ret_val = find_root(mission_dir, root_name)
        if ret_val is not None:
            return ret_val

    files = []
    for glob_expr in ("%s.[0-9]*" % root_name, "%s.[0-9]*.[0-9]*" % root_name):
        for match in glob.glob(os.path.join(mission_dir, glob_expr)):
            files.append(match)

    if files:
        files = unique(files)
        files = sorted(files, key=functools.cmp_to_key(basestation_cmp_function))
        # print("Sorted")
        # for ii in files:
        #     print(ii)
        return files[0]

    if not root_first:
        return find_root(mission_dir, root_name)
    else:
        return None


qc_log_type = collections.namedtuple("qc_log_type", ["qc_str", "qc_type", "qc_points"])


def load_qc_pickl(qc_file):
    """Loads QC pickle file"""
    try:
        fi = open(qc_file, "r")
    except:
        return None

    ret_list = []
    while True:
        try:
            x = pickle.load(fi)
        except EOFError:
            break
        ret_list.append(qc_log_type(*x))
    return ret_list


def fix_gps_rollover(struct_time):
    """Fixes time stamps set from GPS units with the epoch rollover bug"""
    if struct_time.tm_year >= 1999 and struct_time.tm_year <= 2001:
        log_warning(
            "GPS Rollover found (%s)" % struct_time, alert="GPSROLLOVER", max_count=5
        )
        tmp = time.mktime(struct_time) + 619315200  # 1024*7*86400
        struct_time = time.gmtime(tmp)
        del tmp
    return struct_time


def density(salinity, temperature, pressure, longitude, latitude):
    """Computes density using the gsw toolbox"""
    salinity_absolute = gsw.SA_from_SP(salinity, pressure, longitude, latitude)
    dens = gsw.rho_t_exact(
        salinity_absolute,
        temperature,
        np.zeros(salinity_absolute.size).reshape(np.shape(salinity_absolute)),
    )
    return dens


def ptemp(salinity, temperature, pressure, longitude, latitude, pref=0.0):
    """Computes potential temperature using the gsw toolbox"""
    salinity_absolute = gsw.SA_from_SP(salinity, pressure, longitude, latitude)
    l_ptemp = gsw.pt_from_t(salinity_absolute, temperature, pressure, pref)
    return l_ptemp


def svel(salinity, temperature, pressure, longitude, latitude):
    """Computes sound velocity using the gsw toolbox"""
    salinity_absolute = gsw.SA_from_SP(salinity, pressure, longitude, latitude)
    l_svel = gsw.sound_speed(salinity_absolute, temperature, pressure)
    return l_svel


def fp(salinity, pressure, longitude, latitude):
    """Calulates seawater freezing point using the gsw toolbox"""
    salinity_absolute = gsw.SA_from_SP(salinity, pressure, longitude, latitude)
    freeze_pt = gsw.t_freezing(
        salinity_absolute, pressure, np.zeros(len(salinity_absolute))
    )
    return freeze_pt


def parse_time(ts, f_gps_rollover=False):
    """Parse a standard time stamp from file header, returning time in epoch seconds"""
    time_parts = ts.split()
    if int(time_parts[2]) - 100 < 0:
        year_part = int(time_parts[2])
    else:
        year_part = int(time_parts[2]) - 100

    if len(time_parts) >= 7:
        sec_part = time_parts[5]
        dec_sec_part = time_parts[6]
    else:
        sec_parts = time_parts[5].split(".")
        sec_part = sec_parts[0]
        if len(sec_parts) == 2:
            _, dec_sec_part = math.modf(float(time_parts[5]))
        else:
            dec_sec_part = 0.0

    time_string = "%s %s %02d %s %s %s" % (
        time_parts[0],
        time_parts[1],
        year_part,
        time_parts[3],
        time_parts[4],
        sec_part,
    )
    time_struct = time.strptime(time_string, "%m %d %y %H %M %S")
    if f_gps_rollover:
        time_struct = fix_gps_rollover(time_struct)
    return time.mktime(time_struct) + (float(dec_sec_part) / 1000.0)


def format_time(t):
    """Formats time for output files"""
    milli, sec = math.modf(t)
    st = time.localtime(sec)

    # year_part = st.tm_year - 1900

    time_string = "%d %d %d %d %d %d %d" % (
        st.tm_mon,
        st.tm_mday,
        st.tm_year - 1900,
        st.tm_hour,
        st.tm_min,
        st.tm_sec,
        milli * 1000.0,
    )
    return time_string


RTD = 57.29578  # radians to degrees (180./acos(-1.)) 180./3.14159265
DTR = 0.0174532925  # degrees to radians 3.14159265/180.
METERS_PER_DEG = 111120.0  # 60*METERS_PER_N


def bearing(lat0, lon0, lat1, lon1):
    """Returns the bearing and range from current_pos
    target_pos

    Input:
      lat0, lon0 - current position (decimal degrees)
      lat1, lon1 - target position (decimal degrees)

    Returns:
      (rng, bear) where:
      rng - range in meters
      bear - bearning in degrees true
    """
    diff = METERS_PER_DEG * math.cos(lat1 * DTR)
    x = -(lon0 - lon1) * diff
    y = (lat1 - lat0) * METERS_PER_DEG

    rng = math.sqrt(x * x + y * y) / 1000.0

    bear = math.atan2(x, y) * RTD

    if bear > 360.0:
        bear = math.fmod(bear, 360.0)
    if bear < 0.0:
        bear = math.fmod(bear, 360.0) + 360.0

    return (rng, bear)


def synthesize_lat_lon(lat, lon, bear, rng):
    """Generate a new lat/lon

    Input:
        lat, lon - starting position
        bear - heading to new position in degrees
        rng - distance to new position in meters

    Returns:
        new position as (lat,lon) tuple in decimal degress
    """
    range_deg = rng / METERS_PER_DEG

    # convert nav bear to polar radians
    head_rad = (360.0 + 90.0) - bear
    if head_rad > 360.0:
        head_rad -= 360.0

    head_rad /= RTD  # radians

    deg = lat + math.sin(head_rad) * range_deg
    if deg > 90.0:
        deg -= 90.0  # over the North Pole
    elif deg < -90.0:
        deg += 90.0  # over the South poll
    newlat = deg

    # adjust longitude distance according to latitude
    deg = lon + math.cos(head_rad) * range_deg / math.cos(deg * DTR)
    # make mod 180
    if deg > 180.0:
        deg -= 360.0  # around the world from Greenwich W, so make E
    elif deg < -180.0:
        deg += 360.0  # around the world from Greenwich E, so make W
    newlon = deg

    return (newlat, newlon)


def average_position(gps_a_lat, gps_a_lon, gps_b_lat, gps_b_lon):
    """Given two gps positions in D.D format,
    calculate the mean position between them, based on the great cicle route
    """
    gps_a_lat_rad = math.radians(gps_a_lat)
    gps_a_lon_rad = math.radians(gps_a_lon)
    gps_b_lat_rad = math.radians(gps_b_lat)
    delta_lon_rad = math.radians(gps_b_lon - gps_a_lon)

    b_x = math.cos(gps_b_lat_rad) * math.cos(delta_lon_rad)
    b_y = math.cos(gps_b_lat_rad) * math.sin(delta_lon_rad)

    gps_mean_lat = math.atan2(
        math.sin(gps_a_lat_rad) + math.sin(gps_b_lat_rad),
        math.sqrt(
            (math.cos(gps_a_lat_rad) + b_x) * (math.cos(gps_a_lat_rad) + b_x)
            + (b_y * b_y)
        ),
    )
    gps_mean_lon = gps_a_lon_rad + math.atan2(b_y, math.cos(gps_a_lat_rad) + b_x)

    return (math.degrees(gps_mean_lat), math.degrees(gps_mean_lon))


def loadmodule(pathname):
    """Loads a module and returns a module handle

    pathname - fully qualified path to the module to be loaded

    Return:
       None - error
       Module object - success

    """
    # Fast path: see if the module has already been imported.
    _, name = os.path.split(pathname)
    name, _ = os.path.splitext(name)

    try:
        return sys.modules[name]
    except:
        pass

    # If any of the following calls raises an exception,
    # there's a problem we can't handle -- let the caller handle it.
    try:
        spec = importlib.util.spec_from_file_location(name, pathname)
        mod = importlib.util.module_from_spec(spec)
        sys.modules["module.name"] = mod
        spec.loader.exec_module(mod)
        return mod
    except:
        log_error(f"Error loading {pathname}", "exc")
        log_info("No module loaded")
    return None


def open_mission_database(base_opts: BaseOpts.BaseOptions) -> sqlite3.Connection:
    """Opens a mission database file"""
    if not base_opts.mission_dir:
        log_error("mission_dir is not set")
        return None
    if not base_opts.instrument_id:
        log_error("instrument_id is not set")
        return None
    db = os.path.join(base_opts.mission_dir, f"sg{base_opts.instrument_id:03d}.db")
    if not os.path.exists(db):
        log_error(f"{db} does not exist")
        return None
    return sqlite3.connect(db)


def dive_var_trend(base_opts, dive_col, y_col):
    """Get the trend (dive over dive slope) of a dive variable"""

    p_dives_back = (
        base_opts.mission_trends_dives_back
        if dive_col[-1] >= base_opts.mission_trends_dives_back
        else dive_col[-1]
    )

    m, b = np.polyfit(dive_col[-p_dives_back:], y_col[-p_dives_back:], 1)
    return (m, b)


def estimate_endurance(base_opts, dive_col, gauge_col, dive_times, dive_end):
    """Estimate endurace from normalized remaining battery capacity"""
    # print(dive_col)
    p_dives_back = (
        base_opts.mission_energy_dives_back
        if dive_col[-1] >= base_opts.mission_energy_dives_back
        else dive_col[-1]
    )

    m, b = np.polyfit(dive_col[-p_dives_back:], gauge_col[-p_dives_back:], 1)
    log_info(f"m:{m} b:{b}")
    lastdive_num = np.int32((base_opts.mission_energy_reserve_percent - b) / m)
    dives_remaining = lastdive_num - dive_col[-1]
    secs_remaining = dives_remaining * np.mean(dive_times[-p_dives_back:])
    end_date = time.strftime(
        "%Y-%m-%dT%H:%M:%SZ", time.gmtime(dive_end[-1] + secs_remaining)
    )
    days_remaining = secs_remaining / (24.0 * 3600.0)

    return (dives_remaining, days_remaining, end_date)


def extract_calib_consts(dive_nc_file):
    """Extracts the calibration constants from the netCDF file

    Input:
    dive_nc_file - Open dive netcdf file

    Returns:
    calib_consts - calibration constants dictionary
    """

    calib_consts = {}

    sgc_var = re.compile(f"^{BaseNetCDF.nc_sg_cal_prefix}")

    for (dive_nc_varname, nc_var) in list(dive_nc_file.variables.items()):
        nc_is_scalar = len(nc_var.shape) == 0  # treat strings as scalars
        if sgc_var.search(dive_nc_varname):
            _, variable = sgc_var.split(dive_nc_varname)
            if nc_is_scalar:
                calib_consts[variable] = nc_var.getValue()
            else:  # nc_string
                calib_consts[variable] = (
                    nc_var[:].tobytes().decode("utf-8")
                )  # string comments

    return calib_consts

def notifyVis(glider: int, topic: str, body: str):
    # Check for vis.py processes to notify - each main process
    # creates a socket in /tmp so we just glob through there and
    # send notices via zmq

    p = Path('/tmp')
    topic = "{glider:03d}-{topic}"
    for f in p.glob(f'sanic-*-notify.ipc'):
        print(f"connecting to {f}")
        socket = ctx.socket(zmq.PUSH)
        socket.connect(f)
        socket.send_multipart([topic.encode('utf-8'), body.encode('utf-8')])
        socket.close()

