#! /usr/bin/env python

## 
## Copyright (c) 2019, 2020 by University of Washington.  All rights reserved.
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

import json
import os
import requests
import string
import sys
import time

import BaseOpts

from BaseLog import log_error, log_info, BaseLogger

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

    log_info("instrument_id:%s slack_hook_url:%s subject_line:%s message_body:%s" %
             (instrument_id, slack_hook_url, subject_line, message_body))

    msg = {'text': "%s:%s" % (subject_line, message_body)}

    try:
        response = requests.post(slack_hook_url, data=json.dumps(msg), headers={'Content-Type': 'application/json'})
        if response.status_code != 200:
            log_error('Request to slack returned an error %s, the response is:%s'
                % (response.status_code, response.text)
            )
            return 1
    except:
        log_error("Error in post", 'exc')
        return 1

    return 0

if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()
    
    base_opts = BaseOpts.BaseOptions(sys.argv, 'o')
    BaseLogger("SlackPost", base_opts) # initializes BaseLog

    args = base_opts.get_args() # positional arguments

    slack_hook_url = args[0]
    subject_line = args[1]
    gps_message = args[2]
    
    retval = post_slack(base_opts, "", slack_hook_url, subject_line, gps_message)
    
    sys.exit(retval)
