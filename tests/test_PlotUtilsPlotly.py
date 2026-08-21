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

    def __init__(self, close_delay: float = 0.0, running: bool = True) -> None:
        self.close_delay = close_delay
        self.closed = False
        self.running = running

    def is_running(self) -> bool:
        return self.running

    def close(self) -> None:
        time.sleep(self.close_delay)
        self.closed = True
        self.running = False


def _install_fake_server(
    monkeypatch, close_delay: float, running: bool = True
) -> _FakeGlobalServer:
    fake = _FakeGlobalServer(close_delay, running=running)
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


def test_bounded_close_no_op_when_server_already_not_running(monkeypatch) -> None:
    """Regression test: calling close on a server that's already closed (or
    never opened) must not call kaleido's own close() at all - that's what
    produces its "Server already closed" RuntimeWarning, seen in production
    every time the atexit handler runs after a normal run already closed
    the server itself during processing."""
    fake = _install_fake_server(monkeypatch, close_delay=0.0, running=False)

    PlotUtilsPlotly.bounded_close_global_server(1.0)

    assert not fake.closed
    # Nothing needed resetting, so the existing (already-idle) instance is
    # left in place rather than being swapped for an equivalent new one.
    assert PlotUtilsPlotly.kaleido._global_server is fake


def test_reset_kaleido_server_bounded_by_wedged_close(monkeypatch) -> None:
    """KaleidoServer.reset_kaleido_server() must not hang on a wedged background thread."""
    monkeypatch.setattr(PlotUtilsPlotly, "DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS", 0.2)
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
    monkeypatch.setattr(PlotUtilsPlotly, "DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS", 0.2)
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


def test_start_sync_server_without_raw_atexit_suppresses_kaleidos_registration(
    monkeypatch,
) -> None:
    """kaleido's raw, unbounded atexit.register(close) side effect must never
    reach the real atexit handler list when going through our wrapper."""
    registered: list[object] = []
    spy = lambda fn: registered.append(fn)  # noqa: E731
    monkeypatch.setattr(PlotUtilsPlotly.atexit, "register", spy)

    def fake_start_sync_server(*args, **kwargs) -> None:
        # Mimic GlobalKaleidoServer.open(): registers a raw atexit handler
        # as a side effect of starting, exactly like real kaleido does.
        PlotUtilsPlotly.atexit.register(lambda: None)

    monkeypatch.setattr(
        PlotUtilsPlotly.kaleido, "start_sync_server", fake_start_sync_server
    )

    PlotUtilsPlotly._start_sync_server_without_raw_atexit(n=1)

    assert registered == []
    # atexit.register must be restored to exactly what it was before, not
    # left disarmed.
    assert PlotUtilsPlotly.atexit.register is spy


def test_ensure_atexit_handler_registered_is_idempotent(monkeypatch) -> None:
    """Our handler must be armed exactly once no matter how many times
    start_kaleido_global_server() runs across a process's lifetime."""
    monkeypatch.setattr(PlotUtilsPlotly, "_atexit_handler_registered", False)
    calls: list[object] = []
    monkeypatch.setattr(PlotUtilsPlotly.atexit, "register", lambda fn: calls.append(fn))

    PlotUtilsPlotly._ensure_atexit_handler_registered()
    PlotUtilsPlotly._ensure_atexit_handler_registered()

    assert calls == [PlotUtilsPlotly._close_global_server_at_exit]


def test_close_global_server_at_exit_is_bounded_even_if_wedged(monkeypatch) -> None:
    """The one handler that actually runs at interpreter exit must never
    hang, even if the server is wedged at that point - proving there is no
    remaining path to kaleido's raw, unbounded close()."""
    monkeypatch.setattr(PlotUtilsPlotly, "DEFAULT_KALEIDO_SHUTDOWN_TIMEOUT_SECS", 0.2)
    fake = _install_fake_server(monkeypatch, close_delay=5.0)

    start = time.monotonic()
    PlotUtilsPlotly._close_global_server_at_exit()
    elapsed = time.monotonic() - start

    assert elapsed < 2.0
    assert PlotUtilsPlotly.kaleido._global_server is not fake


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


# ---------------------------------------------------------------------------
# is_static_plot_generation_enabled() / start_kaleido_global_server()
#
# See .claude/plans/2026-08-20-matplotlib-thumbnail-engine.md's Step 2: once
# thumbnail_engine defaults to "matplotlib", a standard production run
# (save_webp=True, thumbnail_webp=True, everything else False) has no format
# left that actually needs kaleido - is_static_plot_generation_enabled() must
# recognize that so start_kaleido_global_server()'s own early-return guard
# (`if not self.is_static_plot_generation_enabled() or self.server_running:
# return`) makes the Chrome-startup call structurally unreachable, not just
# "shouldn't run today."
# ---------------------------------------------------------------------------


def _default_base_opts(**overrides) -> types.SimpleNamespace:
    """A base_opts stand-in matching this project's real production defaults
    (save_png/save_jpg/save_svg off, save_webp+thumbnail_webp on, matplotlib
    thumbnail engine) - see BaseOpts.py's option defaults."""
    defaults = dict(
        save_png=False,
        save_jpg=False,
        save_svg=False,
        save_webp=True,
        thumbnail_webp=True,
        thumbnail_engine="matplotlib",
    )
    defaults.update(overrides)
    return types.SimpleNamespace(**defaults)


def test_is_static_plot_generation_enabled_false_for_default_options() -> None:
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts())
    assert server.is_static_plot_generation_enabled() is False


def test_is_static_plot_generation_enabled_true_for_save_png() -> None:
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts(save_png=True))
    assert server.is_static_plot_generation_enabled() is True


def test_is_static_plot_generation_enabled_true_for_save_jpg() -> None:
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts(save_jpg=True))
    assert server.is_static_plot_generation_enabled() is True


def test_is_static_plot_generation_enabled_true_for_save_svg() -> None:
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts(save_svg=True))
    assert server.is_static_plot_generation_enabled() is True


def test_is_static_plot_generation_enabled_true_for_full_size_webp() -> None:
    """save_webp without thumbnail_webp is a full-size kaleido export, not a
    matplotlib thumbnail - still needs kaleido regardless of thumbnail_engine."""
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts(thumbnail_webp=False))
    assert server.is_static_plot_generation_enabled() is True


def test_is_static_plot_generation_enabled_true_when_engine_reverted_to_kaleido() -> (
    None
):
    """The explicit operator escape hatch (thumbnail_engine="kaleido") must
    still route through kaleido - this is the deliberate override case, not
    a bug to route around."""
    server = PlotUtilsPlotly.KaleidoServer(
        _default_base_opts(thumbnail_engine="kaleido")
    )
    assert server.is_static_plot_generation_enabled() is True


def test_is_static_plot_generation_enabled_false_when_no_formats_requested() -> None:
    server = PlotUtilsPlotly.KaleidoServer(
        _default_base_opts(save_webp=False, thumbnail_webp=False)
    )
    assert server.is_static_plot_generation_enabled() is False


def test_start_kaleido_global_server_never_starts_chrome_for_default_options(
    monkeypatch,
) -> None:
    """The concrete Step 2 guarantee: a standard production run must never
    reach kaleido's own server-startup call at all - proven by making that
    call raise if it's ever invoked, not just checking a flag afterward."""
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "_start_sync_server_without_raw_atexit",
        lambda *a, **kw: (_ for _ in ()).throw(
            AssertionError("kaleido must not start for default options")
        ),
    )
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts())

    server.start_kaleido_global_server()  # must return without touching kaleido

    assert server.server_running is False


def test_start_kaleido_global_server_positive_control_still_starts_for_save_png(
    monkeypatch,
) -> None:
    """Proves the gate discriminates correctly rather than being permanently
    disabled, which would silently break real PNG export users: a format
    that genuinely needs kaleido must still reach the startup call."""
    calls: list[int] = []
    monkeypatch.setattr(
        PlotUtilsPlotly,
        "_start_sync_server_without_raw_atexit",
        lambda *a, **kw: calls.append(1),
    )
    monkeypatch.setattr(
        PlotUtilsPlotly.KaleidoServer,
        "is_kaleido_global_server_running",
        lambda self: (True, "fake success"),
    )
    server = PlotUtilsPlotly.KaleidoServer(_default_base_opts(save_png=True))

    server.start_kaleido_global_server()

    assert calls == [1]
