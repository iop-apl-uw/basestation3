#! /usr/bin/env python

## 
## Copyright (c) 2006, 2007, 2009, 2010, 2011, 2012, 2013, 2014, 2015, 2016, 2017, 2018, 2019, 2020 by University of Washington.  All rights reserved.
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
import sys
import os
import math
import time
import imp
import re
import bz2
import subprocess
import signal
from numpy import *
import re
import functools

from BaseLog import *
# cnf files could declare meta data for additional variable names that refer to nc_nan or nc_scalar in various fields
# those are defined in BaseNetCDF and need to be in scope so the eval() call below sees them but...
# from BaseNetCDF import * # fails because of different import race paths betwee Base.py or Reprocess.py
# https://stackoverflow.com/questions/9252543/importerror-cannot-import-name-x
# as running this (attemtped fix) line via Reprocess.py shows...
# from BaseNetCDF import nc_scalar,nc_nan # for meta-data declarations in cnf files
# Traceback (most recent call last):
# ...
#   File "Reprocess.py", line 55, in <module>
#     from CalibConst import getSGCalibrationConstants
#   File "CalibConst.py", line 35, in <module>
#     from BaseNetCDF import *
#   File "BaseNetCDF.py", line 30, in <module>
#     from QC import *
#   File "QC.py", line 32, in <module>
#     import Utils
#   File "Utils.py", line 34, in <module>
#     from BaseNetCDF import nc_scalar,nc_nan # for nc_scalar, etc. in meta-data declarations in cnf files
# ImportError: cannot import name nc_scalar
# So we duplicate these lines here in this module's scope and after numpy import
# TODO: fix delcarations and imports to eliminate circulatities!
nc_nan = array([nan], dtype = float64)[0] # CF1.4 ensure double
nc_scalar = ()
from scipy.io import netcdf
import glob
import socket
from urllib.request import urlopen
import pickle
import collections

def open_netcdf_file(filename, mode='r', mmap=None, version=1): 
    '''A wrapper to handle the fact that mmap does not work on Mac OSX
    Running under Darwin sometimes yields 'Error 24: Too many open files', which is nonsense
    mmap=None says use mmap if you can
    '''
    #return netcdf.netcdf_file(filename,mode,mmap=False if sys.platform == 'darwin' else mmap, version=version)
    return netcdf.netcdf_file(filename, mode, mmap=False, version=version)


col_ncmeta_map_type = collections.namedtuple('col_ncmeta_map_type', ['nc_var_name', 'nc_meta_str'])

def read_cnf_file(conf_file_name, encode_list=True, ensure_list=['column'],lower=True, mission_dir=None, results_d=None):
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
    nc_conf_file_name = conf_file_name.replace('.', '_')
    cnf_file_contents = None
    filename = conf_file_name
    if mission_dir is not None:
        filename = os.path.join(mission_dir, conf_file_name)
    if (os.path.exists(filename)):
        try:
            cnf_file = open(filename, "r")
        except IOError as exception:
            log_debug("Could not open %s (%s)" % (filename, exception.args))
            # fallthrough
        else:
            cnf_file_contents = []
            for conf_line in cnf_file:
                conf_line = conf_line.rstrip() # what about .rstrip(chr(0x1a)) for files uploaded from glider?
                if (conf_line == ""):
                    continue
                # keep comment lines, etc.
                cnf_file_contents.append(conf_line)
            cnf_file.close()
            cnf_file_contents = '\n'.join(cnf_file_contents);

    if (cnf_file_contents is not None):
        if (results_d is not None):
            import BaseNetCDF
            try:
                md = BaseNetCDF.nc_var_metadata[nc_conf_file_name]
            except KeyError:
                md = BaseNetCDF.form_nc_metadata(nc_conf_file_name, False, 'c')
            results_d[nc_conf_file_name] = cnf_file_contents # save/update cnf file contents
    else:
        if (results_d is not None):
            try:
                cnf_file_contents = results_d[nc_conf_file_name] # any saved version?
            except KeyError:
                return (None, None) # nope
        else:
            return (None, None) # neither saved nor file

    cnf_dict = {}
    nc_meta_dict = collections.OrderedDict()
    for conf_line in cnf_file_contents.split('\n'):
        log_debug("Processing %s line (%s)" % (conf_file_name, conf_line))
        if(conf_line[0] == '#'):
            cl = conf_line[1:].rstrip().lstrip()
            if(cl.startswith('(') and cl.endswith(')')):
                # nc meta data adds are potentially included as comments
                # Looks like dimension register - just stash the line 
                try:
                    tmp = col_ncmeta_map_type(*eval(cl))
                except:
                    log_error("Error processing nc meta data in %s (%s)" % (conf_file_name, conf_line), 'exc')
                else:
                    # Confirm format
                    if(tmp.nc_var_name.startswith('register_sensor_dim_info')
                       or ((len(tmp.nc_meta_str) == 4 and isinstance(tmp.nc_meta_str[0], bool) and isinstance(tmp.nc_meta_str[1], str)
                           and isinstance(tmp.nc_meta_str[2], dict) and isinstance(tmp.nc_meta_str[3], tuple)))):
                        nc_meta_dict[tmp.nc_var_name] = tmp.nc_meta_str
                    else:
                        log_error("netcdf meta data in %s (%s) is not formed correctly" % (conf_file_name, conf_line))
            continue # next line
        # parameter=value line
        conf_elts = conf_line.split('=')
        prop = conf_elts[0]
        if lower:
            prop = prop.lower() # Convert to lower case
        value = conf_elts[1]
        try:
            value = int(value)
        except:
            try:
                value = float(value)
            except:
                # TODO? If string is enclosed in "", remove them?
                pass # encode as-is, a string
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
                values = value # use most recent value
        cnf_dict[prop] = values # update
        
    return (cnf_dict, nc_meta_dict)

def unique(s):
    """Return a list of the elements in s, but without duplicates.

    For example, unique([1,2,3,1,2,3]) is some permutation of [1,2,3],
    unique("abcabc") some permutation of ["a", "b", "c"], and
    unique(([1, 2], [2, 3], [1, 2])) some permutation of
    [[2, 3], [1, 2]].

    For best speed, all sequence elements should be hashable.  Then
    unique() will usually work in linear time.

    If not possible, the sequence elements should enjoy a total
    ordering, and if list(s).sort() doesn't raise TypeError it's
    assumed that they do enjoy a total ordering.  Then unique() will
    usually work in O(N*log2(N)) time.

    If that's not possible either, the sequence elements must support
    equality-testing.  Then unique() will usually work in quadratic
    time.
    """

    n = len(s)
    if n == 0:
        return []

    # Try using a dict first, as that's the fastest and will usually
    # work.  If it doesn't work, it will usually fail quickly, so it
    # usually doesn't cost much to *try* it.  It requires that all the
    # sequence elements be hashable, and support equality comparison.
    u = {}
    try:
        for x in s:
            u[x] = 1
    except TypeError:
        del u  # move on to the next method
    else:
        return list(u.keys()) # NOTE This does not preserve sorted order

    # We can't hash all the elements.  Second fastest is to sort,
    # which brings the equal elements together; then duplicates are
    # easy to weed out in a single pass.
    # NOTE:  Python's list.sort() was designed to be efficient in the
    # presence of many duplicate elements.  This isn't true of all
    # sort functions in all languages or libraries, so this approach
    # is more effective in Python than it may be elsewhere.
    try:
        t = sorted(s)
    except TypeError:
        del t  # move on to the next method
    else:
        assert n > 0
        last = t[0]
        lasti = i = 1
        while i < n:
            if t[i] != last:
                t[lasti] = last = t[i]
                lasti += 1
            i += 1
        return t[:lasti]

    # Brute force is all that's left. O(n^2)  TODO Is this ever used?
    u = []
    for x in s:
        if x not in u:
            u.append(x)
    return u

def flatten(inlist, type=type, ltype=(list, tuple), maxint= sys.maxsize):
    """Flatten out a list."""
    try:
        # for every possible index
        for ind in range( maxint):
            # while that index currently holds a list
            while isinstance( inlist[ind], ltype):
                # expand that list into the index (and subsequent indices)
                inlist[ind:ind+1] = list(inlist[ind])
                #ind = ind+1
    except IndexError:
        pass
    return inlist

def cmd(command, input=''):
    """Executes the given command line, returning and in-memory file
    of the output"""
    (i, o) = os.popen4(command)
    if input:
        i.write(input)
    i.close()
    return o

def ddmm2dd(x):
    """Converts a lat/long from ddmm.mmm to dd.dddd

    Input: x - float in ddmm.mm format

    Returns: dd.ddd format of input

    Raises:
    """
    return float(int(x/100.) + math.fmod(x, 100.)/60.)

def dd2ddmm(x):
    """Converts a lat/long from dd.dddd to ddmm.mmm

    Input: x - float in dd.ddd format

    Returns: ddmm.mm format of input

    Raises:
    """
    dd = int(x)
    return dd*100. + (x - dd)*60.

def format_lat_lon_dd(lat_lon_dd, fmt, is_lat):
    """Formats a dd.dd lat or lon to a better output format
    """
    return format_lat_lon(dd2ddmm(lat_lon_dd), fmt, is_lat)


def format_lat_lon(lat_lon, fmt, is_lat):
    """Formats a ddmm.mm lat or lon to a better output format
    """
    if(is_lat):
        prefix = 'N' if lat_lon > 0 else 'S'
    else:
        prefix = 'E' if lat_lon > 0 else 'W'

    if(fmt.lower() == 'ddmm'):
        # DD MM.MM
        degrees = int(math.fabs(lat_lon/100.))
        minutes, _ = math.modf(math.fabs(lat_lon)/100.)
        minutes = minutes * 100.
        return "%s%d %.4f" % (prefix, degrees, minutes )
    elif(fmt.lower() == 'nmea'):
        degrees = int(math.fabs(lat_lon/100.))
        minutes, _ = math.modf(math.fabs(lat_lon)/100.)
        minutes = minutes * 100.
        if (is_lat):
            return "%02d%.4f,%s" % (degrees, minutes, prefix)
        else:
            return "%03d%.4f,%s" % (degrees, minutes, prefix)
    elif(fmt.lower() == 'ddmmss'):
        # DD MM MM.SS
        degrees = int(math.fabs(lat_lon/100.))
        minutes, _ = math.modf(math.fabs(lat_lon)/100.)
        seconds, minutes = math.modf(minutes * 100.)
        seconds = math.fmod(seconds * 60., 100.)
        minutes = int(minutes)
        return "%s%d %d %.2f" % (prefix, degrees, minutes, seconds)
    elif(fmt.lower() == 'dd'):
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
    lock_file_name = os.path.expanduser(os.path.join(base_opts.mission_dir, base_lockfile_name))
    try:
        fo = open(lock_file_name, 'w')
        fo.write("%d" % os.getpid())
        fo.close()
    except:
        log_error("Could not create %s" % lock_file_name, 'exc')
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
    lock_file_name = os.path.expanduser(os.path.join(base_opts.mission_dir, base_lockfile_name))
    try:
        os.remove(lock_file_name)
    except:
        log_error("Could not remove %s" % lock_file_name, 'exc')
        return -1
    else:
        return 0

def check_for_pid(pid):
    """Checks for a pid on the system
    
    Returns:
        True - PID exists
        False - PID does not exist
    """
    import errno

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
    #print time.time(), time_quit
    while(time.time() < time_quit):
        if(not check_for_pid(pid)):
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
    pid_exists = False
    if(base_opts.ignore_lock):
        log_warning('Lock file check ignored due to user options')
        return 0
    else:
        lock_file_name = os.path.expanduser(os.path.join(base_opts.mission_dir, base_lockfile_name))
        if(os.path.exists(lock_file_name)):
            try:
                fi = open(lock_file_name, 'r')
            except:
                log_error("Could not open the log file to check PID - ignoring PID check")
                # Try to clean it up anyway
                return(cleanup_lock_file(base_opts, base_lockfile_name))
            else:
                previous_pid = int(fi.read())
                if(check_for_pid(previous_pid)):
                    return previous_pid
                else:
                    log_error("Previous conversion (pid: %d) went away without cleaning lock file - eliminating lock file and continuing" % previous_pid)
                    return(cleanup_lock_file(base_opts, base_lockfile_name))
        else:
            return 0

def bzip_decompress (input_file_name, output_file_name):
    """Decompess the input name to the output name
    Return 0 for success, 1 for failure
    """
    try:
        input_file = open(input_file_name, 'rb')
    except IOError as exception:
        log_error("Could not open %s (%s)" % (input_file_name, exception.args))
        return 1

    try:
        output_file = open(output_file_name, 'wb')
    except IOError as exception:
        log_error("Could not open %s (%s)" % (output_file__name, exception.args))
        return 1

    try:
        data = input_file.read()
    except IOError as exception:
        log_error("Could not read %s (%s)" % (input_file__name, exception.args))
        return 1

    try:
        data_out = bz2.decompress(data)
    except:
        log_error("Could not decompress %s (%s)" % (input_file__name, exception.args))
        return 1

    try:
        output_file.write(data_out)
    except:
        log_error("Could not write to %s (%s)" % (output_file__name, exception.args))
        return 1
    
    input_file.close()
    output_file.close()
    return 0

class Timeout(Exception): pass
def _timeout(x, y): raise Timeout()

def which(program):
    import os
    def is_exe(fpath):
        return os.path.isfile(fpath) and os.access(fpath, os.X_OK)

    fpath, fname = os.path.split(program)
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
    if not shell:
        cmd = cmd.split()
        cmd[0] = which(cmd[0])
                
    p = subprocess.Popen(cmd, shell=shell, stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, close_fds=True)
    if timeout is None:
        # sts >> 8 to get return code
        pid, sts = os.waitpid(p.pid, 0)
    else:
        handler = signal.signal(signal.SIGALRM, _timeout)
        try:
            signal.alarm(timeout)
            pid, sts =  os.waitpid(p.pid, 0)
        except:
            log_error("Timeout running (%s)" % cmd, 'exc')
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
    in_file = None

    # Change this to look specifically for the %columns: format
    
    #columns_header_pattern = re.compile("^%(?P<header>.*?):(?P<value>.*)")
    columns_header_pattern = re.compile("^%columns:\s*(?P<value>.*)")

    try:
        eng_file = open(eng_file_name, "r")
    except IOError:
        log_error("Could not open %s for reading" % (eng_filename))
        return None

    line_count = 0
    rows = []
    data_column_headers = []
    file_header = []
    while True:
        eng_line_temp = eng_file.readline()
        #log_debug("[%s]" % eng_line_temp)
        if(eng_line_temp == ""):
            break
        eng_line = eng_line_temp.rstrip().rstrip()
        line_count = line_count + 1
        if(eng_line.find("%data") != -1):
            break

        # Record the file header lines 
        file_header.append(eng_line)

        # Look for the data column headers line
        m = columns_header_pattern.match(eng_line)
        if(m):
            for col_head in m.group('value').rstrip().lstrip().split(','):
                data_column_headers.append(col_head)

    if(not data_column_headers):
        return None
    
    # Process the data
    while True:
        eng_line_temp = eng_file.readline()
        #log_debug("[%s]" % eng_line_temp)
        if(eng_line_temp == ""): # EOF?
            break
        eng_line = eng_line_temp.rstrip()
        line_count = line_count + 1
        if(eng_line[0] == '%'):
            continue
        raw_strs = eng_line.split()
        row = []
        for i in range(len(raw_strs)):
            if((raw_strs[i])[0:1] == "N"):
                row.append(nan)
            else:
                try:
                    row.append(float64(raw_strs[i]))
                except:
                    log_error("Problems converting [%s] to float from line [%s] (%s, line %d)"
                                   % (raw_strs[i], eng_line, eng_filename, line_count))
                    continue

        rows.append(row)

    if(not rows):
        return None

    tmp = array(rows, float64)
    data = {}
    for i in range(len(data_column_headers)):
        data[data_column_headers[i]] = tmp[:, i]
        
    eng_file.close()
    #log_info("Eng file col headers %s" % data.keys())
    return {'file_header' : file_header, 'data' : data }

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
    if len(y) !=  len(x):
        log_error("Lengths of scalar arrays are unequal -- bailing out of ctr_1st_diff")
        return 1


    dydx = array(zeros(len(y)), float)
    end = len(x) - 1
    dydx[1:end] = (y[2:] - y[0:end-1])/(x[2:] - x[0:end-1])
    dydx[0] = (y[1] - y[0])/(x[1] - x[0])
    dydx[end] = (y[end] - y[end - 1])/(x[end] - x[end - 1])
    return dydx

# http://staff.washington.edu/bdjwww/medfilt.py
def medfilt1(x=None,L=None):
    '''
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
    '''

    # input checks and adjustments --------------------------------------------
    try:
        N = len(x)
        if N < 2:
            log_error('Input sequence too short: length = %d' % N)
            return None
        elif L < 2:
            log_error('Input filter window length too short: L = %d' % L)
            return None
        elif L > N:
            log_error('Input filter window length too long: L = %d, len(x) = %d'%(L, N))
            return None
    except:
        log_error('Input data must be a sequence', 'exc')
        return None

    xin = array(x)
    if xin.ndim != 1:
        log_error('Input sequence has to be 1d: ndim = %d' % xin.ndim)
        return None
  
    xout = zeros(xin.size)

    # ensure L is odd integer so median requires no interpolation
    L = int(L)
    if L%2 == 0: # if even, make odd
        L += 1 
    else: # already odd
        pass 
    Lwing = (L-1) // 2

    # body --------------------------------------------------------------------

    for i, xi in enumerate(xin):

        # left boundary (Lwing terms)
        if i < Lwing:
            xout[i] = median(xin[0:i+Lwing+1]) # (0 to i+Lwing)

        # right boundary (Lwing terms)
        elif i >= N - Lwing:
            xout[i] = median(xin[i-Lwing:N]) # (i-Lwing to N-1)
          
        # middle (N - 2*Lwing terms; input vector and filter window overlap completely)
        else:
            xout[i] = median(xin[i-Lwing:i+Lwing+1]) # (i-Lwing to i+Lwing)

    return xout

def intersect(list1, list2):
    '''Return the intersection of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set intersection
    
    Raises:
    None
    '''
    return intersect1d(array(list1, object), array(list2, object)).tolist()

def union(list1, list2):
    '''Return the union of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set union
    
    Raises:
    None
    '''
    # ensures unique()
    return union1d(array(list1, object), array(list2, object)).tolist()
    #return union1d(array(list1), array(list2)).tolist()

def setdiff(list1, list2):
    '''Return the set difference of two lists
    Inputs:
    list1,list2 - the lists

    Returns:
    their set difference
    
    Raises:
    None
    '''
    return setdiff1d(array(list1, object), array(list2, object)).tolist()

def sort_i(list1):
    '''Sort a list of indices, returning a list
    Handles arrays

    Inputs:
    list1 - the list or array

    Returns:
    a list, sorted ascending
    
    Raises:
    None
    '''
    list1 = sort(list1)
    return list1.tolist()

def index_i(list1, list_i):
    '''Return a list of elements of list1 selected by indicices in list_i
    E.g., under numpy list1[list_i] but handles lists and returns lists...

    Inputs:
    list1 - the list or array
    list_i - the list or array of indices

    Returns:
    a list of elements
    
    Raises:
    None
    '''
    return array(list1)[list_i].tolist()

def succinct_elts(elts,matlab_offset=1):
    '''Return a string of elts, succinctly showing runs of consecutive values, if any
    Inputs:
    elts - a set of integers
    matlab_offset - offset to use if these are NOT indices

    Returns:
    selts - a succinct string
    
    Raises:
    None
    '''
    elts = sort(unique(elts))
    elts = elts + matlab_offset
    selts = ""
    prefix = ""
    num_elts = len(elts)
    if (num_elts):
        diff_elts = diff(elts)
        breaks_i_v = [i for i in range(len(diff_elts)) if diff_elts[i] > 1]
        breaks_i_v.append(len(elts)-1) # add the final point
        last_i = 0
        for break_i in breaks_i_v:
            nelts =  elts[break_i] - elts[last_i]
            if (nelts == 0):
                selts = "%s%s%d" % (selts, prefix, elts[break_i])
            elif (nelts == 1):
                selts = "%s%s%d %d" % (selts, prefix, elts[last_i], elts[break_i])
            else:
                selts = "%s%s%d:%d" % (selts, prefix, elts[last_i], elts[break_i])
            last_i = break_i+1
            prefix = " "
    return selts

def get_key(dict_d,key,default=None):
    '''Looks for key in dict_d, returns that value otherwise returns default (like getattr but for dicts)'''
    try:
        return dict_d[key]
    except KeyError:
        return default
    
def Oxford_comma(strings,connector='and'):
    '''Returns a string of string elements, in given order, serial comma-separated according to the Oxford rule.
    '''
    n = len(strings)
    if (n == 0):
        return ''
    elif (n == 1):
        return strings[0]
    elif (n == 2):
        return '%s and %s' % (strings[0], strings[1])
    else:
        string = ''
        for i in range(n):
            string = '%s%s, ' % (string, strings[i])
            if (i == n-2):
                string = '%s%s %s' % (string, connector, strings[i+1])
                break
        return string
        
def ensure_basename(basename):
    '''Returns basename with problematic filename characters replaced
    
    Inputs:
    basename - string

    Returns:
    basename possibly modified
    
    Raises:
    None
    '''
    return basename.replace(' ', '_').replace(',', '_').replace('/', '_').replace('&', '_')

def check_versions():
    import Globals
    import numpy
    import scipy

    log_info("Basestation version: %s; QC version: %s" % (Globals.basestation_version, Globals.quality_control_version))
    
    # Check python version
    log_info("Python version %d.%d.%d" % (sys.version_info[0], sys.version_info[1], sys.version_info[2]))
    if sys.version_info < Globals.required_python_version:
        msg = "python %s or greater required" % str(Globals.required_python_version)
        log_critical(msg)
        raise RuntimeError(msg)
    if sys.version_info < Globals.recommended_python_version:
        log_warning("python %s or greater recomemnded" % str(Globals.recommended_python_version))

    # Check numpy version
    log_info("Numpy version %s" % numpy.__version__)
    if normalize_version(numpy.__version__) < normalize_version(Globals.required_numpy_version):
        msg = "Numpy %s or greater required" % Globals.required_numpy_version
        log_critical(msg)
        raise RuntimeError(msg)
    if normalize_version(numpy.__version__) < normalize_version(Globals.recommended_numpy_version):
        log_warning("Numpy %s or greater recomemnded" % Globals.recommended_numpy_version)
    
    # Check scipy version
    log_info("Scipy version %s" % scipy.__version__)
    if normalize_version(scipy.__version__) < normalize_version(Globals.required_scipy_version):
        msg = "Scipy %s or greater required" % Globals.required_scipy_version
        log_critical(msg)
        raise RuntimeError(msg)
    if normalize_version(scipy.__version__) < normalize_version(Globals.recommended_scipy_version):
        log_warning("SciPy %s or greater recomemnded" % Globals.recommended_scipy_version)

def normalize_version(v):
    if not isinstance(v, str) :
        v = str(v) # very old versions of base_station_version for example were stored as floats
    return ([int(x) for x in re.sub(r'(\.0+)*$', '', v).split(".")])
    
def is_integer(s):
    try:
        int(s)
        return True
    except ValueError:
        return False

def is_float(s):
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
    if(column_names is None):
        log_error("No column names supplied for remap_engfile_columns_netcdf conversion - version mismatch?")
        return -1 # return 1?
    ret_val = 1
    for old_name, new_name in list(replace_dict.items()):
        if (old_name in column_names):
            log_debug('Replacing %s with %s' % (old_name, new_name))
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
            splits = calib_consts[remap_str].split(',')
            for s in splits:
                k, v = s.split(':')
                remap_dict[k.strip()] = v.strip()
            return remap_dict
        except:
            log_error("Could not process remap_eng_cols from sg_calib_contants.m (%s)", 'exc')
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
    duplicates_v = [] # location of any duplicated indices
    last_i = 0 # (re)start here
    for first_i in range(first_np):
        first_time = first_values_v[first_i]
        idx = last_i
        while (idx < second_np-1): # ensure we never return an index > second_np
            second_time = second_values_v[idx]
            if (second_time >= first_time):
                break
            idx += 1 # move along
        if (last_i and last_i == idx):
            duplicates_v.append(first_i) # this value in the first has a duplicate index from the second
        last_i = idx # restart search here
        indices_v.append(idx)
    return indices_v, duplicates_v

import scipy.interpolate
def interp1d(first_epoch_time_s_v, data_v, second_epoch_time_s_v, kind='linear'):
    """For each data point data_v at first_epoch_time_s_v, determine the value at second_epoch_time_s_v
    Interpolate according to type
    Assumes both epoch_time_s_v arrays increase monotonically
    Ensures first_epoch_time_s_v and data_v cover second_epoch_time_s_v using 'nearest' values
    """
    # add 'nearest' data item to the ends of data and first_epoch_time_s_v
    if second_epoch_time_s_v[0] < first_epoch_time_s_v[0]:
        # Copy the first value below the interpolation range
        data_v = append(array([data_v[0]]), data_v)
        first_epoch_time_s_v = append(array([second_epoch_time_s_v[0]]), first_epoch_time_s_v)
        
    if second_epoch_time_s_v[-1] > first_epoch_time_s_v[-1]:
        # Copy the last value above the interpolation range
        data_v = append(data_v, array([data_v[-1]]))
        first_epoch_time_s_v = append(first_epoch_time_s_v, array([second_epoch_time_s_v[-1]]))

    interp_data_v = scipy.interpolate.interp1d(first_epoch_time_s_v, data_v, kind=kind)(second_epoch_time_s_v)
    return interp_data_v

def invert_sparton_correction(corrected_angle_degrees_v, prc_degrees_v, coef0, coef1, coef2, coef3):
    """Given corrected angles (pitch or roll) and the alternative (roll or pitch)
    corrected angles, plus the correction coefficients (for pitch or roll)
    compute the originally measured angles from the compass
    """
    # Newton-Raphson on our pitch/roll eqn
    corrected_angle_radians_v = radians(corrected_angle_degrees_v)
    prc_radians_v = radians(prc_degrees_v)
    const = coef0 + coef3*sin(prc_radians_v) - corrected_angle_radians_v
    measured = corrected_angle_radians_v # this is a good starting guess
    threshold = math.radians(0.001) # compute to the nearest 1/100th of a degree
    diff = array([1.0]) # at least one loop
    while (max(abs(diff)) > threshold):
        # derivative of our correction eqn
        diff = ((const + coef1*measured + coef2*sin(measured))/(coef1 + coef2*cos(measured)));
        measured = measured - diff
    return degrees(measured)

# TODO rename this function oxygen_solubility_air?  and the doc on the nc variable
def compute_oxygen_saturation(temp_cor_v, salin_cor_v):
    """ Compute (max) oxygen saturation (solubility) (uM/L)
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
    if False:
        # 'combined fit'
        A = [2.00856, 3.22400, 3.99063, 4.80299, 0.978188, 1.71096]
        B = [6.24097E-3, 6.93498E-3, 6.90358E-3, 4.29155E-3]
        C0 = -3.11680E-7
        # Utils.compute_oxygen_saturation(array([10]),array([35])) # = [array([ 440.40191284]), array([ 352.59215692]), array([ 1.24904058])]
    else:
        # Benson & Krause constants, which Argo prefers, and which Garcia and Gordon recommend (last para)
        A = [2.009070, 3.220140, 4.050100, 4.944570, -0.256847, 3.887670]
        B = [-6.24523E-3, -7.37614E-3, -1.0341E-2, -8.17083E-3]
        C0 = -4.88682E-7
        # 282.0149 is 6.318*44.6596, where 6.318 is the check value in G&G
        # Utils.compute_oxygen_saturation(array([10.0]), array([35.0])) # = [array([ 282.01498073]), array([ 352.75484586]), array([ 0.79946451])]

    A.reverse() # fliplr()
    B.reverse() # fliplr()
    
    Kelvin_offset = 273.15 # for 0 deg C

    temp_cor_K_scaled_v = log( ((Kelvin_offset + 25.0) - temp_cor_v)/(Kelvin_offset + temp_cor_v))
    
    oxygen_sat_fresh_water_v = exp(polyval(A, temp_cor_K_scaled_v)); # [ml/L] based only on temperature
    oxygen_sat_salinity_adjustment_v = exp(salin_cor_v * polyval(B, temp_cor_K_scaled_v) +
                                           C0 * salin_cor_v * salin_cor_v) # adjustment factor
    oxygen_sat_seawater_v = oxygen_sat_salinity_adjustment_v * oxygen_sat_fresh_water_v # [ml/L]

    # NOTE: SBE43 corrections use 44.6596, which is the real gas constant.
    # Aanderaa used 44.6145, the ideal gas constant, (as shown in several of their older manuals)
    # but have gone to the real constant as of 11/2013.
    # Thierry et. al, 2011 report: The value of 44.6596 is derived from the molar volume of the oxygen gas,
    # 22.3916 L/mole, at standard temperature and pressure (0C, 1 atmosphere; e.g., Garcia and Gordon, 1992).
    # so 1/22.3916 = 0.446596 M/L 
    o2_molar_mass = 44.6596; #  uM/L of oxygen at standard pressure and temperature
    # relative_sat_v = measured_molar_oxygen_concentration_v/oxygen_sat_v * 100 # relative O2 saturation (percent)
    return [oxygen_sat_seawater_v*o2_molar_mass, # uM/L
            oxygen_sat_fresh_water_v*o2_molar_mass, # uM/L
            oxygen_sat_salinity_adjustment_v] # scale factor

import smtplib
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
def send_email_text(base_opts, from_email_addr, to_email_addr, from_line, subject_line, message_body, smtp_server=None, smtp_account=None,smtp_password=None, html_format=False):
    """Sends out email

    Input
        from_email_addr - string for the email address (one address only)
        to_email_addr - string for a single email address or a list of strings for multiple addresses
        from_line - a pretty string typically with from_email_addr embedded in <>
        subject_line - subject line for message
        message_body - contents of message
        smtp_server, smtp_account, smtp_password - optional info for using an alternate smtp host as email forwarding server
    Returns
        0 - success
        1 - failure
    """
    if html_format:
        email_msg = MIMEMultipart('alternative')
    else:
        email_msg = MIMENonMultipart('text', 'plain')
    email_msg['From'] = from_line
    email_msg['To'] = to_email_addr if isinstance(to_email_addr, str) else ','.join(to_email_addr)
    email_msg['Date'] = formatdate(localtime=True)
    email_msg['Subject'] = subject_line
    if(base_opts.reply_addr):
        email_msg['Reply-To'] = base_opts.reply_addr
    if html_format:
        html_body = "<html><head></head><body><p>"
        for ll in message_body.splitlines():
            html_body += "<div>%s</div>" % ll
        html_body += "</p></body></html>"
        # Record the MIME types of both parts - text/plain and text/html.
        part1 = MIMEText(message_body, 'plain')
        part2 = MIMEText(html_body, 'html')
        # Attach parts into message container.
        # According to RFC 2046, the last part of a multipart message, in this case
        # the HTML message, is best and preferred.
        email_msg.attach(part1)
        email_msg.attach(part2)
    else:
        email_msg.set_payload(message_body)

    email_send_from = from_email_addr
    email_send_to = []
    email_send_to.append(to_email_addr) if isinstance(to_email_addr, str) else email_send_to.extend(to_email_addr)    
    try:
        if sys.platform == 'darwin':
            # on Mac OSX use some smtp server as the mail forwarder
            if not smtp_server or not smtp_account or not smtp_password:
                # typical servers are smtp.gmail.com or smtp.washington.edu
                log_error('Unable to send mail via smtp on Mac OS X -- requires an smtp account and password.')
                return 1
            smtp = smtplib.SMTP(smtp_server, 587) # port 465 or 587
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(smtp_account, smtp_password)
            if(not base_opts.reply_addr):
                email_msg['Reply-To'] = from_email_addr # smtp servers often rewrite from_line to use 'Original Name <account_name@gmail.com>'
        else: # linux of some sort
            smtp = smtplib.SMTP('localhost')
        smtp.sendmail(email_send_from, email_send_to, email_msg.as_string())
        smtp.close()                        
    except:
        log_error("Unable to send message %s (%s) to %s" % (subject_line, message_body, to_email_addr), 'exc')
        log_info("Continuing processing...")
        return 1
    else:
        return 0

def process_urls(base_opts, pass_num_or_gps, instrument_id, dive_num):
    """Process the urls file - supplying different arguments for the first and second pass
    """
    # Process urls
    urls_file_name = os.path.join(base_opts.mission_dir, ".urls")
    if(not os.path.exists(urls_file_name)):
        log_info("No .urls file found - skipping .urls processing pass %s" % pass_num_or_gps)
    elif(dive_num is None):
        log_error("dive_num is not an integer - skipping .urls file processing")
    elif(instrument_id is None):
        log_error("instrument_id is not an integer - skipping .urls file processing")
    else:
        log_info("Starting processing on .urls pass(%s)" % pass_num_or_gps)
        try:
            urls_file = open(urls_file_name, "r")
        except IOError as exception:
            log_error("Could not open %s (%s) - no urls notified" % (urls_file_name, exception.args))
        else:
            for urls_line in urls_file:
                urls_line = urls_line.rstrip()
                log_debug("urls line = (%s)" % urls_line)
                if (urls_line == ""):
                    continue
                if(urls_line[0] != '#'):
                    log_info("Processing .urls line (%s)" % urls_line)
                    urls_elts = urls_line.split()
                    if(len(urls_elts) > 2):
                        log_error("Too many entries on line (%s)" % urls_line)
                    socket.setdefaulttimeout(int(urls_elts[0]))
                    if(isinstance(pass_num_or_gps, int) and pass_num_or_gps == 1):
                        url_line = "%s?instrument_name=SG%03d&dive=%d&files=perdive" \
                                   % (urls_elts[1], int(instrument_id), int(dive_num))
                    elif(isinstance(pass_num_or_gps, int) and pass_num_or_gps == 2):
                        url_line = "%s?instrument_name=SG%03d&dive=%d&files=all" \
                                   % (urls_elts[1], int(instrument_id), int(dive_num))
                    elif(isinstance(pass_num_or_gps, str) and pass_num_or_gps.startswith("status")):
                        url_line = "%s?instrument_name=SG%03d&%s" \
                                    % (urls_elts[1], int(instrument_id), pass_num_or_gps)                        
                    elif(isinstance(pass_num_or_gps, str)):
                        url_line = "%s?instrument_name=SG%03d&dive=%d&gpsstr=%s" \
                                   % (urls_elts[1], int(instrument_id), int(dive_num), pass_num_or_gps)
                    else:
                        log_error("Unknown pass(%s) - skipping processing" % str(pass_num_or_gps))
                        continue
                        
                    log_debug("URL line (%s)" % url_line)
                    try:
                        url_response = urlopen(url_line).read()
                    except:
                        log_error("Error opening %s" % url_line, 'exc')
                        log_error("Continuing processing...")
                    else:
                        log_info("url (%s) responded with:%s" % (url_line, url_response))
 
        log_info("Finished processing on .urls pass(%s)" % pass_num_or_gps)


from ftplib import FTP
import netrc

def process_ftp_line(base_opts, processed_file_names, mission_timeseries_name, mission_profile_name, ftp_line, known_ftp_tags):
    """Sends indicated files to the ftp site indicated in ftp_line.
    Always sends nc files but can send others according to known_ftp_tags
    Input:
       base_opts - options
       processed_file_names - list of files to send, fully-qualified
       mission_timeseries_name - name or None
       mission_profile_name - name or None
       ftp_line - ftp specification of the form [user[:password]@]host[:port]/path
       known_ftp_tags - list of acceptable tags as a filter (e.g., comm, mission_ts, mission_pro, or explicit extensions)

    Returns
      0 - success
      1 - failure
    """

    ftp_line = ftp_line.rstrip()
    log_debug("ftp line = (%s)" % ftp_line)
    if (ftp_line == ""): # blank line
        return 0
    if(ftp_line[0] != '#'): # not a comment
        log_info("Processing ftp line (%s)" % ftp_line)
        # Lines of the form
        # [user[:password]@]host[:port]/path
        # see .ftp in sg000 for more details
        # NOTE: password can't be an email address (anonymous ftp) because '@' separates host as well
        # HACK: if password contains '_AT_' we replace it with an @
        ftp_tags = ftp_line.split(',')
        # Address
        user = pwd = host = port = path = None

        ftp_addr = ftp_tags[0].split('@')
        if(len(ftp_addr) > 1):
            host_temp = ftp_addr[1]
            temp = ftp_addr[0].split(':')
            if(len(temp) > 1):
                user, pwd = temp
                pwd = pwd.replace('_AT_', '@')
            else:
                user = temp[0]
        else:
            host_temp = ftp_addr[0]

        temp, path = host_temp.split('/', 1)
        if(len(temp.split(':')) > 1):
            host, port = temp.split(':')
        else:
            host = temp

        # If there is no user specified, try the netrc file
        if(user is None):
            try:
                auth = netrc.netrc().authenticators(host)
            except:
                log_warning("Could not process .netrc", 'exc')
            else:
                if auth is not None:
                    user, _, pwd = auth

        log_info("user:%s,host:%s,port:%s,path:%s" % (user, host, port, path))

        # Tags - what to send
        ftp_tags = ftp_tags[1:]

        temp_tags = ftp_tags
        for i in range(len(temp_tags)):
            ftp_tags[i] = temp_tags[i].lower().rstrip().lstrip()

        # Check for what file type
        try:
            ftp_tags.index('all')
        except:
            pass
        else:
            ftp_tags = known_ftp_tags

        # Collect file to send into a list
        ftp_file_names_to_send = []

        for ftp_tag in ftp_tags:
            if(not ftp_tag in known_ftp_tags):
                log_error("Unknown tag (%s) on line (%s) in %s - skipping" % (ftp_tag, ftp_line, ftp_file_name))
            else:
                if ftp_tag == 'comm':
                    ftp_file_names_to_send.append(os.path.join(base_opts.mission_dir, "comm.log"))
                else:
                    for processed_file_name in processed_file_names:
                        head, tail = os.path.splitext(processed_file_name)
                        if(processed_file_name == mission_timeseries_name):
                            if(ftp_tag == 'mission_ts'):
                                ftp_file_names_to_send.append(processed_file_name)
                        elif(processed_file_name == mission_profile_name):
                            if(ftp_tag == 'mission_pro'):
                                ftp_file_names_to_send.append(processed_file_name)
                        elif(os.path.splitext(head)[1] == '.nc' and ftp_tag.lower() == 'nc'):
                            ftp_file_names_to_send.append(processed_file_name)
                        else:
                            head, tail = os.path.splitext(processed_file_name)
                            if tail.lstrip('.') == ftp_tag.lower():
                                ftp_file_names_to_send.append(processed_file_name)

        if(len(ftp_file_names_to_send) < 1):
            return 0 # nothing to send 

        log_debug("ftp files to send %s" % ftp_file_names_to_send)
        # Connect
        try:
            ftp = FTP(host)
        except:
            log_error("Unable to connect", 'exc')
            return 1 # give up
        try:
            ftp.login(user, pwd)
        except:
            log_error("Unable to login", 'exc')
            return 1 # give up

        for i in path.split('/'):
            try:
                # We used to look via LIST to see if the subdir exists
                # but some sites protect against listing.
                # So just blindly try cd'ing to it and deal with the consequences
                ftp.cwd(i) # try to cd to subdir 
            except:
                try:
                    ftp.mkd(i) # Doesn't appear to exist; try to create it
                except:
                    log_error("Could not make %s" % i, 'exc')
                    return 1 # give up
                ftp.cwd(i) # cd to what we just created

        result = 0 # assume the best
        for ftp_file_name_to_send in ftp_file_names_to_send:
            head, tail = os.path.split(ftp_file_name_to_send)
            try:
                fi = open(ftp_file_name_to_send, 'r')
            except:
                log_error("Unable to open %s - skipping" % ftp_file_name_to_send, 'exc')
                result = 1 # we had issues
            else:
                try:
                    ftp.storbinary("STOR %s" % tail, fi)
                except:
                    log_error("Unable to send %s - skipping" % ftp_file_name_to_send, 'exc')
                    result = 1 # we had issues
                else:
                    log_info("Sent %s" % ftp_file_name_to_send)
                fi.close()

        # Shutdown
        ftp.quit()
        return result

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
    return isnan(y), lambda z: z.nonzero()[0]

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
        splits = base.split('.')
        if len(splits) >= 2 and splits[-1].isdigit() and splits[-2].isdigit():
            return (int(splits[-2]) * 1000) + int(splits[-1])
        elif splits[-1].isdigit():
            return int(splits[-1]) * 1000
        else:
            # Note - should never get here as the root file is handled at the outter call
            return 0
            
    a_key = find_dive_counter(a)
    b_key = find_dive_counter(b) 

    if(a_key > b_key):
        return -1
    elif(a_key < b_key):
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
        if(os.path.exists(file_name)):
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

    if(files != []):
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


qc_log_type = collections.namedtuple('qc_log_type', ['qc_str', 'qc_type', 'qc_points'])    

def load_qc_pickl(qc_file):
    try:
        fi = open(qc_file, 'r')
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
        log_warning("GPS Rollover found (%s)" % struct_time,
                    alert="GPSROLLOVER", max_count=5)
        tmp = time.mktime(struct_time) + 619315200 #1024*7*86400
        struct_time = time.gmtime(tmp)
        del tmp
    return struct_time
