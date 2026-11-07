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

"""CommLog.process_comm_log."""

import logging
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

import CommLog
import GPS


def test_scan_back_prints_nothing(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    """scan_back finds the last Connected line without writing the lines it scans to stdout."""
    comm_log = tmp_path / "comm.log"
    comm_log.write_text(
        "Connected at 2026-08-08T11:21:07Z (sg180)\nlogged in\nDisconnected at 2026-08-08T11:30:00Z\n"
        "Connected at 2026-08-08T12:21:07Z (sg180)\nlogged in\n"
    )
    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    _, start_pos, _, _, status = CommLog.process_comm_log(comm_log, base_opts, scan_back=True)
    assert status == 0 and start_pos is not None
    assert capsys.readouterr().out == ""


def test_dive_num_without_call_counter() -> None:
    """A session with a dive number but no call counter gives 0, not None (names are built from it)."""
    session = CommLog.ConnectSession(time.gmtime(0), "UTC")
    session.dive_num = 42
    comm_log = CommLog.CommLog([session], [], {}, {})
    assert comm_log.get_last_dive_num_and_call_counter() == (42, 0)
    session.calls_made = 3
    assert comm_log.get_last_dive_num_and_call_counter() == (42, 3)
    session.call_cycle = 5
    assert comm_log.get_last_dive_num_and_call_counter() == (42, 5)


def test_counter_line_with_hangup_logs_no_gps_error(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """A hangup appended to a counter line (sg238, 2026-10-30) is warned about once, not logged as a bad GPS line."""
    comm_log = tmp_path / "comm.log"
    comm_log.write_text(
        "Connected at 2026-10-28T22:00:26Z (sg238)\nlogged in\n"
        "3:0:1:2:0:114:-3:1549:2194:201:-60.9:-0.01:20.4:15.33:0.00:8.59:42.7:16.4:0.0:-1.1 "
        "GPS,281026,213315,4739.311,-12219.055,2,0.8,4,15.0\n"
        "Disconnected at 2026-10-28T22:10:00Z (normal)\n\n\n"
        "Connected at 2026-10-30T19:40:39Z (sg238)\nlogged in\n"
        "3:0:1:0:0:116:0:1551:2202:202:-88.5:-0.06:18.8:15.53:0.00:8.53:43.5:15.8:0.0:-1.0 "
        "Disconnected at 2026-10-30T19:41:20Z (hangup)\n"
    )
    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    with caplog.at_level(logging.WARNING):
        commlog, _, _, _, _ = CommLog.process_comm_log(comm_log, base_opts)
    assert commlog is not None
    assert commlog.sessions[0].gps_fix is not None and commlog.sessions[0].gps_fix.isvalid
    assert "Bad GPS line" not in caplog.text
    assert not [r for r in caplog.records if r.levelno >= logging.ERROR]
    assert len([r for r in caplog.records if "Unknown line after counter" in r.getMessage()]) == 1


def _session_with_fix(reboot_count):
    session = CommLog.ConnectSession(time.gmtime(0), "UTC")
    session.gps_fix = GPS.GPSFix("GPS,260506,151750,4807.211,-12223.095,34,1.1,34,18.0")
    session.reboot_count = reboot_count
    return session


@pytest.mark.parametrize("previous_count", [None, 3])
def test_has_glider_rebooted_previous_count_missing(previous_count):
    """A previous session with no reboot count (a short counter line) answers 'no reboot', not TypeError."""
    comm_log = CommLog.CommLog([_session_with_fix(previous_count), _session_with_fix(3)], [], {}, {})
    assert comm_log.has_glider_rebooted() is None
