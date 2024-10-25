#! /usr/bin/env python
# -*- python-fmt -*-
## Copyright (c) 2023, 2024  University of Washington.
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
import Utils
import sandwell
import numpy as np
import copy
from scipy.interpolate import RegularGridInterpolator

import time
import tarfile
import io
import warnings
import cartopy.crs as ccrs
import matplotlib
import matplotlib.pyplot as plt
import matplotlib.patches as patches
import sys
from cartopy.mpl.ticker import LatitudeFormatter,LongitudeFormatter

def makeBathyMap(region, delta, safety, minimum, database='sandwell'):
    meters_per_nm = 1852.0;
    meters_per_deg = 111120.0;

    if database == 'sandwell':
       vlon, vlat, img = sandwell.read_grid([region[2] - 1, region[3] + 1, region[0] - 1, region[1] + 1])
    else:
        print('unsupported database')
        return None
      
    vlon = vlon[:,0]
    vlat = vlat[0]
 
    nlat = len(vlat)
    nlon = len(vlon)

    img = -img;
 
    i = np.argwhere(np.logical_and(vlat >= region[0], vlat <= region[1]))
    j = np.argwhere(np.logical_and(vlon >= region[2], vlon <= region[3]))

    x = (vlon - region[2])*60.0*1852.0*math.cos(region[0]*math.pi/180)
    y = (vlat - region[0])*60.0*1852.0
    interp = RegularGridInterpolator((x, y), img)

    xmax = np.max(x[j])
    ymax = np.max(y[i])
    nx = np.abs(math.floor(xmax / delta) + 1)
    ny = np.abs(math.floor(ymax / delta) + 1)

    if nx > 300 or ny > 300:
        print(f'error=resulting map will be too large ({nx} x {ny}), try larger delta or smaller region')
        return None

    xg = np.linspace(0.0, delta*(nx - 1), nx)
    yg = np.linspace(0.0, delta*(ny - 1), ny)

    X,Y = np.meshgrid(xg, yg)

    im = np.round(interp((X,Y)))

    im = im - safety
    j = np.where(im < minimum)
    im[j] = minimum
    j = np.where(im < minimum)

    return { 'nx': nx, 'ny': ny, 'll': [region[2], region[0]], 'delta': delta, 'img': im }

def writeBathyMap(m, fobj):
    fobj.write(f"{m['ny']} {m['nx']} {m['ll'][0]} {m['ll'][1]} {m['delta']}\n".encode('utf-8'))
    for i in range(m['ny']):
        for j in range(m['nx']):
            fobj.write(f"{m['img'][i][j]:.0f} ".encode('utf-8'))

        fobj.write(b'\n')
            

def writeBathySet(m, dirname):
    for k, g in enumerate(m):
        p = f'{dirname}/bathymap.{(k+1):03d}'
        f = open(p, 'wb')
        writeBathyMap(g, f)
        f.close()

def tarBathySet(ms):
    t = io.BytesIO()
    with tarfile.open(fileobj=t, mode="w:gz") as tf:
        for k, m in enumerate(ms):
            mo = io.BytesIO()
            mf = writeBathyMap(m, mo)
            tinfo = tarfile.TarInfo(name=f'bathymap.{(k+1):03d}')
            tinfo.mtime = time.time()
            tinfo.size = mo.tell()
            mo.seek(0)
            tf.addfile(tarinfo=tinfo, fileobj=mo)
            mo.close()

    t.seek(0)
    d = t.read()
    t.close()

    return d

def makeBathySet(bounds, resolution, safety, db='sandwell'):

    la = sorted(bounds[0:2])
    lo = sorted(bounds[2:4])

    NS = Utils.haversine(la[0], lo[0], la[1], lo[0])
    la = min([abs(la[0]), abs(la[1])])
    EW = Utils.haversine(la, lo[0], la, lo[1])
   
    ny = math.ceil(NS / resolution / 250)
    nx = math.ceil(EW / resolution / 250)

    if nx*ny > 10:
        print(f'resolution too high or region too large ({nx} x {ny})')
        print('map set will have more than 10 maps')
        return None

    dlat = (bounds[1] - bounds[0])/ny
    dlon = (bounds[3] - bounds[2])/nx

    fudgeNS = max([0.01*dlat, 2/60])
    fudgeEW = max([0.01*dlon, 2/60])

    ims = []
    for x in range(nx):
        lo1 = bounds[2] + x*dlon - fudgeEW
        lo2 = bounds[2] + (x + 1)*dlon + fudgeEW
        for y in range(ny):
            la1 = bounds[0] + y*dlat - fudgeNS
            la2 = bounds[0] + (y + 1)*dlat + fudgeNS
            im = makeBathyMap([la1, la2, lo1, lo2], resolution, safety, 10, database=db)
            if im:
                ims.append(im)
            else:
                return None

    return ims

class MyLatFormatter(LatitudeFormatter):
    def _get_dms(self, x):
        self._precision = 6
        x = np.asarray(x, 'd')
        degs = np.round(x, self._precision).astype('i')
        y = (x - degs) * 60
        mins = y
        secs = 0
        return x, degs, mins, secs

    def _format_minutes(self, mn):
        out = f'{mn:05.2f}'
        if out[3:5] == '00':
            out = out[0:2]
        elif out[4] == '0':
            out = out[0:4]
        return f'{out}{self._minute_symbol}'

    def _format_seconds(self, sec):
        return ''

class MyLonFormatter(LongitudeFormatter):
    def _get_dms(self, x):
        self._precision = 6
        x = np.asarray(x, 'd')
        degs = np.round(x, self._precision).astype('i')
        y = (x - degs) * 60
        mins = y
        secs = 0
        return x, degs, mins, secs

    def _format_minutes(self, mn):
        out = f'{mn:05.2f}'
        if out[3:5] == '00':
            out = out[0:2]
        elif out[4] == '0':
            out = out[0:4]
        return f'{out}{self._minute_symbol}'

    def _format_seconds(self, sec):
        return ''

def plotBathySet(ms):

    lonmin = []
    latmin = []
    lonmax = []
    latmax = []

    for m in ms:
        lonmin.append(m['ll'][0])
        latmin.append(m['ll'][1])
        latmax.append(m['ll'][1] + m['ny']*m['delta']/1852/60)
        lonmax.append(m['ll'][0] + m['nx']*m['delta']/1852/60/math.cos(m['ll'][1]*math.pi/180))

    ll_lat = min(latmin)
    ur_lat = max(latmax)
    ll_lon = min(lonmin)
    ur_lon = max(lonmax)
  
    ctrlon = (ur_lon + ll_lon)/2
    ctrlat = (ur_lat + ll_lat)/2
    
    # The lat-long projection
    noProj = ccrs.PlateCarree(central_longitude=0)
    # The projection of the map:
    extent = [ll_lon,ur_lon,ll_lat,ur_lat];
    myProj = ccrs.Orthographic(central_longitude=ctrlon, central_latitude=ctrlat)
    myProj._threshold = myProj._threshold/40.  #for higher precision plot

    fig = plt.figure(figsize=(8,12), dpi=200)
    ax = fig.add_subplot(1, 1, 1, projection=myProj)

    fudgex = 0.02*(extent[1] - extent[0])
    fudgey = 0.02*(extent[3] - extent[2])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        ax.set_extent([extent[0]-fudgex,extent[1]+fudgex,extent[2]-fudgey,extent[3]+fudgey], ccrs.PlateCarree())

    g = ax.gridlines(draw_labels=True, x_inline=False, y_inline=False, dms=True)
    
    g.yformatter = MyLatFormatter(dms=True)
    g.xformatter = MyLonFormatter(dms=True)

    ax.title.set_text("")

    deep = matplotlib.colormaps['jet']
    for k, m in enumerate(ms):
        lons = m['ll'][0] + np.linspace(0, (m['nx'] - 1)*m['delta']/1852/60/math.cos(m['ll'][1]*math.pi/180), m['nx'])
        lats = m['ll'][1] + np.linspace(0, (m['ny'] - 1)*m['delta']/1852/60, m['ny'])
        ax.pcolormesh(lons, lats, m['img'], transform=ccrs.PlateCarree(), vmin=0, vmax=1000, 
                      cmap=deep, zorder=0, alpha=1, edgecolors=None, shading='gouraud')
        ax.add_patch(patches.Rectangle((min(lons), min(lats)), max(lons) - min(lons), max(lats) - min(lats), linewidth=1, edgecolor='k', facecolor='none', transform=ccrs.PlateCarree()))
        plt.text(lons.mean(), lats.mean(), f'{(k+1):03d}', transform=ccrs.PlateCarree(), fontsize='x-large', fontweight='bold', color='grey')
        
    bu = io.BytesIO()
    plt.savefig(bu, format="png", bbox_inches='tight')
    bu.seek(0)
     
    return bu.read()

# fmt: on

if __name__ == "__main__":
    if len(sys.argv) < 8:
        print('usage: bathymap.py latSouth latNorth lonWest lonEast resolution safety output.tgz [output.png]')
        print('    specify corner coordinates in degrees, resolution and safety in meters')
        print('    suggest 2000 for resolution in open ocean')
        print('    suggest 10 for safety')
        sys.exit(1)
   
    try:
        region = [ float(sys.argv[1]), float(sys.argv[2]), float(sys.argv[3]), float(sys.argv[4]) ]
    except:
        print('error parsing region')
        sys.exit(1)
    
    try:
        resolution = int(sys.argv[5])
    except:
        print('error parsing resolution')

    try:
        safety = int(sys.argv[6])
    except:
        print('error parsing safety')

    ims = makeBathySet(region, resolution, safety)
    if ims:
        print(f'created {len(ims)} maps')
    else:
       sys.exit(1)
 
    d = tarBathySet(ims)
    try:
        f = open(sys.argv[7] ,'wb')
        f.write(d)
        f.close()
    except:
        print('error writing tarball')

    if len(sys.argv) == 9:
        d = plotBathySet(ims)
        try: 
            f = open(sys.argv[8], 'wb')
            f.write(d)
            f.close()
        except:
            print('error writing overview image')
        
    # example 1 - make a single map and write it to file
    # region = [36.5,37,-122.25,-121.75]
    #region = [60,64,2.9,7.5]
    #m = makeBathyMap(region, 2000, 10, 10)
    #f = open('foo1', 'wb')
    #writeBathyMap(m, 'f)
    #f.close()

    # example 2 - make a set of maps (should be four)
    # region = [60,68,-2,7.5]
    # ims = makeBathySet(region, 2000, 10)

    # write them out to a directory
    # writeBathySet(ims, 'foo')

    # create a png image of all of them
    # d = plotBathySet(ims)
    # f = open('foo2.png', 'wb')
    # f.write(d)
    # f.close()

    # create a tarball of all of them
    # d = tarBathySet(ims)
    # f = open('foo2.tgz' ,'wb')
    # f.write(d)
    # f.close()
