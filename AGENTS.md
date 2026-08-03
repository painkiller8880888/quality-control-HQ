# Agent Workflow Contract

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

## Reading and batching

- Read text files in PowerShell with `Get-Content -Encoding UTF8`.
- Batch only independent, read-only inspections whose results are already known to be needed. Use `Promise.allSettled` when partial results are useful.
- Keep dependent work, approvals, writes, builds, deployments, and operations sharing files or processes sequential.
- Keep each command request to at most 200 lines or 16 KiB of output. Keep each handoff evidence excerpt to at most 40 lines or 4 KiB; summarize and mark truncation without hiding failures.

## ルール

- codexは計画ではなく作業とPRの作成を担当する。計画とレビューはuser(人間)がwebのchatGPTを用いて行う。具体的な方針はdoc/codex-pipeline-personal.md、スキーマはdoc/codex-pipeline-schema.mdを参照する。
- mainへ直接pushしない。作業はブランチ＋PRを経由する。
- 頼まれていないリファクタリングをしない。
- 不確実な仕様を推測で実装しない。
- 変更前にgit statusを確認する。

## 作業手順

1. user(人間)が要求をIssueとして書く
2. webのchatGPTがまず読み、調査すべき不確実性を洗い出す
3. codexが読み取り専用で調査し、結果（関連ファイル・現状の実装・依存関係・既存テストの状態など）を返す
4. webのchatGPTが調査結果をもとにPlanとcodex側モデル（原則Luna）を確定する
5. codexのworktreeで実装させる
6. codexが検証スクリプトを実行させる
7. codexがDraft PRを作らせる
8. webのchatGPTにPRを独立レビューさせる
9. 指摘があればcodexに修正させる
10. user(人間)がCIを通す
11. user(人間)が最終確認してマージする

## 止まるべき条件

- RPと現行コードが矛盾している
- 変更対象が当初計画の2倍以上に広がった
- DBスキーマ変更や権限設計に影響する
- 既存テストの失敗原因を特定できない
- 止まったら、試行内容・確認済み事項・未解決点をPRまたはコメントに書いて報告する。
