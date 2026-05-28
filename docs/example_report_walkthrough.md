# Example Report Walkthrough

This walkthrough explains how to read the public sample report in `samples/reports/sample_client_report.md`. It is written for reviewers who want to understand what the LP risk engine is communicating without needing access to private data, live queries, or full production outputs.

The sample report is illustrative. Its numbers and labels should be read as an example of the reporting format, not as live market guidance.

## What The Model Is Assessing

The engine is designed to assess whether expected LP fee opportunity appears sufficient relative to the risks of providing concentrated liquidity over the model horizon.

For the current portfolio release, the calibration is focused on Uniswap v3 ETH/USDC 0.05% and a weekly decision horizon. The model compares fee opportunity against risks that matter for concentrated liquidity providers, including:

* how price moves through the week;
* whether the LP range is likely to become poorly positioned;
* how much rebalancing burden the position may create;
* whether current market conditions resemble historically fragile or unstable regimes.

The report does not attempt to guarantee profitability. It is intended to make the fee-versus-risk trade-off easier to review before making an LP decision.

## Fee Coverage Ratio

Fee coverage ratio, or FCR, is the model's shorthand for comparing estimated LP fees with modelled risk costs.

In plain English, FCR asks:

> Does the expected fee opportunity look large enough to compensate for price-path risk and rebalancing burden?

A stronger FCR means fees appear more likely to cover the risks the model is measuring. A weaker FCR means the fee opportunity may not be large enough relative to the expected cost, churn, or operational burden of keeping the position in range.

FCR should not be read as a guaranteed return metric. It depends on model assumptions, historical calibration, available data, and the selected LP range.

## Regime Label

The regime label summarizes the model's view of current market conditions. In the sample report, the example regime is:

* `mixed / elevated path risk`

This means the current setup is not cleanly favorable. Some conditions may be acceptable, but the price-path environment looks riskier than normal. For an LP, that matters because a position can earn fees and still suffer from adverse movement, range exits, or repeated repositioning.

Regime labels are not predictions. They are a way to group current conditions so a human reviewer can compare the present setup with similar historical states.

## Recommendation Framing

The engine uses recommendation-style language such as WAIT, DEPLOY, or WIDER to make the output easier to interpret. These labels should be read as decision-support signals, not automatic trading instructions.

* **WAIT** means the model does not see enough fee coverage or market clarity to justify deployment under the tested assumptions. It may indicate elevated path risk, weak FCR, high rebalancing burden, or a fragile transition setup.
* **DEPLOY** means the tested setup appears more favorable: fee opportunity looks stronger relative to measured risks. A DEPLOY-style signal still requires human review, execution checks, and risk limits.
* **WIDER** means the model may prefer a broader LP range because narrower ranges look too exposed to price movement, range churn, or rebalancing costs. This is not the same as saying a wider range is always better; it means the model sees a better risk trade-off for the tested conditions.

In the sample report, the illustrative stance is to wait for stronger fee coverage or clearer price-path conditions. That is a conservative interpretation: the model is flagging that the current fee opportunity may not adequately compensate for the measured risks.

## Why Price-Path Risk Matters

Concentrated liquidity outcomes depend on the path price takes, not just the start and end price.

Two weeks can finish at similar prices but create very different LP experiences. A smooth week inside range may generate fees with manageable repositioning. A volatile week with repeated range crossings may create more churn, adverse inventory shifts, and operational burden even if the final weekly price does not look extreme.

That is why the report emphasizes price-path risk. It is trying to capture whether the journey through the week is likely to be hostile for a concentrated LP position.

## Why Rebalancing Risk Matters

Concentrated LP positions often need active management. If price moves away from the selected range, the LP may need to rebalance, widen exposure, wait, or accept a different inventory profile.

Rebalancing risk captures the cost and burden of that management. It can include:

* the likelihood of the position becoming poorly centered;
* repeated range changes;
* transaction costs or execution friction;
* time spent monitoring and managing the position;
* the possibility of moving liquidity at unfavorable moments.

The sample report describes the rebalancing burden as elevated. That suggests the model sees a higher risk that the LP setup may require active intervention or may become unattractive without it.

## Transition-Risk And Fragility Overlays

Transition-risk and fragility overlays are additional warnings layered on top of the main fee coverage and regime view.

They are meant to identify cases where the market may be moving from one state into another, or where conditions look less stable than the main recommendation alone might suggest. For example, a setup may have moderate fee opportunity but still deserve caution if volatility, liquidity, range churn, or other context signals point to a fragile environment.

These overlays should be interpreted as risk flags. They do not prove that losses will occur, and they do not override human judgment. They are designed to stop the reader from treating a single headline metric as the whole story.

## Limitations

The public sample report is intentionally limited. It omits raw data, private query details, live timestamps, and full production output tables.

Important limitations include:

* the current calibration is specific to Uniswap v3 ETH/USDC 0.05%;
* the public sample is illustrative and should not be used as live market guidance;
* historical diagnostics in this release should not be described as a clean out-of-sample backtest;
* FCR, regime labels, and recommendations depend on model assumptions and available input data;
* new pools, fee tiers, or market conditions would require separate calibration and validation;
* the report does not account for every execution, tax, custody, smart-contract, or operational risk a real LP may face.

## Decision Support, Not Investment Advice

The report is intended to support a human decision process. It helps organize the question: does the fee opportunity appear strong enough for the measured price-path and rebalancing risks?

It should not be treated as investment advice, a guarantee of profitability, or an instruction to deploy capital. A recruiter, analyst, researcher, or liquidity manager should read it as evidence of a structured risk workflow: data is organized, market state is classified, fee coverage is estimated, and the result is translated into clear review language.

