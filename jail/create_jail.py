#! /usr/bin/env python
# -*- python-fmt -*-
##
## Copyright (c) 2006-2022 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

import glob
import pathlib
import os
import sys
import shutil
import pdb

# pip install pylddwrap
import lddwrap

f_create = True

# Needs to be run as root

arch_lib_dir = "aarch64-linux-gnu"

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
    "/etc/pam.d",
    "/var/log",
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
    # End glider_login/glider_logout
    "/usr/local/bin/rawrcv",
    "/usr/local/bin/rawsend",
    #"/usr/local/bin/xs",
    #"/usr/local/bin/xr",
)

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

tree_copy = ["/lib/terminfo"]
    
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
    
jail_root = pathlib.Path("/home/jail")

print(f"Dirs to create {dirs}")
print(f"Files to copy {files_to_copy}")

jail_root.mkdir(exist_ok=True)

for dd in dirs:
    tgt_dir = jail_root.joinpath(str(dd)[1:])
    print(tgt_dir)
    if f_create:
        tgt_dir.mkdir(exist_ok=True)
        shutil.copymode(dd, tgt_dir)

for ff in files_to_copy:
    tgt_file = jail_root.joinpath(str(ff)[1:])
    print(ff, tgt_file)
    if f_create:
        shutil.copy2(ff, tgt_file)


for tree in tree_copy:
    tgt_tree = jail_root.joinpath(str(tree)[1:])
    print(tree, tgt_tree)
    shutil.copytree(tree, tgt_tree)
    
