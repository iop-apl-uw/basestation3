# MakeKML SSH jobs: systemd timers + daily error report

Runs the daily SSH (sea surface height) pipeline on iopbase3 and
seaglider.pub under systemd, as the unprivileged `baserunner` account:

1. **Fetch**: `AvisoUtils.py` downloads, decimates and prunes the Copernicus
   altimetry data into `/home/ssh/data`, once a day for the whole host.
2. **KML**: `MakeKMLSSHMissions.py` generates each active mission's SSH
   contour KML/KMZ from that shared data, for **every group on the host**.
   Each group's files are written by that group's own runner account.
3. **Report**: a daily scan of both jobs' journals, emailed to ioplog@uw.edu.

It replaces these cron jobs:

```
# iopbase3 (before its first systemd migration) and seaglider.pub: gbs, 10:00 daily
0 10 * * * /opt/basestation/bin/python /usr/local/basestation3/ssh/AvisoUtils.py \
    --delete_older 30 --verbose /home/ssh/data >> /home/gbs/MakeKML.log 2>&1

# seaglider.pub: one per jail, in that jail's runner crontab (sams shown), 10:15 daily
15 10 * * * /opt/basestation/bin/python /usr/local/basestation3/ssh/MakeKMLSSHMissions.py \
    --verbose /home/ssh/data /home/jails/sams/gliderjail/home/missions.yml \
    >> /home/jails/sams/gliderjail/home/rundir/MakeKML.log 2>&1
```

It also replaces the earlier version of these units on iopbase3, which ran
as `ioprunner:gliders` over `/home/seaglider/home/missions.yml` only.

## How the KML job finds missions and who writes them

`MakeKMLSSHMissions.py` is given the **master** missions.yml
(`/home/seaglider/home/missions.yml`), the same file vis.py serves:

- Its own `missions:` list is read, and each `domains:` (or `includes:`)
  entry is followed into that group's own missions.yml, recursively. Mission
  paths under a domain are resolved against the domain's `root:` if set,
  else against that domain file's directory. A mission with no `path:` is
  `sgNNN`.
- A mission is active if it has no `status:`, or `status: active`.
- Each active mission is assigned to the site in `/home/admin/sites.yml`
  (BaseRunnerMulti format) whose tree contains the mission directory. A
  site's tree is its `jail_root` if set, else the parent of its `watch_dir`.
  If several sites' trees match, the deepest one wins.
- An active mission under no site's tree is logged as a WARNING and skipped.
  It is never written as baserunner.

Each site's missions are then processed by a short-lived child
(`MakeKMLSSHMissions.py --site_child <site>`, with the missions as JSON on
stdin) started **as that site's `runner_user`**. Its supplementary groups,
gid and uid are set before the child starts. So KMZ files, MakeKML.py runs
(`--mergessh`, the default) and their `makekml_*` logs are all owned by the
group's runner, as they were under the per-jail cron jobs. Sites run one at
a time. Add `--jobs N` to the worker's `ExecStart` to run up to N at once.
Each child empties its capability sets before doing anything else, so
neither it nor MakeKML.py keeps the worker's CAP_SETUID/CAP_SETGID.

### Without a sites file

`--sites_config` is optional. Without it, `MakeKMLSSHMissions.py` behaves
as it did before sites.yml support:
- It reads only the given missions.yml's own `missions:` list.
  `domains:`/`includes:` aren't followed, and entries without a `path:` are
  skipped.
- It processes every active mission in-process, as whoever runs it. There
  are no site children, and no capabilities are needed.

That is how the per-jail cron jobs used it, and it still works for a single
group run from its runner's crontab or its own unit. The one difference
from before is the exit status: it's 1 if any mission fails, where it used
to be 0.

## Units

Ten unit/script files, all in this directory:

- `aviso-fetch.timer` / `aviso-fetch-trigger.service` /
  `aviso-fetch-worker.service`: fire daily at 10:00. The trigger starts the
  worker with `--job-mode=fail`. If the previous run is still going, this
  call is refused outright (visible as a failed unit in `systemctl status`
  and the journal) instead of queueing or overlapping. See
  `../local/systemd-timer-overlap-protection-handoff.md` for the design
  rationale (written for `BaseSMS.py`, but the pattern is identical here).
- `makekml-ssh.timer` / `makekml-ssh-trigger.service` /
  `makekml-ssh-worker.service`: the same pattern, firing daily at 10:15, 15
  minutes after `aviso-fetch.timer`, so the SSH data is already fetched.
  The worker has `AmbientCapabilities=CAP_SETUID CAP_SETGID`, which it needs
  to start each site's child as that site's runner.
- `report_makekml_errors.py`: a daily journal scan for ERROR/WARNING/
  CRITICAL entries from *both* worker units, combined into one emailed
  report. It also scans both `*-trigger.service` units' journals and reports
  any cycles skipped by the overlap protection.
- `makekml-error-report.service` / `makekml-error-report.timer`: run that
  scan once a day, at 11:00.

All three `.service` workers run as `baserunner:baserunner`.

## Install

```bash
# 1. The baserunner account (already present on hosts running
#    BaseRunnerMulti; otherwise create it without a home directory), with
#    journal read access for `journalctl -u ...` and report_makekml_errors.py:
sudo useradd --system --no-create-home --shell /usr/sbin/nologin baserunner  # if missing
sudo usermod -a -G systemd-journal baserunner

# 2. baserunner owns the shared SSH data. The fetch unit's UMask=0022 keeps
#    new files world-readable, so every site runner can read them:
sudo chown -R baserunner:baserunner /home/ssh/data
sudo chmod -R a+rX /home/ssh/data

# 3. Copernicus credentials (copernicus_user / copernicus_passwd, read by
#    AvisoUtils.py): readable by baserunner only.
sudo chown baserunner:baserunner /usr/local/basestation3/ssh/config.py
sudo chmod 640 /usr/local/basestation3/ssh/config.py

# 4. baserunner must be able to read /home/admin/sites.yml and the master
#    /home/seaglider/home/missions.yml (plus every domain missions.yml it
#    points at). Check:
sudo -u baserunner cat /home/admin/sites.yml /home/seaglider/home/missions.yml > /dev/null

# 5. Copy all eight unit files to /etc/systemd/system/. The scripts should
#    already be in /usr/local/basestation3/ssh/ if this is a checkout of the
#    repo at that path.
sudo cp aviso-fetch.timer aviso-fetch-trigger.service aviso-fetch-worker.service \
        makekml-ssh.timer makekml-ssh-trigger.service makekml-ssh-worker.service \
        makekml-error-report.service makekml-error-report.timer \
        /etc/systemd/system/

# 6. Reload and enable all three timers (not the .service units directly).
sudo systemctl daemon-reload
sudo systemctl enable --now aviso-fetch.timer makekml-ssh.timer makekml-error-report.timer

# 7. Run each job once by hand and check it
sudo systemctl start aviso-fetch-trigger.service
journalctl -u aviso-fetch-worker.service --since -10min
sudo systemctl start makekml-ssh-trigger.service
journalctl -u makekml-ssh-worker.service --since -10min
# Each site logs "<site>: processing N mission(s) as <runner>" then "<site>: done".
# Spot-check that a mission's new KMZ is owned by its group's runner:
ls -l /home/jails/<group>/gliderjail/home/sgNNN/*.kmz
systemctl list-timers aviso-fetch.timer makekml-ssh.timer makekml-error-report.timer
```

### Migrating iopbase3

iopbase3 already runs these units as `ioprunner:gliders`. Reinstall them
(steps 1-7). Ownership of `/home/ssh/data` moves from ioprunner to
baserunner (step 2). Mission directories are written by each site's
`runner_user` from sites.yml, so if that is still ioprunner for the
seaglider site (as in `docs/sites.example.yaml`), nothing changes for them.

The worker reads `/home/admin/sites.yml`, but BaseRunnerMulti on iopbase3
reads `/usr/local/basestation3/etc/sites.yaml`. Either make
`/home/admin/sites.yml` a symlink to that file, or change the worker's
`--sites_config`, so both read the same list.

### Migrating seaglider.pub

After steps 1-7 have run cleanly for a day, remove the old cron jobs:

```bash
# The fetch job, from gbs's own crontab:
crontab -e    # delete the AvisoUtils.py line

# The per-jail KML job, from EACH jail runner's crontab:
sudo crontab -u <runner> -e    # delete the MakeKMLSSHMissions.py line

# Old log files, no longer written:
rm /home/gbs/MakeKML.log
rm /home/jails/*/gliderjail/home/rundir/MakeKML.log
```

Use `/home/admin/bin/update_jails.py --dry_run` to list the jailed sites,
so you know which runner crontabs to check.

## Running the error report by hand

```bash
# Print the last day's report instead of emailing it:
python3 report_makekml_errors.py --dry-run

# Scan a different window, or suppress the email when clean:
python3 report_makekml_errors.py --since -7days --only-if-errors
```

By default it emails a report to ioplog@uw.edu every day even when no
errors were found (so a missing daily email itself signals something's
wrong with the pipeline, not just with the MakeKML jobs); pass
`--only-if-errors` to only send when there's something to report.

## Troubleshooting

- `aviso-fetch.timer: Refusing to start, unit aviso-fetch.service to
  trigger not loaded.` (or the same for `makekml-ssh.timer`) — a timer
  activates the unit with its own base name by default
  (`aviso-fetch.service`), but the unit to trigger here is
  `aviso-fetch-trigger.service`. The timer's `[Timer]` section carries an
  explicit `Unit=...-trigger.service` to override that; if this error
  reappears, that line was dropped or the installed copy predates it --
  re-copy the `.timer` file to `/etc/systemd/system/` and `daemon-reload`.
- `...-worker.service: Failed at step USER/GROUP spawning ...` (exit code
  217/USER or 216/GROUP): the `baserunner` account or group doesn't exist
  on this host. See step 1 in Install above.
- `CRITICAL: <site>: unable to run as <runner> - the worker needs CAP_SETUID
  and CAP_SETGID`: the installed `makekml-ssh-worker.service` is missing its
  `AmbientCapabilities=`/`CapabilityBoundingSet=` lines. Re-copy it and
  `daemon-reload`. The same error appears when running
  `MakeKMLSSHMissions.py` by hand as baserunner without them. Use
  `sudo systemd-run --uid=baserunner -p AmbientCapabilities="CAP_SETUID CAP_SETGID" -p PrivateTmp=yes --pty ...`
  to run it by hand.
- `WARNING: sgNNN <path>: not under any site in /home/admin/sites.yml -
  skipping`: an active mission in the master missions.yml tree lives
  outside every site's tree. Either the mission's path or domain `root:` is
  wrong, or its group has no entry in sites.yml. Nothing is generated for it.
- `CRITICAL: Could not load sites from /home/admin/sites.yml`: the file is
  missing, unreadable by baserunner, or has a malformed entry or an unknown
  `runner_user`. The preceding ERROR line names the problem.
- `WARNING: No SSH data in /home/ssh/data newer than 5 days - nothing to
  do`: the fetch job hasn't succeeded recently. Check
  `journalctl -u aviso-fetch-worker.service`, including whether baserunner
  can read `ssh/config.py`.

## Checking for the overlap-protection collision

The daily error report (above) already includes any overlap-protection
refusals from both `*-trigger.service` units' journals, so this is only
needed for a real-time / ad-hoc check between reports:

```bash
# Did either trigger ever refuse to start its worker (i.e. a run took
# longer than a day)?
journalctl -u aviso-fetch-trigger.service | grep -i fail
journalctl -u makekml-ssh-trigger.service | grep -i fail
```
