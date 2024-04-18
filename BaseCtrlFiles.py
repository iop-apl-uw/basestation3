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

"""
BaseDotFiles.py: Processing for various configuration files that reside in the glider
home directory (or other locations)

"""

import copy
import functools
import json
import os
import pdb
import sys
import time
import traceback

import requests
import yaml

import BaseDotFiles
import BaseOpts
import CommLog
from BaseLog import (
    BaseLogger,
    log_critical,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = "darwin" in sys.platform
# DEBUG_PDB = True

pagers_msgs = (
    "lategps",
    "gps",
    "recov",
    "critical",
    "drift",
    "divetar",
    "comp",
    "alerts",
    "errors",
)

pagers_send_funcs = ["email", "slack", "mattermost", "inreach"]


def send_email(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]

    if "address" not in endpoint:
        log_error(f"Missing email address for user:{user}, endpoint:{endpoint}")
        return

    html_format = False
    if "format" in endpoint:
        if endpoint["format"] == "html":
            html_format = True
        else:
            log_error("Unknown email format:{endpoint['format']} - defaulting to text")

    log_info(
        "Sending %s (%s) to %s" % (subject_line, message_body, endpoint["address"])
    )

    BaseDotFiles.send_email(
        base_opts,
        instrument_id,
        endpoint["address"],
        subject_line,
        message_body,
        html_format=html_format,
    )


def send_slack(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "hook" not in endpoint:
        log_error(f"Missing hook address for user:{user}, endpoint:{endpoint}")
        return
    else:
        hook_url = endpoint["hook"]

    msg = {"text": "%s:%s" % (subject_line, message_body)}

    try:
        response = requests.post(
            hook_url,
            data=json.dumps(msg),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                "Request to slack returned an error %s, the response is:%s"
                % (response.status_code, response.text)
            )
    except Exception:
        log_error("Error in post", "exc")


def send_mattermost(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "hook" not in endpoint:
        log_error(f"Missing hook address for user:{user}, endpoint:{endpoint}")
        return
    else:
        hook_url = endpoint["hook"]

    msg_str = f"{subject_line}:{message_body}"

    if "mention" in endpoint:
        if isinstance(endpoint["mention"], list):
            for mention in endpoint["mention"]:
                msg_str = f"{mention} {msg_str}"
        else:
            msg_str = f"{endpoint['mention']} {msg_str}"

    msg = {"text": msg_str}

    if "username" in endpoint:
        msg["username"] = endpoint["username"]

    if "channel" in endpoint:
        msg["channel"] = endpoint["channel"]

    log_info(f"mattermost_hook_url:{hook_url} msg:{msg}")

    try:
        response = requests.post(
            hook_url,
            data=json.dumps(msg),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                "Request to mattermost returned an error %s, the response is:%s"
                % (response.status_code, response.text)
            )
    except Exception:
        log_error(f"Error in post user:{user}, endpoint:{endpoint}", "exc")


def send_inreach(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
) -> None:
    log_info("send_inreach NYI")
    pass


pagers_sendfuncs = {
    "email": send_email,
    "slack": send_slack,
    "inreach": send_inreach,
    "mattermost": send_mattermost,
}

base_pagers_dict = {}
for pa in pagers_msgs:
    base_pagers_dict[pa] = []


def merge_dict(a, b, path=None, allow_override=True):
    "Merges dict b into dict a"
    if path is None:
        path = []
    for key in b:
        if key in a:
            if isinstance(a[key], dict) and isinstance(b[key], dict):
                merge_dict(a[key], b[key], path + [str(key)])
            elif a[key] == b[key]:
                pass  # same leaf value
            elif isinstance(a[key], list):
                if isinstance(b[key], list):
                    a[key] = sum([a[key], b[key]], [])
                else:
                    a[key].append(b[key])
            elif allow_override:
                a[key] = b[key]
            else:
                raise Exception("Conflict at %s" % ".".join(path + [str(key)]))
        else:
            a[key] = b[key]
    return a


def load_ctrl_yml(
    base_opts: BaseOpts.BaseOptions,
    ctrl_file_name: str,
    default_dict: dict | None = None,
) -> dict:
    """Load ctrl yaml files and merge into one"""

    if default_dict:
        yml_dicts = [default_dict]
    else:
        yml_dicts = [{}]

    for yml_file_name in (
        os.path.join(base_opts.basestation_etc, ctrl_file_name),
        os.path.join(base_opts.group_etc, ctrl_file_name)
        if base_opts.group_etc
        else None,
        os.path.join(base_opts.mission_dir, ctrl_file_name),
    ):
        if yml_file_name is None:
            continue
        if not os.path.exists(yml_file_name):
            log_info(f"No ctrl file {yml_file_name} found - skipping")
            continue
        try:
            with open(yml_file_name, "r") as fi:
                # CONSIDER - run check_canonicalize_pagers_dict(pagers_dict) over each
                #           dict as loaded - help with error processing some errors.
                #           Downside - would need to push off checking on defined uses
                #           as later yml files might define them
                yml_dicts.append(yaml.safe_load(fi.read()))
        except Exception:
            log_error(f"Could not procss {yml_file_name} - skipping", "exc")

    # Merge dicts together
    try:
        functools.reduce(merge_dict, yml_dicts)
    except Exception:
        log_error("Error merging config templates", "exc")
        return None

    return yml_dicts[0]


def check_canonicalize_pagers_dict(pagers_dict: dict) -> dict:
    """Process pagers dict - clean up and add any missing states"""
    pagers_updated_dict = {"subscriptions": {}, "users": {}}
    for k, v in pagers_dict.items():
        if k in pagers_msgs:
            new_user_set = set()
            for user in v:
                if user not in pagers_dict:
                    log_warning(f"User {user} (from {k}:{v}) not defined")
                else:
                    new_user_set.add(user)
            if new_user_set:
                pagers_updated_dict["subscriptions"][k] = new_user_set
        elif isinstance(v, dict):
            updated_user_dict = {}
            for sf, sf_list in pagers_dict[k].items():
                if sf == "latlon":
                    if sf_list not in ("ddmm", "dddd", "ddmmss"):
                        log_warning(
                            f"Unknown latlon format {sf} for user {k} - resetting to ddmm"
                        )
                        updated_user_dict[sf] = "ddmm"
                    else:
                        updated_user_dict[sf] = sf_list
                    continue

                if sf == "status":
                    if not isinstance(sf_list, bool):
                        log_warning(
                            f"Status not a bool {sf_list} for user {k} - resetting to True"
                        )
                        updated_user_dict[sf] = "ddmm"
                    else:
                        updated_user_dict[sf] = sf_list
                    continue

                if sf not in pagers_send_funcs:
                    log_error(
                        f"Unknown send_func type {sf} for user {k} - skipping user"
                    )
                    continue

                # Convert single dict endpoints to a list
                if isinstance(sf_list, dict):
                    sf_list = [sf_list]

                if not isinstance(sf_list, list):
                    log_error(
                        f"Endpoints must be a list or dict - user:{k}, send_func{sf}, {sf_list} - skipping endpoints"
                    )
                    continue

                updated_endpoint_list = []
                for ep in sf_list:
                    if not isinstance(ep, dict):
                        log_error(
                            f"Endpoint must be a dict - user:{k}, send_func{sf}, {ep} - skipping endpoint"
                        )
                        continue
                    if "filters" in ep:
                        if not isinstance(ep["filters"], list):
                            log_error(
                                f"filters specification must be a list - user:{k}, send_func{sf}, {ep} - skipping endpoint"
                            )
                            continue
                        for filter_str in ep["filters"]:
                            if filter_str not in pagers_msgs:
                                log_error(
                                    f"filter ({filter_str}) not in known send functions - user:{k}, send_func{sf}, {ep} - skipping endpoint"
                                )
                            continue
                    updated_endpoint_list.append(ep)
                updated_user_dict[sf] = updated_endpoint_list

            # Set any missing states
            if "latlon" not in updated_user_dict:
                updated_user_dict["latlon"] = "ddmm"
            if "status" not in updated_user_dict:
                updated_user_dict["latlon"] = True

            # Further user valdation goes here = status and latlon
            pagers_updated_dict["users"][k] = updated_user_dict
        else:
            log_error(f"Users must be dicts {k}:{v}")

    return pagers_updated_dict


def dump_pagers_dict(pagers_dict: dict) -> None:
    """Dumps the pagers dict to the logging system"""
    for k, v in pagers_dict["users"].items():
        log_info(f"user:{k}")
        for kk, vv in v.items():
            log_info(f"    {kk}:{vv}")

    pagers_msgs_str = ""
    for k, v in pagers_dict["subscriptions"].items():
        pagers_msgs_str += f"{k}:{v} "

    if pagers_msgs_str:
        log_info(f"Subscriptions: {pagers_msgs_str}")


def find_send_list(pagers_dict: dict, msg: str) -> list:
    """Generate a list dicts of users, send_funcs and endpoints that subscribed to the msg"""
    send_list: list[dict] = []
    for user in pagers_dict["subscriptions"][msg]:
        for sf, sf_list in pagers_dict["users"][user].items():
            if sf in ("status", "latlon"):
                continue
            for endpoint in sf_list:
                if "filters" in endpoint and msg not in endpoint["filters"]:
                    continue
                if "status" in endpoint:
                    f_send = endpoint["status"]
                else:
                    f_send = pagers_dict["users"][user]["status"]
                if f_send:
                    if "latlon" in endpoint:
                        latlon = endpoint["latlon"]
                    else:
                        latlon = pagers_dict["users"][user]["latlon"]
                    send_list.append(
                        {
                            "user": user,
                            "send_func": pagers_sendfuncs[sf],
                            "endpoint": endpoint,
                            "latlon": latlon,
                        }
                    )
    return send_list


def process_pagers_yml(
    base_opts,
    instrument_id,
    msgs_to_process,
    comm_log=None,
    session=None,
    pagers_convert_msg=None,
    processed_files_message=None,
    msg_prefix=None,
    crit_other_message=None,
    warn_message=None,
):
    """Processes the pagers.yml"""

    # Possible speed up during normal processing - static variable
    # if hasattr(process_pagers_yml, "pagers_dict"):
    #    pagers_dict = process_pagers_yml.pagers_dict
    # else:
    #    Code below - stash in attribute when checked

    pagers_dict = load_ctrl_yml(
        base_opts, "pagers.yml", copy.deepcopy(base_pagers_dict)
    )
    if pagers_dict is None:
        log_error("Failed to load pager(s).yml - bailing out")
        return

    pagers_dict = check_canonicalize_pagers_dict(pagers_dict)

    # dump_pagers_dict(pagers_dict)

    for msg in msgs_to_process:
        if msg not in pagers_dict["subscriptions"]:
            continue

        send_list = find_send_list(pagers_dict, msg)
        if not send_list:
            continue

        for si in send_list:
            match msg:
                case "drift":
                    if comm_log:
                        drift_message = comm_log.predict_drift(si["latlon"])
                        subject_line = "Drift"
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            drift_message,
                        )
                    else:
                        log_warning(
                            f"Internal error - no comm log - skipping drift predictions for ({si['user']})"
                        )

                case "gps" | "recov" | "critical" | "lategps":
                    dive_prefix = True
                    if comm_log:
                        (
                            gps_message,
                            recov_code,
                            escape_reason,
                            prefix_str,
                        ) = comm_log.last_GPS_lat_lon_and_recov(
                            si["latlon"], dive_prefix
                        )
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
                        ) = CommLog.GPS_lat_lon_and_recov(
                            si["latlon"], dive_prefix, session
                        )
                        if msg_prefix:
                            gps_message = f"{msg_prefix}{gps_message}"
                        try:

                            def convert_f(x):
                                """Conversion helper"""
                                return f"{x:.2f}" if x is not None else "None"

                            gps_message = "%s D=%s,pit=%s,RH=%s,P=%s,24V=%s,10V=%s" % (
                                gps_message,
                                convert_f(session.depth),
                                convert_f(session.obs_pitch),
                                convert_f(session.rh),
                                convert_f(session.int_press),
                                convert_f(session.volt_24V),
                                convert_f(session.volt_10V),
                            )
                        except Exception:
                            log_error("Problem formatting GPS message", "exc")
                        reboot_msg = None
                    else:
                        log_warning(
                            f"Internal error - no comm log, session or critical message supplied - skipping ({si['user']})"
                        )
                        continue

                    if reboot_msg:
                        gps_message = f"{gps_message}\n{reboot_msg}"

                    if prefix_str:
                        prefix_str = " SG%03d %s" % (
                            instrument_id,
                            prefix_str,
                        )

                    if msg in ("gps", "lategps"):
                        subject_line = f"GPS{prefix_str}"
                    elif msg in ("critical", "recov") and reboot_msg:
                        subject_line = f"REBOOTED{prefix_str}"
                    elif (
                        msg == "critical"
                        and recov_code
                        and recov_code != "QUIT_COMMAND"
                    ):
                        subject_line = f"IN NON-QUIT RECOVERY{prefix_str}"
                    elif msg == "recov" and recov_code:
                        subject_line = f"IN RECOVERY{prefix_str}"
                    elif msg == "recov" and escape_reason:
                        subject_line = f"IN ESCAPE{prefix_str}"
                    else:
                        subject_line = None

                    if subject_line is not None:
                        log_info(
                            f"Sending {subject_line} ({gps_message}) to {si['user']}"
                        )
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            gps_message,
                        )

                case "alerts":
                    if pagers_convert_msg and pagers_convert_msg != "":
                        subject_line = f"CONVERSION PROBLEMS SG{instrument_id:03d} "
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            pagers_convert_msg,
                        )
                    if crit_other_message and crit_other_message != "":
                        subject_line = (
                            f"CRITICAL ERROR IN CAPTURE SG{instrument_id:03d}"
                        )
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            crit_other_message,
                        )
                    if warn_message and warn_message != "":
                        subject_line = f"ALERTS FROM PROCESSING SG{instrument_id:03d}"
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            warn_message,
                        )

                case "comp":
                    if processed_files_message and processed_files_message != "":
                        subject_line = f"Processing Complete SG{instrument_id:03d}"
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            processed_files_message,
                        )

                case "divetar":
                    if processed_files_message and processed_files_message != "":
                        subject_line = f"New Dive Tarball(s) SG{instrument_id:03d}"
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            processed_files_message,
                        )

                case "errors":
                    if processed_files_message:
                        subject_line = (
                            f"Warnings and Errors from SG{instrument_id:03d} conversion"
                        )
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            processed_files_message,
                        )

                case _:
                    log_warning(f"pagers msg {msg} NYI")


def main():
    """cli test/utility for ctrl file processing

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    # pylint: disable=unused-argument
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation ctrl file processing",
        additional_arguments={
            "basectrlfiles_action": BaseOpts.options_t(
                (),
                ("BaseCtrlFiles",),
                ("basectrlfiles_action",),
                str,
                {
                    "help": "Which action to run",
                    "choices": set(pagers_msgs),
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)

    log_info("Started processing ")

    if base_opts.basectrlfiles_action in pagers_msgs:
        comm_log = CommLog.process_comm_log(
            os.path.join(base_opts.mission_dir, "comm.log"), base_opts, scan_back=False
        )[0]

    if base_opts.basectrlfiles_action in pagers_msgs:
        process_pagers_yml(
            base_opts,
            comm_log.last_complete_surfacing().sg_id,
            (base_opts.basectrlfiles_action,),
            comm_log=comm_log,
        )
    else:
        log_error("Unkown action {base_opts.basectrlfiles_action}")


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")
