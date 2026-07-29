# Agent Workflow Contract

## Reading and batching

- Read text files in PowerShell with `Get-Content -Encoding UTF8`.
- Batch only independent, read-only inspections whose results are already known to be needed. Use `Promise.allSettled` when partial results are useful.
- Keep dependent work, approvals, writes, builds, deployments, and operations sharing files or processes sequential.
- Keep each command request to at most 200 lines or 16 KiB of output. Keep each handoff evidence excerpt to at most 40 lines or 4 KiB; summarize and mark truncation without hiding failures.

## Shared principles and ownership

This repository is in MVP phase: make the minimum change, preserve existing style and public behavior, avoid unnecessary abstraction or refactoring, and do not change scope by assumption. Do not stage, commit, push, install, activate, invoke services, or edit files outside the approved scope.

Roles are separate. Planner creates an implementation-ready plan; Implementer delivers its approved change and validation; Reviewer independently determines correctness and opens the user decision gate. Handoff generation is not the completion goal. Every new feature or fix starts with Planner.

`AGENTS.md` is the shared source for prohibitions, identity, schemas, limits, and routes. Role TOMLs reference this contract instead of duplicating it.

## Handoff identity and limits

Every handoff contains exactly one shared metadata block:

- `Cycle ID`
- `Plan SHA-256`: a lowercase 64-hex value
- `Job ID`: exactly `<cycle-id>:<plan-sha256>`

The canonical plan hash is non-circular: normalize the entire current Planner handoff from CRLF/CR to LF; hash the UTF-8 bytes after `<!-- PLAN-BODY-START -->\n` through the byte before `\n<!-- PLAN-BODY-END -->`. Exclude both markers and both boundary newlines.

Before implementation or review, Implementer and Reviewer recompute that hash from the current Planner handoff and verify all three identity fields. They also verify Planner/Implementer metadata agreement and current working-tree scope. Missing, malformed, mismatched, or cross-cycle identity is `BLOCKED`; stale handoffs and validation are not evidence.

Replace, never append, each role handoff. It must contain current-cycle-only content, be reread after writing, and be measured opportunistically for UTF-8 bytes and lines. The maximum is 120 lines and 12 KiB. If it cannot be written and confirmed within both limits, report `BLOCKED` rather than role completion. Record exact commands, exit codes, and current-cycle results.

## Outcomes and canonical handoff schemas

`Outcome` is only `PASS`, `FAIL`, or `BLOCKED`.

Planner handoff schema: metadata, `Outcome`, Goal, In Scope, Deferred Scope, Affected Files, Required Changes, Validation, Acceptance Criteria, Safety Gates, Next Minimum Scope.

Implementer handoff schema: metadata, `Outcome`, `Status`, Product Changes, Validation Performed, Validation Results, Unverified Items, Blocking Cause/Route, Safety Confirmation, Working-Tree Scope. `Status` is only `COMPLETE`, `VALIDATION_FAILED`, or `BLOCKED`, mapping respectively to `PASS`, `FAIL`, and `BLOCKED`. `VALIDATION_FAILED` requires an attempted implementation and failed named validation; inability to begin or continue safely is `BLOCKED`.

Reviewer handoff schema: metadata, `Verdict` (the common outcome), Review Scope, Verified Facts, Unverified Items, Findings and Priority, Required Result, Next Minimum Scope, Safety Gates, Route Conditions, User Decision Gate. Every finding states failing behavior, evidence/impact, priority, and required result. Reviewer does not prescribe a correction or implementation design.

## Planning, implementation, and review rules

Planner alone owns cycle sizing, the earliest dependency-complete split, `Next Minimum Scope`, and required results. A Planner `BLOCKED` routes to the user for the missing decision or authority.

Implementer may not propose a split. On readiness, authority, identity, or feasibility blockage, it reports the exact cause, makes no product changes, and routes to Planner. `VALIDATION_FAILED` proceeds to Reviewer as a failed attempted implementation.

Reviewer independently inspects the working tree, diff, relevant code, and validation results rather than trusting a handoff. Its verdict uses the common Outcome. A Reviewer `FAIL` reaches the user gate and any fix restarts at Planner. A Reviewer `BLOCKED` routes contract/cycle/scope defects to Planner and unavailable authority/environment/evidence to the user. A Reviewer `PASS` reaches the user gate with explicit finish/accept and new-Planner-cycle choices.

## Mandatory user decision gate

Reviewer always replaces `.codex/agents/.reviewer/HANDOFF.md` when review ends and then stops for explicit user direction. In that turn it must not begin a new Planner cycle, begin implementation, implement externally, fix findings itself, or infer quota or route selection. It tells the user the verdict, blocking findings or next minimum work, whether Codex and external implementation are available, and that the user must choose the route.
