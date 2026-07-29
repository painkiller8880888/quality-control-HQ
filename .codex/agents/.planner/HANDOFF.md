# Planner Handoff: Stage B Four-Finding Correction

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
