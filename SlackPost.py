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

""" Support for posting .pagers messages to Slack or Mattermost
"""

import json
import os
import sys
import time

import requests

import BaseOpts
import BaseOptsType
from BaseLog import log_error, log_info, BaseLogger


# pylint: disable=unused-argument
def post_slack(base_opts, instrument_id, slack_hook_url, subject_line, message_body):
    """Posts to slack channel

    intput
        slack_hook_url - full url to the slack incoming hook
        subject_line - subject line for message
        message_body - contents of message

    returns
        0 - success
        1 - failure
    """

    log_info(
        "instrument_id:%s slack_hook_url:%s subject_line:%s message_body:%s"
        % (instrument_id, slack_hook_url, subject_line, message_body)
    )

    msg = {"text": "%s:%s" % (subject_line, message_body)}

    try:
        response = requests.post(
            slack_hook_url,
            data=json.dumps(msg),
            headers={"Content-Type": "application/json"},
        )
        if response.status_code != 200:
            log_error(
                "Request to slack returned an error %s, the response is:%s"
                % (response.status_code, response.text)
            )
            return 1
    except:
        log_error("Error in post", "exc")
        return 1

    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    base_options = BaseOpts.BaseOptions(
        "Test entry for slack/mattermost message posting",
        additional_arguments={
            "slack_hook_url": BaseOptsType.options_t(
                None,
                ("SlackPost",),
                ("slack_hook_url",),
                str,
                {
                    "help": "URL of the Slack/Mattermost hook",
                },
            ),
            "subject_line": BaseOptsType.options_t(
                None,
                ("SlackPost",),
                ("subject_line",),
                str,
                {
                    "help": "Subject line for post",
                },
            ),
            "message_body": BaseOptsType.options_t(
                None,
                ("SlackPost",),
                ("message_body",),
                str,
                {
                    "help": "Message body for the post",
                },
            ),
        },
    )
    BaseLogger(base_options)  # initializes BaseLog

    retval = post_slack(
        base_options,
        "",
        base_options.slack_hook_url,
        base_options.subject_line,
        base_options.message_body,
    )

    sys.exit(retval)
