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
#include <sys/time.h>
#include <termios.h>
#include <unistd.h>
#include <string.h>
#include <ctype.h>
#include "md5.h"

extern void rsyslog(int prio, const char *format, ...);

char *
strip(char *f)
{
    char *o = f;
    int i = 0;

    while(*f) {
        if (isalnum(*f) || *f == '.' || *f == '_' || *f == '+') {
            o[i] = *f;
            i ++;
        }
        f ++;
    }

    o[i] = 0;
    return o;
}

int
batch(int argc, char *argv[])
{
    struct termios tios, orig_tios;

    FILE          *fp;
    int            num_to_receive;
    unsigned int   nread;
    struct stat    statbuf;
    unsigned char *sizebuf;
    unsigned char  header[53];
    unsigned int   size;
    struct timeval start, stop;
    struct timeval timeout;
    double         secs;
    int            fd;
    fd_set         fds;
    unsigned char  c;
    char          *md5_in = NULL;
    char           md5_out[65];
    int            i;
    char          *fname;
    char          *prevName = NULL;

    if (argc != 2) {
        printf("NO!"); fflush(stdout);
        return 1;
    }

    num_to_receive = atoi(argv[1]);
    if (num_to_receive < 1) {
        printf("NO!"); fflush(stdout);
        return 1;
    }

    tcgetattr(0, &tios);
    tcgetattr(0, &orig_tios);
    tios.c_iflag = IGNBRK;
    tios.c_oflag = 0;
    // tios.c_lflag &= ~ICANON;
    tios.c_lflag = 0; 
    tcsetattr(0, TCSANOW, &tios);

    rsyslog(0, "ready to receive %d files", num_to_receive);

    printf("READY!"); fflush(stdout);

    for (i = 0 ; i < num_to_receive ; ) {

        nread = 0;
        while(nread < 52) {
            timeout.tv_sec = 20;
            timeout.tv_usec = 0;
            FD_ZERO(&fds);
            FD_SET(0, &fds);
        
            if (select(1, &fds, NULL, NULL, &timeout) > 0) {
                if (read(0, &c, 1) == 1) {
                    header[nread ++] = c;
                }
                else {
                    break;
                }
            }
            else {
                break;
            }
        }
    
        if (nread != 52) {
            rsyslog(0, "did not receive 52 header bytes");
            return 1;
        }

        sizebuf = (unsigned char *) &size;

        sizebuf[3] = header[0];
        sizebuf[2] = header[1];
        sizebuf[1] = header[2];
        sizebuf[0] = header[3];

        fname  = &(header[4]);
        fname[15] = 0;
        md5_in = &(header[20]);
        md5_in[32] = 0;

        //if (!isalnum(fname[0])) {
        //    rsyslog(0, "bad filename %s", fname);
        //    return 1;
        //}

        strip(fname);
        if (fname[0] == 0) {
            rsyslog(0, "bad filename");
            return 1;
        }
        rsyslog(0, "Receiving %u bytes of %s", size, fname);

        fp = fopen(fname, "wb");

        gettimeofday(&start, NULL);
       
        nread = 0;
        while(nread < size) {
            timeout.tv_sec = 20;
            timeout.tv_usec = 0;
            FD_ZERO(&fds);
            FD_SET(0, &fds);

            if (select(1, &fds, NULL, NULL, &timeout) > 0) {
                if (read(0, &c, 1) == 1) {
                    fputc(c, fp);
                    nread ++;
                }
                else {
                    break;
                }
            }
            else {
                break;
            }
        }

        fflush(fp);

        gettimeofday(&stop, NULL);

        secs = (stop.tv_sec - start.tv_sec) + (stop.tv_usec - start.tv_usec)/1e6;

        rsyslog(0, "Received %u bytes of %s (%.1f Bps)", nread, fname, nread/secs);

        fclose(fp);

        md5_compute(fname, md5_out);
        if (size != nread) {
            printf("E0");
            rsyslog(0, "E0 %u %u", size, nread); 
        }
        // this is a redundant size check in regular raw.2
        // else if (size != size2) {
        //     printf("E1");
        //    rsyslog(0, "E1 %u %u", size, size2);
        // }
        else if (strcmp(md5_in, md5_out)) {
            printf("E2"); 
            rsyslog(0, "E2 %s %s", md5_in, md5_out); 
        }
        else {
            printf("OK");
            rsyslog(0, "OK");
            // if the receiver does not receive our OK they will
            // likely try to send the file again. Only increment
            // our count of received files for uniquely received
            // names. 
            if (prevName == NULL || strcmp(prevName, fname)) {
                i ++;
            }
            if (prevName) free(prevName);
            prevName = strdup(fname);
        }

        fflush(stdout);
    }

    tcsetattr(0, TCSANOW, &orig_tios);
    return 0;
}

int
main(int argc, char *argv[])
{
    struct termios tios, orig_tios;

    FILE          *fp;
    unsigned int   nread;
    struct stat    statbuf;
    unsigned char *sizebuf;
    unsigned char  swapbuf[4];
    unsigned int   size;
    struct timeval start, stop;
    struct timeval timeout;
    double         secs;
    int            fd;
    fd_set         fds;
    unsigned char  c;
    unsigned int   size2 = 0;
    char          *md5_in = NULL;
    char           md5_out[65];

    if (strncmp(argv[0], "rawrcvb", 7) == 0) {
        return batch(argc, argv);
    }

    if (argc < 2 || argc == 3 || argc > 4 || (fp = fopen(argv[1], "wb")) == NULL) {
        printf("NO!"); fflush(stdout);
        return 1;
    }

    if (argc == 4) {
        size2 = atol(argv[2]);
        md5_in = argv[3];
    }
 
    tcgetattr(0, &tios);
    tcgetattr(0, &orig_tios);
    tios.c_iflag = IGNBRK;
    tios.c_oflag = 0;
    // tios.c_lflag &= ~ICANON;
    tios.c_lflag = 0; 
    tcsetattr(0, TCSANOW, &tios);

    rsyslog(0, "ready to receive %s", argv[1]);

    printf("READY!"); fflush(stdout);

    nread = 0;
    while(nread < 4) {
        timeout.tv_sec = 20;
        timeout.tv_usec = 0;
        FD_ZERO(&fds);
        FD_SET(0, &fds);
        
        if (select(1, &fds, NULL, NULL, &timeout) > 0) {
            if (read(0, &c, 1) == 1) {
                swapbuf[nread ++] = c;
            }
            else {
                break;
            }
        }
        else {
            break;
        }
    }
    
    if (nread != 4) {
        rsyslog(0, "did not receive four size bytes for %s", argv[1]);
        return 1;
    }

    sizebuf = (unsigned char *) &size;

    sizebuf[3] = swapbuf[0];
    sizebuf[2] = swapbuf[1];
    sizebuf[1] = swapbuf[2];
    sizebuf[0] = swapbuf[3];

    rsyslog(0, "Receiving %u bytes of %s", size, argv[1]);

    gettimeofday(&start, NULL);
   
    nread = 0;
    while(nread < size) {
        timeout.tv_sec = 20;
        timeout.tv_usec = 0;
        FD_ZERO(&fds);
        FD_SET(0, &fds);

        if (select(1, &fds, NULL, NULL, &timeout) > 0) {
            if (read(0, &c, 1) == 1) {
                fputc(c, fp);
                nread ++;
            }
            else {
                break;
            }
        }
        else {
            break;
        }
    }

    fflush(fp);

    gettimeofday(&stop, NULL);

    secs = (stop.tv_sec - start.tv_sec) + (stop.tv_usec - start.tv_usec)/1e6;

    rsyslog(0, "Received %u bytes of %s (%.1f Bps)", nread, argv[1], nread/secs);

    fclose(fp);

    if (argc == 4) {
        md5_compute(argv[1], md5_out);
        if (size != nread) {
            printf("E0");
            rsyslog(0, "E0 %u %u", size, nread); 
        }
        else if (size != size2) {
            printf("E1");
            rsyslog(0, "E1 %u %u", size, size2);
        }
        else if (strcmp(md5_in, md5_out)) {
            printf("E2"); 
            rsyslog(0, "E2 %s %s", md5_in, md5_out); 
        }
        else {
            printf("OK");
            rsyslog(0, "OK");
        }

        fflush(stdout);
    }

    tcsetattr(0, TCSANOW, &orig_tios);
    return nread < size ? 1 : 0;
}
