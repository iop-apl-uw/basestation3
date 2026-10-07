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

import logging
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
