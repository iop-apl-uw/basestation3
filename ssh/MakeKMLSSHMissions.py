#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2023, 2024, 2026 by University of Washington.  All rights reserved.
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

"""Generates SSH contour KML/KMZ files for every active mission, across sites.

Active missions are found by walking a master missions.yml, following its
domains:/includes: entries into each group's own missions.yml. Each mission
is assigned to the site (from a BaseRunnerMulti sites file) whose directory
tree contains it, and each site's missions are processed by a short-lived,
freshly exec'd child of this script (--site_child) running as that site's
runner account, so all files written for a group are owned by that group's
runner. The child gets its missions as JSON on stdin, so it never needs to
read the sites file.

Without --sites_config, the previous single-group behavior is kept: only
the given missions.yml's own missions: list is read (domains:/includes: are
not followed, and entries without a path: are skipped), and every mission is
processed in this process, as whoever runs it - as the per-jail cron jobs
did.

Run as an unprivileged account with CAP_SETUID/CAP_SETGID (see
makekml-systemd-setup.md).
"""

import argparse
import dataclasses
import json
import logging
import os
import pdb
import subprocess
import sys
import time
import traceback
from dataclasses import dataclass
from pathlib import Path

import orjson
import yaml

sys.path.append(os.path.join(os.path.dirname(os.path.realpath(__file__)), os.pardir))
import MakeKMLSSH

import BaseOpts
import BaseOptsType
import Capabilities
import SiteConfig
import Utils
from BaseLog import BaseLogger, log_critical, log_error, log_info, log_warning

DEBUG_PDB = False

# SSH data older than this is considered stale - no KML is generated from it
STALE_DATA_SECS = 3600 * 24 * 5



@dataclass(frozen=True)
class Mission:
    """One active mission from a missions.yml tree.

    Attributes:
        path: The mission directory (host path).
        glider: The glider id.
    """

    path: Path
    glider: int


def _mission_path(base_dir: Path, mission: dict) -> Path:
    """Resolves a missions.yml entry's directory, as vis.py does.

    Args:
        base_dir: Directory relative mission paths are resolved against.
        mission: The missions.yml entry.

    Returns:
        base_dir/path, or base_dir/sgNNN if the entry has no path. An
        absolute path is used as-is.

    Raises:
        KeyError: If the entry has neither a path nor a glider.
        TypeError: If glider is the wrong type.
        ValueError: If glider can't be converted to int.
    """
    if mission.get("path"):
        return base_dir / mission["path"]
    return base_dir / f"sg{int(mission['glider']):03d}"


def load_active_missions(
    missions_yml: Path,
    root: Path | None = None,
    follow_includes: bool = True,
    default_path: bool = True,
    _visited: set[Path] | None = None,
) -> list[Mission] | None:
    """Loads the active missions from a missions.yml file and everything it includes.

    A mission is active if it has no status field, or status "active". Each
    domains: (or includes:) entry other than "root" names another
    missions.yml in its missions: field, which is loaded recursively. Paths
    of missions found through a domain are resolved against that domain's
    root: field if set, else against the domain's missions.yml directory.

    Args:
        missions_yml: The missions.yml file to load.
        root: Directory this file's mission paths are relative to; defaults
            to missions_yml's directory.
        follow_includes: Load the files named by domains:/includes: too.
            False reads only this file's own missions: list (the
            single-group behavior used without --sites_config).
        default_path: Treat a mission without a path: as sgNNN, as vis.py
            does. False skips such missions (the single-group behavior).
        _visited: Internal recursion guard against include cycles; never
            pass this explicitly.

    Returns:
        The active missions, de-duplicated by path in file order, or None if
        missions_yml itself can't be read or has no missions:/domains:/
        includes: (logged). Unreadable included files are logged and
        skipped rather than failing the whole tree.

    Raises:
        No exceptions are raised.
    """
    missions_yml = missions_yml.resolve()
    if _visited is None:
        _visited = set()
    if missions_yml in _visited:
        log_warning(f"{missions_yml}: already visited - skipping (cyclic includes?)")
        return []
    _visited.add(missions_yml)

    try:
        data = yaml.safe_load(missions_yml.read_text())
    except (OSError, yaml.YAMLError):
        log_error(f"Could not read {missions_yml}", "exc")
        return None

    if not isinstance(data, dict):
        log_error(f"{missions_yml}: expected a top-level mapping")
        return None

    missions = data.get("missions")
    includes = data.get("domains", data.get("includes")) if follow_includes else None
    if not isinstance(missions, list) and not isinstance(includes, dict):
        log_error(f"{missions_yml}: no missions list or domains/includes mapping")
        return None

    base_dir = root if root is not None else missions_yml.parent
    found: dict[Path, Mission] = {}

    if isinstance(missions, list):
        for mission in missions:
            if not isinstance(mission, dict) or "glider" not in mission:
                continue
            if mission.get("status", "active") != "active":
                continue
            if not default_path and not mission.get("path"):
                continue
            try:
                entry = Mission(_mission_path(base_dir, mission), int(mission["glider"]))
            except (KeyError, TypeError, ValueError):
                log_warning(f"{missions_yml}: malformed mission entry {mission!r} - skipping")
                continue
            found.setdefault(entry.path, entry)

    if isinstance(includes, dict):
        for name, domain in includes.items():
            if name == "root" or not isinstance(domain, dict) or "missions" not in domain:
                continue
            domain_yml = missions_yml.parent / domain["missions"]
            if not domain_yml.is_file():
                log_warning(f"{missions_yml}: domain {name!r}: {domain_yml} not found - skipping")
                continue
            domain_root = missions_yml.parent / domain["root"] if domain.get("root") else None
            sub = load_active_missions(
                domain_yml, domain_root, follow_includes, default_path, _visited
            )
            if sub is None:
                log_warning(f"{missions_yml}: domain {name!r}: could not load {domain_yml} - skipping")
                continue
            for entry in sub:
                found.setdefault(entry.path, entry)

    return list(found.values())


def site_tree(site: SiteConfig.SiteConfig) -> Path:
    """The directory tree a site's missions live in.

    Args:
        site: The site.

    Returns:
        The site's jail_root if set, else the directory holding its rundir
        (watch_dir.parent) - the same containment root BaseSMS.py uses.

    Raises:
        No exceptions are raised.
    """
    return site.jail_root if site.jail_root is not None else site.watch_dir.parent


def assign_missions(
    missions: list[Mission], sites: dict[str, SiteConfig.SiteConfig]
) -> tuple[dict[str, list[Mission]], list[Mission]]:
    """Groups missions by the site whose directory tree contains them.

    Args:
        missions: The missions to assign.
        sites: Site name -> SiteConfig, in sites file order.

    Returns:
        (site name -> its missions, in sites file order, omitting sites with
        none; missions not under any site's tree). If several sites' trees
        contain a mission, the deepest (most specific) tree wins.

    Raises:
        No exceptions are raised.
    """
    trees = [(name, site_tree(site)) for name, site in sites.items()]
    by_site: dict[str, list[Mission]] = {name: [] for name in sites}
    unmatched: list[Mission] = []

    for mission in missions:
        matches = [
            (name, tree) for name, tree in trees if SiteConfig.is_contained(mission.path, tree)
        ]
        if not matches:
            unmatched.append(mission)
            continue
        name, _ = max(matches, key=lambda match: len(match[1].resolve().parts))
        by_site[name].append(mission)

    return {name: found for name, found in by_site.items() if found}, unmatched


def find_last_update(data_dir: Path) -> float | None:
    """Finds when the newest file in the SSH data directory was changed.

    Args:
        data_dir: The SSH data directory.

    Returns:
        The newest ctime, or None if the directory is empty or missing.

    Raises:
        No exceptions are raised.
    """
    try:
        return max((p.stat().st_ctime for p in Path(data_dir).iterdir()), default=None)
    except OSError:
        return None


def process_site_missions(base_opts: BaseOpts.BaseOptions, missions: list[Mission]) -> bool:
    """Generates the SSH KML for one site's missions (runs in the site's child).

    Args:
        base_opts: Options; mission_dir is set per mission for the lock check.
        missions: The site's active missions.

    Returns:
        True if every mission was processed without error. Missions without
        an sg_plot_constants.m, or with a conversion already running, are
        skipped with a warning and don't count as failures.

    Raises:
        No exceptions are raised.
    """
    ok = True
    for mission in missions:
        mission_dir = mission.path
        instrument_id = mission.glider
        sg_plot_consts = mission_dir / "sg_plot_constants.m"
        if not sg_plot_consts.exists():
            log_warning(f"Didn't find {sg_plot_consts} Skipping")
            continue

        try:
            ret_val = MakeKMLSSH.make_kml(
                base_opts.data_dir,
                mission_dir,
                str(sg_plot_consts),
                instrument_id=instrument_id,
                fetch_ssh=base_opts.fetch_ssh,
            )
        except Exception:
            log_error(f"Could not generate ssh kml for {mission_dir}", "exc")
            ok = False
            continue

        if not ret_val or not base_opts.mergessh:
            continue

        # Check for existing process
        base_opts.ignore_lock = False
        base_opts.mission_dir = mission_dir
        lock_file_pid = Utils.check_lock_file(base_opts, ".conversion_lock")
        if lock_file_pid < 0:
            log_error("Error accessing the lockfile - proceeding anyway...")
        elif lock_file_pid > 0:
            # The PID still exists
            log_warning(
                "Previous conversion process (pid:%d) still exists - skipping launch of MakeKML"
                % lock_file_pid
            )
            continue

        # Create a standard date/time string here
        makekml_log = mission_dir / f"makekml_{time.strftime('%y%m%d%H%M%S', time.gmtime(time.time()))}"
        cmd_line = "%s %s -v --mission_dir %s --config %s  > %s 2>&1" % (
            sys.executable,
            Path(base_opts.basestation_directory) / "MakeKML.py",
            mission_dir,
            mission_dir / f"sg{instrument_id:03d}.conf",
            makekml_log,
        )

        log_info(f"Running {cmd_line}")
        sts, _ = Utils.run_cmd_shell(cmd_line)
        if sts:
            log_error(f"MakeKML.py exited {sts} - see {makekml_log} for details")
            ok = False

        log_info(f"Back from MakeKML.py - see {makekml_log} for details")

        try:
            msg = {
                "glider": instrument_id,
                # This may cause issues with vis, but we'll try it like this to start
                "dive": 0,
                "content": "files=kmz",
                "time": time.time(),
            }
            Utils.notifyVis(instrument_id, "urls-files", orjson.dumps(msg).decode("utf-8"))
        except Exception:
            log_error("Failed notification of vis", "exc")

    return ok


def needs_drop(site: SiteConfig.SiteConfig) -> bool:
    """Checks whether processing a site requires running as its runner.

    Args:
        site: The site.

    Returns:
        False if this process already runs as the site's runner uid/gid
        (e.g. a development run), True otherwise.

    Raises:
        No exceptions are raised.
    """
    return (site.runner_uid, site.runner_gid) != (os.geteuid(), os.getegid())


def child_command(base_opts: BaseOpts.BaseOptions, site_name: str) -> list[str]:
    """Builds the command line that processes one site's missions.

    Args:
        base_opts: The parent's options; the processing flags are passed on.
        site_name: The site being processed (for the child's log lines).

    Returns:
        argv re-running this script in --site_child mode.

    Raises:
        No exceptions are raised.
    """
    cmd = [
        sys.executable,
        str(Path(__file__).resolve()),  # argv requires str
        "--site_child",
        site_name,
        "--mergessh" if base_opts.mergessh else "--no-mergessh",
        "--fetch_ssh" if base_opts.fetch_ssh else "--no-fetch_ssh",
    ]
    if getattr(base_opts, "verbose", False):
        cmd.append("--verbose")
    cmd += [str(base_opts.data_dir), str(base_opts.mission_yml)]  # argv requires str
    return cmd


def child_popen_kwargs(site: SiteConfig.SiteConfig) -> dict:
    """Builds the subprocess.Popen arguments that run a site's child as its runner.

    Popen drops privileges in the child between fork and exec, in the order
    BaseRunnerPrivExec.PrivilegeDropper.drop_and_exec requires: supplementary
    groups (the runner's own, as initgroups would give), then gid, then uid.
    Doing it there - rather than os.fork() plus Python-level setuid - keeps
    the child clear of this (multi-threaded, by numpy/scipy) process's state.

    The runner can't write the worker's own HOME/MPLCONFIGDIR cache
    directory, so the child gets a per-runner one under /tmp (private to the
    service when the unit sets PrivateTmp=yes).

    Args:
        site: The site to run as.

    Returns:
        Keyword arguments for subprocess.Popen: env always, and user/group/
        extra_groups when needs_drop(site).

    Raises:
        No exceptions are raised.
    """
    env = dict(os.environ)
    if not needs_drop(site):
        return {"env": env}
    cache_dir = f"/tmp/makekml-ssh-{site.runner_user}"
    env["HOME"] = cache_dir
    env["MPLCONFIGDIR"] = cache_dir
    return {
        "env": env,
        "user": site.runner_uid,
        "group": site.runner_gid,
        "extra_groups": os.getgrouplist(site.runner_user, site.runner_gid),
    }


def missions_to_json(missions: list[Mission]) -> str:
    """Serializes missions for a site child's stdin.

    Args:
        missions: The missions.

    Returns:
        JSON list of {"path": str, "glider": int}.

    Raises:
        No exceptions are raised.
    """
    return json.dumps(
        [{**dataclasses.asdict(m), "path": str(m.path)} for m in missions]
    )


def missions_from_json(text: str) -> list[Mission]:
    """Parses missions_to_json output.

    Args:
        text: The JSON text.

    Returns:
        The missions.

    Raises:
        ValueError: If text isn't valid JSON (json.JSONDecodeError).
        KeyError: If an entry lacks path or glider.
        TypeError: If an entry has the wrong shape.
    """
    return [Mission(Path(m["path"]), int(m["glider"])) for m in json.loads(text)]


def _flush_output() -> None:
    """Flushes stdio and log handlers so parent and child output stay in order.

    Raises:
        No exceptions are raised.
    """
    sys.stdout.flush()
    sys.stderr.flush()
    loggers = [logging.getLogger()]
    if BaseLogger.log is not None:
        loggers.append(BaseLogger.log)
    for logger in loggers:
        for handler in logger.handlers:
            handler.flush()


def run_sites(
    base_opts: BaseOpts.BaseOptions,
    by_site: dict[str, list[Mission]],
    sites: dict[str, SiteConfig.SiteConfig],
    jobs: int,
) -> list[str]:
    """Processes each site's missions in its own child, running as that site's runner.

    Args:
        base_opts: Options.
        by_site: Site name -> its missions, in processing order.
        sites: Site name -> SiteConfig.
        jobs: Maximum number of site children running at once.

    Returns:
        The names of the sites whose child failed or couldn't be started.

    Raises:
        No exceptions are raised.
    """
    pending = list(by_site.items())
    running: dict[int, tuple[str, subprocess.Popen]] = {}
    failed: list[str] = []

    while pending or running:
        while pending and len(running) < jobs:
            name, missions = pending.pop(0)
            site = sites[name]
            log_info(f"{name}: processing {len(missions)} mission(s) as {site.runner_user}")
            _flush_output()
            try:
                proc = subprocess.Popen(
                    child_command(base_opts, name),
                    stdin=subprocess.PIPE,
                    text=True,
                    **child_popen_kwargs(site),
                )
            except PermissionError:
                log_critical(
                    f"{name}: unable to run as {site.runner_user} - the worker needs "
                    "CAP_SETUID and CAP_SETGID (see makekml-systemd-setup.md)",
                    "exc",
                )
                failed.append(name)
                continue
            except OSError:
                log_error(f"{name}: could not start site child", "exc")
                failed.append(name)
                continue

            try:
                assert proc.stdin is not None  # stdin=PIPE guarantees it
                proc.stdin.write(missions_to_json(missions))
                proc.stdin.close()
            except BrokenPipeError:
                pass  # child already exited - its exit status says why
            running[proc.pid] = (name, proc)

        if not running:
            continue
        pid, status = os.waitpid(-1, 0)
        if pid not in running:
            continue
        name, proc = running.pop(pid)
        proc.returncode = os.waitstatus_to_exitcode(status)  # reaped here, not via proc.wait()
        if proc.returncode == 0:
            log_info(f"{name}: done")
        else:
            log_error(f"{name}: failed (exit {proc.returncode})")
            failed.append(name)

    return failed


def run_site_child(base_opts: BaseOpts.BaseOptions) -> int:
    """The --site_child entry point: processes the missions given on stdin.

    Args:
        base_opts: Options (site_child names the site, for log lines).

    Returns:
        0 if every mission was processed without error, 1 otherwise -
        including when the inherited capabilities couldn't be dropped, in
        which case nothing is processed.

    Raises:
        No exceptions are raised.
    """
    try:
        # Shed the worker's ambient CAP_SETUID/CAP_SETGID before touching any
        # mission - see Capabilities.drop_all_capabilities
        Capabilities.drop_all_capabilities()
    except OSError:
        log_critical(f"{base_opts.site_child}: could not drop capabilities - not processing", "exc")
        return 1

    try:
        missions = missions_from_json(sys.stdin.read())
    except (ValueError, KeyError, TypeError):
        log_critical(f"{base_opts.site_child}: malformed mission list on stdin", "exc")
        return 1
    log_info(f"{base_opts.site_child}: {len(missions)} mission(s)")
    return 0 if process_site_missions(base_opts, missions) else 1


def main(instrument_id: int | None = None, base_opts: BaseOpts.BaseOptions | None = None) -> int:
    """Command line app for creating kml/kmz files of ssh contours

    Args:
        instrument_id: Unused; kept for call compatibility.
        base_opts: Pre-built options (tests); parsed from the command line
            if None.

    Returns:
        0 for success, including when the SSH data is stale and nothing is
        generated. 1 if the sites file or master missions.yml couldn't be
        loaded, or any site's processing failed.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(
            "Command line app for creating kml/kmz files of ssh contours",
            additional_arguments={
                "fetch_ssh": BaseOptsType.options_t(
                    False,
                    {"MakeKMLSSHMissions"},
                    ("--fetch_ssh",),
                    bool,
                    {
                        "help": "Fetch the most recent ssh data",
                        "action": argparse.BooleanOptionalAction,
                    },
                ),
                "data_dir": BaseOptsType.options_t(
                    None,
                    {"MakeKMLSSHMissions"},
                    ("data_dir",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Location of Aviso data",
                        "action": BaseOpts.FullPathlibAction,
                    },
                ),
                "mission_yml": BaseOptsType.options_t(
                    None,
                    {"MakeKMLSSHMissions"},
                    ("mission_yml",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "Path to the master vis mission config file - "
                        "domains:/includes: are followed into each group's own file",
                        "action": BaseOpts.FullPathlibAction,
                    },
                ),
                "sites_config": BaseOptsType.options_t(
                    None,
                    {"MakeKMLSSHMissions"},
                    ("--sites_config",),
                    BaseOpts.FullPathlib,
                    {
                        "help": "BaseRunnerMulti sites file. When given, mission_yml is "
                        "walked as the master file (following domains:/includes:) and "
                        "each site's missions are processed as that site's runner. "
                        "When omitted, only mission_yml's own missions are processed, "
                        "in this process, as the current user",
                        "action": BaseOpts.FullPathlibAction,
                    },
                ),
                "site_child": BaseOptsType.options_t(
                    None,
                    {"MakeKMLSSHMissions"},
                    ("--site_child",),
                    str,
                    {
                        "help": "Internal: process the missions JSON on stdin for "
                        "this site (used by the worker for each site)",
                    },
                ),
                "jobs": BaseOptsType.options_t(
                    1,
                    {"MakeKMLSSHMissions"},
                    ("--jobs",),
                    int,
                    {"help": "Number of sites to process at once"},
                ),
                # Duplicates entries in BaseOpts
                "force": BaseOptsType.options_t(
                    False,
                    {"MakeKMLSSHMissions"},
                    ("--force",),
                    bool,
                    {
                        "help": "Forces creation of all kml files",
                        "action": "store_true",
                    },
                ),
                # End duplicate
                "mergessh": BaseOptsType.options_t(
                    True,
                    {"MakeKMLSSHMissions"},
                    ("--mergessh",),
                    bool,
                    {
                        "help": "Launches MakeKML.py to merge in generated ssh",
                        "action": argparse.BooleanOptionalAction,
                    },
                ),
            },
        )

    BaseLogger(base_opts, include_time=True)

    base_opts.basestation_directory = Path(__file__).resolve().parent.parent

    processing_start_time = time.time()

    log_info(
        "Started processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )

    if getattr(base_opts, "site_child", None):
        return run_site_child(base_opts)

    if base_opts.jobs < 1:
        log_critical(f"--jobs must be at least 1 (got {base_opts.jobs})")
        return 1

    sites = None
    if base_opts.sites_config:
        sites = SiteConfig.load_sites_config(base_opts.sites_config)
        if sites is None:
            log_critical(f"Could not load sites from {base_opts.sites_config}")
            return 1

    last_update = find_last_update(base_opts.data_dir)
    if not base_opts.force and (
        last_update is None or last_update < time.time() - STALE_DATA_SECS
    ):
        log_warning(f"No SSH data in {base_opts.data_dir} newer than 5 days - nothing to do")
        return 0

    if sites is None:
        # Single group, as the current user - the pre-sites.yml behavior
        missions = load_active_missions(
            base_opts.mission_yml, follow_includes=False, default_path=False
        )
        if missions is None:
            log_critical(f"Could not load missions from {base_opts.mission_yml}")
            return 1
        ok = process_site_missions(base_opts, missions)
        failed = [] if ok else [str(base_opts.mission_yml)]
    else:
        missions = load_active_missions(base_opts.mission_yml)
        if missions is None:
            log_critical(f"Could not load missions from {base_opts.mission_yml}")
            return 1

        by_site, unmatched = assign_missions(missions, sites)
        for mission in unmatched:
            log_warning(
                f"sg{mission.glider:03d} {mission.path}: not under any site in "
                f"{base_opts.sites_config} - skipping"
            )

        failed = run_sites(base_opts, by_site, sites, base_opts.jobs)

    log_info(
        "Finished processing "
        + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
    )
    log_info("Run time %f seconds" % (time.time() - processing_start_time))

    if failed:
        log_error(f"SSH KML generation failed for: {', '.join(failed)}")
        return 1
    return 0


if __name__ == "__main__":
    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()
    try:
        retval = main()
    except Exception:
        if DEBUG_PDB:
            _, _, traceb = sys.exc_info()
            traceback.print_exc()
            pdb.post_mortem(traceb)
        log_critical("Unhandled exception in main -- exiting")
        sys.exit(1)
    else:
        sys.exit(retval)
