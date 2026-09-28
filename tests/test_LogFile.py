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

import pytest

import LogFile


@pytest.mark.parametrize(
    "parm_name,value,expected",
    (
        ("$INTERNAL_PRESSURE", "8.2", [("$INTERNAL_PRESSURE", "8.2")]),
        (
            "$INTERNAL_PRESSURE",
            "8.2,8.5",
            [("$INTERNAL_PRESSURE", "8.2"), ("$INTERNAL_PRESSURE_LATCH", "8.5")],
        ),
        (
            "$INTERNAL_PRESSURE",
            "8.2,8.5,7.9,9.1",
            [
                ("$INTERNAL_PRESSURE", "8.2"),
                ("$INTERNAL_PRESSURE_LATCH", "8.5"),
                ("$INTERNAL_PRESSURE_MIN", "7.9"),
                ("$INTERNAL_PRESSURE_MAX", "9.1"),
            ],
        ),
        ("$INTERNAL_PRESSURE", "8.2,8.5,7.9", None),
        (
            "$HUMID",
            "40.1,65,38.2,41.0",
            [
                ("$HUMID", "40.1"),
                ("$HUMID_LIMIT", "65"),
                ("$HUMID_MIN", "38.2"),
                ("$HUMID_MAX", "41.0"),
            ],
        ),
        ("$HUMID", "40.1,65", None),
    ),
)
def test_split_multi_value_parm(parm_name, value, expected):
    assert LogFile.split_multi_value_parm(parm_name, value) == expected


def test_split_multi_value_parm_unknown_parm():
    with pytest.raises(KeyError):
        LogFile.split_multi_value_parm("$D_TGT", "90")
