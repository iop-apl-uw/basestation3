#!/bin/tcsh

## Copyright (c) 2023  University of Washington.
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


if ( $#argv == 2) then
    set base = $2
else
    set base = /home/seaglider/sg"$1"
    # set base = "/server/work1/seaglider/www/selftests" 
endif


if (! -d $base ) then
    echo "no such glider, usage: selfcheck NNN"
    exit
endif

set count = `ls "$base"/pt*.cap |& grep -v ls: | wc -l`
if ( $count == 0 ) then
    if ( -f "$base"/comm.log ) then
       echo "no selftest capture present - here is what we know from comm.log"
       grep st "$base"/comm.log
    else
       echo "no selftests or comm.log present"
    endif
    exit
endif

set fname = `ls -t "$base"/pt*.cap | head -n 1`
set capname = $fname

if ($fname == "" || ! -f $fname ) then
    echo "no selftest capture file (ptNNNMMMM.cap)"
    exit
endif
echo "--------------------------------------------"
set glider = `basename $fname | cut -b3-5`
set testnum = `basename $fname | cut -b6-9`
set date = `grep "RTC time" $fname | cut -f3-8 -d' '`
set filedate = `ls -l $fname | awk '{print $6,$7,$8}'`
echo $fname \("$filedate"\) $glider \#"$testnum" $date
echo "--------------------------------------------"
echo "Summary of comm.log (snippet) for most recent test capture"
echo
grep st"$testnum"k "$base"/comm.log
echo
echo "--------------------------------------------"
echo "Summary of motor moves"
echo
grep omplete $fname | cut -f4- -d, | sed 's/completed from//' | sed 's/ sec /s /' | sed 's/ took /\t/' | sed 's/  /\t/' | sed 's/ cc/cc/g' | sed 's/ deg/deg/g' | sed 's/ cm/cm/g' | sed 's/ [0-9]* ticks//' | sed 's/Vmin/V/g' | grep -v "list complete" | grep -v "call try complete" | grep -v "Measured depth:"
echo ""
echo "--------------------------------------------"
echo "Summary of failures, warnings and errors"
echo
grep -i fail $fname | grep -v HPHONE | grep -v "error failed"
grep -i error $fname | grep -v _MAXERRORS | grep -v "error failed"
grep -i warning $fname
grep -i retr $fname | grep -v gc=
echo ""
echo "--------------------------------------------"
echo "Summary of sensor values"
echo

set press_counts = `grep Mean: $fname | tail -n 1 | cut -f2 -d: | awk '{print $1}'`
set press_offset = `grep ,\$PRESSURE_YINT, $fname | tail -n 1 | cut -f5 -d,`

if ($press_counts == "" || $press_offset == "") then
    echo "insufficient data to check pressure parameters"
else
    if (`echo "$press_counts < 100000" | bc`) then
        echo "pressure counts are low"
    endif
    if (`echo "$press_offset < -200" | bc` || `echo "$press_offset > -20" | bc`) then
        echo "pressure offset out of range $press_offset"
    endif
endif

grep "No SMS email address set" $fname

grep "internal humidity" $fname | cut -f4 -d,
grep "internal pressure" $fname | cut -f4 -d,
grep "Current location" $fname | cut -f4- -d,

set Cfreq = `grep "^ct:" $fname | tail -n 1 | cut -f2 -d' '`
set C0 = `grep sbe_cond_freq_C0 "$base"/sg_calib_constants.m | cut -f2 -d= | cut -f1 -d';'`

if ($Cfreq == "") then
    set Cfreq = `grep -A 3 %data: "$base"/pt"$1""$testnum".eng | tail -1 | cut -f12 -d' '`
else if (`printf %.0f $Cfreq` > 10000) then
    set Cfreq = `echo $Cfreq/1000 | bc -l`
endif
printf "Conductivity frequency=%.3f, Cal value=%.3f\n" $Cfreq $C0

set legatoPressure = `grep HLEGATO,N,pressure: $fname | cut -f2 -d: | cut -f1 -d' '`
if ($legatoPressure != "") then
    set sgcalLegatoPressure = `grep legato_sealevel "$base"/sg_calib_constants.m`
    echo $sgcalLegatoPressure
    if ( "$sgcalLegatoPressure" != "" ) then
        echo "UPDATE: legato_sealevel = $legatoPressure; in sg_calib_constants.m"
    else
        echo "MISSING: Make sure to set legato_sealevel = $legatoPressure; in sg_calib_constants.m"
    endif
endif

set auxSlope = `grep -A 5 "type = auxCompass" $fname | grep coeff | head -n 1 | cut -f2 -d= | dos2unix`
set auxOffset = `grep -A 5 "type = auxCompass" $fname | grep coeff | tail -n 1 | cut -f2 -d= | dos2unix`
set gliderSlope = `grep \$PRESSURE_SLOPE "$base"/pt"$1""$testnum".log | tail -n 1 | cut -f2 -d, | cat`
if ($auxSlope != "" && $auxOffset != "") then 
    set ratio = `echo "1000*$auxSlope"/"$gliderSlope" | bc`
    if ( !($ratio > 990 && $ratio < 1005) && !($ratio > 2080 && $ratio < 2090) )  then
        echo "aux pressure slope looks sketchy ($auxSlope,$gliderSlope,$ratio)"
    endif
else
    echo "no aux pressure slope and offset detected"
endif

set ndat_files = `grep -c SG0...DZ $fname`
set nsc_files = `grep -c SC0....Z $fname`
if ( $ndat_files > 10 || $nsc_files > 10 ) then
    echo "There are a lot of old dive or SciCon data files onboard!"
endif

set fname = `basename $fname .cap`
foreach cal (t_g t_h t_i t_j c_g c_h c_i c_j) 
    set upper = `echo $cal | tr '[:lower:]' '[:upper:]'`
    set parm = `printf 'SEABIRD_%s' $upper`
    set sg_val = `grep $parm "$base"/"$fname".log | cut -f2 -d, | tail -n 1`
    set cal_val = `grep $cal "$base"/sg_calib_constants.m | cut -f2 -d= | cut -f1 -d\;` 
    set sgc = `printf "%.8f" $sg_val`
    set cac = `printf "%.8f" $cal_val`
    if ( $cac == "0.00000000" ) then
        set ratio = 0
    else
        set ratio = `echo "1000*$sgc/$cac" | bc`
    endif
    if ( !($ratio > 990 && $ratio < 1010) ) then
       echo "value for $cal does not match in sg_calib_constants.m $cac and on glider $sgc"
    endif
end

echo "--------------------------------------------"
echo "Raw capture"
echo 
cat "$base"/"$fname".cap

echo ""
echo ------------------------------
set test = `grep '$ID' "$base"/"$fname".cap`
if ( "$test" == "" ) then
    echo "Parameter comparison to log file $fname.log"
    echo
    /usr/local/bin/compare.py RevE "$base"/"$fname".log
else
    echo "Parameter comparison to capture file $fname.cap"
    echo
    /usr/local/bin/compare.py RevE "$base"/"$fname".cap 
endif

if ( -f "$base"/p"$1"0000.prm ) then
    set date = `ls -l "$base"/p"$1"0000.prm | awk '{print $6,$7,$8}'`
    echo ""
    echo ------------------------------
    echo Parameter comparison to prm file p"$1"0000.prm \("$date"\)
    echo
    /usr/local/bin/compare.py RevE "$base"/p"$1"0000.prm
endif

