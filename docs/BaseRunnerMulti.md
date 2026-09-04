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
# Delegates a cgroup subtree to this unit so CgroupJoiner can create
# per-site child cgroups and write cpu.max/cpu.weight/cgroup.procs
# without needing any additional Linux capability.
Delegate=yes
ExecStart=/opt/basestation/bin/python /usr/local/basestation3/BaseRunnerPrivExec.py \
    --sites_config /usr/local/basestation3/etc/sites.yaml \
    --priv_exec_socket /run/baserunner/priv_exec.sock \
    --cgroup_root /sys/fs/cgroup/system.slice/baserunnerprivexec.service \
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
    --base_log /var/log/baserunner/baserunnermulti.log
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

### `KillMode` and in-flight jobs

Every dispatched job is moved into its own `cgroup_root/site-<name>`
sub-cgroup (see `CgroupJoiner.join()`) - a child of
`baserunnerprivexec.service`'s own delegated cgroup tree. Systemd's
default `KillMode=control-group` would SIGTERM/SIGKILL every process in
that whole tree on *any* stop of the unit, not just this unit's own
tracked process - including the routine, documented
`systemctl restart baserunnerprivexec.service` procedure below, not just
a crash or reboot. `baserunnerprivexec.service` sets `KillMode=process`
to avoid that: a stop signals only the main process, leaving dispatched
jobs running completely untouched in their own site cgroups.
`KillMode=mixed` looks like a safer middle ground but isn't - confirmed
on real hardware - per `systemd.kill(5)`, `mixed` sends SIGTERM to only
the main process but still sends SIGKILL to every other process in the
cgroup as soon as that main process exits (not only as a
`TimeoutStopSec` fallback), so it kills in-flight jobs just as fast as
`control-group` does. Only `process` leaves them alone. The man page
calls `process` "not recommended" because it normally lets processes
escape the service manager's lifecycle by accident - here that's the
deliberate, intended design: dispatched jobs are meant to outlive this
helper's own restarts, tracked by `BaseRunnerMulti.py`'s own job-queue
bookkeeping instead.

`KillMode=process` alone is still not sufficient, also confirmed on real
hardware: this unit has `Delegate=yes`, and cgroup v2's "no internal
process" rule means a cgroup cannot simultaneously hold a process
directly *and* have children with controllers enabled in its
`cgroup.subtree_control`. `CgroupJoiner.join()` delegates the `cpu`
controller down to `site-<name>` children - so as long as a job survives
in one of them, that controller stays enabled at this unit's own cgroup
top level across a restart, and systemd's own placement of a *freshly
started* invocation's raw main process - which happens directly into
that top level, before any of our Python code (including
`_move_self_into_leaf_cgroup()`'s own mitigation) ever runs - now
violates the constraint every time. The result was a hard, repeatable
`status=219/CGROUP` start failure for as long as any job stayed alive,
not a rare race: 5 rapid restart attempts, then systemd's rate limiter
gave up and left the unit fully stopped until manually recovered - worse
than the original bug. `DelegateSubgroup=supervisor` (systemd >= 254)
fixes this declaratively: it tells systemd to place this unit's own
freshly started main process into that named subgroup itself, never
into the delegated cgroup's own top level, so the conflict with
surviving job cgroups never arises. It reuses the same `supervisor` name
`_move_self_into_leaf_cgroup()` already uses, making that function's own
move a harmless no-op. A benign `"Found left-over process ... in
control group ... Ignoring"` line in the journal during a
restart-while-job-active is now expected - systemd noticing the
surviving job, not an error.

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
