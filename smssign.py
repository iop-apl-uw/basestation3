#!/usr/bin/python3

## Copyright (c) 2023  University of Washington.
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

# wraps a cmdfile for sending as SMS (via email to IMEI@msg.iridium.com or 
# https://messaging.iriiridiudium.com (leave reply email blank to save
# space)). 

import hmac
import sys
import random

if len(sys.argv) != 5:
    print(f"usage: smssign password pin index file {len(sys.argv)}")
    sys.exit(1)

key = sys.argv[1]
pin = sys.argv[2]
try:
    nonceN = int(sys.argv[3])
except:
    print("invalid index (must be 0-31)")
    sys.exit(1)

if nonceN < 0 or nonceN > 31:
    print("invalid index (must be 0-31)")
    sys.exit(1)

if nonceN >= 26:
    nonce = ord('a') + (nonceN - 26)
else:
    nonce = ord('A') + nonceN

salt = random.getrandbits(28)
salt = f'{salt:07x}' + chr(nonce)
key = key + pin + salt
data = open(sys.argv[4]).read().strip()
data = data.replace('\n', '#')
data = data.replace('\r', '&')
data = data.replace('_', ';')

msg = salt + data
sig = hmac.new(key.encode('ascii'), msg.encode('ascii'), 'md5').hexdigest()
print(f'{sig}{msg}')
