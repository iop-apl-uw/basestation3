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

import argparse
import json
import pathlib
import typing

import plotly.graph_objects
import scipy.interpolate

if typing.TYPE_CHECKING:
    import sqlite3

    import scipy

    import BaseOpts

import BaseOptsType
import Magcal
import PlotUtils
import PlotUtilsPlotly
from Plotting import add_arguments, plotdivesingle

_HELP_SLUG = "dv_magcal"


@add_arguments(
    additional_arguments={
        "plot_magcal_dive_climb": BaseOptsType.options_t(
            False,
            {"Base", "BasePlot", "Reprocess"},
            ("--plot_magcal_dive_climb",),
            bool,
            {
                "help": "Plot dive and climb magcal calibration separately instead of combined",
                "section": "plotting",
                "option_group": "plotting",
                "action": argparse.BooleanOptionalAction,
            },
        ),
    }
)
@plotdivesingle
def plot_mag(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots: bool = True,
    dbcon: sqlite3.Connection | None = None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Plot for compass mag calibration"""
    if "eng_mag_x" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    def _build_output(
        phase: str, basename: str
    ) -> tuple[plotly.graph_objects.Figure | None, list[pathlib.Path]]:
        hard, soft, cover, circ, fig, copy_text = Magcal.magcal_worker(
            [dive_nc_file],
            True,
            "html",
            PlotUtils.get_mission_dive(dive_nc_file),
            phase=phase,
        )
        if fig is None:
            return None, []

        fig.add_annotation(PlotUtilsPlotly.add_help_link(_HELP_SLUG))

        copy_post_script = PlotUtilsPlotly.build_clipboard_button_post_script(
            button_label="Copy calibration",
            get_copy_text_js=f"return {json.dumps(copy_text)};",
            # Anchored to the x-axis title group ("X field") with
            # placement="below_centered" - lands the button below the plot,
            # horizontally centered under the x-axis label. Anchoring to the
            # title group itself (rather than a fixed offset from rect.bg)
            # means the button always clears the tick labels too, since the
            # title is reliably drawn below them.
            anchor_element_js="return gd.querySelector('g.g-xtitle');\n",
            is_visible_js="return true;",
            placement="below_centered",
        )

        return fig, PlotUtilsPlotly.write_output_files(
            base_opts,
            basename,
            fig,
            post_script=copy_post_script,
        )

    if getattr(base_opts, "plot_magcal_dive_climb", False):
        figs = []
        output_files = []
        for phase, suffix in (("dive", "dive"), ("climb", "climb")):
            fig, files = _build_output(
                phase, "dv%04d_magcal_%s" % (dive_nc_file.dive_number, suffix)
            )
            if fig is not None:
                figs.append(fig)
                output_files.extend(files)
        return (figs, output_files)

    fig, output_files = _build_output(
        "all", "dv%04d_magcal" % (dive_nc_file.dive_number,)
    )
    return ([fig] if fig is not None else [], output_files)
