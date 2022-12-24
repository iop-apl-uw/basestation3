#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2022 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

""" Plots motor GC data over whole mission
"""
# TODO: This can be removed as of python 3.11
from __future__ import annotations

import collections
import sys
import time
import traceback
import typing
import cartopy.crs as ccrs
import cartopy
import matplotlib.pyplot as plt
import matplotlib.path as mpath
import matplotlib.patches as patches
import os
from CalibConst import getSGCalibrationConstants
#import warnings
#from shapely.errors import ShapelyDeprecationWarning

import numpy as np
import pandas as pd

# pylint: disable=wrong-import-position
if typing.TYPE_CHECKING:
    import BaseOpts

import PlotUtilsPlotly
import Utils

from BaseLog import log_info, log_error
from Plotting import plotmissionsingle


# DEBUG_PDB = "darwin" in sys.platform
DEBUG_PDB = False

@plotmissionsingle
def mission_map(
    base_opts: BaseOpts.BaseOptions, mission_str: list
) -> tuple[list, list]:
    """Plots mission map"""
    log_info("Starting mission_map")

    conn = Utils.open_mission_database(base_opts)
    if not conn:
        log_error("Could not open mission database")
        return ([], [])

    try:
        df = pd.read_sql_query("SELECT dive,log_gps_lat AS lat,log_gps_lon AS lon FROM dives ORDER BY dive ASC", conn) \
               .sort_values("dive")
    except:
        log_error("database error")
        return([], [])

    ll_lon = df['lon'].min() - 0.3*(df['lon'].max() - df['lon'].min())
    ll_lat = df['lat'].min() - 0.3*(df['lat'].max() - df['lat'].min())
    ur_lon = df['lon'].max() + 0.3*(df['lon'].max() - df['lon'].min())
    ur_lat = df['lat'].max() + 0.3*(df['lat'].max() - df['lat'].min())

    sg_plot_consts_file_name = os.path.join(
        base_opts.mission_dir, "sg_plot_constants.m"
    )
    if os.path.exists(sg_plot_consts_file_name):
        plot_constants = getSGCalibrationConstants(
            sg_plot_consts_file_name, suppress_required_error=True
        )
        if {"lat_south", "lat_north", "lon_west", "lon_east"} <= set(plot_constants):
            ll_lon = plot_constants["lon_west"]
            ur_lon = plot_constants["lon_east"]
            ll_lat = plot_constants["lat_south"]
            ur_lat = plot_constants["lat_north"]

    ctrlat = df['lat'].mean()
    ctrlon = df['lon'].mean()

    # The lat-long projection
    noProj = ccrs.PlateCarree(central_longitude=0)
    # The projection of the map:
    extent = [ll_lon,ur_lon,ll_lat,ur_lat];
    myProj = ccrs.Orthographic(central_longitude=ctrlon, central_latitude=ctrlat)
    myProj._threshold = myProj._threshold/40.  #for higher precision plot

    fig = plt.figure(figsize=(8,12))
    ax = fig.add_subplot(1, 1, 1, projection=myProj)

    fudgex = 0.12*(extent[1] - extent[0])
    fudgey = 0.12*(extent[3] - extent[2])

#    with warnings.catch_warnings():
#        warnings.filterwarnings("ignore", category=ShapelyDeprecationWarning)
    ax.set_extent([extent[0]-fudgex,extent[1]+fudgex,extent[2]-fudgey,extent[3]+fudgey], ccrs.PlateCarree())

    g = ax.gridlines(draw_labels=True, x_inline=False, y_inline=False)
    xt = g.xlocator.tick_values(ll_lon,ur_lon)
    yt = g.ylocator.tick_values(ll_lat,ur_lat)

    xp = []
    yp = []
    for x in xt:
        xp.append(x)
    for i in range(0,len(yt)-1):
        xp.append(xt[-1])
    for i in range(len(xt)-2, -1, -1):
        xp.append(xt[i])
    for i in range(0,len(yt)-1):
        xp.append(xt[0])
    for i in range(0,len(xt)):
        yp.append(yt[0])
    for i in range(1,len(yt)):
        yp.append(yt[i])
    for i in range(0,len(xt) - 1):
        yp.append(yt[-1])
    for i in range(len(yt)-2,-1,-1):
        yp.append(yt[i])

    # Zebra-border-line segments ...
    #  four edges on separate lines of code
    # 1: lower edge: Left - Right
    # 2: Right edge: Bottom - Top
    # 3: Upper edge: Right - Left
    # 4: Left edge: Top - Bottom
    print(len(xp))
    [ax_hdl] = ax.plot(xp, yp, color='black', linewidth=0.5, transform=noProj)
    tx_path = ax_hdl._get_transformed_path()
    path_in_data_coords, _ = tx_path.get_transformed_path_and_affine()
    polygon1s = mpath.Path( path_in_data_coords.vertices)
    vcode = xp
    for i in range(0, len(vcode)):
        vcode[i] = 1 if i%2 == 0 else 2

    polygon1v = mpath.Path( path_in_data_coords.vertices, vcode)

    ax.set_boundary(polygon1s) #masks-out unwanted part of the plot

    # Zebra-pattern creation
    # The pattern line is created from 2 layers
    #  lower layer: thicker, black solid line
    #  top layer: thinner, dashed white line

    patch1s = patches.PathPatch(polygon1s, facecolor='none', ec="black", lw=7, zorder=100)
    patch1v = patches.PathPatch(polygon1v, facecolor='none', ec="white", lw=6, zorder=101)
    ax.add_patch(patch1s)
    ax.add_patch(patch1v)

    ax.stock_img()

    ax.add_feature(cartopy.feature.OCEAN, linewidth=.3, color='lightblue')
    ax.add_feature(cartopy.feature.LAND, zorder=1, edgecolor='black', facecolor='gray')
    ax.title.set_text("")
    plt.plot(df['lon'].to_numpy(), df['lat'].to_numpy(), color='orange', marker='+', transform=ccrs.PlateCarree(), linestyle='None')
    plt.show()

    output_name = "eng_mission_map.png"

    if base_opts.plot_directory is not None:
        output_name = os.path.join(base_opts.plot_directory, output_name)

    ret_list = [output_name]
    plt.savefig(output_name, format="png", bbox_inches='tight')
    
    return ([], ret_list)
