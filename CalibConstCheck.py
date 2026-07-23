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

"""CalibConstCheck.py: validates a sg_calib_constants.m file against the known
calibration constant registry, applying static range checks and specialized
cross-checks (e.g. mass, Seabird CT coefficients) against a selftest capture
or per-dive log file.
"""

import os
import pathlib
import re
import sys
import time
from collections.abc import Callable
from typing import TypedDict

import numpy as np

import BaseNetCDF
import BaseOpts
import CalibConst
import compare
import Globals
import MakeDiveProfiles
from BaseLog import BaseLogger, log_critical, log_error, log_info, log_warning

# The three keys CalibConst.getSGCalibrationConstants requires to be present.
REQUIRED_KEYS = ("id_str", "mission_title", "mass")

# Keys that FlightModel v3 supplies at runtime; CalibConst.py actively warns
# and skips these unless '% FM_ignore' is present on the line, or
# --skip_flight_model is used. See Globals.py:104-119.
_FLIGHT_MODEL_KEYS = frozenset(Globals.flight_variables) | {"vbdbias_drift"}


class Finding(TypedDict):
    """One validation result for a sg_calib_constants.m key (or checker group).

    Attributes:
        key: The calib_consts key name this finding is about.
        known: Whether key is a recognized sg_calib_constants.m variable.
        status: One of "ok", "warn", "crit", "unknown", or "not_checked".
        value: The value found in sg_calib_constants.m, if any.
        expected: Human-readable description of the expected value/range.
        message: Human-readable explanation, empty if status is "ok".
    """

    key: str
    known: bool
    status: str
    value: str | float | int | None
    expected: str
    message: str


CheckerFn = Callable[
    [dict[str, str | float | int], pathlib.Path | None], list[Finding]
]

# Relative severity used when an advisory (below) and a range/checker result
# disagree on status - the more severe of the two wins, but the advisory
# message is always appended regardless.
_SEVERITY_RANK: dict[str, int] = {
    "ok": 0,
    "not_checked": 0,
    "unknown": 0,
    "warn": 1,
    "sers": 2,
    "crit": 3,
}

AdvisoryPredicate = Callable[[str | float | int | None], bool]

# Keys that deserve a pilot's attention regardless of whether their value
# passes a range check - e.g. a setting that's experimental, or normally
# belongs to a different processing stage than real-time flight. Maps key ->
# (status, message, predicate). status sets/upgrades the Finding's color
# (via the same "crit"/"sers"/"warn" -> red/orange/yellow vocabulary used
# throughout SelftestHTML.py); message is appended to the Finding's existing
# message; predicate (if not None) is called with the key's value and must
# return True for the advisory to apply - use this to only flag a value when
# a boolean-style flag is actually enabled, for example.
ADVISORIES: dict[str, tuple[str, str, AdvisoryPredicate | None]] = {
    "depth_slope_correction_gold_standard": (
        "crit",
        "Generally used in post-processing",
        None,
    ),
    "smooth_truck_pressure": (
        "warn",
        "Very experimental",
        lambda v: isinstance(v, (int, float)) and v != 0,
    ),
    # Keys that are known/registered but explicitly ignored elsewhere in the
    # processing pipeline - set here has no effect on the result. Sourced
    # from the "Warn on attempted use of old ... limit types" checks in
    # MakeDiveProfiles.py:4483-4511 and the "motor limits and rates
    # (UNUSED--look at $PITCH_MAX, etc...)" comment block in
    # BaseNetCDF.py:760-772.
    "sbe_temp_freq_min": (
        "warn",
        "Ignored during dive processing - use QC_temp_min/QC_temp_max instead",
        None,
    ),
    "sbe_temp_freq_max": (
        "warn",
        "Ignored during dive processing - use QC_temp_min/QC_temp_max instead",
        None,
    ),
    "sbe_cond_freq_min": (
        "warn",
        "Ignored during dive processing - use QC_cond_min/QC_cond_max instead",
        None,
    ),
    "sbe_cond_freq_max": (
        "warn",
        "Ignored during dive processing - use QC_cond_min/QC_cond_max instead",
        None,
    ),
    "pitch_max_cnts": (
        "warn",
        "Unused - motor limits are controlled by $PITCH_MAX/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "pitch_min_cnts": (
        "warn",
        "Unused - motor limits are controlled by $PITCH_MIN/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "roll_max_cnts": (
        "warn",
        "Unused - motor limits are controlled by $ROLL_MAX/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "roll_min_cnts": (
        "warn",
        "Unused - motor limits are controlled by $ROLL_MIN/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "vbd_max_cnts": (
        "warn",
        "Unused - motor limits are controlled by $VBD_MAX/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "vbd_min_cnts": (
        "warn",
        "Unused - motor limits are controlled by $VBD_MIN/etc glider parameters, not sg_calib_constants.m",
        None,
    ),
    "vbd_cnts_per_cc": (
        "warn",
        "Unused - motor rates are controlled by glider parameters, not sg_calib_constants.m",
        None,
    ),
    "pump_rate_intercept": (
        "warn",
        "Unused - motor rates are controlled by glider parameters, not sg_calib_constants.m",
        None,
    ),
    "pump_rate_slope": (
        "warn",
        "Unused - motor rates are controlled by glider parameters, not sg_calib_constants.m",
        None,
    ),
    "pump_power_intercept": (
        "warn",
        "Unused - motor rates are controlled by glider parameters, not sg_calib_constants.m",
        None,
    ),
    "pump_power_slope": (
        "warn",
        "Unused - motor rates are controlled by glider parameters, not sg_calib_constants.m",
        None,
    ),
    "Voffset": (
        "warn",
        "Unused - retained for legacy sg_calib_constants.m compatibility (sbe43_ext.py)",
        None,
    ),
}


def _apply_advisories(findings: list[Finding]) -> None:
    """Applies ADVISORIES to findings in place.

    Args:
        findings: The findings list being built by check_calib_constants,
          mutated in place.
    """
    for f in findings:
        advisory = ADVISORIES.get(f["key"])
        if advisory is None:
            continue
        status, message, predicate = advisory
        if predicate is not None and not predicate(f["value"]):
            continue
        if _SEVERITY_RANK[status] > _SEVERITY_RANK.get(f["status"], 0):
            f["status"] = status
        f["message"] = f"{f['message']}; {message}" if f["message"] else message

# ---------------------------------------------------------------------------
# Known-variable registry
# ---------------------------------------------------------------------------

# Entries contributed at runtime by Sensors/*_ext.py extension modules via
# meta_data_adds, which are only merged into BaseNetCDF.nc_var_metadata after
# Sensors.init_extensions(base_opts) runs. The CLI entry point below calls
# init_extensions() for an accurate mission-specific registry; long-lived
# callers (e.g. SelftestHTML.py, hosted by the always-running vis.py process)
# cannot safely call init_extensions() a second time (Sensors.py:415), so they
# rely on this hand-maintained supplement instead. Keep in sync by hand if new
# Sensors/*_ext.py extensions are added.
#
# Known casing/registration gaps, surfaced here rather than silently patched:
#   - "PCor" (mixed-case, a legacy depth-correction flag read in
#     MakeDiveProfiles.py) is a *different* key from "Pcor" (lowercase, the
#     SBE43 pressure-correction coefficient read in sbe43_ext.py).
#   - sbe43_ext.py reads calib_consts["Tau20"], but the netCDF registry key
#     (when registered) is "sg_cal_tau20" (lowercase) - both spellings are
#     included below so neither is reported unknown.
#   - "remap_optode_eng_cols" (read in aa4330_ext.py) has no corresponding
#     registry entry at all, unlike its sibling "remap_wetlabs_eng_cols".
_SBE43_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    "calibcomm_oxygen": (True, "SBE43 serial number and calibration date"),
    "Soc": (False, "SBE43 oxygen signal slope"),
    "Foffset": (False, "SBE43 frequency offset"),
    "A": (False, "SBE43 Bittig temperature-correction coefficient"),
    "B": (False, "SBE43 Bittig temperature-correction coefficient"),
    "C": (False, "SBE43 Bittig temperature-correction coefficient"),
    "E": (False, "SBE43 Bittig pressure-correction coefficient"),
    "o_a": (False, "SBE43 Owens-Millard coefficient"),
    "o_b": (False, "SBE43 Owens-Millard coefficient"),
    "o_c": (False, "SBE43 Owens-Millard coefficient"),
    "o_e": (False, "SBE43 Owens-Millard pressure coefficient"),
    "Tau20": (False, "SBE43 sensor time constant at 20C, 1 atm, 0 PSU"),
    "tau20": (False, "SBE43 sensor time constant at 20C, 1 atm, 0 PSU"),
    "D1": (False, "SBE43 Bittig compensation coefficient"),
    "D2": (False, "SBE43 Bittig compensation coefficient"),
    "Boc": (False, "SBE43 oxygen signal slope (alternate/legacy form)"),
    "Pcor": (False, "SBE43 pressure correction coefficient"),
    "Tcor": (False, "SBE43 temperature correction coefficient"),
    "Voffset": (False, "SBE43 voltage offset (unused)"),
    "comm_oxy_type": (
        True,
        "Oxygen sensor variant/model, e.g. 'SBE_43f', 'Pumped_SBE_43f', 'AA4330', 'AA4831'",
    ),
}

_AA3830_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    "calibcomm_optode": (True, "Aanderaa optode serial number and calibration date"),
    **{
        f"optode_C{i}{j}Coef": (False, "Aanderaa 3830 Stern-Volmer coefficient matrix entry")
        for i in range(5)
        for j in range(4)
    },
}

_AA4330_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    **{
        f"optode_TempCoef{i}": (False, "Aanderaa 4330 temperature compensation coefficient")
        for i in range(6)
    },
    **{
        f"optode_PhaseCoef{i}": (False, "Aanderaa 4330 phase coefficient")
        for i in range(4)
    },
    **{
        f"optode_ConcCoef{i}": (False, "Aanderaa 4330 concentration coefficient")
        for i in range(2)
    },
    **{
        f"optode_FoilCoefA{i}": (False, "Aanderaa 4330 foil coefficient (A series)")
        for i in range(14)
    },
    **{
        f"optode_FoilCoefB{i}": (False, "Aanderaa 4330 foil coefficient (B series)")
        for i in range(14)
    },
    **{
        f"optode_SVUCoef{i}": (False, "Aanderaa 4330 Stern-Volmer-Uchida coefficient")
        for i in range(7)
    },
    "optode_SVU_enabled": (
        False,
        "Whether to use the SVU (1) or foil polynomial (0) O2 calculation",
    ),
    "optode_st_calphase": (
        False,
        "Optode calphase reading captured during selftest, for air-cal gain correction",
    ),
    "optode_st_temp": (
        False,
        "Optode temperature reading captured during selftest, for air-cal gain correction",
    ),
    "optode_st_slp": (
        False,
        "Local sea-level pressure at time of selftest, for air-cal gain correction",
    ),
}

_VELO_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    "velo_A": (False, "VELO sensor calibration coefficient A"),
    "velo_B": (False, "VELO sensor calibration coefficient B"),
}

_LEGATO_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    "legato_sealevel": (
        False,
        "Assumed pressure reading at sealevel (dbar * 1000), required for Legato",
    ),
    "legato_config": (
        False,
        "Bitfield describing the Legato configuration when run as a logdev",
    ),
    # Read in Sensors/legato_ext.py:249 but never netCDF-registered at all
    # (not even via a runtime extension) - a genuine pre-existing gap.
    "ignore_truck_legato": (
        False,
        "Ignore any Legato columns present in the truck .eng file",
    ),
}

_CODA_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    "codaTODO_c0": (False, "RBR codaTODO per-instrument O2 correction coefficient"),
    "codaTODO2_c0": (False, "RBR codaTODO2 per-instrument O2 correction coefficient"),
}

_WETLABS_INSTRUMENTS = ("wlbb2fl", "wlbbfl2", "wlbb3", "wlfl3")
_WETLABS_CHANNELS = (
    "sig470nm",
    "sig532nm",
    "sig700nm",
    "sig880nm",
    "sig460nm",
    "sig530nm",
    "sig570nm",
    "sig680nm",
    "sig695nm",
)
_WETLABS_SUFFIXES = (
    ("dark_counts", "dark counts"),
    ("scale_factor", "scale factor"),
    ("resolution_counts", "resolution, counts"),
    ("max_counts", "maximum output, counts"),
)


def _wetlabs_supplement() -> dict[str, tuple[bool, str]]:
    """Builds the fixed WETLabs per-instrument, per-channel key list.

    Returns:
        Mapping of WETLabs calibration key name to (is_string, description),
        covering every documented instrument/channel/suffix combination.
    """
    entries: dict[str, tuple[bool, str]] = {
        "calibcomm_wetlabs": (True, "WETLabs serial number and calibration date"),
        "remap_wetlabs_eng_cols": (True, "Dictionary for remapping WETLabs eng file columns"),
        # Read in Sensors/aa4330_ext.py:1165 but - unlike its sibling
        # remap_wetlabs_eng_cols - has no corresponding netCDF registry entry.
        "remap_optode_eng_cols": (True, "Dictionary for remapping Aanderaa optode eng file columns"),
    }
    for instrument in _WETLABS_INSTRUMENTS:
        for channel in _WETLABS_CHANNELS:
            for suffix, label in _WETLABS_SUFFIXES:
                key = f"{instrument}_{channel}_{suffix}"
                entries[key] = (False, f"WETLabs {instrument} {channel} channel - {label}")
    return entries


_SENSOR_EXTENSION_SUPPLEMENT: dict[str, tuple[bool, str]] = {
    **_SBE43_SUPPLEMENT,
    **_AA3830_SUPPLEMENT,
    **_AA4330_SUPPLEMENT,
    **_VELO_SUPPLEMENT,
    **_LEGATO_SUPPLEMENT,
    **_CODA_SUPPLEMENT,
    **_wetlabs_supplement(),
}

# Instrument calibration-comment keys (calibcomm_<instrument>) are minted
# per-deployment with an arbitrary instrument name by tridente_ext.py and
# coda_ext.py (e.g. calibcomm_tridentebb700bb470chla470); rather than
# enumerating every possible instrument name combination, recognize the shape.
_DYNAMIC_KEY_PATTERNS: tuple[tuple[re.Pattern[str], bool, str], ...] = (
    (
        re.compile(r"^calibcomm_\w+$"),
        True,
        "Per-instrument calibration comment/annotation (serial number, cal date)",
    ),
)


def _describe(meta: dict[str, str]) -> str:
    """Builds a human-readable description from a BaseNetCDF metadata dict.

    Args:
        meta: The metadata dict (third element) from an nc_var_metadata entry.

    Returns:
        A description combining "description" and "units", if present.
    """
    description = meta.get("description", "")
    units = meta.get("units")
    if units:
        return f"{description} ({units})" if description else f"units: {units}"
    return description


def known_calib_vars(
    nc_var_metadata: dict[str, list] | None = None,
) -> dict[str, tuple[bool, str]]:
    """Builds the known sg_calib_constants.m variable registry.

    Combines BaseNetCDF's sg_cal_* metadata entries (populated statically at
    import time, plus any sensor-extension entries already merged in by a
    prior Sensors.init_extensions() call in this process) with a
    hand-maintained supplement covering sensor-extension keys that may not
    yet be registered.

    Args:
        nc_var_metadata: Optional override of BaseNetCDF.nc_var_metadata, for
          testing or a caller-supplied fully-initialized registry. Defaults to
          BaseNetCDF.nc_var_metadata as currently populated in this process.

    Returns:
        Mapping of calib_consts key name (without the "sg_cal_" prefix) to
        (is_string, description).
    """
    registry: dict[str, tuple[bool, str]] = {}
    source = nc_var_metadata if nc_var_metadata is not None else BaseNetCDF.nc_var_metadata
    prefix = BaseNetCDF.nc_sg_cal_prefix
    for nc_name, md in source.items():
        if not nc_name.startswith(prefix):
            continue
        key = nc_name[len(prefix) :]
        _, nc_data_type, meta, _ = md
        registry[key] = (nc_data_type == "c", _describe(meta))

    for key, entry in _SENSOR_EXTENSION_SUPPLEMENT.items():
        registry.setdefault(key, entry)

    return registry


def _lookup(key: str, registry: dict[str, tuple[bool, str]]) -> tuple[bool, bool, str]:
    """Classifies a key against the known-variable registry.

    Args:
        key: The calib_consts key name to look up.
        registry: The registry returned by known_calib_vars.

    Returns:
        A tuple (known, is_string, description).
    """
    if key in registry:
        is_string, description = registry[key]
        return True, is_string, description
    for pattern, is_string, description in _DYNAMIC_KEY_PATTERNS:
        if pattern.match(key):
            return True, is_string, description
    return False, False, ""


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------

_EQ_RE = re.compile(r"^([^=]+)=(.*)")
_COMMENT_RE = re.compile(r"%.*")
_BRACKET_RE = re.compile(r"\[.*")
_OVERRIDE_RE = re.compile(r"override\..*")


def raw_calib_keys(calib_filename: pathlib.Path) -> set[str]:
    """Extracts every assigned variable name from a sg_calib_constants.m file.

    Mirrors the name=value scanning in CalibConst.getSGCalibrationConstants
    (skipping override.* and bracketed [...] assignments), but only collects
    key names rather than coercing values, so unknown keys are not silently
    dropped the way the value parser drops them into best-effort strings.

    Args:
        calib_filename: Path to the sg_calib_constants.m file.

    Returns:
        Set of key names (dots replaced with underscores), matching the keys
        that would appear in the dict returned by getSGCalibrationConstants.

    Raises:
        FileNotFoundError: If calib_filename does not exist.
    """
    keys: set[str] = set()
    with calib_filename.open("r") as calib_file:
        for raw_line in calib_file:
            line = raw_line
            m = _COMMENT_RE.search(line)
            if m:
                line, _ = _COMMENT_RE.split(line)
            for expr in line.split(";"):
                if not _EQ_RE.search(expr):
                    continue
                _, key, value, _ = _EQ_RE.split(expr)
                key = key.strip()
                if _OVERRIDE_RE.search(key):
                    continue
                key = key.replace(".", "_")
                value = value.strip().strip("'\"")
                if _BRACKET_RE.search(value):
                    continue
                keys.add(key)
    return keys


# ---------------------------------------------------------------------------
# Static ranges
# ---------------------------------------------------------------------------

# Values pulled from canonicals/canon_RevE.log where a $PARAM overlaps a
# calib_consts key (mass, Seabird coefficients - note canon_RevE.log's $MASS
# is in grams, divided by 1000 here), and from the literal QC_*/geometry
# defaults in MakeDiveProfiles.sg_config_constants (used as centers with a
# documented margin where the codebase itself has no fixed bound).
STATIC_RANGES: dict[str, tuple[float, float]] = {
    # kg. canon_RevE.log's $MASS,50500,75000 (grams) proved stale against
    # real fleet data: ~351 real sg_calib_constants.m files surveyed span
    # 51.256-87.985 kg after the >100-implies-grams correction (e.g. sg044,
    # sg284 legitimately exceed 75kg), so widened with margin below.
    "mass": (45.0, 95.0),
    # FlightModel-owned keys (see _FLIGHT_MODEL_KEYS handling below): ranges
    # derived from a fleet survey of 257 real sg_calib_constants.m files
    # (parsed with ignore_fm_tags=False), 5th/95th percentile + ~25% padding,
    # cross-checked against FlightModel.get_FM_defaults()'s stock-SG/DeepGlider
    # nominal values. A handful of clear data-entry-error outliers were
    # excluded: hd_a max 0.747 (~200x nominal), hd_c min 8.5e-14 (effectively
    # zero), rho0 min 1.0275 (1000x too small - a kg/m^3 vs kg/L/g/cm^3 unit
    # mixup). hd_s/vbdbias/glider_length had too few real samples (4/2/1) for
    # percentiles - centered on the documented nominal/a domain-reasoned
    # margin instead.
    "volmax": (45000.0, 95000.0),  # cc
    "abs_compress": (1.4e-6, 5.5e-6),  # cc/dbar; SG nominal 4.1e-6, DG 2.1e-6
    "hd_a": (0.0015, 0.0075),  # 1/deg; nominal 0.003548
    "hd_b": (0.002, 0.019),  # Pa^(-1/4); SG nominal 0.011220, DG 0.014125
    "hd_c": (2.2e-6, 1.72e-5),  # 1/rad^2; nominal 5.7e-6
    "hd_s": (-0.35, -0.15),  # nominal -0.25 (Hubbard/Eriksen et al.)
    "rho0": (1020.0, 1032.0),  # kg/m^3; nominal 1027.5
    "vbdbias": (-100.0, 100.0),  # cc; nominal 0
    "therm_expan": (5.5e-5, 8.0e-5),  # cc/degC; SG nominal 7.05e-5, DG 6.214e-5
    "temp_ref": (5.0, 25.0),  # degC; nominal 15.0
    "glider_length": (1.0, 3.0),  # m
    "cpcor": (-2.0e-7, -5.0e-8),  # nominal -9.57e-08
    "ctcor": (1.0e-6, 5.0e-6),  # nominal 3.25e-06
    "QC_temp_min": (-4.0, 0.0),  # default -2.5
    "QC_temp_max": (35.0, 45.0),  # default 43.0
    "QC_cond_min": (0.0, 0.0),
    "QC_cond_max": (5.0, 15.0),  # default 10.0
    "QC_salin_min": (10.0, 25.0),  # default 19.0
    "QC_salin_max": (40.0, 50.0),  # default 45.0
    "GPS_position_error": (10.0, 500.0),  # default 100
    "sbect_tau_T": (0.1, 2.0),  # default 0.6
    "depth_slope_correction": (0.75, 1.25),  # default 1.0; real fleet value observed at 1.20086
    # Boolean flags (0/1). A (0.0, 1.0) bound can't distinguish "0" from "1"
    # as separate meanings, but it does catch garbage/typo'd values.
    "smooth_truck_pressure": (0.0, 1.0),
    "use_auxpressure": (0.0, 1.0),
    "use_auxcompass": (0.0, 1.0),
    "use_adcppressure": (0.0, 1.0),
    "legato_use_truck_pressure": (0.0, 1.0),
    "legato_cond_press_correction": (0.0, 1.0),
    "solve_flare_apogee_speed": (0.0, 1.0),
    "optode_SVU_enabled": (0.0, 1.0),
    # Fallback bounds for the Seabird CT coefficients, used by
    # check_seabird_coefficients only when no capture/log file is available
    # for the precision-aware cross-check. Source: canonicals/canon_RevE.log.
    "t_g": (0.003, 0.006),
    "t_h": (0.0005, 0.0008),
    "t_i": (1e-5, 4e-5),
    "t_j": (1e-6, 5e-6),
    "c_g": (-12.0, -9.0),
    "c_h": (0.5, 1.5),
    "c_i": (-5e-3, -0.5e-3),
    "c_j": (1e-4, 4e-4),
    # --- Fleet-derived entries below ---
    # Empirically derived from ~351 real sg_calib_constants.m files surveyed
    # across ~/work/seagliders and /Volumes/Work/seagliders_community: for
    # each key, take the 5th/95th percentile band (robust to the occasional
    # sentinel/typo value already present in the wild, e.g. a "1e10" used as
    # an effectively-disabled upper bound, or a plain data-entry mistake),
    # exclude raw values far outside that band as outliers, then pad the
    # remaining clean min/max by 25% each side. Keys with fewer than 5
    # samples across the whole fleet were skipped as too little basis for a
    # range. Non-negative quantities (counts, AD counts, frequencies, scale
    # factors) are floored at 0 even if the padding formula would go
    # negative. These coefficients are per-instrument calibration values
    # (Seabird/Aanderaa/WETLabs cal-sheet constants), so the intent is a
    # generous sanity bound that catches gross errors (wrong units, sign
    # flips, decimal-point slips, wrong-sensor-type paste) while tolerating
    # legitimate unit-to-unit calibration variation - not a tight fleet norm.
    "Soc": (9.24e-05, 4.737e-04),
    "Foffset": (-1492.34, -470.06),
    "A": (-0.0022228, -0.0022228),
    "B": (0.00011022, 0.00011022),
    "C": (-2.2231e-06, -2.2231e-06),
    "E": (0.036, 0.036),
    "o_a": (-0.0055241, -0.0001347),
    "o_b": (-1.6561e-05, 2.5903e-04),
    "o_c": (-4.9785e-06, 5.5730e-06),
    "o_e": (0.027, 0.045),
    "Tau20": (0.4975, 2.8125),
    "D1": (0.000192634, 0.000192634),
    "D2": (-0.0464803, -0.0464803),
    "Boc": (-1.0e-4, 1.0e-4),
    "Pcor": (-3.375e-05, 1.6875e-04),
    "Tcor": (0.0017, 0.0017),
    "optode_C00Coef": (2938.57, 6658.12),
    "optode_C01Coef": (-244.161, -83.891),
    "optode_C02Coef": (0.93962, 6.08338),
    "optode_C03Coef": (-0.062936, -0.001440),
    "optode_C10Coef": (-365.085, -156.713),
    "optode_C11Coef": (3.06577, 13.3833),
    "optode_C12Coef": (-0.360654, 0.003595),
    "optode_C13Coef": (-6.024e-04, 0.0039552),
    "optode_C20Coef": (3.44503, 8.09494),
    "optode_C21Coef": (-0.298976, -0.036413),
    "optode_C22Coef": (-0.0012161, 0.0086913),
    "optode_C23Coef": (-1.0173e-04, 2.9597e-05),
    "optode_C30Coef": (-0.083661, -0.035901),
    "optode_C31Coef": (9.1307e-05, 0.0031208),
    "optode_C32Coef": (-9.7879e-05, 2.355e-05),
    "optode_C33Coef": (-4.6303e-07, 1.1984e-06),
    "optode_C40Coef": (1.4454e-04, 3.3188e-04),
    "optode_C41Coef": (-1.2465e-05, 6.5215e-07),
    "optode_C42Coef": (-1.3596e-07, 4.2260e-07),
    "optode_C43Coef": (-5.2829e-09, 2.3900e-09),
    "optode_TempCoef0": (14.7816, 32.7553),
    "optode_TempCoef1": (-0.045281, -0.021770),
    "optode_TempCoef2": (2.0470e-06, 3.8093e-06),
    "optode_TempCoef3": (-5.5065e-09, -3.0837e-09),
    "optode_TempCoef4": (-1.0e-4, 1.0e-4),
    "optode_TempCoef5": (-1.0e-4, 1.0e-4),
    "optode_PhaseCoef0": (-11.711, 3.0574),
    "optode_PhaseCoef1": (0.68892, 1.55541),
    "optode_PhaseCoef2": (-1.0e-4, 1.0e-4),
    "optode_PhaseCoef3": (-1.0e-4, 1.0e-4),
    "optode_ConcCoef0": (-10.3347, 4.51172),
    "optode_ConcCoef1": (0.66954, 1.48235),
    "optode_FoilCoefA0": (-5.5368e-06, -1.5719e-06),
    "optode_FoilCoefA1": (-1.2418e-05, -3.6543e-06),
    "optode_FoilCoefA2": (1.0498e-03, 3.1741e-03),
    "optode_FoilCoefA3": (-0.327985, -0.120120),
    "optode_FoilCoefA4": (3.6361e-04, 1.1870e-03),
    "optode_FoilCoefA5": (-1.7315e-06, 4.8011e-08),
    "optode_FoilCoefA6": (6.9403, 17.3064),
    "optode_FoilCoefA7": (-0.097751, -0.031930),
    "optode_FoilCoefA8": (-1.2768e-06, 3.5131e-04),
    "optode_FoilCoefA9": (-1.8728e-06, 1.3910e-06),
    "optode_FoilCoefA10": (-476.904, -201.747),
    "optode_FoilCoefA11": (1.30782, 3.71089),
    "optode_FoilCoefA12": (-0.027775, 0.002568),
    "optode_FoilCoefA13": (-4.8488e-04, 3.5454e-04),
    "optode_FoilCoefB0": (-3.6267e-06, 6.9654e-06),
    "optode_FoilCoefB1": (2488.11, 5684.13),
    "optode_FoilCoefB2": (-61.6893, -19.8622),
    "optode_FoilCoefB3": (-0.400477, 0.840321),
    "optode_FoilCoefB4": (-0.019146, 0.030601),
    "optode_FoilCoefB5": (-8.9315e-04, 3.2491e-04),
    "optode_FoilCoefB6": (-3.5249e-06, 1.3217e-05),
    "optode_FoilCoefB7": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB8": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB9": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB10": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB11": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB12": (-1.0e-4, 1.0e-4),
    "optode_FoilCoefB13": (-1.0e-4, 1.0e-4),
    "optode_SVUCoef0": (-8.9426e-04, 4.4713e-03),
    "optode_SVUCoef1": (-3.7794e-05, 1.8897e-04),
    "optode_SVUCoef2": (-8.0571e-07, 4.0285e-06),
    "optode_SVUCoef3": (-58.4693, 292.346),
    "optode_SVUCoef4": (-0.385344, 0.077069),
    "optode_SVUCoef5": (-72.1026, 14.4205),
    "optode_SVUCoef6": (-1.18467, 5.92337),
    "optode_st_temp": (3.6853, 18.9237),
    "optode_st_calphase": (22.749, 41.15),
    "optode_st_slp": (745.73, 1291.38),
    "sbe_cond_freq_C0": (2156.89, 3787.84),
    "sbe_cond_freq_min": (1.73813, 3.80934),
    "sbe_cond_freq_max": (5.59755, 10.625),
    "sbe_temp_freq_min": (0.0, 4.43854),
    "sbe_temp_freq_max": (3.06452, 12.5),
    "legato_sealevel": (7239.25, 12848.8),
    "pitch_min_cnts": (0.0, 532.5),
    "pitch_max_cnts": (2636.5, 5087.5),
    "roll_min_cnts": (35.0, 550.0),
    "roll_max_cnts": (2187.5, 5062.5),
    "vbd_min_cnts": (30.0, 750.0),
    "vbd_max_cnts": (2543.0, 4975.0),
    "vbd_cnts_per_cc": (-5.09589, -3.05752),
    "pump_rate_intercept": (0.95625, 1.59375),
    "pump_rate_slope": (-1.875e-04, -1.125e-04),
    "pump_power_intercept": (13.0525, 21.7541),
    "pump_power_slope": (0.013368, 0.02228),
    "wlbb2fl_sig470nm_dark_counts": (16.0, 85.0),
    "wlbb2fl_sig470nm_scale_factor": (5.075e-06, 2.6125e-05),
    "wlbb2fl_sig470nm_resolution_counts": (0.6, 2.0),
    "wlbb2fl_sig470nm_max_counts": (0.0, 12498.8),
    "wlbb2fl_sig695nm_dark_counts": (17.25, 83.75),
    "wlbb2fl_sig695nm_scale_factor": (0.0055, 0.0235),
    "wlbb2fl_sig695nm_resolution_counts": (0.4, 3.0),
    "wlbb2fl_sig695nm_max_counts": (3073.0, 5225.0),
    "wlbb2fl_sig700nm_dark_counts": (19.75, 71.25),
    "wlbb2fl_sig700nm_scale_factor": (4.785e-07, 8.0175e-06),
    "wlbb2fl_sig700nm_resolution_counts": (0.475, 2.625),
    "wlbb2fl_sig700nm_max_counts": (0.0, 12498.8),
    "wlbb2fl_sig460nm_dark_counts": (30.5, 62.5),
    "wlbb2fl_sig460nm_scale_factor": (0.062875, 0.124625),
    "wlbb2fl_sig460nm_resolution_counts": (0.65, 1.75),
    "wlbb2fl_sig460nm_max_counts": (3087.5, 5162.5),
    "wlbbfl2_sig695nm_dark_counts": (24.0, 65.0),
    "wlbbfl2_sig695nm_scale_factor": (0.0, 0.0385),
    "wlbbfl2_sig695nm_resolution_counts": (0.575, 2.125),
    "wlbbfl2_sig695nm_max_counts": (3087.5, 5162.5),
    "wlbbfl2_sig700nm_dark_counts": (24.25, 63.75),
    "wlbbfl2_sig700nm_scale_factor": (0.0, 0.0075),
    "wlbbfl2_sig700nm_resolution_counts": (0.5, 2.5),
    "wlbbfl2_sig700nm_max_counts": (0.0, 12498.8),
    "wlbbfl2_sig460nm_dark_counts": (14.25, 68.75),
    "wlbbfl2_sig460nm_scale_factor": (0.04058, 0.136),
    "wlbbfl2_sig460nm_resolution_counts": (0.4, 3.0),
    "wlbbfl2_sig460nm_max_counts": (3087.5, 5162.5),
    # Enum/config-select integers: bounds are the codebase's documented
    # legal value space (MakeDiveProfiles.sg_config_constants, Sensors/
    # legato_logdev_ext.py's channel bitfield doc, FlightModel's mode
    # comment), NOT fleet-empirical - this particular fleet sample happens
    # to only exercise a few of each key's valid values (e.g. every surveyed
    # file uses sg_ct_type=4), so empirical min/max would incorrectly reject
    # other legitimate configurations.
    "sg_ct_type": (0.0, 4.0),  # 0=orig CT,1=gun CT,2=pumped GPCTD,3=SAILCT,4=Legato
    "sg_configuration": (0.0, 4.0),  # 0=SG,1=SG gun,2=DG,3=SG+GPCTD,4=Oculus
    "legato_config": (0.0, 255.0),  # 8-bit channel-enable bitfield
    "sbect_modes": (0.0, 5.0),  # 0=disabled, else 1/3/5 thermal-inertia modes
    # Bias/correction knobs: the fleet sample is ~always 0 (rarely adjusted),
    # but the field exists precisely to allow occasional deliberate nonzero
    # correction, so use a domain-reasoned margin around zero rather than
    # the fleet's near-zero empirical range (which would defeat the field's
    # own purpose).
    "depth_bias": (-5.0, 5.0),  # meters
    "cond_bias": (-0.05, 0.05),  # S/m
    "temp_bias": (-0.5, 0.5),  # deg C
    "pitchbias": (-5.0, 5.0),  # degrees
    "mass_comp": (0.0, 20.0),  # kg
}


def _static_range_finding(key: str, value: float, description: str) -> Finding:
    """Checks value against STATIC_RANGES, if a range is defined for key.

    Args:
        key: The calib_consts key being checked.
        value: The numeric value found in sg_calib_constants.m.
        description: Registry description, used as "expected" when no static
          range is defined.

    Returns:
        A Finding with status "ok"/"warn" if a range is defined for key,
        otherwise "not_checked".
    """
    bounds = STATIC_RANGES.get(key)
    if bounds is None:
        return Finding(
            key=key,
            known=True,
            status="not_checked",
            value=value,
            expected=description,
            message="no static range defined for this key",
        )
    lo, hi = bounds
    if lo <= value <= hi:
        return Finding(
            key=key, known=True, status="ok", value=value, expected=f"[{lo}, {hi}]", message=""
        )
    return Finding(
        key=key,
        known=True,
        status="warn",
        value=value,
        expected=f"[{lo}, {hi}]",
        message=f"{key}={value} outside expected range [{lo}, {hi}]",
    )


# ---------------------------------------------------------------------------
# CTD-type detection
# ---------------------------------------------------------------------------

# Fleet-validated evidence sources (checked against ~260 real mission
# directories' selftest captures, cross-referenced against each mission's
# actual sg_cal_sg_ct_type/legato_time/gpctd_time netCDF ground truth):
#
#   signal                                    precision  recall
#   "checking ct legatoPoll*"                   1.00      0.62
#   "HLEGATO,N,pressure:" present                1.00      0.84
#   combined (legato_present, below)             1.00      0.91
#   "checking ct sbect"                          1.00      0.16
#   "Logger sensor in logger slot N is RBR"      1.00      n/a (see below)
#
# Earlier candidate signals were tried and dropped after this survey showed
# them unreliable: a bare case-insensitive "CondFreq"/"sbect" substring
# search (selftest.sh:225-228) false-positives on vehicles with no SBE at
# all (the mainboard's ">prop" device-driver dump always lists a
# "sbect = { ... }" capability block regardless of what's plugged in); the
# ".cnf files on disk:" listing's "legato.cnf"/"gpctd.cnf" entries can be
# stale residue from a prior hardware configuration (confirmed: a real
# vehicle's capture showed a legato.cnf dated 4 years before its current,
# genuinely-SBE mission) - "gpctd.cnf" in particular was only 10% precise
# (36 false positives vs. 4 true positives) and isn't usable at all; and the
# eng-file "columns:" header naming a sbect.* column, while much better
# (0.96-0.98 precision), still produced a real false alarm on a vehicle with
# legacy column names left over from a prior hardware generation. The
# similarly-shaped "columns:...rbr\." signal for truck-wired RBR was also
# tried and rejected (0.333 precision - some SciCon-mounted vehicles'
# eng schema declares unused rbr.* placeholder columns regardless of real
# wiring). The signals kept here are the only ones with zero false
# positives fleet-wide.
#
# The Legato-as-logdev signal ("Logger sensor in logger slot N is RBR") is
# a different case: it's the live hardware-enumeration mechanism the
# supervisor already uses fleet-wide for other device types in the same
# slot (SciCon, GPCTD, TMICL, PMAR, etc. - never RBR for any of them), so
# it's the same *class* of signal as the two kept above, not a repeat of
# the rejected column-declaration approach. But RBR-as-logdev has exactly
# one known real-world instance in the entire fleet (hull 677), so recall
# isn't meaningfully measurable the way it is for richer-population
# signals like legatoPoll (~40 real missions) - "precision 1.00" here means
# zero false positives across every other hull's captures fleet-wide
# (~290 real mission directories), not a statistically broad sample.
_CT_CHECKING_RE = re.compile(r"checking ct (\w+)")
# Also extracts the numeric glider-reported sealevel pressure reading for
# check_legato_sealevel below.
_HLEGATO_PRESSURE_RE = re.compile(r"HLEGATO,N,pressure:(?P<value>[0-9.]+)")
# Tolerates a real casing quirk: empty slots log "Logger Sensor ... is not
# installed" (capital S), populated slots log "Logger sensor ... is
# <DEVICE>" (lowercase s). Matches only on "RBR" as a whole word, not the
# device-specific trailing text after it (which varies in shape - e.g.
# "on USART2 (pwr F6) ()" vs. a GPCTD's "on port 3, TPU06/TPU07, ...").
_LOGGER_SLOT_RBR_RE = re.compile(r"Logger [Ss]ensor in logger slot \d+ is RBR\b")


class CTDEvidence(TypedDict):
    """Hardware-presence evidence scraped from a selftest capture file.

    Attributes:
        sbe_present: Whether the capture shows a Seabird-family CT (unpumped,
          gun-mount, GPCTD, or SAILCT) is installed.
        legato_present: Whether the capture shows an RBR Legato is installed.
        legato_via_scicon: Whether the "checking ct legatoPoll*" live SciCon
          self-test line itself matched (a subset of legato_present - the
          weaker standalone HLEGATO signal alone doesn't set this). True only
          when the mount is structurally provable to be SciCon (see
          detect_ctd_type).
        legato_via_logdev: Whether the "Logger sensor in logger slot N is
          RBR" live hardware-enumeration line matched (a subset of
          legato_present) - True only when the mount is structurally
          provable to be a dedicated RBR logger board (logdev), as opposed
          to SciCon-attached (see detect_ctd_type).
        legato_reported_sealevel: The glider-reported Legato sealevel
          pressure reading, if a HLEGATO,N,pressure: line was found in the
          capture; None otherwise.
    """

    sbe_present: bool
    legato_present: bool
    legato_via_scicon: bool
    legato_via_logdev: bool
    legato_reported_sealevel: float | None


def _scan_capture_for_ctd_evidence(capture_file: pathlib.Path | None) -> CTDEvidence:
    """Scans a selftest capture (or per-dive log) file for installed-CTD evidence.

    Only reports evidence from the fleet-validated, zero-false-positive
    signals (see module comment above) - when none are present in the
    capture (the common case; the live scicon self-test, a Legato pressure
    reading, and the logger-slot enumeration line aren't always logged),
    all fields are False rather than falling back to a less reliable guess.

    Args:
        capture_file: Path to a selftest .cap (or per-dive .log) file, or None.

    Returns:
        A CTDEvidence with every field False/None if capture_file is None,
        doesn't exist, or no evidence was found.
    """
    if capture_file is None or not capture_file.exists():
        return CTDEvidence(
            sbe_present=False,
            legato_present=False,
            legato_via_scicon=False,
            legato_via_logdev=False,
            legato_reported_sealevel=None,
        )

    text = capture_file.read_text(errors="ignore")
    checking_ct_match = _CT_CHECKING_RE.search(text)
    device = checking_ct_match.group(1) if checking_ct_match else None
    legato_via_scicon = device is not None and device.startswith("legatoPoll")
    legato_via_logdev = _LOGGER_SLOT_RBR_RE.search(text) is not None
    legato_match = _HLEGATO_PRESSURE_RE.search(text)

    return CTDEvidence(
        sbe_present=device == "sbect",
        legato_present=legato_via_scicon or legato_via_logdev or legato_match is not None,
        legato_via_scicon=legato_via_scicon,
        legato_via_logdev=legato_via_logdev,
        legato_reported_sealevel=float(legato_match.group("value")) if legato_match else None,
    )


def _suppressed_checker_groups(evidence: CTDEvidence) -> dict[tuple[str, ...], str]:
    """Determines which SPECIALIZED_CHECKERS groups don't apply to this vehicle.

    Args:
        evidence: Capture-file hardware-presence evidence.

    Returns:
        Mapping of group -> human-readable reason, for groups whose real
        checker should be skipped in favor of a "not_checked" Finding per
        present key (e.g. Seabird coefficients on a Legato-only vehicle).
        Both evidence fields come from zero-false-positive signals (see
        _scan_capture_for_ctd_evidence), so simple presence/absence is
        sufficient - no ambiguous-both-present case has been observed
        fleet-wide. When neither is present, nothing is suppressed - the
        real checkers run and fall back to STATIC_RANGES.
    """
    suppressed: dict[tuple[str, ...], str] = {}
    if evidence["legato_present"] and not evidence["sbe_present"]:
        suppressed[_SEABIRD_GROUP] = "vehicle uses RBR Legato, not a Seabird CT"
    if evidence["sbe_present"] and not evidence["legato_present"]:
        suppressed[_LEGATO_SEALEVEL_GROUP] = "vehicle uses a Seabird CT, not RBR Legato"
    return suppressed


def detect_ctd_type(
    calib_consts: dict[str, str | float | int],
    evidence: CTDEvidence,
) -> Finding:
    """Cross-checks sg_ct_type against capture-file hardware evidence.

    Args:
        calib_consts: Parsed sg_calib_constants.m dict.
        evidence: Capture-file hardware-presence evidence, from
          _scan_capture_for_ctd_evidence.

    Returns:
        A "detected_ctd_type" Finding: "crit" if the capture evidence
        contradicts sg_ct_type - including sg_ct_type being unset, since
        both evidence signals are fleet-validated at 100% precision (see
        module comment), so "unset" no longer deserves the benefit of the
        doubt once evidence positively identifies the installed CT - "ok"
        otherwise (including when there isn't enough evidence to tell).
        value/expected carry a human-readable description of the detected
        CTD (from MakeDiveProfiles.sb_ct_type_map), plus a mount qualifier -
        "configured as logdev, confirmed by capture" when the logger-slot
        enumeration line structurally proves a dedicated RBR logger board,
        "SciCon-attached, confirmed by capture" when structurally provable
        via the other signal, "legato_config set - configured for logdev
        use" when legato_config is set but there's no capture confirmation
        either way, or "mount not confirmed by capture" otherwise (never
        "truck": no fixture proves a pure-truck-mounted case exists). GPCTD
        (sg_ct_type == 2) is only ever reported from that self-reported
        value - no capture-text signal for it survived fleet validation
        (see module comment).
    """
    sg_ct_type = calib_consts.get("sg_ct_type")
    sg_ct_type_int = int(sg_ct_type) if isinstance(sg_ct_type, (int, float)) else None

    status = "ok"
    message = ""
    if evidence["legato_present"] and not evidence["sbe_present"] and sg_ct_type_int != 4:
        status = "crit"
        message = (
            "capture confirms RBR Legato is attached but sg_ct_type is not set to 4 "
            f"(currently {sg_ct_type_int}); set sg_ct_type=4 in sg_calib_constants.m"
        )
    elif evidence["sbe_present"] and not evidence["legato_present"] and sg_ct_type_int == 4:
        status = "crit"
        message = (
            "capture confirms a Seabird CT is attached but sg_ct_type=4 (Legato); "
            "set sg_ct_type appropriately, or remove the line to use the default"
        )

    if sg_ct_type_int == 4:
        detected = MakeDiveProfiles.sb_ct_type_map[4]
    elif sg_ct_type_int in MakeDiveProfiles.sb_ct_type_map:
        detected = MakeDiveProfiles.sb_ct_type_map[sg_ct_type_int]
    elif evidence["legato_present"]:
        detected = MakeDiveProfiles.sb_ct_type_map[4]
    elif evidence["sbe_present"]:
        detected = "Seabird CT (unpumped/gun/SAILCT/GPCTD variant not verifiable from capture)"
    else:
        detected = "unknown (no sg_ct_type set and no capture evidence available)"

    # Mount: "checking ct <name>" is structurally downstream of "attach
    # scicon.att" (confirmed against real captures), so whenever it matched
    # (legato_via_scicon, or sbe_present - which has no other evidence
    # source), the mount is definitively SciCon. "Logger sensor in logger
    # slot N is RBR" is likewise structural proof of a dedicated RBR logger
    # board (logdev) - checked first since capture evidence outranks the
    # self-reported legato_config fallback below. No fixture anywhere proves
    # a pure-truck-mounted case, so "truck" is never asserted.
    if detected.startswith("unknown"):
        mount_note = ""
    elif evidence["legato_via_logdev"]:
        mount_note = " (configured as logdev, confirmed by capture)"
    elif "legato_config" in calib_consts and (sg_ct_type_int == 4 or evidence["legato_present"]):
        mount_note = " (legato_config set - configured for logdev use)"
    elif evidence["legato_via_scicon"] or evidence["sbe_present"]:
        mount_note = " (SciCon-attached, confirmed by capture)"
    else:
        mount_note = " (mount not confirmed by capture)"
    detected += mount_note

    return Finding(
        key="detected_ctd_type",
        known=True,
        status=status,
        value=sg_ct_type_int,
        expected=detected,
        message=message,
    )


# ---------------------------------------------------------------------------
# Specialized checkers
# ---------------------------------------------------------------------------

_MASS_GROUP = ("mass",)
_SEABIRD_GROUP = ("t_g", "t_h", "t_i", "t_j", "c_g", "c_h", "c_i", "c_j")
_LEGATO_SEALEVEL_GROUP = ("legato_sealevel",)

_SEABIRD_LOG_VARS: dict[str, str] = {
    "t_g": "SEABIRD_T_G",
    "t_h": "SEABIRD_T_H",
    "t_i": "SEABIRD_T_I",
    "t_j": "SEABIRD_T_J",
    "c_g": "SEABIRD_C_G",
    "c_h": "SEABIRD_C_H",
    "c_i": "SEABIRD_C_I",
    "c_j": "SEABIRD_C_J",
}

# $SEABIRD_* values are the glider's single-precision (TT8) telemetered
# readback of what was originally written from the double-precision
# sg_calib_constants.m value, so an exact match is never expected - only a
# match to within single-precision rounding. Reuses the exact constant and
# ratio-based comparison already used for this purpose in
# MakeDiveProfiles.py:2610 (SBECT_coefficents) and FlightModel.py:3148.
SEABIRD_ACCEPTABLE_PRECISION = 0.8e-7  # TT8 has single-precision floats

_G_PER_KG = 1000.0  # matches MakeDiveProfiles.kg2g


def check_seabird_coefficents(
    calib_consts: dict[str, str | float | int],
    capture_file: pathlib.Path | None,
) -> list[Finding]:
    """Cross-checks Seabird CT coefficients against $SEABIRD_* readings.

    Compares t_g/t_h/t_i/t_j/c_g/c_h/c_i/c_j from sg_calib_constants.m
    against the corresponding $SEABIRD_* value reported in a selftest
    capture (or per-dive log) file, accounting for the single-precision
    (TT8) vs. double-precision representation of the two sources via
    SEABIRD_ACCEPTABLE_PRECISION. Falls back to STATIC_RANGES when no
    capture data is available for a coefficient.

    Args:
        calib_consts: Parsed sg_calib_constants.m dict.
        capture_file: Path to a selftest .cap (or fallback .log) file, or
          None if unavailable.

    Returns:
        One Finding per Seabird coefficient present in calib_consts.
    """
    capture_values = compare.parse_param_file(capture_file) if capture_file else None

    findings: list[Finding] = []
    for key in _SEABIRD_GROUP:
        if key not in calib_consts or not isinstance(calib_consts[key], (int, float)):
            continue
        sgc_value = float(calib_consts[key])
        log_var = _SEABIRD_LOG_VARS[key]
        log_value = capture_values.get(log_var) if capture_values else None

        if log_value is None:
            findings.append(_static_range_finding(key, sgc_value, f"matches ${log_var}"))
            continue

        if np.isclose([sgc_value], [0.0], atol=SEABIRD_ACCEPTABLE_PRECISION):
            findings.append(
                Finding(
                    key=key,
                    known=True,
                    status="warn",
                    value=sgc_value,
                    expected=f"nonzero, matches ${log_var}={log_value:g}",
                    message=f"{key} is zero in sg_calib_constants.m",
                )
            )
            continue

        matches = bool(
            np.isclose([log_value / sgc_value], [1.0], atol=SEABIRD_ACCEPTABLE_PRECISION)[0]
        )
        status = "ok" if matches else "warn"
        message = (
            ""
            if matches
            else (
                f"{key}={sgc_value:g} in sg_calib_constants.m differs from "
                f"${log_var}={log_value:g} in {capture_file.name if capture_file else '?'} "
                "by more than single-precision rounding"
            )
        )
        if status == "warn":
            log_warning(message, alert="SBECT_COEFFICIENT")
        findings.append(
            Finding(
                key=key,
                known=True,
                status=status,
                value=sgc_value,
                expected=f"${log_var}={log_value:g}",
                message=message,
            )
        )

    return findings


def check_mass_against_capture(
    calib_consts: dict[str, str | float | int],
    capture_file: pathlib.Path | None,
) -> list[Finding]:
    """Cross-checks mass (kg) against $MASS (g) in a capture/log file.

    Replicates the >100-implies-grams auto-correction and the absolute 1g
    tolerance from MakeDiveProfiles.py:5674-5692. Falls back to
    STATIC_RANGES when no capture data is available.

    Args:
        calib_consts: Parsed sg_calib_constants.m dict.
        capture_file: Path to a selftest .cap (or fallback .log) file, or
          None if unavailable.

    Returns:
        A single-element list with the mass Finding, or an empty list if
        mass is absent/non-numeric (handled as a missing-required-key
        Finding elsewhere).
    """
    if "mass" not in calib_consts or not isinstance(calib_consts["mass"], (int, float)):
        return []

    mass_kg = float(calib_consts["mass"])
    if mass_kg > 100:
        # Same auto-correction as MakeDiveProfiles.py:5678-5683: values > 100
        # are assumed to have been mistakenly entered in grams.
        mass_kg = mass_kg / _G_PER_KG
    mass_g = mass_kg * _G_PER_KG

    capture_values = compare.parse_param_file(capture_file) if capture_file else None
    log_mass_g = capture_values.get("MASS") if capture_values else None

    if log_mass_g is None:
        return [_static_range_finding("mass", mass_kg, "matches $MASS in a capture/log file")]

    if abs(mass_g - log_mass_g) > 1:  # [g], matches MakeDiveProfiles.py:5685
        message = (
            f"mass={mass_g:.1f}g (from sg_calib_constants.m) does not match "
            f"$MASS={log_mass_g:.1f}g in {capture_file.name if capture_file else '?'}"
        )
        log_warning(message, alert="MASS_MISMATCH")
        status = "warn"
    else:
        message = ""
        status = "ok"

    return [
        Finding(
            key="mass",
            known=True,
            status=status,
            value=calib_consts["mass"],
            expected=f"$MASS={log_mass_g:.1f}g",
            message=message,
        )
    ]


LEGATO_SEALEVEL_TOLERANCE = 1.0  # legato_sealevel is a whole sensor count in every real example seen


def check_legato_sealevel(
    calib_consts: dict[str, str | float | int],
    capture_file: pathlib.Path | None,
) -> list[Finding]:
    """Cross-checks legato_sealevel against the glider-reported HLEGATO pressure.

    Compares legato_sealevel from sg_calib_constants.m against the
    HLEGATO,N,pressure: reading in a selftest capture (or per-dive log) file
    (ports selftest.sh:234-243, but only flags a real mismatch instead of
    always suggesting an "update"). Falls back to STATIC_RANGES when no
    capture data is available.

    Args:
        calib_consts: Parsed sg_calib_constants.m dict.
        capture_file: Path to a selftest .cap (or fallback .log) file, or
          None if unavailable.

    Returns:
        A single-element list with the legato_sealevel Finding, or an empty
        list if legato_sealevel is absent/non-numeric.
    """
    if "legato_sealevel" not in calib_consts or not isinstance(
        calib_consts["legato_sealevel"], (int, float)
    ):
        return []

    sgc_value = float(calib_consts["legato_sealevel"])
    reported = _scan_capture_for_ctd_evidence(capture_file)["legato_reported_sealevel"]

    if reported is None:
        return [
            _static_range_finding(
                "legato_sealevel",
                sgc_value,
                "matches the glider's HLEGATO,N,pressure: reading",
            )
        ]

    if abs(sgc_value - reported) > LEGATO_SEALEVEL_TOLERANCE:
        message = (
            f"legato_sealevel={sgc_value:g} in sg_calib_constants.m differs from the "
            f"glider-reported pressure={reported:g} in "
            f"{capture_file.name if capture_file else '?'}; update to {reported:g}"
        )
        log_warning(message, alert="LEGATO_SEALEVEL")
        status = "warn"
    else:
        message = ""
        status = "ok"

    return [
        Finding(
            key="legato_sealevel",
            known=True,
            status=status,
            value=sgc_value,
            expected=f"glider-reported pressure={reported:g}",
            message=message,
        )
    ]


SPECIALIZED_CHECKERS: dict[tuple[str, ...], CheckerFn] = {
    _MASS_GROUP: check_mass_against_capture,
    _SEABIRD_GROUP: check_seabird_coefficents,
    _LEGATO_SEALEVEL_GROUP: check_legato_sealevel,
}


def _find_checker_group(key: str) -> tuple[str, ...] | None:
    """Finds the SPECIALIZED_CHECKERS group key belongs to, if any.

    Args:
        key: The calib_consts key to look up.

    Returns:
        The matching group tuple, or None if key isn't covered by a
        specialized checker.
    """
    for group in SPECIALIZED_CHECKERS:
        if key in group:
            return group
    return None


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def check_calib_constants(
    calib_filename: pathlib.Path,
    capture_file: pathlib.Path | None = None,
    nc_var_metadata: dict[str, list] | None = None,
) -> list[Finding]:
    """Validates a sg_calib_constants.m file against the known-variable registry.

    Args:
        calib_filename: Path to sg_calib_constants.m.
        capture_file: Optional selftest .cap (or per-dive .log) file for
          specialized cross-checks (mass, Seabird CT coefficients,
          legato_sealevel) and CTD-type detection.
        nc_var_metadata: Optional pre-built registry override; see
          known_calib_vars.

    Returns:
        A leading "detected_ctd_type" Finding (see detect_ctd_type); a
        standalone "crit" legato_sealevel Finding if capture_file confirms
        RBR Legato is attached but the key is absent from the file; one
        Finding per key found in the file (known/unknown, in/out of range,
        or "not_checked" when a Seabird/Legato-specific key doesn't apply to
        the CTD type detected from capture_file - the sg_ct_type key's own
        Finding additionally carries its human-readable CT type name in
        message); plus one Finding per required key missing from the file.
        FlightModel-v3-owned keys (hd_a, volmax, etc.) are range-checked like
        any other numeric key but always come back "warn" with an explanatory
        message, since the file's value is silently overridden at runtime
        regardless of whether it looks reasonable.

    Raises:
        FileNotFoundError: If calib_filename does not exist.
    """
    if not calib_filename.exists():
        raise FileNotFoundError(calib_filename)

    # ignore_fm_tags=False so FlightModel-owned keys (hd_a, volmax, etc.) get
    # their real values parsed instead of discarded - the checker wants to
    # range-check and display them (see the FlightModel-key handling below),
    # unlike the real dive-processing pipeline which still ignores them.
    calib_consts = CalibConst.getSGCalibrationConstants(
        calib_filename, suppress_required_error=True, ignore_fm_tags=False
    )
    present_keys = raw_calib_keys(calib_filename)
    registry = known_calib_vars(nc_var_metadata)
    evidence = _scan_capture_for_ctd_evidence(capture_file)
    suppressed_groups = _suppressed_checker_groups(evidence)

    findings: list[Finding] = [detect_ctd_type(calib_consts, evidence)]
    if evidence["legato_present"] and "legato_sealevel" not in present_keys:
        findings.append(
            Finding(
                key="legato_sealevel",
                known=True,
                status="crit",
                value=None,
                expected="required when Legato is installed",
                message=(
                    "capture confirms RBR Legato is attached but legato_sealevel is "
                    "not set in sg_calib_constants.m"
                ),
            )
        )
    checked_groups: set[tuple[str, ...]] = set()

    for key in sorted(present_keys | set(REQUIRED_KEYS)):
        if key in REQUIRED_KEYS and key not in present_keys:
            findings.append(
                Finding(
                    key=key,
                    known=True,
                    status="crit",
                    value=None,
                    expected="required",
                    message=f"{key} is required but missing from {calib_filename.name}",
                )
            )
            continue

        checker_group = _find_checker_group(key)
        if checker_group is not None:
            if checker_group in checked_groups:
                continue
            checked_groups.add(checker_group)
            reason = suppressed_groups.get(checker_group)
            if reason is not None:
                for gkey in checker_group:
                    if gkey not in present_keys:
                        continue
                    findings.append(
                        Finding(
                            key=gkey,
                            known=True,
                            status="not_checked",
                            value=calib_consts.get(gkey),
                            expected="not applicable",
                            message=f"{gkey} is not checked - {reason}",
                        )
                    )
                continue
            findings.extend(SPECIALIZED_CHECKERS[checker_group](calib_consts, capture_file))
            continue

        is_known, is_string, description = _lookup(key, registry)
        value = calib_consts.get(key)
        is_flight_model_key = key in _FLIGHT_MODEL_KEYS
        flight_model_message = (
            f"{key} is normally computed by FlightModel v3; the value in "
            "sg_calib_constants.m is ignored unless '% FM_ignore' is present "
            "on that line, or --skip_flight_model is used."
        )

        if not is_known or is_string or not isinstance(value, (int, float)):
            if is_flight_model_key:
                # vbdbias_drift (the only unregistered flight_variable) or a
                # non-numeric value - no meaningful range to check, so keep
                # the fixed explanatory Finding as before.
                findings.append(
                    Finding(
                        key=key,
                        known=True,
                        status="not_checked",
                        value=value,
                        expected="supplied by FlightModel v3 at runtime",
                        message=flight_model_message,
                    )
                )
            elif not is_known:
                findings.append(
                    Finding(
                        key=key,
                        known=False,
                        status="unknown",
                        value=value,
                        expected="",
                        message=f"{key} is not a recognized sg_calib_constants.m variable",
                    )
                )
            else:
                findings.append(
                    Finding(
                        key=key, known=True, status="ok", value=value, expected=description, message=""
                    )
                )
            continue

        range_finding = _static_range_finding(key, float(value), description)
        if key == "sg_ct_type":
            ct_name = MakeDiveProfiles.sb_ct_type_map.get(int(value), f"unknown (type {int(value)})")
            range_finding["message"] = (
                f"{range_finding['message']}; {ct_name}" if range_finding["message"] else ct_name
            )
        if is_flight_model_key:
            # Run the normal range check (so value/expected show the real
            # number and range) but the point isn't "is this a good
            # FlightModel guess" - it's "this will be silently overridden" -
            # so always warn, regardless of whether it's in range.
            range_finding["status"] = "warn"
            range_finding["message"] = flight_model_message
        findings.append(range_finding)

    _apply_advisories(findings)
    return findings


def render_findings_table(
    findings: list[Finding], pcolors: dict[str, str], rcolors: list[str]
) -> None:
    """Prints an HTML table of findings, matching compare.renderTable's style.

    The toggle button and full table are always present, so a pilot can still
    expand and audit everything that was parsed/checked. If every finding
    (including the "Detected CTD" banner) is "ok", a "No issues detected."
    summary line is printed above the table - as its own line, not baked into
    the table header, since the header would otherwise be stuck reading "No
    issues detected." even after "Show all" reveals the real per-key rows
    beneath it. In that all-"ok" case the header row is also tagged as a
    hidden-by-default "ok row" (there being no other row to keep the table
    visibly non-empty), so the table itself stays fully collapsed until
    "Show all" reveals both the header and every row together.

    Args:
        findings: The list returned by check_calib_constants.
        pcolors: Status-to-background-color mapping (e.g. {"crit": "red",
          "warn": "yellow", "sers": "orange"}), as used by SelftestHTML.py.
        rcolors: Alternating row background colors.
    """
    any_non_ok = any(f["status"] != "ok" for f in findings)

    detected = next((f for f in findings if f["key"] == "detected_ctd_type"), None)
    if detected is not None:
        findings = [f for f in findings if f["key"] != "detected_ctd_type"]
        color = pcolors.get(detected["status"])
        style = f"background-color:{color};" if color else ""
        suffix = f" - {detected['message']}" if detected["message"] else ""
        print(f'<p style="{style}"><b>Detected CTD:</b> {detected["expected"]}{suffix}</p>')

    if not any_non_ok:
        print("<p>No issues detected.</p>")

    print(
        "<script>function toggleCalibOkRows(btn) {"
        "var showing = btn.value === 'Hide [ok]';"
        "var rows = document.getElementsByClassName('calib-ok-row');"
        "for (var i = 0; i < rows.length; i++) {"
        "rows[i].style.display = showing ? 'none' : '';"
        "}"
        "btn.value = showing ? 'Show all' : 'Hide [ok]';"
        "}</script>"
    )
    # Some values (e.g. remap_wetlabs_eng_cols) are long unbroken strings with
    # no spaces to wrap on - without table-layout:fixed + word-break, the
    # browser's default table layout stretches that one column to fit,
    # pushing "expected"/"message" off-screen once "Show all" reveals every
    # row.
    print(
        "<style>"
        "table.calib-findings { table-layout: fixed; width: 100%; }"
        "table.calib-findings col.c-status { width: 6%; }"
        "table.calib-findings col.c-param { width: 14%; }"
        "table.calib-findings col.c-value { width: 20%; }"
        "table.calib-findings col.c-expected { width: 25%; }"
        "table.calib-findings col.c-message { width: 35%; }"
        "table.calib-findings td, table.calib-findings th {"
        "word-break: break-word; overflow-wrap: anywhere; vertical-align: top;"
        "}"
        "</style>"
    )
    print('<input type="button" value="Show all" onclick="toggleCalibOkRows(this);">')
    print(
        '<table class="calib-findings">'
        '<colgroup><col class="c-status"><col class="c-param"><col class="c-value">'
        '<col class="c-expected"><col class="c-message"></colgroup>'
    )
    if any_non_ok:
        print("<tr><th></th><th>parameter</th><th>value</th><th>expected</th><th>message</th></tr>")
    else:
        # No crit/warn/unknown rows exist to keep the table visible on its
        # own, so tag the header as another "ok row" - it hides along with
        # every data row by default, and reappears together with them when
        # "Show all" is clicked, via the same toggleCalibOkRows() JS.
        print(
            '<tr class="calib-ok-row" style="display:none;">'
            "<th></th><th>parameter</th><th>value</th><th>expected</th><th>message</th></tr>"
        )
    trow = 0
    for f in findings:
        if f["status"] == "unknown":
            continue
        if f["status"] == "ok":
            print('<tr class="calib-ok-row" style="background-color:%s; display:none;">' % rcolors[trow % 2])
        else:
            print('<tr style="background-color:%s;">' % rcolors[trow % 2])
        color = pcolors.get(f["status"])
        if color:
            print('<td style="background-color:%s;">[%s]</td>' % (color, f["status"]))
        else:
            print("<td>[%s]</td>" % f["status"])
        print("<td>%s</td>" % f["key"])
        print("<td>%s</td>" % f["value"])
        print("<td>%s</td>" % f["expected"])
        print("<td>%s</td>" % f["message"])
        print("</tr>")
        trow += 1

    for f in findings:
        if f["status"] != "unknown":
            continue
        print('<tr style="background-color:%s;">' % rcolors[trow % 2])
        print(
            '<td style="background-color:%s;">[unknown]</td><td>%s</td><td colspan=3>%s = %s is not a recognized sg_calib_constants.m variable</td>'
            % (pcolors.get("sers", "orange"), f["key"], f["key"], f["value"])
        )
        print("</tr>")
        trow += 1

    print("</table>")


def dump(calib_filename: pathlib.Path, capture_file: pathlib.Path | None) -> None:
    """Logs the validation findings for a sg_calib_constants.m file.

    Args:
        calib_filename: Path to sg_calib_constants.m.
        capture_file: Optional selftest .cap (or per-dive .log) file for
          specialized cross-checks.
    """
    log_info(f"Calibration constants validated from: {calib_filename}")

    findings = check_calib_constants(calib_filename, capture_file)
    for finding in findings:
        log_info(
            "%s: known=%s status=%s value=%s expected=%s %s"
            % (
                finding["key"],
                finding["known"],
                finding["status"],
                finding["value"],
                finding["expected"],
                finding["message"],
            )
        )


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Validates a mission's sg_calib_constants.m from the command line.

    Args:
        cmdline_args: Command-line arguments (defaults to sys.argv[1:]).

    Returns:
        0 for success, 1 for failure.

    Raises:
        Any exceptions raised are considered critical errors and not expected.
    """
    base_opts = BaseOpts.BaseOptions(
        "Test entry for sg_calib_constants.m validation",
        cmdline_args=cmdline_args,
        add_to_arguments=["mission_dir"],
        add_to_required=["mission_dir"],
    )
    BaseLogger(base_opts)  # initializes BaseLog

    calib_filename = base_opts.mission_dir / "sg_calib_constants.m"
    if not calib_filename.exists():
        log_error(f"{calib_filename} does not exist")
        return 1

    capture_candidates = sorted(base_opts.mission_dir.glob("pt*.cap"), reverse=True)
    capture_file = capture_candidates[0] if capture_candidates else None

    dump(calib_filename, capture_file)
    return 0


if __name__ == "__main__":
    ret_val = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        ret_val = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(ret_val)
