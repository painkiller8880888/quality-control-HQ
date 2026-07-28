# Reviewer Handoff: S2-CR-08 Approval Finalization

## Review Scope

- `specification/RELEASE.md`
- `runtime/pseudoprod/evidence/s2-cr08-approval-20260728/approval.pending.json`
- `runtime/pseudoprod/evidence/s2-cr08-approval-20260728/checksums.sha256`
- cycle3 canonical dry-run evidence
- canonical module and management command safety gates
- working-tree scope and diff integrity

## Verdict

**PASS**

No blocking finding remains. The approval-finalization cycle satisfies its acceptance criteria. Pipeline stops at the mandatory user decision gate.

## Verified Facts

- Approval JSON parses and its SHA-256 is exactly:
  `9351e79f5f7c418c4c99c0b820621cf5c85d9a32ce93c08663a4ff8eb7892439`.
- Manifest contains exactly one lowercase entry matching that hash and `approval.pending.json`.
- Cycle3 `measurement.json` SHA-256 is:
  `3ff607867d885ef101d837404358a5fc6900b5e9a2722f13697451e99af55417`.
  It matches the approval source reference and cycle3 manifest.
- Source, candidate, and approved CSV hash/count values match.
- All four table counts, four stable hashes, and the InspectionFile path-set hash match across cycle3, candidate, and approved records.
- UNC configured, accessible, and approved count is 7; all seven privacy-safe identities match.
- All six approved threshold objects are semantically identical to their candidate objects.
- `specification/RELEASE.md` records:
  - `approved_for_stage_b`;
  - approval ID and approval date;
  - review deadline and both re-evaluation triggers;
  - Stage B-only scope and no live approval;
  - `LIVE_BLOCKED=True`;
  - criterion 8 remains `not_evaluable`;
  - backup/restore review precedes live A/B.
- The provisional-threshold section is explicitly retained as proposal history and does not override the approved package.
- No raw UNC path, credential, PID/port tuple, or new drive path appears in the reviewed approval artifacts or RELEASE diff.
- `backend/quality/s2_cr08_canonical.py` and the management command retain `LIVE_BLOCKED = True`.
- `git diff --check` passes for the reviewed change.
- No backup/restore or live A/B result was reviewed or authorized by this cycle.

## Blocking Findings

None.

## Unverified Items

- The evidence directory is ignored by Git, so Git history cannot independently prove the approval JSON's pre-edit contents or manifest regeneration. Current hashes establish the required final invariant.
- Static repository inspection cannot prove that prohibited runtime operations were never executed. No reviewed code or evidence change indicates such execution.
- Six deletions under `.codex/agents/*` remain in the working tree. The approved plan identifies them as pre-existing; attribution cannot be independently established from the current tree.
- Stage B runbook, independent empty restore database identity, cleanup owner, rollback responsibility, and actual backup/restore evidence have not yet been reviewed.

## Next Cycle Minimum Recommended Scope

After the user explicitly selects a route, plan Stage B backup/restore validation against an independently identified empty database.

The next planner must define:

- source and restore database privacy-safe identity checks;
- proof that the restore database is empty and distinct from source/production;
- backup tool/version and storage checks;
- service stop/recovery ordering;
- actual dump, checksum, restore-list, and restore verification;
- source/restore count and stable-hash comparison;
- cleanup owner and rollback responsibility;
- evidence schema, privacy checks, and reviewer acceptance criteria.

Do not begin live A/B measurement in the next cycle.

## Safety Gates and Forbidden Changes

- Preserve the approval JSON, approved baselines, thresholds, approvers, approval conditions, and matching manifest.
- Keep module and command `LIVE_BLOCKED=True`.
- Keep criterion 8 `not_evaluable`.
- Require independent reviewer approval of Stage B backup/restore evidence before any live A/B operation.
- Do not submit Jobs, operate services, modify the active database, or execute backup/restore until the next Stage B plan is approved.
- Do not touch the pre-existing `.codex/agents/*` six-file deletion.
- No unrelated refactor, stage, commit, or push.

## Route Conditions

### Codex Implementation

Codex may create the Stage B plan and execute only the scope explicitly authorized by the user. A separate Codex implementer and independent Codex reviewer are required. The reviewer must update this handoff and stop again at the user decision gate.

### External Implementation

An external implementer may receive the same Stage B planner handoff. Codex must not duplicate the implementation while it is external. After external changes and evidence are returned, Codex must independently inspect the actual state before updating this reviewer handoff.

## User Decision Gate

Pipeline stopped after a PASS review. The user must explicitly choose Codex implementation or external implementation before Stage B planning or execution begins.
