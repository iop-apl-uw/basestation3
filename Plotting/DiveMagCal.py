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

"""Plot for compass mag calibration"""

# TODO: This can be removed as of python 3.11
from __future__ import annotations

import math
import typing

import numpy as np
import scipy.interpolate
import plotly.graph_objects
import datetime
import ppigrf

if typing.TYPE_CHECKING:
    import BaseOpts
    import scipy

import PlotUtils
import PlotUtilsPlotly

from BaseLog import (
    log_info,
)
from Plotting import plotdivesingle


@plotdivesingle
def plot_mag(
    base_opts: BaseOpts.BaseOptions,
    dive_nc_file: scipy.io._netcdf.netcdf_file,
    generate_plots=True,
    dbcon=None,
) -> tuple[list, list]:
    """Plot for compass mag calibration"""
    if "eng_mag_x" not in dive_nc_file.variables or not generate_plots:
        return ([], [])

    pitch = dive_nc_file.variables["eng_pitchAng"][:] * math.pi / 180.0
    roll = dive_nc_file.variables["eng_rollAng"][:] * math.pi / 180.0
    # unused head  = dive_nc_file.variables["eng_head"][:] * math.pi/180.0
    fxm = dive_nc_file.variables["eng_mag_x"][:]
    fym = -dive_nc_file.variables["eng_mag_y"][:]
    fzm = -dive_nc_file.variables["eng_mag_z"][:]
    npts = dive_nc_file.dimensions["sg_data_point"].size

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

            cp = math.cos(pitch[i])
            sp = math.sin(pitch[i])
            cr = math.cos(roll[i])
            sr = math.sin(roll[i])

            R11_i = cp
            R12_i = -sp * sr
            R13_i = -sp * cr
            R22_i = cr
            R23_i = -sr

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

            eqT = np.transpose(np.copy(eq))
            Jac = Jac + eq * eqT
            resid = resid + eq * fi

        dP = np.matmul(np.linalg.inv(Jac), resid)
        P = P - dP

        if it > 0:
            conv = 0

            x = np.transpose(np.divide(dP, P_prev))
            conv = x.dot(x.transpose())
            if conv < 1e-6:
                converged = 1
                break

        P_prev = np.copy(P)


    Ph = P * norm
    log_info(
        f"hard magcal PQR = [{P.item(0):.2f},{P.item(1):.2f},{P.item(2):.2f}], converged={converged:d}, it={it:d}"
    )

    fxm = fxm * norm
    fym = fym * norm
    fzm = fzm * norm


    igrf = ppigrf.igrf(dive_nc_file['log_gps_lon'][0],
                       dive_nc_file['log_gps_lat'][0],
                       0, datetime.datetime.fromtimestamp(dive_nc_file['log_gps_time'][0]))


    Wf = 0.1
    Wfh = 1.0
    F = 1.0
    ix = igrf[0][0][0]
    iy = igrf[1][0][0]
    iz = igrf[2][0][0]
    Fh = math.sqrt(ix*ix + iy*iy)/math.sqrt(ix*ix + iy*iy + iz*iz)

    norm = math.sqrt(Ph[0]*Ph[0] + Ph[1]*Ph[1] + Ph[2]*Ph[2])

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

            pit = pitch[i]
            rol = roll[i]

            cp = math.cos(pit)
            sp = math.sin(pit)
            cr = math.cos(rol)
            sr = math.sin(rol)

            R11_i = cp
            R12_i = -sp*sr
            R13_i = -sp*cr
            R22_i = cr
            R23_i = -sr
            R31_i = sp
            R32_i = cp*sr
            R33_i = cp*cr

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

            eqT = np.transpose(np.copy(eq))
            Jac = Jac + eq * eqT
            resid = resid + eq * fi

        dP = np.matmul(np.linalg.inv(Jac), resid)
        P = P - dP

        if it > 0:
            conv = 0

            x = np.transpose(np.divide(dP, P_prev))
            conv = x.dot(x.transpose())
            if conv < 1e-6:
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


    if abs(abc0[0][1]) > 0.2 or abs(abc[0][2]) > 0.2 or abs(abc[1][0]) > 0.2 or abs(abc[1][2]) > 0.2 or abs(abc[2][0]) > 0.2 or abs(abc0[2][1]) > 0.2:
        log_info('distrusting soft-iron, using identity')
        abc0[0][1] = 0     
        abc0[0][2] = 0     
        abc0[1][0] = 0
        abc0[1][2] = 0
        abc0[2][0] = 0
        abc0[2][1] = 0
        abc0[0][0] = 1
        abc0[1][1] = 1
        abc0[2][2] = 1

    fx = []
    fy = []
    fx_pqr = []
    fy_pqr = []

    doSG = False
    if "log_IRON" in dive_nc_file.variables:
        iron = list(
            map(
                float,
                dive_nc_file.variables["log_IRON"][:]
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
    if "log_MAGCAL" in dive_nc_file.variables:
        iron = list(
            map(
                float,
                dive_nc_file.variables["log_MAGCAL"][:]
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
        f = np.array([fxm[i] - P[0], fym[i] - P[1], fzm[i] - P[2]])
        f.shape = (3, 1)
        fxyz_pqr = Rp @ Rr @ abc0 @ f

        fx.append(fxyz.item(0))
        fy.append(fxyz.item(1))
        fx_pqr.append(fxyz_pqr.item(0))
        fy_pqr.append(fxyz_pqr.item(1))

        if doSG:
            f = np.array([fxm[i] - pqr[0], fym[i] - pqr[1], fzm[i] - pqr[2]])
            f.shape = (3, 1)
            fxyz_sg = Rp @ Rr @ abc @ f
            fx_sg.append(fxyz_sg.item(0))
            fy_sg.append(fxyz_sg.item(1))

        if doMAGCAL:
            f = np.array([fxm[i] - pqr2[0], fym[i] - pqr2[1], fzm[i] - pqr2[2]])
            f.shape = (3, 1)
            fxyz_mc = Rp @ Rr @ abc2 @ f
            fx_mc.append(fxyz_mc.item(0))
            fy_mc.append(fxyz_mc.item(1))

    minx = min([min(fx), min(fx_pqr)]);
    maxx = max([max(fx), max(fx_pqr)]);
    miny = min([min(fy), min(fy_pqr)]);
    maxy = max([max(fy), max(fy_pqr)]);

    fig = plotly.graph_objects.Figure()
    fig.add_trace(
        {
            "x": fx,
            "y": fy,
            "name": "uncorrected",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-down",
                "color": "Red",
            },
            "hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
        }
    )
    fig.add_trace(
        {
            "x": fx_pqr,
            "y": fy_pqr,
            "name": "corrected",
            "type": "scatter",
            "mode": "markers",
            "marker": {
                "symbol": "triangle-up",
                "color": "DarkBlue",
            },
            "hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
        }
    )

    if doSG:
        fig.add_trace(
            {
                "x": fx_sg,
                "y": fy_sg,
                "name": "onboard",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "Magenta",
                },
                "hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
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
                "name": f"autocal<br>cover={mc_cover:.0f}<br>circ={mc_quality:.2f}<br>used={mc_used:.0f}",
                "type": "scatter",
                "mode": "markers",
                "marker": {
                    "symbol": "triangle-up",
                    "color": "cyan",
                },
                "hovertemplate": "%{x:.0f},%{y:.0f}<br><extra></extra>",
            }
        )
        minx = min([minx, min(fx_mc)]);
        maxx = max([maxx, max(fx_mc)]);
        miny = min([miny, min(fy_mc)]);
        maxy = max([maxy, max(fy_mc)]);

    minlim = min([minx, miny])
    maxlim = max([maxx, maxy])
    lim = max([abs(minlim), abs(maxlim)])*1.05
    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    fit_line = (
        f'calculated (blue) hard0="{P.item(0):.1f} {P.item(1):.1f} {P.item(2):.1f}"<br>soft0="{abc0[0][0]:.3f} {abc0[0][1]:.3f} {abc0[0][2]:.3f} {abc0[1][0]:.3f} {abc0[1][1]:.3f} {abc0[1][2]:.3f} {abc0[2][0]:.3f} {abc0[2][1]:.3f} {abc0[2][2]:.3f}'
    )
    title_text = f"{mission_dive_str}<br>Compass calibration<br>{fit_line}"

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

    return (
        [fig],
        PlotUtilsPlotly.write_output_files(
            base_opts,
            "dv%04d_magcal" % (dive_nc_file.dive_number,),
            fig,
        ),
    )
