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

import pytest
import yaml
from pydantic import BaseModel, ConfigDict, ValidationError

import YamlValidation


def _write(tmp_path: pathlib.Path, text: str) -> pathlib.Path:
    f = tmp_path / "x.yml"
    f.write_text(text)
    return f


def test_locate_block_and_flow_style(tmp_path: pathlib.Path) -> None:
    f = _write(
        tmp_path,
        "geoff:\n  email:\n    - {address: a@b.c, filters: [gps, latepgs]}\n    - address: d@e.f\ngps: [geoff]\n",
    )
    data, locate = YamlValidation.load_yaml_with_lines(f)
    assert data["gps"] == ["geoff"]
    assert locate(("geoff",)) == 1
    assert locate(("geoff", "email", 0, "filters", 1)) == 3  # flow style: same line
    assert locate(("geoff", "email", 1, "address")) == 4
    assert locate(("gps", 0)) == 5
    # Unknown tail: the longest known prefix
    assert locate(("geoff", "email", 1, "no_such_field")) == 4


def test_syntax_error_has_file_and_line(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "a: 1\nb: [1, 2\nc: 3\n")
    with pytest.raises(yaml.YAMLError) as excinfo:
        YamlValidation.load_yaml_with_lines(f)
    msg = YamlValidation.format_yaml_error(f, excinfo.value)
    assert msg.startswith(f"{f}:")
    assert int(msg.split(":")[1]) >= 2


class _Thing(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str
    secret: str


def test_validation_errors_have_line_and_are_redacted(tmp_path: pathlib.Path) -> None:
    f = _write(tmp_path, "things:\n  - name: ok\n    secret: s3cret\n    colour: red\n")
    data, locate = YamlValidation.load_yaml_with_lines(f)
    with pytest.raises(ValidationError) as excinfo:
        _Thing(**data["things"][0])
    msgs = YamlValidation.format_validation_errors(
        f, locate, excinfo.value, prefix=("things", 0), redact=lambda loc, v: "****" if loc[-1] == "secret" else v
    )
    assert msgs == [f"{f}:4: things.0.colour: Extra inputs are not permitted (input: 'red')"]
