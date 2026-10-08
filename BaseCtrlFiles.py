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

# fmt: off
import copy
import functools
import json
import os
import pathlib
import pdb
import re
import sys
import time
import traceback
from collections.abc import Callable

import requests
import yaml
from pydantic import ValidationError

import BaseDotFiles
import BaseOpts
import BaseOptsType
import CommLog
import GPS
import PagersModel
import Utils
import YamlValidation
from BaseLog import (
    BaseLogger,
    log_critical,
    log_error,
    log_info,
    log_warning,
)

DEBUG_PDB = False

pagers_msgs = PagersModel.PAGERS_MSGS


def send_email(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]

    if "address" not in endpoint:
        log_error(f"Missing email address for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return

    html_format = False
    if "format" in endpoint:
        if endpoint["format"] == "html":
            html_format = True
        else:
            log_error("Unknown email format:{endpoint['format']} - defaulting to text")

    log_info(
        f"Sending email subject:{subject_line} message_body:({message_body}) endpoint:{endpoint['address']} to user:{user}"
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
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "hook" not in endpoint:
        log_error(f"Missing hook address for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return
    else:
        hook_url = endpoint["hook"]

    # Multi-line bodies (tracebacks, log dumps) get fenced as a code block
    if "\n" in message_body:
        text = f"{subject_line}:\n```\n{message_body}\n```"
    else:
        text = "%s:%s" % (subject_line, message_body)
    msg = {"text": text}

    log_info(f"Sending slack {subject_line} {message_body} {BaseDotFiles.redact_url(hook_url)} to {user}")

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
    except requests.RequestException as exception:
        # No traceback: the exception text includes the hook URL, token and all
        log_error(
            f"Error in slack post to {BaseDotFiles.redact_url(hook_url)} user:{user} "
            f"({type(exception).__name__})"
        )
    except Exception:
        log_error("Error in slack post", "exc")


def send_mattermost(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "hook" not in endpoint:
        log_error(f"Missing hook address for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return
    else:
        hook_url = endpoint["hook"]

    # Multi-line bodies (tracebacks, log dumps) get fenced as a code block
    if "\n" in message_body:
        msg_str = f"{subject_line}:\n```\n{message_body}\n```"
    else:
        msg_str = f"{subject_line}:{message_body}"

    log_info(f"Sending mattermost {subject_line} {message_body} {BaseDotFiles.redact_url(hook_url)} to {user}")

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

    log_info(f"mattermost_hook_url:{BaseDotFiles.redact_url(hook_url)} msg:{msg}")

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
    except requests.RequestException as exception:
        # No traceback: the exception text includes the hook URL, token and all
        log_error(
            f"Error in mattermost post to {BaseDotFiles.redact_url(hook_url)} user:{user} "
            f"({type(exception).__name__})"
        )
    except Exception:
        log_error(
            f"Error in mattermost post user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}",
            "exc",
        )

def send_ntfy(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    default_priorities = { "critical": 5 }
    tags = {
             "gps": "globe_with_meridians",
             "alerts": "warning",
             "errors": "warning",
             "traceback": "warning",
             "critical": "rotating_light",
             "recov": "stop_sign",
             "drift": "wind_face",
             "upload": "inbox_tray",
           }

    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "topic" not in endpoint:
        log_error(f"Missing topic for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return

    # Configured priorities over the defaults. The documented list-of-pairs form never
    # matched before, so every message - critical too - went at priority 3.
    configured = PagersModel.ntfy_priorities(endpoint.get("priority") or {})
    priorities = {**default_priorities, **(configured if isinstance(configured, dict) else {})}

    if 'type' in send_dict and send_dict['type'] in priorities:
        priority = priorities[send_dict['type']]
    else:
        priority = 3 # 3 is ntfy default priority

    msg = {
            "title": subject_line,
            "message": message_body,
            "topic": endpoint["topic"],
            "priority": priority,
          }

    if hasattr(base_opts, 'vis_base_url') and base_opts.vis_base_url:
        msg['actions'] = [
                            {
                                "action": "view",
                                "label": "dives",
                                "clear": True,
                                "url": f"{base_opts.vis_base_url}/{instrument_id}",
                            },
                            {
                                "action": "view",
                                "label": "map",
                                "clear": True,
                                "url": f"{base_opts.vis_base_url}/map/{instrument_id}",
                            },
                        ]
        t = re.search(r"Consult baselog_\d+", message_body)
        if t:
            timestamp = t[0].split('_')[1]
            msg['actions'].append(
                                    {
                                        "action": "view",
                                        "label": "baselog",
                                        "clear": True,
                                        "url": f"{base_opts.vis_base_url}/baselog/{instrument_id}/{timestamp}",
                                    }
                                 )


    if 'type' in send_dict and send_dict['type'] in tags:
        msg['tags'] = [ tags[send_dict['type']] ]

    log_info(f"ntfy:{BaseDotFiles.redact_secret(endpoint['topic'])} msg:{subject_line}+{message_body}")

    try:
        response = requests.post(
            "https://ntfy.sh",
            data=json.dumps(msg),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                "Request to ntfy returned an error %s, the response is:%s"
                % (response.status_code, response.text)
            )
    except requests.RequestException as exception:
        log_error(
            f"Error in ntfy post user:{user}, topic:{BaseDotFiles.redact_secret(endpoint['topic'])} "
            f"({type(exception).__name__})"
        )
    except Exception:
        log_error(
            f"Error in ntfy post user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}",
            "exc",
        )

def send_post(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]
    if "url" not in endpoint:
        log_error(f"Missing url address for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return
    else:
        url = endpoint["url"]

    msg_str = f"{subject_line}:{message_body}"

    log_info(f"post_url:{BaseDotFiles.redact_url(url)} msg:{msg_str}")

    try:
        response = requests.post(
            url,
            data=msg_str,
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                "Post request returned an error %s, the response is:%s"
                % (response.status_code, response.text)
            )
    except requests.RequestException as exception:
        # No traceback: the exception text includes the url
        log_error(
            f"Error in post to {BaseDotFiles.redact_url(url)} user:{user} "
            f"({type(exception).__name__})"
        )
    except Exception:
        log_error(f"Error in post user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}", "exc")



def send_inreach(
    base_opts: BaseOpts.BaseOptions,
    instrument_id: int,
    send_dict: dict,
    subject_line: str,
    message_body: str,
    gps_fix:GPS.GPSFix | None  = None
) -> None:
    endpoint = send_dict["endpoint"]
    user = send_dict["user"]

    if gps_fix is None or not gps_fix.isvalid or gps_fix.datetime is None or gps_fix.lat is None or gps_fix.lon is None:
        log_info(f"No valid gps fix for inreach message user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
        return
    for check_val in ("imei", "usr", "pwd"):
        if check_val not in endpoint:
            log_error(f"Missing imei number for user:{user}, endpoint:{BaseDotFiles.redact_endpoint(endpoint)}")
            return

    msg = "%s:%s" % (subject_line, message_body)
    
    try:
        epoch_ms = int(time.mktime(gps_fix.datetime)) * 1000.0
    except Exception:
        log_error("Unable extract fix/time from message body", 'exc')
        return

    data = {
        "Messages":[
            {
                "Message":msg,
                "Recipients":[ endpoint["imei"] ],
                "ReferencePoint": {
                    "Altitude":0,
                    "Coordinate": {
                        "Latitude":Utils.ddmm2dd(gps_fix.lat),
                        "Longitude":Utils.ddmm2dd(gps_fix.lon),
                    },
                    "Course":0,
                    "Label":"SG%03d" % instrument_id,
                    "LocationType":0,
                    "Speed":0
                },
                "Sender":"sg%03d@iopbase3.apl.washington.edu" % instrument_id,
                "Timestamp":"/Date(%d)/" % epoch_ms
            }
        ]
    }

    #log_info(data)

    ret_val = requests.post("https://us0-enterprise.inreach.garmin.com:443/IpcInbound/V1/Messaging.svc/Message", json=data, auth=(endpoint["usr"], endpoint["pwd"]))
    log_info(f"inReach Post Return {ret_val.json()}")



pagers_sendfuncs = {
    "email":      send_email,
    "slack":      send_slack,
    "inreach":    send_inreach,
    "mattermost": send_mattermost,
    "post":       send_post,
    "ntfy":       send_ntfy,
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
    validate: Callable[[pathlib.Path], dict | None] | None = None,
) -> dict | None:
    """Loads the basestation etc, group etc and mission copies of a ctrl yaml file and merges them.

    Args:
        base_opts: Options (basestation_etc, group_etc, mission_dir).
        ctrl_file_name: e.g. "pagers.yml".
        default_dict: Starting values the files are merged into.
        validate: Loads and validates one file, returning its cleaned contents, or
            None to leave the file out (validate_pagers_file for pagers.yml).

    Returns:
        The merged dict, or None if merging failed.

    Raises:
        None.
    """

    if default_dict:
        yml_dicts = [default_dict]
    else:
        yml_dicts = [{}]

    for yml_file_name in (
        base_opts.basestation_etc / ctrl_file_name,
        base_opts.group_etc / ctrl_file_name
        if base_opts.group_etc
        else None,
        base_opts.mission_dir / ctrl_file_name,
    ):
        if yml_file_name is None:
            continue
        if not os.path.exists(yml_file_name):
            log_info(f"No ctrl file {yml_file_name} found - skipping")
            continue
        if validate is not None:
            log_info(f"ctrl file {yml_file_name} found")
            tmp_dict = validate(pathlib.Path(yml_file_name))
            if tmp_dict is not None:
                yml_dicts.append(tmp_dict)
            continue
        try:
            log_info(f"ctrl file {yml_file_name} found")
            with open(yml_file_name, "r") as fi:
                # CONSIDER - run check_canonicalize_pagers_dict(pagers_dict) over each
                #           dict as loaded - help with error processing some errors.
                #           Downside - would need to push off checking on defined uses
                #           as later yml files might define them
                tmp_dict = yaml.safe_load(fi.read())
                if tmp_dict is None:
                    tmp_dict = {}
                yml_dicts.append(tmp_dict)
        except Exception:
            log_error(f"Could not procss {yml_file_name} - skipping", "exc")

    # Merge dicts together
    try:
        functools.reduce(merge_dict, yml_dicts)
    except Exception:
        log_error("Error merging config templates", "exc")
        return None

    return yml_dicts[0]


_SECRET_FIELDS = ("hook", "url", "topic", "pwd", "password")


def _redact_input(loc: tuple, value: object) -> object:
    """Masks secrets in a validation error's input (see YamlValidation.format_validation_errors)."""
    if isinstance(value, dict):
        return BaseDotFiles.redact_endpoint(value)
    if loc and loc[-1] in _SECRET_FIELDS:
        return BaseDotFiles.redact_url(str(value)) if "://" in str(value) else BaseDotFiles.redact_secret(str(value))
    return value


def _repair_keys(entry: dict, fields: set[str] | tuple[str, ...]) -> tuple[dict, list[tuple[str, str]]]:
    """Reads "name:value" keys (no space after the colon) as name: value, and sets unknown keys aside.

    In a yaml flow mapping, { format:html } is a key "format:html" with no value - the
    sg000 pagers.yml example was written that way, so many files have it. The old code
    ignored unknown keys; validation would drop the whole endpoint for them.

    Args:
        entry: An endpoint or user mapping.
        fields: The keys it may have.

    Returns:
        (repaired, notes): the mapping with "name:value" keys repaired and other unknown
        keys removed, and (key, message) pairs to warn about.
    """
    repaired: dict = {}
    notes: list[tuple[str, str]] = []
    for key, value in entry.items():
        if key in fields:
            repaired[key] = value
            continue
        if isinstance(key, str) and ":" in key and value is None:
            name, rest = (x.strip() for x in key.split(":", 1))
            if name in fields and name not in entry:
                try:
                    parsed = yaml.safe_load(rest) if rest else None
                except yaml.YAMLError:
                    parsed = rest
                repaired[name] = parsed
                shown = _redact_input((name,), parsed)
                # The original key holds the value too - mask it the same way
                original = f"{name}:{shown}" if name in _SECRET_FIELDS else key
                notes.append((key, f"{original!r} read as {name}: {shown!r} - add a space after the colon"))
                continue
        notes.append((key, f"unknown key {key!r} ignored"))
    return repaired, notes


def check_pagers_file(path: pathlib.Path) -> tuple[dict | None, list[str], list[str]]:
    """Loads one pagers.yml and validates it, dropping only the entries that are wrong.

    Nothing is logged here (see validate_pagers_file, and the "check" CLI action).
    Each subscription, user setting and endpoint is checked on its own against
    PagersModel; a bad one is logged with its file:line and left out, and the rest
    of the file is kept. A file that can't be read as yaml, or isn't a mapping at all
    (e.g. a .pagers file saved as pagers.yml - sg267 2026, ~70 tracebacks a day from
    merge_dict), is logged once and left out entirely.

    Args:
        path: A pagers.yml file.

    Returns:
        (contents, errors, warnings): the validated contents as plain dicts and lists
        (subscriptions always lists, statuses always bools) or None to leave the file
        out, and one message per problem found.

    Raises:
        None.
    """
    errors: list[str] = []
    warnings: list[str] = []
    try:
        data, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        errors.append(f"{YamlValidation.format_yaml_error(path, e)} - ignoring this pagers.yml")
        return None, errors, warnings
    except OSError as e:
        errors.append(f"Could not read {path} ({e}) - ignoring it")
        return None, errors, warnings

    if data is None:
        return {}, errors, warnings
    if not isinstance(data, dict):
        hint = (
            " - it looks like .pagers format; convert it with BaseDotFiles.py pagers_to_yml"
            if isinstance(data, str | list)
            else ""
        )
        errors.append(f"{path}: not a pagers.yml mapping (got {type(data).__name__}){hint} - ignoring this file")
        return None, errors, warnings

    def where(loc: tuple) -> str:
        line = locate(loc)
        return f"{path}:{line}" if line is not None else f"{path}"

    def report(err: ValidationError, prefix: tuple, what: str) -> None:
        for msg in YamlValidation.format_validation_errors(path, locate, err, prefix, _redact_input):
            errors.append(f"{msg} - dropping this {what}")

    cleaned: dict = {}
    for key, value in data.items():
        if not isinstance(key, str):
            errors.append(f"{where((key,))}: {key!r} is not a name (quote it) - dropping this entry")
            continue

        if key in pagers_msgs:
            # Each subscriber on its own, so one bad name doesn't drop the others
            names = [value] if isinstance(value, str) else value
            if not isinstance(names, list):
                errors.append(
                    f"{where((key,))}: {key}: subscribers must be a user name or a list of them "
                    f"(got {type(value).__name__}) - dropping this subscription"
                )
                continue
            subscribers = []
            for i, name in enumerate(names):
                try:
                    subscribers.append(PagersModel.SubscriberName.validate_python(name))
                except ValidationError as e:
                    report(e, (key,) if isinstance(value, str) else (key, i), "subscriber")
            cleaned[key] = subscribers
            continue

        if not isinstance(value, dict):
            errors.append(
                f"{where((key,))}: user {key} must be a mapping of settings and send functions "
                f"(got {type(value).__name__}) - dropping this user"
            )
            continue

        # "latlon:dd" / "status:off" at the user level; send functions are checked below
        user_keys = {k for k in value if not (isinstance(k, str) and ":" in k and value[k] is None)}
        repaired, notes = _repair_keys(
            value, {"status", "latlon", *PagersModel.ENDPOINT_MODELS, *(k for k in user_keys if k not in ("status", "latlon"))}
        )
        for bad_key, note in notes:
            warnings.append(f"{where((key, bad_key))}: {key}: {note}")
        value = repaired

        user: dict = {}
        for setting in ("status", "latlon"):
            if setting not in value:
                continue
            try:
                user.update(
                    PagersModel.UserSettings(**{setting: value[setting]}).model_dump(exclude_none=True)
                )
            except ValidationError as e:
                report(e, (key,), "setting")
        if user.get("latlon") == "dddd":
            warnings.append(
                f"{where((key, 'latlon'))}: latlon dddd is not a position format (the raw DDMM.MMMM "
                "value is sent) - use ddmm (DD MM.MM) or dd (DD.DDDD)"
            )

        for send_func, endpoints in value.items():
            if send_func in ("status", "latlon"):
                continue
            model = PagersModel.ENDPOINT_MODELS.get(send_func)
            if model is None:
                errors.append(
                    f"{where((key, send_func))}: {key}.{send_func}: unknown send function "
                    f"(one of {', '.join(PagersModel.ENDPOINT_MODELS)}) - dropping it"
                )
                continue
            single = isinstance(endpoints, dict)
            if single:
                endpoints = [endpoints]
            if not isinstance(endpoints, list):
                errors.append(
                    f"{where((key, send_func))}: {key}.{send_func}: endpoints must be a list or a mapping "
                    f"(got {type(endpoints).__name__}) - dropping them"
                )
                continue
            good = []
            for i, endpoint in enumerate(endpoints):
                prefix = (key, send_func) if single else (key, send_func, i)
                if not isinstance(endpoint, dict):
                    errors.append(
                        f"{where(prefix)}: {'.'.join(str(x) for x in prefix)}: an endpoint must be a mapping "
                        f"(got {type(endpoint).__name__}) - dropping this endpoint"
                    )
                    continue
                endpoint, notes = _repair_keys(endpoint, set(model.model_fields))
                for bad_key, note in notes:
                    warnings.append(f"{where((*prefix, bad_key))}: {'.'.join(str(x) for x in prefix)}: {note}")
                try:
                    good.append(model(**endpoint).model_dump(exclude_none=True))
                except ValidationError as e:
                    report(e, prefix, "endpoint")
                    continue
                if good[-1].get("latlon") == "dddd":
                    warnings.append(
                        f"{where((*prefix, 'latlon'))}: latlon dddd is not a position format - use ddmm or dd"
                    )
            if good:
                user[send_func] = good
        cleaned[key] = user

    return cleaned, errors, warnings


def validate_pagers_file(path: pathlib.Path) -> dict | None:
    """Loads and validates one pagers.yml for processing, logging each problem.

    Args:
        path: A pagers.yml file.

    Returns:
        The validated contents, or None to leave the file out (see check_pagers_file).

    Raises:
        None.
    """
    contents, errors, warnings = check_pagers_file(path)
    for msg in errors:
        log_error(msg)
    for msg in warnings:
        log_warning(msg)
    return contents


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
                        updated_user_dict[sf] = True
                    else:
                        updated_user_dict[sf] = sf_list
                    continue

                if sf not in pagers_sendfuncs:
                    log_error(
                        f"Unknown send_func type {sf} for user {k} - skipping user"
                    )
                    continue

                # Convert single dict endpoints to a list
                if isinstance(sf_list, dict):
                    sf_list = [sf_list]

                if not isinstance(sf_list, list):
                    log_error(
                        f"Endpoints must be a list or dict - user:{k}, send_func{sf}, got {type(sf_list).__name__} - skipping endpoints"
                    )
                    continue

                updated_endpoint_list = []
                for ep in sf_list:
                    if not isinstance(ep, dict):
                        log_error(
                            f"Endpoint must be a dict - user:{k}, send_func{sf}, got {type(ep).__name__} - skipping endpoint"
                        )
                        continue
                    if "filters" in ep:
                        if not isinstance(ep["filters"], list):
                            log_error(
                                f"filters specification must be a list - user:{k}, send_func{sf}, {BaseDotFiles.redact_endpoint(ep)} - skipping endpoint"
                            )
                            continue
                        for filter_str in ep["filters"]:
                            if filter_str not in pagers_msgs:
                                log_error(
                                    f"filter ({filter_str}) not in known send functions - user:{k}, send_func{sf}, {BaseDotFiles.redact_endpoint(ep)} - skipping endpoint"
                                )
                            continue
                    updated_endpoint_list.append(ep)
                updated_user_dict[sf] = updated_endpoint_list

            # Set any missing states
            if "latlon" not in updated_user_dict:
                updated_user_dict["latlon"] = "ddmm"
            if "status" not in updated_user_dict:
                updated_user_dict["status"] = True

            # Further user valdation goes here = status and latlon
            pagers_updated_dict["users"][k] = updated_user_dict
        else:
            log_error(f"Users must be dicts - user:{k} is a {type(v).__name__}")

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
                elif "status" in pagers_dict["users"][user]: # should never be unset
                    f_send = pagers_dict["users"][user]["status"]
                else:
                    f_send = True

                if f_send:
                    if "latlon" in endpoint:
                        latlon = endpoint["latlon"]
                    elif "latlon" in pagers_dict["users"][user]: # should never be unset
                        latlon = pagers_dict["users"][user]["latlon"]
                    else:
                        latlon = 'ddmm'

                    send_list.append(
                        {
                            "user": user,
                            "send_func": pagers_sendfuncs[sf],
                            "endpoint": endpoint,
                            "latlon": latlon,
                            "type": msg
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
    upload_message=None,
):
    """Processes the pagers.yml"""

    # Possible speed up during normal processing - static variable
    # if hasattr(process_pagers_yml, "pagers_dict"):
    #    pagers_dict = process_pagers_yml.pagers_dict
    # else:
    #    Code below - stash in attribute when checked

    pagers_dict = load_ctrl_yml(
        base_opts, "pagers.yml", copy.deepcopy(base_pagers_dict), validate_pagers_file
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
                case "upload":
                    if upload_message and upload_message != "":
                        subject_line = f"SG{instrument_id:03d} NETWORK EVENT"
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            upload_message,
                        )

                case "drift":
                    if comm_log:
                        drift_message = comm_log.predict_drift(si["latlon"])
                        subject_line = f"Drift SG{instrument_id:03d}"
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
                    gps_fix = None
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

                        try:
                            gps_fix = comm_log.last_surfacing().gps_fix
                        except Exception:
                            log_error("Failed to fetch gps_fix from last session in comm.log", "exc")
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

                        try:
                            gps_fix = session.gps_fix
                        except Exception:
                            log_error("Failed to fetch gps_fix from last session in comm.log")

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
                        si["send_func"](
                            base_opts,
                            instrument_id,
                            si,
                            subject_line,
                            gps_message,
                            gps_fix=gps_fix,
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
                        si["type"] = 'critical' # elevate
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

                case "traceback":
                    if processed_files_message:
                        subject_line = (
                            f"Traceback log entres from SG{instrument_id:03d} conversion"
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


def check_merged_pagers(base_opts: BaseOpts.BaseOptions) -> int:
    """Checks the basestation etc, group etc and mission pagers.yml files, and what they merge to.

    Args:
        base_opts: Options (basestation_etc, group_etc, mission_dir).

    Returns:
        0 if every file is clean and every subscriber is defined, 1 otherwise.

    Raises:
        None.
    """
    n_problems = 0
    found = 0
    for path in (
        base_opts.basestation_etc / "pagers.yml",
        base_opts.group_etc / "pagers.yml" if base_opts.group_etc else None,
        base_opts.mission_dir / "pagers.yml" if base_opts.mission_dir else None,
    ):
        if path is None or not path.exists():
            continue
        found += 1
        _, errors, warnings = check_pagers_file(path)
        for msg in [*errors, *warnings]:
            print(msg)
        n_problems += len(errors)
        print(f"{path}: {len(errors)} error(s), {len(warnings)} warning(s)")
    if not found:
        print("No pagers.yml found (basestation etc, group etc or mission dir)")
        return 1

    merged = load_ctrl_yml(base_opts, "pagers.yml", copy.deepcopy(base_pagers_dict), validate_pagers_file)
    if merged is None:
        print("The pagers.yml files could not be merged")
        return 1
    for msg, users in merged.items():
        if msg in pagers_msgs:
            for user in users:
                if user not in merged:
                    print(f"{msg}: subscriber {user} is not defined in any pagers.yml")
                    n_problems += 1
    canonical = check_canonicalize_pagers_dict(merged)
    for user, settings in canonical["users"].items():
        send_funcs = {k: len(v) for k, v in settings.items() if k not in ("status", "latlon")}
        print(f"user {user}: status={settings['status']} latlon={settings['latlon']} endpoints={send_funcs}")
    for msg, users in canonical["subscriptions"].items():
        print(f"subscription {msg}: {', '.join(sorted(users))}")
    return 1 if n_problems else 0


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """cli test/utility for ctrl file processing

    Actions:
        check FILE...   validate pagers.yml file(s); one line per problem as file:line
        check_merged    validate the etc / group etc / mission pagers.yml and their merge
        dump            the merged, canonical pagers.yml (dump_pagers_yml is an alias)
        <subscription>  send that message now (gps, alerts, ...), from the mission's comm.log

    Returns:
        0 for success (although there may have been individual errors in
            file processing); for check and check_merged, 1 if problems were found.
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """

    # pylint: disable=unused-argument
    base_opts = BaseOpts.BaseOptions(
        "cmdline entry for basestation ctrl file processing",
        cmdline_args=cmdline_args,
        additional_arguments={
            "basectrlfiles_action": BaseOptsType.options_t(
                (),
                {"BaseCtrlFiles"},
                ("basectrlfiles_action",),
                str,
                {
                    "help": "Which action to run: check FILE..., check_merged, dump, or a subscription to send",
                    "choices": ("check", "check_merged", "dump", "dump_pagers_yml", *pagers_msgs),
                },
            ),
            "pagers_files": BaseOptsType.options_t(
                [],
                {"BaseCtrlFiles"},
                ("pagers_files",),
                str,
                {
                    "help": "pagers.yml file(s) for the check action",
                    "nargs": "*",
                },
            ),
        },
    )

    BaseLogger(base_opts, include_time=True)

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    action = base_opts.basectrlfiles_action

    if action != "check" and not base_opts.mission_dir:
        log_error(f"{action} needs --mission_dir")
        return 1

    if action == "check":
        if not base_opts.pagers_files:
            log_error("check needs one or more pagers.yml files")
            return 1
        n_errors = 0
        for name in base_opts.pagers_files:
            # A str from argparse; pathlib for the loaders
            path = pathlib.Path(name)
            _, errors, warnings = check_pagers_file(path)
            for msg in [*errors, *warnings]:
                print(msg)
            print(f"{path}: {len(errors)} error(s), {len(warnings)} warning(s)")
            n_errors += len(errors)
        return 1 if n_errors else 0

    if action == "check_merged":
        return check_merged_pagers(base_opts)

    if action in ("dump", "dump_pagers_yml"):
        pagers_dict = load_ctrl_yml(
            base_opts, "pagers.yml", copy.deepcopy(base_pagers_dict), validate_pagers_file
        )
        if pagers_dict is None:
            log_error("Failed to load pager(s).yml - bailing out")
            return 0
        dump_pagers_dict(check_canonicalize_pagers_dict(pagers_dict))
        return 0

    # A subscription: send it now, as processing would
    log_info("Started processing ")
    (comm_log, _, _, _, _) = CommLog.process_comm_log(
        base_opts.mission_dir / "comm.log",
        base_opts,
    )
    if comm_log is None:
        log_error("Could not process comm.log")
        return 1
    process_pagers_yml(
        base_opts,
        comm_log.last_complete_surfacing().sg_id,
        (action,),
        comm_log=comm_log,
    )
    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)

        log_critical("Unhandled exception in main -- exiting", "exc")

    sys.exit(retval)
