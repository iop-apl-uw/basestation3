% Last edited on 28-June-2024 S.Poulos 
% Returned from UW IOP 
% Template file for sg_calib_constants.m,

% basic glider and mission params
    id_str='512';
    mission_title='Mission11 PacIOOS_1';
    mass=52.960;% kg 
%    volmax=52030;% cc
%    rho0=1027.50;% kg/m3

% initial hydrodynamic model params
%    hd_a=3.83600000E-03;
%    hd_b=1.00780000E-02;
%    hd_c=9.85000000E-06;

% software limits from cal sheet
    pitch_min_cnts=215;
    pitch_max_cnts=3897;
    roll_min_cnts=158;
    roll_max_cnts=3882;
    vbd_min_cnts=500;
    vbd_max_cnts=3960;
    vbd_cnts_per_cc=-4.076707;

 % Seabird CT Sail sensor cal constants
     calibcomm=' Serial #: 0073  CAL: 17-Apr-2024';%  Serial # and cal date
     t_g=4.29608656e-003;
     t_h=6.31832592e-004;
     t_i=2.51693688e-005;
     t_j=2.77567381e-006;
     c_g=-1.01615894e+001;
     c_h=1.12934620e+000;
     c_i=-2.21304476e-003;
     c_j=2.31710257e-004;
     cpcor =-9.5700000E-08;
     ctcor =3.2500000E-06;
     sbe_cond_freq_min=3.00570E+00;% kHz, from cal for 0 salinity
     sbe_cond_freq_max=7.91311E+00;% kHz, est for greater than 34.9 sal max T
     sbe_temp_freq_min=2.904505+00;% kHz, from cal for 1 deg T
     sbe_temp_freq_max=5.56452E+00;% kHz, from cal for 32.5 deg T

 % Seabird oxygen cal constants
     comm_oxy_type='SBE_43f';% spec "SBE_43f" or "Pumped_SBE_43f"
     calibcomm_oxygen='SN: 43F 0221 CAL: 25-Jan-2024';%  Serial # and cal date
     Soc= 2.663783e-004;
     Foffset=-8.498901E+02;
     o_a=-4.221797e-003;
     o_b=1.996272e-004;
     o_c=-2.824067e-006;
     o_e=3.6000E-02;
     Tau20=1.12000e+000;
     Pcor=0;

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
     calibcomm_optode=' SN: 199  CAL: 04-Mar-2016 ';%  Serial # and cal date
 
     optode_PhaseCoef0=-5.95434E+00;
     optode_PhaseCoef1=1.10829E+00;
     optode_PhaseCoef2=0.0;
     optode_PhaseCoef3=0.0;
 
     optode_FoilCoefA0=-3.604788E-06;
     optode_FoilCoefA1=-6.843659E-06;
     optode_FoilCoefA2=1.839203E-03;
     optode_FoilCoefA3=-1.984442E-01;
     optode_FoilCoefA4=8.121225E-04;
     optode_FoilCoefA5=-1.220733E-06;
     optode_FoilCoefA6=1.086894E+01;
     optode_FoilCoefA7=-7.093984E-02;
     optode_FoilCoefA8=2.810467E-04;
     optode_FoilCoefA9=-1.328850E-06;
     optode_FoilCoefA10=-3.093750E+02;
     optode_FoilCoefA11=2.923687E+00;
     optode_FoilCoefA12=-2.222011E-02;
     optode_FoilCoefA13=2.146338E-04;
 
     optode_FoilCoefB0=-7.934825E-07;
     optode_FoilCoefB1=3.792412E+03;
     optode_FoilCoefB2=-4.935136E+01;
     optode_FoilCoefB3=6.335210E-01;
     optode_FoilCoefB4=-1.085494E-02;
     optode_FoilCoefB5=1.218953E-04;
     optode_FoilCoefB6=-7.344973E-07;
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

% Wetlabs
%

% iRobot/Kongsberg/HII followed differnt naming conventions for wetlabs column names.  If wetlabs data is to
% be propagated to the netcdf file, the columns must be remapped per the basestation system of naming
% See the list below for the canonical instrument names and calibration constant names

%PARAM remap_wetlabs_eng_cols="oldval1:newval1,oldval2:newval2"

% Note - in the "oldval", any "." should be converted to "_".
% So, if the column in the .eng file is "wlbb2fl.BB1ref", use "wlbb2fl_BB1ref" as value for the oldval.

% Example
% remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm" 
% where the channels are 700nm, Chl and CDOM

%   Last test 1 Jul 2024 showed this in *.dat
%        470nm                           700nm                               Chloro - 695      & 2nd bbfl2,  ref  0nm   1016nm   166nm (not really reading nm - just place holder)
%,wlbb2fl.BB1ref, wlbb2fl.BB1sig,  wlbb2fl.BB2ref,  wlbb2fl.BB2sig,  wlbb2fl.FL1ref, wlbb2fl.FL1sig,  wlbb2fl.temp, \  
%        wlbbfl2.BB1ref,wlbbfl2.BB1sig,wlbbfl2.FL1ref,wlbbfl2.FL1sig,wlbbfl2.FL2ref,wlbbfl2.FL2sig,wlbbfl2.temp

remap_wetlabs_eng_cols="wlbb2fl_BB1ref:wlbb2fl_ref470nm,wlbb2fl_BB1sig:wlbb2fl_sig470nm,wlbb2fl_BB2ref:wlbb2fl_ref700nm,wlbb2fl_BB2sig:wlbb2fl_sig700nm,wlbb2fl_FL1ref:wlbb2fl_ref695nm,wlbb2fl_FL1sig:wlbb2fl_sig695nm,wlbb2fl_temp:wlbb2fl_temp,wlbbfl2_BB1ref:wlbbfl2_ref650nm,wlbbfl2_BB1sig:wlbbfl2_sig650nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_ FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm,wlbbfl2_temp:wlbbfl2_temp"

% If present, the basestation will add additional columns to apply the "standard" correction to
% the wetlabs data per the cal sheet. Format for these entries is:
%
% <instrument>_<channelname>_dark_counts = <dark_counts>;
% <instrument>_<channelname>_max_counts = <max_counts>;
% <instrument>_<channelname>_resolution_counts = <resolution_counts>;
% <instrument>_<channelname>_scale_factor = <scale_factor>;

% Example

% wlbbfl2_sig695nm_dark_counts = 49.0;
% wlbbfl2_sig695nm_max_counts = 4130.0;
% wlbbfl2_sig695nm_resolution_counts = 1.0;
% wlbbfl2_sig695nm_scale_factor = 0.0121;

% Here is the complete list of canonical names and associated calibration constants for WETLabs instruments

%  WETLabs wlbb2fl calibration constants.
     WETLabsCalData_wlbb2fl_calinfo = ' SN: BB2FLIRB-1390, CAL: 13-Jan-2016 ';

    % Backscattering cal constants - wavelength 470
wlbb2fl_sig470nm_dark_counts = 45.0; % For blue scattering channel
wlbb2fl_sig470nm_scale_factor = 1.081E-05; % For blue scattering channel
wlbb2fl_sig470nm_resolution_counts = 1.0; % For blue scattering channel
wlbb2fl_sig470nm_max_counts = 0.0; % For blue scattering channel

     % Backscattering cal constants - wavelength 700
wlbb2fl_sig700nm_dark_counts = 53.0; % For red scattering channel
wlbb2fl_sig700nm_scale_factor = 3.003E-06; % For red scattering channel
wlbb2fl_sig700nm_resolution_counts = 1.2; % For red scattering channel
wlbb2fl_sig700nm_max_counts = 0.0; % For red scattering channel

     % Chlorophyll cal constants   wavelength 695
%     WETLabsCalData.wlbb2fl.Chlorophyll.wavelength=695;
wlbb2fl_sig695nm_dark_counts = 37; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_scale_factor = 1.1900E-02; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_resolution_counts = 1.7; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_max_counts = 4140.0; % For chlorophyll fluorescence channel
wlbb2fl_sig695nm_caltemp = 22.3; % For chlorophyll fluorescence channel
%
%PARAM wlbb2fl_sig532nm_dark_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_scale_factor = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_resolution_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_max_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig880nm_dark_counts = 0.0; % For infrared scattering channel
%PARAM wlbb2fl_sig880nm_scale_factor = 0.0; % For infrared scattering channel
%PARAM wlbb2fl_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
%PARAM wlbb2fl_sig880nm_max_counts = 0.0; % For infrared scattering channel
%PARAM wlbb2fl_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb2fl_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
%PARAM wlbb2fl_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb2fl_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb2fl_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb2fl_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
%PARAM wlbb2fl_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb2fl_sig530nm_max_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb2fl_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb2fl_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb2fl_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb2fl_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb2fl_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb2fl_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb2fl_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb2fl_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

% % % % % %   2nd Wetlabs  

WETLabsCalData_wlbbfl2_calinfo = ' SN: BBFL2VMT-946, CAL: 24-Nov-2015 ';

       % Backscattering cal constants - wavelength 650
wlbbfl2_sig650nm_dark_counts = 42.0; % For red scattering channel 
wlbbfl2_sig650nm_scale_factor = 4.535E-06; % For red scattering channel 
wlbbfl2_sig650nm_resolution_counts = 1.1; % For red scattering channel 
wlbbfl2_sig650nm_max_counts = 0.0; % For For red scattering channel 

        % CDOM cal constants  (for 460nm CDOM fluoroescence)
wlbbfl2_sig460nm_dark_counts = 28.0; % For CDOM fluorescence channel
wlbbfl2_sig460nm_scale_factor = 6.778E-02; % For CDOM fluorescence channel
wlbbfl2_sig460nm_resolution_counts = 1.4; % For CDOM fluorescence channel
wlbbfl2_sig460nm_max_counts = 4130.0; % For CDOM fluorescence channel
wlbbfl2_sig460nm_caltemp = 20.0; % For CDOM temp calibration channel

       % Chlorophyll cal constants
wlbbfl2_sig695nm_dark_counts = 48.0; % For chlorophyll fluorescence channel
wlbbfl2_sig695nm_scale_factor = 1.1800E-02; % For chlorophyll fluorescence channel
wlbbfl2_sig695nm_resolution_counts = 1.0; % For chlorophyll fluorescence channel
wlbbfl2_sig695nm_max_counts = 4130.0; % For chlorophyll fluorescence channel
wlbbfl2_sig695nm_caltemp = 20.0; % For chlorophyll fluorescence channel

%PARAM wlbbfl2_sig470nm_dark_counts = 0.0; % For blue scattering channel
%PARAM wlbbfl2_sig470nm_scale_factor = 0.0; % For blue scattering channel
%PARAM wlbbfl2_sig470nm_resolution_counts = 0.0; % For blue scattering channel
%PARAM wlbbfl2_sig470nm_max_counts = 0.0; % For blue scattering channel
%PARAM wlbbfl2_sig532nm_dark_counts = 0.0; % For green scattering channel
%PARAM wlbbfl2_sig532nm_scale_factor = 0.0; % For green scattering channel
%PARAM wlbbfl2_sig532nm_resolution_counts = 0.0; % For green scattering channel
%PARAM wlbbfl2_sig532nm_max_counts = 0.0; % For green scattering channel
%PARAM wlbbfl2_sig700nm_dark_counts = 0.0; % For red scattering channel
%PARAM wlbbfl2_sig700nm_scale_factor = 0.0; % For red scattering channel
%PARAM wlbbfl2_sig700nm_resolution_counts = 0.0; % For red scattering channel
%PARAM wlbbfl2_sig700nm_max_counts = 0.0; % For red scattering channel
%PARAM wlbbfl2_sig880nm_dark_counts = 0.0; % For infrared scattering channel
%PARAM wlbbfl2_sig880nm_scale_factor = 0.0; % For infrared scattering channel
%PARAM wlbbfl2_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
%PARAM wlbbfl2_sig880nm_max_counts = 0.0; % For infrared scattering channel
%PARAM wlbbfl2_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbbfl2_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
%PARAM wlbbfl2_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbbfl2_sig530nm_max_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbbfl2_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbbfl2_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbbfl2_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbbfl2_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbbfl2_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbbfl2_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbbfl2_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbbfl2_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel

%  3rd type of Wetlabs ECO Puck
%PARAM wlbb3_sig470nm_dark_counts = 0.0; % For blue scattering channel
%PARAM wlbb3_sig470nm_scale_factor = 0.0; % For blue scattering channel
%PARAM wlbb3_sig470nm_resolution_counts = 0.0; % For blue scattering channel
%PARAM wlbb3_sig470nm_max_counts = 0.0; % For blue scattering channel
%PARAM wlbb3_sig532nm_dark_counts = 0.0; % For green scattering channel
%PARAM wlbb3_sig532nm_scale_factor = 0.0; % For green scattering channel
%PARAM wlbb3_sig532nm_resolution_counts = 0.0; % For green scattering channel
%PARAM wlbb3_sig532nm_max_counts = 0.0; % For green scattering channel
%PARAM wlbb3_sig700nm_dark_counts = 0.0; % For red scattering channel
%PARAM wlbb3_sig700nm_scale_factor = 0.0; % For red scattering channel
%PARAM wlbb3_sig700nm_resolution_counts = 0.0; % For red scattering channel
%PARAM wlbb3_sig700nm_max_counts = 0.0; % For red scattering channel
%PARAM wlbb3_sig880nm_dark_counts = 0.0; % For infrared scattering channel
%PARAM wlbb3_sig880nm_scale_factor = 0.0; % For infrared scattering channel
%PARAM wlbb3_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
%PARAM wlbb3_sig880nm_max_counts = 0.0; % For infrared scattering channel
%PARAM wlbb3_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb3_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
%PARAM wlbb3_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb3_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbb3_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb3_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
%PARAM wlbb3_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb3_sig530nm_max_counts = 0.0; % For uranine fluorescence channel
%PARAM wlbb3_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb3_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb3_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb3_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlbb3_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb3_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb3_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb3_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlbb3_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb3_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb3_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb3_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlfl3_sig470nm_dark_counts = 0.0; % For blue scattering channel
%PARAM wlfl3_sig470nm_scale_factor = 0.0; % For blue scattering channel
%PARAM wlfl3_sig470nm_resolution_counts = 0.0; % For blue scattering channel
%PARAM wlfl3_sig470nm_max_counts = 0.0; % For blue scattering channel
%PARAM wlfl3_sig532nm_dark_counts = 0.0; % For green scattering channel
%PARAM wlfl3_sig532nm_scale_factor = 0.0; % For green scattering channel
%PARAM wlfl3_sig532nm_resolution_counts = 0.0; % For green scattering channel
%PARAM wlfl3_sig532nm_max_counts = 0.0; % For green scattering channel
%PARAM wlfl3_sig700nm_dark_counts = 0.0; % For red scattering channel
%PARAM wlfl3_sig700nm_scale_factor = 0.0; % For red scattering channel
%PARAM wlfl3_sig700nm_resolution_counts = 0.0; % For red scattering channel
%PARAM wlfl3_sig700nm_max_counts = 0.0; % For red scattering channel
%PARAM wlfl3_sig880nm_dark_counts = 0.0; % For infrared scattering channel
%PARAM wlfl3_sig880nm_scale_factor = 0.0; % For infrared scattering channel
%PARAM wlfl3_sig880nm_resolution_counts = 0.0; % For infrared scattering channel
%PARAM wlfl3_sig880nm_max_counts = 0.0; % For infrared scattering channel
%PARAM wlfl3_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlfl3_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
%PARAM wlfl3_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlfl3_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlfl3_sig530nm_dark_counts = 0.0; % For uranine fluorescence channel
%PARAM wlfl3_sig530nm_scale_factor = 0.0; % For uranine fluorescence channel
%PARAM wlfl3_sig530nm_resolution_counts = 0.0; % For uranine fluorescence channel
%PARAM wlfl3_sig530nm_max_counts = 0.0; % For uranine fluorescence channel
%PARAM wlfl3_sig570nm_dark_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlfl3_sig570nm_scale_factor = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlfl3_sig570nm_resolution_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlfl3_sig570nm_max_counts = 0.0; % For phycoerythrin/rhodamine fluorescence channel
%PARAM wlfl3_sig680nm_dark_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlfl3_sig680nm_scale_factor = 0.0; % For phycocyanin fluorescence channel
%PARAM wlfl3_sig680nm_resolution_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlfl3_sig680nm_max_counts = 0.0; % For phycocyanin fluorescence channel
%PARAM wlfl3_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlfl3_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
%PARAM wlfl3_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlfl3_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel


 %  WETLabs Older form  wlbb2fl calibration constants.
%     WETLabsCalData_wlbb2fl_calinfo = ' SN: BB2FLIRB-1390, CAL: 13-Jan-2016 ';
 
     % Backscattering cal constants - wavelength 470
%     WETLabsCalData.wlbb2fl.Scatter470.wavelength=470;
%     WETLabsCalData.wlbb2fl.Scatter470.scaleFactor=1.081e-005;
%     WETLabsCalData.wlbb2fl.Scatter470.darkCounts=45;
%     WETLabsCalData.wlbb2fl.Scatter470.resolution=1.0;
 
     % Backscattering cal constants - wavelength 700
%     WETLabsCalData.wlbb2fl.Scatter700.wavelength=700;
%     WETLabsCalData.wlbb2fl.Scatter700.scaleFactor=3.003e-06;
%     WETLabsCalData.wlbb2fl.Scatter700.darkCounts=53;
%     WETLabsCalData.wlbb2fl.Scatter700.resolution=1.2;
 
     % Chlorophyll cal constants
%     WETLabsCalData.wlbb2fl.Chlorophyll.wavelength=695;
%     WETLabsCalData.wlbb2fl.Chlorophyll.darkCounts=37;
%     WETLabsCalData.wlbb2fl.Chlorophyll.scaleFactor=1.1900e-02;
%     WETLabsCalData.wlbb2fl.Chlorophyll.maxOutput=4140;
%     WETLabsCalData.wlbb2fl.Chlorophyll.resolution=1.7;
%     WETLabsCalData.wlbb2fl.Chlorophyll.calTemperature=22.3;

 % WETLabs wlbbfl2 calibration constants.
%    WETLabsCalData_wlbbfl2_calinfo = ' SN: BBFL2VMT-946, CAL: 24-Nov-2015 ';
 
     % Backscattering cal constants - wavelength 650
%    WETLabsCalData.wlbbfl2.Scatter650.wavelength=650;
%    WETLabsCalData.wlbbfl2.Scatter650.scaleFactor=4.5350e-06;
%    WETLabsCalData.wlbbfl2.Scatter650.darkCounts=42;
%    WETLabsCalData.wlbbfl2.Scatter650.resolution=1.1;
 
     % Chlorophyll cal constants
%    WETLabsCalData.wlbbfl2.Chlorophyll.wavelength=695;
%    WETLabsCalData.wlbbfl2.Chlorophyll.darkCounts=48;
%    WETLabsCalData.wlbbfl2.Chlorophyll.scaleFactor=1.1800E-02;
%    WETLabsCalData.wlbbfl2.Chlorophyll.maxOutput=4130;
%    WETLabsCalData.wlbbfl2.Chlorophyll.resolution=1.0;
     WETLabsCalData.wlbbfl2.Chlorophyll.calTemperature=20.0;
 
     % CDOM cal constants
%    WETLabsCalData.wlbbfl2.CDOM.wavelength=460;
%    WETLabsCalData.wlbbfl2.CDOM.maxOutput=4130;
%    WETLabsCalData.wlbbfl2.CDOM.scaleFactor=6.7700E-02;
%    WETLabsCalData.wlbbfl2.CDOM.darkCounts=28;
%    WETLabsCalData.wlbbfl2.CDOM.resolution=1.4;
%    WETLabsCalData.wlbbfl2.CDOM.calTemperature=20.0;
	 
