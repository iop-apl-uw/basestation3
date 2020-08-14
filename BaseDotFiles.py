##
## Copyright (c) 2006-2020 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

"""
BaseDotFiles.py: Processing for various configuration files that reside in the glider
home directory (or other locations)

"""

import fnmatch
import netrc
import os
import smtplib
import socket
import sys
import time

from email.utils import COMMASPACE, formatdate
from email.mime.multipart import MIMEMultipart, MIMEBase
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email import encoders
from ftplib import FTP
from urllib.parse import urlencode
from urllib.request import urlopen

import BaseGZip
import CommLog
import Sensors

from BaseLog import log_error, log_warning, log_info, log_debug

# Configuration
mail_server = "localhost"

# Centeralized approach
# 1) Start with .pagers
# 2) Separate out message dispatch from lookup
# 3) Allow for multiple lookup functions (taking instrument_id, name and tag), returning lists.
# 4) Possible merge or overwrite of lists from lookup routines
# 5) One routine that sends out messages
# 6)

# For some reason, this doesn't really work
# pagers_ext = {'html' : lambda *args: send_email(*args, html_format=True)}
pagers_ext = {
    "html": lambda base_opts, instrument_id, email_addr, subject_line, message_body: send_email(
        base_opts,
        instrument_id,
        email_addr,
        subject_line,
        message_body,
        html_format=True,
    )
}
# inReach message sender
try:
    import InReachSend
except ImportError:
    pass
else:
    pagers_ext["inreach"] = InReachSend.send_inreach

# slack post
try:
    import SlackPost
except ImportError:
    print("Failed slack import")
else:
    pagers_ext["slack"] = SlackPost.post_slack


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
                email_msg[
                    "Reply-To"
                ] = from_email_addr  # smtp servers often rewrite from_line to use 'Original Name <account_name@gmail.com>'
        else:  # linux of some sort
            smtp = smtplib.SMTP("localhost")
        smtp.sendmail(email_send_from, email_send_to, email_msg.as_string())
        smtp.close()
    except:
        log_error(
            "Unable to send message %s (%s) to %s"
            % (subject_line, message_body, to_email_addr),
            "exc",
        )
        log_info("Continuing processing...")
        return 1
    else:
        return 0


def process_urls(base_opts, pass_num_or_gps, instrument_id, dive_num):
    """Process the urls file - supplying different arguments for the first and second pass
    """
    # Process urls
    urls_file_name = os.path.join(base_opts.mission_dir, ".urls")
    if not os.path.exists(urls_file_name):
        log_info(
            f"No .urls file found - skipping .urls processing pass {pass_num_or_gps}"
        )
    elif dive_num is None:
        log_error("dive_num is not an integer - skipping .urls file processing")
    elif instrument_id is None:
        log_error("instrument_id is not an integer - skipping .urls file processing")
    else:
        log_info(f"Starting processing on .urls pass({pass_num_or_gps})")
        try:
            urls_file = open(urls_file_name, "r")
        except IOError as exception:
            log_error(
                f"Could not open {urls_file_name} ({exception.args}) - no urls notified"
            )
        else:
            for urls_line in urls_file:
                urls_line = urls_line.rstrip()
                log_debug(f"urls line = ({urls_line})")
                if urls_line == "":
                    continue
                if urls_line[0] != "#":
                    log_info(f"Processing .urls line ({urls_line})")
                    urls_elts = urls_line.split()
                    if len(urls_elts) > 2:
                        log_error(f"Too many entries on line ({urls_line})")
                    socket.setdefaulttimeout(int(urls_elts[0]))
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
                        url_response = urlopen(url_line).read()
                    except:
                        log_error(f"Error opening {url_line}", "exc")
                        log_error("Continuing processing...")
                    else:
                        log_info(
                            f"url ({url_line}) responded with:{url_response}"
                        )

        log_info(f"Finished processing on .urls pass({pass_num_or_gps})")


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
    """Processes the .pagers file for the tags specified
    """

    pagers_file_name = os.path.join(base_opts.mission_dir, ".pagers")
    if not os.path.exists(pagers_file_name):
        log_info("No .pagers file found - skipping .pagers processing")
    else:
        tags = ""
        for t in tags_to_process:
            tags = f"{tags} {t}"
        log_info(f"Starting processing on .pagers for {tags}")
        log_debug(f"pagers_ext = {pagers_ext}")
        try:
            pagers_file = open(pagers_file_name, "r")
        except IOError as exception:
            log_error(
                f"Could not open {pagers_file_name} ({exception.args}) - no mail sent"
            )
        else:
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
                    if len(pagers_elts) > 1 and (
                        pagers_elts[1] in list(pagers_ext.keys())
                    ):
                        log_info(f"Using sending function {pagers_elts[1]}")
                        send_func = pagers_ext[pagers_elts[1]]
                        pagers_elts = pagers_elts[2:]
                    else:
                        send_func = send_email
                        pagers_elts = pagers_elts[1:]

                    tags_with_fmt = ["lategps", "gps", "recov", "critical"]
                    known_tags = [
                        "lategps",
                        "gps",
                        "recov",
                        "critical",
                        "drift",
                        "divetar",
                        "comp",
                        "alerts",
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
                                subject_line = "Drift"
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

                            if comm_log:
                                (
                                    gps_message,
                                    recov_code,
                                    escape_reason,
                                    prefix_str,
                                ) = comm_log.last_GPS_lat_lon_and_recov(
                                    fmt, dive_prefix
                                )
                                reboot_msg = comm_log.has_glider_rebooted()
                            elif session:
                                (
                                    gps_message,
                                    recov_code,
                                    escape_reason,
                                    prefix_str,
                                ) = CommLog.GPS_lat_lon_and_recov(
                                    fmt, dive_prefix, session
                                )
                                if msg_prefix:
                                    gps_message = f"{msg_prefix}{gps_message}"
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
                                prefix_str = " SG%03d %s" % (instrument_id, prefix_str)

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
                                subject_line = "CONVERSION PROBLEMS"
                                log_info(
                                    f"Sending {subject_line} to {email_addr}"
                                )
                                send_func(
                                    base_opts,
                                    instrument_id,
                                    email_addr,
                                    subject_line,
                                    pagers_convert_msg,
                                )
                            if crit_other_message and crit_other_message != "":
                                subject_line = "CRITICAL ERROR IN CAPTURE"
                                log_info(
                                    f"Sending {subject_line} to {email_addr}"
                                )
                                send_func(
                                    base_opts,
                                    instrument_id,
                                    email_addr,
                                    subject_line,
                                    crit_other_message,
                                )
                            if warn_message and warn_message != "":
                                subject_line = "ALERTS FROM PROCESSING"
                                log_info(
                                    f"Sending {subject_line} to {email_addr}"
                                )
                                send_func(
                                    base_opts,
                                    instrument_id,
                                    email_addr,
                                    subject_line,
                                    warn_message,
                                )

                        elif pagers_tag == "comp" and "comp" in tags_to_process:
                            if (
                                processed_files_message
                                and processed_files_message != ""
                            ):
                                subject_line = "Processing Complete"
                                log_info(
                                    f"Sending {subject_line} to {email_addr}"
                                )
                                send_func(
                                    base_opts,
                                    instrument_id,
                                    email_addr,
                                    subject_line,
                                    processed_files_message,
                                )

                        elif pagers_tag == "divetar" and "divetar" in tags_to_process:
                            if (
                                processed_files_message
                                and processed_files_message != ""
                            ):
                                subject_line = "New Dive Tarball(s)"
                                log_info(
                                    f"Sending {subject_line} to {email_addr}"
                                )
                                send_func(
                                    base_opts,
                                    instrument_id,
                                    email_addr,
                                    subject_line,
                                    processed_files_message,
                                )

        log_info("Finished processing on .pagers")


def process_ftp_line(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    ftp_line,
    known_ftp_tags,
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

    Returns
      0 - success
      1 - failure
    """

    ftp_line = ftp_line.rstrip()
    log_debug(f"ftp line = ({ftp_line})")
    if ftp_line == "":  # blank line
        return 0
    if ftp_line[0] == "#":  # not a comment
        return 0

    log_info(f"Processing ftp line ({ftp_line})")
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
        except:
            log_warning("Could not process .netrc", "exc")
        else:
            if auth is not None:
                user, _, pwd = auth

    log_info(f"user:{user},host:{host},port:{port},path:{path}")

    # Tags - what to send
    ftp_tags = ftp_tags[1:]

    temp_tags = ftp_tags
    for i in range(len(temp_tags)):
        ftp_tags[i] = temp_tags[i].lower().rstrip().lstrip()

    # Check for what file type
    try:
        ftp_tags.index("all")
    except:
        pass
    else:
        ftp_tags = known_ftp_tags

    # Collect file to send into a list
    ftp_file_names_to_send = []

    for ftp_tag in ftp_tags:
        if not ftp_tag in known_ftp_tags:
            log_error(f"Unknown tag ({ftp_tag}) on line ({ftp_line}) - skipping")
        else:
            if ftp_tag == "comm":
                ftp_file_names_to_send.append(
                    os.path.join(base_opts.mission_dir, "comm.log")
                )
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

    if len(ftp_file_names_to_send) < 1:
        return 0  # nothing to send

    log_debug(f"ftp files to send {ftp_file_names_to_send}")
    # Connect
    try:
        ftp = FTP(host)
    except:
        log_error("Unable to connect", "exc")
        return 1  # give up
    try:
        ftp.login(user, pwd)
    except:
        log_error("Unable to login", "exc")
        return 1  # give up

    for i in path.split("/"):
        try:
            # We used to look via LIST to see if the subdir exists
            # but some sites protect against listing.
            # So just blindly try cd'ing to it and deal with the consequences
            ftp.cwd(i)  # try to cd to subdir
        except:
            try:
                ftp.mkd(i)  # Doesn't appear to exist; try to create it
            except:
                log_error(f"Could not make {i}", "exc")
                return 1  # give up
            ftp.cwd(i)  # cd to what we just created

    result = 0  # assume the best
    for ftp_file_name_to_send in ftp_file_names_to_send:
        head, tail = os.path.split(ftp_file_name_to_send)
        try:
            fi = open(ftp_file_name_to_send, "r")
        except:
            log_error(f"Unable to open {ftp_file_name_to_send} - skipping", "exc")
            result = 1  # we had issues
        else:
            try:
                ftp.storbinary(f"STOR {tail}", fi)
            except:
                log_error(f"Unable to send {ftp_file_name_to_send} - skipping", "exc")
                result = 1  # we had issues
            else:
                log_info(f"Sent {ftp_file_name_to_send}")
            fi.close()

    # Shutdown
    ftp.quit()
    return result


def process_ftp(
    base_opts,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
    known_ftp_tags,
):
    """ Process the .ftp file and push the data to a ftp server
    """
    ret_val = 0
    ftp_file_name = os.path.join(base_opts.mission_dir, ".ftp")
    if not os.path.exists(ftp_file_name):
        log_info("No .ftp file found - skipping .ftp processing")
        return 0

    log_info("Starting processing on .ftp")
    try:
        ftp_file = open(ftp_file_name, "r")
    except IOError as exception:
        log_error(
            f"Could not open {ftp_file_name} ({exception.args}) - no mail sent"
        )
        ret_val = 1
    else:
        for ftp_line in ftp_file:
            try:
                process_ftp_line(
                    base_opts,
                    processed_file_names,
                    mission_timeseries_name,
                    mission_profile_name,
                    ftp_line,
                    known_ftp_tags,
                )
            except:
                log_error(f"Could not process {ftp_line} - skipping", "exc")
    log_info("Finished processing on .ftp")
    return ret_val


def process_mailer(
    base_opts,
    instrument_id,
    known_mailer_tags,
    processed_file_names,
    mission_timeseries_name,
    mission_profile_name,
):
    """ Process the .mailer file and send out email
    """
    mailer_file_name = os.path.join(base_opts.mission_dir, ".mailer")
    if not os.path.exists(mailer_file_name):
        log_info("No .mailer file found - skipping .mailer processing")
    else:
        log_info("Starting processing on .mailer")
        try:
            mailer_file = open(mailer_file_name, "r")
        except IOError as exception:
            log_error(
                f"Could not open {mailer_file_name} ({exception.args}) - no mail sent"
            )
        else:
            mailer_conversion_time = time.strftime(
                "%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())
            )
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
                    except:
                        mailer_file_in_body = False
                    else:
                        mailer_tags.remove("body")
                        mailer_file_in_body = True

                    # Check for msgperfile
                    try:
                        mailer_tags.index("msgperfile")
                    except:
                        mailer_msg_per_file = False
                    else:
                        mailer_tags.remove("msgperfile")
                        mailer_msg_per_file = True

                    # Remove the Navy header tag, if present,
                    try:
                        mailer_tags.index("kkyy_subject")
                    except:
                        mailer_subject = "SG%03d files" % (instrument_id)
                    else:
                        mailer_tags.remove("kkyy_subject")
                        mailer_subject = "XBTDATA"

                    # Remove the gzip tag, if present
                    try:
                        mailer_tags.index("gzip")
                    except:
                        mailer_gzip_file = False
                    else:
                        mailer_tags.remove("gzip")
                        if mailer_file_in_body:
                            log_error(
                                "Options body and gzip incompatibile - skipping gzip"
                            )
                            mailer_gzip_file = False
                        else:
                            mailer_gzip_file = True

                    # Check for what file type
                    try:
                        mailer_tags.index("all")
                    except:
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
                                    mailer_file_names_to_send.append(
                                        processed_file_name
                                    )
                                    log_info(f"Matched {processed_file_name}")
                        elif not mailer_tag in known_mailer_tags:
                            log_error(
                                "Unknown tag (%s) on line (%s) in %s - skipping"
                                % (mailer_tag, mailer_line, mailer_file_name)
                            )
                        else:
                            if mailer_tag == "comm":
                                mailer_file_names_to_send.append(
                                    os.path.join(base_opts.mission_dir, "comm.log")
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
                            mailer_msg["To"] = COMMASPACE.join(
                                list(mailer_send_to_list)
                            )
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
                                fi = open(mailer_file_name_to_send, "r")
                                mailer_text = mailer_text + fi.read()
                                fi.close()
                            except:
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
                                        mailer_part.set_payload(
                                            open(
                                                mailer_gzip_file_name_to_send, "rb"
                                            ).read()
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
                                    ):
                                        mailer_part = MIMEBase(
                                            "application", "octet-stream"
                                        )
                                        mailer_part.set_payload(
                                            open(mailer_file_name_to_send, "rb").read()
                                        )
                                    else:
                                        mailer_part = MIMEBase("text", "plain")
                                        mailer_part.set_payload(
                                            open(mailer_file_name_to_send, "r").read()
                                        )
                                    encoders.encode_base64(mailer_part)
                                    mailer_part.add_header(
                                        "Content-Disposition",
                                        'attachment; filename="%s"'
                                        % os.path.basename(mailer_file_name_to_send),
                                    )
                                    mailer_msg.attach(mailer_part)
                            except:
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
                                except:
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
                            except:
                                log_error(
                                    f"Unable to send message [{mailer_line}] skipping",
                                    "exc",
                                )
                                log_info("Continuing processing...")
                        mailer_msg = None

        log_info("Finished processing on .mailer")


def process_extensions(
    extension_file_name,
    base_opts,
    sg_calib_file_name,
    dive_nc_file_names,
    nc_files_created,
    processed_other_files,
    known_mailer_tags,
    known_ftp_tags,
):
    """Processes the extensions file, running each extension

    Returns:
        0 - success
        1 - failure
    """
    ret_val = 0
    extension_directory = base_opts.basestation_directory
    extensions_file_name = os.path.join(base_opts.mission_dir, extension_file_name)
    if not os.path.exists(extensions_file_name):
        log_info(
            "No %s file found - skipping %s processing"
            % (extension_file_name, extension_file_name)
        )
        return 0
    else:
        log_info(f"Starting processing on {extension_file_name}")
        try:
            extensions_file = open(extensions_file_name, "r")
        except IOError as exception:
            log_error(
                "Could not open %s (%s) - skipping %s processing"
                % (extensions_file_name, extension_file_name, exception.args)
            )
            ret_val = 1
        else:
            for extension_line in extensions_file:
                extension_line = extension_line.rstrip()
                log_debug(f"extension file line = ({extension_line})")
                if extension_line == "":
                    continue
                if extension_line[0] != "#":
                    log_info(
                        f"Processing {extension_file_name} line ({extension_line})"
                    )
                    extension_elts = extension_line.split(" ")
                    # First element - extension name, with .py file extension
                    extension_module_name = os.path.join(
                        extension_directory, extension_elts[0]
                    )
                    extension_module = Sensors.loadmodule(extension_module_name)
                    if extension_module is None:
                        log_error(f"Error loading {extension_module_name} - skipping")
                        ret_val = 1
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
                            )
                        except:
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
                            ret_val = 1

        log_info(f"Finished processing on {extension_file_name}")

    return ret_val