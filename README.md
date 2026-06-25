# Concentrated Liquidity LP Risk Engine

A pool-configured LP risk engine, currently calibrated for Uniswap v3 ETH/USDC 0.05%, designed to assess whether upcoming fee opportunity is likely to compensate for price-path and rebalancing risk.

## Model overview

A one-page explanation of the LP Risk Engine’s problem, methodology, outputs, and guardrails.

[View the one-page model overview](LP_Risk_Engine_Single_Pool_Overview_Edward_Black.pdf)

**Status:** Research/product prototype.

This portfolio release demonstrates a local data pipeline, regime-classification workflow, fee-coverage model, reporting layer, and validation framework for concentrated-liquidity LP decision support. It intentionally excludes raw data, paid-source exports, API credentials, private query identifiers, full generated outputs, and live operational files.

## What It Does

The engine combines historical price, fee, liquidity, tick-derived, and options-volatility context into a weekly decision-support workflow. It classifies market regimes, estimates whether fee opportunity is likely to cover price-path and rebalancing risk, compares candidate LP range widths, and produces report-ready summaries for review.

In plain English:

* **Fee coverage ratio (FCR)** compares estimated LP fees with the modelled cost of price movement and rebalancing.
* **Price-path risk** captures the fact that the route price takes through the week matters, not just the start and end price.
* **Rebalancing risk** captures the burden created when a concentrated LP range becomes poorly positioned as price moves.
* **Regime classification** groups recent market conditions so the model can compare the current setup with similar historical states.

## Key Features

* Weekly market-regime classification for concentrated-liquidity LP conditions.
* Expected fee-coverage analysis across candidate LP range widths.
* WAIT / DEPLOY / WIDER-style recommendation framing.
* Transition-risk and fragility overlays.
* Options-market risk signals where available.
* Client-facing report generation.
* Historical recommendation audit and diagnostic validation framework.

## Current Calibration

The current model is calibrated to:

* Protocol: Uniswap v3
* Pool: ETH/USDC
* Fee tier: 0.05%
* Decision horizon: weekly
* Candidate ranges: 5%, 10%, and 20%

## What It Is Not

This is not investment advice, a guaranteed profitable LP strategy, a clean out-of-sample proven backtest, a fully automated DeFi LP scanner, or a model validated across all pools. The current calibration is specific to Uniswap v3 ETH/USDC 0.05%.

## Repository Layout

* `docs/`: product framing, methodology, validation, limitations, roadmap, architecture, an [example report walkthrough](docs/example_report_walkthrough.md), and a [model decision flow](docs/model_decision_flow.md).
* `config/`: public example pool configuration.
* `scripts/core/`: local model and rebuild scripts.
* `scripts/reporting/`: markdown/report generation scripts.
* `scripts/diagnostics/`: audit-oriented scripts.
* `samples/reports/`: sanitised markdown examples.
* `tests/`: lightweight config-loader test.

## Data Policy

No private data, local environment files, API keys, paid exports, large CSVs, or full generated outputs are included. Public users should provide their own data in the expected schema before running scripts.

## Validation Framing

The validation material in this release is a historical recommendation audit / in-sample diagnostic validation. It is useful for showing how the model was evaluated and where it needs improvement, but it should not be read as a clean out-of-sample backtest or as evidence of guaranteed live performance.
