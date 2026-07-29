# Implementer Handoff: Stage B Retry

> This retry supersedes the earlier contents below where they conflict.

## Retry result

- Public `-PlanOnly`, `-Execute`, and `-Cleanup` now dispatch through a code-wired production-adapter boundary. Deployment-specific callbacks fail closed until configured; no test constructs this adapter.
- Strict nested manifest/current-state guards run before any stop/create/drop callback. Execute validates process results, source invariance, semantic equality, OID distinction, and mandatory recovery. Cleanup has separate approval, final-to-manifest linkage, catalog/owner/connection checks, one drop callback, and absence verification.
- Snapshot table hashes match `s2_cr08_canonical.py`: dictionary rows in `id` order, `updated_at` excluded, noncompact `json.dumps(..., ensure_ascii=False, sort_keys=True, default=str)` bytes. Identities use direct normalized-text SHA-256 and path hashes preserve sorted duplicates.
- Hard-coded Python golden SHA-256 values: canonical `5da2618377a0ae442c3c0cd87af286fcb60ecb89902a6eb1f41f64ea79092ab7`; rows `a61793f8ec74bdeada7a7f9a4f8b1de35719aaf2bc867a9c75ec9f2a10420dde`; paths `1083f9182b5913e7df6d35f8b8382e55e0d70a2523460db161f9e915bdb8c7ef`; endpoint `ef6cea1eb186f0c9dd952eba0f2d66c425294d06dc4ea1b3050d4a88d7235908`; OID `785f3ec7eb32f30b90cd0fcf3657d388b5ff4297f2f9716ff66e9b69c05ddd09`.

## Retry validation

- `python deployment/postgresql/test_stage_b_snapshot.py`: passed (5 tests).
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/windows/test_validate_stage_b_backup_restore.ps1`: passed.
- `python -m py_compile deployment/postgresql/stage_b_snapshot.py deployment/postgresql/test_stage_b_snapshot.py`: passed.
- PowerShell parser API for both scoped scripts: passed (0 errors).
- scoped `git diff --check`: passed (line-ending warnings only).

## Retry safety facts

Tests used fake Python connections, fake PowerShell adapters/mutation counters, and a local temporary checksum directory only. No real database, service, PostgreSQL binary, network, UNC, Job, login, PlanOnly prerequisite, or live A/B operation occurred. `LIVE_BLOCKED=True` and criterion 8=`not_evaluable` remain unchanged. Runtime callback configuration and all runtime prerequisites/evidence remain unverified.

## Scope completed

- Implemented the scoped Stage B canonical snapshot contract, privacy-safe identity hashing, and mandatory restore distinct-OID guard.
- Added dot-sourceable PowerShell validators, strict approval/manifest checks, injected-adapter sequence, redacted failure result, atomic JSON/checksum helpers, and fail-closed public entry modes.
- Added pure fake/stub tests and updated only the Stage B README section.

## Changed files

- `deployment/windows/validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/stage_b_snapshot.py`
- `deployment/windows/test_validate_stage_b_backup_restore.ps1`
- `deployment/postgresql/test_stage_b_snapshot.py`
- `deployment/README.md`
- `.codex/agents/.implementer/HANDOFF.md`

## Validation

- `python deployment/postgresql/test_stage_b_snapshot.py`: passed (5 tests).
- `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/windows/test_validate_stage_b_backup_restore.ps1`: passed.
- `python -m py_compile deployment/postgresql/stage_b_snapshot.py deployment/postgresql/test_stage_b_snapshot.py`: passed.
- PowerShell parser API for both scoped `.ps1` files: passed (0 errors).
- `git diff --check -- <five scoped product files>`: passed.

## Safety and unverified items

- Tests used fake Python connections, injected PowerShell adapters, and temporary local files only. No real database, service, PostgreSQL binary, network, UNC, Job, login, live A/B, or PlanOnly prerequisite execution occurred.
- Public runtime modes remain fail-closed because no production adapter is configured in this code-only cycle.
- Sequence failure result preserves the dump hash and has no automatic drop/delete callback; cleanup is a separate approval action.
- `live_blocked=true` and `criterion_8=not_evaluable` are fixed in sequence success/failure results and required by manifest validation.
- Real source/restore identities, catalog empty/absent proof, OIDs, ownership, capacity/retention, client/server compatibility, dump/restore behavior, service recovery, and final evidence are intentionally unverified.

## Working-tree scope

- The five product files listed above are the only product files changed by this implementation. Existing user changes and approved artifacts were not reverted or edited.
- Pre-existing agent-directory changes outside this handoff were not modified.

## Reviewer focus

- Independently inspect strict manifest completeness and the current fail-closed runtime boundary.
- Confirm raw protected values cannot reach emitted JSON/stdout and that no real adapter is reachable from the executed test suite.
