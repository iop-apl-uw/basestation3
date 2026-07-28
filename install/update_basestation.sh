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
# Updates an existing realtime basestation3 install: pulls the latest
# source, re-syncs the uv venv, re-checks Chromium (needed by kaleido for
# static plot image export - a no-op if already installed at the pinned
# version), and refreshes the login/logout scripts (if they haven't been
# hand-edited since install). Does NOT repeat the one-time system package /
# gliders group / PAM steps - see install_basestation.sh for a fresh
# install.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=lib_install.sh
source "$SCRIPT_DIR/lib_install.sh"

usage() {
    cat <<EOF
Usage: sudo $0 --pilot-user <user>

  --pilot-user <user>   Unix account that owns the existing basestation
                         checkout and venv.
  -h, --help             Show this help
EOF
}

PILOT_USER=""
while [ $# -gt 0 ]; do
    case "$1" in
        --pilot-user)
            PILOT_USER="$2"
            shift 2
            ;;
        -h | --help)
            usage
            exit 0
            ;;
        *)
            echo "unknown argument: $1" >&2
            usage
            exit 1
            ;;
    esac
done

require_root
require_pilot_user

log_info "skipping system package install (update mode)"
log_info "skipping gliders group setup (update mode)"
log_info "skipping PAM login edit (update mode)"

checkout_source update
setup_uv_venv
install_playwright_chromium
configure_browser_path_hook
install_login_logout_scripts
smoke_test

log_info "basestation3 updated successfully for pilot user '$PILOT_USER'"
