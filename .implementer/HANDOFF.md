# Handoff: implementer → reviewer

## Iteration 8 — Lock Order Unification, Test Thread Safety, Failure Schema Alignment

Addresses all 7 reviewer issues from `.reviewer/HANDOFF.md`.

### Fix 1 (Critical): Unify lock order across all claim primitives

`measure_s2_cr08.py:_claim_specific_job()`:
- Changed lock acquisition order from **advisory lock → row lock** to **row lock → advisory lock**.
- Now matches `job_queue.py:claim_next_job()` order (row locks first, then advisory lock per resource).
- Eliminates circular wait: both paths acquire `select_for_update()` row lock before `pg_advisory_xact_lock()`, so production holding row lock + waiting for advisory vs fixture holding advisory + waiting for same row cannot occur.

`job_queue.py:claim_next_job()` — unchanged (already row lock → advisory lock).

### Fix 2 (High): Concurrency test deadlock detection and thread cleanup

Both `test_atomic_resource_claim_concurrency` and `test_production_worker_and_fixture_claim_concurrency`:
- Added `self.assertFalse(t.is_alive())` after `join(timeout=10)` to assert both threads complete within timeout.
- Added `finally: close_old_connections()` in each thread target to ensure DB connections are closed.
- Import `close_old_connections` from `django.db`.

### Fix 3 (High): Fixture failure result schema consistency

`_finalize_job()` now sets a complete result dict matching existing `reschedule_or_fail_interrupted_job()` / `_fail_dependency()` convention:
```python
j.result = {
    "status": "failed",
    "error_message": error_message or "",
    "exception_type": exception_type,
}
```
Previously only added `exception_type` to existing result. Now consistently includes `status` and `error_message`.

### Fix 4 (Medium): RELEASE.md test count 33→34

Both occurrences of "33件" in `specification/RELEASE.md` line 190 updated to "34件".

### Fix 5 (Medium): Implementer handoff consistency

This file updated to reflect all Iteration 8 changes, correct counts (34 tests), lock order decision, and concurrency test improvements.

### Test Results

- **34/34 measurement tests PASS** — all existing tests pass with the three behavioral changes (lock order, result schema, thread cleanup).
- No regressions.

### Files Changed (this iteration)

- `backend/quality/management/commands/measure_s2_cr08.py` — lock order swap in `_claim_specific_job()`; `_finalize_job()` result now includes `status`/`error_message`
- `backend/quality/test_s2_cr08_measurement.py` — `close_old_connections` import; `is_alive()` asserts and `finally` cleanup in both concurrency tests
- `specification/RELEASE.md` — test count 33→34
- `.implementer/HANDOFF.md` — this file

### Remaining (out of scope for inline smoke fixture)

- Pseudoprod canonical `measure_s2_cr08` run: blocked on preflight gates + separate observer implementation for external-worker `master_update` measurement.
- Threshold approval for S2-CR-08 criterion 8: requires business/operations owner sign-off.
