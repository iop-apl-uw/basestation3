% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

% REQUIRED
id_str = '267';

% REQUIRED
mission_title ='STSD_WHIRLS_CRUISE_17_JULY';

% REQUIRED
%mass = 74.845; % (kg) scale weight
%mass = 75.053; % (kg) scale weight
mass = 75.360; 

% Optional
%PARAM mass_comp = 0;

% NOTE:
% FlightModel will supply
%
%  volmax, vbdbias, hd_a, hd_b, hd_c, hd_s, rho0, abs_compress, therm_expan, temp_ref
%
% ignoring any settings here and issue a warning, unless
% --skip_flight_model is set, in which case processing will use these
% variables. To suppress warnings about these variables, insert FM_ignore anywhere in a comment on the same
% line as the variable
% 

% Optional - if installed, use the adcp's pressure sensor instead of the truck pressure sensor
% as the basis of ctd_pressure
use_adcppressure = 0;

%
% Legato CTD
%

% Required
sg_ct_type = 4;  % Indicates a legato CTD

calibcomm = 'Legato s/n 233484, calibration 19 Dec 2023';

% Required for Legato as logdev or on the truck
legato_sealevel = 10182.0; % Where this is sealevel presure setting.

% Set to 1 to use the Seaglider pressure sensor for CTD corrections
legato_use_truck_pressure = 0;

% Set to 0 to disable the basestation conductivity pressure correction, in favor of the on in the instrument
% On board correction is applied when X2, X3 and X4 are non-zero (see metadata capture from a selftest)
% See RBR document "0013279revA Conductivity pressure correction for RBRlegato3 with RBR#0007155 top.pdf"
legato_cond_press_correction = 0;

% Misc legato settings

% ignore any legato columns from the truck
ignore_truck_legato = 1; 

% Optode
calibcomm_optode = ''Optode 4831 SN: 1123  Foil ID: 1824M calibrated ??/??/????'';
optode_PhaseCoef0 = -0.666;
optode_PhaseCoef1 = 1;
optode_PhaseCoef2 = 0;
optode_PhaseCoef3 = 0;
optode_ConcCoef0 = 0;
optode_ConcCoef1 = 1;


optode_FoilCoefA0 = -4.42947e-06;
optode_FoilCoefA1 = -9.93412e-06;
optode_FoilCoefA2 = 0.0025393;
optode_FoilCoefA3 = -0.262388;
optode_FoilCoefA4 = 0.000949566;
optode_FoilCoefA5 = -1.38517e-06;
optode_FoilCoefA6 = 13.8451;
optode_FoilCoefA7 = -0.0782011;
optode_FoilCoefA8 = 0.000207783;
optode_FoilCoefA9 = 1.95174e-07;
optode_FoilCoefA10 = -381.523;
optode_FoilCoefA11 = 2.96871;
optode_FoilCoefA12 = -0.00455169;
optode_FoilCoefA13 = -0.000344976;

optode_FoilCoefB0 = 5.20005e-06;
optode_FoilCoefB1 = 4547.3;
optode_FoilCoefB2 = -44.533;
optode_FoilCoefB3 = -0.193677;
optode_FoilCoefB4 = 0.0223095;
optode_FoilCoefB5 = -0.000413419;
optode_FoilCoefB6 = 1.49735e-06;
optode_FoilCoefB7 = 0;
optode_FoilCoefB8 = 0;
optode_FoilCoefB9 = 0;
optode_FoilCoefB10 = 0;
optode_FoilCoefB11 = 0;
optode_FoilCoefB12 = 0;
optode_FoilCoefB13 = 0;

optode_SVU_enabled = 1;

optode_SVUCoef0 = 0.00269322;
optode_SVUCoef1 = 0.000113043;
optode_SVUCoef2 = 2.1963e-06;
optode_SVUCoef3 = 143.382;
optode_SVUCoef4 = -0.236419;
optode_SVUCoef5 = -34.9914;
optode_SVUCoef6 = 2.87713;

%
% Wetlabs
%

% If present, the basestation will add additional columns to apply the "standard" correction to
% the wetlabs data per the cal sheet. Format for these entries is:
%
% <instrument>_<channelname>_dark_counts = <dark_counts>;
% <instrument>_<channelname>_max_counts = <max_counts>;
% <instrument>_<channelname>_resolution_counts = <resolution_counts>;
% <instrument>_<channelname>_scale_factor = <scale_factor>;

wlbb2fl_sig470nm_dark_counts = 49; % For green scattering channel
wlbb2fl_sig470nm_scale_factor = 1.124e-05; % For blue scattering channel
wlbb2fl_sig470nm_resolution_counts = 1.1; % For blue scattering channel
wlbb2fl_sig470nm_max_counts = 9999; % For blue scattering channel

wlbb2fl_sig700nm_dark_counts = 53.0; % For infrared scattering channel
wlbb2fl_sig700nm_scale_factor = 3.009e-6; % For red scattering channel
wlbb2fl_sig700nm_resolution_counts = 1.0; % For red scattering channel
wlbb2fl_sig700nm_max_counts = 9999; % For red scattering channel

wlbb2fl_sig695nm_dark_counts = 49.0; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_scale_factor = 0.0121; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_resolution_counts = 1.0; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_max_counts = 4130; % For chlorophyll fluorescence channel

