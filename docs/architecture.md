# Multi-Pool Architecture v1

## 1. Purpose

The goal is to move from a hardcoded ETH/USDC 0.05% LP model toward a reusable LP risk engine that can support multiple pools and fee tiers over time.

This first version creates a pool configuration layer and loader only. It preserves the current Uniswap v3 ETH/USDC 0.05% production model logic and recommendation outputs.

## 2. Non-goals for this version

- No new data pulls.
- No production recommendation changes.
- No model threshold changes.
- No guardrail or optimiser changes.
- No Candidate 5f logic changes.
- No Deribit overlay logic changes.
- No assumption that ETH/USDC 0.05% calibration transfers directly to other pools.

## 3. Architecture Split

### Reusable components

- Price-path metrics.
- Monday-week rollup logic.
- FCR and LP outcome concepts.
- Report template structure.
- Diagnostics framework.

### Pool-specific components

- Pool address.
- Token pair.
- Fee tier.
- Price source symbol.
- Fee and liquidity inputs.
- Active liquidity reconstruction.
- Regime and FCR calibration.
- Historical weak-rate baselines.
- Expected FCR distributions.
- Deribit/options overlay availability.

## 4. Future Target Structure

```text
config/
  pools.yaml

data_clean/
  eth_usdc_005/
    hourly_engine.csv
    hourly_fees.csv
    hourly_active_liquidity.csv

outputs/
  eth_usdc_005/
    live_lp_recommendation_v1.csv
    live_lp_recommendation_v1.md
    diagnostics/

scripts/
  utils/
    pool_config.py
```

## 5. Migration Plan

### Phase 1

Create `config/pools.yaml` and a loader utility only.

### Phase 2

Make client-facing report scripts pool-aware. Low-risk first targets are hardcoded display metadata in `scripts/build_client_facing_lp_risk_snapshot_v1.py` and `scripts/build_networking_lp_snapshot_v1.py`. This should change labels only, not calculations.

### Phase 3

Make the live refresh workflow accept a `pool_id` argument while defaulting to `eth_usdc_005`.

### Phase 4

Separate pool-specific outputs into `outputs/{pool_id}/`.

### Phase 5

Only after new pool data exists, calibrate additional pools separately.

## 6. Current Status

The canonical active pool is `eth_usdc_005`, defined in `config/pools.yaml`.

The current production engine remains the existing ETH/USDC 0.05% pipeline. This architecture layer does not pull data, spend external data credits, or change optimiser logic, thresholds, guardrails, Candidate 5f logic, Deribit overlay logic, or recommendation calculations.

## 7. Phase 2 Completed: Report Metadata Integration

The first report metadata integration has been completed for:

- `scripts/build_lp_risk_snapshot_v1.py`
- `scripts/build_client_facing_lp_risk_snapshot_v1.py`
- `scripts/build_networking_lp_snapshot_v1.py`

These scripts now load pool metadata from `config/pools.yaml`, defaulting to `eth_usdc_005`. They also accept an optional `--pool-id` argument while preserving existing no-argument behaviour.

Only display/report metadata was changed: pool name, pair label, chain, protocol, pool address, token symbols, fee tier, quote asset, price symbol, and configured bands.

No recommendation logic, optimiser logic, Candidate 5f logic, Deribit overlay logic, thresholds, guardrails, expected FCR calculations, weak-rate calculations, data paths, or output folders were changed. Core model scripts remain hardcoded to the current ETH/USDC 0.05% production pool until later migration phases.

## 8. Phase 3 Completed: Live Workflow Shell Accepts Pool ID

`scripts/run_live_refresh_workflow.py` now accepts an optional `--pool-id` argument. The default remains `eth_usdc_005`.

At workflow start, the selected pool metadata is loaded from `config/pools.yaml` and printed for operator visibility:

- pool ID
- display name
- pool address
- fee tier
- price source symbol

The workflow also supports `--dry-run`, which validates the pool config and prints the steps that would run without executing data pulls, external data calls, model scripts, or report scripts.

For this phase, `pool_id` is passed only to safe report scripts that already support it:

- `scripts/build_lp_risk_snapshot_v1.py`
- `scripts/build_client_facing_lp_risk_snapshot_v1.py`
- `scripts/build_networking_lp_snapshot_v1.py`

The current workflow does not yet call those report scripts directly, so no existing live refresh step receives `--pool-id` today. Core data, model, recommendation, Candidate 5f, Deribit overlay, optimiser, threshold, guardrail, expected FCR, weak-rate, data path, and output-folder logic remains unchanged.

## 9. Phase 4 Completed: Optional Post-Refresh Report Generation

`scripts/run_live_refresh_workflow.py` now accepts an optional `--build-reports` flag.

When enabled, the workflow appends these pool-aware report snapshot scripts as post-refresh reporting steps:

- `scripts/build_lp_risk_snapshot_v1.py`
- `scripts/build_client_facing_lp_risk_snapshot_v1.py`
- `scripts/build_networking_lp_snapshot_v1.py`

The selected `--pool-id` is passed to all three report scripts. The default remains `eth_usdc_005`.

Dry-run mode shows the post-refresh report steps and commands without executing them, so operators can validate the workflow shell without pulling live data, spending external data credits, running model scripts, or regenerating files.

This phase is reporting/productisation only. No core data, model, recommendation, Candidate 5f, Deribit overlay, optimiser, threshold, guardrail, expected FCR, weak-rate, data path, output-folder, or calibration logic was changed.

## 10. Phase 5 Completed: Reports-Only Workflow Mode

`scripts/run_live_refresh_workflow.py` now accepts an optional `--reports-only` flag.

Reports-only mode rebuilds the report bundle from existing local outputs and skips the live refresh/model pipeline entirely. It does not run live price pulls, Deribit pulls, external data pulls, model rebuild scripts, freshness audit, or core recommendation pipeline steps.

The selected `--pool-id` is passed to all three report scripts:

- `scripts/build_lp_risk_snapshot_v1.py`
- `scripts/build_client_facing_lp_risk_snapshot_v1.py`
- `scripts/build_networking_lp_snapshot_v1.py`

Dry-run mode previews the report commands without executing them or regenerating files.

`--build-reports` and `--reports-only` are mutually exclusive. `--build-reports` means run the normal full workflow and then append report generation. `--reports-only` means skip the normal workflow and run only report generation.

This phase is workflow/reporting/productisation only. No core data, model, recommendation, Candidate 5f, Deribit overlay, optimiser, threshold, guardrail, expected FCR, weak-rate, data path, output-folder, or calibration logic was changed.


## Public Portfolio Note

This public copy omits private query identifiers, API credentials, paid-source exports, raw CSVs, and full generated outputs. It documents architecture and packaging only; it is not investment advice and is not presented as a clean out-of-sample backtest.

