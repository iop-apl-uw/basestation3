# Seaglider Sensor Integration and Basestation processing

## Overview

This document disccuss instrument integration into the Seaglider, with a focus on the data flows 
from the Seaglider and data handling/processing on the basestation.

## A note on terminology

Seaglider terminology can be somewhat confusing - dives, profiles, half profiles, casts - all get used and sometimes interchangeable.  For the purpose of this document, here are some definitions:

**dive**
: A single decent to a proscribed depth, then ascent to the surface or a proscribed finish depth.

**cast**
: One of four segments of a dive where science instruments sampled - **dive**, **loiter**, **climb**, **surface loiter**

## Classes of sensors

### Truck

Instruments may be attached to the glider "truck" or main motherboard directly.  Instruments on the truck are
treated as spot sampled - that is, turned on, wait for a warm up, read data and turned off.  Frequency counted 
instruments are possible on a limited number of ports on the motherboard, but almost all instruments attached are 
RS-232 (or logic level) instruments.  (Aa port being a header on the motherboard  with gnd, power TX and RX, generally 
connected to a forward or after bulkhead connector).

In addition support for a set of instruments that have built in support, additional instruments may be attached to the truck
the serdev .cnf files.  A serdev .cnf file contains information on how to interact with the
instrument and on how to extract and store data from the instrument into the seaglider's dat file (the truck generates a single dat file per):

```
name=legato
prefix=rbr
timeout=2000
baud=19200
warmup=12000
voltage=10
headerlines=0
current=0.02
format="%d-%d-%d %d:%d:%f %00 %01 %02 %f %f %f %f %03"
query="%F%n%3%F%n%[ready: ]poll%r%nsleep%r%n"
vcolumn=conduc(10000,0)
column=temp(10000,0)
column=pressure(1000,0)
column=conducTemp(10000,0)
power-policy=1
cycles=0
```

Full documentation on this syntax may be found [here](https://iop.apl.washington.edu/iopsg/serdev.txt)
From a data flow standpoint, the key things are the ```prefix=``` and ```column=``` specifications.  The ```prefix``` 
must be unique - preferably accross all Seagliders everwhere - but it must be unique for all instruments configure on a 
single basestation.  The ```prefix``` is combined with the name portion of the ```column``` to form name of the data column in 
the gliders .dat file:

```columns: rec,elaps_tms,depth,heading,pitch,roll,GC_state,mag.x,mag.y,mag.z,rbr.conduc,rbr.temp,rbr.pressure,rbr.conducTemp,```

The remaining portion of the ```column``` spec is a scaling factor and an offset value.  The glider will subtract the offset, then multiply by the scale to transform the data read from the device.  This is important to get correct, since data columns are transmitted as integer values.  Furthermore, getting the scaling such that it yeilds values as close to zero (on the positive side) is desirable, because the glider will compress the data with a first order difference, so keeping the values close to zero means a smaller difference to be encoded.

### Loggers

The other class of instruments are generally described as ```loggers```.  Loggers also attached to a port on the Seagliders motherboard.  Unlike serdev instruments, loggers are instruments that are generally turned on at the start of the cast and off at the end.  Loggers are expected to handle there own data sampling schedule, and store any data internally and/or return data the glider at the end of the dive.  Loggers software support exists in two broad catagories - custom loggers (where all behavior it built into the glider's firmware) and **logdev** loggers - where the interface is defined by a .cnf file.

### Logdev

There is existing [documentation](https://iop.apl.washington.edu/iopsg/logdev.txt) on how the logdev machinery in the glider's firmware can be used to control a logger device.  This document will focus on the data flows.  Here is a sample .cnf file - this for a Rockland MicroriderG:
```name=MRI
prefix=mr
cmdprefix=$MR_
timeout=5000
baud=115200
warmup=25000
voltage=10
current=0.5
min-power-cycle=15000
powerup-timeout=40000
pre-start=%@30000@
start="%r%[$]odas start%r%[DAQ]%[%n]"
dive-state-end="%r%[$]sh linkfile.sh %f%r%[OK]%[$]odas stop%r%[DAQ stop message sent]%@30000@"
climb-state-end="%r%[$]sh linkfile.sh %f%r%[OK]%[$]odas stop%r%[DAQ stop message sent]%@30000@"
stop=%1
poll="%F%r%[$]odas stats short%r%[%n]%[%n]"
prompt="$"
datatype="u"
clock-set="odas date {%Y-%m-%d %H:%M:%S}%r"
clock-read="odas date%r"
post-clock=on
xmodem="%F%r%[$]sx -k /home/debian/links/%f%r%[now.]"
profiles-download=separate
post-transfer=on
cleanup="%r%r%[$]rm /home/debian/links/* %r"
```

The key items here are the ```prefix=``` and ```datatype=``` and ```xmodem=``` specifications.  ```prefix```  is always exactly two letters
and must be unique from any other loggers - preferably across all Seagliders everywhere - but it must be unique for all instruments configure on a 
single basestation.  While a logdev device can create generate files of any name, they files that are to be transmitted from the glider to the basestation and processed by the basestation must conform to the Seaglider **naming convention** - part of which is made up of the prefix.

The ```datatype``` is one of the known file packing or compression types (see below) - typically z or u for gzipped or uncompressed data.  This specification is used to composite the ```%f``` expansion to define a filename in the gliders namespace.  

<!--todo - add more here on the expansion -->

### Scicon

The scicon is a particular custom logger, that itself has devices (serial or frequency counted) attached to it.  The scicon runs its own sampling schedule - largely independent of the glider's science sampling that is much more flexible.  As with the glider, instruments are spot sampled.  There are three config files that control 
- `scicon.ins` The instruments interface definition file. 
- `scicon.att` How the instruments are attached to the scicon hardware.
- `scicon.sch` How the instruments are sampled.

`scicon.ins` is a list of instrument definitions - it may contain more definitions then are installed on a given scicon.  Here is an example of a single instrument::

```tridentebb700bb470chla470 = {
 prefix = td
 baud = 19200
 cycles = 0
 timeout = 1000
 warmup = 0
 pumptime = 0
 skip = 0
 bufflen = 0
 avg = 0
 dec = 0
 multiline = 0
 power = 0
 terminator = 10
 format = %d, %00, %01, %02
 meta = %9%9%F%n%[Ready: ]getall%r%n%[Ready:]
 column = bb700(100000,0)
 column = bb470(100000,0)
 column = chla470(1000,0)
}
```

Each instrument on a scicon is sampled on its own unique sampling time grid, resulting in a data file containing the time of the observation and all columns recorded for that observation.  From a data flow standpoint, the important specifications are the sensor name - ```tridentebb700bb470chla470``` and the `column` specifications.  The column name in the final .eng file on the basestation will be formed by the sensor name and column name.  Just as in the serdev devices, data will be offset and scaled before a first order diff is applied prior to data transmission.  Unlike the serdev, the scale and offset are included in the transmitted .dat file.

## Data transport

For the purpose of this document, we will assume that the movement of the files generated above to the basestation "just happens". The details of fragmenting files, transfer protocols, and defragmentation are not covered here - from a data flow standpoint, they are transparent.

## Review of Data Flow and Basestation processing

From a sensor data standpoint, basestation processing can be boiled down to:
- Transforming incoming .dat files (to .asc) to .eng files. 
- Reading in the contents from all .eng files from all sensors (truck, scicon, loggers) from a single dive
- Running automatic science calculations and quality control processes
- Writing the results into a .nc (netCDF) file
- Generating plots from the .nc files

<!-- Add note about break between eng and netcdf and note that netcdf can be used to reprocess -->

## Preliminaries

### Basestation Sensor Extensions

Before proceeding, a word about where sensor specific code resides on the
basestation.  While not universally true, almost all code related to the data
flow from .dat files to the .nc files is housed on a `sensor extension`.  These
are individual python module that are called by the basestation core during processing
to perform specific transformations or configuration and meta data for the
instrument the sensor supports.  In the case of serdev instruments, there is a
built in set of machinery that can use a serdev.cnf file to drive some of this
processing.  Basestation extensions are covered in more detail at the end of this document,
but will be referred to during the next section.

### Names and metadata

The process of writing a variables out to netCDF files is driven by metadata
for each variable - such as the type of the variable, the units, standard name
and what dimension and time variable the sensor is associated with.  Sensor
extensions provide this metadata - typically as part of the sensor
initialization.  Serdev devices can supply the meta data as part of the .cnf
file in specially formatted comments.  Scicon based instruments and loggers
require a python based extension to provide this meta data.

## .dat to .eng conversion

### Serdev and Scicon

#### Dat To Asc
For the truck and the scicon, each .dat file is a row/column format with a
single time vector.  The conversion to an .asc file is the mechanical undoing
of the first order difference compression that the seaglider performed.  For
the truck, the .asc file is actually written out to support later processing,
while the scicon instruments .asc format is maintained internally.

#### Asc To Eng

.asc to .eng involves undoing the scale and offset transformations and some
additional meta data being added.  The resulting file contains the data as
captured on the glider or scicon.

Since the scale and offset transformations are not encoded in the in the truck
.dat file, the scale/offset transformation must be informed by the sensor
extension.  A serdev.cnf file can be used to provide the information.  For a
python sensor extension, the transformation is encoded in the `asc2eng` function.  If
no extension is able to handle the scale/offset conversion, the data column is
propagated to the .eng file without conversion.

#### Variable name remapping

Sensor extensions can provide for variable renaming as part of the asc to eng transformation by providing the `remap_engfile_columns_netcdf` function.  This only works for sensors on the truck.  The purpose of this remapping is to be able to process data sets that were generated with sensor names that don't match the current naming conventions.

Remapping is documented here for completeness - new sensor extensions should not need to make use of the facility.

### Loggers

The logger sensor extension's `process_data_files` function is responsible for
the transformation from .dat to .eng - if any.  Many extensions elect to simply
rename the file to have a .eng extension, and put logic for reading data format
for the next step.

## Reading .eng files

For the next step of the process, the basestation will collect all .eng files for a single dive that have the same `prefix` and call the associated eng reader (the name of the reader is registered at sensor extension initialization time).  The reader processes the .eng file(s) and returns any data to be used down stream along with the name the for each data column (this is the name that will appear in the netCDF file).

### Serdev
Serdev names are transformed from `sensorname.columnname` to `eng_sensorname_columnname`

### Scicon
The reader will merge all the casts together to form a coherent timeseries.  Variables are renamed from `sensor.columnname` to `sensor_columnname`

### Loggers
Logdev devices have some choices here.  Some elect not to house data in the netCDF file, so the `eng_file_reader` returns nothing.  Others can choose to propagate the data to the netCDF file, so the reader needs to do any transformation of the logger data to match the name and shape as defined inthe metadata.

## Processing

An extension may include code that performs science or quality assurance code that acts on sensor data - this is done through the `sensor_data_processing` function.  The extension has access to all variables that are destine for the netCDF file.  This function in the extension is called after the CTD data has been processed (hydro model and its output are available as well).  The contract is new data columns may be introduced, and existing columns left alone.

## Writing out to netCDF files

There is no sensor extension interaction during data writing - all the writing is driven off the data columns in memory and its associated metadata.

## Plotting

The details of data plotting and addition of custom plots are covered in [plotting.md](plotting.md).

## Reference

### Naming convention

In general, all files generated on the seaglider (and a few generated on the basestation) follow a naming convention:
ooxxxxtf.s
Where:
:oo - the logger or system that created the file
    :sg - seaglider, st - seaglider selftest, others defined by the logger configuration 
:xxxx - the dive number
:t - the type of file
    :l - logfile, 
	:d - data file, 
	:k - capture file, 
	:a|b|c|d - cast files from a logger
	:p - pdos log
	:e - network logfile
	:r - network profile
:f - the file packing or compression
    :u - uncompressed
	:z - gzip
	:t - tarfile
	:g - gzipped tarfile
	:t - bzipped tarfile
	:p - logger payload file (only for custom loggers)
	:n - network file
:s - the transmission status of the file
	:a - archive (leave on glider) 
	:x - transmit to basestation 
	:xii - fragment (part of a file) to transmit - ii is the number in hexadecimal format, 
	:r - received on basestation (after reassembly)
	
The data encoded in these filenames drives the processing on the basestation.

The "processed" files generated by the basestation follow this naming convention:
poogggddddt.ext
Where:
:oo - the logger that is associated with the file, except for the Seaglider truck, which has no value here
:ggg - the Seaglider's serial number
:dddd - the dive
:t - the cast for the file.  If it is the entire dive, the omit
:ext - the type of the file
    :.log - generally only the Seaglider produces one, but if from a logger, its contents are undefined
    :.dat - the final output of instrument data after combining fragments and undoing compressions
	:.asc - an intermediate format produced by the Seaglider truck instruments.
	:.eng - contains science and engineering data - note: if from a logger, this may not be human readable.
	:.cap - Seaglider capture file

### Sample Sensor Extension

<!-- Insert a simple one here -->

### Installation and configuration of Sensor Extensions

<!-- Outline the installation locations and the dot file syntax -->
