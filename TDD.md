# TDD Evidence

The executable tests live in `run_tests.py`; no test files were changed for this close-out.

## Recorded cycles

`tdd_logs/cycles.jsonl` contains the recorded RED/GREEN runs available in this workspace:

- `Tests.test_01_canonical`: RED exit 1, then GREEN exit 0.
- `Tests.test_02_delivery`: RED exit 1, then GREEN exit 0.
- `Tests.test_03_reorg`: RED exit 1 is recorded. A GREEN record was not present in the pre-existing log; the full current run is the verification for the present implementation.

Each recorded cycle includes command, exit status, and source SHA-256 values where the source file existed at recording time. The per-cycle stdout/stderr and source snapshots are kept in the corresponding `tdd_logs/` directories.

## Current verification

Run:

```bash
python3 run_tests.py
```

The command writes `report.json`. Its counts are generated from the actual `unittest` result, not hand-entered. Process interruption evidence is reported only when such evidence exists; this harness currently records none.
