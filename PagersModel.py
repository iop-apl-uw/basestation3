#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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

"""pydantic models for pagers.yml.

The file has two kinds of top-level entries: subscriptions (a message type from
PAGERS_MSGS mapped to the users who get it) and users (a name mapped to optional
"status"/"latlon" and one or more send functions, each a list of endpoints). The
models are deliberately small so each subscription, user setting and endpoint can be
validated - and, if bad, dropped - on its own (see BaseCtrlFiles.validate_pagers_file).
Field sets follow what the BaseCtrlFiles send_* functions read.
"""

from typing import Annotated, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, TypeAdapter

# The message types users can subscribe to (BaseCtrlFiles.pagers_msgs)
PAGERS_MSGS = (
    "lategps",
    "gps",
    "recov",
    "critical",
    "drift",
    "divetar",
    "comp",
    "alerts",
    "errors",
    "upload",
    "traceback",
)

Subscription = Literal[
    "lategps", "gps", "recov", "critical", "drift", "divetar", "comp", "alerts", "errors", "upload", "traceback"
]

# What Utils.format_lat_lon understands. "dddd" isn't one of them (it falls through to
# the raw DDMM.MMMM number), but older pagers.yml files use it, so it's still accepted
# (BaseCtrlFiles warns about it).
LatLon = Literal["ddmm", "ddmmss", "dd", "nmea", "dddd"]


def _on_off(value: object) -> object:
    """Accepts "on"/"off" (any case) for a status; yaml 1.1 already loads bare on/off as bools."""
    if isinstance(value, str) and value.strip().lower() in ("on", "off"):
        return value.strip().lower() == "on"
    return value


Status = Annotated[bool, BeforeValidator(_on_off)]


class _Endpoint(BaseModel):
    """Fields every endpoint may have."""

    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    filters: list[Subscription] | None = None
    latlon: LatLon | None = None


class EmailEndpoint(_Endpoint):
    address: str
    format: Literal["html", "text"] | None = None


class SlackEndpoint(_Endpoint):
    hook: str


class MattermostEndpoint(_Endpoint):
    hook: str
    mention: str | list[str] | None = None
    username: str | None = None
    channel: str | None = None


class PostEndpoint(_Endpoint):
    url: str


def ntfy_priorities(value: object) -> object:
    """Normalises an ntfy priority setting to a mapping.

    The documented form - priority: [ "critical": 5, "gps": 1 ] - loads as a list of
    one-entry mappings, which send_ntfy's lookup never matched: every message went at
    the default priority, critical included. Merge such a list into one mapping;
    anything else is returned unchanged (and validated as a mapping).
    """
    if isinstance(value, list) and all(isinstance(x, dict) and len(x) == 1 for x in value):
        merged: dict = {}
        for item in value:
            merged.update(item)
        return merged
    return value


class NtfyEndpoint(_Endpoint):
    topic: str
    priority: Annotated[
        dict[Subscription, Annotated[int, Field(ge=1, le=5)]] | None, BeforeValidator(ntfy_priorities)
    ] = None


class InreachEndpoint(_Endpoint):
    imei: str | int
    usr: str
    pwd: str


# Send function name (a user's key) -> its endpoint model; BaseCtrlFiles.pagers_sendfuncs
ENDPOINT_MODELS: dict[str, type[_Endpoint]] = {
    "email": EmailEndpoint,
    "slack": SlackEndpoint,
    "mattermost": MattermostEndpoint,
    "post": PostEndpoint,
    "ntfy": NtfyEndpoint,
    "inreach": InreachEndpoint,
}


class UserSettings(BaseModel):
    """A user's own settings - every other key of a user is a send function."""

    model_config = ConfigDict(extra="forbid")

    status: Status | None = None
    latlon: LatLon | None = None


def _as_list(value: object) -> object:
    """A single user name (the documented "gps: username" form) is a list of one."""
    return [value] if isinstance(value, str) else value


# The users subscribed to a message type
Subscribers = TypeAdapter(Annotated[list[str], BeforeValidator(_as_list)])

# One of them
SubscriberName = TypeAdapter(str)
