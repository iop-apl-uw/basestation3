% sg_calib_constants.m

% 2019/10/07 GBS Compass is not behaving at all.  Too few reported points and sporadic errors in
% pressure
use_auxpressure = 0;

id_str = '179';

mass = 53.962; % 53747 + 215 for beacon

mission_title ='Guam October-2019';

calibcomm = 'SBE CT Sail #0324 calibration 22-Sep-18';
t_g = 4.41207522e-003;
t_h = 6.38273745e-004;
t_i = 2.63175408e-005;
t_j = 3.25401689e-006;

c_g = -9.98406232e+000;
c_h = 1.16889638e+000;
c_i = -1.69586734e-003;
c_j = 2.13976727e-004;

sbe_cond_freq_C0 = 2926.50;

cpcor = -9.57e-08 ;
ctcor =  3.25e-06 ;

% FM_ignore rho0 = 1023.0;


% FM_ignore volmax = 52900;
% FM_ignore hd_a = 1.70782e-03;
% FM_ignore hd_b = 1.55601e-02;
% FM_ignore hd_c = 1.17156e-05;
