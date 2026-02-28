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

import collections
import os
import pdb
import sys
import time
import traceback

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))

import BaseOpts
import Utils2
from BaseLog import BaseLogger, log_error, log_info

# Options
DEBUG_PDB = False

known_labels = (
    "backscatter_00",
    "backscatter_01",
    "backscatter_02",
    "chlorophyll_00",
    "chlorophyll_01",
    "chlorophyll_02",
    "fdom_00",
    "fdom_01",
    "fdom_03",
    "turbidity_00",
    "turbidity_01",
    "turbidity_02",
)
known_typs = ("turb15", "turb21", "turb23", "fluo49", "fluo46")


def main():
    base_opts = BaseOpts.BaseOptions(
        "Get legato pressure correction constants from a Seaglider selftest capture file",
        additional_arguments={
            "capture": BaseOpts.options_t(
                None,
                ("GetTridenteChannels",),
                ("capture",),
                str,
                {
                    "help": "Seaglider self-test capture",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    global DEBUG_PDB
    DEBUG_PDB = base_opts.debug_pdb

    BaseLogger(base_opts)

    line_count = 0

    channels = collections.defaultdict(dict)
    model = serial_num = None
    f_in_tridente = False
    try:
        with open(base_opts.capture, "rb") as fi:
            for raw_line in fi:
                line_count += 1
                try:
                    s = raw_line.decode("utf-8")
                except UnicodeDecodeError:
                    log_info(
                        f"Could not decode line {line_count} in {base_opts.capture} - skipping"
                    )
                    continue
                if s.startswith("*** tridente"):
                    f_in_tridente = True
                elif s.startswith("***"):
                    f_in_tridente = False

                if not f_in_tridente:
                    continue
                s = s.rstrip().removeprefix("Ready:").lstrip()
                if s.startswith("calibration "):
                    for sensor_line in s.split("||"):
                        try:
                            sensor_str, tail = sensor_line.split(" ", 2)[1:]
                            sensor = int(sensor_str)
                        except Exception:
                            continue
                        if not tail:
                            continue
                        splits = tail.split(",")
                        for ss in splits:
                            k, v = (x.strip() for x in ss.split("="))
                            if k == "label" and v not in known_labels:
                                break
                            if k == "datetime":
                                channels[sensor]["datetime"] = time.strftime(
                                    "%Y-%m-%dT%H:%M:%SZ",
                                    time.strptime(v, "%Y%m%d%H%M%S"),
                                )
                elif s.startswith("channel "):
                    for channel_line in s.split("||"):
                        try:
                            channel_str, tail = channel_line.split(" ", 2)[1:]
                            channel = int(channel_str)
                        except Exception:
                            continue
                        splits = tail.split(",")
                        for ss in splits:
                            k, v = (x.strip() for x in ss.split("="))
                            if k == "type":
                                if v not in known_typs:
                                    break
                                channels[channel]["typ"] = v
                            if k == "label":
                                channels[channel]["label"] = v
                elif s.startswith("sensor "):
                    for sensor_line in s.split("||"):
                        try:
                            sensor_str, tail = sensor_line.split(" ", 2)[1:]
                            sensor = int(sensor_str)
                        except Exception:
                            continue
                        if not tail:
                            continue
                        if sensor not in channels:
                            break
                        splits = tail.split(",")
                        for ss in splits:
                            k, v = (x.strip() for x in ss.split("="))
                            if k == "wavelength":
                                channels[sensor]["wavelength"] = v
                elif s.startswith("id model"):
                    for ss in s.split(","):
                        k, v = (x.rstrip().lstrip() for x in ss.split("="))
                        if k == "id model" and v == "RBRtridente":
                            model = v
                        elif k == "serial":
                            serial_num = v
                    if model is None or serial_num is None:
                        model = serial_num = None
        calib_comm = ""
        if model is not None:
            calib_comm += f"{model} "
        if serial_num is not None:
            calib_comm += f"serialnum:{serial_num} "
        found_one = None
        instrument_name = ""

        for channel, values in channels.items():
            if all(x in values for x in ("typ", "label", "wavelength", "datetime")):
                if not found_one:
                    found_one = True
                    print("Tridente channels found")
                print(f"{channel}:{values}")
                calib_comm += f"{values['label']}:{values['datetime']} "
                wl = values["wavelength"][:3]
                if values["label"].startswith("back"):
                    instrument_name += f"bb{wl}"
                elif values["label"].startswith("chlo"):
                    instrument_name += f"chla{wl}"
                elif values["label"].startswith("fdom"):
                    instrument_name += f"fdom{wl}"
                elif values["label"].startswith("tu"):
                    instrument_name += f"tu{wl}"
                else:
                    instrument_name += "UNKNOWN"

        if not found_one:
            print("No Tridente channels found")

        if calib_comm:
            print("Add to sg_calib_constants.m")
            print(f"calibcomm_tridente{instrument_name}='{calib_comm.rstrip()}';")

        if instrument_name not in Utils2.known_tridente_channels():
            print(
                f"WARNING!! {instrument_name} not in list of known tridente channel combinations - please contact the maintainers of https://github.com/iop-apl-uw/basestation3"
            )

    except Exception:
        if DEBUG_PDB:
            _, _, tb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(tb)
        else:
            log_error("Untrapped error", "exc")


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
