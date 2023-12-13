#! /usr/bin/env python
# -*- python-fmt -*-
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

import collections
import os
import pdb
import sys
import traceback

import numpy as np

# pip install scanf
import scanf
import xarray as xr
import cmocean
import plotly
import matplotlib.pyplot as plt

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

import BaseDotFiles
import BaseOpts
from BaseLog import (
    BaseLogger,
    log_error,
    log_critical,
    log_info,
    log_debug,
    log_warning,
)

bathy_t = collections.namedtuple("bathy_t", ("filename", "da"))

# Constants
METERS_PER_DEG = 111120.0

# Options
f_plot = False
f_kml = True
DEBUG_PDB = False


def cmocean_to_plotly(cmap, pl_entries):
    """Convert cmocean to plotly colorscale"""
    h = 1.0 / (pl_entries - 1)
    pl_colorscale = []

    for k in range(pl_entries):
        C = list(map(np.uint8, np.array(cmap(k * h)[:3]) * 255))
        pl_colorscale.append([k * h, "rgb" + str((C[0], C[1], C[2]))])

    return pl_colorscale


def read_bathy(path_to_bathy_map):
    # Reads a Seaglider bathymap and returns a DataArray with lat/lon coordinates
    try:
        with open(path_to_bathy_map, "r") as fi:
            row_dim, col_dim, lon_origin, lat_origin, delta = scanf.scanf(
                "%d %d %f %f %f",
                fi.readline(),
            )
            bathy_data = None
            for jj in range(row_dim):
                row = np.float32(fi.readline().split())
                if bathy_data is None:
                    bathy_data = row
                else:
                    bathy_data = np.vstack([bathy_data, row])

        lats = np.zeros(row_dim, np.float32)
        for jj in range(row_dim):
            lats[jj] = lat_origin + ((jj * delta) + delta / 2) / METERS_PER_DEG
        lons = np.zeros(col_dim, np.float32)
        for ii in range(col_dim):
            lons[ii] = lon_origin + ((ii * delta) + delta / 2) / (
                METERS_PER_DEG * np.cos(np.radians(lat_origin))
            )
        da = xr.DataArray(
            bathy_data.transpose(),
            dims=("lon", "lat"),
            coords={
                "lon": lons,
                "lat": lats,
            },
        )
        return da

    except:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error(f"Could not open {path_to_bathy_map}", "exc")
            return None


def main():
    base_opts = BaseOpts.BaseOptions(
        "Plot Seaglider Bathy maps",
        additional_arguments={
            "bathy_files": BaseOpts.options_t(
                "",
                ("PlotBathy",),
                ("bathy_files",),
                str,
                {
                    "help": "List of bathy files",
                    "nargs": "+",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    BaseLogger(base_opts)

    bathy_data = []
    for bf in base_opts.bathy_files:
        bd = read_bathy(bf)
        if bd is not None:
            data = bd.data
            data[data > 1000] = 1000
            # Note: The following does its best to remove the border around the
            # figure and all axis/ticks/text, but there remains a strip around the edges
            fig = plt.figure(figsize=None)
            ax = plt.axes([0, 0, 1, 1], frameon=False)
            ax.get_xaxis().set_visible(False)
            ax.get_yaxis().set_visible(False)
            plt.autoscale(tight=True)
            plt.imshow(np.rot90(-data), cmap="gray", vmin=-1000, vmax=0, alpha=0.5)
            output_file = bf + ".png"
            plt.savefig(output_file, bbox_inches="tight", transparent=True)
            bathy_data.append(bathy_t(output_file, bd))

    if f_kml:
        bathy_dir = os.path.split(base_opts.bathy_files[0])[0]
        bathy_kml = os.path.join(bathy_dir, "bathymap.kml")
        with open(bathy_kml, "w") as fo:
            fo.write('<?xml version="1.0" encoding="UTF-8"?>\n')
            fo.write(
                '<kml xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance" xmlns:gml="http://www.opengis.net/gml" xmlns:xfdu="urn:ccsds:schema:xfdu:1" xmlns:gx="http://www.google.com/kml/ext/2.2">\n'
            )
            fo.write("<name>Bathymaps</name>\n")
            fo.write("<Document>\n")
            for bathy_img, da in bathy_data:
                fo.write("    <GroundOverlay>\n")
                fo.write("      <Icon>\n")
                fo.write(f"        <href>{bathy_img}</href>\n")
                fo.write("      </Icon>\n")
                fo.write("      <LatLonBox>\n")
                fo.write(f"          <north>{float(max(da.lat))}</north>\n")
                fo.write(f"          <south>{float(min(da.lat))}</south>\n")
                fo.write(f"          <east>{float(max(da.lon))}</east>\n")
                fo.write(f"          <west>{float(min(da.lon))}</west>\n")
                fo.write("          <rotation>0</rotation>\n")
                fo.write("      </LatLonBox>\n")
                fo.write("    </GroundOverlay>\n")
            fo.write("</Document>\n")
            fo.write("</kml>")

    if f_plot:
        fig = plotly.graph_objects.Figure()
        for bd in bathy_data:
            z_min = 0
            z_max = min(1000.0, np.max(bd.data))
            fig.add_trace(
                {
                    "type": "contour",
                    "x": bd.lon,
                    "y": bd.lat,
                    "z": np.transpose(bd.data),
                    # "colorscale": cmocean_to_plotly(cmocean.cm.deep, 256),
                    "colorscale": "Greys",
                    # "hovertemplate": hovertemplate,
                    "zmax": z_max,
                    "zmin": z_min,
                    "contours_coloring": "heatmap",
                    "connectgaps": False,
                    "contours": {
                        "coloring": "heatmap",
                        "showlabels": True,
                        "labelfont": {
                            "family": "Raleway",
                            "size": 12,
                            "color": "white",
                        },
                        # "colorbar": {
                        #     "title": {
                        #         "text": units,
                        #         "side": "top",
                        #  },
                    },
                }
            )
        fig.show()


if __name__ == "__main__":
    try:
        main()
    except:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
