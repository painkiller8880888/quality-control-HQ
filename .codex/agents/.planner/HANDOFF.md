Cycle ID: `S2-CR31-TODO8-CANONICAL-OWNER-PASSWORD-STATE-20260731-01`
Plan SHA-256: `89a8f15e0e3d48da9081f6174699669c01fbf6fa44e3d8f75b2712e82f5a745b`
Job ID: `S2-CR31-TODO8-CANONICAL-OWNER-PASSWORD-STATE-20260731-01:89a8f15e0e3d48da9081f6174699669c01fbf6fa44e3d8f75b2712e82f5a745b`
<!-- PLAN-BODY-START -->
Outcome: `PASS`

Goal:
- Establish an unambiguous canonical source for the two Stage B owner identities.
- Obtain fresh, authoritative, read-only password-null state for exactly those identities without privacy leakage or artifacts.

In Scope:
- Planner-bound owner identity/source proof, static readiness, one in-memory `pg_authid` invocation, password nullness/counts, payload linkage, privacy, and handoff validation.
- External Implementer replaces only its current-cycle handoff; independent Reviewer later replaces its handoff.

Deferred Scope:
- Other role attributes/memberships, role repair, topology, Jobs, clients, storage, services, evidence/recovery, and PlanOnly/Execute/Cleanup.
- Database creation, backup/restore, login tests, product/config edits, tests, install, activation, staging, commit, push, and durable/runtime artifacts.

Affected Files:
- Planner: `.codex/agents/.planner/HANDOFF.md` only.
- Implementer: `.codex/agents/.implementer/HANDOFF.md` only.
- Reviewer: `.codex/agents/.reviewer/HANDOFF.md` only.
- PostgreSQL: one read-only catalog transaction only; mutation count remains `0`.

Required Changes:
1. Re-read `AGENTS.md`; recompute this handoff hash; verify all metadata, clean starting tree at HEAD `591af5f5b74d6c7362bd9a96a674a4331d1389a0`, and all six baselines. After this Planner replacement, require only Planner handoff modified; before runtime, after Implementer replacement is prepared in memory, require only Planner handoff modified and no untracked/staged/conflicted entry.
2. Canonical identity source is this Planner plan body, not deployment/migration variables, database discovery, CR29, or inference. Restore owner is exactly `restore_db_owner`; cleanup owner is exactly `cleanup_db_owner`; they are distinct. Their UTF-8 SHA-256 values are respectively `6910bec65712448bfcafdfeb9667d356bf620ebcd863dc19ff994bb0642ac092` and `7fec20f221f11b386f809e9ffbb2a4eec2e78a0b4cee9cb28f35e968a7156bcb`.
3. Implementer final handoff must record only `owner_identity_source=planner_plan_body`, `restore_owner_sha256=<declared restore hash>`, `cleanup_owner_sha256=<declared cleanup hash>`, and `owner_hashes_distinct=true`; never record either raw owner literal.
4. Derive connection inputs only in memory from approved deployment configuration. Use fixed maintenance database `postgres`, loopback/agreed endpoint, nonempty administrative inputs, and fixed PostgreSQL 18 psql. Do not infer owner identities from any connection/config value.
5. Before runtime create nine protected source entries in exact category order: host, host-and-port endpoint, port, maintenance database, administrator, credential, restore owner, cleanup owner, absolute psql path. Deduplicate ordinally to exactly eight base unique tokens. A count mismatch is `BLOCKED`.
6. Use no helper, temporary SQL/stdout/stderr/JSON/script/log file or directory. Hold SQL/stdout only in shell memory, discard stderr through the platform null sink, and clear PG environment variables in `finally`. Any runtime artifact is `BLOCKED`.
7. Construct SQL only by substituting the two Planner-declared owner literals into the marker-form SQL placeholders. Run exactly one physical psql invocation, no retry, with the in-memory SQL as the single value immediately after `-c`; prohibit stdin/pipeline SQL, `-f`, command substitution, and competing transport.
8. Query `pg_authid` only in `BEGIN TRANSACTION READ ONLY` with local 15-second timeout; filter exactly the two canonical owners and expose administrator authority only as a Boolean.
9. Return one compact JSON line with schema `s2-stage-b-canonical-owner-password-v1` and ordered keys `schema,admin_ok,exact_role_count,restore_count,restore_password_is_null,cleanup_count,cleanup_password_is_null,password_contract_ok`; require native values `true,2,1,true,1,true,true`.
10. A non-singleton owner returns JSON null for that password field and contract false. Classify once: exact exit-0 match → `passed`; valid nonmatch → `state_mismatch`; otherwise `connect_failed`, `query_failed`, `timeout`, or `shape_failed`. No retry, repair, second query, or stale-result reuse.
11. Include exactly one literal redacted-SQL marker pair in Implementer handoff; do not repeat either literal marker string in prose. Between it place complete SQL with owner literals replaced only by `<restore_role>` and `<cleanup_role>`.
12. Canonical marker hash: normalize whole Implementer handoff CRLF/CR to LF; hash UTF-8 bytes inside the marker boundaries excluding markers and boundary newlines. Record it once as redacted SQL hash.
13. Reconstruct raw SQL by exact placeholder substitution, hash its UTF-8 bytes, and record `raw_sql_payload_sha256=<hash>` without recording raw SQL. Reviewer independently reconstructs the same raw payload from this Planner and the marker block; this proves exact canonical identities were queried.
14. Record exactly one line `Exact redacted invocation template:` followed by backtick-delimited `& <psql> -X -q -A -t -v ON_ERROR_STOP=1 -h <host> -p <port> -d <maintenance_database> -U <admin> -c <sql> 2><null_sink>`. Require byte equality and each of its seven placeholders exactly once.
15. Record mapping only as `sql_transport=argument`, `sql_option=-c`, `sql_placeholder_count=1`, `null_sink_kind=platform_null_sink`, `template_null_sink=<null_sink>`, `redacted_sql_sha256=<marker hash>`, and `raw_sql_payload_sha256=<raw hash>`. Never record actual sink syntax or raw command.
16. Final handoff may contain only approved enums, counts, Booleans, schema/key names, hashes, placeholder SQL/template, exit category, relative role-handoff filenames, and zero counts. Do not record source/config paths, resolved values/paths, raw stdout/commands/errors, owner literals, OIDs, credentials, or actual sink syntax.
17. After assembling the complete final handoff in memory, ordinal-scan all bytes against all eight base unique tokens, conditional raw-error/OID tokens, and actual sink token; scan privacy patterns; require zero matches. Require exactly one marker pair, exact template/mapping, one `-c <sql>`, and no competing transport.
18. Report privacy only as `protected_source_entry_count=9`, `protected_base_unique_count=8`, `conditional_protected_token_count=<nonnegative integer>`, `protected_match_count=0`, `actual_null_sink_match_count=0`, `privacy_pattern_match_count=0`, `privacy_scan_ok=true`.
19. Outcome mapping: exact state/identity/linkage/privacy/artifact match → `PASS/COMPLETE`; state/shape/privacy/hash/linkage mismatch after invocation → `FAIL/VALIDATION_FAILED`; readiness/scope/count/no-artifact failure before invocation → `BLOCKED/BLOCKED`.
20. Replace only Implementer handoff; final scope must be exactly Planner and Implementer handoffs modified, with no other entry. Record PostgreSQL mutation `0`, service invocation/mutation `0`, product/config edit `0`, runtime artifact creation `0`, `planonly_ready=false`, `execute_ready=false`, and `criterion_8=not_evaluable`.

Validation:
- Planner read `AGENTS.md`, Reviewer PASS, current HEAD/status, tracked deployment owner references, and baselines. Working tree was clean before this Planner replacement; no runtime probe ran.
- Tracked deployment source defines migration identities but does not define either canonical backup/restore owner literal. Therefore this hashed Planner body is the explicit source contract; CR29 identity/state evidence is rejected.
- Baselines: AGENTS `cfdcf5cfe409358b2c3f5b310d0ff44307a60191618a373c2523c50364525e8d`; bootstrap `dde18bf22df15673066f13b043fe62f849e95ce0c57226f43f4a337428294d86`; runtime env `8f23ef5505413afebc05503014301336e5f18753be8c4db41f9b54f3323b6fc2`; validator `efde112249b259383b736b00fa9b5d7f2093901f0e005b2211d0b5011057ff62`; test `faf07d65e86861e8f5a9452331ba5022bf88644d3a1571d8654a6919589ad32c`; deployment README `475c9100c8ec9a215bf1a342a298b7cc93a23c1e2573ca6de9ceada8703acff3`.
- Reviewer independently reconstructs both owner hashes and raw SQL payload from this plan plus the marker block, then verifies identity, scope, baselines, marker/template/mapping/privacy, and result without rerunning runtime.
- After every handoff replacement, reread it and require at most 120 lines and 12 KiB.

Acceptance Criteria:
- Planner-bound canonical owner identities and source are unambiguous and hash-verifiable.
- One fresh artifact-free authoritative invocation proves the exact two-owner counts and password-null state.
- Reviewer reproduces owner hashes, marker hash, raw SQL payload hash, exact template/mapping, zero privacy matches, and exact final scope.

Safety Gates:
- User requested only an external-implementation Planner handoff. Planner performs no runtime access or implementation.
- No mutation, role repair, helper creation, product/config edit, service access, staging, commit, or push is authorized.
- Any inferred/noncanonical owner, raw disclosure, extra invocation, artifact, or scope deviation is `BLOCKED`; CR29 is not evidence.

Next Minimum Scope:
- External Implementer executes this plan; independent Reviewer replaces its handoff and stops at the mandatory user gate.
- On Reviewer PASS, the next Planner boundary is exact active-Job `queued`/`running` verification. PlanOnly remains blocked.
<!-- PLAN-BODY-END -->
