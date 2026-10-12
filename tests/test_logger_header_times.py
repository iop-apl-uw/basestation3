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

"""Logger extensions skip a file whose %start/%stop header time is garbled, without a traceback.

The same comms damage that hit scicon_ext (sg240 sc0931b, sg271 sc0066b - fixed in 4886185):
pmar_ext and tmicl_ext warned and then re-raised, and scicon's camfb path had no guard.
"""

import logging
import pathlib
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import pmar_ext  # noqa: E402  # ty: ignore[unresolved-import]
import scicon_ext  # noqa: E402  # ty: ignore[unresolved-import]
import tmicl_ext  # noqa: E402  # ty: ignore[unresolved-import]

GOOD = "% start: 9 28 125 5 40 10\n"


@pytest.mark.parametrize(
    "header",
    [
        "% start: 9 28 125 5 40 101103\n",  # sg240 sc0931b: unconverted data remains
        "% start: 9 28\n",  # sg271 sc0066b: list index out of range
        GOOD + "% stop: 9 28\n",
    ],
)
@pytest.mark.parametrize(
    ("module", "extra_args"),
    [(pmar_ext, ("a", "")), (tmicl_ext, ("ch00",))],
)
def test_garbled_header_time_skips_file(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, header: str, module, extra_args
) -> None:
    eng = tmp_path / "pm.eng"
    eng.write_text("% columns: a b\n" + header + "1 2\n")
    with caplog.at_level(logging.WARNING):
        assert module.extract_file_metadata(eng, *extra_args) == (None, None)
    assert "- skipping file" in caplog.text


@pytest.mark.parametrize(("module", "extra_args"), [(pmar_ext, ("a", "")), (tmicl_ext, ("ch00",))])
def test_unreadable_file_is_none_pair(tmp_path: pathlib.Path, module, extra_args) -> None:
    """The callers unpack two values - the failure return is (None, None), not None."""
    assert module.extract_file_metadata(tmp_path / "missing.eng", *extra_args) == (None, None)


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("% start: 9 28\n1000 data\n", "Problems parsing % start in"),
        ("1000 data\n", "No % start: line before the data in"),
    ],
)
def test_camfb_bad_start(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, text: str, message: str) -> None:
    dat = tmp_path / "camfb.dat"
    dat.write_text(text)
    with caplog.at_level(logging.ERROR):
        assert scicon_ext.process_camfb_dat(SimpleNamespace(), str(dat), str(tmp_path / "camfb.eng"), [], []) == 1
    assert message in caplog.text and "skipping file" in caplog.text


def test_camfb_good(tmp_path: pathlib.Path) -> None:
    dat = tmp_path / "camfb.dat"
    dat.write_text(GOOD + "1000 data\n")
    others: list = []
    assert scicon_ext.process_camfb_dat(SimpleNamespace(), str(dat), str(tmp_path / "camfb.eng"), [], others) == 0
    assert len(others) == 1 and others[0].read_text().endswith(" data\n")
