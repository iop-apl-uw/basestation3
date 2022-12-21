import time
import os.path
from parse import parse
import sqlite3
from datetime import datetime
import math

def haversine(lat0, lon0, lat1, lon1):
    R = 6378137.0
    lat0 = lat0*math.pi/180
    lat1 = lat1*math.pi/180
    lon0 = lon0*math.pi/180
    lon1 = lon1*math.pi/180

    sdlat_2 = math.sin(0.5*(lat0 - lat1))
    sdlon_2 = math.sin(0.5*(lon0 - lon1))

    a = sdlat_2*sdlat_2 + math.cos(lat0)*math.cos(lat1)*sdlon_2*sdlon_2
    if a >= 1 or a <= 0:
        return 0

    return 2.0*R*math.asin(math.sqrt(a))

def collectSummary(glider, path):
    possibleDirectives = ["GO", "QUIT", "RESUME", "EXIT_TO_MENU"]

    commlog = f'{path}/comm.log'
    dbfile  = f'{path}/sg{glider:03d}.db'
    cmdfile = f'{path}/cmdfile'
     
    with open(commlog, 'rb') as file:
        file.seek(-10000, 2)
        last_GPS = ''
        directive  = ''
        connected = ''
        for line in file:
            line = line.decode('utf-8', errors='ignore').strip()
            if 'GPS' in line:
                last_GPS = line[line.find('GPS'):]
            elif 'Parsed' in line:
                directive = line.split(' ')[1]
            elif 'Connected at' in line:
                connected = ' '.join(line.split(' ')[3:])
 
        file.close()

    connect_t = datetime.strptime(connected, '%b %d %H:%M:%S %Z %Y').timestamp()
    mtime = os.path.getmtime(commlog) 

    last_GPS = ','.join(last_GPS.split(',')[0:5])
    p = parse("GPS,{:2d}{:2d}{:2d},{:2d}{:2d}{:2d},{:f},{:f}", last_GPS)
    (day,mon,year,hour,min,sec,lat,lon) = p.fixed

    lat_deg = int(lat / 100)
    lon_deg = int(lon / 100)
    lat_min = lat - lat_deg*100
    lon_min = lon - lon_deg*100

    pos_stamp = datetime.strptime(f"{year+2000}-{mon:02d}-{day:02d}T{hour:02d}:{min:02d}:{sec:02d}Z", "%Y-%m-%dT%H:%M:%S%z").timestamp()

    with sqlite3.connect(dbfile) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("SELECT dive,log_glider,batt_volts_10V,batt_volts_24V,batt_capacity_10V,batt_capacity_24V,total_flight_time_s,log_gps_time,error_count,max_depth,log_D_GRID,GPS_north_displacement_m,GPS_east_displacement_m,meters_to_target,log_speed_max,log_D_TGT,log_T_DIVE,log_TGT_LAT,log_TGT_LON,log_gps2_lat,log_gps2_lon,log_gps_lat,log_gps_lon FROM dives ORDER BY dive DESC LIMIT 1")
        data = dict(cur.fetchall()[0])

        cur.execute(f"SELECT pitch_volts,roll_volts,vbd_volts,vbd_eff FROM gc WHERE dive={data['dive']} ORDER BY vbd_eff DESC LIMIT 1")
        gc = dict(cur.fetchall()[0])

    conn.close()

    cmdfileDirective = 'unknown'

    if cmdfile is not None:
        with open(cmdfile, 'rb') as file:
            for line in file:
                line = line.decode('utf-8', errors='ignore').strip()[1:].split(
',')[0]
                if line in possibleDirectives:
                    cmdfileDirective = line
        

        file.close()


    try: 
        dog = math.sqrt(math.pow(data['GPS_north_displacement_m'], 2) +
                        math.pow(data['GPS_east_displacement_m'], 2))

        bestDOG = data['max_depth']/data['log_D_TGT']*(data['log_T_DIVE']*60)*data['log_speed_max']
        dtg1 = haversine(data['log_gps2_lat'], data['log_gps2_lon'], data['log_TGT_LAT'], data['log_TGT_LON']) 
        dtg2 = haversine(data['log_gps_lat'], data['log_gps_lon'], data['log_TGT_LAT'], data['log_TGT_LON']) 

        dmg = dtg1 - dtg2
        dogEff = dmg/bestDOG
    except:
        dmg = 0
        dog = 0
        dogEff = 0
        dtg2 = 0

    dv = data['dive']
    capfile = f"{path}/p{glider:03d}{dv:04d}.cap"
    critcount = 0
    if os.path.exists(capfile):
        cap = 1;
        with open(capfile, 'r') as file:
            for line in file:
                if ',C,' in line:
                    critcount = critcount + 1;
    else:
        cap = 0;

    alertfile = f"{path}/alert_message.html.{dv}"
    if os.path.exists(alertfile):
        alert = 1
    else:
        alert = 0

    out = {}
    out['name'] = int(data['log_glider'])
    out['dive'] = dv
    out['end']  = data['log_gps_time']
    out['next'] = data['log_gps_time'] + data['total_flight_time_s']

    out['dmg'] = dmg
    out['dog'] = dog
    out['dtg'] = dtg2
    out['dogEfficiency'] = dogEff

    out['vbdEfficiency'] = gc['vbd_eff']
    out['vbdVolts'] = gc['vbd_volts']

    out['mtime']    = mtime
    out['connect']  = connect_t
    out['depth']    = data['max_depth']
    out['grid']     = data['log_D_GRID']
    out['fix']      = pos_stamp
    out['lat']      = lat_deg + lat_min/60
    out['lon']      = lon_deg + lon_min/60
    out['volts']    = [ data['batt_volts_10V'], data['batt_volts_24V'] ] 
    out['capacity'] = [ data['batt_capacity_10V'], data['batt_capacity_24V'] ]
    out['errors']   = data['error_count']
    out['commDirective'] = directive
    out['cmdfileDirective'] = cmdfileDirective

    out['cap']   = cap
    out['alert'] = alert
    out['crits']  = critcount

    return out

if __name__ == "__main__":
    msg = collectSummary('/home/seaglider/sg249/sg249.db', '/home/seaglider/sg249/comm.log', '/home/seaglider/sg249/cmdfile')
    print(msg)
