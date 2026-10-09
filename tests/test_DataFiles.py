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

"""DataFiles: the TIMEOUT alert threshold on a glider .dat file's sensor timeouts."""

from collections.abc import Iterator
from pathlib import Path

import pytest

import BaseOpts
import DataFiles
from BaseLog import BaseLogger, log_alerts


@pytest.fixture(autouse=True)
def _fresh_baselog() -> Iterator[None]:
    """Each test starts and ends with no alerts collected."""
    BaseLogger.reset()
    yield
    BaseLogger.reset()


def _dat(tmp_path: Path, timeouts: int) -> Path:
    """Writes a .dat whose sbect columns time out on `timeouts` rows.

    Args:
        tmp_path: Directory for the file.
        timeouts: Rows with a timeout.

    Returns:
        The .dat file.
    """
    rows = [
        f"{i} 5000 {i * 10} {'T' if i < timeouts else 1234} {'T' if i < timeouts else 5678}"
        for i in range(timeouts + 3)
    ]
    dat = tmp_path / "p2630001.dat"
    dat.write_text(
        "version: 67.01\nglider: 263\nmission: 12\ndive: 1\nstart: 10 6 126 3 19 30\n"
        "columns: rec,elaps_tms,depth,sbect.tempFreq,sbect.condFreq,\ndata:\n" + "\n".join(rows) + "\n"
    )
    return dat


def test_option_default() -> None:
    assert BaseOpts.global_options_dict["timeout_alert_threshold"].default_val == 5


@pytest.mark.parametrize(
    ("timeouts", "threshold", "alert"),
    [
        (2, None, False),  # default 5
        (5, None, False),  # at the threshold: no alert
        (6, None, True),
        (2, 1, True),
        (1, 0, True),  # 0: alert on any timeout, the old behavior
    ],
)
def test_timeout_alert_threshold(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, timeouts: int, threshold: int | None, alert: bool
) -> None:
    data_file = DataFiles.process_data_file(
        str(_dat(tmp_path, timeouts)), "dat", {}, timeout_alert_threshold=threshold
    )
    assert data_file is not None
    assert data_file.timeouts == {"sbect": timeouts}
    assert f"{timeouts} timeout(s) seen for sbect in" in caplog.text
    assert ("TIMEOUT" in log_alerts()) is alert
