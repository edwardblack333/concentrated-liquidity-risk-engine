# Methodology Summary

The engine uses locally stored historical datasets to rebuild weekly market state and LP opportunity metrics. It is designed to assess whether expected fee opportunity is likely to compensate for price-path and rebalancing risk across candidate concentrated-liquidity ranges.

## Core Workflow

1. Build an hourly engine from price, fee, liquidity, tick-derived, and volatility inputs.
2. Aggregate hourly inputs into weekly market-state and LP opportunity metrics.
3. Classify the weekly market regime using score-based regime features.
4. Estimate fee coverage relative to price-path risk and rebalancing burden.
5. Compare candidate LP range widths.
6. Produce recommendation-style decision-support outputs and client-facing summaries.

## Key Concepts

* **Fee coverage ratio (FCR)** is the model's measure of whether estimated LP fees are large enough relative to expected path and rebalancing costs.
* **Price-path risk** means the weekly LP outcome depends on how price moved through the period, including volatility, range crossings, and directional movement, not only the final weekly price.
* **Rebalancing risk** is the potential cost, drag, or operational burden created when a concentrated LP range becomes poorly positioned after adverse movement.
* **Regime classification** groups weeks with similar market conditions so current signals can be compared with relevant historical states.

## Public Release Scope

The public release keeps the model workflow visible while excluding raw/private data, paid-source exports, live query infrastructure, and full generated outputs. Scripts expect sample or user-supplied inputs with matching schemas.

The current calibration is for Uniswap v3 ETH/USDC 0.05%. Extending to other pools requires fresh data coverage, liquidity reconstruction, fee calibration, regime review, and validation.
