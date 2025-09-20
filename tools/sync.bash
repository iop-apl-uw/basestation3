#!/usr/bin/bash
#
# Example script to propagage gliders mission directory after basestation
# processing has completed.
#
# Insert a line like this into your crontab
#
# *  *  *  *  * bash /usr/local/basestation3/tools/sync.bash
#
LAST_SYNC=~/last_sync
GLIDER_MISSION_DIR=<insert_glider_mission_dir_here>
if ! test -f "${GLIDER_MISSION_DIR}/.completed"; then
    exit 0
fi
if ! test -f "${LAST_SYNC}"; then
    last_sync_t=0
else
    last_sync_t=`stat -c '%Y' ${LAST_SYNC}`
fi
last_complete_t=`stat -c '%Y' ${GLIDER_MISSION_DIR}/.completed`
if [[ ${last_complete_t} > ${last_sync_t} ]]; then
    echo Sync `date -u +%y%m%d%H%M%S%3N` >> ~/sync.log 2>&1
    # Insert rsync command here
    touch ${LAST_SYNC}
fi
