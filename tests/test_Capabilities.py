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

"""Tests for Capabilities.drop_all_capabilities. The real capset(2) effect is
validated on a Linux host by testlong (test_privilege_drop_chain,
test_multipass_makekml_ssh); these check the call it makes."""

import ctypes
import errno
from typing import Any

import pytest

import Capabilities


def test_noop_off_linux(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Capabilities.sys, "platform", "darwin")
    def _no_libc(*args: Any, **kwargs: Any) -> None:
        raise AssertionError("must not touch libc off Linux")

    monkeypatch.setattr(Capabilities.ctypes, "CDLL", _no_libc)

    Capabilities.drop_all_capabilities()


class _FakeLibc:
    def __init__(self, result: int) -> None:
        self.result = result
        self.calls: list[tuple] = []

    def capset(self, header_ref: Any, data: Any) -> int:
        header = ctypes.cast(header_ref, ctypes.POINTER(Capabilities._CapUserHeader)).contents
        halves = [(d.effective, d.permitted, d.inheritable) for d in data]
        self.calls.append((header.version, header.pid, halves))
        return self.result


def test_capset_called_with_all_zero_sets(monkeypatch: pytest.MonkeyPatch) -> None:
    libc = _FakeLibc(0)
    monkeypatch.setattr(Capabilities.sys, "platform", "linux")
    monkeypatch.setattr(Capabilities.ctypes, "CDLL", lambda *a, **kw: libc)

    Capabilities.drop_all_capabilities()

    assert libc.calls == [(0x20080522, 0, [(0, 0, 0), (0, 0, 0)])]


def test_capset_failure_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(Capabilities.sys, "platform", "linux")
    monkeypatch.setattr(Capabilities.ctypes, "CDLL", lambda *a, **kw: _FakeLibc(-1))
    monkeypatch.setattr(Capabilities.ctypes, "get_errno", lambda: errno.EPERM)

    with pytest.raises(OSError) as excinfo:
        Capabilities.drop_all_capabilities()

    assert excinfo.value.errno == errno.EPERM
