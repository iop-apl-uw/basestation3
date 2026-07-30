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

"""Regression tests for Plotting/DiveSBE43.py dive/climb splitting across the
three SBE43 oxygen sensor hardware paths (gpctd, eng/truck, scicon), and for
the Sensors/sbe43_ext.py zero-frequency QC gap.
"""

import pathlib

import numpy as np
import pytest
import testutils

import Base
import BaseOpts
import QC
import Utils
from Plotting.DiveSBE43 import plot_sbe43

# Each sensor path lands sbe43_dissolved_oxygen on a different netCDF
# dimension/time grid (see Sensors/sbe43_ext.py:sensor_data_processing):
#   gpctd  -> ctd_data_point
#   truck  -> sg_data_point (eng_sbe43_O2Freq)
#   scicon -> sbe43_data_point (sbe43_time/sbe43_o2Freq)
test_cases = (
    (
        "sg525_RMH0726_sbe43_gpctd",
        "p5350003",
        [
            "Missing metadata for log entry $PC_",
            "not a gzipped file/file too short",
            "Problem gzip decompressing",
            "Could not process pc0004bz",
            "Engineering data ends at",
            "Large mis-match between predicted and observed w",
            "Missing metadata for sg_cal_",
            "Dive [4] failed to process completely",
        ],
    ),
    (
        "sg512_PacIOOS_sbe43_truck",
        "p5120002",
        [
            "Unknown nc metadata for",
            "Missing metadata for sg_cal_",
            "Ignoring temperature frequency limits",
            "Ignoring conductivity frequency limits",
            "Substantial unmodeled flight time",
            "Unknown result variable",
        ],
    ),
    (
        "sg160_sbe43_scicon",
        "p1600001",
        [
            "value ignored. v3 Flight Model does not use this value",
            "Found Disconnect with no previous Connected",
            "timeout(s) seen in",
            "Ignoring temperature frequency limits",
            "Ignoring conductivity frequency limits",
            "Substantial unmodeled flight time",
            "Large mis-match between predicted and observed w",
            "Missing metadata for sg_cal_",
        ],
    ),
)


def _assert_leg_trend(depth: np.ndarray, increasing: bool) -> None:
    """Checks that depth generally trends the right way across a dive/climb leg.

    Args:
        depth: depth values (meters) for one leg, in time order.
        increasing: True for a dive leg (expected to deepen), False for a
            climb leg (expected to shoal).

    Raises:
        AssertionError: if the start/end quartile means don't trend as expected.
    """
    quarter = max(1, len(depth) // 4)
    start_mean = float(np.mean(depth[:quarter]))
    end_mean = float(np.mean(depth[-quarter:]))
    if increasing:
        assert start_mean < end_mean
    else:
        assert start_mean > end_mean


@pytest.mark.parametrize("data_dir_name,dive_base,allowed_msgs", test_cases)
def test_sbe43_dive_climb_alignment(caplog, data_dir_name, dive_base, allowed_msgs):
    """Builds a mission to netCDF via the real pipeline and checks that
    plot_sbe43()'s dive/climb traces have matching, correctly-aligned x/y data
    for each SBE43 sensor hardware path.
    """
    data_dir = pathlib.Path("testdata").joinpath(data_dir_name)
    mission_dir = data_dir.joinpath("mission_dir")

    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--plot_types",
        "dives",
        "--dive_plots",
        "plot_sbe43",
    ]

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        cmd_line,
        caplog,
        allowed_msgs,
    )

    dive_number = int(dive_base[-4:])
    assert (mission_dir / "plots" / f"dv{dive_number:04d}_sbe43.div").exists()

    base_opts = BaseOpts.BaseOptions(
        "", cmdline_args=["-m", str(mission_dir)], calling_module="BasePlot"
    )
    ncf = Utils.open_netcdf_file(
        str(mission_dir / f"{dive_base}.nc"), mask_results=False
    )
    figs, _ = plot_sbe43(base_opts, ncf, generate_plots=True, dbcon=None)
    ncf.close()

    traces_by_name = {trace.name: trace for trace in figs[0].data}
    for leg, deepening in (("dive", True), ("climb", False)):
        for series in ("Corrected O2", "Sat O2"):
            name = next(
                n for n in traces_by_name if n.startswith(f"{series} {leg}")
            )
            trace = traces_by_name[name]
            # The original bug: mismatched-length x/y arrays, silently
            # truncated to the shorter one by Plotly.js.
            assert len(trace.x) == len(trace.y) > 0
            _assert_leg_trend(np.asarray(trace.y), increasing=deepening)


def test_sbe43_zero_frequency_marked_unsampled(caplog):
    """Dive 4 of the gpctd fixture has a truncated climb-phase telemetry
    upload that leaves raw gpctd_oxygen frequency at exactly 0 Hz for most of
    the dive. Confirms Sensors/sbe43_ext.py now flags those samples
    QC_UNSAMPLED (rather than leaving them QC_GOOD with impossible negative
    oxygen values).
    """
    data_dir = pathlib.Path("testdata/sg525_RMH0726_sbe43_gpctd")
    mission_dir = data_dir.joinpath("mission_dir")

    cmd_line = [
        "--verbose",
        "--mission_dir",
        str(mission_dir),
        "--plot_types",
        "dives",
        "--dive_plots",
        "plot_sbe43",
    ]

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        cmd_line,
        caplog,
        [
            "Missing metadata for log entry $PC_",
            "not a gzipped file/file too short",
            "Problem gzip decompressing",
            "Could not process pc0004bz",
            "Engineering data ends at",
            "Large mis-match between predicted and observed w",
            "Missing metadata for sg_cal_",
            "Dive [4] failed to process completely",
        ],
    )

    ncf = Utils.open_netcdf_file(
        str(mission_dir / "p5350004.nc"), mask_results=False
    )
    freq = ncf.variables["gpctd_oxygen"][:]
    qc = QC.decode_qc(ncf.variables["sbe43_dissolved_oxygen_qc"][:])
    o2 = ncf.variables["sbe43_dissolved_oxygen"][:]
    ncf.close()

    # gpctd_oxygen (raw, gpctd_data_point) has one extra leading sample vs.
    # the QC'd/derived variables (ctd_data_point); drop it to align.
    n = len(qc)
    zero_freq = freq[-n:] == 0
    assert zero_freq.sum() > 0
    assert np.all(qc[zero_freq] == QC.QC_UNSAMPLED)
    # No more impossible negative oxygen passing as QC_GOOD.
    good_o2 = o2[qc == QC.QC_GOOD]
    good_o2 = good_o2[~np.isnan(good_o2)]
    assert np.all(good_o2 >= 0)
