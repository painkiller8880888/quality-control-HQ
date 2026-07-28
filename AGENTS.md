# AGENTS.md

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

このリポジトリでは、複数のAI agentが役割分離されたパイプラインとして協調する。

現在の基本パイプライン:

1. planner(codex)
2. implementer(opencode)
3. reviewer(codex)

各agentは自分の責務のみ実行する。
1->2, 2->3は異なるクライアント間のhandoffとなる。
各エージェントは次のクライアントのためのhandoff生成をgoalとする。

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

agent間通信は structured handoff のみで行う。

各agentは:
- 自分の責務だけ実行する
- 次agentに必要な情報だけ渡す
- 思考ログを丸ごと渡さない
- 未検証情報を事実として渡さない
