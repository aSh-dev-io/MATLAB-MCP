function out = run_gan_hemt_twin(varargin)
%RUN_GAN_HEMT_TWIN  Drive the Stage 1 device twin through its excitation set.
%
%   OUT = RUN_GAN_HEMT_TWIN() runs every profile and returns one struct per
%   profile containing the timebase and all 16 device outputs.
%
%   OUT = RUN_GAN_HEMT_TWIN(P) uses parameter struct P instead of
%   GAN_PARAMETERS().
%
%   OUT = RUN_GAN_HEMT_TWIN(P, 'dc', VGS, VDS, TCASE) runs a single
%   constant-bias point and returns just that struct. This is the mode the
%   verifier uses to hit datasheet specification points exactly.
%
%   Profiles
%     output      ID-VDS output curves at several gate biases
%     transfer    ID-VGS transfer curve at the RON(on) test drain voltage
%     capacitance CV sweeps of Ciss, Coss and Crss, plus the charge sweeps
%     switching   double-pulse gate drive, hard switched into a resistive load
%     thermal     DC power sweep at 25 degC and 125 degC
%
%   This function writes nothing to disk; EXPORT_TWIN_OUTPUT does that.

args = varargin;
p = [];
profile = '';
dc = [];

if ~isempty(args) && (isstruct(args{1}) || isempty(args{1}))
    p = args{1};
    args(1) = [];
end

k = 1;
known = {'output', 'transfer', 'capacitance', 'charge', 'switching', 'thermal'};
while k <= numel(args)
    key = args{k};

    % A bare profile name is accepted as shorthand.
    if ischar(key) && any(strcmpi(key, known))
        profile = key;
        k = k + 1;
        continue;
    end

    if ~ischar(key)
        error('run_gan_hemt_twin:badArgument', ...
            'Expected an option name, got %s.', class(key));
    end
    if k + 1 > numel(args)
        error('run_gan_hemt_twin:badArgument', ...
            'Option "%s" is missing its value.', key);
    end
    switch lower(key)
        case 'p'
        p = args{k+1};
        case 'profile'
        profile = args{k+1};
        case 'dc'
        dc = args{k+1};
        otherwise
        error('run_gan_hemt_twin:badArgument', ...
            'Unknown option "%s".', key);
    end
    k = k + 2;
end

if isempty(p)
    p = gan_parameters();
end

root = fileparts(fileparts(mfilename('fullpath')));
modelPath = fullfile(root, 'simulink', 'gan_hemt_digital_twin.slx');
if bdIsLoaded('gan_hemt_digital_twin')
    close_system('gan_hemt_digital_twin', 0);
end
if ~isfile(modelPath)
    create_gan_hemt_twin(p);
end

cd(fullfile(root, 'simulink'));
modelName = load_system('gan_hemt_digital_twin');

try
    if ~isempty(dc)
        out = dc_point(modelName, p, dc);
    elseif ~isempty(profile)
        out = run_profile(modelName, p, profile);
    else
        names = {'output', 'transfer', 'capacitance', 'switching', 'thermal'};
        out = struct();
        for k = 1:numel(names)
            out.(names{k}) = run_profile(modelName, p, names{k});
        end
        out.meta = meta_block(p, names);
    end
catch err
    close_system(modelName, 0);
    if isenv('GAN_TWIN_DEBUG') && strcmp(getenv('GAN_TWIN_DEBUG'), '1')
        rethrow(err);
    end
    error('run_gan_hemt_twin:runFailed', ...
        'Twin run failed: %s', err.message);
end
close_system(modelName, 0);
end

%% =========================================================================
function out = run_profile(modelName, p, name)
ts = p.solver.sample_time_s;

switch name
    case 'output'
        vgsSet = [2 3 4 5 5.5];
        vds = (0:0.25:20)';
        sweep = struct('t', [], 'vgs', [], 'vds', []);
        for k = 1:numel(vgsSet)
            g = repmat(vgsSet(k), size(vds));
            d = vds;
            n0 = numel(sweep.t);
            sweep.t = [sweep.t; (n0 + (0:numel(vds)-1)') * ts];
            sweep.vgs = [sweep.vgs; g(:)];
            sweep.vds = [sweep.vds; d(:)];
        end
        out = simulate(modelName, p, sweep);

    case 'transfer'
        vgs = (0:0.05:6)';
        vds = p.dc.vds_ron_spec_V * ones(size(vgs));
        sweep = struct('t', (0:numel(vgs)-1)' * ts, 'vgs', vgs, 'vds', vds);
        out = simulate(modelName, p, sweep);

    case 'capacitance'
        vgsSet = [0 4 5];
        vds = (0:1:150)';
        sweep = struct('t', [], 'vgs', [], 'vds', []);
        for k = 1:numel(vgsSet)
            g = repmat(vgsSet(k), size(vds));
            d = vds;
            n0 = numel(sweep.t);
            sweep.t = [sweep.t; (n0 + (0:numel(vds)-1)') * ts];
            sweep.vgs = [sweep.vgs; g(:)];
            sweep.vds = [sweep.vds; d(:)];
        end
        out = simulate(modelName, p, sweep);

    case 'charge'
        % Gate-charge sweep: ramp VGS to the maximum rating at the datasheet
        % Qgd drain voltage, so QG and QGD are integrated by the twin.
        vgs = linspace(0, p.model.vgs_max_V, 481)';
        vds = p.charge.qgd_vds_V * ones(size(vgs));
        sweep = struct('t', (0:numel(vgs)-1)' * ts, 'vgs', vgs, 'vds', vds);
        out = simulate(modelName, p, sweep);

    case 'switching'
        out = double_pulse(modelName, p);

    case 'thermal'
        vgsSet = [3 5];
        vds = (0:0.5:40)';
        sweep = struct('t', [], 'vgs', [], 'vds', [], 'tcase', []);
        for tcase = [25 125]
            for k = 1:numel(vgsSet)
                g = repmat(vgsSet(k), size(vds));
                d = vds;
n0 = numel(sweep.t);
                sweep.t = [sweep.t; (n0 + (0:numel(vds)-1)') * ts];
                sweep.vgs = [sweep.vgs; g(:)];
                sweep.vds = [sweep.vds; d(:)];
                sweep.tcase = [sweep.tcase; tcase * ones(numel(vds), 1)];
            end
        end
        out = simulate(modelName, p, sweep);

    otherwise
        error('run_gan_hemt_twin:unknownProfile', ...
            'Unknown excitation profile "%s".', name);
end

out.profile = name;
end

%% =========================================================================
function out = dc_point(modelName, p, bias)
%DC_POINT  One constant-bias operating point, long enough for the Unit Delay
%         derivative chain to settle before the sample is taken.

ts = p.solver.sample_time_s;
n = 5;
t = (0:n-1)' * ts;

sweep = struct('t', t, ...
    'vgs', bias(1) * ones(n, 1), ...
    'vds', bias(2) * ones(n, 1));
if numel(bias) >= 3
    sweep.tcase = bias(3) * ones(n, 1);
else
    sweep.tcase = p.model.tnom_C * ones(n, 1);
end

out = simulate(modelName, p, sweep);

% Collapse to the settled final sample so callers see scalars.
names = fieldnames(out);
for k = 1:numel(names)
    v = out.(names{k});
    if (isnumeric(v) || islogical(v)) && numel(v) > 1
        out.(names{k}) = v(end);
    end
end
out.profile = 'dc';
end

%% =========================================================================
function out = double_pulse(modelName, p)
%DOUBLE_PULSE  Hard-switched double-pulse gate drive into a resistive load.
%   The drain is held by the load line: Vds = Vbus - Rload*ID. The twin is
%   therefore run as a switched current-into-resistance loop, which is the
%   only way a resistive load appears without adding a feedback path to the
%   device model itself.

ts = p.solver.sample_time_s;
vbus = p.switching.vbus_V;
rload = p.switching.rload_ohm;
vgOff = p.switching.vgs_off_V;
vgOn = p.switching.vgs_on_V;
idRef = 840;                        % ID,pulse rating from the dataset

% Solve the load line for the on-state drain voltage at the rated current.
f = @(vds) id_at(p, vgOn, vds) - (vbus - vds) / rload;
vdsOn = fzero(f, [0.1, vbus - 1]);

% Sample counts, so every waveform edge lands exactly on the solver grid.
nOn = round(p.switching.t_on_s / ts);
nOff = round(p.switching.t_off_s / ts);
nRise = p.switching.n_rise;
nCycles = p.switching.n_cycles;

total = nOff + nCycles * (2*nRise + nOn + nOff);
t = (0:total-1)' * ts;

vg = zeros(total, 1);
i = nOff + 1;
for c = 1:nCycles
    seg = i + (0:nRise-1)';
    vg(seg) = linspace(vgOff, vgOn, nRise)';
    i = i + nRise;

    seg = i + (0:nOn-1)';
    vg(seg) = vgOn;
    i = i + nOn;

    seg = i + (0:nRise-1)';
    vg(seg) = linspace(vgOn, vgOff, nRise)';
    i = i + nRise + nOff;
end

% Trace the resistive load line sample by sample with the analytic replica.
% This only shapes the stimulus; the device response comes from the twin.
%
% The operating point is the root of
%     f(Vds) = Id_replica(Vds) - (Vbus - Vds)/Rload
% Because the replica current rises with Vds while the load current falls,
% f is monotonically increasing, so exactly one root exists in [0, Vbus] and
% bisection always converges. Plain fixed-point iteration does NOT converge
% here: the two curves cross at a shallow angle, so it alternates between
% the device-off point and a hard-clamped Vds = 0.
vd = zeros(total, 1);
for k = 1:total
    lo = 0;
    hi = vbus;
    for it = 1:60
        mid = 0.5 * (lo + hi);
        if id_at(p, vg(k), mid) - (vbus - mid) / rload > 0
            hi = mid;
        else
            lo = mid;
        end
    end
    vd(k) = 0.5 * (lo + hi);
end

sweep = struct('t', t, 'vgs', vg, 'vds', vd, ...
    'tcase', p.model.tnom_C * ones(size(t)));
out = simulate(modelName, p, sweep);
out.vbus_V = vbus;
out.rload_ohm = rload;
out.ild_ref_A = idRef;
out.vds_on_loadline_V = vdsOn;
end

%% =========================================================================
function id = id_at(p, vgs, vds)
%ID_AT  Analytic replica of the channel model, used only to shape the
%      excitation waveforms before the Simulink run. Not a twin output.

vov = vgs - p.model.vth_V;
vc = 0.5 * vov * (1 + tanh(vov / (2 * p.model.vsmooth_V)));
vdsat = min(max(vc, 0), p.model.vdsat_V);
vdc = min(abs(vds), vdsat);
id = p.model.k_amp_per_v2 * (vc * vdc - 0.5 * vdc^2) * ...
    (1 + abs(vds) / p.model.va_V);
end

%% =========================================================================
function out = simulate(modelName, p, sweep)
%SIMULATE  Run one excitation and collect all device outputs.

t = sweep.t;
if t(1) ~= 0
    t = t - t(1);
end

u = [t, sweep.vgs(:), sweep.vds(:)];
if isfield(sweep, 'tcase') && ~isempty(sweep.tcase)
    u = [u, sweep.tcase(:)];
else
    u = [u, p.model.tnom_C * ones(numel(t), 1)];
end

varName = ['stage1_in_' char(97 + mod(randi(26), 26))];
assignin('base', varName, u);

signals = outNames_local();

set_param(modelName, 'LoadExternalInput', 'on', 'ExternalInput', varName, ...
    'StopTime', num2str(t(end), '%.17g'));

% Called from inside a MATLAB function, Simulink delivers the To Workspace
% outputs into this function's own workspace, so harvest them from here.
sim(modelName);

out = struct();
timeVec = [];
for k = 1:numel(signals)
    name = signals{k};
    if exist(name, 'var') ~= 1
        error('run_gan_hemt_twin:missingOutput', ...
            'The twin did not produce output "%s".', name);
    end
    m = eval(name);
    if size(m, 2) >= 2
        if isempty(timeVec)
            timeVec = m(:, end);
        end
        out.(name) = m(:, 1:end-1);
    else
        out.(name) = m;
    end
end
if isempty(timeVec)
    timeVec = t;
end
out.time = timeVec;
end

%% =========================================================================
function names = outNames_local()
names = {'Vgs', 'Vds', 'ID', 'IG', 'IS', 'RON', 'Pcond', 'Psw', 'Ploss', ...
    'Tj', 'Tcase', 'Qg', 'Qgd', 'Ciss', 'Coss', 'Crss'};
end

%% =========================================================================
function m = meta_block(p, profileNames)
m = struct( ...
    'part_number', p.meta.device_part_number, ...
    'generated_by', 'run_gan_hemt_twin', ...
    'matlab_release', version('-release'), ...
    'sample_time_s', p.solver.sample_time_s, ...
    'tnom_C', p.model.tnom_C, ...
    'profiles', {profileNames}, ...
    'thermal_note', 'Thermal validation not supported by the provided dataset.');
end