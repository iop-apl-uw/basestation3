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

import logging
from typing import Literal
from unittest.mock import MagicMock, patch

import pytest
import requests
from _pytest.logging import LogCaptureFixture

import BaseDotFiles

# Assuming your function lives in a module named BaseDotFiles
import BaseLog


@pytest.fixture
def mock_base_opts() -> MagicMock:
    """Fixture to create a dummy options instance."""
    return MagicMock()

@pytest.mark.parametrize(
    "status_code, response_text, expected_result, expected_log, log_level",
    [
        (200, "ok", 0, "instrument_id:inst_123", "INFO"),
        (400, "Bad Request", 1, "Request to slack returned an error 400", "ERROR"),
        (404, "Not Found", 1, "Request to slack returned an error 404", "ERROR"),
        (500, "Internal Error", 1, "Request to slack returned an error 500", "ERROR"),
    ]
)
def test_post_slack_status_codes(
    caplog: LogCaptureFixture,
    mock_base_opts: MagicMock,
    status_code: int,
    response_text: str,
    expected_result: Literal[0, 1],
    expected_log: str,
    log_level: str
) -> None:
    """Test various HTTP status codes and verify the function's return values and logs."""
    # Arrange
    mock_response: MagicMock = MagicMock()
    mock_response.status_code = status_code
    mock_response.text = response_text

    # Adjust the level output to be info
    save_log_level = BaseLog.BaseLogger.log_level
    BaseLog.BaseLogger.log_level = getattr(logging, log_level.upper(), logging.INFO)
    
    # Act
    with patch("requests.post", return_value=mock_response), caplog.at_level(log_level):
        result: Literal[0, 1] = BaseDotFiles.post_slack(
            base_opts=mock_base_opts,
            instrument_id="inst_123",
            slack_hook_url="https://slack.com",
            subject_line="Alert",
            message_body="System update"
        )

    BaseLog.BaseLogger.log_level = save_log_level
            
    # Assert
    assert result == expected_result
    assert expected_log in caplog.text

def test_post_slack_network_exception(
    caplog: LogCaptureFixture, 
    mock_base_opts: MagicMock
) -> None:
    """Test that a network exception returns 1 and logs the failure."""
    # Arrange & Act
    with patch("requests.post", side_effect=requests.exceptions.ConnectionError("Timeout")), caplog.at_level("ERROR"):
        result: Literal[0, 1] = BaseDotFiles.post_slack(
            base_opts=mock_base_opts,
            instrument_id="inst_123",
            slack_hook_url="https://slack.com",
            subject_line="Alert",
            message_body="Network dropping"
        )
            
    # Assert
    assert result == 1
    assert "Error in post" in caplog.text
