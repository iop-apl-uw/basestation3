import sys
from passlib.hash import sha256_crypt

password = sha256_crypt.hash(sys.argv[1])

print(password)
