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

Check a sites.yaml before (re)starting the services:
    python SiteConfig.py check sites.yaml [--no-resolve_users]
    python SiteConfig.py dump sites.yaml        the resolved sites, defaults filled in
"""

from __future__ import annotations

import dataclasses
import pathlib
import pwd
import sys
from typing import Annotated, Any

import yaml
from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictBool,
    StrictInt,
    StrictStr,
    ValidationError,
    model_validator,
)

import YamlValidation
from BaseLog import log_error, log_info


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
        jail_root: Extra allowed root for this site's directory-tree
            containment check (BaseRunnerPrivExec.validate_dispatch_request),
            alongside watch_dir. When jailed is True, also the real
            filesystem root .run-file paths get rewritten against (they
            were written from inside the jail's own view of the
            filesystem). None means no extra root beyond watch_dir.
        jailed: Whether this site's glider account runs inside a real
            chroot jail, so paths recorded in its .run files are relative
            to the jail's own root and need rewriting against jail_root to
            get their real, outside-the-jail location. False means
            jail_root (if set) only widens the containment check - .run
            file paths are already real, absolute host paths. The dataclass
            default (False) is only a safe no-op fallback for callers that
            construct a SiteConfig directly; load_sites_config's own
            default is whether jail_root is set, so existing always-jailed
            sites' sites.yaml entries need no change. A site that isn't
            jailed but still wants a containment root wider than watch_dir
            must set jailed: false explicitly alongside jail_root.
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
        memory_high_mb: Soft memory cap (systemd MemoryHigh-equivalent) for
            this site's jobs, in MiB, written to each job's own memory.high;
            None means unlimited (the kernel default).
        memory_max_mb: Hard memory cap (systemd MemoryMax-equivalent) for
            this site's jobs, in MiB; crossing it invokes the kernel OOM
            killer scoped to that job's own cgroup only. None means
            unlimited.
        runner_uid: Resolved uid of runner_user; -1 until resolve_ids() runs.
        runner_gid: Resolved gid of runner_user; -1 until resolve_ids() runs.
    """

    name: str
    watch_dir: pathlib.Path
    jail_root: pathlib.Path | None
    runner_user: str
    jailed: bool = False
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
    memory_high_mb: int | None = None
    memory_max_mb: int | None = None
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


def site_cgroup_path(cgroup_root: pathlib.Path, site_name: str) -> pathlib.Path:
    """Path to a site's own cgroup, shared by every job it ever dispatches.

    Shared by BaseRunnerPrivExec.py (which creates/writes it) and
    BaseRunnerMulti.py (which only ever reads it), so both agree on the
    naming convention without duplicating the f-string in each.

    Args:
        cgroup_root: Root of BaseRunnerPrivExec's own delegated cgroup subtree.
        site_name: The site's name.

    Returns:
        cgroup_root/site-<site_name>.
    """
    return cgroup_root / f"site-{site_name}"


def job_cgroup_path(cgroup_root: pathlib.Path, site_name: str, job_id: str) -> pathlib.Path:
    """Path to a job's own leaf cgroup, per CgroupJoiner.join's layout.

    Args:
        cgroup_root: Root of BaseRunnerPrivExec's own delegated cgroup subtree.
        site_name: The job's site name.
        job_id: The job's own id.

    Returns:
        cgroup_root/site-<site_name>/job-<job_id>.
    """
    return site_cgroup_path(cgroup_root, site_name) / f"job-{job_id}"


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


NonEmptyStr = Annotated[StrictStr, Field(min_length=1)]
PositiveInt = Annotated[StrictInt, Field(ge=1)]


class SiteEntry(BaseModel):
    """One site's sites.yaml entry, as written (see SiteConfig for what each key means).

    Strict: an unknown key (a typo such as cpu_quota) is an error, a boolean must be
    true/false (not "false", which bool() would make True), and an int must be an int.
    """

    model_config = ConfigDict(extra="forbid")

    watch_dir: NonEmptyStr
    runner_user: NonEmptyStr
    jail_root: StrictStr | None = None
    jailed: StrictBool | None = None
    archive: StrictBool = False
    ignore_lock: StrictBool = False
    python_version: NonEmptyStr = "/opt/basestation/bin/python"
    queue_scripts: StrictBool = True
    docker_image: StrictStr = ""
    docker_uid: Annotated[StrictInt, Field(ge=-1)] = -1
    docker_gid: Annotated[StrictInt, Field(ge=-1)] = -1
    use_docker_basestation: StrictBool = False
    cpu_quota_pct: PositiveInt | None = None
    cpu_weight: Annotated[StrictInt, Field(ge=1, le=10000)] | None = None  # systemd CPUWeight range
    memory_high_mb: PositiveInt | None = None
    memory_max_mb: PositiveInt | None = None

    @model_validator(mode="after")
    def _consistent(self) -> SiteEntry:
        """Cross-key rules.

        Returns:
            The entry.

        Raises:
            ValueError: jailed is true with no jail_root, or memory_high_mb exceeds memory_max_mb.
        """
        if self.jailed and not self.jail_root:
            raise ValueError("jailed is true but jail_root is not set")
        if self.memory_high_mb is not None and self.memory_max_mb is not None and self.memory_high_mb > self.memory_max_mb:
            raise ValueError(f"memory_high_mb ({self.memory_high_mb}) is above memory_max_mb ({self.memory_max_mb})")
        return self


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
        Nothing for an entry SiteEntry has validated (check_sites only calls it
        for those).
    """
    jail_root = _resolve_path(entry, "jail_root")
    # SiteEntry has already checked the entry (incl. jailed needing jail_root)
    jailed = bool(entry.get("jailed", jail_root is not None))

    return SiteConfig(
        name=name,
        watch_dir=pathlib.Path(entry["watch_dir"]).expanduser().resolve(),
        jail_root=jail_root,
        jailed=jailed,
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
        memory_high_mb=_optional_int(entry, "memory_high_mb"),
        memory_max_mb=_optional_int(entry, "memory_max_mb"),
    )


def check_sites(sites_config_path: pathlib.Path, resolve_users: bool = True) -> tuple[dict[str, SiteConfig] | None, list[str]]:
    """Loads and checks every site in a sites.yaml file, reporting every problem.

    Args:
        sites_config_path: The sites.yaml file.
        resolve_users: Look up each runner_user (off the server, where the
            accounts don't exist, pass False to check only the file's form).

    Returns:
        (sites, problems): sites maps each name to its SiteConfig, or is None if
        there was any problem (fail closed). Each problem is "file:line: where: message".

    Raises:
        No exceptions are raised.
    """
    path = sites_config_path
    try:
        raw, locate = YamlValidation.load_yaml_with_lines(path)
    except yaml.YAMLError as e:
        return None, [YamlValidation.format_yaml_error(path, e)]
    except OSError as e:
        return None, [f"{path}: could not read ({e})"]
    if not isinstance(raw, dict) or not raw:
        return None, [f"{path}: is empty or not a mapping of site names to entries"]
    loaded = YamlValidation.LoadedYaml(path, raw, locate)

    problems: list[str] = []
    sites: dict[str, SiteConfig] = {}
    for name, entry in raw.items():
        if not isinstance(name, str):
            problems.append(f"{loaded.where((str(name),))}: site name {name!r} must be a string")
            continue
        try:
            SiteEntry.model_validate(entry)
        except ValidationError as e:
            problems += YamlValidation.format_validation_errors(path, locate, e, prefix=(name,))
            continue
        site = _build_site(name, entry)
        if resolve_users:
            try:
                pw = lookup_user(site.runner_user)
            except KeyError:
                problems.append(
                    f"{loaded.where((name, 'runner_user'))}: {name}.runner_user: unknown account {site.runner_user!r}"
                )
                continue
            object.__setattr__(site, "runner_uid", pw.pw_uid)
            object.__setattr__(site, "runner_gid", pw.pw_gid)
        sites[name] = site
    return (None if problems else sites), problems


def load_sites_config(sites_config_path: pathlib.Path) -> dict[str, SiteConfig] | None:
    """Loads, validates, and resolves every site in a sites.yaml file.

    Fails closed: any single malformed or unresolvable entry aborts loading
    the entire file rather than silently dropping just that one site, so a
    typo is loud (the caller should refuse to start) instead of quietly
    leaving one site unwatched. Every problem in the file is logged first, at
    file:line, so they can all be fixed at once (check_sites, or
    "SiteConfig.py check").

    Args:
        sites_config_path: Path to the sites.yaml file to load.

    Returns:
        A dict mapping site name to its resolved SiteConfig, or None if the
        file could not be read, was empty/malformed, or any entry failed
        to resolve (already logged via log_error in every such case).

    Raises:
        No exceptions are raised.
    """
    sites, problems = check_sites(sites_config_path)
    for problem in problems:
        log_error(problem)
    if sites is None:
        log_error(f"{sites_config_path}: {len(problems)} problem(s) - not loading any site")
    return sites


def _site_as_dict(site: SiteConfig) -> dict[str, Any]:
    """A resolved site as plain values, for dump.

    Args:
        site: The site.

    Returns:
        Its fields (paths as strings), without the name.

    Raises:
        Nothing.
    """
    out = {}
    for field in dataclasses.fields(site):
        if field.name == "name":
            continue
        value = getattr(site, field.name)
        out[field.name] = str(value) if isinstance(value, pathlib.Path) else value
    return out


def main(cmdline_args: list[str] = sys.argv[1:]) -> int:
    """Checks or dumps a sites.yaml file.

    Args:
        cmdline_args: Command line arguments.

    Returns:
        0 if the file is valid, 1 if not.

    Raises:
        Nothing expected.
    """
    import argparse  # noqa: PLC0415 - only the CLI needs these (the services import this module)

    import BaseOpts  # noqa: PLC0415
    import BaseOptsType  # noqa: PLC0415
    from BaseLog import BaseLogger  # noqa: PLC0415

    base_opts = BaseOpts.BaseOptions(
        "Check a sites.yaml (BaseRunnerMulti / BaseRunnerPrivExec site registry)",
        cmdline_args=cmdline_args,
        calling_module="SiteConfig",
        additional_arguments={
            "action": BaseOptsType.options_t(
                None,
                {"SiteConfig"},
                ("action",),
                str,
                {"help": "check FILE | dump FILE", "choices": ("check", "dump")},
            ),
            "sites_file": BaseOptsType.options_t(
                None,
                {"SiteConfig"},
                ("sites_file",),
                pathlib.Path,
                {"help": "The sites.yaml file"},
            ),
            "resolve_users": BaseOptsType.options_t(
                True,
                {"SiteConfig"},
                ("--resolve_users",),
                bool,
                {
                    "help": "Look up each runner_user (--no-resolve_users off the server)",
                    "action": argparse.BooleanOptionalAction,
                },
            ),
        },
    )
    BaseLogger(base_opts)
    path = pathlib.Path(base_opts.sites_file).expanduser()
    sites, problems = check_sites(path, resolve_users=base_opts.resolve_users)
    for problem in problems:
        log_error(problem)
    if sites is None:
        return 1
    if base_opts.action == "dump":
        # The resolved sites are the output - for redirecting
        print(YamlValidation.dump_text({name: _site_as_dict(site) for name, site in sites.items()}), end="")
    else:
        log_info(f"{path}: OK - {len(sites)} site(s): {', '.join(sites)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
