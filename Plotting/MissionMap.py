#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024, 2025, 2026  University of Washington.
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

"""Plots glider track over entire mission"""

# fmt: off
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import os
import typing
import warnings

import cartopy
import cartopy.crs as ccrs
import matplotlib.colors as mcolors
import matplotlib.patches as patches
import matplotlib.path as mpath
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import pyproj
import xarray as xr
from shapely.geometry import Polygon
from shapely.ops import transform

from CalibConst import getSGCalibrationConstants

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

from cartopy.mpl.ticker import LatitudeFormatter, LongitudeFormatter

import Utils
from BaseLog import log_error, log_info, log_warning
from Plotting import plotmissionsingle


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

def truncate_colormap(cmap, minval=0.0, maxval=1.0, n=-1):
    if n == -1:
        n = cmap.N
    new_cmap = mcolors.LinearSegmentedColormap.from_list(
         'trunc({name},{a:.2f},{b:.2f})'.format(name=cmap.name, a=minval, b=maxval),      # noqa : UP032
         cmap(np.linspace(minval, maxval, n)))
    return new_cmap


@plotmissionsingle
def mission_map(
        base_opts: BaseOpts.BaseOptions, mission_str: list, dive=None, generate_plots=True, dbcon=None
) -> tuple[list, list]:
    """Plots mission map"""

    if not generate_plots:
        return ([], [])

    log_info("Starting mission_map")
    
    if dbcon is None:
        conn = Utils.open_mission_database(base_opts, ro=True)
        if not conn:
            log_error("Could not open mission database")
            return ([], [])
        log_info("mission_map db opened (ro)")
    else:
        conn = dbcon

    try:
        df = pd.read_sql_query("SELECT dive,log_gps_lat AS lat,log_gps_lon AS lon FROM dives ORDER BY dive ASC", conn) \
               .sort_values("dive")
    except Exception:
        log_error("database error")
        if dbcon is None:
            conn.close()
            log_info("mission_map db closed")
        return([], [])

    if dbcon is None:
        conn.close()
        log_info("mission_map db closed")

    ll_lon = df['lon'].min() - 0.3*(df['lon'].max() - df['lon'].min())
    ll_lat = df['lat'].min() - 0.3*(df['lat'].max() - df['lat'].min())
    ur_lon = df['lon'].max() + 0.3*(df['lon'].max() - df['lon'].min())
    ur_lat = df['lat'].max() + 0.3*(df['lat'].max() - df['lat'].min())

    tail = 20

    sg_plot_consts_file_name = os.path.join(
        base_opts.mission_dir, "sg_plot_constants.m"
    )
    if os.path.exists(sg_plot_consts_file_name):
        plot_constants = getSGCalibrationConstants(
            sg_plot_consts_file_name, suppress_required_error=True
        )
        plot_limit_set = {"lat_south", "lat_north", "lon_west", "lon_east"}
        plot_limits_found = plot_limit_set & set(plot_constants)
        if plot_limit_set == plot_limits_found:
            pc_ll_lon = plot_constants["lon_west"]
            pc_ur_lon = plot_constants["lon_east"]
            pc_ll_lat = plot_constants["lat_south"]
            pc_ur_lat = plot_constants["lat_north"]

            # Check for containment
            if all(np.logical_not(np.isnan([ll_lon, ur_lon, ll_lat, ur_lat]))):
                project = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True).transform
                pc_bounding_box = [(pc_ur_lon, pc_ur_lat), (pc_ur_lon, pc_ll_lat), (pc_ll_lon, pc_ll_lat), (pc_ll_lon, pc_ur_lat)]
                gps_bounding_box = [(ur_lon, ur_lat), (ur_lon, ll_lat), (ll_lon, ll_lat), (ll_lon, ur_lat)]
                proj_pc_bounding_box = transform(project, Polygon(pc_bounding_box))
                proj_gps_bounding_box = transform(project, Polygon(gps_bounding_box))
                if not(proj_pc_bounding_box.contains(proj_gps_bounding_box) or proj_pc_bounding_box.intersects(proj_gps_bounding_box)):
                    log_warning(f"Specified plot limits ({pc_bounding_box}) contains no glider locations (max box {gps_bounding_box}) - could lead to map generation problems", alert="MISSION_MAP_BOX")

            # CONSIDER: In extreme situations - with the plot constants bounding box being on the other side of the globe
            # from the gps bounding box, the projection code below will fail and the map will not be generated - see try/except
            # around ax.set_extent
            # Maybe the bounding box should not be changed?
            ll_lon = pc_ll_lon 
            ur_lon = pc_ur_lon 
            ll_lat = pc_ll_lat 
            ur_lat = pc_ur_lat 
                
        elif plot_limits_found:
            log_warning(f"Not all plot limits found:{plot_limits_found}  missing {plot_limit_set - plot_limits_found}")

            
        if "tail" in plot_constants:
            tail = plot_constants["tail"]
    else:
        log_info("no sg_plot_constants.m found - using bounding box")

    if df['lat'].size == 0 or df['lon'].size == 0:
        log_warning(f"No lat/lon found in {Utils.mission_database_filename(base_opts)} - skipping mission_map")
        return([], [])
    
    ctrlat = df['lat'].mean()
    ctrlon = df['lon'].mean()

    if np.isnan(ctrlat) or np.isnan(ctrlon):
        log_warning("Mean of lat or lon is nan - skipping mission_map")
        return([], [])
    
    if np.abs(ctrlat) > 90.0 or np.abs(ctrlon) > 180.0:
        log_warning(f"lat:{ctrlat} or lon:{ctrlon} is nonsensical - skipping mission_map")
        return([], [])
    

    # The lat-long projection
    noProj = ccrs.PlateCarree(central_longitude=0)
    # The projection of the map:
    extent = [ll_lon,ur_lon,ll_lat,ur_lat]
    myProj = ccrs.Orthographic(central_longitude=ctrlon, central_latitude=ctrlat)
    myProj._threshold = myProj._threshold/40.  #for higher precision plot

    bathy_lat_min = extent[2] - 1
    bathy_lat_max = extent[3] + 1
    bathy_lon_min = extent[0] - 1
    bathy_lon_max = extent[1] + 1

    bathy = None
    bathy_db = f'{base_opts.basestation_directory}/data/ETOPO2v2g_f4.nc'
    if not os.path.exists(bathy_db):
        log_warning(f"{bathy_db} does not exist - skipping bathy in plots")
    else:
        bathy = xr.load_dataset(bathy_db)
        lat_range_xr = np.logical_and(
            bathy.y >= bathy_lat_min, bathy.y <= bathy_lat_max
        )
        lon_range_xr = np.logical_and(
            bathy.x >= bathy_lon_min, bathy.x <= bathy_lon_max
        )
        bathy_depth_xr = bathy.z[lat_range_xr, lon_range_xr]
        bathy_depth = bathy_depth_xr.to_numpy()
        bathy_depth[bathy_depth > 0] = 0
        bathy_depth = -bathy_depth
        bathy_lats = bathy.y[lat_range_xr].to_numpy()
        bathy_lons = bathy.x[lon_range_xr].to_numpy()

    fig = plt.figure(figsize=(8,12), dpi=200)
    ax = fig.add_subplot(1, 1, 1, projection=myProj)

    fudgex = 0.12*(extent[1] - extent[0])
    fudgey = 0.12*(extent[3] - extent[2])

    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        try:
            ax.set_extent([extent[0]-fudgex,extent[1]+fudgex,extent[2]-fudgey,extent[3]+fudgey], ccrs.PlateCarree())
        except ValueError as e:
            log_error(f"Error setting map extents ({e}) - possibly due to mismatch between glider position and plot extents")
            return ([], [])

    g = ax.gridlines(draw_labels=True, x_inline=False, y_inline=False, dms=True)
    xt = g.xlocator.tick_values(ll_lon,ur_lon)
    yt = g.ylocator.tick_values(ll_lat,ur_lat)
    
    g.yformatter = MyLatFormatter(dms=True)
    g.xformatter = MyLonFormatter(dms=True)

    xp = []
    yp = []
    for x in xt:
        xp.append(x)
    for _ in range(0,len(yt)-1):
        xp.append(xt[-1])
    for i in range(len(xt)-2, -1, -1):
        xp.append(xt[i])
    for _ in range(0,len(yt)-1):
        xp.append(xt[0])
    for _ in range(0,len(xt)):
        yp.append(yt[0])
    for i in range(1,len(yt)):
        yp.append(yt[i])
    for _ in range(0,len(xt) - 1):
        yp.append(yt[-1])
    for i in range(len(yt)-2,-1,-1):
        yp.append(yt[i])

    # Zebra-border-line segments ...
    #  four edges on separate lines of code
    # 1: lower edge: Left - Right
    # 2: Right edge: Bottom - Top
    # 3: Upper edge: Right - Left
    # 4: Left edge: Top - Bottom
    
    [ax_hdl] = ax.plot(xp, yp, color='black', linewidth=0.5, transform=noProj)
    tx_path = ax_hdl._get_transformed_path()
    path_in_data_coords, _ = tx_path.get_transformed_path_and_affine()
    polygon1s = mpath.Path( path_in_data_coords.vertices)
    vcode = xp
    for i in range(0, len(vcode)):
        vcode[i] = 1 if i%2 == 0 else 2

    try:
        polygon1v = mpath.Path( path_in_data_coords.vertices, vcode)
    except ValueError:
        log_warning("mpath failed - skipping mission map")
        return ([],[])

    ax.set_boundary(polygon1s) #masks-out unwanted part of the plot

    # Zebra-pattern creation
    # The pattern line is created from 2 layers
    #  lower layer: thicker, black solid line
    #  top layer: thinner, dashed white line

    patch1s = patches.PathPatch(polygon1s, facecolor='none', ec="black", lw=7, zorder=100)
    patch1v = patches.PathPatch(polygon1v, facecolor='none', ec="white", lw=6, zorder=101)
    ax.add_patch(patch1s)
    ax.add_patch(patch1v)

    ax.add_feature(cartopy.feature.LAND, zorder=1, edgecolor='black', facecolor='gray')
    ax.title.set_text("")

    deep = truncate_colormap(plt.get_cmap('Blues'), minval=0.3, maxval=1)
    if bathy is not None:
        ax.pcolormesh(bathy_lons, bathy_lats, bathy_depth, transform=ccrs.PlateCarree(), 
                      cmap=deep, zorder=0, alpha=1, edgecolors=None, shading='gouraud')

    Ndv = df['dive'].max()
    rdf = df[df['dive'] > Ndv - tail]
    plt.plot(df['lon'].to_numpy(), df['lat'].to_numpy(), color='lightsalmon', alpha=1, marker='.', markersize=4, transform=ccrs.PlateCarree(), linestyle='None')
    plt.plot(rdf['lon'].to_numpy(), rdf['lat'].to_numpy(), color='red', marker='+', transform=ccrs.PlateCarree(), linestyle='None')

    output_name = "eng_mission_map.webp"

    if base_opts.plot_directory:
        output_name = os.path.join(base_opts.plot_directory, output_name)

    ret_list = [output_name]
    plt.savefig(output_name, format="webp", bbox_inches='tight')
    
    return ([], ret_list)
# fmt: on
