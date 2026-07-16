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

import numpy as np
import pytest

import validate
import WkbConfigText

_BUCKETS_DEPTHS = np.array([100.0, 250.0, 1000.0])
_SAMPLING_RATE = np.array([5.0, 10.0, 20.0])


class _FakeVariable:
    def __init__(self, value):
        self._value = value

    def getValue(self):
        return self._value


class _FakeDiveNcFile:
    def __init__(self, ct_type: int, variables: dict[str, object] | None = None):
        self.variables = {"sg_cal_sg_ct_type": _FakeVariable(ct_type)}
        if variables:
            self.variables.update(variables)


@pytest.mark.parametrize("ct_type", (0, 1, 3))
def test_ct_mount_classic_seabird_is_truck(ct_type):
    assert WkbConfigText.ct_mount(_FakeDiveNcFile(ct_type)) == "truck"


def test_ct_mount_missing_ct_type_is_truck():
    dive_nc_file = _FakeDiveNcFile(0)
    del dive_nc_file.variables["sg_cal_sg_ct_type"]
    assert WkbConfigText.ct_mount(dive_nc_file) == "truck"


def test_ct_mount_gpctd_is_always_logger():
    assert WkbConfigText.ct_mount(_FakeDiveNcFile(2)) == "logger"


def test_ct_mount_legato_scicon():
    dive_nc_file = _FakeDiveNcFile(4, {"legato_time": object()})
    assert WkbConfigText.ct_mount(dive_nc_file) == "scicon"


def test_ct_mount_legato_truck():
    dive_nc_file = _FakeDiveNcFile(4, {"eng_rbr_temp": object()})
    assert WkbConfigText.ct_mount(dive_nc_file) == "truck"


def test_ct_mount_legato_neither_marker_falls_back_to_logger():
    # Unconfirmed by a real test fixture yet (PLAN.md Task 5) - best-guess
    # fallback when neither the truck nor scicon marker variable is present.
    dive_nc_file = _FakeDiveNcFile(4)
    assert WkbConfigText.ct_mount(dive_nc_file) == "logger"


@pytest.mark.parametrize(
    ("ct_type", "expected"),
    (
        (0, "original Seabird unpumped CTD"),
        (1, "gun-style Seabird unpumped CTD"),
        (2, "pumped Seabird GPCTD"),
        (3, "gun-style Seabird unpumped SAILCT"),
        (4, "unpumped RBR Legato"),
    ),
)
def test_ct_type_name(ct_type, expected):
    assert WkbConfigText.ct_type_name(_FakeDiveNcFile(ct_type)) == expected


def test_ct_type_name_missing_variable():
    dive_nc_file = _FakeDiveNcFile(0)
    del dive_nc_file.variables["sg_cal_sg_ct_type"]
    assert WkbConfigText.ct_type_name(dive_nc_file) == "unknown"


@pytest.mark.parametrize(
    ("label", "expected"),
    (
        ("Current", "/ Current"),
        ("%-20", "/ %-20"),
        ("%+0", "/ %+0"),
        ("%+50", "/ %+50"),
    ),
)
def test_comment_line(label, expected):
    assert WkbConfigText.comment_line(label) == expected


def test_comment_line_validates_as_a_comment():
    block = WkbConfigText.comment_line("%-20") + "\n" + WkbConfigText.scicon_ct_block(_BUCKETS_DEPTHS, _SAMPLING_RATE)
    _res, errors, _warnings = validate.sciconsch(block)
    assert errors == 0


def test_scicon_ct_block_matches_expected_text():
    block = WkbConfigText.scicon_ct_block(_BUCKETS_DEPTHS, _SAMPLING_RATE)
    assert block == "ct = {\n 100,5.0\n 250,10.0\n 1000,20.0\n}"


def test_scicon_ct_block_validates_cleanly():
    _res, errors, _warnings = validate.sciconsch(WkbConfigText.scicon_ct_block(_BUCKETS_DEPTHS, _SAMPLING_RATE))
    assert errors == 0


def test_scicon_ct_block_omits_nan_intervals():
    # A bucket deeper than the dive reached (e.g. compute_wkb_schedule's
    # buckets_sampling_rate beyond the actual max depth) is NaN - "500,nan"
    # isn't a usable schedule entry, so it should be dropped rather than
    # printed literally.
    buckets_depths = np.array([100.0, 250.0, 500.0, 1000.0])
    sampling_rate = np.array([5.0, 10.0, np.nan, np.nan])

    block = WkbConfigText.scicon_ct_block(buckets_depths, sampling_rate)

    assert block == "ct = {\n 100,5.0\n 250,10.0\n}"


def test_proposed_config_text_always_scicon_format():
    # No dive/mount info needed at all - always the same scicon-style block.
    text = WkbConfigText.proposed_config_text(_BUCKETS_DEPTHS, _SAMPLING_RATE)

    assert text == "ct = {\n 100,5.0\n 250,10.0\n 1000,20.0\n}"


@pytest.mark.parametrize(
    ("ct_type", "variables", "expected"),
    (
        (0, None, "sbect"),
        (1, None, "sbect"),
        (2, None, "sbect"),
        (0, {"gpctd_time": object()}, "gpctd"),
        (4, None, "legato"),
    ),
)
def test_ctd_instrument_name(ct_type, variables, expected):
    assert WkbConfigText.ctd_instrument_name(_FakeDiveNcFile(ct_type, variables)) == expected


def test_current_grid_block_sorts_and_skips_non_numeric_keys():
    grid = {"profile": "a", 250.0: 10.0, 100.0: 5.0, 1000.0: 20.0}

    block = WkbConfigText.current_grid_block(grid)

    assert block == "ct = {\n 100,5.0\n 250,10.0\n 1000,20.0\n}"


def test_current_grid_block_validates_cleanly():
    grid = {"profile": "a", 250.0: 10.0, 100.0: 5.0, 1000.0: 20.0}
    _res, errors, _warnings = validate.sciconsch(WkbConfigText.current_grid_block(grid))
    assert errors == 0


def test_current_grid_block_returns_none_for_empty_grid():
    assert WkbConfigText.current_grid_block({}) is None


def test_current_grid_block_returns_none_when_only_metadata_keys():
    assert WkbConfigText.current_grid_block({"profile": "a", "dive": 12}) is None
