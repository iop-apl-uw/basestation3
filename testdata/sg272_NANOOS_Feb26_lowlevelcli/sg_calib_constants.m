% Establishes glider calibration constants.

% This file is an example as well as documentation.
% Lines prefixed with %PARAM are parameters, the default value as the right hand side - remove "%PARAM " to enable
% Note - this file MUST be changed apprpriately for your vehicle and mission

% REQUIRED
id_str = '272';

% REQUIRED
mission_title ='NANOOS Feb 2026';

% REQUIRED
mass = 73.956; % (kg) scale weight



%
% Legato CTD
%

% Required
sg_ct_type = 4;  % Indicates a legato CTD

calibcomm = 'Legato s/n 238229, calibration 19 March 2025';

% Required for Legato as logdev or on the truck
legato_sealevel = 10194.0; % Where this is sealevel presure setting.

%
% Optode - RBRcoda T.ODO
%
%calibcomm_codaTODO='RBRcoda serialnum:237923 temp15:2025-03-15T13:54:16Z doxy24:2025-03-20T11:35:41Z opt_05:2025-03-03T14:18:09Z';
%codaTODO_c0=32.000000e-006;

%
% RBRtridente
%
calibcomm_tridentebb700bb470chla470='RBRtridente serialnum:238008 backscatter_00:2025-03-12T13:01:47Z backscatter_01:2025-03-12T13:06:10Z chlorophyll_00:2025-03-11T12:40:47Z';
