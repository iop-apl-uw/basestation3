#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2016, 2017, 2019, 2020 by University of Washington.  All rights reserved.
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
Minimum package versions and common class definitions
"""

from enum import IntEnum

# These document file format versions
# All recorded as globals.file_version in their respective files
mission_profile_nc_fileversion = '2.71'
mission_timeseries_nc_fileversion = '2.71'
mission_per_dive_nc_fileversion = '2.71'
# These document level of functionality
basestation_version = '3.0'
quality_control_version = '1.12'

# The oldest format version this code supports
required_nc_fileversion = '2.7' #  (August, 2011)

# Version stamps for various packages
required_python_version = (3, 7, 7)
recommended_python_version = (3, 7, 7)
required_numpy_version = '1.18.1'
recommended_numpy_version = '1.18.1'

required_scipy_version = '1.4.1'
recommended_scipy_version = '1.4.1'
# need at least 0.11.0 for proper sparse matrix support (scipy.sparse.diags)
required_scipy_sparse_version = '1.4.1'

#pylint: disable=E0239
class WhichHalf(IntEnum):
    """ Used for various profile processing routines
    """
    down = 1
    up = 2
    both = 3
    combine = 4
