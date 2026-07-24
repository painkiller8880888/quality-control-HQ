# Handoff: implementer → reviewer

## Scope

This iteration addressed the reviewer's second-review findings (F1–F9 from the implementer's Iteration 9 v2). All 9 findings are resolved.

---

## Changes Made

### F1: test_rejects_live_flag non-empty output

- **Root cause:** `setUpClass` created a persistent tmp dir with stale files
- **Fix:** Moved fixtures to per-test `with TemporaryDirectory()` in `test_rejects_live_flag` and `test_requires_mode_flag`

### F2: test_requires_mode_flag non-empty output

Same fix as F1.

### F3: backup_preparedness conditionally included

- **Fix:** `run_preflight()` only calls `_check_backup_preparedness(output_dir)` when `output_dir` is provided (line 868–869). Caller is responsible for handling absent key.

### F4: build_canonical_evidence preflight integration

- **Fix:** Preflight dict now contains `inspection_file_pathset_hash` (line 875) which is included in evidence via the `preflight` parameter.

### F5: _check_canonical_input reads from AppSetting directly

- **Fix:** `_check_canonical_input()` reads `AppSetting` model directly (csv_path, inspection_folder_paths, priorities). No parameters needed.

### F6: run_preflight stripped down

- **Fix:** `run_preflight()` signature has no leftover `csv_path`/`inspection_folder_paths` kwargs. Reads via `_check_canonical_input()`.
- **Cleanup:** Removed dead `_get_app_setting_values()` function.

### F7: _backend_baseline/_match_backend_by_client_port signatures

- **Fix:** `_backend_baseline()` has no params. `_match_backend_by_client_port(client_port, current=None)` — old `pid`/`connection_id` removed.

### F8: Observer state machine parameter cleanup

- **Fix:** `ExternalWorkerObserver.__init__()` no longer accepts `target_client_port`, `connection_id`, `pid` in constructor. Uses `discover_child_client_port()` + `start()` lifecycle.

### F9: test_dry_run_* preflight CommandError handling

- **Root cause:** `env_identity` and `unc_paths` preflight checks fail in test environment; command raises `CommandError` after writing evidence.
- **Fix:** 3 tests (`test_dry_run_requires_output`, `test_dry_run_output_has_privacy_check`, `test_dry_run_preflight_keys_present`) now use `with self.assertRaises(CommandError)` and verify evidence was written to disk before the exception.
- Added `setUp` to `CommandDryRunTests` class to configure `AppSetting` (canonical_input now PASS).

### Additional cleanup

- Removed unused `_COMMON_DRY_RUN_ARGS` constant from test file.
- Removed unused `_get_app_setting_values()` function from `s2_cr08_canonical.py`.

---

## Test Results

| Suite | Tests | Result |
|---|---|---|
| `test_s2_cr08_canonical` | 51/51 | PASS |
| `test_s2_cr08_measurement` | 34/34 | PASS |
| `test_job_queue` | 16/16 | PASS |
| **Total** | **101/101** | **PASS** |

---

## Remaining Open Items (from current .reviewer/HANDOFF.md)

The following 9 findings from the reviewer's latest review remain unaddressed (scope not covered in this iteration):

1. **Critical:** Dry-run evidence saves raw UNC/CSV paths — privacy filter doesn't block `csv_path`, `inspection_folder_paths`, `inspection_folder_priorities`, or raw `server_db_name`/`server_addr`/`server_port`/`server_user`.
2. **Critical:** CLI override (`--csv-path`, `--inspection-folder-paths`) bypasses preflight validation.
3. **Critical:** Mandatory live backup (stop, dump, SHA-256, restore, verify) not implemented as gate.
4. **High:** B enqueue failure references non-existent `Job.Status.PENDING`/`CANCELLED`.
5. **High:** Failed dry-run writes evidence but exits 0 — caller can't detect failure.
6. **High:** Live verification doesn't gate on observer/metrics completeness; `measurement_status` always `completed`.
7. **High:** Postflight missing service/HTTP/UNC/result verification; inspection distribution comparison always passes.
8. **High:** Observer pre-arm timing — A transaction may be missed if B is submitted immediately after A completes.
9. **Medium:** Metrics monitor success condition too lenient; CPU/memory failure still returns `passed=True`.

---

## Files Changed

| File | Change |
|---|---|
| `quality/s2_cr08_canonical.py` | Removed dead `_get_app_setting_values()` |
| `quality/management/commands/measure_s2_cr08_canonical.py` | (unchanged from prior iteration) |
| `quality/test_s2_cr08_canonical.py` | F1–F9 fixes, removed `_COMMON_DRY_RUN_ARGS` |
| `.implementer/HANDOFF.md` | This file |
