# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime

# ============================================================
# Live LP Recommendation v1
# ============================================================
# Purpose:
# Build a clean live/current recommendation report from the
# existing model outputs.
#
# This script does NOT add new rules.
# It reads the current model outputs and writes:
# - outputs/live_lp_recommendation_v1.csv
# - outputs/live_lp_recommendation_v1.md
#
# Model stack:
# - Historical base: Candidate 5f
# - External overlay: Deribit Widen Overlay v1
# - Current-state recommendation source:
#   current_state_probability_adjusted_lp_recommendation.csv
# ============================================================

ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs"

CURRENT_REC_FILE = OUTPUT_DIR / "current_state_probability_adjusted_lp_recommendation.csv"
BAND_TABLE_FILE = OUTPUT_DIR / "current_state_probability_adjusted_fcr_by_band.csv"
DERIBIT_SNAPSHOT_FILE = OUTPUT_DIR / "live_deribit_iv_rv_gap_snapshot.csv"
DISTRIBUTION_DIAGNOSTICS_FILE = OUTPUT_DIR / "current_state_band_distribution_diagnostics_v1.csv"

OUT_CSV = OUTPUT_DIR / "live_lp_recommendation_v1.csv"
OUT_MD = OUTPUT_DIR / "live_lp_recommendation_v1.md"

# Weekly model outputs should be judged from the END of the completed model week.
# A week_start of 2026-05-11 represents the completed week ending 2026-05-18.
STALE_DAYS_WARNING = 7

FCR_SKEW_NOTE = (
    "Mean FCR is shown for context but is not treated as the primary deployment signal. "
    "Because FCR divides LP fees by required fees, low required-fee denominator weeks can produce "
    "very high FCR values even when the dollar outcome is small. The report therefore prioritises "
    "median FCR, weak-rate, and expected net outcome vs hold when interpreting whether a setup is attractive."
)


def fmt_pct(x, decimals=1):
    if pd.isna(x):
        return "n/a"
    return f"{x * 100:.{decimals}f}%"


def fmt_num(x, decimals=2):
    if pd.isna(x):
        return "n/a"
    return f"{x:.{decimals}f}"


def fmt_money(x, decimals=2):
    if pd.isna(x):
        return "n/a"

    x = float(x)
    if x < 0:
        return f"-${abs(x):,.{decimals}f}"
    return f"${x:,.{decimals}f}"


def load_single_row(path: Path, name: str) -> pd.Series:
    if not path.exists():
        raise FileNotFoundError(f"Missing required file for {name}: {path}")

    df = pd.read_csv(path)

    if df.empty:
        raise ValueError(f"{name} file is empty: {path}")

    if len(df) > 1:
        print(f"Warning: {name} has {len(df)} rows. Using the first row.")

    return df.iloc[0]


def safe_get(row, col, default=np.nan):
    if col in row.index:
        return row[col]
    return default


def load_optional_csv(path: Path, name: str) -> pd.DataFrame:
    if not path.exists():
        print(f"Optional {name} file not found: {path}")
        return pd.DataFrame()

    df = pd.read_csv(path)
    if df.empty:
        print(f"Optional {name} file is empty: {path}")
    return df


def recommendation_action_label(model_rec):
    """
    Converts model text into a simpler action label.
    """
    if pd.isna(model_rec):
        return "UNKNOWN"

    rec = str(model_rec).strip().lower()

    if "avoid" in rec or "wait" in rec:
        return "WAIT"

    if "defensive" in rec:
        return "DEFENSIVE ONLY"

    if "deploy" in rec or "active" in rec:
        return "DEPLOY"

    return str(model_rec).strip()


def band_to_display(x):
    if pd.isna(x):
        return "n/a"

    try:
        val = float(x)
        if np.isclose(val, 0.05):
            return "5%"
        if np.isclose(val, 0.10):
            return "10%"
        if np.isclose(val, 0.20):
            return "20%"
        return f"{val:.0%}"
    except Exception:
        return str(x)


def normalise_date_string(x):
    if pd.isna(x):
        return "n/a"

    try:
        return pd.to_datetime(x).strftime("%Y-%m-%d")
    except Exception:
        return str(x)


def infer_latest_week_end(current_row: pd.Series):
    """
    Prefer an explicit latest_week_end if a future version of the pipeline adds it.
    Otherwise infer weekly model end as latest_week_start + 7 days.
    """
    latest_week_start = safe_get(current_row, "latest_week_start")
    explicit_week_end = safe_get(current_row, "latest_week_end")

    try:
        latest_week_start_dt = pd.to_datetime(latest_week_start)
    except Exception:
        return np.nan

    if pd.notna(explicit_week_end):
        try:
            return pd.to_datetime(explicit_week_end)
        except Exception:
            pass

    return latest_week_start_dt + pd.Timedelta(days=7)


def get_preferred_distribution_row(df: pd.DataFrame, preferred_band_label: str) -> pd.Series:
    if df.empty or "band" not in df.columns:
        return pd.Series(dtype="object")

    matches = df[df["band"].astype(str) == str(preferred_band_label)]
    if matches.empty:
        return pd.Series(dtype="object")

    return matches.iloc[0]


def calculate_staleness_days(current_row: pd.Series):
    """
    Weekly model staleness is measured from the completed model week END,
    not week_start. This avoids false stale warnings for normal weekly outputs.
    """
    latest_week_end = infer_latest_week_end(current_row)

    if pd.isna(latest_week_end):
        return np.nan

    try:
        now = datetime.now()
        latest_week_end_dt = pd.to_datetime(latest_week_end).to_pydatetime()
        return max((now.date() - latest_week_end_dt.date()).days, 0)
    except Exception:
        return np.nan


# ============================================================
# Load inputs
# ============================================================

print("Loading current recommendation...")
current = load_single_row(CURRENT_REC_FILE, "current recommendation")

print("Loading band table...")
band_df = pd.read_csv(BAND_TABLE_FILE)

if band_df.empty:
    raise ValueError(f"Band table is empty: {BAND_TABLE_FILE}")

print("Loading Deribit snapshot...")
deribit = load_single_row(DERIBIT_SNAPSHOT_FILE, "Deribit snapshot")

print("Loading distribution diagnostics...")
distribution_df = load_optional_csv(DISTRIBUTION_DIAGNOSTICS_FILE, "distribution diagnostics")

# ============================================================
# Extract main recommendation values
# ============================================================

latest_week_start = safe_get(current, "latest_week_start")
latest_week_end = infer_latest_week_end(current)

latest_week_start_label = normalise_date_string(latest_week_start)
latest_week_end_label = normalise_date_string(latest_week_end)

current_state = safe_get(current, "current_state")
state_age_weeks = safe_get(current, "state_age_weeks")
preferred_band = safe_get(current, "preferred_band")
preferred_band_label = band_to_display(preferred_band)

prob_adj_expected_fcr = safe_get(current, "probability_adjusted_expected_fcr")
prob_adj_weak_rate = safe_get(current, "probability_adjusted_weak_rate")
model_recommendation = safe_get(current, "probability_adjusted_recommendation")
final_action = recommendation_action_label(model_recommendation)

fragile_next_probability = safe_get(current, "fragile_next_probability")
favourable_next_probability = safe_get(current, "favourable_next_probability")
transition_away_probability = safe_get(current, "transition_away_probability")
persist_probability = safe_get(current, "persist_probability")
transition_risk_bucket = safe_get(current, "transition_risk_bucket")
most_likely_next_state = safe_get(current, "most_likely_next_state")
most_likely_next_state_probability = safe_get(current, "most_likely_next_state_probability")
transition_risk_summary = safe_get(current, "transition_risk_summary")

staleness_days = calculate_staleness_days(current)
is_stale = bool(pd.notna(staleness_days) and staleness_days > STALE_DAYS_WARNING)

# ============================================================
# Deribit snapshot values
# ============================================================

deribit_timestamp_utc = safe_get(deribit, "timestamp_utc")
chosen_expiry = safe_get(deribit, "chosen_expiry")
days_to_expiry = safe_get(deribit, "days_to_expiry")
deribit_iv = safe_get(deribit, "deribit_short_dated_iv_pct")
realised_vol = safe_get(deribit, "realised_vol_pct")
iv_rv_gap = safe_get(deribit, "iv_rv_gap_pct")
iv_rv_gap_bucket = safe_get(deribit, "iv_rv_gap_bucket")
rv_displacement_ratio = safe_get(deribit, "rv_displacement_ratio")

# ============================================================
# Band table cleanup
# ============================================================

band_df = band_df.copy()

band_display_rows = []

for _, row in band_df.iterrows():
    band_label = str(row.get("band", row.get("band_clean", "n/a")))

    band_display_rows.append({
        "band": band_label,
        "probability_adjusted_expected_fcr": row.get("probability_adjusted_expected_fcr", np.nan),
        "probability_adjusted_weak_rate": row.get("probability_adjusted_weak_rate", np.nan),
        "deribit_transition_adjusted_expected_fcr": row.get("deribit_transition_adjusted_expected_fcr", np.nan),
        "expected_move_to_band_ratio": row.get("expected_move_to_band_ratio", np.nan),
        "expected_move_risk": row.get("expected_move_risk", np.nan),
        "iv_rv_risk": row.get("iv_rv_risk", np.nan),
        "recommendation": row.get(
            "probability_adjusted_recommendation",
            row.get("deribit_transition_adjusted_recommendation", np.nan)
        ),
        "penalty_reasons": row.get("penalty_reasons", ""),
    })

band_summary_df = pd.DataFrame(band_display_rows)

band_order = {"5%": 1, "10%": 2, "20%": 3}
band_summary_df["band_order"] = band_summary_df["band"].map(band_order).fillna(99)
band_summary_df = band_summary_df.sort_values("band_order").drop(columns=["band_order"])

# ============================================================
# Distribution diagnostics cleanup
# ============================================================

distribution_summary_df = pd.DataFrame()
distribution_sample_basis = ""

if not distribution_df.empty:
    distribution_summary_df = distribution_df.copy()

    if "band" not in distribution_summary_df.columns and "band_clean" in distribution_summary_df.columns:
        distribution_summary_df["band"] = distribution_summary_df["band_clean"].apply(band_to_display)

    if "sample_basis" in distribution_summary_df.columns:
        distribution_sample_basis = str(distribution_summary_df["sample_basis"].dropna().iloc[0])

    if "band_clean" in distribution_summary_df.columns:
        distribution_summary_df["band_order"] = pd.to_numeric(
            distribution_summary_df["band_clean"],
            errors="coerce",
        )
    else:
        distribution_summary_df["band_order"] = distribution_summary_df["band"].map(band_order)

    distribution_summary_df = (
        distribution_summary_df
        .sort_values("band_order")
        .drop(columns=["band_order"])
    )

preferred_distribution = get_preferred_distribution_row(
    distribution_summary_df,
    preferred_band_label,
)

preferred_median_fcr = safe_get(preferred_distribution, "median_realised_fcr")
preferred_weak_rate = safe_get(preferred_distribution, "weak_rate")
preferred_expected_net_vs_hold = safe_get(preferred_distribution, "expected_net_outcome_vs_hold")
preferred_mean_fcr = safe_get(preferred_distribution, "mean_realised_fcr")

preferred_band_interpretation = ""
if not preferred_distribution.empty:
    preferred_band_interpretation = (
        f"Although the {preferred_band_label} band shows a high mean FCR of "
        f"{fmt_num(preferred_mean_fcr)}, the median FCR is {fmt_num(preferred_median_fcr)} "
        f"and expected net outcome vs hold is {fmt_money(preferred_expected_net_vs_hold)}. "
        "This supports the WAIT signal because the typical/risk-adjusted opportunity does not "
        "provide a strong margin of safety."
    )

# ============================================================
# Risk flags
# ============================================================

risk_flags = []

if is_stale:
    risk_flags.append(
        f"Current-state model output is stale: latest completed model week ended {latest_week_end_label}, "
        f"approximately {staleness_days} days ago."
    )

if pd.notna(fragile_next_probability) and fragile_next_probability >= 0.60:
    risk_flags.append(f"Fragile-next probability is high at {fmt_pct(fragile_next_probability)}.")

if pd.notna(transition_away_probability) and transition_away_probability >= 0.70:
    risk_flags.append(f"Transition-away probability is high at {fmt_pct(transition_away_probability)}.")

if pd.notna(prob_adj_weak_rate) and prob_adj_weak_rate >= 0.50:
    risk_flags.append(f"Probability-adjusted weak-rate is high at {fmt_pct(prob_adj_weak_rate)}.")

if pd.notna(iv_rv_gap) and iv_rv_gap > 5:
    risk_flags.append(f"IV/RV gap is elevated at {fmt_num(iv_rv_gap)} percentage points.")

if not risk_flags:
    risk_flags.append("No major risk flags triggered from the current live summary inputs.")

# ============================================================
# Final one-row output
# ============================================================

live_summary = {
    "generated_at_local": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    "latest_week_start": latest_week_start_label,
    "latest_week_end": latest_week_end_label,
    "staleness_days_from_week_end": staleness_days,
    "is_stale": is_stale,
    "current_state": current_state,
    "state_age_weeks": state_age_weeks,
    "preferred_band": preferred_band_label,
    "probability_adjusted_expected_fcr": prob_adj_expected_fcr,
    "probability_adjusted_weak_rate": prob_adj_weak_rate,
    "model_recommendation": model_recommendation,
    "final_action": final_action,
    "transition_risk_bucket": transition_risk_bucket,
    "persist_probability": persist_probability,
    "transition_away_probability": transition_away_probability,
    "favourable_next_probability": favourable_next_probability,
    "fragile_next_probability": fragile_next_probability,
    "most_likely_next_state": most_likely_next_state,
    "most_likely_next_state_probability": most_likely_next_state_probability,
    "deribit_timestamp_utc": deribit_timestamp_utc,
    "chosen_expiry": chosen_expiry,
    "days_to_expiry": days_to_expiry,
    "deribit_short_dated_iv_pct": deribit_iv,
    "realised_vol_pct": realised_vol,
    "iv_rv_gap_pct": iv_rv_gap,
    "iv_rv_gap_bucket": iv_rv_gap_bucket,
    "rv_displacement_ratio": rv_displacement_ratio,
    "risk_flags": " | ".join(risk_flags),
    "transition_risk_summary": transition_risk_summary,
}

live_summary_df = pd.DataFrame([live_summary])
live_summary_df.to_csv(OUT_CSV, index=False)

# ============================================================
# Markdown report
# ============================================================

md = []

md.append("# Live LP Recommendation v1")
md.append("")
md.append(f"Generated: **{live_summary['generated_at_local']}**")
md.append("")
md.append("## Final Recommendation")
md.append("")
md.append(f"**Action:** {final_action}")
md.append("")
md.append(f"**Model recommendation:** {model_recommendation}")
md.append("")
md.append(f"**Preferred band if forced:** {preferred_band_label}")
md.append("")
md.append("### Primary Reporting Hierarchy")
md.append("")
md.append("| Metric | Current reading |")
md.append("|---|---:|")
md.append(f"| Recommended action | **{final_action}** |")
md.append(f"| Preferred band if forced | **{preferred_band_label}** |")
md.append(f"| Median FCR / typical fee coverage | **{fmt_num(preferred_median_fcr)}** |")
md.append(f"| Historical distribution weak-rate | **{fmt_pct(preferred_weak_rate)}** |")
md.append(f"| Expected net outcome vs hold | **{fmt_money(preferred_expected_net_vs_hold)}** |")
md.append(f"| Mean FCR / upside-skew context | {fmt_num(preferred_mean_fcr)} |")
md.append(f"| Probability-adjusted expected FCR / model context | {fmt_num(prob_adj_expected_fcr)} |")
md.append(f"| Probability-adjusted weak-rate / transition-risk context | {fmt_pct(prob_adj_weak_rate)} |")
md.append("")
md.append(FCR_SKEW_NOTE)
md.append("")
md.append(
    "The historical distribution weak-rate measures comparable next-week outcomes in the current-state sample. "
    "The probability-adjusted weak-rate incorporates the model's transition layer and is used as broader risk context."
)
md.append("")
if preferred_band_interpretation:
    md.append(preferred_band_interpretation)
    md.append("")
md.append("")

md.append("## Current State")
md.append("")
md.append(f"- **Latest model week:** {latest_week_start_label} -> {latest_week_end_label}")
md.append(f"- **Staleness days from completed week end:** {staleness_days}")
md.append(f"- **Is stale:** {is_stale}")
md.append(f"- **Current state:** {current_state}")
md.append(f"- **State age:** {state_age_weeks} week(s)")
md.append(f"- **Transition risk bucket:** {transition_risk_bucket}")
md.append(f"- **Persist probability:** {fmt_pct(persist_probability)}")
md.append(f"- **Transition-away probability:** {fmt_pct(transition_away_probability)}")
md.append(f"- **Favourable-next probability:** {fmt_pct(favourable_next_probability)}")
md.append(f"- **Fragile-next probability:** {fmt_pct(fragile_next_probability)}")
md.append(f"- **Most likely next state:** {most_likely_next_state} ({fmt_pct(most_likely_next_state_probability)})")
md.append("")

if is_stale:
    md.append(
        "> **Staleness warning:** current-state model output appears stale relative to the completed model week end. "
        "Refresh upstream price/regime/Deribit inputs before treating this as a live trading recommendation."
    )
    md.append("")

md.append("## Deribit / Volatility Snapshot")
md.append("")
md.append(f"- **Snapshot timestamp UTC:** {deribit_timestamp_utc}")
md.append(f"- **Chosen expiry:** {chosen_expiry}")
md.append(f"- **Days to expiry:** {fmt_num(days_to_expiry)}")
md.append(f"- **Short-dated IV:** {fmt_num(deribit_iv)}%")
md.append(f"- **Realised vol:** {fmt_num(realised_vol)}%")
md.append(f"- **IV/RV gap:** {fmt_num(iv_rv_gap)} percentage points")
md.append(f"- **IV/RV bucket:** {iv_rv_gap_bucket}")
md.append(f"- **RV displacement ratio:** {fmt_num(rv_displacement_ratio, 3)}")
md.append("")

md.append("## Band Table")
md.append("")
md.append("| Band | Prob-adjusted FCR / model context | Prob-adjusted weak-rate | Expected move / band | Expected move risk | IV/RV risk | Recommendation |")
md.append("|---:|---:|---:|---:|---|---|---|")

for _, row in band_summary_df.iterrows():
    md.append(
        f"| {row['band']} "
        f"| {fmt_num(row['probability_adjusted_expected_fcr'])} "
        f"| {fmt_pct(row['probability_adjusted_weak_rate'])} "
        f"| {fmt_num(row['expected_move_to_band_ratio'])} "
        f"| {row['expected_move_risk']} "
        f"| {row['iv_rv_risk']} "
        f"| {row['recommendation']} |"
    )

md.append("")

if not distribution_summary_df.empty:
    md.append("## Current-State Outcome Distribution Diagnostics")
    md.append("")

    if distribution_sample_basis:
        md.append(f"Sample basis: {distribution_sample_basis}")
        md.append("")

    md.append("Mean FCR is retained as skew-sensitive context; the primary read is median FCR, weak-rate, and expected net outcome vs hold.")
    md.append("")

    md.append("| Band | Obs | Median FCR / typical fee coverage | Mean FCR (skew-sensitive) | P25 FCR | P75 FCR | Historical distribution weak-rate | Positive vs hold | Mean outcome vs hold | Median outcome vs hold | Expected required fees | Expected LP fees | Expected net vs hold |")
    md.append("|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")

    for _, row in distribution_summary_df.iterrows():
        md.append(
            f"| {row.get('band', 'n/a')} "
            f"| {int(row.get('sample_observations', 0))} "
            f"| {fmt_num(row.get('median_realised_fcr', np.nan))} "
            f"| {fmt_num(row.get('mean_realised_fcr', np.nan))} "
            f"| {fmt_num(row.get('p25_realised_fcr', np.nan))} "
            f"| {fmt_num(row.get('p75_realised_fcr', np.nan))} "
            f"| {fmt_pct(row.get('weak_rate', np.nan))} "
            f"| {fmt_pct(row.get('positive_vs_hold_rate', np.nan))} "
            f"| {fmt_money(row.get('mean_outcome_vs_hold', np.nan))} "
            f"| {fmt_money(row.get('median_outcome_vs_hold', np.nan))} "
            f"| {fmt_money(row.get('expected_required_fees', np.nan))} "
            f"| {fmt_money(row.get('expected_lp_fees', np.nan))} "
            f"| {fmt_money(row.get('expected_net_outcome_vs_hold', np.nan))} |"
        )

    md.append("")

md.append("## Main Risk Flags")
md.append("")

for flag in risk_flags:
    md.append(f"- {flag}")

md.append("")
md.append("## Interpretation")
md.append("")

if final_action == "WAIT":
    md.append(
        "The model is currently signalling **WAIT / avoid deployment**. "
        "The preferred band is shown for reference, but the typical fee-coverage and risk metrics do not show enough margin for deployment."
    )
    if preferred_band_interpretation:
        md.append("")
        md.append(preferred_band_interpretation)
elif final_action == "DEFENSIVE ONLY":
    md.append(
        "The model is signalling **defensive-only deployment**. "
        "This means the setup may be deployable, but only with conservative sizing, close monitoring, and awareness of transition/volatility risks."
    )
else:
    md.append(
        "The model is signalling an active deployment setup. "
        "The preferred band should be interpreted alongside the listed volatility, transition, and weak-rate risks."
    )

md.append("")
md.append("## Model Stack Note")
md.append("")
md.append("- Historical base policy: **Candidate 5f**")
md.append("- External/live-risk overlay: **Deribit Widen Overlay v1**")
md.append("- This live report is an orchestration/reporting layer. It does **not** add new optimisation rules.")
md.append("")

OUT_MD.write_text("\n".join(md), encoding="utf-8")

# ============================================================
# Console output
# ============================================================

print("\nLive LP Recommendation v1 complete.")
print("\nSaved outputs:")
print(f"- {OUT_CSV}")
print(f"- {OUT_MD}")

print("\nFinal recommendation:")
print(f"Action: {final_action}")
print(f"Model recommendation: {model_recommendation}")
print(f"Preferred band: {preferred_band_label}")
print(f"Probability-adjusted expected FCR: {fmt_num(prob_adj_expected_fcr)}")
print(f"Probability-adjusted weak-rate: {fmt_pct(prob_adj_weak_rate)}")
print(f"Current state: {current_state}")
print(f"Latest model week: {latest_week_start_label} -> {latest_week_end_label}")
print(f"Staleness days from week end: {staleness_days}")
print(f"Is stale: {is_stale}")

print("\nRisk flags:")
for flag in risk_flags:
    print(f"- {flag}")



