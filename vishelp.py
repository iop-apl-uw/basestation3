import sys
import re

f = open(sys.argv[1], 'r')
inside = False
rename = { "route": "GET", "post": "POST", "websocket": "WEBSOCKET"}

for line in f:
    if '@app.route' in line or '@app.websocket' in line or '@app.post' in line:
        m = re.match(r"@app\.(.*)\('(.*)'\)", line.strip())
        print(rename[m.group(1)], m.group(2))
        inside = True

    elif inside and ' # ' in line:
        x = line.strip()
        field = x[2:].split(':')[0]
        text  = x[2:].split(':')[1]
        print(f"   {field:11s}: {text}")
    elif inside:
        print()
        inside = False
