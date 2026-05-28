# Model Decision Flow

This document explains the LP risk engine flow in plain English. It describes how the public portfolio release turns market inputs into a recommendation-style report, without exposing private data, production queries, or live operational outputs.

The model is decision-support tooling. It is designed to help a human reviewer understand the fee-versus-risk trade-off for a concentrated liquidity position. It should not be interpreted as investment advice or a guarantee of profitability.

## Inputs

The workflow starts with market and pool context for the configured LP opportunity. In the full workflow, these inputs can include:

* price history;
* fee observations;
* liquidity and tick-derived context;
* volatility context, including options-market signals where available;
* pool configuration, including protocol, asset pair, fee tier, decision horizon, and candidate LP ranges.

The public release excludes raw data, paid-source exports, private query identifiers, API credentials, and full generated outputs. Public users need to provide their own compatible inputs before running the scripts.

## Hourly Engine

The hourly engine rebuilds market state at an hourly level. This gives the model a more detailed view of how price, fees, liquidity, and range conditions evolve through time.

This step matters because concentrated liquidity risk depends on the path price takes. A weekly start and end price can hide intraperiod volatility, range crossings, and periods where a position may have become poorly centered.

## Weekly Regime Metrics

The workflow then aggregates the hourly context into weekly metrics. These weekly metrics summarize the conditions that are most relevant for an LP decision, such as:

* fee opportunity;
* price-path behavior;
* volatility and directional movement;
* liquidity context;
* range churn and rebalancing pressure.

The goal is not to reduce the week to a single price move. The goal is to summarize the conditions that shaped the LP risk and fee opportunity during the decision horizon.

## Regime Classification

The regime classifier groups the current weekly setup into a market-condition label. This helps the reviewer understand whether the environment appears calm, mixed, stressed, fragile, or otherwise elevated in risk.

The regime label is not a prediction. It is a structured way to compare current conditions with similar historical states and to frame the output in language a reviewer can interpret.

## Expected FCR By Band

The model estimates expected fee coverage ratio, or FCR, across candidate LP range widths. In the current calibration, the public release describes candidate ranges such as 5%, 10%, and 20%.

FCR compares estimated fee opportunity with the modelled cost of price-path risk and rebalancing burden. Reviewing FCR by band helps answer questions such as:

* does a narrow range offer enough extra fee opportunity to justify the added churn risk;
* does a wider range reduce rebalancing pressure enough to be preferable;
* are fees too weak relative to risk across all tested bands.

FCR is a model estimate, not a guaranteed return metric.

## Transition-Risk And Fragility Overlays

Transition-risk and fragility overlays add caution flags when conditions appear unstable or are moving between regimes.

These overlays are useful because a headline FCR or regime label may not capture every warning sign. A setup can have moderate fee opportunity while still showing signs of elevated volatility, liquidity stress, range churn, or unstable market structure.

The overlays should be read as risk context. They do not prove that a loss will occur, and they do not automatically invalidate a setup. They tell the reviewer where extra caution may be warranted.

## WAIT / DEPLOY / WIDER-Style Output

The final report translates the model state into recommendation-style language:

* **WAIT** means fee coverage or market clarity does not look strong enough under the tested assumptions.
* **DEPLOY** means the tested setup appears more favorable, with fee opportunity looking stronger relative to measured risks.
* **WIDER** means a broader range may offer a better risk trade-off than a narrower range under the current conditions.

These labels are intentionally simple so the output can be reviewed quickly. They are not automated trade instructions.

## Human Review Caveat

The model is designed to support human review, not replace it.

A reviewer should consider model outputs alongside execution costs, liquidity constraints, wallet and custody controls, tax considerations, smart-contract risk, market news, operational capacity, and the user's own risk limits.

The public portfolio release demonstrates the structure of the workflow: inputs are organized, hourly state is rebuilt, weekly metrics are classified, fee coverage is estimated by range, overlays are applied, and the result is translated into clear decision-support language.
