#!/usr/bin/env python3
"""Stub stand-in for ssh/MakeKMLSSH.py, used only by testlong's multipass
validation VM - NOT real SSH contouring (that needs real Copernicus data).

make_kml writes a fake KMZ into the mission directory whose content is the
identity the calling process ran with, so
test_multipass_makekml_ssh.py can check both who owns the file and which
uid/gid/groups/capabilities MakeKMLSSHMissions.py's per-site child had.
"""

import json
import os
import pathlib


def process_identity() -> dict:
    """Snapshot of this process's identity, environment and capability sets.

    Returns:
        uid/euid/gid/egid, sorted supplementary groups, HOME/MPLCONFIGDIR,
        and the CapPrm/CapEff/CapAmb/CapInh masks from /proc/self/status
        as ints.
    """
    caps = {}
    for line in pathlib.Path("/proc/self/status").read_text().splitlines():
        key, _, value = line.partition(":")
        if key in ("CapInh", "CapPrm", "CapEff", "CapAmb"):
            caps[key] = int(value.strip(), 16)
    return {
        "uid": os.getuid(),
        "euid": os.geteuid(),
        "gid": os.getgid(),
        "egid": os.getegid(),
        "groups": sorted(os.getgroups()),
        "home": os.environ.get("HOME"),
        "mplconfigdir": os.environ.get("MPLCONFIGDIR"),
        **caps,
    }


def make_kml(data_dir, mission_dir, sg_plot_constants, instrument_id=None, fetch_ssh=False):
    """Writes <mission_dir>/sgNNN_ssh.kmz containing process_identity() as JSON.

    Returns:
        The written file's path, as the real make_kml returns its KMZ path.
    """
    kmz = pathlib.Path(mission_dir) / f"sg{instrument_id:03d}_ssh.kmz"
    kmz.write_text(json.dumps(process_identity()))
    return str(kmz)
