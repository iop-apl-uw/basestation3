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


"""ssh/AvisoUtils.py: fetching the day's AVISO file."""

import logging
import pathlib
import sys
import types

import pytest

import Base  # noqa: F401 - normal import order

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "ssh"))
import AvisoUtils  # noqa: E402


@pytest.fixture(autouse=True)
def _credentials(monkeypatch: pytest.MonkeyPatch) -> None:
    """fetch_aviso_nrt imports the Copernicus credentials from a server-only config module."""
    monkeypatch.setitem(sys.modules, "config", types.SimpleNamespace(copernicus_user="u", copernicus_passwd="p"))


def test_not_published_yet(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    """copernicusmarine.get() finds nothing (today's file isn't out yet): a warning, no path - so no
    FileNotFoundError in main's copy (seaglider.pub and iopbase3, 2026-10-16)."""
    monkeypatch.setattr(AvisoUtils.copernicusmarine, "get", lambda **kwargs: None)
    with caplog.at_level(logging.WARNING):
        assert AvisoUtils.fetch_aviso_nrt("20261016", str(tmp_path)) is None
    assert "nrt_global_allsat_phy_l4_20261016_20261016.nc isn't available yet" in caplog.text


def test_fetched(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch) -> None:
    name = "nrt_global_allsat_phy_l4_20261015_20261015.nc"

    def get(**kwargs: object) -> None:
        (pathlib.Path(str(kwargs["output_directory"])) / name).write_bytes(b"")

    monkeypatch.setattr(AvisoUtils.copernicusmarine, "get", get)
    assert AvisoUtils.fetch_aviso_nrt("20261015", str(tmp_path)) == tmp_path / name
    # Already there: nothing to do
    assert AvisoUtils.fetch_aviso_nrt("20261015", str(tmp_path)) is None


def test_fetch_fails(tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture) -> None:
    def get(**kwargs: object) -> None:
        raise RuntimeError("server down")

    monkeypatch.setattr(AvisoUtils.copernicusmarine, "get", get)
    with caplog.at_level(logging.ERROR):
        assert AvisoUtils.fetch_aviso_nrt("20261016", str(tmp_path)) is None
    assert "Failed fetching file" in caplog.text
