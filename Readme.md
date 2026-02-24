# Seaglider Basestation Software

Shore side processing software for
[Seaglider](https://iop.apl.washington.edu/seaglider.php) buoyancy driven
autonomous underwater vehicles, developed at the University of Washington,
maintained and supported by the [IOP group at APL-UW](https://iop.apl.washington.edu/index.php).

# Operation of the basestation

The basestation operation is designed around the following philosophy:

Each Seaglider has its own user login account.
The glider uses this during deployments to log in and write data files to its
home directory.  It has read and write access to its home directory only.
Scripts run during login and logout to convert the data files into their final,
ASCII readable form for subsequent analysis.

The pilot user has read and write access to all the seaglider home
directories - by virtue of being in the same group as the glider -  since the
pilot will update `cmdfiles`, etc. to command the vehicle
and will need to read the data for analysis.

There are two ways to set up the glider home directory.  The first is to have the glider 
read and write files from the root of its home directory.  In the second method, a filesystem 
symlink - ```current``` - points to a sub-directory off the glider's home directory.  When 
this symlink is setup, the glider will connect to that sub-directory before up and down loading 
files.  All processing will occur is this sub-directory.  The script ```NewMission.py``` can be 
used to setup this structure - ```/opt/basestation/bin/python /usr/local/basesation3/NewMission.py --help``` for more details.

When a glider logs in, it expects to see `=` as its prompt, hence the .cshrc
file in each glider's directory.  It also triggers the `.login` script, which sets
up the `.connected` file.  The glider then issues `rawrcv` or `lrz` commands to the basestation
to send all the fragments and files, and `rawsend` or `lsz` commands to receive the `cmdfile`,
etc.  (The modified versions of `lrz` and `lsz` add throughput and error
notifications to `comm.log`.)  When the glider logs out the `.logout` script is
triggered, which in turn runs the `/usr/local/basestation/glider_logout` script,
which in turn runs the `/usr/local/basestation3/glider_logout` script
which in turn runs the `Base.py` script.  The `Base.py` script processes any new or
updated dive files received from the glider and processes any directives in the
`.pagers/.urls` in the `/usr/local/basestation3/etc` directory, then
`.pagers/.mailer/.ftp/.urls` files located in the Seagliders home directory. 
Consult the comments at the top of the `.pagers`/`.mailer`/`.urls/.ftp` file 
in the `/usr/local/basestation3/sg000` directory for documentation on each of
these files.

Processing options for ```Base.py``` that apply to all gliders on a single basestation
are supplied in ```/usr/local/basestation/glider_logout```.  Additional
glider-specific options may be supplied the ```.logout``` script located in each
gliders home directory be setting the environment variable ``GLIDER_OPTIONS``, or
in the Seagliders config file - `sgXXX.conf` that may optionally reside in any
gliders home directory

In addition, to assist the pilot there are a number of command line tools to
perform additional dive processing and also to validate various glider command
files - see [Validation of input files](#validation-of-input-files).  
Each tool provides help when invoked from the command line.  See
[Common Commands](#common-commands) for a list of typical commands.

# Installation

## System requirements

The basestation has been tested on Ubuntu 22.04.

For post processing, MacOS 13.3 has been tested.  It has not been
tested on Microsoft Windows.

The installation instructions assume python 3.10.10.  3.9 might still work,
3.8 and earlier likely won't work.

No explicit hardware requirements are stated, but just about anything fairly
modern should work.  (The basestation is regularly run on raspberry pi4 with 4G
of memory for single glider testing)

## Installation for post-processing

In addition to the usual use of the Seaglider basestation to handle data
coming in real-time from a Seaglider, the basestation may be installed for
re-processing of missions.  In this mode, installation location is the users
choice.  

In addition to an appropriate version of python, 
such a use only requires the required python packages be installed.

    pip install -r requirements.txt

See the section [Common Commands](#common-commands) for useful post processing
commands

## Installation for a realtime basestation

### System Prep

#### Shell installation

The basestation depends on csh being installed on the system.  On
Ubuntu, ```sudo apt-get install tcsh```

#### System time

It is strongly advised to set the basestation timezone to UTC as opposed to
local time. The basestation software internally operates on UTC time - as does
the Seaglider.

On Ubuntu, use ```sudo dpkg-reconfigure tzdata``` to set UTC as the time zone.

#### Gliders group

There needs to be a single group that all Seaglider and pilots belong to. The
instructions below assume this is ```gliders```.  You may substitute something
else, but ```gliders``` will keep things simple.

    sudo addgroup gliders

Unlike previous versions of the basestation, there is no assumption of a
dedicated pilot account.  Pilots are regular users who are in the
```gliders``` group.  Seaglider home directories are setup with group ownership
as ```gliders``` and the group has read/write/execute permissions:

	sudo adduser <user> gliders

#### PAM (Pluggable Authentication Modules)
The PAM system is prone to generating a considerable ammont of output that interferes
with the basestation <-> Seaglider login handshaking.  In /etc/pam.d/login, locate and
comment out the following lines:

    #session    optional   pam_motd.so motd=/run/motd.dynamic
	#session    optional   pam_motd.so noupdate
	#session    optional   pam_lastlog.so


## Basestation source

Basestation3 assumes it is installed in `/usr/local/basesation3`.

``` 
sudo mkdir -p /usr/local/basestation3

```

Next, make sure the directory has the correct ownership and  ```gliders``` group has 
read and execute permissions for all files:

```
sudo chown -R <user>:gliders /usr/local/basestation3
sudo chmod -R g+rx /usr/local/basestation3
```

### Living on the edge

If you want to install and keep up with the latest and greatest (or the very 
leading edge), you can clone this repository to that location:

`git clone https://github.com/iop-apl-uw/basestation3.git /usr/local/basestation3`

Then you can update your basestation code by running a `git pull origin master` from 
`/usr/local/basestation3` at a later time.

You can also download a zip file and unzip that into
`/usr/local/basestation3`. 

A word of caution - the HEAD revision may not be stable and any given point in
time.  It also may contain features or changes that are experimental on subject
to change or removal.

## Installation - two approaches

There are now two approaches to installing python and the required packages.  The first is the "traditional" basestation3 approach - which involves building python from scratch and installing packages via the python package installer - ```pip```.  The second (alternative) approach involves the package/project manager [uv](https://github.com/astral-sh/uv).  For now, either approach will work, but in future releases, the ``uv`` approach will be on the only one documented/supported.  If you want to give the ``uv`` approach a try, jump to [Install python and the basestation packages with UV](#install-python-and-the-basestation-packages-with-uv)

## Installing python

This section applies if the required version of python has changed since the last install of 
basestation3.  If not, skip to [Install the basestation python packages](#install-the-basestation-python-packages)

It is recommended that version 3.10.10 of python be installed along the a specific set of
python support libraries.  The process is as follows:

### Install preliminaries

```
sudo apt-get install -y build-essential checkinstall libreadline-dev libncursesw5-dev \
libssl-dev libsqlite3-dev tk-dev libgdbm-dev libc6-dev libbz2-dev zlib1g-dev openssl libffi-dev libgeos-dev \
python3-dev python3-setuptools wget libgdbm-compat-dev uuid-dev liblzma-dev tcsh
```

Further details on build pre-requisites are available here:
```
https://devguide.python.org/getting-started/setup-building/#build-dependencies
```

### Prepare to build

```
mkdir /tmp/Python3.10
cd /tmp/Python3.10
```

Download python source distribution and build.  Depending on your machine, this can take a while

```
wget https://www.python.org/ftp/python/3.10.10/Python-3.10.10.tar.xz
tar xvf Python-3.10.10.tar.xz
cd Python-3.10.10
./configure --enable-optimizations --prefix /opt/python/3.10.10
make

sudo mkdir -p /opt/python
sudo chown -R <user>:gliders /opt/python
make install
```

Replace ```<user>``` in the above your username.

### Check build and install

``` bash
/opt/python/3.10.10/bin/python3 --version
```

### Install the basestation python packages

```
rm -rf /opt/basestation
```
then
```
sudo mkdir -p /opt/basestation
sudo chown -R <user>:gliders /opt/basestation
```
Replace ```<user>``` in the above your username. Then

```
/opt/python/3.10.10/bin/python3 -m venv /opt/basestation
/opt/basestation/bin/pip install -r /usr/local/basestation3/requirements.txt
```
Now, jump to [login/logout scripts](#loginlogout-scripts)

## Install python and the basestation packages with UV

This alternate (and eventually only) method of setting up python and the supporting packages uses the ``uv`` package manager.

First step is to install [uv](https://github.com/astral-sh/uv).  More detailed instructions can be found in the [uv documentation](https://docs.astral.sh/uv/).

Second, create the virtual environment:

```
sudo mkdir -p /opt/basestation
sudo chown -R <user>:gliders /opt/basestation
sudo mkdir -p /opt/python_versions
sudo chown -R <user>:gliders /opt/python_versions
```
Replace ```<user>``` in the above your username. Then, use ``uv`` to create the virtual environment:

```UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/opt/python_versions uv venv --clear /opt/basestation```

*Note: if you previously created /opt/basestation using the non-uv method, you may encounter the error - failed to remove directory `/opt/basestation`: Permission denied.  If this happens, just re-run the command*

Next activate the virtual environment:

```source /opt/basestation/bin/activate```

Make sure your current directory is the root of the basestation source tree:

```cd /usr/local/basestation3```

Finally, setup the virtual environment:

```UV_MANAGED_PYTHON=1 UV_PYTHON_INSTALL_DIR=/opt/python_versions uv sync --active```

*Note: if you encounter the error - failed to remove directory `/opt/basestation`: Permission denied, just re-run the command*

To test that all is working:

```/opt/basestation/bin/python Base.py --help```

and you should see the help message for ```Base.py```

### login/logout scripts

Basestation3 differs somewhat from Basestation2, but also allows for a server
setup that that has both versions (2 and 3)  to be installed.  For basestation3, the
```.login``` and ```.logout``` scripts in the Seaglider home directory call
```/usr/local/basestation/glider_login``` and
```/usr/local/basestation/glider_logout``` respectively. These scripts are the
location where system wide customization options can be placed.  At the end of
these scripts, ```/usr/local/basestation3/glider_login``` and
```/usr/local/basestation3/glider_logout``` are called.  See
[simple_glider_login](login_logout_scripts/glider_login) and
[simple_glider_logout](login_logout_scripts/glider_logout) for the
minimal examples.  If you are installing basestation3 on a clean machine or do
not want to maintain the option of running basestation2, then these scripts
should be installed:

```
sudo mkdir -p /usr/local/basestation
sudo chown -R <user>:gliders /usr/local/basestation
cp /usr/local/basestation3/login_logout_scripts/glider_login /usr/local/basestation/glider_login
cp /usr/local/basestation3/login_logout_scripts/glider_logout /usr/local/basestation/glider_logout

```

Be sure to review and edit ```/usr/local/basestation/glider_login``` and ```/usr/local/basestation/glider_logout``` any make edits any place indicated.

#### Basesation2

If you want to maintain the ability to run basestation2, you need to do the
following:

1. Move the basesation2 installation to a new directory:

``` sudo mv /usr/local/basestation /usr/local/basestation2 ```

2. Install the switcher scripts

``` bash
sudo mkdir -p /usr/local/basestation
sudo cp /usr/local/basestation3/login_logout_scripts/switch_glider_login /usr/local/basestation/glider_login
sudo cp /usr/local/basestation3/login_logout_scripts/switch_glider_logout /usr/local/basestation/glider_logout
sudo cp /usr/local/basestation3/login_logout_scripts/check_base3 /usr/local/basestation/check_base3
```

Be sure to review and edit ```/usr/local/basestation/glider_login``` and ```/usr/local/basestation/glider_logout``` any place so indicated.

The script ```/usr/local/basestation3/check_base3``` should be edited to select
which gliders will use basestation2 and which will use basestation3

3. Editing of basestation2 files

The files ```/usr/local/basestation2/glider_login``` and ```/usr/local/basestation2/glider_logout```
need to be edited.  The string ```/usr/local/basestation``` needs to be replaced with ```$BASESTATION_PATH```

### Installation of raw protocol

From the ```/usr/local/basestation3/rawxfr``` directory

```
make
sudo make install
```

### Installation of sensor extension tools

From the ```/usr/local/basestation3/Sensors``` directory

```
make
```

### Installation of other software packages

There are two additional packages maintained in their own repositories that
should be installed.
- For all basestations, [seaglider_lrzsz](https://github.com/iop-apl-uw/seaglider_lrzsz).
- If you are using Iridium's RUDICS, [rudicsd](https://github.com/iop-apl-uw/rudicsd).

# Commissioning a new glider

    sudo /opt/basestation/bin/python /usr/local/basestation3/Commission.py XXX

where ```XXX``` is the gliders 3 digit serial number.

By default, the glider password is set to our current, hard-to-remember password scheme:

- Drop any leading zeros from the glider id.
- For even-numbered gliders:
	replace the leading digits of 024680 with the glider id
- For odd-numbered gliders:
	replace the leading digits of 135791 with the glider id

E.g., glider SG074 will have the password 744680 and SG051 will have the
password 515791.

It is strongly suggested that generate a stronger password - just be sure your glider and
basestation agree on what the password is.

Give the ```gliders``` group read/write/execute permission for the glider directory.

     sudo chmod g+rwx <seaglider_home_directory>

## Additional security considertions

### Limit login access

In addition to a strong password, it is recommended to limit the users that can
login via serial line and telnet.  To do so, add the following line to
```/etc/pam.d/login``` at the very top.

```
auth required pam_listfile.so onerr=fail item=user sense=allow file=/etc/users.allow
```

Then create a file (user: root, group: root)

```
/etc/users.allow
```

The file is one user name per-line.  No wildcards allowed.  So, if you had two
gliders ```sg090``` and ```sg095``` both commissioned on your basestation, the
file would be

```
sg090
sg095
```

Any login from the serial line or telnet (rudics) that does not match a line in
```/etc/users.allow``` is not accepted.

### chroot jail for Seagliders

The basestation has support for running the Seaglider user accounts inside a
very limited chroot jail.  Under this scheme, the Seaglider account only has
access to the binaries needed to exchange file information with basestation
server.  The actual running of the conversion process is handled by a different
user account.  See the [Jail ReadMe.md](jail/ReadMe.md) for details.

Note: when running a Seaglider account under a jail, the ```~``` expansion for 
home directory does not work for the Seaglider account.  

# To test the new glider account

Log into the glider account via the su command:

    su - sg001

Where sg001 is a glider you have commissioned.  You should see a prompt of the form:

    sg001=

Log out, then examine the home directory for sg001.  You should see a
file of the form baselog_YYMMDDHHMMSS.  Check for any python
errors (missing package XXXX) - install anything missing.

# Direct modem support using mgetty
If you are using a dialup modem, hook up your modem to the appropriate serial
port and ensure that there is an mgetty servicing that port.

Ensure mgetty is installed: ```sudo apt-get install mgetty```

Look at the boot messages in dmesg that assign ttySn ports to the modems:

	sudo dmesg | grep ttyS
	
For instance, the output might read

```
[    1.170734] 00:01: ttyS0 at I/O 0x3f8 (irq = 4, base_baud = 115200) is a 16550A
[    1.205001] 00:02: ttyS1 at I/O 0x2f8 (irq = 3, base_baud = 115200) is a 16550A
```

Next, create a systemd conf file. For example, if your modem is in /dev/ttyS0,
create the file ```/etc/systemd/system/ttyS0.service``` with the following contents:

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
Enable the service with ```sudo systemctl enable ttyS0.service```

Start the event by issuing a ```sudo systemctl start ttyS0.service``` and confirm the
mgetty is running by consulting the process list.  Verify that the
modem is accessible by inspecting the associated log in the directory
/var/log/mgetty.  Call the associated phone number to verify the
basestation answers.

(If you have two modems, you can use minicom to call one modem from the other.)

# .pagers and .mailer files support

The .pagers and .mailer mechanism rely on a working SMTP MTA on the basestation.
The only one that has been tested is postfix.
Configuring a MTA is beyond the scope of this documentation as it
can be highly dependent on local network management practice.

## Validation of input files

Basestation3 ships with a simple file validator for ```cmdfile```,
```science``` and ```targets``` files.  To invoke he validator, you need to
provide a glider ```.log``` file for the validator to use as a baseline  and a
flag to specify the file type (-c, -s, or -t). For
example:
```
/opt/basestation/bin/python /usr/local/basestation3/validate.py <seaglider_home_directory>/p00010001.log -c ~sg001/cmdfile
```

# Additional documentation

There are a number of configuration files that live in seagliders home
directory.  Documentation for these files are provided in the sample/template
files located in the sg000 sub-directory

- [Pagers](sg000/.pagers?raw=true)
- [Mailer](sg000/.mailer?raw=true)
- [FTP](sg000/.ftp?raw=true)
- [URLS](sg000/.urls?raw=true)
- [Extensions](sg000/.extensions?raw=true)
- [Early Extensions](sg000/.pre_extensions?raw=true)
- [Seaglider conf file](sg000/sg000.conf?raw=true)
- [Meta data for netcdf files](sg000/NODC.yml?raw=true)
- [Section plotting settings](sg000/sections.yml?raw=true)
- [sg_calib_constants.m](sg000/sg_calib_constants.m?raw=true)

Additional documentation can be found in [docs/Docs.md](docs/Docs.md) 

# Additional hook scripts

Hook scripts are executable files that if present in the seagliders mission 
directory, will be executed by the basestation.  Here is a summary of those files:

| Hook Name     | When exccuted                                  | Arguments                          | Notes                                            | Default timeout (secs) | Timeout Option          |
|:--------------|:-----------------------------------------------|:-----------------------------------|:-------------------------------------------------|:-----------------------|-------------------------|
| .pre_login    | During seaglider login                         | None                               | Needs to be fast - holds up login until complete | 5                      | --pre_login_timeout     |
| .post_dive    | After all per-dive file processing is complete | None                               |                                                  | 120                    | --post_dive_timeout     |
| .post_mission | After all file creation is complete            | List of all generated files        |                                                  | 360                    | --post_mission_timeout  |
| .XX_ext.py    | After all logger processing is complete        | List of all processed logger files | XX is the two letter prefix for the logger       | 120  (per script)      | --logger_script_timeout |

All hook scripts are executed with a timeout to complete.  The timeout may be adjusted or removed by setting the timeout option to a different number of seconds (or 0)

While these files can be any executable, generally they are a shell script.  For example, where is a version of ```.post_mission``` that echos out all the newly created files
```
#/bin/bash
for arg in $*; do
 echo ${arg}
done
```

# Misc dot files

## go_fast

If a file named ```.go_fast``` is present in the Seaglider's mission directory, processing for the following areas will be skipped `FlightModel`, `MissionPlots`, `MakeMissionTimeseries`, `MakeMissionProfile` and `MakeKML` during the running of `Base.py` regardless of any other switches or settings.  The intent of this option is to allow the pilot to get rapid turn around of processing on slow systems when directly working on a glider and rapid processing of `pdoscmds.bat` output and `pagers` is needed.  It should be used with caution.

# Differences from previous versions

## FlightModel

Basestation3 contains several new behaviors that users of Basestation2
might not expect (depending on the previous version of Basestation2 used).

The basestation now uses the FlightModel system to continiously evaluate the glider's volume
and hydrodynamic model parameters.  Many of the tuning parameters in sg_calib_constants.m are
no longer used.  This feature can be turned off using the options
```--ignore_flight_model --skip_flight_model```

See [FlightModel.pdf](docs/FlightModel.pdf?raw=true) in the docs directory for further
details.

## Deletion of uploaded files

The default ```glider_logout``` script sets the option
```--delete_upload_files```.  When set, the basestation will examine
Seaglider's home directory and most recent ```comm.log``` call-in session.  If
it is determined that any of the glider input files [```targets```, ```science```,
```pdoscmds.bat```, ```scicon.sch```, ```scicon.att``` ```scicon.ins```] was
successfully uploaded to the glider, that file will be deleted after it is
backed up.  Note: ```cmdfile``` is never deleted.  The algorithm is pessimistic, so clear evidence of an upload is
needed for the file to be deleted. 

This option may be removed from ```glider_logout``` to disable this feature.

## Mission Database

Basestation3 makes use of a sqlite database to store information about the
Seaglider mission.  The database located in the Seaglider's home directory and 
is named ```sgxxx.db```.  This database is primarily to support the
visualization server ```vis.py```, but may be used by user code for whole
mission analysis.  The schema is still somewhat in flux and subject to change
in future releases.

# Common Commands

The most common use case for Basestation3 is the processing of glider data in near
real-time.  There are a number of commands that prove useful for post
processing glider data.

Every python script that can be invoked directly has help available by
supplying the `--help` argument.

## Reprocess.py 

```Reprocess.py``` starts with the `.log` and `.eng` files and can regenerate
netcdf files, run Flight Model and generate plots. 

Regenerate all netcdf files, run Flight Model and generate plots:

```
/opt/basestation/bin/python /usr/local/basestation3/Reprocess.py \
 --mission_dir <seaglider_home_directory> --force --reprocess_plots
```

Regenerate the dive 100 through 102 netcdf files, not re-running Flight Model

```
/opt/basestation/bin/python /usr/local/basestation3/Reprocess.py \
 --mission_dir <seaglider_home_directory> --force --skip_flight_model 100:102
```

## BaseDB.py

The mission database is added to during the normal logout processing.  If there was ever 
a need to regenerate the database:

```
/opt/basestation/bin/python /usr/local/basestation3/BaseDB.py \
 --mission_dir <seaglider_home_directory> addncfs
```

## BasePlot.py

Any of the plots may be generated outside of the normal logout processing.  

To generate all the plots for dive 100, generating stand-alone html files, in addition 
to the normal output:

```
/opt/basestation/bin/python /usr/local/basestation3/BasePlot.py \
 --mission_dir <seaglider_home_directory>  --plot_types dives --full_html p0010100.nc
```

To regenerate the whole mission plots:

```
/opt/basestation/bin/python /usr/local/basestation3/BasePlot.py \
 --mission_dir <seaglider_home_directory>  --plot_types mission
```


## MoveData.py

```MoveData.py``` is used to clean up a Seaglider's home directory prior to
a new deployment.
```
/opt/basestation/bin/python /usr/local/basestation3/MoveData.py \
 --mission_dir <seaglider_home_directory> -t <target_directory> --verbose
```

## BaseCtrlFiles.py

```BaseCtrlFiles.py``` contains the low-level routines that send notifications sent via the ```pagers.yml``` configuration files.  
For debugging purposes, these routines can be accessed directly, but they may not generate meaningful content.  Additionally, it is possible 
to dump the merged ```pagers.yml``` dictionary. 

To execute a low-level notification, simply supply one of the low-level notification tags:
```
/opt/basestation/bin/python /usr/local/basestation3/BaseCtrlFiles.py \
 --mission_dir <seaglider_home_directory> [--group_etc <group_etc_directory>] [divetar,upload,lategps,errors,drift,comp,tracebackrecov,alerts,gps,critical]
```
For example, ```gps``` will dispatch the GPS position found in the last comm session in the ```comm.log``` to those users subscribing to ```gps``` notifications.

To dump the merged ```pagers.yml``` dictionary:
```
/opt/basestation/bin/python /usr/local/basestation3/BaseCtrlFiles.py \
 --mission_dir <seaglider_home_directory> [--group_etc <group_etc_directory>] dump_pagers_yml
```

