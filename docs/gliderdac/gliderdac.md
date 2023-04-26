* GliderDAC extension.

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

** Files

*** sgXXX.conf

Shows a typical seaglider .conf file specifying the three config files and a couple
of option settings.  The exact names of these files is not important - only how they are 
mapped to the option settings in the .conf file

Any content can appear any file.

*** seaglider.yml (option - --gliderdac_base_config)

This is the base glider configuration for all seagliders.  In this example, some content
(such as creators name) is specified here, and not in more specific config files.

*** project.yml (--option gliderdac_project_config)

Intended as the location for config that applies to a set of gliders operating in a single
project/experiment.  Settings here, override those in seaglider.yml.

*** sgXXX.html (--option gliderdac_deployment_config)

Intended as config related to specific glider on a specific deployment. Settings here 
override the other two config files.

*** sg000/.ftp

The sample .ftp file shows a line that may be used to push data to the gliderdac (using 
you user account)

*** sg000/.extensions

The sample .extension file shows how to enable the GliderDAC.py extension
