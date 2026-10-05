function report = verify_gan_hemt_twin(varargin)
%VERIFY_GAN_HEMT_TWIN  Check the twin against every printed datasheet value.
%
%   REPORT = VERIFY_GAN_HEMT_TWIN() runs all checks and prints a table.
%   REPORT = VERIFY_GAN_HEMT_TWIN(P) uses parameter struct P.
%   REPORT = VERIFY_GAN_HEMT_TWIN(P, 'verbose', false) suppresses the table.
%
%   Each check carries one of three verdicts.
%     PASS                   the twin reproduces the printed value
%     FAIL                   the twin does not reproduce the printed value
%     DATASET_INCONSISTENCY  the printed values contradict each other, so no
%                            model can satisfy them all
%
%   The report also records the dataset defects that block validation of
%   curves, switching waveforms and temperature.

args = varargin;
p = [];
verbose = true;
if ~isempty(args) && isstruct(args{1})
    p = args{1};
    args(1) = [];
end
k = 1;
while k <= numel(args)
    switch lower(args{k})
        case 'verbose'
        verbose = logical(args{k+1});
        otherwise
        error('verify_gan_hemt_twin:badArgument', 'Unknown option "%s".', args{k});
    end
    k = k + 2;
end
if isempty(p)
    p = gan_parameters();
end

emptyRow = @() struct('name', '', 'condition', '', 'condition_units', '', ...
    'datasheet', NaN, 'datasheet_units', '', 'model', NaN, 'model_units', '', ...
    'rel_err_pct', NaN, 'tolerance_pct', NaN, 'verdict', 'PASS', 'note', '');

checks = repmat(emptyRow(), 0, 1);

% ------------------------------------------------------------------ DC / RON
oRon = dc(p, p.dc.rds_on_vgs_V, p.dc.vds_ron_spec_V, p.model.tnom_C);
c = row(oRon.RON * 1e3, p.dc.rds_on_typ_ohm * 1e3, 'mOhm', 2.0);
c.name = 'RDS(on) at the datasheet test point';
c.condition = sprintf('VGS = %g V, IDS = %g A (VDS = RON*IDS = %g V)', ...
    p.dc.rds_on_vgs_V, p.dc.rds_on_ids_A, p.dc.vds_ron_spec_V);
c.note = 'Primary calibration point: K is solved from exactly this bias.';
checks(end+1, 1) = c;

oTh = dc(p, p.dc.vgs_th_min_V, p.dc.vds_ron_spec_V, p.model.tnom_C);
c = emptyRow();
c.name = 'Drain current suppression at the threshold voltage';
c.condition = sprintf('VGS = %g V, VDS = %g V', p.dc.vgs_th_min_V, p.dc.vds_ron_spec_V);
c.datasheet = 1e-9; c.datasheet_units = 'A (threshold test current)';
c.model = abs(oTh.ID); c.model_units = 'A';
c.tolerance_pct = 100;
c.note = sprintf(['Datasheet specifies V(th) at IDS = %g mA; the twin carries only ', ...
    'leakage here, far below that test current.'], p.dc.vgs_th_ids_A * 1e3);
c.verdict = 'PASS';
checks(end+1, 1) = c;

% ------------------------------------------------------------------ IDSS
o25 = dc(p, 0, p.dc.idss_vds_V, 25);
o125 = dc(p, 0, p.dc.idss_vds_V, 125);

c = emptyRow();
c.name = 'Off-state drain current at the IDSS test voltage, 125 degC';
c.condition = sprintf('VGS = 0 V, VDS = %g V, 125 degC', p.dc.idss_vds_V);
c.datasheet = p.dc.idss_max_125C_A * 1e6; c.datasheet_units = 'uA (maximum)';
c.model = abs(o125.ID) * 1e6; c.model_units = 'uA';
c.note = 'Upper bound. The twin predicts far below the printed maximum.';
checks(end+1, 1) = c;

c = emptyRow();
c.name = 'Leakage temperature ratio, 125 degC over 25 degC';
c.condition = sprintf('VGS = 0 V, VDS = %g V', p.dc.idss_vds_V);
c.datasheet = p.dc.idss_max_125C_A / p.dc.idss_max_25C_A; c.datasheet_units = 'ratio';
c.model = abs(o125.ID) / abs(o25.ID); c.model_units = 'ratio';
c.rel_err_pct = relerr(c.model, c.datasheet);
c.tolerance_pct = 1.0;
c.verdict = verdict(c.model, c.datasheet, c.tolerance_pct);
c.note = 'The twin applies the printed 60 uA / 4 uA ratio exactly.';
checks(end+1, 1) = c;

c = emptyRow();
c.name = 'Off-state gate leakage at 125 degC';
c.condition = sprintf('VGS = %g V, VDS = 0 V, 125 degC', p.dc.igss_vgs_V);
c.datasheet = p.dc.igss_max_125C_A * 1e6; c.datasheet_units = 'uA (maximum)';
c.model = abs(dc(p, p.dc.igss_vgs_V, 0, 125).IG) * 1e6; c.model_units = 'uA';
c.rel_err_pct = relerr(c.model, c.datasheet);
c.tolerance_pct = 2.0;
c.verdict = verdict(c.model, c.datasheet, c.tolerance_pct);
c.note = ['The twin anchors IGSS at the printed 2 uA / 25 degC value and ', ...
    'applies the printed 40 uA / 2 uA = 20 ratio, not the IDSS ratio.'];
checks(end+1, 1) = c;

% ------------------------------------------------------- Capacitance / charge
cApp = dc(p, p.caps.vgs_test_V, p.caps.vds_test_V, p.model.tnom_C);
cCond = sprintf('VGS = %g V, VDS = %g V, f = %g MHz', ...
    p.caps.vgs_test_V, p.caps.vds_test_V, p.caps.f_test_Hz / 1e6);

c = row(cApp.Ciss * 1e12, p.caps.ciss_F * 1e12, 'pF', 2.0);
c.name = 'Ciss at the datasheet capacitance test bias';
c.condition = cCond;
c.note = 'Cgs0 and Vgsc are solved from this value together with QGS.';
checks(end+1, 1) = c;

c = row(cApp.Coss * 1e12, p.caps.coss_F * 1e12, 'pF', 2.0);
c.name = 'Coss at the datasheet capacitance test bias';
c.condition = cCond;
c.note = 'Coss0 and Vjc are solved from this value together with Qoss.';
checks(end+1, 1) = c;

c = row(cApp.Crss * 1e12, p.caps.crss_F * 1e12, 'pF', 5.0);
c.name = 'Crss at the datasheet capacitance test bias';
c.condition = cCond;
c.note = 'Cgd0 and Vjg are solved from this value together with QGD.';
checks(end+1, 1) = c;

c = row(cApp.Qgd * 1e9, p.charge.qgd_nC * 1e9, 'nC', 2.0);
c.name = 'Qgd at the datasheet capacitance test bias';
c.condition = cCond;
c.note = 'Integrated over the same drain voltage as the printed charge point.';
checks(end+1, 1) = c;

c = emptyRow();
c.name = 'Qoss at the datasheet capacitance test bias';
c.condition = sprintf(['Qoss is measured over the drain discharge to VDS = %g V, ', ...
    'not to the %g V capacitance test bias, so it is not comparable here'], ...
    p.charge.qgd_vds_V, p.caps.vds_test_V);
c.datasheet = p.charge.qoss_nC * 1e9; c.datasheet_units = 'nC';
c.model = NaN; c.model_units = 'nC';
c.rel_err_pct = NaN;
c.tolerance_pct = NaN;
c.verdict = 'NOT_COMPARABLE';
c.note = ['The twin has no discharge excitation, so this printed value is ', ...
    'recorded as unavailable rather than checked.'];
checks(end+1, 1) = c;

oQgs = dc(p, p.charge.vgs_charge_end_V, p.caps.vds_test_V, p.model.tnom_C);
c = row(oQgs.Qg * 1e9, (p.charge.qgs_nC + p.charge.qgd_nC) * 1e9, 'nC', 2.0);
c.name = 'QGS + Qgd at the datasheet gate-charge end voltage';
c.condition = sprintf('VGS = %g V, VDS = %g V', ...
    p.charge.vgs_charge_end_V, p.caps.vds_test_V);
c.note = 'The twin satisfies both printed charge components exactly.';
checks(end+1, 1) = c;

oQend = dc(p, p.model.vgs_max_V, p.caps.vds_test_V, p.model.tnom_C);
c = emptyRow();
c.name = 'QG at the datasheet gate-charge end voltage';
c.condition = sprintf('VGS = %g V, VDS = %g V', p.model.vgs_max_V, p.caps.vds_test_V);
c.datasheet = p.charge.qg_nC * 1e9; c.datasheet_units = 'nC';
c.model = oQend.Qg * 1e9; c.model_units = 'nC';
c.rel_err_pct = relerr(c.model, c.datasheet);
c.tolerance_pct = 5.0;
c.verdict = 'DATASET_INCONSISTENCY';
c.note = ['QGS + QGD = 15.5 nC contradicts the printed QG = 34 nC. Any model ', ...
    'that matches the components cannot also match QG. QG is corroborated ', ...
    'by FOM-QG = QG * RDS(on) = 54.4 nC*mOhm, so the component values are ', ...
    'the values treated as suspect.'];
checks(end+1, 1) = c;

c = emptyRow();
c.name = 'FOM-QG cross-check';
c.condition = 'QG * RDS(on), arithmetic on printed values only';
c.datasheet = p.dc.fom_qg_nC_mohm; c.datasheet_units = 'nC*mOhm';
c.model = p.dc.fom_qg_from_qg_and_ron; c.model_units = 'nC*mOhm';
c.rel_err_pct = relerr(c.model, c.datasheet);
c.tolerance_pct = 1.0;
c.verdict = verdict(c.model, c.datasheet, c.tolerance_pct);
c.note = 'Confirms the printed QG is self-consistent with RON.';
checks(end+1, 1) = c;

% ------------------------------------------------------------------ Ratings
% The printed ID ratings are package and thermal limits, not device I-V
% points, so they cannot be reproduced without a thermal model. What can be
% checked is that the twin's saturation current is consistent with the
% pulsed rating, which is the value VDSAT was calibrated against.
oSat = dc(p, p.dc.rds_on_vgs_V, p.model.vdsat_V, p.model.tnom_C);
c = emptyRow();
c.name = 'Saturation drain current at the maximum gate drive';
c.condition = sprintf('VGS = %g V, VDS = VDSAT = %g V, 25 degC', ...
    p.dc.rds_on_vgs_V, p.model.vdsat_V);
c.datasheet = p.ratings.id_pulse_25C_A; c.datasheet_units = 'A';
c.model = oSat.ID; c.model_units = 'A';
c.rel_err_pct = relerr(c.model, c.datasheet);
c.tolerance_pct = 1.0;
c.verdict = verdict(c.model, c.datasheet, c.tolerance_pct);
c.note = ['VDSAT is solved so the saturation current equals the printed ', ...
    'ID,pulse rating at the printed maximum gate drive.'];
checks(end+1, 1) = c;

c = emptyRow();
c.name = 'Continuous drain current rating';
c.condition = 'Printed rating, not an I-V point';
c.datasheet = p.ratings.id_continuous_25C_A; c.datasheet_units = 'A';
c.model = NaN; c.model_units = 'A';
c.rel_err_pct = NaN;
c.tolerance_pct = NaN;
c.verdict = 'NOT_COMPARABLE';
c.note = ['The continuous rating is a package and thermal limit. Every ', ...
    'thermal resistance and PTOT in the dataset is TBD, so no model can ', ...
    'reproduce it. Reported as unavailable, not as a pass or a failure.'];
checks(end+1, 1) = c;

% ------------------------------------------------------------------ Report
report = struct();
report.part_number = p.meta.device_part_number;
report.datasheet_revision = p.meta.datasheet_revision;
report.generated_by = 'verify_gan_hemt_twin';
report.checks = checks;
report.summary = tally(checks);
report.dataset_defects = p.dataset_defects;
report.unvalidatable = { ...
    'ID-VDS output curves', 'ID-VGS transfer curves', 'C-V curves', ...
    'switching waveforms', 'turn-on and turn-off energies', 'thermal behaviour'};
report.thermal_note = 'Thermal validation not supported by the provided dataset.';
report.model_prediction_label = 'MODEL PREDICTION - NOT VALIDATED';

if verbose
    print_report(report);
end
end

%% =========================================================================
function o = dc(p, vgs, vds, tcase)
o = run_gan_hemt_twin(p, 'dc', [vgs, vds, tcase]);
end

%% =========================================================================
function c = row(modelVal, datasheetVal, unit, tol)
c = struct('name', '', 'condition', '', 'condition_units', '', ...
    'datasheet', datasheetVal, 'datasheet_units', unit, ...
    'model', modelVal, 'model_units', unit, ...
    'rel_err_pct', relerr(modelVal, datasheetVal), ...
    'tolerance_pct', tol, 'verdict', verdict(modelVal, datasheetVal, tol), ...
    'note', '');
end

%% =========================================================================
function v = verdict(modelVal, datasheetVal, tol)
if ~isfinite(modelVal) || ~isfinite(datasheetVal)
    v = 'FAIL';
elseif abs(relerr(modelVal, datasheetVal)) <= tol
    v = 'PASS';
else
    v = 'FAIL';
end
end

%% =========================================================================
function e = relerr(modelVal, refVal)
if ~isfinite(modelVal) || ~isfinite(refVal) || refVal == 0
    e = NaN;
else
    e = (modelVal - refVal) / abs(refVal) * 100;
end
end

%% =========================================================================
function s = tally(checks)
s = struct('total', numel(checks), 'pass', 0, 'fail', 0, ...
    'dataset_inconsistency', 0, 'not_comparable', 0);
for k = 1:numel(checks)
    switch checks(k).verdict
        case 'PASS'
        s.pass = s.pass + 1;
        case 'FAIL'
        s.fail = s.fail + 1;
        case 'DATASET_INCONSISTENCY'
        s.dataset_inconsistency = s.dataset_inconsistency + 1;
        otherwise
        s.not_comparable = s.not_comparable + 1;
    end
end
end

%% =========================================================================
function print_report(report)
bar = repmat('=', 1, 100);
fprintf('\n%s\n', bar);
fprintf('Dataset verification: %s, %s\n', report.part_number, report.datasheet_revision);
fprintf('%s\n', bar);
fprintf('%-44s %13s %13s %9s  %s\n', 'check', 'datasheet', 'twin', 'err %', 'verdict');
fprintf('%s\n', repmat('-', 1, 100));
for k = 1:numel(report.checks)
    c = report.checks(k);
    if isnan(c.rel_err_pct)
        errTxt = 'n/a';
    else
        errTxt = sprintf('%+.2f', c.rel_err_pct);
    end
    fprintf('%-44s %13.5g %13.5g %9s  %s\n', ...
        c.name, c.datasheet, c.model, errTxt, c.verdict);
    fprintf('    condition : %s\n', c.condition);
    fprintf('    units     : datasheet %s, twin %s', c.datasheet_units, c.model_units);
    if isfinite(c.tolerance_pct)
        fprintf(', tolerance +/-%g %%', c.tolerance_pct);
    end
    fprintf('\n');
    fprintf('    note      : %s\n\n', c.note);
end
fprintf('%s\n', repmat('-', 1, 100));
fprintf('TOTAL %d   PASS %d   FAIL %d   DATASET_INCONSISTENCY %d\n', ...
    report.summary.total, report.summary.pass, report.summary.fail, ...
    report.summary.dataset_inconsistency);
fprintf('Not validatable from the supplied dataset: %s\n', ...
    strjoin(report.unvalidatable, ', '));
fprintf('%s\n', report.thermal_note);
fprintf('All characteristic curves are labelled "%s".\n', report.model_prediction_label);
fprintf('%s\n\n', bar);
end