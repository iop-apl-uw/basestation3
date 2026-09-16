#!/usr/bin/env python3
"""Stub stand-in for Base.py, used only by testlong's multipass validation
VM - NOT real basestation processing. Just enough to prove
BaseRunnerMulti/BaseRunnerPrivExec's dispatch mechanics: records who it
actually ran as (proves the privilege-drop chain), and can optionally
simulate a grandchild-forking job (for the PR_SET_CHILD_SUBREAPER
zombie-reaping test), a memory-hungry job (for the memory.max cgroup
enforcement test), or a chosen exit code.

stdout/stderr are already redirected to the job's log_file by
BaseRunnerPrivExec before this execs (see PrivExecServer._run_child), so
plain print() here is enough - no explicit log file handling needed.

Accepts and ignores whatever real Base.py-style flags BaseRunnerMulti
appends (--job_id/--queue_length/--mission_dir/...) via
parse_known_args, since this only needs to observe its own identity, not
actually process anything.
"""

import argparse
import os
import pwd
import sys
import time


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--stub-fork-and-exit", action="store_true")
    parser.add_argument("--stub-exit-code", type=int, default=0)
    parser.add_argument("--stub-sleep-seconds", type=float, default=0.0)
    parser.add_argument("--stub-allocate-mb", type=int, default=0)
    args, _unknown = parser.parse_known_args()

    user = pwd.getpwuid(os.getuid()).pw_name
    print(
        f"user={user} uid={os.getuid()} gid={os.getgid()} pid={os.getpid()} argv={sys.argv}",
        flush=True,
    )

    if args.stub_allocate_mb:
        # bytearray's C-level init memsets every byte to 0 immediately, so
        # the kernel commits real pages right away - not just virtual
        # address space a lazy/CoW zero-page mapping could dodge, which is
        # what memory.max is actually meant to catch. Bound to a name (not
        # a bare expression statement) so it isn't immediately
        # refcount-freed before the sleep below - a job testing "stays
        # alive under the limit" needs to actually keep holding this
        # memory, not just have briefly touched it.
        held_allocation = bytearray(args.stub_allocate_mb * 1024 * 1024)
        print(f"allocated {len(held_allocation)} bytes", flush=True)

    if args.stub_sleep_seconds:
        # Keeps this process (and therefore its cgroup membership)
        # observable for a bit, e.g. for the cgroup.procs check.
        time.sleep(args.stub_sleep_seconds)

    if args.stub_fork_and_exit:
        child_pid = os.fork()
        if child_pid == 0:
            time.sleep(2)
            print(f"grandchild pid={os.getpid()} exiting", flush=True)
            os._exit(0)
        print(
            f"forked grandchild pid={child_pid}, parent exiting immediately "
            "without waiting on it",
            flush=True,
        )
        # Intentionally NOT waiting on child_pid - this is exactly the
        # orphaned-descendant scenario PR_SET_CHILD_SUBREAPER exists for.

    return args.stub_exit_code


if __name__ == "__main__":
    sys.exit(main())
