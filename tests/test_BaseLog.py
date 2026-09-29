# -*- python-fmt -*-

## Copyright (c) 2025, 2026  University of Washington.
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

"""Tests for BaseLog.BaseLogger's process-wide singleton state and reset()."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest

import BaseLog
import BaseOpts
from BaseLog import BaseLogger, log_conversion_alert, log_error, log_info, log_warning


def _opts(*args: str) -> BaseOpts.BaseOptions:
    return BaseOpts.BaseOptions("BaseLog test", cmdline_args=list(args))


@pytest.fixture(autouse=True)
def _fresh_baselog() -> Iterator[None]:
    """Each test starts and ends with BaseLog in its just-imported state."""
    BaseLogger.reset()
    yield
    BaseLogger.reset()


def _messages(caplog: pytest.LogCaptureFixture) -> list[str]:
    return [r.getMessage() for r in caplog.records]


def test_first_init_wins_without_reset(caplog: pytest.LogCaptureFixture) -> None:
    """Documents the singleton behavior that made tests order-dependent."""
    caplog.set_level(logging.DEBUG)
    BaseLogger(_opts())  # no --verbose: WARNING
    BaseLogger(_opts("--verbose"))  # ignored - already initialized
    log_info("dropped info")
    assert BaseLogger.log_level == logging.WARNING
    assert not any("dropped info" in m for m in _messages(caplog))


def test_reset_lets_next_init_set_level(caplog: pytest.LogCaptureFixture) -> None:
    """The test_GliderEarlyGPS -> test_Base failure: a non-verbose first
    init no longer silences a later verbose run's INFO messages."""
    caplog.set_level(logging.DEBUG)
    BaseLogger(_opts())
    log_info("quiet run info")
    BaseLogger.reset()
    BaseLogger(_opts("--verbose"))
    log_info("verbose run info")
    msgs = _messages(caplog)
    assert not any("quiet run info" in m for m in msgs)
    assert any("verbose run info" in m for m in msgs)
    assert BaseLogger.log_level == logging.INFO


def test_reset_clears_handlers_and_state(tmp_path: Path) -> None:
    base_log = tmp_path / "baselog_test"
    BaseLogger(_opts("--verbose", "--base_log", str(base_log)))
    logger = BaseLogger.log
    assert logger is not None
    added = list(BaseLogger._handlers)
    file_handlers = [h for h in added if isinstance(h, logging.FileHandler)]
    assert len(file_handlers) == 1
    warnings_logger = logging.getLogger("py.warnings")
    assert all(h in logger.handlers and h in warnings_logger.handlers for h in added)

    log_error("an error", alert="TEST_ALERT")
    log_warning("a warning")
    log_conversion_alert("key", "msg", "resend")
    log_info("counted", max_count=5)
    assert BaseLogger.alerts_d and BaseLogger.conversion_alerts_d
    assert BaseLogger.warn_error_stream.getvalue()
    assert BaseLog.log_info_max_count

    old_streams = (BaseLogger.warn_error_stream, BaseLogger.traceback_stream)
    BaseLogger.reset()

    assert not any(h in logger.handlers or h in warnings_logger.handlers for h in added)
    assert file_handlers[0].stream is None  # closed
    assert BaseLogger._handlers == []
    assert not BaseLogger.is_initialized
    assert BaseLogger.self is None and BaseLogger.opts is None and BaseLogger.log is None
    assert BaseLogger.log_level == logging.WARNING
    assert BaseLogger.alerts_d == {} and BaseLogger.conversion_alerts_d == {}
    assert BaseLogger.warn_error_stream.getvalue() == ""
    assert BaseLogger.traceback_stream.getvalue() == ""
    assert (BaseLogger.warn_error_stream, BaseLogger.traceback_stream) != old_streams
    for counts in (
        BaseLog.log_error_max_count,
        BaseLog.log_warning_max_count,
        BaseLog.log_info_max_count,
        BaseLog.log_debug_max_count,
    ):
        assert not counts


def test_reset_switches_base_log_file(tmp_path: Path) -> None:
    """Without reset, later runs kept writing to the first run's --base_log."""
    first, second = tmp_path / "baselog_first", tmp_path / "baselog_second"
    BaseLogger(_opts("--verbose", "--base_log", str(first)))
    log_info("to first")
    BaseLogger.reset()
    BaseLogger(_opts("--verbose", "--base_log", str(second)))
    log_info("to second")
    BaseLogger.reset()  # close the file handler before reading
    assert "to first" in first.read_text()
    assert "to second" not in first.read_text()
    assert "to second" in second.read_text()


def test_string_capture_stop_detaches_handler() -> None:
    """Stopped captures leave no handler on the logger, py.warnings or the reset list."""
    BaseLogger(_opts("--verbose"))
    assert BaseLogger.self is not None
    before = list(BaseLogger._handlers)
    BaseLogger.self.startStringCapture()
    handler = BaseLogger.self.stringHandler
    assert handler is not None and handler in BaseLogger._handlers
    log_info("captured")
    captured = BaseLogger.self.stopStringCapture()
    assert "captured" in captured
    assert handler not in BaseLogger._handlers
    assert BaseLogger.log is not None and handler not in BaseLogger.log.handlers
    assert handler not in logging.getLogger("py.warnings").handlers
    assert BaseLogger._handlers == before
