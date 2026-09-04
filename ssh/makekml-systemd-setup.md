# MakeKML SSH jobs: systemd timers + daily error report

Replaces three crontab entries on iopbase3:

```
# gbs, 10:00 daily
0 10 * * * /opt/basestation/bin/python /usr/local/basestation3/ssh/AvisoUtils.py \
    --delete_older 30 --verbose /home/ssh/data >> /var/log/MakeKML.log 2>&1

# ioprunner, 10:15 daily
15 10 * * * /opt/basestation/bin/python /usr/local/basestation3/ssh/MakeKMLSSHMissions.py \
    --verbose /home/ssh/data /home/seaglider/home/missions.yml >> /var/log/MakeKML.log 2>&1

# gbs, 11:00 daily
0 11 * * * /opt/basestation/bin/python /home/gbs/basestation/bin/scan_makekml_errors.py \
    --since-days 1.0 --only-if-errors /var/log/MakeKML.log
```

with three systemd timers, all running as `ioprunner:gliders`, logging to
the journal instead of `/var/log/MakeKML.log`, plus a daily emailed error
report covering both jobs.

Ten unit/script files, all in this directory:

- `aviso-fetch.timer` / `aviso-fetch-trigger.service` /
  `aviso-fetch-worker.service` — fires daily at 10:00, same as the old cron
  job. The trigger starts the worker with `--job-mode=fail`: if the
  previous run is still going, this call is refused outright (visible as a
  failed unit in `systemctl status` / the journal) instead of queueing or
  overlapping. See `../local/systemd-timer-overlap-protection-handoff.md`
  for the full design rationale (written for `BaseSMS.py`, but the pattern
  is identical here).
- `makekml-ssh.timer` / `makekml-ssh-trigger.service` /
  `makekml-ssh-worker.service` — same pattern, fires daily at 10:15 (15
  minutes after `aviso-fetch.timer`, same as before, so the SSH data is
  already fetched).
- `report_makekml_errors.py` — daily journal scan for ERROR/WARNING/
  CRITICAL entries from *both* worker units (journalctl equivalent of
  `~/work/git/basestation/bin/scan_makekml_errors.py`), combined into one
  emailed report — matching the old setup where both jobs shared one
  `MakeKML.log` and one daily scan. Also scans both `*-trigger.service`
  units' journals and reports any cycles skipped by the fail-fast overlap
  protection (previous run still active).
- `makekml-error-report.service` / `makekml-error-report.timer` — run that
  scan once a day, at 11:00 (same time as the old cron job).

## Install

```bash
# 1. Copy all eight unit files to /etc/systemd/system/, and both scripts to
#    /usr/local/basestation3/ssh/ (they should already be there if this is
#    a checkout of the repo at that path).
sudo cp aviso-fetch.timer aviso-fetch-trigger.service aviso-fetch-worker.service \
        makekml-ssh.timer makekml-ssh-trigger.service makekml-ssh-worker.service \
        makekml-error-report.service makekml-error-report.timer \
        /etc/systemd/system/

# 2. Confirm the ioprunner account exists, is in the gliders group (for
#    read/write access to /home/ssh/data and /home/seaglider/...), and can
#    read the system journal (needed for `journalctl -u ...` in step 5
#    below, and by report_makekml_errors.py):
sudo usermod -a -G gliders,systemd-journal ioprunner

# 3. Reload and enable all three timers (not the .service units directly).
sudo systemctl daemon-reload
sudo systemctl enable --now aviso-fetch.timer makekml-ssh.timer makekml-error-report.timer

# 4. Verify
systemctl list-timers aviso-fetch.timer makekml-ssh.timer makekml-error-report.timer
systemctl status aviso-fetch-trigger.service aviso-fetch-worker.service
systemctl status makekml-ssh-trigger.service makekml-ssh-worker.service
journalctl -u aviso-fetch-worker.service -f    # follow live
journalctl -u makekml-ssh-worker.service -f    # follow live

# 5. Remove the three old crontab entries (crontab -e for both gbs and
#    ioprunner) and the old /var/log/MakeKML.log once you've confirmed the
#    timers are running cleanly.
```

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
- `...-worker.service: Failed at step GROUP spawning ...: No such process`
  (exit code 216/GROUP) — `ioprunner` doesn't have a `gliders` group
  membership matching `Group=gliders` in the worker units, or the
  `gliders` group doesn't exist on this host. See step 2 in Install above.

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
