# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

from pathlib import Path
import re
import csv
from datetime import datetime
import argparse
import sys

PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))
from scripts.core.pool_config import load_pool_config


OUTPUT_DIR = PROJECT_ROOT / "outputs"

SOURCE_MD = OUTPUT_DIR / "lp_risk_snapshot_v1.md"

LIVE_FRAGILITY_MD = OUTPUT_DIR / "live_fragility_monitor_v1.md"
LIVE_FRAGILITY_STATUS_NOTE = OUTPUT_DIR / "live_fragility_monitor_v1_status_note.txt"
LIVE_FRAGILITY_CSV = OUTPUT_DIR / "live_fragility_monitor_v1.csv"
DISTRIBUTION_DIAGNOSTICS_CSV = OUTPUT_DIR / "current_state_band_distribution_diagnostics_v1.csv"

OUT_MD = OUTPUT_DIR / "client_facing_lp_risk_snapshot_v1.md"
OUT_TXT = OUTPUT_DIR / "client_facing_lp_risk_snapshot_v1.txt"

DEFAULT_POOL_ID = "eth_usdc_005"

FCR_SKEW_NOTE = (
    "Mean FCR is shown for context but is not the primary deployment signal. "
    "Because FCR divides LP fees by required fees, low required-fee denominator weeks can produce "
    "very high FCR readings even when the dollar outcome is small. The report therefore prioritises "
    "median FCR, weak-outcome rate, and expected net outcome vs hold when assessing whether the setup offers enough margin of safety."
)


def parse_args():
    parser = argparse.ArgumentParser(description="Build the client-facing LP risk snapshot.")
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


def pool_metadata_table(pool):
    price_symbol = pool.get("price_source", {}).get("symbol", "Not available")
    bands = ", ".join(format_percent(band, 0) for band in pool.get("bands", []))
    return f"""| Pool metadata | Current configuration |
|---|---:|
| Pool ID | **{pool.get('pool_id', 'Not available')}** |
| Chain / protocol | **{pool.get('chain', 'Not available')} / {pool.get('protocol', 'Not available')}** |
| Pool address | **{pool.get('pool_address', 'Not available')}** |
| Tokens / fee tier | **{pool.get('token0', 'Not available')}-{pool.get('token1', 'Not available')} / {pool.get('fee_tier_bps', 'Not available')} bps** |
| Quote asset / price source | **{pool.get('quote_asset', 'Not available')} / {price_symbol}** |
| Configured bands | **{bands or 'Not available'}** |"""


def read_text(path: Path) -> str:
    if not path.exists():
        raise FileNotFoundError(f"Required source report not found: {path}")
    return path.read_text(encoding="utf-8", errors="replace")

def read_optional_text(path: Path) -> str:
    if not path.exists():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def clean_value(value: str) -> str:
    if value is None:
        return "Not available"

    value = str(value).strip()
    value = re.sub(r"\*\*", "", value)
    value = re.sub(r"`", "", value)
    value = value.replace("week(s)", "week")
    value = re.sub(r"\s+", " ", value)
    value = value.strip(" |")

    if value == "":
        return "Not available"

    return value


def parse_float(value):
    try:
        if value is None or str(value).strip() == "":
            return None
        return float(value)
    except Exception:
        return None


def parse_display_number(value, percent_as_decimal=False):
    value = clean_value(value)
    if value == "Not available":
        return None

    had_percent = "%" in value
    cleaned = (
        value
        .replace("$", "")
        .replace(",", "")
        .replace("%", "")
        .strip()
    )

    try:
        number = float(cleaned)
    except Exception:
        return None

    if percent_as_decimal and had_percent:
        return number / 100
    return number


def format_number(value, decimals=2):
    x = parse_float(value)
    if x is None:
        return "Not available"
    return f"{x:.{decimals}f}"


def format_percent(value, decimals=1):
    x = parse_float(value)
    if x is None:
        return "Not available"
    return f"{x * 100:.{decimals}f}%"


def format_money(value, decimals=0):
    x = parse_float(value)
    if x is None:
        return "Not available"

    if x < 0:
        return f"-${abs(x):,.{decimals}f}"
    return f"${x:,.{decimals}f}"


def find_distribution_row(rows, preferred_band):
    preferred = clean_value(preferred_band)
    for row in rows:
        if clean_value(row.get("band", "")) == preferred:
            return row
    return {}


def strip_probability_suffix(value: str) -> str:
    """
    Removes trailing probability labels from state names, e.g.
    'Directional Low-Quality (33.3%)' -> 'Directional Low-Quality'
    """
    value = clean_value(value)
    value = re.sub(r"\s*\(\d+(\.\d+)?%\)\s*$", "", value)
    return value.strip()


def format_days(value: str) -> str:
    value = clean_value(value)

    if value == "Not available":
        return value

    if value.endswith("day") or value.endswith("days"):
        return value

    return f"{value} days"


def format_freshness(value: str) -> str:
    value = clean_value(value)

    if value.lower() == "false":
        return "Fresh / not stale"

    if value.lower() == "true":
        return "Stale â€” refresh recommended"

    return value


def find_after_label(text: str, labels, default="Not available"):
    """
    Looks for markdown fields like:
    **Action:** WAIT
    Action: WAIT
    | Action | WAIT |
    """
    if isinstance(labels, str):
        labels = [labels]

    for label in labels:
        patterns = [
            rf"\*\*{re.escape(label)}:\*\*\s*(.+)",
            rf"^{re.escape(label)}:\s*(.+)$",
            rf"\|\s*{re.escape(label)}\s*\|\s*(.+?)\s*\|",
            rf"\*\*{re.escape(label)}\*\*\s*\|\s*(.+)",
        ]

        for pattern in patterns:
            m = re.search(pattern, text, flags=re.IGNORECASE | re.MULTILINE)
            if m:
                return clean_value(m.group(1))

    return default


def find_generated(text: str):
    return find_after_label(
        text,
        ["Generated"],
        default=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    )


def find_live_fragility_bucket(text: str, default="Not available"):
    """
    Handles lines like:
    Live fragility: Normal, score 2.50
    Live entry fragility: Normal
    | Live fragility bucket | Normal |
    """
    direct = find_after_label(
        text,
        [
            "Live fragility bucket",
            "Live entry fragility",
            "Live-entry fragility",
            "Live fragility",
            "Fragility bucket",
        ],
        default="Not available",
    )

    if direct != "Not available":
        # Handles "Normal, score 2.50"
        return clean_value(direct.split(",")[0])

    patterns = [
        r"Live fragility:\s*([A-Za-z /-]+?)(?:,|\n|$)",
        r"Live entry fragility:\s*([A-Za-z /-]+?)(?:,|\n|$)",
        r"Live-entry fragility:\s*([A-Za-z /-]+?)(?:,|\n|$)",
        r"Fragility bucket:\s*([A-Za-z /-]+?)(?:,|\n|$)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE)
        if m:
            return clean_value(m.group(1))

    return default


def find_live_fragility_score(text: str, default="Not available"):
    """
    Handles lines like:
    Live fragility: Normal, score 2.50
    Live fragility score: 2.50
    """
    direct = find_after_label(
        text,
        [
            "Live fragility score",
            "Live-entry fragility score",
            "Fragility score",
        ],
        default="Not available",
    )

    if direct != "Not available":
        return direct

    patterns = [
        r"Live fragility:.*?score\s*([0-9]+(?:\.[0-9]+)?)",
        r"Live entry fragility:.*?score\s*([0-9]+(?:\.[0-9]+)?)",
        r"Live-entry fragility:.*?score\s*([0-9]+(?:\.[0-9]+)?)",
        r"Fragility score:\s*([0-9]+(?:\.[0-9]+)?)",
    ]

    for pattern in patterns:
        m = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
        if m:
            return clean_value(m.group(1))

    return default

def read_live_fragility_csv(path: Path):
    """
    Attempts to extract live fragility bucket and score from the CSV output,
    without assuming exact column names.
    """
    if not path.exists():
        return "Not available", "Not available"

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            reader = csv.DictReader(f)
            rows = list(reader)
    except Exception:
        return "Not available", "Not available"

    if not rows:
        return "Not available", "Not available"

    row = rows[-1]

    bucket = "Not available"
    score = "Not available"

    for col, value in row.items():
        col_clean = clean_value(col).lower()
        value_clean = clean_value(value)

        if value_clean == "Not available":
            continue

        if bucket == "Not available" and (
            "bucket" in col_clean
            or "fragility" in col_clean
            or "status" in col_clean
            or "classification" in col_clean
        ):
            if not re.fullmatch(r"-?\d+(\.\d+)?", value_clean):
                bucket = value_clean

        if score == "Not available" and (
            "score" in col_clean
            or "fragility_score" in col_clean
        ):
            if re.search(r"-?\d+(\.\d+)?", value_clean):
                score = value_clean

    return bucket, score


def read_distribution_diagnostics(path: Path):
    if not path.exists():
        return []

    try:
        with path.open("r", encoding="utf-8", errors="replace", newline="") as f:
            return list(csv.DictReader(f))
    except Exception:
        return []


def build_distribution_section(rows, preferred_band):
    if not rows:
        return ""

    sample_basis = (
        "Transition-conditioned next-week outcomes following historical weeks "
        "with the same current regime state and similar regime age."
    )
    preferred_row = find_distribution_row(rows, preferred_band)

    preferred_note = ""
    if preferred_row:
        median_fcr = format_number(preferred_row.get("median_realised_fcr"))
        mean_fcr = format_number(preferred_row.get("mean_realised_fcr"))
        expected_net = format_money(preferred_row.get("expected_net_outcome_vs_hold"))
        median_note = median_fcr_quality_phrase(median_fcr)
        net_note = expected_net_quality_phrase(expected_net)
        preferred_note = (
            f"\nAlthough the selected {clean_value(preferred_band)} band shows a mean FCR of "
            f"{mean_fcr}, its median FCR is {median_fcr} and expected net outcome vs hold is "
            f"{expected_net}. This supports the current recommendation because {median_note} "
            f"while {net_note}.\n"
        )

    table_rows = []
    for row in rows:
        observations = clean_value(row.get("sample_observations", "Not available"))
        table_rows.append(
            "| "
            + " | ".join([
                clean_value(row.get("band", "Not available")),
                observations,
                format_number(row.get("median_realised_fcr")),
                format_number(row.get("mean_realised_fcr")),
                format_number(row.get("p25_realised_fcr")),
                format_number(row.get("p75_realised_fcr")),
                format_percent(row.get("weak_rate")),
                format_percent(row.get("positive_vs_hold_rate")),
                format_money(row.get("mean_outcome_vs_hold")),
                format_money(row.get("median_outcome_vs_hold")),
                format_money(row.get("expected_required_fees")),
                format_money(row.get("expected_lp_fees")),
                format_money(row.get("expected_net_outcome_vs_hold")),
            ])
            + " |"
        )

    table = "\n".join(table_rows)

    return f"""
### Band-level outcome diagnostic

Sample basis: {sample_basis}

| Band | Observations | Median FCR / typical fee coverage | Mean FCR (skew-sensitive) | P25 FCR | P75 FCR | Historical weak-outcome rate | Positive vs hold | Mean outcome vs hold | Median outcome vs hold | Expected required fees | Expected LP fees | Expected net vs hold |
|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
{table}

Interpretation note: {FCR_SKEW_NOTE}
{preferred_note}
"""

def fill_live_fragility_from_all_sources(source_text: str):
    """
    Pulls live fragility from:
    1. main snapshot text
    2. dedicated live fragility markdown
    3. status note
    4. CSV fallback
    """
    live_fragility = find_live_fragility_bucket(source_text)
    live_fragility_score = find_live_fragility_score(source_text)

    md_text = read_optional_text(LIVE_FRAGILITY_MD)
    note_text = read_optional_text(LIVE_FRAGILITY_STATUS_NOTE)

    combined_text = "\n\n".join([md_text, note_text])

    if live_fragility == "Not available" and combined_text.strip():
        live_fragility = find_live_fragility_bucket(combined_text)

    if live_fragility_score == "Not available" and combined_text.strip():
        live_fragility_score = find_live_fragility_score(combined_text)

    csv_bucket, csv_score = read_live_fragility_csv(LIVE_FRAGILITY_CSV)

    if live_fragility == "Not available" and csv_bucket != "Not available":
        live_fragility = csv_bucket

    if live_fragility_score == "Not available" and csv_score != "Not available":
        live_fragility_score = csv_score

    return live_fragility, live_fragility_score


def state_age_interpretation(value: str) -> str:
    cleaned = clean_value(value)
    if cleaned == "Not available":
        return "Regime-state age is not available."

    match = re.search(r"-?\d+(\.\d+)?", cleaned)
    if not match:
        return f"The current regime-state age is {cleaned}."

    try:
        weeks = float(match.group(0))
    except Exception:
        return f"The current regime-state age is {cleaned}."

    if weeks == 1:
        return "The current regime state has been active for one weekly window."

    if weeks.is_integer():
        weeks_text = str(int(weeks))
    else:
        weeks_text = f"{weeks:.1f}"

    return f"The current regime state has been active for {weeks_text} weekly windows."


def live_entry_risk_interpretation(value: str) -> str:
    cleaned = clean_value(value)
    text = cleaned.lower()

    if cleaned == "Not available":
        return "Short-horizon entry-risk monitor is unavailable."

    if "normal" in text or "low" in text:
        return "Short-horizon monitor does not currently flag abnormal entry stress."

    if "high" in text or "stand down" in text:
        return "Short-horizon monitor is flagging elevated entry stress."

    if "elevated" in text or "moderate" in text:
        return "Short-horizon monitor is flagging some entry stress, so timing risk should be watched."

    return f"Short-horizon entry-risk monitor is classified as {cleaned}."


def live_entry_bucket_note(value: str) -> str:
    cleaned = clean_value(value)
    text = cleaned.lower()

    if cleaned == "Not available":
        return "Short-horizon entry-risk context is not available for this snapshot."
    if "normal" in text or "low" in text:
        return "Short-horizon market conditions are not currently flagging abnormal entry stress."
    if "high" in text or "stand down" in text:
        return "Short-horizon market conditions are flagging elevated entry stress."
    if "elevated" in text or "moderate" in text:
        return "Short-horizon market conditions are flagging some entry stress, so timing risk should be watched."
    return f"Short-horizon entry-risk context is classified as {cleaned}."


def live_entry_summary(value: str, action: str) -> str:
    cleaned = clean_value(value)
    text = cleaned.lower()
    action_text = clean_value(action)
    action_lower = action_text.lower()
    cautious_action = any(term in action_lower for term in ["wait", "avoid", "stand down"])

    if cleaned == "Not available":
        return (
            f"In this snapshot, live entry risk is **{cleaned}**. The current **{action_text}** "
            "recommendation should therefore be read through the broader weekly regime, "
            "transition-adjusted weak-outcome probability, and selected-band compensation profile."
        )

    if "normal" in text or "low" in text:
        if cautious_action:
            return (
                f"In this snapshot, live entry risk is **{cleaned}**. That means the model is not "
                "rejecting entry because of an immediate live shock. The recommendation remains "
                f"**{action_text}** because the broader weekly regime, transition-adjusted "
                "weak-outcome probability, and selected-band compensation profile remain unattractive."
            )
        return (
            f"In this snapshot, live entry risk is **{cleaned}**. That means the model is not "
            "flagging an immediate live shock, so the current "
            f"**{action_text}** recommendation is being driven by the broader model context rather "
            "than short-horizon entry stress."
        )

    return (
        f"In this snapshot, live entry risk is **{cleaned}**. The live monitor is flagging "
        "short-horizon entry stress, so immediate deployment timing should be treated cautiously. "
        f"The current **{action_text}** recommendation should be read alongside the broader weekly "
        "regime, transition-adjusted weak-outcome probability, and selected-band compensation profile."
    )


def options_volatility_interpretation(value: str) -> str:
    cleaned = clean_value(value)
    text = cleaned.lower()

    if cleaned == "Not available":
        return "Options-volatility context is unavailable."

    if "below rv" in text or "below realised" in text or "below realized" in text:
        return (
            "Short-dated implied volatility is below recent realised volatility, "
            "so options markets are not currently pricing elevated stress versus recent movement."
        )

    if "above rv" in text or "above realised" in text or "above realized" in text:
        return (
            "Short-dated implied volatility is above recent realised volatility, "
            "so options markets are pricing additional forward-looking stress."
        )

    if "aligned" in text or "normal" in text:
        return "Options markets appear broadly aligned with recent realised movement."

    return f"Options-volatility context is classified as {cleaned}."


def median_fcr_interpretation(selected_band: str, median_fcr: str) -> str:
    fcr = parse_float(median_fcr)

    if fcr is None:
        return (
            f"For the selected {selected_band} band, comparable historical outcomes do not have "
            "an available median FCR reading."
        )

    if fcr < 1.0:
        coverage_note = "meaning typical fee coverage was below breakeven"
    elif fcr <= 1.25:
        coverage_note = "meaning typical fee coverage was close to breakeven"
    else:
        coverage_note = "meaning typical fee coverage was above breakeven"

    return (
        f"For the selected {selected_band} band, comparable historical outcomes produced "
        f"a median FCR of {median_fcr}, {coverage_note}."
    )


def expected_net_interpretation(selected_band: str, expected_net: str) -> str:
    try:
        cleaned_net = (
            clean_value(expected_net)
            .replace("$", "")
            .replace(",", "")
            .replace("%", "")
            .strip()
        )
        net = float(cleaned_net)
    except Exception:
        net = None

    if net is None:
        return (
            f"For the selected {selected_band} band, comparable average dollar outcomes versus "
            "simply holding are not available."
        )

    if net < 0:
        outcome_note = "suggesting downside weeks outweighed upside weeks"
    elif net > 0:
        outcome_note = "suggesting upside weeks outweighed downside weeks"
    else:
        outcome_note = "suggesting average outcomes were close to breakeven"

    return (
        f"For the selected {selected_band} band, comparable outcomes averaged {expected_net} "
        f"versus simply holding, {outcome_note}."
    )


def median_fcr_quality_phrase(median_fcr: str) -> str:
    fcr = parse_display_number(median_fcr)

    if fcr is None:
        return "the typical fee-coverage outcome is not available"

    if fcr < 1.0:
        return "the typical outcome is below breakeven"
    if fcr <= 1.25:
        return "the typical outcome is close to breakeven"
    return "the typical outcome is above breakeven"


def expected_net_quality_phrase(expected_net: str) -> str:
    net = parse_display_number(expected_net)
    if net is None:
        return "the average dollar result is not available"

    if net < 0:
        return "the average dollar result remains negative"
    if net > 0:
        return "the average dollar result is positive"
    return "the average dollar result is close to breakeven"


def current_answer_phrase(action: str) -> str:
    text = clean_value(action).lower()

    if any(term in text for term in ["wait", "avoid", "stand down"]):
        return "not under the current regime-risk profile"
    if any(term in text for term in ["deploy", "constructive", "active"]):
        return "potentially, but only with the listed risk context and sizing discipline"
    if "defensive" in text:
        return "only defensively under the current regime-risk profile"
    return "unclear under the current regime-risk profile"


def compensation_combination_note(median_fcr: str, expected_net: str) -> str:
    net = parse_display_number(expected_net)
    joiner = "but" if net is not None and net < 0 else "and"

    return (
        "That combination is important. "
        f"{median_fcr_quality_phrase(median_fcr).capitalize()}, {joiner} "
        f"{expected_net_quality_phrase(expected_net)}. "
        "This shows why typical fee coverage and average dollar outcomes need to be read together."
    )


def expected_net_signal_phrase(expected_net: str) -> str:
    net = parse_display_number(expected_net)
    if net is None:
        return "expected net outcome"
    if net < 0:
        return "negative expected net outcome"
    if net > 0:
        return "positive expected net outcome"
    return "breakeven expected net outcome"


def transition_adjusted_fcr_note(
    expected_fcr: str,
    weak_rate: str,
    median_fcr: str,
    expected_net: str,
) -> str:
    pieces = []
    expected = parse_display_number(expected_fcr)

    if expected is None:
        pieces.append(
            "Transition-adjusted expected FCR is not available, so the report leans more heavily on the other risk signals."
        )
    elif expected > 0:
        pieces.append(
            "Although transition-adjusted expected FCR is positive, the report does not treat it as the main deployment signal on its own."
        )
    else:
        pieces.append(
            "Transition-adjusted expected FCR is not positive, so the report leans more heavily on the other risk signals."
        )

    weak = parse_display_number(weak_rate, percent_as_decimal=True)
    fcr = parse_display_number(median_fcr)
    net_phrase = expected_net_signal_phrase(expected_net)

    risk_parts = []
    if weak is not None and weak >= 0.5:
        risk_parts.append("elevated weak-outcome probability")
    elif weak is not None:
        risk_parts.append("weak-outcome probability")

    if fcr is not None and fcr <= 1.25:
        risk_parts.append("marginal median fee coverage")
    elif fcr is not None:
        risk_parts.append("median fee coverage")

    risk_parts.append(net_phrase)

    if len(risk_parts) == 1:
        risk_text = risk_parts[0]
    else:
        risk_text = ", ".join(risk_parts[:-1]) + f", and {risk_parts[-1]}"

    pieces.append(
        f"In this snapshot, the {risk_text} point to a setup that does not offer a strong margin of safety."
    )

    return " ".join(pieces)


def transition_risk_note(transition_bucket: str) -> str:
    bucket = clean_value(transition_bucket).lower()

    if bucket == "not available":
        return "Transition-risk context is not available for this snapshot."
    if "low" in bucket and "moderate" not in bucket and "high" not in bucket:
        return (
            "The next-regime outlook appears less concerning, but it still matters because LP outcomes "
            "depend heavily on the next realised price-path regime."
        )
    if any(term in bucket for term in ["moderate", "high", "elevated", "fragile"]):
        return (
            "The next-regime outlook remains unfavourable, either through persistence of the current "
            "weak state or transition into another fragile LP environment."
        )
    return (
        "The transition layer helps assess whether the next-week regime distribution supports or weakens "
        "the case for LP deployment."
    )


def transition_change_note(transition_away_probability: str) -> str:
    probability = parse_display_number(transition_away_probability, percent_as_decimal=True)

    if probability is None:
        return "The probability of regime change is not available for this snapshot."
    if probability >= 0.5:
        return "The current state has historically changed rather than persisted in a high share of comparable cases."
    return "The current state has historically been more likely to persist than change in comparable cases."


def fragile_next_note(fragile_next_probability: str) -> str:
    probability = parse_display_number(fragile_next_probability, percent_as_decimal=True)

    if probability is None:
        return "The probability of a fragile next regime is not available for this snapshot."
    if probability >= 0.5:
        return "Comparable transitions have often led into regimes where LP fee compensation was weak, directional, or shock-sensitive."
    return "Comparable transitions have less often led into fragile regimes, but the next regime still matters for LP fee compensation."


def most_likely_next_note(current_state: str, most_likely_next_state: str) -> str:
    current = strip_probability_suffix(current_state).lower()
    next_state = strip_probability_suffix(most_likely_next_state).lower()

    if clean_value(most_likely_next_state) == "Not available":
        return "The most likely individual next regime is not available for this snapshot."
    if current != "not available" and next_state == current:
        return (
            "The most likely individual next regime matches the current state, so the risk includes "
            "persistence rather than only a shift elsewhere."
        )
    if any(term in next_state for term in ["quality", "compensated", "benign", "stable"]) and not any(
        term in next_state for term in ["low", "weak", "fragile", "shock"]
    ):
        return (
            "The most likely individual next regime appears more constructive, but LP outcomes still "
            "depend heavily on the realised price-path regime."
        )
    return (
        "The most likely individual next regime remains important because LP outcomes depend heavily "
        "on the realised price-path regime."
    )


def transition_distribution_summary(transition_bucket: str, fragile_next_probability: str) -> str:
    bucket = clean_value(transition_bucket).lower()
    fragile_probability = parse_display_number(fragile_next_probability, percent_as_decimal=True)
    elevated_bucket = any(term in bucket for term in ["moderate", "high", "elevated", "fragile"])

    if elevated_bucket or (fragile_probability is not None and fragile_probability >= 0.5):
        return (
            "This means the concern is not only regime change, but whether the next-week regime "
            "distribution remains tilted toward fragile LP conditions."
        )
    if fragile_probability is not None:
        return (
            "This means the transition layer is not only about regime change, but whether the "
            "next-week regime distribution offers enough support for LP compensation."
        )
    return (
        "This means the transition layer is not only about regime change, but about the quality of "
        "the full next-week regime distribution."
    )


def iv_rv_gap_note(iv_rv_gap: str, iv_rv_bucket: str) -> str:
    bucket = clean_value(iv_rv_bucket).lower()

    if "below rv" in bucket or "below realised" in bucket or "below realized" in bucket:
        return "Short-dated IV is below recent realised volatility."
    if "above rv" in bucket or "above realised" in bucket or "above realized" in bucket:
        return "Short-dated IV is above recent realised volatility."
    if "aligned" in bucket or "normal" in bucket:
        return "Short-dated IV is broadly aligned with recent realised volatility."

    gap = parse_display_number(iv_rv_gap, percent_as_decimal=True)
    if gap is None:
        return "The IV/RV gap is not available for this snapshot."
    if gap < 0:
        return "Short-dated IV is below recent realised volatility."
    if gap > 0:
        return "Short-dated IV is above recent realised volatility."
    return "Short-dated IV is broadly aligned with recent realised volatility."


def options_bucket_note(iv_rv_bucket: str) -> str:
    bucket = clean_value(iv_rv_bucket)
    text = bucket.lower()

    if bucket == "Not available":
        return "Options-volatility context is not available for this snapshot."
    if "below rv" in text or "below realised" in text or "below realized" in text:
        return "Options markets are not currently pricing elevated volatility stress versus recent realised movement."
    if "above rv" in text or "above realised" in text or "above realized" in text:
        return "Options markets are pricing higher forward-looking volatility than recent realised movement."
    if "aligned" in text or "normal" in text:
        return "Options markets appear broadly aligned with recent realised movement."
    return f"Options-volatility context is classified as {bucket}."


def options_overlay_summary(iv_rv_bucket: str, action: str) -> str:
    bucket = clean_value(iv_rv_bucket).lower()
    action_text = clean_value(action)

    if "below rv" in bucket or "below realised" in bucket or "below realized" in bucket:
        return (
            "Options-market data is used as a forward-looking risk overlay, not as the main deployment signal. "
            f"In this snapshot, implied volatility is below realised volatility, so the current {action_text} "
            "recommendation is not being driven by elevated options-market stress."
        )
    if "above rv" in bucket or "above realised" in bucket or "above realized" in bucket:
        return (
            "Options-market data is used as a forward-looking risk overlay, not as the main deployment signal. "
            "In this snapshot, implied volatility is above realised volatility, so options-market stress may be "
            f"contributing to the current {action_text} recommendation."
        )
    if bucket == "not available":
        return (
            "Options-market data is used as a forward-looking risk overlay, not as the main deployment signal. "
            "In this snapshot, options-volatility context is not available, so the recommendation is driven by "
            "the other risk layers."
        )
    return (
        "Options-market data is used as a forward-looking risk overlay, not as the main deployment signal. "
        f"In this snapshot, options-volatility context is classified as {clean_value(iv_rv_bucket)}, so it should "
        f"be read as supporting context for the current {action_text} recommendation."
    )


def options_watch_note(iv_rv_bucket: str, action: str) -> str:
    bucket = clean_value(iv_rv_bucket).lower()
    action_text = clean_value(action)

    if "below rv" in bucket or "below realised" in bucket or "below realized" in bucket:
        return (
            f"IV/RV does not currently drive the **{action_text}** recommendation, but a sharp rise in "
            "implied volatility versus realised volatility could increase caution."
        )
    if "above rv" in bucket or "above realised" in bucket or "above realized" in bucket:
        return (
            f"Options-market stress is already part of the risk context for the **{action_text}** "
            "recommendation; lower implied volatility relative to realised volatility would make this overlay less cautious."
        )
    if bucket == "not available":
        return (
            f"Options-volatility context is not available for the **{action_text}** recommendation; refreshed "
            "IV/RV evidence would improve confidence in the overlay."
        )
    return (
        f"Options-volatility context should be monitored alongside the **{action_text}** recommendation, "
        "because a sharp rise in implied volatility versus realised volatility could increase caution."
    )


def freshness_status_note(data_freshness: str) -> str:
    status = clean_value(data_freshness)
    text = status.lower()

    if status == "Not available":
        return "Freshness status is not available for this snapshot."
    if "stale" in text and "not stale" not in text:
        return "The report should be refreshed before being used for LP deployment decisions."
    if "fresh" in text or "not stale" in text:
        return "The report is considered usable under the current pipeline freshness rules."
    return f"Freshness status is classified as {status} under the current pipeline rules."


def build_report(source_text: str, pool_id=DEFAULT_POOL_ID) -> str:
    pool_config = load_pool_config(pool_id)
    pool = pool_config.get("display_name", "Not available")
    pair_label = pool_pair_label(pool_config)
    metadata_table = pool_metadata_table(pool_config)

    generated = find_generated(source_text)

    model_week = find_after_label(
        source_text,
        ["Model week"],
        "Not available",
    )

    action = find_after_label(
        source_text,
        ["Recommended action", "Action"],
        "Not available",
    )

    model_recommendation = find_after_label(
        source_text,
        ["Model recommendation"],
        "Not available",
    )

    preferred_band = find_after_label(
        source_text,
        ["Preferred band"],
        "Not available",
    )

    risk_class = find_after_label(
        source_text,
        ["Client-facing risk class", "Risk class"],
        "Not available",
    )

    current_state_raw = find_after_label(
        source_text,
        ["Current regime state", "Current state", "Regime state"],
        "Not available",
    )
    current_state = strip_probability_suffix(current_state_raw)

    state_age = find_after_label(
        source_text,
        ["State age"],
        "1 week",
    )
    state_age = clean_value(state_age)

    expected_fcr = find_after_label(
        source_text,
        ["Probability-adjusted expected FCR", "Expected FCR", "Adjusted expected FCR"],
        "Not available",
    )

    weak_rate = find_after_label(
        source_text,
        ["Probability-adjusted weak-rate", "Weak-rate", "Weak rate"],
        "Not available",
    )

    distribution_rows = read_distribution_diagnostics(DISTRIBUTION_DIAGNOSTICS_CSV)
    preferred_distribution = find_distribution_row(distribution_rows, preferred_band)
    preferred_median_fcr = format_number(preferred_distribution.get("median_realised_fcr"))
    preferred_weak_rate = format_percent(preferred_distribution.get("weak_rate"))
    preferred_expected_net_vs_hold = format_money(
        preferred_distribution.get("expected_net_outcome_vs_hold")
    )
    preferred_mean_fcr = format_number(preferred_distribution.get("mean_realised_fcr"))
    distribution_section = build_distribution_section(
        distribution_rows,
        preferred_band,
    )

    preferred_band_interpretation = ""
    if preferred_distribution:
        preferred_band_interpretation = (
            f"Although the {preferred_band} band shows a high mean FCR of "
            f"{preferred_mean_fcr}, the median FCR is {preferred_median_fcr} and expected net outcome vs hold is "
            f"{preferred_expected_net_vs_hold}. This supports the WAIT signal because the typical/risk-adjusted "
            "opportunity does not provide a strong margin of safety."
        )

    live_fragility, live_fragility_score = fill_live_fragility_from_all_sources(source_text)

    transition_bucket = find_after_label(
        source_text,
        ["Transition risk bucket", "Transition risk"],
        "Not available",
    )

    transition_away_probability = find_after_label(
        source_text,
        ["Transition-away probability", "Transition away probability"],
        "Not available",
    )

    fragile_next_probability = find_after_label(
        source_text,
        ["Fragile-next probability", "Fragile next probability"],
        "Not available",
    )

    most_likely_next_state = find_after_label(
        source_text,
        ["Most likely next state"],
        "Not available",
    )

    if current_state == "Not available" and most_likely_next_state != "Not available":
        current_state = strip_probability_suffix(most_likely_next_state)

    deribit_iv = find_after_label(
        source_text,
        ["Deribit short-dated IV", "Short-dated IV", "ATM IV"],
        "Not available",
    )

    realised_vol = find_after_label(
        source_text,
        ["Realised volatility", "Realized volatility", "RV"],
        "Not available",
    )

    iv_rv_gap = find_after_label(
        source_text,
        ["IV/RV gap", "IV RV gap"],
        "Not available",
    )

    iv_rv_bucket = find_after_label(
        source_text,
        ["IV/RV bucket", "IV/RV context"],
        "Not available",
    )

    data_freshness_raw = find_after_label(
        source_text,
        ["Data freshness", "Freshness status", "Is stale"],
        "Not available",
    )
    data_freshness = format_freshness(data_freshness_raw)

    staleness_days_raw = find_after_label(
        source_text,
        ["Staleness days from week end", "Staleness days"],
        "Not available",
    )
    staleness_days = format_days(staleness_days_raw)

    if weak_rate != "Not available":
        main_risk_flag = (
            f"For the selected {preferred_band} band, transition-adjusted "
            f"weak-outcome probability is elevated at {weak_rate}."
        )
    else:
        main_risk_flag = "Current regime quality and fee-compensation risk are the main concerns."

    state_age_note = state_age_interpretation(state_age)
    live_entry_risk_note = live_entry_risk_interpretation(live_fragility)
    options_volatility_note = options_volatility_interpretation(iv_rv_bucket)
    median_fcr_note = median_fcr_interpretation(preferred_band, preferred_median_fcr)
    expected_net_note = expected_net_interpretation(preferred_band, preferred_expected_net_vs_hold)

    action = clean_value(action)
    current_answer = current_answer_phrase(action)
    compensation_note = compensation_combination_note(
        preferred_median_fcr,
        preferred_expected_net_vs_hold,
    )
    transition_fcr_note = transition_adjusted_fcr_note(
        expected_fcr,
        weak_rate,
        preferred_median_fcr,
        preferred_expected_net_vs_hold,
    )
    transition_risk_context = transition_risk_note(transition_bucket)
    transition_change_context = transition_change_note(transition_away_probability)
    fragile_next_context = fragile_next_note(fragile_next_probability)
    most_likely_next_context = most_likely_next_note(current_state, most_likely_next_state)
    transition_distribution_context = transition_distribution_summary(
        transition_bucket,
        fragile_next_probability,
    )
    iv_rv_gap_context = iv_rv_gap_note(iv_rv_gap, iv_rv_bucket)
    options_bucket_context = options_bucket_note(iv_rv_bucket)
    options_overlay_context = options_overlay_summary(iv_rv_bucket, action)
    live_entry_bucket_context = live_entry_bucket_note(live_fragility)
    live_entry_summary_context = live_entry_summary(live_fragility, action)
    options_watch_context = options_watch_note(iv_rv_bucket, action)
    freshness_status_context = freshness_status_note(data_freshness)

    if action.upper() == "WAIT":
        recommendation_language = (
            "The model recommends waiting rather than deploying new liquidity at this point."
        )
        conclusion = (
            "No immediate entry shock is detected, but the weekly regime does not currently "
            "offer enough compensation for the expected path-dependent LP risk."
        )
    else:
        recommendation_language = (
            "The model indicates that liquidity deployment may be considered, subject to risk limits and sizing."
        )
        conclusion = (
            "The current setup appears more favourable, but LP performance remains path-dependent and should be monitored."
        )

    report = f"""# {pair_label} LP Risk Snapshot

Generated: **{generated}**

Pool: **{pool}**  
Model week: **{model_week}**

{metadata_table}

---

## 1. Recommendation Summary

| Item | Snapshot |
|---|---:|
| Recommended action | **{action}** |
| Model recommendation | **{model_recommendation}** |
| Selected band | **{preferred_band}** |
| Median FCR / typical fee coverage | **{preferred_median_fcr}** |
| Historical weak-outcome rate | **{preferred_weak_rate}** |
| Expected net outcome vs hold | **{preferred_expected_net_vs_hold}** |
| Mean FCR / skew-sensitive upside context | {preferred_mean_fcr} |
| Transition-adjusted weak-outcome probability | {weak_rate} |
| Client-facing risk class | **{risk_class}** |
| Current regime state | **{current_state}** |

**Bottom line:** {recommendation_language}

{conclusion}

---

## 2. Executive View

This snapshot assesses whether a {pool} LP position is likely to be adequately compensated for the price-path risk it is taking.

The current recommendation is **{action}**. The key issue is not an immediate live-entry shock: live entry risk is currently classified as **{live_fragility}**. Options-market stress is also not the main driver of the recommendation, with IV/RV currently classified as **{iv_rv_bucket}**.

The main concern is regime quality. The current weekly state is classified as **{current_state}**, and the selected **{preferred_band}** band has a transition-adjusted weak-outcome probability of **{weak_rate}**. In plain English, after accounting for regime-transition risk, comparable {preferred_band} LP deployments have historically produced weak outcomes â€” defined as realised FCR below 1.0 â€” at an elevated rate.

{preferred_band_interpretation}

Mean FCR is shown for context but is not treated as the primary deployment signal because low required-fee denominator weeks can produce very high FCR values even when the dollar outcome is small.

---

## 3. Key Risk Signals

| Signal | Current reading | Interpretation |
|---|---:|---|
| Median FCR / typical fee coverage | **{preferred_median_fcr}** | {median_fcr_note} |
| Historical weak-outcome rate | **{preferred_weak_rate}** | For the selected {preferred_band} band, {preferred_weak_rate} of comparable historical outcomes had realised FCR below 1.0. |
| Transition-adjusted weak-outcome probability | **{weak_rate}** | For the selected {preferred_band} band, the weak-outcome probability rises to {weak_rate} after incorporating likely regime transitions. |
| Expected net outcome vs hold | **{preferred_expected_net_vs_hold}** | {expected_net_note} |
| Mean FCR / skew-sensitive upside context | {preferred_mean_fcr} | Context only; can be inflated by low required-fee denominator weeks and is not the primary deployment signal. |
| Transition-adjusted expected FCR | {expected_fcr} | Modelled expected FCR after transition adjustment; retained as supporting context rather than the main recommendation driver. |
| Current regime state | **{current_state}** | Current weekly environment shows directional price-path risk and weak evidence that fees are compensating LPs for that risk. |
| State age | **{state_age}** | {state_age_note} |
| Live entry risk | **{live_fragility}** | {live_entry_risk_note} |
| Transition risk | **{transition_bucket}** | {transition_risk_context} |
| Options-volatility context | **{iv_rv_bucket}** | {options_volatility_note} |

**Main risk flag:** {main_risk_flag}

For the selected {preferred_band} band, a weak outcome means realised FCR below 1.0. In plain English, this means comparable selected-band LP deployments failed to cover the estimated price-path risk hurdle at an elevated transition-adjusted rate.

The median FCR describes the typical fee-coverage outcome, while expected net outcome is an average dollar result and can be pulled negative by larger downside weeks.

---

## 4. Regime & Fee Compensation

The model's core question is simple:

**Are LPs likely to be compensated for the path-dependent risk they would take by deploying now?**

The current answer is: **{current_answer}**.

The current state is **{current_state}**. For the selected {preferred_band} band, comparable historical outcomes show a median FCR of **{preferred_median_fcr}**, a historical weak-outcome rate of **{preferred_weak_rate}**, and an expected net outcome vs hold of **{preferred_expected_net_vs_hold}**.

{compensation_note}

{transition_fcr_note}

**FCR**, or fee coverage ratio, measures whether estimated LP fees were sufficient to cover the required compensation for price-path risk. An FCR above 1.0 means fees covered the estimated hurdle; below 1.0 means they did not.

**Weak-outcome rate** measures how often comparable historical setups produced realised FCR below 1.0. A high weak-outcome rate does not guarantee a poor result, but it indicates that similar setups have often been fragile or poorly compensated.

{distribution_section}

---

## 5. Transition Risk

| Transition signal | Current reading | Why it matters |
|---|---:|---|
| Transition risk | **{transition_bucket}** | {transition_risk_context} |
| Probability of regime change | **{transition_away_probability}** | {transition_change_context} |
| Probability of fragile next regime | **{fragile_next_probability}** | {fragile_next_context} |
| Most likely next regime | **{most_likely_next_state}** | {most_likely_next_context} |

The transition layer is included because LP outcomes are highly path-dependent. A position can look acceptable at entry but become unattractive if the next-week regime outlook is dominated by persistence of a weak state or transition into another directional, shock-driven, or poorly compensated environment.

In this snapshot, transition risk is classified as **{transition_bucket}**. The model estimates a **{transition_away_probability}** probability of moving away from the current state, while the most likely individual next regime is **{most_likely_next_state}**. The model also estimates a **{fragile_next_probability}** probability of the next regime being fragile or low-quality for LP deployment. {transition_distribution_context}

---

## 6. Options / Volatility Context

| Options / volatility signal | Current reading | Interpretation |
|---|---:|---|
| Deribit short-dated implied volatility | **{deribit_iv}** | Options-market estimate of near-term ETH volatility. |
| Recent realised volatility | **{realised_vol}** | Actual recent ETH volatility based on the realised price path. |
| IV/RV gap | **{iv_rv_gap}** | {iv_rv_gap_context} |
| Options-volatility bucket | **{iv_rv_bucket}** | {options_bucket_context} |

{options_overlay_context}

The main concern remains regime quality, transition-adjusted weak-outcome probability, and whether the selected {preferred_band} band offers enough compensation for path-dependent LP risk.

---

## 7. Live Entry Risk

| Live-entry signal | Current reading | Interpretation |
|---|---:|---|
| Live entry-risk bucket | **{live_fragility}** | {live_entry_bucket_context} |
| Live entry-risk score | **{live_fragility_score}** | Numerical score from the live monitor; higher values indicate greater short-horizon entry risk. |

The live entry-risk monitor is designed to detect short-horizon stress that could make immediate LP deployment unattractive, such as sharp recent price movement, sudden drawdowns, or unstable market conditions.

{live_entry_summary_context}

---

## 8. What Would Change the Recommendation?

The recommendation would only change if the model saw sufficient evidence that conditions were likely to move into more LP-friendly territory, with stronger fee compensation and lower weak-outcome risk.

Key improvements to watch:

1. **Lower weak-outcome probability**  
   The selected {preferred_band} band would need to show a lower probability of realised FCR falling below 1.0 under comparable regime and transition conditions.

2. **Improved regime quality**  
   A move away from **{current_state}** toward a cleaner, more fee-compensated regime would improve the setup.

3. **Stronger selected-band compensation**  
   Higher median FCR, lower weak-outcome rate, and stronger expected net outcome versus hold would suggest LPs are being better compensated for path-dependent LP risk.

4. **Less fragile next-regime outlook**  
   A lower probability of a fragile or low-quality next regime would reduce the risk that an apparently acceptable entry deteriorates quickly.

5. **Contained options-market stress**  
   {options_watch_context}

---

## 9. Methodology in Brief

This report combines four layers for the configured pool, currently calibrated for Uniswap v3 ETH/USDC 0.05%:

1. **Historical LP outcome model**  
   Compares similar historical ETH/USDC LP environments across 5%, 10%, and 20% band widths.

2. **Fee-compensation analysis**  
   Estimates whether expected LP fees appear sufficient relative to the path-dependent rebalancing risk of providing liquidity.

3. **Regime and transition analysis**  
   Classifies the current market state and estimates whether the next-week regime outlook is likely to remain favourable, deteriorate, or improve.

4. **Forward-looking risk overlays**  
   Adds live entry-risk monitoring and Deribit options-volatility context so the report does not rely on historical averages alone.

The report should be read as a decision-support tool, not a performance guarantee. It is intended to support LP deployment assessment and does not constitute financial advice.

---

## 10. Data Freshness

| Freshness item | Current reading | Interpretation |
|---|---:|---|
| Latest completed model week | **{model_week}** | The recommendation is based on the latest weekly window currently available in the pipeline. |
| Days since model week end | **{staleness_days}** | Measures how far the report is from the end of the latest completed model week. |
| Freshness status | **{data_freshness}** | {freshness_status_context} |

The snapshot is only as useful as the freshness of its underlying data. If price, fee, liquidity, TVL, or options inputs become stale, the recommendation should be refreshed before being used for LP deployment decisions.

Freshness is assessed relative to the latest completed model week currently available in the pipeline. A full roll-forward to the next completed week depends on refreshed fee and liquidity inputs.

---

## Final Takeaway

The model currently recommends **{action}**.

There is no major immediate entry shock detected, and options-market stress is not the main issue. The concern is that the current {pair_label} LP environment does not yet offer sufficiently attractive compensation for the expected path-dependent risk.

**Client-facing conclusion:** wait for either stronger fee compensation, a cleaner regime, or lower weak-outcome probability before treating this as an attractive LP deployment window.
"""
    return report


def main(pool_id=DEFAULT_POOL_ID):
    print("Building client-facing LP risk snapshot...")

    source_text = read_text(SOURCE_MD)
    report = build_report(source_text, pool_id=pool_id)

    OUT_MD.write_text(report, encoding="utf-8")
    OUT_TXT.write_text(report, encoding="utf-8")

    print("Saved:")
    print(f"- {OUT_MD}")
    print(f"- {OUT_TXT}")
    print()
    print("Done.")


if __name__ == "__main__":
    args = parse_args()
    main(pool_id=args.pool_id)



