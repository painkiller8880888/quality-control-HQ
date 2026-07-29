<plan>
Cycle Metadata:
- Cycle ID: `QC-CONTRACT-20260729-04`
- Plan SHA-256: `aa3e46c9ef3048fd3d1d85d3be3a31a3609426f0d3fe8b07c35b11fed7fe5084`
- Job ID: `QC-CONTRACT-20260729-04:aa3e46c9ef3048fd3d1d85d3be3a31a3609426f0d3fe8b07c35b11fed7fe5084`
- Hash rule: normalize the entire handoff from CRLF/CR to LF, then hash the UTF-8 bytes after the exact token `<!-- PLAN-BODY-START -->\n` through the byte before the exact token `\n<!-- PLAN-BODY-END -->`; exclude both markers and both boundary newlines.

<!-- PLAN-BODY-START -->
Outcome: `PASS`

Goal:
Produce complete, exact, current-cycle validation evidence for the already-compliant repository-local agent workflow contract.

In Scope:
- One independently reviewable behavior boundary: evidence compliance for the authorized non-empty product/config diff in `AGENTS.md`, `planner.toml`, `implementer.toml`, and `reviewer.toml`.
- Retain that existing product/config diff unchanged and independently rerun the exact validations below.
- Replace `.codex/agents/.implementer/HANDOFF.md` with current-cycle evidence; its prior content must not be preserved or cited.

Out of Scope / Deferred Scope:
- Product/config edits are prohibited. If independent inspection finds a defect that makes continuation impossible, make no product/config change and return `BLOCKED` to Planner with the exact failing behavior.
- Do not modify installed `.codex/agents/.planner/planner.toml`, `.codex/agents/.implementer/implementer.toml`, or `.codex/agents/.reviewer/reviewer.toml`.
- No other files, runtime tests, activation, installation, services, dependencies, staging, commits, or pushes.

Constraints:
- Preserve the authorized product/config bytes and all unrelated working-tree content.
- Evidence must remain exact while fitting the Implementer handoff limits.

Affected Files:
- Authorized existing product scope, read/validate only: `AGENTS.md`, `planner.toml`, `implementer.toml`, `reviewer.toml`.
- Required role output: `.codex/agents/.implementer/HANDOFF.md` (replace).

Required Changes:
1. Verify this plan's Cycle ID, canonical Plan SHA-256, and Job ID before relying on it.
2. Run every command in Validation exactly as printed, in repository root, without abbreviating it. Record the full command text, exit code, and concise current-cycle result in the Implementer handoff.
3. Do not use ellipses, placeholders, omitted script bodies, heredocs, or here-strings in command evidence. Do not claim an earlier cycle's result.
4. Product Changes must identify the authorized existing non-empty four-file diff and state that this evidence-only cycle made no additional product/config edits.
5. Replace the Implementer handoff using the canonical schema and matching cycle metadata. Use `Outcome: PASS` and `Status: COMPLETE` only if every command succeeds and the final handoff passes its post-write checks.

Validation:
1. `python -c "import pathlib,tomllib; [tomllib.loads(pathlib.Path(p).read_text(encoding='utf-8')) for p in ('planner.toml','implementer.toml','reviewer.toml')]"`
2. `Get-Content -LiteralPath 'AGENTS.md','planner.toml','implementer.toml','reviewer.toml' -Encoding UTF8 | Out-Null`
3. `$p=Get-Content -LiteralPath '.codex/agents/.planner/HANDOFF.md' -Raw -Encoding UTF8; $n=$p.Replace("`r`n","`n").Replace("`r","`n"); $a="<!-- PLAN-BODY-START -->`n"; $b="`n<!-- PLAN-BODY-END -->"; $i=$n.IndexOf($a); $j=$n.IndexOf($b,$i+$a.Length); if($i -lt 0 -or $j -lt 0){exit 1}; $x=$n.Substring($i+$a.Length,$j-($i+$a.Length)); $s=[Security.Cryptography.SHA256]::Create(); $h=([BitConverter]::ToString($s.ComputeHash([Text.Encoding]::UTF8.GetBytes($x)))).Replace('-','').ToLowerInvariant(); $d=[regex]::Match($p,'Plan SHA-256: `([0-9a-f]{64})`').Groups[1].Value; $q=[regex]::Match($p,'Job ID: `QC-CONTRACT-20260729-04:([0-9a-f]{64})`').Groups[1].Value; if($h -cne $d -or $h -cne $q){exit 1}`
4. `rg -n "Cycle ID|Plan SHA-256|Job ID|120 lines|12 KiB|200 lines|16 KiB|40 lines|4 KiB" AGENTS.md`
5. `rg -n "Every new feature or fix starts with Planner|VALIDATION_FAILED|required result|finish/accept|BLOCKED" AGENTS.md`
6. `rg -n "^(role|model|reasoning_effort|objective|authority|write_boundary|behavior|output_wrapper) =" planner.toml implementer.toml reviewer.toml`
7. `git diff --check -- AGENTS.md planner.toml implementer.toml reviewer.toml`
8. `git diff --exit-code -- .codex/agents/.planner/planner.toml .codex/agents/.implementer/implementer.toml .codex/agents/.reviewer/reviewer.toml`
9. `git status --short`
10. `git diff -- AGENTS.md`
11. After the Implementer handoff contains the full evidence above, run and record: `$p='.codex/agents/.implementer/HANDOFF.md'; $r=Get-Content -LiteralPath $p -Raw -Encoding UTF8; $q=Get-Content -LiteralPath '.codex/agents/.planner/HANDOFF.md' -Raw -Encoding UTF8; $h=[regex]::Match($q,'Plan SHA-256: `([0-9a-f]{64})`').Groups[1].Value; $l=(Get-Content -LiteralPath $p -Encoding UTF8).Count; $b=[Text.Encoding]::UTF8.GetByteCount($r); if($l -gt 120 -or $b -gt 12288 -or $r -notmatch 'QC-CONTRACT-20260729-04' -or $r -notmatch [regex]::Escape($h)){exit 1}; Write-Output "LINES=$l BYTES=$b"`

Acceptance Criteria:
- Commands 1–11 appear verbatim and unabridged in the Implementer handoff with exit codes and current-cycle results; command evidence contains no ellipsis, substitution token, or omitted body.
- The authorized four-file product/config diff remains non-empty and unchanged by this cycle, all validations pass, and installed TOMLs remain untouched.
- The final Implementer handoff uses cycle `QC-CONTRACT-20260729-04`, the canonical plan hash/job identity, current-cycle-only evidence, and no stale content.
- Final Implementer handoff is at most 120 lines and 12 KiB; its recorded size result is followed by an unchanged-file rerun confirming the same values.

Safety Gates:
- Cycle Sizing Gate: PASS. This is one evidence-only correction boundary with fixed commands and no product/config implementation.
- If any command exposes a product/config defect, unexpected scope change, or failed validation, do not repair it in this cycle; return the cause-specific `BLOCKED` or `VALIDATION_FAILED` result required by `AGENTS.md`.

Risks:
- The only known failure mode is evidence abbreviation or self-inconsistent post-write size reporting; verbatim commands and an unchanged-file final rerun are mandatory.

Next Minimum Scope:
- Current cycle: exact evidence regeneration only.
- After Reviewer `PASS`, the user may finish/accept; any product correction or activation starts with a new Planner cycle.
<!-- PLAN-BODY-END -->
</plan>
