Seaglider Basestation Readme

# Operation of the basestation

The basestation operation is designed around the following philosophy:

Each Seaglider has its own logon id (see "Commissioning a new glider", below).
The glider uses this during deployments to log in and write data files to its
home directory.  It has read and write access to its home directory only.
Scripts run during login and logout to convert the data files into their final,
ASCII readable form for subsequent analysis.

The pilot user has read and write access to all the seaglider home
directories since the pilot will update cmdfiles, etc. to command the vehicle
and will need to read the data for analysis.

When a glider logs in, it expects to see '=' as its prompt, hence the .cshrc
file in each glider's directory.  It also triggers the .login script, which sets
up the .connected file.  The glider then issues lrz commands to the basestation
to send all the fragments and files, and lsz commands to receive the cmdfile,
etc.  (The modified versions of lrz and lsz add throughput and error
notifications to ~/comm.log.)  When the glider logs out the .logout script is
triggered, which in turn runs the /usr/local/basestation/glider_logout script,
which in turn runs the Base.py script.  The Base.py script processes any new or
updated dive files received from the glider and processes any directives in the
.pagers/.mailer/.ftp/.urls files. Consult the comments at the top of the
.pagers/.mailer/.urls file in the sg000 directory for documentation on each of
these files.

Processing options for Base.py that apply to all gliders on a single basestation
are supplied in /usr/local/basestation/glider_logout.  Additional
glider-specific options may be supplied the .logout script located in each
gliders home directory be setting the environment variable GLIDER_OPTIONS.

In addition, to assist the pilot there are a number of command line tools to
perform additional dive processing and also to validate various glider command
files.  Each command line tool has a plain text documentation file in the docs
subdirectory that provides a Unix man style doc format.

# Preparation of the basestation

The description below assumes you are running some Linux variant as the
basestation OS. This code has been tested on Ubuntu 18.04 (server).  It is
possible to run the basestation code on OS X to reprocess Seaglider data.  No
installation instructions are provided. The basestation code will not work on Windows.  

The basestation depends on csh being installed on the system.  On
Ubuntu, 'sudo apt-get install tcsh".

It is strongly advised to set the basestation timezone to UTC as opposed to
local time. The basestation software internally operates on UTC time - as does
the Seaglider.  When interacting with the basestation operating system or files
generated by other applications on the operating system (primarily, this is the
comm.log file), the basestation software attempts to convert from local time to
UTC.  Due to some shortcomings in Python support libraries, many locales do not
have conversions to UTC available.  In these cases, the basestation will assume
the time is UTC and proceed (issuing a warning). Conversion and processing of
the Seaglider software is not affected by these conversions. 

On Ubuntu, use "sudo dpkg-reconfigure tzdata" to set UTC as the time zone.

See the release notes at the bottom for more version specific details.

This version of the code has been written to and tested against python 3.7.7.

See the relevant sections in the install steps on notes on packages versions.

# Notes on basestation code distribution

Depending on what terms you have received the basestation code under, you will have up
to 2 packages:
- Base-3.01.tgz (core basestation)
- packages.tgz (third-party code, referenced from the basestation),

# Installation steps

## Installing python

It is recommended that version 3.7.7 of python be installed along the a specific set of 
python support libraries.  The process is as follows:

1. Install preliminaries

```
sudo apt-get install -y build-essential checkinstall libreadline-gplv2-dev libncursesw5-dev \
libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev zlib1g-dev openssl libffi-dev \
python3-dev python3-setuptools wget

```
2. Prepare to build

``` 
mkdir /tmp/Python37
cd /tmp/Python37
```

3. Download python source distribution and build.  Depending on your machine, this can take a while

```
wget https://www.python.org/ftp/python/3.7.7/Python-3.7.7.tar.xz
tar xvf Python-3.7.7.tar.xz
cd /tmp/Python37/Python-3.7.7
./configure --enable-optimizations
make 
sudo make altinstall
```

4. Check build and install 

``` bash
python3.7 --version
```

## Install the basestation code and python packages

1. If you have an existing installation of the basestation in /usr/local/basestation,
   you should back the contents up
2. Copy the tarball Base-3.01.tgz to /usr/local
3. Unpack the tarball using the command "sudo tar xvzf Base-3.01.tgz"
4. Install the required python libraries

```
cd /usr/local/Base-3.01
pip3.7 install -r requirements.txt
```

5. Install additional plotting libs

```
sudo apt-get install libgeos-dev
pip3.7 install git+https://github.com/matplotlib/basemap.git
```

6. Installseawater routines for python (in packages tarball)

	In /usr/local/Base-3.01/packages, "sudo tar xvzf seawater-1.1.tgz"
	In /usr/local/Base-3.01/packages/seawater-1.1 run 'sudo python setup.py install'
    Tested with version 1.1


6. Copy the support packages tarball - packages.tgz to the /usr/local/Base-3.01 directory, and unpack,
   using the command "sudo tar xvzf packages.tgz"
7. In /usr/local/Base-3.01, run "sudo ./install_base.sh" to install the basestation code into /usr/local/basestation

8. In /usr/local/Base-3.01 run "sudo ./setup_users.sh" to setup the pilot and sg000 accounts

-- OR --

8a. As root, create a user group called gliders
8b. Create the following users and make /bin/csh their login shell:

	pilot
		- write access to all gliders directories
		- put into gliders group
	sg000
		- location of commissioning files for new gliders
		- put into gliders group

9. In /usr/local/Base-3.01 run "sudo ./copy_sg000.sh"
10) Make sure you have Python installed.  See notes above for Python version issues.  
Use 'python --version' to determine the version.

There are several additional packages you will need that are not distributed with
the basestation:



## Install lrzsz
To maintain a log of xmodem communications progress ('comm.log') you must install
modified versions of lrz and lsz in /usr/local/bin.

(Note: You may need to install make on your server machine - 'sudo apt-get install make')

In /usr/local/Base-3.01/packages/lrzsz-0.12.20:
10a) Run "sudo ./build.sh"
10b) Run "sudo make install"
10c) Ensure that /usr/local/bin is at the head of the path for the glider accounts

## Install optional raw send and raw recieve
11a) In /usr/local/Base-3.01/packages unpack rawxfr.tgz by "sudo tar xvzf rawxfer.tgz"
11b) In /usr/local/Base-3.01/packages/rawxfer build the binaries "sudo make"
11c) Copy the binaries to /usr/local/bin "sudo cp rawrcv rawsend /usr/local/bin"

## Install the optional cmdfile, science and targets validator
12a) In /usr/local/Base-3.01/Validate-66.13 run 'sudo make -f Makefile.validate' to build validate binary
12b) In /usr/local/Base-3.01 run "sudo ./install_validate.sh"
12c) Confirm that validate, cmdedit, targedit and sciedit are installed in /usr/local/bin
12d) As pilot, run cmdedit from a glider's home directory to confirm all is working

## Install the optional gliderzip
If you plan to upload gzipped files to the glider, install this special version of gzip. See Upload.py.

13a) In /usr/local/Base-3.01/gliderzip_src build the binaries "sudo make -f Makefile.gliderzip"
13b) Copy gliderzip to /usr/local/basestation

## Install optional RUDICS support
14a) cd /usr/local/Base-3.01 and unpack via "sudo tar xvzf rudics.tgz"
14b) Follow the instructions provided in packages/rudics/ReadMe

# Commissioning a new glider
As root, run:

   	python /usr/local/basestation/Commission.py XXX

The glider password is set to our current, hard-to-remember password scheme:

- Drop any leading zeros from the glider id.
- For even-numbered gliders:
	replace the leading digits of 024680 with the glider id
- For odd-numbered gliders:
	replace the leading digits of 135791 with the glider id

E.g., glider SG074 will have the password 744680 and SG051 will have the
password 515791.

You are free to establish another password policy - just be sure your glider and
basestation agree on what the password is.

# To test the new glider account

Log into the glider account via the su command:

su - sg001

Where sg001 is a glider you have commissioned.  You should see a prompt of the form:

sg001=

Log out, then examine the home directory for sg001.  You should see a
file of the form baselog_YYMMDDHHMMSS.  Check for any python
errors (missing package XXXX) - install anything missing.

# Direct modem support using mgetty
Hook up your modem to the appropriate serial port and ensure that
there an mgetty servicing that port.  

Ubuntu 16.04:
Ensure mgetty is installed: 'sudo apt-get install mgetty'

Look at the boot messages in dmesg that assign ttySn ports to the modems:

[    2.528748] 0000:00:0c.0: ttyS4 at I/O 0xb000 (irq = 17, base_baud = 115200) is a 16550A
[    2.548901] 0000:00:0c.0: ttyS5 at I/O 0xa800 (irq = 17, base_baud = 115200) is a 16550A

Create a systemd conf file. 
Create a systemd conf file. For example, if your modem is in /dev/ttyS0, 
create the file "/etc/systemd/system/ttyS0.service" with the following contents:

```
[Unit]
Description=ttyS0 agetty
Documentation=man:agetty(8)
Requires=systemd-udev-settle.service
After=systemd-udev-settle.service

[Service]
Type=simple
ExecStart=/sbin/mgetty ttyS0
Restart=always
PIDFile=/var/run/agetty.pid.ttyS0

[Install]
WantedBy=multi-user.target
```
Enable the service with "sudo systemctl enable ttyS0.service"

Start the event by issuing a "sudo systemctl start ttyS0.service" and confirm the
mgetty is running by consulting the process list.  Verify that the
modem is accessible by inspecting the associated log in the directory
/var/log/mgetty.  Call the associated phone number to verify the
basestation answers.

[If you have two modems, you can use minicom to call one modem from the other.]

.pagers .mailer
-----------------
The .pagers and .mailer mechanism rely on a working SMTP MTA on the basestation.
The only two that have been tested are sendmail and postfix (with a preference
for postfix).  Configuring a MTA is beyond the scope of this documentation as it
can be highly dependent on local network management practice.

Version specific release notes
------------------------------

Version 3.01
------------
The basestation now uses the FlightModel system to continiously evaluate the glider's volume
and hydrodynamic model parameters.  Many of the tuning parameters in sg_calib_constants.m are 
no longer used - in fact, FligtModel will re-write the sg_calib_constants.m file to remove the
no longer used versions.

N.B. The glider's user account must have write permissions to sg_calib_constants.m

See FlightModel.pdf in the docs directory for further details.
