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

import logging

import numpy as np
import pytest

from Plotting import DivePlot


def test_on_time_base_matching_length_is_kept() -> None:
    values = np.arange(5.0)
    assert DivePlot.on_time_base("x", values, np.arange(5.0), 1) is values


def test_on_time_base_missing_values_is_quiet(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        assert DivePlot.on_time_base("x", None, np.arange(5.0), 1) is None
    assert caplog.text == ""


@pytest.mark.parametrize(
    "time_base, described",
    [
        # sg250 p2500938.nc: GSM speeds on ctd_data_point (4322), no ctd_time,
        # so the plot fell back to the truck time (3182) - IndexError
        (np.arange(3182.0), "3182"),
        (None, "none"),
    ],
)
def test_on_time_base_mismatch_is_dropped_with_warning(
    caplog: pytest.LogCaptureFixture, time_base: np.ndarray | None, described: str
) -> None:
    with caplog.at_level(logging.WARNING):
        result = DivePlot.on_time_base("vert_speed_gsm", np.arange(4322.0), time_base, 938)
    assert result is None
    assert (
        f"Dive 938: vert_speed_gsm has 4322 points but the time base has {described} - not plotted"
        in caplog.text
    )
