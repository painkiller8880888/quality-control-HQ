# Reviewer Handoff: Stage B Four-Finding Correction

## Review Scope

- `.codex/agents/.planner/HANDOFF.md`
- `.codex/agents/.implementer/HANDOFF.md`
- `deployment/windows/validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/stage_b_snapshot.py`
- `deployment/windows/test_validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/test_stage_b_snapshot.py`
- `deployment/README.md`
- approved artifacts, canonical safety gates, criterion 8, and scoped working-tree integrity

## Verdict

**FAIL**

All four prior blocking findings remain unresolved. Some validators, a runtime skeleton, and mutation-free tests were added, but the approved runtime, strict manifest, canonical compatibility, cleanup, and safety-test contract are incomplete. Pipeline stops at the mandatory user decision gate.

## Blocking Findings

### P1: Public runtime paths are not implemented

`-PlanOnly`, `-Cleanup`, and `-Execute` all terminate unconditionally. `Invoke-StageBSequence` is unreachable from the public entry point, production adapters are not connected, and cleanup is absent. The approved dump/restore/verification/evidence sequence therefore cannot run after approval.

Required correction: implement each public mode with production adapters while preserving the exact-manifest gate and prohibition on real execution before later explicit approval.

### P1: Manifest and current-state revalidation are incomplete

Validation checks top-level property names but not the nested source/restore/protected, clients, storage, owners, or services schemas. Hash formats, expiry, capacity, retention, versions, owners, and service order are not adequately enforced. Tests currently accept empty client/storage/service objects and one-character identity hashes.

The sequence stops services before source revalidation, does not validate dump-list or `pg_restore` success, lacks source-unchanged and canonical semantic comparisons, and can retain a success result when service recovery throws.

Required correction: strictly validate all nested fields and current state before the first mutation callback; make every process result, source invariant, semantic comparison, and service recovery mandatory for success.

### P1: Snapshot hashes remain incompatible with the canonical implementation

The snapshot helper hashes `SELECT *` tuple arrays using compact JSON. The existing canonical implementation excludes `updated_at`, hashes dictionary rows, and uses its established JSON encoding. PowerShell raw-string hashing and Python JSON-scalar hashing also differ. Restore distinct-OID input is not bound to a validated source identity.

Required correction: share or exactly reproduce existing canonical field selection, row shape, ordering, encoding, identity hashing, and source-OID binding across both languages.

### P1: Safety tests do not cover the blocking conditions

Tests are predominantly happy-path stubs. They do not establish strict nested schemas, expiry, capacity/retention, version drift, all-guards-before-mutation, restore/recovery failure handling, cleanup approval/revalidation, privacy scanning, or cross-language canonical compatibility.

Required correction: add negative tests and zero-mutation assertions for every guard, cleanup tests, canonical golden values, and privacy-leak scanning.

## Verified Facts

- Python unittest: 5 tests pass.
- PowerShell mutation-free test passes.
- Python `py_compile` passes.
- Both PowerShell files parse with zero syntax errors.
- Scoped `git diff --check` passes.
- No real database, service, PostgreSQL binary, network, UNC, Job, login, or live A/B operation was performed.
- Approved S2-CR-08 approval JSON remains SHA-256 `9351e79f5f7c418c4c99c0b820621cf5c85d9a32ce93c08663a4ff8eb7892439`, with matching manifest.
- Canonical module and command retain `LIVE_BLOCKED=True`.
- RELEASE retains criterion 8=`not_evaluable` and Stage B-only/no-live-approval state.

## Unverified Items

- Actual PlanOnly manifest generation against runtime prerequisites.
- Production adapters and all runtime sequence steps.
- Runtime identity, OID, empty/distinct, version, capacity, and retention checks.
- Dump/list/restore results, source invariance, semantic comparisons, cleanup, service recovery, privacy scan, and final evidence checksums.

## Next Minimum Recommended Scope

Correct only the four P1 findings above. Use the existing five-file scope and agent handoffs. Do not perform runtime execution. The next implementation must make the public paths complete in code, validate every nested/current-state condition before mutation, match canonical golden values exactly, and demonstrate all failure paths with mutation-free tests.

## Safety Gates and Forbidden Changes

- Preserve approved artifacts, baselines, thresholds, approvers, conditions, and manifest.
- Preserve both `LIVE_BLOCKED=True` gates and criterion 8=`not_evaluable`.
- Do not operate services/databases, invoke PostgreSQL binaries, submit Jobs, access UNC, run PlanOnly with real prerequisites, or run live A/B.
- Do not stage, commit, push, or refactor outside the minimum correction scope.
- Do not treat passing static tests as runtime acceptance.

## Route Conditions

### Codex Implementation

After explicit user selection, a new planner may narrow the four P1 corrections, a separate Codex implementer may implement them without runtime operations, and another independent reviewer must update this handoff and stop again.

### External Implementation

After explicit user selection, the same four P1 corrections may be handed to an external implementer. Codex must not duplicate that implementation and must independently review returned changes and evidence.

## User Decision Gate

The user must explicitly select Codex implementation or external implementation before the next correction cycle begins.
