# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
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

import pathlib

import numpy as np
import playwright.sync_api
import pytest
import testutils

import Base
import BaseMagCal
import BasePlot
import Magcal
import MakeDiveProfiles
import Utils

test_cases = (
    ("tcm2mat.cal.0001.0004", ["tcm2mat.cal.0001.0004 to correct heading"], [""]),
    ("search", ["tcm2mat.cal.0001.0004 to correct heading"], [""]),
    ("tcm2mat.cal", [""], ["tcm2mat.cal does not exist"]),
)

# Real old-style (plain, non-DG) tcm2mat.cal content, as produced for a regular
# Seaglider - e.g. sg203_WA_coast_Jul17/tcm2mat.cal. Distinct from the
# tcm2mat.cal.0001.0004 fixture used above, which is the newer key=value format
# parsed by parseNewMagCalFile - a different function with its own (working) closure.
OLD_STYLE_CAL_CONTENTS = (
    '"dive 7 result"\n'
    "0 1 0 0\n"
    "0 1 0 0\n"
    "1.000 0.007 0.004 0.005 1.039 -0.029 0.003 0.007 1.025 17.67 -11.43 19.15\n"
)


def test_parse_mag_cal_returns_callable_pqrc() -> None:
    """parseMagCal's second return value must be callable (compassTransform calls it as
    pqrc(pitchAD)) - regression test for a bug where it returned the raw pqr ndarray
    instead, breaking heading correction for every dive on any mission using an
    old-style plain tcm2mat.cal file (e.g. sg203_WA_coast_Jul17/sg204_WA_coast_Jul17
    hit `TypeError: 'numpy.ndarray' object is not callable` in compassTransform on
    every dive as a result).
    """
    abc, pqrc = BaseMagCal.parseMagCal(OLD_STYLE_CAL_CONTENTS)

    assert abc is not None
    assert callable(pqrc)
    # compassTransform must not raise when given parseMagCal's own output.
    heading = BaseMagCal.compassTransform(abc, pqrc, pitchAD=100.0, roll_deg=0.0, pitch_deg=10.0, mag=np.zeros(3))
    assert heading is not None


@pytest.mark.parametrize(
    "magcal_filename,required_msgs,allowed_msgs",
    test_cases,
)
def test_simpleplotextensionbase(caplog, magcal_filename, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal")
    mission_dir = data_dir.joinpath("mission_dir")
    magcal_filename = mission_dir / magcal_filename

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose  --local --no-notify_vis --skip_flight_model --plot_types none --ignore_flight_model --magcalfile {magcal_filename} --mission_dir {mission_dir}".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
    )


@pytest.mark.parametrize(
    "magcal_filename,required_msgs,allowed_msgs",
    test_cases,
)
def test_simpleplotextensionMDP(caplog, magcal_filename, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal_ncf")
    mission_dir = data_dir.joinpath("mission_dir")
    magcal_filename = mission_dir / magcal_filename

    testutils.run_mission(
        data_dir,
        mission_dir,
        MakeDiveProfiles.main,
        f"--verbose  --magcalfile {magcal_filename} --mission_dir {mission_dir} 2".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
    )


# (baseplot_options, testdata_dir, per-dive nc filename)
_MAGCAL_DIVE = (
    "p6860005.nc --plot_types dives --dive_plot plot_mag --full_html",
    "sg686_Shilshole_28Oct25",
    "p6860005.nc",
)


def test_build_fit_line_text_softiron() -> None:
    """With soft-iron correction, both hard0 and soft0 are present.

    fit_line_html joins them with "<br>" (for the Plotly title); copy_text
    joins the identical content with "\\n" instead (for the clipboard).
    """
    hard = [12.3, -4.6, 78.9]
    abc0 = np.array(
        [
            [1.001, 0.002, -0.003],
            [0.004, 0.995, 0.006],
            [-0.007, 0.008, 1.009],
        ]
    )

    fit_line, copy_text = Magcal.build_fit_line_text(hard, abc0, True)

    assert fit_line == (
        'hard0="12.3 -4.6 78.9"<br>'
        'soft0="1.001 0.002 -0.003 0.004 0.995 0.006 -0.007 0.008 1.009"'
    )
    assert copy_text == fit_line.replace("<br>", "\n")
    assert "<br>" not in copy_text
    assert "\n" in copy_text


def test_build_fit_line_text_no_softiron() -> None:
    """Without soft-iron correction, only the hard0 line is present."""
    hard = [1.0, -2.0, 3.0]

    fit_line, copy_text = Magcal.build_fit_line_text(hard, np.eye(3), False)

    assert fit_line == 'hard0="1.0 -2.0 3.0"'
    assert copy_text == fit_line
    assert "soft0" not in fit_line


def test_build_fit_line_text_negative_values_not_swallowed() -> None:
    """Negative fitted values keep their sign - regression guard against a
    string-formatting slip that could drop the minus sign."""
    hard = [-1.5, -20.2, -100.0]

    fit_line, _ = Magcal.build_fit_line_text(hard, np.eye(3), False)

    assert fit_line == 'hard0="-1.5 -20.2 -100.0"'


def test_magcal_handles_nan_magnetometer_sample(caplog: pytest.LogCaptureFixture) -> None:
    """A single NaN sample in eng_mag_x must not poison the whole hard-iron
    fit into an all-NaN result - regression test for a bug (sg196 dive 13)
    where a NaN anywhere in eng_mag_x/y/z propagated, via an unguarded
    scalar normalization in Magcal.magcal_worker, into every downstream
    sample: the fitted hard-iron vector, the plot's axis range, and the
    title ended up NaN (`hard0="nan nan nan"`), rendering an empty plot.
    """
    baseplot_options, data_dir_name, nc_filename = _MAGCAL_DIVE
    data_dir = pathlib.Path("testdata").joinpath(data_dir_name)
    mission_dir = data_dir.joinpath("mission_dir")

    def inject_nan(mission_dir: pathlib.Path) -> None:
        nc_file = Utils.open_netcdf_file(str(mission_dir / nc_filename), mode="r+")
        nc_file.variables["eng_mag_x"][0] = float("nan")
        nc_file.close()

    cmd_line = ["--verbose", "--mission_dir", str(mission_dir)]
    cmd_line += baseplot_options.split(" ")
    testutils.run_mission(
        data_dir,
        mission_dir,
        BasePlot.main,
        cmd_line,
        caplog,
        [""],
        pre_test_hook=inject_nan,
    )

    nc_file = Utils.open_netcdf_file(str(mission_dir / nc_filename))
    try:
        hard, _soft, _cover, _circ, fig, copy_text = Magcal.magcal_worker(
            [nc_file], True, "html", "test title"
        )
    finally:
        nc_file.close()

    assert fig is not None
    assert copy_text
    assert "nan" not in copy_text.lower()
    assert np.isfinite(hard).all()


def test_copy_button_copies_hard0_soft0(caplog: pytest.LogCaptureFixture) -> None:
    """The magcal plot's "Copy calibration" button copies the exact
    hard0=/soft0= text shown in the title to the clipboard, as plain
    (non-HTML) text.

    Generates a real dive's magcal plot HTML end to end (Plotting.DiveMagCal
    via BasePlot.main), then drives a headless Chromium browser (Playwright)
    against the standalone output: clicks the button and reads back the
    clipboard, comparing it against Magcal.magcal_worker's own copy_text
    computed directly against the same dive - so this doesn't hardcode the
    fitted numeric values, which would make the test brittle to any future
    change in the fit itself.

    Skips (rather than fails) if a Chromium binary isn't available locally
    - playwright is a project dependency, but `playwright install chromium`
    is a separate provisioning step (already done in CI, see
    .github/workflows/action.yml).
    """
    baseplot_options, data_dir_name, nc_filename = _MAGCAL_DIVE
    data_dir = pathlib.Path("testdata").joinpath(data_dir_name)
    mission_dir = data_dir.joinpath("mission_dir")

    cmd_line = ["--verbose", "--mission_dir", str(mission_dir)]
    cmd_line += baseplot_options.split(" ")
    testutils.run_mission(data_dir, mission_dir, BasePlot.main, cmd_line, caplog, [""])

    html_path = (mission_dir / "plots" / "dv0005_magcal.html").resolve()
    assert html_path.exists()

    # Cast to str at the boundary - Utils.open_netcdf_file requires it.
    nc_file = Utils.open_netcdf_file(str(mission_dir / nc_filename))
    try:
        *_, expected_copy_text = Magcal.magcal_worker(
            [nc_file], True, "html", "test title"
        )
    finally:
        nc_file.close()
    assert expected_copy_text

    try:
        with playwright.sync_api.sync_playwright() as p:
            p.chromium.launch(headless=True).close()
    except Exception as exc:
        pytest.skip(f"Chromium not available for Playwright ({exc})")

    with playwright.sync_api.sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        try:
            context = browser.new_context()
            context.grant_permissions(["clipboard-read", "clipboard-write"])
            page = context.new_page()
            console_errors = []
            page.on(
                "console",
                lambda msg: console_errors.append(msg.text)
                if msg.type == "error"
                else None,
            )
            page.on("pageerror", lambda exc: console_errors.append(str(exc)))

            page.goto(html_path.as_uri())

            copy_btn = page.get_by_role(
                "button", name="Copy calibration", exact=True
            )
            copy_btn.wait_for(state="visible", timeout=10000)
            # Positioning settles asynchronously (rAF + staggered retries up
            # to 1500ms, see PlotUtilsPlotly._CLIPBOARD_BUTTON_TEMPLATE) -
            # wait it out before asserting on the button's final position.
            page.wait_for_timeout(1700)

            plot_div = page.locator(".plotly-graph-div")
            xtitle = page.locator("g.g-xtitle")
            plot_box = plot_div.bounding_box()
            xtitle_box = xtitle.bounding_box()
            copy_box = copy_btn.bounding_box()
            assert plot_box is not None
            assert xtitle_box is not None
            assert copy_box is not None
            # placement="below_centered", anchored to the x-axis title
            # group: button sits below the plot, horizontally centered
            # under the x-axis label - anchoring to the title itself
            # (rather than a fixed offset from rect.bg) means it always
            # clears the tick labels too, since the title is reliably
            # drawn below them.
            assert copy_box["y"] >= xtitle_box["y"] + xtitle_box["height"] - 1
            copy_center_x = copy_box["x"] + copy_box["width"] / 2
            xtitle_center_x = xtitle_box["x"] + xtitle_box["width"] / 2
            assert abs(copy_center_x - xtitle_center_x) < 3
            # Must land fully inside the plot div's own (visible) bounds -
            # gd fills the whole standalone page with no scrollable room
            # below it (Plotly's own full_html template), so anything
            # positioned past gd's own bottom edge is clipped, not just
            # scrolled off (confirmed against a real dive's plot when an
            # earlier version anchored below gd itself).
            assert (
                copy_box["y"] + copy_box["height"]
                <= plot_box["y"] + plot_box["height"] + 1
            )

            copy_btn.click()
            page.wait_for_timeout(200)
            clipboard_text = page.evaluate("navigator.clipboard.readText()")

            assert not console_errors, console_errors
        finally:
            browser.close()

    assert clipboard_text == expected_copy_text


def test_magcal_worker_phase_split_produces_different_fits() -> None:
    """magcal_worker(phase="dive")/phase="climb") must fit against
    disjoint sample sets, not silently fall back to the combined
    (phase="all") behavior - regression guard for the dive/climb split
    feature: proves the two fits actually differ rather than both
    happening to compute the same "all" result.
    """
    _baseplot_options, data_dir_name, nc_filename = _MAGCAL_DIVE
    mission_dir = pathlib.Path("testdata").joinpath(data_dir_name, "mission_dir")

    nc_file = Utils.open_netcdf_file(str(mission_dir / nc_filename))
    try:
        hard_dive, _soft_dive, _cover_dive, _circ_dive, fig_dive, _copy_dive = (
            Magcal.magcal_worker(
                [nc_file], True, "html", "test title", phase="dive"
            )
        )
        hard_climb, _soft_climb, _cover_climb, _circ_climb, fig_climb, _copy_climb = (
            Magcal.magcal_worker(
                [nc_file], True, "html", "test title", phase="climb"
            )
        )
    finally:
        nc_file.close()

    assert fig_dive is not None
    assert fig_climb is not None
    assert np.isfinite(hard_dive).all()
    assert np.isfinite(hard_climb).all()
    assert hard_dive != hard_climb
    assert "(dive)" in fig_dive.layout.title.text
    assert "(climb)" in fig_climb.layout.title.text


def test_plot_mag_dive_climb_split(caplog: pytest.LogCaptureFixture) -> None:
    """--plot_magcal_dive_climb makes DiveMagCal emit dv####_magcal_dive/
    _climb instead of the combined dv####_magcal."""
    baseplot_options, data_dir_name, _nc_filename = _MAGCAL_DIVE
    data_dir = pathlib.Path("testdata").joinpath(data_dir_name)
    mission_dir = data_dir.joinpath("mission_dir")

    cmd_line = ["--verbose", "--mission_dir", str(mission_dir)]
    cmd_line += baseplot_options.split(" ")
    cmd_line += ["--plot_magcal_dive_climb"]
    testutils.run_mission(data_dir, mission_dir, BasePlot.main, cmd_line, caplog, [""])

    plots_dir = mission_dir / "plots"
    assert (plots_dir / "dv0005_magcal_dive.html").exists()
    assert (plots_dir / "dv0005_magcal_climb.html").exists()
    assert not (plots_dir / "dv0005_magcal.html").exists()


def test_magcal_function_phase_split_produces_different_fits() -> None:
    """Magcal.magcal()'s phase parameter threads through to
    magcal_worker() - regression guard for the batch-CLI split feature's
    underlying function (Magcal.py:main() is a thin argparse/file-writing
    wrapper around this)."""
    _baseplot_options, data_dir_name, _nc_filename = _MAGCAL_DIVE
    mission_dir = str(pathlib.Path("testdata").joinpath(data_dir_name, "mission_dir"))

    hard_dive, soft_dive, _cover_dive, _circ_dive, html_dive = Magcal.magcal(
        mission_dir, 686, [5], True, "html", phase="dive"
    )
    hard_climb, soft_climb, _cover_climb, _circ_climb, html_climb = Magcal.magcal(
        mission_dir, 686, [5], True, "html", phase="climb"
    )

    assert html_dive
    assert html_climb
    assert hard_dive != hard_climb
    assert not np.array_equal(soft_dive, soft_climb)
