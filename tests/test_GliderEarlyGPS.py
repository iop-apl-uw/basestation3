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

from pathlib import Path
from unittest.mock import MagicMock

import pytest
import testutils

import GliderEarlyGPS


def _make_base_opts(tmp_path: Path) -> MagicMock:
    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    base_opts.path_to_logout = None
    base_opts.base_backup = False
    base_opts.csh_pid = 12345
    base_opts.instrument_id = "sg179"
    return base_opts


def _make_client(
    tmp_path: Path, base_opts: MagicMock, known_files: list[str] | None = None
) -> GliderEarlyGPS.GliderEarlyGPSClient:
    return GliderEarlyGPS.GliderEarlyGPSClient(
        tmp_path / "comm.log", base_opts, known_files or []
    )


def _fake_run_cmd_shell_result() -> tuple[int, MagicMock]:
    fo = MagicMock()
    fo.readline.return_value = b"2026-07-30T00:00:00Z\n"
    return (0, fo)


def test_closeout_session_fallback_removes_connected_and_appends_commlog(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for the exixts() typo - closeout_session's fallback path
    must run to completion (not raise) and perform its cleanup."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts)

    connected_file = tmp_path / ".connected"
    connected_file.touch()

    monkeypatch.setattr(
        GliderEarlyGPS.Utils,
        "run_cmd_shell",
        MagicMock(return_value=_fake_run_cmd_shell_result()),
    )

    client.closeout_session()

    assert not connected_file.exists()
    comm_log_text = (tmp_path / "comm.log").read_text()
    assert "Disconnected at" in comm_log_text
    assert "(shell_disappeared)" in comm_log_text


def test_closeout_session_fallback_when_connected_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Same fallback path, but with no .connected file present - exercises the
    False branch of the fixed .exists() check."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts)

    monkeypatch.setattr(
        GliderEarlyGPS.Utils,
        "run_cmd_shell",
        MagicMock(return_value=_fake_run_cmd_shell_result()),
    )

    client.closeout_session()

    comm_log_text = (tmp_path / "comm.log").read_text()
    assert "Disconnected at" in comm_log_text
    assert "(shell_disappeared)" in comm_log_text


def test_closeout_session_logout_script_branch_returns_early(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """When path_to_logout is configured and exists, closeout_session should
    run the logout script and return before touching .connected/comm.log."""
    base_opts = _make_base_opts(tmp_path)
    logout_script = tmp_path / ".logout"
    logout_script.touch()
    base_opts.path_to_logout = logout_script
    client = _make_client(tmp_path, base_opts)

    connected_file = tmp_path / ".connected"
    connected_file.touch()
    comm_log_file = tmp_path / "comm.log"
    comm_log_file.write_text("sentinel\n")

    monkeypatch.setattr(
        GliderEarlyGPS.Utils,
        "run_cmd_shell",
        MagicMock(return_value=_fake_run_cmd_shell_result()),
    )

    client.closeout_session()

    assert connected_file.exists()
    assert comm_log_file.read_text() == "sentinel\n"


def test_callback_received_no_session_does_not_raise(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for the unguarded self._commlog_session access in
    callback_received - must not raise when no session is active."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts, known_files=["scicon.eng"])
    client._first_time = False
    client._commlog_session = None

    (tmp_path / "scicon.eng").touch()

    copyfile_mock = MagicMock()
    monkeypatch.setattr(GliderEarlyGPS.shutil, "copyfile", copyfile_mock)
    log_error_mock = MagicMock()
    monkeypatch.setattr(GliderEarlyGPS, "log_error", log_error_mock)

    client.callback_received("scicon.eng", 100)

    copyfile_mock.assert_not_called()
    assert any(
        "Could not find a dive number" in str(call.args[0])
        for call in log_error_mock.call_args_list
    )


def test_run_survives_missing_session_and_calls_closeout_at_threshold(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Direct regression test for the reported production crash: comm.log
    unreadable (session stays None) combined with the login shell having gone
    away must not raise, and closeout_session must still fire once the
    shell-missing threshold is reached."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts)
    assert client._commlog_session is None

    monkeypatch.setattr(
        client, "process_comm_log_wrapper", MagicMock(return_value=0)
    )
    monkeypatch.setattr(GliderEarlyGPS.Utils, "check_for_pid", lambda pid: False)
    closeout_mock = MagicMock()
    monkeypatch.setattr(client, "closeout_session", closeout_mock)
    log_info_mock = MagicMock()
    monkeypatch.setattr(GliderEarlyGPS, "log_info", log_info_mock)
    monkeypatch.setattr(
        GliderEarlyGPS.time,
        "sleep",
        MagicMock(side_effect=[None, None, None, KeyboardInterrupt]),
    )

    result = client.run()

    assert result is True
    closeout_mock.assert_called_once()
    assert any(
        "logout_seen:unknown - no session" in str(call.args[0])
        for call in log_info_mock.call_args_list
    )


def test_run_bails_out_after_repeated_unexpected_exceptions(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """After more than 5 consecutive unexpected exceptions, run() should give
    up and call cleanup_shutdown() rather than looping forever."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts)

    monkeypatch.setattr(
        client,
        "process_comm_log_wrapper",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    monkeypatch.setattr(GliderEarlyGPS, "log_error", MagicMock())
    monkeypatch.setattr(
        GliderEarlyGPS.time,
        "sleep",
        MagicMock(side_effect=[None, None, None, None, None, KeyboardInterrupt]),
    )
    cleanup_shutdown_mock = MagicMock()
    monkeypatch.setattr(client, "cleanup_shutdown", cleanup_shutdown_mock)

    result = client.run()

    assert result is True
    cleanup_shutdown_mock.assert_called_once()


def test_process_comm_log_wrapper_dispatches_received_for_extension_known_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for process_comm_log_wrapper not forwarding known_files
    to CommLog.process_comm_log as known_commlog_files. Without that, CommLog
    falls back to its own hardcoded default (cmdfile/science/targets/
    pdoscmds.bat), so a file registered only via a sensor extension - here
    modeled on tcm2mat.cal, one of the entries in Globals.known_files - gets
    dispatched as callback_transfered instead of callback_received when it's
    sent via X/YMODEM (the only path in CommLog.py gated by that list; the
    raw-send path dispatches callback_received unconditionally, so a raw
    example wouldn't exercise this bug)."""
    base_opts = _make_base_opts(tmp_path)
    comm_log_file = tmp_path / "comm.log"
    comm_log_file.write_text(
        "Connected at 2026-08-08T11:21:07Z (sg180)\n"
        "logged in\n"
        "ver=67.01,rev=7538:7540M,frag=8,launch=040826:133554\n"
        "2026-08-08T11:22:30Z [sg180] Sent 392 bytes of tcm2mat.cal/YMODEM: 512 Bytes, 50 BPS\n"
    )

    calls: list[tuple[str, str, int]] = []

    def fake_received(self, filename, size):
        calls.append(("received", filename, size))

    def fake_transfered(self, filename, size):
        calls.append(("transfered", filename, size))

    monkeypatch.setattr(
        GliderEarlyGPS.GliderEarlyGPSClient, "callback_received", fake_received
    )
    monkeypatch.setattr(
        GliderEarlyGPS.GliderEarlyGPSClient, "callback_transfered", fake_transfered
    )

    client = _make_client(tmp_path, base_opts, known_files=["tcm2mat.cal"])
    client._first_time = False

    assert client.process_comm_log_wrapper() == 0
    assert calls == [("received", "tcm2mat.cal", 392)]


def test_run_survives_unexpected_exception_in_loop(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for the widened exception handling in run(): an
    unforeseen exception in the loop body must be logged and the loop should
    keep going rather than killing the whole monitor."""
    base_opts = _make_base_opts(tmp_path)
    client = _make_client(tmp_path, base_opts)

    monkeypatch.setattr(
        client,
        "process_comm_log_wrapper",
        MagicMock(side_effect=RuntimeError("boom")),
    )
    log_error_mock = MagicMock()
    monkeypatch.setattr(GliderEarlyGPS, "log_error", log_error_mock)
    monkeypatch.setattr(
        GliderEarlyGPS.time,
        "sleep",
        MagicMock(side_effect=[None, KeyboardInterrupt]),
    )

    result = client.run()

    assert result is True
    assert (
        sum(
            1
            for call in log_error_mock.call_args_list
            if "Unexpected error in main processing loop" in str(call.args[0])
        )
        >= 2
    )


def test_generate_upload_files_writes_manifest(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """generate_upload_files() should write upload_files listing base_files
    and extension known_files that actually exist in mission_dir, and skip
    ones that don't - formerly BaseLogin.main()'s job."""
    base_opts = _make_base_opts(tmp_path)
    base_opts.pre_login_timeout = 3

    run_extension_script_mock = MagicMock()
    process_extensions_mock = MagicMock()
    monkeypatch.setattr(
        GliderEarlyGPS.BaseDotFiles, "run_extension_script", run_extension_script_mock
    )
    monkeypatch.setattr(
        GliderEarlyGPS.BaseDotFiles, "process_extensions", process_extensions_mock
    )

    (tmp_path / "targets").touch()
    (tmp_path / "science").touch()
    (tmp_path / "custom_known_file.dat").touch()

    init_dict = {
        "some_ext": {"known_files": ["custom_known_file.dat", "missing_file.dat"]},
    }

    ret_val = GliderEarlyGPS.generate_upload_files(base_opts, init_dict)

    assert ret_val == 0
    run_extension_script_mock.assert_called_once_with(
        base_opts, ".pre_login", None, base_opts.pre_login_timeout
    )
    process_extensions_mock.assert_called_once_with(("prelogin",), base_opts)

    upload_files_content = (tmp_path / "upload_files").read_text()
    assert "T" in upload_files_content
    assert "S" in upload_files_content
    assert "custom_known_file.dat" in upload_files_content
    assert "missing_file.dat" not in upload_files_content


def test_process_counter_line_fires_notifications_when_not_first_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Regression test for a real bug: a client constructed with
    first_time=False must actually fire the pager/extension notification
    calls in process_counter_line. The now-removed comm_log/testing replay
    path never set first_time=False, so those calls were silently skipped
    even though the path existed to validate exactly this."""
    base_opts = _make_base_opts(tmp_path)
    base_opts.instrument_id = 179
    client = GliderEarlyGPS.GliderEarlyGPSClient(
        tmp_path / "comm.log", base_opts, [], first_time=False
    )

    process_extensions_mock = MagicMock()
    process_pagers_mock = MagicMock()
    process_pagers_yml_mock = MagicMock()
    monkeypatch.setattr(
        GliderEarlyGPS.BaseDotFiles, "process_extensions", process_extensions_mock
    )
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_pagers", process_pagers_mock)
    monkeypatch.setattr(
        GliderEarlyGPS.BaseCtrlFiles, "process_pagers_yml", process_pagers_yml_mock
    )
    monkeypatch.setattr(GliderEarlyGPS.BaseDB, "addSession", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_urls", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.Utils, "notifyVis", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.Utils, "ddmm2dd", lambda v: 0.0)
    monkeypatch.setattr(GliderEarlyGPS.Utils, "format_lat_lon_dd", lambda *a, **kw: "0")
    monkeypatch.setattr(GliderEarlyGPS.time, "mktime", lambda t: 0.0)

    session = MagicMock()
    session.gps_fix = MagicMock()
    session.dive_num = 5
    session.logout_seen = True
    session.sg_id = "sg179"
    session.to_message_dict.return_value = {}

    client.process_counter_line(session, force=True)

    process_extensions_mock.assert_called_once_with(
        ("commloggps",), base_opts, session=session
    )
    process_pagers_mock.assert_called_once_with(
        base_opts, session.sg_id, ("gps",), session=session
    )
    process_pagers_yml_mock.assert_called_once_with(
        base_opts, session.sg_id, ("gps",), session=session
    )


def test_process_counter_line_skips_notifications_when_first_time(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Companion to the test above: the default first_time=True (the live
    daemon path's first callback, before run() clears it) must still skip
    the notification calls - confirms the fix didn't just make it fire
    unconditionally."""
    base_opts = _make_base_opts(tmp_path)
    base_opts.instrument_id = 179
    client = _make_client(tmp_path, base_opts)

    process_extensions_mock = MagicMock()
    monkeypatch.setattr(
        GliderEarlyGPS.BaseDotFiles, "process_extensions", process_extensions_mock
    )
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_pagers", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseCtrlFiles, "process_pagers_yml", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseDB, "addSession", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_urls", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.Utils, "notifyVis", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.Utils, "ddmm2dd", lambda v: 0.0)
    monkeypatch.setattr(GliderEarlyGPS.Utils, "format_lat_lon_dd", lambda *a, **kw: "0")
    monkeypatch.setattr(GliderEarlyGPS.time, "mktime", lambda t: 0.0)

    session = MagicMock()
    session.gps_fix = MagicMock()
    session.dive_num = 5
    session.logout_seen = True
    session.sg_id = "sg179"
    session.to_message_dict.return_value = {}

    client.process_counter_line(session, force=True)

    process_extensions_mock.assert_not_called()


def test_replay_last_session_main_fires_notifications(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    """Integration-style smoke test against a real fixture comm.log:
    replay_last_session_main() should process the actual last session and
    fire the notification pipeline, not just parse the file and return 0
    without doing anything (the bug this replaces)."""
    data_dir = Path("testdata/sg236_NANOOS_May23_hooks")
    mission_dir = tmp_path / "mission_dir"

    process_extensions_mock = MagicMock()
    monkeypatch.setattr(
        GliderEarlyGPS.BaseDotFiles, "process_extensions", process_extensions_mock
    )
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_pagers", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseCtrlFiles, "process_pagers_yml", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseDB, "addSession", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.BaseDotFiles, "process_urls", MagicMock())
    monkeypatch.setattr(GliderEarlyGPS.Utils, "notifyVis", MagicMock())

    testutils.run_mission(
        data_dir,
        mission_dir,
        GliderEarlyGPS.replay_last_session_main,
        [str(mission_dir / "comm.log")],
        caplog,
        allowed_msgs=[],
    )

    process_extensions_mock.assert_called_once()
