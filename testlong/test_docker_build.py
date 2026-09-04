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

"""Confirms the Dockerfile's runtime/ci stages build and are shaped as expected."""

from __future__ import annotations

import subprocess

import dockerutils


def test_runtime_image_builds(runtime_image: dockerutils.RuntimeImage) -> None:
    """Runtime image builds and can be inspected.

    Args:
        runtime_image: Built runtime-stage image fixture.

    Raises:
        AssertionError: If `docker image inspect` fails for the built tag.
    """
    result = subprocess.run(
        ["docker", "image", "inspect", runtime_image.tag],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr


def test_runtime_image_smoke_test(runtime_image: dockerutils.RuntimeImage) -> None:
    """Base.py --help runs cleanly inside the runtime image.

    Regression guard for build-context issues (e.g. a broken symlink under a
    site-local, gitignored directory like Plotting/local/ that .dockerignore
    fails to exclude) that only surface once the interpreter actually tries
    to import the full module graph - `docker image inspect` alone won't
    catch this class of bug.

    Args:
        runtime_image: Built runtime-stage image fixture.

    Raises:
        AssertionError: If Base.py --help exits non-zero.
    """
    result = dockerutils.run_container(
        runtime_image.tag,
        [".venv/bin/python", "/usr/local/basestation3/Base.py", "--help"],
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_user_is_baserunner(runtime_image: dockerutils.RuntimeImage) -> None:
    """The runtime image's default user/uid matches the build args used.

    Args:
        runtime_image: Built runtime-stage image fixture.

    Raises:
        AssertionError: If whoami/id don't match the build args used.
    """
    whoami = dockerutils.run_container(runtime_image.tag, ["whoami"])
    assert whoami.stdout.strip() == runtime_image.baserunner

    uid = dockerutils.run_container(runtime_image.tag, ["id", "-u"])
    assert uid.stdout.strip() == str(runtime_image.user_id)


def test_ci_image_builds(ci_image: str) -> None:
    """CI image builds and has the ci extras (ruff) installed.

    Args:
        ci_image: Built ci-stage image fixture.

    Raises:
        AssertionError: If the image fails to build or lacks ruff.
    """
    result = dockerutils.run_container(ci_image, ["uv", "run", "ruff", "--version"])
    assert result.returncode == 0, result.stderr


_FIND_AND_LAUNCH_CHROME = (
    'CHROME_BIN=$(find /opt/playwright-browsers -iname chrome -type f -executable '
    "| sort | tail -1); "
    'test -n "$CHROME_BIN" && "$CHROME_BIN" --headless --disable-gpu --no-sandbox '
    "--dump-dom about:blank"
)


def test_ci_image_chromium_launches(ci_image: str) -> None:
    """Chromium (installed for tests/test_MagCal.py's Playwright click-test) launches headless.

    Mirrors .github/workflows/action.yml's "Verify Chromium launches" step, so a
    future dependency bump that breaks it (e.g. a Playwright version mismatch, or
    a missing OS runtime library) fails here instead of silently degrading to a
    self-skipped click-test in CI. Independent of kaleido, which no longer needs
    a managed Chrome server - see PlotUtilsPlotly.write_output_files(). Chromium
    lives only in the ci stage now, not runtime - production images never carry
    it (see testlong/test_install_script.py::test_install_does_not_install_chromium
    for the equivalent bare-metal-install guard).

    Args:
        ci_image: Built ci-stage image fixture.

    Raises:
        AssertionError: If no Chromium executable is found, or it fails to launch.
    """
    result = dockerutils.run_container(ci_image, ["sh", "-c", _FIND_AND_LAUNCH_CHROME])
    assert result.returncode == 0, result.stdout + result.stderr


def test_runtime_image_does_not_include_chromium(
    runtime_image: dockerutils.RuntimeImage,
) -> None:
    """Runtime image must not carry Chromium/Playwright - it's a dev/CI-only concern.

    Regression guard for the split introduced when Chromium moved out of the
    shared `base` stage into `ci` only: a future edit that accidentally moves
    the `RUN uv run playwright install --with-deps chromium` step (or an
    `--extra ci` sync) back into `base`/`runtime` would silently bloat every
    production image without failing anything else.

    Args:
        runtime_image: Built runtime-stage image fixture.

    Raises:
        AssertionError: If a Chromium binary is found, or playwright imports.
    """
    find_result = dockerutils.run_container(
        runtime_image.tag,
        ["sh", "-c", "find /opt/playwright-browsers -iname chrome -type f 2>/dev/null"],
    )
    assert not find_result.stdout.strip(), (
        f"Chromium unexpectedly present: {find_result.stdout}"
    )

    import_result = dockerutils.run_container(
        runtime_image.tag, [".venv/bin/python", "-c", "import playwright"]
    )
    assert import_result.returncode != 0, (
        "playwright package unexpectedly importable in the runtime image"
    )
