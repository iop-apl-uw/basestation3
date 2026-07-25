#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

"""Generates cut-and-paste proposed CTD sampling-schedule text for the WKB
schedule plot, always in scicon.sch's `ct = { ... }` format regardless of
the dive's actual CT mount (see proposed_config_text) - and reports the
dive's actual CT type/mount for the plot's explanatory note (ct_type_name,
ct_mount).
"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import math
import typing

import numpy as np
from numpy.typing import NDArray

import MakeDiveProfiles


def _sg_ct_type(dive_nc_file) -> int | None:
    """Reads sg_cal_sg_ct_type, or None if the variable is absent (older files)."""
    if "sg_cal_sg_ct_type" not in dive_nc_file.variables:
        return None
    return int(dive_nc_file.variables["sg_cal_sg_ct_type"].getValue())


def ct_type_name(dive_nc_file) -> str:
    """Human-readable CT sensor type, e.g. "unpumped RBR Legato".

    Args:
        dive_nc_file: Open per-dive netCDF dataset.

    Returns:
        The name from MakeDiveProfiles.sb_ct_type_map, or "unknown" if
        sg_cal_sg_ct_type is absent or an unrecognized value.
    """
    ct_type = _sg_ct_type(dive_nc_file)
    if ct_type is None:
        return "unknown"
    return MakeDiveProfiles.sb_ct_type_map.get(ct_type, f"unknown (type {ct_type})")


def ct_mount(dive_nc_file) -> typing.Literal["truck", "scicon", "logger"]:
    """Determines the dive's CT sensor mount: "truck", "scicon", or "logger".

    GPCTD (sg_cal_sg_ct_type == 2) is always logger-mounted - its own
    dedicated data path (Sensors/payload_ext.py), never through the truck
    science file or scicon.sch. Legato (sg_cal_sg_ct_type == 4) is usually
    truck- or scicon-mounted, distinguished the same way DiveCTD.py/
    DiveLegatoData.py do (by which netCDF variable is present), but can
    occasionally be logger-mounted too - that case isn't yet confirmed by a
    real test fixture (basestation3/.claude/PLAN.md Task 5), so it's a
    best-guess fallback when neither the truck nor scicon marker variable is
    present. Classic unpumped Seabird CTDs (types 0/1/3, including SAILCT)
    are always truck-mounted; an absent sg_cal_sg_ct_type (older files)
    falls back to truck too, matching DiveCTD.py/DiveTS.py's own handling.

    Args:
        dive_nc_file: Open per-dive netCDF dataset.

    Returns:
        "truck", "scicon", or "logger".
    """
    ct_type = _sg_ct_type(dive_nc_file)
    if ct_type == 2:
        return "logger"
    if ct_type == 4:
        if "legato_time" in dive_nc_file.variables:
            return "scicon"
        if "eng_rbr_temp" in dive_nc_file.variables:
            return "truck"
        return "logger"
    return "truck"


def _ct_block(depth_intervals: list[tuple[float, float]]) -> str:
    """Formats (depth, interval) pairs as a `ct = { depth,seconds ... }` block.

    Pairs whose interval is NaN (e.g. a bucket deeper than the dive
    actually reached) are omitted - "500,nan" isn't a usable schedule
    entry, either to read or to paste into scicon.sch.
    """
    lines = [f" {depth:.0f},{interval:.1f}" for depth, interval in depth_intervals if not math.isnan(interval)]
    return "ct = {\n" + "\n".join(lines) + "\n}"


def scicon_ct_block(buckets_depths: NDArray[np.floating], sampling_rate: NDArray[np.floating]) -> str:
    """Builds a scicon.sch `ct = { depth,seconds ... }` block.

    Args:
        buckets_depths: Depth bucket boundaries (m), ascending.
        sampling_rate: Proposed sampling interval (s) at each bucket.

    Returns:
        The `ct = { ... }` block text, matching scicon.sch's grammar
        (validate.sciconsch).
    """
    return _ct_block(list(zip((float(d) for d in buckets_depths), (float(r) for r in sampling_rate), strict=True)))


def ctd_instrument_name(dive_nc_file) -> str:
    """Determines the science-grid instrument name for the dive's CT sensor.

    Matches the exact classification DiveCTD.py uses to pick its ctd_type
    for PlotUtils.collect_timeouts/add_sample_range_overlay, since
    ScienceGrid.find_current_grid keys its schemes on this same canonical
    name (post Sensors.process_sensor_extensions remapping), not the raw
    "ct"/"legatoPoll" names seen in scicon.att.

    Args:
        dive_nc_file: Open per-dive netCDF dataset.

    Returns:
        "legato", "gpctd", or "sbect".
    """
    is_legato = (
        "sg_cal_sg_ct_type" in dive_nc_file.variables
        and dive_nc_file.variables["sg_cal_sg_ct_type"].getValue() == 4
    )
    if is_legato:
        return "legato"
    if "gpctd_time" in dive_nc_file.variables:
        return "gpctd"
    return "sbect"


def current_grid_block(grid: dict) -> str | None:
    """Formats a ScienceGrid.find_current_grid() result as a `ct = { ... }` block.

    Args:
        grid: The `.grid` field of the instra_grid_tuple returned by
            ScienceGrid.find_current_grid - a dict mapping depth (float, or
            a non-numeric metadata key like "profile") to sample interval
            (s).

    Returns:
        The `ct = { ... }` block text, or None if grid has no depth entries
        (e.g. no active scheme found for this dive/instrument).
    """
    depth_intervals = []
    for depth, interval in grid.items():
        try:
            depth_intervals.append((float(depth), float(interval)))
        except (TypeError, ValueError):
            continue
    if not depth_intervals:
        return None
    depth_intervals.sort()
    return _ct_block(depth_intervals)


def comment_line(label: str) -> str:
    """Builds a scicon.sch-style comment line identifying which schedule follows.

    validate.py treats any line starting with "/" as a comment (skipped),
    for both the science and scicon.sch grammars - so this is safe to paste
    directly above a ct = { ... } block.

    Args:
        label: "Current" for the current sampling, or "%+0"/"%-20"/"%+50"
            etc. matching the percent-difference shown in that option's
            legend trace name (ctd_sampling.plotting's `pct` computation).

    Returns:
        The comment line, e.g. "/ Current" or "/ %-20".
    """
    return f"/ {label}"


def proposed_config_text(
    buckets_depths: NDArray[np.floating],
    sampling_rate: NDArray[np.floating],
) -> str:
    """Builds the cut-and-paste proposed CTD sampling-schedule text for one WKB option.

    Always in scicon.sch's `ct = { ... }` format, regardless of the dive's
    actual CT mount - illustrative/comparative, not literally "paste this
    into your truck's science file". The truck's science file has no
    isolated "CTD section" the way scicon does (its seconds= is shared
    across every sensor sampled in that depth bin, not CT-specific), so a
    truck-specific proposal was never well-founded; scicon's format is used
    uniformly instead. See ct_mount/ct_type_name for reporting the dive's
    actual mount/type in the plot's explanatory note - that's the only place
    mount varies the display, not this text.

    Args:
        buckets_depths: Depth bucket boundaries (m), ascending.
        sampling_rate: Proposed sampling interval (s) at each bucket (dive
            direction).

    Returns:
        The proposed config text.
    """
    return scicon_ct_block(buckets_depths, sampling_rate)
