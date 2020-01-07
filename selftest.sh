#!/bin/sh
## 
## Copyright (c) 2014,2015,2016 University of Washington.  All rights reserved.
## 
## This file contains proprietary information and remains the 
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
for cap_file in `ls -1 -ta pt*.cap | head -1`; do
  echo Scanning $cap_file in `pwd`
  eng_file=`basename -s .cap "$cap_file"`.eng
  # report all motor moves
  grep omplete $cap_file | grep -v GPS | cut -f4- -d, | sed 's/completed from//' | sed 's/ sec /s /' | sed 's/ took /\t/' | sed 's/  /\t/' | sed 's/ cc/cc/g' | sed 's/ deg/deg/g' | sed 's/ cm/cm/g' | sed 's/ [0-9]* ticks//' | sed 's/Vmin/V/g'
  echo
  # Report SW version
  # grep 'N,Version:' $cap_file
  # grep 'Compiled on:' $cap_file
  # look for surprises
  grep '!' $cap_file  | cut -f4-5 -d,
  # look for CRITICALs and skip the compass coefficients
  grep ',C,' $cap_file | grep -v 'A,B,C'  | cut -f4-5 -d,
  # look for ERROR (but not ERRORS)
  grep 'ERROR' $cap_file | grep -v 'ERRORS' | grep -v 'HPHONE,N,NUM:'  | cut -f4-5 -d,
  # look for warnings and failures
  egrep -i '(warn|fail|-->)' $cap_file | egrep -v '(CREG|Expected)'  | cut -f4-5 -d,
  # look for interrupts (typically spurious)
  grep 'interrupt' $cap_file | egrep -v '(stack|continue)'  | cut -f4 -d,
  grep "internal humidity" $cap_file | cut -f4 -d,
  grep "internal pressure" $cap_file | cut -f4 -d,
  grep "bathymap" $cap_file | cut -f4 -d, | sort
  grep "Current location" $cap_file | cut -f4-5 -d,
  # look for missing data (in eng files)
  echo -n Data lines with timed out or missing values in $eng_file ': '
  egrep --count '(NaN|9999)' $eng_file
  echo 
done
