"""Tests for ctd_sampling.buoyancy.

No reference toolbox is available to check exact numeric values against
(the original used the legacy EOS-80 ``seawater`` toolbox; this port
deliberately uses TEOS-10 ``gsw`` instead, per project decision, so exact
parity isn't expected or meaningful). These tests instead check physically
sane behavior on synthetic profiles.
"""

import numpy as np

from ctd_sampling.buoyancy import buoyancy_frequency


def test_stable_stratification_is_positive_and_finite() -> None:
    """A monotonically cooling, freshening-with-depth profile is stably stratified."""
    z = np.arange(0.0, 200.0, 5.0)
    salinity = 35.0 - 0.01 * z
    temperature = 28.0 - 0.05 * z

    bf = buoyancy_frequency(z, temperature, salinity, longitude=84.5, latitude=8.0)

    assert np.all(np.isfinite(bf))
    assert np.all(bf > 0)


def test_unstable_stratification_gives_zero_not_positive() -> None:
    """Statically unstable water should read as buoyancy frequency ~0, not a spurious positive value."""
    # Colder (denser) water sitting *above* warmer water: statically unstable.
    z = np.arange(0.0, 200.0, 5.0)
    salinity = np.full_like(z, 35.0)
    temperature = 10.0 + 0.05 * z

    bf = buoyancy_frequency(z, temperature, salinity, longitude=84.5, latitude=8.0)

    # N^2 < 0 here, so sqrt(N^2) is purely imaginary (real part exactly 0,
    # not negative) -- matching the original MATLAB script, which only
    # masks *negative* real values to NaN. That masking only actually
    # triggers at the two edge points (via linear extrapolation, which can
    # overshoot past zero); interior unstable water reads as a buoyancy
    # frequency of ~0, not NaN.
    assert np.all(np.isfinite(bf))
    np.testing.assert_allclose(bf, 0.0, atol=1e-8)


def test_stronger_stratification_gives_higher_frequency() -> None:
    """A steeper temperature gradient should produce a higher buoyancy frequency."""
    z = np.arange(0.0, 200.0, 5.0)
    salinity = np.full_like(z, 35.0)

    weak = buoyancy_frequency(z, 20.0 - 0.01 * z, salinity, longitude=84.5, latitude=8.0)
    strong = buoyancy_frequency(z, 20.0 - 0.1 * z, salinity, longitude=84.5, latitude=8.0)

    mid = slice(2, -2)
    assert np.all(strong[mid] > weak[mid])
