# Planner Handoff: S2-CR-08 Approval Finalization

## Goal

Finalize the approved Stage B package record by correcting the RELEASE status and regenerating the approval manifest, then hand the result to an independent reviewer.

## Approved Scope

- Edit `specification/RELEASE.md`.
- Edit `runtime/pseudoprod/evidence/s2-cr08-approval-20260728/checksums.sha256`.
- Treat `runtime/pseudoprod/evidence/s2-cr08-approval-20260728/approval.pending.json` as read-only.
- Write the implementer handoff to `.codex/agent/.implementer/HANDOFF.md`.

## Required Changes

1. Before editing, verify that `approval.pending.json` SHA-256 is:
   `9351e79f5f7c418c4c99c0b820621cf5c85d9a32ce93c08663a4ff8eb7892439`.
   Stop without changing approval content if it differs.
2. Update the S2-CR-08 P2 approval-package record in `specification/RELEASE.md` so it accurately records:
   - package status `approved_for_stage_b`;
   - approval ID `QCHQ-20260728-0001`;
   - approval date `2026-07-28`;
   - review deadline `2026-08-21`;
   - re-evaluation at the earlier of three successful same-condition canonical A/B run pairs or `2026-08-21`;
   - immediate re-review after one fail threshold or two consecutive warning results;
   - approved baseline, UNC identities, six threshold definitions, and responsible approvals are recorded in the package;
   - approval is limited to Stage B and is not live approval;
   - `LIVE_BLOCKED=True`, criterion 8 remains `not_evaluable`, and backup/restore review must precede live A/B;
   - the later provisional-threshold section is retained as the proposal history and does not override the approved package.
3. Do not modify `approval.pending.json`.
4. Regenerate `checksums.sha256` from the final approval JSON as exactly one lowercase entry:
   `9351e79f5f7c418c4c99c0b820621cf5c85d9a32ce93c08663a4ff8eb7892439  approval.pending.json`
5. Write `.codex/agent/.implementer/HANDOFF.md` with exact changes and validation results.

## Acceptance Checks

- Approval JSON parses and its pre/post SHA-256 remains the reviewed value.
- Manifest has one entry and matches the current approval JSON.
- RELEASE and the approved package agree on status, approval metadata, re-evaluation triggers, Stage B limitation, `LIVE_BLOCKED=True`, and `not_evaluable`.
- Approved baseline, counts, hashes, UNC identities, and all six threshold objects remain unchanged and match cycle3 evidence/candidates.
- No raw UNC path, drive path, credential, or PID/port tuple is added.
- Both canonical module and management command retain `LIVE_BLOCKED = True`.
- Scoped product/evidence changes are limited to RELEASE and the manifest.
- `git diff --check` reports no whitespace errors in changed scoped files.

## Safety Stops

- Do not change approved values, approvers, approval conditions, or the approval JSON filename.
- Do not run backup/restore, submit Jobs, operate services, modify the DB, run canonical dry-run, or execute live A/B.
- Do not touch the pre-existing `.codex/agents/*` six-file deletion.
- Do not stage, commit, push, or perform unrelated refactors.
- Stop after the implementer handoff and wait for independent review.
