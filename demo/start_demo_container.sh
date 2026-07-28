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
# Starts a throwaway Docker container, reachable over SSH, staged through
# Readme.md's "Basestation source" section - so a live demo can start typing
# right at the "## Installation" heading (install uv, create the venv,
# uv sync, Chromium, login/logout scripts) instead of re-deriving everything
# from a bare box. See demo/Readme.md.
#
# Usage: demo/start_demo_container.sh [--pilot-user <user>] [--port <port>]

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
CONTAINER_NAME="basestation-demo"
PILOT_USER="demo"
PORT="2222"

log_info() { echo "[start_demo_container] $*" >&2; }
log_error() { echo "[start_demo_container] ERROR: $*" >&2; }

usage() {
    cat <<EOF
Usage: $0 [--pilot-user <user>] [--port <port>]

  --pilot-user <user>   Pilot account to create in the container (default: demo)
  --port <port>         Host port to map to the container's sshd (default: 2222)
  -h, --help             Show this help
EOF
}

while [ $# -gt 0 ]; do
    case "$1" in
        --pilot-user)
            PILOT_USER="$2"
            shift 2
            ;;
        --port)
            PORT="$2"
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

if ! command -v docker >/dev/null 2>&1; then
    log_error "docker not found on PATH"
    exit 1
fi
if ! docker info >/dev/null 2>&1; then
    log_error "docker not available (daemon not running?)"
    exit 1
fi

if docker ps -a --format '{{.Names}}' | grep -qx "$CONTAINER_NAME"; then
    log_error "container '$CONTAINER_NAME' already exists - run demo/stop_demo_container.sh first"
    exit 1
fi

CONTAINER_STARTED=0
cleanup_on_error() {
    if [ "$CONTAINER_STARTED" -eq 1 ]; then
        log_error "setup failed - removing '$CONTAINER_NAME'"
        docker rm -f "$CONTAINER_NAME" >/dev/null 2>&1 || true
    fi
}
trap cleanup_on_error ERR

log_info "starting container '$CONTAINER_NAME' (ubuntu:22.04, sshd on 127.0.0.1:$PORT)"
docker run -d --rm \
    -p "127.0.0.1:$PORT:22" \
    -v "$REPO_ROOT:/src:ro" \
    --name "$CONTAINER_NAME" \
    ubuntu:22.04 sleep infinity >/dev/null
CONTAINER_STARTED=1

log_info "installing sudo/openssh-server"
docker exec -e DEBIAN_FRONTEND=noninteractive "$CONTAINER_NAME" \
    bash -c "apt-get update -qq && apt-get install -y -qq sudo openssh-server"

log_info "creating pilot user '$PILOT_USER' (passwordless sudo - demo container only)"
docker exec "$CONTAINER_NAME" adduser --disabled-password --gecos '' "$PILOT_USER"
docker exec "$CONTAINER_NAME" adduser "$PILOT_USER" sudo
docker exec "$CONTAINER_NAME" bash -c \
    "echo '$PILOT_USER ALL=(ALL) NOPASSWD:ALL' > /etc/sudoers.d/90-demo-nopasswd && chmod 0440 /etc/sudoers.d/90-demo-nopasswd"

HOST_PUBKEY=""
for candidate in "$HOME/.ssh/id_ed25519.pub" "$HOME/.ssh/id_rsa.pub"; do
    if [ -f "$candidate" ]; then
        HOST_PUBKEY="$candidate"
        break
    fi
done

if [ -n "$HOST_PUBKEY" ]; then
    log_info "installing host public key ($HOST_PUBKEY) for '$PILOT_USER'"
    docker exec "$CONTAINER_NAME" mkdir -p "/home/$PILOT_USER/.ssh"
    docker exec -i "$CONTAINER_NAME" bash -c "cat > /home/$PILOT_USER/.ssh/authorized_keys" <"$HOST_PUBKEY"
    docker exec "$CONTAINER_NAME" bash -c \
        "chown -R $PILOT_USER:$PILOT_USER /home/$PILOT_USER/.ssh && chmod 700 /home/$PILOT_USER/.ssh && chmod 600 /home/$PILOT_USER/.ssh/authorized_keys"
    PASSWORD=""
    PW_AUTH="no"
else
    PASSWORD="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 16)"
    log_info "no host SSH public key found - falling back to a generated password"
    docker exec "$CONTAINER_NAME" bash -c "echo '$PILOT_USER:$PASSWORD' | chpasswd"
    PW_AUTH="yes"
fi

log_info "starting sshd"
docker exec "$CONTAINER_NAME" bash -c "
    mkdir -p /run/sshd
    ssh-keygen -A >/dev/null
    printf 'PermitRootLogin no\nPasswordAuthentication %s\n' '$PW_AUTH' >>/etc/ssh/sshd_config
    /usr/sbin/sshd
"

log_info "staging prerequisites (system packages, gliders group, PAM, source checkout)"
docker exec -e PILOT_USER="$PILOT_USER" -e BASESTATION_SOURCE_DIR=/src \
    "$CONTAINER_NAME" bash /src/demo/stage_prereqs.sh

trap - ERR

echo >&2
log_info "ready - connect with:"
log_info "  ssh $PILOT_USER@localhost -p $PORT"
if [ -n "$PASSWORD" ]; then
    log_info "  password: $PASSWORD"
fi
log_info "start typing at the '## Installation' heading in Readme.md (install uv, then the venv)."
log_info "tear down with: demo/stop_demo_container.sh"
