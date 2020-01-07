//
// Copyright (c) 1997-2013 University of Washington.  All rights reserved.
//
// This file contains proprietary information and remains the 
// unpublished property of the University of Washington. Use, disclosure,
// or reproduction is prohibited except as permitted by express written
// license agreement with the University of Washington.
//

#include <stdio.h> 
#include <stdlib.h>
#include <sys/stat.h>
#include <termios.h>
#include <unistd.h>

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
    

    if (argc != 2 || (fp = fopen(argv[1], "wb")) == NULL) {
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

    lsyslog(0, "ready to receive %s", argv[1]);

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
        lsyslog(0, "did not receive four size bytes for %s", argv[1]);
        return 1;
    }
    else {
        lsyslog(0, "received four size bytes %u %u %u %u",
                swapbuf[0], swapbuf[1], swapbuf[2], swapbuf[3]);
    }

    sizebuf = (unsigned char *) &size;

    sizebuf[3] = swapbuf[0];
    sizebuf[2] = swapbuf[1];
    sizebuf[1] = swapbuf[2];
    sizebuf[0] = swapbuf[3];

    lsyslog(0, "Receiving %u bytes of %s", size, argv[1]);

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

    lsyslog(0, "Received %u bytes of %s (%.1f Bps)", nread, argv[1], nread/secs);

    fclose(fp);
    tcsetattr(0, TCSANOW, &orig_tios);
    return nread < size ? 1 : 0;
}
