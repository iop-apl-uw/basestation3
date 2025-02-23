#! /usr/bin/env python

## Copyright (c) 2023, 2024, 2025  University of Washington.
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
Upload.py

Creates an glider upload and verification script and file chunks for a large file
"""

import getopt
import gzip
import hashlib
import os
import subprocess
import sys


def create_upload(upload_file_name, chunk_size, glider_zip, pdos_xr_filename, pdos_md5_filename):
    """Given a file to upload to a glider, zip the file, break it into pieces
    and build pdoscmds.bat file(s) to put the file back togther.

    Assumes the file to split is in the current directory and the user can create files
    in that same directory
    """
    # Gzip original file
    base_upload_file_name = os.path.basename(upload_file_name)
    base_upload_md5 = hashlib.md5()
    with open(base_upload_file_name, "rb") as fi:
        base_upload_md5.update(fi.read())

    gzip_upload_file_name = "CHUNK.GZ"
    if(glider_zip == "gzip"):
        fi = open(base_upload_file_name, 'rb')
        fo = gzip.open(gzip_upload_file_name, 'wb', 9)
        data = fi.read()
        fo.write(data)
        fi.close()
        fo.close()
    else:
        cmd = "%s /c %s %s" % (glider_zip, base_upload_file_name, gzip_upload_file_name)
        status, output = subprocess.getstatusoutput(cmd)
        if(status):
            print("Error %d executing %s (%s)- bailing out" % (status, cmd, output))
        
    # md5 hash the gzipped file original
    gzip_upload_md5 = hashlib.md5()
    with open(gzip_upload_file_name, "rb") as fi:
        gzip_upload_md5.update(fi.read())
    
    # Break it up into uniform sizes
    gzip_upload_file_size = os.stat(gzip_upload_file_name).st_size

    pdoscmds_file_xr = open(pdos_xr_filename, "w")
    if pdos_md5_filename is None:
        pdoscmds_file_md5 = pdoscmds_file_xr # commands to the same file
    else:
        pdoscmds_file_md5 = open(pdos_md5_filename, "w")
    
    fi = open(gzip_upload_file_name, "rb")
    counter = 0
    while(gzip_upload_file_size > 0):
        if(chunk_size < gzip_upload_file_size):
            chunk_file_size = chunk_size
        else:
            chunk_file_size = gzip_upload_file_size
        #print counter, gzip_upload_file_size
        gzip_upload_file_size = gzip_upload_file_size - chunk_file_size
        chunk_file_name = "CHUNK.U%02X" % counter
        # Copy off a piece of the original
        fo = open(chunk_file_name, "wb")
        fo.write(fi.read(chunk_file_size))
        fo.close()
        fo = open(chunk_file_name, "rb")
        # Calculate the md5 hash
        chunk_md5 = hashlib.md5()
        chunk_md5.update(fo.read())
        fo.close()
        # Write out pdos contribution
        pdoscmds_file_xr.write("xr %s\n" % chunk_file_name)
        pdoscmds_file_xr.write("stroke\n")
        pdoscmds_file_md5.write("strip1a %s %d\n" % (chunk_file_name, chunk_file_size))
        pdoscmds_file_md5.write("md5 %s %s\n" % (chunk_md5.hexdigest(), chunk_file_name))
        counter = counter + 1

    # Finish up the pdoscmds.bat file

    # Write out the cat command
    append = ">"
    files = ""
    for i in range(counter):
        files = files + "CHUNK.U%02X " % i
        if(i % 6 == 5):
            # New line
            pdoscmds_file_md5.write("cat %s %s %s\n" % (files, append, gzip_upload_file_name))
            files = ""
            append = ">>"
    if(files != ""):
        pdoscmds_file_md5.write("cat %s %s %s\n" % (files, append, gzip_upload_file_name))
    # MD5 the new cat file and unzip
    pdoscmds_file_md5.write("md5 %s %s\n" % (gzip_upload_md5.hexdigest(), gzip_upload_file_name))
    if(base_upload_file_name == "main.run"):
        prefix = "//"
    else:
        prefix = ""
    pdoscmds_file_md5.write("%sgunzip %s %s\n" % (prefix, gzip_upload_file_name, base_upload_file_name))
    pdoscmds_file_md5.write("md5 %s %s\n" % (base_upload_md5.hexdigest(), base_upload_file_name))
    pdoscmds_file_md5.write("//del /v CHUNK.U*\n")
    
    pdoscmds_file_xr.close()
    if pdos_md5_filename is not None:
        pdoscmds_file_md5.close()
    
if __name__ == "__main__":
    c_size = 4096
    gliderzip_binary = "gzip"
    pdoscmds_file_name = None # assume the default file names below
    usage_string = "usage: %s [--chunksize NNNN] [--pdoscmds combined-pdoscmds-file-name] <filename>"

    print("This program only supports uploads to a RevE motherboard")

    try:
        opts, args = getopt.getopt(sys.argv[1:], "c:", ["chunksize=", "pdoscmds="])
    except getopt.GetoptError:
        print(usage_string % sys.argv[0])
        sys.exit(1)

    for o, a in opts:
        if o in ("--chunksize"):
            c_size = int(a)
        #if o in ("--gliderzip"):
        #    gliderzip_binary = a
        if o in ("--pdoscmds"):
            pdoscmds_file_name = a

    #if(not gliderzip_binary):
    #    head, tail = os.path.split(sys.argv[0])
    #    gliderzip_binary = os.path.join(sys.path[0], "gliderzip")

    if (len(args) != 1):
        print(usage_string % sys.argv[0])
        sys.exit(1)

    #if(not os.path.exists(gliderzip_binary) and gliderzip_binary != "gzip"):
    #    print(("Error - glider version of gzip [%s] does not exist - use --gliderzip to specify" % gliderzip_binary))
    #    sys.exit(1)

    if pdoscmds_file_name is None:
        # Onboard the glider if you try to xr a file that already exists, it will skip the xr.
        # Thus we separate the xr commands into a separate file so you don't have to nurse them along.
        # Just wait until all the files are skipped, then send the second pdoscmds file to
        # do the md5 checks and combinations.

        # If any files were bolluxed, make a pdoscmds file that deletes the
        # onboard image before the resend xr (which you must do in any case) and add
        # the strip1a and md5 commands to verify transmission. Then re-execute
        # the combination cat, md5, and gunzip commands to verify the final
        # assembly.
        pdos_xr_filename  = "pdoscmds.bat.xr"
        pdos_md5_filename = "pdoscmds.bat.md5"
    else:
        # If the user gives a filename (e.g., pdoscmds.bat.upload), combine all commands into the single file
        pdos_xr_filename  = pdoscmds_file_name
        pdos_md5_filename = None
    retval = create_upload(args[0], c_size, gliderzip_binary, pdos_xr_filename, pdos_md5_filename)
    sys.exit(retval)
