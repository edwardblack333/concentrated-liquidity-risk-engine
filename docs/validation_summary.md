# Validation Summary

This is a historical recommendation audit / in-sample diagnostic validation, not a clean out-of-sample backtest.

In a historical diagnostic audit of 118 candidate recommendation rows, deploy-like calls had an 86.5% positive chosen-band rate and a 13.5% weak-outcome rate. The audit also showed that WAIT logic was too conservative in some cases: 42.4% of WAIT rows were false-WAITs under the current materiality definition. Follow-up diagnostics suggest this was not mainly a wider-range-only issue, as 25 of 28 false-WAIT rows had all tested bands positive.

These results are useful for product and model diagnostics, but they do not establish guaranteed profitability, live production readiness, or portability across all pools.

The main takeaway is not that the model is finished. It is that the audit identifies both strengths and failure modes: deploy-like calls were often associated with positive chosen-band outcomes, while the WAIT logic appears too conservative in a meaningful subset of historical cases.
