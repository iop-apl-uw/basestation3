# Basestation Plotting.

This document covers the basics of basestation3 plots and ways to add additional plots such that they are visible through the vis.py website.

## Plot File Location

All plot files must reside in the ```plots``` subdirectory of the Seaglider's mission directory.  This directory is automatically created
by the basestation code when needed.  Plot generating code should not create this directory manually - getting the
directory permissions is important for later access.

## Plot File Format

Plot files may be static images or a plotly ```<div>``` format.  Just about any static image type will work - the preferred format is ```webp```, but ```png``` and ```jpg``` are also known to work.  Output size should be 1058 pixels wide and 894 pixels high.  Other sizes may work, but these values are what other plotting output uses. Vis will auto shrink plots (for thumbnails in the ribbon).  While generating `<div>` content (that is, HTML), the only path that is known to currently work is through the basestation provided utilities.

In order to get the thumbnail in the ribbon to look correct a static image must be supplied, with a `<div>` being optional.

Plot file need to file the following naming convention:

### Per-dive Plot files

```dvXXXX_<plot_name>.<extension>```
Where `<XXXX>` is the 4 digit dive number, zero padded, `<plot_name>` is the name of the plot.  Use underscores to separate parts of the name - `vert_vel_regression` as an example and note required `_` between the dive number and the plot name.  `<extension>` is the file type (`webp`, `png`, etc.)  These files will only be shown in the ribbon and main plot window of the currently active dive in vis.

### Whole Mission Plot files

```eng_<plot_name>.<extension>```
Where `<plot_name>` is the name of the plot.  Use underscores to separate parts of the name - `mission_volmax` as an example and note required `_` between `eng` and plot name.  `<extension>` is the file type (`webp`, `png`, etc.)  These files will be shown in the ribbon and main plot window for all dives.

## Relationship of the plots directory and vis

When vis is running over a mission directory, any new or updated files that appear in the `plots` directory will be displayed in vis - no other explicit action is needed after generating a new plot. Because this uncoupled arrangement, there are a number of ways to add new plots.

At a minimum, a static file format must be provided (`webp`, `png` or `jpeg` all work).  This file will be shrunk to fit in the ribbon and displayed full size in the main plot window.  The expected size of the plot is 1058 wide and 894 high.  An alternative html verision of the plot may also be present - this file with a `div` extension.  The basestation code use [Plotly](https://plotly.com/) to generate such files - other generators may work, but are untested.  If the `div` is present, it will be displayed in the main plot window intead of the static format.

## Ways of generating plot files

### Decoupled from basestation processing

One completely valid way to add new plots is to have some other process running locally or on another machine that generates plots, pushing the results into the `plots` sub-directory.  For example, there could be a cronjob running on a periodic basis that looks for new data files in the mission directory, performs some analysis and generates output plots that are copied into the `plots` sub-directory.

An issue to be aware of is the plots directory needs to be writable by the user id generating the plots and readable by the user id that vis is running under.  By default, the plots directory is owend by the glider or the runner account (depending on which method you are using).  One solution is to make the plots directory writeable by everyone - with the attendent security concerns.  If using a runner account, another option is to use that account to generate the plots.

#### vis notifications

The drawback of the above is that <code>vis</code> is not notified when a new plot has been created and will not automatically add the new plot to the interface.  Later basestation activity will cause the plots directory to be re-scanned, or the users browswer can be refreshed.

### Using a hook script file.

There are a number of places where the basestation calls out to hook scripts - these any executable with the correct naming - during the course of processing.  (See the main [Readme.md](../Readme.md#additional-hook-scripts) for more details on hook scripts)  One good option is to `.post_mission` script - which gets called with a list of all files generated or updated during processing on the cmdline - allowing the script to look for any specific files to generate plots off.


### Using a basestation extension

Basestation extensions are a flexible way to extend the basestation's functionality.  They can be called from a number places in the seaglider processing code and generally have enough context to allow plots to be generated based on what files have been updated during the current processing run.  Generally, the best place to run a per-dive plotting extension is from the <code>[dive]</code> section of <code>.extensions</code>, and the <code>[mission]</code> section for whole-mission plots.

[SimplePlotExtension.py](../SimplePlotExtension.py) is an example of such an extension that may be used as a starting point for per-dive plots.  See [.extensions](../sg000/.extensions) for more details and references to other extensions included in the basestation code base.

### Using a basestation plotting extension

Basestation plotting extensions are the most closely coupled with the built-in basestation plotting routines.  All plotting extensions reside in `/usr/local/basestaiton3/Plotting` or in `/usr/local/basestaiton3/Plotting/local`.  Files in the later location may be symlinks to other locations in the file system.

### Configurable plotting services

There are currently two basestation plotting extensions that allow plot generation for variables driven by user defined configuration files.  
- For single dives, [DiveScience](../sg000/divescience.yml) allows for single or multiple variables to plotted as down and up profiles against gliderdepth.
- For a series of dives, [MissionProfile](../sg000/sections.yml) allows for the plotting of single variables as a heatmap as time vs. depth.
