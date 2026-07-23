%%% Establishes glider calibration constants.

%%% This file is an example as well as documentation.
%%% Lines prefixed with a single % are disabled parameters - the nominal/default
%%% value is on the right hand side; delete the leading "% " to enable.
%%% Lines prefixed with %%% (like this one) are explanations only, not parameters.
%%% Note - this file MUST be changed apprpriately for your vehicle and mission

%%% REQUIRED
id_str = '000';

%%% REQUIRED
mission_title ='No Mission Specified';

%%% REQUIRED
mass = 52.173; % (kg) scale weight

%%% Optional - mass (kg) of compressee (e.g. syntactic foam) ballast added to the
%%% vehicle, separate from the scale weight above. Default 0 (no compressee); used
%%% in FlightModel buoyancy calculations. Values greater than 20 are assumed to be
%%% a grams/kg data-entry mistake and are auto-corrected.
% mass_comp = 0;

%%% Optional - overall vehicle configuration, drives defaults for CT type/geometry
%%% and vehicle/sensor geometry constants below. 0=stock SG w/ original CT mount,
%%% 1=stock SG w/ gun-style CT, 2=DeepGlider, 3=stock SG w/ pumped GPCTD, 4=Oculus.
%%% Normally inferred automatically from id_str and log_deepglider; only set this
%%% if that inference is wrong for your vehicle.
% sg_configuration = 0;

%%% Optional - WMO id assigned to this deployment, if any (e.g. 'a8xx1234'; may be
%%% preceded with 'Q' if data may go to TESAC, hence the string requirement)
% wmo_id = '';

%%% Correction factor to apply to truck depth to compensate for data with incorrect pressure slope
%%% Only change this if you are sure your dataset has this issue
% depth_slope_correction = 1.0;

%%% Smooth the truck (main pressure sensor) pressure/depth signal using a
%%% median + Savitzky-Golay hybrid filter. Set to 1 to enable. This also feeds
%%% forward into salinity/density/sound-velocity corrections and FlightModel
%%% fits, not just the displayed depth/pressure - the pre-processing signal is
%%% preserved as the pressure_raw netCDF variable.
% smooth_truck_pressure = 0;
% smooth_truck_pressure_window_secs = 42.0;
% smooth_truck_pressure_polyorder = 3;

%%% Rather than hand-tuning depth_slope_correction, name an existing netCDF
%%% pressure variable here (e.g. ad2cp_pressure, from an AD2CP ADCP) to treat as
%%% ground truth; a depth_slope_correction will be auto-fit against it (applied
%%% after smooth_truck_pressure, if that is also enabled). Ignored if
%%% depth_slope_correction is explicitly set above - that always wins.
% depth_slope_correction_gold_standard = 'ad2cp_pressure';

%%% NOTE:
%%% FlightModel will supply
%%%
%%%  volmax, vbdbias, hd_a, hd_b, hd_c, hd_s, rho0, abs_compress, therm_expan, temp_ref
%%%
%%% ignoring any settings here and issue a warning, unless
%%% --skip_flight_model is set, in which case processing will use these
%%% variables. To suppress warnings about these variables, insert FM_ignore anywhere in a comment on the same
%%% line as the variable
%%%
%%% The commented values below are nominal defaults for a stock Seaglider
%%% (from FlightModel.get_FM_defaults()), shown for reference - they are not
%%% used unless --skip_flight_model is set and the lines are uncommented.
% volmax = 51436.6; % [cc] hull displaced volume at neutral buoyancy (vehicle-specific; derived from mass/rho0)
% vbdbias = 0.0; % [cc] VBD bias/offset
% hd_a = 3.548133892336e-03; % [1/deg] lift coefficient
% hd_b = 1.1220184543020e-02; % drag coefficient
% hd_c = 5.7e-06; % [1/deg^2] induced drag coefficient
% hd_s = -0.25; % dimensionless hydrodynamic shape scaling factor (Hubbard 1990)
% rho0 = 1027.5; % [kg/m^3] reference seawater density
% abs_compress = 4.1e-06; % [m^3/dbar] hull compressibility
% therm_expan = 7.05e-05; % [m^3/degC] hull thermal expansion
% temp_ref = 15.0; % [degC] typical temperature where ballasted

%%%
%%% Parms affecting basestation processing
%%%
%%% The allowable horizontal position error (HPE) in GPS fixes.  GPS fixes with measured HPE values greater
%%% then this value are not usable in surface dift and/or depth averaged current calculations
% GPS_position_error = 100;

%%% Use the aux pressure sensor over the truck pressure sensor, if present (default on)
% use_auxpressure = 1;
%%% Use the aux compass over the truck compass, if present (default off)
% use_auxcompass = 0;
%%%

%%%
%%% Sensor bias corrections - apply only if you have independent evidence
%%% (e.g. bench comparison, post-mission validation) that a sensor is offset
%%%
% depth_bias = 0; % [m] depth bias because of a flakey or mis-tared pressure sensor
% cond_bias = 0; % [S/m] conductivity bias
% temp_bias = 0; % [deg C] temperature bias
% pitchbias = 0; % [deg] pitch sensor bias
% rollbias = 0; % [deg] roll sensor bias
%%%

%%%
%%% Quality control (QC) bounds - control the standard basestation QC tests.
%%% Defaults below follow Carnes, 'Lager Manual v1.0' (2008) and Schmid, et al.,
%%% 'The Real-Time Data Management System for Argo Profiling Float Observations'
%%% (JAOT 2007). Rarely need changing.
%%%
% QC_bound_action = 4; % QC_BAD - what QC to assert when a bound is exceeded
% QC_spike_action = 8; % QC_INTERPOLATED - what QC to assert when a spike is detected
% QC_temp_min = -2.5; % [deg C]
% QC_temp_max = 43.0; % [deg C]
% QC_temp_spike_depth = 500.0; % [m] depth separating shallow/deep spike tests
% QC_temp_spike_shallow = 0.05; % [deg C/m] allowable temperature spike above QC_temp_spike_depth
% QC_temp_spike_deep = 0.01; % [deg C/m] allowable temperature spike below QC_temp_spike_depth
% QC_cond_min = 0.0; % [S/m]
% QC_cond_max = 10.0; % [S/m]
% QC_cond_spike_depth = 500.0; % [m] depth separating shallow/deep spike tests
% QC_cond_spike_shallow = 0.006; % [S/m/m] allowable conductivity spike above QC_cond_spike_depth
% QC_cond_spike_deep = 0.001; % [S/m/m] allowable conductivity spike below QC_cond_spike_depth
% QC_salin_min = 19.0; % [PSU]
% QC_salin_max = 45.0; % [PSU]
% QC_overall_ctd_percentage = 0.3; % maximum fraction of CTD data that can be QC_BAD
% QC_overall_speed_percentage = 0.2; % minimum fraction of good speeds needed to trust HDM speeds
%%%

%%%
%%% Vehicle and sensor geometry (advanced) - normally derived automatically from
%%% sg_configuration above; only override individual values here for a
%%% non-standard build. Values below are for a stock Seaglider (sg_configuration=0).
%%%
% glider_length = 0; % [m] supplied by FlightModel; see NOTE above
% glider_interstitial_length = 0.2; % [m]
% glider_interstitial_volume = 12e-3; % [m^3]
% glider_r_en = 0.00635; % [m] entry radius
% glider_wake_entry_thickness = 0.0; % [m]
% glider_vol_wake = 18e-3; % [m^3] attached wake volume
% glider_r_fair = 0.3; % [m] fairing radius
% glider_xT = -1.1800; % [m] glider x coord of thermistor tip
% glider_zT = 0.1700; % [m] glider z coord of thermistor tip
% glider_xP = -0.6870; % [m] glider x coord of pressure gauge
% glider_zP = -0.0254; % [m] glider z coord of pressure gauge

%%% Sparton compass pitch/roll correction coefficients (optional, rarely used -
%%% only needed to invert a correction already applied onboard)
% sparton_pitch0 = 0.0;
% sparton_pitch1 = 0.0;
% sparton_pitch2 = 0.0;
% sparton_pitch3 = 0.0;
% sparton_roll0 = 0.0;
% sparton_roll1 = 0.0;
% sparton_roll2 = 0.0;
% sparton_roll3 = 0.0;
%%%

%%%
%%% Seabird un-pumped CT
%%%

%%% REQUIRED - use the correct values from the Seabird cal sheet

% calibcomm = 'SBE s/n 0041, calibration 25 April 2006';
% t_g =  4.37369092e-03 ;
% t_h =  6.48722213e-04 ;
% t_i =  2.63414771e-05 ;
% t_j =  2.83524759e-06 ;
% c_g = -9.97922732e+00 ;
% c_h =  1.12270684e+00 ;
% c_i = -2.35632554e-03 ;
% c_j =  2.37469252e-04 ;
% cpcor = -9.57e-08 ;
% ctcor =  3.25e-06 ;

%%% Optional - if installed, use the adcp's pressure sensor instead of the truck pressure sensor
%%% as the basis of ctd_pressure
% use_adcppressure = 0;

%%% CT cell/sail geometry constants (advanced) - normally derived automatically
%%% from sg_configuration/sg_ct_type above; only override for a non-standard
%%% CT mount. Values below are for a stock unpumped SBE41 with the original CT sail.
% sbect_tau_T = 0.6; % [s] thermistor response, from SBE
% sbect_x_m = 0.0087; % [m] length of mouth portion of cell
% sbect_r_m = 0.0081; % [m] radius of mouth portion of cell
% sbect_cell_length = 0.09; % [m] combined length of narrow (sample) portions of cell
% sbect_x_w = 0.0386; % [m] length of wide portion of cell
% sbect_r_w = 0.0035; % [m] radius of wide portion of cell
% sbect_r_n = 0.002; % [m] radius of narrow portion of cell
% sbect_x_T = -0.014; % [m] cell mouth to thermistor x offset
% sbect_z_T = -0.015; % [m] cell mouth to thermistor z offset
% sbect_C_d0 = 1.2; % cell mouth drag coefficient

%%%
%%% Seabird pumped CTD (payload CTD/GPCTD)
%%%

%%% The following is to address the case where the GPCTD clock
%%% is not being set by the Seaglider at the start of the profile,
%%% is running while the GPCTD is on and the clock is latched over the power off/on.
%%%
%%% If all the GPCTD payload data times are outside the time range of the glider's
%%% dive time range, all the GPCTD times are adjusted so the first GPCTD time is the
%%% start of the glider's dive time. This correction won't work (or work very well)
%%% if only the up profile is being sampled and is dependent on what looks like
%%% the way the Kongsberg Seaglider code works - to run the GPCTD through the dive,
%%% apogee and up to the start of the

% gpctd_align_start_time = 1;

%%%
%%% Seabird SBE43 dissolved oxygen
%%%

%%% Use the correct values from the SBE43 cal sheet. comm_oxy_type identifies the
%%% sensor variant, e.g. 'SBE_43f' or 'Pumped_SBE_43f' (also shared with the
%%% Aanderaa optode sections below, where it takes a value like 'AA4330').
% calibcomm_oxygen = 'SBE43 s/n 0041, calibration 25 April 2006';
% comm_oxy_type = 'SBE_43f';
% Soc = 0.0;
% Foffset = 0.0;
% A = 0.0; % Bittig temperature-correction coefficient
% B = 0.0; % Bittig temperature-correction coefficient
% C = 0.0; % Bittig temperature-correction coefficient
% E = 0.0; % Bittig pressure-correction coefficient
% o_a = 0.0; % Owens-Millard coefficient
% o_b = 0.0; % Owens-Millard coefficient
% o_c = 0.0; % Owens-Millard coefficient
% o_e = 0.0; % Owens-Millard pressure coefficient
% Tau20 = 0.0; % sensor time constant at 20C, 1 atm, 0 PSU
% D1 = 0.0; % compensation coefficient
% D2 = 0.0; % compensation coefficient
% Boc = 0.0; % oxygen signal slope (alternate/legacy form)
%%% NOTE: "Pcor" (lowercase, below) is the SBE43 pressure correction coefficient.
%%% It is unrelated to the legacy mixed-case "PCor" flag some old
%%% sg_calib_constants.m files used to select an SBE43 correction style - that
%%% flag is deprecated and should not be set in new files.
% Pcor = 0.0;
% Tcor = 0.0; % temperature correction coefficient
% Voffset = 0.0; % voltage offset (unused)

%%%
%%% Legato CTD
%%%

%%% Required
% sg_ct_type = 4;  % Indicates a legato CTD

% calibcomm = 'Legato s/n 0041, calibration 25 April 2016';

%%% Required for Legato as logdev or on the truck
% legato_sealevel = 10082.0; % Where this is sealevel presure setting.

%%% Set to 1 to use the Seaglider pressure sensor for CTD corrections
% legato_use_truck_pressure = 0;

%%% Set to 0 to disable the basestation conductivity pressure correction, in favor of the on in the instrument
%%% On board correction is applied when X2, X3 and X4 are non-zero (see metadata capture from a selftest)
%%% See RBR document "0013279revA Conductivity pressure correction for RBRlegato3 with RBR#0007155 top.pdf"
% legato_cond_press_correction = 1;

%%% For Kongsberg/HII gliders with legato as a logdev device
% legato_config=191;

%%% where the values to be logical or'd together are
%%% channel			flag
%%% -----------------------------------
%%% conductivity      0x01        1
%%% temperature       0x02        2
%%% pressure          0x04        4
%%% sea pressure      0x08        8
%%% depth             0x10        16
%%% salinity          0x20        32
%%% counts            0x40        64
%%% cond cell temp    0x80       128

%%% Misc legato settings

%%% ignore any legato columns from the truck
% ignore_truck_legato = 1;

%%%
%%% RBR tridente
%%%

%%% The correct form of this parameter is generated by running
%%%    /opt/basestation/bin/python /usr/local/basestation3/tools/GetTridenteChannels.py <selftest>
%%% where selftest is a selftest capture file that contains the tridente meta data.

%%% This parameter is only used to annotate tridente plots
% calibcomm_tridentebb700bb470chla470='RBRtridente serialnum:238008 backscatter_00:2025-03-12T13:01:47Z backscatter_01:2025-03-12T13:06:10Z chlorophyll_00:2025-03-11T12:40:47Z';

%%%
%%% RBR codaTODO
%%%

%%% The correct form of the parameters below are generated by running
%%%    /opt/basestation/bin/python /usr/local/basestation3/tools/GetCodaMeta.py <selftest>
%%% where selftest is a selftest capture file that contains the CODA meta data.

%%% This parameter is only used to annotate coda plots.
% calibcomm_codaTODO='RBRcoda serialnum:237923 temp15:2025-03-15T13:54:16Z doxy24:2025-03-20T11:35:41Z opt_05:2025-03-03T14:18:09Z';

%%% This parameter is used to calculate an additional compensater O2 vector (in addtion to the one reported by the instrument) using corrected salinity from the CTD.  See /usr/local/basesation3/Sensors/coda_ext.py for further details.
% codaTODO_c0=32.000000e-006;

%%%
%%% Aanderaa 3830 Optode (older sensor variant - a vehicle has either a 3830 or
%%% a 4330/4831, not both; use this section OR the "Aanderaa Optode" section
%%% below, not both)
%%%

% calibcomm_optode = 'Optode 3830 SN: 000  CAL: 31-Feb-2014';
%%% Stern-Volmer coefficient matrix (5x4), from the AA3830 cal sheet
% optode_C00Coef = 0.1;
% optode_C01Coef = 0.1;
% optode_C02Coef = 0.1;
% optode_C03Coef = 0.1;
% optode_C10Coef = 0.1;
% optode_C11Coef = 0.1;
% optode_C12Coef = 0.1;
% optode_C13Coef = 0.1;
% optode_C20Coef = 0.1;
% optode_C21Coef = 0.1;
% optode_C22Coef = 0.1;
% optode_C23Coef = 0.1;
% optode_C30Coef = 0.1;
% optode_C31Coef = 0.1;
% optode_C32Coef = 0.1;
% optode_C33Coef = 0.1;
% optode_C40Coef = 0.1;
% optode_C41Coef = 0.1;
% optode_C42Coef = 0.1;
% optode_C43Coef = 0.1;

%%%
%%% Aanderaa Optode
%%%

%%% The parameters needed to correct the aanderaa optode output can be obtained by running
%%%    /opt/basestation/bin/python /usr/local/basestation3/tools/GetOptodeConstants.py <selftest>
%%% where selftest is a selftest capture file that contains the aanderaa optode meta data.

% calibcomm_optode = ''Optode 4831 SN: 940  Foil ID: 1824M calibrated 03-12-2020'';

% optode_PhaseCoef0 = -2.734;
% optode_PhaseCoef1 = 1;
% optode_PhaseCoef2 = 0;
% optode_PhaseCoef3 = 0;
% optode_ConcCoef0 = 0;
% optode_ConcCoef1 = 1;
% optode_FoilCoefA0 = -2.67928e-06;
% optode_FoilCoefA1 = -7.4836e-06;
% optode_FoilCoefA2 = 0.00196001;
% optode_FoilCoefA3 = -0.207285;
% optode_FoilCoefA4 = 0.000601246;
% optode_FoilCoefA5 = -6.60427e-07;
% optode_FoilCoefA6 = 11.1802;
% optode_FoilCoefA7 = -0.0514806;
% optode_FoilCoefA8 = 6.8985e-05;
% optode_FoilCoefA9 = 8.46501e-07;
% optode_FoilCoefA10 = -314.351;
% optode_FoilCoefA11 = 2.05112;
% optode_FoilCoefA12 = -0.00298703;
% optode_FoilCoefA13 = -4.44977e-06;
% optode_FoilCoefB0 = -1.86135e-06;
% optode_FoilCoefB1 = 3814.9;
% optode_FoilCoefB2 = -32.2281;
% optode_FoilCoefB3 = -0.1678;
% optode_FoilCoefB4 = 0.0189482;
% optode_FoilCoefB5 = -0.000690143;
% optode_FoilCoefB6 = 1.04269e-05;
% optode_FoilCoefB7 = 0;
% optode_FoilCoefB8 = 0;
% optode_FoilCoefB9 = 0;
% optode_FoilCoefB10 = 0;
% optode_FoilCoefB11 = 0;
% optode_FoilCoefB12 = 0;
% optode_FoilCoefB13 = 0;
% optode_SVU_enabled = 1;
% optode_SVUCoef0 = 0.00276388;
% optode_SVUCoef1 = 0.00011389;
% optode_SVUCoef2 = 2.47865e-06;
% optode_SVUCoef3 = 166.347;
% optode_SVUCoef4 = -0.263223;
% optode_SVUCoef5 = -37.8607;
% optode_SVUCoef6 = 3.37836;

%%%
%%% Johnson, Plant, Riser, Gilbert. 'Air oxygen calibration of oxygen optodes on a profiling float array'
%%% submitted, Journal of Atmospheric and Oceanic Technology 2015
%%% The optode apparently drifts from its calibration when exposed to air but then stops drifting in (sea)water.
%%% Investigation shows this is captured by a gain rather
%%% than additive drift, that is, the drift is proportional to the O2 signal. Johnson et al. compute the gain
%%% by comparing the output of the sensor in air with the expected
%%% O2 concentration given temperature and pressure.
%%%
%%% These parameter are not supplied by the above tool
% optode_st_temp = 10.723; % From selftest capture
% optode_st_calphase = 30.826; % From selftest capture
% optode_st_slp = 1008.3; % From local observation

%%%
%%% VELO
%%%

% velo_A = 0.0;
% velo_B = 0.0;

%%%
%%% Wetlabs
%%%

%%% iRobot/Kongsberg/HII followed differnt naming conventions for wetlabs column names.  If wetlabs data is to
%%% be propagated to the netcdf file, the columns must be remapped per the basestation system of naming
%%% See the list below for the canonical instrument names and calibration constant names

% remap_wetlabs_eng_cols="oldval1:newval1,oldval2:newval2"

%%% Same idea, but for Aanderaa optode eng-file columns. NOTE: unlike
%%% remap_wetlabs_eng_cols above, this key is not registered in the netCDF
%%% metadata table, so it will not appear in the mission-level netCDF profile.
% remap_optode_eng_cols="oldval1:newval1,oldval2:newval2"

%%% Note - in the "oldval", any "." should be converted to "_".
%%% So, if the column in the .eng file is "wlbb2fl.BB1ref", use "wlbb2fl_BB1ref" as value for the oldval.

%%% Example
%%% remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm"
%%% where the channels are 700nm, Chl and CDOM

%%% If present, the basestation will add additional columns to apply the "standard" correction to
%%% the wetlabs data per the cal sheet. Format for these entries is:
%%%
%%% <instrument>_<channelname>_dark_counts = <dark_counts>;
%%% <instrument>_<channelname>_max_counts = <max_counts>;
%%% <instrument>_<channelname>_resolution_counts = <resolution_counts>;
%%% <instrument>_<channelname>_scale_factor = <scale_factor>;

%%% Example

%%% wlbbfl2_sig695nm_dark_counts = 49.0;
%%% wlbbfl2_sig695nm_max_counts = 4130.0;
%%% wlbbfl2_sig695nm_resolution_counts = 1.0;
%%% wlbbfl2_sig695nm_scale_factor = 0.0121;

%%% Here is the complete list of canonical names and associated calibration constants for WETLabs instruments

% wlbb2fl_sig470nm_dark_counts = 0.0; % For blue scattering channel
% wlbb2fl_sig470nm_scale_factor = 0.0; % For blue scattering channel
% wlbb2fl_sig470nm_resolution_counts = 0.0; % For blue scattering channel
% wlbb2fl_sig470nm_max_counts = 0.0; % For blue scattering channel

% wlbb2fl_sig532nm_dark_counts = 0.0; % For green scattering channel
% wlbb2fl_sig532nm_scale_factor = 0.0; % For green scattering channel
% wlbb2fl_sig532nm_resolution_counts = 0.0; % For green scattering channel
% wlbb2fl_sig532nm_max_counts = 0.0; % For green scattering channel

% wlbb2fl_sig700nm_dark_counts = 0.0; % For red scattering channel
% wlbb2fl_sig700nm_scale_factor = 0.0; % For red scattering channel
% wlbb2fl_sig700nm_resolution_counts = 0.0; % For red scattering channel
% wlbb2fl_sig700nm_max_counts = 0.0; % For red scattering channel

% wlbb2fl_sig880nm_dark_counts = 0.0; % For infrared scattering channel
% wlbb2fl_sig880nm_scale_factor = 0.0; % For infrared scattering channel
% wlbb2fl_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
% wlbb2fl_sig880nm_max_counts = 0.0; % For infrared scattering channel

% wlbb2fl_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
% wlbb2fl_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
% wlbb2fl_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
% wlbb2fl_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel

% wlbb2fl_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
% wlbb2fl_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
% wlbb2fl_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
% wlbb2fl_sig530nm_max_counts = 0.0; % For uranine fluorescence channel

% wlbb2fl_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb2fl_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb2fl_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb2fl_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel

% wlbb2fl_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
% wlbb2fl_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
% wlbb2fl_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
% wlbb2fl_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

% wlbb2fl_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
% wlbb2fl_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
% wlbb2fl_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
% wlbb2fl_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel

% wlbbfl2_sig470nm_dark_counts = 0.0; % For blue scattering channel
% wlbbfl2_sig470nm_scale_factor = 0.0; % For blue scattering channel
% wlbbfl2_sig470nm_resolution_counts = 0.0; % For blue scattering channel
% wlbbfl2_sig470nm_max_counts = 0.0; % For blue scattering channel

% wlbbfl2_sig532nm_dark_counts = 0.0; % For green scattering channel
% wlbbfl2_sig532nm_scale_factor = 0.0; % For green scattering channel
% wlbbfl2_sig532nm_resolution_counts = 0.0; % For green scattering channel
% wlbbfl2_sig532nm_max_counts = 0.0; % For green scattering channel

% wlbbfl2_sig700nm_dark_counts = 0.0; % For red scattering channel
% wlbbfl2_sig700nm_scale_factor = 0.0; % For red scattering channel
% wlbbfl2_sig700nm_resolution_counts = 0.0; % For red scattering channel
% wlbbfl2_sig700nm_max_counts = 0.0; % For red scattering channel

% wlbbfl2_sig880nm_dark_counts = 0.0; % For infrared scattering channel
% wlbbfl2_sig880nm_scale_factor = 0.0; % For infrared scattering channel
% wlbbfl2_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
% wlbbfl2_sig880nm_max_counts = 0.0; % For infrared scattering channel

% wlbbfl2_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
% wlbbfl2_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
% wlbbfl2_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
% wlbbfl2_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel

% wlbbfl2_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
% wlbbfl2_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
% wlbbfl2_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
% wlbbfl2_sig530nm_max_counts = 0.0; % For uranine fluorescence channel

% wlbbfl2_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbbfl2_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbbfl2_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbbfl2_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel

% wlbbfl2_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
% wlbbfl2_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
% wlbbfl2_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
% wlbbfl2_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

% wlbbfl2_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
% wlbbfl2_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
% wlbbfl2_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
% wlbbfl2_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel

% wlbb3_sig470nm_dark_counts = 0.0; % For blue scattering channel
% wlbb3_sig470nm_scale_factor = 0.0; % For blue scattering channel
% wlbb3_sig470nm_resolution_counts = 0.0; % For blue scattering channel
% wlbb3_sig470nm_max_counts = 0.0; % For blue scattering channel

% wlbb3_sig532nm_dark_counts = 0.0; % For green scattering channel
% wlbb3_sig532nm_scale_factor = 0.0; % For green scattering channel
% wlbb3_sig532nm_resolution_counts = 0.0; % For green scattering channel
% wlbb3_sig532nm_max_counts = 0.0; % For green scattering channel

% wlbb3_sig700nm_dark_counts = 0.0; % For red scattering channel
% wlbb3_sig700nm_scale_factor = 0.0; % For red scattering channel
% wlbb3_sig700nm_resolution_counts = 0.0; % For red scattering channel
% wlbb3_sig700nm_max_counts = 0.0; % For red scattering channel

% wlbb3_sig880nm_dark_counts = 0.0; % For infrared scattering channel
% wlbb3_sig880nm_scale_factor = 0.0; % For infrared scattering channel
% wlbb3_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
% wlbb3_sig880nm_max_counts = 0.0; % For infrared scattering channel

% wlbb3_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
% wlbb3_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
% wlbb3_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
% wlbb3_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel

% wlbb3_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
% wlbb3_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
% wlbb3_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
% wlbb3_sig530nm_max_counts = 0.0; % For uranine fluorescence channel

% wlbb3_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb3_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb3_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlbb3_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel

% wlbb3_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
% wlbb3_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
% wlbb3_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
% wlbb3_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

% wlbb3_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
% wlbb3_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
% wlbb3_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
% wlbb3_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel

% wlfl3_sig470nm_dark_counts = 0.0; % For blue scattering channel
% wlfl3_sig470nm_scale_factor = 0.0; % For blue scattering channel
% wlfl3_sig470nm_resolution_counts = 0.0; % For blue scattering channel
% wlfl3_sig470nm_max_counts = 0.0; % For blue scattering channel

% wlfl3_sig532nm_dark_counts = 0.0; % For green scattering channel
% wlfl3_sig532nm_scale_factor = 0.0; % For green scattering channel
% wlfl3_sig532nm_resolution_counts = 0.0; % For green scattering channel
% wlfl3_sig532nm_max_counts = 0.0; % For green scattering channel

% wlfl3_sig700nm_dark_counts = 0.0; % For red scattering channel
% wlfl3_sig700nm_scale_factor = 0.0; % For red scattering channel
% wlfl3_sig700nm_resolution_counts = 0.0; % For red scattering channel
% wlfl3_sig700nm_max_counts = 0.0; % For red scattering channel

% wlfl3_sig880nm_dark_counts = 0.0; % For infrared scattering channel
% wlfl3_sig880nm_scale_factor = 0.0; % For infrared scattering channel
% wlfl3_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
% wlfl3_sig880nm_max_counts = 0.0; % For infrared scattering channel

% wlfl3_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
% wlfl3_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
% wlfl3_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
% wlfl3_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel

% wlfl3_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
% wlfl3_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
% wlfl3_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
% wlfl3_sig530nm_max_counts = 0.0; % For uranine fluorescence channel

% wlfl3_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlfl3_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlfl3_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
% wlfl3_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel

% wlfl3_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
% wlfl3_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
% wlfl3_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
% wlfl3_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

% wlfl3_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
% wlfl3_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
% wlfl3_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
% wlfl3_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel
