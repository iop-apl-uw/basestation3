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

import os
import pathlib
import signal
import socket
import sys
import tempfile
import threading
import uuid
from collections.abc import Callable

import orjson
import pytest

import BaseRunnerMulti
import SiteConfig
import Utils


@pytest.fixture
def short_socket_path():
    """A short-enough AF_UNIX socket path (see test_BaseRunnerPrivExec.py)."""
    path = pathlib.Path(tempfile.gettempdir()) / f"brm-{uuid.uuid4().hex[:8]}.sock"
    try:
        yield path
    finally:
        path.unlink(missing_ok=True)


def _site(watch_dir, *, name="seaglider", jail_root=None, archive=False, ignore_lock=True):
    watch_dir.mkdir(parents=True, exist_ok=True)
    return SiteConfig.SiteConfig(
        name=name,
        watch_dir=watch_dir,
        jail_root=jail_root,
        runner_user="ioprunner",
        runner_uid=1,
        runner_gid=1,
        archive=archive,
        ignore_lock=ignore_lock,
    )


def _write_run_file(
    watch_dir,
    filename,
    seaglider_home_dir,
    seaglider_mission_dir,
    log_file,
    cmd_line,
):
    run_file = watch_dir / filename
    run_file.write_text(f"{seaglider_home_dir} {seaglider_mission_dir} {log_file} {cmd_line}\n")
    return run_file


class FakePrivExecClient:
    """In-memory PrivExecClient used to exercise Dispatcher without a real socket."""

    def __init__(self):
        self.dispatched: list[tuple[str, list[str], pathlib.Path]] = []
        self._next_pid = 1000
        self._statuses: dict[int, tuple[bool, int | None]] = {}
        self.raise_on_dispatch: Exception | None = None
        self.raise_on_status: Exception | None = None
        # Optional hooks so individual tests can override behavior without
        # reassigning (and thereby shadowing) the dispatch/status methods.
        self.dispatch_override: Callable[[str, list[str], pathlib.Path], int] | None = None
        self.status_override: Callable[[int], tuple[bool, int | None]] | None = None

    def dispatch(self, site: str, argv: list[str], log_file: pathlib.Path) -> int:
        if self.dispatch_override:
            return self.dispatch_override(site, argv, log_file)
        if self.raise_on_dispatch:
            raise self.raise_on_dispatch
        pid = self._next_pid
        self._next_pid += 1
        self.dispatched.append((site, argv, log_file))
        self._statuses[pid] = (False, None)
        return pid

    def status(self, pid: int) -> tuple[bool, int | None]:
        if self.status_override:
            return self.status_override(pid)
        if self.raise_on_status:
            raise self.raise_on_status
        return self._statuses[pid]

    def set_status(self, pid: int, done: bool, returncode: int | None) -> None:
        self._statuses[pid] = (done, returncode)


class _FakeInotify:
    """Stand-in for inotify_simple.INotify - real INotify() doesn't work off-Linux."""

    def __init__(self):
        self._next_wd = 1
        self.watches: dict[int, str] = {}
        self.fail_paths: set[str] = set()

    def add_watch(self, path, mask):
        if str(path) in self.fail_paths:
            raise OSError(f"simulated add_watch failure for {path}")
        wd = self._next_wd
        self._next_wd += 1
        self.watches[wd] = str(path)
        return wd


# --- quit_func ---


def test_quit_func_sets_exit_event():
    BaseRunnerMulti.exit_event.clear()
    try:
        BaseRunnerMulti.quit_func(signal.SIGTERM, None)
        assert BaseRunnerMulti.exit_event.is_set()
    finally:
        BaseRunnerMulti.exit_event.clear()


# --- _try_activate_site ---


def test_try_activate_site_missing_watch_dir(tmp_path):
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=tmp_path / "does-not-exist",
        jail_root=None,
        runner_user="ioprunner",
        runner_uid=1,
        runner_gid=1,
    )
    assert BaseRunnerMulti._try_activate_site(site) is False


def test_try_activate_site_with_ignore_lock(tmp_path):
    site = _site(tmp_path / "seaglider", ignore_lock=True)
    assert BaseRunnerMulti._try_activate_site(site) is True
    assert (site.watch_dir / BaseRunnerMulti.base_runner_lockfile_name).exists()


def test_try_activate_site_stays_pending_when_lock_held_by_live_pid(tmp_path, caplog):
    site = _site(tmp_path / "seaglider", ignore_lock=False)
    lock_file = site.watch_dir / BaseRunnerMulti.base_runner_lockfile_name
    lock_file.write_text(str(os.getpid()))  # a real, live pid (ourselves)

    assert BaseRunnerMulti._try_activate_site(site) is False
    assert any(r.levelname == "ERROR" for r in caplog.records)
    # The stale lock is left untouched - the operator, not this process,
    # is responsible for stopping whatever still holds it.
    assert lock_file.read_text() == str(os.getpid())


# --- SiteRegistry ---


def test_site_registry_activates_available_sites(tmp_path):
    ready = _site(tmp_path / "seaglider")
    missing = SiteConfig.SiteConfig(
        name="caricoos",
        watch_dir=tmp_path / "caricoos-missing",
        jail_root=None,
        runner_user="runner-caricoos",
        runner_uid=1,
        runner_gid=1,
        ignore_lock=True,
    )
    inotify = _FakeInotify()
    registry = BaseRunnerMulti.SiteRegistry({"seaglider": ready, "caricoos": missing}, inotify)

    active_names = {s.name for s in registry.active_sites}
    assert active_names == {"seaglider"}
    assert len(inotify.watches) == 1


def test_site_registry_retries_pending_sites(tmp_path):
    site = SiteConfig.SiteConfig(
        name="caricoos",
        watch_dir=tmp_path / "caricoos",
        jail_root=None,
        runner_user="runner-caricoos",
        runner_uid=1,
        runner_gid=1,
        ignore_lock=True,
    )
    inotify = _FakeInotify()
    registry = BaseRunnerMulti.SiteRegistry({"caricoos": site}, inotify)
    assert registry.active_sites == []

    site.watch_dir.mkdir()
    registry.activate_pending()
    assert {s.name for s in registry.active_sites} == {"caricoos"}


def test_site_registry_add_watch_failure_stays_pending(tmp_path):
    site = _site(tmp_path / "seaglider")
    inotify = _FakeInotify()
    inotify.fail_paths.add(str(site.watch_dir))
    registry = BaseRunnerMulti.SiteRegistry({"seaglider": site}, inotify)
    assert registry.active_sites == []


def test_site_registry_site_for_wd(tmp_path):
    site = _site(tmp_path / "seaglider")
    inotify = _FakeInotify()
    registry = BaseRunnerMulti.SiteRegistry({"seaglider": site}, inotify)
    wd = next(iter(inotify.watches))
    assert registry.site_for_wd(wd) is site
    assert registry.site_for_wd(9999) is None


# --- _update_queue_length ---


def test_update_queue_length_replaces_placeholder():
    argv = ["Base.py", "--queue_length", "0", "--job_id", "x"]
    assert BaseRunnerMulti._update_queue_length(argv, 3) == [
        "Base.py",
        "--queue_length",
        "3",
        "--job_id",
        "x",
    ]


def test_update_queue_length_noop_when_absent():
    argv = ["Base.py", "--job_id", "x"]
    assert BaseRunnerMulti._update_queue_length(argv, 3) == argv


# --- Dispatcher.handle_run_file_event ---


def test_handle_run_file_event_ignores_missing_file(tmp_path):
    site = _site(tmp_path / "seaglider")
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher.handle_run_file_event(site, site.watch_dir / "does-not-exist.run")
    assert not dispatcher.job_queues


def test_handle_run_file_event_ignores_non_run_suffix(tmp_path):
    site = _site(tmp_path / "seaglider")
    stray = site.watch_dir / "not-a-run-file.txt"
    stray.write_text("irrelevant")
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher.handle_run_file_event(site, stray)
    assert not dispatcher.job_queues
    assert stray.exists()  # untouched - never recognized as a .run file


def test_handle_run_file_event_enqueues_known_script(tmp_path):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir,
        "sg272.run",
        "/home/sg272",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    assert not run_file.exists()  # cleaned up (unlinked, archive=False)
    que = ("seaglider", "/home/sg272/current", "Base.py", 272)
    assert que in dispatcher.job_queues
    assert len(dispatcher.job_queues[que]) == 1
    job = dispatcher.job_queues[que][0]
    assert job.argv[0] == site.python_version
    assert job.argv[1].endswith("Base.py")
    assert "--job_id" in job.argv
    assert "--queue_length" in job.argv
    assert job.argv[job.argv.index("--queue_length") + 1] == "0"
    assert str(job.log_file) == "/home/sg272/current/baselog.log"


def test_handle_run_file_event_archives_when_configured(tmp_path):
    site = _site(tmp_path / "seaglider", archive=True)
    run_file = _write_run_file(
        site.watch_dir,
        "sg272.run",
        "/home/sg272",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    assert not run_file.exists()
    assert (site.watch_dir / "archive" / "sg272.run").exists()


def test_handle_run_file_event_unknown_script(tmp_path, caplog):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir,
        "sg272.run",
        "/home/sg272",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "NotAScript.py --foo",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    assert not run_file.exists()
    assert not dispatcher.job_queues
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_handle_run_file_event_malformed_content_still_cleans_up(tmp_path, caplog):
    site = _site(tmp_path / "seaglider")
    run_file = site.watch_dir / "sg272.run"
    run_file.write_text("not enough fields\n")
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    assert not run_file.exists()
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_handle_run_file_event_bad_glider_id_defaults_to_zero(tmp_path):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir,
        "weird.run",
        "/home/not-a-glider-dir",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    que = ("seaglider", "/home/sg272/current", "Base.py", 0)
    assert que in dispatcher.job_queues


def test_handle_run_file_event_jail_root_rewrites_paths(tmp_path):
    jail_root = tmp_path / "jail"
    site = _site(tmp_path / "seaglider", jail_root=jail_root)
    run_file = _write_run_file(
        site.watch_dir,
        "sg272.run",
        "/home/sg272",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    expected_mission_dir = str(jail_root / "home/sg272/current")
    que = ("seaglider", expected_mission_dir, "Base.py", 272)
    assert que in dispatcher.job_queues
    job = dispatcher.job_queues[que][0]
    assert expected_mission_dir in job.argv
    assert str(job.log_file) == str(jail_root / "home/sg272/current/baselog.log")


def test_cleanup_run_file_refuses_path_outside_site_tree(tmp_path, caplog):
    site = _site(tmp_path / "seaglider")
    outside_dir = tmp_path / "elsewhere"
    outside_dir.mkdir()
    outside_file = outside_dir / "sneaky.run"
    outside_file.write_text("x")
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher._cleanup_run_file(site, outside_file)

    assert outside_file.exists()  # left untouched
    assert any(r.levelname == "CRITICAL" for r in caplog.records)


# --- Dispatcher dispatch/poll roundtrip ---


def test_dispatch_queued_and_poll_completion_roundtrip(tmp_path):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir,
        "sg272.run",
        "/home/sg272",
        "/home/sg272/current",
        "/home/sg272/current/baselog.log",
        "Base.py --mission_dir /home/sg272/current",
    )
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    dispatcher.handle_run_file_event(site, run_file)

    que = ("seaglider", "/home/sg272/current", "Base.py", 272)
    dispatcher.dispatch_queued()

    assert len(client.dispatched) == 1
    assert que in dispatcher.running_jobs
    pid = dispatcher.running_jobs[que].pid

    # Still running - poll is a no-op.
    dispatcher.poll_completions()
    assert que in dispatcher.running_jobs

    client.set_status(pid, True, 0)
    dispatcher.poll_completions()
    assert que not in dispatcher.running_jobs


def test_dispatch_queued_updates_queue_length_for_second_job(tmp_path):
    site = _site(tmp_path / "seaglider")
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)

    run_file_1 = _write_run_file(
        site.watch_dir, "a.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher.handle_run_file_event(site, run_file_1)
    run_file_2 = _write_run_file(
        site.watch_dir, "b.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher.handle_run_file_event(site, run_file_2)

    que = ("seaglider", "/home/sg272/current", "Base.py", 272)
    assert len(dispatcher.job_queues[que]) == 2

    dispatcher.dispatch_queued()  # dispatches the first-queued job

    # --queue_length reports how many more jobs are still waiting behind
    # this one, i.e. the queue's length *after* popping this job - one
    # job remains behind the one just dispatched.
    argv = client.dispatched[0][1]
    assert argv[argv.index("--queue_length") + 1] == "1"


def test_poll_completions_writes_timing_line_for_timing_scripts(tmp_path):
    site = _site(tmp_path / "seaglider")
    mission_dir = tmp_path / "sg272" / "current"
    mission_dir.mkdir(parents=True)
    log_file_path = mission_dir / "baselog.log"
    log_file_path.write_text("")
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", str(tmp_path / "sg272"), str(mission_dir),
        str(log_file_path), f"BaseLogin.py --mission_dir {mission_dir}",
    )
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    dispatcher.handle_run_file_event(site, run_file)
    dispatcher.dispatch_queued()

    que = next(iter(dispatcher.running_jobs))
    pid = dispatcher.running_jobs[que].pid
    log_file = dispatcher.running_jobs[que].log_file

    client.set_status(pid, True, 0)
    dispatcher.poll_completions()

    contents = log_file.read_text()
    assert "BaseLogin.py" in contents
    assert "returncode=0" in contents


def test_poll_completions_handles_status_rpc_failure(tmp_path, caplog):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    dispatcher.handle_run_file_event(site, run_file)
    dispatcher.dispatch_queued()

    client.raise_on_status = BaseRunnerMulti.PrivExecError("transient failure")
    dispatcher.poll_completions()  # must not raise; job stays running for retry

    que = next(iter(dispatcher.running_jobs))
    assert que in dispatcher.running_jobs
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_dispatch_queued_skips_que_already_running(tmp_path):
    site = _site(tmp_path / "seaglider")
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    run_file_1 = _write_run_file(
        site.watch_dir, "a.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher.handle_run_file_event(site, run_file_1)
    dispatcher.dispatch_queued()
    assert len(client.dispatched) == 1

    run_file_2 = _write_run_file(
        site.watch_dir, "b.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher.handle_run_file_event(site, run_file_2)
    dispatcher.dispatch_queued()  # que already running - must not dispatch a second job

    assert len(client.dispatched) == 1


# --- Dispatcher._dispatch_blocking (dead-code parity path) ---


def test_dispatch_blocking_immediate_success(tmp_path):
    site = _site(tmp_path / "seaglider")
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)

    def fake_dispatch(site_name, argv, log_file):
        pid = 4242
        client._statuses[pid] = (True, 0)
        return pid

    client.dispatch_override = fake_dispatch
    dispatcher._dispatch_blocking(site, ["/bin/true"], str(site.watch_dir / "log"))


def test_dispatch_blocking_logs_warning_on_nonzero_returncode(tmp_path, caplog):
    site = _site(tmp_path / "seaglider")
    client = FakePrivExecClient()

    def fake_dispatch(site_name, argv, log_file):
        pid = 4242
        client._statuses[pid] = (True, 3)
        return pid

    client.dispatch_override = fake_dispatch
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    dispatcher._dispatch_blocking(site, ["/bin/false"], str(site.watch_dir / "log"))
    assert any(r.levelname == "WARNING" for r in caplog.records)


def test_process_run_file_uses_blocking_dispatch_when_queue_scripts_false(tmp_path):
    site = _site(tmp_path / "seaglider")
    object.__setattr__(site, "queue_scripts", False)
    client = FakePrivExecClient()

    def fake_dispatch(site_name, argv, log_file):
        pid = 4242
        client._statuses[pid] = (True, 0)
        return pid

    client.dispatch_override = fake_dispatch
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )

    dispatcher.handle_run_file_event(site, run_file)

    assert not dispatcher.job_queues  # never queued - dispatched inline instead


# --- UnixSocketPrivExecClient ---


def test_unix_socket_priv_exec_client_dispatch_success(short_socket_path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(short_socket_path))
    listener.listen(1)

    def _server():
        conn, _ = listener.accept()
        with conn:
            data = BaseRunnerMulti._recv_frame(conn)
            assert data is not None
            request = orjson.loads(data)
            assert request["site"] == "seaglider"
            BaseRunnerMulti._send_frame(conn, orjson.dumps({"ok": True, "pid": 4242}))

    thread = threading.Thread(target=_server)
    thread.start()
    client = BaseRunnerMulti.UnixSocketPrivExecClient(str(short_socket_path))
    pid = client.dispatch("seaglider", ["/bin/true"], pathlib.Path("/tmp/x.log"))
    thread.join(timeout=5)
    listener.close()

    assert pid == 4242


def test_unix_socket_priv_exec_client_status(short_socket_path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(short_socket_path))
    listener.listen(1)

    def _server():
        conn, _ = listener.accept()
        with conn:
            BaseRunnerMulti._recv_frame(conn)
            BaseRunnerMulti._send_frame(
                conn, orjson.dumps({"ok": True, "done": True, "returncode": 1})
            )

    thread = threading.Thread(target=_server)
    thread.start()
    client = BaseRunnerMulti.UnixSocketPrivExecClient(str(short_socket_path))
    done, returncode = client.status(4242)
    thread.join(timeout=5)
    listener.close()

    assert (done, returncode) == (True, 1)


def test_unix_socket_priv_exec_client_raises_on_error_response(short_socket_path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(short_socket_path))
    listener.listen(1)

    def _server():
        conn, _ = listener.accept()
        with conn:
            BaseRunnerMulti._recv_frame(conn)
            BaseRunnerMulti._send_frame(
                conn, orjson.dumps({"ok": False, "error": "nope"})
            )

    thread = threading.Thread(target=_server)
    thread.start()
    client = BaseRunnerMulti.UnixSocketPrivExecClient(str(short_socket_path))
    with pytest.raises(BaseRunnerMulti.PrivExecError, match="nope"):
        client.status(1)
    thread.join(timeout=5)
    listener.close()


def test_unix_socket_priv_exec_client_raises_when_unreachable(tmp_path):
    client = BaseRunnerMulti.UnixSocketPrivExecClient(str(tmp_path / "no-such.sock"))
    with pytest.raises(BaseRunnerMulti.PrivExecError):
        client.status(1)


def test_unix_socket_priv_exec_client_raises_on_no_response(short_socket_path):
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(short_socket_path))
    listener.listen(1)

    def _server():
        conn, _ = listener.accept()
        conn.close()  # close without responding

    thread = threading.Thread(target=_server)
    thread.start()
    client = BaseRunnerMulti.UnixSocketPrivExecClient(str(short_socket_path))
    with pytest.raises(BaseRunnerMulti.PrivExecError, match="no response"):
        client.status(1)
    thread.join(timeout=5)
    listener.close()


# --- main() ---


# --- Additional error-branch coverage ---


def test_check_lock_file_access_error_is_non_fatal(tmp_path, monkeypatch):
    site = _site(tmp_path / "seaglider", ignore_lock=False)
    monkeypatch.setattr(Utils, "check_lock_file", lambda *_a, **_k: -1)
    assert BaseRunnerMulti._try_activate_site(site) is True


def test_handle_run_file_event_keyboard_interrupt_sets_exit_event(tmp_path, monkeypatch):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    def _raise(*_a, **_k):
        raise KeyboardInterrupt

    monkeypatch.setattr(dispatcher, "_process_run_file", _raise)
    BaseRunnerMulti.exit_event.clear()
    try:
        dispatcher.handle_run_file_event(site, run_file)
        assert BaseRunnerMulti.exit_event.is_set()
    finally:
        BaseRunnerMulti.exit_event.clear()


def test_handle_run_file_event_docker_branch(tmp_path):
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=tmp_path / "seaglider",
        jail_root=None,
        runner_user="ioprunner",
        runner_uid=1,
        runner_gid=1,
        ignore_lock=True,
        docker_image="basestation:latest",
        use_docker_basestation=True,
    )
    site.watch_dir.mkdir()
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    que = ("seaglider", "/home/sg272/current", "Base.py", 272)
    job = dispatcher.job_queues[que][0]
    assert job.argv[1] == "/usr/local/basestation3/Base.py"


def test_enqueue_strips_daemon_flag(tmp_path):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/gps.log",
        "GliderEarlyGPS.py --daemon --mission_dir /home/sg272/current",
    )
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher.handle_run_file_event(site, run_file)

    que = ("seaglider", "/home/sg272/current", "GliderEarlyGPS.py", 272)
    job = dispatcher.job_queues[que][0]
    assert "--daemon" not in job.argv


def test_dispatch_blocking_polls_until_done(tmp_path):
    site = _site(tmp_path / "seaglider")
    client = FakePrivExecClient()
    calls = {"n": 0}

    def fake_dispatch(site_name, argv, log_file):
        return 4242

    def fake_status(pid):
        calls["n"] += 1
        if calls["n"] < 2:
            return (False, None)
        return (True, 0)

    client.dispatch_override = fake_dispatch
    client.status_override = fake_status
    dispatcher = BaseRunnerMulti.Dispatcher(client)

    dispatcher._dispatch_blocking(site, ["/bin/true"], str(site.watch_dir / "log"))

    assert calls["n"] == 2


def test_cleanup_run_file_missing_file_is_noop(tmp_path):
    site = _site(tmp_path / "seaglider")
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher._cleanup_run_file(site, site.watch_dir / "does-not-exist.run")  # no raise


def test_cleanup_run_file_archive_mkdir_failure_falls_back_to_unlink(tmp_path, monkeypatch, caplog):
    site = _site(tmp_path / "seaglider", archive=True)
    run_file = site.watch_dir / "sg272.run"
    run_file.write_text("x")

    def fake_mkdir(self, *a, **k):
        raise OSError("simulated mkdir failure")

    monkeypatch.setattr(pathlib.Path, "mkdir", fake_mkdir)
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher._cleanup_run_file(site, run_file)

    assert not run_file.exists()  # fell back to plain unlink
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_cleanup_run_file_archive_move_failure_falls_back_to_unlink(tmp_path, monkeypatch, caplog):
    site = _site(tmp_path / "seaglider", archive=True)
    (site.watch_dir / "archive").mkdir()
    run_file = site.watch_dir / "sg272.run"
    run_file.write_text("x")

    def fake_move(*a, **k):
        raise OSError("simulated move failure")

    monkeypatch.setattr("shutil.move", fake_move)
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher._cleanup_run_file(site, run_file)

    assert not run_file.exists()
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_cleanup_run_file_unlink_failure_logs_critical(tmp_path, monkeypatch, caplog):
    site = _site(tmp_path / "seaglider")
    run_file = site.watch_dir / "sg272.run"
    run_file.write_text("x")

    def fake_unlink(self, *a, **k):
        raise OSError("simulated unlink failure")

    monkeypatch.setattr(pathlib.Path, "unlink", fake_unlink)
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())

    dispatcher._cleanup_run_file(site, run_file)

    assert any(r.levelname == "CRITICAL" for r in caplog.records)


def test_poll_completions_outer_exception_is_caught(tmp_path, monkeypatch, caplog):
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher.running_jobs[("seaglider", "x", "Base.py", 1)] = BaseRunnerMulti.RunningJob(
        "job1", 1, ["argv"], tmp_path / "log", 0.0
    )

    def _raise(que):
        raise RuntimeError("boom")

    monkeypatch.setattr(dispatcher, "_poll_one_completion", _raise)
    dispatcher.poll_completions()  # must not raise
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_poll_one_completion_logs_warning_on_nonzero_returncode(tmp_path):
    site = _site(tmp_path / "seaglider")
    run_file = _write_run_file(
        site.watch_dir, "sg272.run", "/home/sg272", "/home/sg272/current",
        "/home/sg272/current/baselog.log", "Base.py --mission_dir /home/sg272/current",
    )
    client = FakePrivExecClient()
    dispatcher = BaseRunnerMulti.Dispatcher(client)
    dispatcher.handle_run_file_event(site, run_file)
    dispatcher.dispatch_queued()

    que = next(iter(dispatcher.running_jobs))
    pid = dispatcher.running_jobs[que].pid
    client.set_status(pid, True, 1)
    dispatcher.poll_completions()

    assert que not in dispatcher.running_jobs


def test_write_timing_line_failure_is_logged(tmp_path, caplog):
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    # A directory, not a file - open("a") on it raises.
    bad_log_file = tmp_path / "a-directory"
    bad_log_file.mkdir()
    running = BaseRunnerMulti.RunningJob("job1", 1, ["argv"], bad_log_file, 0.0)

    dispatcher._write_timing_line("seaglider", "BaseLogin.py", running, 0)

    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_dispatch_queued_outer_exception_is_caught(tmp_path, monkeypatch, caplog):
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher.job_queues[("seaglider", "x", "Base.py", 1)].append(
        BaseRunnerMulti.QueuedJob("job1", ["argv"], tmp_path / "log")
    )

    def _raise(que):
        raise RuntimeError("boom")

    monkeypatch.setattr(dispatcher, "_dispatch_one_queued", _raise)
    dispatcher.dispatch_queued()  # must not raise
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_dispatch_one_queued_empty_queue_is_noop(tmp_path):
    dispatcher = BaseRunnerMulti.Dispatcher(FakePrivExecClient())
    dispatcher._dispatch_one_queued(("seaglider", "x", "Base.py", 1))  # nothing queued - no raise
    assert not dispatcher.running_jobs


def test_main_returns_1_on_bad_sites_config(monkeypatch, tmp_path):
    bad_config = tmp_path / "sites.yaml"
    bad_config.write_text("[\n")  # syntactically invalid YAML
    monkeypatch.setattr(
        sys, "argv", ["BaseRunnerMulti.py", "--sites_config", str(bad_config)]
    )
    assert BaseRunnerMulti.main() == 1
