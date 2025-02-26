#!/bin/sh
ii=0
while [ $ii -le 10000 ]
do
    echo $ii stdout
    echo $((ii + 1)) stderr  >&2
    ii=$((ii + 2))
done
