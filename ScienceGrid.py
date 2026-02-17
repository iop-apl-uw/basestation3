#! /usr/bin/env python
# -*- python-fmt -*-

import asyncio
import collections
import contextlib
import copy
import functools
import pathlib
import pdb
import sys
import tempfile
import traceback
from typing import Literal

import scicon
import Sensors
import Utils

# import validate
from BaseLog import log_error, log_info

DEBUG_PDB = False


def DEBUG_PDB_F() -> None:
    """Enter the debugger on exceptions"""
    if DEBUG_PDB:
        _, __, traceb = sys.exc_info()
        traceback.print_exc()
        pdb.post_mortem(traceb)


def dive_counter(ff: pathlib.Path) -> tuple[int, int]:
    """Returns the dive and counter for a command file"""
    dive = None
    counter = None

    splits = str(ff.name).split(".")

    int_list: list[int] = []
    for ss in splits:
        with contextlib.suppress(ValueError):
            int_list.append(int(ss))

    # This is a capture - just mark as dive -1
    if len(int_list) == 0:
        return (-1, -1)
    dive = int_list[0]
    if len(int_list) > 1:
        counter = int_list[1]
    else:
        counter = 0

    return (dive, counter)


def cmp_function(a: pathlib.Path, b: pathlib.Path) -> Literal[-1, 0, 1]:
    """Compares two archived files, sorting in chronilogical order (most recent one first)"""
    a_dive, a_counter = dive_counter(a)
    b_dive, b_counter = dive_counter(b)

    if a_dive > b_dive:
        return 1
    elif a_dive < b_dive:
        return -1
    else:
        if a_counter > b_counter:
            return 1
        elif a_counter < b_counter:
            return -1
        else:
            return 0


def find_command_files(mission_dir: pathlib.Path, cmd_root: str) -> list[pathlib.Path]:
    command_files: list[pathlib.Path] = []
    for glob_expr in (
        f"{cmd_root}.[0-9]*",
        f"{cmd_root}.[0-9]*.[0-9]*",
    ):
        for match in mission_dir.glob(glob_expr):
            command_files.append(match)

    command_files_sorted = sorted(
        list(set(command_files)), key=functools.cmp_to_key(cmp_function)
    )
    return command_files_sorted


def extract_section(
    file_path: pathlib.Path,
    start_string: str,
    end_string: str,
    include_start_line=False,
    include_end_line=False,
    case_insensitive=False,
) -> str:
    extracted_lines = []
    reading_section = False

    if case_insensitive:
        start_string = start_string.lower()
        end_string = end_string.lower()

    try:
        with open(file_path, "rb") as file:
            for s in file:
                try:
                    line = s.decode("utf-8")
                except UnicodeDecodeError:
                    # print(f"Could not decode line {s} in {file_path} - skipping")
                    continue

                if case_insensitive:
                    line_match = line.lower()
                else:
                    line_match = line

                if end_string in line_match and reading_section:
                    reading_section = False
                    if include_end_line:
                        extracted_lines.append(line)
                    break

                if reading_section:
                    extracted_lines.append(line)

                if start_string in line_match:
                    reading_section = True
                    if include_start_line:
                        extracted_lines.append(line)

    except FileNotFoundError:
        return f"Error: The file '{file_path}' was not found."
    except Exception as e:
        return f"An error occurred: {e}"

    return "".join(extracted_lines)


def find_scicon_sch(filepath: pathlib.Path) -> str:
    return extract_section(filepath, ">scheme", ">sysclk")


def find_scicon_att(filepath: pathlib.Path) -> str:
    return extract_section(filepath, ">attach", ">scheme")


def find_scicon_ins(filepath: pathlib.Path) -> str:
    return extract_section(filepath, ">prop", ">attach")


def find_science(filepath: pathlib.Path) -> str:
    section_str = extract_section(
        filepath,
        "---- Reporting science specifications ----",
        "---- Reporting battery status ----",
    )
    if len(section_str):
        return section_str

    return extract_section(
        filepath,
        "Reporting targets and science specifications",
        "Reporting battery status",
    )


def find_active(
    dive_num: int, scicon_cfg: dict[pathlib.Path, dict]
) -> dict[str, dict[str, str]]:
    last_dict: dict[str, dict] = {}
    for k, v in scicon_cfg.items():
        if dive_counter(k)[0] + 1 > dive_num:
            break
        last_dict = v
    return last_dict


def convert_dict_to_float(data_dict):
    """
    Attempts to convert all keys and values in a dictionary to float.

    Non-convertible values are kept in their original format.

    Args:
        data_dict (dict): The input dictionary.

    Returns:
        dict: A new dictionary with values converted to float where possible.
    """
    converted_dict = {}
    for key, value in data_dict.items():
        try:
            converted_key = float(key)
        except (ValueError, TypeError):
            # If conversion fails (e.g., value is a non-numeric string or None),
            # keep the original value
            converted_key = key
        try:
            # Attempt to convert the value to a float
            converted_dict[converted_key] = float(value)
        except (ValueError, TypeError):
            # If conversion fails (e.g., value is a non-numeric string or None),
            # keep the original value
            converted_dict[key] = value
    return converted_dict


def setup_science_grid(base_opts) -> None:
    if hasattr(base_opts, "science_grid") and base_opts.science_grid is not None:
        return

    try:
        schemes: dict[pathlib.Path, dict] = {}
        science: dict[pathlib.Path, dict] = {}
        attach: dict[pathlib.Path, dict] = {}
        # ins: dict[pathlib.Path, dict] = {}

        # Captures
        captures = sorted(base_opts.mission_dir.glob("pt???????.cap"))
        if captures:
            # TODO - add code to catch the case of a CTD that is configured to migrate from scicon to truck
            # Note - this change may require the plotting code to specify if origin is the truck or the scicon
            science_body = find_science(captures[-1])

            with tempfile.NamedTemporaryFile(mode="w+t", delete=True) as temp_file:
                for ll in science_body.split("\n"):
                    if ll:
                        start_ii = ll.index(",N,")
                        science_line = ll[start_ii + 3 :]
                        # TODO - capture the loiter line
                        try:
                            float(science_line.split()[0])
                        except ValueError:
                            continue
                        temp_file.write(science_line)
                        temp_file.write("\n")
                temp_file.flush()

                temp_file.seek(0)

                science[captures[-1]] = asyncio.run(
                    Utils.readScienceFile(temp_file.name)
                )

            scicon_sch_body = find_scicon_sch(captures[-1])
            schemes[captures[-1]] = scicon.parseBody(
                scicon_sch_body.replace("\r", ""), uniq=False
            )

            scicon_att_body = find_scicon_att(captures[-1])
            attach[captures[-1]] = scicon.parseBody(
                scicon_att_body.replace("\r", ""), uniq=True
            )

            # scicon_ins_body = find_scicon_ins(captures[-1])
            # ins[captures[-1]] = scicon.parseBody(
            #     scicon_ins_body.replace("\r", ""), uniq=True
            # )

        # Scicon files
        scicon_sch_files = find_command_files(base_opts.mission_dir, "scicon.sch")

        for t in scicon_sch_files:
            with t.open() as fi:
                schemes[t] = scicon.parseBody(fi.read(), uniq=False)

        scicon_att_files = find_command_files(base_opts.mission_dir, "scicon.att")

        for t in scicon_att_files:
            with t.open() as fi:
                attach[t] = scicon.parseBody(fi.read(), uniq=True)

        # scicon_ins_files = find_command_files(base_opts.mission_dir, "scicon.ins")

        # for t in scicon_ins_files:
        #     with t.open() as fi:
        #         ins[t] = scicon.parseBody(fi.read(), uniq=True)

        # Read scicon files
        scheme_type = collections.namedtuple("scheme_type", ("origin_file", "schemes"))

        # TODO: Make sure to sort the dpeth values found in the schemes
        schemes_dict = collections.defaultdict(dict)
        for scicon_sch_file, scheme in schemes.items():
            # Dive number where the scheme applies is one after where it was recorded
            dive_num = dive_counter(scicon_sch_file)[0] + 1
            instr_dict = {}
            for instr_name, instr_schemes in scheme.items():
                # Map name
                attach_dict = find_active(dive_num, attach)
                if not attach_dict:
                    continue
                if instr_name not in attach_dict:
                    # No matching entry in attach, so instrument isn't going to sample
                    continue
                mapped_name = attach_dict[instr_name]["type"]
                # Run through extension remapper for instrument name - varioius flavors of legato
                # names is the classic test case
                instra_list = [mapped_name]
                Sensors.process_sensor_extensions("remap_instrument_names", instra_list)
                mapped_name = instra_list[0]

                all_profiles = None
                for instr_scheme in instr_schemes:
                    if "profile" not in instr_scheme:
                        all_profiles = instr_scheme

                full_instr_schemes: list[dict] = []
                for profile in ("a", "b", "c", "d"):
                    found_profile = False
                    for instr_scheme in instr_schemes:
                        for name, value in instr_scheme.items():
                            if "profile" in name and value == profile:
                                full_instr_schemes.append(
                                    convert_dict_to_float(instr_scheme)
                                )
                                found_profile = True
                    if not found_profile and all_profiles:
                        tmp_all_profile = copy.deepcopy(all_profiles)
                        tmp_all_profile["profile"] = profile
                        full_instr_schemes.append(
                            convert_dict_to_float(tmp_all_profile)
                        )

                instr_dict[mapped_name] = full_instr_schemes
            schemes_dict[dive_num] = scheme_type(scicon_sch_file.name, instr_dict)
        schemes_dict[10000] = scheme_type("", {})

        # Science files
        for science_file in find_command_files(base_opts.mission_dir, "science"):
            tmp_science_list = asyncio.run(Utils.readScienceFile(science_file))
            # This check is essentially for old column oriented (not supported) vs
            # new name/value paired files
            for science_item in tmp_science_list:
                if science_item.keys() >= {"name", "seconds", "sensors"}:
                    science[science_file] = tmp_science_list
                    break

        science_schemes_dict = collections.defaultdict(dict)

        # Derived from the capture file - assumed to no change during the mission
        raw_sensor_map: dict[str, str] = {}

        for science_file_name, science_dict in science.items():
            # Dive number where the science applies is one after where it was recorded
            dive_num = dive_counter(science_file_name)[0] + 1
            raw_sensor_names = []
            nc_file_name = None
            if dive_num == 0:
                sensor_lines = extract_section(
                    science_file_name,
                    "Reporting hardware configuration",
                    "Logger Sensor",
                    case_insensitive=True,
                )
                for sensor_line in sensor_lines.split("\n"):
                    ii = sensor_line.find(" is ")
                    if ii < 0:
                        # ignore it
                        continue
                    try:
                        raw_sensor_name = sensor_line[ii + 4 :].split()[0]
                    except Exception as e:
                        log_error(f"Failed to process {sensor_line} ({e})")
                        raw_sensor_name = "nil"

                    if raw_sensor_name == "not":
                        raw_sensor_name = "nil"

                    raw_sensor_names.append(raw_sensor_name)
                    if raw_sensor_name == "nil":
                        raw_sensor_map[raw_sensor_name] = raw_sensor_name
                    else:
                        # Find the mapping
                        sensor_config = extract_section(
                            science_file_name,
                            f"name={raw_sensor_name}",
                            "prefix",
                            include_end_line=True,
                        )
                        if len(sensor_config) == 0:
                            # No config found - this is the usual case for older capture files
                            # There is no definitive way to figure out the mapping
                            log_info(
                                f"Unable to find mapping/config for {raw_sensor_name} in {science_file_name} - will guess {raw_sensor_name.lower()}"
                            )
                            raw_sensor_map[raw_sensor_name] = raw_sensor_name.lower()
                        else:
                            try:
                                raw_sensor_map[raw_sensor_name] = (
                                    sensor_config.rstrip().split("=")[1]
                                )
                            except Exception as e:
                                DEBUG_PDB_F()
                                log_error(f"Could not process {sensor_config} ({e})")
                                raw_sensor_map[raw_sensor_name] = "nil"
                                continue
            else:
                try:
                    nc_file_name = (
                        base_opts.mission_dir
                        / f"p{base_opts.instrument_id:03d}{dive_num:04d}.nc"
                    )

                    dsi = Utils.open_netcdf_file(str(nc_file_name), "r")
                    sensors_line = (
                        dsi.variables["log_SENSORS"][:].tobytes().decode("utf-8")
                    )
                    dsi.close()
                except Exception as e:
                    log_error(
                        f"Could not open {nc_file_name} ({e}) - skipping {science_file} processing"
                    )
                    continue

                for sensor in sensors_line.split(",")[:6]:
                    raw_sensor_names.append(sensor)

            sensor_names = []
            for raw_sensor_name in raw_sensor_names:
                if raw_sensor_name not in raw_sensor_map:
                    sensor_names.append("nil")
                else:
                    # Map name from $SENSORS entries the "names" from the .cnf file to the "prefix" in the .dat/.asc/.eng files
                    mapped_name = raw_sensor_map[raw_sensor_name]
                    # Run through extension remapper for instrument name - varioius flavors of legato
                    # names is the classic test case
                    instra_list = [mapped_name]
                    Sensors.process_sensor_extensions(
                        "remap_instrument_names", instra_list
                    )
                    mapped_name = instra_list[0]
                    sensor_names.append(mapped_name)

            # log_info(f"{science_file_name}:{sensor_names}")

            science_schemes: dict[str, list] = {}
            all_profiles = ("a", "b", "c", "d")
            for sensor_name in sensor_names:
                if sensor_name == "nil":
                    continue
                science_schemes[sensor_name] = []
                for profile in all_profiles:
                    science_schemes[sensor_name].append({"profile": profile})

            for science_line in science_dict:
                try:
                    # TODO - need to propagate this to the loiter profile
                    if science_line["name"] == "loiter":
                        continue
                    depth = float(science_line["name"])
                    interval = float(science_line["seconds"])
                    sensors = [float(vv) for vv in science_line["sensors"]]
                except ValueError as e:
                    log_error(f"Could not convert {science_line} ({e})")
                    continue
                except KeyError as e:
                    log_error(f"{science_line} missing {e}")
                    continue
                # Note - there is no processing for profiles or dives tags as they deterine what dive or profile
                # is sampled, not what the sampling grid is
                for ii, sensor in enumerate(sensors):
                    sample_interval = sensor * interval
                    # TODO - write code protect against out of range access
                    sensor_name = sensor_names[ii]
                    if sensor_name == "nil":
                        continue

                    for ii in range(len(all_profiles)):
                        science_schemes[sensor_name][ii][depth] = sample_interval

            science_schemes_dict[dive_num] = scheme_type(
                science_file_name.name, science_schemes
            )

        # Temp return value
        science_schemes_dict[10000] = scheme_type("", {})

        # Update the base_opts object with the new map so its generated just once
        base_opts.science_grid = {
            "science": science_schemes_dict,
            "scicon": schemes_dict,
        }
    except Exception:
        DEBUG_PDB_F()
        log_error("Failed to setup the science grid", "exc")


instra_grid_tuple = collections.namedtuple(
    "instra_grid_tuple", ("dive", "filename", "grid")
)


def find_current_grid(base_opts, dive_num, profile, instrument_name):
    if not hasattr(base_opts, "science_grid") or base_opts.science_grid is None:
        return instra_grid_tuple(-1, "", {})

    try:
        # for grid_type, grid_dict in base_opts.science_grid.items():
        for _, grid_dict in base_opts.science_grid.items():
            # TODO - the type of lookup - science or scicon - should come in as an argument
            # log_info(f"grid_type:{grid_type}")
            dives = list(grid_dict.keys())

            active_dive_grid_num = None
            for ii in range(len(dives) - 1):
                if dives[ii] <= dive_num < dives[ii + 1]:
                    active_dive_grid_num = dives[ii]
                    break

            if active_dive_grid_num is None:
                continue

            file_name, instr_dict = grid_dict[active_dive_grid_num]
            if instrument_name in instr_dict:
                for scheme in instr_dict[instrument_name]:
                    if scheme["profile"] == profile:
                        return instra_grid_tuple(
                            active_dive_grid_num, file_name, scheme
                        )
    except Exception:
        log_error("Failed to find the current science grid", "exc")

    return instra_grid_tuple(-1, "", {})


def dump_grid(base_opts):
    if not hasattr(base_opts, "science_grid") or base_opts.science_grid is None:
        return

    for grid_type, grid_dict in base_opts.science_grid.items():
        log_info(f"grid_type:{grid_type}")

        for dd, vv in grid_dict.items():
            file_name, instr_dict = vv
            log_info(f"    dive:{dd}")
            log_info(f"    file:{file_name}")
            for instr, schemes in instr_dict.items():
                log_info(f"        instr:{instr}")
                for ss in schemes:
                    log_info(f"            {ss}")
