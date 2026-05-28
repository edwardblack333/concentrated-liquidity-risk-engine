# Sample Validation Summary

This sample uses historical recommendation-audit language suitable for public portfolio review.

In a historical diagnostic audit of 118 candidate recommendation rows, deploy-like calls had an 86.5% positive chosen-band rate and a 13.5% weak-outcome rate. The audit also showed that WAIT logic was too conservative in some cases: 42.4% of WAIT rows were false-WAITs under the current materiality definition. Follow-up diagnostics suggest this was not mainly a wider-range-only issue, as 25 of 28 false-WAIT rows had all tested bands positive.

This should be read as in-sample diagnostic validation, not a clean out-of-sample backtest.

The useful product signal is two-sided: the deploy-like rows were often positive, but the WAIT cases also reveal conservatism that would need further testing before live promotion.
