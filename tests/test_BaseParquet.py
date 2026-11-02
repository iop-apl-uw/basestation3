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


import pathlib
import shutil
import types
from unittest.mock import patch

import BaseParquet
import Utils

NC = pathlib.Path("testdata/sg236_NANOOS_May23_netcdfs/p2360001.nc")


def _opts() -> types.SimpleNamespace:
    return types.SimpleNamespace(dump_whole_mission_config=False, whole_mission_config=None)


def test_write_parquet_files_merge_failure_returns_failure() -> None:
    """A config merge failure returns (1, []) - it returned None, and every caller unpacks two values."""
    with patch.object(BaseParquet, "reduce", side_effect=ValueError("bad template")):
        assert BaseParquet.write_parquet_files([NC], _opts()) == (1, [])


def test_write_parquet_file_closes_the_netcdf_file(tmp_path) -> None:
    nc = tmp_path / NC.name
    shutil.copy(NC, nc)
    opened = []
    real_open = Utils.open_netcdf_file

    def open_netcdf_file(*args, **kwargs):
        opened.append(real_open(*args, **kwargs))
        return opened[-1]

    with patch.object(BaseParquet.Utils, "open_netcdf_file", open_netcdf_file):
        ret_val, out_files = BaseParquet.write_parquet_file(nc, _opts(), {})
    assert ret_val == 0
    assert out_files and all(f.parent == tmp_path / "parquet" for f in out_files)
    assert not opened[0].isopen()
