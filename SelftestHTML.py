#!/usr/bin/python3

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

if len(sys.argv) != 2:
    sys.exit(1)

try:
    sgnum = int(sys.argv[1])
except:
    sys.exit(1)

base = '/home/seaglider' # for iopbase
# base = "/server/work1/seaglider/www/selftests" # for website

selftestFiles = sorted(glob.glob(base + '/sg%03d/pt*.cap' % sgnum), reverse=True)

if len(selftestFiles) == 0:
    print("no selftest files found")
    sys.exit(1)

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

    if insideDir and line.find(',') > -1:
        print("</pre>")
        insideDir = False

    if insideParam and line.find('not between') == -1: 
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
        print("<tr><th></th><th>current</th><th>min</th><th>max</th></tr>")

    elif line.find(',SUSR,N,---- Self test') > -1:
        parts = line.split(',')
        if showingRaw:
            print("<h2>%s</h2>" % parts[3])
        else:
            format(line)
            
    elif line.find(',SUSR,N,---- ') > -1:
        parts = line.split(',')
        print("<h2>%s</h2>" % parts[3])
    elif insideParam:
        if line.find('not between') > -1:
            print('<tr style="background-color:%s;">' % rcolors[trow % 2])
            parts = line.split(' ')
            
            print('<td style="background-color:%s;">%s</td>' % (pcolors[parts[0]], parts[0]))
            print("<td>%s</td>" % parts[1])
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
