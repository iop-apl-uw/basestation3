
% basic glider and mission params				
id_str 	=	'160'	;	
mass = 55.614;  % scale wt 
% volmax = 54976 + 69; % target scale wt after ballasting with old rudder
		     % was 55518. Actual was 55533. Predicted volmax
		     % was 54974.5. Add 1.5 for extra lead and 69 cc
		     % for difference in volume with split rudder.
mission_title	= 'Shilshole February 2013';
rho0        = 1023.0;
therm_expan = 70.5e-6;    % SG thermal expansion coeff [/degree C]
temp_ref    = 15;  % reference temperature for SG thermal expansion calculation
abs_compress = 4.18e-6;  % SG vehicle compressibility
pitchbias   = 0;	% pitch reference in regressions

% software motor limits				
pitch_min_cnts 	=	155	;
pitch_max_cnts 	=	3900	;	
roll_min_cnts 	=	220	;	
roll_max_cnts 	=	3200	;	
vbd_min_cnts 	=	190	;	
vbd_max_cnts 	=	3660	;	
vbd_cnts_per_cc =	-4.0767	;				

new_C_VBD = 2650;
volmax = mass*1000/(rho0/1000) - (new_C_VBD - vbd_min_cnts)/vbd_cnts_per_cc;

% CT sensors cal constants				
calibcomm ='SN 0067 cal 31-Oct-12';	% SN and cal date
t_g 	= 	4.35676049e-003;	
t_h 	=	6.35628902e-004;
t_i 	=	2.46019009e-005;
t_j 	=	2.61458249e-006;

c_g 	=     	-9.88339309e+000; 
c_h 	=	1.10298752e+000;
c_i 	=      -1.14426153e-003;
c_j 	=	1.79030161e-004;

cpcor 	=	-9.5700000E-08	;	
ctcor 	=	3.2500000E-06	;	

sbe_cond_freq_min =	2.8	; % kHz, from cal for 0 salinity
sbe_cond_freq_max =	8.5	; % kHz, est for greater than 32.5 
sbe_temp_freq_min =	2.8	; % kHz, from cal for 1 deg T
sbe_temp_freq_max =	7.4	; % kHz, from cal for 32.5 deg T
				
% SBE oxygen cal constants				
comm_oxy_type= 'SBE 43F';
calibcomm_oxygen = 'SN 43F0145, cal 15-Apr-08'; % SN and cal date
Soc 	=	2.5708E-04	;	
Foffset =	-8.6340E+02	;	
%Boc	=	0.0	;
%Tcor	=	4.0e-4	;	
%Pcor	=	1.35e-4	;	
% other type of parameters from SBE oxygen
o_a = -1.2395E-03;
o_b = 1.4642E-04;
o_c = -2.9991E-06;
o_e = 3.60E-02;
Tau20 = 1.62;
PCor = 0;   % used as flag to force usage of new algorithm

% this glider carries WET Labs BB2F-VMG SN 156 

% initial hydrodynamic model params				
hd_a 	=	0.003836;
hd_b 	=	0.010078;	 
hd_c 	=	9.85E-06; 

hd_a = 3.17702e-03;
hd_b = 1.18334e-02;
hd_c = 1.71709e-05;
