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

import sys
import glob
import re
import plotly.graph_objects
import io
from contextlib import redirect_stdout
import asyncio
import math

shortcuts = ["top", "capture", "parameters", "pitch", "roll", "VBD", "GPS", "SciCon", "pressure", "compass", "bathymetry", "software", "hardware"]

def format(line):
    reds = ["errors", "error", "Failed", "failed", "[crit]", "timed out"]
    yellows = ["WARNING"]
    for r in reds:
        if line.find(r) > -1:
            line = line.replace(r, "<span style='background-color:red;'>%s</span>" % r)
            break
    for y in yellows:
        if line.find(y) > -1:
            line = line.replace(y, "<span style='background-color:orange;'>%s</span>" % y)
            break

    a = re.search('(\d+\.\d+,[SH][A-Z0-9]+,[NCD],)(.+)?', line)
    if a:
        print(f"<span style='color:gray;'>{a.group(1)}</span>", end="")
        b = None
        c = None
        d = None
        if a.group(2) is not None:
            try:
                b = re.search('(\$[A-Z_0-9]+),(-?[0-9]+(?:\.[0-9e\-]+)?$)', a.group(2))
                c = re.search('\s*[A-Za-z0-9_]+:\s*[0-9]+\.[0-9]+\s*amp-sec\s*/\s*[0-9]+\.[0-9]+\s*sec', a.group(2))
                d = re.search('Updating parameter \$([A-Z0-9_]+) to (.+)', a.group(2))
            except:
                pass

        if b:
            print(f'<a href="../parms#{b.group(1)[1:]}">{b.group(1)}</a>,{b.group(2)}<br>')
        elif c:
            print(f'<pre class="inline">{a.group(2)}</pre><br>')
        elif d:
            print(f'Updating parameter <a href="../parms#{d.group(1)}">${d.group(1)}</a> to {d.group(2)}<br>')
        else:
            print(f"<span>{a.group(2) if a.group(2) else ''}</span><br>")    
    else:
        print(line + "<br>")

def plotBathymaps(bathymaps, includes):
    fig = plotly.graph_objects.Figure()

    lat = 0
    lon = 0
    latmn = 180
    latmx = -180
    lonmn = 360
    lonmx = -360

    n = 0
    for m in bathymaps: 
        fig.add_trace(plotly.graph_objects.Scattermapbox(
                name = f"{m['n']:03d}",
                mode = "lines",
                lon = [ m['ll'][1], m['ll'][1], m['ur'][1], m['ur'][1], m['ll'][1] ],
                lat = [ m['ll'][0], m['ur'][0], m['ur'][0], m['ll'][0], m['ll'][0] ] ))

        lat = lat + (m['ll'][0] + m['ur'][0])/2
        lon = lon + (m['ll'][1] + m['ur'][1])/2
        n = n + 1

        if m['ll'][1] < lonmn:
            lonmn = m['ll'][1]
        if m['ll'][0] < latmn:
            latmn = m['ll'][0]
        if m['ur'][1] > lonmx:
            lonmx = m['ur'][1]
        if m['ur'][0] > latmx:
            latmx = m['ur'][0]

    lat = lat / n
    lon = lon / n

    max_bound = max(abs(lonmn - lonmx), abs(latmn - latmx)) * 111
    zoom = 11.5 - math.log(max_bound)

    fig.update_layout(
        margin = {'l':0,'t':0,'b':0,'r':0},
        width = 800,
        height = 800,
        mapbox = {
            'center': {'lon': lon, 'lat': lat},
            'style': "open-street-map",
            'zoom': zoom})

    return fig.to_html(
                        include_plotlyjs=includes,
                        include_mathjax=includes,
                        full_html=False,
                        validate=True,
                        config={
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                            "scrollZoom": True,
                        },
                      )

def plotMoveRecord(x, which, includes):
    fig = plotly.graph_objects.Figure()
    n = len(x)
    curr = [y[4] for y in x]

    if which == "VBD":
        ad1 = [y[0] for y in x]
        ad2 = [y[1] for y in x]
        t = [idx/1.0 for idx in range(n)]
        fig.add_trace(
            {
                "x": t, 
                "y": ad1,
                "name": "linpot A",
                "type": "scatter",
                "mode": "lines",
                "line": {"color": "Black"},
                "hovertemplate": "%{x:.1f},%{y:.1f}<br><extra></extra>",
            }
        )
        fig.add_trace(
            {
                "x": t, 
                "y": ad2,
                "name": "linpot B",
                "type": "scatter",
                "mode": "lines",
                "line": {"color": "Red"},
                "hovertemplate": "%{x:.1f},%{y:.1f}<br><extra></extra>",
            }
        )
    else:
        if which == "Pitch":
            ad = [y[2] for y in x]
        elif which == "Roll":
            ad = [y[3] for y in x]

        t = [idx/10.0 for idx in range(n)]
        fig.add_trace(
            {
                "x": t, 
                "y": ad,
                "name": which,
                "type": "scatter",
                "mode": "lines",
                "line": {"color": "Black"},
                "hovertemplate": "%{x:.3f},%{y:.1f}<br><extra></extra>",
            }
        )

    fig.add_trace(
        {
            "x": t, 
            "y": curr,
            "yaxis": "y2",
            "xaxis": "x1",
            "name": "current",
            "type": "scatter",
            "mode": "lines",
            "line": {"color": "Blue"},
            "hovertemplate": "%{x:.1f},%{y:.0f}mA<br><extra></extra>",
        }
    )

    fig.update_layout(
        {
            "xaxis": {
                "title": "time (s)",
                "showgrid": True,
            },
            "yaxis": {
                "title": "AD counts",
                "showgrid": True,
            },
            "yaxis2": {
                "title": "current (mA)",  
                "overlaying": "y1",
                "side": "right",
            },

            "title": {
                "text": f"{which} move record",
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "height": 800,
            "width": 800,
#            "margin": {
#                "t": 20,
#                "b": 20,
#            },
        }
    )

    return fig.to_html(
                        include_plotlyjs=includes,
                        include_mathjax=includes,
                        full_html=False,
                        validate=True,
                        config={
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                            "scrollZoom": False,
                        },
                      )
     

def motorCheck(valueToPrint, valueToCheck, minVal, maxVal):
    if float(valueToCheck) < minVal:
         return "<span style='background-color:yellow;'>%s</span>" % valueToPrint
    elif float(valueToCheck) > maxVal:
        return "<span style='background-color:orange;'>%s</span>" % valueToPrint
    else:
        return valueToPrint

def printNav(div):
    print('<span>')
    for idx, v in enumerate(shortcuts):
        if idx > 0:
            print(' &bull; ', end="")

        if div == v:
            print(f'{v}', end="")
        else:
            print(f'<a href="#{v}">{v}</a>', end="")

    print('</span><p>')

    
async def process(sgnum, base, num, mission=None, missions=None):
    selftestFiles = sorted(glob.glob(base + '/pt*.cap'), reverse=True)

    print("<html><head><title>%03d-selftest</title>" % sgnum)
    print("<style>table.motors th,td { text-align: center; padding-left: 10px; padding-right: 10px; } a {font-family: verdana, arial, tahoma, 'sans serif'; } a:link {color:#0000ff; text-decoration:none} a:visited {color:#0000aa; text-decoration:none} a:hover {color:#0000aa; text-decoration:underline} a:active {color:#0000aa; text-decoration:underline} pre.inline {display: inline;} h2 {margin-bottom:0px;} </style></head><body>")

    firstLink = False

    if len(selftestFiles) > 1:
        stnums = []
        for stf in selftestFiles:
            a = re.search(f".+pt{sgnum:03d}(\d+).cap", stf)
            stnums.append(int(a.group(1)))

        if num == 0:
            stnums = stnums[1:]
        else:
            stnums.remove(num)

        for stn in stnums:
            if firstLink == True:
                print(" &bull; ")
            else:
                print("Selftest history: ")
                
            if mission:
                print(f"<a href=\"../selftest/{sgnum}?mission={mission}&num={stn}\">{mission} #{stn:04d}</a> ")
            else:     
                print(f"<a href=\"../selftest/{sgnum}?num={stn}\">#{stn:04d}</a> ")

            firstLink = True

    if missions:
        for m in missions:
            if 'path' not in m or m['path'] == base or m['path'] is None:
                continue

            m_selftestFiles = sorted(glob.glob(m['path'] + '/pt*.cap'), reverse=True) 
            for stf in m_selftestFiles:
                a = re.search(f".+pt{sgnum:03d}(\d+).cap", stf)
                stnum = a.group(1)
                if firstLink == True:
                    print(" &bull; ")
                else:
                    print("Selftest history: ")

                print(f"<a href=\"../selftest/{sgnum}?mission={m['mission']}&num={stnum}\">{m['mission']} #{stnum}</a> ")
                firstLink = True

    print('<a id="top"></a>')

    if len(selftestFiles) == 0:
        print("<p>no matching selftest files found</html>")
        return 

    if firstLink:
        print("<hr>")

    proc = await asyncio.create_subprocess_exec('%s/selftest.sh' % sys.path[0], f"{sgnum}", base, f"{num}", stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
#    proc = subprocess.Popen(['%s/selftest.sh' % sys.path[0], f"{sgnum}", base, num], stdout=subprocess.PIPE, stderr=subprocess.PIPE)

    stdo, stde = await proc.communicate()
    
    pcolors = {"[crit]": "red", "[warn]": "yellow", "[sers]": "orange"}
    rcolors = ["#cccccc", "#eeeeee"]
    trow = 0

    # try:
    #     st = open(selftestFiles[0], "rb")
    # except IOError:
    #     print("could not open %s" % selftestFiles[0])
    #     sys.exit(1)


    print('<a id="top"></a>')
    printNav('top')

    showingRaw = False
    insideMoveDump = False
    insideDir = False
    insideParam = False
    insideMotorSummary = False
    insidePre = False
    highlightSensorResult = False

    bathymaps = []

    idnum = 0
    minRates = { 'Pitch': 100, 'Roll': 300, 'Pump': 5, 'Bleed': 15 }
    maxRates = { 'Pitch': 300, 'Roll': 500, 'Pump': 10, 'Bleed': 30 }
    minCurr = { 'Pitch': 40, 'Roll': 15, 'Pump': 400, 'Bleed': 0 }
    maxCurr = { 'Pitch': 400, 'Roll': 150, 'Pump': 1000 , 'Bleed': 2000 }
    firstPlot = True

    stdo.replace(b'\r', b'')
    for raw_line in stdo.splitlines(): # proc.stdout:
        try:
            line = raw_line.decode('utf-8').rstrip()
        except:
            continue

        if insideMoveDump and line.find(',') > -1 and line.find('SMOTOR,N,') == -1:
            print('</div>')
            if len(moveRecord) > 0:
                print('<div id=plot%d style="display: block;">' % idnum)
                plot = plotMoveRecord(moveRecord, insideMoveDump, "cdn" if firstPlot else False)
                print(plot)
                print("</div>")
                firstPlot = False
            insideMoveDump = False
            idnum = idnum + 1
        elif insideMoveDump and line.find(',N,') == -1:
            try:
                moveRecord.append(list(map(lambda x: float(x), line.split())))
            except:
                pass

        if line.find('Loaded bathymap.') > -1:
            a = re.search('Loaded bathymap.(\d+) ', line)
            b = re.search('\(LL\)\s*([\-0-9\.]+),([\-0-9\.]+)\s*\(UR\)\s*([\-0-9\.]+),([\-0-9\.]+)', line)
            ll = [float(b.group(1)), float(b.group(2))]
            ur = [float(b.group(3)), float(b.group(4))]
            num = int(a.group(1))
            bathymaps.append( { "n": num, "ll": ll, "ur": ur } )

        if len(bathymaps) > 0 and line.find('Loaded bathymap.') == -1:
            print('<a href="#" onclick="document.getElementById(\'bathyplot\').style.display == \'none\' ? document.getElementById(\'bathyplot\').style.display = \'block\' : document.getElementById(\'bathyplot\').style.display = \'none\'; return false;">map view</a><br>')
            print('<div id=bathyplot style="display: block;">')
            plot = plotBathymaps(bathymaps, "cdn" if firstPlot else False)
            print(plot)
            print("</div>")
            bathymaps = []
            firstPlot = False

        if insideDir and line.find(',') > -1 and line.find('is empty') == -1:
            print("</pre>")
            insideDir = False

        if insidePre and (line.find('>') == 0 or line.find(',---- ') > -1):
            print("</pre>")
            insidePre = False

        if highlightSensorResult:
            c = re.search('[A-Za-z0-9_]+:', line)
            if not c:
                print("</b>")
                highlightSensorResult = False

        if insideParam and line.find('not between') == -1 and line.find('skipping') == -1 and line.find('canon') == -1 and line.find('[inf]') == -1 and line.find('[unknown]') == -1: 
            if len(line) > 2:
                insideParam = False
                print("</table>")

        if insideMotorSummary and not (line.startswith('Pitch') or line.startswith('Roll') or line.startswith('VBD') or line.startswith('Pump')) and line != '':
            insideMotorSummary = False
            print("</table>")
        
        if line.find('Reporting directory') > -1: 
            parts = line.split(',')
            print("<h2>%s</h2>" % parts[3])
            print("<pre>") 
            insideDir = True

        elif line.find(' completed from ') > -1 and showingRaw:
            a = re.search(",(\w+) completed from ", line)
            insideMoveDump = a.group(1)
            moveRecord = []
            format(line)
            print('<a href="#" onclick="document.getElementById(\'div%d\').style.display == \'none\' ? document.getElementById(\'div%d\').style.display = \'block\' : document.getElementById(\'div%d\').style.display = \'none\'; return false;">details</a>' % (idnum, idnum, idnum));
            print(' &bull; <a href="#" onclick="document.getElementById(\'plot%d\').style.display == \'none\' ? document.getElementById(\'plot%d\').style.display = \'block\' : document.getElementById(\'plot%d\').style.display = \'none\'; return false;">plot</a><br>' % (idnum, idnum, idnum));
            print('<div id=div%d style="display: none;">' % idnum)

        elif line.startswith('Meta:'):
            i = line.find('Dated:')
            print("<h2>")
            if i > -1:
                print(line[0:i+7])
                print("<span style='background-color: pink;'>%s</span><br>" % line[i+7:-1])
            else:
                format(line)
            print("</h2>")

        elif line.startswith('----------'):
            continue

        elif line.startswith('Raw capture'):
            showingRaw = True
            print('<h2 id="capture" style="margin-bottom:0px;">%s</h2>' % line)
            # print('<a href="#top">top</a> &bull; capture &bull; <a href="#parameters">parameters</a><br>')
            printNav('capture')

        elif line.startswith('Summary of motor moves'): 
            print('<h2>%s</h2>' % line)
            print('<table class="motors" rules="rows">')
            print('<tr><th>motor</th><th>start EU</th><th>end EU</th><th>start AD</th><th>end AD</th><th>dest AD</th><th>sec</th><th>AD/sec</th><th>avg mA</th><th>max mA</th><th>avg V</th><th>min V</th></tr>')
            insideMotorSummary = True

        elif line.startswith('Summary of'): 
            print('<h2>%s</h2>' % line)

        elif line.startswith('Parameter comparison'):
            print('<h2 id="parameters" style="margin-bottom:0px;">%s</h2>' % line)
            # print('<a href="#top">top</a> &bull; <a href="#capture">capture</a> &bull; parameters<br>')
            printNav('parameters')
            insideParam = True
            print("<table>")
            print("<tr><th></th><th>parameter</th><th>current</th><th>min</th><th>max</th></tr>")

        elif line.find(',SUSR,N,---- Self test') > -1:
            parts = line.split(',')
            if showingRaw:
                print("<h2>%s</h2>" % parts[3])
            else:
                format(line)
                
        elif line.find(',SUSR,N,---- ') > -1:
            a = re.search(',SUSR,N,(.+)', line)
            m = re.search('Checking (\w+)', line)
            n = re.search('Reporting (\w+)', line)
            if m:
                id = m.group(1).split()[0]
                print(f'<h2 id="{id}">{a.group(1)}</h2>')
            elif n:
                id = n.group(1).split()[0]
                print(f'<h2 id="{id}">{a.group(1)}</h2>')
            else:
                print(f'<h2>{a.group(1)}</h2>')
               
            if (m or n) and id in shortcuts:
                printNav(id)

        elif not insidePre and (line.find('>prop') > -1 or line.find('>attach') > -1 or line.find('>scheme') > -1 or line.find('>sysclk') > -1 or line.find('>log meta') > -1):
            format(line)
            print("<pre>")
            insidePre = True

        elif line.find('>log test') > -1:
            print("<h2>logger sensor test results</h2>")
            format(line)

        elif line.startswith('--checking '):
            format(line)
            print("<b>")
            highlightSensorResult = True

        elif insideMotorSummary:
            if not (line.startswith('Pitch') or line.startswith('Roll') or line.startswith('VBD') or line.startswith('Pump')) and line != '':
                insideMotorSummary = False
            else:
                result = None
                which = None
                haveDest = True
                if line.startswith('VBD'):
                    result = re.search(r'(?P<which>[A-Za-z]+)\s+(?P<startEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<startAD>[+-]?\d+(?:\.\d+)?)\)\s+to\s+(?P<endEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<endAD>[+-]?\d+(?:\.\d+)?)\s+[^\)]+\)\s+dest\s+(?P<dest>[+-]?\d+(?:\.\d+)?)\s+(?P<time>\d+(?:\.\d+)?)s\s+(?P<avgCurr>\d+(?:\.\d+)?)mA\s+\((?P<maxCurr>\d+(?:\.\d+)?)mA\s+peak\)\s+(?P<avgVolts>\d+(?:\.\d+)?)V\s+\((?P<minVolts>\d+(?:\.\d+)?)V\)\s+(?P<rate>\d+(?:\.\d+)?)\s+AD\/sec', line)
                    if result:
                        if float(result['dest']) > float(result['startAD']):
                            which = 'Bleed'
                        else:
                            which = 'Pump'
                elif line.startswith('Pump'):
                    result = re.search(r'(?P<which>[A-Za-z]+)\s+(?P<startEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<startAD>[+-]?\d+(?:\.\d+)?)\)\s+to\s+(?P<endEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<endAD>[+-]?\d+(?:\.\d+)?)\s+[^\)]+\)\s+(?P<time>\d+(?:\.\d+)?)s\s+(?P<avgCurr>\d+(?:\.\d+)?)\s+mA\s+\((?P<maxCurr>\d+(?:\.\d+)?)\s+mA\s+peak\)\s+(?P<avgVolts>\d+(?:\.\d+)?)\s+V\s+(?P<rate>\d+(?:\.\d+)?)\s+AD\/sec', line)
                    haveDest = False

                else:
                    result = re.search(r'(?P<which>[A-Za-z]+)\s+(?P<startEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<startAD>[+-]?\d+(?:\.\d+)?)\)\s+to\s+(?P<endEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<endAD>[+-]?\d+(?:\.\d+)?)\)\s+dest\s+(?P<dest>[+-]?\d+(?:\.\d+)?)\s+(?P<time>\d+(?:\.\d+)?)s\s+(?P<avgCurr>\d+(?:\.\d+)?)mA\s+\((?P<maxCurr>\d+(?:\.\d+)?)mA\s+peak\)\s+(?P<avgVolts>\d+(?:\.\d+)?)V\s+\((?P<minVolts>\d+(?:\.\d+)?)V\)\s+(?P<rate>\d+(?:\.\d+)?)\s+AD\/sec', line)
                    if not result:
                        result = re.search(r'(?P<which>[A-Za-z]+)\s+(?P<startEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<startAD>[+-]?\d+(?:\.\d+)?)\)\s+to\s+(?P<endEU>[+-]?\d+(?:\.\d+)?)[a-z]+\s+\((?P<endAD>[+-]?\d+(?:\.\d+)?)\)\s+(?P<time>\d+(?:\.\d+)?)s\s+(?P<avgCurr>\d+(?:\.\d+)?)\s+mA\s+\((?P<maxCurr>\d+(?:\.\d+)?)\s+mA\s+peak\)\s+(?P<avgVolts>\d+(?:\.\d+)?)\s+V\s+(?P<rate>\d+(?:\.\d+)?)\s+AD\/sec', line)
                        haveDest = False

                if result:
                    if not which:
                        which = result['which']

                    print(f"<tr><td>{which}</td> \
                            <td>{result['startEU']}</td> \
                            <td>{result['endEU']}</td> \
                            <td>{result['startAD']}</td> \
                            <td>{motorCheck(result['endAD'], abs(float(result['endAD']) - float(result['dest'])), 0, 100) if haveDest else result['endAD']}</td> \
                            <td>{result['dest'] if haveDest else '-'}</td> \
                            <td>{result['time']}</td> \
                            <td>{motorCheck(result['rate'], result['rate'], minRates[which], maxRates[which])}</td> \
                            <td>{motorCheck(result['avgCurr'], result['avgCurr'], minCurr[which], maxCurr[which])}</td> \
                            <td>{result['maxCurr']}</td> \
                            <td>{result['avgVolts']}</td> \
                            <td>{result['minVolts'] if haveDest else result['avgVolts']}</td></tr>") 
        
     
        elif insideParam:
            if line.find('not between') > -1:
                print('<tr style="background-color:%s;">' % rcolors[trow % 2])
                parts = line.split(' ')
                
                print('<td style="background-color:%s;">%s</td>' % (pcolors[parts[0]], parts[0]))
                print('<td><a href="../parms#%s">%s</a> &nbsp;</td>' % (parts[1].split(',')[0][1:], parts[1].split(',')[0]))
                print("<td>%s</td>" % parts[1].split(',')[1])
                print("<td>%s</td>" % parts[4])
                print("<td>%s</td>" % parts[6])
                print("</tr>")
                trow = trow + 1
            elif line.find('[unknown]') > -1:
                pass 
            elif line.find('[inf]') > -1:
                # format(line)
                print('<tr style="background-color:%s;">' % rcolors[trow % 2])
                parts = line.split(' ')
                
                print('<td>%s</td>' % parts[0])
                print('<td><a href="../parms#%s">%s</a> &nbsp;</td>' % (parts[1].split(',')[0][1:], parts[1].split(',')[0]))
                print("<td>%s</td>" % parts[1].split(',')[1])
                print("<td colspan=2>%s</td>" % ' '.join(parts[2:]))
                print("</tr>")
                trow = trow + 1
            else:
                format(line)
                
        elif insideDir or insidePre:
            print(line)
        else:
            format(line)
        
    if insideParam:
        print("</table>")

    print("</body></html>")

async def html(sgnum, base, num, mission=None, missions=None):
    f = io.StringIO()
    with redirect_stdout(f):
        await process(sgnum, base, num, mission=mission, missions=missions)

    return f.getvalue()

if __name__ == "__main__":

    if len(sys.argv) < 2:
        sys.exit(1)

    try:
        sgnum = int(sys.argv[1])
    except:
        sys.exit(1)

    if len(sys.argv) >= 3:
        base = sys.argv[2]
    else:
        base = f'/home/seaglider/sg{sgnum:03d}' # make a guess

    if len(sys.argv) == 4:
        num = int(sys.argv[3])
    else:
        num = 0

    asyncio.run(process(sgnum, base, num))
