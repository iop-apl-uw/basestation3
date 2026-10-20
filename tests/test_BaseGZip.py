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

"""BaseGZip: compress (gzip module based) and decompress round trips."""

import gzip
import io
import os
from pathlib import Path

import pytest

import BaseGZip


@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    f = tmp_path / "p6860005.nc"
    f.write_bytes(bytes(range(256)) * 50)
    os.utime(f, (1_700_000_000, 1_700_000_000))
    return f


@pytest.mark.parametrize("as_path", [True, False])
def test_compress_round_trip(data_file: Path, tmp_path: Path, as_path: bool) -> None:
    """A str or Path output name (it used to raise TypeError for a str, and refuse a Path)."""
    out = tmp_path / "p6860005.nc.gz"
    assert BaseGZip.compress(data_file if as_path else str(data_file), out if as_path else str(out)) == 0
    assert gzip.decompress(out.read_bytes()) == data_file.read_bytes()
    # The header carries the input's name and modification time
    with gzip.open(out) as gz:
        gz.read()
        assert gz.mtime == 1_700_000_000
    assert b"p6860005.nc\x00" in out.read_bytes()[:40]
    # and BaseGZip's own decompress reads it back
    back = tmp_path / "back"
    assert BaseGZip.decompress(out, back) == 0
    assert back.read_bytes() == data_file.read_bytes()


def test_compress_to_open_file(data_file: Path) -> None:
    buf = io.BytesIO()
    assert BaseGZip.compress(data_file, buf) == 0
    assert gzip.decompress(buf.getvalue()) == data_file.read_bytes()


def test_compress_failures(data_file: Path, tmp_path: Path) -> None:
    assert BaseGZip.compress(tmp_path / "missing", tmp_path / "out.gz") == 1
    assert BaseGZip.compress(data_file, tmp_path / "no_such_dir" / "out.gz") == 1
    assert BaseGZip.compress(data_file, 42) == 1  # ty: ignore[invalid-argument-type]
