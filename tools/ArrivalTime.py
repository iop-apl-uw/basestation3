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

"""Esitmate time of arrival at target based on past N days run
"""
import argparse
import math
import sys
import os
import glob
import pdb
import time
import traceback

from pyproj import Geod
from shapely.geometry import Point, LineString
import xarray as xr
import numpy as np

DEBUG_PDB = False


def ddmm2dd(x):
    """Converts a lat/long from ddmm.mmm to dd.dddd

    Input: x - float in ddmm.mm format

    Returns: dd.ddd format of input

    Raises:
    """
    return float(int(x / 100.0) + math.fmod(x, 100.0) / 60.0)


def main():
    ap = argparse.ArgumentParser(
        "Esitmate time of arrival at target based on past N days run",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )
    ap.add_argument(
        "--days_back",
        default=2.0,
        type=float,
        help="Number of days of mission history to use",
    )
    ap.add_argument(
        "--mission_dir", type=str, required=True, help="Seagliders mission directory"
    )

    args = vars(ap.parse_args())

    days_back = args["days_back"]
    mission_dir = os.path.expanduser(args["mission_dir"])

    if not os.path.exists(mission_dir):
        print(f"Dir {mission_dir} does not exists")
        sys.exit(1)

    cdfs = []
    for m in glob.glob(os.path.join(f"{mission_dir}/p???????.nc")):
        cdfs.append(m)

    cdfs = sorted(cdfs)[::-1]

    latest_fix = None
    first_fix = None
    for cdf in cdfs:
        ds = xr.open_dataset(cdf)
        # pdb.set_trace()
        if not latest_fix:
            tgt_lat, tgt_lon = (
                ds["log_TGT_LATLONG"].to_numpy().tobytes().decode().split(",")
            )
            tgt_lat = ddmm2dd(float(tgt_lat))
            tgt_lon = ddmm2dd(float(tgt_lon))
            tgt_name = ds["log_TGT_NAME"].to_numpy().tobytes().decode()
            sg_id = int(ds["log_ID"].to_numpy())
            latest_fix = (
                ds["log_gps_time"][2].data.astype(np.float64) / 1000000000.0,
                float(ds["log_gps_lon"][2].data.astype(np.float64)),
                float(ds["log_gps_lat"][2].data.astype(np.float64)),
                int(ds["trajectory"].data.astype(np.int32)[0]),
            )
        else:
            first_fix = (
                ds["log_gps_time"][0].data.astype(np.float64) / 1000000000.0,
                float(ds["log_gps_lon"][0].data.astype(np.float64)),
                float(ds["log_gps_lat"][0].data.astype(np.float64)),
                int(ds["trajectory"].data.astype(np.int32)[0]),
            )
            if (latest_fix[0] - first_fix[0]) > days_back * 24 * 3600:
                break

    # print(latest_fix)
    # print(first_fix)

    geod = Geod(ellps="WGS84")
    line_string = LineString(
        [Point(first_fix[1], first_fix[2]), Point(latest_fix[1], latest_fix[2])]
    )
    dist_covered = geod.geometry_length(line_string)
    time_elapsed = latest_fix[0] - first_fix[0]

    dtg = geod.geometry_length(
        LineString([Point(latest_fix[1], latest_fix[2]), Point(tgt_lon, tgt_lat)])
    )

    # dtg += 28000

    ttg = dtg / (dist_covered / time_elapsed)

    # In UTC
    # arrival_time = time.strftime(
    #     "%Y-%m-%dT%H:%M:%SZ",
    #     time.gmtime(latest_fix[0] + ttg),
    # )
    arrival_time = time.strftime(
        "%Y-%m-%dT%H:%M:%S %Z",
        time.localtime(latest_fix[0] + ttg),
    )

    print(
        f"SG{sg_id} Dives {first_fix[3]}:{latest_fix[3]} dist_covered:{dist_covered/1000.0:.2f}km in {time_elapsed/3600.0:.2f} hours"
    )
    print(
        f"SG{sg_id} Target {tgt_name} ({tgt_lon:.4f},{tgt_lat:.4f}) dtg:{dtg/1000.0:.2f}km ttg:{ttg/3600.0:.2f} hours ({arrival_time})"
    )


try:
    main()
except SystemExit:
    pass
except Exception:
    if DEBUG_PDB:
        extype, value, tb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(tb)
    sys.stderr.write("Exception in main (%s)\n" % traceback.format_exc())
