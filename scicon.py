import sys
import asyncio
import aiofiles
from anyio import Path
import re

def parseBody(body, uniq=True):
    exp = re.compile(r'(?P<lead>^#[\S\s]*?)?(?P<inst>^[A-Za-z0-9_]+)\s+=\s+{$\s+(?P<def>[^}]*)}$', re.MULTILINE)
    objs = {}
    for p in [ m.groupdict() for m in exp.finditer(body) ]:
        obj = {}
        if not uniq and p['inst'] not in objs:
            objs[p['inst']] = []

        for d in p['def'].split('\n'):
            if len(d) == 0 or d[0] == '#' or len(d.strip()) == 0:
                continue

            kv = [ m.strip() for m in re.split('[=,]', d) ]
            if len(kv) == 2:
                obj.update( { kv[0]: kv[1] } )

        
        if uniq:
            objs.update( { p['inst']: obj } )
        else:
            objs[p['inst']].append(obj)

    return objs
  
async def fromFile(name, uniq=True):
    async with aiofiles.open(name, 'rb') as f:
        body = (await f.read()).decode('utf-8', errors='ignore')

    return parseBody(body.strip().replace('\r', ''), uniq=uniq) 

async def state(base):
    p = Path(base)
    print(base)
    insFiles = sorted([x async for x in p.glob('scicon.ins.*')], reverse=True)
    attFiles = sorted([x async for x in p.glob('scicon.att.*')], reverse=True)
    schFiles = sorted([x async for x in p.glob('scicon.sch.*')], reverse=True)

    inst = {}
    attach = {}
    scheme = {}

    insSrc = None
    attSrc = None
    schSrc = None

    if len(insFiles) == 0 or len(attFiles) == 0 or len(schFiles) == 0:
        selftestFiles = sorted([x async for x in p.glob('pt*.cap')], reverse=True)
        if len(selftestFiles) == 0:
            return None

        print(selftestFiles[0])
        print(await selftestFiles[0].absolute())
        async with aiofiles.open(str(selftestFiles[0]), 'rb') as f:
            st = (await f.read()).decode('utf-8', errors='ignore')

        i = re.search(r'^>prop\s+(?P<defs>[\s\S]*)?^\r\n>a', st, re.MULTILINE)
        a = re.search(r'^>attach\s+(?P<defs>[\s\S]*)?^\r\n>scheme', st, re.MULTILINE)
        s = re.search(r'^>scheme\s+(?P<defs>[\s\S]*)?^\r\n>log', st, re.MULTILINE)

        inst = parseBody(i.groupdict()['defs'].strip().replace('\r', ''))
        attach = parseBody(a.groupdict()['defs'].strip().replace('\r', ''))
        scheme = parseBody(s.groupdict()['defs'].strip().replace('\r', ''), uniq=False)

        insSrc = selftestFiles[0].name
        attSrc = selftestFiles[0].name
        schSrc = selftestFiles[0].name

    if len(insFiles):
        inst = await fromFile(str(insFiles[0]))
        insSrc = insFiles[0].name
    if len(attFiles):
        attach = await fromFile(str(attFiles[0]))
        attSrc = attFiles[0].name
    if len(schFiles):       
        scheme = await fromFile(str(schFiles[0]), uniq=False)
        schSrc = schFiles[0].name

    for k in attach.keys():
        attach[k]['prop'] = inst[attach[k]['type']] if attach[k]['type'] in inst else None
        attach[k]['scheme'] = scheme[k] if k in scheme else []
  
    return (attach, insSrc, attSrc, schSrc)

if __name__ == "__main__":
    
    (a, _, _, _) = asyncio.run(state('./'))
    print(a)
