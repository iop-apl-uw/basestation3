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
| `jail_root` | no | `null` | Extra allowed root for this site's directory-tree containment check, alongside `watch_dir`. Also the rewrite target for `.run`-file paths when `jailed` is true. |
| `jailed` | no | whether `jail_root` is set | Whether this site's glider account runs inside a real chroot jail, so `.run`-file paths need rewriting against `jail_root`. A site that isn't jailed but still wants a containment root wider than `watch_dir` must set this `false` explicitly alongside `jail_root` - see "Unjailed sites and `jail_root`" below. |
| `archive` | no | `false` | Archive consumed `.run` files under `watch_dir/archive/` instead of deleting them. Only `ioptest` sets this today. |
| `ignore_lock` | no | `false` | Bypass this site's lock-file check. Testing only - never set `true` in production. |
| `python_version` | no | `/opt/basestation/bin/python` | Interpreter used to launch this site's jobs. |
| `queue_scripts` | no | `true` | Queue known scripts for async dispatch. Leave `true` - `false` blocks the *shared* event loop for every site, not just this one. |
| `docker_image` | no | `""` | Docker image to launch `Base.py` under, if used. |
| `docker_uid` / `docker_gid` | no | `-1` | uid/gid to run the docker container as. |
| `use_docker_basestation` | no | `false` | Use the basestation install baked into the docker image instead of mounting this checkout. |
| `cpu_quota_pct` | no | `null` | Hard CPU cap for this site's jobs, as a percentage of one core (e.g. `60` -> 60%). See "Per-site CPU throttling" below. |
| `cpu_weight` | no | `null` | Relative cgroup `CPUWeight` for this site's jobs (systemd default is 100 when unset). |
| `memory_high_mb` | no | `null` | Soft memory cap (systemd `MemoryHigh`-equivalent) for this site's jobs, in MiB, written to each job's own `memory.high`. See "Per-site memory limits" below. |
| `memory_max_mb` | no | `null` | Hard memory cap (systemd `MemoryMax`-equivalent) for this site's jobs, in MiB; crossing it triggers the kernel OOM killer scoped to that one job's own cgroup. See "Per-site memory limits" below. |

Loading is **fail-closed**: any single malformed or unresolvable entry
(e.g. an unknown `runner_user`) aborts loading the whole file rather than
silently dropping just that one site - a typo should be loud (the process
refuses to start) rather than a silent per-site regression.

A missing `watch_dir` for an otherwise-valid site is different: that site
is logged and left pending rather than failing the whole process, and
`BaseRunnerMulti.py` retries pending sites periodically (once per minute)
so a site coming online later doesn't require a daemon restart.

### Unjailed sites and `jail_root`

`jail_root` does two unrelated jobs, and `jailed` is what tells them apart:

1. It's an extra root `BaseRunnerPrivExec.validate_dispatch_request` accepts
   a job's `log_file` under, alongside `watch_dir` - this is the boundary
   the privileged helper enforces before it will touch a path at all.
2. When `jailed` is true, it's *also* the real filesystem root `.run`-file
   paths get rewritten against, because those paths were written from
   inside a chroot jail's own view of the filesystem and need translating
   back to their real, outside-the-jail location.

Every real deployment today uses a real chroot jail, so `jailed` defaults
to whether `jail_root` is set and existing `sites.yaml` files need no
change. But a site with unjailed glider accounts living directly under
some shared root (e.g. several `sgNNN` home directories under `/home`,
with no chroot at all) still needs a `jail_root` wider than `watch_dir` for
the containment check to accept their paths - and setting one without
`jailed: false` silently corrupts every dispatch, since `.run`-file paths
there are already real, absolute host paths and don't need (or survive)
the jail rewrite: prepending `jail_root` a second time turns
`/home/sg090/.../baselog.log` into `/home/home/sg090/.../baselog.log`,
which then fails to open. For that case, set both fields explicitly:

```yaml
test:
  watch_dir: /home/rundir
  jail_root: /home
  jailed: false
  runner_user: sg090-runner
```

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

## Per-site memory limits

Memory can't reuse CPU throttling's shared, site-level cgroup. CPU quota
degrades gracefully under contention - N concurrent jobs for the same
site sharing one quota each get roughly `1/N` of it, nobody gets killed.
A shared `memory.max` doesn't degrade the same way: once the *combined*
usage of everything in that cgroup crosses the limit, the kernel's cgroup
OOM killer picks a victim from whatever's in there - which could be an
unrelated sibling job for the same site, killed purely as collateral
damage from a different job's overrun.

So every dispatched job gets its own leaf cgroup,
`site-<name>/job-<job_id>`, nested under the existing site cgroup. This
leaf is created **unconditionally** - even for a site with no
`memory_high_mb`/`memory_max_mb` configured - purely so `memory.current`
is always readable there for tracking. `memory_high_mb`/`memory_max_mb`
only add the `memory.high`/`memory.max` writes on top of that leaf; a
fresh cgroup's own `memory.max`/`memory.high` already default to `max`
(the kernel's literal "unlimited") until written, so leaving these
`null` reproduces "off" for free - no separate on/off flag is needed.

The site-level aggregate view comes for free too: cgroup v2 always rolls
a parent's accounting up from its children, so `site-<name>/memory.current`
is automatically the sum of that site's concurrently-running jobs, with
no extra code.

`BaseRunnerMulti.py` reads (never writes) `memory.current`/`memory.peak`
under its own `--cgroup_root`, which must match
`baserunnerprivexec.service`'s `--cgroup_root` exactly, or memory
reporting silently reads nothing - fail-open, like every other cgroup
failure mode here, not fatal.

**Deploy `baserunnerprivexec.service` and `baserunnermulti.service`
together** when rolling this out (or `baserunnermulti.service` first) -
dispatch requests now carry a `job_id` that older `BaseRunnerMulti.py`
builds never sent, so an upgraded `baserunnerprivexec.service` paired
with an old `baserunnermulti.service` rejects every dispatch until both
are upgraded. The reverse order is safe: an old `baserunnerprivexec.service`
just ignores the unknown `job_id` key.

**Expected transient warning right after an upgrade restart**: a job
dispatched under the *old* code that survives a
`baserunnerprivexec.service` restart (`KillMode=process` lets it, see
above) is still a direct member of `site-<name>` itself, not a
`job-<job_id>` leaf. Until that straggler exits, any *new* dispatch for
that same site fails to enable `memory` on `site-<name>`'s own
`cgroup.subtree_control` (cgroup v2 refuses that while the cgroup still
has member processes) and falls into `CgroupJoiner.join`'s existing
fail-open path - logged as a `WARNING`, the new job runs
untracked/unthrottled until the straggler drains. Self-healing, not a
bug.

## Deployment

Both processes need their own systemd unit. Neither should ever run as
root.

Ready-to-copy unit files live alongside this doc:
[`baserunnerprivexec.service`](baserunnerprivexec.service) and
[`baserunnermulti.service`](baserunnermulti.service), plus a
[`baserunner.logrotate`](baserunner.logrotate) config for
`/etc/logrotate.d/` - these are the actual files to copy onto a target
host (see "Installing the units" below), not just illustrative
snippets, so keep them and this doc in sync if any of them changes.

```ini
# docs/baserunnerprivexec.service
[Unit]
Description=Privileged exec helper for BaseRunnerMulti
After=network.target

[Service]
User=baserunner
Group=baserunner
# baserunner has no home directory (--no-create-home), so matplotlib's
# default $HOME/.config/matplotlib cache dir isn't writable; it falls
# back to a throwaway /tmp dir with a startup warning if left unset.
CacheDirectory=baserunner
Environment=MPLCONFIGDIR=/var/cache/baserunner
AmbientCapabilities=CAP_SETUID CAP_SETGID
CapabilityBoundingSet=CAP_SETUID CAP_SETGID
Delegate=yes
# Nests this unit under baserunner.slice instead of directly under
# system.slice - see "KillMode and in-flight jobs" below for why this
# (not DelegateSubgroup=, which doesn't work on systemd < 254) is what
# actually keeps restarts working once any job has ever been dispatched.
Slice=baserunner.slice
# Idempotent bootstrap, runs as root (the "+" prefix) regardless of this
# unit's own User=baserunner: makes baserunner.slice's own cgroup
# writable by baserunner and enables cpu/memory there, one level up from
# where CgroupJoiner creates per-site (site-<name>) and per-job
# (site-<name>/job-<job_id>) child cgroups.
ExecStartPre=+/bin/sh -c 'mkdir -p /sys/fs/cgroup/baserunner.slice && chown -R baserunner:baserunner /sys/fs/cgroup/baserunner.slice && echo "+cpu +memory" > /sys/fs/cgroup/baserunner.slice/cgroup.subtree_control'
ExecStart=/opt/basestation/bin/python /usr/local/basestation3/BaseRunnerPrivExec.py \
    --sites_config /usr/local/basestation3/etc/sites.yaml \
    --priv_exec_socket /run/baserunner/priv_exec.sock \
    --cgroup_root /sys/fs/cgroup/baserunner.slice \
    --base_log /var/log/baserunner/baserunner-privexec.log
RuntimeDirectory=baserunner
# Creates /var/log/baserunner/ owned baserunner:baserunner (mode 0750) on
# every start, recreating it if it's ever missing - no manual mkdir/chown
# of the log directory needed. Requires systemd >= 235.
LogsDirectory=baserunner
# BaseRunnerPrivExec.py calls sd_notify(READY=1) only after its socket is
# bound and listening - this makes baserunnermulti.service's
# Wants=/After= on this unit an actual readiness guarantee, not just
# "the process was forked". Without Type=notify here, systemd considers
# this unit started the instant ExecStart's process exists, so the
# watcher could start and try to dispatch through a socket that doesn't
# exist yet - seen in production as a PrivExecError connecting to
# priv_exec.sock right after boot.
Type=notify
Restart=always
# See "KillMode and in-flight jobs" below.
KillMode=process

[Install]
WantedBy=multi-user.target
```

```ini
# docs/baserunnermulti.service
[Unit]
Description=Consolidated multi-site glider account runner
After=network.target baserunnerprivexec.service
# Wants=, not Requires=: pulls baserunnerprivexec.service in and (via
# After= above) orders this unit's start after it, but unlike Requires=
# does not stop this unit whenever baserunnerprivexec.service is stopped
# or restarted - see "Deployment" below.
Wants=baserunnerprivexec.service

[Service]
User=baserunner
Group=baserunner
# baserunner has no home directory (--no-create-home), so matplotlib's
# default $HOME/.config/matplotlib cache dir isn't writable; it falls
# back to a throwaway /tmp dir with a startup warning if left unset.
CacheDirectory=baserunner
Environment=MPLCONFIGDIR=/var/cache/baserunner
ExecStart=/opt/basestation/bin/python /usr/local/basestation3/BaseRunnerMulti.py \
    --sites_config /usr/local/basestation3/etc/sites.yaml \
    --priv_exec_socket /run/baserunner/priv_exec.sock \
    --cgroup_root /sys/fs/cgroup/baserunner.slice \
    --base_log /var/log/baserunner/baserunnermulti.log
# Read-only: only used to read memory.current/memory.peak for per-job
# memory tracking (see "Per-site memory limits" above) - must match
# baserunnerprivexec.service's own --cgroup_root exactly.
LogsDirectory=baserunner
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

Both units log to `--base_log` paths under `/var/log/baserunner/`, not
directly under `/var/log/` - `/var/log/` itself is root-owned and not
group-writable, so a bare `logging.FileHandler(opts.base_log)` running as
`baserunner` can't create a log file there (`PermissionError: [Errno 13]
Permission denied`, seen the first time a fresh `baserunner` account
starts either unit). Rather than a one-time manual `mkdir`/`chown` -
which then has to be re-done by hand if the directory is ever deleted
(log-cleanup script, disk migration, container rebuild) - both units
declare `LogsDirectory=baserunner`, which makes systemd itself create
`/var/log/baserunner/` owned `baserunner:baserunner`, mode `0750`, fresh
on every unit start. Nothing needs to pre-create or `chown` that
directory by hand.

Both units also set `CacheDirectory=baserunner` +
`Environment=MPLCONFIGDIR=/var/cache/baserunner` for the same reason:
`baserunner` has no home directory (`--no-create-home`), so anything
importing `matplotlib` (transitively, via the plotting code these
daemons dispatch into) can't write its default `$HOME/.config/matplotlib`
cache and falls back to a throwaway `/tmp/matplotlib-*` dir with a
startup warning every time - harmless, but avoidable the same
self-healing way as the log directory.

`baserunnerprivexec.service` is `Type=notify`, and `BaseRunnerPrivExec.py`
only calls `sd_notify(READY=1)` after its UNIX socket is bound and
listening (not on process start). This closes a real startup/restart
race: `baserunnermulti.service`'s `Wants=`/`After=` on this unit
orders the two units' *start jobs*, but for a plain `Type=simple` unit
systemd considers a unit "started" the instant its `ExecStart` process
exists - not once it's actually finished loading `sites.yaml` and binding
its socket. If a `.run` file was already waiting in a site's rundir at
boot, `BaseRunnerMulti.py` could reach its dispatch step before the
helper had opened `priv_exec.sock`, raising `PrivExecError: could not
reach privileged exec helper: [Errno 2] No such file or directory`. With
`Type=notify` here, systemd's ordering guarantee becomes real: the
watcher's start job doesn't begin until the helper has actually signaled
ready. This doesn't need a matching `WatchdogSec=` on this unit -
`baserunnermulti.service` already retries a dispatch that fails for any
reason (queued job goes back into `job_queues` rather than being
dropped - see the `Dispatcher._dispatch_one_queued` requeue-on-failure
path), so a slow-to-ready helper now just delays the first successful
dispatch instead of silently losing a job.

`baserunnermulti.service` declares `Wants=baserunnerprivexec.service`,
not `Requires=`. Both pull the named unit in and (combined with `After=`
above) order this unit's start after it - the difference only shows up on
*stop*: `Requires=` also stops this unit whenever
`baserunnerprivexec.service` is stopped, including an ordinary
`systemctl restart baserunnerprivexec.service` to pick up a
`sites.yaml`/cgroup edit (see "Installing the units" below) or a
unit-file change. Since `Requires=`'s stop-propagation isn't symmetric -
starting `baserunnerprivexec.service` again does *not* restart whatever
it took down - that silently left `baserunnermulti.service` stopped until
someone noticed and started it by hand (found on `madrona` while
validating the fixes above). `Wants=` keeps the readiness-ordering
guarantee on a cold start without that stop-propagation: restarting the
helper alone now just produces the same transient, requeued dispatch
failures described above, with `baserunnermulti.service` itself
untouched throughout. That description covers only jobs not yet
dispatched at restart time - a job already in flight when the helper
restarts is a separate case, covered next.

### `KillMode`, `Slice=`, and in-flight jobs

Every dispatched job is moved into its own `cgroup_root/site-<name>`
sub-cgroup (see `CgroupJoiner.join()`) - a child of `baserunner.slice`,
**not** of `baserunnerprivexec.service`'s own cgroup (see `Slice=` in the
unit above; this split is the whole point, explained below). Systemd's
default `KillMode=control-group` would SIGTERM/SIGKILL every process in
this unit's own cgroup on *any* stop of the unit, not just this unit's
own tracked process. `baserunnerprivexec.service` sets `KillMode=process`
to avoid that: a stop signals only the main process. `KillMode=mixed`
looks like a safer middle ground but isn't - confirmed on real hardware -
per `systemd.kill(5)`, `mixed` sends SIGTERM to only the main process but
still sends SIGKILL to every other process in the cgroup as soon as that
main process exits (not only as a `TimeoutStopSec` fallback). Only
`process` leaves other processes in the cgroup alone. The man page calls
`process` "not recommended" because it normally lets processes escape
the service manager's lifecycle by accident - here that's the deliberate,
intended design: dispatched jobs are meant to outlive this helper's own
restarts, tracked by `BaseRunnerMulti.py`'s own job-queue bookkeeping
instead.

**Why `Slice=baserunner.slice` exists, and why `DelegateSubgroup=` (the
obvious-looking alternative) doesn't work here**: cgroup v2's "no internal
process" rule means a cgroup cannot simultaneously hold a process
directly *and* have a controller enabled in its own `cgroup.subtree_control`
for children. `CgroupJoiner.join()` enables `cpu`/`memory` unconditionally
on `cgroup_root` (every site, not just throttled/memory-limited ones -
see "Per-site memory limits" above) the moment the *first* job is ever
dispatched to *any* site - and that enablement is permanent, nothing ever
unsets it. If `cgroup_root` were this unit's own cgroup (as it used to
be, before this split), then from that point on, *every* restart of
`baserunnerprivexec.service` - not just while a job is in flight - would
have systemd try to place the freshly started invocation's raw main
process directly into that same top level, which now permanently
violates the constraint. Confirmed on real hardware (Ubuntu 22.04/systemd
249, matching production) as a hard, repeatable `status=219/CGROUP` start
failure, not a rare race: 5 rapid restart attempts, then systemd's rate
limiter gave up and left the unit fully stopped until manually
recovered - worse than the original bug. `DelegateSubgroup=` (systemd >=
254) is the systemd-native fix for exactly this shape of problem, but it
does not help on systemd 249: the key is silently ignored
(`Unknown key name 'DelegateSubgroup' in section 'Service', ignoring'`),
so there is no working fallback for it on older hosts.

`Slice=baserunner.slice` fixes this structurally instead, on every
systemd version: nesting this unit *under* a slice means `cpu`/`memory`
get enabled on the *slice's* own `cgroup.subtree_control` (see
`ExecStartPre=` above) - one level **above** this unit's own cgroup, not
on it. A slice never has a "main process" of its own (nothing systemd
ever auto-places there), so it can safely delegate controllers to its
children - this unit's own cgroup, plus every `site-<name>` - forever,
with no restart-time conflict, because this unit's own cgroup itself
never has a controller enabled on it and never needs to. Confirmed
empirically (see `.claude/plans/2026-08-11-multipass-baserunner-validation.md`'s
successor investigation, 2026-09-16): a process already living inside a
`Delegate=yes`-chowned tree (placed there by root/systemd, exactly as
`ExecStartPre=`+`Slice=` do here) can freely create and migrate into
sibling cgroups within that same tree - which is exactly what
`CgroupJoiner.join()` needs to do from within the forked child. A benign
`"Found left-over process ... in control group ... Ignoring"` line in the
journal during a restart-while-job-active is expected - systemd noticing
the surviving job, not an error.

That fixes the kill, but not for free: `ChildTable`
(`BaseRunnerPrivExec.py`) is purely in-memory, per-process state with no
persistence across a restart, and the new process is never an ancestor
of the old instance's forked children, so it structurally cannot
`waitpid()` them - only a real parent can reap a process. A job that
survives a restart this way is invisible to the *new* helper process:
`BaseRunnerMulti.py`'s `_poll_one_completion` gets an authoritative
"unknown pid" rejection the next time it polls, logs one `WARNING` and a
matching line in the job's own log file, and drops it from tracking. The
job still runs to completion under its own identity - it just does so
with no returncode ever recorded, no timing line, and no vis
notification. This is a deliberate, bounded tradeoff (see `TODO.md` for
why reconciling orphaned jobs after a restart isn't done today) rather
than an oversight.

### Installing the units

Both unit files above are plain text, not templates - copy them in as-is
(adjusting only the paths if this host's checkout doesn't live at
`/usr/local/basestation3`) and drive them through the normal
copy/daemon-reload/enable/start sequence, in this order:

1. **Create the `baserunner` account and add it to every site's group.**
   This has to happen before either unit is started - `BaseRunnerMulti.py`
   resolves the group membership at its own startup, not on the fly.

   ```bash
   sudo useradd --system --no-create-home --shell /usr/sbin/nologin baserunner
   # repeat -aG for every site group listed in sites.yaml on this host
   sudo usermod -aG seaglider baserunner
   sudo usermod -aG ioptest baserunner
   ```

2. **Copy both unit files from `docs/` into `/etc/systemd/system/`.**
   Root-owned, mode `644`, same as any other system unit. Edit the
   `ExecStart=`/`--sites_config`/`--base_log` paths first if this host's
   checkout doesn't live at `/usr/local/basestation3`:

   ```bash
   sudo install -o root -g root -m 644 docs/baserunnerprivexec.service /etc/systemd/system/
   sudo install -o root -g root -m 644 docs/baserunnermulti.service /etc/systemd/system/
   ```

3. **Copy the logrotate config into `/etc/logrotate.d/`.** Root-owned,
   mode `644`. Neither daemon rotates its own log (see the comment in the
   file itself for why `copytruncate` specifically is required here, not
   logrotate's default rename-based rotation), and nothing else on a
   fresh host will do this for you:

   ```bash
   sudo install -o root -g root -m 644 docs/baserunner.logrotate /etc/logrotate.d/baserunner
   ```

   Nothing needs to be pre-created under `/var/log/baserunner/` for this
   step - both units' `LogsDirectory=baserunner` (see above) creates that
   directory with the right ownership the first time either unit starts,
   and logrotate is happy to manage a glob that doesn't match anything
   yet (`missingok`).

4. **`daemon-reload`, then enable and start the privileged helper before
   the watcher.** `baserunnermulti.service` already declares
   `Wants=baserunnerprivexec.service`/`After=baserunnerprivexec.service`,
   so starting the watcher first would just have systemd start the helper
   as a dependency anyway - starting the helper explicitly first makes
   that ordering visible instead of implicit, and lets step 5 check the
   helper's capabilities in isolation before the watcher can dispatch
   anything through it.

   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now baserunnerprivexec.service
   sudo systemctl enable --now baserunnermulti.service
   ```

5. **Confirm both came up clean:**

   ```bash
   systemctl status baserunnerprivexec.service baserunnermulti.service
   journalctl -u baserunnerprivexec.service -u baserunnermulti.service -f
   ls -l /var/log/baserunner/
   ```

   `baserunnermulti.service` is `Type=notify` with `WatchdogSec=30`, so
   `active (running)` here means the process reached its own ready
   callback, not just that it forked - a hang before that point shows as
   `activating (start)` and then a watchdog-timeout failure, not a false
   "running". The `ls` confirms `LogsDirectory=` actually took effect -
   both `baserunnermulti.log` and `baserunner-privexec.log` should be
   owned `baserunner:baserunner`.

Re-running steps 2-5 (copy, `daemon-reload`, `restart` instead of
`enable --now`) is also how you pick up a unit-file change later - e.g.
adding `cpu_quota_pct`/`cpu_weight` support required a `Delegate=yes`
edit to `baserunnerprivexec.service`, which needed exactly this sequence
to take effect. `KillMode=process` (see above) means restarting
`baserunnerprivexec.service` for any reason - this procedure, a crash, a
reboot - won't kill a job already in flight, but that job's completion
will never be tracked afterward (see above) - if avoiding that for a
specific job matters, check for a quiet dispatch queue first; nothing
today blocks or warns about this at restart time itself.

**Validate the capability chain before relying on it in production** -
this is an easy corner of Linux privilege separation to get subtly wrong.
On a scratch host: start `baserunnerprivexec.service`, then
`getpcaps $(pgrep BaseRunnerPrivExec)` to confirm it holds exactly
`cap_setuid,cap_setgid` and nothing else, and drop a `.run` file into a
real site's rundir to confirm the resulting job's output files are owned
by that site's `runner-<site>` uid/gid, not `baserunner`.

If using per-site CPU throttling, validate that chain too: with
`cpu_quota_pct`/`cpu_weight` set for a test site, confirm
`cpu.max`/`cpu.weight` under `/sys/fs/cgroup/baserunner.slice/site-<name>/`
match what `sites.yaml` asked for - `Delegate=yes`/`Slice=` and cgroup v2
write permissions are worth confirming empirically rather than trusting
the derivation in "Per-site CPU throttling" above.

If using per-site memory limits, validate that chain too, and separately
from CPU - this is the one that actually needs a real cgroup v2 host,
since the unit tests fake cgroupfs with a plain `tmp_path` directory and
can only verify *what CgroupJoiner writes*, not real kernel enforcement
or the two-level `subtree_control` enablement chain "Per-site memory
limits" above describes:

- With `memory_max_mb` set for a test site, confirm the dispatched job's
  pid actually lands in
  `/sys/fs/cgroup/baserunner.slice/site-<name>/job-<job_id>/cgroup.procs`
  (not `site-<name>/cgroup.procs` - that path now stays process-free
  once `memory` is enabled there), and that `job-<job_id>/memory.max`
  matches what `sites.yaml` asked for, in bytes, not MiB.
- Deliberately drive one test job over its `memory_max_mb` (e.g. a small
  limit against a script that allocates more) and confirm via
  `dmesg`/`journalctl` that only *that job's* process gets OOM-killed -
  look for the `oom-kill` line naming that job's own cgroup path - while
  a concurrent sibling job dispatched for the *same site* keeps running
  unaffected. This is the concrete test of the "no collateral damage"
  property per-job cgroups exist for.
  - **Check whether the host has swap first.** With no swap (confirmed
    on the 2026-09-16 testlong validation VM), `memory_high_mb`'s
    reclaim-based throttling has nothing reclaimable to work with once a
    job crosses it, and can stall the job's forward progress almost to a
    halt (~100KB grown in 30s, in one observed case) rather than letting
    it climb to `memory_max_mb` and get OOM-killed promptly. A "runaway"
    job may hang instead of dying cleanly on a swapless host - worth
    confirming this host's actual swap configuration before assuming the
    OOM-based collateral-damage protection kicks in promptly.
- Confirm the `job-<job_id>` leaf directory is actually removed once the
  job exits (`ChildTable`'s reap-time cleanup) - it shouldn't linger.

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
