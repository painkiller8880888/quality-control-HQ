# Reviewer Handoff: Stage B Retry

## Latest Review Scope

- Same five Stage B implementation/test/documentation files
- Current planner and implementer handoffs
- Approved artifacts, canonical safety gates, and scoped diff

## Latest Verdict

**FAIL**

The Django ForeignKey canonical mapping is materially improved, but functional production/public evidence paths, typed recovery, cleanup linkage, and the required mutation/privacy/residue test matrix remain incomplete.

## Latest Blocking Findings

### P1: Production callbacks, public modes, and atomic evidence are incomplete

Core production callbacks still contain fixed throws and do not match the planned exact adapter contract. PlanOnly does not publish its checksum; Execute/Cleanup do not publish privacy-scanned, atomically reread execution/cleanup bundles and checksums.

Required correction: implement every planned production callback without placeholders and make all three public modes enforce existing-final refusal, privacy scanning, atomic publication, checksums, and reread validation.

### P1: Execute typed results and recovery are incomplete

Dump/List/Restore/Mutation/Service callback results lack exact typed schema enforcement. Service state readback is absent. Failure handling does not track only the services stopped by this invocation and can ignore recovery callbacks that return unsuccessful results.

Required correction: strictly validate all callback results; require stop/start state readbacks; track stopped services; recover only those services in the correct order; validate recovery callback results and final states.

### P1: Cleanup linkage and one-drop contract are incomplete

Cleanup reuses the pending absent/empty state instead of a restored-state contract, binds approval to the pending manifest rather than execution bytes, and does not validate execution checksum, actual dump bytes, cleanup owner, Jobs, privacy, drop result, absence readback, or publish cleanup evidence.

Required correction: add a cleanup-specific restored state and bind the exact execution evidence/checksum/dump/identity/owner/zero-Jobs/connections conditions before the sole drop. Require success plus absence and atomically publish cleanup evidence.

### P1: Table-driven mutation/privacy/residue coverage is still absent

The PowerShell suite still has only a small set of manifest/preflight/cleanup cases and lacks public dispatch, adapter schemas, all state/callback/recovery failures, existing-empty success, cleanup one-drop success, evidence linkage, dump reread, privacy sentinels, existing-final refusal, and orphan-temp checks.

Required correction: add the planned per-callback counters and full table. Prove preflight/cleanup failure mutation=0, runtime failure drop/delete=0, cleanup success drop=1, artifact privacy, existing-final refusal, and no temporary residue.

### P2: README contradicts canonical/evidence behavior

The Stage B section still describes compact JSON and distinct paths although the contract uses non-compact JSON and duplicate-preserving sorted paths, and overstates evidence readiness.

Required correction: update only the Stage B section to the actual contract and explicitly unverified runtime state.

## Latest Verified Facts

- Django ForeignKey mapping now uses Django keys for `master` and `class_master`.
- Fixed fields, `id` ordering, `updated_at` exclusion, non-compact JSON, and a nullable-FK/Unicode golden are present.
- Python 6 tests, PowerShell fake tests, Python compile, PowerShell parser, and scoped diff check pass.
- Snapshot/Catalog/create/source-invariant skeletons improved.
- Approved artifacts and both `LIVE_BLOCKED=True` gates are unchanged.
- Criterion 8 remains `not_evaluable`; Stage B-only state is preserved.
- No prohibited runtime operation occurred.

## Latest Unverified Items

- Functional production callbacks and public modes.
- Atomic execution/cleanup evidence and checksums.
- Service-state recovery and cleanup one-drop linkage.
- Full privacy/residue and mutation-count proof.
- All real runtime prerequisites and execution.

## Latest Minimum Scope

Keep the same five files. Correct only production/public evidence, Execute recovery/result strictness, Cleanup restored-state/linkage, table-driven privacy/residue tests, and README consistency. Do not perform runtime execution.

## Latest Safety Gates and Routes

Preserve approved artifacts, both live blocks, criterion 8, Stage-B-only status, and failure retention. Do not use real DB/services/PostgreSQL/network/UNC/Jobs/login/live A/B. After explicit user selection, either Codex or an external implementer may receive this scope; a separate Codex reviewer must review it.

## Latest User Decision Gate

The user must explicitly select the next route before work continues.

---

## Superseded Current Review Scope

- Stage B PowerShell/Python implementation
- Stage B PowerShell/Python tests
- Stage B README section
- planner/implementer handoffs
- approved artifacts, canonical gates, criterion 8, and scoped diff

## Current Verdict

**FAIL**

The implementation improved canonical encoding, strict validation helpers, runtime skeletons, and fake tests, but all four P1 findings remain blocked by incomplete production callbacks, execution/cleanup guards, ForeignKey canonical mapping, and negative coverage. Pipeline stops at the mandatory user decision gate.

## Current Blocking Findings

### P1: Public modes are not connected to functional production callbacks

`New-StageBProductionAdapter` still uses fixed throws for core pending/snapshot/catalog/service/state/create/drop callbacks. Valid PlanOnly/Execute/Cleanup therefore cannot complete. Execute also does not persist final privacy-safe evidence/checksums through the public path.

Required correction: implement the actual local read/service/catalog/snapshot/dump/list/restore/create/drop callbacks using array arguments and child-only credentials, connect all public modes, and atomically persist privacy-safe execution/cleanup evidence.

### P1: Execute and Cleanup guards/success conditions remain incomplete

Create is not followed by strict target/OID/owner revalidation. Snapshot callback schemas are not strict, so missing semantic hashes can compare as equal. Post-restore source identity, service stop/start results, and recovery states are not mandatory success conditions.

Cleanup does not bind approval to final evidence, recheck final checksum/dump bytes/cleanup owner, or use a cleanup-specific current-state contract. A valid post-restore cleanup can conflict with the pending absent/empty state check.

Required correction: strict typed callback schemas; create-time identity proof; complete semantic/source/recovery checks; cleanup-specific state and final-evidence linkage; dump/checksum/operator/zero-connections/zero-Jobs/target checks before the sole drop.

### P1: ForeignKey canonical field mapping is incompatible

Existing canonical hashes use Django field names such as `master` and `class_master`; the new DB-row dictionaries use column names such as `master_id` and `class_master_id`. MasterClass and InspectionFile hashes therefore differ from the approved canonical bytes.

Required correction: define exact per-table Django-field-to-DB-column mappings and add hard-coded golden tests covering ForeignKeys, Unicode, Decimal/time values, duplicate paths, identity, and OID across Python and PowerShell.

### P1: Negative zero-mutation coverage remains insufficient

Tests do not cover every nested missing/extra/type/collision/time/action/current-state/adapter failure, all runtime stage/recovery failures, both restore-state success paths, cleanup guards and one-drop success, public dispatch, privacy artifacts, or atomic residue.

Required correction: implement the planner's table-driven suite. Every preflight/cleanup failure must show mutation count zero; runtime failures must show drop/delete zero; cleanup success must show exactly one drop and verified absence.

## Current Verified Facts

- Python tests pass: 5 tests.
- PowerShell fake test passes.
- Python compile and PowerShell parser checks pass.
- Scoped `git diff --check` has no errors.
- Changes remain within the five product/test files and handoffs.
- Direct normalized-text identity hashing, non-compact Python JSON encoding, `updated_at` exclusion, duplicate path preservation, and restore source-OID argument format checks are present.
- Approved artifacts are unchanged.
- Both `LIVE_BLOCKED=True` gates, criterion 8=`not_evaluable`, and Stage-B-only status remain intact.
- No real database/service/PostgreSQL binary/network/UNC/Job/login/live-A/B operation occurred.

## Current Unverified Items

- Functional production adapters and all public runtime modes.
- Real manifest generation, dump/list/restore/recovery/cleanup.
- Runtime identity, capacity, retention, permissions, and service behavior.
- Final privacy-safe evidence and checksums.

## Next Minimum Scope

Keep the same five product/test files. Correct only functional production callbacks/public evidence, Execute/Cleanup strict guards, canonical ForeignKey mapping, and complete mutation-count/privacy tests. Do not perform runtime execution.

## Safety Gates

- Preserve approved artifacts and their hashes.
- Preserve both `LIVE_BLOCKED=True` gates and criterion 8=`not_evaluable`.
- Do not operate services/databases, invoke PostgreSQL binaries, use network/UNC, run real PlanOnly, submit Jobs, log in, or run live A/B.
- Do not stage, commit, push, or refactor outside the minimum scope.

## Route Conditions

After explicit user selection, either a Codex implementer or external implementer may receive the same minimum scope. A separate Codex reviewer must independently verify returned code/tests and update this handoff.

## Current User Decision Gate

The user must explicitly select Codex implementation or external implementation before another correction cycle.

---

## Superseded Prior Review

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
