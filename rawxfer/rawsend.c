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
#include <time.h>

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
        lsyslog(0, "Sending %u bytes of %s", size, fname);
    
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
        lsyslog(0, "Sent %u bytes of %s", sent, fname);

    tcsetattr(1, TCSANOW, &orig_tios);

    fclose(fp);
    return 0;
}
