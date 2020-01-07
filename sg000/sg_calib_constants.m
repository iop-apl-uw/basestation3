% sg_calib_constants.m
% Establishes glider calibration constants.

% This file is an example and MUST be changed apprpriately for your vehicle.

id_str = '000';
mission_title =' 2006';

mass = 52.173; % (kg) scale weight
mass_comp = 0;

% NOTE: FlightModel will supply volmax, vbdbias, hd_a, hd_b, hd_c, hd_s, rho0, abs_compress, therm_expan, temp_ref

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

calibcomm_oxygen = 'SBE 43F s/n 0106 calibation 1 April 2006';
Soc = 2.1921e-04;
Boc = 0.0;
Foffset = -825.6362;
TCor = 0.0017;
PCor = 1.350e-04;

