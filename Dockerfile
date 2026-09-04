# syntax=docker/dockerfile:1
## Copyright (c) 2023, 2024, 2026  University of Washington.
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
#
# Multi-stage build, aligned with the uv-based toolchain used by
# .github/workflows/action.yml and the Makefile (see .python-version /
# pyproject.toml / uv.lock for the pinned interpreter and dependencies).
#
# Stages:
#   base    - shared foundation: system packages, uv, python, synced deps
#   runtime - (default target) the container used to run the basestation
#             conversions from BaseRunner.py.  Not well tested and highly
#             experimental.
#   ci      - runtime deps plus the "ci" extra (pytest/ruff/ty/playwright) and
#             Chromium (needed by kaleido's static-image-export smoke test
#             and tests/test_MagCal.py's browser-click test - not needed by
#             runtime, which never manages a Chrome server), used to run
#             lint/typecheck/tests inside a container - see testlong/.
#
# Known Issues (runtime stage):
#  .pagers/pagers.yml
#       URL/web based notifiers (nfty for example) work
#       smtp based untested
#  .ftp - untested
#  .mailer - untested
#  .urls - untested but should work
#
# - vis notifications not working from inside the container.
#
# To Build:
# docker build -t basestation:latest --target runtime --build-arg USER_ID=$(id BASERUNNER -u) --build-arg GROUP_ID=$(id BASERUNNER -g) --build-arg BASERUNNER=BASERUNNER .
# docker build -t basestation:ci --target ci .
#
# where BASERUNNER is the account name for the baserunner account (usually runner-glider)
#
# Due to docker caching, to ensure you get the latest, add the --no-cache option to the above
# or run
# docker system prune -f
# to clear the cache
#
# Here is a typical launch of BaseRunner.py:
# /opt/basestation/bin/python BaseRunner.py --docker_image basestation:latest --use_docker_basestation --verbose /home/rundir
#
# To run the lint/typecheck/test suite the same way CI does, inside a container:
# docker run --rm basestation:ci uv run ruff check
# docker run --rm basestation:ci uv run ty check
# docker run --rm basestation:ci uv run pytest -rsx --cov --cov-report term-missing tests/
#

FROM ubuntu:22.04 AS base

ENV DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get -y dist-upgrade
# Runtime dependencies for selftest.sh (tcsh itself, plus bc and dos2unix which
# it shells out to, and ca-certificates for uv/pip TLS) - none are part of a
# minimal Ubuntu install
RUN apt-get install -y tcsh bc dos2unix ca-certificates
# A compiler toolchain plus the GEOS/PROJ headers shapely/cartopy bind
# against. Kept even though CI (x86_64 GitHub runners) installs prebuilt
# wheels for everything, because not every dependency publishes a wheel for
# every platform this image is built on - notably cartopy has no linux/arm64
# wheel, and arm64 (e.g. Raspberry Pi 4) is a documented deployment target
# (see Readme.md's "System requirements" section) where uv falls back to
# building it from source.
RUN apt-get install -y build-essential libgeos-dev libproj-dev

# uv - pinned to match the version installed by astral-sh/setup-uv in
# .github/workflows/action.yml, so the Docker and CI toolchains can't drift
COPY --from=ghcr.io/astral-sh/uv:0.11.28 /uv /uvx /usr/local/bin/

ENV UV_MANAGED_PYTHON=1
ENV UV_PYTHON_INSTALL_DIR=/opt/python_versions

WORKDIR /usr/local/basestation3

# Install the pinned python version and base dependencies before copying in
# the rest of the source, so this layer stays cached across ordinary source
# edits. ctd_sampling is a uv workspace member (see [tool.uv.workspace] in
# pyproject.toml) installed in editable mode, so uv needs its build inputs
# (pyproject.toml/Readme.md/src) on disk too - just not its tests/fixtures,
# which change independently and aren't needed to resolve/build the package.
COPY pyproject.toml uv.lock .python-version ./
COPY ctd_sampling/pyproject.toml ctd_sampling/Readme.md ./ctd_sampling/
COPY ctd_sampling/src ./ctd_sampling/src
RUN uv python install
RUN uv sync --locked --no-install-project

# Bring in the actual build context (replaces the previous "git clone master
# from GitHub", so the image reflects the checkout being built/tested rather
# than always fetching HEAD of master)
COPY . .
RUN uv sync --locked

FROM base AS runtime

ARG USER_ID
ARG GROUP_ID
ARG BASERUNNER

RUN addgroup --gid $GROUP_ID $BASERUNNER
RUN adduser --disabled-password --gecos '' --uid $USER_ID --gid $GROUP_ID $BASERUNNER

USER $BASERUNNER

FROM base AS ci

RUN uv sync --locked --extra ci

# World-readable/executable so the container's non-root users can still
# launch the browser - matches the /opt/playwright-browsers convention used
# by .github/workflows/action.yml.
ENV PLAYWRIGHT_BROWSERS_PATH=/opt/playwright-browsers

# kaleido (used for static plot image export - png/jpg/webp/svg) needs an
# externally supplied Chromium as of kaleido>=1.0, and
# tests/test_MagCal.py's browser-click test launches its own Chromium
# session directly; playwright (a ci-extra dependency, synced above)
# provides and manages it. --with-deps also installs the OS-level libraries
# Chromium needs to actually launch (nss, atk, etc.) - left to playwright to
# resolve rather than hand-listing packages, since the exact package
# names/versions differ across Ubuntu releases (e.g. the *t64 suffix on
# 24.04, which this 22.04-based image doesn't use).
RUN uv run playwright install --with-deps chromium
RUN chmod -R o+rx "$PLAYWRIGHT_BROWSERS_PATH"

# kaleido's Chrome discovery does not pick up PLAYWRIGHT_BROWSERS_PATH on its
# own - it needs BROWSER_PATH pointed at the actual chrome binary. Resolving
# and exporting that as a plain environment variable doesn't work here: this
# stage execs `.venv/bin/python`/`uv run` directly (no login shell, no
# systemd EnvironmentFile), so nothing would ever source it. Instead, add a
# sitecustomize.py hook (same approach Readme.md's "Installing Chromium"
# section documents for a bare-metal dev setup): it runs at Python
# interpreter startup regardless of how the interpreter was invoked, so it
# works uniformly here too.
RUN CHROME_BIN=$(find "$PLAYWRIGHT_BROWSERS_PATH" -iname chrome -type f -executable | sort | tail -1) && \
    test -n "$CHROME_BIN" && \
    SITE_PACKAGES=$(.venv/bin/python3 -c 'import site; print(site.getsitepackages()[0])') && \
    printf 'import os\nos.environ.setdefault("BROWSER_PATH", "%s")\n' "$CHROME_BIN" >> "$SITE_PACKAGES/sitecustomize.py"
