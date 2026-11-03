# -*- python-fmt -*-

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


"""tools/ run as scripts: exit statuses, DEBUG_PDB defaults, CorrectSciconTime's climb correction."""

import pathlib
import shutil
import subprocess
import sys
import time
import types

import numpy as np
import pytest

TOOLS = pathlib.Path(__file__).resolve().parent.parent / "tools"
sys.path.insert(0, str(TOOLS))
import CorrectSciconTime  # noqa: E402  # ty: ignore[unresolved-import]

TESTDATA = pathlib.Path(__file__).resolve().parent.parent / "testdata"


def _run(
    tool: str, args: list[str], cwd: pathlib.Path | None = None
) -> subprocess.CompletedProcess:
    """Runs a tool as a script (stdin closed, so a stray pdb prompt can't hang the test)."""
    return subprocess.run(
        [sys.executable, str(TOOLS / tool), *args],
        capture_output=True,
        text=True,
        check=False,
        cwd=cwd,
        stdin=subprocess.DEVNULL,
        timeout=300,
        env={"TZ": "UTC", "PATH": "/usr/bin:/bin"},
    )


@pytest.mark.parametrize(
    ("required", "exit_code"),
    [(True, 0), (False, 1)],
    ids=["required files", "missing comm.log"],
)
def test_convert_from_cfcard_exit_status(
    tmp_path: pathlib.Path, required: bool, exit_code: int
) -> None:
    """1 when a required file is missing, 0 after converting (they were the other way round)."""
    (tmp_path / "sg_calib_constants.m").touch()
    if required:
        (tmp_path / "comm.log").touch()
    (tmp_path / "SG0001DZ.X").touch()
    ret = _run("convert_from_cfcard.py", [], cwd=tmp_path)
    assert ret.returncode == exit_code, ret.stdout + ret.stderr
    # By listed name - the file system may be case-insensitive
    assert ("sg0001dz.x" in [p.name for p in tmp_path.iterdir()]) is required


def test_arrivaltime_needs_two_dives(tmp_path: pathlib.Path) -> None:
    """One dive: a message and exit 1 (it raised TypeError, and every exit was 0)."""
    shutil.copy(TESTDATA / "sg686_Shilshole_28Oct25" / "p6860005.nc", tmp_path)
    ret = _run("ArrivalTime.py", ["--mission_dir", str(tmp_path)])
    assert ret.returncode == 1, ret.stdout + ret.stderr
    assert "Need at least two dives" in ret.stdout
    assert "Exception in main" not in ret.stderr


def test_arrivaltime_missing_dir_exits_1(tmp_path: pathlib.Path) -> None:
    ret = _run("ArrivalTime.py", ["--mission_dir", str(tmp_path / "nowhere")])
    assert ret.returncode == 1
    assert "does not exists" in ret.stdout


def test_arrivaltime_import_does_not_run_main() -> None:
    """Importing the module doesn't parse the command line (main ran at import)."""
    ret = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys; sys.path.insert(0, {str(TOOLS)!r}); import ArrivalTime",
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    assert ret.returncode == 0
    assert "usage:" not in ret.stderr + ret.stdout


def test_sectiontimes_exit_status_no_sections(tmp_path: pathlib.Path) -> None:
    """No sections.yml: main's 1 is the exit status (it always exited 0)."""
    shutil.copy(TESTDATA / "sg686_Shilshole_25Oct25_multidive" / "comm.log", tmp_path)
    ret = _run("SectionTimes.py", ["--mission_dir", str(tmp_path)])
    assert ret.returncode == 1, ret.stdout + ret.stderr


def test_extratargets_debug_pdb_off_by_default() -> None:
    """DEBUG_PDB comes from --debug_pdb (it defaulted to True, so any error opened pdb)."""
    import ExtraTargetsAlongLine  # ty: ignore[unresolved-import]

    assert ExtraTargetsAlongLine.DEBUG_PDB is False


def test_correctscicontime_climb_without_start_time() -> None:
    """No <instr>_starttime_b: the dive is corrected, the climb skipped (it raised TypeError and returned 1)."""
    t0 = 1_700_000_000.0
    log_f = types.SimpleNamespace(
        gc_state_data={
            "state": [0, 5, 2, 14],
            "secs": [t0 + 10, t0 + 100, t0 + 110, t0 + 200],
        }
    )
    eng_f = types.SimpleNamespace(start_ts=time.gmtime(t0))
    legato_time = np.array([t0 + 10, t0 + 30, t0 + 50, t0 + 300, t0 + 320])
    results_d = {
        "legato_time": legato_time.copy(),
        "legato_starttime_a": t0 + 10,
        "legato_stoptime_a": t0 + 50,
        "legato_stoptime_b": t0 + 320,
    }
    ret = CorrectSciconTime.main(
        base_opts=types.SimpleNamespace(debug_pdb=False),
        nc_dive_file_name="p0010001.nc",
        stats=0,
        globals_d={},
        log_f=log_f,
        eng_f=eng_f,
        results_d=results_d,
    )
    assert ret == 0
    # Dive half rescaled onto the apogee time (start 10 s, apogee 100 s: x 90/40); climb half untouched
    np.testing.assert_allclose(
        results_d["legato_time"][:3], [t0 + 10, t0 + 55, t0 + 100]
    )
    np.testing.assert_array_equal(results_d["legato_time"][3:], legato_time[3:])
