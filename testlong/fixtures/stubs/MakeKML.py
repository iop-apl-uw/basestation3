#!/usr/bin/env python3
"""Stub stand-in for MakeKML.py, used only by testlong's multipass
validation VM - NOT real KML generation.

MakeKMLSSHMissions.py (--mergessh) shells out to MakeKML.py from each site's
child; this records that grandchild's identity to
<mission_dir>/makekml_stub.json so test_multipass_makekml_ssh.py can check
the runner identity (and nothing more) carried through the shell and exec.
"""

import argparse
import json
import pathlib
import sys

# ssh/MakeKMLSSH.py is swapped for its stub by the same test, which exports
# the shared identity snapshot.
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent / "ssh"))
from MakeKMLSSH import process_identity  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mission_dir", required=True)
    args, _unknown = parser.parse_known_args()
    out = pathlib.Path(args.mission_dir) / "makekml_stub.json"
    out.write_text(json.dumps(process_identity()))
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
