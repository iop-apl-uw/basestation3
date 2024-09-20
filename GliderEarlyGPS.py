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

"""Runs a monitor of the comm log traffic for the duration of the call - quits on disconnect or reconnect"""

import inspect
import os
import signal
import sys
import time
import traceback
from urllib.parse import urlencode
import orjson

import BaseCtrlFiles
import BaseDB
import BaseDotFiles
import BaseOpts
import BaseOptsType
import CommLog
import Daemon
import Utils
from BaseLog import BaseLogger, log_info, log_warning, log_error, log_critical

# Early process for gps - call back for ver= line in comm.log - at that point, recovery condition has been seen
# Form up the GPS line and call proceess .pagers

gliderearlygps_lockfile_name = ".gliderearlygps_lockfile"


class GliderEarlyGPSClient:
    """Client to handle connection to jabber server and comm callbacks"""

    def __init__(self, comm_log_file_name, base_opts):
        self.__comm_log_file_name = comm_log_file_name
        self.__base_opts = base_opts
        self._start_pos = 0
        self._commlog_session = None
        self._commlog_linecount = 0
        self.__comm_log = None
        self._first_time = True

        # Callback functions for the CommLog processor
        self.callbacks = {}
        for name, val in inspect.getmembers(self):
            if inspect.ismethod(val) and name.startswith("callback_"):
                self.callbacks[name[len("callback_") :]] = val

    def run(self):
        """Main processing loop - runs until keyboard interrupt is caught

        Returns: False - failed to start
                 True - connection terminated  by operator

        """
        shell_missing_count = 0
        comm_log_error_count = 0
        while True:
            try:
                if self.process_comm_log_wrapper():
                    comm_log_error_count += 1
                    if comm_log_error_count > 5:
                        log_error(
                            f"Error processing comm.log {comm_log_error_count} times - bailing out"
                        )
                        self.cleanup_shutdown()
                if self._first_time:
                    log_info(f"First time finished - start_pos:{self._start_pos}")
                    if (
                        not self.__base_opts.instrument_id
                        and self._commlog_session is not None
                    ):
                        # If the session object is set, it should contain the sg_id,
                        # either from sg_id from the Connect line, or uses the name
                        # of the mission_directory, which for an active mission should be
                        # of the form sgXXX.
                        #
                        # This situation arises when GliderEarlyGPS launches and catches the
                        # initial Connected line from this active session.  In that case, the
                        # scan back will stop at the initial Connected, so the session list in the
                        # comm.log will be empty
                        #
                        if self._commlog_session.sg_id is None:
                            log_error(
                                "Session object does not have sg_id set - not setting instrument_id"
                            )
                        else:
                            self.__base_opts.instrument_id = self._commlog_session.sg_id
                            log_info(
                                f"Setting instrument_id from session object {self._commlog_session.sg_id}"
                            )

                    if (
                        not self.__base_opts.instrument_id
                        and self.__comm_log is not None
                    ):
                        # This situation arrises when GliderEarlyGPS launches fast enough
                        # that only the previous session (not the current session) is in the log file.
                        # In this case, the session object is None because we are outside of a session proper
                        self.__base_opts.instrument_id = (
                            self.__comm_log.get_instrument_id()
                        )
                        if self.__base_opts.instrument_id:
                            log_info(
                                f"Setting instrument_id from session list {self.__base_opts.instrument_id}"
                            )

                    if not self.__base_opts.instrument_id:
                        log_error(
                            f"Failed to set the instrument id ({self.__base_opts.instrument_id})"
                        )
                self._first_time = False
                if self.__base_opts.csh_pid:
                    if not Utils.check_for_pid(self.__base_opts.csh_pid):
                        shell_missing_count += 1
                        log_info(
                            f"login shell has gone away ({shell_missing_count}, logout_seen:{self._commlog_session.logout_seen})"
                        )
                        # Wait 4 seconds before doing anything
                        if shell_missing_count >= 4:
                            self.closeout_commlog()
                        # Let the normal disconnect code will handle the rest of closeout and shutdown
                time.sleep(1)

            except KeyboardInterrupt:
                log_error("Interupted by operator")
                break

        log_info("Disconnected ....")
        return True

    # Functions
    def process_comm_log_wrapper(self):
        """
        Called to process the comm log

        Returns
            error code from comm.log processing
        """
        # log_info(f"start_pos in:{self._start_pos}")
        # pylint: disable=C0301
        try:
            (
                self.__comm_log,
                self._start_pos,
                self._commlog_session,
                self._commlog_linecount,
                err_code,
            ) = CommLog.process_comm_log(
                self.__comm_log_file_name,
                self.__base_opts,
                start_pos=self._start_pos,
                call_back=self,
                session=self._commlog_session,
                scan_back=self._first_time,
            )
        except:
            log_error("comm_log processing failed", "exc")
            return 1
        else:
            return err_code
        # log_info(f"start_pos out:{self._start_pos}")

    def closeout_commlog(self):
        """
        Closes out the comm.log and removes the .connected file
        """
        connected_file = os.path.join(self.__base_opts.mission_dir, ".connected")
        if os.path.exists(connected_file):
            try:
                os.remove(connected_file)
            except:
                log_error(f"Unable to remove {connected_file} -- permissions?", "exc")

        try:
            # (_, fo) = Utils.run_cmd_shell("date")
            # (_, fo) = Utils.run_cmd_shell('date +"%a %b %d %R:%S %Z %Y"')
            (_, fo) = Utils.run_cmd_shell('date -u +"%Y-%m-%dT%H:%M:%SZ"')
        except:
            log_error("Error running date", "exc")
        else:
            ts = fo.readline().decode().rstrip()
            log_info(ts)
            fo.close()

            comm_log_filename = os.path.join(self.__base_opts.mission_dir, "comm.log")
            try:
                with open(comm_log_filename, "a") as fo:
                    fo.write(f"Disconnected at {ts} (shell_disappeared)\n\n\n")
            except:
                log_error("Could not update {commlog}")

    def cleanup_shutdown(self):
        """
        Terminates the process
        """
        # Clean up and shutdown
        Utils.cleanup_lock_file(self.__base_opts, gliderearlygps_lockfile_name)
        log_info(
            "Ended processing "
            # + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
            + time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(time.time()))
        )
        # sys.exit(0)
        # pylint: disable=W0212
        os._exit(0)  # Don't run any clean up code

    # CommLog callbacks
    def callback_connected(self, connect_ts):
        """Callback for a comm.log Connected line"""
        if not self._first_time:
            # msg = "Connected: %s" % time.strftime("%a %b %d %H:%M:%S %Z %Y", connect_ts)
            msg = "Connected: %s" % time.strftime("%Y-%m-%dT%H:%M:%SZ", connect_ts)
            log_info(msg)

    def callback_reconnected(self, reconnect_ts):
        """Callback for a comm.log ReConnected line"""
        if not self._first_time:
            msg = "Reconnected: %s" % time.strftime(
                # "%a %b %d %H:%M:%S %Z %Y", reconnect_ts
                "%Y-%m-%dT%H:%M:%SZ",
                reconnect_ts,
            )
            log_info(msg)

    def callback_disconnected(self, session):
        """Callback for a comm.log Disconnected line"""
        if not self._first_time:
            if session is None:
                log_warning("disconnected callback called with empty session")
            else:
                if session.logout_seen:
                    logout_msg = "Logout received"
                else:
                    logout_msg = "Did not see a logout"

                msg = "Disconnected:%s %s" % (
                    # time.strftime("%a %b %d %H:%M:%S %Z %Y", session.disconnect_ts),
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", session.disconnect_ts),
                    logout_msg,
                )
                log_info(msg)

                send_str = urlencode(
                    {
                        "status": "disconnected - logout%s seen"
                        % ("" if session.logout_seen else " not")
                    }
                )
                log_info(send_str)
                if session.dive_num is None:
                    session.dive_num = -1
                BaseDotFiles.process_urls(
                    self.__base_opts, send_str, session.sg_id, session.dive_num
                )
                try:
                    msg = {
                        "glider": session.sg_id,
                        "dive": session.dive_num,
                        "content": "status=disconnected",
                        "time": time.time(),
                    }
                    Utils.notifyVis(
                        session.sg_id, "urls-status", orjson.dumps(msg).decode("utf-8")
                    )
                except:
                    log_error("notifyVis failed", "exc")
                self.cleanup_shutdown()

    def callback_transfered(self, filename, receivedsize):
        """Callback for comm.log transfer line"""
        if not self._first_time:
            msg = "Transfered %d bytes of %s" % (receivedsize, filename)
            log_info(msg)

    def callback_received(self, filename, receivedsize):
        """Callback for comm.log received line"""
        if not self._first_time:
            msg = "Received file %s (%d bytes)" % (filename, receivedsize)
            log_info(msg)

    def callback_recovery(self, recovery_msg):
        """Callback for a comm.log In Recovery line"""
        if not self._first_time:
            if recovery_msg is not None:
                msg = "In Recovery: %s" % recovery_msg
                log_info(msg)

    def callback_counter_line(self, session):
        """Callback for comm.log counter line (begining and end of session)"""
        if not self._first_time:
            if session is None:
                log_warning("counter_line callback called with empty session")
            else:
                self.process_counter_line(session)

    def callback_iridium(self, session):
        """Callback for comm.log Iridium geolocation line"""
        if not self._first_time:
            if session is None:
                log_warning("iridium callback called with empty session")
            else:
                BaseDB.addSession(self.__base_opts, session)

    def process_counter_line(self, session, testing=False):
        """
        Returns True for success, False for failure
        """
        ret_val = None
        if session.gps_fix is None:
            ret_val = "No GPS fix in most recent counter line - skipping"
        elif session.dive_num is None:
            ret_val = "No dive number in most recent counter line - skipping"
        elif session.logout_seen is True and testing is False:
            # ret_val = "Logout seen - must be second counter line - skipping"
            # Ignore second counter line
            pass
        else:
            if not self._first_time:
                BaseDotFiles.process_extensions(
                    ("commloggps",),
                    self.__base_opts,
                    session=session,
                )

                BaseDotFiles.process_pagers(
                    self.__base_opts, session.sg_id, ("gps",), session=session
                )
                BaseCtrlFiles.process_pagers_yml(
                    self.__base_opts, session.sg_id, ("gps",), session=session
                )

            try:
                gliderLat = Utils.ddmm2dd(session.gps_fix.lat)
                gliderLon = Utils.ddmm2dd(session.gps_fix.lon)
                gliderTime = time.mktime(session.gps_fix.datetime)

                send_str = '"%s %s %s"' % (
                    Utils.format_lat_lon_dd(gliderLat, "ddmm", True),
                    Utils.format_lat_lon_dd(gliderLon, "ddmm", False),
                    time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(gliderTime)),
                )

                log_info(
                    f"Adding session to basestation (sg{self.__base_opts.instrument_id:03d})"
                )
                BaseDB.addSession(self.__base_opts, session)

                payload = session.to_message_dict()
                BaseDotFiles.process_urls(
                    self.__base_opts,
                    send_str,
                    session.sg_id,
                    session.dive_num,
                    payload=payload,
                )
                try:
                    # old school gpsstr, just the string - not used
                    # Utils.notifyVis(session.sg_id, "urls-gpsstr", f"gpsstr={send_str}")
                    # new school send the whole session as a json dict
                    Utils.notifyVis(
                        session.sg_id,
                        "urls-gpsstr",
                        orjson.dumps(payload).decode("utf-8"),
                    )
                except:
                    log_error("notifyVis failed", "exc")

            except:
                ret_val = "Failed to process gps position (%s)" % traceback.format_exc()

        if ret_val is not None:
            log_error(ret_val)


def main():
    """comm.log processor launched as soon as the glider connects"""
    # Set up the call back here
    base_opts = BaseOpts.BaseOptions(
        "comm.log processor launched as soon as the glider connects",
        additional_arguments={
            "comm_log": BaseOptsType.options_t(
                "",
                ("GliderEarlyGPS",),
                ("comm_log",),
                str,
                {
                    "help": "comm.log file (for testing only)",
                    "nargs": "?",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)  # initializes BaseLog

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    # Check for required "options"
    if base_opts.mission_dir:
        comm_log_filename = os.path.join(base_opts.mission_dir, "comm.log")
        testing = False
    elif base_opts.comm_log:
        comm_log_filename = base_opts.comm_log
        base_opts.mission_dir, _ = os.path.split(base_opts.comm_log)
        testing = True
    else:
        log_critical("Dive directory must be supplied or path to comm.log.")
        return 1

    if base_opts.daemon:
        if Daemon.createDaemon(base_opts.mission_dir, False):
            log_error("Could not launch as a daemon - bailing out")
            return 1

    log_info("PID:%d" % os.getpid())
    log_info("login_shell PID:%d" % base_opts.csh_pid)

    lock_file_pid = Utils.check_lock_file(base_opts, gliderearlygps_lockfile_name)
    if lock_file_pid < 0:
        log_error("Error accessing the lockfile - proceeding anyway...")
    elif lock_file_pid > 0:
        # The PID still exists
        log_warning(
            "Previous GliderEarlyGPS process (pid:%d) still exists - signalling process to complete"
            % lock_file_pid
        )
        os.kill(lock_file_pid, signal.SIGKILL)
        if Utils.wait_for_pid(lock_file_pid, 10):
            # The alternative here is to try and kill the process:
            log_error(
                "Process pid:%d did not respond to sighup after %d seconds - bailing out"
                % (lock_file_pid, 10)
            )
            return 1
        log_info(
            "Previous GliderEarlyGPS process (pid:%d) apparently received the signal - proceeding"
            % lock_file_pid
        )
    else:
        # No lock file - move along
        pass

    Utils.create_lock_file(base_opts, gliderearlygps_lockfile_name)

    # Start up the bot
    glider_client = GliderEarlyGPSClient(comm_log_filename, base_opts)
    if testing:
        # For testing, go to the last session and process that
        (comm_log, _, _, _, _) = CommLog.process_comm_log(base_opts.comm_log, base_opts)
        if comm_log is None:
            log_error("Could not process %s - bailing out" % base_opts.comm_log)
            return 1
        try:
            glider_client.process_counter_line(comm_log.sessions[-1], testing=True)
        except:
            log_error("Problem in process_counter_line", "exc")
            return 1
        return 0

    try:
        log_info("Starting the GliderEarlyGPS client....")
        glider_client.run()
    except:
        log_error("GliderEarlyGPS failed", "exc")
        return 1

    # Normally, we never get here
    Utils.cleanup_lock_file(base_opts, gliderearlygps_lockfile_name)
    log_info(
        "Ended processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    return 0


if __name__ == "__main__":
    os.environ["TZ"] = "UTC"
    time.tzset()

    retval = main()
    sys.exit(retval)
