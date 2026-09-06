# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
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

"""Regression test: ssh/MakeKMLSSHMissions.py launches MakeKML.py as a
fire-and-forget subprocess with output redirected to a log file, but
previously discarded the exit status entirely. A nonzero exit must now
produce an explicit log_error (in addition to the existing "see log for
details" message) so a failed MakeKML.py run isn't silently missed."""

import logging
import pathlib
import sys
import time

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ssh"))
import MakeKMLSSHMissions  # noqa: E402  # ty: ignore[unresolved-import]


def test_main_logs_error_when_makekml_exits_nonzero(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setattr(MakeKMLSSHMissions, "BaseLogger", lambda *a, **kw: None)
    monkeypatch.setattr(
        MakeKMLSSHMissions, "get_active_missions", lambda base_opts: [(tmp_path, 7)]
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions, "find_last_update", lambda data_dir: time.time()
    )
    (tmp_path / "sg_plot_constants.m").write_text("")

    monkeypatch.setattr(
        MakeKMLSSHMissions.MakeKMLSSH,
        "make_kml",
        lambda *a, **kw: str(tmp_path / "fake.kmz"),
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions.Utils, "check_lock_file", lambda base_opts, lock_name: 0
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions.Utils, "run_cmd_shell", lambda cmd_line: (1, None)
    )
    monkeypatch.setattr(
        MakeKMLSSHMissions.Utils, "notifyVis", lambda *a, **kw: None
    )

    class FakeBaseOpts:
        data_dir = tmp_path
        force = False
        fetch_ssh = False
        mergessh = True
        mission_yml = tmp_path / "missions.yml"

    with caplog.at_level(logging.ERROR):
        ret_val = MakeKMLSSHMissions.main(base_opts=FakeBaseOpts())

    assert ret_val == 0
    assert any("MakeKML.py exited 1" in r.message for r in caplog.records)
