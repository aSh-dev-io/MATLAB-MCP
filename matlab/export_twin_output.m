function results = export_twin_output(varargin)
%EXPORT_TWIN_OUTPUT  Generate every Stage-1 artefact from the digital twin.
%
%   RESULTS = EXPORT_TWIN_OUTPUT() runs all six excitation profiles, writes
%   the MAT, CSV and JSON data files and renders the six characteristic
%   plots.
%
%   Name-value options
%     'p'         parameter struct        (default gan_parameters())
%     'profiles'  cell array of names     (default all six profiles)
%     'root'      project root            (default parent of this folder)
%     'write'     false to skip data files (default true)
%     'verify'    false to skip verification (default true)
%
%   Every characteristic plot carries the label
%   'MODEL PREDICTION - NOT VALIDATED'. The supplied datasheet contains no
%   characteristic curves, so none of these curves can be validated.

args = varargin;
p = [];
profiles = {'output', 'transfer', 'capacitance', 'charge', 'switching', 'thermal'};
root = '';
doWrite = true;
doVerify = true;

k = 1;
while k <= numel(args)
    if ~ischar(args{k})
        error('export_twin_output:badArgument', 'Option names must be strings.');
    end
    if k + 1 > numel(args)
        error('export_twin_output:badArgument', 'Option "%s" is missing its value.', args{k});
    end
    switch lower(args{k})
        case 'p'
        p = args{k+1};
        case 'profiles'
        profiles = args{k+1};
        case 'root'
        root = args{k+1};
        case 'write'
        doWrite = logical(args{k+1});
        case 'verify'
        doVerify = logical(args{k+1});
        otherwise
        error('export_twin_output:badArgument', 'Unknown option "%s".', args{k});
    end
    k = k + 2;
end

if isempty(p)
    p = gan_parameters();
end
if isempty(root)
    root = fileparts(fileparts(mfilename('fullpath')));
end
resultsDir = fullfile(root, 'results');
plotDir = fullfile(root, 'plots');

label = 'MODEL PREDICTION - NOT VALIDATED';
thermalNote = 'Thermal validation not supported by the provided dataset.';

fprintf('Stage-1 export: %s\n', p.meta.device_part_number);
fprintf('  %-12s %8s %14s %14s %14s\n', 'profile', 'samples', 't_stop_s', 'ID_min_A', 'ID_max_A');

data = struct();
for j = 1:numel(profiles)
    name = profiles{j};
    data.(name) = run_gan_hemt_twin(p, name);
    d = data.(name);
    fprintf('  %-12s %8d %14.6g %14.6g %14.6g\n', ...
        name, numel(d.time), d.time(end), min(d.ID), max(d.ID));
end

if doVerify
    report = verify_gan_hemt_twin(p, 'verbose', false);
    fprintf('  verification: %d PASS, %d FAIL, %d DATASET_INCONSISTENCY, %d NOT_COMPARABLE\n', ...
        report.summary.pass, report.summary.fail, ...
        report.summary.dataset_inconsistency, report.summary.not_comparable);
else
    report = struct('summary', struct('total', 0, 'pass', 0, 'fail', 0, ...
        'dataset_inconsistency', 0, 'not_comparable', 0));
end

%% ------------------------------------------------------------ MAT and CSV
generated = char(datetime('now', 'TimeZone', 'UTC', ...
    'Format', 'yyyy-MM-dd''T''HH:mm:ss''Z'''));
modelFile = fullfile(root, 'simulink', 'gan_hemt_digital_twin.slx');

meta = struct();
meta.part_number = p.meta.device_part_number;
meta.datasheet_revision = p.meta.datasheet_revision;
meta.generated_by = 'export_twin_output';
meta.generated_utc = generated;
meta.matlab_release = version('-release');
meta.model_file = modelFile;
meta.model_prediction_label = label;
meta.thermal_note = thermalNote;
meta.profiles = profiles;

if doWrite
    if ~isfolder(resultsDir)
        mkdir(resultsDir);
    end
    matPath = fullfile(resultsDir, 'stage1_output.mat');
    save(matPath, 'meta', 'p', 'data', 'report', '-v7.3');
    fprintf('  wrote %s\n', matPath);

    csvPath = fullfile(resultsDir, 'stage1_output.csv');
    write_csv(csvPath, data, profiles);
    fprintf('  wrote %s\n', csvPath);

    jsonPath = fullfile(resultsDir, 'stage1_summary.json');
    write_json(jsonPath, meta, p, data, profiles, report);
    fprintf('  wrote %s\n', jsonPath);
end

%% ----------------------------------------------------------------- Plots
if ~isfolder(plotDir)
    mkdir(plotDir);
end
plotFiles = {};
plotFiles{end+1} = plot_output(plotDir, data, p, label);
plotFiles{end+1} = plot_transfer(plotDir, data, p, label);
plotFiles{end+1} = plot_capacitance(plotDir, data, p, label);
plotFiles{end+1} = plot_charge(plotDir, data, p, label);
plotFiles{end+1} = plot_switching(plotDir, data, p, label);
plotFiles{end+1} = plot_thermal(plotDir, data, p, label, thermalNote);
fprintf('  wrote %d plots to %s\n', numel(plotFiles), plotDir);

results = struct('meta', meta, 'data', data, 'report', report, ...
    'plot_files', {plotFiles});

if doWrite
    fprintf('Stage-1 export complete.\n');
end
end

%% =========================================================================
function write_csv(path, data, profiles)
%WRITE_CSV  One tidy long-format table covering every profile.

cols = {'profile', 't_s', 'Vgs_V', 'Vds_V', 'Tcase_C', 'ID_A', 'IG_A', ...
    'IS_A', 'RON_ohm', 'Pcond_W', 'Psw_W', 'Ploss_W', 'Tj_C', ...
    'Qg_C', 'Qgd_C', 'Ciss_F', 'Coss_F', 'Crss_F'};

fid = fopen(path, 'w');
if fid < 0
    error('export_twin_output:csvOpen', 'Cannot open %s for writing.', path);
end
cleanup = onCleanup(@() fclose(fid));

fmt = [repmat('%.10g,', 1, 17) '\n'];
fprintf(fid, '%s\n', strjoin(cols, ','));
for j = 1:numel(profiles)
    name = profiles{j};
    d = data.(name);
    m = [d.time, d.Vgs, d.Vds, d.Tcase, d.ID, d.IG, d.IS, d.RON, ...
        d.Pcond, d.Psw, d.Ploss, d.Tj, d.Qg, d.Qgd, d.Ciss, d.Coss, d.Crss];
    for r = 1:size(m, 1)
        fprintf(fid, '%s,', name);
        fprintf(fid, fmt, m(r, :));
    end
end
end

%% =========================================================================
function write_json(path, meta, p, data, profiles, report)
%WRITE_JSON  Machine-readable summary of the run and the verification.

entries = cell(numel(profiles), 1);
for j = 1:numel(profiles)
    name = profiles{j};
    d = data.(name);
    e = struct();
    e.name = name;
    e.samples = numel(d.time);
    e.time_start_s = d.time(1);
    e.time_stop_s = d.time(end);
    e.vgs_min_V = min(d.Vgs);   e.vgs_max_V = max(d.Vgs);
    e.vds_min_V = min(d.Vds);   e.vds_max_V = max(d.Vds);
    e.tcase_min_C = min(d.Tcase); e.tcase_max_C = max(d.Tcase);
    e.id_min_A = min(d.ID);     e.id_max_A = max(d.ID);
    e.ig_abs_max_A = max(abs(d.IG));
    e.ron_at_vgs5_mohm = ron_at(d, p.dc.rds_on_vgs_V) * 1e3;
    e.ploss_max_W = max(d.Ploss);
    e.psw_max_W = max(d.Psw);
    e.qg_final_C = d.Qg(end);
    e.qgd_final_C = d.Qgd(end);
    e.tj_max_C = max(d.Tj);
    entries{j} = e;
end
idxSwitch = find(strcmp(profiles, 'switching'), 1);
if ~isempty(idxSwitch) && isfield(data, 'switching')
    entries{idxSwitch}.id_pulse_peak_A = max(data.switching.ID);
    entries{idxSwitch}.vds_on_loadline_V = data.switching.vds_on_loadline_V;
    entries{idxSwitch}.switching_energy_J = ...
        trapz(data.switching.time, data.switching.Psw);
end

checks = cell(0, 1);
defects = {};
unvalidatable = {};
if isfield(report, 'checks')
    checks = cell(numel(report.checks), 1);
    for k = 1:numel(report.checks)
        c = report.checks(k);
        checks{k} = struct('name', c.name, 'condition', c.condition, ...
            'datasheet', c.datasheet, 'datasheet_units', c.datasheet_units, ...
            'twin', c.model, 'twin_units', c.model_units, ...
            'rel_err_pct', c.rel_err_pct, 'tolerance_pct', c.tolerance_pct, ...
            'verdict', c.verdict, 'note', c.note);
    end
    defects = report.dataset_defects;
    unvalidatable = report.unvalidatable;
end

out = struct();
out.meta = meta;
out.profiles = entries;
out.verification = struct('summary', report.summary, 'checks', {checks}, ...
    'dataset_defects', {defects}, 'unvalidatable', {unvalidatable});
out.ratings = struct( ...
    'vds_V', p.ratings.vds_drain_source_V, ...
    'vgs_max_V', p.ratings.vgs_max_V, ...
    'id_continuous_25C_A', p.ratings.id_continuous_25C_A, ...
    'id_pulse_25C_A', p.ratings.id_pulse_25C_A, ...
    'id_pulse_150C_A', p.ratings.id_pulse_150C_A, ...
    'br_dss_min_V', p.dc.br_dss_min_V, ...
    'pd_total_W', json_null(p.ratings.pd_total_W));
out.thermal_note = thermal_note_local();

fid = fopen(path, 'w');
if fid < 0
    error('export_twin_output:jsonOpen', 'Cannot open %s for writing.', path);
end
cleanup = onCleanup(@() fclose(fid));
encoded = jsonencode(out, 'PrettyPrint', true);
if ischar(encoded)
    fprintf(fid, '%s\n', encoded);
else
    fwrite(fid, encoded, 'char');
end
end

%% =========================================================================
function s = thermal_note_local()
s = 'Thermal validation not supported by the provided dataset.';
end

%% =========================================================================
function v = json_null(x)
if isnan(x)
    v = [];
else
    v = x;
end
end

%% =========================================================================
function r = ron_at(d, vgs)
sel = abs(d.Vgs - vgs) < 1e-9;
if ~any(sel)
    r = NaN;
else
    r = median(d.RON(sel));
end
end

%% =========================================================================
function f = new_figure(w, h)
f = figure('Visible', 'off', 'Position', [100 100 w h], ...
    'Color', 'w');
end

%% =========================================================================
function f = plot_output(plotDir, data, p, label)
d = data.output;
vgsSet = unique(round(d.Vgs * 1e6) / 1e6);

f = new_figure(1150, 800);
tl = tiledlayout(f, 1, 2, 'TileSpacing', 'compact', 'Padding', 'compact');

nexttile(tl);
hold on;
for k = 1:numel(vgsSet)
    sel = abs(d.Vgs - vgsSet(k)) < 1e-9;
    plot(d.Vds(sel), d.ID(sel), '-', 'LineWidth', 1.6, ...
        'DisplayName', sprintf('V_{GS} = %g V', vgsSet(k)));
end
hold off;
set(gca, 'YScale', 'log');
ylabel('I_D (A)');
title('Output characteristics');
legend('Location', 'northwest');
grid on;

nexttile(tl);
hold on;
for k = 1:numel(vgsSet)
    sel = abs(d.Vgs - vgsSet(k)) < 1e-9 & d.Vds > 0 & isfinite(d.RON);
    plot(d.Vds(sel), d.RON(sel) * 1e3, '-', 'LineWidth', 1.6, ...
        'DisplayName', sprintf('V_{GS} = %g V', vgsSet(k)));
end
hold off;
set(gca, 'YScale', 'log');
xlabel('V_{DS} (V)');
ylabel('R_{DS(on)} (m\\Omega)');
title('On-resistance from the twin');
grid on;

f = annotate_datasheet(f, p, sprintf('Datasheet point: %g A at V_{DS} = %g V gives %g m\\Omega (typ).', ...
    p.dc.rds_on_ids_A, p.dc.vds_ron_spec_V, p.dc.rds_on_typ_ohm * 1e3));
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'output_characteristics.png'));
end

%% =========================================================================
function f = plot_transfer(plotDir, data, p, label)
d = data.transfer;
gm = gradient(d.ID, d.Vgs);

f = new_figure(1150, 800);
tl = tiledlayout(f, 1, 2, 'TileSpacing', 'compact', 'Padding', 'compact');

nexttile(tl);
plot(d.Vgs, d.ID, '-', 'LineWidth', 1.8);
hold on;
plot(p.model.vth_V, interp1(d.Vgs, d.ID, p.model.vth_V), 'o', ...
    'MarkerSize', 8, 'LineWidth', 1.5);
hold off;
xlabel('V_{GS} (V)');
ylabel('I_D (A)');
title(sprintf('Transfer at V_{DS} = %g V', p.dc.vds_ron_spec_V));
legend(sprintf('Twin'), sprintf('V_{th} = %g V', p.model.vth_V), ...
    'Location', 'northwest');
grid on;

nexttile(tl);
plot(d.Vgs, gm, '-', 'LineWidth', 1.8);
xlabel('V_{GS} (V)');
ylabel('g_m (S)');
title('Transconductance from the twin');
grid on;

f = annotate_datasheet(f, p, sprintf( ...
    ['Datasheet V_{th} = %g to %g V at I_{DS} = %g mA. The twin uses the ', ...
    'range minimum, %g V, as V_{th}, so no appreciable conduction is ', ...
    'predicted at that gate drive.'], ...
    p.dc.vgs_th_min_V, p.dc.rds_on_vgs_V, p.dc.vgs_th_ids_A * 1e3, p.model.vth_V));
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'transfer_characteristics.png'));
end

%% =========================================================================
function f = plot_capacitance(plotDir, data, p, label)
d = data.capacitance;
vgsSet = unique(round(d.Vgs * 1e6) / 1e6);

f = new_figure(1150, 800);
hold on;
cols = lines(numel(vgsSet));
leg = cell(3 * numel(vgsSet) + 1, 1);
n = 0;
for k = 1:numel(vgsSet)
    sel = abs(d.Vgs - vgsSet(k)) < 1e-9;
    n = n + 1;
    plot(d.Vds(sel), d.Ciss(sel) * 1e12, '-', 'LineWidth', 1.6, 'Color', cols(k, :));
    leg{n} = sprintf('C_{iss}, V_{GS} = %g V', vgsSet(k));
end
for k = 1:numel(vgsSet)
    sel = abs(d.Vgs - vgsSet(k)) < 1e-9;
    n = n + 1;
    plot(d.Vds(sel), d.Coss(sel) * 1e12, '--', 'LineWidth', 1.6, 'Color', cols(k, :));
    leg{n} = sprintf('C_{oss}, V_{GS} = %g V', vgsSet(k));
end
for k = 1:numel(vgsSet)
    sel = abs(d.Vgs - vgsSet(k)) < 1e-9;
    n = n + 1;
    plot(d.Vds(sel), d.Crss(sel) * 1e12, ':', 'LineWidth', 1.8, 'Color', cols(k, :));
    leg{n} = sprintf('C_{rss}, V_{GS} = %g V', vgsSet(k));
end
plot(p.caps.vds_test_V, p.caps.ciss_F * 1e12, 'kp', 'MarkerSize', 14, ...
    'MarkerFaceColor', 'y');
hold off;
leg{n + 1} = sprintf('datasheet C_{iss} at V_{DS} = %g V', p.caps.vds_test_V);
xlabel('V_{DS} (V)');
ylabel('Capacitance (pF)');
title('Capacitance characteristics');
legend(leg, 'Location', 'northeast');
grid on;

f = annotate_datasheet(f, p, sprintf( ...
    'Datasheet at V_{GS} = %g V, V_{DS} = %g V, %g MHz: C_{iss} = %g pF, C_{oss} = %g pF, C_{rss} = %g pF.', ...
    p.caps.vgs_test_V, p.caps.vds_test_V, p.caps.f_test_Hz / 1e6, ...
    p.caps.ciss_F * 1e12, p.caps.coss_F * 1e12, p.caps.crss_F * 1e12));
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'capacitance_characteristics.png'));
end

%% =========================================================================
function f = plot_charge(plotDir, data, p, label)
d = data.charge;

f = new_figure(1000, 750);
plot(d.Vgs, d.Qg * 1e9, '-', 'LineWidth', 2.0);
hold on;
plot(d.Vgs, d.Qgd * 1e9, '--', 'LineWidth', 2.0);
plot(p.model.vgs_max_V, d.Qg(end) * 1e9, 'ko', 'MarkerSize', 8, 'LineWidth', 1.5);
plot(d.Vgs(end), d.Qgd(end) * 1e9, 'o', 'MarkerSize', 8, 'LineWidth', 1.5);
hold off;
xlabel('V_{GS} (V)');
ylabel('Charge (nC)');
title(sprintf('Gate charge at V_{DS} = %g V', p.charge.qgd_vds_V));
legend('Q_G (twin)', 'Q_{GD} (twin)', ...
    sprintf('twin Q_G at V_{GS} = %g V = %.2f nC', p.model.vgs_max_V, d.Qg(end) * 1e9), ...
    'Location', 'northwest');
grid on;

f = annotate_datasheet(f, p, sprintf( ...
    ['DATASET INCONSISTENCY. Datasheet prints Q_G = %g nC but Q_{GS} + Q_{GD} = %g nC. ', ...
    'FOM-QG = Q_G * R_{DS(on)} = %g nC*mOmega corroborates Q_G, so the twin is built ', ...
    'from the two charge components and cannot also reach the printed Q_G.'], ...
    p.charge.qg_nC * 1e9, (p.charge.qgs_nC + p.charge.qgd_nC) * 1e9, p.dc.fom_qg_nC_mohm));
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'gate_charge.png'));
end

%% =========================================================================
function f = plot_switching(plotDir, data, p, label)
d = data.switching;
t = d.time * 1e6;

f = new_figure(1150, 1000);
tl = tiledlayout(f, 4, 1, 'TileSpacing', 'compact', 'Padding', 'compact');

nexttile(tl);
plot(t, d.Vgs, '-', 'LineWidth', 1.8);
hold on;
plot(t, d.Vds, '-', 'LineWidth', 1.2);
hold off;
ylabel('V_{GS}, V_{DS} (V)');
legend('V_{GS}', 'V_{DS}', 'Location', 'best');
title(sprintf('Hard-switched double pulse, V_{bus} = %g V, R_{load} = %g \\Omega', ...
    p.switching.vbus_V, p.switching.rload_ohm));
grid on;

nexttile(tl);
plot(t, d.ID, '-', 'LineWidth', 1.8);
hold on;
yline(p.ratings.id_pulse_25C_A, 'r--', 'LineWidth', 1.4);
hold off;
ylabel('I_D (A)');
legend('I_D (twin)', 'I_{D,pulse} rating', 'Location', 'best');
grid on;

nexttile(tl);
plot(t, d.IG * 1e3, '-', 'LineWidth', 1.6);
hold off;
ylabel('I_G (mA)');
legend('I_G (twin)', 'Location', 'best');
grid on;

nexttile(tl);
plot(t, d.Psw, '-', 'LineWidth', 1.6);
hold on;
plot(t, d.Ploss, '-', 'LineWidth', 1.6);
hold off;
xlabel('time (\\mus)');
ylabel('Power (W)');
legend('P_{sw} (W)', 'P_{loss} (W)', 'Location', 'best');
grid on;

f = annotate_datasheet(f, p, sprintf( ...
    ['Peak I_D = %g A against the %g A pulsed rating. The excitation is a ', ...
    'resistive load line only: the dataset has no freewheeling or ', ...
    'parasitic values, so the waveform is not a datasheet double-pulse test.'], ...
    max(d.ID), p.ratings.id_pulse_25C_A));
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'switching_waveforms.png'));
end

%% =========================================================================
function f = plot_thermal(plotDir, data, p, label, thermalNote)
d = data.thermal;
tcaseSet = unique(round(d.Tcase));
vgsSet = unique(round(d.Vgs * 1e6) / 1e6);

f = new_figure(1150, 800);
hold on;
cols = lines(numel(tcaseSet));
leg = cell(1, numel(tcaseSet) * numel(vgsSet));
n = 0;
for a = 1:numel(tcaseSet)
    for b = 1:numel(vgsSet)
        sel = abs(d.Tcase - tcaseSet(a)) < 1e-9 & abs(d.Vgs - vgsSet(b)) < 1e-9;
        [vd, ~, ord] = unique(d.Vds(sel));
        id = d.ID(sel);
        id = id(ord);
        n = n + 1;
        plot(vd, id, '-', 'LineWidth', 1.7, 'Color', cols(a, :));
        leg{n} = sprintf('V_{GS} = %g V, T_{case} = %g ^\\circC', vgsSet(b), tcaseSet(a));
    end
end
hold off;
xlabel('V_{DS} (V)');
ylabel('I_D (A)');
title('Temperature effect on the output curves');
legend(leg, 'Location', 'northwest');
grid on;

f = annotate_datasheet(f, p, thermalNote);
f = stamp(f, label);
f = save_figure(f, fullfile(plotDir, 'thermal_id.png'));
end

%% =========================================================================
function f = annotate_datasheet(f, p, txt)
annotation(f, 'textbox', [0.02 0.015 0.96 0.075], 'String', txt, ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'left', ...
    'VerticalAlignment', 'bottom', 'FontSize', 8.5, 'Interpreter', 'tex', ...
    'Color', [0.25 0.25 0.25]);
end

%% =========================================================================
function f = stamp(f, label)
annotation(f, 'textbox', [0.60 0.945 0.385 0.045], 'String', label, ...
    'EdgeColor', 'none', 'HorizontalAlignment', 'right', ...
    'VerticalAlignment', 'middle', 'FontSize', 9, 'FontWeight', 'bold', ...
    'Color', [0.7 0 0], 'Interpreter', 'none');
end

%% =========================================================================
function f = save_figure(f, path)
exportgraphics(f, path, 'Resolution', 200);
close(f);
end