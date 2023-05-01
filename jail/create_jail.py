#! /usr/bin/env python
# -*- python-fmt -*-
## Copyright (c) 2023  University of Washington.
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

import argparse
import glob
import pathlib
import os
import sys
import shutil
import pdb

# pip install pylddwrap
import lddwrap

# Needs to be run as root to create jails

# Note: this script does not setup glider accounts (passwd, shadow, group and shadow group)
# See ReadMe.md for those instructions


class FullPaths(argparse.Action):
    """Expand user- and relative-paths"""

    def __call__(self, parser, namespace, values, option_string=None):
        if values is not None:
            setattr(namespace, self.dest, os.path.abspath(os.path.expanduser(values)))
        else:
            setattr(namespace, self.dest, values)


def mk_jail(
    jail_root_name, glider_home_dir, glider_home_dir_target, f_create, f_update
):
    if f_update:
        f_create = True

    jail_root = pathlib.Path(jail_root_name)

    arch_lib_dir = f"{os.uname().machine}-linux-gnu"

    ddirs = [
        "/bin",
        "/dev",
        "/etc",
        "/home",
        "/lib",
        f"/lib/{arch_lib_dir}",
        f"/lib/{arch_lib_dir}/security",
        "/usr",
        "/usr/bin",
        "/usr/local",
        "/usr/local/bin",
        "/var",
        "/var/log",
        # "/etc/pam.d",
        "/usr/local/basestation",
        "/usr/local/basestation3",
    ]
    dirs = []
    for dd in ddirs:
        dirs.append(pathlib.Path(dd))

    files_to_copy = set()
    seaglider_files = (
        "/usr/bin/tcsh",
        # Start glider_login/glider_logout
        "/usr/bin/rm",
        "/usr/bin/touch",
        "/usr/bin/date",
        "/usr/bin/printf",
        "/usr/bin/pwd",
        "/usr/bin/sleep",
        # End glider_login/glider_logout
        "/usr/local/bin/rawrcv",
        "/usr/local/bin/rawrcv2",
        "/usr/local/bin/rawrcvb",
        "/usr/local/bin/rawsend",
        # For coompressed log and profile for pilot jail
        # "/usr/local/bin/x3decode",
        # "/usr/local/bin/log",
        "/usr/local/bin/lsx",
        "/usr/local/bin/lrx",
        "/usr/local/bin/lsb",
        "/usr/local/bin/lrb",
    )

    script_files = [
        "/usr/local/basestation3/glider_login",
        "/usr/local/basestation3/glider_logout",
    ]

    if not f_update:
        script_files.append("/usr/local/basestation/glider_login")
        script_files.append("/usr/local/basestation/glider_logout")

    for script_file in script_files:
        files_to_copy.add(pathlib.Path(script_file))

    for sgf in seaglider_files:
        path = pathlib.Path(sgf)
        files_to_copy.add(path)
        deps = lddwrap.list_dependencies(path=path)
        for dep in deps:
            if dep.path:
                files_to_copy.add(dep.path)
                # Build a list of directories to be added to the dirs list, adding in descending order
                parts = dep.path.parts[:-1]
                accum = pathlib.Path(parts[0])
                for p in parts[1:]:
                    accum = accum.joinpath(p)
                    if accum not in dirs:
                        dirs.append(accum)

    pam_related_libs = [
        f"/lib/{arch_lib_dir}/libnss_files*",
        f"/lib/{arch_lib_dir}/libnss_compat*",
        f"/lib/{arch_lib_dir}/libnsl*",
        f"/lib/{arch_lib_dir}/security/*",
    ]

    for gg in pam_related_libs:
        for m in glob.glob(gg):
            f_tmp = pathlib.Path(m)
            files_to_copy.add(f_tmp)

    tree_copy = ["/lib/terminfo", "/etc/pam.d"]

    # cp /lib/aarch64-linux-gnu/libnss_files-2.31.so /home/jail/lib/aarch64-linux-gnu/libnss_files-2.31.so
    # cp /lib/aarch64-linux-gnu/libnss_files.so.2 /home/jail/lib/aarch64-linux-gnu/libnss_files.so.2
    # cp /lib/aarch64-linux-gnu/libnss_files.so /home/jail/lib/aarch64-linux-gnu/libnss_files.so
    # cp /lib/aarch64-linux-gnu/libnss_compat-2.31.so /home/jail/lib/aarch64-linux-gnu/libnss_compat-2.31.so
    # cp /lib/aarch64-linux-gnu/libnss_compat.so.2 /home/jail/lib/aarch64-linux-gnu/libnss_compat.so.2
    # cp /lib/aarch64-linux-gnu/libnss_compat.so /home/jail/lib/aarch64-linux-gnu/libnss_compat.so
    # cp /lib/aarch64-linux-gnu/libnsl-2.31.so /home/jail/lib/aarch64-linux-gnu/libnsl-2.31.so
    # cp /lib/aarch64-linux-gnu/libnsl.so.1 /home/jail/lib/aarch64-linux-gnu/libnsl.so.1
    # cp /lib/aarch64-linux-gnu/libnsl.a /home/jail/lib/aarch64-linux-gnu/libnsl.a
    # cp /lib/aarch64-linux-gnu/libnsl.so /home/jail/lib/aarch64-linux-gnu/libnsl.so
    # cp /lib/aarch64-linux-gnu/security/* /home/jail/lib/security/

    print(f"Dirs to create {dirs}")
    print(f"Files to copy {files_to_copy}")

    jail_root.mkdir(exist_ok=True)

    for dd in dirs:
        tgt_dir = jail_root.joinpath(str(dd)[1:])
        print(tgt_dir)
        if f_create:
            tgt_dir.mkdir(exist_ok=True)
            shutil.copymode(dd, tgt_dir)
            stat_info = os.stat(dd)
            os.chown(tgt_dir, stat_info.st_uid, stat_info.st_gid)

    for ff in files_to_copy:
        tgt_file = jail_root.joinpath(str(ff)[1:])
        print(ff, tgt_file)
        if f_create:
            shutil.copy2(ff, tgt_file)

    for tree in tree_copy:
        tgt_tree = jail_root.joinpath(str(tree)[1:])
        print(tree, tgt_tree)
        if f_create:
            shutil.copytree(tree, tgt_tree, dirs_exist_ok=True)

    if glider_home_dir and not f_update:
        if glider_home_dir_target:
            tgt_dir = jail_root.joinpath(str(glider_home_dir_target)[1:])
        else:
            tgt_dir = jail_root.joinpath(str(glider_home_dir)[1:])
        print(glider_home_dir, tgt_tree)
        if f_create:
            tgt_dir.mkdir(exist_ok=True)
            shutil.copymode(glider_home_dir, tgt_dir)
            stat_info = os.stat(glider_home_dir)
            os.chown(tgt_dir, stat_info.st_uid, stat_info.st_gid)
        src_files = []
        for m in glob.glob(os.path.join(glider_home_dir, "*")):
            src_files.append(m)
        for m in glob.glob(os.path.join(glider_home_dir, ".*")):
            src_files.append(m)
        for src_file in src_files:
            tgt_file = os.path.join(tgt_dir, os.path.split(src_file)[1])
            print(src_file, tgt_file)
            if f_create:
                shutil.copy(src_file, tgt_file)
                shutil.copystat(src_file, tgt_file)
                shutil.copymode(src_file, tgt_file)
                stat_info = os.stat(src_file)
                os.chown(tgt_file, stat_info.st_uid, stat_info.st_gid)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__)
    # Add verbosity arguments

    # ap.add_argument(
    #    "--verbose", default=False, action="store_true", help="enable verbose output"
    # )
    ap.add_argument(
        "jail_root",
        help="Root of the new jail",
        action=FullPaths,
    )
    ap.add_argument(
        "--create",
        help="Create the jail",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    ap.add_argument(
        "--update",
        help="Update the jail",
        action=argparse.BooleanOptionalAction,
        default=False,
    )
    ap.add_argument(
        "--glider_dir",
        help="Path to glider directory to include in the jail",
        action=FullPaths,
        default=None,
    )
    ap.add_argument(
        "--glider_dir_target",
        help="Location in jail for glider directory",
        action=FullPaths,
        default=None,
    )

    args = ap.parse_args()

    # Add option to include a glider directory in the jail

    mk_jail(
        args.jail_root,
        args.glider_dir,
        args.glider_dir_target,
        args.create,
        args.update,
    )
    if args.create:
        print(f"Jail created in {args.jail_root}")

    if args.glider_dir:
        jailed_passwd = os.path.join(args.jail_root, "/etc/passwd")
        jailed_group = os.path.join(args.jail_root, "/etc/group")
        print(
            f"{jailed_passwd} and {jailed_group} are not created by this script - they updated by Commission.py for new gliders"
        )
        print("For existing gliders, you need to do the updates yourself")
        print(
            f"Note that for the jail to work, entries /etc/password for glider accounts must have {args.jail_root} for the home directory and /sbin/chrootshell for the shell"
        )
