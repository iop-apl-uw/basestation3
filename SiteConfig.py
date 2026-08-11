#! /usr/bin/env python
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

"""Shared site-registry types and sites.yaml loader for BaseRunnerMulti and
BaseRunnerPrivExec.

Both processes load their own SiteConfig table independently, from the same
sites.yaml, at their own startup - this module is what guarantees they can
never observe different data for the same site name.
"""

from __future__ import annotations

import dataclasses
import pathlib
import pwd

import yaml

from BaseLog import log_error


@dataclasses.dataclass(frozen=True)
class SiteConfig:
    """One site's resolved runtime configuration.

    Immutable once constructed except for runner_uid/runner_gid, which are
    populated by resolve_ids() after the fact - this is deliberate: nothing
    downstream can mutate a site's identity once it has been resolved.

    Also doubles as the lightweight "base_opts-like" namespace expected by
    Utils.create_lock_file/check_lock_file/wait_for_pid/cleanup_lock_file,
    which only ever read .mission_dir and .ignore_lock off whatever object
    they're given.

    Attributes:
        name: Site name, matches its key in sites.yaml (e.g. "aoml").
        watch_dir: Rundir this site's .run files are watched for/consumed in.
        jail_root: Root of this site's glider jail, if any.
        runner_user: Name of this site's runner-<site> Linux account.
        archive: Whether completed .run files are archived instead of
            unlinked (only ioptest sets this True today).
        ignore_lock: Whether to bypass the per-site lock-file check.
        python_version: Path to the python interpreter used to launch jobs.
        queue_scripts: Whether known_scripts are queued instead of run inline.
        docker_image: Docker image to use for this site's jobs, if any.
        docker_uid: uid to run the docker image as, if docker_image is set.
        docker_gid: gid to run the docker image as, if docker_image is set.
        use_docker_basestation: Whether to use the basestation installed in
            the docker container rather than mounting this checkout.
        cpu_quota_pct: Hard CPU cap for this site's jobs, as a percentage of
            one core (e.g. 60 -> 60%); None means unthrottled.
        cpu_weight: Relative systemd cgroup CPUWeight for this site's jobs
            (below/above the default of 100); None means default.
        runner_uid: Resolved uid of runner_user; -1 until resolve_ids() runs.
        runner_gid: Resolved gid of runner_user; -1 until resolve_ids() runs.
    """

    name: str
    watch_dir: pathlib.Path
    jail_root: pathlib.Path | None
    runner_user: str
    archive: bool = False
    ignore_lock: bool = False
    python_version: str = "/opt/basestation/bin/python"
    queue_scripts: bool = True
    docker_image: str = ""
    docker_uid: int = -1
    docker_gid: int = -1
    use_docker_basestation: bool = False
    cpu_quota_pct: int | None = None
    cpu_weight: int | None = None
    runner_uid: int = dataclasses.field(default=-1, compare=False)
    runner_gid: int = dataclasses.field(default=-1, compare=False)

    @property
    def mission_dir(self) -> pathlib.Path:
        """Alias for watch_dir so Utils' lock-file helpers work unmodified.

        Returns:
            The site's watch_dir.
        """
        return self.watch_dir


def lookup_user(name: str) -> pwd.struct_passwd:
    """Thin, mockable seam around pwd.getpwnam.

    Kept as its own function (rather than calling pwd.getpwnam directly from
    resolve_ids) purely so tests can monkeypatch account resolution instead
    of depending on real system accounts existing in the test sandbox.

    Args:
        name: Account name to resolve.

    Returns:
        The pwd database entry for name.

    Raises:
        KeyError: If name is not a known account on this system.
    """
    return pwd.getpwnam(name)


def resolve_ids(site: SiteConfig) -> bool:
    """Resolves site.runner_user to a uid/gid via lookup_user, in place.

    Args:
        site: The SiteConfig to resolve. Mutated in place (via
            object.__setattr__, since SiteConfig is frozen) on success.

    Returns:
        True if runner_user resolved to a real account, False otherwise
        (logged as an error; site is left unmodified).

    Raises:
        No exceptions are raised.
    """
    try:
        pw = lookup_user(site.runner_user)
    except KeyError:
        log_error(f"Site {site.name}: unknown runner_user {site.runner_user!r}")
        return False
    object.__setattr__(site, "runner_uid", pw.pw_uid)
    object.__setattr__(site, "runner_gid", pw.pw_gid)
    return True


def is_contained(path: pathlib.Path, root: pathlib.Path) -> bool:
    """Checks whether path resolves to root or one of its descendants.

    Shared by BaseRunnerMulti.py and BaseRunnerPrivExec.py so both use
    identical containment logic - once a consolidated process has
    legitimate access to every site's tree, the OS no longer backstops a
    code bug that confuses which site a path belongs to, so this check is
    the only thing that does.

    Args:
        path: Candidate path to check. Not required to exist.
        root: Root directory the candidate must be contained within.

    Returns:
        True if path's resolved form is root itself or a descendant of it,
        False otherwise (including if either path can't be resolved).
    """
    try:
        resolved_root = root.resolve()
        resolved_path = path.resolve()
    except OSError:
        return False
    return resolved_path == resolved_root or resolved_path.is_relative_to(resolved_root)


def _resolve_path(entry: dict, key: str) -> pathlib.Path | None:
    """Resolves an optional path-valued key from a sites.yaml entry.

    Args:
        entry: One site's raw mapping, as loaded from YAML.
        key: Key to look up.

    Returns:
        The expanded, resolved path, or None if key is absent/empty.
    """
    value = entry.get(key)
    if not value:
        return None
    return pathlib.Path(value).expanduser().resolve()


def _optional_int(entry: dict, key: str) -> int | None:
    """Resolves an optional int-valued key from a sites.yaml entry.

    Args:
        entry: One site's raw mapping, as loaded from YAML.
        key: Key to look up.

    Returns:
        The value cast to int, or None if key is absent.

    Raises:
        TypeError: If the value has the wrong shape to convert to int.
        ValueError: If the value can't be converted to int.
    """
    value = entry.get(key)
    if value is None:
        return None
    return int(value)


def _build_site(name: str, entry: dict) -> SiteConfig:
    """Builds one SiteConfig from its raw sites.yaml mapping.

    Args:
        name: Site name (the entry's key in sites.yaml).
        entry: The site's raw mapping, as loaded from YAML.

    Returns:
        The constructed SiteConfig (runner_uid/runner_gid still unresolved).

    Raises:
        KeyError: If a required key (watch_dir, runner_user) is missing.
        TypeError: If a value has the wrong shape for its field.
        ValueError: If a value can't be converted to its field's type.
    """
    return SiteConfig(
        name=name,
        watch_dir=pathlib.Path(entry["watch_dir"]).expanduser().resolve(),
        jail_root=_resolve_path(entry, "jail_root"),
        runner_user=entry["runner_user"],
        archive=bool(entry.get("archive", False)),
        ignore_lock=bool(entry.get("ignore_lock", False)),
        python_version=entry.get("python_version", "/opt/basestation/bin/python"),
        queue_scripts=bool(entry.get("queue_scripts", True)),
        docker_image=entry.get("docker_image", ""),
        docker_uid=int(entry.get("docker_uid", -1)),
        docker_gid=int(entry.get("docker_gid", -1)),
        use_docker_basestation=bool(entry.get("use_docker_basestation", False)),
        cpu_quota_pct=_optional_int(entry, "cpu_quota_pct"),
        cpu_weight=_optional_int(entry, "cpu_weight"),
    )


def load_sites_config(sites_config_path: pathlib.Path) -> dict[str, SiteConfig] | None:
    """Loads, validates, and resolves every site in a sites.yaml file.

    Fails closed: any single malformed or unresolvable entry aborts loading
    the entire file rather than silently dropping just that one site, so a
    typo is loud (the caller should refuse to start) instead of quietly
    leaving one site unwatched.

    Args:
        sites_config_path: Path to the sites.yaml file to load.

    Returns:
        A dict mapping site name to its resolved SiteConfig, or None if the
        file could not be read, was empty/malformed, or any entry failed
        to resolve (already logged via log_error in every such case).

    Raises:
        No exceptions are raised.
    """
    try:
        raw = yaml.safe_load(sites_config_path.read_text())
    except Exception:
        log_error(f"Could not process {sites_config_path}", "exc")
        return None

    if not isinstance(raw, dict) or not raw:
        log_error(f"{sites_config_path} is empty or not a mapping")
        return None

    sites: dict[str, SiteConfig] = {}
    for name, entry in raw.items():
        if not isinstance(entry, dict):
            log_error(f"Malformed sites.yaml entry for site {name!r}")
            return None
        try:
            site = _build_site(name, entry)
        except (KeyError, TypeError, ValueError):
            log_error(f"Malformed sites.yaml entry for site {name!r}", "exc")
            return None
        if not resolve_ids(site):
            return None
        sites[name] = site

    return sites
