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

# Routines for dumping array contents to a file for later comparison w/
# another program.  See trace_results_stop, trace_array, etc.
# for ((i=1; i<280; i=i+1)); do echo -n $i; diff trace_$i.ptrc trace_$i.mtrc | wc; done
# Results are dumped in a form that could be easily modified to be
# readable in either MATLAB or python for progreammatic comparison

from typing import Any

TRACE_DATA:list[Any] = [];
TRACE_STATUS:list[Any] = [];

def trace_results(file:str, tag:str)->None:
    global TRACE_DATA;
    if (trace_disabled()):
        return None
    if (len(TRACE_DATA)):
        trace_comment('Trace file not properly closed!!')
        trace_results_stop()
        
    fid = open(file, 'w'); # was 'a'
    # PARAMETER was 10, no more than 16 since 2^53 = 9007199254740992L
    # if zero, just use normal significance
    # if < 9, no changes in reported small differences 
    # if >= 9 the number of tiny differences increases
    # CONSIDER a binary dump of arrays and compare program
    precision = 0;
    format = '%g';
    nc = 6;
    if (precision):
        format = '%%.%dg' % (precision);
        nc = int(65/(precision+4));
    comment = '%'; # % or #
    cont = '%sE' % (comment); # end of line continuation
    TRACE_DATA = [None, fid, file, nc, format, comment, cont]; # state, add None so addressing doesn't change from MATLAB version
    trace_comment('Starting trace in %s, precision %d' % (file, precision));
    trace_comment(tag);

# disable tracing
def trace_enable()->None:
    global TRACE_STATUS;
    TRACE_STATUS = [];

def trace_disable()->None:
    global TRACE_STATUS;
    TRACE_STATUS = [1];

# is tracing enabled?
def trace_disabled()->int:
    global TRACE_STATUS;
    return len(TRACE_STATUS);

# stop tracing
def trace_results_stop()->None:
    global TRACE_DATA;
    if (trace_disabled()):
        trace_enable();
    if (len(TRACE_DATA)):
        trace_comment('Ending trace');
        fid = TRACE_DATA[1];
        fid.close();
        TRACE_DATA = [];

def trace_array(tag:str, x:Any)->None:
    global TRACE_DATA;
    if (trace_disabled()):
        return None
    trace_ensure_file();
    fid = TRACE_DATA[1];
    # ignore filename in TRACE_DATA[2]
    nc = TRACE_DATA[3];
    format = TRACE_DATA[4]; # numeric format
    comment = TRACE_DATA[5];
    cont = TRACE_DATA[6];

    fid.write('%s %s = %s\n' % (comment, tag, cont));
    fid.write('[');
    prefix = '';
    # M for i=1:len(x)
    start = 0;
    for i in range(len(x)):
        fid.write('%s' % (prefix));
        if ((i+1) % nc == 0):
            fid.write('%s %s %d\n' % (cont, tag, start+1)); # consider adding tag to line as well...matlab index
            start = i;
        fid.write(format % x[i] );
        prefix = ', ';
    fid.write(']\n'); # no continuation here


# dump a comment to the trace file
def trace_comment(tag:str)->None:
    global TRACE_DATA;
    if (trace_disabled()):
        return
    trace_ensure_file();
    fid = TRACE_DATA[1];
    comment = TRACE_DATA[5];
    fid.write('%s %s\n' % (comment, tag));

# ensure there is a trace file
def trace_ensure_file() -> None:
    global TRACE_DATA;
    if (len(TRACE_DATA) == 0):
        print("Run trace_results() before calling trace routines!\n");
