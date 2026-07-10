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

from unittest.mock import MagicMock

import pytest

import FTPPush


def _make_base_opts(tmp_path, ftp_type: str) -> MagicMock:
    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    base_opts.ftp_type = ftp_type
    base_opts.file_spec = ""
    return base_opts


def _patch_common(monkeypatch: pytest.MonkeyPatch, base_opts: MagicMock) -> None:
    monkeypatch.setattr(FTPPush.BaseOpts, "BaseOptions", lambda *a, **k: base_opts)
    monkeypatch.setattr(FTPPush, "BaseLogger", MagicMock())


def test_ftppush_all_processes_all_three_types(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """--ftp_type all (the default) should push via .ftp, .sftp, and .ftps."""
    base_opts = _make_base_opts(tmp_path, "all")
    _patch_common(monkeypatch, base_opts)

    calls = []

    def fake_process_ftp(
        base_opts,
        processed_file_names,
        mission_ts,
        mission_pro,
        known_ftp_tags,
        ftp_type,
    ):
        calls.append(ftp_type)
        return 0

    monkeypatch.setattr(FTPPush.BaseDotFiles, "process_ftp", fake_process_ftp)

    result = FTPPush.main()

    assert result == 0
    assert calls == [".ftp", ".sftp", ".ftps"]


@pytest.mark.parametrize(
    "ftp_type,expected", [("ftp", ".ftp"), ("sftp", ".sftp"), ("ftps", ".ftps")]
)
def test_ftppush_single_type_only_pushes_that_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path, ftp_type: str, expected: str
) -> None:
    """Passing a specific --ftp_type should restrict processing to just that dotfile."""
    base_opts = _make_base_opts(tmp_path, ftp_type)
    _patch_common(monkeypatch, base_opts)

    calls = []

    def fake_process_ftp(
        base_opts,
        processed_file_names,
        mission_ts,
        mission_pro,
        known_ftp_tags,
        ftp_type,
    ):
        calls.append(ftp_type)
        return 0

    monkeypatch.setattr(FTPPush.BaseDotFiles, "process_ftp", fake_process_ftp)

    result = FTPPush.main()

    assert result == 0
    assert calls == [expected]


def test_ftppush_aggregates_failures(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    """If any of the three types fails, main() should return a non-zero exit code."""
    base_opts = _make_base_opts(tmp_path, "all")
    _patch_common(monkeypatch, base_opts)

    def fake_process_ftp(
        base_opts,
        processed_file_names,
        mission_ts,
        mission_pro,
        known_ftp_tags,
        ftp_type,
    ):
        return 1 if ftp_type == ".sftp" else 0

    monkeypatch.setattr(FTPPush.BaseDotFiles, "process_ftp", fake_process_ftp)

    result = FTPPush.main()

    assert result == 1


def test_ftppush_missing_mission_dir_is_an_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    base_opts = _make_base_opts(None, "all")
    base_opts.mission_dir = None
    _patch_common(monkeypatch, base_opts)

    process_ftp = MagicMock(return_value=0)
    monkeypatch.setattr(FTPPush.BaseDotFiles, "process_ftp", process_ftp)

    result = FTPPush.main()

    assert result == 1
    process_ftp.assert_not_called()
