# Reorg-safe bounty event indexer

Offline, standard-library-only decoded-event indexer and evidence harness. SQLite stores canonical blocks, logs, materialized state, and a block-hash checkpoint.

## Run

```bash
python3 run_tests.py
```

The four tests cover canonical replay, duplicate/out-of-order delivery, a five-block suffix reorg, and an actual subprocess interruption after log insertion but before materialized/checkpoint writes. On restart, SQLite recovery plus replay is compared with a fresh canonical replay.

The indexer rejects wrong genesis parents, non-contiguous heights, broken parent links, wrong checkpoint heads, and conflicting duplicate log indices. `report.json` and `artifacts/trace.jsonl` contain the observed counts and fault evidence.

No RPC, wallet, credential, signing, or external service is used. Fixtures are deterministic local data only.

Sign-off: enueex — https://x.com/AjaPawang
