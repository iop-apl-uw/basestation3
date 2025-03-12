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

import math

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
