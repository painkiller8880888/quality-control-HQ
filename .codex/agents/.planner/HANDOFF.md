Cycle ID: `S2-CR30-TODO8-WORKTREE-RECOVERY-20260731-01`
Plan SHA-256: `79149b1635530fcbadf8ec3596309904dc8fe1b6d738e34e0823852095a9376d`
Job ID: `S2-CR30-TODO8-WORKTREE-RECOVERY-20260731-01:79149b1635530fcbadf8ec3596309904dc8fe1b6d738e34e0823852095a9376d`
<!-- PLAN-BODY-START -->
Outcome: `PASS`

Goal:
- Recover the working tree from the CR29 scope/artifact defect.
- Remove only the three verified untracked helper artifacts and restore the exact five-file modified scope before any further release validation.

In Scope:
- Read-only identity/scope checks, exact metadata checks for three untracked files, their guarded deletion, and post-deletion scope verification.
- External Implementer replaces only its current-cycle handoff; independent Reviewer later replaces its handoff.

Deferred Scope:
- PostgreSQL access, password/role validation or repair, privacy-probe correction, topology, Jobs, clients, storage, services, evidence/recovery, and all PlanOnly/Execute/Cleanup work.
- Product/config edits, test execution, install, activation, staging, commit, push, and creation of any replacement helper or evidence artifact.

Affected Files:
- Planner: `.codex/agents/.planner/HANDOFF.md` only.
- Implementer: `.codex/agents/.implementer/HANDOFF.md` only.
- Reviewer: `.codex/agents/.reviewer/HANDOFF.md` only.
- Delete exactly these untracked root files after every guard passes: `check_pwd.ps1`, `check_pwd2.ps1`, `compute_hash.ps1`.
- Preserve unchanged the two modified Stage B PowerShell files and every other workspace path.

Required Changes:
1. Re-read `AGENTS.md`; recompute this handoff hash; verify metadata agreement and HEAD `2c5e854d1fe7edafd4527215525afb4459a962e4`.
2. Require the exact starting scope: five modified files—the three handoffs plus the two Stage B PowerShell files—and exactly three untracked files named above. Any other tracked, untracked, ignored-relevant, staged, conflicted, renamed, or deleted entry is `BLOCKED`; delete nothing.
3. Resolve each deletion target to an absolute path and require it equals the workspace root joined with its declared filename. Require a regular non-directory file, no reparse point/link, and no path traversal.
4. Without executing or displaying contents, verify exact size/hash pairs: `check_pwd.ps1` 445 bytes / `80cf1574f6cc2c21afc3aab4d42c96964e0c13a176319179f44887eccee8cad1`; `check_pwd2.ps1` 372 bytes / `20c4ffe85ef259442be1ccdd31977726f169d8c2a9facb865303aff53108b898`; `compute_hash.ps1` 1717 bytes / `9f5d7bcae0bc2cc41d13a70a726d0f076935b5cc6453784b72d7707459fb00d2`. Any mismatch is `BLOCKED`; delete nothing.
5. Record that these files are untracked and deletion is not recoverable from Git. The external Implementer is authorized to delete only these three exact verified artifacts for this recovery cycle.
6. Delete each verified file with native PowerShell `Remove-Item -LiteralPath` using explicit resolved paths, non-recursively. Do not use globs, environment-variable targets, another shell, or broad cleanup commands.
7. If any deletion fails after an attempt, stop immediately, report which declared filename remains without exposing contents, make no further change, and map to `FAIL/VALIDATION_FAILED`.
8. After deletion, require all three targets absent and `git status --porcelain=v1 --untracked-files=all` shows exactly the five expected modified files and no other entry.
9. Recompute all six baselines; require exact matches. Confirm no content change to the two Stage B files beyond their preserved pre-existing hashes.
10. Do not read helper contents, run scripts/tests/runtime, access PostgreSQL/services, alter any tracked product/config file, create files/directories, or stage/commit/push.
11. Replace only Implementer handoff. Record exact read-only/preflight/delete/postflight commands and exit codes, three deletion results, final exact five-file scope, zero created artifacts, zero product/config edits, zero PostgreSQL/service invocations or mutations, and `planonly_ready=false`, `execute_ready=false`, `criterion_8=not_evaluable`.
12. Outcome mapping: exact guarded deletion and exact post-scope → `PASS/COMPLETE`; attempted deletion with failed postcondition → `FAIL/VALIDATION_FAILED`; any preflight identity/scope/path/type/hash/size defect → `BLOCKED/BLOCKED` with no deletion.

Validation:
- Planner read `AGENTS.md`, current Reviewer BLOCKED findings, HEAD, actual eight-entry scope, target metadata, and baselines. It did not open helper contents or delete anything.
- Current targets are ordinary untracked files with the exact sizes/hashes declared above; current starting scope is exactly five modified plus those three untracked files.
- Baselines: AGENTS `cfdcf5cfe409358b2c3f5b310d0ff44307a60191618a373c2523c50364525e8d`; bootstrap `dde18bf22df15673066f13b043fe62f849e95ce0c57226f43f4a337428294d86`; runtime env `8f23ef5505413afebc05503014301336e5f18753be8c4db41f9b54f3323b6fc2`; validator `efde112249b259383b736b00fa9b5d7f2093901f0e005b2211d0b5011057ff62`; test `faf07d65e86861e8f5a9452331ba5022bf88644d3a1571d8654a6919589ad32c`; deployment README `475c9100c8ec9a215bf1a342a298b7cc93a23c1e2573ca6de9ceada8703acff3`.
- Independent Reviewer verifies target absence, exact five-file scope, identities, baselines, and that no runtime/product change occurred.
- After every handoff replacement, reread it and require at most 120 lines and 12 KiB.

Acceptance Criteria:
- Exactly the three declared untracked artifacts are absent.
- Working tree contains exactly the five expected modified files, with HEAD and all six baselines unchanged.
- No helper content was exposed or executed; no replacement artifact, runtime access, product/config change, staging, commit, or push occurred.

Safety Gates:
- User requested only an external-implementation Planner handoff. Planner performs no runtime access or implementation.
- Deletion authority is limited to the three exact untracked files after all guards pass. Any mismatch or additional target is `BLOCKED`.
- Do not reuse CR29 runtime/privacy/state claims as evidence or authorization.

Next Minimum Scope:
- External Implementer performs only guarded recovery; independent Reviewer replaces its handoff and stops at the mandatory user gate.
- On Reviewer PASS, start a new Planner cycle to establish the canonical approved owner identities/source and fresh read-only password state. PlanOnly remains blocked.
<!-- PLAN-BODY-END -->
