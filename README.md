# A-share sealed batch data and backtest runner

Public, strategy-blind compute plane for the simplified A-share trading system.

The repository receives an AES-256-GCM sealed request, performs bounded public
data acquisition or deterministic daily order/account replay inside an
ephemeral GitHub-hosted runner, and uploads only sealed results. Strategy
selection, parameters, rankings, account identity and acceptance gates remain
in the private repository.

Supported generic tasks:

- `daily_market_snapshot_v1`: full-market daily OHLC, trading status, limits
  and PIT market capitalization in a bounded date window;
- `pit_financial_events_v1`: publication-dated quarterly financial events;
- `daily_order_replay_v1`: dated order-intent and account replay.

JSON workloads and results are deterministically gzip-compressed before sealing.
Large historical runs must be split into digest-bound batches by the private
control plane so workflow inputs remain within the dispatch safety limit.
The provider interface is pinned to `zzshare==0.4.9`; anonymous use is allowed,
while an optional `ZZSHARE_TOKEN` repository secret may raise provider limits.

## Security boundary

- Manual `workflow_dispatch` only; owner and `main` only.
- Read-only workflow token and immutable action pins.
- Plaintext exists only in runner memory/ephemeral disk.
- Logs contain job id, group, case count and status only.
- Result artifacts contain ciphertext only and expire after one day.
- The runner is generic: it consumes dated order intents and market bars, not
  strategy source.
- Provider success is not a strategy or data-admission pass; all PIT, coverage
  and acceptance gates remain private.
- A retryable provider result makes its matrix job fail after writing the
  ciphertext result, so the failed group is visible and can be resumed.

## Required secret

`SEALED_JOB_KEY_B64`: base64 for exactly 32 random bytes. The same key must be
held by the private control plane. Never paste it into an issue, workflow input,
log or repository file.

## Local verification

```bash
python -m pip install -r requirements.txt
python -m unittest discover -s tests -v
```
