# Limitations

This project is a research/product prototype and should be interpreted as decision-support tooling, not investment advice or an automated trading system.

Current limitations include:

* The current calibration is specific to Uniswap v3 ETH/USDC 0.05%.
* Historical diagnostics are in-sample and should not be described as a clean out-of-sample backtest.
* The public release omits raw data, private data, paid-source exports, and live query infrastructure.
* New pools require separate data validation, liquidity reconstruction, regime calibration, threshold review, and reporting checks.
* Live production use would require stronger monitoring, schema validation, failure handling, reproducibility checks, and operational controls.
* FCR estimates, regime labels, and report outputs are decision-support features. They should be reviewed by a human and should not be treated as automatic trade instructions.

The current release is intended to demonstrate the modelling approach, architecture, reporting workflow, and validation discipline behind the project rather than provide a plug-and-play LP deployment system.
