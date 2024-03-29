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
import io
from contextlib import redirect_stdout
import aiofiles
import aiofiles.os
import asyncio

def ctext(text, color):
    x = f'<font color="{color}">{text}</font>'
    return x

async def displayTables(fname):
    global GC
    global L
    global PING

    if not await aiofiles.os.path.exists(fname):
        return

    L = {}
    GC = []
    PING = []

    last_real_GC = 0
    async with aiofiles.open(fname, 'r') as file:
        async for line in file:
            line = line.rstrip()
            if line.startswith('version'):
                version = float(line.split(':')[1])
                continue
            elif not line.startswith('$'):
                continue

            pieces = line.split(',')
            key = pieces[0][1:]
            if len(pieces) == 2:
                try:
                    L[key] = float(pieces[1])
                except:
                    L[key] = pieces[1] 
            elif key == 'GC':
                GC.append(list(map(float, pieces[1:])))
                last_real_GC = len(GC)
            elif key == 'STATE':
                GC.append(['state'] + pieces[1:])
            elif key == 'PING':
                PING.append(list(map(float, pieces[1:])))
            else:
                try:
                    L[key] = list(map(float, pieces[1:]))
                except:
                    L[key] = pieces[1:]
   
    if not 'GCHEAD' in L:
        return
 
    L['GCHEAD'] = L['GCHEAD'] + ["pitch_rate", "roll_rate", "vbd_rate", "vbd_eff"]

    GCrows = len(GC)

    GC_out_names = ["st_secs", "depth", "ob_vertv", "data_pts", "end_secs", "gcphase", "pitch_ctl", "pitch_secs", "pitch_i", "pitch_ad", "pitch_rate", "roll_secs", "roll_i", "roll_ad", "roll_rate", "vbd_ctl", "vbd_secs", "vbd_i", "vbd_ad", "vbd_rate", "vbd_eff", "pitch_errors", "roll_errors", "vbd_errors", "pitch_volts", "roll_volts", "vbd_volts"]

    phase = {0:"no move", 1:"pitch", 2:"VBD", 4:"roll", 8:"turning", 256:"roll -", 512:"roll +"}

    k_t1 = L['GCHEAD'].index("st_secs")
    k_t2 = L['GCHEAD'].index("end_secs")
    if 'gcphase' in L['GCHEAD']:
        k_phase = L['GCHEAD'].index("gcphase")
    else:
        k_phase = L['GCHEAD'].index("flags")

    prev_phase = 0
    turn_time = 0
    for g in GC:
        if g[0] == "state":
            continue

        idx = int(g[k_phase])
        
        if (idx & 256) or (idx & 512):
            prev_phase = 1
            turn_start = g[k_t1]
        elif (idx & 1024):
            if (prev_phase == 1):
                turn_end = g[k_t2]
                turn_time += turn_end - turn_start
           
            prev_phase = 0 

    
    print("""
 <table cellspacing=0 cellpadding=0 border=0 style="border-spacing: 20px 0px; font-family:verdana, arial, tahoma, 'sans serif'; font-size: 14px;">
<tbody>
 <tr>
    """)

    print("<td>") # row 1, col 1
    if '_CALLS' in L:
        print("&#8226 Previous call tries %s" % ctext("%.0f" % L['_CALLS'], "red" if L['_CALLS'] > 1 else "green"))
    print("</td>")
   
    print("<td>") # row 1, col 2
    if 'GPS1' in L:
        if len(L['GPS1']) >= 8:
            st = 2
        else:
            st = 1

        print("&#8226 GPS1 time: %s s" % ctext(L['GPS1'][st + 2], "red" if L['GPS1'][st + 2] > 90 else "green"))
        if (L['GPS1'][st + 3] > 2):
            print(", HDOP was %s m" % L['GPS1'][st + 3])
    print("</td>")

    print("<td>") # row 1, col 3
    if 'GPS2' in L:
        if len(L['GPS2']) >= 8:
            st = 2
        else:
            st = 1

        print("&#8226 GPS2 time: %s s" % ctext(L['GPS2'][st + 2], "red" if L['GPS2'][st + 2] > 90 else "green"))
        if (L['GPS2'][st + 3] > 2):
            print(", HDOP was %s m" % L['GPS2'][st + 3])
    print("</td>")

    print("</tr>")

    print("<tr>") # row 2

    print("<td>") # row 2, col 1
    if 'AH0_24V' in L and '24V_AH' in L:
        pct24 = 100*(1.0 - L['24V_AH'][1]/L['AH0_24V'])
        print("&#8226 %5.2f of %5.2f AH used of 24V (%s%% remains)" % (L['24V_AH'][1], L['AH0_24V'], ctext("%5.2f" % pct24, "red" if pct24 < 10 else "green")))
    print("</td>")
  
    print("<td>") # row 2, col 2 
    if 'AH0_10V' in L and L['AH0_10V'] > 0:
        pct10 = 100*(1.0 - L['10V_AH'][1]/L['AH0_10V'])
        print("&#8226 %5.2f of %5.2f AH used of 10V (%s%% remains)" % (L['10V_AH'][1], L['AH0_10V'], ctext("%5.2f" % pct10, "red" if pct10 < 10 else "green")))

    print("</td>")

    print("<td>") # row 2, col 3 
    print("&#8226 Sensor errors: %.0f" % sum(L['ERRORS'][6:]))
    print("</td>")

    print("</tr>")
    print("<tr>") # row 3

    print("<td>") # row 3, col 1
    if '_SM_ANGLEo' in L and '_SM_DEPTHo' in L:
        print("&#8226 Surface angle %s deg, depth %s m" %
          (ctext(L['_SM_ANGLEo'], "red" if L['_SM_ANGLEo'] > -45 else "green"),
           ctext(L['_SM_DEPTHo'], "red" if L['_SM_ANGLEo'] > 2.5 else "green")))
    print("</td>")

    print("<td>") # row 3, col 2 
    if 'MHEAD_RNG_PITCHd_Wd' in L:
        print("&#8226 Intended pitch %s deg, speed %s cm/s" % 
          (ctext(L['MHEAD_RNG_PITCHd_Wd'][2], 
                "red" if abs(L['MHEAD_RNG_PITCHd_Wd'][2]) < 10 or 
                         abs(L['MHEAD_RNG_PITCHd_Wd'][2]) > 20 else "green"),
            L['MHEAD_RNG_PITCHd_Wd'][3]))
    print("</td>")

    print("<td>") # row 3, col 3 
    print("&#8226 Motor errors: %.0f" % sum(L['ERRORS'][0:6]))
    print("</td>")

    print("</tr>")
    print("<tr>") #row 4

    print("<td>") # row 4, col 1
    if 'SM_CCo' in L:
        if len(L['SM_CCo']) > 7:
            i = 7
        else:
            i = 6
        
        if (L['SM_CCo'][i] > GC[last_real_GC - 1][2] + 5):
            if (L['SM_CCo'][i] >= L['SM_CC'] + 1):
                print("&#8226 %s" % ctext(f"VBD pumped to {L['SM_CCo'][i]} (beyond SM_CC={L['SM_CC']})", "red"))
            else:
                print("&#8226 %s" % ctext(f"VBD pumped to {L['SM_CCo'][i]} (SM_CC={L['SM_CC']})", "green"))
        else:
            print(f"&#8226 No surface pump (final VBD was {L['SM_CCo'][6]}, SM_CC={L['SM_CC']})")
    print("</td>")

    print("<td>") # row 4, col 2 
    if 'XPDR_PINGS' in L and isinstance(L['XPDR_PINGS'], (list, tuple)):
        print("&#8226 Transponder ping count: %d" % L['XPDR_PINGS'][0])
    elif 'XPDR_PINGS' in L:
        print("&#8226 Transponder ping count: %d" % L['XPDR_PINGS'])
    ms = -1
    print("</td>")

    print("<td>") # row 4, col 3 
    print("&#8226 Turning time %d s" % turn_time)
    print("</td>")

    print("</tr>")
    print("<tr>") # row 5

    print("<td>") # row 5, col 1 
    if 'ALTIM_TOP_PING' in L:
        dep = L['ALTIM_TOP_PING'][0]
        rng = L['ALTIM_TOP_PING'][1]

        if len(PING) > 0 and len(PING[0]) > 4:
            for p in PING:
                if rng == p[2] and dep == p[0]:
                    ms = p[3]
                    Rs = p[4]

        print("&#8226 surface range %s m at %s m depth, ceiling %.1f m" %  
          (L['ALTIM_TOP_PING'][1], L['ALTIM_TOP_PING'][0], L['ALTIM_TOP_PING'][0] - L['ALTIM_TOP_PING'][1]))
        if ms > -1:
            print("(m = %.2f, R^2 = %.2f)" % (ms, Rs))


    print("</td>")

    print("<td>") # row 5, col 2 
    
    m = -1
    if 'ALTIM_BOTTOM_PING' in L:
        dep = L['ALTIM_BOTTOM_PING'][0]
        rng = L['ALTIM_BOTTOM_PING'][1]
        if (len(PING) > 0 and len(PING[0]) > 4):
            for p in PING:
                if (rng == p[2] and dep == p[0]):
                    m = p[3]
                    R = p[4]

        print("&#8226 bottom range %s m at %s m, depth %.0f m (%.0f m grid)" %
             (rng, dep, dep + rng, L['D_GRID']))
        if m > -1:
            print("(m = %.2f, R^2 = %.2f)" % (m, R))
    print("</td>")

    print("<td>") # row 5, col 3 
    print("</td>")

    print("</tr>")
    print("</tbody></table>")

    print("""
<table rules=groups style="text-align:center; font-family:verdana, arial, tahoma, 'sans serif'; font-size: 12px;">
<colgroup span=6><colgroup span=5><colgroup span=4><colgroup span=6><colgroup span=3><colgroup span=3>
<thead>
<tr bgcolor="#aaaaaa">
<td rowspan=2>t(s)</td>
<td rowspan=2>depth(m)</td>
<td rowspan=2>w(cm/s)</td>
<td rowspan=2>num pts</td>
<td rowspan=2>t(s)</td>
<td rowspan=2>GC phase</td>
<td colspan=5>pitch</td>
<td colspan=4>roll</td>
<td colspan=6>VBD</td>
<td colspan=3>errors</td>
<td colspan=3>volts</td>
</tr>
<tr bgcolor="#aaaaaa">
<td>ctl(cm)</td>
<td>t(s)</td>
<td>A</td>
<td>pos(AD)</td>
<td>rate</td>
<td>t(s)</td>
<td>A</td>
<td>pos(AD)</td>
<td>rate</td>
<td>ctl(cc)</td>
<td>t(s)</td>
<td>A</td>
<td>pos(AD)</td>
<td>rate</td>
<td>eff</td>
<td>pit</td>
<td>rol</td>
<td>VBD</td>
<td>pit</td><td>roll</td><td>VBD</td>
</tr>
</thead>
<tbody>
""")

    color = ["#cccccc", "#eeeeee"]

    k_pit = L['GCHEAD'].index("pitch_rate")
    k_rol = L['GCHEAD'].index("roll_rate")
    k_vbd = L['GCHEAD'].index("vbd_rate")
    k_eff = L['GCHEAD'].index("vbd_eff")
    k_pres = L['GCHEAD'].index("depth")
    k_vbd_i = L['GCHEAD'].index("vbd_i")
    k_vbd_v = L['GCHEAD'].index("vbd_volts")

    j = -1 # last row with actual GC (not STATE) data
    for i in range(GCrows):
        g = GC[i] + [0,0,0,0]

        if g[0] == "state":
            continue

        g[k_pit] = 0
        g[k_rol] = 0
        g[k_vbd] = 0
        g[k_eff] = 0

        if (j > -1):
            k_t = L['GCHEAD'].index("pitch_secs")
            k_ad = L['GCHEAD'].index("pitch_ad")

            if (g[k_t] != 0):
                rate  = (g[k_ad] - GC[j][k_ad]) / g[k_t]
            else:
                rate  = 0

            if (abs(g[k_ad] - GC[j][k_ad]) > 2):
                g[k_pit] = "%.1f" % rate
            else:
                g[k_pit] = 0.0

            k_t = L['GCHEAD'].index("roll_secs")
            k_ad = L['GCHEAD'].index("roll_ad")

            if (g[k_t] != 0):
                rate  = (g[k_ad] - GC[j][k_ad]) / g[k_t]
            else:
                rate  = 0

            if (abs(g[k_ad] - GC[j][k_ad]) > 2):
                g[k_rol] = "%.1f" % rate
            else:
                g[k_rol] = 0.0

            k_t = L['GCHEAD'].index("vbd_secs")
            k_ad = L['GCHEAD'].index("vbd_ad")

            if (g[k_t] != 0):
                rate  = (g[k_ad] - GC[j][k_ad]) / g[k_t]
            else:
                rate  = 0;

            if (abs(g[k_ad] - GC[j][k_ad]) > 2):
                g[k_vbd] = "%.1f" % rate

                rate = rate*L['VBD_CNV'] # -4.0767;
                if g[k_vbd_i] > 0:
                    x = 0.01*rate*g[k_pres]/g[k_vbd_i]/g[k_vbd_v] # L['24V_AH'][0]
                    g[k_eff] = "%.3f" % x

            GC[i] = g

        j = i

    for i in range(GCrows):
        g = GC[i]
        print("<tr bgcolor=\"%s\">" % color[i%2]) 
 
     
        if (g[0] == "state"):
            print("<td>%d</td>" % int(g[1]))
            if (len(g) >= 4):
                print("<td align=left colspan=5>%s: %s</td>" %(g[2], g[3]))
            elif (len(g) == 3):
                print("<td align=left colspan=5>%s</td>" % g[2])
            else:
                print("<td align=left colspan=5></td>")

            print("<td colspan=5><td colspan=4><td colspan=6><td colspan=3>")
            print("<td colspan=3>")

        else:

            for j in range(len(GC_out_names)):
                flags = ""
                
                if (GC_out_names[j] == "gcphase"): # called flags in v67 onward
                    p = int(g[k_phase])
                    idx = p & 31
                    y = ""
                    for k in phase.keys():
                        if k & idx:
                            y = y + phase[k] + ","

                    if y == "":
                        y = "-"
                    else:
                        y = y.rstrip(',') 

                    if (p & 32):
                        flags = flags + "VBD_w_adj,"
                    if (p & 64):
                        flags = flags + "pitch_w_adj,"
                    if (p & 128):
                        flags = flags + "pitch_adj,"
                    if (p & 256):
                        flags = flags + "roll_pos,"
                    if (p & 512):
                        flags = flags + "roll_neg,"
                    if (p & 1024):
                        flags = flags + "roll_ctr,"
                    if (p & 2048):
                        flags = flags + "pitch_pos,"
                    if (p & 4096):
                        flags = flags + "pitch_neg,"
                    if (p & 8192):
                        flags = flags + "pump,"
                    if (p & 16384):
                        flags = flags + "bleed,"

                else:
                    if not GC_out_names[j] in L['GCHEAD']:
                        y = '-'
                    else:
                        k_col = L['GCHEAD'].index(GC_out_names[j])
                        if (k_col < len(g)):
                            y = g[k_col]
                            if (y == 0):
                                y = "-"
                            elif GC_out_names[j].find("_volts") > -1 and y > 28:
                                y = "-"
                        else:
                            y = "-"
                 
                if (flags == ""):
                    print("<td>%s</td>" % y)
                else:
                    print("<td title=\"%s\">%s</td>" % (flags.rstrip(","), y))

        print("</tr>")

    if 'SM_GC' in L:
        print("<tr><td>SM</td>")
        print("<td>%s</td>" % L['SM_GC'][0])
        print("<td>-</td>") # w
        print("<td>-</td>") # num pts
        print("<td>-</td>") # t
        print("<td>-</td>") # phase

        if version >= 67: 
            k_vbd = 1
            k_pit = 2
            k_rol = 3
            vbd_ad_inc = 2 
            retries_inc = 0
            vbd_V = L['SM_GC'][15]
        else:
            k_pit = 1
            k_rol = 2 
            k_vbd = 3
            vbd_ad_inc = 0
            retries_inc = 1
            vbd_V = L['SM_GC'][21]

        print("<td>-</td>") # pitch ctl
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_pit] == 0 else L['SM_GC'][k_pit])) # pitch t
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_pit + 3] == 0 else L['SM_GC'][k_pit +3])) # pitch A
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_pit + 6 + vbd_ad_inc] == 0 else L['SM_GC'][k_pit+ 6 +vbd_ad_inc])) # pitch pos
        # pitch rate
        if (L['SM_GC'][k_pit] > 0):
            x = (L['SM_GC'][k_pit + 6 + vbd_ad_inc] - GC[last_real_GC - 1][23])/L['SM_GC'][k_pit]
            print("<td>%.1f</td>" % x)
        else:
            print("<td>-</td>")

        print("<td>%s</td>" % ("-" if L['SM_GC'][k_rol] == 0 else L['SM_GC'][k_rol])) # roll t
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_rol + 3] == 0 else L['SM_GC'][k_rol + 3])) # roll A
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_rol + 6 + vbd_ad_inc] == 0 else L['SM_GC'][k_rol + 6 + vbd_ad_inc])) # roll AD

        # roll rate
        if (L['SM_GC'][k_rol] > 0):
            x = (L['SM_GC'][k_rol + 6 + vbd_ad_inc] - GC[last_real_GC - 1][24])/L['SM_GC'][k_rol]
            print("<td>%.1f</td>" % x)
        else:
            print("<td>-</td>")

        print("<td>-</td>") # VBD ctl
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_vbd] == 0 else L['SM_GC'][k_vbd])) # VBD t
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_vbd + 3] == 0 else L['SM_GC'][k_vbd + 3])) # VBD A
        print("<td>%s</td>" % ("-" if L['SM_GC'][k_vbd + 6 + vbd_ad_inc] == 0 else L['SM_GC'][k_vbd + 6 + vbd_ad_inc])) # VBD pos

        # VBD rate and effic
        if (L['SM_GC'][k_vbd] > 0):
            rate = (L['SM_GC'][k_vbd + 6 + vbd_ad_inc] - GC[last_real_GC - 1][20])/L['SM_GC'][k_vbd]
            print("<td>%.1f</td>" % rate)
            rate = -rate/4.0767
            x = 0.01*L['SM_GC'][0]*rate/L['SM_GC'][k_vbd + 3]/vbd_V
            print("<td>%.3f</td>" % x)
        else:
            print("<td>-</td>")
            print("<td>-</td>")

        if version >= 67:
            print("<td>%s</td>" % ("-" if L['SM_GC'][13] == 0 else L['SM_GC'][13])) # pitch errors
            print("<td>%s</td>" % ("-" if L['SM_GC'][14] == 0 else L['SM_GC'][14])) # roll errors
            print("<td>%s</td>" % ("-" if L['SM_GC'][12] == 0 else L['SM_GC'][12])) # VBD errors

            print("<td>%s</td>" % ("-" if L['SM_GC'][16] == 0 else L['SM_GC'][16])) # pitch V
            print("<td>%s</td>" % ("-" if L['SM_GC'][17] == 0 else L['SM_GC'][17])) # roll V
            print("<td>%s</td>" % ("-" if L['SM_GC'][15] == 0 else L['SM_GC'][15])) # VBD V
        else:
            print("<td>%s</td>" % ("-" if L['SM_GC'][14] == 0 else L['SM_GC'][14])) # pitch errors
            print("<td>%s</td>" % ("-" if L['SM_GC'][16] == 0 else L['SM_GC'][16])) # roll errors
            print("<td>%s</td>" % ("-" if L['SM_GC'][18] == 0 else L['SM_GC'][18])) # VBD errors

            print("<td>%s</td>" % ("-" if L['SM_GC'][19] == 0 else L['SM_GC'][16])) # pitch V
            print("<td>%s</td>" % ("-" if L['SM_GC'][20] == 0 else L['SM_GC'][20])) # roll V
            print("<td>%s</td>" % ("-" if L['SM_GC'][21] == 0 else L['SM_GC'][21])) # VBD V

        print("</tr>")

    print("</tbody></table>")

async def captureTables(fname):
    f = io.StringIO()
    with redirect_stdout(f):
        await displayTables(fname)

    return f.getvalue()
 
if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit()

    print("<html><body>")
    asyncio.run(displayTables(sys.argv[1]))
    # print(captureTables(sys.argv[1]))
    # out = asyncio.run(captureTables(sys.argv[1]))
    # print(out)
    print("</body></html>")
