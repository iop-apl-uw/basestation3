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

"""Regression test for Sensors/cp_ext.py's subprocess exit-status
handling - process_data_files previously discarded Utils.run_cmd_shell()'s
return value entirely (no failure detection at all before copying the
non-existent matfile into place); it must now return 1 and append
nothing to the processed-file lists when the ad2cpMAT convertor fails."""

import pathlib
import sys
from unittest.mock import MagicMock

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import cp_ext  # noqa: E402  # ty: ignore[unresolved-import]


def test_process_data_files_failure_with_fake_convertor(tmp_path: pathlib.Path) -> None:
    sensors_dir = tmp_path / "Sensors"
    sensors_dir.mkdir()
    convertor = sensors_dir / "ad2cpMAT"
    convertor.write_text("#!/bin/sh\nexit 1\n")
    convertor.chmod(0o755)

    class FakeBaseOpts:
        basestation_directory = str(tmp_path)

    up_file = tmp_path / "pc0000au.000"
    up_file.write_bytes(b"dummy ad2cp data")
    eng_file = tmp_path / "pc0000a.eng"

    fc = MagicMock()
    fc.is_down_data.return_value = False
    fc.is_up_data.return_value = True
    fc.full_filename.return_value = up_file
    fc.mk_base_engfile_name.return_value = eng_file

    processed_logger_eng_files = []
    processed_logger_other_files = []

    ret_val = cp_ext.process_data_files(
        FakeBaseOpts(),
        "cp_ext",
        {},
        fc,
        processed_logger_eng_files,
        processed_logger_other_files,
    )

    assert ret_val == 1
    assert processed_logger_eng_files == []
    assert not eng_file.exists()
