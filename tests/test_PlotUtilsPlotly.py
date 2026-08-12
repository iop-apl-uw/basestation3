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

import pathlib
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

    PlotUtilsPlotly.bounded_close_global_server(2.0)

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
    PlotUtilsPlotly.bounded_close_global_server(0.2)
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert any("Timeout" in msg for msg in logged)
    # The wedged instance must be abandoned, not left in place, so the next
    # start_kaleido_global_server() isn't blocked by stale "already open" state.
    assert PlotUtilsPlotly.kaleido._global_server is not fake


def test_bounded_close_no_op_when_no_server(monkeypatch) -> None:
    """Nothing to close is not an error."""
    monkeypatch.setattr(PlotUtilsPlotly.kaleido, "_global_server", None, raising=False)

    PlotUtilsPlotly.bounded_close_global_server(1.0)

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


def test_bounded_render_returns_fast_result() -> None:
    """A render that finishes well within the timeout returns its value normally."""
    assert PlotUtilsPlotly.bounded_render(lambda: 42, 2.0) == 42


def test_bounded_render_times_out_without_blocking_caller() -> None:
    """A render that never returns must not block the caller past the timeout.

    The abandoned worker thread is a daemon, so it can't block process exit
    either - unlike signal.alarm(), giving up here never has to forcibly
    interrupt the render itself.
    """

    def _hang() -> None:
        time.sleep(5.0)

    start = time.monotonic()
    try:
        PlotUtilsPlotly.bounded_render(_hang, 0.2)
        raised = False
    except PlotUtilsPlotly.RenderTimeout:
        raised = True
    elapsed = time.monotonic() - start

    assert raised
    assert elapsed < 2.0


def test_bounded_render_reraises_fn_exception() -> None:
    """An exception raised by fn() itself (not a timeout) propagates to the caller unchanged."""

    def _boom() -> None:
        raise ValueError("bad render")

    try:
        PlotUtilsPlotly.bounded_render(_boom, 2.0)
        raised = False
    except ValueError as exc:
        raised = True
        assert "bad render" in str(exc)

    assert raised


class _FakeFigure:
    """Stand-in for a plotly Figure: write_html() is instant, write_image()'s
    delay is configurable per output format so a single write_output_files()
    call can exercise "one format times out, the others succeed"."""

    def __init__(self, image_delay_by_format: dict[str, float]) -> None:
        self.image_delay_by_format = image_delay_by_format
        self.written_images: list[str] = []

    def write_html(self, file, **kwargs) -> None:
        if hasattr(file, "write"):
            file.write("<div>fake</div>")
        else:
            pathlib.Path(file).write_text("<div>fake</div>")

    def write_image(self, output_stream, *, format, **kwargs) -> None:
        time.sleep(self.image_delay_by_format.get(format, 0.0))
        self.written_images.append(format)
        if hasattr(output_stream, "write"):
            output_stream.write(b"fake-image-bytes")
        else:
            pathlib.Path(output_stream).write_bytes(b"fake-image-bytes")


def test_write_output_files_one_format_timeout_does_not_block_others(
    tmp_path, monkeypatch
) -> None:
    """A timed-out format is logged and skipped; sibling formats in the same
    call still complete - the concrete behavioral fix for the "silent budget
    loss" bug (previously a shared signal.alarm() meant one slow format could
    starve/skip formats after it, or a fast one could silently eat the whole
    budget)."""
    reset_calls: list[float] = []
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "bounded_close_global_server",
        lambda timeout: reset_calls.append(timeout),
    )
    logged: list[str] = []
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "log_error",
        lambda msg, **kwargs: logged.append(msg),
    )

    fig = _FakeFigure(image_delay_by_format={"png": 5.0, "webp": 0.0})
    base_opts = types.SimpleNamespace(
        plot_directory=tmp_path,
        full_html=False,
        compress_div=False,
        save_png=True,
        save_jpg=False,
        save_webp=True,
        save_svg=False,
        thumbnail_webp=False,
        plot_dive_timeout=0.2,
    )

    output_files = PlotUtilsPlotly.write_output_files(base_opts, "test_plot", fig)

    # webp succeeded despite png (rendered first) timing out.
    assert "webp" in fig.written_images
    assert "png" not in fig.written_images
    assert any(str(f).endswith(".webp") for f in output_files)
    assert not any(str(f).endswith(".png") for f in output_files)
    # .div always gets written (pure HTML, not kaleido/Chrome).
    assert any(str(f).endswith(".div") for f in output_files)

    assert any(
        "static image generation failed" in msg and "test_plot.png" in msg
        for msg in logged
    )
    assert reset_calls == [PlotUtilsPlotly.DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS]
