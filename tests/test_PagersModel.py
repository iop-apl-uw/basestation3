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
import typing

import pytest
import yaml
from pydantic import ValidationError

import PagersModel


def test_subscription_literal_matches_pagers_msgs() -> None:
    assert set(typing.get_args(PagersModel.Subscription)) == set(PagersModel.PAGERS_MSGS)


@pytest.mark.parametrize(
    "send_func, endpoint",
    [
        ("email", {"address": "a@b.c", "format": "html"}),
        ("slack", {"hook": "https://h/hooks/x"}),
        ("mattermost", {"hook": "https://h/hooks/x", "mention": ["@a", "@b"], "username": "sg", "channel": "c"}),
        ("post", {"url": "https://h/notify"}),
        ("ntfy", {"topic": "t", "priority": {"critical": 5, "gps": 1}}),
        ("inreach", {"imei": 300000000000000, "usr": "u", "pwd": "p"}),
    ],
)
def test_endpoints_valid_and_required_fields(send_func: str, endpoint: dict) -> None:
    model = PagersModel.ENDPOINT_MODELS[send_func]
    model(**endpoint, status=True, filters=["gps"], latlon="dd")
    common = {"status", "filters", "latlon"}
    for required in (k for k, f in model.model_fields.items() if f.is_required() and k not in common):
        with pytest.raises(ValidationError, match=required):
            model(**{k: v for k, v in endpoint.items() if k != required})
    with pytest.raises(ValidationError, match="Extra inputs"):
        model(**endpoint, adress="typo")


@pytest.mark.parametrize("bad", [{"filters": ["latepgs"]}, {"latlon": "dddddd"}, {"status": "maybe"}])
def test_common_fields_rejected(bad: dict) -> None:
    with pytest.raises(ValidationError):
        PagersModel.EmailEndpoint(address="a@b.c", **bad)


@pytest.mark.parametrize("value, expected", [(True, True), ("on", True), ("OFF", False), (False, False)])
def test_status_on_off(value, expected: bool) -> None:
    assert PagersModel.UserSettings(status=value).status is expected


def test_ntfy_documented_list_form_is_a_mapping() -> None:
    """The documented [ "critical": 5, ... ] loads as a list of pairs - merge it."""
    priority = yaml.safe_load('[ "critical": 5, "gps": 1, "alerts": 3]')
    assert PagersModel.NtfyEndpoint(topic="t", priority=priority).priority == {"critical": 5, "gps": 1, "alerts": 3}
    with pytest.raises(ValidationError):
        PagersModel.NtfyEndpoint(topic="t", priority={"critical": 9})
    with pytest.raises(ValidationError):
        PagersModel.NtfyEndpoint(topic="t", priority=[1, 2])


def test_subscribers_scalar_is_a_list() -> None:
    """The documented "gps: username" - iterated character by character before."""
    assert PagersModel.Subscribers.validate_python("username") == ["username"]
    assert PagersModel.Subscribers.validate_python(["a", "b"]) == ["a", "b"]
