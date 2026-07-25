"""Smoke test for ctd_sampling.cli."""

from pathlib import Path
from unittest.mock import patch

from ctd_sampling.cli import main

_FIXTURES = Path(__file__).parent / "fixtures"


def test_main_runs_end_to_end_and_writes_figures(tmp_path: Path) -> None:
    """The CLI should run against the bundled fixtures and write both HTML figures."""
    main(
        [
            "--data-dir",
            str(_FIXTURES),
            "--sg-label",
            "167",
            "--latest-profile",
            "97",
            "--n-dives",
            "5",
            "--output-dir",
            str(tmp_path),
        ]
    )

    buoyancy_html = tmp_path / "buoyancy_frequency.html"
    schedule_html = tmp_path / "sampling_schedule.html"
    assert buoyancy_html.is_file()
    assert schedule_html.is_file()
    assert buoyancy_html.stat().st_size > 0
    assert schedule_html.stat().st_size > 0


def test_show_flag_opens_both_figures_in_browser(tmp_path: Path) -> None:
    """--show should open both generated figures via the default web browser."""
    with patch("webbrowser.open") as mock_open:
        main(
            [
                "--data-dir",
                str(_FIXTURES),
                "--output-dir",
                str(tmp_path),
                "--show",
            ]
        )

    assert mock_open.call_count == 2


def test_without_show_flag_does_not_open_browser(tmp_path: Path) -> None:
    """Without --show, no browser tab should be opened."""
    with patch("webbrowser.open") as mock_open:
        main(["--data-dir", str(_FIXTURES), "--output-dir", str(tmp_path)])

    mock_open.assert_not_called()
