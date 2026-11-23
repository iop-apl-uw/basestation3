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

"""Tests for GPS.py - GPS line date/time checks."""

import logging
import time

import pytest

import GPS


@pytest.mark.parametrize(
    ("date_field", "time_field", "sms_line", "expected"),
    [
        ("260506", "151750", False, True),
        ("260506", "1517", True, True),  # the truncated SMS form
        ("260506", "1517", False, False),  # HHMM only on an SMS line
        ("2111", "0016", False, False),  # sg262 under-ice nav fix (DDMM,HHMM)
        ("0611", "2016", False, False),
        ("260506", "151750.5", False, False),
        ("26O506", "151750", False, False),
    ],
)
def test_gps_timestamp_well_formed(
    date_field: str, time_field: str, sms_line: bool, expected: bool
) -> None:
    """Only DDMMYY,HHMMSS (HHMM on an SMS line) is well formed."""
    assert GPS.gps_timestamp_well_formed(date_field, time_field, sms_line) is expected


def test_well_formed_line_is_valid() -> None:
    """A normal fix parses its date and time."""
    fix = GPS.GPSFix("GPS,260506,151750,4807.211,-12223.095,34,1.1,34,18.0")
    assert fix.isvalid
    assert not fix.timestamp_malformed
    assert fix.datetime is not None
    assert time.strftime("%Y-%m-%d %H:%M:%S", fix.datetime) == "2006-05-26 15:17:50"


def test_sms_line_hhmm() -> None:
    """The 7 field SMS form reports HHMM and still parses."""
    fix = GPS.GPSFix("GPS,260506,1517,4807.211,-12223.095,1.1,34")
    assert fix.isvalid
    assert fix.datetime is not None
    assert time.strftime("%Y-%m-%d %H:%M", fix.datetime) == "2006-05-26 15:17"


@pytest.mark.parametrize(
    "line",
    [
        # sg262 BBOS_Sep26 comm.log, dive 255 (2026-11-21) - parsed as 21 Nov 2000, then a TypeError
        "GPS,2111,0016,7152.144,-6758.859,0,69535.0,0,-30.8",
        # sg262 p2620237.log - silently parsed as 6 Nov 2020 01:06
        "$GPS,0611,2016,7151.293,-6759.892,0,69535.0,0,-30.8",
        "$GPS1,0511,1616,7151.793,-6757.713,0,69535.0,0,-30.8,0.0,0.0,0,0.0",
        # six digits each, but no such month
        "GPS,261306,151750,4807.211,-12223.095,34,1.1,34,18.0",
    ],
)
def test_malformed_timestamp_marks_fix_invalid(
    line: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A malformed date/time marks the fix invalid with no time - not guessed at - and keeps the position."""
    with caplog.at_level(logging.WARNING):
        fix = GPS.GPSFix(line)
    assert not fix.isvalid
    assert fix.timestamp_malformed
    assert fix.datetime is None
    assert fix.lat is not None and fix.lon is not None and fix.hdop is not None
    assert "Malformed date/time" in caplog.text
    assert "fix marked invalid" in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
