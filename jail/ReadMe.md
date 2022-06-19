# Glider Jail notes

## Current script

Current jail a mix from:
    https://askubuntu.com/questions/547737/jailing-particular-users-on-login
and 
    http://www.kegel.com/crosstool/current/doc/chroot-login-howto.html
	
The script is intended to help boot strap and update as the system binaries are updated.

## To sort out

### The latter has the following:

    cd dev
    mknod null   c 1 3
    mknod zero   c 1 5
    mknod random c 1 8
    chmod 666 *
	mount -t proc proc  $JAIL/proc
Needed?

### Termcap
To shut up output from tcsh, this tree is copied

    /lib/terminfo

just to provide the definition for the "dumb" terminal - needed?

### passwd, shadow, group, gshadow

None of these files are being created automatically - probably no need to, but they will need documentation on how to setup.

## ToDo

- Need to create an updated commmision.py to setup glider directories in the jail

## Setup notes



