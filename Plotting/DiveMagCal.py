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
    npts = dive_nc_file.dimensions["sg_data_point"]

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
    P[0] = mx
    P[1] = my
    P[2] = mz
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

    fxm = fxm * norm
    fym = fym * norm
    fzm = fzm * norm

    P = P * norm
    log_info(
        f"magcal PQR = [{P.item(0):.2f},{P.item(1):.2f},{P.item(2):.2f}], converged={converged:d}, it={it:d}"
    )

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
        fxyz_pqr = Rp @ Rr @ f

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

    mission_dive_str = PlotUtils.get_mission_dive(dive_nc_file)
    fit_line = (
        f'calculated (blue) hard0="{P.item(0):.1f} {P.item(1):.1f} {P.item(2):.1f}"'
    )
    title_text = f"{mission_dive_str}<br>Compass hard iron calibration<br>{fit_line}"

    fig.update_layout(
        {
            "xaxis": {
                "title": "X field",
                "showgrid": True,
            },
            "yaxis": {
                "title": "Y field",
                "showgrid": True,
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
