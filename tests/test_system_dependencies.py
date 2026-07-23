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

"""Smoke test for external command dependencies that shell scripts rely on.

selftest.sh shells out to command-line utilities that are not part of a
minimal Ubuntu install and must be explicitly provisioned - a gap that went
unnoticed for some time (dos2unix was missing from the Dockerfile) because
nothing exercised it. This test exists to catch that class of gap early,
rather than as a silent runtime failure (e.g. a truncated selftest.sh
section). Keep REQUIRED_COMMANDS in sync with Readme.md's "Shell
installation" section and the Dockerfile's runtime-dependencies apt-get line.
"""

import shutil

import pytest

REQUIRED_COMMANDS = ["tcsh", "bc", "dos2unix"]


@pytest.mark.parametrize("command", REQUIRED_COMMANDS)
def test_required_command_available(command: str) -> None:
    """Verifies a command selftest.sh depends on is available on PATH.

    Args:
        command: The command name to check for.

    Raises:
        AssertionError: If the command is not found on PATH.
    """
    assert shutil.which(command) is not None, (
        f"required command {command!r} not found on PATH - see Readme.md's "
        "'Shell installation' section"
    )
