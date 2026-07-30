% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

id_str = '535';
mission_title ='RMH0726';

mass = 53.680; %%DRH or change volmax manually to 52630 (somewhere matlab is using 52787) 53.580; % (kg) scale weight
%volmax = 52633.3;

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
% GPCTD params - uncomment the following 2 lines if a GPCTD is installed in the glider
   sg_configuration=3; %  selects GPCTD configuration
   calibcomm=' GPCTD Serial #: 0022 CAL: 28-Oct-2023';%  Serial # and cal dat	

%
% Seabird un-pumped CT
%
%calibcomm = 'SBE s/n 0041, calibration 25 April 2006';
%t_g =  4.37369092e-03 ;
%t_h =  6.48722213e-04 ;
%t_i =  2.63414771e-05 ; 
%t_j =  2.83524759e-06 ;
%c_g = -9.97922732e+00 ;
%c_h =  1.12270684e+00 ;
%c_i = -2.35632554e-03 ;
%c_j =  2.37469252e-04 ;
%cpcor = -9.57e-08 ;
%ctcor =  3.25e-06 ;

% % Seabird oxygen cal constants
     comm_oxy_type='Pumped_SBE_43f';% spec "SBE_43f" or "Pumped_SBE_43f"
     calibcomm_oxygen='S/N 0208 Cal 14-Oct-23';%  Serial # and cal date
     Soc=2.250100E-04;
     Foffset=-786.37;
     o_a=-4.73600E-03;
     o_b=1.845000E-04;
     o_c=-2.24690E-06;
     o_e=0.036000E+00;
     Tau20=0.85;
     Pcor=0;

%
% Legato CTD
%

% Required
%PARAM sg_ct_type = 4;  % Indicates a legato CTD

%PARAM calibcomm = 'Legato s/n 0041, calibration 25 April 2016';

% Required for Legato as logdev or on the truck
%PARAM legato_sealevel = 10082.0; % Where this is sealevel presure setting.

% Set to 1 to use the Seaglider pressure sensor for CTD corrections
%PARAM legato_use_truck_pressure = 0; 

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
% See the list below for the canonical instrument names and calibration constant names

%PARAM remap_wetlabs_eng_cols="oldval1:newval1,oldval2:newval2"

% Note - in the "oldval", any "." should be converted to "_".
% So, if the column in the .eng file is "wlbb2fl.BB1ref", use "wlbb2fl_BB1ref" as value for the oldval.

% Example
% remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm" 
remap_wetlabs_eng_cols = "wlbbfl2_BB1ref:wlbbfl2_ref700nm,wlbbfl2_BB1sig:wlbbfl2_sig700nm,wlbbfl2_FL1ref:wlbbfl2_ref695nm,wlbbfl2_FL1sig:wlbbfl2_sig695nm,wlbbfl2_FL2ref:wlbbfl2_ref460nm,wlbbfl2_FL2sig:wlbbfl2_sig460nm" 
% where the channels are 700nm (650 for this case but not accepted by basestation!!!DRH), Chl and CDOM

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

% WETLabs wlbbfl2 calibration constants.
     wlbbfl2_calinfo = ' SN: BBFL2IRB-8491, CAL: 9/28/2023 ';
 
     % Backscattering cal constants - wavelength 650 (DOES NOT ALLOW 650 IN NAMES?? DRH)
	 wlbbfl2_sig700nm_dark_counts = 25.0; % For red scattering channel
	 wlbbfl2_sig700nm_scale_factor = 3.634E-6; % For red scattering channel
	 wlbbfl2_sig700nm_resolution_counts = 1.0; % For red scattering channel
	 %wlbbfl2_sig650nm_max_counts = 0.0; % For red scattering channel     
	 
     % Chlorophyll cal constants - wavelength=695
	 wlbbfl2_sig695nm_dark_counts = 49.0; % For chlorophyll fluorescence channel
	 wlbbfl2_sig695nm_scale_factor = 0.0121; % For chlorophyll fluorescence channel
	 wlbbfl2_sig695nm_resolution_counts = 1.0; % For chlorophyll fluorescence channel
	 wlbbfl2_sig695nm_max_counts = 4130; % For chlorophyll fluorescence channel

     % CDOM cal constants - wavelength=460
	 wlbbfl2_sig460nm_dark_counts = 49.0; % For CDOM fluorescence channel
	 wlbbfl2_sig460nm_scale_factor = 0.0911; % For CDOM fluorescence channel
	 wlbbfl2_sig460nm_resolution_counts = 1.0; % For CDOM fluorescence channel
	 wlbbfl2_sig460nm_max_counts = 4130; % For CDOM fluorescence channel     

% Here is the complete list of canonical names and associated calibration constants for WETLabs instruments

%PARAM wlbb2fl_sig470nm_dark_counts = 0.0; % For blue scattering channel
%PARAM wlbb2fl_sig470nm_scale_factor = 0.0; % For blue scattering channel
%PARAM wlbb2fl_sig470nm_resolution_counts = 0.0; % For blue scattering channel
%PARAM wlbb2fl_sig470nm_max_counts = 0.0; % For blue scattering channel
%PARAM wlbb2fl_sig532nm_dark_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_scale_factor = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_resolution_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig532nm_max_counts = 0.0; % For green scattering channel
%PARAM wlbb2fl_sig700nm_dark_counts = 0.0; % For red scattering channel
%PARAM wlbb2fl_sig700nm_scale_factor = 0.0; % For red scattering channel
%PARAM wlbb2fl_sig700nm_resolution_counts = 0.0; % For red scattering channel
%PARAM wlbb2fl_sig700nm_max_counts = 0.0; % For red scattering channel
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
%PARAM wlbb2fl_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb2fl_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb2fl_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbb2fl_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel
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
%PARAM wlbbfl2_sig460nm_dark_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbbfl2_sig460nm_scale_factor = 0.0; % For CDOM fluorescence channel
%PARAM wlbbfl2_sig460nm_resolution_counts = 0.0; % For CDOM fluorescence channel
%PARAM wlbbfl2_sig460nm_max_counts = 0.0; % For CDOM fluorescence channel
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
%PARAM wlbbfl2_sig695nm_dark_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbbfl2_sig695nm_scale_factor = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbbfl2_sig695nm_resolution_counts = 0.0; % For chlorophyll fluorescence channel
%PARAM wlbbfl2_sig695nm_max_counts = 0.0; % For chlorophyll fluorescence channel
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

