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

import ctypes
import os
import pathlib
import socket
import struct
import sys
import tempfile
import threading
import uuid
from unittest import mock

import orjson
import pytest

import BaseRunnerPrivExec
import SiteConfig


@pytest.fixture
def short_socket_path():
    """A short-enough AF_UNIX socket path.

    pytest's tmp_path nests deep enough on macOS to exceed AF_UNIX's
    ~104 byte path limit, so socket-server tests need their own shallow
    path under the system temp dir instead.
    """
    path = pathlib.Path(tempfile.gettempdir()) / f"brpe-{uuid.uuid4().hex[:8]}.sock"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _recv_response(sock: socket.socket) -> dict:
    data = BaseRunnerPrivExec._recv_frame(sock)
    assert data is not None
    return orjson.loads(data)


def _make_site(tmp_path, *, uid=4242, gid=4343, name="seaglider", jail_root=None):
    watch_dir = tmp_path / name
    watch_dir.mkdir(exist_ok=True)
    return SiteConfig.SiteConfig(
        name=name,
        watch_dir=watch_dir,
        jail_root=jail_root,
        runner_user="ioprunner",
        runner_uid=uid,
        runner_gid=gid,
    )


# --- framing helpers ---


def test_send_and_recv_frame_roundtrip():
    a, b = socket.socketpair()
    try:
        BaseRunnerPrivExec._send_frame(a, b"hello world")
        assert BaseRunnerPrivExec._recv_frame(b) == b"hello world"
    finally:
        a.close()
        b.close()


def test_recv_frame_returns_none_on_early_close():
    a, b = socket.socketpair()
    try:
        a.close()
        assert BaseRunnerPrivExec._recv_frame(b) is None
    finally:
        b.close()


def test_recv_frame_returns_none_on_partial_header():
    a, b = socket.socketpair()
    try:
        a.send(b"\x00\x00")  # 2 of 4 header bytes, then close
        a.close()
        assert BaseRunnerPrivExec._recv_frame(b) is None
    finally:
        b.close()


# --- _peer_uid ---


def test_peer_uid_none_without_so_peercred(monkeypatch):
    monkeypatch.delattr(socket, "SO_PEERCRED", raising=False)
    a, b = socket.socketpair()
    try:
        assert BaseRunnerPrivExec._peer_uid(a) is None
    finally:
        a.close()
        b.close()


def test_peer_uid_reads_so_peercred(monkeypatch):
    monkeypatch.setattr(socket, "SO_PEERCRED", 17, raising=False)

    def fake_getsockopt(self, level, optname, buflen):
        return struct.pack("3i", 1234, 4242, 5555)

    monkeypatch.setattr(socket.socket, "getsockopt", fake_getsockopt)
    a, b = socket.socketpair()
    try:
        assert BaseRunnerPrivExec._peer_uid(a) == 4242
    finally:
        a.close()
        b.close()


# --- _set_child_subreaper ---


class _FakeLibc:
    def __init__(self, ret):
        self.ret = ret
        self.calls = []

    def prctl(self, *args):
        self.calls.append(args)
        return self.ret


def test_set_child_subreaper_noop_on_non_linux(monkeypatch, caplog):
    monkeypatch.setattr(sys, "platform", "darwin")
    BaseRunnerPrivExec._set_child_subreaper()
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_set_child_subreaper_success_on_linux(monkeypatch):
    monkeypatch.setattr(sys, "platform", "linux")
    fake = _FakeLibc(0)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake)
    BaseRunnerPrivExec._set_child_subreaper()
    assert fake.calls == [(36, 1, 0, 0, 0)]


def test_set_child_subreaper_failure_logs_warning(monkeypatch, caplog):
    monkeypatch.setattr(sys, "platform", "linux")
    fake = _FakeLibc(-1)
    monkeypatch.setattr(ctypes, "CDLL", lambda *a, **k: fake)
    monkeypatch.setattr(ctypes, "get_errno", lambda: 1)
    BaseRunnerPrivExec._set_child_subreaper()
    assert any(r.levelname == "WARNING" for r in caplog.records)


# --- PrivilegeDropper ---


def test_privilege_dropper_call_order(monkeypatch):
    calls = []
    monkeypatch.setattr(os, "setgroups", lambda groups: calls.append(("setgroups", groups)))
    monkeypatch.setattr(os, "setgid", lambda gid: calls.append(("setgid", gid)))
    monkeypatch.setattr(os, "setuid", lambda uid: calls.append(("setuid", uid)))
    monkeypatch.setattr(
        os, "execve", lambda path, argv, env: calls.append(("execve", path, argv, env))
    )

    BaseRunnerPrivExec.PrivilegeDropper().drop_and_exec(
        4242, 4343, ["/bin/true"], {"PATH": "/bin"}
    )

    assert calls == [
        ("setgroups", [4343]),
        ("setgid", 4343),
        ("setuid", 4242),
        ("execve", "/bin/true", ["/bin/true"], {"PATH": "/bin"}),
    ]


# --- ChildTable ---


def test_child_table_status_before_reap():
    table = BaseRunnerPrivExec.ChildTable(waitpid_fn=lambda *_: (0, 0))
    table.note_started(111)
    assert table.status(111) == (False, None)


def test_child_table_reaps_and_reports_returncode():
    responses = iter([(111, 0), (0, 0)])

    def fake_waitpid(pid, opts):
        return next(responses)

    table = BaseRunnerPrivExec.ChildTable(waitpid_fn=fake_waitpid)
    table.note_started(111)
    assert table.status(111) == (True, 0)


def test_child_table_reports_nonzero_returncode():
    # 3 << 8 encodes a normal exit with status 3.
    responses = iter([(222, 3 << 8), (0, 0)])

    def fake_waitpid(pid, opts):
        return next(responses)

    table = BaseRunnerPrivExec.ChildTable(waitpid_fn=fake_waitpid)
    table.note_started(222)
    assert table.status(222) == (True, 3)


def test_child_table_unknown_pid_raises():
    table = BaseRunnerPrivExec.ChildTable(waitpid_fn=lambda *_: (0, 0))
    with pytest.raises(KeyError):
        table.status(999)


def test_child_table_reap_stops_on_child_process_error():
    def fake_waitpid(pid, opts):
        raise ChildProcessError()

    table = BaseRunnerPrivExec.ChildTable(waitpid_fn=fake_waitpid)
    table.reap_available()  # must not raise


# --- validate_dispatch_request ---


def test_validate_dispatch_request_valid(tmp_path):
    site = _make_site(tmp_path)
    sites = {"seaglider": site}
    log_file = site.watch_dir / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(log_file)}

    req = BaseRunnerPrivExec.validate_dispatch_request(sites, request)

    assert req.site is site
    assert req.argv == ["/bin/true"]
    assert req.log_file == log_file


def test_validate_dispatch_request_unknown_site(tmp_path):
    with pytest.raises(ValueError, match="unknown site"):
        BaseRunnerPrivExec.validate_dispatch_request({}, {"site": "nope"})


def test_validate_dispatch_request_missing_site_key(tmp_path):
    with pytest.raises(ValueError, match="unknown site"):
        BaseRunnerPrivExec.validate_dispatch_request({}, {})


def test_validate_dispatch_request_bad_argv(tmp_path):
    site = _make_site(tmp_path)
    request = {"site": "seaglider", "argv": "not-a-list", "log_file": "x"}
    with pytest.raises(ValueError, match="argv"):
        BaseRunnerPrivExec.validate_dispatch_request({"seaglider": site}, request)


def test_validate_dispatch_request_empty_argv(tmp_path):
    site = _make_site(tmp_path)
    request = {"site": "seaglider", "argv": [], "log_file": "x"}
    with pytest.raises(ValueError, match="argv"):
        BaseRunnerPrivExec.validate_dispatch_request({"seaglider": site}, request)


def test_validate_dispatch_request_bad_log_file_type(tmp_path):
    site = _make_site(tmp_path)
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": 12345}
    with pytest.raises(ValueError, match="log_file must be a string"):
        BaseRunnerPrivExec.validate_dispatch_request({"seaglider": site}, request)


def test_validate_dispatch_request_log_file_outside_site_tree(tmp_path):
    site = _make_site(tmp_path)
    outside = tmp_path / "elsewhere" / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(outside)}
    with pytest.raises(ValueError, match="not contained"):
        BaseRunnerPrivExec.validate_dispatch_request({"seaglider": site}, request)


def test_validate_dispatch_request_no_roots_at_all(tmp_path):
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=tmp_path / "unused",
        jail_root=None,
        runner_user="ioprunner",
        runner_uid=1,
        runner_gid=1,
    )
    object.__setattr__(site, "watch_dir", None)
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": "/tmp/x"}
    with pytest.raises(ValueError, match="not contained"):
        BaseRunnerPrivExec.validate_dispatch_request({"seaglider": site}, request)


# --- PrivExecServer.handle_dispatch / _run_child ---


def test_handle_dispatch_success(tmp_path):
    site = _make_site(tmp_path)
    server = BaseRunnerPrivExec.PrivExecServer(
        {"seaglider": site}, mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper), fork_fn=lambda: 4242
    )
    log_file = site.watch_dir / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(log_file)}

    response = server.handle_dispatch(request)

    assert response == {"ok": True, "pid": 4242}
    assert server._children.status(4242) == (False, None)


def test_handle_dispatch_child_branch_calls_run_child(monkeypatch, tmp_path):
    site = _make_site(tmp_path)
    server = BaseRunnerPrivExec.PrivExecServer(
        {"seaglider": site},
        mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper),
        fork_fn=lambda: 0,
    )
    calls = []

    def fake_run_child(req, log_fd):
        calls.append((req, log_fd))
        raise SystemExit(0)  # _run_child never returns for real either

    monkeypatch.setattr(server, "_run_child", fake_run_child)

    log_file = site.watch_dir / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(log_file)}

    with pytest.raises(SystemExit):
        server.handle_dispatch(request)

    assert len(calls) == 1


def test_handle_dispatch_rejects_invalid_request(tmp_path, caplog):
    server = BaseRunnerPrivExec.PrivExecServer(
        {}, mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper)
    )
    response = server.handle_dispatch({"site": "nope"})
    assert response["ok"] is False
    assert "unknown site" in response["error"]


def test_handle_dispatch_log_file_open_failure(tmp_path):
    site = _make_site(tmp_path)
    server = BaseRunnerPrivExec.PrivExecServer(
        {"seaglider": site}, mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper)
    )
    # A directory that doesn't exist as a parent -> os.open raises OSError.
    bad_log_file = site.watch_dir / "no" / "such" / "dir" / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(bad_log_file)}

    response = server.handle_dispatch(request)

    assert response["ok"] is False
    assert "could not open log_file" in response["error"]


def test_handle_dispatch_fork_failure(monkeypatch, tmp_path):
    site = _make_site(tmp_path)

    def _raise_fork():
        raise OSError("out of resources")

    server = BaseRunnerPrivExec.PrivExecServer(
        {"seaglider": site},
        mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper),
        fork_fn=_raise_fork,
    )
    log_file = site.watch_dir / "baselog.log"
    request = {"site": "seaglider", "argv": ["/bin/true"], "log_file": str(log_file)}

    response = server.handle_dispatch(request)

    assert response["ok"] is False
    assert "fork failed" in response["error"]


class _ExitCalled(Exception):
    def __init__(self, code):
        super().__init__(code)
        self.code = code


def test_run_child_drops_privilege_and_exits_126(monkeypatch, tmp_path):
    dup2_calls = []
    monkeypatch.setattr(os, "dup2", lambda fd, target: dup2_calls.append((fd, target)))
    monkeypatch.setattr(os, "close", lambda fd: dup2_calls.append(("close", fd)))
    monkeypatch.setattr(os, "_exit", lambda code: (_ for _ in ()).throw(_ExitCalled(code)))

    dropper = mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper)
    site = _make_site(tmp_path)
    server = BaseRunnerPrivExec.PrivExecServer({"seaglider": site}, dropper)
    req = BaseRunnerPrivExec.DispatchRequest(
        site=site, argv=["/bin/true"], log_file=site.watch_dir / "baselog.log"
    )

    with pytest.raises(_ExitCalled) as excinfo:
        server._run_child(req, log_fd=99)

    assert excinfo.value.code == 126
    dropper.drop_and_exec.assert_called_once_with(
        site.runner_uid, site.runner_gid, ["/bin/true"], {"PATH": os.environ.get("PATH", "/usr/bin:/bin")}
    )
    assert (99, 1) in dup2_calls
    assert (99, 2) in dup2_calls


def test_run_child_exits_127_on_exception(monkeypatch, tmp_path):
    # Only fail for our synthetic log_fd - a blanket-raising fake would also
    # break pytest's own fd-capture teardown, which calls os.dup2 for real.
    real_dup2 = os.dup2

    def fake_dup2(fd, target):
        if fd == 99:
            raise OSError("dup2 fail")
        return real_dup2(fd, target)

    monkeypatch.setattr(os, "dup2", fake_dup2)
    monkeypatch.setattr(os, "_exit", lambda code: (_ for _ in ()).throw(_ExitCalled(code)))

    dropper = mock.Mock(spec=BaseRunnerPrivExec.PrivilegeDropper)
    site = _make_site(tmp_path)
    server = BaseRunnerPrivExec.PrivExecServer({"seaglider": site}, dropper)
    req = BaseRunnerPrivExec.DispatchRequest(
        site=site, argv=["/bin/true"], log_file=site.watch_dir / "baselog.log"
    )

    with pytest.raises(_ExitCalled) as excinfo:
        server._run_child(req, log_fd=99)

    assert excinfo.value.code == 127
    dropper.drop_and_exec.assert_not_called()


# --- PrivExecServer.handle_status / handle_request ---


def test_handle_status_bad_pid_type():
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    assert server.handle_status({"pid": "not-an-int"})["ok"] is False


def test_handle_status_unknown_pid():
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    response = server.handle_status({"pid": 999})
    assert response == {"ok": False, "error": "unknown pid 999"}


def test_handle_status_known_running_pid():
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    server._children.note_started(555)
    response = server.handle_status({"pid": 555})
    assert response == {"ok": True, "done": False, "returncode": None}


def test_handle_request_routes_status():
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    response = server.handle_request({"query": "status", "pid": 999})
    assert response["ok"] is False
    assert "unknown pid" in response["error"]


def test_handle_request_routes_dispatch():
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    response = server.handle_request({"site": "nope"})
    assert response["ok"] is False
    assert "unknown site" in response["error"]


# --- PrivExecServer.handle_connection ---


def test_handle_connection_rejects_wrong_peer_uid(monkeypatch, tmp_path):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: os.getuid() + 1)
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    a, b = socket.socketpair()
    try:
        BaseRunnerPrivExec._send_frame(b, orjson.dumps({"query": "status", "pid": 1}))
        server.handle_connection(a)
        b.settimeout(0.2)
        with pytest.raises((TimeoutError, OSError)):
            b.recv(4)
    finally:
        a.close()
        b.close()


def test_handle_connection_returns_early_on_no_frame(monkeypatch):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: None)
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    a, b = socket.socketpair()
    try:
        b.close()
        server.handle_connection(a)  # must not raise
    finally:
        a.close()


def test_handle_connection_invalid_json(monkeypatch):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: None)
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    a, b = socket.socketpair()
    try:
        BaseRunnerPrivExec._send_frame(b, b"not json{{{")
        server.handle_connection(a)
        response = _recv_response(b)
        assert response["ok"] is False
        assert "invalid JSON" in response["error"]
    finally:
        a.close()
        b.close()


def test_handle_connection_non_dict_request(monkeypatch):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: None)
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    a, b = socket.socketpair()
    try:
        BaseRunnerPrivExec._send_frame(b, orjson.dumps([1, 2, 3]))
        server.handle_connection(a)
        response = _recv_response(b)
        assert response["ok"] is False
        assert "must be an object" in response["error"]
    finally:
        a.close()
        b.close()


def test_handle_connection_full_roundtrip(monkeypatch):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: None)
    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    a, b = socket.socketpair()
    try:
        BaseRunnerPrivExec._send_frame(b, orjson.dumps({"query": "status", "pid": 42}))
        server.handle_connection(a)
        response = _recv_response(b)
        assert response == {"ok": False, "error": "unknown pid 42"}
    finally:
        a.close()
        b.close()


# --- PrivExecServer.serve_forever ---


def test_serve_forever_serves_one_request_then_stops(monkeypatch, short_socket_path):
    monkeypatch.setattr(BaseRunnerPrivExec, "_peer_uid", lambda conn: None)
    socket_path = short_socket_path
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)

    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    stop_event = threading.Event()
    responses = []

    def _client():
        client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        client.connect(str(socket_path))
        BaseRunnerPrivExec._send_frame(client, orjson.dumps({"query": "status", "pid": 1}))
        responses.append(_recv_response(client))
        client.close()
        stop_event.set()

    thread = threading.Thread(target=_client)
    thread.start()
    server.serve_forever(listener, stop_event)
    thread.join(timeout=5)
    listener.close()

    assert responses == [{"ok": False, "error": "unknown pid 1"}]


def test_main_returns_1_on_bad_sites_config(monkeypatch, tmp_path):
    bad_config = tmp_path / "sites.yaml"
    bad_config.write_text("[\n")  # syntactically invalid YAML
    monkeypatch.setattr(
        sys, "argv", ["BaseRunnerPrivExec.py", "--sites_config", str(bad_config)]
    )
    assert BaseRunnerPrivExec.main() == 1


def test_serve_forever_reaps_on_accept_timeout(monkeypatch, short_socket_path):
    socket_path = short_socket_path
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)

    server = BaseRunnerPrivExec.PrivExecServer({}, mock.Mock())
    reap_calls = []
    monkeypatch.setattr(server._children, "reap_available", lambda: reap_calls.append(1))

    stop_event = threading.Event()

    def _stop_soon():
        import time

        time.sleep(1.5)
        stop_event.set()

    thread = threading.Thread(target=_stop_soon)
    thread.start()
    server.serve_forever(listener, stop_event)
    thread.join(timeout=5)
    listener.close()

    assert reap_calls  # at least one timeout-triggered reap happened
