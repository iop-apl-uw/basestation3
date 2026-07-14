% sg_calib_constants.m
% establishes glider calibration constants

id_str = '180';
    
mission_title ='Shilshole 01-Jul-26';

mass = 56.122;

calibcomm = 'SBE CT Sail #220 calibration 31-Oct-25';
t_g = 4.39408113e-03;
t_h = 6.35181568e-04;
t_i = 2.52541356e-05;
t_j = 3.01804897e-06;

c_g = -9.68862293e+00;
c_h = 1.10452835e+00;
c_i = -1.40677134e-03;
c_j = 1.98326664e-04;

sbe_cond_freq_C0 = 2964.97;

cpcor = -9.57e-08 ;;
ctcor =  3.25e-06 ;


% Wetlabs BB2FLIRB2-6739
calibcomm_wetlabs = 'BB2FLIRB2-6739 3/24/2021';

%For blue scattering channel
wlbb2fl_sig470nm_dark_counts = 56.0;
wlbb2fl_sig470nm_max_counts = 9999.0;
wlbb2fl_sig470nm_resolution_counts = 1.6;
wlbb2fl_sig470nm_scale_factor = 1.237e-05;

%For red scattering channel
wlbb2fl_sig700nm_dark_counts = 44.0;
wlbb2fl_sig700nm_max_counts = 9999.0;
wlbb2fl_sig700nm_resolution_counts = 1.5;
wlbb2fl_sig700nm_scale_factor = 3.375e-06;

%For chlorophyll fluorescence channel
wlbb2fl_sig695nm_dark_counts = 35.0;
wlbb2fl_sig695nm_max_counts = 4140.0;
wlbb2fl_sig695nm_resolution_counts = 1.1;
wlbb2fl_sig695nm_scale_factor = 0.0121;

