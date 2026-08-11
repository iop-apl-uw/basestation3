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

import dataclasses
import pathlib
import pwd

import pytest

import SiteConfig

GOOD_YAML = """
seaglider:
  watch_dir: {seaglider_dir}
  jail_root: {seaglider_dir}/jail
  runner_user: ioprunner
ioptest:
  watch_dir: {ioptest_dir}
  runner_user: runner-ioptest
  archive: true
"""


def _fake_pwent(uid: int, gid: int) -> pwd.struct_passwd:
    return pwd.struct_passwd(
        ("ioprunner", "x", uid, gid, "", "/nonexistent", "/usr/sbin/nologin")
    )


@pytest.fixture
def patch_lookup_user(monkeypatch):
    """Maps a fixed set of account names to fixed uid/gid pairs."""
    known = {
        "ioprunner": (5001, 6001),
        "runner-ioptest": (5002, 6002),
    }

    def _lookup(name: str) -> pwd.struct_passwd:
        try:
            uid, gid = known[name]
        except KeyError:
            raise KeyError(name) from None
        return _fake_pwent(uid, gid)

    monkeypatch.setattr(SiteConfig, "lookup_user", _lookup)
    return known


def test_load_sites_config_valid(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider" / "rundir"
    seaglider_dir.mkdir(parents=True)
    ioptest_dir = tmp_path / "ioptest" / "rundir"
    ioptest_dir.mkdir(parents=True)

    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        GOOD_YAML.format(seaglider_dir=seaglider_dir, ioptest_dir=ioptest_dir)
    )

    sites = SiteConfig.load_sites_config(config_path)

    assert sites is not None
    assert set(sites) == {"seaglider", "ioptest"}

    seaglider = sites["seaglider"]
    assert seaglider.name == "seaglider"
    assert seaglider.watch_dir == seaglider_dir.resolve()
    assert seaglider.jail_root == (seaglider_dir / "jail").resolve()
    assert seaglider.runner_user == "ioprunner"
    assert seaglider.archive is False
    assert seaglider.runner_uid == 5001
    assert seaglider.runner_gid == 6001
    assert seaglider.mission_dir == seaglider.watch_dir
    assert seaglider.python_version == "/opt/basestation/bin/python"
    assert seaglider.queue_scripts is True
    assert seaglider.docker_uid == -1
    assert seaglider.cpu_quota_pct is None
    assert seaglider.cpu_weight is None

    ioptest = sites["ioptest"]
    assert ioptest.archive is True
    assert ioptest.jail_root is None
    assert ioptest.runner_uid == 5002
    assert ioptest.runner_gid == 6002


def test_site_config_is_frozen(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: ioprunner\n")

    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None

    with pytest.raises(dataclasses.FrozenInstanceError):
        sites["seaglider"].name = "not-seaglider"  # ty: ignore[invalid-assignment]


def test_load_sites_config_missing_file(tmp_path, caplog):
    missing = tmp_path / "does-not-exist.yaml"
    assert SiteConfig.load_sites_config(missing) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_empty_file(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_not_a_mapping(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("- just\n- a\n- list\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_entry_not_a_mapping(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    config_path.write_text("seaglider: just-a-string\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_missing_required_key(tmp_path, caplog):
    config_path = tmp_path / "sites.yaml"
    # Missing watch_dir
    config_path.write_text("seaglider:\n  runner_user: ioprunner\n")
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_bad_scalar_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  docker_uid: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_cpu_fields_present(tmp_path, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_quota_pct: 60\n"
        f"  cpu_weight: 50\n"
    )
    sites = SiteConfig.load_sites_config(config_path)
    assert sites is not None
    assert sites["seaglider"].cpu_quota_pct == 60
    assert sites["seaglider"].cpu_weight == 50


def test_load_sites_config_bad_cpu_quota_pct_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_quota_pct: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_bad_cpu_weight_value(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n"
        f"  watch_dir: {seaglider_dir}\n"
        f"  runner_user: ioprunner\n"
        f"  cpu_weight: not-an-int\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_unknown_runner_user(tmp_path, caplog, patch_lookup_user):
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: runner-does-not-exist\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None
    assert any(r.levelname == "ERROR" for r in caplog.records)


def test_load_sites_config_one_bad_entry_fails_whole_file(
    tmp_path, caplog, patch_lookup_user
):
    """A single malformed site must abort the whole load, not just skip it."""
    seaglider_dir = tmp_path / "seaglider"
    seaglider_dir.mkdir()
    config_path = tmp_path / "sites.yaml"
    config_path.write_text(
        f"seaglider:\n  watch_dir: {seaglider_dir}\n  runner_user: ioprunner\n"
        f"broken:\n  runner_user: ioprunner\n"
    )
    assert SiteConfig.load_sites_config(config_path) is None


def test_lookup_user_delegates_to_pwd(monkeypatch):
    sentinel = _fake_pwent(1234, 5678)

    def _fake_getpwnam(name: str) -> pwd.struct_passwd:
        assert name == "someone"
        return sentinel

    monkeypatch.setattr(pwd, "getpwnam", _fake_getpwnam)
    assert SiteConfig.lookup_user("someone") == sentinel


def test_resolve_ids_success(monkeypatch):
    monkeypatch.setattr(
        SiteConfig, "lookup_user", lambda name: _fake_pwent(42, 43)
    )
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=pathlib.Path("/tmp/seaglider"),
        jail_root=None,
        runner_user="ioprunner",
    )
    assert SiteConfig.resolve_ids(site) is True
    assert site.runner_uid == 42
    assert site.runner_gid == 43


def test_is_contained_true_for_root_itself(tmp_path):
    assert SiteConfig.is_contained(tmp_path, tmp_path) is True


def test_is_contained_true_for_descendant(tmp_path):
    child = tmp_path / "a" / "b"
    child.mkdir(parents=True)
    assert SiteConfig.is_contained(child, tmp_path) is True


def test_is_contained_false_for_unrelated_path(tmp_path):
    sibling = tmp_path.parent / "not-related"
    assert SiteConfig.is_contained(sibling, tmp_path) is False


def test_is_contained_false_for_parent_of_root(tmp_path):
    # tmp_path's parent is NOT contained within tmp_path itself.
    assert SiteConfig.is_contained(tmp_path.parent, tmp_path) is False


def test_is_contained_rejects_traversal_out_of_root(tmp_path):
    site_root = tmp_path / "site"
    site_root.mkdir()
    escaping = site_root / ".." / "escaped"
    assert SiteConfig.is_contained(escaping, site_root) is False


def test_is_contained_false_when_resolve_raises(tmp_path, monkeypatch):
    def _raise_resolve(self, *args, **kwargs):
        raise OSError("simulated resolve failure")

    monkeypatch.setattr(pathlib.Path, "resolve", _raise_resolve)
    assert SiteConfig.is_contained(tmp_path / "x", tmp_path) is False


def test_resolve_ids_unknown_user(monkeypatch, caplog):
    def _raise(name: str) -> pwd.struct_passwd:
        raise KeyError(name)

    monkeypatch.setattr(SiteConfig, "lookup_user", _raise)
    site = SiteConfig.SiteConfig(
        name="seaglider",
        watch_dir=pathlib.Path("/tmp/seaglider"),
        jail_root=None,
        runner_user="runner-does-not-exist",
    )
    assert SiteConfig.resolve_ids(site) is False
    assert site.runner_uid == -1
    assert site.runner_gid == -1
    assert any(r.levelname == "ERROR" for r in caplog.records)
