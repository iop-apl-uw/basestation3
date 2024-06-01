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

    print(line + "<br>")

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

async def process(sgnum, base, num):
    selftestFiles = sorted(glob.glob(base + '/pt*.cap'), reverse=True)

    if len(selftestFiles) == 0:
        print("no selftest files found")
        sys.exit(1)

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

    print("<html><head><title>%03d-selftest</title>" % sgnum)
    print('<style>table.motors th,td { text-align: center; padding-left: 10px; padding-right: 10px; }</style></head><body>')
    print('<div id="top">top*<a href="#capture">capture</a>*<a href="#parameters">parameters</a>*<a href="#pitch">pitch</a>*<a href="#roll">roll</a>*<a href="#VBD">VBD</a><div><br>')

    showingRaw = False
    insideMoveDump = False
    insideDir = False
    insideParam = False
    insideMotorSummary = False
    insidePre = False
    idnum = 0
    minRates = { 'Pitch': 100, 'Roll': 300, 'Pump': 5, 'Bleed': 15 }
    maxRates = { 'Pitch': 300, 'Roll': 500, 'Pump': 10, 'Bleed': 30 }
    minCurr = { 'Pitch': 40, 'Roll': 15, 'Pump': 400, 'Bleed': 0 }
    maxCurr = { 'Pitch': 400, 'Roll': 150, 'Pump': 1000 , 'Bleed': 2000 }
    firstPlot = True

    for raw_line in stdo.splitlines(): # proc.stdout:
        try:
            line = raw_line.decode('utf-8').rstrip()
        except:
            continue

        if insideMoveDump and line.find('SUSR') > -1:
            print('</div><div id=plot%d style="display: none;">' % idnum)
            plot = plotMoveRecord(moveRecord, insideMoveDump, "cdn" if firstPlot else False)
            print(plot)
            print("</div>")
            insideMoveDump = False
            firstPlot = False
            idnum = idnum + 1
        elif insideMoveDump and line.find(',N,') == -1:
            moveRecord.append(list(map(lambda x: float(x), line.split())))

        if insideDir and line.find(',') > -1 and line.find('is empty') == -1:
            print("</pre>")
            insideDir = False

        if insidePre and line.find('>') == 0:
            print("</pre>")
            insidePre = False

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
            print(' * <a href="#" onclick="document.getElementById(\'plot%d\').style.display == \'none\' ? document.getElementById(\'plot%d\').style.display = \'block\' : document.getElementById(\'plot%d\').style.display = \'none\'; return false;">plot</a><br>' % (idnum, idnum, idnum));
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
            print('<a href="#top">top</a>*capture*<a href="#parameters">parameters</a><br>')

        elif line.startswith('Summary of motor moves'): 
            print('<h2>%s</h2>' % line)
            print('<table class="motors" rules="rows">')
            print('<tr><th>motor</th><th>start EU</th><th>end EU</th><th>start AD</th><th>end AD</th><th>dest AD</th><th>sec</th><th>AD/sec</th><th>avg mA</th><th>max mA</th><th>avg V</th><th>min V</th></tr>')
            insideMotorSummary = True

        elif line.startswith('Summary of'): 
            print('<h2>%s</h2>' % line)

        elif line.startswith('Parameter comparison'):
            print('<h2 id="parameters" style="margin-bottom:0px;">%s</h2>' % line)
            print('<a href="#top">top</a>*<a href="#capture">capture</a>*parameters<br>')
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
            if m:
                id = m.group(1).split()[0]
                print(f'<h2 id="{id}">{a.group(1)}</h2>')
            else:
                print(f'<h2>{a.group(1)}</h2>')
                

        elif not insidePre and (line.find('>prop') > -1 or line.find('>attach') > -1 or line.find('>scheme') > -1):
            format(line)
            print("<pre>")
            insidePre = True

        elif line.find('>log test') > -1:
            print("<h2>logger sensor test results</h2>")
            format(line)

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
                format(line)
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

async def html(sgnum, base, num):
    f = io.StringIO()
    with redirect_stdout(f):
        await process(sgnum, base, num)

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
