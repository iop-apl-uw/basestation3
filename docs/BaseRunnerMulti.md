# BaseRunnerMulti: consolidated multi-site glider account runner

## Background

`BaseRunner.py` runs as one long-lived daemon per site, each started by
its own systemd unit as a distinct Linux account, watching that site's
rundir via inotify for `.run` files dropped by
`glider_login`/`glider_logout`, and dispatching
`BaseLogin.py`/`GliderEarlyGPS.py`/`Base.py` accordingly. This works fine
for a handful of sites, but as the number of sites on one host grows,
having that many processes fork simultaneously at boot causes CPU
contention and systemd watchdog timeouts. `BaseRunnerMulti.py` fixes this
at the root by replacing all of those per-site processes with **one**
consolidated process that watches every site with a single `inotify`
instance and a single event loop - eliminating the boot storm entirely,
rather than smoothing it over with systemd-level staggering/throttling.
Even on a host with only two or three sites, it's still worth it for the
single audit trail and single log stream alone.

`BaseRunner.py` itself is unchanged in behavior and still supported -
sites migrate to `BaseRunnerMulti.py` one at a time by repointing that
site's systemd unit, with instant per-site rollback if needed (see
"Migrating a site" below).

## Architecture

Three files, three responsibilities:

- **`SiteConfig.py`** - shared `sites.yaml` schema and loader. Both
  processes below load their own copy of the site table independently,
  from the same file, at their own startup, so the two processes can
  never observe different data for the same site.

- **`BaseRunnerMulti.py`** - the watcher/dispatcher daemon. Watches every
  active site's rundir (`SiteRegistry`), parses `.run` files, and manages
  the per-`(site, mission_dir, script, glider)` job queues
  (`Dispatcher`) - the direct multi-site generalization of `BaseRunner.py`'s
  own event loop. This process runs as a dedicated, non-root `baserunner`
  account, which must be a member of every site's group (the same way
  this org's admin accounts already are) so it can read every site's
  rundir. It **never** launches a job directly and **never** holds any
  special privilege - launching is delegated to...

- **`BaseRunnerPrivExec.py`** - a small, separately-auditable privileged
  helper. It is the *only* process that holds `CAP_SETUID`/`CAP_SETGID`
  (granted narrowly via its systemd unit's `AmbientCapabilities=`, never
  via `sudo` and never as root - see "Privilege model" below). It serves
  requests from `BaseRunnerMulti.py` over a local UNIX socket, each
  request naming a site (never a uid/gid), forks, drops privilege to
  that site's own `runner-<site>` account, and execs the job - so the
  job's file ownership ends up exactly as it would under today's
  per-site `BaseRunner.py` model.

```
                    ┌─────────────────────┐
  sites.yaml ──────▶│   BaseRunnerMulti    │  runs as: baserunner
                    │  (watcher/dispatch)  │  (member of every site's group,
                    └──────────┬───────────┘   no special capability)
                               │ UNIX socket
                               │ {"site": "seaglider", "argv": [...], "log_file": ...}
                               ▼
                    ┌─────────────────────┐
  sites.yaml ──────▶│  BaseRunnerPrivExec  │  runs as: baserunner
                    │  (privileged helper) │  (CAP_SETUID + CAP_SETGID only)
                    └──────────┬───────────┘
                               │ fork + setgroups/setgid/setuid + exec
                               ▼
                     job runs as runner-<site>
```

## Privilege model

Site isolation in this deployment is fundamentally **group-based**: each
site's directory tree is owned by that site's own group, with `o-rwx` (no
access for anyone outside the group) - mirroring how this org's non-root
admin accounts already work (member of every site's group, gated by
password-required `sudo` for anything beyond ordinary group-permitted file
access).

`BaseRunnerMulti.py` (the watcher) needs read/write access to every site's
rundir just to watch and parse `.run` files - giving it membership in
every site's group is sufficient for that, no special capability required.

Launching a job as a *specific* site's `runner-<site>` account is a
different problem: only a process holding `CAP_SETUID`/`CAP_SETGID` (or
running as root) can change its uid/gid. Rather than run the whole watcher
as root, or use `sudo` (which would mean carving a `NOPASSWD` exception
into an otherwise deliberately password-gated sudo policy, just for this
one unattended daemon), that narrow capability is isolated into
`BaseRunnerPrivExec.py` alone:

- `BaseRunnerPrivExec.py` never trusts a uid/gid from the request it
  receives - only a site *name*, looked up in its own table (loaded
  independently from `sites.yaml`, not from anything `BaseRunnerMulti.py`
  says). There is no code path by which a compromised watcher could ask
  the helper to become an arbitrary uid.
- The privilege drop, in the forked child, is `setgroups([gid])` →
  `setgid(gid)` → `setuid(uid)` → `exec`, in that exact order. Skipping
  `setgroups` is the dangerous, silent failure mode - the child would
  keep `baserunner`'s membership in *every* site's group, defeating the
  whole point of the drop.
- `CAP_SETUID` is not a "safe" subset of root - a process holding it can
  call `setuid(0)`. The safety margin here comes entirely from the
  helper's own code being small, separately reviewable, and never letting
  anything externally-influenced pick the target uid - not from the
  capability itself being weak.
- Neither process ever runs as root, at any point.

## `sites.yaml`

See [`sites.example.yaml`](sites.example.yaml) for a fully-commented
sample. Top-level mapping keyed by site name; each entry:

| Field | Required | Default | Meaning |
|---|---|---|---|
| `watch_dir` | yes | - | Rundir this site's `.run` files are watched for/consumed in. |
| `runner_user` | yes | - | This site's `runner-<site>` Linux account name, resolved to uid/gid via `pwd.getpwnam` at each process's own startup. |
| `jail_root` | no | `null` | Root of this site's glider jail, if any - used to rewrite paths written from inside the jail's view. |
| `archive` | no | `false` | Archive consumed `.run` files under `watch_dir/archive/` instead of deleting them. Only `ioptest` sets this today. |
| `ignore_lock` | no | `false` | Bypass this site's lock-file check. Testing only - never set `true` in production. |
| `python_version` | no | `/opt/basestation/bin/python` | Interpreter used to launch this site's jobs. |
| `queue_scripts` | no | `true` | Queue known scripts for async dispatch. Leave `true` - `false` blocks the *shared* event loop for every site, not just this one. |
| `docker_image` | no | `""` | Docker image to launch `Base.py` under, if used. |
| `docker_uid` / `docker_gid` | no | `-1` | uid/gid to run the docker container as. |
| `use_docker_basestation` | no | `false` | Use the basestation install baked into the docker image instead of mounting this checkout. |
| `cpu_quota_pct` | no | `null` | Hard CPU cap for this site's jobs, as a percentage of one core (e.g. `60` -> 60%). See "Per-site CPU throttling" below. |
| `cpu_weight` | no | `null` | Relative cgroup `CPUWeight` for this site's jobs (systemd default is 100 when unset). |

Loading is **fail-closed**: any single malformed or unresolvable entry
(e.g. an unknown `runner_user`) aborts loading the whole file rather than
silently dropping just that one site - a typo should be loud (the process
refuses to start) rather than a silent per-site regression.

A missing `watch_dir` for an otherwise-valid site is different: that site
is logged and left pending rather than failing the whole process, and
`BaseRunnerMulti.py` retries pending sites periodically (once per minute)
so a site coming online later doesn't require a daemon restart.

## Per-site CPU throttling

The one-process-per-site `BaseRunner.py` model got per-site CPU isolation
for free: each site was already its own systemd unit/cgroup, and a
runaway site's process couldn't starve another site's, since they were
never in the same cgroup to begin with. Consolidating into one process
loses that for free lunch - a unit-level `CPUQuota` on `BaseRunnerMulti`'s
own unit would cap the *combined* total of every site's jobs together,
not each site individually.

`BaseRunnerPrivExec.py` restores it: since it already forks a child
per dispatched job before dropping privilege, that child joins a
site-scoped delegated cgroup (`CgroupJoiner`) while still running as the
unprivileged `baserunner` account, writing `cpu.max`/`cpu.weight` from a
site's `cpu_quota_pct`/`cpu_weight` config, then drops privilege and execs
- remaining in the cgroup it already joined (cgroup membership is
independent of uid). This is fail-open by design: any failure to join or
configure the cgroup is logged and the job still launches unthrottled -
throttling must never be able to prevent a job from running at all.

This requires the helper's own systemd unit to delegate a cgroup subtree
to it (`Delegate=yes`, see the unit example below) and `--cgroup_root` to
point at that subtree. Neither field is set by default (`cpu_quota_pct`/
`cpu_weight` both default to `null`, meaning unthrottled) - only set them
for a site that's shown to actually need it.

## Deployment

Both processes need their own systemd unit. Neither should ever run as
root.

```ini
# /etc/systemd/system/baserunnerprivexec.service
[Unit]
Description=Privileged exec helper for BaseRunnerMulti
After=network.target

[Service]
User=baserunner
Group=baserunner
AmbientCapabilities=CAP_SETUID CAP_SETGID
CapabilityBoundingSet=CAP_SETUID CAP_SETGID
# Delegates a cgroup subtree to this unit so CgroupJoiner can create
# per-site child cgroups and write cpu.max/cpu.weight/cgroup.procs
# without needing any additional Linux capability.
Delegate=yes
ExecStart=/opt/basestation/bin/python /usr/local/basestation3/BaseRunnerPrivExec.py \
    --sites_config /usr/local/basestation3/etc/sites.yaml \
    --priv_exec_socket /run/baserunner/priv_exec.sock \
    --cgroup_root /sys/fs/cgroup/system.slice/baserunnerprivexec.service \
    --base_log /var/log/baserunner-privexec.log
RuntimeDirectory=baserunner
Restart=always

[Install]
WantedBy=multi-user.target
```

```ini
# /etc/systemd/system/baserunnermulti.service
[Unit]
Description=Consolidated multi-site glider account runner
After=network.target baserunnerprivexec.service
Requires=baserunnerprivexec.service

[Service]
User=baserunner
Group=baserunner
ExecStart=/opt/basestation/bin/python /usr/local/basestation3/BaseRunnerMulti.py \
    --sites_config /usr/local/basestation3/etc/sites.yaml \
    --priv_exec_socket /run/baserunner/priv_exec.sock \
    --base_log /var/log/baserunnermulti.log
WatchdogSec=30
Restart=always
Type=notify

[Install]
WantedBy=multi-user.target
```

The `baserunner` account itself needs to be created and added to every
site's group before either unit starts - it plays the same role as this
org's existing admin accounts (broad group membership, no special
capability of its own). Neither unit is enabled by this repo; both are
infra-level artifacts for whoever operates the deployment.

**Validate the capability chain before relying on it in production** -
this is an easy corner of Linux privilege separation to get subtly wrong.
On a scratch host: start `baserunnerprivexec.service`, then
`getpcaps $(pgrep BaseRunnerPrivExec)` to confirm it holds exactly
`cap_setuid,cap_setgid` and nothing else, and drop a `.run` file into a
real site's rundir to confirm the resulting job's output files are owned
by that site's `runner-<site>` uid/gid, not `baserunner`.

If using per-site CPU throttling, validate that chain too: with
`cpu_quota_pct`/`cpu_weight` set for a test site, confirm
`/sys/fs/cgroup/.../baserunnerprivexec.service/site-<name>/cgroup.procs`
actually contains the dispatched job's pid after it launches, and that
`cpu.max`/`cpu.weight` under that path match what `sites.yaml` asked for
- `Delegate=yes` and cgroup v2 write permissions are worth confirming
empirically rather than trusting the derivation in "Per-site CPU
throttling" above.

## Migrating a site

Sites move from `BaseRunner.py` to `BaseRunnerMulti.py` one at a time,
manually - there is no automatic takeover:

1. **Stop and disable that site's old `baserunner-<site>@.service`
   unit first** - `sudo systemctl stop baserunner-<site>@runner-<site>.service`
   then `disable`, in that order. This step is required: both processes
   use the same lock-file name (`.base_runner_lockfile`) as
   `BaseRunner.py`, and `BaseRunnerMulti.py` will not evict or signal
   whatever still holds it - if the old unit is still running when
   `BaseRunnerMulti.py` starts watching that site, it detects the live
   lock, logs an error, and leaves the site pending (retried on its
   normal interval) until an operator stops the old unit. `disable`
   matters too: every unit in this system, old and new, has
   `Restart=always`, so a bare `stop` without `disable` risks the old
   unit coming back on its own later.
2. Add the site's entry to `sites.yaml` (or confirm it's already there -
   `BaseRunnerMulti.py` can be started with a partial `sites.yaml` and
   will pick up new sites on its periodic retry, no restart needed to
   pick up a *new* site once it's already running - though `sites.yaml`
   is only read once at startup today, so an already-running instance
   won't see edits to *existing* entries or removed sites without a
   restart).
3. Confirm `BaseRunnerMulti.service`/`baserunnerprivexec.service` are
   running (or start them, if this is the very first site migrated). If
   they were already running, the site is picked up on the next retry
   pass once step 1's lock is clear - no restart needed.

Rollback is the reverse: stop `BaseRunnerMulti.py`'s watch of that site
(or the whole process, if only one site is affected), then re-enable and
start the old per-site unit.

## Operational notes

- `BaseRunnerMulti.py`'s log lines are prefixed `[site_name]` so a single
  combined log file stays greppable per site - this is the main day-to-day
  cost of consolidation (one file instead of twenty).
- `BaseRunnerPrivExec.py` logs to its **own** file, separate from the
  watcher's - the audit trail of "who was granted which uid/gid, when"
  shouldn't be interleaved with or lost among the much higher-volume
  watcher log.
- Job-queue keys and vis.py's `queue_id` payloads now include the site
  name (`{site}||{mission_dir}||{script}`) - if anything downstream
  parses `queue_id` as an opaque two-part string, confirm it tolerates
  the added prefix before relying on it.
