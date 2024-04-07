#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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

""" Basestation wide logging infrastructure """

import argparse
import collections
import inspect
import logging
import os
import sys
import traceback
from io import StringIO
from typing import DefaultDict, Dict, List, Tuple

# CONSIDER make adding code location an option for debugging
# e.g., BaseLogger.opts.log_code_location
# otherwise drop for released code
# However, Geoff reports much after-the-fact debugging for which the linenos are critical.
#                 debug,    info,      warning, error,    critical
_stack_options = ["caller", "caller", "caller", "caller", "exc"]  # default
# _stack_options = ['caller', None,      None,    None,     'exc'] # relative silence
# _stack_options = ['caller', None,      None,    'caller', 'exc'] # only if we have big issues
# DEBUG _stack_options = ['caller', 'exc',    'exc',   'exc',    'exc'] # exercise


class BaseLogger:
    """
    BaseLog: for use by all basestation code and utilities
    """

    self = None  # the global instance
    is_initialized = False
    opts = None  # whatever starting options
    log = None  # the logger
    # for transient string logging
    stringHandler = None
    stringBuffer: None | StringIO = None
    # Turns out that calling the logging calls is expensive
    # it always generates its own line info for a logging record before
    # finally handing it off to each handler
    # But we know what we want so record locallyand use to short-circuit these calls

    # warnings, errors, and criticals are always enabled
    # -v turns on log_info, ---debug turns on log_debug
    debug_enabled = info_enabled = False
    debug_loc, info_loc, warning_loc, error_loc, critical_loc = _stack_options

    # support adding messages to a set of final alerts to send to pilots
    # these are keyed by a section and  are an appended list of strings
    alerts_d: Dict[str, List[str]] = {}
    conversion_alerts_d: Dict[str, List[Tuple[str, str]]] = {}

    # Stream to catch WARN-CRITICAL errors
    warn_error_stream: StringIO = StringIO()

    def __init__(self, opts: argparse.Namespace, include_time: bool = False) -> None:
        """
        Initializes a logging.Logger object, according to options (opts).
        """

        if not BaseLogger.is_initialized:
            BaseLogger.self = self
            BaseLogger.opts = opts

            calling_module = os.path.splitext(
                os.path.split(inspect.stack()[1].filename)[1]
            )[0]

            # create logger
            BaseLogger.log = logging.getLogger(calling_module)
            BaseLogger.log.setLevel(logging.DEBUG)

            # create a file handler if log filename is specified in opts
            if opts is not None and opts.base_log is not None and opts.base_log != "":
                fh = logging.FileHandler(opts.base_log)
                # fh.setLevel(logging.NOTSET) # messages of all levels will be recorded
                self.setHandler(fh, opts, include_time)

            # always create a console handler
            sh = logging.StreamHandler()
            self.setHandler(sh, opts, include_time)

            # Catch warning, error and critical

            self.setHandler(
                logging.StreamHandler(stream=BaseLogger.warn_error_stream),
                None,
                include_time,
            )

            BaseLogger.is_initialized = True
            log_info("Process id = %d" % os.getpid())  # report our process id
            try:
                if opts.config_file_not_found:
                    log_warning(
                        f"Config file {opts._opts.config_file_name} was not found"
                    )
            except AttributeError:
                pass

    def setHandler(
        self,
        handle: logging.Handler,
        opts: argparse.Namespace | None,
        include_time: bool,
    ) -> None:
        """
        Set a logging handle.
        """
        if include_time:
            formatter = logging.Formatter(
                "%(asctime)s: %(levelname)s: %(message)s", "%H:%M:%S %d %b %Y %Z"
            )
        else:
            # Remove timestamps for easier log comparison and reading
            formatter = logging.Formatter("%(levelname)s: %(message)s")

        if opts is not None:
            if opts.debug:
                BaseLogger.debug_enabled = True
                BaseLogger.info_enabled = True
                handle.setLevel(logging.DEBUG)
            elif opts.verbose:
                BaseLogger.info_enabled = True
                handle.setLevel(logging.INFO)
            else:
                handle.setLevel(logging.WARNING)

        else:
            handle.setLevel(logging.WARNING)

        handle.setFormatter(formatter)
        assert BaseLogger.log is not None
        BaseLogger.log.addHandler(handle)

        logging.captureWarnings(True)
        warnings_logger = logging.getLogger("py.warnings")
        warnings_logger.addHandler(handle)

    def getLogger(self) -> logging.Logger:
        """getLogger: access function to log (static member)"""
        if not BaseLogger.is_initialized:
            # error condition
            pass
        assert BaseLogger.log is not None
        return BaseLogger.log

    def startStringCapture(self, include_time: bool = False) -> None:
        """
        Start capturing all logging traffic to a string
        """
        if self.stringHandler:
            # already capturing...probably not closed properly from previous call due to bailing out or exception handling
            self.stopStringCapture()  # close handler and drop string on the floor

        self.stringBuffer = StringIO()  # start a string stream
        self.stringHandler = logging.StreamHandler(self.stringBuffer)
        self.setHandler(self.stringHandler, self.opts, include_time)

    def stopStringCapture(self) -> str:
        """
        Stop capturing logging traffic to a string and return results
        """
        if self.stringHandler is None:
            return ""  # not capturing, return an empty string
        else:
            assert self.log is not None
            self.log.removeHandler(self.stringHandler)
            self.stringHandler.flush()
            self.stringHandler = None

            if self.stringBuffer is None:
                return ""

            self.stringBuffer.flush()
            value = self.stringBuffer.getvalue()
            self.stringBuffer = None
            return value


def __log_caller_info(s: object, loc: str | None) -> str:
    """Add stack or module: line number info for log caller to given string
    Input:
    s - object to be logged

    Return:
    string with possible location information added
    """
    s = repr(s)
    if loc:
        try:
            # skip our local callers
            offset = 3
            # __log_caller_info(); log_XXXX; <caller>
            if loc in ["caller", "parent"]:
                if loc == "parent":  # A utlity routine
                    offset = offset + 1
                frame = traceback.extract_stack(None, offset)[0]
                module, lineno, function, _ = frame
                module = os.path.basename(module)  # lose extension
                s = "%s(%d): %s" % (module, lineno, s)
            elif loc == "exc":
                exc = traceback.format_exc()
                if exc:  # if no exception, nothing added
                    s = "%s:\n%s" % (s, exc)
            elif loc == "stack":
                # frame_num = 0
                prefix = ">"
                stack = ""
                frames = traceback.extract_stack()
                # normally from bottom to top; reverse this so most recent call first
                frames.reverse()
                for frame in frames[offset - 1 : -1]:  # drop our callers
                    module, lineno, function, _ = frame  # avoid the source code text
                    module = os.path.basename(module)  # lose extension
                    stack = "%s\n%s %s(%d) %s()" % (
                        stack,
                        prefix,
                        module,
                        lineno,
                        function,
                    )
                    prefix = " "
                s = "%s:%s" % (s, stack)
            else:  # unknown location request
                s = "(%s?): %s" % (loc, s)
        except Exception:
            pass
    return s


def log_warn_errors() -> StringIO:
    """Fetch the stream capturing WARN/ERROR/CRITICAL"""
    return BaseLogger.warn_error_stream


def log_alerts() -> Dict[str, List[str]]:
    """Fetches the alerts dictionary"""
    return BaseLogger.alerts_d


def log_conversion_alerts() -> Dict[str, List[Tuple[str, str]]]:
    """Fetches the conversion alerts dictionary"""
    return BaseLogger.conversion_alerts_d


def log_conversion_alert(key: str, msg: str, resend: str) -> None:
    """Log a conversion alert"""
    conversion_alerts_d = BaseLogger.conversion_alerts_d
    if key not in conversion_alerts_d:
        conversion_alerts_d[key] = []
    conversion_alerts_d[key].append((msg, resend))


def _log_alert(key: str, s: str) -> None:
    """Log a genreral alert"""
    if not isinstance(key, str):
        log_warning(f"{type(key)} in alerts", "exc")
        return
    alerts_d = BaseLogger.alerts_d
    if key not in alerts_d:
        alerts_d[key] = []
    alerts_d[key].append(s)


# alert=None argument is optional to the log_X functions
# for easy searching, call like:
# log_warning("You got issues boss",alert='Salinity processing')


def log_critical(
    s: object, loc: str = BaseLogger.critical_loc, alert: str | None = None
) -> None:
    """Report string to baselog as a CRITICAL error
    Args:
        s: msg to be logged
    """
    if alert:
        _log_alert(alert, "CRITICAL: %s" % s)
    s = __log_caller_info(s, loc)
    if BaseLogger.log:
        BaseLogger.log.critical(s)
    else:
        sys.stderr.write("CRITICAL: %s\n" % s)


log_error_max_count: DefaultDict[str, int] = collections.defaultdict(int)


def log_error(
    s: object,
    loc: str = BaseLogger.error_loc,
    alert: str | None = None,
    max_count: int | None = None,
) -> None:
    """Report string to baselog as an ERROR
    Args:
        s: msg to be logged
    """
    if alert:
        alert_str = f"ERROR: {s}"

    s = __log_caller_info(s, loc)

    if max_count:
        k = s.split(":")[0]
        log_error_max_count[k] += 1
        if log_error_max_count[k] == max_count:
            s += " (Max message count exceeded)"
        elif log_error_max_count[k] > max_count:
            return

    if alert:
        _log_alert(alert, alert_str)

    if BaseLogger.log:
        BaseLogger.log.error(s)
    else:
        sys.stderr.write("ERROR: %s\n" % s)


log_warning_max_count: DefaultDict[str, int] = collections.defaultdict(int)


def log_warning(
    s: object,
    loc: str = BaseLogger.warning_loc,
    alert: str | None = None,
    max_count: int | None = None,
) -> None:
    """Report string to baselog as a WARNING
    Input:
    s - string to be logged
    alert - string indicating the class of alert this warning should be assigned to
    max_count - maximum number of times this warning should be issued.
                if a positive value, the count is indexed by the module name and line number
                if a negative value, the count is indexed by the module name, line number andwarning string
    """
    if alert:
        alert_str = f"WARNING: {s}"

    s = __log_caller_info(s, loc)

    if max_count:
        k = s.split(":")[0]
        if max_count < 0:
            k = f"{k}:{s}"
        log_warning_max_count[k] += 1
        if log_warning_max_count[k] == abs(max_count):
            s += " (Max message count exceeded)"
        elif log_warning_max_count[k] > abs(max_count):
            return

    if alert:
        _log_alert(alert, alert_str)

    if BaseLogger.log:
        BaseLogger.log.warning(s)
    else:
        sys.stderr.write("WARNING: %s\n" % s)


log_info_max_count: DefaultDict[str, int] = collections.defaultdict(int)


def log_info(
    s: object,
    loc: str = BaseLogger.info_loc,
    alert: str | None = None,
    max_count: int | None = None,
) -> None:
    """Report string to baselog as an ERROR
    Args:
        s: msg to be logged
    """
    if not BaseLogger.info_enabled:
        return

    if alert:
        alert_str = f"INFO: {s}"

    s = __log_caller_info(s, loc)

    if max_count:
        k = s.split(":")[0]
        log_info_max_count[k] += 1
        if log_info_max_count[k] == max_count:
            s += " (Max message count exceeded)"
        elif log_info_max_count[k] > max_count:
            return

    if alert:
        _log_alert(alert, alert_str)

    if BaseLogger.log:
        BaseLogger.log.info(s)
    else:
        sys.stderr.write("INFO: %s\n" % s)


log_debug_max_count: DefaultDict[str, int] = collections.defaultdict(int)


def log_debug(
    s: object,
    loc: str | None = BaseLogger.debug_loc,
    alert: str | None = None,
    max_count: int | None = None,
) -> None:
    """Report string to baselog as DEBUG info
    Args:
        s: msg to be logged
    """
    if not BaseLogger.debug_enabled:
        return

    if alert:
        alert_str = f"DEBUG: {s}"

    s = __log_caller_info(s, loc)

    if max_count:
        k = s.split(":")[0]
        log_debug_max_count[k] += 1
        if log_debug_max_count[k] == max_count:
            s += " (Max message count exceeded)"
        elif log_debug_max_count[k] > max_count:
            return

    if alert:
        _log_alert(alert, alert_str)

    if BaseLogger.log:
        BaseLogger.log.debug(s)
    else:
        sys.stderr.write("DEBUG: %s\n" % s)
