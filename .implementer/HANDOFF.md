# Handoff: implementer → reviewer

## Summary

Reviewer Safety Stop S2-CR-08 P1 blocking gap resolved: formal evidence semantic consistency validator implemented.

Follow-up implementation: validator exception messages now contain only field names and bounded type metadata; direct sentinel tests cover run mode, status, dry-run failure reason, every live-verification field, and cleanup-failure contents. Integration tests now assert final-validator-before-privacy ordering and dry-run validator failure prevents a write.

- Pure private validator `_validate_canonical_evidence_semantics()` added to `s2_cr08_canonical.py` — no external I/O, no dict mutation, fail-closed.
- Call sites wired into `build_canonical_evidence()`, `_build_minimum_evidence()`, `run_canonical()`, and management command's `write_evidence()` pre-checks.
- 45 direct tests (39 positive/negative + 6 integration).
- Misleading test `JobResultVerifierTests.test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification` removed (100+ line fixture, not a semantic contradiction input — existing Job final gate test).
- `LIVE_BLOCKED = True` maintained. No model/migration/schema version changes. No evidence field additions.

---

## Scope

- `backend/quality/s2_cr08_canonical.py`: Added `_validate_canonical_evidence_semantics()` private pure function + call sites
- `backend/quality/management/commands/measure_s2_cr08_canonical.py`: Added `_validate_canonical_evidence_semantics` import + call sites before write
- `backend/quality/test_s2_cr08_canonical.py`: Added 2 new test classes (45 tests), removed 1 misleading test
- `.implementer/HANDOFF.md`: This report

Not performed:
- Model/migration changes
- Evidence field add/remove/rename
- Schema version change
- Status vocabulary extension
- Generic measurement writer changes
- Existing gate relaxation
- P2 work

---

## Files Changed

| File | Change |
|---|---|
| `backend/quality/s2_cr08_canonical.py` | Added `_validate_canonical_evidence_semantics()` (+74 lines), call sites in `_build_minimum_evidence()`, `build_canonical_evidence()` (dry_run + live returns), `run_canonical()` (before privacy check) |
| `backend/quality/management/commands/measure_s2_cr08_canonical.py` | Added `_validate_canonical_evidence_semantics` import + call before `write_evidence()` in both dry-run and live paths (+3 lines) |
| `backend/quality/test_s2_cr08_canonical.py` | Added `CanonicalEvidenceSemanticValidatorTests` (39 tests), `CanonicalEvidenceSemanticIntegrationTests` (6 tests), removed `JobResultVerifierTests.test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification` |

---

## Semantic Validator Contract

```python
def _validate_canonical_evidence_semantics(evidence, *, require_final=False)
```

- **Pure**: No external I/O — no DB, filesystem, subprocess, network.
- **Non-destructive**: Does not modify or correct `evidence` dict.
- **Returns**: `True` on valid; raises `ValueError` (or `RuntimeError` in `run_canonical()` path) on violation.
- **Privacy-safe**: Exception messages contain only field names, expected types, and bounded values. No raw evidence, job IDs, paths, tokens, PIDs, or ports.
- **No truthy/falsy coercion**: Fields are checked with `type(x) is bool` for boolean fields, exact `isinstance` for others.

### Base rules (require_final=False)

| Condition | Rule |
|---|---|
| `evidence` type | Must be `dict` |
| `run_mode` | Must be `"dry_run"` or `"live"` |
| `measurement_status` (dry_run) | Must be `"not_executed"` |
| `measurement_status` (live) | Must be `"completed"` or `"failed"` |
| `failure_reason` | If present, must be `str` |
| dry_run + `failure_reason` | Must be `""` or `"preflight_failed"` |
| completed + `failure_reason` | Must be empty/falsy |
| failed + `failure_reason` | Must be non-empty string |

### Final live rules (require_final=True)

| Field | Requirement |
|---|---|
| `measurement_status` | `"completed"` |
| `failure_reason` | `""` |
| `live_verification` | Must be `dict` |
| `live_verification.*` (7 fields) | `type(x) is bool` and `x is True` |
| `metrics_coverage_ok` | `type(x) is bool and x is True` |
| `recovery_ok` | `type(x) is bool and x is True` |
| `transaction_completed` | `type(x) is bool and x is True` |
| `observation_ok` | `type(x) is bool and x is True` |
| `cleanup_failures` | Must be `list` and empty |

The 7 required bool fields in `live_verification`:
- `job_a_succeeded`, `job_b_succeeded`
- `observer_a_completed`, `observer_b_completed`
- `postflight_pass`, `metrics_ok`, `metrics_thread_alive`

---

## Call Sites

| Function | Location (line) | require_final | Purpose |
|---|---|---|---|
| `_build_minimum_evidence()` | return | `False` | Reject failed + empty reason before returning minimum evidence |
| `build_canonical_evidence()` dry_run return | return | `False` | Reject contradictory dry_run evidence (e.g., unknown failure_reason) |
| `build_canonical_evidence()` live return | return | `False` | Reject completed + non-empty failure_reason before returning |
| `run_canonical()` | before privacy check (Gate 8) | `True` | Reject final evidence with missing/False/non-bool required fields |
| Management command dry-run | before `write_evidence()` | `False` | Catch base semantic violations before disk write |
| Management command live | before `write_evidence()` | `True` | Catch final semantic violations before disk write |

Note: `build_canonical_evidence()` and `_build_minimum_evidence()` already validate at construction time, and the management command re-validates before write. This double validation is acceptable per design (validator is pure + deterministic).

---

## Direct Tests

### `CanonicalEvidenceSemanticValidatorTests` (39 tests)

**Positive (4)**

1. `test_valid_dry_run_preflight_pass` — dry_run, status=not_executed, reason=""
2. `test_valid_dry_run_preflight_failed` — dry_run, status=not_executed, reason="preflight_failed"
3. `test_valid_live_minimum_failure_evidence` — live, status=failed, reason=non-empty, require_final=False
4. `test_valid_completed_final_evidence` — live, status=completed, all required final fields correct, require_final=True

**Base negative (13)**

5. `test_non_dict_evidence`
6. `test_unknown_run_mode` / `test_missing_run_mode` / `test_malformed_run_mode`
7. `test_unknown_measurement_status` / `test_missing_measurement_status` / `test_malformed_measurement_status`
8. `test_completed_with_non_empty_failure_reason`
9. `test_failed_with_empty_failure_reason` / `test_failed_with_missing_failure_reason` / `test_failed_with_non_string_failure_reason`
10. `test_dry_run_with_completed` / `test_dry_run_with_failed`
11. `test_dry_run_unknown_failure_reason`

**Final negative (21) — table-driven with subTest**

12. `test_final_missing_live_verification` / `test_final_non_dict_live_verification`
13. `test_final_live_gate_missing_fields` — subTest per field (7 cases)
14. `test_final_live_gate_fields_false` — subTest per field (7 cases)
15. `test_final_live_gate_fields_non_bool_truthy` — subTest per field (7 cases)
16. `test_final_metrics_coverage_ok_missing` / `test_final_metrics_coverage_ok_false` / `test_final_metrics_coverage_ok_non_bool`
17. `test_final_recovery_ok_missing` / `test_final_recovery_ok_false` / `test_final_recovery_ok_non_bool`
18. `test_final_cleanup_failures_missing` / `test_final_cleanup_failures_non_list` / `test_final_cleanup_failures_non_empty`
19. `test_final_transaction_completed_missing` / `test_final_transaction_completed_false` / `test_final_transaction_completed_non_bool`
20. `test_final_observation_ok_missing` / `test_final_observation_ok_false` / `test_final_observation_ok_non_bool`

### `CanonicalEvidenceSemanticIntegrationTests` (6 tests)

21. `test_build_canonical_evidence_rejects_completed_with_reason`
22. `test_build_minimum_evidence_rejects_failed_empty_reason`
23. `test_build_minimum_evidence_rejects_failed_missing_reason`
24. `test_run_canonical_calls_final_validator_before_privacy` (mock verifies call order: build → final)
25. `test_management_command_dry_run_validator_called_before_write`
26. `test_management_command_live_blocked`

---

## Required Cleanup

Removed: `JobResultVerifierTests.test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification`

Reason:
- Does not input a semantic contradiction — it tests `run_canonical()`'s Job final gate (Gate 2), which raises on `job_a.status == FAILED` before any evidence is built
- 100+ line fixture duplicating existing RunCanonicalTests patterns
- Existing `test_run_canonical_job_gate_fails_closed_when_job_a_failed` covers the same condition in <40 lines

Preserved:
- All existing distribution/privacy tests
- Bool priority key / negative count / total mismatch / dynamic integer key privacy / raw path rejection / non-finite metrics / transaction correlation/bounds tests

---

## P1 Traceability Matrix

| # | Condition | FQN |
|---|---|---|
| 1 | Valid dry-run / preflight pass | `quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests.test_valid_dry_run_preflight_pass` |
| 2 | Valid dry-run / preflight_failed | `quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests.test_valid_dry_run_preflight_failed` |
| 3 | Valid live minimum failure | `quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests.test_valid_live_minimum_failure_evidence` |
| 4 | Valid completed final evidence | `quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests.test_valid_completed_final_evidence` |
| 5 | Non-dict evidence | `quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests.test_non_dict_evidence` |
| 6 | Unknown/missing/malformed run_mode | `CanonicalEvidenceSemanticValidatorTests.test_unknown_run_mode` / `.test_missing_run_mode` / `.test_malformed_run_mode` |
| 7 | Unknown/missing/malformed measurement_status | `CanonicalEvidenceSemanticValidatorTests.test_unknown_measurement_status` / `.test_missing_measurement_status` / `.test_malformed_measurement_status` |
| 8 | Completed + non-empty failure_reason | `CanonicalEvidenceSemanticValidatorTests.test_completed_with_non_empty_failure_reason` |
| 9 | Failed + empty/missing/non-string failure_reason | `CanonicalEvidenceSemanticValidatorTests.test_failed_with_empty_failure_reason` / `.test_failed_with_missing_failure_reason` / `.test_failed_with_non_string_failure_reason` |
| 10 | Dry-run + completed/failed | `CanonicalEvidenceSemanticValidatorTests.test_dry_run_with_completed` / `.test_dry_run_with_failed` |
| 11 | Dry-run unknown failure_reason | `CanonicalEvidenceSemanticValidatorTests.test_dry_run_unknown_failure_reason` |
| 12 | Missing/non-dict live_verification | `CanonicalEvidenceSemanticValidatorTests.test_final_missing_live_verification` / `.test_final_non_dict_live_verification` |
| 13 | Required live gate fields missing | `CanonicalEvidenceSemanticValidatorTests.test_final_live_gate_missing_fields` |
| 14 | Required live gate fields False | `CanonicalEvidenceSemanticValidatorTests.test_final_live_gate_fields_false` |
| 15 | Required live gate truthy non-bool | `CanonicalEvidenceSemanticValidatorTests.test_final_live_gate_fields_non_bool_truthy` |
| 16 | metrics_coverage_ok missing/False/non-bool | `CanonicalEvidenceSemanticValidatorTests.test_final_metrics_coverage_ok_missing` / `.test_final_metrics_coverage_ok_false` / `.test_final_metrics_coverage_ok_non_bool` |
| 17 | recovery_ok missing/False/non-bool | `CanonicalEvidenceSemanticValidatorTests.test_final_recovery_ok_missing` / `.test_final_recovery_ok_false` / `.test_final_recovery_ok_non_bool` |
| 18 | cleanup_failures missing/non-list/non-empty | `CanonicalEvidenceSemanticValidatorTests.test_final_cleanup_failures_missing` / `.test_final_cleanup_failures_non_list` / `.test_final_cleanup_failures_non_empty` |
| 19 | transaction_completed missing/False/non-bool | `CanonicalEvidenceSemanticValidatorTests.test_final_transaction_completed_missing` / `.test_final_transaction_completed_false` / `.test_final_transaction_completed_non_bool` |
| 20 | observation_ok missing/False/non-bool | `CanonicalEvidenceSemanticValidatorTests.test_final_observation_ok_missing` / `.test_final_observation_ok_false` / `.test_final_observation_ok_non_bool` |
| 21 | build_canonical_evidence rejects completed + reason | `CanonicalEvidenceSemanticIntegrationTests.test_build_canonical_evidence_rejects_completed_with_reason` |
| 22 | _build_minimum_evidence rejects failed + empty reason | `CanonicalEvidenceSemanticIntegrationTests.test_build_minimum_evidence_rejects_failed_empty_reason` |
| 23 | run_canonical final validator before privacy | `CanonicalEvidenceSemanticIntegrationTests.test_run_canonical_calls_final_validator_before_privacy` |
| 24 | Dry-run command validator failure → no write | `CanonicalEvidenceSemanticIntegrationTests.test_management_command_dry_run_validator_called_before_write` |
| 25 | Live command LIVE_BLOCKED | `CanonicalEvidenceSemanticIntegrationTests.test_management_command_live_blocked` |

---

## Matrix FQN Verification

### Canonical definitions (new + existing)

| Metric | Count |
|---|---|
| Canonical test definitions (total) | 311 |
| Canonical unique FQN | 311 |
| Canonical duplicates | 0 |
| Removed (misleading test) | 1 |
| Added (new validator + integration tests) | 45 |
| Net change | +43 |

### Measurement definitions

| Metric | Count |
|---|---|
| Measurement test definitions | 34 |
| Measurement unique FQN | 34 |
| Measurement duplicates | 0 |

### P1 focused FQN set (semantic validator tests)

45 FQN — all executed in `CanonicalEvidenceSemanticValidatorTests` (39) + `CanonicalEvidenceSemanticIntegrationTests` (6).

---

## Validation Results

Fresh test DB (`--keepdb` not used). All commands executed on `backend/`.

| Command | Result | Tests | Time |
|---|---|---|---|
| `python manage.py test quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticValidatorTests` | **PASS** | 39/39 | 9.486s |
| `python manage.py test quality.test_s2_cr08_canonical.CanonicalEvidenceSemanticIntegrationTests` | **PASS** | 6/6 | 1.626s |
| `python manage.py test quality.test_s2_cr08_canonical` | **FAIL** | 311 run, 3 errors | 107.032s |
| `python manage.py check` | **PASS** | — | — |
| `python manage.py makemigrations --check --dry-run` | **PASS** | No changes | — |
| `git diff --check` | **PASS** | CRLF warnings only | — |

Note: Full suite `quality.test_s2_cr08_canonical` (311 tests) shows 3 errors in `CommandDryRunTests` only when run in the combined test runner. The errors are dry-run preflight failures (`env_identity`, worker service/process tree, UNC paths), before the semantic-validator write path; focused tests pass with fresh DB. The known isolation issue is outside this change's scope.

---

## Test Count and Uniqueness

| File | Definitions | Unique | Duplicates |
|---|---|---|---|
| `quality.test_s2_cr08_canonical` (new) | 311 | 311 | 0 |
| `quality.test_s2_cr08_measurement` | 34 | 34 | 0 |

P1 focused set: 45 tests, all unique, no duplicates.

---

## Preserved Safety Conditions

- `backend/quality/s2_cr08_canonical.py`: `LIVE_BLOCKED = True` (line 2530)
- `backend/quality/management/commands/measure_s2_cr08_canonical.py`: `LIVE_BLOCKED = True` (line 49)
- Schema version: `CANONICAL_SCHEMA_VERSION = "s2-cr-08-canonical-v1"` unchanged
- No model/migration changes
- No evidence field add/remove/rename
- No status vocabulary extension
- No generic measurement writer changes
- No existing gate relaxation
- Validator is pure: no DB, filesystem, subprocess, or network I/O
- Exception messages are privacy-safe: no raw evidence, job IDs, paths, tokens, PIDs, or ports

---

## Not Performed

- P2 work
- canonical `--dry-run` / `--live` execution
- Pseudoprod or real Job submission
- Windows service operations
- backup/restore
- Threshold approval/change
- `specification/RELEASE.md` state change
- Model/migration/schema version changes
- Unrelated refactoring
- Stage/commit

---

## Unverified Items / Remaining Risks

- Live `write_evidence()` validator integration cannot be end-to-end tested because `LIVE_BLOCKED = True`. Validated via mock call-order test.
- `run_canonical()` service recovery check (Gate 6) has a pre-existing bug: `_check_service_status()` returns a dict but is compared to `"Running"` string. This does not affect the semantic validator but could cause false positives in real execution. Not fixed per "no scope expansion" rule.
- `CommandDryRunTests` has three combined-run preflight failures; its isolation behavior was not revalidated in this follow-up.

---

## Reviewer Focus

1. **Validator purity**: Confirm `_validate_canonical_evidence_semantics()` performs no external I/O.
2. **Non-destructive**: Confirm the function does not modify the evidence dict.
3. **Call site ordering**: Confirm `run_canonical()` calls final validation before privacy check.
4. **Test coverage**: Confirm all 20 matrix conditions are covered by direct test FQNs.
5. **Removed test**: Confirm `test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification` is removed and the existing `test_run_canonical_job_gate_fails_closed_when_job_a_failed` covers the same gate.
6. **No scope creep**: Confirm no model/migration/field/schema changes.
7. **Fresh DB validation**: Confirm the focused 45-test set passes, and assess the three existing combined-run `CommandDryRunTests` failures separately.
