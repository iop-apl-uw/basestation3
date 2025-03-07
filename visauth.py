## Copyright (c) 2025  University of Washington.
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

import getpass
import io
import os.path
import random
import smtplib
import sqlite3
import sys
import time
from contextlib import closing
from email.mime.nonmultipart import MIMENonMultipart
from email.utils import formatdate

import pyqrcode
from passlib.hash import sha256_crypt
from passlib.totp import TOTP

# CREATE TABLE users (name PRIMARY KEY, email, domain, password, type, totp, totp_verify_by int, otc, otc_expiry int, last int, last_t int, fails int, locked int);

FAILED_LOGIN_LIMIT = 10
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

    # email_send_from = fromAddr
    # email_send_to = [toAddr]

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

    query(db, "UPDATE users SET fails=?,locked=?,last_t=? WHERE name=?", (fails, locked, time.time(), username))

def addUser(db, username, email, domain, authType, password):
    if password is None:
        pw1 = getpass.getpass()
        print("confirm")
        pw2 = getpass.getpass()
        if pw1 == pw2:
            password = pw1
        else:
            print("passwords do not match")
            return

    query(db, "INSERT INTO users(name,email,domain,type,password,fails,locked) VALUES(?,?,?,?,?,?,?)", 
          (username, email, domain, authType, sha256_crypt.hash(password), 0, 0))

def unlockUser(db, username):
    query(db, "UPDATE users SET fails=?,locked=? WHERE name=?", (0,0,username))
 
def generateOneTimeCode(db, username, email):
    otc = ''.join([str(random.randint(0,9)) for i in range(6)])
    otc_hash = sha256_crypt.hash(otc)
    otc_expires = time.time() + OTC_EXPIRE_TIME

    s = query(db, "UPDATE users SET otc=?,otc_expiry=? WHERE name=?",
              (otc_hash, otc_expires, username))

    if s:
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
    except Exception:
        return { 'status': 'error', 'msg': 'invalid' }

    try:
        buffer = io.BytesIO()
        pyqrcode.create(totp.to_uri(label=f'{username}')).svg(buffer, scale=6, background="white", xmldecl=False, svgns=False, omithw=True)
    except Exception:
        return { 'status': 'error', 'msg': 'QR error' }
        
    query(db, "UPDATE users SET totp=?,last=?,last_t=?,fails=?,locked=?,otc=?,otc_expiry=?,totp_verify_by=? WHERE name=?",
          (keydata, 0, 0, 0, 0, '', 0, time.time() + TOTP_VERIFY_TIME,  username))

    return { 'status': 'pending', 'qr': buffer.getvalue().decode('utf-8'), 'key': totp.pretty_key() }

def setupUser(db, username, domain, password_input, code, new_password):
    r = query(db, f"SELECT type,domain,password,totp,totp_verify_by,otc,otc_expiry,last,last_t,fails,locked from users WHERE name='{username}'", ())
    if not r:
        return {'msg': 'error', 'status': 'error'}

    if not r['otc'] or r['otc'] == '': 
        return {'msg': 'one-time-code error', 'status': 'error'}

    if r['otc_expiry'] < time.time():
        return {'msg': 'one-time-code expired', 'status': 'error'}
        
    if r['locked']:
        return {'msg': 'account locked', 'status': 'error'}

    if r['type'] == 'view':
        return {'msg': 'invalid', 'status': 'error'}

    if domain and r['domain'] != domain:
        return {'msg': 'unauthorized', 'status': 'error'}

    try:
        passok = sha256_crypt.verify(password_input, r['password'])
    except Exception:
        passok = False

    try: 
        otcok = sha256_crypt.verify(code, r['otc'])
    except Exception:
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
                 'Your piloting password has been changed. If you did not\n'
               + 'request this change contact your administrator immediately.\n')

def authorizeUser(db, username, domain, password_input, code_input, new_password=None):
    r = query(db, f"SELECT type,email,domain,password,totp,totp_verify_by,otc,otc_expiry,last,last_t,fails,locked from users WHERE name='{username}'", ())
    if not r:
        return {'status': 'error', 'msg': 'error'}

    if r['locked']:
        return {'msg': 'account locked', 'status': 'error'}

    if r['domain'] != domain:
        return {'msg': 'unauthorized', 'status': 'error'}

    try:
        passok = sha256_crypt.verify(password_input, r['password'])
    except Exception:
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

    # totp not setup yet or previous setup never confirmed
    if not r['totp'] or r['totp'] == '' or (r['totp_verify_by'] and r['totp_verify_by'] < time.time()): 

        if (not r['otc'] or r['otc'] == '') or r['otc_expiry'] < time.time(): # otc never sent or expired
            return generateOneTimeCode(db, username, r['email'])
        elif r['otc'] != '' and r['otc_expiry'] > time.time():
            return { 'status': 'pending', 'msg': 'one-time-code already sent' }

    else:
        try:
            libname = os.path.join(os.path.dirname(db), 'authlib.txt')
            fact = TOTP.using(secrets_path=libname, issuer="seaglider")
            token = fact.from_source(r['totp'])
        except Exception as e:
            return { 'status': 'error', 'msg': f'OTP invalid {e}' }

        try:
            match = fact.verify(code_input, token, last_counter=r['last'])
        except Exception:
            match = False

        if match:
            last_t = time.time() # match.time + match.cache_seconds
            query(db, "UPDATE users SET last=?,last_t=?,fails=0,totp_verify_by=0 WHERE name=?", (match.counter, last_t, username))
            if new_password:
                changeUserPassword(db, username, r['email'], new_password)
                return { 'status': 'changed', 'msg': 'password updated', 'fails': r['fails'], 'previous': r['last_t'] }
            else:
                return { 'status': 'authorized', 'msg': 'authorized', 'fails': r['fails'], 'previous': r['last_t'] }
        else:
            updateFails(db, r['fails'], r['locked'], username)
            return { 'status': 'error', 'msg': 'unauthorized' }

    return { 'status': 'error', 'msg': 'error' } # never gets here

if __name__ == "__main__":

    # from passlib.totp import generate_secret
    # generate_secret()
    # '....' -> file(authlib.txt) -> date: secret

    # add username email domain type(view|pilot) initialPassword
    if sys.argv[1] == 'add' and len(sys.argv) >= 6:
        addUser('./auth.db', sys.argv[2], sys.argv[3], sys.argv[4], sys.argv[5], sys.argv[6] if len(sys.argv) == 7 else None)

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
