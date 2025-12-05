% Last edited on 2023/12/08 by D Hayes 
% Last edited on 2024/03/10 by A Erofeev 
% Last edited on 2024/04/16 by J Marquardt
% Last edited on 2025/01/03 by J Marquardt 

% basic glider and mission params
    id_str='686';
    mission_title='Shilshole 28-Oct-25';
    mass=55.160; % kg  % Updated  10/23/25 - pH sensor / pump
%    mass=53.398; % kg  % Changed back on Dive 112 5/3/2024
%    volmax=52542;% cc
%    volmax = 52430.4; % 15-Apr-2024 VBD Regression
%    rho0=1027.500;% kg/m3

% initial hydrodynamic model params; used only with NAV_MODE,2;
% regression needed to obtain realistic values
%    hd_a=0.003548;
%    hd_b=0.011220;
%    hd_c=5.7e-6;

% 15-Apr-2024 16:36:25 RMS=1.3512 cm/s Dives: 23:25 28 29 VBD Regression
%    hd_a = 2.44838e-03;
%    hd_b = 1.24762e-02;
%    hd_c = 6.96150e-07;

 % Seabird CT Sail sensor cal constants
 % Updated on 1/3/2025 J Marquardt
     calibcomm=' Serial #: 0399  CAL: 26-Nov-24';%  Serial # and cal date
     t_g=4.418707e-003;
     t_h=6.422725e-004;
     t_i=2.582635e-005;
     t_j=3.132603e-006;
     c_g=-1.008748e+001;
     c_h=1.124446e+000;
     c_i=-1.695477e-003;
     c_j=1.963163e-004;
     ctcor=3.250000e-006;
     cpcor=-9.570000e-008;
     sbe_cond_freq_C0=2999.60;

%  Aanderaa cal constants   -   OLD OPTODE (1012 dead)
%     comm_oxy_type=' AA4831 '; % make and model e.g. AA4831 or AA4330
%     calibcomm_optode=' SN: 1012  CAL: 09/03/2022 '; %  Serial # and cal date

%     optode_PhaseCoef0=-2.056000E+00;
%     optode_PhaseCoef1=1.000000E+00;
%     optode_PhaseCoef2=0.000000E+00;
%     optode_PhaseCoef3=0.000000E+00;

%     optode_FoilCoefA0=-2.679283E-06;
%     optode_FoilCoefA1=-7.483597E-06;
%     optode_FoilCoefA2=1.960006E-03;
%     optode_FoilCoefA3=-2.072853E-01;
%     optode_FoilCoefA4=6.012464E-04;
%     optode_FoilCoefA5=-6.604266E-07;
%     optode_FoilCoefA6=1.118020E+01;
%     optode_FoilCoefA7=-5.148064E-02;
%     optode_FoilCoefA8=6.898503E-05;
%     optode_FoilCoefA9=8.465012E-07;
%     optode_FoilCoefA10=-3.143506E+02;
%     optode_FoilCoefA11=2.051116E+00;
%     optode_FoilCoefA12=-2.987026E-03;
%     optode_FoilCoefA13=-4.449771E-06;

%     optode_FoilCoefB0=-1.861349E-06;
%     optode_FoilCoefB1=3.814899E+03;
%     optode_FoilCoefB2=-3.222806E+01;
%     optode_FoilCoefB3=-1.678000E-01;
%     optode_FoilCoefB4=1.894820E-02;
%     optode_FoilCoefB5=-6.901433E-04;
%     optode_FoilCoefB6=1.042693E-05;
%     optode_FoilCoefB7=0.000000E+00;
%     optode_FoilCoefB8=0.000000E+00;
%     optode_FoilCoefB9=0.000000E+00;
%     optode_FoilCoefB10=0.000000E+00;
%     optode_FoilCoefB11=0.000000E+00;
%     optode_FoilCoefB12=0.000000E+00;
%     optode_FoilCoefB13=0.000000E+00;

%     optode_SVU_enabled = 1;
%     optode_SVUCoef0=2.72460E-03;
%     optode_SVUCoef1=1.15756E-04;
%     optode_SVUCoef2=2.34561E-06;
%     optode_SVUCoef3=9.80882E+01;
%     optode_SVUCoef4=-1.18764E-01;
%     optode_SVUCoef5=-2.06929E+01;
%    optode_SVUCoef6=1.97897E+00;
%
%     optode_ConcCoef0=0.000000E+00;
%     optode_ConcCoef1=1.000000E+00;

 % Aanderaa cal constants   -   (979 good)
     comm_oxy_type=' AA4831 '; % make and model e.g. AA4831 or AA4330
     calibcomm_optode=' SN: 979  CAL: 14-Jul-2021 ';%  Serial # and cal date

     optode_PhaseCoef0 = -6.650000E-01;
     optode_PhaseCoef1 = 1.000000E+00;
     optode_PhaseCoef2 = 0.000000E+00;
     optode_PhaseCoef3 = 0.000000E+00;


     optode_ConcCoef0 = 0.000000E+00;
     optode_ConcCoef1 = 1.000000E+00;

     optode_FoilCoefA0 = -2.679283E-06;
     optode_FoilCoefA1 = -7.483597E-06;
     optode_FoilCoefA2 = 1.960006E-03;
     optode_FoilCoefA3 = -2.072853E-01;
     optode_FoilCoefA4 = 6.012464E-04;
     optode_FoilCoefA5 = -6.604266E-07;
     optode_FoilCoefA6 = 1.118020E+01;
     optode_FoilCoefA7 = -5.148064E-02;
     optode_FoilCoefA8 = 6.898503E-05;
     optode_FoilCoefA9 = 8.465012E-07;
     optode_FoilCoefA10 = -3.143506E+02;
     optode_FoilCoefA11 = 2.051116E+00;
     optode_FoilCoefA12 = -2.987026E-03;
     optode_FoilCoefA13 = -4.449771E-06;

     optode_FoilCoefB0 = -1.861349E-06;
     optode_FoilCoefB1 = 3.814899E+03;
     optode_FoilCoefB2 = -3.222806E+01;
     optode_FoilCoefB3 = -1.678000E-01;
     optode_FoilCoefB4 = 1.894820E-02;
     optode_FoilCoefB5 = -6.901433E-04;
     optode_FoilCoefB6 = 1.042693E-05;
     optode_FoilCoefB7 = 0.000000E+00;
     optode_FoilCoefB8 = 0.000000E+00;
     optode_FoilCoefB9 = 0.000000E+00;
     optode_FoilCoefB10 = 0.000000E+00;
     optode_FoilCoefB11 = 0.000000E+00;
     optode_FoilCoefB12 = 0.000000E+00;
     optode_FoilCoefB13 = 0.000000E+00;

          % Uncomment "optode_SVU_enabled" to process data using SVU algorithm.
     optode_SVU_enabled = 1;
     optode_SVUCoef0=2.759664E-03;
     optode_SVUCoef1=1.150958E-04;
     optode_SVUCoef2=2.495004E-06;
     optode_SVUCoef3=1.863217E+02;
     optode_SVUCoef4=-2.354856E-01;
     optode_SVUCoef5=-4.297383E+01;
     optode_SVUCoef6=3.757123E+00;

 % WETLabs wlbbfl2 calibration constants.
%    WETLabsCalData_wlbbfl2_calinfo = ' SN: BBFL2IRB-7513, CAL: 04/09/2022 ';

%    % Backscattering cal constants - wavelength 700
%    WETLabsCalData.wlbbfl2.Scatter700.wavelength=700;
%    WETLabsCalData.wlbbfl2.Scatter700.scaleFactor=3.475E-06;
%    WETLabsCalData.wlbbfl2.Scatter700.darkCounts=48;
%    WETLabsCalData.wlbbfl2.Scatter700.resolution=1.0;

%    % Chlorophyll cal constants
%    WETLabsCalData.wlbbfl2.Chlorophyll.wavelength=695;
%    WETLabsCalData.wlbbfl2.Chlorophyll.darkCounts=49;
%    WETLabsCalData.wlbbfl2.Chlorophyll.scaleFactor=0.0121;
%    WETLabsCalData.wlbbfl2.Chlorophyll.maxOutput=4130;
%    WETLabsCalData.wlbbfl2.Chlorophyll.resolution=1.0;
%    WETLabsCalData.wlbbfl2.Chlorophyll.calTemperature=21.0;

%    % CDOM cal constants
%    WETLabsCalData.wlbbfl2.CDOM.wavelength=460;
%    WETLabsCalData.wlbbfl2.CDOM.maxOutput=4130;
%    WETLabsCalData.wlbbfl2.CDOM.scaleFactor=0.0907;
%    WETLabsCalData.wlbbfl2.CDOM.darkCounts=50;
%    WETLabsCalData.wlbbfl2.CDOM.resolution=1.0;
%    WETLabsCalData.wlbbfl2.CDOM.calTemperature=21.0;



wlbb2fl_sig700nm_dark_counts = 48; % For red scattering channel
wlbb2fl_sig700nm_scale_factor = 3.475E-06; % For red scattering channel
wlbb2fl_sig700nm_resolution_counts = 1.0; % For red scattering channel
wlbb2fl_sig700nm_max_counts = 9999; % For red scattering channel
wlbb2fl_sig695nm_dark_counts = 49; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_scale_factor = 0.0121; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_resolution_counts = 1.0; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_max_counts = 4130; % For chlorophyll fluorescence channel
wlbb2fl_sig460nm_dark_counts = 50; % For CDOM fluorescence channel
wlbb2fl_sig460nm_scale_factor = 0.0907; % For CDOM fluorescence channel
wlbb2fl_sig460nm_resolution_counts = 1.0; % For CDOM fluorescence channel
wlbb2fl_sig460nm_max_counts = 4130; % For CDOM fluorescence channel

