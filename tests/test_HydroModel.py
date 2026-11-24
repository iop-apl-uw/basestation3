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


"""HydroModel.hydro_model: enough iterations to converge at the edge of the SGX drag grid."""

from pathlib import Path

import numpy as np
import pytest

import Base  # noqa: F401 - normal import order
import HydroModel

# sg263 NANOOS_Aug26 dive 40 at hd_a 0.001, hd_b 0.030, vbdbias 0 cc: one point of FM's coarse vbdbias search
FIXTURE = Path("testdata/sg263_NANOOS_Aug26_hydro/dive40_vbdbias0.npz")


def _inputs() -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    data = np.load(FIXTURE)
    consts = {
        k.removeprefix("const_"): float(data[k]) for k in data if k.startswith("const_")
    }
    return data["buoyancy"], data["pitch"], consts


def test_converges_at_sgx_grid_edge() -> None:
    """This point takes 83 iterations; with 61 FM found no vbdbias for sg263 dives 40-88."""
    buoyancy, pitch, consts = _inputs()
    converged, speed, _, stalled = HydroModel.hydro_model(buoyancy, pitch, consts)
    assert converged
    assert len(stalled) < 0.2 * len(buoyancy) and np.all(np.isfinite(speed))


def test_too_few_iterations(monkeypatch: pytest.MonkeyPatch) -> None:
    """The old limit (61) doesn't converge here - the regression the limit guards."""
    monkeypatch.setattr(HydroModel, "hydro_loop_count", 61)
    assert not HydroModel.hydro_model(*_inputs())[0]
