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

"""divescience.yml validation: per-file form, the merge, the merged plots, the CLI and plot_science."""

import logging
import pathlib
from types import SimpleNamespace

import pytest
import testutils
import yaml

import Base  # noqa: F401 - normal import order
import BaseLog
import BasePlot
import DiveScienceModel

CONFIG = pathlib.Path("config/divescience.yml")
SAMPLE = pathlib.Path("sg000/divescience.yml")

# What the old loader (Plotting/DiveScience.validate_dict) gave for the sg000 sample's lg plot
LG = {
    "instrument": "legato",
    "layout": {
        "xaxis_title": "Temperature (C)",
        "xaxis2_title": "Conductivity (mS/cm)",
        "xaxis_type": "linear",
        "xaxis2_type": "linear",
    },
    "vars": {
        "temp": {"xaxis": "x1", "color_down": "Red", "color_up": "Magenta", "units": "C", "hoverfmt": ".4f", "visible": True},
        "conduc": {
            "xaxis": "x2",
            "color_down": "Green",
            "color_up": "DarkGreen",
            "units": "mS/cm",
            "hoverfmt": ".4f",
            "visible": True,
        },
    },
}


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text)
    return p


@pytest.mark.parametrize("path", [CONFIG, SAMPLE])
def test_samples_valid(path: pathlib.Path) -> None:
    loaded, problems, bad = DiveScienceModel.check_file(path)
    assert loaded is not None and problems == [] and bad == set()


def test_samples_merge_as_before() -> None:
    result = DiveScienceModel.load_merged([CONFIG, SAMPLE])
    assert (result.problems, result.changes) == ([], [])
    assert list(result.plots) == ["fet", "microriderg", "suna", "lg"]
    assert result.plots["lg"] == LG
    # Defaults are filled in as before
    assert result.plots["fet"]["vars"]["Vrse"]["visible"] is True
    assert result.plots["fet"]["layout"]["xaxis_type"] == "linear"


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("p:\n  instrument: x\n  vars:\n    v:\n      colour_down: Red\n", 5, "p.vars.v.colour_down: Extra inputs are not permitted"),
        ("p:\n  instrument: x\n  vars:\n    v:\n      color_down: Read\n", 5, "'Read' is not a color plotly knows"),
        ("p:\n  instrument: x\n  vars:\n    v:\n      xaxis: x3\n", 5, "p.vars.v.xaxis: Input should be 'x1' or 'x2'"),
        ("p:\n  instrument: x\n  layout:\n    xaxis_titel: T\n", 4, "p.layout.xaxis_titel: Extra inputs are not permitted"),
        ("p:\n  instrument: x\n  lay_out: {}\n", 3, "p.lay_out: Extra inputs are not permitted"),
        ("p:\n  instrument: 5\n", 2, "p.instrument: Input should be a valid string"),
        ("p: [1, 2]\n", 1, "p: Input should be a valid dictionary"),
    ],
)
def test_file_errors(tmp_path: pathlib.Path, text: str, line: int, message: str) -> None:
    """Each problem is reported at its line, and only that plot is marked bad."""
    path = _write(tmp_path, "divescience.yml", text + "ok:\n  instrument: y\n")
    loaded, problems, bad = DiveScienceModel.check_file(path)
    assert loaded is not None and bad == {"p"}
    assert len(problems) == 1 and problems[0].startswith(f"{path}:{line}: ") and message in problems[0]


def test_file_unusable(tmp_path: pathlib.Path) -> None:
    """A YAML error, a non-mapping or an unreadable file can't be used; an empty one is empty."""
    syntax = _write(tmp_path, "a.yml", "p:\n  instrument: [x\n")
    loaded, problems, _ = DiveScienceModel.check_file(syntax)
    assert loaded is None and problems[0].startswith(f"{syntax}:")
    listed = _write(tmp_path, "b.yml", "- p\n")
    loaded, problems, _ = DiveScienceModel.check_file(listed)
    assert loaded is None and problems == [f"{listed}: divescience.yml must map plot names to plots (got list)"]
    loaded, problems, _ = DiveScienceModel.check_file(tmp_path)
    assert loaded is None and problems[0].startswith(f"{tmp_path}: could not read (")
    loaded, problems, bad = DiveScienceModel.check_file(_write(tmp_path, "c.yml", "# nothing\n"))
    assert loaded is not None and loaded.data == {} and (problems, bad) == ([], set())
    loaded, problems, bad = DiveScienceModel.check_file(_write(tmp_path, "d.yml", "5:\n  instrument: x\n"))
    assert bad == {"5"} and "plot name 5 must be a string" in problems[0]


def test_merge_override_add_remove(tmp_path: pathlib.Path) -> None:
    """A later file changes one color, adds a var, removes a var and a whole plot."""
    mission = _write(
        tmp_path,
        "divescience.yml",
        "lg:\n  vars:\n    temp:\n      color_down: Purple\n    conduc: null\n    salin:\n      xaxis: x2\nsuna: null\n",
    )
    result = DiveScienceModel.load_merged([CONFIG, SAMPLE, mission])
    assert result.problems == []
    assert "suna" not in result.plots
    lg_vars = result.plots["lg"]["vars"]
    assert list(lg_vars) == ["temp", "salin"]
    assert lg_vars["temp"]["color_down"] == "Purple" and lg_vars["temp"]["units"] == "C"
    assert lg_vars["salin"] == {"xaxis": "x2", "color_down": "Red", "color_up": "Magenta", "units": "", "hoverfmt": "", "visible": True}
    changes = "\n".join(result.changes)
    assert f"{mission}:4: lg.vars.temp.color_down: overrides {SAMPLE}:" in changes
    assert f"{mission}:5: lg.vars.conduc: removes it (set at {SAMPLE}:" in changes
    assert f"{mission}:8: suna: removes it (set at {CONFIG}:" in changes


def test_merge_bad_override_drops_plot(tmp_path: pathlib.Path) -> None:
    """A plot with a problem in any file is dropped altogether; the others are kept."""
    mission = _write(tmp_path, "divescience.yml", "lg:\n  vars:\n    temp:\n      color_down: Read\n")
    result = DiveScienceModel.load_merged([CONFIG, SAMPLE, mission])
    assert "lg" not in result.plots and list(result.plots) == ["fet", "microriderg", "suna"]
    assert len(result.problems) == 2
    assert result.problems[0].startswith(f"{mission}:4: lg.vars.temp.color_down:")
    assert result.problems[1] == f"{mission}:1: lg: has problems (above) - not plotted"


def test_merge_unusable_file_skipped(tmp_path: pathlib.Path) -> None:
    """A file that can't be used is skipped on its own (the old loader then dropped every file)."""
    mission = _write(tmp_path, "divescience.yml", "- not a mapping\n")
    result = DiveScienceModel.load_merged([CONFIG, SAMPLE, mission])
    assert list(result.plots) == ["fet", "microriderg", "suna", "lg"] and len(result.problems) == 1


def test_merged_incomplete(tmp_path: pathlib.Path) -> None:
    """A plot left without an instrument or vars after the merge is dropped (an empty instrument matched every dive)."""
    mission = _write(tmp_path, "divescience.yml", "new:\n  vars:\n    x: {}\nempty:\n  instrument: y\nlg:\n  instrument: ''\n")
    result = DiveScienceModel.load_merged([SAMPLE, mission])
    assert result.plots == {}
    problems = "\n".join(result.problems)
    assert f"{mission}:1: new.instrument: Field required in the merged plot - not plotted" in problems
    assert f"{mission}:4: empty.vars: Field required in the merged plot - not plotted" in problems
    assert f"{mission}:6: lg.instrument: String should have at least 1 character in the merged plot" in problems
    plots, problems = DiveScienceModel.check_merged_plots({"x": {}}, [])
    assert plots == {} and problems[0].startswith("(no files): x.instrument")


def test_config_files(tmp_path: pathlib.Path) -> None:
    """The plot's search order: basestation config, basestation etc, group_etc, mission dir."""
    for sub in ("bs/config", "bs/etc", "group", "mission"):
        (tmp_path / sub).mkdir(parents=True)
        (tmp_path / sub / "divescience.yml").write_text("{}\n")
    (tmp_path / "bs/etc/divescience.yml").unlink()
    opts = SimpleNamespace(basestation_directory=tmp_path / "bs", group_etc=tmp_path / "group", mission_dir=tmp_path / "mission")
    assert DiveScienceModel.config_files(opts) == [
        tmp_path / "bs/config/divescience.yml",
        tmp_path / "group/divescience.yml",
        tmp_path / "mission/divescience.yml",
    ]
    opts.group_etc = None
    assert len(DiveScienceModel.config_files(opts)) == 2


def test_cli_single_file(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    assert DiveScienceModel.main(["check", str(SAMPLE)]) == 0
    capsys.readouterr()
    assert DiveScienceModel.main(["dump", str(SAMPLE)]) == 0
    assert yaml.safe_load(capsys.readouterr().out) == yaml.safe_load(SAMPLE.read_text())
    bad = _write(tmp_path, "bad.yml", "p:\n  instrument: x\n  vars:\n    v: {color_up: Bleu}\n")
    with caplog.at_level(logging.ERROR):
        assert DiveScienceModel.main(["check", str(bad)]) == 1
        assert DiveScienceModel.main(["dump", str(bad)]) == 1
        assert DiveScienceModel.main(["check"]) == 1
    assert f"{bad}:4: p.vars.v.color_up" in caplog.text and "check needs a divescience.yml file" in caplog.text
    assert capsys.readouterr().out == ""


def test_cli_merged(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    mission = tmp_path / "mission"
    mission.mkdir()
    (mission / "divescience.yml").write_text(SAMPLE.read_text())
    with caplog.at_level(logging.INFO):
        assert DiveScienceModel.main(["--verbose", "check_merged", "-m", str(mission)]) == 0
    assert "Merged: 4 plot(s) - fet, microriderg, suna, lg" in caplog.text
    capsys.readouterr()
    assert DiveScienceModel.main(["dump_merged", "-m", str(mission)]) == 0
    assert yaml.safe_load(capsys.readouterr().out)["lg"] == LG
    (mission / "divescience.yml").write_text("lg:\n  vars:\n    temp: {color_down: Purple, xaxis: x9}\n")
    with caplog.at_level(logging.ERROR):
        assert DiveScienceModel.main(["check_merged", "-m", str(mission)]) == 1
        assert DiveScienceModel.main(["check_merged"]) == 1
        assert DiveScienceModel.main(["dump_merged", str(SAMPLE), "-m", str(mission)]) == 1
    assert "lg: has problems (above) - not plotted" in caplog.text
    assert "check_merged needs --mission_dir" in caplog.text and "dump_merged takes no file" in caplog.text
    # An override of a shipped plot (lg is only in the sg000 sample, not config/)
    (mission / "divescience.yml").write_text("fet:\n  vars:\n    Vk: {color_down: Purple}\n")
    with caplog.at_level(logging.INFO):
        assert DiveScienceModel.main(["--verbose", "check_merged", "-m", str(mission)]) == 0
    assert "fet.vars.Vk.color_down: overrides" in caplog.text


def test_plot_science_bad_plot_alert(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """plot_science raises DIVESCIENCE_CONFIG for a bad mission plot and still draws the good ones."""

    def add_config(mission_dir: pathlib.Path) -> None:
        (mission_dir / "divescience.yml").write_text(
            "fet:\n  vars:\n    Vk:\n      color_down: Purple\nbogus:\n  instrument: fet\n  vars:\n    Vk: {color_down: Read}\n"
        )

    mission_dir = tmp_path / "mission_dir"
    testutils.run_mission(
        pathlib.Path("testdata/sg686_Shilshole_28Oct25"),
        mission_dir,
        BasePlot.main,
        ["--verbose", "--mission_dir", str(mission_dir), "p6860005.nc", "--plot_types", "dives", "--dive_plots", "plot_science"],
        caplog,
        [""],
        pre_test_hook=add_config,
        required_msgs=["bogus.vars.Vk.color_down", "bogus: has problems (above) - not plotted"],
    )
    assert list(mission_dir.joinpath("plots").glob("*fet*.webp")), "the good fet plot wasn't drawn"
    assert not list(mission_dir.joinpath("plots").glob("*bogus*"))
    assert "Traceback" not in caplog.text
