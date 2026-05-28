# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

from pathlib import Path
from datetime import datetime
import re
import argparse
import sys

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.core.pool_config import load_pool_config


OUTPUT_DIR = ROOT / "outputs"

LIVE_REC_FILE = OUTPUT_DIR / "live_lp_recommendation_v1.csv"
DISTRIBUTION_FILE = OUTPUT_DIR / "current_state_band_distribution_diagnostics_v1.csv"
CLIENT_MD_FILE = OUTPUT_DIR / "client_facing_lp_risk_snapshot_v1.md"
LIVE_FRAGILITY_FILE = OUTPUT_DIR / "live_fragility_monitor_v1.csv"
PREVIOUS_AUDIT_CSV = OUTPUT_DIR / "previous_signal_realised_audit_v1.csv"

OUT_MD = OUTPUT_DIR / "networking_lp_snapshot_v1.md"
OUT_TXT = OUTPUT_DIR / "networking_lp_snapshot_v1.txt"

UNAVAILABLE = "Unavailable"
DEFAULT_POOL_ID = "eth_usdc_005"
FRESHNESS_CAVEAT = (
    "Freshness is assessed relative to the latest completed model week currently available in the pipeline. "
    "Full roll-forward to the next completed week depends on refreshed fee/liquidity inputs."
)


def parse_args():
    parser = argparse.ArgumentParser(description="Build the networking LP snapshot.")
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
    price_symbol = pool.get("price_source", {}).get("symbol", UNAVAILABLE)
    pair_label = pool_pair_label(pool)
    bands = ", ".join(fmt_pct(band, 0) for band in pool.get("bands", []))
    return "\n".join(
        [
            f"- Pool ID: **{pool.get('pool_id', UNAVAILABLE)}**",
            f"- Chain / protocol: **{pool.get('chain', UNAVAILABLE)} / {pool.get('protocol', UNAVAILABLE)}**",
            f"- Pool address: **{pool.get('pool_address', UNAVAILABLE)}**",
            f"- Asset pair / fee tier: **{pair_label} / {pool.get('fee_tier_bps', UNAVAILABLE)} bps**",
            f"- Quote asset / price reference: **{pool.get('quote_asset', UNAVAILABLE)} / {price_symbol}**",
            f"- Configured bands: **{bands or UNAVAILABLE}**",
        ]
    )


def read_optional_csv(path: Path) -> pd.DataFrame:
    if not path.exists():
        return pd.DataFrame()
    try:
        return pd.read_csv(path)
    except Exception:
        return pd.DataFrame()


def read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception:
        return ""


def first_row(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    return df.iloc[0].to_dict()


def last_row(df: pd.DataFrame) -> dict:
    if df.empty:
        return {}
    return df.iloc[-1].to_dict()


def get_value(row: dict, key: str, default=UNAVAILABLE):
    value = row.get(key, default)
    if value is None:
        return default
    try:
        if pd.isna(value):
            return default
    except Exception:
        pass
    if isinstance(value, str) and value.strip() == "":
        return default
    return value


def parse_float(value):
    if value is None:
        return np.nan
    if isinstance(value, str):
        cleaned = (
            value.strip()
            .replace("$", "")
            .replace(",", "")
            .replace("%", "")
        )
        if cleaned == "" or cleaned.lower() == "unavailable":
            return np.nan
        try:
            x = float(cleaned)
        except Exception:
            return np.nan
        if "%" in value:
            return x / 100
        return x
    try:
        if pd.isna(value):
            return np.nan
        return float(value)
    except Exception:
        return np.nan


def fmt_fcr(value, decimals=2):
    x = parse_float(value)
    if pd.isna(x):
        return UNAVAILABLE
    return f"{x:.{decimals}f}"


def fmt_pct(value, decimals=1):
    x = parse_float(value)
    if pd.isna(x):
        return UNAVAILABLE
    if abs(x) > 1:
        return f"{x:.{decimals}f}%"
    return f"{x * 100:.{decimals}f}%"


def fmt_money(value, decimals=0):
    x = parse_float(value)
    if pd.isna(x):
        return UNAVAILABLE
    if x < 0:
        return f"-${abs(x):,.{decimals}f}"
    return f"${x:,.{decimals}f}"


def clean_text(value):
    if value is None:
        return UNAVAILABLE
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return UNAVAILABLE
    return text


def find_markdown_field(text: str, labels, default=UNAVAILABLE):
    if isinstance(labels, str):
        labels = [labels]

    for label in labels:
        patterns = [
            rf"^{re.escape(label)}:\s*\*\*(.*?)\*\*",
            rf"^{re.escape(label)}:\s*(.+)$",
            rf"\|\s*{re.escape(label)}\s*\|\s*\*\*(.*?)\*\*\s*\|",
            rf"\|\s*{re.escape(label)}\s*\|\s*(.*?)\s*\|",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if match:
                return clean_text(match.group(1))

    return default


def preferred_distribution_row(dist: pd.DataFrame, preferred_band: str) -> dict:
    if dist.empty:
        return {}

    if "band" in dist.columns:
        matches = dist[dist["band"].astype(str) == str(preferred_band)]
        if not matches.empty:
            return matches.iloc[0].to_dict()

    return first_row(dist)


def action_category(action, model_recommendation):
    text = f"{action} {model_recommendation}".lower()
    if any(term in text for term in ["wait", "avoid", "stand down"]):
        return "wait"
    if any(term in text for term in ["deploy", "constructive", "active"]):
        return "constructive"
    return "uncertain"


def action_sentence(category):
    if category == "wait":
        return (
            "The model does not currently identify an attractive LP deployment setup. "
            "Across the tested 5%, 10%, and 20% ranges, it currently favours waiting "
            "rather than opening a new LP position."
        )
    if category == "constructive":
        return "The model sees a more constructive LP setup."
    return "The signal is not clearly constructive and should be reviewed before use."


def fragility_sentence(bucket):
    text = clean_text(bucket).lower()
    if text == UNAVAILABLE.lower():
        return "Live fragility context is unavailable."
    if any(term in text for term in ["normal", "low"]):
        return "The signal is not mainly being driven by immediate entry shock."
    if any(term in text for term in ["elevated", "high"]):
        return "Short-horizon entry fragility is contributing to caution."
    return f"Live fragility is classified as {bucket}."


def ivrv_sentence(bucket):
    text = clean_text(bucket).lower()
    if text == UNAVAILABLE.lower():
        return "Options-market context is unavailable."
    if "below rv" in text or "below realised" in text or "below realized" in text:
        return "Options-market stress is not the main driver; IV is currently below realised volatility."
    if "aligned" in text or "roughly aligned" in text:
        return "Options-market stress is not a dominant driver."
    if any(term in text for term in ["above", "elevated", "high", "stressed"]):
        return "Options-market stress may be adding caution."
    return f"Options-market context is classified as {bucket}."


def fee_sentences(median_fcr, net_vs_hold):
    sentences = []

    median = parse_float(median_fcr)
    if pd.isna(median):
        sentences.append("Typical fee coverage is unavailable.")
    elif median < 1:
        sentences.append("Typical fee coverage is below breakeven.")
    elif median <= 1.25:
        sentences.append("Typical fee coverage is close to breakeven and does not provide a strong margin of safety.")
    else:
        sentences.append("Typical fee coverage is more constructive.")

    net = parse_float(net_vs_hold)
    if pd.isna(net):
        sentences.append("Expected net outcome versus holding is unavailable.")
    elif net < 0:
        sentences.append("Expected net outcome versus holding is negative.")
    elif net > 0:
        sentences.append("Expected net outcome versus holding is positive.")
    else:
        sentences.append("Expected net outcome versus holding is around breakeven.")

    return " ".join(sentences)


def mean_fcr_skew_sentence(mean_fcr, median_fcr):
    mean = parse_float(mean_fcr)
    median = parse_float(median_fcr)
    if pd.isna(mean) or pd.isna(median):
        return ""
    if median > 0 and mean > 2 * median and mean > 3:
        return (
            "Mean FCR is shown as context only because low required-fee denominator weeks "
            "can inflate FCR even when the dollar outcome is small."
        )
    return ""


def weak_rate_sentences(historical_weak, probability_adjusted_weak):
    sentences = []
    hist = parse_float(historical_weak)
    prob = parse_float(probability_adjusted_weak)

    if not pd.isna(hist):
        if hist > 0.40:
            sentences.append("Comparable historical outcomes show elevated weak-outcome risk.")
        elif hist < 0.25:
            sentences.append("Comparable historical outcomes show lower weak-outcome risk.")

    if not pd.isna(hist) and not pd.isna(prob):
        if prob > hist:
            sentences.append("The transition layer adds caution.")
        elif prob < hist:
            sentences.append("The transition layer is less cautious than the raw distribution.")

    return " ".join(sentences)


def regime_sentence(state):
    text = clean_text(state).lower()
    if text == UNAVAILABLE.lower():
        return ""
    fragile_terms = ["directional", "low-quality", "low quality", "shock", "fragile", "high-churn", "high churn"]
    constructive_terms = ["clean", "balanced", "oscillation", "fee opportunity"]

    if any(term in text for term in fragile_terms):
        return f"Regime quality is fragile: the current state is {state}."
    if any(term in text for term in constructive_terms):
        return f"Regime quality is cleaner or more constructive: the current state is {state}."
    return f"The current regime state is {state}."


def transition_sentence(fragile_next, transition_away):
    fragile = parse_float(fragile_next)
    away = parse_float(transition_away)

    if not pd.isna(fragile) and fragile > 0.50 and not pd.isna(away) and away >= 0.60:
        return (
            "Transition context remains fragile, with elevated probability of a fragile next state "
            "and a high transition-away probability."
        )
    if not pd.isna(fragile) and fragile > 0.50:
        return "Transition context remains fragile, with elevated probability of a fragile next state."
    if not pd.isna(fragile) and fragile < 0.30:
        return "Transition context is less fragile."
    if not pd.isna(away) and away >= 0.60:
        return "The current state has a high transition-away probability."

    return ""


def takeaway(category):
    if category == "wait":
        return "Wait for stronger fee compensation, a cleaner regime, or a lower weak-outcome risk before treating this as an attractive LP deployment window."
    if category == "constructive":
        return "The setup is more constructive, but deployment should still be monitored against regime deterioration, live fragility, and realised fee capture."
    return "Signal requires review before use."


def regime_quality_paragraph(current_state, probability_adjusted_weak, expected_net_vs_hold):
    return (
        f"The current regime is classified as {clean_text(current_state)}. In similar modelled conditions, "
        f"the probability-adjusted weak-outcome rate is {fmt_pct(probability_adjusted_weak)}, "
        f"and the expected net outcome versus holding is {fmt_money(expected_net_vs_hold)}. "
        "This suggests that fees are not currently expected to offer enough compensation for "
        "inventory drift and rebalancing drag."
    )


def transition_risk_paragraph(transition_away_probability, most_likely_next_state):
    return (
        "The transition layer also flags regime fragility: "
        f"the transition-away probability is {fmt_pct(transition_away_probability)}, "
        f"while the most likely next state is {clean_text(most_likely_next_state)}. "
        "That means the model is not yet seeing strong evidence of a cleaner, more "
        "fee-compensated LP environment forming."
    )


def shock_options_paragraph(live_fragility, iv_rv_bucket):
    fragility = clean_text(live_fragility)
    fragility_phrase = (
        "currently normal"
        if fragility.lower() == "normal"
        else f"currently {fragility.lower()}"
        if fragility != UNAVAILABLE
        else "currently unavailable"
    )
    options_bucket = clean_text(iv_rv_bucket).lower()
    if any(term in options_bucket for term in ["above", "elevated", "high", "stressed"]):
        options_phrase = f"options-market stress is classified as {clean_text(iv_rv_bucket)}"
    elif clean_text(iv_rv_bucket) == UNAVAILABLE:
        options_phrase = "options-market stress context is unavailable"
    else:
        options_phrase = "options-market stress is not elevated"

    return (
        "This is not primarily an immediate shock signal. "
        f"Live fragility is {fragility_phrase}, and {options_phrase}. "
        "The main concern is regime quality: the current price path appears too directional "
        "relative to the fee compensation available."
    )


def presentation_label(value: str) -> str:
    cleaned = clean_text(value)
    if cleaned == UNAVAILABLE:
        return cleaned
    return cleaned.replace("_", " ").replace("-", " ").title()


def audit_reason_note(reason: str) -> str:
    cleaned = clean_text(reason)
    if cleaned == "No complete realised LP outcome rows available for the forward window yet.":
        return "Realised LP outcome data for the forward window is not yet complete."
    return cleaned


def audit_note(audit: dict):
    if not audit:
        return "Previous-signal realised audit: pending until the relevant realised fee/liquidity data is available."

    signal_id = clean_text(get_value(audit, "signal_id"))
    status = presentation_label(get_value(audit, "audit_status"))
    verdict = presentation_label(get_value(audit, "audit_verdict"))
    start = clean_text(get_value(audit, "forward_window_start"))
    end = clean_text(get_value(audit, "forward_window_end"))
    reason = audit_reason_note(get_value(audit, "reason"))

    lines = [
        f"- Previous signal ID: **{signal_id}**",
        f"- Audit status: **{status}**",
        f"- Audit window: **{start} to {end}**",
    ]

    if verdict != UNAVAILABLE:
        lines.append(f"- Result/verdict: **{verdict}**")
    if reason != UNAVAILABLE:
        lines.append(f"- Note: {reason}")

    return "\n".join(lines)


def main(pool_id=DEFAULT_POOL_ID):
    print("Building networking LP snapshot v1...")

    pool_config = load_pool_config(pool_id)
    pool = pool_config.get("display_name", UNAVAILABLE)
    pair_label = pool_pair_label(pool_config)
    pool_metadata = pool_metadata_lines(pool_config)

    live = first_row(read_optional_csv(LIVE_REC_FILE))
    dist = read_optional_csv(DISTRIBUTION_FILE)
    client_md = read_optional_text(CLIENT_MD_FILE)
    fragility = last_row(read_optional_csv(LIVE_FRAGILITY_FILE))
    audit = first_row(read_optional_csv(PREVIOUS_AUDIT_CSV))

    risk_class = find_markdown_field(client_md, "Client-facing risk class", UNAVAILABLE)

    action = clean_text(get_value(live, "final_action"))
    model_recommendation = clean_text(get_value(live, "model_recommendation"))
    preferred_band = clean_text(get_value(live, "preferred_band"))
    current_state = clean_text(get_value(live, "current_state"))
    latest_week_start = clean_text(get_value(live, "latest_week_start"))
    latest_week_end = clean_text(get_value(live, "latest_week_end"))
    model_week = (
        f"{latest_week_start} to {latest_week_end}"
        if latest_week_start != UNAVAILABLE and latest_week_end != UNAVAILABLE
        else UNAVAILABLE
    )

    drow = preferred_distribution_row(dist, preferred_band)
    median_fcr = get_value(drow, "median_realised_fcr")
    historical_weak_rate = get_value(drow, "weak_rate")
    expected_net_vs_hold = get_value(drow, "expected_net_outcome_vs_hold")
    mean_fcr = get_value(drow, "mean_realised_fcr")

    probability_adjusted_fcr = get_value(live, "probability_adjusted_expected_fcr")
    probability_adjusted_weak = get_value(live, "probability_adjusted_weak_rate")
    live_fragility = clean_text(get_value(fragility, "overall_fragility_bucket", get_value(fragility, "fragility_bucket")))
    iv_rv_bucket = clean_text(get_value(live, "iv_rv_gap_bucket"))
    transition_risk_bucket = clean_text(get_value(live, "transition_risk_bucket"))
    fragile_next_probability = get_value(live, "fragile_next_probability")
    transition_away_probability = get_value(live, "transition_away_probability")
    most_likely_next_state = clean_text(get_value(live, "most_likely_next_state"))

    category = action_category(action, model_recommendation)

    if category == "wait":
        interpretation_paragraphs = [
            action_sentence(category),
            regime_quality_paragraph(
                current_state,
                probability_adjusted_weak,
                expected_net_vs_hold,
            ),
            transition_risk_paragraph(
                transition_away_probability,
                most_likely_next_state,
            ),
            shock_options_paragraph(live_fragility, iv_rv_bucket),
        ]
    else:
        recommendation_regime_paragraph = " ".join([
            p for p in [
                action_sentence(category),
                regime_sentence(current_state),
            ]
            if p
        ])
        fee_transition_paragraph = " ".join([
            p for p in [
                fee_sentences(median_fcr, expected_net_vs_hold),
                weak_rate_sentences(historical_weak_rate, probability_adjusted_weak),
                transition_sentence(fragile_next_probability, transition_away_probability),
            ]
            if p
        ])
        live_options_paragraph = " ".join([
            p for p in [
                fragility_sentence(live_fragility),
                ivrv_sentence(iv_rv_bucket),
            ]
            if p
        ])
        skew_paragraph = mean_fcr_skew_sentence(mean_fcr, median_fcr)

        interpretation_paragraphs = [
            p for p in [
                recommendation_regime_paragraph,
                fee_transition_paragraph,
                live_options_paragraph,
                skew_paragraph,
            ]
            if p
        ]

    generated = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    md = f"""# {pair_label} LP Risk Snapshot - Weekly Summary

Generated: **{generated}**

Pool: **{pool}**  
Model week: **{model_week}**

{pool_metadata}

## Current Signal

| Item | Reading |
|---|---:|
| Recommended action | **{action}** |
| Model recommendation | **{model_recommendation}** |
| Preferred band if deploying | **{preferred_band}** |
| Current regime | **{current_state}** |
| Risk class | **{risk_class}** |
| Median FCR / typical fee coverage | **{fmt_fcr(median_fcr)}** |
| Historical weak-outcome rate | **{fmt_pct(historical_weak_rate)}** |
| Transition-adjusted weak-outcome probability | {fmt_pct(probability_adjusted_weak)} |
| Expected net outcome versus holding | **{fmt_money(expected_net_vs_hold)}** |

## Interpretation

{chr(10).join([p + chr(10) for p in interpretation_paragraphs]).rstrip()}

## What This Tests

This snapshot asks one practical question:

**Is the current market regime attractive for Uniswap v3 LP deployment, or are LPs unlikely to be paid enough for the price-path and rebalancing risk they are taking?**

The model compares historical outcomes from similar regimes across 5%, 10%, and 20% LP ranges, then adjusts the signal using transition risk, live fragility, and options-market context.

## Current Risk Context

| Signal | Reading |
|---|---:|
| Live entry fragility | **{live_fragility}** |
| IV/RV context | **{iv_rv_bucket}** |
| Transition risk | **{transition_risk_bucket}** |
| Fragile-next probability | **{fmt_pct(fragile_next_probability)}** |
| Transition-away probability | **{fmt_pct(transition_away_probability)}** |
| Most likely next state | **{most_likely_next_state}** |

## Freshness / Audit Note

{FRESHNESS_CAVEAT}

{audit_note(audit)}

## Takeaway

{takeaway(category)}
"""

    OUT_MD.write_text(md, encoding="utf-8")
    OUT_TXT.write_text(md, encoding="utf-8")

    print("Saved:")
    print(f"- {OUT_MD}")
    print(f"- {OUT_TXT}")


if __name__ == "__main__":
    args = parse_args()
    main(pool_id=args.pool_id)



