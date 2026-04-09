% last edited on 2026/02/13 AB Added QC bounds and biases on temperature and salinity for reprocessing w/ basestation 3 + %FM_ignore label
% Last edited on 2016/05/13 EMB
% Template file for sg_calib_constants.m, Kongsberg Document No. 4000122
% Applies to SGxxx_trim_sheet_ocean_for_mission_xxx_yyyymmdd.xlsx

% basic glider and mission params
    id_str='561';
    mission_title='provolo_lofoten_may2016';
    mass=53.959;% kg
  %  volmax=53109;% FM_ignore % cc from ballasting in tank, may be modified by regression results as below
    rho0=1028.025;% FM_ignore % kg/m3 density at apogee

% initial hydrodynamic model params
%     hd_a=3.83600000E-03;% FM_ignore
%     hd_b=1.00780000E-02;% FM_ignore
%     hd_c=9.85000000E-06;% FM_ignore
%     therm_expan=7.05000000E-05;% FM_ignore
%     temp_ref=1.50000000E+01;% FM_ignore
%     abs_compress=4.18000000E-06;% FM_ignore
%     pitchbias=0.00000000E+00;% FM_ignore

% 12-May-2016 09:57:50 RMS=0.6715 cm/s Provolo Dives: 5 9 11:21 24:29 31 32 34 37
%    glider_length=2;
%    volmax = 53023.7;
%    hd_a = 3.07191e-03;
%    hd_b = 8.67522e-03;
%    hd_c = 1.86559e-12;

% 12-May-2016 14:35:03 RMS=0.6715 cm/s Provolo Dives: 5 9 11:21 24:29 31 32 34 37
%     glider_length=1.8;% FM_ignore
%     volmax = 53023.7;% FM_ignore
%     hd_a = 3.79152e-03;% FM_ignore
%     hd_b = 1.07105e-02;% FM_ignore
%     hd_c = 2.53055e-12;% FM_ignore
    
% QC bounds and biases (removed) applied during delayed mode reprocessing with bs3:	
QC_temp_min = -2; % units degC
QC_temp_max = 30; % units degC
QC_salin_min = 27; % units PSU
QC_salin_max = 36; % units PSU
temp_bias = -0.006; % temperature offset in deg C
cond_bias = -0.0085; % conductivity offset in mS/cm 

% software limits from cal sheet
%     pitch_min_cnts=271;
%     pitch_max_cnts=3942;
%     roll_min_cnts=245;
%     roll_max_cnts=3880;
%     vbd_min_cnts=600;
%     vbd_max_cnts=3960;
%     vbd_cnts_per_cc=-4.076707;

% pump parameters
%     pump_rate_intercept=1.275;
%     pump_rate_slope=-0.00015;
%     pump_power_intercept=17.4033;
%     pump_power_slope=0.017824;

 % Seabird CT Sail sensor cal constants
     calibcomm=' Serial #: 0185  CAL: 26-Aug-2015';%  Serial # and cal date
     t_g=4.30756194e-3;
     t_h=6.19891580e-4;
     t_i=2.22051627e-5;
     t_j=2.30403084e-6;
     c_g=-9.77330323e0;
     c_h=1.11174919e0;
     c_i=-1.39380491e-3;
     c_j=1.82300843e-4;
     cpcor=-9.57000000E-08;
     ctcor=3.25000000E-06;
   %  sbe_cond_freq_min=2.9000E+00;% kHz, from cal for 0 salinity
   %  sbe_cond_freq_max=8.00000000E+00;% kHz, est for greater than 34.9 sal max T
   %  sbe_temp_freq_min=2.50E+00;% kHz, for low temps (EMB)
   %  sbe_temp_freq_max=5.71351700E+00;% kHz, from cal for 32.5 deg T

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

% Aanderaa cal constants
     comm_oxy_type=' AA4330 '; % make and model e.g. AA4831 or AA4330
     calibcomm_optode=' SN: 799  CAL: ? ';%  Serial # and cal date
 
     optode_PhaseCoef0=-6.032104E-01;
     optode_PhaseCoef1=1.019023E+00;
     optode_PhaseCoef2=0.0;
     optode_PhaseCoef3=0.0;
 
     optode_FoilCoefA0=-3.738569E-06;
     optode_FoilCoefA1=-8.656474E-06;
     optode_FoilCoefA2=2.206881E-03;
     optode_FoilCoefA3=-2.269625E-01;
     optode_FoilCoefA4=7.958562E-04;
     optode_FoilCoefA5=-6.780085E-07;
     optode_FoilCoefA6=1.189709E+01;
     optode_FoilCoefA7=-6.533028E-02;
     optode_FoilCoefA8=1.284304E-04;
     optode_FoilCoefA9=-2.894669E-07;
     optode_FoilCoefA10=-3.249648E+02;
     optode_FoilCoefA11=2.497815E+00;
     optode_FoilCoefA12=-7.050041E-03;
     optode_FoilCoefA13=-1.363821E-05;
 
     optode_FoilCoefB0=5.316651E-07;
     optode_FoilCoefB1=3.832035E+03;
     optode_FoilCoefB2=-3.871124E+01;
     optode_FoilCoefB3=1.475505E-01;
     optode_FoilCoefB4=-3.303319E-04;
     optode_FoilCoefB5=2.289283E-05;
     optode_FoilCoefB6=-5.008295E-07;
     optode_FoilCoefB7=0.0;
     optode_FoilCoefB8=0.0;
     optode_FoilCoefB9=0.0;
     optode_FoilCoefB10=0.0;
     optode_FoilCoefB11=0.0;
     optode_FoilCoefB12=0.0;
     optode_FoilCoefB13=0.0;

% % Biospherical PAR Calibration Constants and Device Properties
%     PARCalData_manufacturer='Biospherical Instruments, Inc';% Manufacturer
%     PARCalData_serialNumber=0;%  Serial #
%     PARCalData.calDate='26-May-2011';% cal date
%     PARCalData.darkOffset=10.6;% mv
%     PARCalData.scaleFactor=6.678E+00;% Volts/uE/cm^2sec

% %  WETLabs wlbb2fl calibration constants.
%     WETLabsCalData_wlbb2fl_calinfo = ' SN: BB2FLVMT-872, CAL: 31-Oct-2011 ';
% 
%     % Backscattering cal constants - wavelength 470
%     WETLabsCalData.wlbb2fl.Scatter470.wavelength=470;
%     WETLabsCalData.wlbb2fl.Scatter470.scaleFactor=3.0160E-06;
%     WETLabsCalData.wlbb2fl.Scatter470.darkCounts=49;
%     WETLabsCalData.wlbb2fl.Scatter470.resolution=1;
% 
%     % Backscattering cal constants - wavelength 700
%     WETLabsCalData.wlbb2fl.Scatter700.wavelength=700;
%     WETLabsCalData.wlbb2fl.Scatter700.scaleFactor=3.0160E-06;
%     WETLabsCalData.wlbb2fl.Scatter700.darkCounts=49;
%     WETLabsCalData.wlbb2fl.Scatter700.resolution=1;
% 
%     % Chlorophyll cal constants
%     WETLabsCalData.wlfl3.Chlorophyll.wavelength=695;
%     WETLabsCalData.wlbb2fl.Chlorophyll.darkCounts=48;
%     WETLabsCalData.wlbb2fl.Chlorophyll.scaleFactor=1.2000E-02;
%     WETLabsCalData.wlbb2fl.Chlorophyll.maxOutput=4130;
%     WETLabsCalData.wlbb2fl.Chlorophyll.resolution=1;
%     WETLabsCalData.wlbb2fl.Chlorophyll.calTemperature=23.5;

% % WETLabs wlbb3 calibration constants.
%     WETLabsCalData_wlbb3_calinfo = ' SN: BB3IRB-991, CAL: 01-May-2014 ';
% 
%     % Backscattering cal constants - wavelength 532
%     WETLabsCalData.wlbb3.Scatter532.wavelength=532;
%     WETLabsCalData.wlbb3.Scatter532.scaleFactor=7.560E-06;
%     WETLabsCalData.wlbb3.Scatter532.darkCounts=49;
%     WETLabsCalData.wlbb3.Scatter532.resolution=1.5;
% 
%     % Backscattering cal constants - wavelength 650
%     WETLabsCalData.wlbb3.Scatter650.wavelength=650;
%     WETLabsCalData.wlbb3.Scatter650.scaleFactor=3.703E-06;
%     WETLabsCalData.wlbb3.Scatter650.darkCounts=43;
%     WETLabsCalData.wlbb3.Scatter650.resolution=1.2;
% 
%     % Backscattering cal constants - wavelength 880
%     WETLabsCalData.wlbb3.Scatter880.wavelength=800;
%     WETLabsCalData.wlbb3.Scatter880.scaleFactor=2.139E-06;
%     WETLabsCalData.wlbb3.Scatter880.darkCounts=60;
%     WETLabsCalData.wlbb3.Scatter880.resolution=1.3;

% % WETLabs wlbbfl2 calibration constants.
%     WETLabsCalData_wlbbfl2_calinfo = ' SN: BBFL2VMT-817, CAL: 28-Mar-2011 ';
% 
%     % Backscattering cal constants - wavelength 532
%     WETLabsCalData.wlbbfl2.Scatter532.wavelength=532;
%     WETLabsCalData.wlbbfl2.Scatter532.scaleFactor=8.618E-06;
%     WETLabsCalData.wlbbfl2.Scatter532.darkCounts=43;
%     WETLabsCalData.wlbbfl2.Scatter532.resolution=1.0;
% 
%     % Chlorophyll cal constants
%     WETLabsCalData.wlfl3.Chlorophyll.wavelength=695;
%     WETLabsCalData.wlbbfl2.Chlorophyll.darkCounts=44;
%     WETLabsCalData.wlbbfl2.Chlorophyll.scaleFactor=1.2200E-02;
%     WETLabsCalData.wlbbfl2.Chlorophyll.maxOutput=4130;
%     WETLabsCalData.wlbbfl2.Chlorophyll.resolution=1.0;
%     WETLabsCalData.wlbbfl2.Chlorophyll.calTemperature=21.5;
% 
%     % CDOM cal constants
%     WETLabsCalData.wlfl3.CDOM.wavelength=460;
%     WETLabsCalData.wlbbfl2.CDOM.maxOutput=4130;
%     WETLabsCalData.wlbbfl2.CDOM.scaleFactor=8.9000E-02;
%     WETLabsCalData.wlbbfl2.CDOM.darkCounts=45;
%     WETLabsCalData.wlbbfl2.CDOM.resolution=0.9;
%     WETLabsCalData.wlbbfl2.CDOM.calTemperature=21.5;

% % WETLabs wlfl3 calibration constants.
%     WETLabsCalData_wlfl3_calinfo = ' SN: FL3IRB-2884, CAL: 30-Apr-2014 ';
% 
%     % Chlorophyll cal constants ug/l/count
%     WETLabsCalData.wlfl3.Chlorophyll.wavelength=695;
%     WETLabsCalData.wlfl3.Chlorophyll.darkCounts=38;
%     WETLabsCalData.wlfl3.Chlorophyll.scaleFactor=1.2000E-02;
%     WETLabsCalData.wlfl3.Chlorophyll.maxOutput=4130;
%     WETLabsCalData.wlfl3.Chlorophyll.resolution=1;
%     WETLabsCalData.wlfl3.Chlorophyll.calTemperature=21.0;
% 
%     % CDOM cal constants ppb/count
%     WETLabsCalData.wlfl3.CDOM.wavelength=460;
%     WETLabsCalData.wlfl3.CDOM.maxOutput=4130;
%     WETLabsCalData.wlfl3.CDOM.scaleFactor=9.8400E-02;
%     WETLabsCalData.wlfl3.CDOM.darkCounts=49;
%     WETLabsCalData.wlfl3.CDOM.resolution=1.0;
%     WETLabsCalData.wlfl3.CDOM.calTemperature=21.0;
% 
%     % Phycoerythrin cal constants ppb/count
%     WETLabsCalData.wlfl3.Phycoerythrin.wavelength=570;
%     WETLabsCalData.wlfl3.Phycoerythrin.maxOutput=4130;
%     WETLabsCalData.wlfl3.Phycoerythrin.scaleFactor=4.3200E-02;
%     WETLabsCalData.wlfl3.Phycoerythrin.darkCounts=46;
%     WETLabsCalData.wlfl3.Phycoerythrin.resolution=1.0;
%     WETLabsCalData.wlfl3.Phycoerythrin.calTemperature=21.0;
%
%     % Uranine cal constants ppb/count - wavelength 530 nm
%     WETLabsCalData.wlfl3.Uranine.wavelength=530;
%     WETLabsCalData.wlfl3.Uranine.maxOutput=4130;
%     WETLabsCalData.wlfl3.Uranine.scaleFactor=4.3200E-02;
%     WETLabsCalData.wlfl3.Uranine.darkCounts=46;
%     WETLabsCalData.wlfl3.Uranine.resolution=1.0;
%     WETLabsCalData.wlfl3.Uranine.calTemperature=21.0;
%
%     % Rhodamine cal constants ppb/count - wavelength 570 nm
%     WETLabsCalData.wlfl3.Rhodamine.wavelength=570;
%     WETLabsCalData.wlfl3.Rhodamine.maxOutput=4130;
%     WETLabsCalData.wlfl3.Rhodamine.scaleFactor=4.3200E-02;
%     WETLabsCalData.wlfl3.Rhodamine.darkCounts=46;
%     WETLabsCalData.wlfl3.Rhodamine.resolution=1.0;
%     WETLabsCalData.wlfl3.Rhodamine.calTemperature=21.0;
%
%     % Phycocyanin cal constants ppb/count - wavelength 680 nm
%     WETLabsCalData.wlfl3.Phycocyanin.wavelength=680;
%     WETLabsCalData.wlfl3.Phycocyanin.maxOutput=4130;
%     WETLabsCalData.wlfl3.Phycocyanin.scaleFactor=4.3200E-02;
%     WETLabsCalData.wlfl3.Phycocyanin.darkCounts=46;
%     WETLabsCalData.wlfl3.Phycocyanin.resolution=1.0;
%     WETLabsCalData.wlfl3.Phycocyanin.calTemperature=21.0;
