# Glider Jail notes

# Overview

To increase the security of a basestation, it can be useful to run the
Seaglider accounts in a chroot jail.  When this setup is used, the Seaglider
account is limited to a very narrow set of functionality - just enough to
transfer files and write to the comm.log.  The heavy lifting for running
conversion processes is handled by a different user account - the "runner" -
that has a full basestation installation.

# Setup

## chrootshell
The binary that handles the chroot work is maintained in a separate repository.

[iop-apl-uw/chrootshell](https://github.com/iop-apl-uw/chrootshell)

After building and installing chrootshell, select a directory that is the root
of the jail - the directions below assume this is ```/home/jail```.  They also
assume you have the gliders in a ```gliders``` group and you have setup python
as described the main [Readme.md](../Readme.md).

# Create jail directory structure
```
sudo mkdir -p /home/jail/home/rundir
```

## Create the runner account
```
sudo adduser --disabled-login --disabled-password --shell /usr/sbin/nologin --no-create-home --ingroup gliders runner-glider
```

## Update ownership and permissions
```
sudo chown -R runner-glider:gliders /home/jail
sudo chmod o-rwx /home/jail
sudo chmod g+rwx /home/jail/home/rundir
```

## Create glider jail infrastructure

```
sudo /opt/basestation/bin/python /usr/local/basestation3/jail/create_jail.py --create /home/jail
```
Update permissions

```
sudo chown runner-glider:gliders /home/jail/usr/local/basestation/glider_log*
sudo chmod ug+rw /home/jail/usr/local/basestation/glider_log*
```

Update the ```/home/jail/usr/local/basestation/glider_login``` and
```/home/jail/usr/local/basestation/glider_logout``` files to include this line
at the top of the file:

```
set RUNNER_DIR=/home/rundir
```
## Commission gliders

### Glider not yet commissioned

If you have not commissioned your gliders yet, then run the
```Commission.py``` script.  It is suggested that you select a more secure
password then the default on generated.

```
sudo /opt/basestation/bin/python /usr/local/basestation3/Commission.py
--glider_password <glider_pwd> --jail /home/jail --glider_group gliders
--home_dir_group gliders <gliderid>
```

Note: you need to manually update ```/etc/passwd``` per the output instructions
from Commission.py

### Glider already commissioned

If you have already commissioned your glider, then do the following:

```
sudo mv ~sg<gliderid> /home/jails/home/sg<gliderid>
sudo chmod -R g+rw /home/jail/home/sg<gliderid>
```

Now you must update the main ```/etc/password``` file and the jail
```/home/jail/etc/password``` file.

```
sudo touch /home/jail/etc/password
sudo chown root:root /home/jail/etc/password
sudo chmod ugo+r /home/jail/etc/password
```

You then must update the gliders entry in /etc/password.  Here is an example
change.
Locate the gliders entry in ```/etc/password``` - for example:
```
sg001:x:1000:1000:Seaglider 1:/home/sg001://usr/sbin/tcsh

```
Copy that line to ```/home/jail/etc/password``` using the editor of your
choice, as root.  Now modified the entry in ```/etc/password``` to look like
this:

```
sg001:x:1000:1000:Seaglider 1:/home/jail:/sbin/chrootshell
```

Finally, you need to create/modify the jail's ```/etc/group``` file:

```
sudo touch /home/jail/etc/group
sudo chown root:root /home/jail/etc/group
sudo chmod ugo+r /home/jail/etc/group
```

Locate the ```gliders``` entry in the ```/etc/group``` file - for example:

```
gliders:x:1000:sg001,sg002
```

Copy/modify the corresponding line in ```/home/jail/etc/group```.  For example,
if you are only going to jail sg001 in the above example, then the line in
```/home/jail/etc/group``` should be:

```
gliders:x:1000:sg001
```

## Add runner service to systemd

```
sudo cp /usr/local/basestation3/baserunner@.service /etc/systemd/system/baserunner@.service
```
Edit the ```/etc/systemd/system/baserunner@.service``` new file with the correct paths
for the logfile use ```/home/jail/home/rundir/baserunner.log```
```
sudo systemctl daemon-reload
sudo systemctl enable baserunner@runner-gliders
sudo systemctl start baserunner@runner-gliders
sudo systemctl status baserunner@runner-gliders
```
Check the output to make sure the runner started

## Testing

You can test the jail by logging in as the user and logging out:

```
su - sg001
```

Consult ```/home/jail/home/rundir/baserunner.log``` for an errors relating the
to runner process - normal there should be no output.  Next consult
```/home/jail/home/sg<gliderid>``` There should be the typical files like
```comm.log``` and ```baselog.log```.  Check ```baselog.log``` for any
errors/processing issues.

## Jail maintenance

The jail contains copies of system binaries as well as copies of a
few pieces of basestation3.  If you update either, you need to update the
jail.  That can be done by running:

```
sudo /opt/basestation/bin/python /usr/local/basestation3/jail/create_jail.py --update /home/jail
```

# Background notes on current script

These notes are not part of the installation process -

Current jail a mix from:
    https://askubuntu.com/questions/547737/jailing-particular-users-on-login
and
    http://www.kegel.com/crosstool/current/doc/chroot-login-howto.html

The script is intended to help boot strap and update as the system binaries are updated.

## The latter script has the following:

    cd dev
    mknod null   c 1 3
    mknod zero   c 1 5
    mknod random c 1 8
    chmod 666 *
	mount -t proc proc  $JAIL/proc

Does not seem to be needed

## Termcap
To shut up output from tcsh, this tree is copied

    /lib/terminfo

just to provide the definition for the "dumb" terminal
