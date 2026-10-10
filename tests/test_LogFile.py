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

import pytest

import LogFile


@pytest.mark.parametrize(
    "parm_name,value,expected",
    (
        ("$INTERNAL_PRESSURE", "8.2", [("$INTERNAL_PRESSURE", "8.2")]),
        (
            "$INTERNAL_PRESSURE",
            "8.2,8.5",
            [("$INTERNAL_PRESSURE", "8.2"), ("$INTERNAL_PRESSURE_LATCH", "8.5")],
        ),
        (
            "$INTERNAL_PRESSURE",
            "8.2,8.5,7.9,9.1",
            [
                ("$INTERNAL_PRESSURE", "8.2"),
                ("$INTERNAL_PRESSURE_LATCH", "8.5"),
                ("$INTERNAL_PRESSURE_MIN", "7.9"),
                ("$INTERNAL_PRESSURE_MAX", "9.1"),
            ],
        ),
        ("$INTERNAL_PRESSURE", "8.2,8.5,7.9", None),
        (
            "$HUMID",
            "40.1,65,38.2,41.0",
            [
                ("$HUMID", "40.1"),
                ("$HUMID_LIMIT", "65"),
                ("$HUMID_MIN", "38.2"),
                ("$HUMID_MAX", "41.0"),
            ],
        ),
        ("$HUMID", "40.1,65", None),
    ),
)
def test_split_multi_value_parm(parm_name, value, expected):
    assert LogFile.split_multi_value_parm(parm_name, value) == expected


def test_split_multi_value_parm_unknown_parm():
    with pytest.raises(KeyError):
        LogFile.split_multi_value_parm("$D_TGT", "90")


# --- $WARN lines: counted kinds, state notices, everything else ---

_LOG_HEADER = "version: 67.01\nglider: 283\nmission: 4\ndive: 624\nstart: 10 9 126 18 27 58\ndata:\n$ID,283\n$DIVE,624\n"


@pytest.fixture
def _fresh_baselog():
    from BaseLog import BaseLogger

    BaseLogger.reset()
    yield
    BaseLogger.reset()


def _parse_warns(tmp_path, warns, monkeypatch, **kwargs):
    """Parses a log with these $WARN values.

    Returns:
        (log_file, alert tags raised, [(warning text, alert)] for the WARN:( warnings).
    """
    import BaseLog

    warnings = []

    def grab(s, *args, alert=None, **kw):
        if str(s).startswith("WARN:("):
            warnings.append((s, alert))
        BaseLog.log_warning(s, alert=alert)

    monkeypatch.setattr(LogFile, "log_warning", grab)
    log = tmp_path / "p2830624.log"
    log.write_text(_LOG_HEADER + "".join(f"$WARN,{w}\n" for w in warns))
    log_file = LogFile.parse_log_file(str(log), issue_warn=True, **kwargs)
    return log_file, sorted(BaseLog.log_alerts()), warnings


@pytest.mark.usefixtures("_fresh_baselog")
def test_warn_counted_kinds_alert_above_threshold(tmp_path, monkeypatch):
    warns = (
        ["pressure timeout"]  # 1: logged, no alert
        + ["PPS timeout"] * 4  # 4 > 3: GLIDER_TIMEOUT
        + ["2 ct parse errors", "3 ct parse errors"]  # sum 5 > 3
        + ["HSCICON missed fuel gauge read"]  # 1
        + ["tcm2mat error"] * 4  # 4 > 3
        + ["HTMICL TMICL logging already stopped"]  # state notice: no alert
        + ["spurious depths detected D_ABORT=990, D_TGT=1000"]  # one-off: always alerts
    )
    log_file, alerts, warnings = _parse_warns(tmp_path, warns, monkeypatch)
    assert log_file is not None
    assert log_file.warn == warns  # every raw value kept
    by_text = dict(warnings)
    log = tmp_path / "p2830624.log"
    assert by_text[f"WARN:(1 pressure timeout(s)) in {log} (first at line 9)"] is None
    assert by_text[f"WARN:(4 PPS timeout(s)) in {log} (first at line 10)"] == "GLIDER_TIMEOUT"
    assert by_text[f"WARN:(5 ct parse error(s)) in {log} (first at line 14)"] == "CT_PARSE_ERRORS"
    assert by_text[f"WARN:(1 SCICON missed fuel gauge read(s)) in {log} (first at line 16)"] is None
    assert by_text[f"WARN:(4 tcm2mat error(s)) in {log} (first at line 17)"] == "TCM2MAT_ERROR"
    assert by_text[f"WARN:(HTMICL TMICL logging already stopped) in {log}"] is None
    assert by_text[f"WARN:(spurious depths detected D_ABORT=990, D_TGT=1000) in {log}"] == "LOGFILE_WARN"
    # One warning per counted kind and name, not one per $WARN line
    assert len(warnings) == 7
    assert alerts == ["CT_PARSE_ERRORS", "GLIDER_TIMEOUT", "LOGFILE_WARN", "TCM2MAT_ERROR"]


@pytest.mark.usefixtures("_fresh_baselog")
def test_warn_thresholds_from_caller(tmp_path, monkeypatch):
    # Threshold 0 alerts on any; a high one silences
    _, alerts, _ = _parse_warns(tmp_path, ["pressure timeout"], monkeypatch, alert_thresholds={"glider_timeout": 0})
    assert alerts == ["GLIDER_TIMEOUT"]
    _, alerts, _ = _parse_warns(tmp_path, ["5 ct parse errors"], monkeypatch, alert_thresholds={"ct_parse_errors": 10})
    assert "CT_PARSE_ERRORS" not in alerts


@pytest.mark.usefixtures("_fresh_baselog")
def test_warn_not_issued(tmp_path):
    from BaseLog import log_alerts

    log = tmp_path / "p2830624.log"
    log.write_text(_LOG_HEADER + "$WARN,pressure timeout\n$WARN,spurious depths detected\n")
    log_file = LogFile.parse_log_file(str(log))
    assert log_file is not None and log_file.warn == [] and log_alerts() == {}


def test_warn_alert_thresholds_from_options(tmp_path):
    import BaseOpts

    base_opts = BaseOpts.BaseOptions(
        "test",
        # argparse takes str
        cmdline_args=["--mission_dir", str(tmp_path), "--glider_timeout_alert_threshold", "7"],
        calling_module="Base",
    )
    assert LogFile.warn_alert_thresholds(base_opts) == {
        "glider_timeout": 7,
        "fuel_gauge": 3,
        "ct_parse_errors": 3,
        "tcm2mat_error": 3,
    }
