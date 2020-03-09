#! /usr/bin/env python

##
## Copyright (c) 2006, 2007, 2008, 2009, 2010, 2011, 2012, 2013, 2014, 2017, 2018, 2019, 2020 by University of Washington.  All rights reserved.
##
## This file contains proprietary information and remains the
## unpublished property of the University of Washington. Use, disclosure,
## or reproduction is prohibited except as permitted by express written
## license agreement with the University of Washington.
##
## THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
## AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
## IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE
## ARE DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE
## LIABLE FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR
## CONSEQUENTIAL DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF
## SUBSTITUTE GOODS OR SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS
## INTERRUPTION) HOWEVER CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN
## CONTRACT, STRICT LIABILITY, OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE)
## ARISING IN ANY WAY OUT OF THE USE OF THIS SOFTWARE, EVEN IF ADVISED OF THE
## POSSIBILITY OF SUCH DAMAGE.
##

# TODOCC
# 1) Convert from optparse to argparse
# 2) argv in the constructor - needed? Reconcile with the sys.argv[0] to setup the basestation directory

"""
  Common set of pathnames and constants for basestation code:
  Default values supplemented by option processing, both config file and command line
"""

import configparser
import optparse
import os
import os.path
import sys
import traceback

from Globals import WhichHalf, basestation_version

#
# Default values supplemented by option processing, both config file and command line
#

class BaseOptions:

    """
    BaseOptions: for use by all basestation code and utilities.
       Default options in code are trumped by options listed in configuration file;
       config file options are trumped by command-line arguments.
    """
    is_initialized = False

    # default values
    config_file_name = None
    debug = False
    verbose = False
    force = False
    reprocess = False
    divetarballs = 0
    local = False
    daemon = False
    target_dir = None
    encrypt = None
    mission_dir = None
    magcalfile = None
    auxmagcalfile = None
    delete_upload_files = False
    bin_width = 5.0
    which_half = WhichHalf(3) #pylint: disable=E1120
    interval = 0
    reply_addr = None
    domain_name = None
    web_file_location = None
    base_log = None # base_log file name
    instrument_id = 0
    make_dive_profiles = False
    make_dive_pro = False
    make_dive_bpo = False
    make_dive_netCDF = False
    make_mission_profile = False
    make_mission_timeseries = False
    make_dive_kkyy = False
    ver_65 = False
    clean = False
    gzip_netcdf = False
    profile = False
    ignore_lock = False
    home_dir = None
    glider_password = None
    glider_group = None
    home_dir_group = None
    reprocess_plots = False
    reprocess_flight = False
    nice = 0

    # statics, valid after initialization
    _opts = None
    _args = None
    _op = None

    def __init__(self, argv, src, usage=None):
        """
        Input:
            argv - raw argument string
            src - source program:
                    a - BattGuage.py
                    b - Base.py
                    c - Commission.py
                    d - MakeDiveProfiles.py
                    e - CommStats.py
                    f - DataFiles.py
                    g - MakePlot.py
                    h - BaseAES.py
                    i - BaseSMS.py
                    j - GliderJabber.py
                    k - MakeKML.py
                    l - LogFile.py
                    m - MoveData.py
                    n - BaseLogin.py
                    o - CommLog.py
                    r - Cap.py
                    p - MakeMissionProfile.py
                    q - Aquadopp.py
                    s - Strip1A.py
                    t - MakeMissionTimeSeries.py
                    u - Bogue.py
                    z - BaseGZip.py
            usage - use string
        """
        if argv:
            basestation_directory, _ = os.path.split(os.path.abspath(os.path.expanduser(argv[0])))
            BaseOptions.basestation_directory = basestation_directory # make avaiable
            sys.path.append(basestation_directory) # add path to load common basestation modules from subdirectories

        if not BaseOptions.is_initialized:
            # default values for config parser: only used if called with "-c"
            cp = configparser.RawConfigParser({
                "debug": str(self.debug),
                "verbose":  str(self.verbose),
                "force":  str(self.force),
                "reprocess":  str(self.reprocess),
                "divetarballs":  self.divetarballs,
                "local":  str(self.local),
                "daemon":  str(self.daemon),
                "target_dir": self.target_dir,
                "encrypt": self.encrypt,
                "mission_dir": self.mission_dir,
                "magcalfile": self.magcalfile,
                "auxmagcalfile": self.magcalfile,
                "delete_upload_files": self.delete_upload_files,
                "base_log": self.base_log,
                "instrument_id": self.instrument_id,
                "make_dive_profiles": str(self.make_dive_profiles),
                "make_dive_pro": str(self.make_dive_pro),
                "make_dive_bpo": str(self.make_dive_bpo),
                "make_dive_netCDF": str(self.make_dive_netCDF),
                "make_mission_profile": str(self.make_mission_profile),
                "make_mission_timeseries": str(self.make_mission_timeseries),
                "make_dive_kkyy": str(self.make_dive_kkyy),
                "ver_65": self.ver_65,
                "clean": self.clean,
                "gzip_netcdf": self.gzip_netcdf,
                "profile": self.profile,
                "ignore_lock": self.ignore_lock,
                "bin_width": self.bin_width,
                "which_half": self.which_half,
                "interval": self.interval,
                "reply_addr": self.reply_addr,
                "domain_name": self.domain_name,
                "web_file_locaion": self.web_file_location,
                "reprocess_plots": self.reprocess_plots,
                "reprocess_flight": self.reprocess_flight,
                "nice": self.nice,
                "which_half": self.which_half,
                })

            op = optparse.OptionParser(usage=usage, version="%prog" + " %s" % basestation_version)

            # Common
            op.add_option("-c", "--config", dest="config",
                          help="script configuration file")
            op.add_option("--base_log", dest="base_log",
                          help="basestation log file, records all levels of notifications")
            op.add_option("--nice", dest="nice",
                          help="processing priority level (niceness)")


            if src in 'abdeghijkmnvpqt':
                op.add_option("-m", "--mission_dir", dest="mission_dir",
                              help="dive directory")
                op.add_option("--delete_upload_files", dest="delete_upload_files", action='store_true',
                              help="Delete any successfully uploaded input files")

            if src in 'abdeghijkmnvpqt':
                op.add_option("--magcalfile", dest="magcalfile",
                              help="compass cal file or search to use most recent version of tcm2mat.cal")
                op.add_option("--auxmagcalfile", dest="auxmagcalfile",
                              help="auxcompass cal file or search to use most recent version of scicon.tcm")

            if src in 'abcdfeghijklmnopqrstuz':
                op.add_option("-v", "--verbose", dest="verbose",
                              action="store_true",
                              help="print status messages to stdout")
                op.add_option("-q", "--quiet", dest="verbose",
                              action="store_false",
                              help="don't print status messages to stdout")
                op.add_option("--debug", dest="debug",
                              action="store_true",
                              help="log/display debug messages")

            if src in 'bdpqt':
                op.add_option("-i", "--instrument_id", dest="instrument_id",
                              help="force instrument (glider) id")
                op.add_option("--gzip_netcdf",
                              dest="gzip_netcdf",
                              action="store_true",
                              help="gzip netcdf files")

            if src in 'bdkpt':
                op.add_option("--profile",
                              dest="profile",
                              action="store_true",
                              help="Profiles time to process")


            if src in 'bm':
                op.add_option("--ver_65",
                              dest="ver_65",
                              action="store_true",
                              help="Processes Version 65 glider format")

            if src in 'bp':
                op.add_option("--bin_width",
                              dest="bin_width",
                              help="Width of bins")
                op.add_option("--which_half",
                              dest="which_half",
                              help="Which half of the profile to use - 1 down, 2 up, 3 both, 4 combine down and up")

            if src in 'i':
                op.add_option("--interval",
                              dest="interval",
                              help="Interval in seconds between checks")

            if src in 'bd':
                pass # was --dac_src

            if src in 'bij':
                op.add_option("--daemon", dest="daemon",
                              action="store_true",
                              help="Launch conversion as a daemon process")
                op.add_option("--ignore_lock",
                              dest="ignore_lock",
                              action="store_true",
                              help="Ignore the lock file, if present")
            if src in 'b':
                op.add_option("--divetarballs", dest="divetarballs",
                              #action="store_true",
                              help="Creates per-dive tarballs of processed files - 0 don't create, -1 create, > create fragments of specified size")
                op.add_option("--local", dest="local",
                              action="store_true",
                              help="Performs no remote operations (no .urls, .pagers, .mailer, etc.)")
                op.add_option("--clean",
                              dest="clean",
                              action="store_true",
                              help="Clean up (delete) intermediate files from working (mission) directory after processing.")
                op.add_option("--reply_addr",
                              dest="reply_addr",
                              help="Optional email address to be inserted into the reply to field email messages")
                op.add_option("--domain_name",
                              dest="domain_name",
                              help="Optional domain name to use for email messages")
                op.add_option("--web_file_location",
                              dest="web_file_location",
                              help="Optional location to prefix file locations in comp email messages")

            if src in 'bd':
                op.add_option("-f", "--force", dest="force",
                              action="store_true",
                              help="Forces conversion of all dives")
                op.add_option("--reprocess", dest="reprocess",
                              action="store_true",
                              help="Forces re-running of MakeDiveProfiles, regardless of file time stamps (generally used for debugging " \
                              "- normally --force is the right option)")
            if src in 'bd':
                op.add_option("--make_dive_profiles",
                              dest="make_dive_profiles",
                              action="store_true",
                              help="Create the common profile data products")
                op.add_option("--make_dive_pro",
                              dest="make_dive_pro",
                              action="store_true",
                              help="Create the dive profile in text format")
                op.add_option("--make_dive_bpo",
                              dest="make_dive_bpo",
                              action="store_true",
                              help="Create the dive binned profile in text format")
                op.add_option("--make_dive_netCDF",
                              dest="make_dive_netCDF",
                              action="store_true",
                              help="Create the dive netCDF output file")
                op.add_option("--make_mission_profile",
                              dest="make_mission_profile",
                              action="store_true",
                              help="Create mission profile output file")
                op.add_option("--make_mission_timeseries",
                              dest="make_mission_timeseries",
                              action="store_true",
                              help="Create mission timeseries output file")
                op.add_option("--make_dive_kkyy",
                              dest="make_dive_kkyy",
                              action="store_true",
                              help="Create the dive kkyy output files")
            if src in 'd':
                op.add_option("--reprocess_plots",
                              dest="reprocess_plots",
                              action="store_true",
                              help="Force reprocessing of plots (Reprocess.py only)")
                op.add_option("--reprocess_flight",
                              dest="reprocess_flight",
                              action="store_true",
                              help="Force reprocessing of flight model data (Reprocess.py only)")

            if src in 'c':
                op.add_option("--home_dir", dest="home_dir",
                              help="home directory base, used by Commission.py")
                op.add_option("--glider_password", dest="glider_password",
                              help="glider password, used by Commission.py")
                op.add_option("--glider_group", dest="glider_group",
                              help="glider group, used by Commission.py")
                op.add_option("--home_dir_group", dest="home_dir_group",
                              help="group owner for glider home directory, used by Commission.py")

            if src in 'm':
                op.add_option("-t", "--target_dir", dest="target_dir",
                              help="target directory, used by MoveData.py")

            if src in 'h':
                op.add_option("-e", "--encrypt", dest="encrypt", action="store_true",
                              help="encrypt the file")

            self._op = op

            (o, a) = op.parse_args()

            # handle the config file first, then see if any args trump them

            BaseOptions.make_dive_kkyy = False

            if o.config is not None:
                BaseOptions.config_file_name = os.path.abspath(os.path.expanduser(o.config))
                try:
                    cp.read(BaseOptions.config_file_name)
                except:
                    sys.stderr.write("ERROR parsing %s (%s)  - skipping..\n" % (BaseOptions.config_file_name, traceback.format_exc()))
                    BaseOptions.config_file_name = None
                else:
                    try:
                        debug = cp.get("DEFAULT", "debug")
                        BaseOptions.debug = (debug.lower() == "true")
                    except:
                        pass

                    try:
                        verbose = cp.get("DEFAULT", "verbose")
                        BaseOptions.verbose = (verbose.lower() == "true")
                    except:
                        pass

                    try:
                        force = cp.get("DEFAULT", "force")
                        BaseOptions.force = (force.lower() == "true")
                    except:
                        pass

                    try:
                        reprocess = cp.get("DEFAULT", "reprocess")
                        BaseOptions.reprocess = (reprocess.lower() == "true")
                    except:
                        pass

                    try:
                        local = cp.get("DEFAULT", "local")
                        BaseOptions.local = (local.lower() == "true")
                    except:
                        pass

                    try:
                        BaseOptions.divetarballs = cp.getint("DEFAULT", "divetarballs")
                    except:
                        pass

                    try:
                        daemon = cp.get("DEFAULT", "daemon")
                        BaseOptions.daemon = (daemon.lower() == "true")
                    except:
                        pass

                    try:
                        encrypt = cp.get("DEFAULT", "encrypt")
                        BaseOptions.encrypt = (encrypt.lower() == "true")
                    except:
                        pass

                    try:
                        BaseOptions.target_dir = cp.get("DEFAULT", "target_dir")
                        if BaseOptions.target_dir is not None:
                            if BaseOptions.target_dir[-1] != "/":
                                BaseOptions.target_dir = BaseOptions.target_dir + "/"
                            BaseOptions.target_dir = os.path.expanduser(BaseOptions.target_dir)
                    except:
                        pass

                    try:
                        BaseOptions.mission_dir = cp.get("DEFAULT", "mission_dir")
                        if BaseOptions.mission_dir is not None:
                            BaseOptions.mission_dir = os.path.abspath(os.path.expanduser(BaseOptions.mission_dir))
                            if BaseOptions.mission_dir[-1] != "/":
                                BaseOptions.mission_dir = BaseOptions.mission_dir + "/"
                    except:
                        pass

                    try:
                        BaseOptions.magcalfile = cp.get("DEFAULT", "magcalfile")
                    except:
                        pass

                    try:
                        BaseOptions.auxmagcalfile = cp.get("DEFAULT", "auxmagcalfile")
                    except:
                        pass

                    try:
                        BaseOptions.delete_upload_files = cp.get("DEFAULT", "delete_upload_files")
                    except:
                        pass

                    try:
                        BaseOptions.home_dir = cp.get("DEFAULT", "home_dir")
                    except:
                        pass
                    try:
                        BaseOptions.glider_password = cp.get("DEFAULT", "glider_password")
                    except:
                        pass
                    try:
                        BaseOptions.glider_group = cp.get("DEFAULT", "glider_group")
                    except:
                        pass
                    try:
                        BaseOptions.home_dir_group = cp.get("DEFAULT", "home_dir_group")
                    except:
                        pass

                    try:
                        BaseOptions.base_log = cp.get("DEFAULT", "base_log")
                    except:
                        pass

                    try:
                        BaseOptions.instrument_id = cp.get("DEFAULT", "instrument_id")
                    except:
                        pass

                    try:
                        make_dive_profiles = cp.get("DEFAULT", "make_dive_profiles")
                        BaseOptions.make_dive_profiles = (make_dive_profiles.lower() == "true")
                    except:
                        pass

                    try:
                        reprocess_plots = cp.get("DEFAULT", "reprocess_plots")
                        BaseOptions.reprocess_plots = (reprocess_plots.lower() == "true")
                    except:
                        pass

                    try:
                        reprocess_flight = cp.get("DEFAULT", "reprocess_flight")
                        BaseOptions.reprocess_flight = (reprocess_flight.lower() == "true")
                    except:
                        pass


                    try:
                        make_dive_pro = cp.get("DEFAULT", "make_dive_pro")
                        BaseOptions.make_dive_pro = (make_dive_pro.lower() == "true")
                    except:
                        pass

                    try:
                        make_dive_bpo = cp.get("DEFAULT", "make_dive_bpo")
                        BaseOptions.make_dive_bpo = (make_dive_bpo.lower() == "true")
                    except:
                        pass

                    try:
                        make_dive_netCDF = cp.get("DEFAULT", "make_dive_netCDF")
                        BaseOptions.make_dive_netCDF = (make_dive_netCDF.lower() == "true")
                    except:
                        pass

                    try:
                        make_mission_profile = cp.get("DEFAULT", "make_mission_profile")
                        BaseOptions.make_mission_netCDF = (make_mission_profile.lower() == "true")
                    except:
                        pass

                    try:
                        make_mission_timeseries = cp.get("DEFAULT", "make_mission_timeseries")
                        BaseOptions.make_mission_timeseries = (make_mission_timeseries.lower() == "true")
                    except:
                        pass

                    try:
                        make_dive_kkyy = cp.get("DEFAULT", "make_dive_kkyy")
                        if make_dive_kkyy.lower() == "true":
                            BaseOptions.make_dive_kkyy = True
                    except:
                        pass

                    try:
                        ver_65 = cp.get("DEFAULT", "ver_65")
                        BaseOptions.ver_65 = (ver_65.lower() == "true")
                    except:
                        pass

                    try:
                        clean = cp.get("DEFAULT", "clean")
                        BaseOptions.clean = (clean.lower() == "true")
                    except:
                        pass

                    try:
                        gzip_netcdf = cp.get("DEFAULT", "gzip_netcdf")
                        BaseOptions.gzip_netcdf = (gzip_netcdf.lower() == "true")
                    except:
                        pass

                    try:
                        profile = cp.get("DEFAULT", "profile")
                        BaseOptions.profile = (profile.lower() == "true")
                    except:
                        pass

                    try:
                        ignore_lock = cp.get("DEFAULT", "ignore_lock")
                        BaseOptions.igrore_lock = (ignore_lock.lower() == "true")
                    except:
                        pass

                    try:
                        BaseOptions.bin_width = cp.getfloat("DEFAULT", "bin_width")
                    except ValueError:
                        pass

                    try:
                        BaseOptions.which_half = WhichHalf(cp.getint("DEFAULT", "which_half")) #pylint: disable=E1120
                    except ValueError:
                        pass

                    try:
                        BaseOptions.interval = cp.getint("DEFAULT", "interval")
                    except ValueError:
                        pass

                    try:
                        BaseOptions.nice = cp.getint("DEFAULT", "nice")
                    except ValueError:
                        pass

                    try:
                        BaseOptions.reply_addr = cp.get("DEFAULT", "reply_addr")
                    except:
                        pass

                    try:
                        BaseOptions.domain_name = cp.get("DEFAULT", "domain_name")
                    except:
                        pass

                    try:
                        BaseOptions.web_file_location = cp.get("DEFAULT", "web_file_location")
                    except:
                        pass


                    #print "debug from config file: " + str(BaseOptions.debug) # DEBUG
                    #print "verbose from config file: " + str(BaseOptions.verbose) # DEBUG
                    #print "target_dir from config file: " + str(BaseOptions.target_dir) # DEBUG
                    #print "mission_dir from config file: " + str(BaseOptions.mission_dir) # DEBUG
                    #print "base_log from config file: " + str(BaseOptions.base_log) # DEBUG
                    #print "instrument_id from config file: " + str(BaseOptions.instrument_id) # DEBUG
                    #print "make_dive_profiles from config file: " + str(BaseOptions.make_dive_profiles) # DEBUG
                    #print "make_netCDF from config file: " + str(BaseOptions.make_netCDF) # DEBUG
                    #print "ver_65 from config file: " + str(BaseOptions.ver_65) # DEBUG
                    #print "clean from config file: " + str(BaseOptions.clean) # DEBUG
                    #print "profile from config file: " + str(BaseOptions.profile) # DEBUG
                    #print "ignore_locki from config file: " + str(BaseOptions.ignore_lock) # DEBUG
            if  getattr(o, 'debug', None) is not None:
                BaseOptions.debug = o.debug
                #print "debug from cmd-line options: " + str(o.debug) # DEBUG

            if getattr(o, 'verbose', None) is not None:
                BaseOptions.verbose = o.verbose
                #print "verbose from cmd-line options: " + str(o.verbose) # DEBUG

            if getattr(o, 'force', None) is not None:
                BaseOptions.force = o.force
                #print "force from cmd-line options: " + str(o.force) # DEBUG

            if getattr(o, 'reprocess', None) is not None:
                BaseOptions.reprocess = o.reprocess
                #print "reprocess from cmd-line options: " + str(o.reprocess) # DEBUG

            if getattr(o, 'divetarballs', None) is not None:
                try:
                    BaseOptions.divetarballs = int(o.divetarballs)
                except:
                    sys.stderr.write("divetarballs must be a int (%s)\n" % o.divetarballs)
                    BaseOptions.divetarballs = 0
                #print "divetarballs from cmd-line options: " + str(o.divetarballs) # DEBUG

            if getattr(o, 'local', None) is not None:
                BaseOptions.local = o.local
                #print "local from cmd-line options: " + str(o.local) # DEBUG

            if getattr(o, 'daemon', None) is not None:
                BaseOptions.daemon = o.daemon
                #print "daemon from cmd-line options: " + str(o.daemon) # DEBUG

            if getattr(o, 'encrypt', None) is not None:
                BaseOptions.encrypt = o.encrypt
                #print "encrypt from cmd-line options: " + str(o.encrypt) # DEBUG

            if getattr(o, 'target_dir', None) is not None:
                BaseOptions.target_dir = o.target_dir
                if BaseOptions.target_dir[-1] != "/":
                    BaseOptions.target_dir = BaseOptions.target_dir + "/"
                BaseOptions.target_dir = os.path.expanduser(BaseOptions.target_dir)
                #print "target_dir from cmd-line options: " + str(o.target_dir) # DEBUG

            if getattr(o, 'mission_dir', None) is not None:
                BaseOptions.mission_dir = os.path.abspath(os.path.expanduser(o.mission_dir))
                if BaseOptions.mission_dir[-1] != "/":
                    BaseOptions.mission_dir = BaseOptions.mission_dir + "/"
                #print "mission_dir from cmd-line options: " + str(o.mission_dir) # DEBUG

            if getattr(o, 'magcalfile', None) is not None:
                BaseOptions.magcalfile = o.magcalfile
                #print "magcalfle from cmd-line options: " + str(o.magcalfile) # DEBUG

            if getattr(o, 'auxmagcalfile', None) is not None:
                BaseOptions.auxmagcalfile = o.auxmagcalfile
                #print "auxmagcalfle from cmd-line options: " + str(o.auxmagcalfile) # DEBUG

            if getattr(o, 'delete_upload_files', None) is not None:
                BaseOptions.delete_upload_files = o.delete_upload_files
                #print "delete_upload_files from cmd-line options: " + str(o.delete_upload_files) # DEBUG

            if getattr(o, 'reply_addr', None) is not None:
                BaseOptions.reply_addr = o.reply_addr

            if getattr(o, 'domain_name', None) is not None:
                BaseOptions.domain_name = o.domain_name

            if getattr(o, 'web_file_location', None) is not None:
                BaseOptions.web_file_location = o.web_file_location

            if getattr(o, 'home_dir', None) is not None:
                BaseOptions.home_dir = o.home_dir
            if getattr(o, 'glider_password', None) is not None:
                BaseOptions.glider_password = o.glider_password
            if getattr(o, 'glider_group', None) is not None:
                BaseOptions.glider_group = o.glider_group
            if getattr(o, 'home_dir_group', None) is not None:
                BaseOptions.home_dir_group = o.home_dir_group

            if getattr(o, 'base_log', None) is not None:
                BaseOptions.base_log = o.base_log
                #print "base_log from cmd-line options: " + str(o.base_log) # DEBUG

            if getattr(o, 'instrument_id', None) is not None:
                BaseOptions.instrument_id = o.instrument_id
                #print "instrument_id from cmd-line options: " + str(o.instrument_id) # DEBUG

            if getattr(o, 'make_dive_profiles', None) is not None:
                BaseOptions.make_dive_profiles = o.make_dive_profiles
                BaseOptions.make_dive_netCDF = True
                #print "make_dive_profiles from cmd-line options: " + str(o.make_dive_profiles) # DEBUG

            if getattr(o, 'reprocess_plots', None) is not None:
                BaseOptions.reprocess_plots = o.reprocess_plots
                #print "reprocess_plots from cmd-line options: " + str(o.reprocess_plots) # DEBUG

            if getattr(o, 'reprocess_flight', None) is not None:
                BaseOptions.reprocess_flight = o.reprocess_flight
                #print "reprocess_flight from cmd-line options: " + str(o.reprocess_flight) # DEBUG

            if getattr(o, 'make_dive_pro', None) is not None:
                BaseOptions.make_dive_pro = o.make_dive_pro
                #print "make_pro from cmd-line options: " + str(o.make_pro) # DEBUG

            if getattr(o, 'make_dive_bpo', None) is not None:
                BaseOptions.make_dive_bpo = o.make_dive_bpo
                #print "make_bpo from cmd-line options: " + str(o.make_bpo) # DEBUG

            if getattr(o, 'make_dive_netCDF', None) is not None:
                BaseOptions.make_dive_netCDF = o.make_dive_netCDF
                #print "make_dive_netCDF from cmd-line options: " + str(o.make_netCDF) # DEBUG

            if getattr(o, 'make_mission_profile', None) is not None:
                BaseOptions.make_mission_profile = o.make_mission_profile
                #print "make_mission_profile from cmd-line options: " + str(o.make_netCDF) # DEBUG

            if getattr(o, 'make_mission_timeseries', None) is not None:
                BaseOptions.make_mission_timeseries = o.make_mission_timeseries
                #print "make_mission_timeseries from cmd-line options: " + str(o.make_netCDF) # DEBUG

            if getattr(o, 'make_dive_kkyy', None) is not None:
                BaseOptions.make_dive_kkyy = o.make_dive_kkyy
                #print "make_kkyy from cmd-line options: " + str(o.make_dive_kkyy) # DEBUG

            if getattr(o, 'ver_65', None) is not None:
                BaseOptions.ver_65 = o.ver_65
                #print "ver_65 from cmd-line options: " + str(o.ver_65) # DEBUG

            if getattr(o, 'clean', None) is not None:
                BaseOptions.clean = o.clean
                #print "clean from cmd-line options: " + str(o.clean) # DEBUG

            if getattr(o, 'gzip_netcdf', None) is not None:
                BaseOptions.gzip_netcdf = o.gzip_netcdf
                #print "gzip_netcdf from cmd-line options: " + str(o.no_gzip_netcdf) # DEBUG

            if getattr(o, 'profile', None) is not None:
                BaseOptions.profile = o.profile
                #print "profile from cmd-line options: " + str(o.profile) # DEBUG

            if getattr(o, 'ignore_lock', None) is not None:
                BaseOptions.ignore_lock = o.ignore_lock
                #print "ignore_lock from cmd-line options: " + str(o.ignore_lock) # DEBUG

            if getattr(o, 'bin_width', None) is not None:
                try:
                    BaseOptions.bin_width = float(o.bin_width)
                except:
                    sys.stderr.write("bin_width must be a float (%s)\n" % o.bin_width)
                    BaseOptions.bin_width = 0.0
                #print "bin_width from cmd-line options: %f" % BaseOptions.bin_width # DEBUG

            if getattr(o, 'which_half', None) is not None:
                try:
                    #pylint:disable:no-value-for-parameter
                    BaseOptions.which_half = WhichHalf(o.which_half) #pylint: disable=E1120
                except:
                    sys.stderr.write("which_half must be a int (%s)\n" % o.which_half)
                    #pylint:disable:no-value-for-parameter
                    BaseOptions.which_half = WhichHalf(3) #pylint: disable=E1120
                #print "which_half from cmd-line options: %d" % BaseOptions.which_half # DEBUG

            if getattr(o, 'interval', None) is not None:
                try:
                    BaseOptions.interval = int(o.interval)
                except:
                    sys.stderr.write("interval must be a int (%s)\n" % o.interval)
                    BaseOptions.interval = 0
                #print "interval from cmd-line options: %d" % BaseOptions.interval # DEBUG

            if getattr(o, 'nice', None) is not None:
                try:
                    BaseOptions.nice = int(o.nice)
                except:
                    sys.stderr.write("nice must be a int (%s)\n" % o.nice)
                    BaseOptions.nice = 0
                #print "nice from cmd-line options: %d" % BaseOptions.nice # DEBUG

            BaseOptions._opts = o
            BaseOptions._args = a

            BaseOptions.is_initialized = True

    def format_help(self):
        """ Returns help as a formatted string
        """
        formatter = optparse.IndentedHelpFormatter(indent_increment=4)
        formatter.indent()
        x = self._op.format_help(formatter)
        return x

    def get_args(self):
        """ Returns a copy of the list of arguments
        """
        return self._args.copy()
