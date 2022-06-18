#
# Copyright (c) 1997-2013 University of Washington.  All rights reserved.
#
# This file contains proprietary information and remains the 
# unpublished property of the University of Washington. Use, disclosure,
# or reproduction is prohibited except as permitted by express written
# license agreement with the University of Washington.
#

CC = gcc

all:    rawrcv2 rawsend

rawrcv2: rawrcv.o lsyslog.o md5.o
		$(CC) -o rawrcv2 rawrcv.o lsyslog.o md5.o

rawsend: rawsend.o lsyslog.o
		$(CC) -o rawsend rawsend.o lsyslog.o
