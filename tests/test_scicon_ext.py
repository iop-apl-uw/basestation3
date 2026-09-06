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

"""Regression tests for Sensors/scicon_ext.py's subprocess exit-status
handling - process_adcp_dat and process_ctx3_dat must treat a nonzero
Utils.run_cmd_shell() exit status as a failure (return 1, append nothing
to the processed-file lists), matching the sibling fix in BaseNetwork.py
(convert_network_logfile/convert_network_profile used to check
`if sts >> 8:`, an os.wait()-style check that doesn't apply to
run_cmd_shell's plain 0-255 returncode)."""

import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import scicon_ext  # noqa: E402  # ty: ignore[unresolved-import]


def test_process_adcp_dat_failure_with_fake_convertor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """A sc2mat_convertor that exits nonzero must be treated as a failure -
    process_adcp_dat must return 1 and must not append to either
    processed-file list or copy the (non-existent) matfile into place."""
    sensors_dir = tmp_path / "Sensors"
    sensors_dir.mkdir()
    convertor = sensors_dir / "fake_sc2mat"
    convertor.write_text("#!/bin/sh\nexit 1\n")
    convertor.chmod(0o755)

    class FakeBaseOpts:
        basestation_directory = str(tmp_path)
        sc2mat_convertor = "fake_sc2mat"

    scicon_file = str(tmp_path / "sc0000ad.eng.raw")
    pathlib.Path(scicon_file).write_bytes(b"dummy adcp data")
    scicon_eng_file = str(tmp_path / "sc0000ad.eng")

    processed_logger_eng_files = []
    processed_logger_other_files = []

    ret_val = scicon_ext.process_adcp_dat(
        FakeBaseOpts(),
        scicon_file,
        scicon_eng_file,
        processed_logger_eng_files,
        processed_logger_other_files,
    )

    assert ret_val == 1
    assert processed_logger_eng_files == []
    assert processed_logger_other_files == []
    assert not pathlib.Path(scicon_eng_file).exists()


def test_process_ctx3_dat_failure_with_fake_convertor(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Same regression as above, for process_ctx3_dat. The x3decode_ts
    convertor path is hardcoded (not derived from base_opts), so the
    existence/executable checks are bypassed via monkeypatch to reach the
    exit-status check under test."""
    monkeypatch.setattr(scicon_ext.os.path, "isfile", lambda p: True)
    monkeypatch.setattr(scicon_ext.os, "access", lambda p, mode: True)
    monkeypatch.setattr(
        scicon_ext.Utils, "run_cmd_shell", lambda *a, **kw: (1, None)
    )

    scicon_file = str(tmp_path / "sc0000ct.eng.raw")
    output_file = str(tmp_path / "sc0000ct.eng")
    processed_logger_other_files = []

    ret_val = scicon_ext.process_ctx3_dat(
        object(), scicon_file, output_file, processed_logger_other_files
    )

    assert ret_val == 1
    assert processed_logger_other_files == []
