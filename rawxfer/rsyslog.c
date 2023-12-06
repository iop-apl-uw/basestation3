#define _GNU_SOURCE // for VASPRINTF

#include <stdio.h>
#include <stdarg.h>
#include <stdlib.h>
#include <time.h>
#include <syslog.h>

void
rsyslog(int priority, char *format, ...)
{
    char    *ptr;
    va_list  ap;
    FILE    *fp;
    char     logname[64];
    time_t   now;
 
    va_start(ap, format);
    vasprintf(&ptr, format, ap);
    va_end(ap);

    //snprintf(logname, 63, "%s/comm.log", getenv("HOME"));
    //fp = fopen(logname, "ab");
    fp = fopen("comm.log", "ab");
    if (fp == NULL) {
        syslog(priority, "rawxfer [%s] %s", getenv("USER"), ptr);
    }
    else {
        now = time(NULL);
        strftime(logname, 63, "%Y-%m-%dT%H:%M:%SZ", gmtime(&now));
        fprintf(fp, "%s [%s] %s\n", logname, getenv("USER"), ptr);
        fclose(fp);
    }

    free(ptr);
}    
    
