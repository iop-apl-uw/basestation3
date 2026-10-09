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

"""MissionCallStats with a comm.log that has no dive numbers yet."""

from pathlib import Path
from types import SimpleNamespace

import pytest

import CommLog
from Plotting import MissionCallStats


def test_no_dive_numbers_skips_plot(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """Calls without a dive number (e.g. a new deployment's selftests) don't raise.

    sg627 2026-10-09: interp1d was handed empty arrays (ValueError in scipy's _reshape_yi).
    """
    comm_log = SimpleNamespace(sessions=[SimpleNamespace(dive_num=None), SimpleNamespace(dive_num=None)])
    monkeypatch.setattr(CommLog, "process_comm_log", lambda *_args, **_kw: (comm_log, None, None, None, None))
    messages: list[str] = []
    monkeypatch.setattr(MissionCallStats, "log_info", messages.append, raising=False)
    base_opts = SimpleNamespace(mission_dir=tmp_path)
    assert MissionCallStats.mission_callstats(base_opts, ["sg627"]) == ([], [])
    assert messages == ["No calls with a dive number in comm.log yet - skipping mission_callstats"]
