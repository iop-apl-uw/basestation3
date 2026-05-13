% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

% REQUIRED
id_str = '171';

% REQUIRED
mission_title = 'EKAMSAT 2024';

% REQUIRED
mass = 56.690 ; % (kg) scale weight

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

%
% Seabird un-pumped CT
%

% REQUIRED - use the correct values from the Seabird cal sheet

calibcomm = 'SBE s/n 0260, calibration 12 Sep 2023';
t_g =  4.40953569e-003 ; 
t_h =  6.45635007e-004 ;
t_i =  2.58444570e-005 ;
t_j =  3.22925756e-006 ;
c_g =  -9.78674202e+000 ;
c_h =  1.15519227e+000 ;
c_i =  -1.61005305e-003 ;
c_j =  1.98148889e-004 ;
cpcor = -9.57e-08 ;
ctcor =  3.25e-06 ;
sbe_cond_freq_C0 = 2914.46 ;


calibcomm_optode = ''Optode 4831 SN: 141  Foil ID: 1206E calibrated ??/??/????'';
optode_PhaseCoef0 = 0;
optode_PhaseCoef1 = 1;
optode_PhaseCoef2 = 0;
optode_PhaseCoef3 = 0;
optode_ConcCoef0 = 1.14256;
optode_ConcCoef1 = 1.05977;


optode_FoilCoefA0 = -2.98831e-06;
optode_FoilCoefA1 = -6.13778e-06;
optode_FoilCoefA2 = 0.00168466;
optode_FoilCoefA3 = -0.185717;
optode_FoilCoefA4 = 0.00067844;
optode_FoilCoefA5 = -5.59791e-07;
optode_FoilCoefA6 = 10.4016;
optode_FoilCoefA7 = -0.0598691;
optode_FoilCoefA8 = 0.000136042;
optode_FoilCoefA9 = -4.77698e-07;
optode_FoilCoefA10 = -303.294;
optode_FoilCoefA11 = 2.5305;
optode_FoilCoefA12 = -0.0126704;
optode_FoilCoefA13 = 0.000104045;

optode_FoilCoefB0 = -3.56039e-07;
optode_FoilCoefB1 = 3816.71;
optode_FoilCoefB2 = -44.7551;
optode_FoilCoefB3 = 0.438616;
optode_FoilCoefB4 = -0.00714634;
optode_FoilCoefB5 = 8.90624e-05;
optode_FoilCoefB6 = -6.34301e-07;
optode_FoilCoefB7 = 0;
optode_FoilCoefB8 = 0;
optode_FoilCoefB9 = 0;
optode_FoilCoefB10 = 0;
optode_FoilCoefB11 = 0;
optode_FoilCoefB12 = 0;
optode_FoilCoefB13 = 0;

optode_SVU_enabled = 0;

optode_SVUCoef0 = 0;
optode_SVUCoef1 = 0;
optode_SVUCoef2 = 0;
optode_SVUCoef3 = 0;
optode_SVUCoef4 = 0;
optode_SVUCoef5 = 0;
optode_SVUCoef6 = 0;

%columns: wlbb2flvmt.time wlbb2flvmt.470sig wlbb2flvmt.700sig wlbb2flvmt.Chlsig wlbb2flvmt.temp 

%
% Wetlabs
%
calibcomm_wetlabs = 'BBFL2VMT-588 1/27/2009';

wlbb2fl_sig650nm_dark_counts = 480; % For red scattering channel
wlbb2fl_sig650nm_scale_factor = 3.971E-06; % For red scattering channel
wlbb2fl_sig650nm_resolution_counts = 2.0; % For red scattering channel
wlbb2fl_sig650nm_max_counts = 9999; % For red scattering channel

wlbb2fl_sig460nm_dark_counts = 49; % For CDOM fluorescence
wlbb2fl_sig460nm_scale_factor = 0.0878; % For CDOM fluorescence
wlbb2fl_sig460nm_resolution_counts = 1.4; % For CDOM fluorescence
wlbb2fl_sig460nm_max_counts = 4120; % For CDOM fluorescence

wlbb2fl_sig695nm_dark_counts = 52; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_scale_factor = 0.0129; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_resolution_counts = 1.3; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_max_counts = 4120; % For chlorophyll fluorescence channel

