Cycle ID: `S2-CR08-TODO5-20260729-02`
Plan SHA-256: `da39da32ef4d23deba6d486602b562f914ab808d3dc568fff691d9f2e5fa648f`
Job ID: `S2-CR08-TODO5-20260729-02:da39da32ef4d23deba6d486602b562f914ab808d3dc568fff691d9f2e5fa648f`
<!-- PLAN-BODY-START -->
Outcome: `PASS`

Goal:
- Complete only `specification/RELEASE.md` Stage B resume TODO 5: independently audit, minimally correct if necessary, and freshly validate the preserved candidate implementation of an atomic, privacy-scanned execution-evidence bundle linked to the exact approved pending-manifest checksum.

In Scope:
- Treat the user-approved `AGENTS.md` safe-batching preamble as an accepted, user-owned working-tree baseline; preserve it unchanged.
- Treat the two product-file TODO 5 changes from the blocked prior cycle as unreviewed candidate work, not accepted completion.
- Validate the pending bundle checksum, approval, manifest, and evidence destination before any Execute callback can mutate state.
- Convert the Execute result to a strict privacy-safe evidence record, then publish and verify the complete bundle atomically without overwrite.
- Add direct fake/static tests for checksum linkage, exact evidence schema, privacy, atomic visibility, tamper/write failures, and residue cleanup.

Deferred Scope:
- TODO 6 Cleanup/restored-state linkage, retained-dump validation, owner/Jobs guards, exact one-drop, final absence proof, and Cleanup evidence.
- TODO 7 production-provider integration, TODO 8 runtime exercise, real PostgreSQL/Windows services/database/network/UNC/Job/login/backup/restore, live A/B, and application behavior.
- Do not change Process/callback contracts, service ownership/recovery, pending publication semantics, Cleanup/DropRestore behavior, `specification/RELEASE.md`, `AGENTS.md`, or accepted TODO 1-4 behavior.

Affected Files:
- `deployment/windows/validate_stage_b_backup_restore.ps1`
- `deployment/windows/test_validate_stage_b_backup_restore.ps1`
- `.codex/agents/.implementer/HANDOFF.md` (role output only; replace)

Required Changes:
1. Before product work, recompute this Planner body hash and verify Cycle ID, Plan SHA-256, and Job ID. Verify the current tree contains the accepted `AGENTS.md` preamble, accepted cumulative TODO 1-4 changes, preserved candidate TODO 5 changes in only the two product files, and role handoffs. Any other scope is `BLOCKED`.
2. Audit the preserved TODO 5 product and test diff against every requirement below. Keep correct candidate code intact and make only the smallest necessary corrections or direct-test additions; do not broaden or refactor.
3. For `-Execute`, require `EvidenceRoot` to name a not-yet-existing bundle directory whose parent already exists. Reject a missing/empty root, existing file/directory, missing parent, or path collision before `Invoke-StageBSequence` and before any adapter mutation. Do not create or overwrite the final root during preflight.
4. Before Execute mutation, validate the pending manifest's sibling `checksums.sha256` as exactly one UTF-8 line `<lowercase-64-hex><two spaces><pending-manifest leaf><LF>`, with no extra line/file-name substitution. Recompute the manifest SHA-256 and constant-time compare it with both the checksum entry and the exact execute approval already required by `Test-StageBApproval`; parse and validate the manifest only after linkage succeeds.
5. Freeze the execution evidence as the exact three-property record `status`, `dump_hash`, `manifest_sha256`. `status` is exact `System.String` `success` or `failed`; `manifest_sha256` is a lowercase 64-hex string equal to the validated pending checksum; success requires a lowercase 64-hex `dump_hash`, while failure permits only null or a lowercase 64-hex dump hash. Reject null, scalar, missing/extra properties, wrong types/case, truthy stand-ins, invalid status/hash, and inconsistent success/null combinations.
6. Construct evidence by explicit allowlist projection from `Invoke-StageBSequence`; never serialize its raw error, exception, callback value, path, host, database, account, environment, approval, or manifest. Validate the projected object before serialization and validate the parsed serialized bytes again. Errors exposed by the publication path remain the fixed privacy-safe Stage B failure message.
7. Publish an exact bundle containing only `execution.json` and `checksums.sha256`. `execution.json` is canonical compact UTF-8 without BOM plus one LF. Its checksum file is exactly one lowercase SHA-256 entry for `execution.json`, plus one LF. No absolute or temporary path may appear in either file.
8. Build and fully verify both files in a unique sibling temporary directory while the final root remains absent; run the existing mode-local post-write test hook there; reject hook tampering or unexpected files; then move the complete directory to the final `EvidenceRoot` in one rename. Re-read the published files and recompute their linkage before returning the exact evidence record.
9. Refuse overwrite/races at every safe boundary. On any pre-publication validation, write, hook, checksum, privacy, or move failure, remove only this invocation's temporary directory, leave an existing destination untouched, and leave no `*.tmp`/temporary bundle residue. External concurrent filesystem-actor hardening beyond these deterministic checks remains deferred.
10. Add positive Execute-main tests proving approval/checksum/manifest linkage, exact fake callback order, exact returned/file evidence equality, exact two-file inventory, checksum recomputation, final-root absence during staging verification, and no automatic `DropRestore`.
11. Add negative/table-driven tests proving missing/malformed/extra/wrong-name/uppercase/mismatched pending checksum, approval mismatch, malformed evidence records, existing destination, missing parent, unexpected staged file, staged-content/checksum tamper, and write/move failure all fail closed with the required zero-mutation or no-partial-publication behavior.
12. Add a privacy sentinel Execute failure whose callback throws raw credential/host/path-like text. Prove the published failed evidence and surfaced error contain none of the sentinels, the failed record has only the exact allowed fields, and recovery behavior remains invocation-owned and unchanged.
13. Preserve exact valid fake order `stop-worker,stop-web,pg_dump,pg_restore_list,create,pg_restore,start-web,start-worker`, strict TODO 1-4 validators/tests, dump-hash retention, pending bundle behavior, no automatic `DropRestore`, `LIVE_BLOCKED=True`, and criterion 8 `not_evaluable`.
14. Replace the Implementer handoff with matching identity and canonical schema, exact commands/exits/results, unverified items, safety confirmation, and actual final tree scope including the accepted user-owned `AGENTS.md` baseline.

Validation:
1. `powershell.exe -NoProfile -ExecutionPolicy Bypass -File deployment/windows/test_validate_stage_b_backup_restore.ps1`
2. `python deployment/postgresql/test_stage_b_snapshot.py`
3. `git diff --check -- deployment/windows/validate_stage_b_backup_restore.ps1 deployment/windows/test_validate_stage_b_backup_restore.ps1`
4. `git diff -- deployment/windows/validate_stage_b_backup_restore.ps1 deployment/windows/test_validate_stage_b_backup_restore.ps1`
5. `git diff -- AGENTS.md`
6. `git status --short`
7. Recompute the Planner canonical body hash and verify all three identity fields.
8. Reread `.codex/agents/.implementer/HANDOFF.md`; verify matching metadata, required schema, current-cycle-only evidence, at most 120 lines, and at most 12 KiB.

Acceptance Criteria:
- Execute cannot begin until the pending checksum, recomputed manifest hash, exact execute approval, manifest, and new evidence destination agree.
- Success and failure publish only the exact privacy-safe execution record, atomically as an exact two-file bundle linked to the approved manifest checksum.
- Every named malformed, privacy, tamper, collision, and write failure is directly rejected with no partial final bundle; preflight failures cause zero adapter mutation.
- Validation commands 1-3 exit 0; commands 4-6 show only the two approved cumulative product files, role handoffs, and the accepted unchanged `AGENTS.md` baseline.
- No runtime resource is contacted or mutated; Cleanup remains unchanged, `LIVE_BLOCKED=True` remains true, and criterion 8 remains `not_evaluable`.

Safety Gates:
- Identity mismatch, loss/change of the accepted `AGENTS.md` preamble, or any new working-tree scope is `BLOCKED`: make no product change and route to Planner.
- If TODO 5 requires a Cleanup change, production provider, runtime resource, approval relaxation, or non-allowlisted evidence, stop without broadening scope and route to Planner.
- A failed named validation after implementation is `Outcome: FAIL`, `Status: VALIDATION_FAILED`, and proceeds to Reviewer.

Next Minimum Scope:
- After independent Reviewer verdict and explicit user direction, TODO 6 only: Cleanup restored-state linkage, retained-dump validation, owner/Jobs guards, exact one-drop, final absence proof, and atomic Cleanup evidence.
<!-- PLAN-BODY-END -->
