#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2024  University of Washington.
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

"""compass mag calibration"""
# fmt: off

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import math
import typing
import os
import sys

import numpy as np
import plotly.graph_objects
import datetime
import warnings
import ppigrf
import random
import argparse

if typing.TYPE_CHECKING:
    import scipy

import PlotUtils
import BaseOpts
import BaseOptsType
import Utils
import CommLog
import RegressVBD

from BaseLog import (
    log_info,
)


def magcal(
    path: str,
    glider: int,
    dives: list[int],
    softiron: bool,
    doplot: str
) -> tuple[list, np.array, float, float, Any]:

    nc_files = []
    for d in dives:
        fname = os.path.join(path, f'p{glider:03d}{d:04d}.nc')
        try:
            nc_files.append(Utils.open_netcdf_file(fname))
        except:
            pass

    if len(nc_files) == 0:
        return ([], [], 0, 0, None)

    if len(nc_files) == 1:
        title = PlotUtils.get_mission_dive(nc_files[0])
    else:
        title = PlotUtils.get_mission_str(nc_files[0]) + f' dives {dives}'

    hard, soft, cover, circ, fig = magcal_worker(nc_files, softiron, doplot, title)

    if fig and doplot == 'png':
        imgs = fig.to_image(format="png")
    elif fig and doplot == 'html':
        imgs = fig.to_html(
                            include_plotlyjs="cdn",
                            full_html=False,
                            validate=True,
                            config={
                                "modeBarButtonsToRemove": ["lasso2d", "select2d"],
                                "scrollZoom": False,
                            },
                            include_mathjax="cdn",
                           ) 
    else:
        imgs = None

    return (hard, soft, cover, circ, imgs)

def magcal_worker(
    dive_nc_file: list[scipy.io._netcdf.netcdf_file],
    softiron: bool,
    doplot: str,
    title: str
) -> tuple[list, np.array, float, float, plotly.graph_object.Figure]:
    
    if "eng_mag_x" not in dive_nc_file[0].variables:
        return ([], [], 0, 0, None)

    npts      = 0
    for f in dive_nc_file:
        npts = npts + f.dimensions["sg_data_point"].size

    pitch     = np.empty(shape=(0))
    roll      = np.empty(shape=(0))
    fxm       = np.empty(shape=(0))
    fym       = np.empty(shape=(0))
    fzm       = np.empty(shape=(0))
    pitch_deg = np.empty(shape=(0))
    roll_deg  = np.empty(shape=(0))

    if npts > 2000:
        decimate = math.ceil(npts / 2000)
        idx = range(0, npts, decimate)
        npts = len(idx) + len(dive_nc_file)
    else:
        decimate = 1

    pitch     = np.empty(shape=(npts,))
    roll      = np.empty(shape=(npts,))
    fxm       = np.empty(shape=(npts,))
    fym       = np.empty(shape=(npts,))
    fzm       = np.empty(shape=(npts,))
    pitch_deg = np.empty(shape=(npts,))
    roll_deg  = np.empty(shape=(npts,))

    k = 0
    for f in dive_nc_file:
        mpts = f.dimensions["sg_data_point"].size
        idx = range(0, mpts, decimate)
        print(idx)
        mpts = len(idx)
        print(npts, k, mpts)
        print(len(f.variables["eng_pitchAng"][idx]))
        print(len(pitch[k:k+mpts]))
        pitch[k:k+mpts]     = f.variables["eng_pitchAng"][idx] * math.pi / 180.0
        roll[k:k+mpts]      = f.variables["eng_rollAng"][idx] * math.pi / 180.0
        fxm[k:k+mpts]       = f.variables["eng_mag_x"][idx]
        fym[k:k+mpts]       = -f.variables["eng_mag_y"][idx]
        fzm[k:k+mpts]       = -f.variables["eng_mag_z"][idx]
        pitch_deg[k:k+mpts] = f.variables["eng_pitchAng"][idx]
        roll_deg[k:k+mpts]  = f.variables["eng_rollAng"][idx]
        k = k + mpts
        
    npts = max([k, npts])

    obs_num = np.arange(0,npts)
    
    norm = 0
    mx = 0
    my = 0
    mz = 0
    for i in range(0, npts):
        norm = norm + math.sqrt(fxm[i] * fxm[i] + fym[i] * fym[i] + fzm[i] * fzm[i])
        mx = mx + fxm[i]
        my = my + fym[i]
        mz = mz + fzm[i]

    mx = mx / norm
    my = my / norm
    mz = mz / norm

    norm = norm / npts

    fxm = fxm / norm
    fym = fym / norm
    fzm = fzm / norm

    P = np.zeros([4, 1])
    P[0] = 0 # mx
    P[1] = 0 # my
    P[2] = 0 # mz
    P[3] = 1

    converged = 0

    eq = np.empty([4, 1])
    resid = np.empty([4, 1])

    cp = np.cos(pitch)
    sp = np.sin(pitch)
    cr = np.cos(roll)
    sr = np.sin(roll)

    for it in range(0, 25):
        Jac = np.zeros([4, 4])
        resid = np.zeros([4, 1])

        p = P[0]
        q = P[1]
        r = P[2]
        F = P[3]

        R21_i = 0
        for i in range(0, npts):
            Mx_i = fxm[i] - p
            My_i = fym[i] - q
            Mz_i = fzm[i] - r

            R11_i = cp[i]
            R12_i = -sp[i] * sr[i]
            R13_i = -sp[i] * cr[i]
            R22_i = cr[i]
            R23_i = -sr[i]

            eq[0] = -2 * R11_i * (
                R11_i * Mx_i + R12_i * My_i + R13_i * Mz_i
            ) - 2 * R21_i * (R21_i * Mx_i + R22_i * My_i + R23_i * Mz_i)
            eq[1] = -2 * R12_i * (
                R11_i * Mx_i + R12_i * My_i + R13_i * Mz_i
            ) - 2 * R22_i * (R21_i * Mx_i + R22_i * My_i + R23_i * Mz_i)
            eq[2] = -2 * R13_i * (
                R11_i * Mx_i + R12_i * My_i + R13_i * Mz_i
            ) - 2 * R23_i * (R21_i * Mx_i + R22_i * My_i + R23_i * Mz_i)
            eq[3] = -2 * F

            Fxi = R11_i * Mx_i + R12_i * My_i + R13_i * Mz_i
            Fyi = R21_i * Mx_i + R22_i * My_i + R23_i * Mz_i

            fi = Fxi * Fxi + Fyi * Fyi - F * F

            # eqT = np.transpose(np.copy(eq))
            Jac = Jac + np.outer(eq, eq) # eq * eqT
            resid = resid + eq * fi

        dP = np.matmul(np.linalg.inv(Jac), resid)
        P = P - dP

        if it > 0:
            x = np.divide(dP, P_prev)
            conv = np.dot(x.reshape(4,), x.reshape(4,))
            if conv < 1e-4:
                converged = 1
                break

        P_prev = np.copy(P)


    Ph = P * norm
    log_info(
        f"hard magcal PQR = [{Ph.item(0):.2f},{Ph.item(1):.2f},{Ph.item(2):.2f}], converged={converged:d}, it={it:d}"
    )

    fxm = fxm * norm
    fym = fym * norm
    fzm = fzm * norm

    if softiron:
        with warnings.catch_warnings():
            # GBS 2024/04/12 - getting this
            # WARNING: /opt/basestation/lib/python3.10/site-packages/ppigrf/ppigrf.py:139: FutureWarning:
            # The 'unit' keyword in TimedeltaIndex construction is deprecated and will be removed in a future version. Use pd.to_timedelta instead.
            # on some package combos - filter out for now
            warnings.simplefilter('ignore', FutureWarning)            
            igrf = ppigrf.igrf(dive_nc_file[0]['log_gps_lon'][0],
                               dive_nc_file[0]['log_gps_lat'][0],
                               0, datetime.datetime.fromtimestamp(dive_nc_file[0]['log_gps_time'][0]))

        Wf = 0.1
        Wfh = 1.0
        F = 1.0
        # GBS 2024/11/21 - Inslates the code from versions of ppigrf that return (1,1) or (1,) arrays
        ix = np.squeeze(igrf)[0]
        iy = np.squeeze(igrf)[1]
        iz = np.squeeze(igrf)[2]
        Fh = math.sqrt(ix*ix + iy*iy)/math.sqrt(ix*ix + iy*iy + iz*iz)

        norm = math.sqrt(Ph.item(0)*Ph.item(0) + Ph.item(1)*Ph.item(1) + Ph.item(2)*Ph.item(2))

        P = np.zeros([12, 1])
        P[0] = Ph[0] / norm
        P[1] = Ph[1] / norm
        P[2] = Ph[2] / norm
        for j in range(4,12):
            P[j] = 0;
       
        P[3] = 1;
        P[7] = 1;
        P[11] = 1;

        fxm = fxm / norm
        fym = fym / norm
        fzm = fzm / norm

        converged = 0

        eq = np.empty([12, 1])
        resid = np.empty([12, 1])

        for it in range(0, 25):
            Jac = np.zeros([12, 12])
            resid = np.zeros([12, 1])

            p = P[0]
            q = P[1]
            r = P[2]
            a = P[3]
            b = P[4]
            c = P[5]
            d = P[6]
            e = P[7]
            f = P[8]
            g = P[9]
            h = P[10]
            k = P[11]

            R21_i = 0
            for i in range(0, npts):
                Mx_i = fxm[i] - p
                My_i = fym[i] - q
                Mz_i = fzm[i] - r

                R11_i = cp[i]
                R12_i = -sp[i]*sr[i]
                R13_i = -sp[i]*cr[i]
                R22_i = cr[i]
                R23_i = -sr[i]
                R31_i = sp[i]
                R32_i = cp[i]*sr[i]
                R33_i = cp[i]*cr[i]

                eq[0] = Wf*((-2*R11_i*a - 2*R12_i*d - 2*R13_i*g)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*a - 2*R22_i*d - 2*R23_i*g)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R31_i*a - 2*R32_i*d - 2*R33_i*g)*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*((-2*R11_i*a - 2*R12_i*d - 2*R13_i*g)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*a - 2*R22_i*d - 2*R23_i*g)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[1] = Wf*((-2*R11_i*b - 2*R12_i*e - 2*R13_i*h)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*b - 2*R22_i*e - 2*R23_i*h)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R31_i*b - 2*R32_i*e - 2*R33_i*h)*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*((-2*R11_i*b - 2*R12_i*e - 2*R13_i*h)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*b - 2*R22_i*e - 2*R23_i*h)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[2] = Wf*((-2*R11_i*c - 2*R12_i*f - 2*R13_i*k)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*c - 2*R22_i*f - 2*R23_i*k)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R31_i*c - 2*R32_i*f - 2*R33_i*k)*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*((-2*R11_i*c - 2*R12_i*f - 2*R13_i*k)*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + (-2*R21_i*c - 2*R22_i*f - 2*R23_i*k)*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[3] = Wf*(2*R11_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R31_i*Mx_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R11_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[4] = Wf*(2*R11_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R31_i*My_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R11_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[5] = Wf*(2*R11_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R31_i*Mz_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R11_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R21_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[6] = Wf*(2*R12_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R32_i*Mx_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R12_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[7] = Wf*(2*R12_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R32_i*My_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R12_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[8] = Wf*(2*R12_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R32_i*Mz_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R12_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R22_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[9] = Wf*(2*R13_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R33_i*Mx_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R13_i*Mx_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*Mx_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[10] = Wf*(2*R13_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R33_i*My_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R13_i*My_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*My_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))
                eq[11] = Wf*(2*R13_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R33_i*Mz_i*(R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i))) + Wfh*(2*R13_i*Mz_i*(R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)) + 2*R23_i*Mz_i*(R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)))

                Fxi = R11_i*(a*Mx_i + b*My_i + c*Mz_i) + R12_i*(d*Mx_i + e*My_i + f*Mz_i) + R13_i*(g*Mx_i + h*My_i + k*Mz_i)
                Fyi = R21_i*(a*Mx_i + b*My_i + c*Mz_i) + R22_i*(d*Mx_i + e*My_i + f*Mz_i) + R23_i*(g*Mx_i + h*My_i + k*Mz_i)
                Fzi = R31_i*(a*Mx_i + b*My_i + c*Mz_i) + R32_i*(d*Mx_i + e*My_i + f*Mz_i) + R33_i*(g*Mx_i + h*My_i + k*Mz_i)

                fi = Wf*(Fxi*Fxi + Fyi*Fyi + Fzi*Fzi - F*F) + Wfh*(Fxi*Fxi + Fyi*Fyi - Fh*Fh)

                # eqT = np.transpose(np.copy(eq))
                Jac = Jac + np.outer(eq,eq) # eq * eqT
                resid = resid + eq * fi

            dP = np.matmul(np.linalg.inv(Jac), resid)
            P = P - dP

            if it > 0:
                # x = np.transpose(np.divide(dP, P_prev))
                # conv = x.dot(x.transpose())

                x = np.divide(dP, P_prev)
                conv = np.dot(x.reshape(12,),x.reshape(12,))
                if conv < 1e-4:
                    converged = 1
                    break

            P_prev = np.copy(P)

        fxm = fxm * norm
        fym = fym * norm
        fzm = fzm * norm
        P[0] = P[0]*norm
        P[1] = P[1]*norm
        P[2] = P[2]*norm

        abc0 = np.array(
            [
                [P[3][0], P[4][0], P[5][0]],
                [P[6][0], P[7][0], P[8][0]],
                [P[9][0], P[10][0], P[11][0]],
            ]
        )

        log_info(
            f"hard+soft magcal PQR = [{P.item(0):.2f},{P.item(1):.2f},{P.item(2):.2f}], converged={converged:d}, it={it:d}"
        )

        abc0 = abc0 / P[3][0]

        log_info(
            f"hard+soft magcal abc = {abc0[0][0]:.3f},{abc0[0][1]:.3f},{abc0[0][2]:.3f},{abc0[1][0]:.3f},{abc0[1][1]:.3f},{abc0[1][2]:.3f},{abc0[2][0]:.3f},{abc0[2][1]:.3f},{abc0[2][2]:.3f}"
        )


        if not converged or abs(abc0[0][1]) > 0.2 or abs(abc0[0][2]) > 0.2 or abs(abc0[1][0]) > 0.2 or abs(abc0[1][2]) > 0.2 or abs(abc0[2][0]) > 0.2 or abs(abc0[2][1]) > 0.2:
            log_info('distrusting soft-iron, using hard-only solution with identity for soft')
            abc0 = np.eye(3)
            P = Ph
            softiron = False
    else:
        P = Ph
        abc0 = np.eye(3)

    fx = []
    fy = []
    fx_pqr = []
    fy_pqr = []
    fx_h = []
    fy_h = []

    doSG = False
    if "log_IRON" in dive_nc_file[-1].variables:
        iron = list(
            map(
                float,
                dive_nc_file[-1].variables["log_IRON"][:]
                .tobytes()
                .decode("utf-8")
                .split(","),
            )
        )

        abc = np.array(
            [
                [iron[0], iron[1], iron[2]],
                [iron[3], iron[4], iron[5]],
                [iron[6], iron[7], iron[8]],
            ]
        )
        pqr = np.array([iron[9], iron[10], iron[11]])
        pqr.shape = (3, 1)
        fx_sg = []
        fy_sg = []
        doSG = True
        
    doMAGCAL = False
    if "log_MAGCAL" in dive_nc_file[-1].variables:
        iron = list(
            map(
                float,
                dive_nc_file[-1].variables["log_MAGCAL"][:]
                .tobytes()
                .decode("utf-8")
                .split(","),
            )
        )

        abc2 = np.array(
            [
                [iron[0], iron[1], iron[2]],
                [iron[3], iron[4], iron[5]],
                [iron[6], iron[7], iron[8]],
            ]
        )
        pqr2 = np.array([iron[9], iron[10], iron[11]])
        pqr2.shape = (3, 1)
        fx_mc = []
        fy_mc = []
        mc_cover = iron[12]
        mc_quality = iron[13]
        mc_used = iron[14]
        doMAGCAL = True

    Radius = 0
    Radius2 = 0
    Radius_pqr = 0
    Radius_pqr2 = 0
    Radius_h = 0
    Radius_h2 = 0
    Radius_sg = 0
    Radius_sg2 = 0
    Radius_mc = 0
    Radius_mc2 = 0
    for i in range(0, npts):
        c = math.cos(roll[i])
        s = math.sin(roll[i])
        Rr = np.array([[1, 0, 0], [0, c, s], [0, -s, c]])
        c = math.cos(pitch[i])
        s = math.sin(pitch[i])
        Rp = np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]])

        Rp = np.transpose(Rp)
        Rr = np.transpose(Rr)

        f = np.array([fxm[i], fym[i], fzm[i]])
        f.shape = (3, 1)
        fxyz = Rp @ Rr @ f

        f = np.array([fxm[i] - Ph[0], fym[i] - Ph[1], fzm[i] - Ph[2]])
        f.shape = (3, 1)
        fxyz_h = Rp @ Rr @ f
        
        if softiron:
            f = np.array([fxm[i] - P[0], fym[i] - P[1], fzm[i] - P[2]])
            f.shape = (3, 1)
            fxyz_pqr = Rp @ Rr @ abc0 @ f

            fx_pqr.append(fxyz_pqr.item(0))
            fy_pqr.append(fxyz_pqr.item(1))
            rad = math.sqrt(fxyz_pqr.item(0)*fxyz_pqr.item(0) + fxyz_pqr.item(1)*fxyz_pqr.item(1))
            # full hard+soft correction
            Radius_pqr = Radius_pqr + rad
            Radius_pqr2 = Radius_pqr2 + rad*rad

        fx.append(fxyz.item(0))
        fy.append(fxyz.item(1))
        rad = math.sqrt(fxyz.item(0)*fxyz.item(0) + fxyz.item(1)*fxyz.item(1))
        # uncorrected
        Radius = Radius + rad
        Radius2 = Radius2 + rad*rad


        fx_h.append(fxyz_h.item(0))
        fy_h.append(fxyz_h.item(1))
        rad = math.sqrt(fxyz_h.item(0)*fxyz_h.item(0) + fxyz_h.item(1)*fxyz_h.item(1))
        # hard only correction
        Radius_h = Radius_h + rad
        Radius_h2 = Radius_h2 + rad*rad

        if doSG:
            f = np.array([fxm[i] - pqr[0], fym[i] - pqr[1], fzm[i] - pqr[2]])
            f.shape = (3, 1)
            fxyz_sg = Rp @ Rr @ abc @ f
            fx_sg.append(fxyz_sg.item(0))
            fy_sg.append(fxyz_sg.item(1))
            rad = math.sqrt(fxyz_sg.item(0)*fxyz_sg.item(0) + fxyz_sg.item(1)*fxyz_sg.item(1))
            # as corrected onboard
            Radius_sg = Radius_sg + rad
            Radius_sg2 = Radius_sg2 + rad*rad

        if doMAGCAL:
            f = np.array([fxm[i] - pqr2[0], fym[i] - pqr2[1], fzm[i] - pqr2[2]])
            f.shape = (3, 1)
            fxyz_mc = Rp @ Rr @ abc2 @ f
            fx_mc.append(fxyz_mc.item(0))
            fy_mc.append(fxyz_mc.item(1))
            rad = math.sqrt(fxyz_mc.item(0)*fxyz_mc.item(0) + fxyz_mc.item(1)*fxyz_mc.item(1))
            # as corrected with autocal
            Radius_mc = Radius_mc + rad
            Radius_mc2 = Radius_mc2 + rad*rad

    minx = min(fx)
    maxx = max(fx)
    miny = min(fy)
    maxy = max(fy)

    if Radius_mc > 0:
        Radius_mc = Radius_mc / len(fx_mc)
        circ_mc = math.sqrt(Radius_mc2/len(fx_mc) - Radius_mc*Radius_mc) / Radius_mc
    if Radius_sg > 0:
        Radius_sg = Radius_sg / len(fx_sg)
        circ_sg = math.sqrt(Radius_sg2/len(fx_sg) - Radius_sg*Radius_sg) / Radius_sg

    Radius_h = Radius_h / len(fx)
    circ_h = math.sqrt(Radius_h2/len(fx) - Radius_h*Radius_h) / Radius_h
    Radius = Radius / len(fx)
    circ = math.sqrt(Radius2/len(fx) - Radius*Radius) / Radius

    if softiron:
        Radius_pqr = Radius_pqr / len(fx)
        circ_pqr = math.sqrt(Radius_pqr2/len(fx) - Radius_pqr*Radius_pqr) / Radius_pqr

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": fx,
            "y": fy,
            "customdata": np.squeeze(
                np.dstack(
                    (np.transpose(obs_num), np.transpose(roll_deg), np.transpose(pitch_deg))
                )
            ),
            "name": f"uncorrected ({circ:.2f})",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Red",
            },
            #"hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
            "hovertemplate": "X:%{x:.0f},Y:%{y:.0f}<br>obs:%{customdata[0]},roll:%{customdata[1]:.1f},pitch:%{customdata[2]:.1f}<extra></extra>",
        }
    )

    if softiron:
        fig.add_trace(
            {
                "x": fx_pqr,
                "y": fy_pqr,
                "customdata": np.squeeze(
                    np.dstack(
                        (np.transpose(obs_num), np.transpose(roll_deg), np.transpose(pitch_deg))
                    )
                ),
                "name": f"corrected ({circ_pqr:.2f})",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "DarkBlue",
                },
                #"hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
                "hovertemplate": "X:%{x:.0f},Y:%{y:.0f}<br>obs:%{customdata[0]},roll:%{customdata[1]:.1f},pitch:%{customdata[2]:.1f}<extra></extra>",
            }
        )
        minx = min([minx, min(fx_pqr)]);
        maxx = max([maxx, max(fx_pqr)]);
        miny = min([miny, min(fy_pqr)]);
        maxy = max([maxy, max(fy_pqr)]);

    fig.add_trace(
        {
            "x": fx_h,
            "y": fy_h,
            "customdata": np.squeeze(
                np.dstack(
                    (np.transpose(obs_num), np.transpose(roll_deg), np.transpose(pitch_deg))
                )
            ),
            "name": f"hard corrected ({circ_h:.2f})",
            "type": "scatter",
            "mode": "markers",
            "visible": "legendonly" if softiron else True,
            "marker": {
                "symbol": "triangle-down",
                "color": "cyan",
            },
            #"hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
            "hovertemplate": "X:%{x:.0f},Y:%{y:.0f}<br>obs:%{customdata[0]},roll:%{customdata[1]:.1f},pitch:%{customdata[2]:.1f}<extra></extra>",
        }
    )

    if doSG:
        fig.add_trace(
            {
                "x": fx_sg,
                "y": fy_sg,
                "customdata": np.squeeze(
                    np.dstack(
                        (np.transpose(obs_num), np.transpose(roll_deg), np.transpose(pitch_deg))
                    )
                ),
                "name": f"onboard ({circ_sg:.2f})",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Magenta",
                },
                #"hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
                "hovertemplate": "X:%{x:.0f},Y:%{y:.0f}<br>obs:%{customdata[0]},roll:%{customdata[1]:.1f},pitch:%{customdata[2]:.1f}<extra></extra>",
            }
        )
        minx = min([minx, min(fx_sg)]);
        maxx = max([maxx, max(fx_sg)]);
        miny = min([miny, min(fy_sg)]);
        maxy = max([maxy, max(fy_sg)]);

    if doMAGCAL:
        fig.add_trace(
            {
                "x": fx_mc,
                "y": fy_mc,
                "customdata": np.squeeze(
                    np.dstack(
                        (np.transpose(obs_num), np.transpose(roll_deg), np.transpose(pitch_deg))
                    )
                ),
                "name": f"autocal<br>cover={mc_cover:.0f}<br>circ={mc_quality:.2f}<br>used={mc_used:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "LightBlue",
                },
                #"hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
                "hovertemplate": "X:%{x:.0f},Y:%{y:.0f}<br>obs:%{customdata[0]},roll:%{customdata[1]:.1f},pitch:%{customdata[2]:.1f}<extra></extra>",
            }
        )
        minx = min([minx, min(fx_mc)]);
        maxx = max([maxx, max(fx_mc)]);
        miny = min([miny, min(fy_mc)]);
        maxy = max([maxy, max(fy_mc)]);

    minlim = min([minx, miny])
    maxlim = max([maxx, maxy])
    lim = max([abs(minlim), abs(maxlim)])*1.05
    if softiron:
        fit_line = (
            f'hard0="{P.item(0):.1f} {P.item(1):.1f} {P.item(2):.1f}"<br>soft0="{abc0[0][0]:.3f} {abc0[0][1]:.3f} {abc0[0][2]:.3f} {abc0[1][0]:.3f} {abc0[1][1]:.3f} {abc0[1][2]:.3f} {abc0[2][0]:.3f} {abc0[2][1]:.3f} {abc0[2][2]:.3f}'
        )
    else:
        fit_line = (
            f'hard0="{Ph.item(0):.1f} {Ph.item(1):.1f} {Ph.item(2):.1f}"'
        )

    title_text = f"{title}<br>compass calibration<br>{fit_line}"

    fig.update_layout(
        {
            "xaxis": {
                "title": "X field",
                "showgrid": True,
                "range": [-lim, lim],
            },
            "yaxis": {
                "title": "Y field",
                "showgrid": True,
                "range": [-lim, lim],
                "domain": [0.0, 0.95],
            },
            "title": {
                "text": title_text,
                "xanchor": "center",
                "yanchor": "top",
                "x": 0.5,
                "y": 0.95,
            },
            "margin": {
                "t": 100,
                "b": 125,
            },
        }
    )

    fig.update_yaxes(
        scaleanchor="x",
        scaleratio=1,
    )


    cover = 0
    return (
        [P.item(0), P.item(1), P.item(2)],
        abc0,
        cover,
        circ_pqr if softiron else circ_h,
        fig,
    )

def main():
    base_opts = BaseOpts.BaseOptions("Command line app for compass calibration\nTypical usage (from glider mission directory): python Magcal.py -m ./ -i 235 --dives 3-5 --out results.html",
        additional_arguments={
            "dives": BaseOptsType.options_t(
                "",
                ("Magcal",),
                ( "--dives", ), 
                str,
                {
                    "help": "dives to process (e.g.: 3-4,7)",
                    "required": ("Magcal",) 
                }
            ),
            "out": BaseOptsType.options_t(
                "",
                ("Magcal",),
                ( "--out", ), 
                str,
                {
                    "help": "output file name",
                    "required": ("Magcal",) 
                }
            ),
            "soft": BaseOptsType.options_t(
                True,
                ("Magcal",),
                ("--soft",),
                bool,
                {
                    "help": "include soft-iron",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
        }
    )

    if not base_opts.instrument_id:
        (comm_log, _, _, _, _) = CommLog.process_comm_log(
            os.path.join(base_opts.mission_dir, "comm.log"),
            base_opts,
        )
        if comm_log:
            base_opts.instrument_id = comm_log.get_instrument_id()

    if not base_opts.instrument_id:
        _, tail = os.path.split(base_opts.mission_dir[:-1])
        if tail[-5:-3] != "sg":
            print("Can't figure out the instrument id - bailing out")
            return
        try:
            base_opts.instrument_id = int(tail[-3:])
        except:
            print("Can't figure out the instrument id - bailing out")
            return

    dives = RegressVBD.parseRangeList(base_opts.dives)
    if not dives or len(dives) < 1:
        print("invalid dives list")
        return 

    if base_opts.out and 'html' in base_opts.out:
        fmt = 'html'
    elif base_opts.out and 'png' in base_opts.out:
        fmt = 'png'
    else:
        fmt = False

    hard, soft, cover, circ, plt = magcal(base_opts.mission_dir,
                                          base_opts.instrument_id,
                                          dives,
                                          base_opts.soft,
                                          fmt)

    if fmt == 'html':
        fid = open(base_opts.out, 'w')
    elif fmt == 'png':
        fid = open(base_opts.out, 'wb')

    fid.write(plt)
    fid.close()
  
    print(f"hard = {hard}")
    print(f"soft = {soft}")

if __name__ == "__main__":
    retval = 1

    retval = main()

    sys.exit(retval)
