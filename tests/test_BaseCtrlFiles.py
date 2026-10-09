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

import json
import logging
import pathlib
from unittest.mock import MagicMock, patch

import pytest
import requests

import BaseCtrlFiles
import BaseLog

SECRET = "SECRETTOKEN"
HOOK = f"https://sahale.example.edu/mattermost/hooks/{SECRET}"


@pytest.fixture(autouse=True)
def debug_log_level():
    """BaseLog gates levels itself; let INFO/DEBUG through to caplog."""
    saved = BaseLog.BaseLogger.log_level
    BaseLog.BaseLogger.log_level = logging.DEBUG
    yield
    BaseLog.BaseLogger.log_level = saved


CONNECTION_ERROR = requests.exceptions.ConnectionError(
    "HTTPSConnectionPool(host='sahale.example.edu', port=443): Max retries exceeded "
    f"with url: /mattermost/hooks/{SECRET}"
)


@pytest.mark.parametrize(
    "send_func, endpoint",
    [
        (BaseCtrlFiles.send_mattermost, {"hook": HOOK}),
        (BaseCtrlFiles.send_slack, {"hook": HOOK}),
        (BaseCtrlFiles.send_post, {"url": HOOK}),
        (BaseCtrlFiles.send_ntfy, {"topic": f"glider-{SECRET}"}),
    ],
)
@pytest.mark.parametrize(
    "post_kwargs",
    [
        {"return_value": MagicMock(status_code=200, text="ok")},
        {"return_value": MagicMock(status_code=500, text="Internal Error")},
        {"side_effect": CONNECTION_ERROR},
        {"side_effect": RuntimeError("unexpected")},
    ],
)
def test_send_funcs_never_log_secrets(
    caplog: pytest.LogCaptureFixture, send_func, endpoint: dict, post_kwargs: dict
) -> None:
    """Hooks, post urls and ntfy topics are secrets; so is requests' error text.

    The sg274 2026-09-21 Mattermost alert carried the full hook URL from the
    INFO line, and a ConnectionError traceback carries it in its message.
    """
    send_dict = {"endpoint": endpoint, "user": "pilot", "type": "alerts"}
    with patch("requests.post", **post_kwargs), caplog.at_level("DEBUG"):
        send_func(MagicMock(vis_base_url=None), 263, send_dict, "Subject", "Body")
    assert caplog.text  # something was logged
    assert SECRET not in caplog.text


def test_send_mattermost_connection_error_is_one_line(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Mattermost being unreachable is environmental: say so, no traceback."""
    send_dict = {"endpoint": {"hook": HOOK}, "user": "pilot"}
    with patch("requests.post", side_effect=CONNECTION_ERROR), caplog.at_level("ERROR"):
        BaseCtrlFiles.send_mattermost(MagicMock(), 263, send_dict, "Subject", "Body")
    assert (
        "Error in mattermost post to https://sahale.example.edu/**** user:pilot (ConnectionError)"
        in caplog.text
    )
    assert "Traceback" not in caplog.text


def test_send_inreach_never_logs_password(caplog: pytest.LogCaptureFixture) -> None:
    send_dict = {"endpoint": {"imei": "300000000000000", "usr": "pilot", "pwd": SECRET}, "user": "pilot"}
    with caplog.at_level("DEBUG"):
        BaseCtrlFiles.send_inreach(MagicMock(), 263, send_dict, "Subject", "Body", gps_fix=None)
    assert "No valid gps fix" in caplog.text
    assert SECRET not in caplog.text


def test_pagers_validation_errors_never_log_secrets(caplog: pytest.LogCaptureFixture) -> None:
    """A bad filter logs the endpoint on every run (sg613 latepgs, 740 errors)."""
    pagers = {
        "pilot": {
            "mattermost": [{"hook": HOOK, "filters": ["latepgs"]}],
            "slack": f"https://hooks.slack.com/services/{SECRET}",
            "ntfy": [f"glider-{SECRET}"],
        }
    }
    with caplog.at_level("DEBUG"):
        BaseCtrlFiles.check_canonicalize_pagers_dict(pagers)
    assert "filter (latepgs) not in known send functions" in caplog.text
    assert SECRET not in caplog.text


# --- pagers.yml validation -------------------------------------------------


def _pagers(tmp_path: pathlib.Path, text: str, name: str = "pagers.yml") -> pathlib.Path:
    f = tmp_path / name
    f.write_text(text)
    return f


def test_check_pagers_file_drops_only_bad_entries(tmp_path: pathlib.Path) -> None:
    f = _pagers(
        tmp_path,
        "pilot:\n"
        "  status: off\n"
        "  email:\n"
        "    - {address: pilot@example.com, filters: [gps, latepgs]}\n"
        "    - {address: ok@example.com, format: html}\n"
        "  fax: [{number: 1}]\n"
        "team: [a, b]\n"
        "gps: pilot\n"
        "alerts: [pilot, 3]\n",
    )
    contents, errors, warnings = BaseCtrlFiles.check_pagers_file(f)
    assert contents == {
        "pilot": {"status": False, "email": [{"address": "ok@example.com", "format": "html"}]},
        "gps": ["pilot"],
        "alerts": ["pilot"],
    }
    assert any(e.startswith(f"{f}:4: pilot.email.0.filters.1:") and "dropping this endpoint" in e for e in errors)
    assert any(e.startswith(f"{f}:6:") and "unknown send function" in e for e in errors)
    assert any(e.startswith(f"{f}:7:") and "user team must be a mapping" in e for e in errors)
    assert any(e.startswith(f"{f}:9: alerts.1:") and "dropping this subscriber" in e for e in errors)
    assert not warnings


def test_check_pagers_file_repairs_keys_without_a_space(tmp_path: pathlib.Path) -> None:
    """{ format:html } is a key "format:html" in yaml - the old sg000 example had it (43 in production)."""
    f = _pagers(
        tmp_path,
        "pilot:\n"
        "  email: [ { address: a@b.c, format:html }, { address: q@r.s, colour: red } ]\n"
        f"  ntfy: [ {{ topic:{SECRET}, priority: [ \"critical\": 5, \"gps\": 1] }} ]\n",
    )
    contents, errors, warnings = BaseCtrlFiles.check_pagers_file(f)
    assert not errors
    assert contents["pilot"]["email"] == [{"address": "a@b.c", "format": "html"}, {"address": "q@r.s"}]
    assert contents["pilot"]["ntfy"] == [{"topic": SECRET, "priority": {"critical": 5, "gps": 1}}]
    assert any("'format:html' read as format: 'html' - add a space after the colon" in w for w in warnings)
    assert any("unknown key 'colour' ignored" in w for w in warnings)
    assert not any(SECRET in m for m in warnings + errors)


def test_check_pagers_file_dot_pagers_format(tmp_path: pathlib.Path) -> None:
    """sg267 2026: a .pagers file saved as pagers.yml - ~70 merge_dict tracebacks a day."""
    f = _pagers(tmp_path, "someone@example.com,gps,critical,alerts\nother@example.com, critical,alerts\n")
    contents, errors, _ = BaseCtrlFiles.check_pagers_file(f)
    assert contents is None
    assert errors == [
        f"{f}: not a pagers.yml mapping (got str) - it looks like .pagers format; convert it with "
        "BaseDotFiles.py pagers_to_yml - ignoring this file"
    ]


def test_check_pagers_file_yaml_error_and_empty(tmp_path: pathlib.Path) -> None:
    contents, errors, _ = BaseCtrlFiles.check_pagers_file(_pagers(tmp_path, "a: [1, 2\n"))
    assert contents is None and errors and "ignoring this pagers.yml" in errors[0]
    assert BaseCtrlFiles.check_pagers_file(_pagers(tmp_path, "# nothing\n", "empty.yml")) == ({}, [], [])


def test_check_pagers_file_dddd_warns(tmp_path: pathlib.Path) -> None:
    contents, errors, warnings = BaseCtrlFiles.check_pagers_file(
        _pagers(tmp_path, "pilot: {latlon: dddd, email: {address: a@b.c}}\n")
    )
    assert contents["pilot"]["latlon"] == "dddd" and not errors
    assert any("latlon dddd is not a position format" in w for w in warnings)


def test_load_ctrl_yml_skips_bad_file_and_merges_the_rest(tmp_path: pathlib.Path) -> None:
    etc = tmp_path / "etc"
    mission = tmp_path / "mission"
    etc.mkdir()
    mission.mkdir()
    _pagers(etc, "ops: {email: {address: ops@example.com}}\ncritical: ops\n")
    _pagers(mission, "pilot@example.com,gps,critical\n")  # .pagers format
    base_opts = MagicMock(basestation_etc=etc, group_etc=None, mission_dir=mission)
    merged = BaseCtrlFiles.load_ctrl_yml(
        base_opts, "pagers.yml", {m: [] for m in BaseCtrlFiles.pagers_msgs}, BaseCtrlFiles.validate_pagers_file
    )
    assert merged["critical"] == ["ops"]
    assert merged["ops"] == {"email": [{"address": "ops@example.com"}]}


@pytest.mark.parametrize(
    "priority, expected",
    [
        (None, {"critical": 5, "gps": 3}),  # built-in default for critical
        ('[ "critical": 4, "gps": 1 ]', {"critical": 4, "gps": 1}),  # documented list form - was ignored
        ("{gps: 2}", {"critical": 5, "gps": 2}),  # mapping, merged over the defaults
    ],
)
def test_send_ntfy_applies_priorities(priority, expected: dict) -> None:
    """The documented list form never matched: every message (critical too) went at 3."""
    import yaml

    endpoint = {"topic": "t"}
    if priority is not None:
        endpoint["priority"] = yaml.safe_load(priority)
    for msg_type, want in expected.items():
        with patch("requests.post", return_value=MagicMock(status_code=200)) as post:
            BaseCtrlFiles.send_ntfy(
                MagicMock(vis_base_url=None), 263, {"endpoint": endpoint, "user": "u", "type": msg_type}, "S", "B"
            )
        sent = json.loads(post.call_args.kwargs["data"])
        assert sent["priority"] == want, msg_type


def test_cli_check_exit_codes(tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture) -> None:
    """Results go through the logger (File.py(line) prefix), not print; no alerts from a standalone check."""
    BaseLog.BaseLogger.alerts_d = {}
    good = _pagers(tmp_path, "pilot: {email: {address: a@b.c}}\ngps: pilot\n", "good.yml")
    bad = _pagers(tmp_path, "pilot@example.com,gps\n", "bad.yml")
    with caplog.at_level(logging.INFO):
        assert BaseCtrlFiles.main(["check", "--verbose", str(good)]) == 0
        assert BaseCtrlFiles.main(["check", "--verbose", str(good), str(bad)]) == 1
    assert f"{good}: 0 error(s), 0 warning(s)" in caplog.text
    assert any(r.levelname == "ERROR" and f"{bad}: not a pagers.yml mapping" in r.getMessage() for r in caplog.records)
    assert BaseCtrlFiles.PAGERS_YML_ALERT not in BaseLog.log_alerts()


def test_cli_check_merged(
    tmp_path: pathlib.Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    BaseLog.BaseLogger.alerts_d = {}
    mission = tmp_path / "mission"
    mission.mkdir()
    _pagers(
        mission,
        f"pilot: {{slack: {{hook: https://h.example.com/hooks/{SECRET}, colour: red}}}}\ngps: pilot\nalerts: [pilot, ghost]\n",
    )
    with caplog.at_level(logging.INFO):
        assert BaseCtrlFiles.main(["check_merged", "--verbose", "--mission_dir", str(mission)]) == 1  # ghost isn't defined
    text = caplog.text
    assert text.count("unknown key 'colour' ignored") == 1  # reported once, not again by the merge
    assert text.count("User ghost") == 1
    assert "user pilot: status=True latlon=ddmm endpoints={'slack': 1}" in text
    assert SECRET not in text
    assert capsys.readouterr().out == ""  # nothing printed
    assert BaseCtrlFiles.PAGERS_YML_ALERT not in BaseLog.log_alerts()


def test_validate_pagers_file_raises_alerts_for_errors_only(tmp_path: pathlib.Path) -> None:
    """Dropped entries and ignored files reach pilots as PAGERS_YML alerts; repairs don't."""
    BaseLog.BaseLogger.alerts_d = {}
    bad = _pagers(tmp_path, "pilot: {email: [{address: a@b.c, filters: [latepgs]}]}\n", "bad.yml")
    dot = _pagers(tmp_path, "pilot@example.com,gps\n", "dot.yml")
    repaired = _pagers(tmp_path, "pilot: {email: [{address: a@b.c, format:html}]}\n", "repaired.yml")

    BaseCtrlFiles.validate_pagers_file(repaired)
    assert BaseCtrlFiles.PAGERS_YML_ALERT not in BaseLog.log_alerts()

    BaseCtrlFiles.validate_pagers_file(bad)
    BaseCtrlFiles.validate_pagers_file(dot)
    alerts = BaseLog.log_alerts()[BaseCtrlFiles.PAGERS_YML_ALERT]
    assert len(alerts) == 2
    assert alerts[0].startswith(f"ERROR: {bad}:1: pilot.email.0.filters.0:")
    assert alerts[1].startswith(f"ERROR: {dot}: not a pagers.yml mapping")
    BaseLog.BaseLogger.alerts_d = {}
