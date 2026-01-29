% sg_calib_constants.m
% establishes glider calibration constants

sg_ct_type = 4;  % Unpumped RBR legatto
legato_use_truck_pressure = 1;
%legato_sealevel = 10315;


id_str = '236';
    
mission_title ='NANOOS May-2023';

mass = 72.293;


calibcomm_optode = 'Optode 4831 SN: 757 Foil ID: 1517M calibrated 08/06/2018';
optode_PhaseCoef0 = -0.483;
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
optode_SVUCoef0 = 0.00267239;
optode_SVUCoef1 = 0.000115969;
optode_SVUCoef2 = 2.10441e-06;
optode_SVUCoef3 = 161.114;
optode_SVUCoef4 = -0.233715;
optode_SVUCoef5 = -36.6419;
optode_SVUCoef6 = 3.2395;
    
calibcomm_wetlabs = 'BB2FLIRB-1336 6/20/2018';

%For blue scattering channel
wlbb2fl_sig470nm_dark_counts = 53.0;
wlbb2fl_sig470nm_max_counts = 9999.0;
wlbb2fl_sig470nm_resolution_counts = 1.0;
wlbb2fl_sig470nm_scale_factor = 1.03e-05;

%For red scattering channel
wlbb2fl_sig700nm_dark_counts = 51.0;
wlbb2fl_sig700nm_max_counts = 9999.0;
wlbb2fl_sig700nm_resolution_counts = 1.2;
wlbb2fl_sig700nm_scale_factor = 4.13e-06;

%For chlorophyll fluorescence channel
wlbb2fl_sig695nm_dark_counts = 50.0;
wlbb2fl_sig695nm_max_counts = 4130.0;
wlbb2fl_sig695nm_resolution_counts = 1.0;
wlbb2fl_sig695nm_scale_factor = 0.0117;
