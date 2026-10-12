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

import logging
import pathlib
import sys

import numpy as np
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


# --- corrupt SUNA lines (sg283 SG283_WHIRLS_CRUISE, July 2026) -------------

_SUNA_HEADER = (
    "%instrument: suna suna\n"
    "%columns: suna.time suna.nitrate \n"
    "%container: sc0053a\n"
    "%comment: SG283\n"
    "%start: 7 8 126 19 33 45 372\n"
)


def test_extract_file_data_drops_ragged_rows(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Garbled lines parse short; one ragged row used to lose every row of the file (dive 53)."""
    eng = tmp_path / "psc2830053a_suna_suna.eng"
    eng.write_text(
        _SUNA_HEADER
        + "1783539282.581 4.270 \n"
        + "CD9CC981C3C2BCC6B4D1AC83A4129BC694018CD4,750} 4.1 \n"  # junk token skipped -> 1 column
        + "1783539297.726 4.200 \n"
        + "1783539312.923 4.260 \n"
    )
    with caplog.at_level(logging.WARNING):
        data = scicon_ext.extract_file_data(eng)
    assert data is not None and len(data) == 2
    np.testing.assert_array_equal(data[0], [1783539282.581, 1783539297.726, 1783539312.923])
    np.testing.assert_array_equal(data[1], [4.270, 4.200, 4.260])
    assert "1 line(s) with an unexpected number of columns dropped (expected 2)" in caplog.text


def test_extract_file_data_clean_file_unchanged(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    eng = tmp_path / "psc2830028a_suna_suna.eng"
    eng.write_text(_SUNA_HEADER + "1.0 2.0 \n3.0 4.0 \n")
    with caplog.at_level(logging.WARNING):
        data = scicon_ext.extract_file_data(eng)
    np.testing.assert_array_equal(data[0], [1.0, 3.0])
    np.testing.assert_array_equal(data[1], [2.0, 4.0])
    assert "dropped" not in caplog.text


def test_eng_file_reader_non_ascii_auxdata(tmp_path: pathlib.Path) -> None:
    """A garbled character in a SUNA status record ('\\u02aa', dive 55) raised UnicodeEncodeError
    building the auxdata byte strings, dropping the dive's SUNA data."""
    eng = tmp_path / "psc2830055a_suna_suna.eng"
    eng.write_text(
        _SUNA_HEADER.replace("sc0053a", "sc0055a")
        + "1783539282.581 4.270 \n"
        + "%57209 0x1768,A,07/08/2026 19:34:09,1783539264,0.52\n"
        + "1783539297.726 4.200 \n"
        + "%72354 0x9B77,A,07/08/2026 19:34:29,\u02aa82,768\n"
        + "1783539312.923 4.260 \n",
        encoding="utf-8",
    )
    ret_list, _ = scicon_ext.eng_file_reader([{"file_name": eng, "cast": "a"}], {}, {})
    aux = [v for name, v in ret_list if "auxdata_data" in name]
    assert aux, f"no auxdata in {[name for name, _ in ret_list]}"
    records = [bytes(x).rstrip() for x in aux[0]]
    assert records[0].startswith(b"0x1768,A,07/08/2026")
    assert records[1] == b"0x9B77,A,07/08/2026 19:34:29,?82,768"


@pytest.mark.parametrize(("timeouts", "threshold", "alert"), [(3, 5, False), (5, 5, False), (6, 5, True), (1, 0, True)])
def test_convert_dat_to_eng_timeout_alert_threshold(
    tmp_path: pathlib.Path, timeouts: int, threshold: int, alert: bool
) -> None:
    """A cast's timeouts raise a TIMEOUT alert only above --timeout_alert_threshold."""
    from types import SimpleNamespace

    from BaseLog import BaseLogger, log_alerts

    BaseLogger.reset()
    dat = tmp_path / "ct.dat"
    dat.write_text("% columns: time t c\n" + "".join(f"% {32500 + i} T-O {{}}\n" for i in range(timeouts)))
    eng = tmp_path / "ct.eng"
    df_meta = SimpleNamespace(
        instrument=SimpleNamespace(instr_class="ct"), scale_off={}, start_time=0.0, columns="time t c", sealevel=None
    )
    base_opts = SimpleNamespace(timeout_alert_threshold=threshold)
    assert scicon_ext.ConvertDatToEng(dat, eng, df_meta, base_opts) == 0
    assert f"%timeouts: {timeouts}" in eng.read_text()
    assert ("TIMEOUT" in log_alerts()) is alert
    BaseLogger.reset()


def _cast(tmp_path: pathlib.Path, data_lines: list[str]) -> tuple[pathlib.Path, pathlib.Path, object, object]:
    """A minimal ct cast: time and two delta-encoded columns, scale 1, offset 0."""
    from types import SimpleNamespace

    dat = tmp_path / "ct.dat"
    dat.write_text("% columns: time t c\n" + "".join(f"{line}\n" for line in data_lines))
    df_meta = SimpleNamespace(
        instrument=SimpleNamespace(instr_class="ct"),
        scale_off=[scicon_ext.scale_off_type(1.0, 0.0)] * 3,
        start_time=1000.0,
        columns="time t c",
        sealevel=None,
    )
    return dat, tmp_path / "ct.eng", df_meta, SimpleNamespace(timeout_alert_threshold=5)


def _rows(eng: pathlib.Path) -> list[list[float]]:
    return [[float(v) for v in line.split()] for line in eng.read_text().splitlines() if not line.startswith("%")]


@pytest.mark.parametrize(
    ("bad", "reason"),
    [
        ("1000 -4-354 2", "invalid literal for int() with base 10: '-4-354'"),  # sg271 sc0095b: fused values
        ("1000 3", "2 values, expected 3"),  # short line
    ],
)
def test_convert_dat_to_eng_stops_at_a_bad_line(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, bad: str, reason: str
) -> None:
    """A damaged data line keeps the rows before it - values are deltas, so nothing after it is used."""
    dat, eng, df_meta, base_opts = _cast(tmp_path, ["0 10 20", "1000 1 2", "1000 1 2", bad, "1000 1 2"])
    with caplog.at_level(logging.ERROR):
        assert scicon_ext.ConvertDatToEng(dat, eng, df_meta, base_opts) == 0
    assert _rows(eng) == [[1000.0, 10.0, 20.0], [1001.0, 11.0, 22.0], [1002.0, 12.0, 24.0]]
    assert f"Bad data line 5 of {dat} ({reason}) - keeping the 3 row(s) before it" in caplog.text
    assert "%timeouts: 0" in eng.read_text()


def test_convert_dat_to_eng_bad_first_line(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    dat, eng, df_meta, base_opts = _cast(tmp_path, ["0 1x0 20", "1000 1 2"])
    with caplog.at_level(logging.ERROR):
        assert scicon_ext.ConvertDatToEng(dat, eng, df_meta, base_opts) == 1
    assert f"Bad data line 2 of {dat}" in caplog.text


def test_convert_dat_to_eng_clean_cast(tmp_path: pathlib.Path) -> None:
    dat, eng, df_meta, base_opts = _cast(tmp_path, ["0 10 20", "1000 1 2", "1000 -1 -2"])
    assert scicon_ext.ConvertDatToEng(dat, eng, df_meta, base_opts) == 0
    assert _rows(eng) == [[1000.0, 10.0, 20.0], [1001.0, 11.0, 22.0], [1002.0, 10.0, 20.0]]


_HEADER = (
    "%instrument: 0 ct\n%columns: time(1000,0) t(1,0) c(1,0)\n%container: sc0849b\n"
    "%start: 9 28 125 5 40 10\n%samples: 3\n%sealevel: 10082\n%data:\n"
)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("%sealevel: 10082\n", "%sealevel:  \n", "Bad %sealevel value '' in"),  # sg240 sc0849b: truncated header
        ("%samples: 3\n", "%samples: 3x\n", "Bad %samples value '3x' in"),
        ("%start: 9 28 125 5 40 10\n", "%start: 9 28\n", "Problems parsing %start in"),
    ],
)
def test_extract_file_metadata_bad_header_field(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, old: str, new: str, message: str
) -> None:
    """A garbled header field skips the file with a warning - no exception."""
    good = tmp_path / "good.dat"
    good.write_text(_HEADER)
    meta, _ = scicon_ext.extract_file_metadata(good)
    assert (meta.samples, meta.sealevel, meta.instrument.instr_class) == (3, 10082, "ct")
    bad = tmp_path / "ct.dat"
    bad.write_text(_HEADER.replace(old, new))
    assert scicon_ext.extract_file_metadata(bad) == (None, None)
    assert message in caplog.text and "skipping file" in caplog.text
