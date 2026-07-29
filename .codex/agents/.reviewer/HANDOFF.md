# Reviewer Handoff: Stage B Backup/Restore

## Review Scope

- `deployment/windows/validate_stage_b_backup_restore.ps1`
- `deployment/windows/test_validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/stage_b_snapshot.py`
- `deployment/postgresql/test_stage_b_snapshot.py`
- Stage B section of `deployment/README.md`
- approved artifacts, safety gates, and working-tree scope

## Verdict

**FAIL**

The most recent implementation cycle produced no product-file changes. The implementer reported `VALIDATION_FAILED`, and the remaining Stage B findings are unresolved.

## Verified Facts

- No product diff was produced in the most recent cycle.
- The verified Django ForeignKey canonical mapping remains unchanged.
- Fixed fields, `id` ordering, `updated_at` exclusion, non-compact JSON encoding, and duplicate-preserving sorted InspectionFile paths remain present.
- Both canonical `LIVE_BLOCKED=True` gates remain unchanged.
- Criterion 8 remains `not_evaluable`.
- The approved package remains Stage B-only and is not live approval.
- Approved artifacts and hashes remain unchanged.
- No real database, service, PostgreSQL binary, network, UNC, Job, login, PlanOnly runtime, or live A/B operation was performed.

## Unverified Items

- Functional production callbacks and public PlanOnly/Execute/Cleanup paths.
- Atomic pending, execution, and cleanup evidence bundles and checksums.
- Execute callback typing, service-state readbacks, and stopped-service-only recovery.
- Cleanup restored-state linkage, retained-dump verification, owner/Jobs guards, one-drop behavior, and absence verification.
- Complete mutation-count, privacy-sentinel, and temporary-residue test coverage.
- All real runtime prerequisites and runtime behavior.

## Findings and Priority

### P1: Production callbacks and public atomic evidence are incomplete

Production adapter callbacks still contain fixed configuration failures and do not implement the required exact callback contract. Public PlanOnly does not publish a verified checksum, and Execute/Cleanup do not publish linked, privacy-scanned, atomically verified evidence bundles.

### P1: Execute typed readback and recovery are incomplete

Dump/List/Restore result schemas and service-state readbacks are incomplete. Failure recovery does not reliably track only services stopped by the current invocation or reject unsuccessful non-throwing recovery callbacks.

### P1: Cleanup restored-state linkage and one-drop contract are incomplete

Cleanup still depends on the pending absent/empty state rather than a restored-state contract. It does not fully bind approval to exact execution evidence or validate execution checksums, retained dump bytes, cleanup identity, Jobs, typed drop success, and final absence before publishing cleanup evidence.

### P1: Mutation, privacy, and residue test coverage is incomplete

The current test suite does not provide the required table-driven per-callback proof for all public-dispatch, schema, drift, execution, recovery, cleanup, privacy, existing-final, and temporary-residue conditions.

### P2: README is inconsistent with the verified contract

The Stage B section still describes compact/distinct hashing and overstates evidence readiness. The verified contract uses non-compact canonical JSON and duplicate-preserving sorted paths, and runtime readiness remains unverified.

## Next Minimum Scope

The next planner must select only the first dependency-complete behavior boundary:

1. Implement the exact production adapter contract and functional PlanOnly atomic manifest/checksum path.

Defer Execute, Cleanup, the full test-matrix expansion, and README finalization to later user-gated cycles unless strictly required to validate this first boundary.

## Safety Gates

- Preserve approved artifacts, hashes, baselines, thresholds, approvers, and conditions.
- Preserve both `LIVE_BLOCKED=True` gates and criterion 8=`not_evaluable`.
- Preserve Stage B-only/no-live-approval status.
- Do not operate real databases or services.
- Do not invoke PostgreSQL binaries, use network or UNC, submit Jobs, log in, run real PlanOnly prerequisites, or run live A/B.
- Do not delete retained dumps or partial restore databases.
- Do not treat fake/static validation as runtime acceptance.

## Route Conditions

### Codex Implementation

After explicit user selection, planner defines only the first dependency-complete scope above. A separate Codex implementer performs that bounded change and validation, followed by an independent Codex reviewer.

### External Implementation

After explicit user selection, the same bounded scope may be handed to an external implementer. Codex must not duplicate that implementation and must independently review the returned product diff and validation.

## User Decision Gate

The user must explicitly select Codex implementation or external implementation before the next cycle begins.
