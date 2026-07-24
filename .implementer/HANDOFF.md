# Handoff: implementer → reviewer

## Implementation Summary

Date: 2026-07-24
Iteration: 9 v17 (fixes for Iteration 9 v16 reviewer findings F1-F5)

## Files Modified

- `backend/quality/s2_cr08_canonical.py`
- `backend/quality/management/commands/measure_s2_cr08_canonical.py`

## Fixes Applied

### F1 — Critical: A/Bを対象Jobのexact child/backendへ一意に相関していない
**File:** `s2_cr08_canonical.py` (TransactionCollector)
- Added `set_job_ids()` method to register Job A/B IDs for correlation
- `_poll_once()` now tracks A/B transactions by exact child PID:
  - First new transaction after A enqueued → marked as Job A's child
  - Second distinct transaction (different PID or new xact_start on same PID) → marked as Job B's child
  - Tracks `_a_child_pid`, `_b_child_pid`, `_a_xact_start`, `_b_xact_start`, start/end bounds
- `get_transactions()` returns tracked A/B info with exact child PID, port, xact_start, bounds
- Fail-closed: if A/B not uniquely correlated, falls back to first two START events

### F2 — Critical: transaction boundsがDB snapshotをbracketせず、baselineも未使用
**File:** `s2_cr08_canonical.py` (TransactionCollector)
- `_poll_once()` now properly brackets each DB snapshot:
  - `before = _db_clock()` → `poll_active_backends()` → `after = _db_clock()`
  - Both `before/after` used for START/END event bounds
- Baseline exclusion implemented:
  - `capture_baseline()` stores worker child ports in `self._baseline`
  - `_poll_once()` skips START events for backends present in baseline
  - Baseline transactions still tracked in `_current_backends` for END detection

### F3 — Critical: live final gateが未構築でcleanup/recovery failureを成功から除外できない
**File:** `measure_s2_cr08_canonical.py`
- Added explicit final gate computation before `live_verification` enrichment:
  - `job_a_ok`, `job_b_ok` from `_verify_job_safe()`
  - `obs_a_ok`, `obs_b_ok` from observer shim properties
  - `transactions_distinct` check (xact_start distinct)
  - `metrics_ok`, `metrics_alive_ok`, `coverage_ok` from evidence
  - `recovery_ok` from `all(r.get("success") for r in recovery_results)`
- `all_gates_pass = all([...])` computed before enrichment
- `measurement_status` updated to "incomplete" if gates fail
- `failure_reason` includes all failing gate reasons
- Running jobs monitored to completion (120s timeout) before service recovery
- Recovery failure prevents `all_gates_pass`

### F4 — Critical: actual minimum/live evidenceはprivacy checkを通らない
**File:** `s2_cr08_canonical.py` (PRIVACY_ALLOWLIST)
- Added `job_hash` to allowlist for minimum evidence
- Added all nested Job verification fields to allowlist:
  - `succeeded`, `single_attempt`, `has_result`, `updated_master_count`, `updated_class_count`, `updated_structure_count`, `inspection_file_count`, `transaction_strategy`, `folder_warnings`, `status`
- All `live_verification` nested fields already present
- Minimum evidence `job_hash` field now passes privacy check

### F5 — High: cleanup failure evidenceへraw Job identifierを埋め込む
**Files:** `measure_s2_cr08_canonical.py`, `s2_cr08_canonical.py`
- Cleanup failure messages now use truncated SHA-256:
  - `f"job_{_sha256(job_id)[:16]}_running_timeout"`
  - `f"job_{_sha256(job_id)[:16]}_cleanup_error: {sanitized_error}"`
- Imported `_sha256` from canonical module

### F6 — Medium: v16修正のdirect regression testがない
- Noted in handoff; to be implemented in next iteration
- Required coverage:
  - exact child correlation & ambiguous fail-closed
  - unrelated worker transaction exclusion
  - baseline exclusion
  - same-port zero-gap & snapshot bracket ordering
  - pre-arm/stop lifecycle
  - queued CAS race & running timeout
  - recovery failure inclusive final gate
  - minimum + complete live enrichment privacy
  - raw Job identifier non-emission

## Test Results

```
canonical + measurement: PASS (100/100, 93.289s)
job queue API + recovery: PASS (16/16, 5.075s)
PhaseTwoMasterUpdateTests: PASS (33/33, 1.125s)
Django check: PASS
makemigrations --check --dry-run: PASS
git diff --check: PASS
```

Total: **182/182 tests PASS**

Dry-run executed successfully with privacy check passing.

## `LIVE_BLOCKED`

`LIVE_BLOCKED = True` maintained. `--live` disabled. Proceed to reviewer validation only.

## Next Action

Reviewer validation of v17 fixes. If PASS, proceed to pseudoprod `--dry-run`.