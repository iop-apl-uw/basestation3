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

"""FlightModel run after each dive arrives, as in a live mission, compared with one batch run.

The other FlightModel tests hand a run every dive at once; a mission runs FM once per glider
call, with the flight database (restart cache, volmax, abs_compress) carried between runs.
"""

import logging
import os
import pickle
import shutil
import time
from pathlib import Path

import pytest

import Base
import BaseLog
import BaseNetCDF
import FlightModel
import FlightModelCLI
import Sensors

DATA_DIR = Path("testdata/sg561_provolo_lofoten_may2016_dive2on")
DIVES = (2, 3, 4, 5)
FM_VALUES = ("hd_a", "hd_b", "volmax", "vbdbias", "abs_compress")
EARLIER_THAN_EVERY = "is earlier than every dive in the flight database"


def _new_mission(mission_dir: Path) -> None:
    """An empty sg561 mission: comm.log and sg_calib_constants.m, no dives yet."""
    mission_dir.mkdir(parents=True)
    for name in ("comm.log", "sg_calib_constants.m"):
        shutil.copy2(DATA_DIR / name, mission_dir / name)


def _arrive(mission_dir: Path, dive_nums: list[int]) -> None:
    """The dives' .log, .eng and .nc land in the mission directory."""
    for dive_num in dive_nums:
        for f in DATA_DIR.glob(f"p561{dive_num:04d}.*"):
            shutil.copy2(f, mission_dir / f.name)


def _reset_module_state() -> None:
    """Fresh module state, as a new Base.py process would have (as testutils.run_mission does)."""
    os.environ["TZ"] = "UTC"
    time.tzset()
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()
    Base.set_globals()
    BaseLog.BaseLogger.reset()


def _run_fm(
    mission_dir: Path, caplog: pytest.LogCaptureFixture
) -> list[logging.LogRecord]:
    """One FlightModel run, as after a glider call.

    Returns:
        The WARNING and above records of the run
    """
    _reset_module_state()
    caplog.clear()
    with caplog.at_level(logging.INFO):
        assert (
            FlightModelCLI.main(["--verbose", "--mission_dir", str(mission_dir)]) == 0
        )
    return [r for r in caplog.records if r.levelno >= logging.WARNING]


def _flight_db(mission_dir: Path) -> dict:
    with (mission_dir / "flight" / "flight.pkl").open("rb") as fi:
        return pickle.load(fi)


def _fm_values(db: dict) -> dict[int | str, dict[str, float]]:
    """Each dive's FM values, and the mission-wide ones under "mission"."""
    values: dict[int | str, dict[str, float]] = {
        d: {v: float(getattr(db[d], v)) for v in FM_VALUES} for d in DIVES
    }
    values["mission"] = {v: float(db[v]) for v in ("volmax", "abs_compress")}
    return values


@pytest.fixture(scope="module")
def batch_values(
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[int | str, dict[str, float]]:
    """FM values from one run over all the dives."""
    mission_dir = tmp_path_factory.mktemp("batch") / "mission_dir"
    _new_mission(mission_dir)
    _arrive(mission_dir, list(DIVES))
    _reset_module_state()
    assert FlightModelCLI.main(["--verbose", "--mission_dir", str(mission_dir)]) == 0
    return _fm_values(_flight_db(mission_dir))


@pytest.mark.parametrize(
    "arrivals",
    [
        [2, 3, 4, 5],
        [2, 4, 3, 5],  # a late dive with an earlier dive in the database
        [
            3,
            4,
            2,
            5,
        ],  # a late dive earlier than every dive in the database (sg175 TasmanX, 2026-11)
    ],
    ids=["in_order", "swapped", "before_first"],
)
def test_fm_after_each_dive(
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    batch_values: dict[int | str, dict[str, float]],
    arrivals: list[int],
) -> None:
    """FM runs cleanly after every arrival and ends where a batch run does."""
    mission_dir = tmp_path / "mission_dir"
    _new_mission(mission_dir)
    earlier_than_every = None
    for n, dive_num in enumerate(arrivals, 1):
        _arrive(mission_dir, [dive_num])
        problems = _run_fm(mission_dir, caplog)
        if dive_num < min(arrivals[: n - 1], default=dive_num):
            earlier_than_every = dive_num
            # the only warning; BaseLog prefixes the File.py(line)
            assert len(problems) == 1, [r.getMessage() for r in problems]
            assert (
                problems[0]
                .getMessage()
                .endswith(
                    f"Dive {dive_num} {EARLIER_THAN_EVERY} (first {min(arrivals[: n - 1])}) - starting it"
                    " from the defaults and recomputing the later dives"
                )
            )
        else:
            assert not problems, [r.getMessage() for r in problems]
        db_dives = {d for d in _flight_db(mission_dir) if isinstance(d, int)}
        assert db_dives == set(arrivals[:n])  # every dive so far, none left "new"

    values = _fm_values(_flight_db(mission_dir))
    if earlier_than_every is None:
        # Arrival order doesn't matter as long as some dive came before
        for key, want in batch_values.items():
            assert values[key] == pytest.approx(want, rel=1e-9), key
        return
    # The flight solution and the mission-wide abs_compress match.  The initial volmax estimate
    # comes from the first dive the database saw (dive 3 here, not 2), so volmax and each dive's
    # vbdbias/abs_compress, solved together against it, differ a little: for this fixture volmax
    # 0.05cc, vbdbias < 0.4cc, abs_compress up to 6% (dive 3, the database's first).  In a longer
    # mission the final-volmax adjustment (early_volmax_adjust dives) brings volmax together.
    assert values["mission"]["abs_compress"] == pytest.approx(
        batch_values["mission"]["abs_compress"], rel=1e-9
    )
    assert values["mission"]["volmax"] == pytest.approx(
        batch_values["mission"]["volmax"], abs=1.0
    )
    for dive_num in DIVES:
        got, want = values[dive_num], batch_values[dive_num]
        assert got["hd_a"] == pytest.approx(want["hd_a"], rel=1e-9), dive_num
        assert got["hd_b"] == pytest.approx(want["hd_b"], rel=1e-9), dive_num
        assert got["volmax"] == pytest.approx(want["volmax"], abs=1.0), dive_num
        assert got["vbdbias"] == pytest.approx(want["vbdbias"], abs=1.0), dive_num
        assert got["abs_compress"] == pytest.approx(want["abs_compress"], rel=0.1), (
            dive_num
        )
