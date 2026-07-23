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

"""Tests for CalibConstCheck.py's CTD-type capture-evidence detection.

Real selftest captures for the sg_ct_type driver-name variants named in
Sensors/legato_ext.py's instruments_d - legatoFast, legatoPoll,
legatoPollSUNA, legatoPollv4, rbr - are hard to come by (some, like
legatoFast, are only ever switched to mid-mission and never seen at
selftest time). These fixtures cover the variants confirmed available as
real pre-launch selftest captures; see docs/dev/plans for the fleet
validation these signals were derived from.

testdata/sg677_logdev/ covers a separate, previously-unavailable mount: RBR
configured as a dedicated logdev board (as opposed to SciCon-mounted or
truck-wired) - hull 677 is the only known real-world vehicle configured
this way fleet-wide.
"""

import pathlib

import CalibConstCheck


def test_evidence_legatopoll_scicon() -> None:
    """Confirms plain legatoPoll (the common case, ~27 of 40 real Legato missions
    surveyed) is detected as SciCon-mounted Legato."""
    capture = pathlib.Path("testdata/sg261_Shilshole_17Jul26_legatoPoll/pt2610003.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["legato_present"] is True
    assert evidence["legato_via_scicon"] is True
    assert evidence["legato_via_logdev"] is False
    assert evidence["sbe_present"] is False
    assert evidence["legato_reported_sealevel"] == 10152.0


def test_evidence_rbr_truck_not_confirmed() -> None:
    """rbr (truck-mounted Legato, per legato_ext.py's instruments_d) has no
    validated capture-text signal - confirms the checker stays honestly silent
    rather than asserting "truck" without proof.

    A candidate signal (the main truck "columns:" line naming rbr.* columns,
    e.g. "rbr.conduc,rbr.temp,rbr.pressure,rbr.conducTemp" - present in this
    exact fixture) was fleet-validated and rejected: only 0.333 precision,
    since some SciCon-mounted vehicles' truck eng schema also unconditionally
    declares unused rbr.* placeholder columns regardless of real wiring (the
    same "declared capability, not live use" trap as the rejected .cnf-file
    signals). This vehicle is confirmed genuinely truck-mounted via its
    processed netCDF data (eng_rbr_temp present) - not available pre-dive.
    """
    capture = pathlib.Path("testdata/sg677_Hurricane_Jul25_rbr_truck/pt6770020.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["sbe_present"] is False
    assert evidence["legato_present"] is False
    assert evidence["legato_via_scicon"] is False
    assert evidence["legato_via_logdev"] is False


def test_evidence_legatopollv4_scicon() -> None:
    """Confirms legatoPollv4 (a legatoPoll* variant) is detected as SciCon-mounted Legato."""
    capture = pathlib.Path("testdata/sg263_Shilshole_24Jun26_legatoPollv4/pt2630015.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["legato_present"] is True
    assert evidence["legato_via_scicon"] is True
    assert evidence["legato_via_logdev"] is False
    assert evidence["sbe_present"] is False
    assert evidence["legato_reported_sealevel"] == 10165.0


def test_evidence_legatopollsuna_scicon() -> None:
    """Confirms legatoPollSUNA (a legatoPoll* variant) is detected as SciCon-mounted Legato."""
    capture = pathlib.Path("testdata/sg283_deck_7May26_legatoPollSUNA/pt2830006.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["legato_present"] is True
    assert evidence["legato_via_scicon"] is True
    assert evidence["legato_via_logdev"] is False
    assert evidence["sbe_present"] is False
    assert evidence["legato_reported_sealevel"] == 10093.0


def test_evidence_gpctd_not_confirmed() -> None:
    """GPCTD has no reliable capture-text signal (yet) - confirms the checker stays
    honestly silent (neither sbe_present nor legato_present) rather than guessing.

    A promising but not-yet-validated signal exists in this same capture
    ("---- Checking GPCTD ----", "Logger sensor in logger slot 2 is GPCTD" -
    live hardware-discovery lines, not the static file-listing signals
    already rejected for GPCTD) - not wired in until validated against more
    real GPCTD fleet examples.
    """
    capture = pathlib.Path("testdata/sg654_gpctd/pt6540082.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["sbe_present"] is False
    assert evidence["legato_present"] is False
    assert evidence["legato_via_scicon"] is False
    assert evidence["legato_via_logdev"] is False


def test_evidence_legato_logdev_confirmed() -> None:
    """Confirms RBR configured as a dedicated logdev board (legato_config set,
    rb0*.x* device files - as opposed to SciCon-mounted) is detected via the
    "Logger sensor in logger slot N is RBR" live hardware-enumeration line -
    the same class of signal already validated for SciCon/GPCTD in other
    slots, not the rejected "columns:...rbr\\." declared-capability signal.

    This is the first real selftest capture ever located for this mount -
    see docs/dev/plans/2026-07-18-calib-html-output-refinements.md's
    "Legato-as-logdev" section for the fleet survey that had been unable to
    find one until now. This capture additionally completes a full
    "---- Checking RBR ----" self-test with a live HRBR channel reporting
    "prefix = rb", matching the rb0*.x* device-file convention.
    """
    capture = pathlib.Path("testdata/sg677_logdev/pt6770009.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["legato_present"] is True
    assert evidence["legato_via_logdev"] is True
    assert evidence["legato_via_scicon"] is False
    assert evidence["sbe_present"] is False


def test_evidence_legato_logdev_confirmed_no_selftest_block() -> None:
    """Same logdev vehicle (hull 677), a capture where the RBR self-test didn't
    run to completion (no "---- Checking RBR ----"/HRBR block present) -
    confirms the logger-slot enumeration line alone is sufficient evidence;
    the fuller self-test block isn't load-bearing."""
    capture = pathlib.Path("testdata/sg677_logdev/pt6770005.cap")
    evidence = CalibConstCheck._scan_capture_for_ctd_evidence(capture)
    assert evidence["legato_present"] is True
    assert evidence["legato_via_logdev"] is True
    assert evidence["legato_via_scicon"] is False
    assert evidence["sbe_present"] is False


def test_detect_ctd_type_logdev_mount_confirmed_by_capture() -> None:
    """Capture-confirmed logdev evidence outranks the older, calib-file-only
    "legato_config set" mount note - matches this module's existing
    philosophy that capture evidence outranks self-report (as already true
    for the SciCon-attached branch)."""
    calib_consts: dict[str, str | float | int] = {"sg_ct_type": 4, "legato_config": 191}
    evidence = CalibConstCheck.CTDEvidence(
        sbe_present=False,
        legato_present=True,
        legato_via_scicon=False,
        legato_via_logdev=True,
        legato_reported_sealevel=None,
    )
    finding = CalibConstCheck.detect_ctd_type(calib_consts, evidence)
    assert finding["status"] == "ok"
    assert "configured as logdev, confirmed by capture" in str(finding["expected"])
    assert "unpumped RBR Legato" in str(finding["expected"])


def test_detect_ctd_type_logdev_config_only_unchanged() -> None:
    """Regression: with no capture confirmation (legato_via_logdev False),
    behavior is unchanged from before this signal was added - falls back to
    the calib-file-only "legato_config set" mount note."""
    calib_consts: dict[str, str | float | int] = {"sg_ct_type": 4, "legato_config": 191}
    evidence = CalibConstCheck.CTDEvidence(
        sbe_present=False,
        legato_present=False,
        legato_via_scicon=False,
        legato_via_logdev=False,
        legato_reported_sealevel=None,
    )
    finding = CalibConstCheck.detect_ctd_type(calib_consts, evidence)
    assert "legato_config set - configured for logdev use" in str(finding["expected"])
