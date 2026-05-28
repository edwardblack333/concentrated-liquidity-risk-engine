# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

from pathlib import Path
from datetime import datetime
import argparse
import sys

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT / "outputs"

SIGNAL_SOURCE = OUTPUT_DIR / "candidate5e_10pct_to_5pct_high_shock_recommendations.csv"
REALISED_SOURCE = OUTPUT_DIR / "v3_tick_liquidity_fcr_monday_2023_present.csv"

OUT_AUDIT = OUTPUT_DIR / "recommendation_audit_v2.csv"
OUT_MD = OUTPUT_DIR / "recommendation_audit_v2.md"
OUT_BY_ACTION = OUTPUT_DIR / "recommendation_audit_v2_by_action.csv"
OUT_BY_BAND = OUTPUT_DIR / "recommendation_audit_v2_by_band.csv"
OUT_FALSE_WAITS = OUTPUT_DIR / "recommendation_audit_v2_false_waits.csv"
OUT_FALSE_DEPLOYS = OUTPUT_DIR / "recommendation_audit_v2_false_deploys.csv"
OUT_BAND_SELECTION = OUTPUT_DIR / "recommendation_audit_v2_band_selection.csv"

AUDIT_LABEL = "Historical recommendation audit / in-sample diagnostic validation"
TESTED_BANDS = ["5%", "10%", "20%"]


def parse_args():
    parser = argparse.ArgumentParser(description="Build recommendation audit v2 with all-band realised outcomes.")
    parser.add_argument(
        "--materiality-threshold",
        type=float,
        default=50.0,
        help="Dollar threshold used to flag material missed opportunities for WAIT rows.",
    )
    return parser.parse_args()


def read_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def clean_text(value, default=""):
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    text = str(value).strip()
    if text.lower() in {"", "nan", "none"}:
        return default
    return text


def parse_date(value):
    return pd.to_datetime(value, errors="coerce")


def fmt_date(value):
    dt = parse_date(value)
    if pd.isna(dt):
        return ""
    return dt.strftime("%Y-%m-%d")


def normalise_band(value):
    text = clean_text(value)
    if not text:
        return ""
    if text.upper() == "WAIT":
        return "WAIT"
    if text.endswith("%"):
        return text
    try:
        x = float(text)
    except Exception:
        return text
    if abs(x) <= 1:
        return f"{x * 100:.0f}%"
    return f"{x:.0f}%"


def band_suffix(band):
    return band.replace("%", "")


def action_from_choice(choice):
    band = normalise_band(choice)
    if band == "WAIT" or "wait" in clean_text(choice).lower():
        return "WAIT"
    if band:
        return "DEPLOY"
    return ""


def safe_float(value):
    try:
        if pd.isna(value):
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def bool_or_blank(value):
    if pd.isna(value):
        return np.nan
    return bool(value)


def inspect_file(path: Path):
    row = {
        "file": path.name,
        "exists": path.exists(),
        "rows": 0,
        "columns": "",
        "role": "",
    }
    if not path.exists():
        row["role"] = "missing"
        return row
    df = read_csv(path)
    row["rows"] = len(df)
    row["columns"] = ", ".join(df.columns[:30])
    if path == SIGNAL_SOURCE:
        row["role"] = "recommendation source"
    elif path == REALISED_SOURCE:
        row["role"] = "realised all-band LP outcome source"
    else:
        row["role"] = "context"
    return row


def build_realised_lookup(realised: pd.DataFrame, missing):
    required = {"week_start", "week_end", "band_clean", "realised_fcr", "outcome_vs_hold_after_fees"}
    missing_cols = sorted(required - set(realised.columns))
    if missing_cols:
        missing.append(f"Realised source missing columns: {', '.join(missing_cols)}")
        return {}

    lookup = {}
    for _, row in realised.iterrows():
        week = fmt_date(row.get("week_start"))
        band = normalise_band(row.get("band_clean"))
        if not week or band not in TESTED_BANDS:
            continue
        lookup[(week, band)] = {
            "week_end": fmt_date(row.get("week_end")),
            "realised_fcr": safe_float(row.get("realised_fcr")),
            "realised_outcome": safe_float(row.get("outcome_vs_hold_after_fees")),
        }
    return lookup


def rank_band(outcomes, band):
    available = {b: v for b, v in outcomes.items() if not pd.isna(v)}
    if band not in available:
        return np.nan
    ordered = sorted(available.items(), key=lambda item: item[1], reverse=True)
    for idx, (candidate, _) in enumerate(ordered, start=1):
        if candidate == band:
            return idx
    return np.nan


def best_worst(outcomes):
    available = {b: v for b, v in outcomes.items() if not pd.isna(v)}
    if not available:
        return "", np.nan, "", np.nan
    best_band = max(available, key=available.get)
    worst_band = min(available, key=available.get)
    return best_band, available[best_band], worst_band, available[worst_band]


def build_audit(signals: pd.DataFrame, realised_lookup, materiality_threshold, missing):
    required = {"feature_week_start", "target_week_start", "current_state", "candidate5e_choice"}
    missing_cols = sorted(required - set(signals.columns))
    if missing_cols:
        missing.append(f"Signal source missing columns: {', '.join(missing_cols)}")
        if "candidate5e_choice" not in signals.columns:
            return pd.DataFrame()

    rows = []
    for _, source_row in signals.iterrows():
        model_week_start = fmt_date(source_row.get("feature_week_start"))
        model_week_end = fmt_date(parse_date(model_week_start) + pd.Timedelta(days=7))
        realised_week_start = fmt_date(source_row.get("target_week_start"))
        realised_week_end = ""

        recommendation = clean_text(source_row.get("candidate5e_choice"))
        action = action_from_choice(recommendation)
        preferred_band = normalise_band(recommendation)
        deployed_band = preferred_band if action != "WAIT" and preferred_band in TESTED_BANDS else ""

        fcr = {}
        outcomes = {}
        weak = {}
        weak_fcr = {}
        weak_economic = {}
        positive = {}
        for band in TESTED_BANDS:
            data = realised_lookup.get((realised_week_start, band), {})
            if data and not realised_week_end:
                realised_week_end = data.get("week_end", "")
            fcr[band] = data.get("realised_fcr", np.nan)
            outcomes[band] = data.get("realised_outcome", np.nan)
            weak_fcr[band] = fcr[band] < 1 if not pd.isna(fcr[band]) else np.nan
            weak_economic[band] = outcomes[band] < 0 if not pd.isna(outcomes[band]) else np.nan
            if not pd.isna(weak_economic[band]):
                weak[band] = weak_economic[band]
            elif not pd.isna(weak_fcr[band]):
                weak[band] = weak_fcr[band]
            else:
                weak[band] = np.nan
            positive[band] = outcomes[band] > 0 if not pd.isna(outcomes[band]) else np.nan

        if not realised_week_end and realised_week_start:
            realised_week_end = fmt_date(parse_date(realised_week_start) + pd.Timedelta(days=7))

        available_weak = [weak[b] for b in TESTED_BANDS if not pd.isna(weak[b])]
        available_positive = [positive[b] for b in TESTED_BANDS if not pd.isna(positive[b])]
        all_bands_weak = all(available_weak) if available_weak else np.nan
        any_band_positive = any(available_positive) if available_positive else np.nan
        all_bands_positive = all(available_positive) if available_positive else np.nan

        best_band, best_outcome, worst_band, worst_outcome = best_worst(outcomes)
        chosen_outcome = outcomes.get(deployed_band, np.nan) if deployed_band else np.nan
        chosen_fcr = fcr.get(deployed_band, np.nan) if deployed_band else np.nan
        chosen_weak = weak.get(deployed_band, np.nan) if deployed_band else np.nan
        chosen_positive = positive.get(deployed_band, np.nan) if deployed_band else np.nan
        chosen_rank = rank_band(outcomes, deployed_band) if deployed_band else np.nan
        chosen_was_best = chosen_rank == 1 if not pd.isna(chosen_rank) else np.nan

        wait_hard_correct = action == "WAIT" and all_bands_weak is True
        wait_soft_correct = np.nan
        wait_false_positive = (
            action == "WAIT"
            and (
                all_bands_positive is True
                or (not pd.isna(best_outcome) and best_outcome > materiality_threshold)
            )
        )
        missed_opportunity = best_outcome if action == "WAIT" and not pd.isna(best_outcome) and best_outcome > 0 else 0.0 if action == "WAIT" else np.nan

        deploy_correct = action != "WAIT" and not pd.isna(chosen_outcome) and chosen_outcome > 0
        false_deploy = action != "WAIT" and not pd.isna(chosen_outcome) and chosen_outcome < 0
        nonchosen_positive = any(
            positive[b] is True for b in TESTED_BANDS if b != deployed_band and not pd.isna(positive[b])
        )
        severe_band_miss = bool(false_deploy and nonchosen_positive)

        out = {
            "audit_type": AUDIT_LABEL,
            "signal_source_file": SIGNAL_SOURCE.name,
            "realised_outcome_source_file": REALISED_SOURCE.name,
            "alignment_assumption": "feature/model week is aligned to next-week realised LP outcomes via target_week_start == realised week_start",
            "model_week_start": model_week_start,
            "model_week_end": model_week_end,
            "realised_week_start": realised_week_start,
            "realised_week_end": realised_week_end,
            "regime_state": clean_text(source_row.get("current_state")),
            "regime_label": clean_text(source_row.get("regime_label")),
            "recommendation": recommendation,
            "model_action": action,
            "preferred_band": preferred_band,
            "deployed_band": deployed_band,
            "expected_fcr": source_row.get("expected_fcr", np.nan),
            "expected_fcr_capped": source_row.get("expected_fcr_capped", np.nan),
            "expected_weak_rate": source_row.get("expected_weak_rate", np.nan),
            "expected_outcome_vs_hold": source_row.get("expected_outcome_vs_hold", np.nan),
            "realised_fcr_chosen_band": chosen_fcr,
            "realised_outcome_chosen_band": chosen_outcome,
            "best_realised_band": best_band,
            "best_realised_outcome": best_outcome,
            "worst_realised_band": worst_band,
            "worst_realised_outcome": worst_outcome,
            "all_bands_weak": bool_or_blank(all_bands_weak),
            "any_band_positive": bool_or_blank(any_band_positive),
            "all_bands_positive": bool_or_blank(all_bands_positive),
            "chosen_band_rank": chosen_rank,
            "chosen_band_was_best": bool_or_blank(chosen_was_best),
            "chosen_band_was_positive": bool_or_blank(chosen_positive),
            "chosen_band_was_weak": bool_or_blank(chosen_weak),
            "wait_soft_correct": wait_soft_correct,
            "wait_hard_correct": bool(wait_hard_correct) if action == "WAIT" else np.nan,
            "wait_false_positive": bool(wait_false_positive) if action == "WAIT" else np.nan,
            "missed_opportunity_if_wait": missed_opportunity,
            "deploy_correct": bool(deploy_correct) if action != "WAIT" else np.nan,
            "false_deploy": bool(false_deploy) if action != "WAIT" else np.nan,
            "severe_band_miss": bool(severe_band_miss) if action != "WAIT" else np.nan,
            "materiality_threshold_usd": materiality_threshold,
            "decision_reason": clean_text(source_row.get("decision_reason", source_row.get("reason"))),
            "risk_reasons": clean_text(source_row.get("candidate5e_rule_reason")),
            "caveat": "Historical diagnostic/in-sample validation; not a clean out-of-sample backtest unless generation timing is separately proven.",
        }
        for band in TESTED_BANDS:
            suffix = band_suffix(band)
            out[f"realised_fcr_{suffix}"] = fcr[band]
            out[f"realised_outcome_{suffix}"] = outcomes[band]
            out[f"weak_fcr_{suffix}"] = bool_or_blank(weak_fcr[band])
            out[f"weak_{suffix}"] = bool_or_blank(weak[band])
            out[f"positive_{suffix}"] = bool_or_blank(positive[band])

        rows.append(out)

    return pd.DataFrame(rows)


def rate(series):
    clean = series.dropna()
    if clean.empty:
        return np.nan
    return clean.astype(bool).mean()


def build_by_action(audit: pd.DataFrame):
    rows = []
    for action, group in audit.groupby("model_action", dropna=False):
        rows.append({
            "model_action": action,
            "rows": len(group),
            "deploy_like_rows": int((group["model_action"] != "WAIT").sum()),
            "wait_rows": int((group["model_action"] == "WAIT").sum()),
            "chosen_band_weak_rate": rate(group["chosen_band_was_weak"]),
            "chosen_band_positive_rate": rate(group["chosen_band_was_positive"]),
            "median_chosen_band_outcome": group["realised_outcome_chosen_band"].median(),
            "median_best_realised_outcome": group["best_realised_outcome"].median(),
            "wait_hard_correct_rate": rate(group["wait_hard_correct"]),
            "wait_false_positive_rate": rate(group["wait_false_positive"]),
            "median_missed_opportunity_if_wait": group["missed_opportunity_if_wait"].dropna().median(),
            "false_deploy_count": int(group["false_deploy"].fillna(False).astype(bool).sum()),
            "severe_band_miss_count": int(group["severe_band_miss"].fillna(False).astype(bool).sum()),
        })
    return pd.DataFrame(rows)


def build_by_band(audit: pd.DataFrame):
    deploy = audit[audit["model_action"] != "WAIT"].copy()
    if deploy.empty:
        return pd.DataFrame()
    return deploy.groupby("deployed_band", dropna=False).agg(
        rows=("deployed_band", "size"),
        weak_rate=("chosen_band_was_weak", lambda x: rate(x)),
        positive_rate=("chosen_band_was_positive", lambda x: rate(x)),
        median_outcome=("realised_outcome_chosen_band", "median"),
        mean_outcome=("realised_outcome_chosen_band", "mean"),
        chosen_best_rate=("chosen_band_was_best", lambda x: rate(x)),
        median_rank=("chosen_band_rank", "median"),
        false_deploy_count=("false_deploy", lambda x: int(x.fillna(False).astype(bool).sum())),
        severe_band_miss_count=("severe_band_miss", lambda x: int(x.fillna(False).astype(bool).sum())),
    ).reset_index()


def build_band_selection(audit: pd.DataFrame):
    deploy = audit[audit["model_action"] != "WAIT"].copy()
    if deploy.empty:
        return pd.DataFrame()
    rank_counts = deploy["chosen_band_rank"].value_counts(dropna=False).sort_index()
    rows = [{
        "metric": "deploy_rows",
        "value": len(deploy),
    }, {
        "metric": "chosen_band_best_rate",
        "value": rate(deploy["chosen_band_was_best"]),
    }, {
        "metric": "chosen_band_positive_rate",
        "value": rate(deploy["chosen_band_was_positive"]),
    }, {
        "metric": "severe_band_miss_count",
        "value": int(deploy["severe_band_miss"].fillna(False).astype(bool).sum()),
    }]
    for rank, count in rank_counts.items():
        rows.append({"metric": f"chosen_band_rank_{rank}", "value": count})
    return pd.DataFrame(rows)


def pct(value):
    try:
        if pd.isna(value):
            return "n/a"
        return f"{float(value) * 100:.1f}%"
    except Exception:
        return "n/a"


def money(value):
    try:
        if pd.isna(value):
            return "n/a"
        x = float(value)
    except Exception:
        return "n/a"
    return f"-${abs(x):,.0f}" if x < 0 else f"${x:,.0f}"


def build_markdown(audit, by_action, by_band, false_waits, false_deploys, band_selection, inventory, missing, materiality_threshold):
    rows = len(audit)
    wait = audit[audit["model_action"] == "WAIT"]
    deploy = audit[audit["model_action"] != "WAIT"]
    deploy_weak_rate = rate(deploy["chosen_band_was_weak"]) if not deploy.empty else np.nan
    deploy_positive_rate = rate(deploy["chosen_band_was_positive"]) if not deploy.empty else np.nan
    deploy_median = deploy["realised_outcome_chosen_band"].median() if not deploy.empty else np.nan
    false_deploy_count = int(deploy["false_deploy"].fillna(False).astype(bool).sum()) if not deploy.empty else 0
    wait_hard_rate = rate(wait["wait_hard_correct"]) if not wait.empty else np.nan
    wait_false_rate = rate(wait["wait_false_positive"]) if not wait.empty else np.nan
    missed_median = wait["missed_opportunity_if_wait"].median() if not wait.empty else np.nan
    best_rate = rate(deploy["chosen_band_was_best"]) if not deploy.empty else np.nan
    severe_count = int(deploy["severe_band_miss"].fillna(False).astype(bool).sum()) if not deploy.empty else 0

    lines = [
        f"# {AUDIT_LABEL} v2",
        "",
        f"Generated: **{datetime.now().strftime('%Y-%m-%d %H:%M:%S')}**",
        "",
        "## Caveat",
        "",
        "This is a historical recommendation audit / in-sample diagnostic validation. "
        "It should not be described as a clean out-of-sample backtest unless generation timing is separately proven.",
        "",
        "## Source files used",
        "",
        f"- Recommendation source: `{SIGNAL_SOURCE.name}`",
        f"- Realised all-band LP outcome source: `{REALISED_SOURCE.name}`",
        "",
        "## Alignment",
        "",
        "Each recommendation row uses `feature_week_start` as the model/signal week and aligns to next-week realised LP outcomes using `target_week_start == week_start` in the realised outcome file. The realised bands are 5%, 10%, and 20% where available.",
        "",
        "## Headline results",
        "",
        f"- Rows audited: **{rows}**",
        f"- WAIT rows: **{len(wait)}**",
        f"- Deploy-like rows: **{len(deploy)}**",
        "",
        "## Deploy-like performance",
        "",
        f"- Chosen-band weak rate: **{pct(deploy_weak_rate)}**",
        f"- Chosen-band positive rate: **{pct(deploy_positive_rate)}**",
        f"- Median chosen-band outcome: **{money(deploy_median)}**",
        f"- False deploy count: **{false_deploy_count}**",
        "",
        "## WAIT performance",
        "",
        f"- Hard-correct WAIT rate: **{pct(wait_hard_rate)}**",
        f"- False-WAIT rate: **{pct(wait_false_rate)}** using materiality threshold **{money(materiality_threshold)}**",
        f"- Median missed opportunity if WAIT: **{money(missed_median)}**",
        "",
        "Largest missed opportunities:",
        "",
    ]
    if false_waits.empty:
        lines.append("- None.")
    else:
        for _, row in false_waits.head(8).iterrows():
            lines.append(
                f"- {row['realised_week_start']} / {row['regime_state']}: best band {row['best_realised_band']} "
                f"earned {money(row['best_realised_outcome'])}."
            )

    lines.extend([
        "",
        "## Band-selection performance",
        "",
        f"- Chosen band best-rate: **{pct(best_rate)}**",
        f"- Chosen band positive-rate: **{pct(deploy_positive_rate)}**",
        f"- Severe band miss count: **{severe_count}**",
        "",
    ])
    if not by_band.empty:
        lines.extend(["By deployed band:", ""])
        for _, row in by_band.iterrows():
            lines.append(
                f"- {row['deployed_band']}: rows {int(row['rows'])}, weak rate {pct(row['weak_rate'])}, "
                f"median outcome {money(row['median_outcome'])}, best-rate {pct(row['chosen_best_rate'])}."
            )

    lines.extend(["", "## Worst false deploys", ""])
    if false_deploys.empty:
        lines.append("- None.")
    else:
        for _, row in false_deploys.head(8).iterrows():
            lines.append(
                f"- {row['realised_week_start']} / {row['regime_state']} / chosen {row['deployed_band']}: "
                f"{money(row['realised_outcome_chosen_band'])}, FCR {row['realised_fcr_chosen_band']:.2f}; "
                f"best band {row['best_realised_band']} earned {money(row['best_realised_outcome'])}."
            )

    lines.extend([
        "",
        "## Caveats",
        "",
        "- The source is a historical diagnostic candidate-policy file, not a proven append-only live signal ledger.",
        "- The audit attaches realised all-band outcomes after the fact; use it for diagnostic validation, not performance marketing.",
        "- WAIT soft-correct is left blank because the source has no single deployed reference band for WAIT rows.",
        "- Economic weak flags use outcome versus holding below zero. FCR weak flags are also reported separately.",
        "- Results are specific to the available Uniswap v3 ETH/USDC 0.05% 5%, 10%, and 20% test bands.",
        "",
        "## Recommended v3 improvements",
        "",
        "- Build an append-only timestamped live signal ledger before outcomes exist.",
        "- Preserve the exact production recommendation schema for every historical signal.",
        "- Add explicit default/reference band for WAIT rows, if one is intended.",
        "- Add slippage/gas/operational assumptions if turning this into a capital deployment backtest.",
        "- Separate research candidate-policy diagnostics from production/live model audits.",
        "- Add confidence intervals by regime, band, and sample size.",
        "",
        "## Missing columns / assumptions",
        "",
    ])
    if missing:
        lines.extend([f"- {item}" for item in missing])
    else:
        lines.append("- Required columns were available for the v2 all-band diagnostic audit.")

    lines.extend(["", "## File inventory", "", "| File | Exists | Rows | Role | Columns sample |", "|---|---:|---:|---|---|"])
    for row in inventory:
        lines.append(f"| {row['file']} | {row['exists']} | {row['rows']} | {row['role']} | {row['columns'][:140]} |")

    return "\n".join(lines) + "\n"


def main():
    args = parse_args()
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    missing = []
    print(f"Building {AUDIT_LABEL} v2...")
    print(f"Recommendation source: {SIGNAL_SOURCE}")
    print(f"Realised outcome source: {REALISED_SOURCE}")

    inventory = [
        inspect_file(SIGNAL_SOURCE),
        inspect_file(REALISED_SOURCE),
        inspect_file(OUTPUT_DIR / "recommendation_audit_v1.csv"),
        inspect_file(OUTPUT_DIR / "lp_recommendation_signal_history.csv"),
    ]
    for item in inventory:
        print(f"- {item['role']}: {item['file']} exists={item['exists']} rows={item['rows']}")

    signals = read_csv(SIGNAL_SOURCE)
    realised = read_csv(REALISED_SOURCE)
    realised_lookup = build_realised_lookup(realised, missing)
    audit = build_audit(signals, realised_lookup, args.materiality_threshold, missing)

    if audit.empty:
        missing.append("No audit rows were created.")

    by_action = build_by_action(audit) if not audit.empty else pd.DataFrame()
    by_band = build_by_band(audit) if not audit.empty else pd.DataFrame()
    false_waits = (
        audit[audit["wait_false_positive"].fillna(False).astype(bool)]
        .sort_values("missed_opportunity_if_wait", ascending=False)
        if not audit.empty else pd.DataFrame()
    )
    false_deploys = (
        audit[audit["false_deploy"].fillna(False).astype(bool)]
        .sort_values("realised_outcome_chosen_band", ascending=True)
        if not audit.empty else pd.DataFrame()
    )
    band_selection = build_band_selection(audit) if not audit.empty else pd.DataFrame()

    audit.to_csv(OUT_AUDIT, index=False)
    by_action.to_csv(OUT_BY_ACTION, index=False)
    by_band.to_csv(OUT_BY_BAND, index=False)
    false_waits.to_csv(OUT_FALSE_WAITS, index=False)
    false_deploys.to_csv(OUT_FALSE_DEPLOYS, index=False)
    band_selection.to_csv(OUT_BAND_SELECTION, index=False)

    md = build_markdown(
        audit,
        by_action,
        by_band,
        false_waits,
        false_deploys,
        band_selection,
        inventory,
        missing,
        args.materiality_threshold,
    )
    OUT_MD.write_text(md, encoding="utf-8")

    print(f"Saved: {OUT_AUDIT}")
    print(f"Saved: {OUT_MD}")
    print(f"Saved: {OUT_BY_ACTION}")
    print(f"Saved: {OUT_BY_BAND}")
    print(f"Saved: {OUT_FALSE_WAITS}")
    print(f"Saved: {OUT_FALSE_DEPLOYS}")
    print(f"Saved: {OUT_BAND_SELECTION}")
    print("Done.")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise



