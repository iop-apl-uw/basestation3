#! /usr/bin/env python
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
"""Linux capability helpers shared by the processes that drop to a site's runner.

BaseRunnerPrivExec (and other workers run as baserunner) hold ambient
CAP_SETUID/CAP_SETGID so they can start work as each site's runner_user.
Linux does NOT clear capabilities when a process with ambient capabilities
changes between two non-root uids, and ambient capabilities survive exec -
so after setgid/setuid alone, the runner-side process (and everything it
runs) would still hold CAP_SETUID/CAP_SETGID and could make itself root.
drop_all_capabilities() closes that gap.
"""

from __future__ import annotations

import ctypes
import os
import sys

# capset(2) ABI - see <linux/capability.h>
_LINUX_CAPABILITY_VERSION_3 = 0x20080522


class _CapUserHeader(ctypes.Structure):
    _fields_ = [("version", ctypes.c_uint32), ("pid", ctypes.c_int)]


class _CapUserData(ctypes.Structure):
    _fields_ = [
        ("effective", ctypes.c_uint32),
        ("permitted", ctypes.c_uint32),
        ("inheritable", ctypes.c_uint32),
    ]


def drop_all_capabilities() -> None:
    """Irreversibly empties this process's capability sets (Linux only).

    Empties the permitted, effective and inheritable sets with capset(2),
    which also empties the ambient set (the kernel keeps ambient a subset
    of permitted & inheritable). Lowering capabilities is always allowed,
    so this only fails on a kernel/ABI error. A no-op off Linux.

    Call it after the setgid/setuid that makes this process a site's
    runner, and before exec'ing anything as that runner.

    Raises:
        OSError: If capset(2) fails.
    """
    if not sys.platform.startswith("linux"):
        return
    libc = ctypes.CDLL(None, use_errno=True)
    header = _CapUserHeader(_LINUX_CAPABILITY_VERSION_3, 0)
    data = (_CapUserData * 2)()  # version 3 takes two 32-bit halves, all zero
    if libc.capset(ctypes.byref(header), data) != 0:
        err = ctypes.get_errno()
        raise OSError(err, os.strerror(err))
