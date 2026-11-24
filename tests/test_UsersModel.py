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

"""users.yml checker: warnings at file:line (it only reports), no password hash in any output, the CLI."""

import logging
from collections.abc import Iterator
from pathlib import Path

import pytest
import yaml
from passlib.hash import sha256_crypt  # ty: ignore[import-not-found] - passlib.hash builds its members lazily

import Base  # noqa: F401 - normal import order
import BaseLog
import MissionsModel
import UsersModel

HASH = sha256_crypt.using(rounds=1000).hash("not-a-real-password")

CLEAN = f"""\
alice:
  groups: [pilots, uw]
  password: "{HASH}"
bob:
  groups: [uw]
"""


@pytest.fixture(autouse=True)
def _fresh_baselog() -> Iterator[None]:
    BaseLog.BaseLogger.reset()
    yield
    BaseLog.BaseLogger.reset()


def _write(tmp_path: Path, text: str, name: str = "users.yml") -> Path:
    p = tmp_path / name
    p.write_text(text)
    return p


def test_clean_file(tmp_path: Path) -> None:
    data, warnings, problems = UsersModel.check_file(_write(tmp_path, CLEAN))
    assert (warnings, problems) == ([], []) and data is not None
    assert data["alice"]["groups"] == ["pilots", "uw"]


@pytest.mark.parametrize(
    ("text", "line", "message"),
    [
        (
            "bob:\n",
            1,
            "bob: should be a mapping (groups:, password:), not NoneType - vis fails to start",
        ),
        (
            "bob:\n  groups: pilots\n",
            2,
            "bob.groups: should be a list (e.g. groups: [pilots]) - as text, each character",
        ),
        ("bob:\n  groups: 3\n", 2, "bob.groups: should be a list of groups, not int"),
        (
            "bob:\n  groups:\n    - uw\n    - 7\n",
            4,
            "bob.groups.1: should be a group name, not int",
        ),
        (
            "bob:\n  password: hunter2\n",
            2,
            "bob.password: isn't a sha256_crypt hash ($5$...) - login fails",
        ),
        ("bob:\n  password: 12345\n", 2, "bob.password: isn't a sha256_crypt hash"),
        (
            "bob:\n  grups: [uw]\n",
            2,
            "bob.grups: not a user key - ignored (known: groups, password)",
        ),
        (
            "1234:\n  groups: [uw]\n",
            1,
            "1234: user name should be text, not int - every login fails (quote it)",
        ),
        (
            "Bob:\n  groups: [uw]\nbob:\n  groups: [uw]\n",
            3,
            "bob: same name as 'Bob' but for case",
        ),
    ],
    ids=[
        "not_mapping",
        "groups_text",
        "groups_int",
        "group_int",
        "plain_password",
        "int_password",
        "unknown_key",
        "int_name",
        "case_twin",
    ],
)
def test_warnings(tmp_path: Path, text: str, line: int, message: str) -> None:
    path = _write(tmp_path, text)
    data, warnings, problems = UsersModel.check_file(path)
    assert data is not None and problems == []
    assert any(w.startswith(f"{path}:{line}: {message}") for w in warnings), warnings


def test_no_groups_is_fine(tmp_path: Path) -> None:
    """A user without groups (a shared account given access by name) and a default: entry are fine."""
    path = _write(
        tmp_path,
        f'default:\n  groups: [guest]\nshared:\n  password: "{HASH}"\nbob:\n  password: x\n',
    )
    _, warnings, _ = UsersModel.check_file(path)
    assert len(warnings) == 1 and "bob.password" in warnings[0]


def test_no_password_in_messages(tmp_path: Path) -> None:
    """A bad password is reported without its value (it may be a real password typed in)."""
    _, warnings, _ = UsersModel.check_file(
        _write(tmp_path, "bob:\n  groups: [uw]\n  password: hunter2\n")
    )
    assert warnings and not any("hunter2" in w for w in warnings)


def test_unusable(tmp_path: Path) -> None:
    for text, got in (("", "an empty file"), ("- bob\n", "list")):
        path = _write(tmp_path, text)
        assert UsersModel.check_file(path) == (
            None,
            [],
            [
                f"{path}: users.yml must be a mapping of user names (got {got}) - vis fails to start"
            ],
        )
    syntax = _write(tmp_path, "bob:\n  groups: [uw\n")
    assert UsersModel.check_file(syntax)[2][0].startswith(f"{syntax}:")
    assert "could not read" in UsersModel.check_file(tmp_path / "missing.yml")[2][0]


def test_cli(
    tmp_path: Path, caplog: pytest.LogCaptureFixture, capsys: pytest.CaptureFixture[str]
) -> None:
    clean = _write(tmp_path, CLEAN)
    with caplog.at_level(logging.INFO):
        assert UsersModel.main(["--verbose", "check", str(clean)]) == 0
    assert f"{clean}: OK" in caplog.text
    capsys.readouterr()
    assert UsersModel.main(["dump", str(clean)]) == 0
    out = capsys.readouterr().out
    assert HASH not in out and "$5$" not in out
    assert yaml.safe_load(out)["alice"] == {
        "groups": ["pilots", "uw"],
        "password": "<set>",
    }
    bad = _write(tmp_path, "bob:\n  groups: pilots\n", "bad.yml")
    with caplog.at_level(logging.WARNING):
        assert UsersModel.main(["check", str(bad)]) == 1
    assert "should be a list" in caplog.text
    broken = _write(tmp_path, "- a\n", "broken.yml")
    assert UsersModel.main(["check", str(broken)]) == 1
    assert UsersModel.main(["dump", str(broken)]) == 1


def test_missions_follows_domain_users(tmp_path: Path) -> None:
    """MissionsModel check follows a domain's users: file (path_map for server paths); --no-follow doesn't."""
    mirror = tmp_path / "mirror"
    (mirror / "a").mkdir(parents=True)
    _write(mirror / "a", "missions:\n  - { glider: 1 }\n", "missions.yml")
    users = _write(mirror / "a", "bob:\n  groups: pilots\n")
    master = _write(
        tmp_path,
        "domains:\n  a: { missions: /home/jails/a/missions.yml, users: /home/jails/a/users.yml }\n"
        "  b: { missions: /home/jails/a/missions.yml, users: /home/jails/b/users.yml }\n",
        "missions.yml",
    )
    _, warnings, _ = MissionsModel.check_file(master, {"/home/jails": str(mirror)})
    text = "\n".join(warnings)
    assert f"{users}:2: bob.groups: should be a list" in text
    assert (
        f"{mirror / 'b' / 'users.yml'} not found - not checked (vis: no users for b)"
        in text
    )
    assert (
        MissionsModel.check_file(master, {"/home/jails": str(mirror)}, follow=False)[1]
        == []
    )
    _write(mirror / "a", "- bob\n")
    assert (
        "users.yml must be a mapping"
        in MissionsModel.check_file(master, {"/home/jails": str(mirror)})[2][0]
    )
