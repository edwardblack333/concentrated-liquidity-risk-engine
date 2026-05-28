# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

import pandas as pd
import numpy as np
from pathlib import Path

# --------------------------------------------------
# Paths
# --------------------------------------------------

BASE_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = BASE_DIR / "outputs"

INPUT_FILE = OUTPUT_DIR / "extended_weekly_regime_metrics_with_risk_scores_and_tvl.csv"
OUT_FILE = OUTPUT_DIR / "extended_weekly_regime_metrics_with_score_based_states.csv"

# --------------------------------------------------
# Helpers
# --------------------------------------------------

def clean_numeric(series):
    return pd.to_numeric(
        series.astype(str)
        .str.replace(",", "", regex=False)
        .str.replace("$", "", regex=False)
        .str.replace("Â£", "", regex=False)
        .str.replace("%", "", regex=False)
        .str.strip()
        .replace({"": np.nan, "nan": np.nan, "None": np.nan}),
        errors="coerce"
    )

def percentile(series):
    return series.rank(pct=True)

def clipped(series):
    return series.clip(lower=0, upper=1)

# --------------------------------------------------
# Load
# --------------------------------------------------

df = pd.read_csv(INPUT_FILE)

print("Loaded:", INPUT_FILE)
print("Rows:", len(df))

# --------------------------------------------------
# Required columns
# --------------------------------------------------

required_cols = [
    "week_start",
    "week_end",
    "regime_label",
    "path_length",
    "path_balance",
    "absolute_net_movement",
    "realised_vol_annualised",
    "total_fees_usd",
    "total_volume_usd",
    "avg_tvl_usd",
    "avg_active_liquidity",
    "shock_score",
    "shock_tag",
    "directionality_score",
    "directionality_tag",
]

missing = [c for c in required_cols if c not in df.columns]
if missing:
    raise ValueError(f"Missing required columns: {missing}")

# --------------------------------------------------
# Clean numeric columns
# --------------------------------------------------

numeric_cols = [
    "path_length",
    "path_balance",
    "absolute_net_movement",
    "realised_vol_annualised",
    "total_fees_usd",
    "total_volume_usd",
    "avg_tvl_usd",
    "avg_active_liquidity",
    "shock_score",
    "directionality_score",
]

for col in numeric_cols:
    df[col] = clean_numeric(df[col])

df = df.dropna(subset=numeric_cols).copy()

df = df[
    (df["path_length"] > 0)
    & (df["avg_tvl_usd"] > 0)
    & (df["total_fees_usd"] >= 0)
    & (df["total_volume_usd"] >= 0)
].copy()

print("Rows after cleaning:", len(df))

# --------------------------------------------------
# Derived fee metrics
# --------------------------------------------------

df["fee_yield"] = df["total_fees_usd"] / df["avg_tvl_usd"]
df["volume_yield"] = df["total_volume_usd"] / df["avg_tvl_usd"]

df["fees_per_path"] = df["fee_yield"] / df["path_length"]
df["volume_per_path"] = df["volume_yield"] / df["path_length"]

# --------------------------------------------------
# Percentiles
# --------------------------------------------------

df["fee_yield_percentile"] = percentile(df["fee_yield"])
df["volume_yield_percentile"] = percentile(df["volume_yield"])
df["path_length_percentile"] = percentile(df["path_length"])
df["realised_vol_percentile"] = percentile(df["realised_vol_annualised"])
df["active_liquidity_percentile"] = percentile(df["avg_active_liquidity"])
df["path_balance_percentile"] = percentile(df["path_balance"])

# --------------------------------------------------
# Controlled path activity
# --------------------------------------------------
# We do not want path quality to simply reward extreme path length.
# This gives highest score around moderately elevated activity.
# Centre can be adjusted later after validation.

target_path_percentile = 0.65

df["controlled_path_activity"] = (
    1 - ((df["path_length_percentile"] - target_path_percentile).abs() / target_path_percentile)
)

df["controlled_path_activity"] = clipped(df["controlled_path_activity"])

# --------------------------------------------------
# Inverse risk scores
# --------------------------------------------------

df["non_directional_score"] = 1 - df["directionality_score"]
df["non_shock_score"] = 1 - df["shock_score"]

df["non_directional_score"] = clipped(df["non_directional_score"])
df["non_shock_score"] = clipped(df["non_shock_score"])

# --------------------------------------------------
# Fee Opportunity Score
# --------------------------------------------------
# Measures whether the pool/regime is generating trading activity and fees.
# This is NOT automatically good for LPs â€” it is the opportunity side.

df["fee_opportunity_score"] = (
    0.40 * df["fee_yield_percentile"]
    + 0.30 * df["volume_yield_percentile"]
    + 0.20 * df["path_length_percentile"]
    + 0.10 * df["realised_vol_percentile"]
)

# --------------------------------------------------
# Path Quality Score
# --------------------------------------------------
# Measures whether movement looks LP-friendly:
# balanced, non-directional, non-shock, and not pathologically extreme.

df["path_quality_score"] = (
    0.40 * df["path_balance_percentile"]
    + 0.30 * df["non_directional_score"]
    + 0.20 * df["non_shock_score"]
    + 0.10 * df["controlled_path_activity"]
)

df["fee_opportunity_score"] = clipped(df["fee_opportunity_score"])
df["path_quality_score"] = clipped(df["path_quality_score"])

# --------------------------------------------------
# Buckets
# --------------------------------------------------

def bucket_score(score):
    if pd.isna(score):
        return "Unknown"
    if score >= 0.75:
        return "High"
    if score >= 0.50:
        return "Moderate"
    if score >= 0.25:
        return "Low"
    return "Very Low"

df["fee_opportunity_bucket"] = df["fee_opportunity_score"].apply(bucket_score)
df["path_quality_bucket"] = df["path_quality_score"].apply(bucket_score)

# --------------------------------------------------
# Score-based regime state classifier
# --------------------------------------------------
# Order matters:
# first identify dangerous/high-risk combinations,
# then clean opportunities,
# then neutral/low-opportunity states.

def classify_score_based_state(row):
    fee = row["fee_opportunity_score"]
    quality = row["path_quality_score"]
    shock = row["shock_score"]
    direction = row["directionality_score"]
    path_balance = row["path_balance"]

    high_fee = fee >= 0.70
    moderate_fee = fee >= 0.50

    high_quality = quality >= 0.65
    moderate_quality = quality >= 0.50
    low_quality = quality < 0.50

    high_direction = direction >= 0.70
    directional_bias = direction >= 0.50

    high_shock = shock >= 0.75
    shock_contaminated = shock >= 0.60

    high_balance = path_balance >= 0.80

    # Most dangerous: fee-rich but hostile path.
    if high_fee and high_direction and high_shock:
        return "Fee-Rich Directional Shock"

    if high_fee and high_direction:
        return "Fee-Rich Directional Risk"

    if high_fee and high_shock:
        return "Fee-Rich Shock Risk"

    # Cleanest LP-style setup.
    if moderate_fee and high_quality and not high_direction and not high_shock:
        return "Clean Fee Opportunity"

    # High churn, decent path balance, but contaminated by some risk.
    if high_fee and high_balance and not high_direction:
        return "High-Churn Fee Opportunity"

    # Directional regimes without enough fee strength.
    if high_direction and not high_fee:
        return "Directional Low-Quality"

    # Shocky regimes without enough fee strength.
    if high_shock and not high_fee:
        return "Shock-Contaminated Low-Quality"

    # Moderate fee and moderate quality.
    if moderate_fee and moderate_quality:
        return "Moderate Fee / Moderate Quality"

    # Clean but low-fee regime.
    if not moderate_fee and high_quality:
        return "Clean but Low Fee"

    # Everything else.
    if low_quality:
        return "Low-Quality / Low-Conviction"

    return "Neutral / Low-Conviction"


df["score_based_regime_state"] = df.apply(classify_score_based_state, axis=1)

# --------------------------------------------------
# Save
# --------------------------------------------------

df.to_csv(OUT_FILE, index=False)

print("\nSaved:")
print(OUT_FILE)

print("\nFee opportunity summary:")
print(df["fee_opportunity_score"].describe())

print("\nPath quality summary:")
print(df["path_quality_score"].describe())

print("\nFee opportunity bucket counts:")
print(df["fee_opportunity_bucket"].value_counts())

print("\nPath quality bucket counts:")
print(df["path_quality_bucket"].value_counts())

print("\nScore-based regime state counts:")
print(df["score_based_regime_state"].value_counts())

print("\nRecent rows:")
recent_cols = [
    "week_start",
    "week_end",
    "regime_label",
    "shock_tag",
    "directionality_tag",
    "fee_yield",
    "volume_yield",
    "fee_opportunity_score",
    "fee_opportunity_bucket",
    "path_quality_score",
    "path_quality_bucket",
    "score_based_regime_state",
]

print(df[recent_cols].tail(20).to_string(index=False))

# --------------------------------------------------
# State medians
# --------------------------------------------------

state_summary = (
    df.groupby("score_based_regime_state")
    .agg(
        observations=("week_start", "count"),
        median_fee_opportunity_score=("fee_opportunity_score", "median"),
        median_path_quality_score=("path_quality_score", "median"),
        median_fee_yield=("fee_yield", "median"),
        median_volume_yield=("volume_yield", "median"),
        median_shock_score=("shock_score", "median"),
        median_directionality_score=("directionality_score", "median"),
        median_path_balance=("path_balance", "median"),
        median_path_length=("path_length", "median"),
    )
    .reset_index()
    .sort_values("observations", ascending=False)
)

STATE_SUMMARY_FILE = OUTPUT_DIR / "score_based_regime_state_summary.csv"
state_summary.to_csv(STATE_SUMMARY_FILE, index=False)

print("\nSaved state summary:")
print(STATE_SUMMARY_FILE)

print("\nState summary:")
print(state_summary.to_string(index=False))


