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
import os
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


# --- process_ftp_line / process_sftp_line / process_ftp -------------------


@pytest.fixture
def ftp_base_opts(tmp_path) -> MagicMock:
    """Fixture with a real mission_dir containing a file to send.

    The "file_test.eng" ftp/sftp tag matches this file via a filesystem
    glob against base_opts.mission_dir, so mission_dir has to be real.
    """
    (tmp_path / "test.eng").write_text("data")
    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    return base_opts


FTP_LINE = "someone:passwd@ftp.example.com/remote/path,file_test.eng"


def test_process_ftp_line_plain_ftp_success(ftp_base_opts: MagicMock) -> None:
    """Plain (non-TLS) FTP should use FTP, not FTP_TLS, and send the matched file."""
    mock_ftp = MagicMock()
    with (
        patch("BaseDotFiles.FTP", return_value=mock_ftp) as mock_ftp_cls,
        patch("BaseDotFiles.FTP_TLS") as mock_ftp_tls_cls,
    ):
        result = BaseDotFiles.process_ftp_line(
            ftp_base_opts, [], None, None, FTP_LINE, []
        )

    assert result == 0
    mock_ftp_cls.assert_called_once_with(timeout=30)
    mock_ftp_tls_cls.assert_not_called()
    mock_ftp.connect.assert_called_once_with(host="ftp.example.com")
    mock_ftp.login.assert_called_once_with("someone", "passwd")
    mock_ftp.storbinary.assert_called_once()
    assert mock_ftp.storbinary.call_args.args[0] == "STOR test.eng"
    mock_ftp.quit.assert_called_once()
    mock_ftp.auth.assert_not_called()
    mock_ftp.prot_p.assert_not_called()


def test_process_ftp_line_ftps_success(ftp_base_opts: MagicMock) -> None:
    """use_ftps=True should use FTP_TLS and negotiate TLS on both channels."""
    mock_ftp_tls = MagicMock()
    with (
        patch("BaseDotFiles.FTP_TLS", return_value=mock_ftp_tls) as mock_ftp_tls_cls,
        patch("BaseDotFiles.FTP") as mock_ftp_cls,
    ):
        result = BaseDotFiles.process_ftp_line(
            ftp_base_opts, [], None, None, FTP_LINE, [], use_ftps=True
        )

    assert result == 0
    mock_ftp_tls_cls.assert_called_once_with(timeout=30)
    mock_ftp_cls.assert_not_called()
    mock_ftp_tls.auth.assert_called_once()
    mock_ftp_tls.login.assert_called_once_with("someone", "passwd")
    mock_ftp_tls.prot_p.assert_called_once()
    mock_ftp_tls.storbinary.assert_called_once()
    mock_ftp_tls.quit.assert_called_once()


def test_process_ftp_line_ftps_auth_failure_aborts(
    caplog: LogCaptureFixture, ftp_base_opts: MagicMock
) -> None:
    """If the TLS upgrade of the control channel fails, abort rather than fall back to plaintext."""
    mock_ftp_tls = MagicMock()
    mock_ftp_tls.auth.side_effect = Exception("TLS not supported")

    with (
        patch("BaseDotFiles.FTP_TLS", return_value=mock_ftp_tls),
        caplog.at_level("ERROR"),
    ):
        result = BaseDotFiles.process_ftp_line(
            ftp_base_opts, [], None, None, FTP_LINE, [], use_ftps=True
        )

    assert result == 1
    assert "Unable to negotiate TLS" in caplog.text
    mock_ftp_tls.login.assert_not_called()
    mock_ftp_tls.storbinary.assert_not_called()


def test_process_ftp_line_ftps_prot_p_failure_continues(
    caplog: LogCaptureFixture, ftp_base_opts: MagicMock
) -> None:
    """A failure securing just the data channel is a warning, not a hard failure."""
    mock_ftp_tls = MagicMock()
    mock_ftp_tls.prot_p.side_effect = Exception("no PROT support")

    with (
        patch("BaseDotFiles.FTP_TLS", return_value=mock_ftp_tls),
        caplog.at_level("WARNING"),
    ):
        result = BaseDotFiles.process_ftp_line(
            ftp_base_opts, [], None, None, FTP_LINE, [], use_ftps=True
        )

    assert result == 0
    assert "Could not secure data channel" in caplog.text
    mock_ftp_tls.storbinary.assert_called_once()


@pytest.fixture
def known_hosts_file(tmp_path) -> "os.PathLike[str]":
    f = tmp_path / "known_hosts"
    f.write_text("")
    return f


def test_process_sftp_line_success(ftp_base_opts: MagicMock, known_hosts_file) -> None:
    mock_sftp = MagicMock()
    mock_client = MagicMock()
    mock_client.open_sftp.return_value = mock_sftp

    sftp_line = f"host.example.com,someuser,somepass,,{known_hosts_file},,remote/dir,file_test.eng"

    with patch("BaseDotFiles.paramiko.SSHClient", return_value=mock_client):
        result = BaseDotFiles.process_sftp_line(
            ftp_base_opts, [], None, None, sftp_line, []
        )

    assert result == 0
    mock_client.load_host_keys.assert_called_once_with(str(known_hosts_file))
    mock_client.connect.assert_called_once_with(
        "host.example.com",
        port=22,
        username="someuser",
        password="somepass",
        key_filename=None,
    )
    mock_sftp.put.assert_called_once_with(
        ftp_base_opts.mission_dir / "test.eng",
        os.path.join("remote/dir", "test.eng"),
    )
    mock_client.close.assert_called_once()


def test_process_sftp_line_incomplete_spec(ftp_base_opts: MagicMock) -> None:
    """Fewer than 7 comma-separated fields is a malformed line, not a connect attempt."""
    result = BaseDotFiles.process_sftp_line(
        ftp_base_opts, [], None, None, "host.example.com,someuser", []
    )
    assert result == 1


def test_process_sftp_line_connect_failure(
    caplog: LogCaptureFixture, ftp_base_opts: MagicMock, known_hosts_file
) -> None:
    mock_client = MagicMock()
    mock_client.connect.side_effect = Exception("connection refused")

    sftp_line = f"host.example.com,someuser,somepass,,{known_hosts_file},,remote/dir,file_test.eng"

    with (
        patch("BaseDotFiles.paramiko.SSHClient", return_value=mock_client),
        caplog.at_level("ERROR"),
    ):
        result = BaseDotFiles.process_sftp_line(
            ftp_base_opts, [], None, None, sftp_line, []
        )

    assert result == 1
    assert "Could not connect" in caplog.text


def test_process_ftp_dispatch_selects_line_processor_and_type(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    """process_ftp() must route .ftp/.sftp/.ftps to the right handler, with .ftps using use_ftps=True."""
    base_opts = MagicMock()
    base_opts.basestation_etc = tmp_path / "etc"
    base_opts.basestation_etc.mkdir()
    base_opts.group_etc = None
    base_opts.mission_dir = tmp_path / "mission"
    base_opts.mission_dir.mkdir()

    calls = []

    def fake_ftp_line(
        base_opts,
        processed_file_names,
        mission_timeseries_name,
        mission_profile_name,
        ftp_line,
        known_ftp_tags,
        use_ftps=False,
    ):
        calls.append(("ftp", ftp_line.strip(), use_ftps))
        return 0

    def fake_sftp_line(
        base_opts,
        processed_file_names,
        mission_timeseries_name,
        mission_profile_name,
        sftp_line,
        known_ftp_tags,
    ):
        calls.append(("sftp", sftp_line.strip()))
        return 0

    monkeypatch.setattr(BaseDotFiles, "process_ftp_line", fake_ftp_line)
    monkeypatch.setattr(BaseDotFiles, "process_sftp_line", fake_sftp_line)

    (base_opts.mission_dir / ".ftp").write_text("plainhost/path,nc\n")
    (base_opts.mission_dir / ".sftp").write_text("host,user,pwd,,,,path,nc\n")
    (base_opts.mission_dir / ".ftps").write_text("secure.host/path,nc\n")

    assert BaseDotFiles.process_ftp(base_opts, [], None, None, [], ftp_type=".ftp") == 0
    assert (
        BaseDotFiles.process_ftp(base_opts, [], None, None, [], ftp_type=".sftp") == 0
    )
    assert (
        BaseDotFiles.process_ftp(base_opts, [], None, None, [], ftp_type=".ftps") == 0
    )

    assert ("ftp", "plainhost/path,nc", False) in calls
    assert ("sftp", "host,user,pwd,,,,path,nc") in calls
    assert ("ftp", "secure.host/path,nc", True) in calls


def test_process_ftp_unsupported_type(caplog: LogCaptureFixture) -> None:
    base_opts = MagicMock()
    with caplog.at_level("ERROR"):
        result = BaseDotFiles.process_ftp(
            base_opts, [], None, None, [], ftp_type=".bogus"
        )
    assert result == 1
    assert "Unsupported ftp type" in caplog.text
