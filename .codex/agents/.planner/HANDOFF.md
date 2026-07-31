Cycle ID: `S2-CR33-TODO8-ACTIVE-JOBS-ZERO-EVIDENCE-20260731-01`
Plan SHA-256: `39b6e3afa6330f40de7d84c08fa068c8ad93fd90661e140f15ff66261124ab91`
Job ID: `S2-CR33-TODO8-ACTIVE-JOBS-ZERO-EVIDENCE-20260731-01:39b6e3afa6330f40de7d84c08fa068c8ad93fd90661e140f15ff66261124ab91`
<!-- PLAN-BODY-START -->
Outcome: `PASS`

Goal:
- Resolve only CR32 Reviewer finding P1 by producing fresh current-cycle active-Job evidence with the complete required zero-side-effect ledger.
- Reconfirm `queued=0`, `running=0`, and `active=0` in one read-only PostgreSQL snapshot because cross-cycle runtime results are stale evidence.

In Scope:
- One artifact-free read-only psql invocation using the unchanged CR32 SQL.
- Exact result validation plus explicit current-cycle records for Job mutation and service invocation/mutation, along with the previously required zero records.
- External Implementer replaces only its handoff; independent Reviewer later replaces only its handoff.

Deferred Scope:
- Any change to Job or service state; Job IDs/details; polling/waiting; owners/roles; topology; client/server compatibility; storage; HTTP; UNC; backup/restore; recovery; PlanOnly/Execute/Cleanup.
- Product/config edits, tests, install, activation, helper/artifact creation, staging, commit, or push.

Affected Files:
- Planner: `.codex/agents/.planner/HANDOFF.md` only.
- Implementer: `.codex/agents/.implementer/HANDOFF.md` only.
- Reviewer: `.codex/agents/.reviewer/HANDOFF.md` only during independent review.
- PostgreSQL: one read-only transaction statement sequence; all mutation counts remain `0`.

Required Changes:
1. Re-read `AGENTS.md`; recompute this plan hash; verify all metadata, HEAD `dc8e8c1ad15ce81daeb080884adf00575f46022f`, and the six baselines. Missing/mismatched identity is `BLOCKED`.
2. CR32 handoffs and runtime result are context only, never current-cycle evidence. Execute one fresh invocation under this identity; do not copy CR32 validation as the result.
3. Preserve the pre-existing Implementer TOML byte-for-byte at SHA-256 `2056be1f0646b46d6a217fec284138be126e3ebe595e46bc436015e0a20a926f`. Preserve the CR32 Reviewer handoff until Reviewer replaces it; its pre-review hash is `9a130f16c241e3172ce61f0da2ed24c7ef741404ecf051b9dc3f7dbbc2a86a1f`.
4. Before runtime require exactly the four currently tracked modifications: Planner handoff, stale Implementer handoff, frozen Implementer TOML, and stale Reviewer handoff; require no staged, untracked, or conflicted entry. Any other drift is `BLOCKED`.
5. Define active Job only as `public.quality_job.status IN ('queued','running')`. Do not add a predicate, inspect a row, or access Job fields beyond status counts.
6. Derive host, port, database, user, and credential only in memory from the approved pseudoprod runtime configuration at its declared hash. Use fixed PostgreSQL 18 psql and no service, HTTP, ORM, validator, or alternate database.
7. Protect seven source categories in order: host, host-and-port endpoint, port, database, user, credential, absolute psql path. Deduplicate nonempty values ordinally; record counts only and require zero final-handoff matches.
8. Use no helper, temporary SQL/stdout/stderr/JSON/script/log file or directory. Keep SQL/stdout only in shell memory, discard stderr through the platform null sink, and clear PG environment variables in `finally`.
9. Establish an in-memory operation ledger before execution with exactly these counters: psql invocation `0`, PostgreSQL mutation `0`, Job mutation `0`, service invocation `0`, service mutation `0`, product/config edit `0`, runtime artifact creation `0`.
10. Run exactly one physical psql invocation and increment only the psql invocation counter to `1`. No other command, callback, service API/cmdlet, ORM action, or retry may execute after readiness and before final ledger capture.
11. Supply the exact marker SQL below as the single value immediately after `-c`; prohibit stdin/pipeline SQL, `-f`, command substitution, and competing transports. The SQL payload hash must be `09011cf0662f7cd503a87681c2e1773d15e816ae5cef51c5112c9d63ae0f8b97`.
12. Require one compact JSON line with schema `s2-stage-b-active-jobs-v1`, ordered keys `schema,queued_count,running_count,active_count,active_zero`, native values `0,0,0,true`, exact arithmetic, and Boolean equivalence.
13. Classify once: exact exit-0 zero result and exact ledger gives `passed`; valid nonzero/result/ledger mismatch gives `state_mismatch`; otherwise `connect_failed`, `query_failed`, `timeout`, or `shape_failed`. No retry, wait, repair, cleanup, or stale reuse.
14. Implementer handoff must contain exactly one SQL marker pair with the exact SQL, one exact invocation template, and one `sql_payload_sha256` matching both plan and marker bytes.
15. The exact template is `& <psql> -X -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <port> -d <database> -U <user> -c <sql> 2><null_sink>`; each of its seven placeholders occurs exactly once and no actual command/sink appears.
16. Under a `Zero-Side-Effect Ledger:` heading, record each of these exact tokens once: `psql_invocation_count=1`, `pg_mutation=0`, `job_mutation=0`, `service_invocation=0`, `service_mutation=0`, `product_config_edit=0`, `runtime_artifact_creation=0`.
17. The final ledger must be captured after PG environment cleanup and immediately before in-memory handoff assembly. Any nonzero forbidden counter, missing/duplicate token, intervening operation, or inability to substantiate a counter gives `FAIL/VALIDATION_FAILED`.
18. Also record exactly once: `sql_transport=argument`, `sql_option=-c`, `sql_placeholder_count=1`, `null_sink_kind=platform_null_sink`, `template_null_sink=<null_sink>`, `criterion_8=not_evaluable`, `planonly_ready=false`, and `execute_ready=false`.
19. Final handoff may contain only approved schema/key names, enums, counts/Booleans, hashes, zero ledger, placeholder SQL/template, and relative handoff filenames. Exclude connection/config values and paths, Job data, raw stdout/command/error, OIDs, credentials, and actual sink syntax.
20. In-memory privacy scan must report `protected_source_entry_count=7`, unique count `1..7`, conditional token count, and zero protected/sink/pattern matches. Require one marker pair, exact template/mapping, one `-c <sql>`, no competing transport, and no artifacts.
21. Outcome mapping: exact result/ledger/identity/hash/privacy/scope match gives `PASS/COMPLETE`; post-invocation mismatch gives `FAIL/VALIDATION_FAILED`; pre-invocation readiness/scope/baseline failure gives `BLOCKED/BLOCKED`.
22. Replace only Implementer handoff. Before independent review the tracked modified set remains exactly Planner handoff, Implementer handoff, frozen Implementer TOML, and stale Reviewer handoff, with no staged/untracked/conflicted entry.

Canonical SQL:
<!-- REDACTED-SQL-ST -->
BEGIN TRANSACTION READ ONLY;SET LOCAL statement_timeout='15s';SELECT json_build_object('schema','s2-stage-b-active-jobs-v1','queued_count',count(*) FILTER(WHERE status='queued'),'running_count',count(*) FILTER(WHERE status='running'),'active_count',count(*),'active_zero',(count(*)=0))::text FROM public.quality_job WHERE status IN('queued','running');
<!-- REDACTED-SQL-END -->

Validation:
- Planner read `AGENTS.md`, CR32 Reviewer FAIL, current Implementer handoff, HEAD/status/diff-check, and frozen-file hashes. Planner performed no runtime query or implementation.
- Baselines: AGENTS `cfdcf5cfe409358b2c3f5b310d0ff44307a60191618a373c2523c50364525e8d`; bootstrap `dde18bf22df15673066f13b043fe62f849e95ce0c57226f43f4a337428294d86`; runtime env `8f23ef5505413afebc05503014301336e5f18753be8c4db41f9b54f3323b6fc2`; validator `efde112249b259383b736b00fa9b5d7f2093901f0e005b2211d0b5011057ff62`; validator test `faf07d65e86861e8f5a9452331ba5022bf88644d3a1571d8654a6919589ad32c`; deployment README `475c9100c8ec9a215bf1a342a298b7cc93a23c1e2573ca6de9ceada8703acff3`.
- Reviewer independently verifies all metadata/hashes, fresh current-cycle result, exact ledger tokens/counts, protected-token privacy, frozen-file scope, and handoff limits without rerunning PostgreSQL.
- Reread each replaced handoff and require at most 120 lines and 12 KiB normalized UTF-8.

Acceptance Criteria:
- Fresh current-cycle snapshot proves queued `0`, running `0`, active `0`, active-zero `true`.
- Exact ledger proves one psql invocation and zero PostgreSQL/Job/service/product/config/artifact side effects.
- CR32 P1 is fully resolved without expanding the boundary; Reviewer reaches the mandatory user gate.

Safety Gates:
- User authorized only this external-implementation Planner cycle. Planner performs no implementation or runtime access.
- No Job/service action is authorized. A nonzero count or ledger value is evidence, not permission to correct state.
- No product/config edit, helper/artifact, test, staging, commit, push, PlanOnly, Execute, or Cleanup is authorized.

Next Minimum Scope:
- External Implementer executes this plan; independent Reviewer replaces its handoff and stops at the mandatory user gate.
- On Reviewer PASS, the next Planner boundary is exact PostgreSQL client/server compatibility read-only verification. PlanOnly remains blocked.
<!-- PLAN-BODY-END -->
