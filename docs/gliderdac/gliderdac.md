# GliderDAC extension.

The basestation extension - GliderDAC.py - can assist you in preparing data for 
submission to the GliderDAC.  Setting up GliderDAC access, WMO ids, and internal workings
of the GliderDAC are not covered here.

The extension works by extracting variables (timeseries and singletons) from the per-dive netcdf files created
by the basestation and generating a new netcdf file for submission.  The extraction and variable metadata is
largely data driven based on a three configuration file hierarchy.  Configuration files are YAML (https://yaml.org/).

The files are separated following a typical pattern of glider deployment.  All contents could be placed in a 
single file (although the extension requires three to be specified).  Example files are included in this directory. 
Many of the fields are examples taken from an actually glider deployment - be sure to modify everything specific to 
your situation.

## Files

### [sgXXX.conf](sgXXX.conf)

Shows a typical seaglider .conf file specifying the three config files and a couple
of option settings.  The exact names of these files is not important - only how they are 
mapped to the option settings in the .conf file

Any content can appear any file.

### [seaglider.yml](seaglider.yml) (option - --gliderdac_base_config)

This is the base glider configuration for all seagliders.  In this example, some content
(such as creators name) is specified here, and not in more specific config files.

### [project.yml](project.yml) (--option gliderdac_project_config)

Intended as the location for config that applies to a set of gliders operating in a single
project/experiment.  Settings here add to, or override, those in seaglider.yml.

### [sgXXX.yml](sgXXX.yml) (--option gliderdac_deployment_config)

Intended as config related to specific glider on a specific deployment. Settings here 
add to, or override, the other two config files.

### [sg000/.ftp](../../sg000/.ftp)

The sample .ftp file shows a line that may be used to push data to the gliderdac (using 
you user account)

### [sg000/.extensions](../../sg000/.extensions)

The sample .extension file shows how to enable the GliderDAC.py extension

## Checking the configuration

The three yml files are merged base, then project, then deployment - from the most general to the most
specific. A later file adds to the earlier ones, key by key, and overrides any value they set (a list,
e.g. `dimensions`, is replaced whole). To remove something an earlier file set - an attribute, a whole
variable, a `timeseries_vars` entry - set it to `null` in the later file. Check them with
`GliderDACModel.py` (every problem is reported as `file:line`; with `--verbose`, `check_merged` also
lists each override and removal and where it came from):

```
GliderDACModel.py check sgXXX.yml                                  # one file on its own
GliderDACModel.py dump sgXXX.yml > loaded.yml                      # one file, as loaded
GliderDACModel.py --verbose check_merged --config sgXXX.conf       # the files the .conf names, merged
GliderDACModel.py dump_merged --config sgXXX.conf > merged.yml     # the merged template
```

A misspelled key, a bad `type` or `qc_data`, a YAML syntax error, or a `platform`/`instrument_*`
variable without a `_FillValue` stops GliderDAC output until fixed. A variable
left without `type`, `dimensions` or `attributes` after the merge - often a mis-indented block - is
dropped and the rest is still written. Both raise the `GLIDERDAC_CONFIG` alert.

## Processing

The GliderDAC.py extension uses a normal per-dive netCDF file as input and generates a gliderdac netcdf file 
per the above configuration settings.  Typically, this is done the normal course of processing the Seaglider's
output in near realtime.

The extension may also be invoked directly if re-processing is needed:

### All per-dive netCDF files

```
/opt/basestation/bin/python /usr/local/basestation3/GliderDAC.py \
 --mission_dir <seaglider_home_directory>  --config <seaglider_config_file> 
```

### A single per-dive netCDF files

```
/opt/basestation/bin/python /usr/local/basestation3/GliderDAC.py  --config <seaglider_config_file> <path_to_pxxxyyyy.nc>
```

To push manually push files to the gliderdac, the following script is useful:

```/opt/basestation/bin/python /usr/local/basestation3/FTPPush.py --mission_dir <seaglider_home_directory> --verbose "./gliderdac/*"```


