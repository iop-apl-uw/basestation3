% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

% REQUIRED
id_str = '263';

% REQUIRED
mission_title ='NANOOS March 2025';

% REQUIRED
mass = 72.982; % (kg) scale weight


%
% Legato CTD
%

% Required
sg_ct_type = 4;  % Indicates a legato CTD

calibcomm = 'Legato s/n 209913, calibration 2022 May 06';
legato_sealevel = 10029;

% Set to 1 to use the Seaglider pressure sensor for CTD corrections
legato_use_truck_pressure = 0;

% Set to 0 to disable the basestation conductivity pressure correction, in favor of the on in the instrument
% On board correction is applied when X2, X3 and X4 are non-zero (see metadata capture from a selftest)
% See RBR document "0013279revA Conductivity pressure correction for RBRlegato3 with RBR#0007155 top.pdf"
legato_cond_press_correction = 1;

% ignore any legato columns from the truck
%PARAM ignore_truck_legato = 1; 

calibcomm_optode = ''Optode 4831 SN: 940  Foil ID: 1824M calibrated 03-12-2020'';
optode_PhaseCoef0 = -2.734;
optode_PhaseCoef1 = 1;
optode_PhaseCoef2 = 0;
optode_PhaseCoef3 = 0;
optode_ConcCoef0 = 0;
optode_ConcCoef1 = 1;


optode_FoilCoefA0 = -2.67928e-06;
optode_FoilCoefA1 = -7.4836e-06;
optode_FoilCoefA2 = 0.00196001;
optode_FoilCoefA3 = -0.207285;
optode_FoilCoefA4 = 0.000601246;
optode_FoilCoefA5 = -6.60427e-07;
optode_FoilCoefA6 = 11.1802;
optode_FoilCoefA7 = -0.0514806;
optode_FoilCoefA8 = 6.8985e-05;
optode_FoilCoefA9 = 8.46501e-07;
optode_FoilCoefA10 = -314.351;
optode_FoilCoefA11 = 2.05112;
optode_FoilCoefA12 = -0.00298703;
optode_FoilCoefA13 = -4.44977e-06;

optode_FoilCoefB0 = -1.86135e-06;
optode_FoilCoefB1 = 3814.9;
optode_FoilCoefB2 = -32.2281;
optode_FoilCoefB3 = -0.1678;
optode_FoilCoefB4 = 0.0189482;
optode_FoilCoefB5 = -0.000690143;
optode_FoilCoefB6 = 1.04269e-05;
optode_FoilCoefB7 = 0;
optode_FoilCoefB8 = 0;
optode_FoilCoefB9 = 0;
optode_FoilCoefB10 = 0;
optode_FoilCoefB11 = 0;
optode_FoilCoefB12 = 0;
optode_FoilCoefB13 = 0;

optode_SVU_enabled = 1;

optode_SVUCoef0 = 0.00276388;
optode_SVUCoef1 = 0.00011389;
optode_SVUCoef2 = 2.47865e-06;
optode_SVUCoef3 = 166.347;
optode_SVUCoef4 = -0.263223;
optode_SVUCoef5 = -37.8607;
optode_SVUCoef6 = 3.37836;

% Wetlabs BB2FLIRB2-
calibcomm_wetlabs = 'BB2FLIRB2-6732 3/24/2021';

%For blue scattering channel
wlbb2fl_sig470nm_dark_counts = 49.0;
wlbb2fl_sig470nm_max_counts = 9999.0;
wlbb2fl_sig470nm_resolution_counts = 1.3;
wlbb2fl_sig470nm_scale_factor = 1.208e-05;

%For red scattering channel
wlbb2fl_sig700nm_dark_counts = 46.0;
wlbb2fl_sig700nm_max_counts = 9999.0;
wlbb2fl_sig700nm_resolution_counts = 1.6;
wlbb2fl_sig700nm_scale_factor = 3.386e-06;

%For chlorophyll fluorescence channel
wlbb2fl_sig695nm_dark_counts = 42.0;
wlbb2fl_sig695nm_max_counts = 4150.0;
wlbb2fl_sig695nm_resolution_counts = 1.0;
wlbb2fl_sig695nm_scale_factor = 0.0121;
