// Copyright (c) 2023  University of Washington.
// 
// Redistribution and use in source and binary forms, with or without
// modification, are permitted provided that the following conditions are met:
// 
// 1. Redistributions of source code must retain the above copyright notice, this
//    list of conditions and the following disclaimer.
// 
// 2. Redistributions in binary form must reproduce the above copyright notice,
//    this list of conditions and the following disclaimer in the documentation
//    and/or other materials provided with the distribution.
// 
// 3. Neither the name of the University of Washington nor the names of its
//    contributors may be used to endorse or promote products derived from this
//    software without specific prior written permission.
// 
// THIS SOFTWARE IS PROVIDED BY THE UNIVERSITY OF WASHINGTON AND CONTRIBUTORS “AS
// IS” AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
// IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
// DISCLAIMED. IN NO EVENT SHALL THE UNIVERSITY OF WASHINGTON OR CONTRIBUTORS BE
// LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
// CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE
// GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION)
// HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT
// LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT
// OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

#include <stdio.h>
#include <stdlib.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>
#include <time.h>
#include <string.h>

extern void rsyslog(int prio, const char *format, ...);

int
main(int argc, char *argv[])
{
    FILE          *fp;
    unsigned char  buff[1024];
    int            nread;
    unsigned int   sent;
    struct stat    statbuf;
    unsigned char *sizebuf;
    unsigned char  swapbuf[4];
    unsigned int   size;
    struct termios tios, orig_tios;
    time_t         start, end;
    char          *fname = NULL;
    int            verbose = 0;

    if (argc == 3 && strcmp(argv[1], "-v") == 0) {
        verbose = 1;    
        fname = argv[2];
    }
    else if (argc == 2)
        fname = argv[1];
 
    if (fname == NULL || (fp = fopen(fname, "rb")) == NULL) {
        printf("NO!"); fflush(stdout);
        return 1;
    }

    stat(fname, &statbuf);
    size = statbuf.st_size;
    sizebuf = (unsigned char *) &size;
    swapbuf[3] = sizebuf[0];
    swapbuf[2] = sizebuf[1];
    swapbuf[1] = sizebuf[2];
    swapbuf[0] = sizebuf[3];

    printf("READY!"); fflush(stdout);

    if (verbose)
        fprintf(stderr, "Sending %u bytes of %s\r\n", size, fname);
    else
        rsyslog(0, "Sending %u bytes of %s", size, fname);
    
    tcgetattr(1, &tios);
    tcgetattr(1, &orig_tios);
    tios.c_iflag = IGNBRK;
    tios.c_oflag = 0;
    tcsetattr(1, TCSANOW, &tios);

    start = time(NULL);

    write(1, swapbuf, 4);
    tcdrain(1);

    sent = 0;
    while(!feof(fp)) {         
        nread = fread(buff, sizeof(unsigned char), 1024, fp);
        if (nread) {
            sent += write(1, buff, nread);
            tcdrain(1);
        }
        if (verbose)
            fprintf(stderr,"%u bytes of %u\r", sent, size);
    }

    end = time(NULL);

    if (verbose)    
        fprintf(stderr,"\nComplete %f bytes/sec\r\n",
                sent / (float) (end - start));
    else
        rsyslog(0, "Sent %u bytes of %s", sent, fname);

    tcsetattr(1, TCSANOW, &orig_tios);

    fclose(fp);
    return 0;
}
