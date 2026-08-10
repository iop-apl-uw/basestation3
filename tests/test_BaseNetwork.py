# -*- python-fmt -*-

## Copyright (c) 2026  University of Washington.
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
import pathlib
import shutil
import sys

import numpy as np
import pytest
import testutils
import xarray as xr

import BaseNetwork
import BaseOpts

REAL_LOG_DECOMPRESSOR = pathlib.Path("/usr/local/bin/log")
REAL_PROFILE_DECOMPRESSOR = pathlib.Path("/usr/local/bin/x3decode_ts")


def _main_with_argv(cmd_line: list[str]) -> int:
    """Invokes BaseNetwork.main() the way the real CLI does - via sys.argv."""
    old_argv = sys.argv
    sys.argv = ["BaseNetwork.py", *cmd_line]
    try:
        return BaseNetwork.main()
    finally:
        sys.argv = old_argv


def _make_base_opts(**cmdline_overrides: str) -> BaseOpts.BaseOptions:
    args = []
    for k, v in cmdline_overrides.items():
        args.extend([f"--{k}", v])
    return BaseOpts.BaseOptions("", cmdline_args=args, calling_module="BaseNetwork")


# ---------------------------------------------------------------------------
# Tier 1 - pure unit tests, no I/O
# ---------------------------------------------------------------------------


def test_fix_ints():
    attrs = {"_FillValue": -999, "flag_values": [0, 1, 2], "comment": "hello"}
    result = BaseNetwork.fix_ints(np.int32, attrs)
    assert result["flag_values"] == [np.int32(0), np.int32(1), np.int32(2)]
    assert result["comment"] == "hello"


def test_create_ds_var_scalar():
    template = {
        "variables": {
            "dive_number": {
                "type": "i2",
                "attributes": {"_FillValue": -999, "comment": "test"},
            },
        }
    }
    dso = xr.Dataset()
    da = BaseNetwork.create_ds_var(dso, template, "dive_number", 5)
    assert da.item() == 5
    assert dso["dive_number"].item() == 5


def test_create_ds_var_array_with_dims():
    template = {
        "variables": {
            "depth": {
                "type": "f4",
                "num_digits": 2,
                "dimensions": ["depth_data_point"],
                "attributes": {"_FillValue": -999},
            },
        }
    }
    dso = xr.Dataset()
    da = BaseNetwork.create_ds_var(
        dso, template, "depth", np.array([1.234, 5.678], dtype=np.float64)
    )
    assert da.dims == ("depth_data_point",)
    np.testing.assert_allclose(da.values, [1.23, 5.68])


def test_create_ds_var_string():
    template = {
        "variables": {
            "name": {"type": "c"},
        }
    }
    dso = xr.Dataset()
    da = BaseNetwork.create_ds_var(dso, template, "name", "hello")
    assert bytes(da.values).decode().rstrip("\x00") == "hello"


def test_make_netcdf_network_files_groups_by_dive_number(monkeypatch, tmp_path):
    calls = []

    def fake_make_netcdf_network_file(
        network_logfile: pathlib.Path,
        network_profile: pathlib.Path,
        ts_outputfile: bool = False,
    ) -> pathlib.Path:
        calls.append((network_logfile, network_profile))
        return network_logfile.with_suffix(".ncdf")

    monkeypatch.setattr(
        BaseNetwork, "make_netcdf_network_file", fake_make_netcdf_network_file
    )

    network_files = [
        tmp_path / "p2720002.nlog",
        tmp_path / "p2720002.npro",
        tmp_path / "p2720003.nlog",
    ]
    processed: list[pathlib.Path] = []
    ret_val = BaseNetwork.make_netcdf_network_files(network_files, processed)
    assert ret_val == 0
    # One call per dive number (2 and 3), not per file
    assert len(calls) == 2
    assert len(processed) == 2


def test_make_netcdf_network_files_warns_on_unknown_suffix(
    monkeypatch, tmp_path, caplog
):
    monkeypatch.setattr(
        BaseNetwork, "make_netcdf_network_file", lambda *a, **k: None
    )
    bogus = tmp_path / "p2720002.txt"
    processed: list[pathlib.Path] = []
    with caplog.at_level(logging.WARNING):
        ret_val = BaseNetwork.make_netcdf_network_files([bogus], processed)
    assert ret_val == 0
    assert any("is not a network file" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tier 2 - guard-clause tests, no decompressor binary needed
# ---------------------------------------------------------------------------


def test_convert_network_logfile_missing_convertor(tmp_path, caplog):
    base_opts = _make_base_opts(network_log_decompressor=str(tmp_path / "nope"))
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"data")
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_logfile(base_opts, in_file, None)
    assert result is None
    assert any("does not exit" in r.message for r in caplog.records)


def test_convert_network_logfile_non_executable_convertor(tmp_path, caplog):
    convertor = tmp_path / "fake_log"
    convertor.write_text("#!/bin/sh\n")
    convertor.chmod(0o644)
    base_opts = _make_base_opts(network_log_decompressor=str(convertor))
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"data")
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_logfile(base_opts, in_file, None)
    assert result is None
    assert any("not marked as executable" in r.message for r in caplog.records)


def test_convert_network_logfile_missing_input(tmp_path, caplog):
    convertor = tmp_path / "fake_log"
    convertor.write_text("#!/bin/sh\ncat\n")
    convertor.chmod(0o755)
    base_opts = _make_base_opts(network_log_decompressor=str(convertor))
    missing = tmp_path / "does_not_exist.x"
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_logfile(base_opts, missing, None)
    assert result is None
    assert any("does not exist" in r.message for r in caplog.records)


def test_convert_network_profile_missing_convertor(tmp_path, caplog):
    base_opts = _make_base_opts(
        network_profile_decompressor=str(tmp_path / "nope")
    )
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"data")
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_profile(base_opts, in_file, None)
    assert result is None
    assert any("does not exit" in r.message for r in caplog.records)


def test_convert_network_profile_non_executable_convertor(tmp_path, caplog):
    convertor = tmp_path / "fake_profile"
    convertor.write_text("#!/bin/sh\n")
    convertor.chmod(0o644)
    base_opts = _make_base_opts(network_profile_decompressor=str(convertor))
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"data")
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_profile(base_opts, in_file, None)
    assert result is None
    assert any("not marked as executable" in r.message for r in caplog.records)


def test_convert_network_profile_missing_input(tmp_path, caplog):
    convertor = tmp_path / "fake_profile"
    convertor.write_text("#!/bin/sh\ncat\n")
    convertor.chmod(0o755)
    base_opts = _make_base_opts(network_profile_decompressor=str(convertor))
    missing = tmp_path / "does_not_exist.x"
    with caplog.at_level(logging.ERROR):
        result = BaseNetwork.convert_network_profile(base_opts, missing, None)
    assert result is None
    assert any("does not exists" in r.message for r in caplog.records)


# ---------------------------------------------------------------------------
# Tier 5 - fake shell-script decompressors, exercising the success path
# without the proprietary binaries
# ---------------------------------------------------------------------------


def test_convert_network_logfile_success_with_fake_decompressor(tmp_path):
    convertor = tmp_path / "fake_log"
    convertor.write_text('#!/bin/sh\ncat "$1"\n')
    convertor.chmod(0o755)
    base_opts = _make_base_opts(network_log_decompressor=str(convertor))
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"$ID,272\n$DIVE,2\n")
    out_file = tmp_path / "p2720002.nlog"
    result = BaseNetwork.convert_network_logfile(base_opts, in_file, out_file)
    assert result == out_file
    assert out_file.read_bytes() == b"$ID,272\n$DIVE,2\n"


def test_convert_network_profile_success_with_fake_decompressor(tmp_path):
    convertor = tmp_path / "fake_profile"
    convertor.write_text(
        "#!/bin/sh\n"
        "while [ $# -gt 0 ]; do\n"
        '  case "$1" in\n'
        '    -i) in_file="$2"; shift 2;;\n'
        '    -o) out_file="$2"; shift 2;;\n'
        "    *) shift;;\n"
        "  esac\n"
        "done\n"
        'cp "$in_file" "$out_file"\n'
    )
    convertor.chmod(0o755)
    base_opts = _make_base_opts(network_profile_decompressor=str(convertor))
    in_file = tmp_path / "p2720002.pro_raw"
    in_file.write_bytes(b"raw profile data")
    out_file = tmp_path / "p2720002.npro"
    result = BaseNetwork.convert_network_profile(base_opts, in_file, out_file)
    assert result == out_file
    assert out_file.read_bytes() == b"raw profile data"


# ---------------------------------------------------------------------------
# Tier 6 - skip-guarded real-binary tests (only run where the proprietary
# decompressors are actually installed)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not REAL_LOG_DECOMPRESSOR.is_file(),
    reason="requires proprietary log decompressor binary",
)
def test_convert_network_logfile_real_decompressor_smoke(tmp_path):
    base_opts = _make_base_opts()
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"")
    result = BaseNetwork.convert_network_logfile(base_opts, in_file, None)
    # Just confirm it runs to completion without raising - the binary's
    # actual behavior against a real compressed file isn't reproducible here.
    assert result is None or isinstance(result, pathlib.Path)


@pytest.mark.skipif(
    not REAL_PROFILE_DECOMPRESSOR.is_file(),
    reason="requires proprietary ct profile decompressor binary",
)
def test_convert_network_profile_real_decompressor_smoke(tmp_path):
    base_opts = _make_base_opts()
    in_file = tmp_path / "p2720002.x"
    in_file.write_bytes(b"")
    result = BaseNetwork.convert_network_profile(base_opts, in_file, None)
    assert result is None or isinstance(result, pathlib.Path)


# ---------------------------------------------------------------------------
# Tier 3 - integration tests reusing the existing per-dive netcdf fixture,
# no decompressor binary needed
# ---------------------------------------------------------------------------


def test_make_netcdf_network_file_from_perdive(tmp_path):
    src = pathlib.Path("testdata/sg272_NANOOS_Feb26_lowlevelcli/p2720002.nc")
    dst = tmp_path / "p2720002.nc"
    shutil.copy(src, dst)

    result = BaseNetwork.make_netcdf_network_file_from_perdive(dst)

    assert result == dst.with_suffix(".ncdf")
    assert result.exists()
    ds = xr.open_dataset(result)
    try:
        assert "depth" in ds.variables
        assert "temperature" in ds.variables
        assert "salinity" in ds.variables
        assert int(ds["dive_number"].item()) == 2
    finally:
        ds.close()


def test_ncf_subparser_end_to_end(caplog):
    data_dir = pathlib.Path("testdata/sg272_NANOOS_Feb26_lowlevelcli")
    mission_dir = data_dir / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        _main_with_argv,
        [
            "--verbose",
            "ncf",
            str(mission_dir / "p2720002.nc"),
        ],
        caplog,
        [""],
    )

    assert (mission_dir / "p2720002.ncdf").exists()


# ---------------------------------------------------------------------------
# Tier 4 - synthetic .nlog/.npro pair driving the "cdf" subparser end to
# end: this is the direct regression test for the reported crash
# (AttributeError: 'str' object has no attribute 'suffix').
# ---------------------------------------------------------------------------


def test_cdf_subparser_reproduces_and_fixes_crash(tmp_path, caplog):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    nlog_path = data_dir / "p2720002.nlog"
    nlog_path.write_text("$ID,272\n$DIVE,2\nstart:01 01 26 00 00 00\n")
    mission_dir = tmp_path / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        _main_with_argv,
        [
            "--verbose",
            "cdf",
            str(mission_dir / "p2720002.nlog"),
        ],
        caplog,
        [
            "not found - skipping",  # expected: no paired .npro file
            "Empty GC table - skipping",  # expected: no $GC lines in fixture
            "no depth",  # expected: BaseDB, minimal fixture has no depth data
            "gc time not in",  # expected: BaseDB, minimal fixture has no GC table
            "gps fixes not in",  # expected: BaseDB, minimal fixture has no GPS fixes
        ],
    )

    ncdf_file = mission_dir / "p2720002.ncdf"
    assert ncdf_file.exists()
    ds = xr.open_dataset(ncdf_file)
    try:
        assert int(ds["dive_number"].item()) == 2
    finally:
        ds.close()


def test_cdf_subparser_state_only_dive_no_gc_table(tmp_path, caplog):
    """Regression test for a `.nlog` with $STATE lines but zero $GC lines
    (e.g. a pressure-timeout/aborted dive) - previously crashed with
    `ValueError: ... array at index 0 has size 1 and the array at index 1
    has size 12` because `full_gc_table` was still `None` when the
    state-table loop ran its first `np.vstack`.
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    nlog_path = data_dir / "p2720002.nlog"
    nlog_path.write_text(
        "$ID,272\n"
        "$DIVE,2\n"
        "start:01 01 26 00 00 00\n"
        "$STATE,10.0,begin dive,CONTROL_FINISHED_OK\n"
        "$STATE,20.0,end dive,CONTROL_FINISHED_OK\n"
    )
    mission_dir = tmp_path / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        _main_with_argv,
        [
            "--verbose",
            "cdf",
            str(mission_dir / "p2720002.nlog"),
        ],
        caplog,
        [
            "not found - skipping",  # expected: no paired .npro file
            "no depth",  # expected: BaseDB, minimal fixture has no depth data
            "gps fixes not in",  # expected: BaseDB, minimal fixture has no GPS fixes
        ],
    )

    ncdf_file = mission_dir / "p2720002.ncdf"
    assert ncdf_file.exists()
    ds = xr.open_dataset(ncdf_file)
    try:
        assert int(ds["dive_number"].item()) == 2
        assert "log_GC" in ds.variables
        gc = ds["log_GC"].values
        assert gc.shape == (2, 12)
        # time (col 0) is populated; the 9 GC columns (1-9) are nan for a
        # state-only dive with no $GC lines.
        assert not np.any(np.isnan(gc[:, 0]))
        assert np.all(np.isnan(gc[:, 1:10]))
        # state (col 10) and eop_code (col 11) are populated, not nan.
        assert not np.any(np.isnan(gc[:, 10:12]))
    finally:
        ds.close()


def test_cdf_subparser_state_and_gc_table_merge(tmp_path, caplog):
    """A dive with both $GC and $STATE lines must merge both into log_GC -
    guards against a regression re-introducing the workaround that
    commented out the $STATE merge entirely (which silently dropped
    state/eop_code data even for normal dives that do have GC data).
    """
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    nlog_path = data_dir / "p2720002.nlog"
    nlog_path.write_text(
        "$ID,272\n"
        "$DIVE,2\n"
        "start:01 01 26 00 00 00\n"
        "$GC,5.0,1,2,3,4,5,6,7,8,9\n"
        "$STATE,10.0,begin dive,CONTROL_FINISHED_OK\n"
        "$STATE,20.0,end dive,CONTROL_FINISHED_OK\n"
    )
    mission_dir = tmp_path / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        _main_with_argv,
        [
            "--verbose",
            "cdf",
            str(mission_dir / "p2720002.nlog"),
        ],
        caplog,
        [
            "not found - skipping",  # expected: no paired .npro file
            "no depth",  # expected: BaseDB, minimal fixture has no depth data
            "gps fixes not in",  # expected: BaseDB, minimal fixture has no GPS fixes
        ],
    )

    ncdf_file = mission_dir / "p2720002.ncdf"
    assert ncdf_file.exists()
    ds = xr.open_dataset(ncdf_file)
    try:
        gc = ds["log_GC"].values
        # One GC row plus two STATE rows, sorted by time.
        assert gc.shape == (3, 12)
        # The single $GC row has real values in columns 1-9, and nan
        # state/eop_code columns.
        is_gc_row = ~np.isnan(gc[:, 1])
        assert is_gc_row.sum() == 1
        gc_row = gc[is_gc_row][0]
        assert not np.any(np.isnan(gc_row[1:10]))
        assert np.all(np.isnan(gc_row[10:12]))
        # The two $STATE rows have nan GC columns and populated
        # state/eop_code columns.
        state_rows = gc[~is_gc_row]
        assert state_rows.shape == (2, 12)
        assert np.all(np.isnan(state_rows[:, 1:10]))
        assert not np.any(np.isnan(state_rows[:, 10:12]))
    finally:
        ds.close()


def test_cdf_subparser_with_nlog_and_npro(tmp_path, caplog):
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    nlog_path = data_dir / "p2720002.nlog"
    nlog_path.write_text("$ID,272\n$DIVE,2\nstart:01 01 26 00 00 00\n")
    npro_path = data_dir / "p2720002.npro"
    npro_path.write_text(
        "%first_bin_depth:7.5\n%bin_width:5.0\n10.5 34.2\n10.3 34.1\n"
    )
    mission_dir = tmp_path / "mission_dir"

    testutils.run_mission(
        data_dir,
        mission_dir,
        _main_with_argv,
        [
            "--verbose",
            "cdf",
            str(mission_dir / "p2720002.nlog"),
            str(mission_dir / "p2720002.npro"),
        ],
        caplog,
        [""],
    )

    ncdf_file = mission_dir / "p2720002.ncdf"
    assert ncdf_file.exists()
    ds = xr.open_dataset(ncdf_file)
    try:
        assert "temperature" in ds.variables
        assert "salinity" in ds.variables
        assert "depth" in ds.variables
    finally:
        ds.close()
