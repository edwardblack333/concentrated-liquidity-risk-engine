# Public portfolio copy: expects local sample/master inputs to be supplied separately.
# Raw data, paid exports, API credentials, and live output files are intentionally excluded.

from pathlib import Path
import pandas as pd
import numpy as np

BASE_DIR = Path(__file__).resolve().parents[2]

# ============================================================
# Input / output files
# ============================================================

INPUT_ENGINE = BASE_DIR / "samples" / "data" / "extended_hourly_engine.csv"

OUTPUT_WEEKLY = BASE_DIR / "outputs" / "extended_weekly_regime_metrics.csv"
OUTPUT_SUMMARY = BASE_DIR / "outputs" / "extended_weekly_regime_summary.csv"

# ============================================================
# Settings
# ============================================================

# Weekly regime windows:
# Monday 00:00 -> Monday 00:00
WEEK_START_DAY = 0  # Monday=0, Tuesday=1, Wednesday=2, etc.

HOURS_PER_WEEK = 168

# ============================================================
# Helpers
# ============================================================

def assign_week_start(hour):
    """
    Assign each timestamp to the Monday 00:00 week bucket.
    """
    hour = pd.Timestamp(hour)
    days_since_week_start = (hour.weekday() - WEEK_START_DAY) % 7
    return (hour - pd.Timedelta(days=days_since_week_start)).normalize()


def safe_divide(a, b):
    if b == 0 or pd.isna(b):
        return np.nan
    return a / b


def label_regime(row):
    """
    Rule-based regime classifier.

    This keeps the same broad labels we have been using:
    - Balanced Oscillation
    - High-Churn Mean Reversion
    - Mixed Oscillation
    - Shock-Influenced / Jump Risk
    - Directional Uptrend
    - Upward Drift
    - Downward Drift
    - Volatile Downtrend
    - Volatile Uptrend
    """

    net_return = row["net_return"]
    path_length = row["path_length"]
    path_balance = row["path_balance"]
    displacement = row["displacement_ratio"]
    shock_dominance = row["shock_dominance"]

    # Strong directional regimes
    if net_return >= 0.15 and displacement >= 0.22:
        return "Directional Uptrend"

    if net_return <= -0.15 and displacement >= 0.15:
        if path_length >= 0.80:
            return "Volatile Downtrend"
        return "Downward Drift"

    # Medium directional drift
    if net_return >= 0.08 and displacement >= 0.14:
        if path_length >= 0.95:
            return "Volatile Uptrend"
        return "Upward Drift"

    if net_return <= -0.08 and displacement >= 0.12:
        if path_length >= 0.80:
            return "Volatile Downtrend"
        return "Downward Drift"

    # Shock-heavy weeks
    if shock_dominance >= 0.07:
        return "Shock-Influenced / Jump Risk"

    # Very high path length but not strongly directional
    if path_length >= 1.00 and path_balance >= 0.80 and displacement < 0.12:
        return "High-Churn Mean Reversion"

    # Clean balanced oscillation
    if path_balance >= 0.86 and displacement <= 0.08:
        return "Balanced Oscillation"

    # Mixed / choppy but less clean
    return "Mixed Oscillation"


def calculate_week_metrics(group, week_start):
    group = group.sort_values("hour").copy()

    week_end = week_start + pd.Timedelta(days=7)

    start_price = group["price"].iloc[0]
    end_price = group["price"].iloc[-1]

    returns = group["price"].pct_change().dropna()
    abs_returns = returns.abs()

    up_path = returns[returns > 0].sum()
    down_path = abs(returns[returns < 0].sum())

    path_length = abs_returns.sum()
    net_return = (end_price / start_price) - 1
    absolute_net_movement = abs(net_return)

    larger_path_side = max(up_path, down_path)
    smaller_path_side = min(up_path, down_path)

    path_balance = safe_divide(smaller_path_side, larger_path_side)
    displacement_ratio = safe_divide(absolute_net_movement, path_length)
    path_efficiency = 1 - displacement_ratio if pd.notna(displacement_ratio) else np.nan

    max_hourly_move = abs_returns.max()
    avg_hourly_move = abs_returns.mean()

    shock_dominance = safe_divide(max_hourly_move, path_length)
    shock_ratio = safe_divide(max_hourly_move, avg_hourly_move)

    realised_vol_annualised = returns.std() * np.sqrt(24 * 365)

    total_volume_usd = group["volume_usd"].sum()
    total_fees_usd = group["fees_usd"].sum()
    fee_to_volume_rate = safe_divide(total_fees_usd, total_volume_usd)

    avg_tvl_usd = group["tvl_usd"].mean() if "tvl_usd" in group.columns else np.nan
    avg_active_liquidity = group["active_liquidity"].mean()

    avg_tick = group["tick"].mean() if "tick" in group.columns else np.nan
    avg_sqrt_price_x96 = group["sqrt_price_x96"].mean() if "sqrt_price_x96" in group.columns else np.nan

    result = {
        "week_start": week_start,
        "week_end": week_end,
        "hours": len(group),

        "start_price": start_price,
        "end_price": end_price,

        "net_return": net_return,
        "absolute_net_movement": absolute_net_movement,

        "path_length": path_length,
        "up_path": up_path,
        "down_path": down_path,
        "path_balance": path_balance,

        "displacement_ratio": displacement_ratio,
        "path_efficiency": path_efficiency,

        "max_hourly_move": max_hourly_move,
        "avg_hourly_move": avg_hourly_move,
        "shock_dominance": shock_dominance,
        "shock_ratio": shock_ratio,

        "realised_vol_annualised": realised_vol_annualised,

        "total_volume_usd": total_volume_usd,
        "total_fees_usd": total_fees_usd,
        "fee_to_volume_rate": fee_to_volume_rate,

        "avg_tvl_usd": avg_tvl_usd,
        "avg_active_liquidity": avg_active_liquidity,
        "avg_tick": avg_tick,
        "avg_sqrt_price_x96": avg_sqrt_price_x96,
    }

    result["regime_label"] = label_regime(result)

    return result


# ============================================================
# Load engine
# ============================================================

engine = pd.read_csv(INPUT_ENGINE)

engine.columns = engine.columns.str.strip().str.lower()

engine["hour"] = pd.to_datetime(engine["hour"], errors="coerce")
engine = engine.dropna(subset=["hour"]).copy()

numeric_cols = [
    "price",
    "volume_usd",
    "fees_usd",
    "active_liquidity",
    "tick",
    "sqrt_price_x96",
]

if "tvl_usd" in engine.columns:
    numeric_cols.append("tvl_usd")

for col in numeric_cols:
    if col in engine.columns:
        engine[col] = pd.to_numeric(engine[col], errors="coerce")

required_cols = [
    "hour",
    "price",
    "volume_usd",
    "fees_usd",
    "active_liquidity",
]

missing_required = [col for col in required_cols if col not in engine.columns]

if missing_required:
    raise ValueError(
        f"Missing required columns: {missing_required}. "
        f"Columns found: {engine.columns.tolist()}"
    )

engine = engine.sort_values("hour").reset_index(drop=True)

# ============================================================
# Assign Monday weekly buckets
# ============================================================

engine["week_start"] = engine["hour"].apply(assign_week_start)

# Keep only complete Monday-to-Monday weeks
week_counts = engine.groupby("week_start")["hour"].count().reset_index(name="hours")
complete_weeks = week_counts.loc[week_counts["hours"] == HOURS_PER_WEEK, "week_start"]

engine_complete = engine[engine["week_start"].isin(complete_weeks)].copy()

# ============================================================
# Build weekly metrics
# ============================================================

weekly_rows = []

for week_start, group in engine_complete.groupby("week_start"):
    weekly_rows.append(calculate_week_metrics(group, week_start))

weekly = pd.DataFrame(weekly_rows)
weekly = weekly.sort_values("week_start").reset_index(drop=True)

# ============================================================
# Build summary
# ============================================================

summary = (
    weekly
    .groupby("regime_label")
    .agg(
        observations=("regime_label", "count"),
        avg_net_return=("net_return", "mean"),
        median_net_return=("net_return", "median"),
        avg_abs_net_movement=("absolute_net_movement", "mean"),
        avg_path_length=("path_length", "mean"),
        median_path_length=("path_length", "median"),
        avg_path_balance=("path_balance", "mean"),
        avg_displacement_ratio=("displacement_ratio", "mean"),
        avg_shock_dominance=("shock_dominance", "mean"),
        avg_realised_vol_annualised=("realised_vol_annualised", "mean"),
        avg_total_volume_usd=("total_volume_usd", "mean"),
        avg_total_fees_usd=("total_fees_usd", "mean"),
    )
    .reset_index()
)

summary["total_weeks_in_sample"] = len(weekly)
summary["observation_share"] = summary["observations"] / len(weekly)

summary = summary.sort_values("observations", ascending=False).reset_index(drop=True)

# ============================================================
# Save outputs
# ============================================================

OUTPUT_WEEKLY.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_SUMMARY.parent.mkdir(parents=True, exist_ok=True)

weekly.to_csv(OUTPUT_WEEKLY, index=False)
summary.to_csv(OUTPUT_SUMMARY, index=False)

# ============================================================
# Print diagnostics
# ============================================================

print()
print("Extended weekly regime metrics complete.")
print(f"Weekly metrics saved to: {OUTPUT_WEEKLY}")
print(f"Summary saved to: {OUTPUT_SUMMARY}")

print()
print("Weekly window validation:")
print(
    weekly
    .assign(
        start_day=pd.to_datetime(weekly["week_start"]).dt.day_name(),
        end_day=pd.to_datetime(weekly["week_end"]).dt.day_name(),
    )
    [["week_start", "start_day", "week_end", "end_day", "hours", "regime_label"]]
    .head(20)
    .to_string(index=False)
)

print()
print("Start weekday counts:")
print(pd.to_datetime(weekly["week_start"]).dt.day_name().value_counts())

print()
print("End weekday counts:")
print(pd.to_datetime(weekly["week_end"]).dt.day_name().value_counts())

print()
print("Date range:")
print(f"{weekly['week_start'].min()} to {weekly['week_end'].max()}")

print()
print("Rows created:")
print(len(weekly))

print()
print("Regime counts:")
print(weekly["regime_label"].value_counts())

print()
print("Regime summary:")
print(summary.to_string(index=False))

print()
print("Most directional weeks:")
print(
    weekly
    .sort_values("displacement_ratio", ascending=False)
    [[
        "week_start",
        "week_end",
        "regime_label",
        "net_return",
        "path_length",
        "path_balance",
        "displacement_ratio",
        "shock_dominance",
        "realised_vol_annualised",
    ]]
    .head(15)
    .to_string(index=False)
)

print()
print("Highest path-length weeks:")
print(
    weekly
    .sort_values("path_length", ascending=False)
    [[
        "week_start",
        "week_end",
        "regime_label",
        "net_return",
        "path_length",
        "path_balance",
        "displacement_ratio",
        "shock_dominance",
        "realised_vol_annualised",
    ]]
    .head(15)
    .to_string(index=False)
)

print()
print("Most shock-dominated weeks:")
print(
    weekly
    .sort_values("shock_dominance", ascending=False)
    [[
        "week_start",
        "week_end",
        "regime_label",
        "net_return",
        "path_length",
        "max_hourly_move",
        "shock_dominance",
        "shock_ratio",
        "displacement_ratio",
    ]]
    .head(15)
    .to_string(index=False)
)

print()
print("Preview:")
print(
    weekly
    [[
        "week_start",
        "week_end",
        "regime_label",
        "net_return",
        "path_length",
        "path_balance",
        "displacement_ratio",
        "shock_dominance",
        "realised_vol_annualised",
        "total_volume_usd",
        "total_fees_usd",
    ]]
    .head(30)
    .to_string(index=False)
)


