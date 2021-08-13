#! /usr/bin/env python
# -*- python-fmt -*-

##
## Copyright (c) 2006, 2007, 2009, 2012, 2013, 2015, 2016, 2019, 2020, 2021 by University of Washington.  All rights reserved.
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

"""Extension for adding wind/rain estimates to netcdf files
"""

import cProfile
import pstats
import sys
import os
import time
import shutil
import collections
import numpy as np

import Utils
import BaseOpts
import MakeDiveProfiles
import Conf
import CalibConst
import QC
from BaseLog import log_critical, log_error, log_info, log_debug, BaseLogger
from windrain.SPL import pmar_spectrum_to_SPL
from windrain.wind import pmar_v2019_fun_SPL8kHz2wind
from windrain.rain import pmar_v2019_fun_SPL5kHz2rain

#import matplotlib
#matplotlib.use('MacOSX')
#import matplotlib.pyplot as plt

wind_rain_section = 'windrain'
wind_rain_default_dict = {'new_netcdf_file': [1, 0, 1]} # 1 to create a new netcdf file, 0 to update existing file

# Mapping of variables to be updated
name_pairs = collections.namedtuple('name_pairs', ['name', 'meta', 'qc'])
windrain_vars_metadata = collections.namedtuple('windrain_vars_metadata', ['spectra', 'spl', 'wind', 'rain', 'logavg_time', 'center_freqs'])

# TODO - expand to multi-channel and single channel PMAR combinations

# name_pairs with non-None metadata are always scrubbed from the output netcdf file
# before processing, so any failures are not propagated in the event the netcdf file is
# updated in place
windrain_vars = (windrain_vars_metadata(name_pairs('pmar_logavg_ch00_a', None, 'pmar_logavg_ch00_a_qc'),
                                        name_pairs('pmar_logavg_spl_ch00_a', {'description' : 'Sound Pressure Level down',
                                                                              'units' : 'dB re 1uPa'}, None),
                                        name_pairs('pmar_logavg_wind_ch00_a', {'description' : 'Wind speed down', 'units' : 'm/s'}, None),
                                        name_pairs('pmar_logavg_rain_ch00_a', {'description' : 'Rain rate down', 'units' : 'mm/hr'}, None),
                                        name_pairs('pmar_logavg_time_ch00_a', None, None),
                                        name_pairs('pmar_logavg_ch00_a_center_freqs', None, None)),
                 windrain_vars_metadata(name_pairs('pmar_logavg_ch00_b', None, 'pmar_logavg_ch00_b_qc'),
                                        name_pairs('pmar_logavg_spl_ch00_b', {'description' : 'Sound Pressure Level up',
                                                                              'units' : 'dB re 1uPa'}, None),
                                        name_pairs('pmar_logavg_wind_ch00_b', {'description' : 'Wind speed down', 'units' : 'm/s'}, None),
                                        name_pairs('pmar_logavg_rain_ch00_b', {'description' : 'Rain rate down', 'units' : 'mm/hr'}, None),
                                        name_pairs('pmar_logavg_time_ch00_b', None, None),
                                        name_pairs('pmar_logavg_ch00_b_center_freqs', None, None)))

param_defaults = {
    "windrain_SPL_offset_value": 0,
    "windrain_wind_slope": -15.7,
    "windrain_slope_div": 1,
    "windrain_var_div": 5,
    "windrain_min_wind": 2.5,
    'pmar_hphone_sens_ch00': 0,
    'pmar_hphone_sens_ch01': 0,
    }

def add_variable(ncf, name, value, typecode, dimensions, meta_data):
    """ Adds a new variable to a netcdf files
    Input:
        ncf - open for writing netcdf file
        name - new varible name
        value - numpy array for new value (no singletons)
        typecode - type of variable
        dimensions - tuple of names of dimensions as strs.  N.B. - dimensions must already exist
        meta_data - dictionary, where keys are the arrtibutes and values are the attribute values
    """
    new_var = ncf.createVariable(name, typecode, dimensions)
    new_var[:] = value
    for k, v in list(meta_data.items()):
        setattr(new_var, k, v)

#pylint: disable=unused-argument
def main(instrument_id=None, base_opts=None, sg_calib_file_name=None, dive_nc_file_names=None, nc_files_created=None,
         processed_other_files=None, known_mailer_tags=None, known_ftp_tags=None, processed_file_names=None):
    """Basestation extension for adding wind/rain estimates to netcdf files

    Returns:
        0 for success (although there may have been individual errors in
            file processing).
        Non-zero for critical problems.

    Raises:
        Any exceptions raised are considered critical errors and not expected
    """
    if base_opts is None:
        base_opts = BaseOpts.BaseOptions(sys.argv, 'g',
                                         usage="%prog [Options] ")
    BaseLogger("WindRain", base_opts) # initializes BaseLog

    args = base_opts.get_args() # positional arguments

    log_info("Started processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))

    if(not base_opts.mission_dir and len(args) == 1):
        dive_nc_file_names = [os.path.expanduser(args[0])]
        mission_dir, _ = os.path.split(dive_nc_file_names[0])
        if sg_calib_file_name is None:
            sg_calib_file_name = os.path.join(mission_dir, "sg_calib_constants.m")
    else:
        if nc_files_created is not None:
            dive_nc_file_names = nc_files_created
        elif not dive_nc_file_names:
            # Collect up the possible files
            dive_nc_file_names = MakeDiveProfiles.collect_nc_perdive_files(base_opts)
        if sg_calib_file_name is None:
            sg_calib_file_name = os.path.join(base_opts.mission_dir, 'sg_calib_constants.m')

    # Get processing parameters
    calib_consts = CalibConst.getSGCalibrationConstants(sg_calib_file_name)
    if not calib_consts:
        log_error("Could not process %s" % sg_calib_file_name)
        return 1

    params = {}
    for p in list(param_defaults.keys()):
        if p in list(calib_consts.keys()):
            params[p] = calib_consts[p]
        elif param_defaults[p] is None:
            log_error("%s must be specificed in sg_calib_constants - bailing out")
            return 1
        else:
            params[p] = param_defaults[p]

    wind_rain_conf = Conf.conf(wind_rain_section, wind_rain_default_dict)
    if wind_rain_conf.parse_conf_file(base_opts.config_file_name) > 2:
        log_error("Count not process %s - continuing with defaults" % base_opts.config_file_name)
    wind_rain_conf.dump_conf_vars()

    for dive_nc_file_name in dive_nc_file_names:
        log_info("Processing %s" % dive_nc_file_name)

        netcdf_in_filename = dive_nc_file_name
        head, _ = os.path.splitext(netcdf_in_filename)
        netcdf_out_filename = "%s_windrain.ncf" % (head)

        if not os.path.exists(netcdf_in_filename):
            sys.stderr.write("File %s does not exists\n" % netcdf_in_filename)
            break

        try:
            nci = Utils.open_netcdf_file(netcdf_in_filename, 'r', mmap=False)
        except:
            log_error("Could not open %s - skipping" % netcdf_in_filename, 'exc')
            break

        # Check for the needed variables and columns
        # N.B. - Currently only support PMARXL single channel
        if params['pmar_hphone_sens_ch00'] != 0.:
            hphone_sens_db = params['pmar_hphone_sens_ch00']
        else:
            try:
                hphone_sens_db = nci.variables['pmar_hphone_sens_ch00'].getValue()
            except KeyError:
                log_error("pmar_hphone_sens_ch00 not found in netcdf for sg_calib_constants.m  - skipping")
                break
        try:
            gain_stage_db = nci.variables['pmar_gain0_ch00'].getValue() + nci.variables['pmar_gain1_ch00'].getValue()
        except:
            log_error('Error fetching gain vaules - skipping', 'exc')
            break

        log_info("Output file = %s" % (netcdf_out_filename if wind_rain_conf.new_netcdf_file else netcdf_in_filename))

        nco = Utils.open_netcdf_file(netcdf_out_filename, 'w', False)

        # Dup the original file
        for d in list(nci.dimensions.keys()):
            nco.createDimension(d, nci.dimensions[d])

        for v in list(nci.variables.keys()):
            # Pretty hairy list comprehension - builds a list of all posible names
            # with non-None metadata
            if v not in [y.name for x in windrain_vars for y in x if y.meta]:
                nco.variables[v] = nci.variables[v]

        #pylint: disable=protected-access
        for a in list(nci._attributes.keys()):
            nco.__setattr__(a, nci._attributes[a])

        for v in windrain_vars:
            # Collect the needed variables
            try:
                spectra = nci.variables[v.spectra.name][:].copy()
                spectra_qc = QC.decode_qc(nci.variables[v.spectra.qc][:])
                logavg_time_var = nci.variables[v.logavg_time.name]
                logavg_time = logavg_time_var[:]
            except KeyError:
                log_info("Cannot find needed variable - skipping", 'exc')
                break

            # Spectra to spl
            spl = pmar_spectrum_to_SPL(spectra, gain_stage_db, hphone_sens_db)

            add_variable(nco, v.spl.name, spl, nci.variables[v.spectra.name].typecode(), nci.variables[v.spectra.name].dimensions, v.spl.meta)

            spectra_qc = np.tile(spectra_qc, (np.shape(spectra)[1], 1)).transpose()

            spl[spectra_qc != 1] = 0.

            # TODO - spl offset value from calib_constants
            # spl -= calib_constants_spl_offset

            # Wind/Rain

            # Compute the mean slope between 1 kHz and 50 kHz  (in loglog space),
            # and the variance relative to that slope, for each estimate.

            log_debug('calculating initial slope fit')

            linear_fit = spl * np.nan
            linear_fit_P = np.zeros((len(logavg_time), 2)) * np.nan
            #var_linear_fit = list(logavg_time * np.nan)
            var_linear_fit = np.zeros(len(logavg_time)) * np.nan

            freqs = nci.variables[v.center_freqs.name][:]
            freq_log = np.log10(freqs)
            index = np.logical_and(freqs >= 0.9e3, freqs <= 50e3)
            band_width = max(freqs[index]) - min(freqs[index]) # bandwidth in Hz.

            # Calculate SPL_05, SPL_08, SPL_21
            SPL = {}
            ff = [5.4, 8.3, 20.51] # kHz
            df = 1.5 # kHz
            for kk in range(len(ff)):
                ii = np.logical_and(freqs/1000. >= ff[kk] - df/2., freqs/1000. <= ff[kk] + df/2.)
                tmp_spl = np.zeros(len(logavg_time))
                for jj in range(len(tmp_spl)):
                    tmp_spl[jj] = np.nanmean(spl[jj, ii])
                SPL['%02.0f' % ff[kk]] = tmp_spl
                # This didn't do it.
                #SPL['%02.0f' % ff[kk]] = np.nanmean(spl[:,ii])

            for index_ensemble in range(len(logavg_time)):
                # Fit the mean SP(1 to 50k)
                P = np.polyfit(freq_log[index], spl[index_ensemble, index], 1)
                linear_fit_P[index_ensemble, :] = P
                linear_fit[index_ensemble] = np.polyval(P, freq_log)

                # calcuate the variance of the difference (over the same range of frequencies)
                spl_diff = spl[index_ensemble, :] - linear_fit[index_ensemble]
                var_linear_fit[index_ensemble] = np.trapz(freqs[index], np.power(spl_diff[index], 2))/band_width

            # Histogram of the differences...
            #plt.hist(var_linear_fit, bins=51, density=1)
            #plt.title("")
            #plt.show()

            # Wind Reference
            # TODO - Specify and import the wind reference here

            # Wind
            log_debug("Wind")
            # wind flag:
            # 1 => small variance relative to linear fit and more than  1.1 of noise floor
            # 2 => slope close to expected value and more than  1.1 of noise floor
            # 3 => small variance relative to linear fit and slope close to expected value and more than  1.1 of noise floor
            #       ********* really trust only wind_flag==3

            # Wind: mostly a linear fit, and slope is close to param.wind_slope.
            pmar_wind = pmar_v2019_fun_SPL8kHz2wind(SPL['08'])
            pmar_wind_flag = np.zeros(len(pmar_wind))
            pmar_wind_flag[np.logical_and(var_linear_fit <= params['windrain_var_div'], pmar_wind > params['windrain_min_wind'])] = 1

            #pylint: disable=no-member
            pmar_wind_flag[np.logical_and.reduce((linear_fit_P[:, 0] >= params['windrain_wind_slope'] - params['windrain_slope_div'],
                                                  linear_fit_P[:, 0] <= params['windrain_wind_slope'] + params['windrain_slope_div'],
                                                  pmar_wind > params['windrain_min_wind']))] = 2
            pmar_wind_flag[np.logical_and.reduce((var_linear_fit <= params['windrain_var_div'],
                                                  linear_fit_P[:, 0] >= params['windrain_wind_slope'] - params['windrain_slope_div'],
                                                  linear_fit_P[:, 0] <= params['windrain_wind_slope'] + params['windrain_slope_div'],
                                                  pmar_wind > params['windrain_min_wind']))] = 3
            #pylint: enable=no-member

            # For now, elinate all non-3 wind estimates - good plan, or propagate and plot with overlay to indicate the
            # nature of the estimate in the plot?
            pmar_wind[pmar_wind_flag != 3] = np.nan

            add_variable(nco, v.wind.name, pmar_wind, 'd', logavg_time_var.dimensions, v.wind.meta)

            # Rain
            log_debug("Rain")
            # rain flag:
            # 1 => SPL21kHz > 194 - 2.34 * SPL5.4khz)
            # 2 => SPL21kHz > 48dB and SPL5.4khz > 53dB
            # 3 => Drizzle: SPL21kHz > 44 and SPL21kHz > 14 + 0.7 * SPL8.3kHz;
            #       ********* trust rain_flag > 0

            pmar_rain_flag = np.zeros(len(pmar_wind))
            #### Rain Detection

            # SPL21kHz > 194 - 2.34 * SPL5.4khz)
            pmar_rain_flag[SPL['21'] > (194 - 2.35 * SPL['05'])] = 1

            # SPL21kHz > 48dB and SPL5.4khz > 53dB
            pmar_rain_flag[np.logical_and(SPL['21'] > 48, SPL['05'] > 53)] = 2
            #### Drizzle detection algorithm

            # Drizzle: SPL21kHz > 44 and SPL21kHz > 14 + 0.7 * SPL8.3kHz;
            pmar_rain_flag[np.logical_and(SPL['21'] > 44, SPL['21'] > (14 + 0.7 * SPL['08']))] = 3

            pmar_rain = pmar_v2019_fun_SPL5kHz2rain(SPL['05'])
            pmar_rain[pmar_rain_flag == 0] = np.nan

            add_variable(nco, v.rain.name, pmar_rain, 'd', logavg_time_var.dimensions, v.rain.meta)

        nci.close()
        nco.sync()
        nco.close()

        if not wind_rain_conf.new_netcdf_file:
            shutil.move(netcdf_out_filename, netcdf_in_filename)

        if processed_other_files is not None:
            if wind_rain_conf.new_netcdf_file:
                processed_other_files.append(netcdf_out_filename)
            else:
                if netcdf_in_filename not in processed_other_files:
                    processed_other_files.append(netcdf_in_filename)

    log_info("Finished processing " + time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time())))
    return 0

if __name__ == "__main__":
    retval = 1

    # Force to be in UTC
    os.environ['TZ'] = 'UTC'
    time.tzset()

    try:
        if "--profile" in sys.argv:
            sys.argv.remove('--profile')
            profile_file_name = os.path.splitext(os.path.split(sys.argv[0])[1])[0] + '_' \
                + Utils.ensure_basename(time.strftime("%H:%M:%S %d %b %Y %Z", time.gmtime(time.time()))) + ".cprof"
            # Generate line timings
            retval = cProfile.run("main()", filename=profile_file_name)
            stats = pstats.Stats(profile_file_name)
            stats.sort_stats('time', 'calls')
            stats.print_stats()
        else:
            retval = main()
    except Exception:
        log_critical("Unhandled exception in main -- exiting")

    sys.exit(retval)
