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

"""
Commission.py: Sets up a new glider account on a basestation.

**NOTES**
- You must run as root

"""

import grp
import os
import pwd
import subprocess
import sys
import shutil

import BaseOpts
import BaseDB
from BaseLog import BaseLogger, log_critical, log_error, log_info


def syscall(command):
    """Exectute a command in a sub-process"""
    print("Executing %s" % command)
    try:
        retcode = subprocess.call(command, shell=True)
        if retcode < 0:
            print(
                "Child %s was terminated by signal %d" % (command, -retcode),
                file=sys.stderr,
            )
        elif retcode > 0:
            print("Child %s returned %d" % (command, retcode), file=sys.stderr)
    except OSError as e:
        print("Execution failed:", e, file=sys.stderr)


def generate_password(glider_id):
    """Generate the standard glider password"""
    if glider_id % 2:
        pwd_template = "135791"
    else:
        pwd_template = "024680"
    glider_id_str = "%d" % glider_id
    password = "%s%s" % (glider_id_str, pwd_template[len(glider_id_str) : 6])
    return password


def main():
    """Creates the user accounts and populates home directories for new gliders

    notes:
        You must be root to run this script

    returns:
        0 for success
        1 for failure

    raises:
        Any exceptions raised are considered critical errors and not expected

    """

    # Get options
    base_opts = BaseOpts.BaseOptions(
        "Creates the user accounts and populates home directories for new gliders (Run as root)",
        additional_arguments={
            "home_dir": BaseOpts.options_t(
                "/home",
                ("Commission",),
                ("--home_dir",),
                str,
                {
                    "help": "home directory base, used by Commission.py",
                },
            ),
            "glider_password": BaseOpts.options_t(
                None,
                ("Commission",),
                ("--glider_password",),
                str,
                {
                    "help": "glider password, used by Commission.py",
                },
            ),
            "glider_group": BaseOpts.options_t(
                "gliders",
                ("Commission",),
                ("--glider_group",),
                str,
                {
                    "help": "glider group, used by Commission.py",
                },
            ),
            "home_dir_group": BaseOpts.options_t(
                "gliders",
                ("Commission",),
                ("--home_dir_group",),
                str,
                {
                    "help": "home dir group, used by Commission.py",
                },
            ),
            "glider_id": BaseOpts.options_t(
                None,
                ("Commission",),
                ("glider_id",),
                int,
                {
                    "help": "serial number of glider to commission (no leading sg)",
                },
            ),
            "glider_jail": BaseOpts.options_t(
                None,
                ("Commission",),
                ("--jail",),
                str,
                {
                    "help": "Root of the jail to commision the glider in",
                    "action": BaseOpts.FullPathAction,
                },
            ),
            "uid": BaseOpts.options_t(
                None,
                ("Commission",),
                ("--uid",),
                int,
                {
                    "help": "UID for the glider",
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    glider_id = base_opts.glider_id

    sg000 = "sg000"

    if base_opts.glider_password is None:
        passwd = generate_password(glider_id)
    else:
        passwd = base_opts.glider_password

    glider = "sg%03d" % glider_id

    glider_path = "%s/%s" % (base_opts.home_dir, glider)
    sg000_path = os.path.join(base_opts.basestation_directory, sg000)
    initial_files = (
        ".login",
        ".logout",
        ".cshrc",
        ".pagers",
        ".urls",
        "cmdfile",
        "sg_calib_constants.m",
        ".hushlogin",
        ".extensions",
        ".ftp",
        ".mailer",
        ".pre_extensions",
        "sections.yml",
        "NODC.yml",
    )

    if base_opts.glider_jail:
        if not os.path.exists(base_opts.glider_jail):
            log_error(f"Jail dir {base_opts.glider_jail} does not exsist - bailing out")
            return 1
        else:
            log_info(f"Jail location ({base_opts.glider_jail})")

    # Adding "-g <group> -G <group>" forces the initial group (lowercase g) to
    # be gliders rather than letting useradd create a new unique group
    if base_opts.uid:
        uid_str = f"-u {base_opts.uid}"
    else:
        uid_str = ""
    syscall(
        '/usr/sbin/useradd -d %s -c "Seaglider %s" -g %s -G %s -m -k %s %s %s'
        % (
            glider_path,
            glider_id,
            base_opts.glider_group,
            base_opts.glider_group,
            sg000_path,
            uid_str,
            glider,
        )
    )
    syscall(
        "chmod g+rwxs,o+rx %s" % glider_path
    )  # Let group members have full privies, read-only otherwise

    syscall("chgrp %s %s" % (base_opts.home_dir_group, glider_path))

    for file_name in initial_files:
        full_file_name = os.path.join(sg000_path, file_name)
        full_dst_file_name = os.path.join(glider_path, file_name)
        shutil.copyfile(full_file_name, full_dst_file_name)
        syscall("chown %s %s" % (glider, full_dst_file_name))

    base_opts.instrument_id = glider_id
    base_opts.mission_dir = glider_path
    BaseDB.createDB(base_opts)
    db_file_name = os.path.join(glider_path, "%s.db" % glider)
    syscall("chown %s.%s %s" % (glider, base_opts.home_dir_group, db_file_name))

    # syscall("chown pilot %s/cmdfile" % glider_path)
    # syscall("echo %s | passwd %s --stdin" % (passwd, glider))
    syscall("echo %s:%s | chpasswd" % (glider, passwd))
    syscall("chsh -s /usr/bin/tcsh %s" % glider)
    if base_opts.glider_jail:
        # More the home directory
        syscall(
            f"mv {glider_path} {os.path.join(base_opts.glider_jail, glider_path[1:])}"
        )

        # Deal with the jailed passwd file
        pd = pwd.getpwnam(glider)
        pwd_str = f"{pd.pw_name}:{pd.pw_passwd}:{pd.pw_uid}:{pd.pw_gid}:{pd.pw_gecos}:{pd.pw_dir}:{pd.pw_shell}"
        jail_pwd = os.path.join(base_opts.glider_jail, "etc/passwd")
        log_info(f"Jail password file {jail_pwd}")
        try:
            fi = open(jail_pwd, "r")
            for ll in fi.readlines():
                if ll.split(":")[0].startswith(glider):
                    log_error(
                        f"Entry already exists in {jail_pwd} for {glider} - bailing out"
                    )
                    return 1
        except FileNotFoundError:
            pass
        except:
            log_error(f"Could not open {jail_pwd}", "exc")
            return 0
        leading_newline = ""
        try:
            with open(jail_pwd, "r") as fi:
                buffer = fi.read()
                if isinstance(buffer, str) and not buffer.endswith("\n"):
                    leading_newline = "\n"
        except FileNotFoundError:
            pass
        except:
            log_error(f"Could not read {jail_pwd}", "exc")
            return 1
        try:
            with open(jail_pwd, "a") as fo:
                log_info(f"Writing {pwd_str} to {jail_pwd}")
                fo.write(f"{leading_newline}{pwd_str}\n")
        except:
            log_error(f"Could not write to {jail_pwd}", "exc")
            return 1

        gp = grp.getgrgid(pd.pw_gid)
        jail_grp = os.path.join(base_opts.glider_jail, "etc/group")
        # grp.struct_group(gr_name='gliders', gr_passwd='x', gr_gid=1002, gr_mem=['sg095', 'gbs', 'sg080'])
        grp_str = f"{gp.gr_name}:{gp.gr_passwd}:{gp.gr_gid}:"
        for member in gp.gr_mem:
            grp_str = f"{grp_str}{member},"
        if grp_str.endswith(","):
            grp_str = grp_str[:-1]

        # Deal with the jailed group file
        try:
            with open(jail_grp, "r") as fi:
                grp_lines = fi.readlines()
        except FileNotFoundError:
            try:
                with open(jail_grp, "w") as fo:
                    fo.write(f"{grp_str}\n")
            except:
                log_error(f"Failed to create {jail_grp} - jail will not work", "exc")
        except:
            log_error(f"Could not open {jail_grp} - not updating", "exc")
        else:
            f_update = False
            f_already_in = False
            for ii in range(len(grp_lines)):
                ll = grp_lines[ii]
                splits = ll.split(":")
                if splits[0].startswith(gp.gr_name):
                    for pw_name in splits[3].split(","):
                        if pw_name == glider:
                            log_info(
                                f"{glider} already in {jail_grp} group {gp.gr_name}"
                            )
                            f_already_in = True
                            break
                    else:
                        log_info(
                            f"Found group {gp.gr_name} in {jail_grp}, {glider} not included - will add"
                        )
                        grp_lines[ii] = f"{ll.rstrip()},{glider}"
                        f_update = True
            if not f_already_in and not f_update:
                log_info(f"Did not find group {gp.gr_name} in {jail_grp} - will add")
                grp_lines.append(f"{grp_str}\n")
                f_update = True
            if f_update:
                try:
                    with open(jail_grp, "w") as fo:
                        for ll in grp_lines:
                            fo.write(ll)
                except:
                    log_error(f"Error updating {jail_grp}")
        print(
            "You must manually change the gliders entry in /etc/password to look like this"
        )
        jail_pwd_str = f"{pd.pw_name}:{pd.pw_passwd}:{pd.pw_uid}:{pd.pw_gid}:{pd.pw_gecos}:{base_opts.glider_jail}:/sbin/chrootshell"
        print(jail_pwd_str)

    print("Account %s created in %s with password %s" % (glider, glider_path, passwd))
    return 0


if __name__ == "__main__":
    import time

    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
