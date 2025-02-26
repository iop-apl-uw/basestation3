# -*- python-fmt -*-

## Copyright (c) 2025  University of Washington.
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

import pytest

import Utils


@pytest.mark.parametrize("test_timeout", (10, None))
def test_run_cmd_shell(caplog, test_timeout):
    ret_code, fo = Utils.run_cmd_shell(
        "tests/echo_err.sh", timeout=test_timeout, shell=True
    )
    # Check for known WARNING, ERROR or CRITICAL msgs
    bad_errors = ""
    for record in caplog.records:
        if record.levelname in ["CRITICAL", "ERROR", "WARNING"]:
            bad_errors += f"{record.levelname}:{record.getMessage()}\n"
    if bad_errors:
        pytest.fail(bad_errors)

    assert ret_code is not None
    assert fo is not None

    # No good way to verify output - even with sorting, due to the binary output and
    # buffer sizes, some of the lines are partial.
    # l_lines = fo.readlines()
    # for ii, l_line in enumerate(sorted(l_lines,key=lambda x: int(x.decode.split("")[0]))):
    #    tag = "stderr" if ii % 2 else "stdout"
    #    assert l_line == f"{ii} {tag}\n".encode()


def test_run_cmd_shell_timeout(caplog):
    ret_code, fo = Utils.run_cmd_shell("tests/loop_infinite.sh", timeout=2, shell=True)

    # Check for known WARNING, ERROR or CRITICAL msgs
    # Timeout message expected
    allowed_msgs = ["Timeout running"]
    bad_errors = ""
    for record in caplog.records:
        for msg in allowed_msgs:
            if msg in record.msg:
                break
        else:
            if record.levelname in ["CRITICAL", "ERROR", "WARNING"]:
                bad_errors += f"{record.levelname}:{record.getMessage()}\n"
    if bad_errors:
        pytest.fail(bad_errors)

    assert ret_code is None
    assert fo is None
