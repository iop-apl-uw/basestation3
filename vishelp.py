## Copyright (c) 2023, 2025  University of Washington.
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

# ruff: noqa

import sys
import re

f = open(sys.argv[1], 'r')
inside = False
rename = { "route": "GET", "post": "POST", "websocket": "WEBSOCKET"}
handler = None
api = {}
for line in f:
    if '@app.route' in line or '@app.websocket' in line or '@app.post' in line:
        m = re.match(r"@app\.(.*)\('(.*)'\)", line.strip())
        # print(rename[m.group(1)], m.group(2))
        handler = m.group(2).split('/')[1]
        if handler == '':
            handler = 'A'
        if handler[0:1] == '<':
            handler = 'AA'

        api[handler] = { 'method': rename[m.group(1)], 'syntax': m.group(2) }
    elif handler and ' # ' in line:
        x = line.strip()
        field = x[2:].split(':')[0].strip()
        text  = x[2:].split(':')[1].strip()
        api[handler].update({ field: text })
        # print(f"   {field:11s}: {text}")
    elif handler:
        handler = None

show = ['description', 'args', 'payload', 'parameters', 'returns']
for k in sorted(api.keys()):
    print(f"{api[k]['method']} {api[k]['syntax']}")
    for m in show:
        if m in api[k]:
            print(f"    {m:11s}: {api[k][m]}")

    print()
