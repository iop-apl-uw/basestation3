# -*- python-fmt -*-

## Copyright (c) 2024, 2025, 2026  University of Washington.
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

import logging
import os
import pathlib
import types
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest
import testutils

import Base

test_cases = (
    (
        "testdata/sg179_Guam_Oct19_noct",
        "sg179",
        "",
        (
            "Found Disconnect with no previous Connected",
            "No CT data found",
            "Failed to create profiles for",
            "is marked as having a processing error",
            "Profiles for dive [100] had problems during processing.",
            "Could not load variables ctd_time or ctd_depth",
            "mpath failed - skipping mission map",
            "No call data found in database - skipping eng_mission_commlog",
            "Unable to load 'ctd_time' - skipping plot_CTW",
            "Could not load 'ctd_depth'",
            "Could not fetch needed variables 'depth'",
            "skipping bathy in plots",
            "Not all needed vars available for buoy freq",
            "Could not find a dive number in the comm.log - using alert_message.html for alerts",
        ),
    ),
    (
        "testdata/sg179_Guam_Oct19",
        "sg179",
        "--plot_types none --make_mission_timeseries --make_mission_profile",
        (
            "Found Disconnect with no previous Connected:",
            "timeout(s) seen for compass",
            "CTD out of the water after",
            "Large mis-match between predicted and observed w",
            "Compass invalid out for",
            "is marked as having a processing error",
            "Could not find a dive number in the comm.log - using alert_message.html for alerts",
        ),
    ),
    (
        "testdata/sg178_Guam_Oct19",
        "sg178",
        "--plot_types none",
        (
            "timeout(s) seen in",
            "CTD out of the water after",
            "Large mis-match between predicted and observed w",
            "ALERT:TIMEOUT",
        ),
    ),
    (
        "testdata/sg677_GoMex_2022_M1_Legato",
        "sg677",
        "",
        (
            "Found Disconnect with no previous Connected:",
            "Found Connected with no previous Disconnect:",
            "No handler found for columns",
            "Restarting anomaly after",
            "Large unexplained positive conductivity",
            "No call data found in database",
            "skipping bathy in plots",
        ),
    ),
    (
        "testdata/sg263_NANOOS_Mar25_missingupload",
        "sg263",
        "",
        (
            "CRC check failed on",
            "Incorrect length of data produced from ",
            "Problem gzip decompressing",
            "Problems extracting contents of",
            "Could not process sc1051bg",
            "No call data found in database - skipping eng_mission_commlog",
            "Dive [1051] failed to process completely.",
            "Problems extracting sc1051b/wl.dat (unexpected end of data)",
            "Problems extracting sc1051b/optode.dat (unexpected end of data)",
            "Problems extracting sc1051b/depth.dat (unexpected end of data)",
            "1 timeout(s) seen for rbr in /Users/gbs/work/git/basestation3/testdata/sg265_NANOOS_Mar25_missingupload/sg1051du.r",
            "No dives to process",
            "CTD out of the water after climb (0.040m)",
            "Large mis-match between predicted and observed w; significant up/downwelling or poor flight model. DAC suspect.",
            "Displacements under-estimate likely positions by 10.2%; DAC suspect",
            "skipping bathy in plots",
            "skipping mission map",
            "ALERT:TIMEOUT",
            "1 timeout(s) seen for rbr ",
        ),
    ),
)

test_inputs = []

for test_data_dir, glider, additional_args, allowed_msgs in test_cases:
    test_inputs.append(
        (
            test_data_dir,
            # {mission_dir} is filled in per test (a tmp_path, so parallel runs don't collide)
            f"--verbose --local --plot_types none --no-notify_vis {additional_args} --mission_dir {{mission_dir}} --config {{mission_dir}}/{glider}.conf".split(),
            allowed_msgs,
        )
    )


@pytest.mark.parametrize("test_data_dir,cmd_line,allowed_msgs", test_inputs)
def test_conversion(tmp_path, caplog, test_data_dir, cmd_line, allowed_msgs):
    data_dir = pathlib.Path(test_data_dir)
    mission_dir = tmp_path / "mission_dir"
    cmd_line = [arg.replace("{mission_dir}", str(mission_dir)) for arg in cmd_line]

    testutils.run_mission(
        data_dir, mission_dir, Base.main, cmd_line, caplog, allowed_msgs
    )


reprocess_test_cases = (
    ("", ["Dives to process = []"], [""]),
    ("--force", ["Processed dive(s) [2]"], [""]),
    ("2", ["Processed dive(s) [2]"], [""]),
)


@pytest.mark.parametrize(
    "additional_options,required_msgs,allowed_msgs",
    reprocess_test_cases,
)
def test_reprocess(tmp_path, caplog, additional_options, required_msgs, allowed_msgs):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_base")
    mission_dir = tmp_path / "mission_dir"

    def update_timestamps(mission_dir: pathlib.Path) -> None:
        for p in mission_dir.iterdir():
            new_time = datetime(2026, 5, 10, 0, 0, 0).timestamp()
            if p.is_dir():
                continue
            os.utime(p, (new_time, new_time))

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose --local --no-notify_vis --plot_types none --skip_flight_model --mission_dir {mission_dir} {additional_options}".split(),
        caplog,
        allowed_msgs,
        required_msgs=required_msgs,
        pre_test_hook=update_timestamps,
    )


def test_skip_files(tmp_path, caplog):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal")
    mission_dir = tmp_path / "mission_dir"

    def create_skip_file(mission_dir: pathlib.Path) -> None:
        skip_file_name = mission_dir / "files_to_skip.txt"
        files_to_skip = ["sg0002dz", "sg0002lz", "sc0002ag", "sc0002bg"]
        with open(skip_file_name, "w") as skip_file:
            for file_to_skip in files_to_skip:
                skip_file.write(f"{file_to_skip}\n")

    allowed_msgs = [""]
    required_msgs = ["Dives to process = []"]
    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose  --local --no-notify_vis --skip_flight_model --plot_types none --ignore_flight_model --mission_dir {mission_dir}".split(),
        caplog,
        allowed_msgs,
        pre_test_hook=create_skip_file,
        required_msgs=required_msgs,
    )


def test_eng_precision(tmp_path, caplog):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_base")
    mission_dir = tmp_path / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose --local --no-notify_vis --plot_types none --skip_flight_model --force --mission_dir {mission_dir}".split(),
        caplog,
        [""],
    )
    # Check that legato has 3 decimal places of precision
    with open(mission_dir / "sc0002a" / "psc2720002a_legatoPoll_ct.eng") as fi:
        for line in fi.readlines():
            if line.startswith("%"):
                continue
            assert all(
                [Decimal(vv.strip()).as_tuple().exponent == -3 for vv in line.split()]
            )
            break

    # Check that the backscatter channes have 5 decimal places of precision
    with open(
        mission_dir / "sc0002a" / "psc2720002a_tridentebb700bb470chla470_tridente.eng"
    ) as fi:
        for line in fi.readlines():
            if line.startswith("%"):
                continue

            exponents = [-3, -5, -5, -3]
            assert all(
                [
                    Decimal(vv.strip()).as_tuple().exponent == exponents[ii]
                    for ii, vv in enumerate(line.split())
                ]
            )
            break


def test_process_file_group_network_logfile_casts_str_to_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Regression test for a production crash: a network-logfile fragment
    that never goes through the tar/gzip/bzip branches produces a plain str
    in_file_name (from the string-concatenated defrag_file_name) -
    process_file_group must cast it to a pathlib.Path before calling
    BaseNetwork.convert_network_logfile, which requires one
    (AttributeError: 'str' object has no attribute 'is_file' otherwise).

    Also covers a second, related bug: convert_network_logfile's return
    value (None on failure - missing decompressor, missing input, etc.)
    must gate whether the expected output filename is added to
    processed_other_files - a downstream consumer (e.g.
    MakePlotTSProfile.py) that tries to open a name that was never
    actually created crashes with FileNotFoundError (production case:
    iopbase3, sg244 dive 835)."""
    Base.set_globals()
    fragment = tmp_path / "sg0000en.x"
    data = b"dummy network logfile bytes"
    fragment.write_bytes(data)

    comm_log = MagicMock()
    comm_log.find_fragment_transfer_method.return_value = "raw"

    convert_mock = MagicMock(return_value=None)
    monkeypatch.setattr(Base.BaseNetwork, "convert_network_logfile", convert_mock)

    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    base_opts.run_bogue = False

    fragment_size_dict = {
        "sg0000en.x": Base.CommLog.file_expected_actual_nt(len(data), len(data))
    }

    ret_val = Base.process_file_group(
        base_opts,
        [str(fragment)],
        fragment_size_dict,
        {},
        179,
        comm_log,
        [],
    )

    assert ret_val == 0
    convert_mock.assert_called_once()
    called_in_file_name = convert_mock.call_args.args[1]
    assert isinstance(called_in_file_name, pathlib.Path)
    assert Base.processed_other_files == []


def test_process_file_group_network_profile_casts_str_to_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """Same regressions as above, for convert_network_profile - the sibling
    call site with the identical latent bugs."""
    Base.set_globals()
    fragment = tmp_path / "sg0000rn.x"
    data = b"dummy network profile bytes"
    fragment.write_bytes(data)

    comm_log = MagicMock()
    comm_log.find_fragment_transfer_method.return_value = "raw"

    convert_mock = MagicMock(return_value=None)
    monkeypatch.setattr(Base.BaseNetwork, "convert_network_profile", convert_mock)

    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    base_opts.run_bogue = False

    fragment_size_dict = {
        "sg0000rn.x": Base.CommLog.file_expected_actual_nt(len(data), len(data))
    }

    ret_val = Base.process_file_group(
        base_opts,
        [str(fragment)],
        fragment_size_dict,
        {},
        179,
        comm_log,
        [],
    )

    assert ret_val == 0
    convert_mock.assert_called_once()
    called_in_file_name = convert_mock.call_args.args[1]
    assert isinstance(called_in_file_name, pathlib.Path)
    assert Base.processed_other_files == []


def test_process_file_group_network_profile_appends_on_success(
    monkeypatch: pytest.MonkeyPatch, tmp_path: pathlib.Path
) -> None:
    """When convert_network_profile succeeds (returns the created files -
    e.g. .npro_ct.dat and .npro_wl.dat for a new-style profile), those
    files - and only those - must land in processed_other_files."""
    Base.set_globals()
    fragment = tmp_path / "sg0000rn.x"
    data = b"dummy network profile bytes"
    fragment.write_bytes(data)

    comm_log = MagicMock()
    comm_log.find_fragment_transfer_method.return_value = "raw"

    converted_paths = [tmp_path / "p0000000.npro_ct.dat", tmp_path / "p0000000.npro_wl.dat"]
    convert_mock = MagicMock(return_value=converted_paths)
    monkeypatch.setattr(Base.BaseNetwork, "convert_network_profile", convert_mock)

    base_opts = MagicMock()
    base_opts.mission_dir = tmp_path
    base_opts.run_bogue = False

    fragment_size_dict = {
        "sg0000rn.x": Base.CommLog.file_expected_actual_nt(len(data), len(data))
    }

    ret_val = Base.process_file_group(
        base_opts,
        [str(fragment)],
        fragment_size_dict,
        {},
        179,
        comm_log,
        [],
    )

    assert ret_val == 0
    assert Base.processed_other_files == converted_paths


def test_unreadable_history_log(tmp_path, caplog):
    """history.log there but unreadable: logged, no merge (merge_lists_with_ts used to get None and raise)."""
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_magcal")
    mission_dir = tmp_path / "mission_dir"

    def unreadable_history(mission_dir: pathlib.Path) -> None:
        (mission_dir / "files_to_skip.txt").write_text("sg0002dz\nsg0002lz\nsc0002ag\nsc0002bg\n")
        history = mission_dir / "history.log"
        history.write_text("")
        history.chmod(0)

    testutils.run_mission(
        data_dir,
        mission_dir,
        Base.main,
        f"--verbose  --local --no-notify_vis --skip_flight_model --plot_types none --ignore_flight_model --mission_dir {mission_dir}".split(),
        caplog,
        ["Could not open", "No dives to process"],
        pre_test_hook=unreadable_history,
        required_msgs=["history.log for reading"],
    )


def test_check_file_fragments(tmp_path):
    """Full fragments then a shorter last one are fine; a short fragment before the last isn't."""
    import CommLog

    def fragments(sizes):
        names = []
        for n, size in enumerate(sizes):
            f = tmp_path / f"sg0042dz.x0{n}"
            f.write_bytes(b"\0" * size)
            names.append(str(f))
        return names, {pathlib.Path(f).name: CommLog.file_expected_actual_nt(8192, -1) for f in names}

    good, sizes = fragments((8192, 8192, 100))
    assert Base.check_file_fragments(str(tmp_path / "sg0042dz.r"), good, sizes, 686)
    short, sizes = fragments((8192, 4000, 100))
    assert not Base.check_file_fragments(str(tmp_path / "sg0042dz.r"), short, sizes, 686)


def test_expunge_secrets_unwritable(tmp_path):
    """A log with secrets that can't be rewritten: 1 and an error (its Path name used to raise TypeError)."""
    log = tmp_path / "p6860042.log"
    log.write_text("version: 67.01\ndata:\n$ID,686\n$PASSWD,secret\n")
    log.chmod(0o444)  # readable, not writable
    assert Base.expunge_secrets(log) == 1


def test_process_progress_unknown_section(tmp_path, caplog):
    opts = types.SimpleNamespace(instrument_id=686, job_id=None, mission_dir=tmp_path)
    progress = Base.ProcessProgress(opts)
    with caplog.at_level(logging.WARNING):
        progress.process_progress("no_such_section", "start")
    assert "Unknown section name no_such_section" in caplog.text
