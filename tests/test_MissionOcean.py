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


"""adcp's MissionOcean.py (mission_oceanvelocityprofile, the ADCP section plots) end to end.

The basestation-specific parts of the adcp repo are tested here. Skipped when the
adcp extension isn't installed (Plotting/local/MissionOcean.py and
BaseADCPMission.py in etc/.extensions) - e.g. in the CI pipeline.

testdata/sg171_EKAMSAT_Apr24 (per-dive .nc files with ADCP data, dives 100-109) is
reprocessed once: Reprocess writes sg_calib_constants.m, loads the mission database
(the plot needs its dives table) and, through BaseADCPMission, builds the ADCP
profile timeseries the plot reads. The fixture has no comm.log, so BasePlot is
given --instrument_id.
"""

import logging
import pathlib

import pytest
import testutils

import Base  # noqa: F401 - normal import order
import BaseLog
import BaseNetCDF
import BasePlot
import FlightModel
import Plotting
import Reprocess
import Sensors

PLOT = "mission_oceanvelocityprofile"
PLOT_FILES = ("sg_ad2cp_inv_profile_section_000.webp", "sg_ad2cp_inv_profile_section_000.div")
SECTIONS = """\
defaults:
  top: 0
  bottom: 990
  bin: 5
  step: 1
variables:
  temperature: {colormap: thermal}
adcp_variables:
  ad2cp_inv_profile_vocn: {colormap: balance, top: 0, bottom: 500}
sections:
  "000": {start: 100, stop: -1}
"""


def _adcp_installed() -> str | None:
    """Why the adcp mission plot can't be tested here, or None if it can."""
    if PLOT not in Plotting.mission_plot_funcs:
        return f"{PLOT} isn't registered (no Plotting/local/MissionOcean.py from the adcp extension)"
    extensions = pathlib.Path.cwd() / "etc/.extensions"
    if not extensions.exists():
        return f"{extensions} does not exist"
    lines = [line for line in extensions.read_text().splitlines() if not line.startswith("#")]
    if not any("BaseADCPMission.py" in line for line in lines):
        return f"BaseADCPMission.py not installed in {extensions}"
    return None


pytestmark = pytest.mark.skipif(_adcp_installed() is not None, reason=str(_adcp_installed()))


@pytest.fixture(scope="module")
def reprocessed(tmp_path_factory: pytest.TempPathFactory) -> pathlib.Path:
    """sg171 dives 100-109 reprocessed: database, sg_calib_constants.m and the ADCP profile timeseries."""
    mission_dir = tmp_path_factory.mktemp("mission_ocean") / "mission_dir"
    testutils.run_mission(
        pathlib.Path("testdata/sg171_EKAMSAT_Apr24"),
        mission_dir,
        Reprocess.main,
        ["--verbose", "--mission_dir", str(mission_dir), "--skip_flight_model", "--force", "100:109"],
        _NoCaplog(),
        [""],
    )
    assert next(mission_dir.glob("*_adcp_profile_timeseries.nc"), None) is not None
    return mission_dir


class _NoCaplog:
    """run_mission wants a caplog; the module-scoped setup has none (its checks are the assert above)."""

    records: list = []


def _plot(mission_dir: pathlib.Path, sections: str) -> None:
    """Writes sections.yml, clears earlier plots and runs just this mission plot, as BasePlot would."""
    (mission_dir / "sections.yml").write_text(sections)
    for name in PLOT_FILES:
        (mission_dir / "plots" / name).unlink(missing_ok=True)
    Sensors.set_globals()
    BaseNetCDF.set_globals()
    FlightModel.set_globals()
    Base.set_globals()
    BaseLog.BaseLogger.reset()
    rc = BasePlot.main(
        ["--verbose", "--mission_dir", str(mission_dir), "--plot_types", "mission", "--mission_plots", PLOT,
         "--instrument_id", "171"]
    )  # fmt: skip
    assert rc == 0


def _drawn(mission_dir: pathlib.Path) -> bool:
    return all((mission_dir / "plots" / name).exists() for name in PLOT_FILES)


def test_draws_the_adcp_section(reprocessed: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level(logging.WARNING):
        _plot(reprocessed, SECTIONS)
    assert _drawn(reprocessed)
    assert "SECTIONS_CONFIG" not in BaseLog.log_alerts()
    assert not [r for r in caplog.records if r.levelname in ("ERROR", "CRITICAL")]


def test_bad_adcp_entry_warned_and_left_out(reprocessed: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """A bad key in adcp_variables is reported (SECTIONS_CONFIG) and ignored; the plot is still drawn."""
    with caplog.at_level(logging.WARNING):
        _plot(reprocessed, SECTIONS.replace("bottom: 500}", "bottom: 500, colour: red, step: 0}"))
    assert _drawn(reprocessed)
    alerts = BaseLog.log_alerts()["SECTIONS_CONFIG"]
    assert len(alerts) == 2
    assert any("adcp_variables.ad2cp_inv_profile_vocn.colour: Extra inputs are not permitted" in a for a in alerts)
    assert any("adcp_variables.ad2cp_inv_profile_vocn.step: Input should be greater than or equal to 1" in a for a in alerts)


def test_shared_problems_left_to_mission_profiles(reprocessed: pathlib.Path) -> None:
    """Problems in defaults/variables/sections aren't reported by the adcp plot (mission_profiles reports them)."""
    _plot(reprocessed, SECTIONS.replace("step: 1", "step: 1\n  colormap: dense_r").replace("{colormap: thermal}", "{bogus: 1}"))
    assert _drawn(reprocessed)
    assert "SECTIONS_CONFIG" not in BaseLog.log_alerts()


def test_no_adcp_variables_no_plot(reprocessed: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Without adcp_variables there's no ADCP plot - an info line, no alert (most missions have no ADCP)."""
    without = "".join(line + "\n" for line in SECTIONS.splitlines() if "adcp" not in line)
    with caplog.at_level(logging.INFO):
        _plot(reprocessed, without)
    assert not _drawn(reprocessed)
    assert "No 'adcp_variables' key found" in caplog.text and "SECTIONS_CONFIG" not in BaseLog.log_alerts()


def test_unusable_file_no_plot_no_alert(reprocessed: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """A file that can't be used: a warning here, no alert (mission_profiles alerts on the same file)."""
    with caplog.at_level(logging.WARNING):
        _plot(reprocessed, "- not a mapping\n")
    assert not _drawn(reprocessed)
    assert "no ADCP section plots" in caplog.text and "SECTIONS_CONFIG" not in BaseLog.log_alerts()
