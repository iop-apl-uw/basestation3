#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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


"""Package setup for plotting routines"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import importlib
import inspect
import pathlib
import sys
import typing

# Avoid circular input for type checking
if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

from BaseLog import log_error, log_info

dive_plot_funcs = {}
mission_plot_funcs = {}
plotting_additional_arguments = {}


# pylint: disable=unused-argument
def plot_dive_single(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file_name: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Signature for per-dive plotting routines"""
    return ([], [])


# pylint: disable=unused-argument
def plot_mission_single(
    base_opts: BaseOpts.BaseOptions,
    mission_str: list,
    dive=None,
    generate_plots=True,
    dbcon=None,
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


def add_arguments(_func=None, *, additional_arguments=None):
    """Specifies any additional arguments to be added to BaseOpts"""

    def add_arguments_dec(func, additional_arguments=additional_arguments):
        # TODO - check all dicts are options_t
        if additional_arguments and isinstance(additional_arguments, dict):
            global plotting_additional_arguments
            plotting_additional_arguments |= additional_arguments

    if _func is None:
        return add_arguments_dec
    else:
        return add_arguments_dec(_func, additional_arguments=None)


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

# from . import DiveCOG # deprecated in favor of the COG trace on the CTW plot
from . import DiveCTW
from . import DiveOptode
from . import DiveWetlabs
from . import DiveOCR504i
from . import DiveCTD
from . import DiveTS
from . import DiveTMICL
from . import DivePMAR
from . import DiveCompassCompare
from . import DiveLegatoPressure
from . import DiveLegatoData
from . import DiveCTDCorrections

# from . import DiveVertVelocity
from . import DiveVertVelocityNew
from . import DivePitchRoll
from . import DiveMagCal
from . import DiveSBE43

# Whole mission plotting routines
from . import MissionEnergy
from . import MissionVolume
from . import MissionMotors
from . import MissionIntSensors
from . import MissionDepthAngle
from . import MissionMap
from . import MissionDisk
from . import MissionCommLog
from . import MissionProfiles
from . import MissionCallStats

# Load any other plotting routines located in the local directory
# Note: symlinks to other modules will be followed
l_dir = pathlib.Path(__file__).parent.joinpath("local")
if l_dir.exists() and l_dir.is_dir():
    for l_file in l_dir.iterdir():
        if l_file.suffix == ".py":
            if l_file.stem not in sys.modules:
                spec = importlib.util.spec_from_file_location(l_file.stem, l_file)
                mod = importlib.util.module_from_spec(spec)
                sys.modules[l_file.stem] = mod
                spec.loader.exec_module(mod)
