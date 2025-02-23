#! /usr/bin/env python
# -*- python-fmt -*-
## Copyright (c) 2023, 2024, 2025  University of Washington.
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
import os
import pdb
import sys
import traceback

from pyproj import Geod

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

import BaseOpts
from BaseLog import BaseLogger, log_error

# Options
DEBUG_PDB = True


def ddmm2dd(x):
    """Converts a lat/long from ddmm.mmm to dd.dddd

    Input: x - float in ddmm.mm format

    Returns: dd.ddd format of input

    Raises:
    """
    return float(int(x / 100.0) + math.fmod(x, 100.0) / 60.0)


def dd2ddmm(x):
    """Converts a lat/long from dd.dddd to ddmm.mmm

    Input: x - float in dd.ddd format

    Returns: ddmm.mm format of input

    Raises:
    """
    dd = int(x)
    return dd * 100.0 + (x - dd) * 60.0


def main():
    base_opts = BaseOpts.BaseOptions(
        "Generates intermediate targets between to target locations",
        additional_arguments={
            "lat0": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("lat0",),
                float,
                {
                    "help": "Latitude of starting positions in ddmm",
                },
            ),
            "lon0": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("lon0",),
                float,
                {
                    "help": "Longitude of starting positions in ddmm",
                },
            ),
            "lat1": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("lat1",),
                float,
                {
                    "help": "Latitude of ending positions in ddmm",
                },
            ),
            "lon1": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("lon1",),
                float,
                {
                    "help": "Longitude of ending positions in ddmm",
                },
            ),
            "num_points": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("num_points",),
                int,
                {
                    "help": "Number of intermediate targets",
                },
            ),
            "radius": BaseOpts.options_t(
                None,
                ("ExtraTargetsAlongLine",),
                ("radius",),
                float,
                {
                    "help": "Target Radius in meters",
                },
            ),
            "start_target_name": BaseOpts.options_t(
                "START",
                ("ExtraTargetsAlongLine",),
                ("--start_target_name",),
                str,
                {
                    "help": "Name of the initial target",
                },
            ),
            "end_target_name": BaseOpts.options_t(
                "END",
                ("ExtraTargetsAlongLine",),
                ("--end_target_name",),
                str,
                {
                    "help": "Name of the end target",
                },
            ),
        },
    )

    BaseLogger(base_opts)

    lat0 = ddmm2dd(base_opts.lat0)
    lon0 = ddmm2dd(base_opts.lon0)

    lat1 = ddmm2dd(base_opts.lat1)
    lon1 = ddmm2dd(base_opts.lon1)

    # print(lon0, lat0)
    # print(lon1, lat1)

    # n_extra_points = 5

    geoid = Geod(ellps="WGS84")
    extra_points = geoid.npts(lon0, lat0, lon1, lat1, base_opts.num_points)

    # print(type(extra_points))

    print(
        f"{base_opts.start_target_name} lat={dd2ddmm(lat0):.2f} lon={dd2ddmm(lon0):.2f} radius={base_opts.radius:.0f} goto={base_opts.start_target_name}_0"
    )

    pts = []
    for ii, p in enumerate(extra_points):
        if ii == len(extra_points) - 1:
            print(
                f"{base_opts.start_target_name}_{int(ii)} lat={dd2ddmm(p[1]):.2f} lon={dd2ddmm(p[0]):.2f} radius={base_opts.radius} goto={base_opts.end_target_name}"
            )
        else:
            print(
                f"{base_opts.start_target_name}_{int(ii)} lat={dd2ddmm(p[1]):.2f} lon={dd2ddmm(p[0]):.2f} radius={base_opts.radius} goto={base_opts.start_target_name}_{int(ii + 1)}"
            )
        pts.append((ii, p))

    print(
        f"{base_opts.end_target_name} lat={dd2ddmm(lat1):.2f} lon={dd2ddmm(lon1):.2f} radius={base_opts.radius} goto={base_opts.end_target_name}_{int(len(pts) - 1)}"
    )

    while pts:
        ii, p = pts.pop()
        if ii == 0:
            print(
                f"{base_opts.end_target_name}_{int(ii)} lat={dd2ddmm(p[1]):.2f} lon={dd2ddmm(p[0]):.2f} radius={base_opts.radius} goto={base_opts.start_target_name}"
            )
        else:
            print(
                f"{base_opts.end_target_name}_{int(ii)} lat={dd2ddmm(p[1]):.2f} lon={dd2ddmm(p[0]):.2f} radius={base_opts.radius} goto={base_opts.end_target_name}_{int(ii - 1)}"
            )

    # print(
    #    f"{base_opts.end_target_name} lat={dd2ddmm(lat0):.2f} lon={dd2ddmm(lon0):.2f} radius={base_opts.radius} goto={base_opts.start_target_name}_0"
    # )


if __name__ == "__main__":
    try:
        main()
    except Exception:
        if DEBUG_PDB:
            _, __, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")
