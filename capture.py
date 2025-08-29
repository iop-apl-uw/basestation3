## Copyright (c) 2025  University of Washington.
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

import asyncio
import copy
import math
import re
import sys

import aiofiles
import plotly.graph_objects
from scipy import stats


def rmse(f, x, y):
    s = 0
    n = len(x)
    if n < 2:
        return 0
    for i in range(n):
        e = y[i] - (f.intercept + f.slope*x[i])
        s = s + e*e
     
    return math.sqrt(s/n)

def analyzeMoveRecord(x, which, param, warn):
    p = [y[2] for y in x]
    r = [y[3] for y in x]
    v1 = [y[0] for y in x]
    v2 = [y[1] for y in x]

    n = len(p)
    idx = range(n)

    pitch = stats.describe(p)
    roll  = stats.describe(r)
    vbd1  = stats.describe(v1)
    vbd2  = stats.describe(v2)

    z_pitch = abs(pitch.minmax[1] - pitch.minmax[0])
    z_roll = abs(roll.minmax[1] - roll.minmax[0])
    z_vbd1 = abs(vbd1.minmax[1] - vbd1.minmax[0])
    z_vbd2 = abs(vbd2.minmax[1] - vbd2.minmax[0])
   
    if param and 'current' in param['PITCH_MIN'] and (pitch.minmax[0] < param['PITCH_MIN']['current']-10 or pitch.minmax[1] > param['PITCH_MAX']['current']+10):
        p_flag = True
    else:
        p_flag = False
    if param and 'current' in param['ROLL_MIN'] and (roll.minmax[0] < param['ROLL_MIN']['current']-10 or roll.minmax[1] > param['ROLL_MAX']['current']+10):
        r_flag = True
    else:
        r_flag = False
    if param and 'current' in param['VBD_MIN'] and ((vbd1.minmax[0] + vbd2.minmax[0])/2 < param['VBD_MIN']['current']-10 or (vbd1.minmax[1] + vbd2.minmax[1])/2 > param['VBD_MAX']['current'] + 10):
        v_flag = True
    else:
        v_flag = False


    l_pitch = stats.linregress(idx, p) 
    pitche = rmse(l_pitch, idx, p)
    l_roll = stats.linregress(idx, r) 
    rolle = rmse(l_roll, idx, r)
    l_vbd1 = stats.linregress(idx, v1) 
    vbd1e = rmse(l_vbd1, idx, v1)
    l_vbd2 = stats.linregress(idx, v2) 
    vbd2e = rmse(l_vbd2, idx, v2)

    if which == "VBD":
        if vbd1e > 20:
            warn(f"VBD pot A count linearity is low (RMSE={vbd1e} counts)")
        if vbd2e > 20:
            warn(f"VBD pot B count linearity is low (RMSE={vbd2e} counts)")

        if z_pitch > 10:
            warn(f"possible outliers in pitch AD during VBD move (max-min={z_pitch})") 
        elif p_flag:
            warn("possible outliers in pitch AD during VBD move (AD values outside _MIN/_MAX)") 
        if z_roll > 10:
            warn(f"possible outliers in roll AD during VBD move (max-min={z_roll})") 
        elif r_flag:
            warn("possible outliers in roll AD during VBD move (AD values outside _MIN/_MAX)") 
    elif which == "Roll":
        if rolle > 20:
            warn(f"roll AD count linearity is low (RMSE={rolle} counts)")
        if z_pitch > 10:
            warn(f"possible outliers in pitch AD during roll move (max-min={z_pitch})") 
        elif p_flag:
            warn("possible outliers in pitch AD during roll move (AD values outside _MIN/_MAX)") 
        if z_vbd1 > 10:
            warn(f"possible outliers in VBD A AD during roll move (max-min={z_vbd1})") 
        if z_vbd2 > 10:
            warn(f"possible outliers in VBD B AD during roll move (max-min={z_vbd2})")
        if v_flag:
            warn("possible outliers in VBD AD during roll move (AD values outside _MIN/_MAX)") 
    elif which == "Pitch":
        if pitche > 20:
            warn(f"pitch AD count linearity is low (RMSE={pitche} counts)")
        if z_roll > 10:
            warn(f"possible outliers in roll AD during pitch move (max-min={z_roll}") 
        elif r_flag:
            warn("possible outliers in roll AD during pitch move (AD values outside _MIN/_MAX)") 
        if z_vbd1 > 10:
            warn(f"possible outliers in VBD A AD during pitch move (max-min={z_vbd1})") 
        if z_vbd2 > 10:
            warn(f"possible outliers in VBD B AD during pitch move (max-min={z_vbd2})") 
        if v_flag:
            warn("possible outliers in VBD AD during pitch move (AD values outside _MIN/_MAX)") 

        
def plotMoveRecord(x, which, time, includes):
    fig = plotly.graph_objects.Figure()
    n = len(x)
      
    i = 0
    j = 0
    t0 = 0
#    if len(which) > 1:
#        print(which)
#        print(time)
    colors = { "VBD": "Black", "Pitch": "Blue", "Roll": "Green" }

    if "Roll" in which and len(which) > 1:
        k = which.index("Roll")
        if k > 0:
            roll_n = int(time[k]*10)
            if abs(x[0][3] - x[roll_n][3]) > abs(x[-roll_n][3] - x[-1][3]):
                tempw = copy.deepcopy(which)
                tempt = copy.deepcopy(time)
                which[0] = 'Roll'
                time[0] = time[k]          
                for m in range(1,len(which)):
                    time[m] = tempt[m-1]
                    which[m] = tempw[m-1]
   
    indices = [] 
    for move in which: 
        if move == "VBD":
            n = int(time[j])
            indices.append([i, i+n])
            ad1 = [ y[0] for y in x[i:i+n] ]
            ad2 = [ y[1] for y in x[i:i+n] ]
            t = [t0 + idx/1.0 for idx in range(n)]
            fig.add_trace(
                {
                    "x": t, 
                    "y": ad1,
                    "name": "linpot A",
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"color": "Black"},
                    "hovertemplate": "VBD1 %{x:.1f},%{y:.1f}<br><extra></extra>",
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
                    "hovertemplate": "VBD2 %{x:.1f},%{y:.1f}<br><extra></extra>",
                }
            )
        elif move == "Pitch":
            n = int(time[j]*10)
            ad = [ y[2] for y in x[i:i+n] ]

            indices.append([i, i+n])
            t = [t0 + idx/10.0 for idx in range(n)]
            fig.add_trace(
                {
                    "x": t, 
                    "y": ad,
                    "name": "Pitch",
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"color": "Blue"},
                    "hovertemplate": "pitch %{x:.3f},%{y:.1f}<br><extra></extra>",
                }
            )
        elif move == "Roll":
            n = int(time[j]*10)
            ad = [ y[3] for y in x[i:i+n] ]

            indices.append([i, i+n])
            t = [t0 + idx/10.0 for idx in range(n)]
            fig.add_trace(
                {
                    "x": t, 
                    "y": ad,
                    "name": "Roll",
                    "type": "scatter",
                    "mode": "lines",
                    "line": {"color": "Green"},
                    "hovertemplate": "roll %{x:.3f},%{y:.1f}<br><extra></extra>",
                }
            )

        curr = [ y[4] for y in x[i:i+n] ]
        fig.add_trace(
            {
                "x": t, 
                "y": curr,
                "yaxis": "y2",
                "xaxis": "x1",
                "name": f"{move} current",
                "type": "scatter",
                "mode": "lines",
                "line": {"color": colors[move], "dash": "dash" },
                "hovertemplate": "%{x:.1f},%{y:.0f}mA<br><extra></extra>",
            }
        )


        j = j + 1
        i = i + n
        if len(t):
            t0 = t[-1]

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
                "text": "move record",
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

    html = fig.to_html(
                        include_plotlyjs=includes,
                        include_mathjax=includes,
                        full_html=False,
                        validate=True,
                        config={
                            "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                            "scrollZoom": False,
                        },
                      )

    return (html, which, time, indices)

async def formatCaptureFile(file, firstPlot=False):
    insideMoveDump = []
    moveRecord = []
    moveTime = []

    out = ''

    inside = re.compile(r'^\s*[0-9]+\.[0-9]+\s+[0-9]+')
    summary = re.compile(r'^[0-9]+\.[0-9]+,SMOTOR,N,[0-9]+\.[0-9]+,[0-9]+\.[0-9]+,[0-9]+\.[0-9]+,[0-9]+\.[0-9]+,[0-9]+\.[0-9]+')
    crit = re.compile(r'^[0-9]+\.[0-9]+,[SH][A-Z_0-9]+,C,')
    completed = re.compile(r',(\w+) completed from [A-Za-z0-9\.()\[\]\->, ]+ took ([0-9\.]+) sec')

    crits = 0
    linenum = 0 
    rowcolor =  {"VBD": "#FFF3F0", "Pitch": "#E2FFFF", "Roll": "#E7F8E6"}
    async with aiofiles.open(file, 'rb') as capfile:
        async for line in capfile:
            line = line.decode('utf-8', errors='ignore').rstrip()
            linenum = linenum + 1

            if len(insideMoveDump) > 0:
                if line.find(' completed from ') > -1:
                    a = completed.search(line)
                    insideMoveDump.append(a.group(1))
                    moveTime.append(float(a.group(2)))
                    moveRecord = []
                    pass

                elif inside.search(line):
                    try:
                        d = list(map(lambda x: float(x), line.split()))
                        moveRecord.append(d)
                        continue
                    except Exception:
                        pass
                elif summary.search(line):
                    pass
                else:
                    if len(moveRecord) > 0:
                        (html, order, tm, idx) = plotMoveRecord(moveRecord, insideMoveDump, moveTime, "cdn" if firstPlot else False)
                        out = out + '<table><tr>'
                        out = out + '<th>VBD1 AD'
                        out = out + '<th>VBD2 AD'
                        out = out + '<th>pitch AD'
                        out = out + '<th>roll AD'
                        out = out + '<th>curr mA'
                        out = out + '<th>volts'
                        out = out + '<th>pressure'
                        out = out + '<th>heading'
                        out = out + '<th>pitch'
                        out = out + '<th>roll</tr>'
                        
                       
                        for m in range(0,len(order)):
                            for ii in range(idx[m][0],idx[m][1]):
                                out = out + f'<tr bgcolor="{rowcolor[order[m]]}">'
                                for i in moveRecord[ii]:
                                    out = out + f"<td>{i}"

                                out = out + "</tr>" 
                        out = out + "</table>"
                         
                        out = out + "<div>" + html
                        firstPlot = False
                        out = out + "</div>"
                    insideMoveDump = []
                    moveTime = []

            elif line.find(' completed from ') > -1:
                a = completed.search(line)
                insideMoveDump.append(a.group(1))
                moveTime.append(float(a.group(2)))
                moveRecord = []

            if crit.search(line):
                out = out + f'<span id="crits{crits}"><b>' + line + "</b></span>\n"                
                crits = crits + 1
            else:
                out = out + line + "\n"                

    return (out, crits)

if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(1)

    (out, crits) = asyncio.run(formatCaptureFile(sys.argv[1], firstPlot=True))
    print(f"<html><pre>{out}</pre></html>")
