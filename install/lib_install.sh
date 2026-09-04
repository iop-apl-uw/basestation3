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
# Shared functions for install_basestation.sh / update_basestation.sh.
# Not meant to be run directly - sourced by the two entrypoint scripts.
#
# Automates the manual steps documented in Readme.md's "Installation for a
# realtime basestation" section. Does NOT cover the chroot jail setup,
# Basestation2 coexistence, rawxfer/Sensors builds, external repos, modem
# setup, or Commission.py - those remain manual/advanced steps.

BASESTATION_DIR="/usr/local/basestation3"
BASESTATION_SHIM_DIR="/usr/local/basestation"
LOGIN_LOGOUT_SRC_DIR="$BASESTATION_DIR/login_logout_scripts"
VENV_DIR="/opt/basestation"
PYTHON_VERSIONS_DIR="/opt/python_versions"
GLIDERS_GROUP="gliders"
DEFAULT_SOURCE_URL="https://github.com/iop-apl-uw/basestation3.git"

log_info() { echo "[install_basestation] $*" >&2; }
log_warn() { echo "[install_basestation] WARNING: $*" >&2; }
log_error() { echo "[install_basestation] ERROR: $*" >&2; }

require_root() {
    if [ "$(id -u)" -ne 0 ]; then
        log_error "this step must be run as root (use sudo)"
        exit 1
    fi
}

require_pilot_user() {
    if [ -z "${PILOT_USER:-}" ]; then
        log_error "--pilot-user <user> is required"
        exit 1
    fi
    if ! id "$PILOT_USER" >/dev/null 2>&1; then
        log_error "user '$PILOT_USER' does not exist - create it first (e.g. sudo adduser $PILOT_USER)"
        exit 1
    fi
}

run_as_pilot() {
    sudo -u "$PILOT_USER" -H "$@"
}

install_apt_packages() {
    require_root
    log_info "installing system packages"
    # tcsh/bc/dos2unix - runtime deps for selftest.sh.
    # ca-certificates/git/curl - needed by this script itself (checkout_source,
    # and the uv installer fallback in setup_uv_venv), not just at runtime.
    # build-essential/libgeos-dev/libproj-dev - not every basestation3
    # dependency publishes a wheel for every platform (notably cartopy has no
    # linux/arm64 wheel, and arm64/Raspberry Pi is a documented deployment
    # target - see Readme.md's "System requirements" section), so uv needs a
    # compiler and the GEOS/PROJ headers to fall back to building from source.
    apt-get update
    apt-get install -y \
        tcsh bc dos2unix \
        ca-certificates git curl \
        build-essential libgeos-dev libproj-dev
}

ensure_gliders_group() {
    require_root
    if getent group "$GLIDERS_GROUP" >/dev/null; then
        log_info "group '$GLIDERS_GROUP' already exists"
    else
        log_info "creating group '$GLIDERS_GROUP'"
        addgroup "$GLIDERS_GROUP"
    fi
}

add_user_to_gliders_group() {
    require_root
    require_pilot_user
    if id -nG "$PILOT_USER" | tr ' ' '\n' | grep -qx "$GLIDERS_GROUP"; then
        log_info "'$PILOT_USER' already in group '$GLIDERS_GROUP'"
    else
        log_info "adding '$PILOT_USER' to group '$GLIDERS_GROUP'"
        adduser "$PILOT_USER" "$GLIDERS_GROUP"
    fi
}

# Comments out the pam_motd/pam_lastlog lines in /etc/pam.d/login that
# otherwise interfere with the basestation <-> Seaglider login handshake.
# Idempotent (only touches currently-uncommented lines) and takes a
# timestamped backup before editing.
patch_pam_login() {
    require_root
    local pam_file="/etc/pam.d/login"
    if [ ! -f "$pam_file" ]; then
        log_warn "$pam_file not found - skipping PAM edit"
        return 0
    fi

    local backup
    backup="${pam_file}.bak.$(date +%s)"
    cp "$pam_file" "$backup"

    sed -E -i \
        -e '/^[[:space:]]*#/!{
              s|^([[:space:]]*)(session[[:space:]]+optional[[:space:]]+pam_motd\.so[[:space:]]+motd=/run/motd\.dynamic.*)$|\1#\2|
              s|^([[:space:]]*)(session[[:space:]]+optional[[:space:]]+pam_motd\.so[[:space:]]+noupdate.*)$|\1#\2|
              s|^([[:space:]]*)(session[[:space:]]+optional[[:space:]]+pam_lastlog\.so.*)$|\1#\2|
            }' \
        "$pam_file"

    if diff -u "$backup" "$pam_file" >/tmp/pam_login.diff 2>&1; then
        log_info "$pam_file already up to date, no changes made"
        rm -f "$backup"
    else
        log_info "patched $pam_file (backup: $backup)"
        cat /tmp/pam_login.diff >&2
    fi
    rm -f /tmp/pam_login.diff
}

# mode is "install" (clone, fails if a checkout already exists) or "update"
# (git pull, fails if no checkout exists yet). Source defaults to the public
# GitHub repo; override with BASESTATION_SOURCE_DIR (a local path or another
# git remote) - used by testlong/ to validate against a local checkout
# instead of always fetching from GitHub.
checkout_source() {
    local mode="$1"
    require_root
    require_pilot_user
    local source_url="${BASESTATION_SOURCE_DIR:-$DEFAULT_SOURCE_URL}"

    case "$mode" in
        install)
            if [ -d "$BASESTATION_DIR/.git" ]; then
                log_error "$BASESTATION_DIR already has a git checkout - use update_basestation.sh"
                exit 1
            fi
            mkdir -p "$BASESTATION_DIR"
            chown "$PILOT_USER:$GLIDERS_GROUP" "$BASESTATION_DIR"
            chmod g+rx "$BASESTATION_DIR"
            log_info "cloning $source_url into $BASESTATION_DIR"
            run_as_pilot git clone "$source_url" "$BASESTATION_DIR"
            ;;
        update)
            if [ ! -d "$BASESTATION_DIR/.git" ]; then
                log_error "$BASESTATION_DIR has no git checkout - run install_basestation.sh first"
                exit 1
            fi
            log_info "pulling latest source in $BASESTATION_DIR"
            run_as_pilot git -C "$BASESTATION_DIR" pull origin master
            ;;
        *)
            log_error "checkout_source: unknown mode '$mode'"
            exit 1
            ;;
    esac
}

# Creates/refreshes the uv-managed venv at $VENV_DIR, per the "Install
# python and the basestation packages with UV" section of Readme.md. Runs
# the actual uv commands as the pilot user, since $VENV_DIR ends up owned by
# that user.
setup_uv_venv() {
    require_root
    require_pilot_user
    mkdir -p "$VENV_DIR" "$PYTHON_VERSIONS_DIR"
    chown "$PILOT_USER:$GLIDERS_GROUP" "$VENV_DIR" "$PYTHON_VERSIONS_DIR"

    # `uv venv --clear` on an already-populated venv tries to remove and
    # recreate $VENV_DIR itself, which needs write access to $VENV_DIR's
    # *parent* (typically /opt, root-owned) - something the pilot user
    # doesn't have, so it fails with "Permission denied" on every run after
    # the first (this is the "failed to remove directory ... Permission
    # denied" quirk Readme.md warns about and tells the operator to just
    # re-run past). Emptying the directory's contents here, as root, avoids
    # it deterministically: uv only needs to populate an already-empty,
    # already-correctly-owned directory, never remove/recreate it.
    if [ -d "$VENV_DIR" ]; then
        find "$VENV_DIR" -mindepth 1 -maxdepth 1 -exec rm -rf {} +
    fi

    log_info "setting up uv-managed venv at $VENV_DIR"
    run_as_pilot env \
        UV_MANAGED_PYTHON=1 \
        UV_PYTHON_INSTALL_DIR="$PYTHON_VERSIONS_DIR" \
        VENV_DIR="$VENV_DIR" \
        BASESTATION_DIR="$BASESTATION_DIR" \
        HOME="$(getent passwd "$PILOT_USER" | cut -d: -f6)" \
        bash -c '
            set -euo pipefail
            command -v uv >/dev/null 2>&1 || curl -LsSf https://astral.sh/uv/install.sh | sh
            export PATH="$HOME/.local/bin:$PATH"
            # cd into the project *before* creating the venv, so uv resolves
            # the interpreter from .python-version there - creating the venv
            # from outside the project picks whatever uv defaults to instead
            # of the pin, and uv sync then has to tear down and recreate the
            # venv to fix it, which can fail with a permission error partway
            # through (this is the "failed to remove directory /opt/basestation:
            # Permission denied" quirk Readme.md warns about).
            #
            # No --extra here: the "ci" extras group (pytest/ruff/ty/
            # playwright) is a dev/CI-only concern - production installs
            # never run the test suite or need Chromium (kaleido static
            # image export is a deprecated, low-volume path; see
            # PlotUtilsPlotly.write_output_files()).
            cd "$BASESTATION_DIR"
            uv venv --clear "$VENV_DIR"
            VIRTUAL_ENV="$VENV_DIR" uv sync --active
        '
}

# Installs (or refreshes) the login/logout shim scripts at
# $BASESTATION_SHIM_DIR. On refresh, only overwrites a script if it still
# matches the checksum recorded at install time - Readme.md tells operators
# to hand-edit these after install (e.g. adding --reply_addr), and this
# guards against silently clobbering that.
install_login_logout_scripts() {
    require_root
    require_pilot_user
    mkdir -p "$BASESTATION_SHIM_DIR"
    chown "$PILOT_USER:$GLIDERS_GROUP" "$BASESTATION_SHIM_DIR"

    local f src dst checksum_file recorded current
    for f in glider_login glider_logout; do
        src="$LOGIN_LOGOUT_SRC_DIR/$f"
        dst="$BASESTATION_SHIM_DIR/$f"
        checksum_file="$BASESTATION_SHIM_DIR/.$f.sha256"

        if [ -f "$dst" ]; then
            recorded=""
            [ -f "$checksum_file" ] && recorded="$(cat "$checksum_file")"
            current="$(sha256sum "$dst" | awk '{print $1}')"
            if [ -n "$recorded" ] && [ "$recorded" != "$current" ]; then
                log_warn "$dst was modified since install - not overwriting. Diff against the repo copy:"
                diff -u "$dst" "$src" >&2 || true
                continue
            fi
        fi

        log_info "installing $dst"
        cp "$src" "$dst"
        chown "$PILOT_USER:$GLIDERS_GROUP" "$dst"
        sha256sum "$dst" | awk '{print $1}' > "$checksum_file"
        chown "$PILOT_USER:$GLIDERS_GROUP" "$checksum_file"
    done
}

smoke_test() {
    require_pilot_user
    log_info "running smoke test: $VENV_DIR/bin/python $BASESTATION_DIR/Base.py --help"
    local out status
    set +e
    out="$(run_as_pilot "$VENV_DIR/bin/python" "$BASESTATION_DIR/Base.py" --help 2>&1)"
    status=$?
    set -e
    if [ "$status" -ne 0 ]; then
        log_error "smoke test failed (exit $status). Output:"
        printf '%s\n' "$out" | tail -n 40 >&2
        exit 1
    fi
    log_info "smoke test passed"
}
