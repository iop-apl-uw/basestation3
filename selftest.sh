#!/bin/tcsh

set base = "/home/seaglider"
# set base = "/server/work1/seaglider/www/selftests" 

if (! -d "$base"/sg"$1" ) then
    echo "no such glider, usage: selfcheck NNN"
    exit
endif

set count = `ls "$base"/sg"$1"/pt*.cap |& grep -v ls | wc -l`
if ( $count == 0 ) then
    if ( -f "$base"/sg"$1"/comm.log ) then
       echo "no selftest capture present - here is what we know from comm.log"
       grep st "$base"/sg"$1"/comm.log
    else
       echo "no selftests or comm.log present"
    endif
    exit
endif

set fname = `ls "$base"/sg"$1"/pt*.cap | sort | tail -1`
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
grep st"$testnum"k "$base"/sg"$1"/comm.log
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
set C0 = `grep sbe_cond_freq_C0 "$base"/sg"$1"/sg_calib_constants.m | cut -f2 -d= | cut -f1 -d';'`

if ($Cfreq == "") then
    set Cfreq = `grep -A 3 %data: "$base"/sg"$1"/pt"$1""$testnum".eng | tail -1 | cut -f12 -d' '`
else if (`printf %.0f $Cfreq` > 10000) then
    set Cfreq = `echo $Cfreq/1000 | bc -l`
endif
printf "Conductivity frequency=%.3f, Cal value=%.3f\n" $Cfreq $C0

set legatoPressure = `grep HLEGATO,N,pressure: $fname | cut -f2 -d: | cut -f1 -d' '`
if ($legatoPressure != "") then
    set sgcalLegatoPressure = `grep legato_sealevel "$base"/sg"$1"/sg_calib_constants.m`
    echo $sgcalLegatoPressure
    if ( "$sgcalLegatoPressure" != "" ) then
        echo "UPDATE: legato_sealevel = $legatoPressure; in sg_calib_constants.m"
    else
        echo "MISSING: Make sure to set legato_sealevel = $legatoPressure; in sg_calib_constants.m"
    endif
endif

set auxSlope = `grep -A 5 "type = auxCompass" $fname | grep coeff | head -n 1 | cut -f2 -d= | dos2unix`
set auxOffset = `grep -A 5 "type = auxCompass" $fname | grep coeff | tail -n 1 | cut -f2 -d= | dos2unix`
set gliderSlope = `grep \$PRESSURE_SLOPE "$base"/sg"$1"/pt"$1""$testnum".log | tail -n 1 | cut -f2 -d, | cat`
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
    set sg_val = `grep $parm "$base"/sg"$1"/"$fname".log | cut -f2 -d, | tail -n 1`
    set cal_val = `grep $cal "$base"/sg"$1"/sg_calib_constants.m | cut -f2 -d= | cut -f1 -d\;` 
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
cat "$base"/sg"$1"/"$fname".cap

echo ""
echo ------------------------------
set test = `grep '$ID' "$base"/sg"$1"/"$fname".cap`
if ( "$test" == "" ) then
    echo "Parameter comparison to log file $fname.log"
    echo
    /usr/local/bin/compare.py RevE "$base"/sg"$1"/"$fname".log
else
    echo "Parameter comparison to capture file $fname.cap"
    echo
    /usr/local/bin/compare.py RevE "$base"/sg"$1"/"$fname".cap 
endif

if ( -f "$base"/sg"$1"/p"$1"0000.prm ) then
    set date = `ls -l "$base"/sg"$1"/p"$1"0000.prm | awk '{print $6,$7,$8}'`
    echo ""
    echo ------------------------------
    echo Parameter comparison to prm file p"$1"0000.prm \("$date"\)
    echo
    /usr/local/bin/compare.py RevE "$base"/sg"$1"/p"$1"0000.prm
endif

