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

import time
import types

import PlotUtilsPlotly


class _FakeGlobalServer:
    """Stand-in for kaleido's GlobalKaleidoServer, with a controllable close() delay."""

    def __init__(self, close_delay: float = 0.0) -> None:
        self.close_delay = close_delay
        self.closed = False

    def close(self) -> None:
        time.sleep(self.close_delay)
        self.closed = True


def _install_fake_server(monkeypatch, close_delay: float) -> _FakeGlobalServer:
    fake = _FakeGlobalServer(close_delay)
    monkeypatch.setattr(PlotUtilsPlotly.kaleido, "_global_server", fake, raising=False)
    return fake


def test_bounded_close_replaces_server_when_close_is_fast(monkeypatch) -> None:
    """A healthy (fast) close should complete well within the timeout and swap in a fresh instance."""
    fake = _install_fake_server(monkeypatch, close_delay=0.0)

    PlotUtilsPlotly._bounded_close_global_server(2.0)

    assert PlotUtilsPlotly.kaleido._global_server is not fake
    assert isinstance(PlotUtilsPlotly.kaleido._global_server, _FakeGlobalServer)


def test_bounded_close_times_out_on_wedged_server(monkeypatch) -> None:
    """A close() that never returns must not block the caller past the timeout."""
    logged: list[str] = []
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "log_error",
        lambda msg, **kwargs: logged.append(msg),
    )
    fake = _install_fake_server(monkeypatch, close_delay=5.0)

    start = time.monotonic()
    PlotUtilsPlotly._bounded_close_global_server(0.2)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert any("Timeout" in msg for msg in logged)
    # The wedged instance must be abandoned, not left in place, so the next
    # start_kaleido_global_server() isn't blocked by stale "already open" state.
    assert PlotUtilsPlotly.kaleido._global_server is not fake


def test_bounded_close_no_op_when_no_server(monkeypatch) -> None:
    """Nothing to close is not an error."""
    monkeypatch.setattr(PlotUtilsPlotly.kaleido, "_global_server", None, raising=False)

    PlotUtilsPlotly._bounded_close_global_server(1.0)

    assert PlotUtilsPlotly.kaleido._global_server is None


def test_reset_kaleido_server_bounded_by_wedged_close(monkeypatch) -> None:
    """KaleidoServer.reset_kaleido_server() must not hang on a wedged background thread."""
    monkeypatch.setattr(
        PlotUtilsPlotly, "DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS", 0.2
    )
    fake = _install_fake_server(monkeypatch, close_delay=5.0)
    server = PlotUtilsPlotly.KaleidoServer(types.SimpleNamespace())

    start = time.monotonic()
    server.reset_kaleido_server()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert PlotUtilsPlotly.kaleido._global_server is not fake


def test_stop_kaleido_global_server_bounded_by_wedged_close(monkeypatch) -> None:
    """KaleidoServer.stop_kaleido_global_server() must not hang on a wedged background thread.

    This is the exact call that produced the multi-hour sg180 production hang
    (see .claude/plans/2026-08-10-plotly-timeout-hang-analysis.md): an earlier
    per-plot timeout left the shared kaleido thread wedged, and the unguarded
    shutdown then blocked forever.
    """
    monkeypatch.setattr(
        PlotUtilsPlotly, "DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS", 0.2
    )
    fake = _install_fake_server(monkeypatch, close_delay=5.0)
    server = PlotUtilsPlotly.KaleidoServer(types.SimpleNamespace())
    server.server_running = True

    start = time.monotonic()
    server.stop_kaleido_global_server()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert server.server_running is False
    assert PlotUtilsPlotly.kaleido._global_server is not fake


def test_stop_kaleido_global_server_no_op_when_not_running(monkeypatch) -> None:
    """If the server was never marked running, stop is a no-op and doesn't touch the global server."""
    fake = _install_fake_server(monkeypatch, close_delay=0.0)
    server = PlotUtilsPlotly.KaleidoServer(types.SimpleNamespace())
    assert server.server_running is False

    server.stop_kaleido_global_server()

    assert PlotUtilsPlotly.kaleido._global_server is fake
    assert not fake.closed
