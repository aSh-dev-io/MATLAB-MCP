function modelFile = create_gan_hemt_twin(p)
%CREATE_GAN_HEMT_TWIN  Build the Stage-1 GaN HEMT device digital twin.
%
%   modelFile = CREATE_GAN_HEMT_TWIN(p) builds simulink/gan_hemt_digital_twin.slx
%   from the parameter set returned by gan_parameters and saves it.
%
%   MODEL STRUCTURE
%     The top level is deliberately shallow: three excitation inports, one
%     twin subsystem, and the device output ports. The twin is a genuine
%     three-terminal device model, not a converter and not an ideal switch.
%
%       Vgs_cmd  Vds_cmd  Tcase_cmd
%              |    |      |
%       [   GaN_HEMT_Twin   ]   <- the digital twin
%              |    |      |
%        Vgs  Vds  ID  IG  IS  RON  Pcond  Psw  Ploss  Tj  Tcase  Qg  Qgd
%        Ciss Coss Crss
%
%     Inside the twin the three physical parts of the device are separated:
%
%       capacitance_model  depletion capacitances Cgs(Vgs), Cgd(Vds),
%                          Cds(Vds) and their charges, giving the gate,
%                          Miller and drain displacement currents
%       channel_model      square-law channel with velocity saturation,
%                          output conductance and gate/drain leakage
%       terminals_losses   terminal current closure, conduction and
%                          switching loss, on-resistance
%
%     Every physics block receives its constants from a self-contained
%     struct-valued Constant block, so the saved model runs without any
%     MATLAB workspace variables.
%
%   NOT MODELLED: degradation, health state, DHI and RUL are out of Stage-1
%   scope. No thermal network is built because every thermal resistance in
%   the datasheet is printed as TBD, so the model is isothermal at the
%   supplied case temperature.

if nargin < 1 || isempty(p)
    p = gan_parameters();
end

modelName = 'gan_hemt_digital_twin';
thisDir   = fileparts(mfilename('fullpath'));
slxDir    = fullfile(fileparts(thisDir), 'simulink');
modelFile = fullfile(slxDir, [modelName '.slx']);

drop_stale_model(modelName, modelFile);
load_system('simulink');
load_system('simulink/Ports & Subsystems');
load_system('simulink/Math Operations');
load_system('simulink/Discrete');
load_system('simulink/Sources');
load_system('simulink/User-Defined Functions');
new_system(modelName);
open_system(modelName);

add_block('simulink/Ports & Subsystems/Subsystem', [modelName '/GaN_HEMT_Twin'], 'Position', [170 120 350 200]);
sub = [modelName '/GaN_HEMT_Twin'];

% A freshly created subsystem carries default In1/Out1 blocks. Remove them so
% the twin exposes exactly its own ports.
delete_block([sub '/In1']);
delete_block([sub '/Out1']);

outNames = { 'Vgs', 'Vds', 'ID', 'IG', 'IS', 'RON', 'Pcond', 'Psw', 'Ploss', ...
             'Tj', 'Tcase', 'Qg', 'Qgd', 'Ciss', 'Coss', 'Crss'};

%% ------------------------------------------------------------------------
%  Twin subsystem inputs
%  ------------------------------------------------------------------------
add_block('simulink/Ports & Subsystems/In1', [sub '/Vgs_in'],  'Position', [30  60  60  80], 'PortName', 'Vgs_in', 'PortDimensions', '1');
add_block('simulink/Ports & Subsystems/In1', [sub '/Vds_in'],  'Position', [30 110  60 130], 'PortName', 'Vds_in', 'PortDimensions', '1');
add_block('simulink/Ports & Subsystems/In1', [sub '/Tcase_in'],'Position', [30 160  60 180], 'PortName', 'Tcase_in', 'PortDimensions', '1');

%% ------------------------------------------------------------------------
%  Terminal-derivative sensing (unit delay + difference)
% -------------------------------------------------------------------------
add_block('simulink/Discrete/Unit Delay', [sub '/Vgs_prev'], 'Position', [120 55 200 75], ...
    'SampleTime', num2str(p.solver.sample_time_s));
add_block('simulink/Discrete/Unit Delay', [sub '/Vds_prev'], 'Position', [120 105 200 125], ...
    'SampleTime', num2str(p.solver.sample_time_s));
add_block('simulink/Math Operations/Sum', [sub '/dVgs'], 'Position', [240 67 270 113], 'Inputs', '+-');
add_block('simulink/Math Operations/Sum', [sub '/dVds'], 'Position', [240 117 270 163], 'Inputs', '+-');

add_block('simulink/Sources/Constant', [sub '/Ts'], 'Position', [240 20 300 46], ...
    'Value', num2str(p.solver.sample_time_s));

%% ------------------------------------------------------------------------
%  Self-contained parameter block
% -------------------------------------------------------------------------
%  One numeric row vector carries every physics constant. Index positions are
%  fixed by p.model.vector_names in gan_parameters.m:
%    1 cgd0      2 vjg       3 coss0     4 vjc       5 cgs0     6 vgsc
%    7 vth       8 vgs_min   9 k        10 vsmooth  11 vdsat   12 va
%   13 idss     14 vdss_ref 15 igss     16 vgs_max  17 vigs_iso
%    18 leak_ratio 19 leak_span 20 tnom   21 ron_ithresh  22 igss_leak_ratio
add_block('simulink/Sources/Constant', [sub '/P_all'], 'Position', [300 200 400 220], ...
    'Value', vec_literal(p.model.vector));
%% ------------------------------------------------------------------------
%  Physics blocks
% -------------------------------------------------------------------------
add_mf(sub, 'capacitance_model', [300 280 470 440], ...
    {'Vgs_in', 'Vds_in', 'dVgs', 'dVds', 'P_all', 'Ts'}, ...
    {'Qg', 'Qgd', 'Qds', 'iCgs', 'iCgd', 'iCds', 'Ciss', 'Coss', 'Crss'}, ...
    capScript());

add_mf(sub, 'channel_model', [500 280 670 440], ...
    {'Vgs_in', 'Vds_in', 'Tcase_in', 'P_all'}, ...
    {'Ich', 'Pcond', 'Ild', 'Ilg'}, ...
    channelScript());

add_mf(sub, 'terminals_losses', [700 280 870 440], ...
    {'Vds_in', 'P_all', 'Ich', 'iCgs', 'iCgd', 'iCds', 'Ilg', 'Ild'}, ...
    {'ID', 'IG', 'IS', 'RON', 'Psw', 'Ploss'}, ...
    terminalsScript());

%% ------------------------------------------------------------------------
%  Internal wiring
% -------------------------------------------------------------------------
wire(sub, { ...
    'Vgs_in/1',       'Vgs_prev/1'      ; ...
    'Vgs_in/1',       'dVgs/1'          ; ...
    'Vgs_prev/1',     'dVgs/2'          ; ...
    'Vds_in/1',       'Vds_prev/1'      ; ...
    'Vds_in/1',       'dVds/1'          ; ...
    'Vds_prev/1',     'dVds/2'          ; ...
    'dVgs/1',         'capacitance_model/3' ; ...
    'dVds/1',         'capacitance_model/4' ; ...
    'Vgs_in/1',       'capacitance_model/1' ; ...
    'Vds_in/1',       'capacitance_model/2' ; ...
    'P_all/1',        'capacitance_model/5' ; ...
    'Ts/1',           'capacitance_model/6' ; ...
    'Vgs_in/1',       'channel_model/1' ; ...
    'Vds_in/1',       'channel_model/2' ; ...
    'Tcase_in/1',     'channel_model/3' ; ...
    'P_all/1',        'channel_model/4' ; ...
    'Vds_in/1',       'terminals_losses/1' ; ...
    'P_all/1',        'terminals_losses/2' ; ...
    'channel_model/1','terminals_losses/3' ; ...
    'capacitance_model/4','terminals_losses/4' ; ...
    'capacitance_model/5','terminals_losses/5' ; ...
    'capacitance_model/6','terminals_losses/6' ; ...
    'channel_model/4','terminals_losses/7' ; ...
    'channel_model/3','terminals_losses/8' });

%% ------------------------------------------------------------------------
%  Twin subsystem outputs
% -------------------------------------------------------------------------
outSrc = { ...
    'Vgs_in/1',        'Vds_in/1',        'terminals_losses/1', ...
    'terminals_losses/2','terminals_losses/3','terminals_losses/4', ...
    'channel_model/2',  'terminals_losses/5', 'terminals_losses/6', ...
    'Tcase_in/1',      'Tcase_in/1',      'capacitance_model/1', ...
    'capacitance_model/2', 'capacitance_model/7', 'capacitance_model/8', ...
    'capacitance_model/9'};

outY = 55 + (0:numel(outNames)-1)*30;
for k = 1:numel(outNames)
    add_block('simulink/Ports & Subsystems/Out1', sprintf('%s/%s', sub, outNames{k}), ...
        'Position', [1180 outY(k) 1210 outY(k)+18], 'PortName', outNames{k});
end
for k = 1:numel(outNames)
    add_line(sub, outSrc{k}, sprintf('%s/1', outNames{k}), 'autorouting', 'on');
end

% Subsystem port names are taken from each port block's PortName setting.

%% ------------------------------------------------------------------------
%  Top level
% -------------------------------------------------------------------------
add_block('simulink/Ports & Subsystems/In1', [modelName '/Vgs_cmd'], 'Position', [30 90 60 110], 'PortName', 'Vgs_cmd', 'PortDimensions', '1');
add_block('simulink/Ports & Subsystems/In1', [modelName '/Vds_cmd'], 'Position', [30 130 60 150], 'PortName', 'Vds_cmd', 'PortDimensions', '1');
add_block('simulink/Ports & Subsystems/In1', [modelName '/Tcase_cmd'], 'Position', [30 170 60 190], 'PortName', 'Tcase_cmd', 'PortDimensions', '1');

wire(modelName, { ...
    'Vgs_cmd/1',   'GaN_HEMT_Twin/1' ; ...
    'Vds_cmd/1',   'GaN_HEMT_Twin/2' ; ...
    'Tcase_cmd/1', 'GaN_HEMT_Twin/3' });

topY = 55 + (0:numel(outNames)-1)*30;
for k = 1:numel(outNames)
    add_block('simulink/Ports & Subsystems/Out1', sprintf('%s/%s', modelName, outNames{k}), ...
        'Position', [420 topY(k) 450 topY(k)+18], 'PortName', outNames{k});
end

% Wire the twin outputs using the subsystem's real port handles so the
% connection never depends on a guessed port number.
twinPorts = get_param([modelName '/GaN_HEMT_Twin'], 'PortHandles');
if numel(twinPorts.Outport) ~= numel(outNames)
    found = find_system([modelName '/GaN_HEMT_Twin'], 'SearchDepth', 1, ...
        'BlockType', 'Outport');
    error('create_gan_hemt_twin:portCount', ...
        ['Twin exposes %d output ports but %d were declared. Found: %s'], ...
        numel(twinPorts.Outport), numel(outNames), strjoin(found, ' | '));
end
for k = 1:numel(outNames)
    dstPh = get_param([modelName '/' outNames{k}], 'PortHandles').Inport;
    add_line(modelName, twinPorts.Outport(k), dstPh, 'autorouting', 'on');
end

% Data-generation layer: one To Workspace collector per device output. This
% is what makes the twin emit a standardized dataset from a plain simulation.
wsY = 480 + (0:numel(outNames)-1)*28;
for k = 1:numel(outNames)
    add_block('simulink/Sinks/To Workspace', sprintf('%s/ws_%s', modelName, outNames{k}), ...
        'Position', [500 wsY(k) 660 wsY(k)+20], ...
        'VariableName', outNames{k}, ...
        'SaveFormat', 'Array', ...
        'MaxDataPoints', 'inf', ...
        'Decimation', '1', ...
        'SampleTime', '-1');
    wsIn = get_param([modelName '/ws_' outNames{k}], 'PortHandles').Inport;
    add_line(modelName, twinPorts.Outport(k), wsIn, 'autorouting', 'on');
end

%% ------------------------------------------------------------------------
%  Solver
% -------------------------------------------------------------------------
set_param(modelName, 'Solver', p.solver.solver_type, ...
    'SolverType', 'Fixed-step', ...
    'FixedStep', num2str(p.solver.sample_time_s), ...
    'MaxStep', num2str(p.solver.max_step_s), ...
    'StartTime', '0', 'StopTime', '1e-5', ...
    'ReturnWorkspaceOutputs', 'off');

save_system(modelName, modelFile);
fprintf('Twin model written: %s\n', modelFile);
fprintf('  3 excitation inports, %d device outputs, 3 physics blocks\n', numel(outNames));

end

%% =========================================================================
function add_mf(parent, name, position, srcNames, dstNames, scriptText)
%ADD_MF  Place a MATLAB Function block and load its script.
%   The block's ports are derived from the script signature at compile time,
%   so srcNames/dstNames are used only to confirm the script and the wiring
%   agree.

path = [parent '/' name];
add_block('simulink/User-Defined Functions/MATLAB Function', path, 'Position', position);
ch = sfroot().find('-isa', 'Stateflow.EMChart', 'Path', path);
if isempty(ch)
    error('create_gan_hemt_twin:noChart', ...
        'MATLAB Function block %s was not created.', path);
end
ch.Script = scriptText;

sig = regexp(scriptText, '^function\s*\[([^\]]*)\]\s*=\s*\w+\(([^)]*)\)', 'tokens', 'once');
if isempty(sig)
    error('create_gan_hemt_twin:badSignature', ...
        'Script for %s does not start with a parseable function signature.', name);
end
gotIn  = numel(strtrim(strsplit(sig{2}, ',')));
gotOut = numel(strtrim(strsplit(sig{1}, ',')));
if gotIn ~= numel(srcNames) || gotOut ~= numel(dstNames)
    error('create_gan_hemt_twin:portMismatch', ...
        '%s declares %d in / %d out ports but is wired for %d in / %d out.', ...
        name, gotIn, gotOut, numel(srcNames), numel(dstNames));
end
end
function wire(parent, pairs)
%WIRE  Add a batch of autorouted connections from an N-by-2 cell array of
%      {sourcePort, destinationPort} pairs.

if ~iscell(pairs) || size(pairs, 2) ~= 2
    error('create_gan_hemt_twin:badWireList', ...
        'wire() needs an N-by-2 cell array of {source, destination} ports.');
end

for k = 1:size(pairs, 1)
    src = pairs{k, 1};
    dst = pairs{k, 2};
    srcBlk = src(1:find(src == '/', 1, 'first') - 1);
    if getSimulinkBlockHandle([parent '/' srcBlk]) <= 0
        error('create_gan_hemt_twin:missingBlock', ...
            'Cannot wire from %s: block %s does not exist in %s.', src, srcBlk, parent);
    end
    try
        add_line(parent, src, dst, 'autorouting', 'on');
    catch err
        error('create_gan_hemt_twin:wireFailed', ...
            'Failed to wire %s -> %s in %s. Cause: %s', src, dst, parent, err.message);
    end
end
end
%% =========================================================================
function s = struct_expr(s)
%STRUCT_EXPR  Render a numeric struct as a self-contained MATLAB literal so
%      the Constant block needs no workspace variable.

f = fieldnames(s);
parts = cell(1, numel(f));
for k = 1:numel(f)
    parts{k} = ['''' f{k} ''', ', num2str(s.(f{k}), 17)];
end
s = ['struct(' strjoin(parts, ', ') ')'];
end

%% =========================================================================
function drop_stale_model(modelName, modelFile)
%DROP_STALE_MODEL  Remove any previous copy so rebuilds start clean.

if bdIsLoaded(modelName)
    close_system(modelName, 0);
end
if isfile(modelFile)
    delete(modelFile);
end
end

%% =========================================================================
function s = capScript()
s = strjoin({ ...
'function [Qg,Qgd,Qds,iCgs,iCgd,iCds,Ciss,Coss,Crss] = fcn(Vgs,Vds,dVgs,dVds,Pc,Ts)'
'%#codegen'
'% Pc is the flat parameter vector; see p.model.vector_names.'
'cgd0 = Pc(1); vjg = Pc(2); coss0 = Pc(3); vjc = Pc(4);'
'cgs0 = Pc(5); vgsc = Pc(6); vth = Pc(7); vgs_min = Pc(8);'
''
'vg  = max(Vgs, vgs_min);'
'va  = abs(Vds);'
'sgn = sign(Vds);'
''
'% Depletion capacitances: C(V) = C0 / (1 + |V| / Vj).'
'Cgd  = cgd0 ./ (1 + va ./ vjg);'
'Coss = coss0 ./ (1 + va ./ vjc);'
'Cds  = Coss - Cgd;'
'Cgs  = cgs0 ./ (1 + max(vg,0) ./ vgsc);'
'Ciss = Cgs + 2*Cgd;'
'Crss = Cgd;'
''
'% Integrated charge forms of the same depletion curves.'
'qgd_d  = cgd0  .* vjg  .* log(1 + va ./ vjg);'
'qoss_d = coss0 .* vjc .* log(1 + va ./ vjc);'
'qgs_g  = cgs0 .* vgsc .* log(1 + max(vg,0) ./ vgsc);'
''
'% Above threshold the Miller charge acquires a gate-referred term.'
'Vc  = max(Vgs - vth, 0);'
'Qgd = qgd_d + Cgd .* Vc;'
'Qgs = qgs_g;'
'Qds = qoss_d - qgd_d;'
'Qg  = Qgs + Qgd;'
''
'dvgs_dt = dVgs ./ Ts;'
'dvds_dt = dVds ./ Ts;'
'iCgd = Cgd .* sgn .* dvds_dt + Cgd .* double(Vgs > vth) .* dvgs_dt;'
'iCds = Cds .* sgn .* dvds_dt;'
'iCgs = Cgs .* dvgs_dt;'
'end'}, sprintf('\n'));
end

%% =========================================================================
function s = channelScript()
s = strjoin({ ...
'function [Ich,Pcond,Ild,Ilg] = fcn(Vgs,Vds,Tcase,Pc)'
'%#codegen'
'% Pc is the flat parameter vector; see p.model.vector_names.'
'k = Pc(9); vth = Pc(7); vsmooth = Pc(10); vdsat_max = Pc(11); va = Pc(12);'
'idss = Pc(13); vdss_ref = Pc(14); igss = Pc(15); vgs_max = Pc(16);'
'vigs_iso = Pc(17); leak_ratio = Pc(18); leak_span = Pc(19); tnom = Pc(20);'
'igss_ratio = Pc(22);'
''
'Vov = Vgs - vth;'
'Vc  = 0.5 * Vov .* (1 + tanh(Vov ./ (2*vsmooth)));'
'Vda = abs(Vds);'
'Vdsat = min(max(Vc,0), vdsat_max);'
'Vdc  = min(Vda, Vdsat);'
'Ich  = sign(Vds) .* k .* (Vc .* Vdc - 0.5*Vdc.^2) .* (1 + Vda ./ va);'
'Pcond = Vds .* Ich;'
''
'% Leakage magnitudes are anchored to the datasheet maxima; the temperature'
'% ratio comes from the two printed IDSS points.'
'tf  = leak_ratio .^ ((Tcase - tnom) ./ leak_span);'
'tf_exp = (Tcase - tnom) ./ leak_span;'
'Ild = idss .* (min(Vda, vdss_ref) ./ vdss_ref).^0.5 .* tf;'
'Ilg = -igss .* tanh(-Vgs ./ vigs_iso) ./ tanh(-vgs_max ./ vigs_iso) .* (igss_ratio .^ tf_exp);'
'end'}, sprintf('\n'));
end

%% =========================================================================
function s = terminalsScript()
s = strjoin({ ...
'function [ID,IG,IS,RON,Psw,Ploss] = fcn(Vds,Pc,Ich,iCgs,iCgd,iCds,Ilg,Ild)'
'%#codegen'
'ron_ithresh = Pc(21);'
''
'ID = Ich + iCgd + iCds + Ild;'
'IG = iCgs + iCgd + Ilg;'
'IS = -(ID + IG);'
''
'RON = NaN(size(ID));'
'mask = ID > ron_ithresh;'
'RON(mask) = Vds(mask) ./ ID(mask);'
''
'Psw   = Vds .* abs(iCgd);'
'Ploss = Vds .* Ich + Psw;'
'end'}, sprintf('\n'));
end

%% =========================================================================
function s = vec_literal(v)
%VEC_LITERAL  Render a numeric vector as a self-contained MATLAB literal so
%      the Constant block needs no workspace variable.

parts = arrayfun(@(x) num2str(x, 17), v, 'UniformOutput', false);
s = ['[' strjoin(parts, ', ') ']'];
end
