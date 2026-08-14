#!/bin/bash
#
# Provisions the testlong/ multipass validation VM: three fake sites
# (alpha/bravo/charlie), the baserunner service account, a real `uv
# sync`'d copy of this checkout with stub Base.py/BaseLogin.py/
# GliderEarlyGPS.py swapped in, and the systemd units - but does NOT
# start baserunnermulti/baserunnerprivexec themselves. Starting/stopping
# those (and the legacy per-site unit used by the migration test) is
# left to the Python-side test fixtures, since different tests need
# different start/stop orderings (in particular the migration/rollback
# test).
#
# Expects, already transferred into the VM alongside this script:
#   ~/basestation3/          - a full checkout of this repo
#   ~/fixtures/stubs/*.py    - stub Base.py/BaseLogin.py/GliderEarlyGPS.py
#   ~/fixtures/sites.yaml
#   ~/fixtures/*.service
#
# Usage: sudo ./setup_baserunner_env.sh
#
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "Must be run as root (sudo)." >&2
    exit 1
fi

SITES=(alpha bravo charlie)
BASESTATION_DIR=/usr/local/basestation3
REAL_USER="${SUDO_USER:-ubuntu}"

echo "== Installing system dependencies =="
apt-get update -qq
# build-essential: some deps (e.g. gsw) have no prebuilt ARM64 wheel and
# need to compile from source during `uv sync`.
apt-get install -y -qq curl python3 python3-venv build-essential >/dev/null

echo
echo "== Copying checkout into ${BASESTATION_DIR} =="
rm -rf "${BASESTATION_DIR}"
cp -r "/home/${REAL_USER}/basestation3" "${BASESTATION_DIR}"
chown -R "${REAL_USER}:${REAL_USER}" "${BASESTATION_DIR}"

# A dev checkout can have personal, gitignored symlinks (e.g.
# Plotting/local/*.py -> sibling files via an absolute host path, per
# Plotting/local/.gitignore) that `multipass transfer -r` copies as
# symlinks pointing at a path that doesn't exist in this VM. A real
# clone of this repo would never have these files at all - Plotting/
# __init__.py's local-plugin loader already handles that directory
# being empty/absent, so just remove whatever didn't survive the
# transfer intact rather than trying to preserve it.
find "${BASESTATION_DIR}" -xtype l -delete

echo
echo "== Installing uv and syncing dependencies (this takes a while) =="
sudo -u "${REAL_USER}" bash -c '
    if ! command -v uv &>/dev/null; then
        curl -LsSf https://astral.sh/uv/install.sh | sh
    fi
    export PATH="$HOME/.local/bin:$PATH"
    cd '"${BASESTATION_DIR}"'
    uv sync --no-progress
'

echo
echo "== Swapping in stub Base.py/BaseLogin.py/GliderEarlyGPS.py =="
for script in Base.py BaseLogin.py GliderEarlyGPS.py; do
    cp "/home/${REAL_USER}/fixtures/stubs/${script}" "${BASESTATION_DIR}/${script}"
done

echo
echo "== Making the checkout world-readable/executable =="
chmod -R o+rX "${BASESTATION_DIR}"

# .venv/bin/python is a symlink into ~<REAL_USER>/.local/share/uv/python/...
# (uv installs the interpreter per-user, not into the venv itself) - the
# target is already world-readable/executable, but the default Ubuntu
# home directory mode (0750) blocks path traversal into it for anyone
# outside the ubuntu group, which baserunner is not. Only add the
# traversal bit ("x"), not "r" - no need to make the rest of the home
# directory listable/readable for this.
chmod o+x "/home/${REAL_USER}"

echo
echo "== Creating baserunner account =="
if ! id baserunner &>/dev/null; then
    useradd --system --no-create-home --shell /usr/sbin/nologin baserunner
fi

echo
echo "== Creating fake sites =="
for site in "${SITES[@]}"; do
    user="runner-${site}"
    if ! getent group "${site}" &>/dev/null; then
        groupadd --system "${site}"
    fi
    if ! id "${user}" &>/dev/null; then
        useradd --system --no-create-home --shell /usr/sbin/nologin --gid "${site}" "${user}"
    fi
    usermod -aG "${site}" baserunner

    jaildir="/home/jails/${site}/gliderjail/home/rundir"
    mkdir -p "${jaildir}"
    chown -R "${user}:${site}" "/home/jails/${site}"
    chmod -R g+rwx "/home/jails/${site}"
    chmod o-rwx "/home/jails/${site}"
    # setgid on every directory (not files - setgid means something
    # different, and unwanted, on a regular file) so new files/dirs
    # created anywhere under here - by whichever account - inherit this
    # site's group automatically, the same way a real glider_login
    # writing a .run file relies on.
    find "/home/jails/${site}" -type d -exec chmod g+s {} +
done

echo
echo "== Installing sites.yaml =="
mkdir -p "${BASESTATION_DIR}/etc"
cp "/home/${REAL_USER}/fixtures/sites.yaml" "${BASESTATION_DIR}/etc/sites.yaml"

echo
echo "== Pre-creating log files owned by baserunner (parent dir /var/log isn't writable by it) =="
touch /var/log/baserunnermulti.log /var/log/baserunner-privexec.log
chown baserunner:baserunner /var/log/baserunnermulti.log /var/log/baserunner-privexec.log

echo
echo "== Installing systemd units =="
cp "/home/${REAL_USER}/fixtures/baserunnermulti.service" /etc/systemd/system/
cp "/home/${REAL_USER}/fixtures/baserunnerprivexec.service" /etc/systemd/system/
cp "/home/${REAL_USER}/fixtures/baserunner-legacy@.service" /etc/systemd/system/
systemctl daemon-reload

echo
echo "Fixture environment ready. Sites: ${SITES[*]}"
echo "Nothing has been started yet - that's left to the test fixtures."
