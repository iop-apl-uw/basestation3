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
import subprocess

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

if len(sys.argv) < 2:
    sys.exit(1)

try:
    sgnum = int(sys.argv[1])
except:
    sys.exit(1)

if len(sys.argv) == 3:
    base = sys.argv[2]
else:
    base = f'/home/seaglider/sg{sgnum:03d}' # for iopbase
    # base = "/server/work1/seaglider/www/selftests" # for website

selftestFiles = sorted(glob.glob(base + '/pt*.cap'), reverse=True)

if len(selftestFiles) == 0:
    print("no selftest files found")
    sys.exit(1)

if len(sys.argv) == 3:
    proc = subprocess.Popen(['%s/selftest.sh' % sys.path[0], sys.argv[1], sys.argv[2]], stdout=subprocess.PIPE)
else:
    proc = subprocess.Popen(['%s/selftest.sh' % sys.path[0], sys.argv[1]], stdout=subprocess.PIPE)

pcolors = {"[crit]": "red", "[warn]": "yellow", "[sers]": "orange"}
rcolors = ["#cccccc", "#eeeeee"]
trow = 0

# try:
#     st = open(selftestFiles[0], "rb")
# except IOError:
#     print("could not open %s" % selftestFiles[0])
#     sys.exit(1)

print("<html><head><title>%03d-selftest</title></head><body>" % sgnum)

print('<div id="top">top*<a href="#capture">capture</a>*<a href="#parameters">parameters</a><div><br>')

showingRaw = False
insideMoveDump = False
insideDir = False
insideParam = False
idnum = 0
for raw_line in proc.stdout:
    try:
        line = raw_line.decode('utf-8').rstrip()
    except:
        continue

    if insideMoveDump and line.find('SUSR') > -1:
        print("</div>")
        insideMoveDump = False

    if insideDir and line.find(',') > -1 and line.find('is empty') == -1:
        print("</pre>")
        insideDir = False

    if insideParam and line.find('not between') == -1 and line.find('skipping') == -1: 
        if len(line) > 2:
            insideParam = False
            print("</table>")

    
    if line.find('Reporting directory') > -1: 
        parts = line.split(',')
        print("<h2>%s</h2>" % parts[3])
        print("<pre>") 
        insideDir = True

    elif line.find(' completed from ') > -1 and showingRaw:
        insideMoveDump = True
        format(line)
        print('<a href="#" onclick="document.getElementById(\'div%d\').style.display == \'none\' ? document.getElementById(\'div%d\').style.display = \'block\' : document.getElementById(\'div%d\').style.display = \'none\'; return false;">move record</a><br>' % (idnum, idnum, idnum));
        print('<div id=div%d style="display: none;">' % idnum)
        idnum = idnum + 1

    elif line.startswith('----------'):
        continue

    elif line.startswith('Raw capture'):
        showingRaw = True
        print('<h2 id="capture" style="margin-bottom:0px;">%s</h2>' % line)
        print('<a href="#top">top</a>*capture*<a href="#parameters">parameters</a><br>')

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
        parts = line.split(',')
        print("<h2>%s</h2>" % parts[3])

    elif line.find('>log test') > -1:
        print("<h2>logger sensor test results</h2>")
        format(line)

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
        else:
            format(line)
            
    elif insideDir:
        print(line)
    else:
        format(line)
    
if insideParam:
    print("</table>")

print("</body></html>")
