##
## Copyright (c)  2020, 2023 University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##

# To support rebuilding a deployment from scratch, ensure raw data files
# are lower-cased (see globs in FileMgr), and that required files are present.
import sys
import os
import glob
import shutil

if __name__ == "__main__":
    # to rebuild the world
    for required_file in ["comm.log", "sg_calib_constants.m"]:
        if not os.path.exists(required_file):
            print(f"Missing required file: {required_file}")
            sys.exit(0)

    report_files_moved = False
    num_files_moved = 0
    # glob is case-sensitive so we find the upper-cased versions of transmitted files
    # rename archive (A) files that can from a flash card dump rather than transmitted
    for g in [
        "[A-Z][A-Z][0-9][0-9][0-9][0-9][LDKP][UZTG].[XA]",
        "[A-Z][A-Z][0-9][0-9][0-9][0-9][AB][UZTG].[XA]",
        "[a-z][a-z][0-9][0-9][0-9][0-9][ldkp][uztg].[xa]",
        "[a-z][a-z][0-9][0-9][0-9][0-9][ab][uztg].[xa]",
    ]:
        for fn in glob.glob(g):
            fnx = fn.lower()
            fnx = fnx[:-1] + "x"  # esnure x extension
            if report_files_moved:
                print(f"{fn} -> {fnx}")
            num_files_moved += 1
            shutil.move(fn, fnx)
    # TODO what about removing fragment files *.X00 etc?
    # Note that the fragment numbers are in hex (with K for C)
    if num_files_moved:
        print("Renamed %d data files" % num_files_moved)

    sys.exit(1)
