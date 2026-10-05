"""Streamlit dashboard for the GaN HEMT Digital Twin.

Read-only viewer over the existing Stage 1 / Phase 2 artefacts. It adds no
physics, no degradation law and no health score: every number on screen is read
from stage2_manifest.json, stress_analysis.json, exposure_indicators.json or
stress_dataset.csv, and anything the upstream artefacts record as unavailable is
shown as N/A.
"""

from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

import data_loader as dl

st.set_page_config(
    page_title="GaN HEMT Digital Twin",
    page_icon="*",
    layout="wide",
    initial_sidebar_state="collapsed",
)

st.markdown(
    """
    <style>
      .block-container { padding-top: 1.6rem; padding-bottom: 2rem; max-width: 1500px; }
      h1 { font-size: 1.5rem; letter-spacing: -.2px; margin-bottom: .1rem; }
      h2 { font-size: 1.02rem; text-transform: uppercase; letter-spacing: .6px;
           color: #334155; border-bottom: 1px solid #e2e8f0; padding-bottom: .3rem;
           margin-top: 1.2rem; }
      [data-testid="stMetricValue"] { font-size: 1.24rem; font-weight: 600; }
      [data-testid="stMetricLabel"] { font-size: .74rem; color: #64748b; }
      .card { border: 1px solid #e2e8f0; border-radius: 6px; padding: .5rem .65rem;
              background: #fbfcfe; }
      .card .k { font-size: .69rem; text-transform: uppercase; letter-spacing: .5px;
                 color: #64748b; margin-bottom: .12rem; }
      .card .v { font-size: .93rem; font-weight: 600; color: #0f172a; }
      .card .u { font-size: .74rem; font-weight: 400; color: #64748b; }
      .banner { border-left: 3px solid #b45309; background: #fffbeb;
                padding: .5rem .7rem; font-size: .8rem; color: #78350f; border-radius: 3px; }
      .sub { font-size: .82rem; color: #475569; }
      .na { color: #94a3b8; font-weight: 600; }
    </style>
    """,
    unsafe_allow_html=True,
)

PLOT_CONFIG = {"displayModeBar": False, "displaylogo": False}
ACCENT = "#1d4ed8"
ACCENT2 = "#b45309"
GRID = "#eef2f7"


def plot(fig: go.Figure, height: int = 320) -> None:
    """Render a Plotly figure with a compact, animation-free configuration."""
    fig.update_layout(
        height=height,
        margin=dict(l=8, r=8, t=26, b=8),
        font=dict(size=11),
        title_font=dict(size=12),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="left", x=0,
                    font=dict(size=10)),
        hoverlabel=dict(font_size=11),
        transition=dict(duration=0),
        paper_bgcolor="white",
        plot_bgcolor="white",
    )
    fig.update_xaxes(showgrid=True, gridcolor=GRID, zeroline=False, linecolor="#cbd5e1")
    fig.update_yaxes(showgrid=True, gridcolor=GRID, zeroline=False, linecolor="#cbd5e1")
    st.plotly_chart(fig, config=PLOT_CONFIG, width="stretch")


def num(value, digits: int = 4) -> str:
    """Plain numeric text for use inside st.metric (no HTML)."""
    if value is None or value != value:
        return "N/A"
    if abs(value) >= 10000 or (value != 0 and abs(value) < 0.0001):
        return f"{value:.4g}"
    return f"{value:.{digits}f}".rstrip("0").rstrip(".") or "0"


def card(label: str, value: str, unit: str = "") -> None:
    """One compact bordered parameter card. Never invents a value."""
    shown = value if value == "N/A" else f"{value} <span class='u'>{unit}</span>"
    st.markdown(
        f"<div class='card'><div class='k'>{label}</div>"
        f"<div class='v'>{shown}</div></div>",
        unsafe_allow_html=True,
    )


# ---------------------------------------------------------------------------
# Guard: fail loudly rather than render an empty dashboard
# ---------------------------------------------------------------------------
try:
    manifest = dl.load_manifest()
    stress = dl.load_stress()
    indicators = dl.load_indicators()
    frame = dl.load_stress_dataset()
except dl.MissingArtefact as exc:
    st.error(str(exc))
    st.stop()

device = dl.device_cards()
quality = dl.data_quality()

# ---------------------------------------------------------------------------
# 1. Header
# ---------------------------------------------------------------------------
st.title("GaN HEMT Digital Twin")
st.markdown(
    "<div class='sub'>Device Parameter &amp; Operating Stress Analysis</div>",
    unsafe_allow_html=True,
)
st.caption(
    f"Stage 2A validation and Phase 2B/2C stress analysis of "
    f"{device['manufacturer']} {device['part_number']} - "
    f"{quality['total_samples']:,} simulated samples across "
    f"{quality['trajectory_count']:,} operating trajectories."
)

# ---------------------------------------------------------------------------
# 2. Device cards
# ---------------------------------------------------------------------------
st.markdown("## Device")
dcols = st.columns(5)
for col, (label, value, sub) in zip(
    dcols,
    [
        ("Manufacturer", device["manufacturer"], ""),
        ("Part number", device["part_number"], ""),
        ("Technology", device["technology"], ""),
        ("Model status", "MODEL PREDICTION", "not validated"),
        ("Validation status", "NOT AVAILABLE", "no experimental data"),
    ],
):
    with col:
        note = f"<div class='u'>{sub}</div>" if sub else ""
        st.markdown(
            f"<div class='card'><div class='k'>{label}</div>"
            f"<div class='v'>{value}</div>{note}</div>",
            unsafe_allow_html=True,
        )

# ---------------------------------------------------------------------------
# 3. Current parameters
# ---------------------------------------------------------------------------
st.markdown("## Current parameters")
params = dl.current_parameters()
pcols = st.columns(5)
order = ["VGS", "VDS", "ID", "RON", "Tj", "Tcase", "Pcond", "Psw", "Ploss"]
for index, label in enumerate(order):
    entry = params[label]
    with pcols[index % 5]:
        card(label, num(entry["value"], 5), entry["unit"])
st.caption(
    "Latest value carried by the dataset for each channel. A channel with no "
    "usable numeric value is shown as N/A."
)

# ---------------------------------------------------------------------------
# 4. Interactive time-series
# ---------------------------------------------------------------------------
st.markdown("## Interactive time series")
sel = st.columns([1, 2, 2])
profiles = sorted(frame["profile"].unique().tolist())
chosen_profile = sel[0].selectbox("Profile", profiles, index=0)

profile_rows = frame[frame["profile"] == chosen_profile]
keys = sorted(profile_rows["operating_point_key"].unique().tolist())
chosen_key = sel[1].selectbox("Operating point", keys, index=0)
selected = sel[2].multiselect(
    "Channels",
    list(dl.TRACE_CHANNELS),
    default=["VDS", "ID"],
    help="Plotted against time for the selected operating point.",
)

trace = profile_rows[profile_rows["operating_point_key"] == chosen_key].sort_values("t_s")
if selected:
    fig = go.Figure()
    for channel in selected:
        column = dl.TRACE_CHANNELS[channel]
        fig.add_trace(go.Scattergl(
            x=trace["t_s"],
            y=trace[column],
            name=f"{channel} ({dl.TRACE_UNITS[channel]})",
            mode="lines",
            line=dict(width=1.6),
            connectgaps=False,
        ))
    fig.update_layout(
        title=f"{chosen_profile} - operating point {chosen_key} ({len(trace):,} samples)",
        xaxis_title="time (s)",
        yaxis_title="value",
    )
    plot(fig, height=320)
    st.caption(
        "Gaps in RON are samples the existing Phase 2 run flagged as not RON-valid. "
        "They are left empty rather than interpolated."
    )
else:
    st.info("Select at least one channel to plot.")

# ---------------------------------------------------------------------------
# 5. RON analysis
# ---------------------------------------------------------------------------
st.markdown("## RON analysis")
ron_stats = dl.ron_statistics()
ron = stress["on_resistance"]
spec = ron["at_spec_point"]

if ron_stats:
    rcols = st.columns(6)
    for col, label, key in zip(
        rcols[:5],
        ["RON minimum", "RON median", "RON P95", "RON P99", "RON maximum"],
        ["min_ohm", "median_ohm", "p95_ohm", "p99_ohm", "max_ohm"],
    ):
        col.metric(label, f"{num(ron_stats[key], 5)} ohm")
    rcols[5].metric(
        "RON-valid samples", f"{ron_stats['samples']:,}",
        help=f"{quality['ron_valid_pct']:.1f}% of {quality['total_samples']:,} samples",
    )
    st.caption(
        f"RON-valid samples only, per the existing Phase 2 flag: "
        f"{ron_stats['samples']:,} of {quality['total_samples']:,} "
        f"({quality['ron_valid_pct']:.1f}%). Percentiles are a display aggregation "
        "over that existing subset; no validity rule is re-implemented here."
    )
else:
    st.warning("No RON-valid samples in the dataset.")

ratios = st.columns(4)
ratios[0].metric("RON at printed test point", f"{num(spec['ron_ohm'], 6)} ohm")
ratios[1].metric(
    "RON / printed typical", f"{num(spec['ratio_to_typ'], 4)} x",
    help="Printed RDS(on) typical 1.6 mohm at IDS = 50 A, VGS = 5 V, VDS = 0.08 V",
)
ratios[2].metric("Margin to printed typical", num(1.0 - spec["ratio_to_typ"], 4))
temp_coeff = ron["temperature_coefficient"]
ratios[3].metric(
    "RON / printed maximum", f"{num(spec['margin_ratio_to_max'], 4)} margin",
    help="Ratio of the printed test point to the printed RDS(on) maximum of 2.2 mohm",
)
st.caption(
    "Temperature normalisation of RON is unavailable: the Stage 1 model carries no "
    "temperature term in its channel current, so RON varies by less than 1e-7 across "
    f"{temp_coeff.get('t_low_C', 25)}-{temp_coeff.get('t_high_C', 125)} degC."
)

ron_diag = indicators["ron_diagnostic"]
if ron_diag.get("available"):
    st.caption(
        f"The RON maximum is not used as a headroom indicator: "
        f"{ron_diag['max_ohm']:.4g} ohm ({ron_diag['max_to_printed_max']:.0f}x the "
        f"printed maximum) occurs in the {ron_diag['max_profile']} profile at "
        f"VDS = {ron_diag['max_vds_V']:g} V where the device is not fully enhanced, so "
        "VDS/ID there is a triode-region quantity rather than the datasheet RDS(on)."
    )

# ---------------------------------------------------------------------------
# 6. Rating utilisation
# ---------------------------------------------------------------------------
st.markdown("## Rating utilisation")
utilisation = dl.utilisation_maxima()
ucols = st.columns(len(utilisation))
for col, (column, entry) in zip(ucols, utilisation.items()):
    value = entry["value"]
    with col:
        if value is None:
            st.metric(entry["label"], "N/A")
            continue
        st.metric(entry["label"], f"{value:.3g} x")
        st.progress(max(0.0, min(1.0, value)))
        if value > 1.0:
            st.caption("stimulus above printed rating")
        elif value >= 0.999:
            st.caption("at printed rating")
        else:
            st.caption("within printed rating")

st.caption(
    "Worst case over the whole dataset. A utilisation above 1 means the simulated "
    "excitation drove that terminal past its printed limit; it is a property of the "
    "stimulus, not a measurement of the device. Dissipated-power utilisation is N/A "
    "because PTOT is unspecified in the source dataset."
)

# ---------------------------------------------------------------------------
# 7. Operating stress state
# ---------------------------------------------------------------------------
st.markdown("## Operating stress state")
st.markdown(
    "<div class='banner'><b>OPERATING STRESS STATE</b> - based on simulated operating "
    "exposure relative to available device ratings. It is not a measurement of "
    "physical degradation or RUL.</div>",
    unsafe_allow_html=True,
)

scols = st.columns(5)
scols[0].metric(
    "Samples outside rated envelope", f"{quality['outside_envelope_pct']:.1f} %",
    help=f"{quality['outside_envelope_count']:,} of {quality['total_samples']:,} samples",
)
scols[1].metric(
    "Worst ID vs continuous rating",
    f"{utilisation['id_continuous_rating_utilisation']['value']:.3g} x",
)
scols[2].metric(
    "Exposure indicators available",
    f"{indicators['available_count']} of {indicators['indicator_count']}",
)
scols[3].metric(
    "Indicators blocked", f"{indicators['blocked_count']}",
    help="; ".join(b["indicator"] for b in indicators["blocked_indicators"]),
)
scols[4].metric("Experimental validation", "NOT AVAILABLE")

with st.expander("Indicator detail and blocked quantities"):
    rows = []
    for key, rec in indicators["indicators"].items():
        rows.append({
            "indicator": key,
            "value": rec["value"],
            "unit": rec["unit"],
            "evidence": rec["evidence"],
            "margin to limit": rec["margin_to_limit"],
            "limit basis": rec["threshold_basis"],
            "blocked reason": rec["unavailable_reason"] or "",
        })
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")
    st.caption(indicators["not_a_health_assessment"])

# ---------------------------------------------------------------------------
# 8. Analysis tabs
# ---------------------------------------------------------------------------
st.markdown("## Analysis")
tab_iv, tab_tr, tab_cv, tab_sw, tab_th = st.tabs(
    ["I-V Characteristics", "Transfer", "Capacitance", "Switching", "Thermal"]
)

with tab_iv:
    out = dl.profile_frame("output")
    if out.empty:
        st.info("No output-characterisation rows in the dataset.")
    else:
        fig = go.Figure()
        for vgs, group in out.groupby("vgs_V"):
            group = group.sort_values("vds_V")
            fig.add_trace(go.Scattergl(
                x=group["vds_V"], y=group["id_A"], name=f"VGS = {vgs:g} V",
                mode="lines", line=dict(width=1.8), connectgaps=False))
        fig.update_layout(
            title="Output characteristic (profile: output)",
            xaxis_title="VDS (V)", yaxis_title="ID (A)")
        plot(fig, height=360)
        st.caption(
            f"{len(out):,} rows, {out['vgs_V'].nunique()} gate voltages. The "
            "datasheet contains no printed ID-VDS curve, so this is simulation "
            "output and not a datasheet overlay."
        )

with tab_tr:
    tr = dl.profile_frame("transfer").sort_values("vgs_V")
    if tr.empty:
        st.info("No transfer rows in the dataset.")
    else:
        fig = go.Figure()
        fig.add_trace(go.Scattergl(
            x=tr["vgs_V"], y=tr["id_A"], name="ID", mode="lines",
            line=dict(width=2, color=ACCENT), connectgaps=False))
        valid = tr["ron_valid"]
        fig.add_trace(go.Scattergl(
            x=tr.loc[valid, "vgs_V"], y=tr.loc[valid, "id_A"],
            name="RON-valid samples", mode="markers",
            marker=dict(size=5, color=ACCENT2)))
        fig.update_layout(
            title=f"Transfer characteristic at VDS = {tr['vds_V'].iloc[0]:g} V "
                  "(profile: transfer)",
            xaxis_title="VGS (V)", yaxis_title="ID (A)")
        plot(fig, height=360)
        st.caption(
            f"{len(tr):,} rows. Markers are the {int(valid.sum())} samples the "
            "existing Phase 2 run flagged RON-valid. No printed transfer curve "
            "exists in the datasheet."
        )

with tab_cv:
    cv = dl.profile_frame("capacitance")
    if cv.empty:
        st.info("No capacitance rows in the dataset.")
    else:
        fig = go.Figure()
        for column, name, colour in (
            ("coss_F", "Coss", ACCENT),
            ("crss_F", "Crss", ACCENT2),
            ("ciss_F", "Ciss", "#0f766e"),
        ):
            fig.add_trace(go.Scattergl(
                x=cv["vds_V"], y=cv[column] * 1e12, name=name, mode="lines",
                line=dict(width=1.8, color=colour), connectgaps=False))
        fig.update_layout(
            title="Capacitance vs drain voltage (profile: capacitance)",
            xaxis_title="VDS (V)", yaxis_title="capacitance (pF)")
        plot(fig, height=360)
        cap = stress["capacitance"]
        ccols = st.columns(4)
        ccols[0].metric("Printed Coss at test VDS", f"{num(cap['printed_coss_F'], 12)} F")
        ccols[1].metric("Modelled Coss at zero VDS", f"{num(cap['coss_at_zero_vds_F'], 12)} F")
        ccols[2].metric("Integrated Qoss", f"{num(cap['qoss_integrated_C'], 6)} C",
                        help=cap.get("qoss_note", ""))
        ccols[3].metric("Integrated Eoss", f"{num(cap['eoss_J'], 6)} J")
        st.caption(
            "The datasheet gives a single printed Coss point and no C-V curve. "
            "Values are converted from F to pF by 1e12 for display only."
        )

with tab_sw:
    sw = dl.profile_frame("switching")
    if sw.empty:
        st.info("No switching rows in the dataset.")
    else:
        sw_keys = sorted(sw["operating_point_key"].unique().tolist())
        pick = st.selectbox("Switching trajectory", sw_keys, index=0)
        window = sw[sw["operating_point_key"] == pick].sort_values("t_s")
        fig = go.Figure()
        fig.add_trace(go.Scattergl(
            x=window["t_s"], y=window["vds_V"], name="VDS (V)", mode="lines",
            line=dict(width=1.8, color=ACCENT)))
        fig.add_trace(go.Scattergl(
            x=window["t_s"], y=window["id_A"], name="ID (A)", mode="lines",
            line=dict(width=1.8, color=ACCENT2)))
        fig.update_layout(
            title=f"Switching waveform - operating point {pick}",
            xaxis_title="time (s)", yaxis_title="V / A")
        plot(fig, height=320)

        swj = stress["switching"]
        wcols = st.columns(4)
        wcols[0].metric("Transition windows", f"{swj['n_windows_resolved']}")
        wcols[1].metric("Turn-on / turn-off", f"{swj['n_turn_on']} / {swj['n_turn_off']}")
        wcols[2].metric("Load line reversible",
                        "Yes" if swj["reversibility"]["load_line_is_reversible"] else "No")
        wcols[3].metric("Switching energy per cycle", "NOT AVAILABLE")
        st.warning(
            "Switching loss is NOT AVAILABLE. " + swj["switching_loss_unavailable_reason"]
        )

with tab_th:
    th = dl.profile_frame("thermal")
    if th.empty:
        st.info("No thermal rows in the dataset.")
    else:
        fig = go.Figure()
        for tcase, group in th.groupby("tcase_C"):
            group = group.sort_values("vds_V")
            fig.add_trace(go.Scattergl(
                x=group["vds_V"], y=group["id_A"],
                name=f"Tcase = {tcase:g} degC", mode="lines",
                line=dict(width=1.8), connectgaps=False))
        fig.update_layout(
            title="Output characteristic by case temperature (profile: thermal)",
            xaxis_title="VDS (V)", yaxis_title="ID (A)")
        plot(fig, height=340)
        leak = indicators["leakage_diagnostic"]
        lcols = st.columns(3)
        if leak.get("available"):
            lcols[0].metric(
                "Leakage coefficient", f"{leak['coefficient_per_C']:.3e} /degC",
                help=f"Measured at {leak['matched_bias_points']} matched bias points "
                     f"between {leak['case_temperatures_C'][0]:g} and "
                     f"{leak['case_temperatures_C'][1]:g} degC")
            lcols[1].metric("Measured leakage ratio",
                            f"{leak['leakage_ratio_high_over_low']:.4f} x")
            lcols[2].metric("Stage 1 declared ratio",
                            f"{leak['model_declared_ratio']:.4f} x")
        else:
            lcols[0].metric("Leakage coefficient", "N/A")
        st.info(
            "Junction-temperature rise is unavailable: the dataset sets Tj = Tcase "
            "and every thermal resistance and PTOT are printed TBD, so no thermal "
            "model exists to derive it from."
        )

# ---------------------------------------------------------------------------
# 9. Data quality
# ---------------------------------------------------------------------------
st.markdown("## Data quality")
qcols = st.columns(5)
qcols[0].metric("Total samples", f"{quality['total_samples']:,}")
qcols[1].metric("RON-valid samples", f"{quality['ron_valid_samples']:,}")
qcols[2].metric("RON-valid percentage", f"{quality['ron_valid_pct']:.1f} %")
qcols[3].metric("Outside rated envelope", f"{quality['outside_envelope_pct']:.1f} %",
                help=f"{quality['outside_envelope_count']:,} samples")
qcols[4].metric("Experimental validation", "NOT AVAILABLE")

st.caption(
    f"Evidence class: {quality['evidence_class']}. "
    f"Is this an aging measurement: {'yes' if quality['is_aging_measurement'] else 'no'}. "
    f"Aging-time column present: {'yes' if frame['aging_time_h'].notna().any() else 'no'}."
)
with st.expander("Phase 2A quality checks by severity"):
    summary = manifest["quality_summary"]
    st.write(
        ", ".join(f"{k.upper()} {v}" for k, v in summary.items() if k != "total")
        + f" (total {summary['total']})"
    )
    st.markdown("**Blockers carried forward**")
    blocker_ids = ", ".join(
        f"`{b}`" if isinstance(b, str) else f"`{b.get('id', '?')}`"
        for b in manifest["blockers"]
    )
    st.write(blocker_ids)
    st.caption(
        "These are dataset limitations recorded by Phase 2A, not pipeline errors. "
        "They bound what the stress and exposure phases can legitimately claim."
    )

# ---------------------------------------------------------------------------
# 10. Provenance
# ---------------------------------------------------------------------------
st.markdown("## Provenance")
pcols = st.columns(4)
pcols[0].metric("Manufacturer", device["manufacturer"])
pcols[1].metric("Part number", device["part_number"])
pcols[2].metric("Technology", "AlGaN/GaN HEMT")
pcols[3].metric("Model status", "MODEL PREDICTION - NOT VALIDATED")

st.markdown(
    f"- **Model file**: `{device['model_file']}`  \n"
    f"- **Generated**: {device['generated_utc']} (MATLAB R{device['matlab_release']})  \n"
    f"- **Datasheet revision**: {device['datasheet_revision']}  \n"
    f"- **Package**: {device['package']}  \n"
    f"- **Authoritative source**: `stage1_output.mat` (Stage 1 read-only)  \n"
    f"- **Evidence class**: {quality['evidence_class']}  \n"
    f"- **Thermal note**: {device['thermal_note']}"
)

with st.expander("Generated reports"):
    st.markdown(
        "- `PHASE2A_REPORT.md` - validated dataset, equations, provenance\n"
        "- `stress_analysis_report.md` - Phase 2B stress and exposure analysis\n"
        "- `PHASE2C_REPORT.md` - Phase 2C exposure indicators and blocked quantities"
    )
    st.caption(
        indicators["required_limitation_statement"]
    )
