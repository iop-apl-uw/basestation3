#! /usr/bin/env python
# -*- python-fmt -*-

## Copyright (c) 2023, 2024  University of Washington.
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
Bogue.py: Pass unstripped file segments (log, data, etc.) to detect and remove Bogue's syndrome,
     duplicated sector data transmitted by the glider.

     *** Use at your own risk, partially tested ***
"""

import os
import stat
import sys
import time

import BaseOpts
import BaseOptsType
from BaseLog import BaseLogger, log_debug, log_error, log_info, log_critical


def Bogue(in_filename):
    """Pass unstripped segments to detect and remove Bogue's syndrome.

    Looks for and removes any duplicated sector data transmitted by a glider
    If found, creates a new file in_filename.b.ext, leving original untouched.

    Returns:
        Name of bogue-syndrom-free file.

    Raises:
        All low level exception are let through, or re-raised

    """

    return_filename = in_filename

    in_filename = os.path.abspath(in_filename)
    log_debug("Checking for Bogue syndrome on file: %s" % in_filename)

    try:
        filesize = os.stat(in_filename)[stat.ST_SIZE]
    except:
        log_error("Error stat %s" % in_filename)
        raise

    log_debug("Filesize reported by OS: %d bytes" % filesize)

    if filesize <= 256:
        log_debug("No Bogue's syndrome on file (too small, filesize < 256 bytes)")
        return return_filename

    # Read file and look for duplicated sector data

    found_duplicates = []
    found_padding = []
    # padding = "\x1a\x1a\x1a\x1a\x1a\x1a\x1a\x1a" # 8 ^Zs
    padding = bytes((26, 26, 26, 26, 26, 26, 26, 26))  # 8 ^Zs
    padding_block = padding * 16  # 128 ^Zs

    in_file = None
    temp_file = None

    try:
        log_debug("Opening file for reading")
        in_file = open(in_filename, "rb")
        in_file_contents = in_file.read()

        if len(in_file_contents) != filesize:
            read_size = len(in_file_contents)
            log_error(
                "Unable to read %s: (read %d bytes, expected %d bytes)"
                % (in_filename, read_size, filesize)
            )

        root, ext = os.path.splitext(in_filename)
        temp_filename = root + ".b" + ext
        temp_file = open(temp_filename, "wb")

        start = 0
        last_block = filesize - 128
        while start <= last_block:
            block = in_file_contents[start : start + 128]
            log_debug("Checking block at %d to %d" % (start, start + 128))

            # If we see a full block of padding, eliminate it
            # We get this when we send files longer than 16K,
            # as when we are battling flash problem
            if block == padding_block:
                # record the finding of this padding
                found_padding.append((start, 128))
                log_debug("Found padding at %d to %d" % (start, start + 128))

                start = start + 128
                continue  # looking at 128-byte chunks of the data file

            # Scan ahead to see if this 128-byte block is duplicated
            log_debug("Scanning ahead to see if current block is duplicated.")
            found_bogue = False
            dup_start = start + 128
            while dup_start <= last_block and not found_bogue:
                dup_block = in_file_contents[dup_start : dup_start + 128]
                # log_debug("dup_block: %d to %d" % (dup_start, dup_start+128))
                if (
                    dup_block == padding_block
                ):  # original bogue.pl only looked at the first 8 bytes [ie, padding]
                    log_debug(
                        "dup_block: %d to %d is PADDING" % (dup_start, dup_start + 128)
                    )
                    dup_start = dup_start + 128
                    continue  # looking for dupes of a given data block

                if dup_block == block:
                    # It is, prima facia evidence for duplicated sector
                    # Compute the size of the duplicated sector.
                    # The duplication occurs immediately after the first copy
                    log_debug(
                        "dup_block: %d to %d is SAME AS BLOCK %d to %d"
                        % (dup_start, dup_start + 128, start, start + 128)
                    )
                    dup_size = dup_start - start
                    dup_head = in_file_contents[start:dup_start]
                    dup = in_file_contents[dup_start : dup_start + dup_size]

                    if dup == dup_head:
                        found_bogue = True  # gotcha!

                        # record the finding of this dupe
                        found_duplicates.append((start, dup_size))
                        # log_debug("FOUND BOGUE: %d to %d same as %d to %d"
                        #              % (dup_head, int(dup_head)+int(dup_size), dup_start, int(dup_start)+int(dup_size)))
                        log_debug(
                            "FOUND BOGUE: %d to %d same as %d to %d"
                            % (start, dup_start, dup_start, dup_start + dup_size)
                        )
                        temp_file.write(dup_head)
                        start = dup_start + dup_size
                        break

                dup_start = dup_start + 128

            if not found_bogue:
                log_debug("No Bogue found, writing block and moving on.")
                # write the good section to the tempfile
                temp_file.write(block)
                start = start + 128

        # finally, shuffle files appropriately
        in_file.close()
        temp_file.close()

        if found_duplicates != [] or found_padding != []:
            # we made changes, so temp_file is the correct file to use:
            return_filename = temp_filename
            log_debug("We made changes, so keep the corrected file: %s" % temp_filename)

            # Report the duplicates we found (but not padding)
            if found_duplicates != []:
                duplicate_blocks = ", ".join(
                    ["%d to %d" % (start, end) for start, end in found_duplicates]
                )
                log_info(
                    "Eliminated duplicate data at %s in %s"
                    % (duplicate_blocks, in_filename)
                )
            if found_padding != []:
                log_info("Eliminated padding found in %s" % in_filename)
        else:
            log_debug("No duplicates or padding found in %s" % in_filename)
            log_debug("Deleting tempfile: %s" % temp_filename)
            os.remove(temp_filename)

    except:
        log_error("Error in Bogue processing")
        raise

    # finally:
    if in_file is not None and not in_file.closed:
        in_file.close()
    if temp_file is not None and not temp_file.closed:
        temp_file.close()

    return return_filename


def main():
    """Processes gliders files for Bogue syndrome

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    base_opts = BaseOpts.BaseOptions(
        "Processes gliders files for Bogue syndrome",
        additional_arguments={
            "input_file": BaseOptsType.options_t(
                None,
                ("Bogue",),
                ("input_file",),
                str,
                {
                    "help": "File to analyze for bogue syndrome",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )
    BaseLogger(base_opts)  # initializes BaseLog

    if base_opts.input_file:
        Bogue(base_opts.input_file)

    return 0


if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        retval = main()
    except SystemExit:
        pass
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
