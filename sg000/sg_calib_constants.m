% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

id_str = '000';
mission_title ='No Mission Specified';

mass = 52.173; % (kg) scale weight
% Optional
%PARAM mass_comp = 0;

% NOTE: FlightModel will supply volmax, vbdbias, hd_a, hd_b, hd_c, hd_s, rho0, abs_compress, therm_expan, temp_ref

%
% Seabird un-pumped CT
%
calibcomm = 'SBE s/n 0041, calibration 25 April 2006';
t_g =  4.37369092e-03 ;
t_h =  6.48722213e-04 ;
t_i =  2.63414771e-05 ; 
t_j =  2.83524759e-06 ;
c_g = -9.97922732e+00 ;
c_h =  1.12270684e+00 ;
c_i = -2.35632554e-03 ;
c_j =  2.37469252e-04 ;
cpcor = -9.57e-08 ;
ctcor =  3.25e-06 ;

%
% Legato CTD
%

% Required
%PARAM sg_ct_type = 4;  % Indicates
%PARAM calibcomm = 'Legato s/n 0041, calibration 25 April 2016';

% Required for Legato as logdev or on the truck
%PARAM legato_sealevel = 10082.0; % Where this is sealevel presure setting.

% For Kongsberg/HII gliders with legato as a logdev device
%PARAM legato_config=191;

% where the values to be logical or'd together are
% channel			flag
% -----------------------------------
% conductivity      0x01        1
% temperature       0x02        2
% pressure          0x04        4
% sea pressure      0x08        8
% depth             0x10        16
% salinity          0x20        32
% counts            0x40        64
% cond cell temp    0x80       128

% Misc legato settings

% ignore any legato columns from the truck
%PARAM ignore_truck_legato = 1; 

% Optode

%
% Wetlabs
%

% iRobot/Kongsberg/HII followed differnt naming conventions for wetlabs column names.  If wetlabs data is to
% be propagated to the netcdf file, the columns must be remapped per the basestation system of naming

%PARAM remap_wetlabs_eng_cols="oldval1:newval1,oldval2:newval2"

% Example
% remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm" 
% where the channels are 700nm, Chl and CDOM

% TODO - point to docs with full name set and synonyms

% If present, the basestation will add additional columns to apply the "standard" correction to
% the wetlabs data per the cal sheet. Format for these entries is:
%
% <instrument>_<channelname>_dark_counts = <dark_counts>;
% <instrument>_<channelname>_max_counts = <max_counts>;
% <instrument>_<channelname>_resolution_counts = <resolution_counts>;
% <instrument>_<channelname>_scale_factor = <scale_factor>;

% Example
%
% wlbbfl2_sig695nm_dark_counts = 49.0;
% wlbbfl2_sig695nm_max_counts = 4130.0;
% wlbbfl2_sig695nm_resolution_counts = 1.0;
% wlbbfl2_sig695nm_scale_factor = 0.0121;
