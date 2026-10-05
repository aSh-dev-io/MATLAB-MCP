function out = gan_init()
%GAN_INIT  Bootstrap the Stage-1 GaN HEMT digital twin.
%
%   out = GAN_INIT() adds the Stage-1 entry points to the MATLAB path, loads
%   the device parameter set, confirms the Simulink package is available and
%   returns everything the other Stage-1 entry points need.
%
%   Stage 1 produces a device-level twin of the onsemi NTLEF2D2N15GN1 and a
%   standardized continuous output layer. It does not perform degradation
%   prediction or health-state assessment.

thisDir = fileparts(mfilename('fullpath'));
projectRoot = fileparts(thisDir);
matlabDir   = thisDir;
slxDir      = fullfile(projectRoot, 'simulink');
resDir      = fullfile(projectRoot, 'results');
plotDir     = fullfile(projectRoot, 'plots');

addpath(thisDir);

for d = {slxDir, resDir, plotDir}
    if ~exist(d{1}, 'dir')
        mkdir(d{1});
    end
end

p = gan_parameters();

if license('test', 'Simulink') ~= 1
    error('gan_init:noSimulink', ...
        'Simulink is not available. The twin model cannot be built or run.');
end

out = struct( ...
    'params',      p, ...
    'projectRoot', projectRoot, ...
    'matlabDir',   matlabDir, ...
    'slxDir',      slxDir, ...
    'resultsDir',  resDir, ...
    'plotsDir',    plotDir, ...
    'modelFile',   fullfile(slxDir, 'gan_hemt_digital_twin.slx'));

fprintf('Stage 1 GaN HEMT device digital twin\n');
fprintf('  device          : %s (%s)\n', p.meta.device_part_number, p.meta.manufacturer);
fprintf('  datasheet       : %s\n', p.meta.datasheet_revision);
fprintf('  model version   : %s\n', p.meta.model_version);
fprintf('  project root    : %s\n', projectRoot);
fprintf('  degradation     : not modelled (out of Stage-1 scope)\n');
fprintf('  health state    : not modelled (out of Stage-1 scope)\n');
end