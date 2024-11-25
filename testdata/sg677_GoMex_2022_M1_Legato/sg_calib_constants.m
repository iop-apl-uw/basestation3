% Last edited on 11/17/2020 by E. Creed
% Template file for sg_calib_constants.m, Kongsberg Document No. 4000122
% Applies to Post Tank Trim Sheet - RBR Legato and GPCTD
% updated 6/2022 - Kevin Martin for USM SG677

%GBS 2023/02/06
sg_ct_type = 4;  % Unpumped RBR legatto

%GBS 2023/02/06 - a nominal value to get things rolling
legato_sealevel = 10082.0;

% basic glider and mission params
    id_str='677'; % Update glider ID after commissioning
    mission_title='GoMex_2022_M1';
    mass=53.549;% kg  (from sum on trim sheet) (51473.0 g from cmd file)
% FM_ignore     volmax=52787;% cc  (from ballast worksheet final table)
% FM_ignore     rho0=1027.5;% kg/m3 (from ballast worksheet for "new" environment)  (1.023300 from cmd file)

% initial hydrodynamic model params
% regression needed to obtain realistic values
% FM_ignore     hd_a=3.83600000E-03;
% FM_ignore     hd_b=1.00780000E-02;
% FM_ignore     hd_c=9.85000000E-06;

% GPCTD params - uncomment the following 2 lines if a GPCTD is installed in the glider
%   sg_configuration=3; %  selects GPCTD configuration
%   calibcomm=' GPCTD Serial #: 0022 CAL: 05-Dec-2010';%  Serial # and cal dat

% % CT sensors cal constants
%     calibcomm=' Serial #: 0155  CAL: 14-Mar-10';%  Serial # and cal date
%     t_g=4.42913607e-003;
%     t_h=6.43659763e-004;
%     t_i=2.65816280e-005;
%     t_j=2.65816280e-006;
%     c_g=-1.00733141e+001;
%     c_h=1.10813555e+000;
%     c_i=--2.85054114e-003;
%     c_j=2.82466238e-004;
%     cpcor=-9.5700e-08;
%     ctcor=3.2500e-06;
%     sbe_cond_freq_min=2.93745e+0;
%     sbe_cond_freq_max=7.72255e+0;
%     sbe_temp_freq_min=2.946407e+0;
%     sbe_temp_freq_max=5.670807e+0;

% % RBR Legato configuration
% %
% % channel               flag    int
% % -----------------------------------
% % conductivity          0x01      1
% % temperature           0x02      2
% % pressure              0x04      4
% % sea pressure          0x08      8
% % depth                 0x10     16
% % salinity              0x20     32
% % counts                0x40     64
% % cond cell temp        0x80    128
% %
% % For all enabled channels, add the corresponding int values and set legato_config
% % ex: 
% % conductivity, temperature, pressure, and conductivity cell temperature are enabled
% % legato_config = 1 + 2 + 4 + 128 = 135 (0x87)
% % USM Legato_config = 1+2+4+8+16+32+128 = 191 - Kevin M. Martin 6/11/22
% % WARNING: Do not disable conductivity, temperature, and pressure. They are required for glider flight
% % Default value is 7
   legato_config=191; % selects RBR Legato configuration - uncomment if RBR installed
   calibcomm=' RBR Legato Serial #: 0210300   CAL: 28-Apr-2022'; %Serial # and cal date - uncomment if RBR installed

% % Seabird oxygen cal constants
%     comm_oxy_type='0';% spec "SBE_43f" or "Pumped_SBE_43f"
%     calibcomm_oxygen='0';%  Serial # and cal date
%     Soc=0.000000E+00;
%     Foffset=0.000000E+00;
%     o_a=0.000000E+00;
%     o_b=0.000000E+00;
%     o_c=0.000000E+00;
%     o_e=0.000000E+00;
%     Tau20=0.00;
%     Pcor=0;

% % Aanderaa 3830 cal constants
%     comm_oxy_type = ' AA3830 ';  % type and model
%     calibcomm_optode = ' SN: 000  CAL: 31-Feb-2014 '; % serial # and cal date
% 
%     optode_C00Coef=0.1;
%     optode_C01Coef=0.1;
%     optode_C02Coef=0.1;
%     optode_C03Coef=0.1;
% 
%     optode_C10Coef=0.1;
%     optode_C11Coef=0.1;
%     optode_C12Coef=0.1;
%     optode_C13Coef=0.1;
% 
%     optode_C20Coef=0.1;
%     optode_C21Coef=0.1;
%     optode_C22Coef=0.1;
%     optode_C23Coef=0.1;
% 
%     optode_C30Coef=0.1;
%     optode_C31Coef=0.1;
%     optode_C32Coef=0.1;
%     optode_C33Coef=0.1;
% 
%     optode_C40Coef=0.1;
%     optode_C41Coef=0.1;
%     optode_C42Coef=0.1;
%     optode_C43Coef=0.1;

% % Aanderaa cal constants
comm_oxy_type=' AA4831 '; %make and model e.g. AA4831 or AA4330
calibcomm_optode=' SN: 875  CAL: 10-02-2020 ';%  Serial # and cal date
optode_PhaseCoef0=-2.513000E+00;
optode_PhaseCoef1=1.000000E+00;
optode_PhaseCoef2=0.000000E+00;
optode_PhaseCoef3=0.000000E+00;

optode_FoilCoefA0=-4.429471E-06;
optode_FoilCoefA1=-9.934120E-06;
optode_FoilCoefA2=2.539297E-03;
optode_FoilCoefA3=-2.623883E-01;
optode_FoilCoefA4=9.495663E-04;
optode_FoilCoefA5=-1.385170E-06;
optode_FoilCoefA6=1.384506E+01;
optode_FoilCoefA7=-7.820107E-02;
optode_FoilCoefA8=2.077827E-04;
optode_FoilCoefA9=1.951742E-07;
optode_FoilCoefA10=-3.815226E+02;
optode_FoilCoefA11=2.968714E+00;
optode_FoilCoefA12=-4.551691E-03;
optode_FoilCoefA13=-3.449760E-04;

optode_FoilCoefB0=5.200052E-06;
optode_FoilCoefB1=4.547302E+03;
optode_FoilCoefB2=-4.453296E+01;
optode_FoilCoefB3=-1.936771E-01;
optode_FoilCoefB4=2.230949E-02;
optode_FoilCoefB5=-4.134188E-04;
optode_FoilCoefB6=1.497347E-06;
optode_FoilCoefB7=0.000000E+00;
optode_FoilCoefB8=0.000000E+00;
optode_FoilCoefB9=0.000000E+00;
optode_FoilCoefB10=0.000000E+00;
optode_FoilCoefB11=0.000000E+00;
optode_FoilCoefB12=0.000000E+00;
optode_FoilCoefB13=0.000000E+00;

optode_SVU_enabled;
optode_SVUCoef0=2.793541E-03;
optode_SVUCoef1=1.236392E-04;
optode_SVUCoef2=2.142995E-06;
optode_SVUCoef3=1.853489E+02;
optode_SVUCoef4=-2.551195E-01;
optode_SVUCoef5=-3.864259E+01;
optode_SVUCoef6=3.692958E+00;

optode_ConcCoef0=0.000000E+00;
optode_ConcCoef1=1.000000E+00;

remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm" 

% WETLabs wlbbfl2 calibration constants.

calibcomm_wetlabs = ' SN: BBFL2IRB-6148, CAL: 3/4/2020 ';

%    WETLabsCalData.wlbbfl2.Scatter700.wavelength=700;
%    WETLabsCalData.wlbbfl2.Scatter700.scaleFactor=0.0060;
%    WETLabsCalData.wlbbfl2.Scatter700.darkCounts=50;
%    WETLabsCalData.wlbbfl2.Scatter700.resolution=1.0;

wlbbfl2_sig700nm_dark_counts = 50.0;
wlbbfl2_sig700nm_max_counts = 9999.0;
wlbbfl2_sig700nm_resolution_counts = 1.0;
wlbbfl2_sig700nm_scale_factor = 0.006;

%
%    % Chlorophyll cal constants
%    WETLabsCalData.wlbbfl2.Chlorophyll.wavelength=695;
%    WETLabsCalData.wlbbfl2.Chlorophyll.darkCounts=49;
%    WETLabsCalData.wlbbfl2.Chlorophyll.scaleFactor=0.0121;
%    WETLabsCalData.wlbbfl2.Chlorophyll.maxOutput=4130;
%    WETLabsCalData.wlbbfl2.Chlorophyll.resolution=1.0;
%    WETLabsCalData.wlbbfl2.Chlorophyll.calTemperature=22.8;
wlbbfl2_sig695nm_dark_counts = 49.0;
wlbbfl2_sig695nm_max_counts = 4130.0;
wlbbfl2_sig695nm_resolution_counts = 1.0;
wlbbfl2_sig695nm_scale_factor = 0.0121;

%    % CDOM cal constants
    % WETLabsCalData.wlbbfl2.CDOM.wavelength=460;
    % WETLabsCalData.wlbbfl2.CDOM.maxOutput=4130;
    % WETLabsCalData.wlbbfl2.CDOM.scaleFactor=0.0887;
    % WETLabsCalData.wlbbfl2.CDOM.darkCounts=49;
    % WETLabsCalData.wlbbfl2.CDOM.resolution=1;
    % WETLabsCalData.wlbbfl2.CDOM.calTemperature=22.8;
wlbbfl2_sig460nm_dark_counts = 49.0;
wlbbfl2_sig460nm_max_counts = 4130.0;
wlbbfl2_sig460nm_resolution_counts = 1.0;
wlbbfl2_sig460nm_scale_factor = 0.0887;
