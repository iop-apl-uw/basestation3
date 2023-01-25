#
# Copyright (c) 1997-2013, 2023 University of Washington.  All rights reserved.
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

install:
	sudo cp --remove-destination rawsend /usr/local/bin/rawsend
	sudo cp --remove-destination rawrcv2 /usr/local/bin/rawrcv2
	sudo ln -s -f /usr/local/bin/rawrcv2 /usr/local/bin/rawrcv
	sudo ln -s -f /usr/local/bin/rawrcv2 /usr/local/bin/rawrcvb
