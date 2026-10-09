# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""
BaseDotFiles.py: Processing for various configuration files that reside in the glider
home directory (or other locations)

"""

from __future__ import annotations

import configparser
import fnmatch
import functools
import itertools
import json
import netrc
import os
import pathlib
import pdb
import re
import smtplib
import sys
import tempfile
import time
import traceback
import warnings
from email import encoders
from email.mime.multipart import MIMEBase, MIMEMultipart
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import COMMASPACE, formatdate
from ftplib import FTP, FTP_TLS
from ftplib import all_errors as ftp_errors
from typing import TYPE_CHECKING, Literal
from urllib.parse import urlencode, urlsplit

import requests
import yaml

# paramiko is throwing a warning on import because it refernces Blowfish - which is depricated
# Issue is here https://github.com/paramiko/paramiko/issues/2038
# TODO: Remove when the warning has been fixed and the newer version is required
with warnings.catch_warnings():
    warnings.filterwarnings("ignore")
    import paramiko

import BaseGZip
import BaseOpts
import BaseOptsType
import CommLog
import Globals
import Utils
import Utils2
from BaseLog import (
    BaseLogger,
    log_critical,
    log_debug,
    log_error,
    log_info,
    log_warning,
)

if TYPE_CHECKING:
    from BaseOpts import BaseOptions


DEBUG_PDB = False

# Configuration
mail_server = "localhost"


def post_slack(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: str,
    slack_hook_url: str,
    subject_line: str,
    message_body: str,
) -> Literal[0, 1]:
    """Posts a formatted message to a Slack channel via an incoming webhook.

    Args:
        base_opts: Configuration options for the system runtime.
        instrument_id: Unique identifier for the logging instrument.
        slack_hook_url: Full URL to the Slack incoming webhook.
        subject_line: Subject line prefix for the notification.
        message_body: Core text contents of the message.

    Returns:
        The execution status code.
        0: Success.
        1: Failure.
    """

    log_info(
        f"instrument_id:{instrument_id} slack_hook_url:{redact_url(slack_hook_url)} "
        f"subject_line:{subject_line} message_body:{message_body}"
    )

    # Multi-line bodies (tracebacks, log dumps) get fenced as a code block
    if "\n" in message_body:
        text = f"{subject_line}:\n```\n{message_body}\n```"
    else:
        text = f"{subject_line}:{message_body}"
    msg = {"text": text}

    try:
        response = requests.post(
            slack_hook_url,
            data=json.dumps(msg),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                f"Request to slack returned an error {response.status_code}, "
                f"the response is:{response.text}"
            )
            return 1

    except requests.RequestException as exception:
        # No traceback: the exception text includes the hook URL, token and all
        log_error(
            f"Error in post to {redact_url(slack_hook_url)} ({type(exception).__name__})"
        )
        return 1
    except Exception:
        log_error("Error in post", "exc")
        return 1

    return 0


# For some reason, this doesn't really work
# pagers_ext = {'html' : lambda *args: send_email(*args, html_format=True)}
pagers_ext = {
    "html": lambda base_opts, instrument_id, email_addr, subject_line, message_body: (
        send_email(
            base_opts,
            instrument_id,
            email_addr,
            subject_line,
            message_body,
            html_format=True,
        )
    ),
    "slack": post_slack,
}


def send_email_text(
    base_opts,
    from_email_addr,
    to_email_addr,
    from_line,
    subject_line,
    message_body,
    smtp_server=None,
    smtp_account=None,
    smtp_password=None,
    html_format=False,
):
    """Sends out email

    Input
        from_email_addr - string for the email address (one address only)
        to_email_addr - string for a single email address or a list of strings for multiple addresses
        from_line - a pretty string typically with from_email_addr embedded in <>
        subject_line - subject line for message
        message_body - contents of message
        smtp_server, smtp_account, smtp_password - optional info for using an alternate smtp host as email forwarding server
    Returns
        0 - success
        1 - failure
    """
    if html_format:
        email_msg = MIMEMultipart("alternative")
    else:
        email_msg = MIMENonMultipart("text", "plain")
    email_msg["From"] = from_line
    email_msg["To"] = (
        to_email_addr if isinstance(to_email_addr, str) else ",".join(to_email_addr)
    )
    email_msg["Date"] = formatdate(localtime=True)
    email_msg["Subject"] = subject_line
    if base_opts.reply_addr:
        email_msg["Reply-To"] = base_opts.reply_addr
    if html_format:
        html_body = "<html><head></head><body><p>"
        for ll in message_body.splitlines():
            html_body += f"<div>{ll}</div>"
        html_body += "</p></body></html>"
        # Record the MIME types of both parts - text/plain and text/html.
        part1 = MIMEText(message_body, "plain")
        part2 = MIMEText(html_body, "html")
        # Attach parts into message container.
        # According to RFC 2046, the last part of a multipart message, in this case
        # the HTML message, is best and preferred.
        email_msg.attach(part1)
        email_msg.attach(part2)
    else:
        email_msg.set_payload(message_body)

    email_send_from = from_email_addr
    email_send_to = []

    # Previous version - re-written for clarity

    # email_send_to.append(to_email_addr) if isinstance(
    #    to_email_addr, str
    # ) else email_send_to.extend(to_email_addr)

    if isinstance(to_email_addr, str):
        email_send_to.append(to_email_addr)
    else:
        email_send_to.extend(to_email_addr)

    try:
        if sys.platform == "darwin":
            # on Mac OSX use some smtp server as the mail forwarder
            if not smtp_server or not smtp_account or not smtp_password:
                # typical servers are smtp.gmail.com or smtp.washington.edu
                log_error(
                    "Unable to send mail via smtp on Mac OS X -- requires an smtp account and password."
                )
                return 1
            smtp = smtplib.SMTP(smtp_server, 587)  # port 465 or 587
            smtp.ehlo()
            smtp.starttls()
            smtp.ehlo()
            smtp.login(smtp_account, smtp_password)
            if not base_opts.reply_addr:
                email_msg["Reply-To"] = (
                    from_email_addr  # smtp servers often rewrite from_line to use 'Original Name <account_name@gmail.com>'
                )
        else:  # linux of some sort
            smtp = smtplib.SMTP("localhost")
        smtp.sendmail(email_send_from, email_send_to, email_msg.as_string())
        smtp.close()
    except Exception:
        log_error(
            "Unable to send message %s (%s) to %s"
            % (subject_line, message_body, to_email_addr),
            "exc",
        )
        log_info("Continuing processing...")
        return 1
    else:
        return 0


def process_urls(base_opts, pass_num_or_gps, instrument_id, dive_num, payload=None):
    """Process the master and local urls file - supplying different arguments for the first and second pass"""
    # Process urls

    def process_one_urls(urls_file):
        if dive_num is None:
            log_error("dive_num is not an integer - skipping .urls file processing")
        elif instrument_id is None:
            log_error(
                "instrument_id is not an integer - skipping .urls file processing"
            )
        else:
            log_info(f"Starting processing on .urls pass({pass_num_or_gps})")
            for urls_line in urls_file:
                urls_line = urls_line.rstrip()
                log_debug(f"urls line = ({urls_line})")
                if urls_line == "":
                    continue
                if urls_line[0] != "#":
                    log_info(f"Processing .urls line ({urls_line})")
                    urls_elts = urls_line.split()
                    if len(urls_elts) > 3:
                        log_error(f"Too many entries on line ({urls_line})")
                    cert_file = True
                    if len(urls_elts) > 2:
                        cert_file = os.path.expanduser(urls_elts[2])
                    get_timeout = int(urls_elts[0])
                    if isinstance(pass_num_or_gps, int) and pass_num_or_gps == 1:
                        url_line = "%s?instrument_name=SG%03d&dive=%d&files=perdive" % (
                            urls_elts[1],
                            int(instrument_id),
                            int(dive_num),
                        )
                    elif isinstance(pass_num_or_gps, int) and pass_num_or_gps == 2:
                        url_line = "%s?instrument_name=SG%03d&dive=%d&files=all" % (
                            urls_elts[1],
                            int(instrument_id),
                            int(dive_num),
                        )
                    elif isinstance(
                        pass_num_or_gps, str
                    ) and pass_num_or_gps.startswith("status"):
                        url_line = "%s?instrument_name=SG%03d&%s" % (
                            urls_elts[1],
                            int(instrument_id),
                            pass_num_or_gps,
                        )
                    elif isinstance(pass_num_or_gps, str):
                        url_line = "%s?instrument_name=SG%03d&dive=%d&%s" % (
                            urls_elts[1],
                            int(instrument_id),
                            int(dive_num),
                            urlencode({"gpsstr": pass_num_or_gps}),
                        )
                    else:
                        log_error(
                            "Unknown pass(%s) - skipping processing"
                            % str(pass_num_or_gps)
                        )
                        continue

                    log_debug(f"URL line ({url_line})")
                    try:
                        url_response = requests.post(
                            url_line,
                            verify=cert_file,
                            timeout=get_timeout,
                            json=payload,
                        )
                    except Exception:
                        log_error(f"Error opening {url_line}", "exc")
                        log_error("Continuing processing...")
                    else:
                        log_info(
                            f"url ({url_line}) responded with code:{repr(url_response)} text:{url_response.text}"
                        )

        log_info(f"Finished processing on .urls pass({pass_num_or_gps})")

    for urls_file_name in (
        base_opts.basestation_etc / ".urls",
        base_opts.group_etc / ".urls" if base_opts.group_etc else None,
        base_opts.mission_dir / ".urls",
    ):
        if urls_file_name is None:
            continue
        if not os.path.exists(urls_file_name):
            log_info(
                f"No .urls file {urls_file_name} found - skipping pass {pass_num_or_gps}"
            )
            continue
        try:
            with open(urls_file_name, "r") as urls_file:
                process_one_urls(urls_file)
        except Exception:
            log_error(f"Could not process {urls_file_name} - no urls notified", "exc")


def send_email(
    base_opts, instrument_id, email_addr, subject_line, message_body, html_format=False
):
    """Sends out email from glider

    Input
        instrument_id - id of glider
        email_addr - string for the email address (one address only)
        subject_line - subject line for message
        message_body - contents of message

    Returns
        0 - success
        1 - failure
    """
    if base_opts.domain_name:
        email_send_from = "sg%03d@%s" % (instrument_id, base_opts.domain_name)
    else:
        email_send_from = "sg%03d" % (instrument_id)
    from_line = "Seaglider %d <%s>" % (instrument_id, email_send_from)
    return send_email_text(
        base_opts,
        email_send_from,
        email_addr,
        from_line,
        subject_line,
        message_body,
        html_format=html_format,
    )


# .pagers tags (process_pagers): those that take a position-format suffix, and all known
_PAGERS_TAGS_WITH_FMT = ("lategps", "gps", "recov", "critical", "drift")
_PAGERS_KNOWN_TAGS = ("lategps", "gps", "recov", "critical", "drift", "divetar", "comp", "alerts", "errors")


def _pagers_user_name(address: str, taken: dict[str, str]) -> str:
    """A pagers.yml user name for a .pagers address, unique within the conversion."""
    base = re.sub(r"[^a-z0-9]+", "_", address.lower()).strip("_") or "user"
    name, n = base, 2
    while name in taken and taken[name] != address:
        name, n = f"{base}_{n}", n + 1
    taken[name] = address
    return name


def convert_pagers_to_yml(lines: list[str]) -> tuple[dict, list[str]]:
    """Converts .pagers lines to the equivalent pagers.yml contents.

    Follows process_pagers' parsing: "address,[html|slack,]tag[,tag...]", tags optionally
    suffixed with a position format (gpsdd, recovddmmss; default ddmm). One pagers.yml user
    per address (repeated addresses merge); each line's tags become endpoints with those
    filters (one endpoint per position format), and each tag's subscription lists the user.

    Args:
        lines: The .pagers file's lines.

    Returns:
        (pagers_yml, warnings): the pagers.yml contents (users, then subscriptions), and one
        message per line or tag that couldn't be converted.

    Raises:
        None.
    """
    users: dict[str, dict] = {}
    subscriptions: dict[str, list[str]] = {}
    taken: dict[str, str] = {}
    n_hooks = 0
    hook_names: dict[str, str] = {}
    warnings: list[str] = []

    for line_no, raw in enumerate(lines, start=1):
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        elts = [e.strip() for e in line.split(",")]
        address, rest = elts[0], elts[1:]
        send_func, fmt_html = "email", False
        if rest and rest[0].lower() in ("html", "slack"):
            if rest[0].lower() == "slack":
                send_func = "slack"
            else:
                fmt_html = True
            rest = rest[1:]
        if not address or not rest:
            warnings.append(f"line {line_no}: no address or no tags - skipped")
            continue

        by_fmt: dict[str, list[str]] = {}
        for tag in (t.lower() for t in rest if t):
            fmt = ""
            for base in _PAGERS_TAGS_WITH_FMT:
                if tag.startswith(base):
                    fmt, tag = tag[len(base) :], base
                    break
            if tag not in _PAGERS_KNOWN_TAGS:
                warnings.append(f"line {line_no}: unknown tag {tag!r} - skipped")
                continue
            if fmt not in ("", "dd", "ddmm", "ddmmss"):
                warnings.append(f"line {line_no}: unknown position format {fmt!r} on {tag} - using ddmm")
                fmt = ""
            by_fmt.setdefault(fmt or "ddmm", []).append(tag)
        if not by_fmt:
            warnings.append(f"line {line_no}: no known tags - skipped")
            continue

        if send_func == "slack":
            if address not in hook_names:
                n_hooks += 1
                hook_names[address] = f"hook_{n_hooks}"
            name = hook_names[address]
        else:
            name = _pagers_user_name(address, taken)
        user = users.setdefault(name, {})
        for fmt, tags in by_fmt.items():
            endpoint: dict = {"hook": address} if send_func == "slack" else {"address": address}
            if fmt_html:
                endpoint["format"] = "html"
            endpoint["filters"] = tags
            if fmt != "ddmm":
                endpoint["latlon"] = fmt
            user.setdefault(send_func, []).append(endpoint)
            for tag in tags:
                if name not in subscriptions.setdefault(tag, []):
                    subscriptions[tag].append(name)

    return {**users, **subscriptions}, warnings


def process_pagers(
    base_opts,
    instrument_id,
    tags_to_process,
    comm_log=None,
    session=None,
    pagers_convert_msg=None,
    processed_files_message=None,
    msg_prefix=None,
    crit_other_message=None,
    warn_message=None,
):
    """Processes the .pagers file for the tags specified"""

    def process_one_pagers(pagers_file_name, pagers_file):
        tags = ""
        for t in tags_to_process:
            tags = f"{tags} {t}"
        log_info(f"Starting processing on {pagers_file_name} for {tags}")
        log_debug(f"pagers_ext = {pagers_ext}")
        for pagers_line in pagers_file:
            pagers_line = pagers_line.rstrip()
            log_debug(f"pagers line = ({pagers_line})")
            if pagers_line == "":
                continue
            if pagers_line[0] != "#":
                log_info(f"Processing .pagers line ({pagers_line})")
                pagers_elts = pagers_line.split(",")
                email_addr = pagers_elts[0]
                # Look for alternate sending functions
                if len(pagers_elts) > 1 and (pagers_elts[1] in pagers_ext):
                    log_info(f"Using sending function {pagers_elts[1]}")
                    send_func = pagers_ext[pagers_elts[1]]
                    pagers_elts = pagers_elts[2:]
                else:
                    send_func = send_email
                    pagers_elts = pagers_elts[1:]

                tags_with_fmt = ["lategps", "gps", "recov", "critical", "drift"]
                known_tags = [
                    "lategps",
                    "gps",
                    "recov",
                    "critical",
                    "drift",
                    "divetar",
                    "comp",
                    "alerts",
                    "errors",
                ]

                for pagers_tag in pagers_elts:
                    pagers_tag = pagers_tag.lstrip().rstrip().lower()

                    # Strip off the format first
                    fmt = ""
                    for tag in tags_with_fmt:
                        if pagers_tag.startswith(tag):
                            fmt = pagers_tag[len(tag) :]
                            pagers_tag = tag
                            break

                    if fmt == "":
                        fmt = "ddmm"

                    if pagers_tag not in known_tags:
                        log_error(
                            "Unknown tag (%s) on line (%s) in %s - skipping"
                            % (pagers_tag, pagers_line, pagers_file_name)
                        )
                        continue

                    log_debug(f"pagers_tag:{pagers_tag} fmt:{fmt}")

                    if "drift" in tags_to_process and pagers_tag == "drift":
                        if comm_log:
                            drift_message = comm_log.predict_drift(fmt)
                            subject_line = f"Drift SG{instrument_id:03d}"
                            log_info(
                                "Sending %s (%s) to %s"
                                % (subject_line, drift_message, email_addr)
                            )
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                drift_message,
                            )
                        else:
                            log_warning(
                                "Internal error - no comm log - skipping drift predictions for (%s)"
                                % email_addr
                            )

                    elif (
                        pagers_tag in ("gps", "recov", "critical", "lategps")
                        and pagers_tag in tags_to_process
                    ):
                        fmts = fmt.split("_")
                        dive_prefix = False
                        if len(fmts) > 1:
                            if fmts[1].lower()[0:7] == "divenum":
                                dive_prefix = True
                            fmt = fmts[0]

                        # GBS - 2023/03/27
                        # Due to a long standing bug in CommLog.py:GPS_lat_lon_and_recov, the
                        # divenum formatting has been in place for all these messages.
                        # The bug in CommLog has been fixed, but at this point, its seems more
                        # useful to have the diveprefix on all these messages
                        dive_prefix = True

                        log_debug(f"fmt:{fmt} dive_prefix:{dive_prefix}")
                        if comm_log:
                            (
                                gps_message,
                                recov_code,
                                escape_reason,
                                prefix_str,
                            ) = comm_log.last_GPS_lat_lon_and_recov(fmt, dive_prefix)
                            if session:
                                gps_message = (
                                    "%s D=%.2f,pit=%.2f,RH=%.2f,P=%.2f,24V=%.2f,10V=%.2f"
                                    % (
                                        gps_message,
                                        session.depth,
                                        session.obs_pitch,
                                        session.rh,
                                        session.int_press,
                                        session.volt_24V,
                                        session.volt_10V,
                                    )
                                )
                            reboot_msg = comm_log.has_glider_rebooted()
                        elif session:
                            (
                                gps_message,
                                recov_code,
                                escape_reason,
                                prefix_str,
                            ) = CommLog.GPS_lat_lon_and_recov(fmt, dive_prefix, session)
                            if msg_prefix:
                                gps_message = f"{msg_prefix}{gps_message}"
                            try:

                                def convert_f(x):
                                    """Conversion helper"""
                                    return f"{x:.2f}" if x is not None else "None"

                                gps_message = (
                                    "%s D=%s,pit=%s,RH=%s,P=%s,24V=%s,10V=%s"
                                    % (
                                        gps_message,
                                        convert_f(session.depth),
                                        convert_f(session.obs_pitch),
                                        convert_f(session.rh),
                                        convert_f(session.int_press),
                                        convert_f(session.volt_24V),
                                        convert_f(session.volt_10V),
                                    )
                                )
                            except Exception:
                                log_error("Problem formatting GPS message", "exc")
                            reboot_msg = None
                        else:
                            log_warning(
                                "Internal error - no comm log, session or critical message supplied - skipping (%s)"
                                % email_addr
                            )
                            continue

                        if reboot_msg:
                            gps_message = f"{gps_message}\n{reboot_msg}"

                        if prefix_str:
                            prefix_str = " SG%03d %s" % (
                                instrument_id,
                                prefix_str,
                            )

                        if pagers_tag in ("gps", "lategps"):
                            subject_line = f"GPS{prefix_str}"
                        elif pagers_tag in ("critical", "recov") and reboot_msg:
                            subject_line = f"REBOOTED{prefix_str}"
                        elif (
                            pagers_tag == "critical"
                            and recov_code
                            and recov_code != "QUIT_COMMAND"
                        ):
                            subject_line = f"IN NON-QUIT RECOVERY{prefix_str}"
                        elif pagers_tag == "recov" and recov_code:
                            subject_line = f"IN RECOVERY{prefix_str}"
                        elif pagers_tag == "recov" and escape_reason:
                            subject_line = f"IN ESCAPE{prefix_str}"
                        else:
                            subject_line = None

                        if subject_line is not None:
                            log_info(
                                "Sending %s (%s) to %s"
                                % (subject_line, gps_message, email_addr)
                            )
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                gps_message,
                            )

                    elif pagers_tag == "alerts" and "alerts" in tags_to_process:
                        if pagers_convert_msg and pagers_convert_msg != "":
                            subject_line = f"CONVERSION PROBLEMS SG{instrument_id:03d} "
                            log_info(f"Sending {subject_line} to {email_addr}")
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                pagers_convert_msg,
                            )
                        if crit_other_message and crit_other_message != "":
                            subject_line = (
                                f"CRITICAL ERROR IN CAPTURE SG{instrument_id:03d}"
                            )
                            log_info(f"Sending {subject_line} to {email_addr}")
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                crit_other_message,
                            )
                        if warn_message and warn_message != "":
                            subject_line = (
                                f"ALERTS FROM PROCESSING SG{instrument_id:03d}"
                            )
                            log_info(f"Sending {subject_line} to {email_addr}")
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                warn_message,
                            )

                    elif pagers_tag == "comp" and "comp" in tags_to_process:
                        if processed_files_message and processed_files_message != "":
                            subject_line = f"Processing Complete SG{instrument_id:03d}"
                            log_info(f"Sending {subject_line} to {email_addr}")
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                processed_files_message,
                            )

                    elif pagers_tag == "divetar" and "divetar" in tags_to_process:
                        if processed_files_message and processed_files_message != "":
                            subject_line = f"New Dive Tarball(s) SG{instrument_id:03d}"
                            log_info(f"Sending {subject_line} to {email_addr}")
                            send_func(
                                base_opts,
                                instrument_id,
                                email_addr,
                                subject_line,
                                processed_files_message,
                            )

                    elif (
                        pagers_tag == "errors"
                        and "errors" in tags_to_process
                        and processed_files_message
                        and processed_files_message != ""
                    ):
                        subject_line = (
                            f"Warnings and Errors from SG{instrument_id:03d} conversion"
                        )
                        log_info(f"Sending {subject_line} to {email_addr}")
                        send_func(
                            base_opts,
                            instrument_id,
                            email_addr,
                            subject_line,
                            processed_files_message,
                        )

        log_info(f"Finished processing on {pagers_file_name}")

    for pagers_file_name in (
        base_opts.basestation_etc / ".pagers",
        base_opts.group_etc / ".pagers" if base_opts.group_etc else None,
        base_opts.mission_dir / ".pagers",
    ):
        if pagers_file_name is None:
            continue
        if not os.path.exists(pagers_file_name):
            log_info(
                f"No .pagers file {pagers_file_name} found - skipping {tags_to_process}"
            )
            continue
        try:
            with open(pagers_file_name, "r") as pagers_file:
                process_one_pagers(pagers_file_name, pagers_file)
        except Exception:
            log_error(
                f"Could not process {pagers_file_name} - no pagers notified", "exc"
            )


REDACTED_PASSWORD = "****"


def redact_ftp_line(ftp_line: str) -> str:
    """Masks the password in a .ftp/.ftps line so it can be logged.

    The line is of the form [user[:password]@]host[:port]/path,tags...
    Everything between the first ':' and the first '@' is masked, even if
    the password holds characters (',', ':', '/') that would defeat the
    line parser - a malformed line is exactly the one that gets logged.

    Args:
        ftp_line: A line from a .ftp or .ftps file.

    Returns:
        The line with any password replaced by REDACTED_PASSWORD.

    Raises:
        None.
    """
    at = ftp_line.find("@")
    colon = ftp_line.find(":")
    if at == -1 or colon == -1 or colon > at:
        return ftp_line
    return f"{ftp_line[: colon + 1]}{REDACTED_PASSWORD}{ftp_line[at:]}"


def redact_sftp_line(sftp_line: str) -> str:
    """Masks the password in a .sftp line so it can be logged.

    The line is of the form host,user,password,path_to_key,...

    Args:
        sftp_line: A line from a .sftp file.

    Returns:
        The line with the password field replaced by REDACTED_PASSWORD.

    Raises:
        None.
    """
    fields = sftp_line.split(",")
    if len(fields) > 2 and fields[2]:
        fields[2] = REDACTED_PASSWORD
    return ",".join(fields)


def redact_url(url: str) -> str:
    """Masks everything after the host in a URL so it can be logged.

    Webhook URLs (Slack, Mattermost) carry their secret token in the path, and
    other POST endpoints may carry one in the query string. Any user:password
    before the host is dropped too.

    Args:
        url: A URL, e.g. a .pagers/pagers.yml hook or post url.

    Returns:
        scheme://host[:port], plus /REDACTED_PASSWORD if there was anything
        after the host. REDACTED_PASSWORD alone if url can't be parsed.

    Raises:
        None.
    """
    try:
        parts = urlsplit(str(url))
        host = parts.hostname or ""
        if parts.port:
            host = f"{host}:{parts.port}"
    except ValueError:
        return REDACTED_PASSWORD
    if not parts.scheme or not host:
        return REDACTED_PASSWORD
    tail = parts.path.strip("/") or parts.query or parts.fragment
    return f"{parts.scheme}://{host}" + (f"/{REDACTED_PASSWORD}" if tail else "")


def redact_secret(secret: str) -> str:
    """Masks a secret name, e.g. an ntfy topic, keeping a short prefix to tell them apart.

    On ntfy.sh anyone who knows a topic name can read and post to it, so the
    topic is the secret.

    Args:
        secret: The value to mask.

    Returns:
        The first three characters followed by REDACTED_PASSWORD, or just
        REDACTED_PASSWORD for values too short to show any of.

    Raises:
        None.
    """
    secret = str(secret)
    return f"{secret[:3]}{REDACTED_PASSWORD}" if len(secret) > 8 else REDACTED_PASSWORD


def redact_endpoint(endpoint: dict) -> dict:
    """Returns a copy of a notification endpoint that is safe to log.

    Args:
        endpoint: An endpoint from pagers.yml (hook, url, topic, ...).

    Returns:
        A shallow copy with hook and url passed through redact_url, topic
        through redact_secret, and passwords (pwd, password) replaced by
        REDACTED_PASSWORD. Other keys are unchanged.

    Raises:
        None.
    """
    safe = dict(endpoint)
    for key in ("hook", "url"):
        if key in safe:
            safe[key] = redact_url(safe[key])
    if "topic" in safe:
        safe["topic"] = redact_secret(safe["topic"])
    for key in ("pwd", "password"):
        if key in safe:
            safe[key] = REDACTED_PASSWORD
    return safe


def process_ftp_tags(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    ftp_tags,
    known_ftp_tags,
    ftp_line,
):
    """Process the ftp tags for either .ftp or .sftp file"""

    temp_tags = ftp_tags
    for i in range(len(temp_tags)):
        ftp_tags[i] = temp_tags[i].lower().rstrip().lstrip()

    # Check for what file type
    try:
        ftp_tags.index("all")
    except Exception:
        pass
    else:
        ftp_tags = known_ftp_tags

    # Collect file to send into a list
    ftp_file_names_to_send = []

    for ftp_tag in ftp_tags:
        if ftp_tag.startswith("fnmatch_"):
            _, m = ftp_tag.split("_", 1)
            log_info(f"Match criteria ({m})")
            for processed_file_name in processed_file_names:
                # Case insenitive match since tags were already lowercased
                # Str conversion to handle pathlib objects in list
                if fnmatch.fnmatchcase(str(processed_file_name).lower(), m):
                    ftp_file_names_to_send.append(processed_file_name)
                    log_info(f"fnmatched {processed_file_name}")

        elif ftp_tag.startswith("file_"):
            _, file_name = ftp_tag.split("_", 1)
            log_info(f"Filename ({file_name})")
            for m in pathlib.Path(base_opts.mission_dir).glob(file_name):
                ftp_file_names_to_send.append(m)
                log_info(f"alwaysfile matched {m}")

        elif ftp_tag in known_ftp_tags:
            if ftp_tag == "comm":
                ftp_file_names_to_send.append(base_opts.mission_dir / "comm.log")
            else:
                for processed_file_name in processed_file_names:
                    head, tail = os.path.splitext(processed_file_name)
                    if processed_file_name == mission_timeseries_name:
                        if ftp_tag == "mission_ts":
                            ftp_file_names_to_send.append(processed_file_name)
                    elif processed_file_name == mission_profile_name:
                        if ftp_tag == "mission_pro":
                            ftp_file_names_to_send.append(processed_file_name)
                    elif os.path.splitext(head)[1] == ".nc" and ftp_tag.lower() == "nc":
                        ftp_file_names_to_send.append(processed_file_name)
                    else:
                        head, tail = os.path.splitext(processed_file_name)
                        if tail.lstrip(".") == ftp_tag.lower():
                            ftp_file_names_to_send.append(processed_file_name)
        else:
            log_error(f"Unknown tag ({ftp_tag}) on line ({ftp_line}) - skipping")

    return ftp_file_names_to_send


def process_ftp_line(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    ftp_line,
    known_ftp_tags,
    use_ftps=False,
):
    """Sends indicated files to the ftp site indicated in ftp_line.
    Always sends nc files but can send others according to known_ftp_tags
    Input:
       base_opts - options
       processed_file_names - list of files to send, fully-qualified
       mission_timeseries_name - name or None
       mission_profile_name - name or None
       ftp_line - ftp specification of the form [user[:password]@]host[:port]/path
       known_ftp_tags - list of acceptable tags as a filter (e.g., comm, mission_ts, mission_pro, or explicit extensions)
       use_ftps - if True, negotiate FTPS (explicit TLS) instead of plain FTP

    Returns
      0 - success
      1 - failure
    """

    ftp_line = ftp_line.rstrip()
    safe_ftp_line = redact_ftp_line(ftp_line)
    log_debug(f"ftp line = ({safe_ftp_line})")
    if ftp_line == "":  # blank line
        return 0
    if ftp_line[0] == "#":  # not a comment
        return 0

    log_debug(f"{processed_file_names}")
    log_info(f"Processing ftp line ({safe_ftp_line})")
    # Lines of the form
    # [user[:password]@]host[:port]/path
    # see .ftp in sg000 for more details
    # NOTE: password can't be an email address (anonymous ftp) because '@' separates host as well
    # HACK: if password contains '_AT_' we replace it with an @
    ftp_tags = ftp_line.split(",")
    # Address
    user = pwd = host = port = path = None

    ftp_addr = ftp_tags[0].split("@")
    if len(ftp_addr) > 1:
        host_temp = ftp_addr[1]
        temp = ftp_addr[0].split(":")
        if len(temp) > 1:
            user, pwd = temp
            pwd = pwd.replace("_AT_", "@")
        else:
            user = temp[0]
    else:
        host_temp = ftp_addr[0]

    temp, path = host_temp.split("/", 1)
    if len(temp.split(":")) > 1:
        host, port = temp.split(":")
    else:
        host = temp

    # If there is no user specified, try the netrc file
    if user is None:
        try:
            auth = netrc.netrc().authenticators(host)
        except Exception:
            log_warning("Could not process .netrc", "exc")
        else:
            if auth is not None:
                user, _, pwd = auth

    log_info(f"user:{user},host:{host},port:{port},path:{path}")

    try:
        ftp_port = int(port) if port else 21
    except ValueError:
        log_error(f"Bad port ({port}) for {host} in {redact_ftp_line(ftp_line)} - skipping")
        return 1

    ftp_file_names_to_send = process_ftp_tags(
        base_opts,
        processed_file_names,
        mission_timeseries_name,
        mission_profile_name,
        ftp_tags[1:],
        known_ftp_tags,
        safe_ftp_line,
    )

    if len(ftp_file_names_to_send) < 1:
        return 0  # nothing to send

    log_debug(f"ftp files to send {ftp_file_names_to_send}")

    # Connect
    try:
        # Some hosts - gliders.ioos.us for example - don't want to login when the
        # host is specified in the FTP object creation - and then only when running from Base.py
        if use_ftps:
            ftp = FTP_TLS(timeout=30)
        else:
            ftp = FTP(timeout=30)
        # The parsed port used to be ignored - every connection went to 21
        connect_response = ftp.connect(host=host, port=ftp_port)
    except ftp_errors as exception:
        # Timeouts, refused connections, DNS failures: the host is the useful part
        log_error(f"Unable to connect to {host}:{ftp_port} ({type(exception).__name__}: {exception})")
        return 1  # give up
    except Exception:
        log_error(f"Unable to connect to {host}", "exc")
        return 1  # give up
    log_info(connect_response)

    if use_ftps:
        try:
            ftp.auth()  # upgrade control channel to TLS, on port 21
        except ftp_errors as exception:
            log_error(
                f"Unable to negotiate TLS with {host} ({exception}) - aborting rather than send credentials insecurely"
            )
            ftp.close()
            return 1  # give up
        except Exception:
            log_error(
                "Unable to negotiate TLS - aborting rather than send credentials insecurely",
                "exc",
            )
            ftp.close()
            return 1  # give up

    try:
        # ftp.set_debuglevel(2) # 2 is max level - all to stdout
        ftp.set_pasv(True)
        login_response = ftp.login(user, pwd)
    except ftp_errors as exception:
        # The server's reply (e.g. "530 Login incorrect.") - never the password
        log_error(f"Unable to login to {host} as {user} ({exception})")
        ftp.close()
        return 1  # give up
    except Exception:
        log_error(f"Unable to login to {host}", "exc")
        ftp.close()
        return 1  # give up

    log_info(login_response)

    if use_ftps:
        try:
            ftp.prot_p()  # secure the data channel too, after login
        except Exception:
            log_warning("Could not secure data channel - continuing", "exc")

    for i in path.split("/"):
        try:
            # We used to look via LIST to see if the subdir exists
            # but some sites protect against listing.
            # So just blindly try cd'ing to it and deal with the consequences
            ftp.cwd(i)  # try to cd to subdir
        except Exception:
            try:
                ftp.mkd(i)  # Doesn't appear to exist; try to create it
            except Exception:
                log_error(f"Could not make {i}", "exc")
                return 1  # give up
            ftp.cwd(i)  # cd to what we just created

    result = 0  # assume the best
    for ftp_file_name_to_send in ftp_file_names_to_send:
        _, tail = os.path.split(ftp_file_name_to_send)
        try:
            with open(ftp_file_name_to_send, "rb") as fi:
                log_info(f"Sending {tail}")
                try:
                    ftp.storbinary(f"STOR {tail}", fi)
                except Exception as exception:
                    log_error(
                        f"Unable to send {ftp_file_name_to_send} [{exception.args}]- skipping"
                    )
                    result = 1  # we had issues
                else:
                    log_info(f"Sent {ftp_file_name_to_send}")
        except Exception:
            log_error(f"Unable to open {ftp_file_name_to_send} - skipping", "exc")
            result = 1  # we had issues

    # Shutdown. The files were sent, or their failures already logged, so a
    # server error on QUIT (e.g. 451 after a failed STOR, sg263 2026-09-11) is
    # only worth a warning.
    try:
        ftp.quit()
    except ftp_errors as exception:
        log_warning(f"Error closing the connection to {host} ({exception})")
        ftp.close()
    return result


def process_sftp_line(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    sftp_line,
    known_ftp_tags,
):
    """Sends indicated files to the ftp site indicated in ftp_line.
    Always sends nc files but can send others according to known_ftp_tags
    Input:
       base_opts - options
       processed_file_names - list of files to send, fully-qualified
       mission_timeseries_name - name or None
       mission_profile_name - name or None
       sftp_line - ftp specification of the form host,user,password,path_to_key,port,path,[files]
       known_ftp_tags - list of acceptable tags as a filter (e.g., comm, mission_ts, mission_pro, or explicit extensions)

    Returns
      0 - success
      1 - failure
    """

    sftp_line = sftp_line.rstrip()
    safe_sftp_line = redact_sftp_line(sftp_line)
    log_debug(f"ftp line = ({safe_sftp_line})")
    if sftp_line == "":  # blank line
        return 0
    if sftp_line[0] == "#":  # not a comment
        return 0

    log_debug(f"{processed_file_names}")
    log_info(f"Processing sftp line ({safe_sftp_line})")

    # sftp specification of the form host, user,password,path_to_key,port,path,[files]
    sftp_tags = sftp_line.split(",")
    if len(sftp_tags) < 7:
        log_error(f"Incomplete sftp specification {safe_sftp_line} - skipping")
        return 1

    # Address
    host, user, pwd, path_to_key, path_to_known_hosts, port, remote_path = sftp_tags[:7]

    if not port:
        port = 22

    if not pwd:
        pwd = None

    if not path_to_key:
        path_to_key = None
    else:
        path_to_key = os.path.expanduser(path_to_key)

    if path_to_key and not os.path.exists(path_to_key):
        log_error(f"Key file {path_to_key} not found")
        return 1

    if not path_to_known_hosts:
        path_to_known_hosts = os.path.expanduser("~/.ssh/known_hosts")
    else:
        path_to_known_hosts = os.path.expanduser(path_to_known_hosts)

    if path_to_known_hosts and not os.path.exists(path_to_known_hosts):
        log_error(f"Key file {path_to_known_hosts} not found")
        return 1

    log_info(
        f"user:{user},host:{host},keyfile:{path_to_key},path_to_known_hosts:{path_to_known_hosts},port:{port},remote_path:{remote_path}"
    )

    sftp_file_names_to_send = process_ftp_tags(
        base_opts,
        processed_file_names,
        mission_timeseries_name,
        mission_profile_name,
        sftp_tags[7:],
        known_ftp_tags,
        safe_sftp_line,
    )

    if len(sftp_file_names_to_send) < 1:
        return 0  # nothing to send

    log_debug(f"ftp files to send {sftp_file_names_to_send}")

    # pkey = paramiko.ed25519key.Ed25519Key(filename=path_to_key)
    # transport = transport = paramiko.Transport((host, port))
    # transport.connect(username = user, pkey = pkey)
    # sftp = paramiko.SFTPClient.from_transport(transport)

    try:
        client = paramiko.SSHClient()
        client.load_host_keys(path_to_known_hosts)
        client.connect(
            host, port=port, username=user, password=pwd, key_filename=path_to_key
        )
        sftp = client.open_sftp()
    except Exception:
        log_error(f"Could not connect {safe_sftp_line}", "exc")
        return 1

    for sftp_file_name_to_send in sftp_file_names_to_send:
        remote_file = os.path.join(
            remote_path, os.path.split(sftp_file_name_to_send)[1]
        )
        log_info(f"Sending {sftp_file_name_to_send} to {remote_file}")
        sftp.put(sftp_file_name_to_send, remote_file)

    client.close()

    return 0


def process_ftp(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    known_ftp_tags,
    ftp_type=".ftp",
):
    def process_one_ftp(ftp_file, process_line, redact_line):
        """Process the .ftp/.sftp/.ftps file and push the data to a ftp/sftp/ftps server"""

        for ftp_line in ftp_file:
            try:
                process_line(
                    base_opts,
                    processed_file_names,
                    mission_timeseries_name,
                    mission_profile_name,
                    ftp_line,
                    known_ftp_tags,
                )
            except Exception:
                log_error(f"Could not process {redact_line(ftp_line.rstrip())} - skipping", "exc")

    if ftp_type not in (".ftp", ".sftp", ".ftps"):
        log_error(f"Unsupported ftp type {ftp_type}")
        return 1

    if ftp_type == ".ftp":
        process_line = process_ftp_line
        redact_line = redact_ftp_line
    elif ftp_type == ".ftps":
        process_line = functools.partial(process_ftp_line, use_ftps=True)
        redact_line = redact_ftp_line
    else:
        process_line = process_sftp_line
        redact_line = redact_sftp_line

    log_info(f"Starting processing on {ftp_type}")

    for ftp_file_name in (
        base_opts.basestation_etc / ftp_type,
        base_opts.group_etc / ftp_type if base_opts.group_etc else None,
        base_opts.mission_dir / ftp_type,
    ):
        if ftp_file_name is None:
            continue
        if not os.path.exists(ftp_file_name):
            log_info(
                f"No {ftp_type} file {ftp_file_name} file found - skipping {ftp_type} processing"
            )
            continue
        try:
            with open(ftp_file_name, "r") as ftp_file:
                process_one_ftp(ftp_file, process_line, redact_line)
        except Exception:
            log_error(f"Could not process {ftp_file_name} - no ftp sent", "exc")

    log_info(f"Finished processing on {ftp_type}")
    return 0


def process_mailer(
    base_opts,
    instrument_id,
    known_mailer_tags,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
):
    """Process the .mailer file and send out email"""

    def process_one_mailer(mailer_file, mailer_file_name, mailer_conversion_time):
        for mailer_line in mailer_file:
            mailer_line = mailer_line.rstrip()
            log_debug(f"mailer line = ({mailer_line})")
            if mailer_line == "":
                continue
            if mailer_line[0] != "#":
                log_info(f"Processing .mailer line ({mailer_line})")
                mailer_tags = mailer_line.split(",")
                mailer_send_to = mailer_tags[0]
                mailer_tags = mailer_tags[1:]
                mailer_send_to_list = []
                mailer_send_to_list.append(mailer_send_to)

                temp_tags = mailer_tags
                for i in range(len(temp_tags)):
                    mailer_tags[i] = temp_tags[i].lower().rstrip().lstrip()

                # Remove the body tag, if present
                try:
                    mailer_tags.index("body")
                except Exception:
                    mailer_file_in_body = False
                else:
                    mailer_tags.remove("body")
                    mailer_file_in_body = True

                # Check for msgperfile
                try:
                    mailer_tags.index("msgperfile")
                except Exception:
                    mailer_msg_per_file = False
                else:
                    mailer_tags.remove("msgperfile")
                    mailer_msg_per_file = True

                # Remove the Navy header tag, if present,
                try:
                    mailer_tags.index("kkyy_subject")
                except Exception:
                    mailer_subject = "SG%03d files" % (instrument_id)
                else:
                    mailer_tags.remove("kkyy_subject")
                    mailer_subject = "XBTDATA"

                # Remove the gzip tag, if present
                try:
                    mailer_tags.index("gzip")
                except Exception:
                    mailer_gzip_file = False
                else:
                    mailer_tags.remove("gzip")
                    if mailer_file_in_body:
                        log_error("Options body and gzip incompatibile - skipping gzip")
                        mailer_gzip_file = False
                    else:
                        mailer_gzip_file = True

                # Check for what file type
                try:
                    mailer_tags.index("all")
                except Exception:
                    pass
                else:
                    mailer_tags = known_mailer_tags

                # Collect file to send into a list
                mailer_file_names_to_send = []

                for mailer_tag in mailer_tags:
                    if mailer_tag.startswith("fnmatch_"):
                        _, m = mailer_tag.split("_", 1)
                        log_info(f"Match criteria ({m})")
                        for processed_file_name in processed_file_names:
                            # Case insenitive match since tags were already lowercased
                            if fnmatch.fnmatchcase(processed_file_name.lower(), m):
                                mailer_file_names_to_send.append(processed_file_name)
                                log_info(f"Matched {processed_file_name}")
                    elif mailer_tag not in known_mailer_tags:
                        log_error(
                            "Unknown tag (%s) on line (%s) in %s - skipping"
                            % (mailer_tag, mailer_line, mailer_file_name)
                        )
                    else:
                        if mailer_tag == "comm":
                            mailer_file_names_to_send.append(
                                base_opts.mission_dir / "comm.log"
                            )
                        elif (
                            mailer_tag in ("nc", "mission_ts", "mission_pro")
                            and mailer_file_in_body
                        ):
                            log_error(
                                "Sending netCDF files in the message body not supported"
                            )
                            continue
                        else:
                            for processed_file_name in processed_file_names:
                                if processed_file_name == mission_timeseries_name:
                                    if mailer_tag == "mission_ts":
                                        mailer_file_names_to_send.append(
                                            processed_file_name
                                        )
                                elif processed_file_name == mission_profile_name:
                                    if mailer_tag == "mission_pro":
                                        mailer_file_names_to_send.append(
                                            processed_file_name
                                        )
                                else:
                                    _, tail = os.path.splitext(processed_file_name)
                                    if tail.lstrip(".") == mailer_tag.lower():
                                        mailer_file_names_to_send.append(
                                            processed_file_name
                                        )

                if mailer_file_names_to_send:
                    log_info(f"Sending {mailer_file_names_to_send}")
                else:
                    log_info("No files found to send")

                # Set up messsage here if there is only one message per recipient
                if not mailer_msg_per_file:
                    if not mailer_file_in_body:
                        mailer_msg = MIMEMultipart()
                    else:
                        mailer_msg = MIMENonMultipart("text", "plain")

                    # mailer_msg['From'] = "SG%03d" % (instrument_id)
                    if base_opts.domain_name:
                        mailer_msg["From"] = "Seaglider %d <sg%03d@%s>" % (
                            instrument_id,
                            instrument_id,
                            base_opts.domain_name,
                        )
                    else:
                        mailer_msg["From"] = "Seaglider %d <sg%03d>" % (
                            instrument_id,
                            instrument_id,
                        )
                    mailer_msg["To"] = COMMASPACE.join(list(mailer_send_to_list))
                    mailer_msg["Date"] = formatdate(localtime=True)
                    mailer_msg["Subject"] = mailer_subject
                    if base_opts.reply_addr:
                        mailer_msg["Reply-To"] = base_opts.reply_addr

                    if not mailer_file_in_body:
                        mailer_msg.attach(
                            MIMEText(
                                "New/Updated files as of %s conversion\n"
                                % mailer_conversion_time
                            )
                        )
                    mailer_text = ""

                for mailer_file_name_to_send in mailer_file_names_to_send:
                    if mailer_msg_per_file:
                        # Set up message here if there are multiple messages per recipient
                        if not mailer_file_in_body:
                            mailer_msg = MIMEMultipart()
                        else:
                            mailer_msg = MIMENonMultipart("text", "plain")
                        # mailer_msg['From'] = "SG%03d" % (instrument_id)
                        if base_opts.domain_name:
                            mailer_msg["From"] = "Seaglider %d <sg%03d@%s>" % (
                                instrument_id,
                                instrument_id,
                                base_opts.domain_name,
                            )
                        else:
                            mailer_msg["From"] = "Seaglider %d <sg%03d>" % (
                                instrument_id,
                                instrument_id,
                            )
                        mailer_msg["To"] = COMMASPACE.join(list(mailer_send_to_list))
                        mailer_msg["Date"] = formatdate(localtime=True)
                        mailer_msg["Subject"] = mailer_subject
                        if base_opts.reply_addr:
                            mailer_msg["Reply-To"] = base_opts.reply_addr

                        if not mailer_file_in_body:
                            mailer_msg.attach(
                                MIMEText(
                                    "File %s as of %s conversion\n"
                                    % (
                                        mailer_file_name_to_send,
                                        mailer_conversion_time,
                                    )
                                )
                            )
                        mailer_text = ""

                    if mailer_file_in_body:
                        try:
                            with open(mailer_file_name_to_send, "r") as fi:
                                mailer_text = mailer_text + fi.read()
                        except Exception:
                            log_error(
                                "Unable to include %s in mailer message - skipping"
                                % mailer_file_name_to_send,
                                "exc",
                            )
                            log_info("Continuing processing...")
                    else:
                        try:
                            # Message as attachment
                            _, tail = os.path.splitext(mailer_file_name_to_send)
                            if mailer_gzip_file:
                                if tail.lstrip(".").lower() != "gz":
                                    mailer_gzip_file_name_to_send = (
                                        mailer_file_name_to_send + ".gz"
                                    )
                                    gzip_ret_val = BaseGZip.compress(
                                        mailer_file_name_to_send,
                                        mailer_gzip_file_name_to_send,
                                    )
                                    if gzip_ret_val > 0:
                                        log_error(
                                            "Problem compressing %s - skipping"
                                            % mailer_file_name_to_send
                                        )
                                else:
                                    gzip_ret_val = 0

                                if gzip_ret_val <= 0:
                                    mailer_part = MIMEBase(
                                        "application", "octet-stream"
                                    )
                                    try:
                                        with open(
                                            mailer_gzip_file_name_to_send, "rb"
                                        ) as fi:
                                            mailer_part.set_payload(fi.read())
                                    except Exception:
                                        log_error(
                                            f"Unable set message payload {mailer_gzip_file_name_to_send}",
                                            "exc",
                                        )

                                    encoders.encode_base64(mailer_part)
                                    mailer_part.add_header(
                                        "Content-Disposition",
                                        'attachment; filename="%s"'
                                        % os.path.basename(
                                            mailer_gzip_file_name_to_send
                                        ),
                                    )
                                    mailer_msg.attach(mailer_part)
                            else:
                                if (
                                    tail.lstrip(".").lower() == "nc"
                                    or tail.lstrip(".").lower() == "gz"
                                    or tail.lstrip(".").lower() == "bz2"
                                    or tail.lstrip(".").lower() == "mat"
                                    or tail.lstrip(".").lower() == "ad2cp"
                                ):
                                    mailer_part = MIMEBase(
                                        "application", "octet-stream"
                                    )
                                    try:
                                        with open(mailer_file_name_to_send, "rb") as fi:
                                            mailer_part.set_payload(fi.read())
                                    except Exception:
                                        log_error(
                                            f"Unable set message payload {mailer_file_name_to_send}",
                                            "exc",
                                        )
                                else:
                                    mailer_part = MIMEBase("text", "plain")
                                    try:
                                        with open(mailer_file_name_to_send, "r") as fi:
                                            mailer_part.set_payload(fi.read())
                                    except Exception:
                                        log_error(
                                            f"Unable set message payload {mailer_file_name_to_send}",
                                            "exc",
                                        )

                                encoders.encode_base64(mailer_part)
                                mailer_part.add_header(
                                    "Content-Disposition",
                                    'attachment; filename="%s"'
                                    % os.path.basename(mailer_file_name_to_send),
                                )
                                mailer_msg.attach(mailer_part)
                        except Exception:
                            log_error(
                                f"Error processing {mailer_file_name_to_send}",
                                "exc",
                            )
                            continue

                    if mailer_msg_per_file:
                        # For multiple messages per recipient, send out message here
                        if mailer_file_in_body:
                            mailer_msg.set_payload(mailer_text)
                        # Send it out
                        if len(mailer_file_names_to_send):
                            if base_opts.domain_name:
                                mailer_send_from = "sg%03d@%s" % (
                                    instrument_id,
                                    base_opts.domain_name,
                                )
                            else:
                                mailer_send_from = "sg%03d" % (instrument_id)
                            try:
                                smtp = smtplib.SMTP(mail_server)
                                smtp.sendmail(
                                    mailer_send_from,
                                    mailer_send_to,
                                    mailer_msg.as_string(),
                                )
                                smtp.close()
                            except Exception:
                                log_error(
                                    "Unable to send message [%s] skipping"
                                    % mailer_line,
                                    "exc",
                                )
                                log_info("Continuing processing...")
                        mailer_msg = None

                if not mailer_msg_per_file:
                    # For single messages per recipient, send out message here
                    if mailer_file_in_body:
                        mailer_msg.set_payload(mailer_text)
                    # Send it out
                    if len(mailer_file_names_to_send):
                        if base_opts.domain_name:
                            mailer_send_from = "sg%03d@%s" % (
                                instrument_id,
                                base_opts.domain_name,
                            )
                        else:
                            mailer_send_from = "sg%03d" % (instrument_id)
                        log_info(f"Sending from {mailer_send_from}")
                        try:
                            smtp = smtplib.SMTP(mail_server)
                            smtp.sendmail(
                                mailer_send_from,
                                mailer_send_to,
                                mailer_msg.as_string(),
                            )
                            smtp.close()
                        except Exception:
                            log_error(
                                f"Unable to send message [{mailer_line}] skipping",
                                "exc",
                            )
                            log_info("Continuing processing...")
                    mailer_msg = None

    log_info("Started processing on .mailer")
    mailer_conversion_time = time.strftime(
        "%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())
    )
    for mailer_file_name in (
        base_opts.basestation_etc / ".mailer",
        base_opts.group_etc / ".mailer" if base_opts.group_etc else None,
        base_opts.mission_dir / ".mailer",
    ):
        if mailer_file_name is None:
            continue
        if not os.path.exists(mailer_file_name):
            log_info(
                f"No .mailer file {mailer_file_name} file found - skipping .mailer processing"
            )
            continue

        try:
            with open(mailer_file_name, "r") as mailer_file:
                process_one_mailer(
                    mailer_file, mailer_file_name, mailer_conversion_time
                )
        except Exception:
            log_error(f"Could not process {mailer_file_name} - no .mailer sent", "exc")

    log_info("Finished processing on .mailer")


def run_extension_script(
    base_opts: BaseOptions,
    script_name: str,
    script_args: list[str] | None,
    timeout: int = 0,
) -> None:
    """Attempts to execute a script named under a shell context

    Output is recorded to the log, error code is ignored, no timeout enforced
    """
    # TODO - after conversion of all paths to pathlib, remove conversions to the
    # object below.  For now, they have the side effect of stripping the trailing
    # / from the path before adding to the command line
    full_script_name = pathlib.Path(base_opts.mission_dir) / script_name

    if os.path.exists(full_script_name):
        log_info(f"Processing {full_script_name}")
        cmdline = f"{full_script_name} "
        cmdline += f"{pathlib.Path(base_opts.basestation_directory)} "
        cmdline += f"{pathlib.Path(base_opts.mission_dir)} "
        if script_args:
            for i in script_args:
                cmdline = f"{cmdline} {i} "
        log_debug(f"Running ({cmdline})")
        try:
            (_, fo) = Utils.run_cmd_shell(cmdline, timeout=timeout)
        except Exception:
            log_error(f"Error running {cmdline}", "exc")
        else:
            if fo is not None:
                for f in fo:
                    log_info(f)
                fo.close()
    else:
        log_info(f"Extension script {full_script_name} not found")


def process_extensions(
    sections: tuple[
        Literal[
            "init_extension",
            "dive",
            "missionearly",
            "global",
            "mission",
            "prelogin",
            "commloggps",
            "postnetcdf",
        ],
        ...,
    ],
    base_opts: BaseOptions,
    sg_calib_file_name: pathlib.path | None = None,
    dive_nc_file_names: list[pathlib.Path] | None = None,
    nc_files_created: list[pathlib.Path] | None = None,
    processed_other_files: list[pathlib.Path] | None = None,
    known_mailer_tags: list[str] | None = None,
    known_ftp_tags: list[str] | None = None,
    processed_file_names: list[pathlib.Path] | None = None,
    log_output_info=True,
    **kwargs,
) -> int:
    """Processes the extensions file, running each extension

    Returns:
        0 - success
        1 - failure
    """

    def process_one_extension_file(
        extensions_file_name, additional_search_path, sections
    ):
        if log_output_info:
            log_info(
                f"Starting processing on {extensions_file_name} section(s):{sections}"
            )
        else:
            log_debug(
                f"Starting processing on {extensions_file_name} section(s):{sections}"
            )
        ret_val = 0
        cp = configparser.ConfigParser(allow_no_value=True, inline_comment_prefixes="#")
        cp.optionxform = str
        try:
            # Anything not inside a section tag is in [global] section
            with open(extensions_file_name) as fi:
                cp.read_file(
                    itertools.chain(["[global]"], fi), source=extensions_file_name
                )
        except (OSError, PermissionError) as exception:
            log_error(
                "Could not open %s (%s) - skipping %s processing"
                % (extensions_file_name, extensions_file_name, exception.args)
            )
            return 1
        else:
            f_init_extension = False
            if sections[0] == "init_extension":
                f_init_extension = True
                section_list = cp.sections()
            else:
                section_list = sections
            for section in section_list:
                if cp.has_section(section):
                    for extension_line in cp[section]:
                        extension_line.lstrip().rstrip()
                        if len(extension_line) < 1:
                            continue
                        if not f_init_extension:
                            log_info(
                                f"Processing:{extensions_file_name} section:{section} line:{extension_line}"
                            )
                        extension_elts = extension_line.split(" ")
                        # First element - extension name, with .py file extension
                        if extension_elts[0] in Globals.extensions_to_skip:
                            log_warning(
                                f"Skipping processing of {extension_elts[0]} - {Globals.extensions_to_skip[extension_elts[0]]}"
                            )
                            continue

                        for search_path in (
                            base_opts.basestation_directory,
                            additional_search_path,
                        ):
                            if search_path is None:
                                continue
                            extension_module_name = os.path.join(
                                search_path, extension_elts[0]
                            )
                            if not os.path.exists(extension_module_name):
                                log_debug(
                                    f"Extension {extension_module_name} does not exist - skipping"
                                )
                                continue
                            extension_module = Utils.loadmodule(extension_module_name)
                            if extension_module is None:
                                log_error(
                                    f"Error loading {extension_module_name} - skipping"
                                )
                                continue
                            log_info(f"Running {extension_module_name}")

                            if f_init_extension:
                                if not hasattr(extension_module, "init_extension"):
                                    continue
                                log_info(
                                    f"Calling init_extension on {extension_module_name}"
                                )
                                try:
                                    extension_ret_val = extension_module.init_extension(
                                        extension_module_name,
                                        base_opts=base_opts,
                                        **kwargs,
                                    )
                                except Exception:
                                    log_error(
                                        f"Extension {extension_module_name} raisedb an exception callinig init_extension",
                                        "exc",
                                    )
                                    extension_ret_val = 1
                                if extension_ret_val:
                                    log_error(
                                        "Error running %s - return %d"
                                        % (extension_module_name, extension_ret_val)
                                    )
                                    ret_val |= extension_ret_val
                            else:
                                try:
                                    # Invoke the extension
                                    extension_ret_val = extension_module.main(
                                        base_opts=base_opts,
                                        sg_calib_file_name=sg_calib_file_name,
                                        dive_nc_file_names=dive_nc_file_names,
                                        nc_files_created=nc_files_created,
                                        processed_other_files=processed_other_files,
                                        known_mailer_tags=known_mailer_tags,
                                        known_ftp_tags=known_ftp_tags,
                                        processed_file_names=processed_file_names,
                                        **kwargs,
                                    )
                                except Exception:
                                    log_error(
                                        "Extension %s raised an exception"
                                        % extension_module_name,
                                        "exc",
                                    )
                                    extension_ret_val = 1
                                if extension_ret_val:
                                    log_error(
                                        "Error running %s - return %d"
                                        % (extension_module_name, extension_ret_val)
                                    )
                                    ret_val |= extension_ret_val
            if log_output_info:
                log_info(f"Finished processing on {extensions_file_name}")
            else:
                log_debug(f"Finished processing on {extensions_file_name}")
        return ret_val

    ret_val = 0
    for extensions_file_name, additional_search_path in (
        (base_opts.basestation_etc / ".extensions", None),
        (
            base_opts.group_etc / ".extensions" if base_opts.group_etc else None,
            base_opts.group_etc,
        ),
        (base_opts.mission_dir / ".extensions", base_opts.mission_dir),
    ):
        if extensions_file_name is None:
            continue
        if not os.path.exists(extensions_file_name):
            log_debug(f"No .extensions file {extensions_file_name} found")
            continue
        ret_val |= process_one_extension_file(
            extensions_file_name, additional_search_path, sections
        )

    return ret_val


def pagers_to_yml(base_opts: BaseOpts.BaseOptions) -> int:
    """The pagers_to_yml action: converts a .pagers file to pagers.yml, checked before it's written.

    Args:
        base_opts: Options (pagers_file or mission_dir, and pagers_yml_out).

    Returns:
        0 on success, 1 if there was nothing to convert, the result didn't validate, or
        the output file already exists.

    Raises:
        None.
    """
    import BaseCtrlFiles  # here: BaseCtrlFiles imports this module

    src = base_opts.pagers_file or (base_opts.mission_dir / ".pagers" if base_opts.mission_dir else None)
    if src is None or not src.exists():
        log_error(f"No .pagers file to convert ({src or 'give --pagers_file or --mission_dir'})")
        return 1
    out = base_opts.pagers_yml_out
    if out is not None and out.exists():
        log_error(f"{out} already exists - not overwriting it")
        return 1

    contents, warnings = convert_pagers_to_yml(src.read_text(errors="replace").splitlines())
    for msg in warnings:
        log_warning(f"{src}: {msg}")
    if not contents:
        log_error(f"Nothing to convert in {src}")
        return 1
    text = f"# pagers.yml converted from {src} by BaseDotFiles.py pagers_to_yml\n" + yaml.safe_dump(
        contents, sort_keys=False, default_flow_style=None, width=120
    )

    # Validate exactly what would be written
    with tempfile.TemporaryDirectory() as tmp:
        check_file = pathlib.Path(tmp) / "pagers.yml"
        check_file.write_text(text)
        _, errors, _ = BaseCtrlFiles.check_pagers_file(check_file)
    if errors:
        for msg in errors:
            log_error(f"converted pagers.yml doesn't validate: {msg}")
        return 1

    if out is None:
        # The converted file itself, for redirecting - data, not a message, so
        # stdout rather than the logger (messages above all go through the logger)
        print(text, end="")
    else:
        out.write_text(text)
        log_info(f"Wrote {out}")
    return 0


def main(cmdline_args: list[str] | None = None) -> int | None:
    """cli test/utility for dot file processing

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    # pylint: disable=unused-argument
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation dot file processing",
        cmdline_args=cmdline_args,
        additional_arguments={
            "basedotfiles_action": BaseOptsType.options_t(
                (),
                {
                    "BaseDotFiles",
                },
                ("basedotfiles_action",),
                str,
                {
                    "help": "Which action to run",
                    "choices": ("gps", "drift", "ftp", "sftp", "ftps", "urls", "pagers_to_yml"),
                },
            ),
            "ftp_files": BaseOptsType.options_t(
                [],
                {
                    "BaseDotFiles",
                },
                ("ftp_files",),
                str,
                {
                    "help": "List of files to upload",
                    "nargs": "*",
                },
            ),
            "pagers_file": BaseOptsType.options_t(
                None,
                {"BaseDotFiles"},
                ("--pagers_file",),
                BaseOpts.FullPathlib,
                {
                    "help": "pagers_to_yml: the .pagers file to convert (default: the mission dir's .pagers)",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "pagers_yml_out": BaseOptsType.options_t(
                None,
                {"BaseDotFiles"},
                ("--pagers_yml_out",),
                BaseOpts.FullPathlib,
                {
                    "help": "pagers_to_yml: write the pagers.yml here (default: print it); never overwrites",
                    "action": BaseOpts.FullPathlibAction,
                },
            ),
            "pass_num": BaseOptsType.options_t(
                1,
                {
                    "BaseDotFiles",
                },
                ("pass_num",),
                int,
                {
                    "help": "URLs pass number",
                    "nargs": "?",
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if base_opts.basedotfiles_action == "pagers_to_yml":
        return pagers_to_yml(base_opts)

    if not base_opts.mission_dir:
        log_error(f"{base_opts.basedotfiles_action} needs --mission_dir")
        return 1

    if base_opts.basedotfiles_action in ("gps", "drift", "urls"):
        comm_log = CommLog.process_comm_log(
            base_opts.mission_dir / "comm.log", base_opts, scan_back=False
        )[0]

        if comm_log is None:
            log_error("Could not process comm.log")
            return

    if base_opts.basedotfiles_action in ("gps", "drift"):
        process_pagers(
            base_opts,
            comm_log.last_complete_surfacing().sg_id,
            (base_opts.basedotfiles_action,),
            comm_log=comm_log,
        )
    elif base_opts.basedotfiles_action == "ftp":
        process_ftp(
            base_opts,
            [os.path.join(base_opts.mission_dir, ii) for ii in base_opts.ftp_files],
            Utils2.get_mission_timeseries_name(base_opts),
            None,
            Globals.known_ftp_tags,
        )
    elif base_opts.basedotfiles_action == "sftp":
        process_ftp(
            base_opts,
            [os.path.join(base_opts.mission_dir, ii) for ii in base_opts.ftp_files],
            Utils2.get_mission_timeseries_name(base_opts),
            None,
            Globals.known_ftp_tags,
            ftp_type=".sftp",
        )
    elif base_opts.basedotfiles_action == "ftps":
        process_ftp(
            base_opts,
            [os.path.join(base_opts.mission_dir, ii) for ii in base_opts.ftp_files],
            Utils2.get_mission_timeseries_name(base_opts),
            None,
            Globals.known_ftp_tags,
            ftp_type=".ftps",
        )
    elif base_opts.basedotfiles_action == "urls":
        process_urls(
            base_opts,
            base_opts.pass_num,
            comm_log.last_complete_surfacing().sg_id,
            comm_log.last_complete_surfacing().dive_num,
        )
    else:
        log_error("Unkown action {base_opts.basedotfiles_action}")


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main() or 0
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")

    sys.exit(retval)
