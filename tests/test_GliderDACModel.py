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

"""GliderDAC template validation: per-file form, the merge and the merged result."""

import logging
import pathlib

import pytest
import yaml

import Base  # noqa: F401 - normal import order
import BaseLog
import GliderDACModel

DOCS = pathlib.Path("docs/gliderdac")
DOCS_TRIPLE = [DOCS / "seaglider.yml", DOCS / "project.yml", DOCS / "sgXXX.yml"]


@pytest.fixture(autouse=True)
def _fresh_baselog():
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: pathlib.Path, name: str, text: str) -> pathlib.Path:
    p = tmp_path / name
    p.write_text(text)
    return p


@pytest.mark.parametrize(
    "path",
    [*DOCS_TRIPLE, *sorted(pathlib.Path("testdata/sg160_sbe43_scicon").glob("gliderdac_deployment*.yml"))],
)
def test_samples_and_fixtures_are_valid(path: pathlib.Path) -> None:
    loaded, problems = GliderDACModel.check_file(path)
    assert problems == [] and loaded is not None


def test_docs_triple_merges() -> None:
    result = GliderDACModel.load_merged(DOCS_TRIPLE)
    assert (result.problems, result.dropped) == ([], [])
    assert result.template is not None and "temperature" in result.template["variables"]


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        ("variables:\n  t:\n    type: f9\n", 3, "variables.t.type: Value error, not a numpy type code"),
        ("variables:\n  t:\n    type: f8\n    qc_data: QC_GREAT\n", 4, "variables.t.qc_data: Value error, unknown QC name"),
        ("variables:\n  t:\n    dimension: [time]\n", 3, "variables.t.dimension: Extra inputs are not permitted"),
        ("global_attrs:\n  a: 1\n", 1, "global_attrs: Extra inputs are not permitted"),
        ("config:\n  timeseries_vars:\n    temperature: [temperature]\n", 3, "config.timeseries_vars.temperature: Input should be a valid string"),
    ],
)
def test_form_errors_have_file_and_line(tmp_path: pathlib.Path, text: str, line: int, message: str) -> None:
    path = _write(tmp_path, "t.yml", text)
    loaded, problems = GliderDACModel.check_file(path)
    assert loaded is None
    assert len(problems) == 1 and problems[0].startswith(f"{path}:{line}: {message}")


def test_not_a_mapping_and_syntax_error(tmp_path: pathlib.Path) -> None:
    lst = _write(tmp_path, "list.yml", "- a\n- b\n")
    assert GliderDACModel.check_file(lst)[1] == [f"{lst}: a GliderDAC template must be a mapping (got list)"]
    bad = _write(tmp_path, "bad.yml", "variables:\n  t: [\n")
    loaded, problems = GliderDACModel.check_file(bad)
    assert loaded is None and problems[0].startswith(f"{bad}:")


def test_later_template_overrides(tmp_path: pathlib.Path) -> None:
    """More specific templates override the more general - value by value, lists whole."""
    a = _write(
        tmp_path,
        "base.yml",
        "global_attributes:\n  title: one\n  keep: k\n"
        "variables:\n  t:\n    attributes: {_FillValue: -999, accuracy: '0.1'}\n    dimensions: [time]\n    type: f8\n",
    )
    b = _write(
        tmp_path,
        "dep.yml",
        "global_attributes:\n  title: two\nvariables:\n  t:\n    attributes: {accuracy: '0.01'}\n    dimensions: [time, x]\n",
    )
    result = GliderDACModel.load_merged([a, b])
    assert result.problems == [] and result.template is not None
    assert result.template["global_attributes"] == {"title": "two", "keep": "k"}
    assert result.template["variables"]["t"] == {
        "attributes": {"_FillValue": -999, "accuracy": "0.01"},
        "dimensions": ["time", "x"],
        "type": "f8",
    }
    assert result.changes == [
        f"{b}:2: global_attributes.title: overrides {a}:2 ('one' -> 'two')",
        f"{b}:5: variables.t.attributes.accuracy: overrides {a}:6 ('0.1' -> '0.01')",
        f"{b}:6: variables.t.dimensions: overrides {a}:7 (['time'] -> ['time', 'x'])",
    ]


def test_null_removes(tmp_path: pathlib.Path) -> None:
    a = _write(
        tmp_path,
        "base.yml",
        "global_attributes:\n  drop_me: x\n"
        "variables:\n"
        "  t:\n    attributes: {_FillValue: -999, accuracy: '0.1'}\n    dimensions: [time]\n    type: f8\n"
        "  u:\n    attributes: {_FillValue: -999}\n    dimensions: [time]\n    type: f8\n",
    )
    b = _write(tmp_path, "dep.yml", "global_attributes:\n  drop_me: null\nvariables:\n  t:\n    attributes: {accuracy: null}\n  u: null\n")
    result = GliderDACModel.load_merged([a, b])
    assert result.template is not None
    assert result.template["global_attributes"] == {}
    assert list(result.template["variables"]) == ["t"]
    assert result.template["variables"]["t"]["attributes"] == {"_FillValue": -999}
    assert [c.split(": ", 2)[1] for c in result.changes] == [
        "global_attributes.drop_me",
        "variables.t.attributes.accuracy",
        "variables.u",
    ]
    assert all("removes it (set at" in c for c in result.changes)


def test_incomplete_variable_is_dropped(tmp_path: pathlib.Path) -> None:
    """sg686 (OSU): dimensions/type indented under attributes - that variable is dropped, the rest loads."""
    base = _write(
        tmp_path,
        "base.yml",
        "variables:\n"
        "  temperature:\n    attributes: {_FillValue: -999}\n    dimensions: [time]\n    type: f8\n"
        "  dissolved_oxygen_n:\n    attributes:\n      _FillValue: -999\n      dimensions: [ time ]\n      type: i2\n",
    )
    result = GliderDACModel.load_merged([base])
    assert result.problems == [] and result.template is not None
    assert list(result.template["variables"]) == ["temperature"]
    assert result.dropped == [
        f"{base}:6: variables.dissolved_oxygen_n: no type, dimensions in any template "
        "(type, dimensions found under attributes - mis-indented?) - dropping this variable"
    ]


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("variables:\n  instrument_ctd:\n    attributes: {comment: x}\n    dimensions: []\n    type: i4\n",
         "variables.instrument_ctd.attributes: no _FillValue"),
        ("variables:\n  t_qc:\n    attributes: {_FillValue: -127}\n    dimensions: [time]\n    type: f8\n",
         "variables.t_qc.type: a QC variable must be an integer type"),
    ],
)
def test_merged_errors_fail_the_load(tmp_path: pathlib.Path, text: str, message: str) -> None:
    path = _write(tmp_path, "t.yml", text)
    result = GliderDACModel.load_merged([path])
    assert result.template is None and len(result.problems) == 1 and message in result.problems[0]


def test_undefined_timeseries_target_is_not_a_template_error(tmp_path: pathlib.Path) -> None:
    """A mapping to an undefined variable is GliderDAC.py's to skip at write time, not a form error."""
    dep = _write(tmp_path, "dep.yml", "config:\n  timeseries_vars:\n    sbe43_dissolved_oxygen: nonexistent_variable\n")
    result = GliderDACModel.load_merged([*DOCS_TRIPLE[:2], dep])
    assert result.template is not None and (result.problems, result.dropped) == ([], [])


def _conf(tmp_path: pathlib.Path, name: str, templates: list[pathlib.Path]) -> pathlib.Path:
    """A mission .conf naming the templates in merge order (fewer than three leaves the rest unset)."""
    lines = [f"{opt} = {path.resolve()}\n" for opt, path in zip(GliderDACModel.TEMPLATE_OPTIONS, templates, strict=False)]
    return _write(tmp_path, name, "[gliderdac]\n" + "".join(lines))


def test_cli_single_file(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """check and dump take one template, with or without --config."""
    assert GliderDACModel.main(["check", str(DOCS_TRIPLE[0])]) == 0
    conf = _conf(tmp_path, "sg123.conf", list(DOCS_TRIPLE))
    assert GliderDACModel.main(["check", str(DOCS_TRIPLE[1]), "--config", str(conf)]) == 0
    bad = _write(tmp_path, "bad.yml", "variables:\n  t:\n    type: f9\n")
    with caplog.at_level(logging.ERROR):
        assert GliderDACModel.main(["check", str(bad)]) == 1
    assert f"{bad}:3: variables.t.type" in caplog.text
    capsys.readouterr()
    assert GliderDACModel.main(["dump", str(DOCS_TRIPLE[2])]) == 0
    assert yaml.safe_load(capsys.readouterr().out) == yaml.safe_load(DOCS_TRIPLE[2].read_text())
    assert GliderDACModel.main(["dump", str(bad)]) == 1
    assert capsys.readouterr().out == ""
    with caplog.at_level(logging.ERROR):
        assert GliderDACModel.main(["check"]) == 1
    assert "check needs a template file" in caplog.text
    with pytest.raises(SystemExit):
        GliderDACModel.main(["check", str(bad), str(bad)])


def test_cli_merged(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]) -> None:
    """check_merged and dump_merged merge the templates --config names, as GliderDAC.py does."""
    conf = _conf(tmp_path, "sg123.conf", list(DOCS_TRIPLE))
    assert GliderDACModel.main(["check_merged", "--config", str(conf)]) == 0
    capsys.readouterr()
    assert GliderDACModel.main(["dump_merged", "--config", str(conf)]) == 0
    out = capsys.readouterr().out
    assert yaml.safe_load(out) == GliderDACModel.load_merged(DOCS_TRIPLE).template
    # Block style, but a list of scalars on one line
    assert "\n  conductivity:\n    attributes:\n" in out and "flag_values: [0, 1, 2," in out
    with caplog.at_level(logging.ERROR):
        assert GliderDACModel.main(["check_merged"]) == 1
        assert GliderDACModel.main(["dump_merged", str(DOCS_TRIPLE[0]), "--config", str(conf)]) == 1
        assert GliderDACModel.main(["check_merged", "--config", str(tmp_path / "missing.conf")]) == 1
        assert GliderDACModel.main(["check_merged", "--config", str(_conf(tmp_path, "two.conf", list(DOCS_TRIPLE[:2])))]) == 1
    assert "check_merged needs --config" in caplog.text
    assert "dump_merged takes no template file" in caplog.text
    assert f"{tmp_path / 'missing.conf'} does not exist" in caplog.text
    assert "gliderdac_deployment_config file not specified" in caplog.text


MISINDENTED = (
    "variables:\n"
    "  platform:\n"
    "    attributes:\n"
    "      _FillValue: -999\n"
    "      type: platform\n"
    "    dimensions: []\n"
    "    type: i4\n"
    "  dissolved_oxygen_n:\n"
    "    attributes:\n"
    "      _FillValue: -999\n"
    "      dimensions: [time]\n"
    "      type: i2\n"
)


@pytest.mark.parametrize("path", DOCS_TRIPLE)
def test_cli_check_docs_examples(path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """GliderDACModel.py check passes each docs/gliderdac example on its own, with no warnings."""
    with caplog.at_level(logging.WARNING):
        assert GliderDACModel.main(["check", str(path)]) == 0
    assert caplog.records == []


def test_cli_check_merged_docs_examples(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """GliderDACModel.py check_merged passes the three docs/gliderdac examples merged, with no warnings."""
    conf = _conf(tmp_path, "sgXXX.conf", list(DOCS_TRIPLE))
    with caplog.at_level(logging.WARNING):
        assert GliderDACModel.main(["check_merged", "--config", str(conf)]) == 0
    assert caplog.records == []


def test_suspect_attributes(tmp_path: pathlib.Path) -> None:
    """A variable field indented under attributes is flagged; platform's real type attribute isn't (OSU sg686)."""
    path = _write(tmp_path, "seaglider.yml", MISINDENTED)
    loaded, problems = GliderDACModel.check_file(path)
    assert loaded is not None and problems == []
    assert GliderDACModel.suspect_attributes(loaded) == [
        f"{path}:11: variables.dissolved_oxygen_n.attributes.dimensions: looks like a variable field indented under attributes",
        f"{path}:12: variables.dissolved_oxygen_n.attributes.type: looks like a variable field indented under attributes",
    ]


def test_cli_suspect_and_missing(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """check warns (exit 0); check_merged warns, names missing templates, and fails if none exist."""
    path = _write(tmp_path, "seaglider.yml", MISINDENTED)
    with caplog.at_level(logging.WARNING):
        assert GliderDACModel.main(["check", str(path)]) == 0
    assert "dissolved_oxygen_n.attributes.type: looks like a variable field" in caplog.text
    caplog.clear()
    with caplog.at_level(logging.WARNING):
        assert GliderDACModel.main(["check_merged", "--config", str(_conf(tmp_path, "a.conf", [path, *DOCS_TRIPLE[1:]]))]) == 1
    assert "dissolved_oxygen_n.attributes.dimensions: looks like a variable field" in caplog.text
    assert "(type, dimensions found under attributes - mis-indented?)" in caplog.text
    caplog.clear()
    gone = [tmp_path / "x.yml", tmp_path / "y.yml", tmp_path / "z.yml"]
    with caplog.at_level(logging.WARNING):
        assert GliderDACModel.main(["check_merged", "--config", str(_conf(tmp_path, "b.conf", gone))]) == 1
    assert f"gliderdac_base_config {gone[0].resolve()} does not exist - not checked" in caplog.text
    assert "names exist - nothing to check" in caplog.text


def test_cli_merged_missing_dropped_overrides(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """check_merged skips a missing template (as GliderDAC.py does), fails on a dropped variable, logs overrides."""
    missing = tmp_path / "missing.yml"
    conf = _conf(tmp_path, "a.conf", [*DOCS_TRIPLE[:2], missing])
    with caplog.at_level(logging.INFO):
        assert GliderDACModel.main(["--verbose", "check_merged", "--config", str(conf)]) == 0
    assert f"{missing.resolve()} does not exist - skipping" in caplog.text
    partial = _write(tmp_path, "partial.yml", "variables:\n  not_in_base:\n    type: f8\n")
    conf = _conf(tmp_path, "b.conf", [*DOCS_TRIPLE[:2], partial])
    assert GliderDACModel.main(["check_merged", "--config", str(conf)]) == 1
    general = _write(tmp_path, "general.yml", "global_attributes:\n  title: general\n")
    specific = _write(tmp_path, "specific.yml", "global_attributes:\n  title: specific\n")
    conf = _conf(tmp_path, "c.conf", [general, missing, specific])
    with caplog.at_level(logging.INFO):
        assert GliderDACModel.main(["--verbose", "check_merged", "--config", str(conf)]) == 0
    assert f"{specific.resolve()}:2: global_attributes.title: overrides {general.resolve()}:2" in caplog.text


def test_check_file_unreadable_and_empty(tmp_path: pathlib.Path) -> None:
    """A path that can't be read is one problem; an empty file is a valid (empty) template."""
    loaded, problems = GliderDACModel.check_file(tmp_path)
    assert loaded is None and len(problems) == 1 and problems[0].startswith(f"{tmp_path}: could not read (")
    loaded, problems = GliderDACModel.check_file(_write(tmp_path, "empty.yml", ""))
    assert loaded is not None and loaded.data == {} and problems == []


def test_check_merged_no_templates() -> None:
    """A merged problem no template mentions is placed at "(no templates)"."""
    problems, dropped = GliderDACModel.check_merged_template({"variables": {"x_qc": {"type": "f8"}}}, [])
    assert any(d.startswith("(no templates): ") for d in problems + dropped)


def test_load_templates_alerts(tmp_path: pathlib.Path) -> None:
    """GliderDAC.load_templates: a dropped variable or a failed load raises GLIDERDAC_CONFIG."""
    from types import SimpleNamespace

    import GliderDAC

    incomplete = _write(tmp_path, "dep.yml", "variables:\n  x_n:\n    attributes: {_FillValue: -999}\n")
    opts = SimpleNamespace(
        gliderdac_base_config=DOCS_TRIPLE[0], gliderdac_project_config=DOCS_TRIPLE[1], gliderdac_deployment_config=incomplete
    )
    merged = GliderDAC.load_templates(opts)
    assert merged is not None and "x_n" not in merged["variables"]
    (alert,) = BaseLog.log_alerts()["GLIDERDAC_CONFIG"]
    assert "variables.x_n: no type, dimensions in any template - dropping this variable" in alert

    BaseLog.BaseLogger.reset()
    opts.gliderdac_deployment_config = _write(tmp_path, "bad.yml", "variables:\n  t:\n    type: f9\n")
    assert GliderDAC.load_templates(opts) is None
    alerts = BaseLog.log_alerts()["GLIDERDAC_CONFIG"]
    assert len(alerts) == 2 and "no GliderDAC output" in alerts[1]
