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

"""FileMgr.FileCode: the names a transmitted file converts to."""

from pathlib import Path

import pytest

import FileMgr


@pytest.fixture
def logger(monkeypatch: pytest.MonkeyPatch) -> str:
    """A configured logger prefix (as logger_init adds one)."""
    monkeypatch.setattr(FileMgr, "logger_prefixes", [*FileMgr.logger_prefixes, "pm"])
    return "pm"


@pytest.mark.parametrize(
    ("raw", "dat"),
    [
        ("pm0042az.r", "ppm6860042a.dat"),  # dive
        ("pm0042bz.r", "ppm6860042b.dat"),  # climb
        ("pm0042cz.r", "ppm6860042c.dat"),  # loiter
        ("pm0042dz.r", "ppm6860042d.dat"),  # surface loiter - or a whole-dive data file, same type letter
    ],
)
def test_logger_dat_names_carry_the_cast(logger: str, tmp_path: Path, raw: str, dat: str) -> None:
    assert FileMgr.FileCode(tmp_path / raw, 686).mk_base_datfile_name() == tmp_path / dat


def test_logger_whole_dive_dat_name(logger: str, tmp_path: Path) -> None:
    """A logger file of a type that isn't a cast gets no cast letter."""
    assert FileMgr.FileCode(tmp_path / "pm0042lz.r", 686).mk_base_datfile_name() == tmp_path / "ppm6860042.dat"


def test_seaglider_dat_names(tmp_path: Path) -> None:
    assert FileMgr.FileCode(tmp_path / "sg0042dz.r", 686).mk_base_datfile_name() == tmp_path / "p6860042.dat"
    assert FileMgr.FileCode(tmp_path / "st0042dz.r", 686).mk_base_datfile_name() == tmp_path / "pt6860042.dat"


def test_processed_log_names(tmp_path: Path) -> None:
    selftest = FileMgr.FileCode(tmp_path / "pt6860042.log", 0)
    assert selftest.is_processed_seaglider_selftest_log()  # was always False ([0:1] == "pt")
    dive = FileMgr.FileCode(tmp_path / "p6860042.log", 0)
    assert dive.is_processed_seaglider_log() and not dive.is_processed_seaglider_selftest_log()
