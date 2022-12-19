#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
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


""" Package setup for plotting routines
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations
import inspect
import logging
import typing

# Avoid circular input for type checking
if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

from BaseLog import log_error, log_info

dive_plot_funcs = {}
mission_plot_funcs = {}

# pylint: disable=unused-argument
def plot_dive_single(
    base_opts: BaseOpts.BaseOptions, dive_nc_file_name: scipy.io._netcdf.netcdf_file
) -> tuple[list, list]:
    """Signature for per-dive plotting routines"""
    return ([], [])


# pylint: disable=unused-argument
def plot_mission_single(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Signature for whole mission plotting routines"""
    return ([], [])


plot_dive_sig = inspect.signature(plot_dive_single)
plot_mission_sig = inspect.signature(plot_mission_single)


def compare_sigs(sig_a, sig_b):
    """Compares two signatures for type equivalence
    Returns:
        True for equivalent
        False if not equivilent
    """
    if len(sig_a.parameters) != len(sig_b.parameters):
        return False

    for t1, t2 in zip(sig_a.parameters.items(), sig_b.parameters.items()):
        if not t1 or not t2:
            return False
        if t1[1].annotation != t2[1].annotation:
            return False
    return sig_a.return_annotation == sig_b.return_annotation


def plotdivesingle(func):
    """Register a per-dive plotting function"""
    sig = inspect.signature(func)
    if compare_sigs(plot_dive_sig, sig):
        # print(f"Addiing {func.__name__}")
        dive_plot_funcs[func.__name__] = func
    else:
        print(f"ERROR: {func.__name__} does not match signature")
    return func


def plotmissionsingle(func):
    """Register a whole mission plotting function"""
    sig = inspect.signature(func)
    if compare_sigs(plot_mission_sig, sig):
        # print(f"Addiing {func.__name__}")
        mission_plot_funcs[func.__name__] = func
    else:
        print(f"ERROR: {func.__name__} does not match signature")
    return func


# pylint: disable=wrong-import-position

# Per-dive plotting routines
from . import DivePlot
from . import DiveCOG
from . import DiveCTW
from . import DiveOptode
from . import DiveWetlabs
from . import DiveOCR504i
from . import DiveCTD
from . import DiveTS
from . import DiveTMICL
from . import DivePMAR
from . import DiveCompassCompare
from . import DiveVertVelocity
from . import DivePitchRoll
from . import DiveMagCal

# Whole mission plotting routines
from . import MissionEnergy
