#!/usr/bin/env bash
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
#
# Run as root inside the demo container by start_demo_container.sh. Stages
# everything install_basestation.sh does *before* Readme.md's
# "## Installation" heading - system packages, the gliders group, the PAM
# login edit, and the /usr/local/basestation3 checkout - by calling the same
# lib_install.sh functions install_basestation.sh itself uses, so the demo's
# "before" state can't drift from the real install path.
#
# Deliberately stops there: does NOT call setup_uv_venv,
# install_playwright_chromium, configure_browser_path_hook, or
# install_login_logout_scripts - those are the steps the live demo walks
# through by hand from "## Installation" onward.
#
# Expects PILOT_USER (pilot account, already created) and
# BASESTATION_SOURCE_DIR (path/URL checkout_source clones from - typically
# the read-only repo bind mount at /src) in the environment.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=../install/lib_install.sh
source "$SCRIPT_DIR/../install/lib_install.sh"

require_root
require_pilot_user

install_apt_packages
ensure_gliders_group
add_user_to_gliders_group
patch_pam_login
checkout_source install

log_info "prereqs staged - /usr/local/basestation3 checked out for '$PILOT_USER', ready for the '## Installation' walkthrough"
