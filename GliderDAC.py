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

"""Create a file for submission to the GliderDAC from an existing netCDF file"""
#
# Notes:
#
# Overall, this code can produce timeseries data (--gliderdac_bin_width == 0.0) or
# binned output (--gliderdac_bin_width > 0.0)
#
# netcdf files without a ctd_time or ctd_depth vector are rejected
#
# 1) For input timeseries vectors with associated QC vectors, only points marked QC_GOOD are
#    accepted.  All other points are converted to nans
# 2) If timeseries vectors are associated with multiple time basis, there is a single
#    time basis constructed contain all observations (this can be very sparse
#    table for a scicon instrument)
# 3) For output, timeseries variables time, depth, latitude, longitude and pressure are
#    marked no_qc_performed (QC_NOCHANGE) for non-nan data and missing_value (QC_MISSING)
#    for nan.
#    All other timeseries variables are marked good_data (QC_GOOD) for non-nan and
#    missing_value (QC_MISSING) for nan data.

import argparse
import collections.abc
import pathlib
import pdb
import stat
import sys
import time
import traceback
import typing
from functools import reduce

import gsw
import netCDF4
import numpy as np
import plotly.graph_objects
import xarray as xr
import yaml

import BaseOpts
import BaseOptsType
import MakeDiveProfiles
import NetCDFUtils
import PlotUtils
import PlotUtilsPlotly
import QC
import TraceArray
import Utils
from BaseLog import BaseLogger, log_debug, log_error, log_info, log_warning

# Local config
DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


class dim_map_t(typing.NamedTuple):
    """Maps a dimension's span within the unsorted, concatenated master time
    vector.

    Attributes:
        first_i: Index of the first element for this dimension.
        last_i: Index one past the last element for this dimension.
    """

    first_i: int
    last_i: int


# Util functions
def fix_ints(
    data_type: type, attrs: dict[str, typing.Any]
) -> dict[str, typing.Any]:
    """Convert int values from LL (json format) to appropriate size per gliderdac specs

    Args:
        data_type: Numpy scalar type to cast int-valued attributes to.
        attrs: Attribute dictionary to convert.

    Returns:
        A new attribute dictionary with int values cast to data_type.
    """
    new_attrs = {}
    for k, v in attrs.items():
        if isinstance(type(v), int):
            new_attrs[k] = data_type(v)
        elif k == "flag_values":
            new_attrs[k] = [data_type(li) for li in v]
        else:
            new_attrs[k] = v
    return new_attrs


def lookup_qc_val(value: str) -> np.int8 | None:
    """Resolves a QC name string (e.g. "QC_NO_CHANGE") to its numeric value.

    Args:
        value: QC name string, as it appears in a template's qc_data or
            qc_missing_data field.

    Returns:
        The matching QC value, or None if value doesn't match a known QC
        name.
    """
    for k, v in QC.qc_name_d.items():
        if value.rstrip().lstrip() == v:
            return np.int8(k)
    log_warning(f"Unkown QC string {value} - ignoring")
    return None


def create_nc_var(
    dso: xr.Dataset,
    template: dict[str, typing.Any],
    var_name: str,
    data: str | int | float | np.generic | np.ndarray | xr.DataArray,
    qc_val: int | np.generic | np.ndarray | xr.DataArray | None = None,
    qc_missing_val: int | np.generic | None = None,
) -> tuple[xr.DataArray, xr.DataArray | None]:
    """Creates a nc variable and sets meta data

    Args:
        dso: Output dataset.
        template: Dictionary of variable metadata.
        var_name: Name of variable as it appears in template.
        data: Input data - scalar, string, or array-like.
        qc_val: Optional; QC value(s) to use - a scalar QC value, a
            per-point QC array, or a QC DataArray copied from the source
            netCDF. Overrides the template's own qc_data default. Defaults
            to None (use the template default).
        qc_missing_val: Optional; QC value to use for missing (fill-value)
            points. Defaults to None (use the template's qc_missing_data,
            or QC.QC_MISSING).

    Returns:
        A tuple of (dataarray for the variable, dataarray for the matching
        qc variable, or None if no qc variable was created).
    """

    if qc_val is None and "qc_data" in template["variables"][var_name]:
        qc_val = lookup_qc_val(template["variables"][var_name]["qc_data"])

    if qc_missing_val is None:
        if "qc_missing_data" in template["variables"][var_name]:
            qc_missing_val = lookup_qc_val(
                template["variables"][var_name]["qc_missing_data"]
            )
        else:
            # Only has impact if qc_val is not None
            qc_missing_val = QC.QC_MISSING

    is_str = False
    if isinstance(data, str):
        inp_data = np.array(data, dtype=np.dtype(("S", len(data))))
        is_str = True
    elif np.ndim(data) == 0:
        # Scalar data
        inp_data = np.dtype(template["variables"][var_name]["type"]).type(data)
    else:
        # np.ndim(data) == 0 above already routed every scalar (including
        # bare int/float) to the previous branch - only array-like data
        # (np.ndarray/xr.DataArray) reaches here, but ty can't narrow that
        # from a runtime np.ndim() check.
        inp_data = data.astype(  # ty: ignore[unresolved-attribute]
            template["variables"][var_name]["type"]
        )

    if "num_digits" in template["variables"][var_name]:
        inp_data = inp_data.round(template["variables"][var_name]["num_digits"])

    # Check for scalar variables
    if np.ndim(inp_data) == 0:
        if np.issubdtype(inp_data.dtype, np.number) and np.isnan(inp_data):
            inp_data = template["variables"][var_name]["attributes"]["_FillValue"]
    else:
        inp_data[np.isnan(inp_data)] = template["variables"][var_name][  # ty: ignore[invalid-assignment]
            "attributes"
        ]["_FillValue"]

    # GBS 2022/02/09 In what can only be a bug, if the time_qc variable is written out after the time variable,
    # time variables attributes are deleted, leaving an empty dict.  No other variables have
    # this issue.  If the order is reversed - qc before regular variable - no problems.  This
    # may be related to the fact that the time variable has the same name as the time dimension,
    # and is there for picked up as an indexing coordinate by xarray.

    # QC array

    qc_name = f"{var_name}_qc"
    if qc_name in template["variables"] and qc_val is not None:
        if np.ndim(data) == 0:
            qc_v = np.dtype(template["variables"][qc_name]["type"]).type(qc_val)
        else:
            # Populate the initial vector with qc_val...
            qc_v = np.zeros((np.size(inp_data)), dtype="b") + np.dtype(
                template["variables"][qc_name]["type"]
            ).type(qc_val)
            # ...and mark the missing data
            if qc_missing_val is not None:
                qc_v[
                    inp_data
                    == template["variables"][var_name]["attributes"]["_FillValue"]
                ] = qc_missing_val
        da_q = xr.DataArray(
            qc_v,
            dims=template["variables"][qc_name]["dimensions"],
            attrs=fix_ints(np.byte, template["variables"][qc_name]["attributes"]),
        )
        if "nc_varname" in template["variables"][qc_name]:
            dso[template["variables"][qc_name]["nc_varname"]] = da_q
        else:
            dso[qc_name] = da_q
    else:
        da_q = None

    da = xr.DataArray(
        inp_data,
        dims=template["variables"][var_name]["dimensions"] if not is_str else None,
        attrs=fix_ints(np.int32, template["variables"][var_name]["attributes"]),
        # coords=None,
    )
    if "nc_varname" in template["variables"][var_name]:
        dso[template["variables"][var_name]["nc_varname"]] = da
    else:
        dso[var_name] = da

    return (da, da_q)


def load_var(
    dci: xr.Dataset,
    var_name: str,
    dims_map: dict[tuple[collections.abc.Hashable, ...], dim_map_t],
    sort_i: np.ndarray,
) -> np.ndarray | None:
    """Loads one variable's data, QC'd and remapped into sorted master-time
    order.

    Args:
        dci: Input per-dive dataset.
        var_name: Name of the variable to load.
        dims_map: Mapping of each dimension tuple to its span within the
            unsorted, concatenated master time vector.
        sort_i: Index array mapping unsorted master-time order to sorted
            order.

    Returns:
        The variable's data, QC'd (only QC_GOOD points kept, others NaN)
        and remapped into sorted master-time order, or None if var_name's
        size doesn't match its expected span in dims_map.
    """
    var = dci[var_name]
    qc_name = f"{var_name}_qc"
    if qc_name and qc_name in dci.variables:
        var_q = dci[qc_name].data
        try:
            qc_vals = QC.decode_qc(var_q)
        except Exception:
            log_warning(f"Could not decode QC for {var_name} - not applying", "exc")
        else:
            var[qc_vals != QC.QC_GOOD] = np.nan

    if len(var) != dims_map[var.dims].last_i - dims_map[var.dims].first_i:
        log_error(f"Mismatch in sizes for {var_name} and {dims_map[var.dims]}")
        return None

    # Create new var, same type as var that is all nan, size of sort_i and map var into this space
    expanded_var = np.zeros(len(sort_i), var.dtype) * np.nan
    temp_var = expanded_var.copy()
    temp_var[dims_map[var.dims].first_i : dims_map[var.dims].last_i] = var
    expanded_var = temp_var[sort_i]

    return expanded_var


def load_templates(base_opts: BaseOpts.BaseOptions) -> dict[str, typing.Any] | None:
    """Loads the base/project/deployment configuration template files and
    merges them into one.

    Args:
        base_opts: Options object, providing gliderdac_base_config,
            gliderdac_project_config, and gliderdac_deployment_config.

    Returns:
        The merged template dictionary, or None if a required config option
        is missing or a template file couldn't be loaded/merged.
    """

    # Check for all variables being set
    if not base_opts.gliderdac_base_config:
        log_error("gliderdac_base_config file not specified")
        return None

    if not base_opts.gliderdac_project_config:
        log_error("gliderdac_project_config file not specified")
        return None

    if not base_opts.gliderdac_deployment_config:
        log_error("gliderdac_deployment_config file not specified")
        return None

    templates = [{}]
    for file_name, option_name in (
        (base_opts.gliderdac_base_config, "gliderdac_base_config"),
        (base_opts.gliderdac_project_config, "gliderdac_project_config"),
        (base_opts.gliderdac_deployment_config, "gliderdac_deployment_config"),
    ):
        if not file_name:
            log_warning(f"GliderDAC option --{option_name} not specified")
            continue
        if not file_name.exists():
            log_info(f"{file_name} does not exist - skipping")
            continue
        try:
            with open(file_name, "r") as fi:
                templates.append(yaml.safe_load(fi.read()))
        except Exception:
            log_error(f"Could not procss {file_name}", "exc")
            return None

    # Merge templates together
    try:
        reduce(NetCDFUtils.merge_dict, templates)
    except Exception as e:
        log_error(f"Error merging config templates - {e.args}")
        return None

    return templates[0]


def find_deepest_bin_i(
    depth: np.ndarray, bin_centers: np.ndarray, bin_width: float
) -> np.intp:
    """Finds the last index within the deepest bin

    Args:
        depth: Depth values (meters), in master-time order.
        bin_centers: Downcast bin center depths.
        bin_width: Bin width (meters).

    Returns:
        Index of the first sample past the deepest bin.
    """

    max_i = np.argmax(depth)
    while depth[max_i] >= bin_centers[-1] - (bin_width / 2.0):
        max_i += 1

    # Return the first shallower max_i
    # max_i -= 1
    return max_i


def load_additional_arguments() -> (
    tuple[list[str], dict[str, str], dict[str, BaseOptsType.options_t]]
):
    """Defines and extends arguments related to this extension.
    Called by BaseOpts when the extension is set to be loaded

    Returns:
        A tuple of (names of existing BaseOpts options this extension also
        uses, option-group descriptions keyed by group name, this
        extension's own options keyed by option name).
    """
    return (
        # Add this module to these options defined in BaseOpts - the
        # plot_* options are needed for plot_gliderdac_dive()'s
        # PlotUtils.setup_plot_directory()/PlotUtilsPlotly.write_output_files()
        # calls (same list SimplePlotExtension.py uses for the same reason).
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
        # Description for any option_group tags used below
        {"gliderdac": "NetCDF file generation for submission to the Glider DAC"},
        # Add these options that are local to this extension
        {
            "gliderdac_base_config": BaseOptsType.options_t(
                None,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_base_config",),
                BaseOpts.FullPathlib,
                {
                    "help": "GliderDAC base configuration YAML file - common for all Seagliders",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "gliderdac_project_config": BaseOptsType.options_t(
                None,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_project_config",),
                BaseOpts.FullPathlib,
                {
                    "help": "GliderDAC project configuration YAML file - common for single study area",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "gliderdac_deployment_config": BaseOptsType.options_t(
                None,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_deployment_config",),
                BaseOpts.FullPathlib,
                {
                    "help": "GliderDAC deployoment configuration YAML file - specific to the current glider deoployment",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "gliderdac_directory": BaseOptsType.options_t(
                None,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_directory",),
                BaseOpts.FullPathlib,
                {
                    "help": "Directory to place output files in",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "delayed_submission": BaseOptsType.options_t(
                False,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--delayed_submission",),
                bool,
                {
                    "help": "Generated files for delayed submission",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "gliderdac_plot_dives": BaseOptsType.options_t(
                False,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_plot_dives",),
                bool,
                {
                    "help": "Generate quick-check plots of the GliderDAC output for each dive",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
            "gliderdac_bin_width": BaseOptsType.options_t(
                0.0,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_bin_width",),
                float,
                {
                    "help": "Width of bins for GliderDAC file (0.0 indicates timeseries)",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                },
            ),
            "gliderdac_reduce_output": BaseOptsType.options_t(
                True,
                {
                    "Base",
                    "Reprocess",
                    "GliderDAC",
                },
                ("--gliderdac_reduce",),
                bool,
                {
                    "help": "No longer has any effect - output is never reduced/intersected across timeseries variables",
                    "section": "gliderdac",
                    "option_group": "gliderdac",
                    "action": BaseOptsType.DeprecateAction,
                },
            ),
        },
    )


def plot_gliderdac_dive(
    base_opts: BaseOpts.BaseOptions,
    gliderdac_nc_filename: pathlib.Path,
    template: dict[str, typing.Any] | None = None,
) -> tuple[list[plotly.graph_objects.Figure], list[pathlib.Path]]:
    """Generates quick-check plots of a GliderDAC output netCDF file.

    Re-opens gliderdac_nc_filename from disk (a freshly-written GliderDAC
    output, not the main per-dive netCDF) and produces one plot per science
    timeseries variable (value vs. depth, dive/climb split, QC value in the
    hover tooltip), following Plotting/DiveScience.py's conventions.
    Pressure/lat/lon/conductivity/depth/time are excluded (axes or not
    science content); temperature and salinity share one dual-x-axis plot.
    These are a quick sanity check on the GliderDAC output itself, not a
    replacement for the main Plotting/*.py pipeline.

    Args:
        base_opts: Options object.
        gliderdac_nc_filename: Path to the already-written GliderDAC output
            netCDF file to plot.
        template: Unused - accepted for API symmetry with the rest of
            GliderDAC.py's pipeline. Every value needed (units, long_name)
            is already present as an attribute on gliderdac_nc_filename's
            own variables, so re-reading from disk is self-sufficient.

    Returns:
        A tuple of (created Figures, written output file paths).
    """
    if base_opts.mission_dir:
        if PlotUtils.setup_plot_directory(base_opts):
            return ([], [])
    else:
        # Standalone single-file CLI mode - no mission plots/ directory to
        # default into (PlotUtils.setup_plot_directory() requires
        # mission_dir). Mirrors how gliderdac_directory itself falls back
        # in this mode: a "plots" directory alongside (not inside)
        # gliderdac_directory - gliderdac_directory.parent is the same
        # netcdf_filename.parent gliderdac_directory itself was derived
        # from, in both single-file and mission-dir modes.
        if not base_opts.plot_directory:
            base_opts.plot_directory = base_opts.gliderdac_directory.parent / "plots"
        if not base_opts.plot_directory.exists():
            try:
                base_opts.plot_directory.mkdir()
                base_opts.plot_directory.chmod(
                    stat.S_IRUSR
                    | stat.S_IWUSR
                    | stat.S_IXUSR
                    | stat.S_IRGRP
                    | stat.S_IXGRP
                    | stat.S_IWGRP
                    | stat.S_IROTH
                    | stat.S_IXOTH,
                )
            except Exception:
                log_error(f"Could not create {base_opts.plot_directory}", "exc")
                return ([], [])

    ds = Utils.open_netcdf_file(str(gliderdac_nc_filename))

    def _masked(var: netCDF4.Variable) -> np.ndarray:
        """Reads var's data as float, with its own _FillValue points
        replaced by NaN (Utils.open_netcdf_file opens with mask_results=
        False, so fill values otherwise come back as literal numbers -
        e.g. -999 - that swamp real readings on a plot)."""
        data = np.asarray(var[:], dtype=float)
        fill_value = getattr(var, "_FillValue", None)
        if fill_value is not None:
            data[data == fill_value] = np.nan
        return data

    try:
        dive_num = int(ds.variables["profile_id"][...])
        title_ident = f"{ds.trajectory} Dive {dive_num} Started {ds.time_coverage_start}"
        depth = _masked(ds.variables["depth"])
    except Exception:
        log_error(f"Could not load identity/depth from {gliderdac_nc_filename}", "exc")
        ds.close()
        return ([], [])

    max_depth_i = int(np.nanargmax(depth))
    point_num = np.arange(depth.size)

    skip_vars = {"pressure", "lat", "lon", "conductivity", "depth", "time"}
    plot_vars = [
        var_name
        for var_name, var in ds.variables.items()
        if var.dimensions == ("time",)
        and var_name not in skip_vars
        and f"{var_name}_qc" in ds.variables
    ]

    def _add_leg_traces(
        fig: plotly.graph_objects.Figure,
        var_name: str,
        long_name: str,
        units: str,
        xaxis: str,
    ) -> None:
        """Adds a dive-leg and climb-leg trace for one variable to fig."""
        data = _masked(ds.variables[var_name])
        qc_strs = np.asarray(QC.qc_to_str(QC.decode_qc(ds.variables[f"{var_name}_qc"][:])))
        for leg, sl, symbol, color in (
            ("Dive", slice(0, max_depth_i), "triangle-down", "Red"),
            ("Climb", slice(max_depth_i, None), "triangle-up", "Magenta"),
        ):
            fig.add_trace(
                {
                    "name": f"{long_name} {leg}",
                    "x": data[sl],
                    "y": depth[sl],
                    "customdata": np.squeeze(
                        np.dstack((point_num[sl], qc_strs[sl]))
                    ),
                    "xaxis": xaxis,
                    "yaxis": "y1",
                    "mode": "markers",
                    "marker": {"symbol": symbol, "color": color},
                    "hovertemplate": (
                        f"{long_name} {leg}<br>%{{x:.3f}} {units}<br>"
                        "%{y:.2f} m<br>%{customdata[0]:d} point_num<br>"
                        "%{customdata[1]}<extra></extra>"
                    ),
                }
            )

    ret_figs: list[plotly.graph_objects.Figure] = []
    ret_plots: list[pathlib.Path] = []

    for var_name in plot_vars:
        if var_name in ("temperature", "salinity"):
            continue  # plotted together below
        var = ds.variables[var_name]
        long_name = getattr(var, "long_name", var_name)
        units = getattr(var, "units", "")
        fig = plotly.graph_objects.Figure()
        _add_leg_traces(fig, var_name, long_name, units, "x1")
        fig.update_layout(
            {
                "xaxis": {"title": f"{long_name} ({units})", "showgrid": True},
                "yaxis": {
                    "title": "Depth (m)",
                    "showgrid": True,
                    "autorange": "reversed",
                },
                "title": {
                    "text": f"{title_ident}<br>{long_name} vs Depth",
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {"t": 150},
            }
        )
        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts, f"dv{dive_num:04d}_gliderdac_{var_name}", fig
            )
        )

    if "temperature" in plot_vars and "salinity" in plot_vars:
        temp_units = getattr(ds.variables["temperature"], "units", "")
        salinity_units = getattr(ds.variables["salinity"], "units", "")
        fig = plotly.graph_objects.Figure()
        _add_leg_traces(
            fig,
            "temperature",
            getattr(ds.variables["temperature"], "long_name", "Temperature"),
            temp_units,
            "x1",
        )
        _add_leg_traces(
            fig,
            "salinity",
            getattr(ds.variables["salinity"], "long_name", "Salinity"),
            salinity_units,
            "x2",
        )
        fig.update_layout(
            {
                "xaxis": {
                    "title": f"Temperature ({temp_units})",
                    "showgrid": True,
                    "side": "bottom",
                },
                "xaxis2": {
                    "title": f"Salinity ({salinity_units})",
                    "overlaying": "x1",
                    "side": "top",
                    "showgrid": False,
                },
                "yaxis": {
                    "title": "Depth (m)",
                    "showgrid": True,
                    "autorange": "reversed",
                },
                "title": {
                    "text": f"{title_ident}<br>Temperature/Salinity vs Depth",
                    "xanchor": "center",
                    "yanchor": "top",
                    "x": 0.5,
                    "y": 0.95,
                },
                "margin": {"t": 150},
            }
        )
        ret_figs.append(fig)
        ret_plots.extend(
            PlotUtilsPlotly.write_output_files(
                base_opts, f"dv{dive_num:04d}_gliderdac_temperature_salinity", fig
            )
        )

    ds.close()
    return (ret_figs, ret_plots)


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
) -> int:
    """Basestation extension for creating simplified netCDF files

    Args:
        cmdline_args: Command line arguments, used to build base_opts when
            base_opts isn't already provided.
        instrument_id: Unused; part of the standard basestation extension
            signature.
        base_opts: Options object; self-constructed from cmdline_args if
            not provided.
        sg_calib_file_name: Unused; part of the standard basestation
            extension signature.
        dive_nc_file_names: Per-dive netCDF files to process. Collected via
            base_opts.mission_dir if not provided.
        nc_files_created: Per-dive netCDF files created by an earlier
            pipeline stage this run - takes priority over
            dive_nc_file_names when provided.
        processed_other_files: Optional; if provided, each GliderDAC output
            netCDF path is appended to this list.
        known_mailer_tags: Unused; part of the standard basestation
            extension signature.
        known_ftp_tags: Unused; part of the standard basestation extension
            signature.
        processed_file_names: Unused; part of the standard basestation
            extension signature.

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
            "Basestation extension for creating GliderDAC netCDF files",
            additional_arguments=additional_arguments,
            add_option_groups=add_option_groups,
            add_to_arguments=add_to_arguments,
            cmdline_args=cmdline_args,
        )

        global DEBUG_PDB
        DEBUG_PDB = base_opts.debug_pdb

    BaseLogger(base_opts)

    # GliderDAC.py never uses TraceArray's MATLAB-comparison tracing (that's
    # MakeDiveProfiles.py's own debug mechanism) - disable it so
    # QC.assert_qc()'s trace_array() calls don't print "Run trace_results()
    # before calling trace routines!" every time (tracing defaults to
    # enabled-but-no-file-open at process start).
    TraceArray.trace_disable()

    if base_opts.delayed_submission:
        delayed_str = "_delayed"
    else:
        delayed_str = ""

    processing_start_time = time.gmtime(time.time())
    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", processing_start_time)
    )

    if not base_opts.mission_dir:
        if hasattr(base_opts, "netcdf_filename") and base_opts.netcdf_filename:
            # Called from CLI with a single argument
            # TODO assert_type(base_opts.netcdf_filename, pathlib.Path)
            dive_nc_file_names = [base_opts.netcdf_filename]
            if not base_opts.gliderdac_directory:
                base_opts.gliderdac_directory = (
                    base_opts.netcdf_filename.parent / "gliderdac"
                )
    else:
        if nc_files_created is not None:
            dive_nc_file_names = nc_files_created
        elif dive_nc_file_names is None:
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        if not base_opts.gliderdac_directory:
            base_opts.gliderdac_directory = base_opts.mission_dir / "gliderdac"

    if dive_nc_file_names is None:
        log_error("Either mission_dir or netcdf_file must be specified")
        return 1

    if not base_opts.gliderdac_directory.exists():
        try:
            base_opts.gliderdac_directory.mkdir()
            # Ensure that MoveData can move it as pilot if not run as the glider account
            base_opts.gliderdac_directory.chmod(
                stat.S_IRUSR
                | stat.S_IWUSR
                | stat.S_IXUSR
                | stat.S_IRGRP
                | stat.S_IXGRP
                | stat.S_IWGRP
                | stat.S_IROTH
                | stat.S_IXOTH,
            )
        except Exception:
            log_error(f"Could not create {base_opts.gliderdac_directory}", "exc")
            log_info("Bailing out")
            return 1

    template = load_templates(base_opts)
    if not template:
        return 1

    def _base_qc(var_name: str) -> int | np.int8 | None:
        """Resolve a variable's base QC value the same way create_nc_var
        does - from its template's qc_data field if present, else
        QC_NO_CHANGE.

        Args:
            var_name: Name of the variable as it appears in template.

        Returns:
            The resolved base QC value.
        """
        if "qc_data" in template["variables"][var_name]:
            return lookup_qc_val(template["variables"][var_name]["qc_data"])
        return QC.QC_NO_CHANGE

    # Default timeseries variables and the name mapping
    # Can be overridden by same names in the "config" dictionary from the template(s)
    requested_timeseries_vars = {
        "temperature": "temperature",
        "salinity": "salinity",
        "conductivity": "conductivity",
        "latitude": "lat",
        "longitude": "lon",
        "ctd_pressure": "pressure",
    }

    # Update anything overridden by config
    if "config" in template and "timeseries_vars" in template["config"]:
        requested_timeseries_vars = template["config"]["timeseries_vars"]

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)
        try:
            dsi = xr.open_dataset(dive_nc_file_name, decode_times=False)
        except Exception:
            log_error(f"Error opening {dive_nc_file_name}", "exc")
            continue

        dso = xr.Dataset()

        if "ctd_time" not in dsi or "ctd_depth" not in dsi:
            log_error("Could not load variables - skipping", "exc")
            continue

        # Inventory timeseries variables - construct a master time vector and interpolate missing depth points
        time_vars = set()
        # Reset this every time in case of processing multiple files
        timeseries_vars = {}
        for var_name, var_content in requested_timeseries_vars.items():
            if var_name not in dsi.variables:
                log_warning(
                    f"Requested variable {var_name} not in {dive_nc_file_name} - skipping"
                )
                continue
            timeseries_vars[var_name] = var_content
            dims = dsi[var_name].dims
            for vv in dsi.variables:
                vv_name = str(vv)
                if (
                    dsi[vv].dims == dims
                    and vv_name.endswith("_time")
                    and "_results_" not in vv_name
                ):
                    time_vars.add((vv_name, dims))

        unsorted_master_time = np.zeros(0)
        dims_map = {}
        last_i = 0
        for t_var, t_dim in time_vars:
            # Xarray converts to numpy.datetime64(ns) - get it back to something useful
            # new_time_v = dsi[t_var].data.astype(np.float64) / 1000000000.0
            new_time_v = dsi[t_var]
            dims_map[t_dim] = dim_map_t(last_i, last_i + len(new_time_v))
            last_i += len(new_time_v)
            unsorted_master_time = np.concatenate((unsorted_master_time, new_time_v))
        del time_vars
        sort_i = np.argsort(unsorted_master_time)
        # NOTE: A possible issue is if there are repeated time values in different time_vars.
        # A solution is to wrap the call below with np.unique(), but is not tested
        master_time = unsorted_master_time[sort_i]

        master_depth = NetCDFUtils.interp1_extend(
            # dsi["ctd_time"].data.astype(np.float64) / 1000000000.0,
            dsi["ctd_time"].data,
            dsi["ctd_depth"].data,
            master_time,
        )

        if base_opts.gliderdac_bin_width:
            max_depth = np.floor(np.nanmax(master_depth))
            # This is actually bin edges, so one more point then actual bins
            bin_edges = np.arange(
                -base_opts.gliderdac_bin_width / 2.0,
                max_depth + base_opts.gliderdac_bin_width / 2.0 + 0.01,
                base_opts.gliderdac_bin_width,
            )

            # Do this to ensure everything is caught in the binned statistic
            bin_edges[0] = -20.0
            bin_edges[-1] = max_depth + 50.0

            bin_centers_down = np.arange(
                0.0, max_depth + 0.01, base_opts.gliderdac_bin_width
            )
            max_depth_i = find_deepest_bin_i(
                master_depth, bin_centers_down, base_opts.gliderdac_bin_width
            )

            bin_centers = np.concatenate(
                (bin_centers_down, bin_centers_down[:-1][::-1])
            )

            t_profile = np.zeros(len(bin_centers))

            t_profile[: len(bin_centers_down)] = NetCDFUtils.interp1_extend(
                master_depth[:max_depth_i], master_time[:max_depth_i], bin_centers_down
            )
            t_profile[len(bin_centers_down) :] = NetCDFUtils.interp1_extend(
                master_depth[max_depth_i:],
                master_time[max_depth_i:],
                bin_centers_down[1:][::-1],
            )

        # Note: for non-binned, this variable is just a copy of the data straight from
        # the netcdf file
        binned_vars = {}
        for var_name in timeseries_vars:
            log_debug(f"Adding variable {var_name}")
            data = load_var(
                dsi,
                var_name,
                dims_map,
                sort_i,
            )
            if data is None:
                # load_var already logged the mismatch - skip this variable
                # rather than crash on it below.
                continue
            if base_opts.gliderdac_bin_width:
                # Calculated above
                # max_depth_i = find_deepest_bin_i(
                #    master_depth, bin_edges, base_opts.gliderdac_bin_width
                # )

                var_v = np.zeros(np.size(bin_centers)) * np.nan
                n_obs = np.zeros(np.size(bin_centers))
                (
                    var_v[: np.size(bin_centers_down)],
                    n_obs[: np.size(bin_centers_down)],
                    *_,
                ) = NetCDFUtils.bindata(
                    master_depth[:max_depth_i], data[:max_depth_i], bin_edges
                )

                var_tmp, n_obs_tmp, *_ = NetCDFUtils.bindata(
                    master_depth[max_depth_i:], data[max_depth_i:], bin_edges
                )
                var_v[np.size(bin_centers_down) :] = var_tmp[:-1][::-1]
                n_obs[np.size(bin_centers_down) :] = n_obs_tmp[:-1][::-1]
                binned_vars[var_name] = (var_v, n_obs)
            else:
                # With the new remapping code, data isn't a xarray object, but a numpy object
                # binned_vars[var_name] = (data.data,)
                binned_vars[var_name] = (data,)

        # Create variables
        output_vars = {}
        for var_name, val in binned_vars.items():
            output_vars[var_name] = val[0].copy()
            create_nc_var(
                dso,
                template,
                timeseries_vars[var_name],
                output_vars[var_name],
            )
            # This is just for debugging
            # if base_opts.gliderdac_bin_width and var_name == "temperature":
            #    create_nc_var(dso, template, "temperature_n", val[1])

        if base_opts.gliderdac_bin_width:
            depth_var = bin_centers.copy()
            time_var = t_profile.copy()
            del (
                bin_centers,
                t_profile,
            )
            depth_qc_v = None
        else:
            depth_var = master_depth.copy()
            time_var = master_time.copy()
            depth_qc_v = QC.initialize_qc(len(depth_var), _base_qc("depth"))
            QC.assert_qc(
                QC.QC_INTERPOLATED,
                depth_qc_v,
                np.nonzero(np.logical_not(np.isin(time_var, dsi["ctd_time"].data)))[0],
                "depth interpolated onto non-CTD sample time",
                log_changes=False,
            )

        # Lat/lon are only densely sampled on the CTD timebase - interpolate
        # onto every other science variable's own sample time too, and mark
        # the filled-in points QC_INTERPOLATED (matches lat/lon's existing
        # "Values may be interpolated between measured GPS fixes" template
        # comment, docs/gliderdac/seaglider.yml).
        for ll_var in ("latitude", "longitude"):
            ll_qc_v = QC.initialize_qc(
                len(output_vars[ll_var]), _base_qc(timeseries_vars[ll_var])
            )
            nan_v = np.isnan(output_vars[ll_var])
            if np.nonzero(nan_v)[0].size:
                output_vars[ll_var][nan_v] = NetCDFUtils.interp1_extend(
                    time_var[np.logical_not(nan_v)],
                    output_vars[ll_var][np.logical_not(nan_v)],
                    time_var[nan_v],
                )
                QC.assert_qc(
                    QC.QC_INTERPOLATED,
                    ll_qc_v,
                    np.nonzero(nan_v)[0],
                    f"{ll_var} interpolated onto non-CTD sample time",
                    log_changes=False,
                )
            create_nc_var(
                dso,
                template,
                timeseries_vars[ll_var],
                output_vars[ll_var],
                qc_val=ll_qc_v,
            )

        # lat/lon are now densely interpolated (see above), but gsw.SA_from_SP
        # returns NaN wherever salinity itself is NaN regardless of lon/lat -
        # no need to mask lat/lon to non-interpolated points here (confirmed
        # empirically).
        salinity_absolute = gsw.SA_from_SP(
            output_vars["salinity"],
            np.zeros(output_vars["salinity"].size),
            output_vars["longitude"],
            output_vars["latitude"],
        )
        density = gsw.rho_t_exact(
            salinity_absolute,
            output_vars["temperature"],
            np.zeros(salinity_absolute.size),
        )
        create_nc_var(
            dso,
            template,
            "density",
            density,
        )

        del binned_vars

        # Depth and time
        create_nc_var(
            dso,
            template,
            "depth",
            depth_var,
            qc_val=depth_qc_v,
        )
        create_nc_var(
            dso,
            template,
            "time",
            time_var,
        )

        # Singleton variables

        # Time related
        start_ts = time.strftime("%Y%m%dT%H%M", time.gmtime(dsi.attrs["start_time"]))
        trajectory_name = f"{dsi.attrs['platform_id'].lower()}-{start_ts}"
        dso.attrs["trajectory"] = trajectory_name
        create_nc_var(dso, template, "trajectory", trajectory_name)
        dso.attrs["time_coverage_start"] = f"{start_ts}Z"
        dso.attrs["time_coverage_end"] = time.strftime(
            "%Y%m%dT%H%MZ", time.gmtime(np.nanmax(time_var))
        )
        dso.attrs["id"] = trajectory_name

        # Variables
        create_nc_var(dso, template, "profile_id", dsi.attrs["dive_number"])

        median_time_i = np.abs(time_var - np.median(time_var)).argmin()
        create_nc_var(
            dso,
            template,
            "profile_time",
            time_var[median_time_i],
        )

        create_nc_var(
            dso,
            template,
            "profile_lat",
            output_vars["latitude"][median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "profile_lon",
            output_vars["longitude"][median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "v",
            dsi["depth_avg_curr_north"],
            qc_val=dsi["depth_avg_curr_qc"],
        )
        create_nc_var(
            dso,
            template,
            "u",
            dsi["depth_avg_curr_east"],
            qc_val=dsi["depth_avg_curr_qc"],
        )
        create_nc_var(
            dso,
            template,
            "time_uv",
            time_var[median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "lat_uv",
            output_vars["latitude"][median_time_i],
        )
        create_nc_var(
            dso,
            template,
            "lon_uv",
            output_vars["longitude"][median_time_i],
        )

        # This varibles are just to hold the attched metadata
        metadata_vars = ["platform"]
        for var_n in template["variables"]:
            if var_n.startswith("instrument_"):
                metadata_vars.append(var_n)

        for var_n in metadata_vars:
            create_nc_var(
                dso,
                template,
                var_n,
                template["variables"][var_n]["attributes"]["_FillValue"],
            )

        # attributes
        dso.attrs["history"] = (
            f"{time.strftime('%Y-%m-%dT%H:%M:%SZ', processing_start_time)}: GliderDac.py"
        )
        now_ts = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
        dso.attrs["date_created"] = now_ts
        dso.attrs["date_issued"] = now_ts
        dso.attrs["date_modified"] = now_ts

        #
        # These are not required by the spec
        #
        # per-profile "date_created": "2021-07-16T15:16:27.037189",
        # per-profile "date_modified": "2021-07-19T15:44:11.181969",
        # per-profile "date_issued": "2021-07-19T15:44:57.933159",
        # per-profile "geospatial_bounds": "POLYGON ((-117.6545 33.2183, -117.6833 33.2308, -117.6761 33.227675, -117.6545 33.2183))",
        # for a in (
        #     "geospatial_lat_min",
        #     "geospatial_lat_max",
        #     "geospatial_lon_min",
        #     "geospatial_lon_max",
        # ):
        #     dso.attrs[a] = np.format_float_positional(
        #         dsi.attrs[a], precision=4, unique=False
        #     )

        # dso.attrs["geospatial_vertical_min"] = np.format_float_positional(
        #     np.floor(np.nanmin(depth_var)), precision=2, unique=False
        # )
        # dso.attrs["geospatial_vertical_max"] = np.format_float_positional(
        #     np.ceil(np.nanmax(depth_var)), precision=2, unique=False
        # )

        # Apply global attributes from template
        for k, v in template["global_attributes"].items():
            dso.attrs[k] = v

        netcdf_out_filename: pathlib.Path = (
            base_opts.gliderdac_directory
            / f"{trajectory_name}Z{delayed_str}.nc".replace("-", "_")
        )
        comp: dict[str, typing.Any] = dict(zlib=True, complevel=9)
        # encoding = {var: comp for var in dso.data_vars}
        encoding: dict[typing.Any, dict[str, typing.Any]] = {}
        for var in dso.data_vars:
            encoding[var] = comp.copy()
            if template["variables"][var]["type"] == "c":
                encoding[var]["char_dim_name"] = template["variables"][var][
                    "dimensions"
                ][0]
        dso.to_netcdf(
            netcdf_out_filename,
            "w",
            encoding=encoding,
            # engine="netcdf4",
            format="NETCDF4",
        )

        if processed_other_files is not None:
            processed_other_files.append(netcdf_out_filename)

        if base_opts.gliderdac_plot_dives:
            plot_gliderdac_dive(base_opts, netcdf_out_filename, template)

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
        sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())

    sys.exit(retval)
