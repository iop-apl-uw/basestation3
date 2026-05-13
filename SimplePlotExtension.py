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

"""Simple basestation extension that generates plot output - starting point for new extensions"""

from __future__ import annotations

import pathlib
import pdb
import sys
import time
import traceback

import plotly.graph_objects

import BaseOpts
import MakeDiveProfiles
import PlotUtils
import PlotUtilsPlotly
import Utils
from BaseLog import BaseLogger, log_error, log_info

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


def load_additional_arguments():
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded
    """
    return (
        # Add this module to these options defined in BaseOpts
        [
            "mission_dir",
            "netcdf_filename",
            "plot_directory",
            "full_html",
            "compress_div",
            "thumbnail_webp",
            "save_png",
            "save_jpg",
            "save_webp",
            "save_svg",
        ],
        # Option groups
        {},
        # Additional arguments
        {},
    )


def main(
    cmdline_args: list[str] = sys.argv[1:],
    instrument_id: int | None = None,
    base_opts: BaseOpts.BaseOptions | None = None,
    sg_calib_file_name: pathlib.Path | None = None,
    dive_nc_file_names: list[pathlib.Path] | None = None,
    nc_files_created: list[pathlib.Path] | None = None,
    processed_other_files: list[pathlib.Path] | None = None,
    known_mailer_tags: list[str] | None = None,
    known_ftp_tags: list[str] | None = None,
    processed_file_names: list[pathlib.Path] | None = None,
):
    """Basestation sample extension

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    # pylint: disable=unused-argument
    if base_opts is None:
        add_to_arguments, add_option_groups, additional_arguments = (
            load_additional_arguments()
        )

        base_opts = BaseOpts.BaseOptions(
            "Basestation extension plotting example",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
            cmdline_args=cmdline_args,
        )
    BaseLogger(base_opts)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    if not base_opts.mission_dir:
        if hasattr(base_opts, "netcdf_filename") and base_opts.netcdf_filename:
            # Called from CLI with a single argument
            dive_nc_file_names = [
                base_opts.netcdf_filename
            ]  # ty: ignore[invalid-assignment]
    elif base_opts.mission_dir:
        if nc_files_created is not None:
            # Called from MakeDiveProfiles as extension
            dive_nc_file_names = nc_files_created
        elif dive_nc_file_names is None:
            # Called from CLI to process whole mission directory
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
    if dive_nc_file_names is None:
        log_error("Either mission_dir or netcdf_file must be specified")
        return 1

    # If being invoked stand-alone, this needs to be set for the plot directory
    if not base_opts.mission_dir:
        base_opts.mission_dir = dive_nc_file_names[0].parent

    PlotUtils.setup_plot_directory(base_opts)

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}"
    )

    log_info(
        f"Started processing {time.strftime('%H:%M:%S %d %b %Y %Z', time.gmtime(time.time()))}"
    )

    ret_plots = []
    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)
        try:
            dive_nc_file = Utils.open_netcdf_file(dive_nc_file_name, "r")
        except Exception:
            log_error(f"Error opening {dive_nc_file_name}", "exc")
            continue

        mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
        title_text = f"{mission_dive_str}<br>TestPlot"
        fig = plotly.graph_objects.Figure()

        fig.update_layout(
            {
                "xaxis": {
                    "title": "x-axis title",
                },
                "yaxis": {
                    "title": "y-axis title",
                },
                "title": {
                    "text": title_text,
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {
                    "t": 150,
                    # "b": 150,
                },
            }
        )

        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts,
                f"dv{dive_nc_file.dive_number:04d}_testplot",
                fig,
            )
        )

    if processed_other_files is not None:
        processed_other_files.extend(ret_plots)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    retval = 0
    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        DEBUG_PDB_F()
        sys.stderr.write(f"Exception in main ({traceback.format_exc()})\n")

    sys.exit(retval)
