# Planner Handoff: Stage B Retry

## Current Cycle Goal

Correct only four remaining P1 findings:

1. Functional production callbacks, public dispatch, and atomic evidence bundles.
2. Complete Execute/Cleanup guards and success conditions.
3. Django-compatible ForeignKey canonical hashing.
4. Table-driven zero-mutation, privacy, and residue tests.

This cycle is fake/static validation only. Modify only the same five Stage B files and handoffs. Preserve approved artifacts, `LIVE_BLOCKED=True`, criterion 8=`not_evaluable`, failure retention, and Web→worker recovery. Do not operate real DB/services, invoke PostgreSQL binaries, use network/UNC, run real PlanOnly, submit Jobs, log in, or run live A/B.

## Current Cycle Requirements

- Public modes must be functional: PlanOnly writes atomic pending manifest/checksum; Execute validates approval/current state, runs the complete sequence, and writes atomic execution evidence/checksum; Cleanup binds approval to execution bytes, performs exactly one validated drop, and writes atomic cleanup evidence/checksum.
- `New-StageBProductionAdapter` must provide non-placeholder callbacks for PendingInputs, Snapshot, Catalog, Jobs, Clients, Storage, Owners, ServiceState, Stop/StartService, Dump, ListDump, CreateRestore, Restore, and DropRestore using local resolved paths, `ArgumentList`, and child-only credentials. Remove fixed throws from valid paths.
- Strictly validate exact adapter keys and typed Snapshot, Catalog, Service, Dump, List, and Mutation result schemas.
- Complete every Execute guard before mutation. Require callback success/readback at every service/dump/list/create/restore/snapshot/recovery stage. Revalidate create-time target/OID/owner/empty proof; require restore/source semantic and identity invariants. Success is formed only after verified Web→worker recovery and atomic evidence reread/checksum.
- Failure recovers only services stopped by this invocation, remains failed if recovery fails, publishes redacted evidence, and never drops the restore or deletes the dump.
- Cleanup uses its own `restored` state contract. Before the sole drop, verify pending and execution bytes/checksum/linkage/privacy, cleanup approval bound to execution bytes, actual dump size/hash, zero Jobs/connections, exact target/OID/owner, cleanup owner, and source/protected distinctness. Require drop success and verified absence. Never delete the dump or retry drop.
- Evidence schemas must be exact, privacy-safe, atomic, deterministic, and refuse existing final bundles. Temporary bundle cleanup is limited to the invocation's validated temp path.
- Python must map Django field names to DB columns exactly: MasterClass `master→master_id`, `class_master→class_master_id`; InspectionFile `master→master_id`; dictionary keys remain Django field names. Preserve `id` order, `updated_at` exclusion, non-compact existing JSON bytes, and duplicate sorted paths.
- Python tests add independent hard-coded golden values for ForeignKeys, Unicode, Decimal/datetime, nullable FK, duplicate paths, identity, and OID binding.
- PowerShell tests are table-driven with per-callback counters covering all schema/time/hash/collision/drift/result/runtime/recovery/cleanup/public-dispatch failures. Every preflight and cleanup guard failure has zero mutations; runtime failures have zero drop/delete; cleanup success has exactly one drop and verified absence.
- Privacy scans cover all pending/execution/cleanup/checksum/error/output artifacts with raw sentinels. Atomic tests cover deterministic hashes, existing-final refusal, pre-publication cleanup, and no orphan temporary bundles.
- Update only the Stage B README section and accurately state that runtime remains unverified.

## Current Cycle Acceptance

Run only the Python tests, PowerShell fake tests, Python compile, PowerShell parser API, scoped diff, and `git diff --check`. Accept only with functional public dispatch, no placeholder callbacks, strict typed schemas, all guards before mutation, complete success/recovery conditions, atomic linked evidence, one-drop cleanup, ForeignKey golden compatibility, full mutation/privacy/residue proof, unchanged safety gates, and no prohibited runtime operation.

The implementer handoff must include exact files/results, test table counts, mutation-counter proof, golden hashes, privacy/residue results, confirmation production adapters were not constructed/invoked in tests, prohibited-operation confirmation, and unresolved runtime prerequisites.

---

## Superseded Prior Cycle Goal

Correct only the latest four P1 findings: complete all public code paths, enforce strict nested schemas and a full current-state gate before mutation, match existing canonical snapshot hashes, and prove all blocking/failure conditions with zero-mutation tests. This cycle is code plus fake-adapter validation only.

## Current Scope and Prohibitions

Modify only the Stage B PowerShell/Python implementation, their two tests, the Stage B README section, and agent handoffs. Preserve approved artifacts, both `LIVE_BLOCKED=True` gates, criterion 8=`not_evaluable`, and Stage-B-only status.

Do not operate real databases/services, invoke PostgreSQL binaries, use network/UNC, run PlanOnly with real prerequisites, submit Jobs, log in, or run live A/B. Tests use injected fakes and local temporary files. Production adapters are code-wired but never constructed or invoked by tests.

## Required Implementation

1. Match existing canonical semantics exactly: non-compact `json.dumps(..., ensure_ascii=False, sort_keys=True, default=str)` bytes; fixed dictionary fields; `id` order; exclude `updated_at`; preserve duplicate sorted InspectionFile paths. Use direct normalized-text SHA-256 for identity in both languages with shared golden literals.
2. Require `--expected-source-oid-hash` in restore mode; reject malformed/missing/equal values and source-mode misuse before output.
3. Implement strict schema/hash/privacy/atomic/checksum helpers and `New-StageBProductionAdapter`, `Get/Assert-StageBCurrentState`, pending manifest construction, Execute, Cleanup, Recovery, Entry, and Main dispatch. Remove unconditional valid-mode throws.
4. Strictly validate all top-level and nested manifest fields: schema/run/scope/live block/criterion/times; source/restore/protected identity and OID state; source baseline; clients/majors; local capacity/retention; distinct owners; service identities and worker→Web/Web→worker order. Reject missing/extra/type/hash/time/collision/drift errors.
5. Require exact execute/cleanup approvals with constant-time byte-hash binding and bounded approval time.
6. Code-wire local production adapters with `ProcessStartInfo.ArgumentList`, child-only credentials, typed privacy-safe results, complete read-only callbacks, and stop/start/dump/list/create/restore/drop callbacks. Tests never construct them.
7. PlanOnly uses only read callbacks, runs all guards, privacy-scans, and atomically writes manifest/checksum.
8. Execute must finish all current-state guards before the first mutation: approval, adapter contract, zero Jobs, source baseline, restore empty/absent/distinct, protected set, versions, capacity/retention, owners, and service state/order. A validated token is required to mutate.
9. Execute order: stop worker→Web; recheck source; dump and verify exit/size/hash; verify nonempty dump-list; recheck/create approved restore and distinct OID; transactional restore and result check; bound semantic comparison; source unchanged proof; recover Web→worker and verify. Recovery failure means failure. Never auto-drop/delete.
10. Atomically write allowlisted privacy-safe final evidence/checksums.
11. Cleanup is separately approved and validates pending/final linkage, dump hash, exact target/OID/owner, protected/source distinctness, cleanup owner, zero connections/Jobs, and eligible state before exactly one drop; verify absent; never delete dump.
12. Python tests use independent hard-coded golden hashes for canonical rows/Unicode/Decimal/time/duplicate paths/identity/OID binding/privacy/no-output failures.
13. PowerShell tests are table-driven and mutation-counting for every nested/preflight/approval/drift failure; every execution/recovery failure; successful absent/existing-empty paths; all cleanup guards; privacy sentinels; deterministic checksums; no temporary residue. Every preflight/cleanup failure must prove zero mutation.
14. Update only the Stage B README section and do not claim runtime acceptance.

## Current Acceptance

Allowed commands are the Python test, PowerShell test, Python compile, PowerShell parser API, scoped diff, and `git diff --check`. Accept only if all fake/static tests pass, public modes dispatch to code-complete paths, all guards precede mutation, all stage and recovery results are mandatory, canonical golden/cross-language literals match, all negative cases prove zero mutation, cleanup is separate, privacy scans pass, and no prohibited operation occurs.

Update `.codex/agents/.implementer/HANDOFF.md` with exact files/results, mutation-count proof, golden literals, confirmation production adapters were not invoked, prohibited-operation confirmation, and unresolved runtime prerequisites.

---

## Superseded Prior Plan

## Goal

Correct only the four blocking findings: complete the approval-gated runtime/evidence code path, bind the pending manifest to privacy-safe runtime identities and prerequisites, make snapshot hashes canonical with mandatory distinct-OID proof, and add mutation-free focused safety tests.

This cycle implements and tests code only. It must not operate real databases/services, invoke PostgreSQL binaries, run PlanOnly with real prerequisites, submit Jobs, access UNC, or run live A/B.

## Scope

- `deployment/windows/validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/stage_b_snapshot.py`
- `deployment/windows/test_validate_stage_b_backup_restore.ps1` (new)
- `deployment/postgresql/test_stage_b_snapshot.py` (new)
- `deployment/README.md`

Preserve approved artifacts, `LIVE_BLOCKED=True`, and criterion 8=`not_evaluable`.

## Required Changes

1. Implement one deterministic UTF-8 canonical JSON/hash contract. Use explicit canonical fields/order compatible with the existing canonical implementation. InspectionFile path-set is a sorted distinct scalar-string list. Hash normalized host, port, endpoint, database, OID, role, and server version without emitting raw identities. Restore mode must require a source-distinct OID hash before output.
2. Refactor the PowerShell script into dot-sourceable pure validators and explicit mutually-exclusive `-PlanOnly`, `-Execute`, and `-Cleanup` entry modes.
3. Make PlanOnly strictly bind schema version, scope, live block, criterion 8, expiry, privacy-safe source/restore/protected identities, OID/role/empty-or-absent proof, source baseline, client/server versions and hashes, fixed command tokens, storage/capacity/retention, owner hashes, service hashes/order, and execution state. Reject collisions, nonempty/unknown targets, denylist hits, source-derived restore names, UNC storage, insufficient capacity, and missing owners.
4. Require an exact execute-approval schema and byte hash. Strictly revalidate every manifest field and all current identity/version/baseline/capacity/retention values before the first mutation callback.
5. Put process/service/database behavior behind injectable adapters. Implement the approved sequence: zero Jobs; stop worker then Web; source revalidation; custom no-owner/no-acl dump/list; create or verify only the approved distinct target; transactional restore; canonical comparisons; source unchanged proof; recover Web then worker.
6. Use array process arguments and child-process environment credentials. Never emit secrets, raw identities/paths, command lines, or raw errors.
7. Retain dump and restore DB on failure. Implement separately approved cleanup that revalidates final checksum, dump hash, endpoint/database/OID/owner, and cleanup owner before dropping only the restore DB; never auto-delete the dump.
8. Atomically generate privacy-safe success/failure evidence and deterministic lowercase checksums.
9. Add Python `unittest` coverage for canonical values/order, stable rows, InspectionFile paths, composite identity, and mandatory distinct OID using fakes only.
10. Add Pester-independent PowerShell tests for identifier/host/port, denylist, strict schemas, approval tamper/time/action, empty/distinct guards, redaction, canonical JSON, checksums, and stubbed sequence ordering/zero-mutation failures/separate cleanup approval.
11. Update only the Stage B README section. Do not claim runtime validation succeeded.

## Allowed Validation

- `python deployment/postgresql/test_stage_b_snapshot.py`
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/windows/test_validate_stage_b_backup_restore.ps1`
- `python -m py_compile deployment/postgresql/stage_b_snapshot.py deployment/postgresql/test_stage_b_snapshot.py`
- PowerShell parser API against both `.ps1` files without invoking the orchestrator
- scoped diff inspection and `git diff --check`

Acceptance requires all mutation-free tests to pass; zero real DB/service/process/network/UNC/Job/login/live-A/B calls; all guard failures before the first mutation callback; canonical hashes and mandatory distinct proof; deterministic privacy-safe evidence; separate cleanup approval; unchanged approved artifacts/safety gates; and no scope change outside these five files plus agent handoffs.

## Implementer Handoff

Write `.codex/agents/.implementer/HANDOFF.md` with exact files, validation results, proof that real adapters were not invoked, unresolved runtime prerequisites, and working-tree scope. Then stop for independent review.
