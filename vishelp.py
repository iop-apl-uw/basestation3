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


for k in sorted(api.keys()):
    print(f"{api[k]['method']} {api[k]['syntax']}")
    for m in api[k].keys():
        if m in ['syntax', 'method']:
            continue

        print(f"    {m:11s}: {api[k][m]}")

    print()
