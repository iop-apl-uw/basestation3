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

"""Plot for compass mag calibration"""
# fmt: off

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import pathlib
import typing

import plotly.graph_objects
import scipy.interpolate

if typing.TYPE_CHECKING:
    import scipy

    import BaseOpts

import Magcal
import PlotUtils
import PlotUtilsPlotly
from Plotting import plotdivesingle


@plotdivesingle
def plot_mag(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plot for compass mag calibration"""
    if "eng_mag_x" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    hard, soft, cover, circ, fig = Magcal.magcal_worker([dive_nc_file], True, 'html', PlotUtils.get_mission_dive(dive_nc_file))


    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_magcal" % (dive_nc_file.dive_number,),
            fig,
        ),
    )
