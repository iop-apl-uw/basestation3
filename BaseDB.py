import sys
sys.path.append('/usr/local/basestation3')
import numpy
import Utils
import os.path
import glob
import sqlite3
import sys

def insertColumn(dive, cur, col, val, type):
    try:
        cur.execute(f"ALTER TABLE dives ADD COLUMN {col} {type};")
    except:
        pass

    if type == 'TEXT':
        cur.execute(f"UPDATE dives SET {col} = '{val}' WHERE dive={dive};")
    else:
        cur.execute(f"UPDATE dives SET {col} = {val} WHERE dive={dive};")

def loadFileToDB(cur, filename):
    nci = Utils.open_netcdf_file(filename)
    dive = nci.variables['log_DIVE'].getValue()
    cur.execute(f"DELETE FROM dives WHERE dive={dive};")
    cur.execute(f"INSERT INTO dives(dive) VALUES({dive});")
    for v in list(nci.variables.keys()):
        if not nci.variables[v].dimensions:
            if not v.startswith('sg_cal'):
                insertColumn(dive, cur, v, nci.variables[v].getValue(), 'FLOAT')

    dep_mx = numpy.nanmax(nci.variables['depth'][:])
    insertColumn(dive, cur, "max_depth", dep_mx, 'FLOAT')

    i = numpy.where(nci.variables['eng_elaps_t'][:] < nci.variables['start_of_climb_time'].getValue())
    pi_div = numpy.nanmean(nci.variables['eng_pitchAng'][i])
    ro_div = numpy.nanmean(nci.variables['eng_rollAng'][i])

    i = numpy.where(nci.variables['eng_elaps_t'][:] > nci.variables['start_of_climb_time'].getValue())
    pi_clm = numpy.nanmean(nci.variables['eng_pitchAng'][i])
    ro_clm = numpy.nanmean(nci.variables['eng_rollAng'][i])
    insertColumn(dive, cur, "pitch_dive", pi_div, 'FLOAT')
    insertColumn(dive, cur, "pitch_climb", pi_clm, 'FLOAT')

    [pitchErrors, rollErrors, vbdErrors, pitchRetries, rollRetries, vbdRetries,
     GPS_line_timeouts, compass_timeouts, pressure_timeouts,
     sensor_timeouts0, sensor_timeouts1,
     sensor_timeouts2, sensor_timeouts3,
     sensor_timeouts4, sensor_timeouts5,
     logger_timeouts0, logger_timeouts1,
    # logger_timeouts2, logger_timeouts3] = nci.variables['log_ERRORS'][:].tobytes().decode('utf-8').split(',')
     logger_timeouts2] = nci.variables['log_ERRORS'][:].tobytes().decode('utf-8').split(',')

    [v10,ah10] = list(map(float, nci.variables['log_10V_AH'][:].tobytes().decode('utf-8').split(',')))
    [v24,ah24] = list(map(float, nci.variables['log_24V_AH'][:].tobytes().decode('utf-8').split(',')))
    if nci.variables['log_AH0_24V'].getValue() > 0:
        avail24 = 1 - ah24/nci.variables['log_AH0_24V'].getValue()
    else:
        avail24 = 0

    if nci.variables['log_AH0_10V'].getValue() > 0:
        avail10 = 1 - ah10/nci.variables['log_AH0_10V'].getValue()
    else:
        avail10 = 0

    insertColumn(dive, cur, "volts_10V", v10, 'FLOAT')
    insertColumn(dive, cur, "volts_24V", v24, 'FLOAT')
    insertColumn(dive, cur, "capacity_24V", avail24, 'FLOAT')
    insertColumn(dive, cur, "capacity_10V", avail10, 'FLOAT')

    [mhead,rng,pitchd,wd,theta,dbdw,pressureNoise] = list(map(float, nci.variables['log_MHEAD_RNG_PITCHd_Wd'][:].tobytes().decode('utf-8').split(',')))
 
    insertColumn(dive, cur, "mag_heading_to_target", mhead, 'FLOAT') 
    insertColumn(dive, cur, "meters_to_target", rng, 'FLOAT') 
    [tgt_la, tgt_lo] = list(map(float, nci.variables['log_TGT_LATLONG'][:].tobytes().decode('utf-8').split(',')))

    insertColumn(dive, cur, "target_lat", tgt_la, 'FLOAT') 
    insertColumn(dive, cur, "target_lon", tgt_lo, 'FLOAT') 

    nm = nci.variables['log_TGT_NAME'][:].tobytes().decode('utf-8')
    insertColumn(dive, cur, "target_name", nm, 'TEXT')

def rebuildDB(path):

    glider = os.path.basename(path)
    sg = int(glider[2:])
    db = path + '/' + glider + '.db'
    print("rebuilding %s" % db)
    con = sqlite3.connect(db)
    with con:
        cur = con.cursor()
        cur.execute("DROP TABLE IF EXISTS dives;")
        cur.execute("CREATE TABLE dives(dive INT);")
        patt = path + '/p%03d????.nc' % sg
        for filename in glob.glob(patt):
            loadFileToDB(cur, filename)

        cur.close()

def loadDB(filename):
    sg = int(filename[1:4])
    db = '/home/seaglider/sg' + sg + '/sg' + sg + '.db'
    print("loading %s to %s" % (filename, db))
    con = sqlite3.connect(db)
    with con:
        cur = con.cursor()
        loadFileToDB(cur, filename)

        cur.close()

if __name__ == '__main__':
    if len(sys.argv) != 2:
        sys.exit() 

    if os.path.isdir(sys.argv[1]):
        rebuildDB(sys.argv[1])
    else:    
        loadDB(sys.argv[1])
