import aiosqlite
import asyncio
import sys
from anyio import Path

def rowToDict(cursor: aiosqlite.Cursor, row: aiosqlite.Row) -> dict:
    data = {}
    for idx, col in enumerate(cursor.description):
        data[col[0]] = row[idx]

    return data

async def pilotRecs(path:str, glider:int):
    dbfile = f'{path}/sg{glider:03d}.db'
    if not await Path(dbfile).exists():
        return (None, None, None)


    row = None
    async with aiosqlite.connect('file:' + dbfile + '?immutable=1', uri=True) as conn:
        conn.row_factory = rowToDict 
        cur = await conn.cursor()
        try:
            await cur.execute("SELECT dive,pitch_flying_rmse,pitch_linear_C_PITCH,pitch_linear_PITCH_GAIN,pitch_linear_rmse,pitch_fixed_C_PITCH,pitch_fixed_PITCH_GAIN,pitch_fixed_rmse,pitch_shift_C_PITCH,pitch_shift_PITCH_GAIN,pitch_shift_PITCH_VBD_SHIFT,pitch_shift_rmse,roll_C_ROLL_DIVE,roll_C_ROLL_CLIMB,turn_centered_C_ROLL_DIVE,turn_centered_C_ROLL_CLIMB,turn_all_C_ROLL_DIVE,turn_all_C_ROLL_CLIMB,vert_vel_flying_rmse,vert_vel_buoyancy_rmse,vert_vel_buoyancy_C_VBD,vert_vel_hd_C_VBD,vert_vel_hd_rmse,vert_vel_regress_rmse,vert_vel_regress_C_VBD,log_C_PITCH,log_C_VBD,log_C_ROLL_DIVE,log_C_ROLL_CLIMB,log_PITCH_GAIN,log_PITCH_VBD_SHIFT FROM dives ORDER BY dive DESC LIMIT 1")
            row = await cur.fetchone()
        except aiosqlite.OperationalError as e:
            return (None, None, None)

    pitch = { 
                'current': { 'rmse': row['pitch_flying_rmse'], 'C_PITCH': row['log_C_PITCH'], 'PITCH_GAIN': row['log_PITCH_GAIN'], 'PITCH_VBD_SHIFT': row['log_PITCH_VBD_SHIFT'] },
                'linear':  { 'rmse': row['pitch_linear_rmse'], 'C_PITCH': row['pitch_linear_C_PITCH'], 'PITCH_GAIN': row['pitch_linear_PITCH_GAIN'] },
                'fixed':   { 'rmse': row['pitch_fixed_rmse'], 'C_PITCH': row['pitch_fixed_C_PITCH'], 'PITCH_GAIN': row['pitch_fixed_PITCH_GAIN'] },
                'shift':   { 'rmse': row['pitch_shift_rmse'], 'C_PITCH': row['pitch_shift_C_PITCH'], 'PITCH_GAIN': row['pitch_shift_PITCH_GAIN'], 'PITCH_VBD_SHIFT': row['pitch_shift_PITCH_VBD_SHIFT'] },
            }
    if row['pitch_fixed_rmse'] < row['pitch_flying_rmse']:
        p = { 
                'C_PITCH':    row['log_C_PITCH'] + 0.5*(row['pitch_fixed_C_PITCH'] - row['log_C_PITCH']),
                'PITCH_GAIN': row['log_PITCH_GAIN'] + 0.5*(row['pitch_fixed_PITCH_GAIN'] - row['log_PITCH_GAIN']),
                'rmse':       row['pitch_fixed_rmse'],
                'model':      'fixed shift',
            }
    elif row['pitch_linear_rmse'] < row['pitch_flying_rmse']:
        p = { 
                'C_PITCH':    row['log_C_PITCH'] + 0.5*(row['pitch_linear_C_PITCH'] - row['log_C_PITCH']),
                'PITCH_GAIN': row['log_PITCH_GAIN'] + 0.5*(row['pitch_linear_PITCH_GAIN'] - row['log_PITCH_GAIN']),
                'rmse':       row['pitch_linear_rmse'],
                'model':      'linear',
            }
    else:
        p = None

    pitch.update( { 'rec': p } )

    vbd =   { 
                'current':  { 'rmse': row['vert_vel_flying_rmse'],   'C_VBD': row['log_C_VBD'] },
                'buoyancy': { 'rmse': row['vert_vel_buoyancy_rmse'], 'C_VBD': row['vert_vel_buoyancy_C_VBD'] },
                'hd':       { 'rmse': row['vert_vel_hd_rmse'],       'C_VBD': row['vert_vel_hd_C_VBD'] },
                'regress':  { 'rmse': row['vert_vel_regress_rmse'],  'C_VBD': row['vert_vel_regress_C_VBD'] },
            }
    if row['vert_vel_hd_rmse'] < row['vert_vel_flying_rmse']:
        v = { 
                'C_VBD': row['log_C_VBD'] + 0.5*(row['vert_vel_hd_C_VBD'] - row['log_C_VBD']),
                'rmse':  row['vert_vel_hd_rmse'],
                'model': 'buoyancy + HD',
            }
    elif row['vert_vel_buoyancy_rmse'] < row['vert_vel_flying_rmse']:
        v = { 
                'C_VBD': row['log_C_VBD'] + 0.5*(row['vert_vel_buoyancy_C_VBD'] - row['log_C_VBD']),
                'rmse':  row['vert_vel_buoyancy_rmse'],
                'model': 'buoyancy',
            }
    else:
        v = None

    vbd.update( { 'rec': v } )

    roll =  {
                'current':  { 'C_ROLL_DIVE': row['log_C_ROLL_DIVE'],           'C_ROLL_CLIMB': row['log_C_ROLL_CLIMB'], },
                'roll':     { 'C_ROLL_DIVE': row['roll_C_ROLL_DIVE'],          'C_ROLL_CLIMB': row['roll_C_ROLL_CLIMB'], },
                'centered': { 'C_ROLL_DIVE': row['turn_centered_C_ROLL_DIVE'], 'C_ROLL_CLIMB': row['turn_centered_C_ROLL_CLIMB'], },
                'all':      { 'C_ROLL_DIVE': row['turn_all_C_ROLL_DIVE'],      'C_ROLL_CLIMB': row['turn_all_C_ROLL_CLIMB'], },
            }
 

    d1 = row['roll_C_ROLL_DIVE'] - row['log_C_ROLL_DIVE']
    d2 = row['turn_centered_C_ROLL_DIVE'] - row['log_C_ROLL_DIVE']

    if d1*d2 > 0:
        if abs(d1) < abs(d2):
            d = {
                    'C_ROLL_DIVE': row['log_C_ROLL_DIVE'] + 0.5*d1,
                    'model': 'roll',
                }
        else:
            d = {
                    'C_ROLL_DIVE': row['log_C_ROLL_DIVE'] + 0.5*d2,
                    'model': 'centered turning',
                }
 
    else:
        d = None

    c1 = row['roll_C_ROLL_CLIMB'] - row['log_C_ROLL_CLIMB']
    c2 = row['turn_centered_C_ROLL_CLIMB'] - row['log_C_ROLL_CLIMB']
    if c1*c2 > 0:
        if abs(c1) < abs(c2):
            c = {
                    'C_ROLL_CLIMB': row['log_C_ROLL_CLIMB'] + 0.5*c1,
                    'model': 'roll',
                }
        else:
            c = {
                    'C_ROLL_CLIMB': row['log_C_ROLL_CLIMB'] + 0.5*c2,
                    'model': 'centered turning',
                }
 
    else:
        c = None

    roll.update( { 'dive': d, 'climb': c } )
    
    return (pitch, roll, vbd)
 
if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(1)
 
    path = sys.argv[1]
    glider = int(sys.argv[2])
    (pitch, roll, vbd) = asyncio.run(pilotRecs(path, glider))

    # pitch
    print(f"pitch RMSE as flying: {pitch['current']['rmse']:.2f}")
    if pitch and 'rec' in pitch and pitch['rec']:
        print(f"Based on {pitch['rec']['model']} model (RMSE={pitch['rec']['rmse']:.2f}) and the 50% rule, suggest:")
        print(f"   $C_PITCH,{pitch['rec']['C_PITCH']:.1f} (currently {pitch['current']['C_PITCH']:.1f})")
        print(f"   $PITCH_GAIN,{pitch['rec']['PITCH_GAIN']:.1f} (currently {pitch['current']['PITCH_GAIN']:.1f})")

    # VBD
    print(f"VBD RMSE as flying: {vbd['current']['rmse']:.2f}")
    if vbd and 'rec' in vbd and vbd['rec']:
        print(f"Based on {vbd['rec']['model']} model (RMSE={vbd['rec']['rmse']:.2f}) and the 50% rule, suggest:")
        print(f"   $C_VBD,{vbd['rec']['C_VBD']:.1f} (currently {vbd['current']['C_VBD']:.1f})")

    # ROLL
    if roll and 'dive' in roll and roll['dive']:
        print(f"Based on {roll['dive']['model']}, suggest:")
        print(f"   $C_ROLL_DIVE,{roll['dive']['C_ROLL_DIVE']:.1f} (currently {roll['current']['C_ROLL_DIVE']:.1f})")

    if roll and 'climb' in roll and roll['climb']:
        print(f"Based on {roll['climb']['model']}, suggest:")
        print(f"   $C_ROLL_CLIMB,{roll['climb']['C_ROLL_CLIMB']:.1f} (currently {roll['current']['C_ROLL_CLIMB']:.1f})")
