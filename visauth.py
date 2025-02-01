# CREATE TABLE users (name PRIMARY KEY, email, domain, password, type, totp, totp_verify_by int, otc, otc_expiry int, last int, last_t int, fails int, locked int);
import sys
import sqlite3
import pyqrcode 
import io
import time
import random
from passlib.totp import TOTP
from passlib.hash import sha256_crypt
from contextlib import closing
import smtplib
import os.path
from email.mime.nonmultipart import MIMENonMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
import getpass

FAILED_LOGIN_LIMIT = 5
OTC_EXPIRE_TIME    = 300
TOTP_VERIFY_TIME   = 300

def sendMail(fromAddr, toAddr, subj, body):
    email_msg = MIMENonMultipart("text", "plain")

    email_msg["From"]     = fromAddr
    email_msg["To"]       = toAddr
    email_msg["Date"]     = formatdate(localtime=True)
    email_msg["Subject"]  = subj
    email_msg["Reply-To"] = fromAddr

    email_msg.set_payload(body)

    email_send_from = fromAddr
    email_send_to = [toAddr]

    try:
        smtp = smtplib.SMTP("localhost")
        smtp.sendmail(fromAddr, [toAddr], email_msg.as_string())
        smtp.close()
    except Exception:
        print("Unable to send message")
        return False

    return True


def query(db, q, args):
    with closing(sqlite3.connect(db)) as con, con, closing(con.cursor()) as cur:
        try:
            cur.execute(q, args)
            row = cur.fetchone()
            data = {}
            if row and len(row) > 0:
                for idx, col in enumerate(cur.description):
                    data[col[0]] = row[idx]
            return data
        except Exception as e:
            print(e)
            return False

def updateFails(db, fails, locked, username):
    fails = fails + 1
    if fails >= FAILED_LOGIN_LIMIT:
        locked = 1

    query(db, "UPDATE users SET fails=?,locked=? WHERE name=?", (fails, locked, username))

def addUser(db, username, email, domain, authType, password):
    query(db, f"INSERT INTO users(name,email,domain,type,password,fails,locked) VALUES(?,?,?,?,?,?,?)", 
          (username, email, domain, authType, sha256_crypt.hash(password), 0, 0))

def unlockUser(db, username):
    query(db, f"UPDATE users SET fails=?,locked=? WHERE name=?", (0,0,username))
 
def generateOneTimeCode(db, username, email):
    otc = ''.join([str(random.randint(0,9)) for i in range(6)])
    otc_hash = sha256_crypt.hash(otc)
    otc_expires = time.time() + OTC_EXPIRE_TIME

    s = query(db, f"UPDATE users SET otc=?,otc_expiry=? WHERE name=?",
              (otc_hash, otc_expires, username))

    if s != False:
        sendMail('no-reply', email, 'setup your pilot account',
                 f'Your one-time-code is {otc}. It expires in 5 minutes.\n\n'
                 + 'Do not share this code. Use this code along with your\n'
                 + 'current password to change your password (required) and\n'
                 + 'configure multiactor authentication (required).')
        return { 'msg': 'check your email for your one-time-code', 'status': 'pending' }
    else:
        return { 'msg': "invalid", 'status': 'error' }

    return { 'msg': "unknown", 'status': 'error' }

def setupTOTP(db, username):

    try:
        libname = os.path.join(os.path.dirname(db), 'authlib.txt')
        fact = TOTP.using(secrets_path=libname, issuer="seaglider")
        totp = fact.new()
        keydata = totp.to_json()
    except:
        return { 'status': 'error', 'msg': 'invalid' }

    try:
        buffer = io.BytesIO()
        pyqrcode.create(totp.to_uri(label=f'{username}')).svg(buffer, scale=6, background="white", xmldecl=False, svgns=False, omithw=True)
    except:
        return { 'status': 'error', 'msg': 'QR error' }
        
    query(db, f"UPDATE users SET totp=?,last=?,last_t=?,fails=?,locked=?,otc=?,otc_expiry=?,totp_verify_by=? WHERE name=?",
          (keydata, 0, 0, 0, 0, '', 0, time.time() + TOTP_VERIFY_TIME,  username))

    return { 'status': 'pending', 'qr': buffer.getvalue().decode('utf-8'), 'key': totp.pretty_key() }

def setupUser(db, username, domain, password_input, code, new_password):
    r = query(db, f"SELECT type,domain,password,totp,totp_verify_by,otc,otc_expiry,last,last_t,fails,locked from users WHERE name='{username}'", ())
    if r == False:
        return {'status': 'error'}

    if not r['otc'] or r['otc'] == '': 
        return {'msg': 'OTC error', 'status': 'error'}

    if r['otc_expiry'] < time.time():
        return {'msg': 'one-time-code expired', 'status': 'error'}
        
    if r['locked']:
        return {'msg': 'locked', 'status': 'error'}

    if r['type'] == 'view':
        return {'msg': 'invalid', 'status': 'error'}

    if domain and r['domain'] != domain:
        return {'msg': 'unauthorized', 'status': 'error'}

    try:
        passok = sha256_crypt.verify(password_input, r['password'])
    except:
        passok = False

    try: 
        otcok = sha256_crypt.verify(code, r['otc'])
    except:
        otcok = False

    if not passok or not otcok:
        updateFails(db, r['fails'], r['locked'], username)
        return {'msg': 'unauthorized', 'status': 'error'}

    query(db, "UPDATE users SET password=? WHERE name=?", (sha256_crypt.hash(new_password), username))

    return setupTOTP(db, username)

def changeUserPassword(db, username, email, new_password):
    query(db, "UPDATE users SET password=? WHERE name=?", (sha256_crypt.hash(new_password), username))
    if email:
        sendMail('no-reply', email, 'your password has been changed',
                 f'Your piloting password has been changed. If you did not\n'
                + 'request this change contact your administrator immediately.\n')

def authorizeUser(db, username, domain, password_input, code_input, new_password=None):
    r = query(db, f"SELECT type,email,domain,password,totp,totp_verify_by,otc,otc_expiry,last,last_t,fails,locked from users WHERE name='{username}'", ())
    if r == False:
        return {'status': 'error'}

    if r['locked']:
        return {'msg': 'locked', 'status': 'error'}

    if r['domain'] != domain:
        return {'msg': 'unauthorized', 'status': 'error'}

    try:
        passok = sha256_crypt.verify(password_input, r['password'])
    except:
        passok = False

    if r['type'] == 'view':
        # no failure lockouts / rate limiting for view only accounts
        if passok:
            return { 'status': 'authorized', 'msg': 'authorized' }
        else:
            return { 'status': 'error', 'msg': 'unauthorized' }

    if not passok:
        updateFails(db, r['fails'], r['locked'], username)
        return {'msg': 'unauthorized', 'status': 'error'}

    if r['last_t'] is None or time.time() > r['last_t']:
        last = 0 # prev counter expired, we're immune to a fast replay

    
    # totp not setup yet or previous setup never confirmed
    if not r['totp'] or r['totp'] == '' or (r['totp_verify_by'] and r['totp_verify_by'] < time.time()): 

        if (not r['otc'] or r['otc'] == '') or r['otc_expiry'] < time.time(): # otc never sent or expired
            return generateOneTimeCode(db, username, r['email'])
        elif r['otc'] != '' and r['otc_expiry'] > time.time():
            return { 'status': 'pending', 'msg': 'one-time-code already sent' }

    else:
        if r['last_t'] is None or time.time() > r['last_t']:
            last = 0 # prev counter expired, we're immune to a fast replay

        try:
            libname = os.path.join(os.path.dirname(db), 'authlib.txt')
            fact = TOTP.using(secrets_path=libname, issuer="seaglider")
            token = fact.from_source(r['totp'])
        except:
            return { 'status': 'error', 'msg': 'invalid' }

        try:
            match = fact.verify(code_input, token, last_counter=r['last'])
        except Exception as e:
            match = False

        if match:
            last_t = match.time + match.cache_seconds
            query(db, "UPDATE users SET last=?,last_t=?,fails=0,totp_verify_by=0 WHERE name=?", (match.counter, last_t, username))
            if new_password:
                changeUserPassword(db, username, r['email'], new_password)
                return { 'status': 'changed', 'msg': 'password updated' }
            else:
                return { 'status': 'authorized', 'msg': 'authorized' }
        else:
            updateFails(db, r['fails'], r['locked'], username)
            return { 'status': 'error', 'msg': 'unauthorized' }

    return { 'status': 'error', 'msg': 'error' } # never gets here

if __name__ == "__main__":

    # from passlib.totp import generate_secret
    # generate_secret()
    # '....' -> file(authlib.txt) -> date: secret

    # add username email domain type(view|pilot) initialPassword
    if sys.argv[1] == 'add' and len(sys.argv) == 7:
        addUser('./auth.db', sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6])

    # auth username
    elif sys.argv[1] == "auth" and len(sys.argv) == 4:
        status = authorizeUser('./auth.db', sys.argv[2], sys.argv[3])
        print(status['msg'], status['status'])

    elif sys.argv[1] == "unlock" and len(sys.argv) == 3:
        unlockUser('./auth.db', sys.argv[2])

    elif sys.argv[1] == "password" and len(sys.argv) == 3:
        pw1 = getpass.getpass()
        print("confirm")
        pw2 = getpass.getpass()
        if pw1 == pw2:
            changeUserPassword('./auth.db', sys.argv[2], None, pw1)
    else:
        print("unrecognized command")
        print(" auth.py add username email domain type(view|pilot) initialPassword")
        print(" auth.py unlock username")
        print(" auth.py auth username domain")
