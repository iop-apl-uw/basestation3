#!/usr/bin/env python
# -*- python-fmt -*-

#
# Derived from the minigzip.py in the Python distribution
#

# Demo program for zlib; it compresses or decompresses files, but *doesn't*
# delete the original.  This doesn't support all of gzip's options.
#
# The 'gzip' module in the standard library provides a more complete
# implementation of gzip-format files.

# We use this in the basestation instead of the standard gzip because we have
# more control over the error conditions with this module.  The standard gzip
# module is pickier then the command line gzip on CRC checks and trailing extra
# garbage - both of which show up in the typical glider uploads.

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

""" Basestation implimentation of gzip and gunzip
"""

import cProfile
import io
import os
import pstats
import sys
import time
import zlib

import BaseOpts
from BaseLog import BaseLogger, log_error, log_debug, log_critical, log_info
import Utils

FTEXT, FHCRC, FEXTRA, FNAME, FCOMMENT = 1, 2, 4, 8, 16


def write32(output, value):
    """Output a 32 bit value as a char"""
    output.write(chr(value & 255))
    value = value // 256
    output.write(chr(value & 255))
    value = value // 256
    output.write(chr(value & 255))
    value = value // 256
    output.write(chr(value & 255))


def read32(input_file):
    """Read a 32 bit value as a char and convert to an int"""
    v = ord(input_file.read(1))
    v += ord(input_file.read(1)) << 8
    v += ord(input_file.read(1)) << 16
    v += ord(input_file.read(1)) << 24
    return v


def compress(input_file_name, output_file_or_file_name):
    """Compress one file into another
    Input:
        input_file_name - file name
        output_file_or_file_name - file name or object with write method
    """
    try:
        input_file = open(input_file_name, "rb")
    except IOError as exception:
        log_error("Could not open %s (%s)" % (input_file_name, exception.args))
        return 1

    if isinstance(output_file_or_file_name, str):
        try:
            output_file = open(output_file_or_file_name, "wb")
        except IOError as exception:
            log_error(
                "Could not open %s (%s)" % (output_file_or_file_name, exception.args)
            )
            return 1
    elif hasattr(output_file_or_file_name, "write"):
        output_file = output_file_or_file_name
    else:
        log_error(
            "Unknown type %s for output argument" % type(output_file_or_file_name)
        )
        return 1

    output_file.write("\037\213\010")  # Write the header, ...
    output_file.write(chr(FNAME))  # ... flag byte ...

    statval = os.stat(input_file_name)  # ... modification time ...
    mtime = statval[8]
    write32(output_file, mtime)
    output_file.write("\002")  # ... slowest compression alg. ...
    output_file.write("\377")  # ... OS (=unknown) ...
    output_file.write(input_file_name + "\000")  # ... original filename ...

    crcval = zlib.crc32("")
    compobj = zlib.compressobj(9, zlib.DEFLATED, -zlib.MAX_WBITS, zlib.DEF_MEM_LEVEL, 0)
    while True:
        data = input_file.read(1024)
        if data == "":
            break
        crcval = zlib.crc32(data, crcval)
        output_file.write(compobj.compress(data))
    output_file.write(compobj.flush())
    write32(output_file, crcval)  # ... the CRC ...
    write32(output_file, statval[6])  # and the file size.


# def unsigned(n):
#    return n & 4294967295


def U32(i):
    """Return i as an unsigned integer, assuming it fits in 32 bits.

    If it's >= 2GB when viewed as a 32-bit unsigned int, return a long.
    """
    if i < 0:
        i += 1 << 32
    return i


def decompress(input_file_name, output_file_or_file_name):
    """Takes two open files as input
    Return 0 for success, -1 for warning, 1 for failure
    """
    # set up logging
    retval = 0

    try:
        input_file = open(input_file_name, "rb")
    except IOError as exception:
        log_error("Could not open %s (%s)" % (input_file_name, exception.args))
        return 1

    if isinstance(output_file_or_file_name, str):
        try:
            output_file = open(output_file_or_file_name, "wb")
        except IOError as exception:
            log_error(
                "Could not open %s (%s)" % (output_file_or_file_name, exception.args)
            )
            return 1
    elif isinstance(output_file_or_file_name, io.IOBase):
        output_file = output_file_or_file_name
    else:
        log_error(
            "Unknown type %s for output argument" % type(output_file_or_file_name)
        )
        return 1

    magic = input_file.read(2)
    # if magic != '\037\213':
    if magic[0] != 0x1F or magic[1] != 0x8B:
        log_error("%s not a gzipped file" % input_file_name)
        return 1
    if ord(input_file.read(1)) != 8:
        log_error("Unknown compression method for %s" % input_file_name)
        return 1
    flag = ord(input_file.read(1))
    input_file.read(4 + 1 + 1)  # Discard modification time,
    # extra flags, and OS byte.
    if flag & FEXTRA:
        # Read & discard the extra field, if present
        xlen = ord(input_file.read(1))
        xlen += 256 * ord(input_file.read(1))
        input_file.read(xlen)
    if flag & FNAME:
        # Read and discard a null-terminated string containing the filename
        while True:
            s = input_file.read(1)
            if s == "\0" or s == b"\x00":
                break

    if flag & FCOMMENT:
        # Read and discard a null-terminated string containing a comment
        while True:
            s = input_file.read(1)
            if s == "\0" or s == b"\x00":
                break
    if flag & FHCRC:
        input_file.read(2)  # Read & discard the 16-bit header CRC

    decompobj = zlib.decompressobj(-zlib.MAX_WBITS)
    crcval = zlib.crc32("".encode())

    length = 0
    data_block = 0
    while True:
        data = input_file.read(1024)
        if not data:
            break
        try:
            decompdata = decompobj.decompress(data)
        except zlib.error as exception:
            log_error(
                "Error while decompressing %s (%s) on data block %d"
                % (input_file_name, exception.args, data_block)
            )
            retval = 1
        else:
            output_file.write(decompdata)
            length += len(decompdata)
            crcval = zlib.crc32(decompdata, crcval)
        data_block = data_block + 1

    decompdata = decompobj.flush()
    output_file.write(decompdata)
    length += len(decompdata)
    crcval = zlib.crc32(decompdata, crcval)
    log_debug(
        "Computed CRC = 0x%08x, Outfile file length = 0x%x" % (U32(crcval), length)
    )

    # We've read to the end of the file, so we have to rewind in order
    # to reread the 8 bytes containing the CRC and the file size.  The
    # decompressor is smart and knows when to stop, so feeding it
    # extra data is harmless.
    input_file.seek(-8, 2)
    crc32 = read32(input_file)
    isize = read32(input_file)
    #
    # HACK ALERT - this deals with the files that have the extra \x1a at the end of them
    #
    if (crc32 != U32(crcval)) and (isize != length):
        input_file.seek(-1, 2)
        check_1a = input_file.read(1)
        if check_1a == "\x1a".encode():
            # Found a trailing 1a - try to re-calc the crc and filelen w/o this value
            log_info(
                "Bad CRC and file len and %s has a trailing 1a - trying to recalc the crc and file length without it"
                % input_file_name
            )
            input_file.seek(-9, 2)
            crc32 = read32(input_file)
            isize = read32(input_file)
            # Fall through to the normal checks

    log_debug("File provided CRC = 0x%x, File provided length = 0x%x" % (crc32, isize))
    if crc32 != U32(crcval):
        log_error(
            "CRC check failed on %s - expected 0x%s, generated 0x%x"
            % (input_file_name, crc32, U32(crcval))
        )
        retval = 1
    if isize != length:
        log_error(
            "Incorrect length of data produced from %s - expected 0x%x, generated 0x%x"
            % (input_file_name, isize, length)
        )
        retval = 1
    else:
        log_debug(
            "Data produced from decompression of %s - expected 0x%x, generated 0x%x"
            % (input_file_name, isize, length)
        )
    input_file.close()
    output_file.close()
    return retval


def main():
    """Decompresses files from the glider to stdout

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    base_opts = BaseOpts.BaseOptions(
        "Decompresses files from the glider to stdout",
        additional_arguments={
            "compressed_file": BaseOpts.options_t(
                None,
                ("BaseGZip",),
                ("compressed_file",),
                str,
                {
                    "help": "File to decompress",
                    "action": BaseOpts.FullPathAction,
                },
            ),
        },
    )

    BaseLogger(base_opts)  # initializes BaseLog

    decompress(base_opts.compressed_file, f"{base_opts.compressed_file}.decomp")
    return 0


if __name__ == "__main__":
    ret_val = 1

    # Force to be in UTC
    os.environ["TZ"] = "UTC"
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove("--profile")
            profile_file_name = (
                os.path.splitext(os.path.split(sys.argv[0])[1])[0]
                + "_"
                + Utils.ensure_basename(
                    time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))
                )
                + ".cprof"
            )
            # Generate line timings
            ret_val = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats("time", "calls")
            stats.print_stats()
        else:
            ret_val = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(ret_val)
