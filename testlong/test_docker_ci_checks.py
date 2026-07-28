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

"""Runs the same lint/typecheck/test checks CI runs, inside the ci image.

Mirrors .github/workflows/action.yml's Ruff/ty/pytest steps one-for-one, but
executed inside the container built from the Dockerfile's `ci` stage - this
is the "build a container, copy in source, run lint/typecheck/tests"
validation.
"""

from __future__ import annotations

import dockerutils
import pytest

_CHECKS = [
    pytest.param(["uv", "run", "ruff", "check", "--output-format=github"], id="ruff"),
    pytest.param(["uv", "run", "ty", "check", "--output-format=github"], id="ty"),
    pytest.param(
        ["uv", "run", "pytest", "-rsx", "--cov", "--cov-report", "term-missing", "tests/"],
        id="pytest",
    ),
]


@pytest.mark.parametrize("cmd", _CHECKS)
def test_check_passes_in_container(ci_image: str, cmd: list[str]) -> None:
    """A CI check command passes when run inside the ci-stage container.

    Args:
        ci_image: Built ci-stage image fixture.
        cmd: The command to run inside the container.

    Raises:
        AssertionError: If the command exits non-zero.
    """
    result = dockerutils.run_container(ci_image, cmd)
    assert result.returncode == 0, result.stdout + result.stderr
