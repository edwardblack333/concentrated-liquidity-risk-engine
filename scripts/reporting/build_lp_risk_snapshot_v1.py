# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

import pandas as pd
import numpy as np
from pathlib import Path
from datetime import datetime
import argparse
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.core.pool_config import load_pool_config

ROOT = PROJECT_ROOT
OUTPUT_DIR = ROOT / "outputs"

LIVE_REC_FILE = OUTPUT_DIR / "live_lp_recommendation_v1.csv"
LIVE_REC_MD = OUTPUT_DIR / "live_lp_recommendation_v1.md"

FRAGILITY_FILE = OUTPUT_DIR / "live_fragility_monitor_v1.csv"
FRESHNESS_FILE = OUTPUT_DIR / "live_data_freshness_audit.csv"
FRESHNESS_MD = OUTPUT_DIR / "live_data_freshness_audit.md"

OUT_MD = OUTPUT_DIR / "lp_risk_snapshot_v1.md"
OUT_TXT = OUTPUT_DIR / "lp_risk_snapshot_v1.txt"

DEFAULT_POOL_ID = "eth_usdc_005"


def parse_args():
    parser = argparse.ArgumentParser(description="Build the LP risk snapshot report.")
    parser.add_argument("--pool-id", default=DEFAULT_POOL_ID)
    return parser.parse_args()


def pool_pair_label(pool):
    display_name = str(pool.get("display_name", "")).strip()
    for part in display_name.split():
        if "/" in part:
            return part

    quote = pool.get("quote_asset") or pool.get("token0")
    base = pool.get("token1")
    if quote and base:
        return f"{base}/{quote}"
    return pool.get("display_name", "LP")


def pool_metadata_lines(pool):
    price_symbol = pool.get("price_source", {}).get("symbol", "Unavailable")
    bands = ", ".join(fmt_pct(band, 0) for band in pool.get("bands", []))
    return [
        f"Pool focus: **{pool.get('display_name', 'Unavailable')}**",
        f"Pool ID: **{pool.get('pool_id', 'Unavailable')}**",
        f"Chain / protocol: **{pool.get('chain', 'Unavailable')} / {pool.get('protocol', 'Unavailable')}**",
        f"Pool address: **{pool.get('pool_address', 'Unavailable')}**",
        f"Tokens / fee tier: **{pool.get('token0', 'Unavailable')}-{pool.get('token1', 'Unavailable')} / {pool.get('fee_tier_bps', 'Unavailable')} bps**",
        f"Quote asset / price source: **{pool.get('quote_asset', 'Unavailable')} / {price_symbol}**",
        f"Configured bands: **{bands or 'Unavailable'}**",
    ]


def load_optional_csv(path: Path, name: str):
    if not path.exists():
        print(f"Missing optional file: {name} | {path}")
        return None
    print(f"Loading {name}: {path}")
    return pd.read_csv(path)


def get_latest_row(df):
    if df is None or df.empty:
        return {}
    return df.tail(1).iloc[0].to_dict()


def first_available(row, candidates, default="Unavailable"):
    for c in candidates:
        if c in row and pd.notna(row[c]):
            return row[c]
    return default


def fmt_num(x, decimals=2, default="Unavailable"):
    try:
        if pd.isna(x):
            return default
        return f"{float(x):.{decimals}f}"
    except Exception:
        return default


def fmt_pct(x, decimals=1, default="Unavailable"):
    try:
        if pd.isna(x):
            return default

        x = float(x)

        # Handles both 0.622 and 62.2 formats.
        if abs(x) <= 1:
            x *= 100

        return f"{x:.{decimals}f}%"
    except Exception:
        return default


def clean_action(x):
    if x is None:
        return "Unavailable"
    return str(x).strip()


def classify_client_risk(action, weak_rate, fragility_bucket):
    action_s = str(action).lower()
    frag_s = str(fragility_bucket).lower()

    weak = np.nan
    try:
        weak = float(weak_rate)
        if abs(weak) <= 1:
            weak *= 100
    except Exception:
        pass

    if "stand down" in frag_s or "high fragility" in frag_s:
        return "High short-horizon entry risk"

    if "wait" in action_s or "avoid" in action_s:
        return "High regime risk"

    if pd.notna(weak) and weak >= 50:
        return "Elevated weak-outcome risk"

    if "elevated" in frag_s:
        return "Elevated entry fragility"

    return "Acceptable / monitor"


def build_plain_language_summary(action, state, preferred_band, expected_fcr, weak_rate, fragility_bucket):
    action_s = str(action).upper()
    state_s = str(state)

    if "WAIT" in action_s or "AVOID" in action_s:
        return (
            f"The model currently recommends **waiting rather than deploying new liquidity**. "
            f"The latest regime is classified as **{state_s}**, and the weak-rate risk remains high enough "
            f"that the expected fee compensation does not justify taking LP inventory risk at this point."
        )

    return (
        f"The model currently supports deployment, with a preferred range width of **{preferred_band}**. "
        f"The expected FCR is **{expected_fcr}**, while the weak-rate risk is **{weak_rate}**. "
        f"Live entry fragility is currently **{fragility_bucket}**, so the setup should still be monitored before entry."
    )


def build_what_would_change(action, fragility_bucket):
    action_s = str(action).lower()
    frag_s = str(fragility_bucket).lower()

    items = []

    if "wait" in action_s or "avoid" in action_s:
        items.extend([
            "A cleaner regime state with lower directional/path-quality risk.",
            "Lower probability-adjusted weak-rate risk.",
            "Improved expected fee coverage across the preferred band.",
            "Reduced transition risk away from the current state.",
        ])
    else:
        items.extend([
            "A deterioration in live fragility conditions.",
            "A rise in one-sided directional flow or shock intensity.",
            "A fall in expected FCR or a rise in weak-rate risk.",
            "Liquidity deterioration near the active price range.",
        ])

    if "normal" not in frag_s:
        items.append("A return of the live fragility monitor to Normal conditions.")

    return items


def freshness_summary(freshness_df):
    if freshness_df is None or freshness_df.empty:
        return "Freshness audit unavailable.", []

    rows = []

    # Try to infer status columns flexibly.
    for _, r in freshness_df.iterrows():
        source = first_available(r, ["source", "data_source", "name", "dataset"], "Unknown source")
        status = first_available(r, ["status", "freshness_status", "result"], "Unknown")
        max_time = first_available(r, ["max_timestamp", "max_time", "latest_timestamp", "latest_time", "max"], "")

        rows.append({
            "source": source,
            "status": status,
            "latest": max_time,
        })

    problem_rows = [
        r for r in rows
        if "ok" not in str(r["status"]).lower()
        and "fresh" not in str(r["status"]).lower()
        and "unknown" not in str(r["status"]).lower()
    ]

    if not problem_rows:
        summary = "Data freshness audit does not show any obvious blocking issue."
    else:
        summary = "Some data freshness checks may need attention."

    return summary, rows


def main(pool_id=DEFAULT_POOL_ID):
    print("Building LP Risk Snapshot v1...")

    pool = load_pool_config(pool_id)
    pair_label = pool_pair_label(pool)
    pool_metadata = "\n".join(pool_metadata_lines(pool))

    live_rec = load_optional_csv(LIVE_REC_FILE, "live recommendation")
    fragility = load_optional_csv(FRAGILITY_FILE, "live fragility monitor")
    freshness = load_optional_csv(FRESHNESS_FILE, "freshness audit")

    rec = get_latest_row(live_rec)

    # Fragility file has multiple windows. Use the overall fields if present.
    if fragility is not None and not fragility.empty:
        frag_row = fragility.tail(1).iloc[0].to_dict()
        overall_score = first_available(frag_row, ["overall_fragility_score", "raw_fragility_score"], np.nan)
        overall_bucket = first_available(frag_row, ["overall_fragility_bucket", "fragility_bucket"], "Unavailable")

        strongest = fragility.sort_values(
            by="raw_fragility_score",
            ascending=False,
            na_position="last",
        ).head(1)

        if not strongest.empty:
            strongest_row = strongest.iloc[0].to_dict()
        else:
            strongest_row = {}
    else:
        frag_row = {}
        strongest_row = {}
        overall_score = np.nan
        overall_bucket = "Unavailable"

    action = first_available(rec, ["action", "final_action"], "Unavailable")
    model_recommendation = first_available(rec, ["model_recommendation", "recommendation"], "Unavailable")
    preferred_band = first_available(rec, ["preferred_band", "final_band", "recommended_band"], "Unavailable")
    expected_fcr = first_available(
        rec,
        ["probability_adjusted_expected_fcr", "expected_fcr", "adjusted_expected_fcr"],
        np.nan,
    )
    weak_rate = first_available(
        rec,
        ["probability_adjusted_weak_rate", "weak_rate", "expected_weak_rate"],
        np.nan,
    )
    current_state = first_available(rec, ["current_state", "state", "score_based_state"], "Unavailable")

    latest_week_start = first_available(
        rec,
        [
            "latest_model_week_start",
            "latest_week_start",
            "model_week_start",
            "week_start",
            "feature_week_start",
            "current_week_start",
            "latest_completed_week_start",
        ],
        "Unavailable",
    )

    latest_week_end = first_available(
        rec,
        [
            "latest_model_week_end",
            "latest_week_end",
            "model_week_end",
            "week_end",
            "feature_week_end",
            "current_week_end",
            "latest_completed_week_end",
        ],
        "Unavailable",
    )
    staleness_days = first_available(rec, ["staleness_days_from_week_end", "staleness_days"], "Unavailable")
    is_stale = first_available(rec, ["is_stale"], "Unavailable")

    # Deribit / options context
    deribit_timestamp_utc = first_available(rec, ["deribit_timestamp_utc"], "Unavailable")
    chosen_expiry = first_available(rec, ["chosen_expiry"], "Unavailable")
    days_to_expiry = first_available(rec, ["days_to_expiry"], np.nan)
    deribit_short_dated_iv_pct = first_available(rec, ["deribit_short_dated_iv_pct"], np.nan)
    realised_vol_pct = first_available(rec, ["realised_vol_pct"], np.nan)
    iv_rv_gap_pct = first_available(rec, ["iv_rv_gap_pct"], np.nan)
    iv_rv_gap_bucket = first_available(rec, ["iv_rv_gap_bucket"], "Unavailable")
    rv_displacement_ratio = first_available(rec, ["rv_displacement_ratio"], np.nan)

    # Transition / forward-risk context
    state_age_weeks = first_available(rec, ["state_age_weeks"], "Unavailable")
    transition_risk_bucket = first_available(rec, ["transition_risk_bucket"], "Unavailable")
    persist_probability = first_available(rec, ["persist_probability"], np.nan)
    transition_away_probability = first_available(rec, ["transition_away_probability"], np.nan)
    favourable_next_probability = first_available(rec, ["favourable_next_probability"], np.nan)
    fragile_next_probability = first_available(rec, ["fragile_next_probability"], np.nan)
    most_likely_next_state = first_available(rec, ["most_likely_next_state"], "Unavailable")
    most_likely_next_state_probability = first_available(rec, ["most_likely_next_state_probability"], np.nan)
    transition_risk_summary = first_available(rec, ["transition_risk_summary"], "Unavailable")
    risk_flags = first_available(rec, ["risk_flags"], "None")

    risk_class = classify_client_risk(action, weak_rate, overall_bucket)

    expected_fcr_fmt = fmt_num(expected_fcr, 2)
    weak_rate_fmt = fmt_pct(weak_rate, 1)
    frag_score_fmt = fmt_num(overall_score, 2)

    days_to_expiry_fmt = fmt_num(days_to_expiry, 2)
    deribit_iv_fmt = fmt_pct(deribit_short_dated_iv_pct, 1)
    realised_vol_fmt = fmt_pct(realised_vol_pct, 1)
    iv_rv_gap_fmt = fmt_pct(iv_rv_gap_pct, 1)
    rv_displacement_ratio_fmt = fmt_num(rv_displacement_ratio, 3)

    persist_probability_fmt = fmt_pct(persist_probability, 1)
    transition_away_probability_fmt = fmt_pct(transition_away_probability, 1)
    favourable_next_probability_fmt = fmt_pct(favourable_next_probability, 1)
    fragile_next_probability_fmt = fmt_pct(fragile_next_probability, 1)
    most_likely_next_state_probability_fmt = fmt_pct(most_likely_next_state_probability, 1)

    summary = build_plain_language_summary(
        action=action,
        state=current_state,
        preferred_band=preferred_band,
        expected_fcr=expected_fcr_fmt,
        weak_rate=weak_rate_fmt,
        fragility_bucket=overall_bucket,
    )

    change_items = build_what_would_change(action, overall_bucket)
    freshness_text, freshness_rows = freshness_summary(freshness)

    strongest_window = first_available(strongest_row, ["lookback_hours"], "Unavailable")
    strongest_reasons = first_available(strongest_row, ["risk_reasons"], "Unavailable")

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    freshness_table = ""
    if freshness_rows:
        freshness_table = "\n".join([
            f"| {r['source']} | {r['status']} | {r['latest']} |"
            for r in freshness_rows
        ])
    else:
        freshness_table = "| Unavailable | Unavailable | Unavailable |"

    change_list = "\n".join([f"- {x}" for x in change_items])

    options_interpretation = (
        "Options-market stress is currently being used as a forward-looking risk overlay. "
        "It should not be interpreted as a standalone deploy/avoid signal. Its role is to add caution when implied volatility, realised volatility, or expected-move conditions confirm weak regime quality, transition risk, or live fragility."
    )

    transition_interpretation = (
        "The transition layer estimates whether the current regime is likely to persist, improve, or move into a more fragile state. "
        "High transition-away or fragile-next probabilities reduce confidence in narrow LP deployment, especially when weak-rate risk is already elevated."
    )

    md = f"""# {pair_label} LP Risk Snapshot v1

Generated: **{generated}**

{pool_metadata}

Model week: **{latest_week_start} to {latest_week_end}**

---

## 1. Final Recommendation

**Action:** {action}

**Model recommendation:** {model_recommendation}

**Preferred band:** {preferred_band}

**Client-facing risk class:** {risk_class}

---

## 2. Executive Summary

{summary}

The current short-horizon fragility monitor is **{overall_bucket}**, with an overall score of **{frag_score_fmt}**. This means the model does not currently detect an immediate live-entry shock signal, but the broader weekly recommendation should still dominate the deployment decision.

---

## 3. Core Model Signals

| Signal | Current reading |
|---|---:|
| Current regime/state | {current_state} |
| Preferred band | {preferred_band} |
| Probability-adjusted expected FCR | {expected_fcr_fmt} |
| Probability-adjusted weak-rate | {weak_rate_fmt} |
| Staleness days from week end | {staleness_days} |
| Is stale | {is_stale} |

---

## 4. Live Entry Fragility

| Signal | Current reading |
|---|---:|
| Overall fragility score | {frag_score_fmt} |
| Overall fragility bucket | {overall_bucket} |
| Strongest warning window | {strongest_window}h |
| Main live-risk reasons | {strongest_reasons} |

Interpretation:

The live monitor is designed to catch short-horizon conditions that may make LP entry dangerous, such as large recent moves, directional path persistence, one-sided flow proxies, volume intensity, or liquidity deterioration.

This layer should be interpreted as an **entry-timing risk check**, not as the main weekly allocation signal.

---

## 5. Transition & Forward Regime Risk

| Signal | Current reading |
|---|---:|
| State age | {state_age_weeks} week(s) |
| Transition risk bucket | {transition_risk_bucket} |
| Persist probability | {persist_probability_fmt} |
| Transition-away probability | {transition_away_probability_fmt} |
| Favourable-next probability | {favourable_next_probability_fmt} |
| Fragile-next probability | {fragile_next_probability_fmt} |
| Most likely next state | {most_likely_next_state} |
| Most likely next-state probability | {most_likely_next_state_probability_fmt} |

Interpretation:

{transition_interpretation}

Transition summary:

> {transition_risk_summary}

---

## 6. Options / Volatility Context

| Signal | Current reading |
|---|---:|
| Deribit timestamp | {deribit_timestamp_utc} |
| Chosen expiry | {chosen_expiry} |
| Days to expiry | {days_to_expiry_fmt} |
| Deribit short-dated IV | {deribit_iv_fmt} |
| Realised volatility | {realised_vol_fmt} |
| IV/RV gap | {iv_rv_gap_fmt} |
| IV/RV bucket | {iv_rv_gap_bucket} |
| RV displacement ratio | {rv_displacement_ratio_fmt} |

Interpretation:

{options_interpretation}

Risk flags:

> {risk_flags}

---

## 7. Why This Recommendation Matters

Uniswap v3 LP returns are path-dependent. A position can earn fees and still lose versus passive holding if price movement creates enough inventory/rebalancing drag.

The model therefore focuses on whether expected fees are likely to compensate for:

- price-path risk
- directional movement
- shock contamination
- range stress
- weak-rate risk
- live entry fragility

The central question is:

> Are fees likely to compensate LPs for the path-dependent risk they are taking?

Current answer: **{model_recommendation}**

---

## 8. What Would Change the Recommendation?

{change_list}

---

## 9. Data Freshness

{freshness_text}

| Source | Status | Latest timestamp |
|---|---|---:|
{freshness_table}

---

## 10. Methodology Summary

This snapshot combines:

1. Historical LP/FCR outcome analysis by regime and band.
2. Score-based regime classification.
3. Probability-adjusted weak-rate and expected FCR estimates.
4. Deribit / options-informed risk overlays where available.
5. Live short-horizon fragility monitoring.
6. Data freshness checks.

The output is intended to support LP range deployment decisions by separating:

- attractive fee environments
- uncompensated rebalancing risk
- live shock/entry timing risk
- stale or unreliable data conditions

---

## 11. Files Used

- `{LIVE_REC_FILE}`
- `{FRAGILITY_FILE}`
- `{FRESHNESS_FILE}`

## 12. Output Files

- `{OUT_MD}`
- `{OUT_TXT}`
"""

    OUT_MD.write_text(md, encoding="utf-8")
    OUT_TXT.write_text(md, encoding="utf-8")

    print("\nLP Risk Snapshot v1 complete.")
    print(f"Saved markdown: {OUT_MD}")
    print(f"Saved text copy: {OUT_TXT}")
    print("\nSummary:")
    print(f"Action: {action}")
    print(f"Model recommendation: {model_recommendation}")
    print(f"Preferred band: {preferred_band}")
    print(f"Expected FCR: {expected_fcr_fmt}")
    print(f"Weak-rate: {weak_rate_fmt}")
    print(f"Current state: {current_state}")
    print(f"Live fragility: {overall_bucket} ({frag_score_fmt})")
    print(f"Risk class: {risk_class}")


if __name__ == "__main__":
    args = parse_args()
    main(pool_id=args.pool_id)



