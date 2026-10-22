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


"""Sensor extension fixes: legato's remap, pmar's binary eng files, tridente's error paths."""

import array
import pathlib
import pdb
import sys

import numpy as np
import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "Sensors"))
import legato_ext  # noqa: E402  # ty: ignore[unresolved-import]
import pmar_ext  # noqa: E402  # ty: ignore[unresolved-import]
import tridente_ext  # noqa: E402  # ty: ignore[unresolved-import]


def test_legato_fast_salinity_remaps_to_legato_salinity() -> None:
    """legatoFast_salinity was remapped to "legato_salnity"."""
    names = ["legatoFast_time", "legatoFast_salinity"]
    assert legato_ext.remap_engfile_columns_netcdf(None, "legato_ext", {}, names) == 0
    assert names == ["legato_time", "legato_salinity"]


def test_pmar_binary_upload_eng(tmp_path: pathlib.Path) -> None:
    """upload.eng's binary block is read as uint16s (the text-mode read failed on it)."""
    values = array.array("H", [1, 2, 0xC3FF, 40000])
    upload = tmp_path / "upload.eng"
    upload.write_bytes(b"%binaryoutput: 1\n%start: 1 2 3\n" + values.tobytes() + b"\n%stop: 4 5 6\n")
    assert list(pmar_ext.extract_file_data(upload)) == list(values)


def test_pmar_text_eng(tmp_path: pathlib.Path) -> None:
    """Text eng files still come back as columns."""
    eng = tmp_path / "pm0001a_logavg.eng"
    eng.write_text("%columns: a,b\n1.0 2.0\n3.0 4.0\n")
    cols = pmar_ext.extract_file_data(eng)
    np.testing.assert_array_equal(cols[0], [1.0, 3.0])
    np.testing.assert_array_equal(cols[1], [2.0, 4.0])


@pytest.mark.parametrize(("cols", "pts"), [(None, {}), (["a"], None)])
def test_tridente_eng_decimal_pts_mismatch_doesnt_stop(
    cols: list[str] | None, pts: dict | None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A version mismatch logs an error and returns -1 - it called pdb.set_trace(), stopping a server run."""

    def no_debugger() -> None:
        raise AssertionError("pdb.set_trace() called")

    monkeypatch.setattr(pdb, "set_trace", no_debugger)
    assert tridente_ext.eng_decimal_pts(None, "tridente_ext", cols, pts) == -1
