#!/usr/bin/python3

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

# this is a simple version of validate that is not as
# feature aware as the version distributed along 
# with glider binaries. Particularly, it does not warn
# about parameter values and is more sensitive to 
# proper selection of the logfile used as the reference

import asyncio
import os
import re
import sys

import parmdata
import parms
import scicon


def cmdfile(body, parms=None):
    if not parms:
        d = parmdata.parms
    else:
        d = parms

    errors = 0
    warnings = 0
    directives = ['$GO', '$QUIT', '$RESUME', '$EXIT_TO_MENU']
    directive = None
    res = []

    linenum = 0
    for line in body.split('\n'):
        linenum = linenum + 1
        line = line.strip()
       
        if line == '' or line[0] == '/':
            continue
 
        if line in directives:
            directive = line
            continue

        try:
            pcs = line.split(',')
        except Exception:
            res.append(f"unknown content line {linenum} ({line})")
            warnings = warnings + 1
            continue

        if line[0] == '$' and len(pcs) == 2:
            p = pcs[0][1:]
            if p not in d:
                res.append(f"unknown parameter {pcs[0]}")
                warnings = warnings + 1
                continue

            note = ''

            if d[p]['type'] == 'INT':
                try:
                    v = int(pcs[1])
                except Exception:
                    res.append(f"${p},{pcs[1]} must be an integer value")
                    errors = errors + 1
                    continue

                if 'menufield' in d[p]:
                    if v not in [ x['value'] for x in d[p]['menufield'] ]:
                        res.append(f"${p},{pcs[1]} has an unrecognized value") 
                        errors = errors + 1
                        continue
                    try: # noqa: SIM105
                        note = '(' + next(x for x in d[p]['menufield'] if x['value'] == v)['function'] + ')'
                    except Exception:
                        pass
                elif 'bitfield' in d[p]:
                    bits = [ x['value'] for x in d[p]['bitfield'] ]
                    total = 0
                    notes = []
                    if v == 0 and 0 in bits:
                        notes.append(next(x for x in d[p]['bitfield'] if x['value'] == 0)['function'])
                    else:    
                        for b in [ x['value'] for x in d[p]['bitfield'] ]:
                            if b & v:
                                try: # noqa: SIM105
                                    notes.append(next(x for x in d[p]['bitfield'] if x['value'] == b)['function'])
                                except Exception:
                                    pass
                                
                                total = total + b

                    if len(notes):
                        note = '(' + ','.join(notes) + ')'

                    if total != v:
                        res.append(f"${p},{pcs[1]} has an invalid sum for bitmask") 
                        errors = errors + 1
                        continue
                        
            else:
                try:
                    v = float(pcs[1])
                except Exception:
                    res.append(f"${p},{pcs[1]} must be a numeric value")
                    errors = errors + 1
                    continue

            if v < d[p]['min'] or v > d[p]['max']:
                if d[p]['mode'] == 'FORCE':
                    res.append(f"${p} must be between {d[p]['min']} and {d[p]['max']}")
                    errors = errors + 1 
                else:
                    res.append(f"${p} recommended range between {d[p]['min']} and {d[p]['max']}")
                    warnings = warnings + 1 
                     
            elif 'current' in d[p] and abs(v - d[p]['current']) > 1e-5:
                res.append(f"value of ${p} will change from {d[p]['current']} to {v} {note}")
            elif 'current' not in d[p]:
                res.append(f"value of ${p} will be set to {v} {note}")
            
        else:
            res.append(f"unknown content line {linenum} ({line})")
            warnings = warnings + 1

    if not directive:
        res.append("no directive given")
        errors = errors + 1
    elif directive == '$GO':
        res.append("$GO given - will continue in current mode")
    elif directive == '$RESUME':
        res.append("$RESUME given - will start or continue diving")
    elif directive == '$QUIT':
        res.append("$QUIT given - will enter or continue in recovery")

    return (res, errors, warnings)

# parms unused
def targets(body, parms=None):
    errors = 0
    warnings = 0
    res = []

    knownFields = ["lat", "lon", "goto", "head", "depth", "finish", "dives", "exec", "radius",
                   "timeout", "timeout-exec", "timeout-goto", 
                   "src", "src-timeout", "src-timeout-exec", "src-timeout-goto", 
                   "slow-progress", "slow-progress-goto", "slow-progress-exec",
                   "fence-lat", "fence-lon", "fence-radius", "fence-goto", "fence-exec"] 

    linenum = 0
    targets = []
    for line in body.split('\n'):
        linenum = linenum + 1
        line = line.strip()
        if line == '' or line[0] == '/':
            continue

        try:
            pcs = line.split()
            if len(pcs) < 3:
                res.append(f"parse error line {linenum}")
                errors = errors + 1
                continue
        except Exception:
            res.append(f"parse error line {linenum}")
            errors = errors + 1
            continue
 
        name = pcs[0]
        target = { "name": name }
        for x in pcs[1:]:
            flds = x.split('=')
            if len(flds) != 2:
                res.append(f"parse error line {linenum}")
                errors = errors + 1            

            target[flds[0]] = flds[1] 
        
            if flds[0] not in knownFields:
                res.append(f"target {name} has unknown field {flds[0]}")
                warnings = warnings + 1
    
        if 'lat' in target and 'lon' in target and 'radius' in target and 'goto' in target:  # noqa: SIM114
            targets.append(target)
        elif 'head' in target and 'goto' in target:  # noqa: SIM114
            targets.append(target) 
        else:
            res.append(f"target {name} is missing required fields")
            errors = errors + 1

    currTarget = None
    if errors == 0:
        for t in targets:
            match = False
            for g in targets:
                if t['goto'] == g['name']:
                    match = True
                    break

            if not match:
                res.append(f"invalid goto on target {t['name']}")
                errors = errors + 1 
    
            if parms and '$TGT_NAME' in parms and t['name'] == parms['$TGT_NAME']:
                currTarget = t

    if errors == 0:
        for t in targets:
            txt = ''
            if currTarget and t['name'] == currTarget['name']: 
                txt = txt + f" => {t['name']}"
            else:
                txt = txt + f"    {t['name']}"

            for fld in t:
                if fld != 'name':
                    txt = txt + f" {fld}={t[fld]}"
        
            res.append(txt)

    return (res, errors, warnings)

def science(body, parms=None):
    if not parms:
        d = parmdata.parms
    else:
        d = parms
    if d is None:
        d = parmdata.parms

    errors = 0
    warnings = 0
    res = []

    linenum = 0
    specs = []
    sensors = 0
    for i in range(1,7):
        dev = f'DEVICE{i}'
        if dev in d and 'current' in d[dev] and d[dev]['current'] > -1:
            sensors = sensors + 1

    for line in body.split('\n'):
        linenum = linenum + 1
        line = line.strip()
        if len(line) == 0 or line == '' or line[0] == '/':
            continue

        # Rev E
        if '=' in line:
            pcs = line.split()
            if len(pcs) < 4:
                res.append(f"parse error line {linenum}")
                errors = errors + 1
                continue

            depth = pcs[0]
            if depth != 'loiter':
                try:
                    d = float(depth)
                except ValueError:
                    res.append("invalid depth bin spec")
                    errors = errors + 1
                    continue

            spec = { "depth": depth }
            for x in pcs[1:]:
                flds = x.split('=')
                if len(flds) != 2:
                    res.append(f"parse error line {linenum}")
                    errors = errors + 1            

                spec[flds[0]] = flds[1] 
                
        # assume Rev B
        else:
            pcs = line.split()
            if len(pcs) != 4:
                res.append(f"parse error line {linenum}")
                errors = errors + 1
                continue

            try:
                depth = float(pcs[0])
            except ValueError:
                res.append("invalid depth bin spec")
                errors = errors + 1
                continue

            spec = { "depth": depth, "seconds": pcs[1], "sensors": pcs[2], "gc": pcs[3] }

        if not ('sensors' in spec and 'gc' in spec and 'seconds' in spec):
            res.append(f"spec {depth} is missing required fields (seconds, sensors, gc)")
            errors = errors + 1
            continue

        if sensors > 0 and len(spec['sensors']) != sensors:
            res.append(f"not enough sensors specified for {depth} (have {len(spec['sensors'])}, need {sensors})")
            errors = errors + 1
            continue

        specs.append(spec)

    if errors == 0:
        for s in specs:
            txt = f"  {s['depth']}"
            for fld in s:
                if fld != 'depth':
                    txt = txt + f" {fld}={s[fld]}"
            
            res.append(txt) 

    return (res, errors, warnings)

def sciconsch(body, state=None):
    exp = re.compile(r'(?P<lead>^#[\S\s]*?)?(?P<inst>^[A-Za-z0-9_]+)\s+=\s+{$\s+(?P<def>[^}]*)}$', re.MULTILINE)
    keys = [ "profile", "dive", "xmit", "dec", "avg", "coeff", "conf", "conf_file" ]
    defs = [m.groupdict() for m in exp.finditer(body)]
    res = []
    errors = 0
    
    for d in defs:
        if state and d['inst'] not in state:        
            errors = errors + 1
            res.append(f"unknown instrument {d['inst']}")

        binprev = 0
        res.append(f"{d['inst']} = {{")
        for line in d['def'].split('\n'):
            line = line.strip()
            if len(line) == 0 or line[0] == '#':
                continue
               
            line = line.split('#', 1)[0] 
            if len(pcs := [p.strip() for p in line.split('=', 1)]) == 2:
                if pcs[0].strip() not in keys:
                    errors = errors + 1
                    res.append(f"# !! unknown key {pcs[0]} on {d['inst']}") 
                else:
                    res.append("   " + line)

            elif len(pcs := line.split(',')) == 2:
                try: 
                    dep = float(pcs[0])
                    secs = float(pcs[1])
                except Exception:
                    res.append(f"# !! could not parse depth,secs in {line} on {d['inst']}")
                    errors = errors + 1
                    continue

                if dep < binprev:
                    res.append(f"# !! depth bin out of order in {line} on {d['inst']}")
                    errors = errors + 1
                    continue

                if secs == 0:
                    res.append("   " + line + f" # {binprev:.0f}m-{dep:.0f}m = off")
                else:
                    res.append("   " + line + f" # {binprev:.0f}m-{dep:.0f}m = {secs:.2f}s")
                binprev = dep

            else:
                res.append(f"# !! unrecognized line {line}")
                errors = errors + 1

        res.append(f"}} # off below {binprev:.0f}m")

    return (res, errors, 0)

def validate(which, body, parms=None):
    if which == 'cmdfile':
        return cmdfile(body, parms)
    elif which == 'science':
        return science(body, parms)
    elif which == 'targets':
        return targets(body, parms)
    elif which == 'scicon.sch':
        return sciconsch(body, parms)

    return ([ "unknown" ], 1, 0)

if __name__ == "__main__":
    if len(sys.argv) != 4:
        print("usage: validate logfile [-c|-s|-t|-i] file_to_validate")
        sys.exit(1)

    if sys.argv[1] != '-' and os.path.exists(sys.argv[1]):
        log = open(sys.argv[1], "r")
    else:
        log = None

    which = sys.argv[2]

    f = open(sys.argv[3], "r")

    if which == '-c':
        d = asyncio.run(parms.state(None, logfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))
        (res, e, w) = cmdfile(f.read(), parms=d)
    elif which == '-t':
        (res, e, w) = targets(f.read())
    elif which == '-s':
        d = asyncio.run(parms.state(None, logfile=sys.argv[1], cmdfile=(sys.argv[2] if len(sys.argv) == 3 else None)))
        (res, e, w) = science(f.read(), parms=d)
    elif which == '-i':
        (d, _, _, _) = asyncio.run(scicon.state(os.path.dirname(sys.argv[3])))
        (res, e, w) = sciconsch(f.read(), state=d)
    else:
        print("usage: validate logfile [-c|-s|-t|-i] file_to_validate")
        sys.exit(1)
 
    print('\n'.join(res))
    sys.exit(0)
