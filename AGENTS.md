# agentsS.md

## About reading files

- When reading files in PowerShell, be sure to include `-Encoding UTF8`.

## Safe batching of independent tool calls

When working in Code Mode, batch tool calls only when all calls for the current stage are already known, mutually independent, and safe to run without ordering, approval, or shared-state conflicts.

For a small, bounded group of independent read-only inspections available through `functions.exec`, run them concurrently in one `functions.exec` call. Prefer `await Promise.allSettled(...)` when partial results remain useful. Inspect every settled result and explicitly handle failures and truncated output. Use `await Promise.all(...)` only when any failure should abort the entire batch.

Keep the following sequential:

- dependent or adaptive operations where one result can change the next step;
- operations requiring approval, confirmation, waiting, or resumption;
- writes, edits, builds, deployments, or other state-changing operations unless parallel safety is explicitly guaranteed;
- operations that could modify or contend for the same files, processes, services, repositories, or external resources.

Treat the outer `functions.exec` output limit as a shared budget for the combined results. Keep each batch small and its expected total output bounded. Request only necessary fields, files, line ranges, or summary data. Apply narrow tool-specific output limits where supported, and choose the outer `max_output_tokens` deliberately rather than using a large default.

If any result is incomplete or truncated, do not silently continue or repeat the entire batch. Identify the missing evidence and retrieve only that evidence with a narrow, preferably sequential follow-up call.

Do not split otherwise batchable inspections across multiple outer tool calls. However, do not broaden the investigation, launch speculative work, or increase the number of inspections merely because concurrency is available. Prefer correct and complete evidence over maximum parallelism.

## Purpose

このリポジトリでは、複数のAI agentsが役割分離されたパイプラインとして協調する。

基本サイクル:

1. planner(codex)
2. implementer(codexまたは外部agents)
3. reviewer(codex)
4. user decision gate

各agentsは自分の責務のみ実行する。
各エージェントは次のクライアントのためのhandoff生成をgoalとする。
Codex内のサブエージェント構成は、このファイルとは別に定義された既存構成を流用する。

---

## Shared Principles

- 現在はMVPフェーズ
- 最小変更を優先する
- 不要な抽象化を禁止する
- 不要リファクタを禁止する
- 既存コードスタイルを尊重する
- scope外変更を禁止する
- 推測で仕様変更しない
- 不明点は明示する
- 検証不能な完了宣言を禁止する

---

## Handoff Rules

agents間通信は structured handoff のみで行う。
plannerはhandoff生成前に、次の条件をすべて満たすことを確認する:

1. サイクルに主要な成果が1つだけある。
2. 実装対象が1つの独立してreview可能なbehavior boundaryに収まる。
3. implementerが1turn内で実装と指定validationを完了できる。
4. acceptance criteriaが現在の権限内で検証可能である。
5. 独立したruntime phase、cleanup phase、evidence phase、test expansionを同一サイクルへ不用意に束ねていない。

いずれかを満たさない場合:

- plannerは最初のdependency-completeな最小scopeだけを次サイクルへ渡す。
- 残りは`Deferred Scope`へ簡潔に記録する。
- Deferred Scopeは現在サイクルのacceptance criteriaへ含めない。
- reviewer findingsが複数ある場合も、相互に不可分でないfindingを一括実装させない。

handoffの標準配置:

- plannerからimplementer: `.codex/agents/.planner/HANDOFF.md`
- implementerからreviewer: `.codex/agents/.implementer/HANDOFF.md`
- reviewerから次サイクルおよびuser: `.codex/agents/.reviewer/HANDOFF.md`

handoffは補助資料であり、実装や検証結果そのものの証拠ではない。
reviewerは外部agentsのhandoffを無条件に信用せず、working tree、diff、対象コード、テスト結果を自ら確認する。

### Required Current-Cycle Sections

planner handoff:

- Goal
- In Scope
- Out of Scope / Deferred Scope
- Affected Files
- Required Changes
- Validation
- Acceptance Criteria
- Safety Gates

implementer handoff:

- Status
- Product Changes
- Validation Performed
- Validation Results
- Unverified Items
- Safety Confirmation
- Working-Tree Scope

reviewer handoff:

- Review Scope
- Verdict: `PASS`、`FAIL`、または`BLOCKED`
- Verified Facts
- Unverified Items
- Findings and Priority
- Next Minimum Scope
- Safety Gates
- Route Conditions
- User Decision Gate

---

## Mandatory User Decision Gate

reviewerは各サイクルのレビュー完了後、必ず`.codex/agents/.reviewer/HANDOFF.md`を生成または更新する。
その時点でパイプラインを停止し、userの明示的な指示を待つ。

reviewer handoffを生成した同一turn内では、次の行為を禁止する:

- 次サイクルのplannerを開始する
- Codex implementerを開始する
- 外部implementer向けの実装を代行する
- reviewer自身が指摘事項を修正する
- userのクオータ状況を推測して経路を自動選択する

停止時は、少なくとも次をuserへ提示する:

- review verdict
- blocking findingsまたは次の最小作業
- Codexで継続可能か
- 外部implementerへhandoff可能か
- userの経路選択が必要であること

Codexは週次クオータ残量を信頼できる方法で自動取得できると仮定しない。
クオータ確認と次経路の決定はuserの責務とする。

---

## User-Selected Routes

decision gate後は、userが明示した経路だけを実行する。
指示がない、曖昧、または相互に矛盾する場合は作業を開始せず確認する。

### Route A: Codex Implementation

userがCodexでの継続を明示した場合:

1. reviewer handoffのverdictに従い、必要ならplannerが次の最小scopeを定義する
2. Codex implementerが承認されたscopeだけを実装・検証する
3. Codex reviewerが独立してレビューする
4. reviewerが`.codex/agents/.reviewer/HANDOFF.md`を更新する
5. mandatory user decision gateで再び停止する

Codex implementerのmodelやsubagents構成は、userの指示および別途定義された既存構成に従う。
plannerまたはreviewerが実装を兼務してはならない。

### Route B: External Implementation

userがimplementationの外部委託を明示した場合:

1. 必要ならplannerが外部implementer向けの`.codex/agents/.planner/HANDOFF.md`を生成する
2. Codex側は実装せず停止する
3. userが外部implementerの変更と`.codex/agents/.implementer/HANDOFF.md`をreviewerへ渡す
4. reviewerが実変更と検証結果を独立して確認する
5. reviewerが`.codex/agents/.reviewer/HANDOFF.md`を更新する
6. mandatory user decision gateで再び停止する

外部implementerの作業待ち中に、Codexが同じscopeを先行実装してはならない。

---

## Reviewer Handoff Minimum Contents

`.codex/agents/.reviewer/HANDOFF.md`には少なくとも次を含める:

- review scope
- verdict: `PASS`、`FAIL`、または`BLOCKED`
- verified factsと未検証事項
- blocking findingsと優先度
- 次サイクルの最小推奨scope
- 変更禁止範囲および維持すべきsafety gate
- Codex implementationとexternal implementationのどちらにも渡せる実行条件

`PASS`であってもuser decision gateを省略しない。
