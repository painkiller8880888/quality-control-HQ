# Handoff: reviewer → planner / implementer

## Review Scope

- `.planner/HANDOFF.md`
- latest `.implementer/HANDOFF.md`
- previous findings F1–F5
- semantic consistency gap
- retained/removed test bodies
- distribution/privacy direct tests
- test definitions / uniqueness
- `LIVE_BLOCKED = True`
- `git diff --check`

## Verdict

**FAIL — Safety Stop / planner decision required**

implementerは、`measurement_status`、`failure_reason`、`live_verification`のsemantic consistency validatorがproductionに存在しないことを正しくgapとして報告した。

これはP1 acceptance criterion 4の必須fail-closed条件そのものであるため、reviewerはgapを受容してPASSへ変更できない。production/schema互換性へ影響する可能性がある変更は現planner scopeで禁止されており、implementerのSafety Stopは妥当である。

P2へ進まない。`LIVE_BLOCKED = True`を維持する。

## Resolved Findings

次は解消済み:

- distribution bool priority key rejection: preflight/postflight
- distribution negative count rejection: preflight/postflight
- total mismatch testのtraceability
- privacy dynamic integer priority key: preflight/postflight
- raw path実入力のprivacy rejection
- canonical test method重複
- test count / uniqueness
- repository rootでの`git diff --check`
- semantic contradictionを受理する`test_build_evidence_semantic_contradiction_completed_with_failure_reason`の削除
- 不存在F4 testを追加済みとする記載の撤回

reviewer静的実測:

| Target | Definitions | Unique | Duplicates |
|---|---:|---:|---:|
| canonical | 267 | 267 | 0 |
| measurement | 34 | 34 | 0 |

次も確認済み:

- module/command双方で`LIVE_BLOCKED = True`
- reviewer `git diff --check`: exit 0、CRLF warningのみ
- implementer申告fresh DB: canonical 267/267、measurement 34/34、queue + PhaseTwo 49/49 PASS

## Blocking Finding

### B1 — High: formal evidence semantic consistencyは未実装

implementer gap analysis:

> `measurement_status`、`failure_reason`、`live_verification`の自己矛盾を拒否するsemantic consistency validatorは現状存在しない。

reviewerのコード確認とも一致する。`build_canonical_evidence()`は次のような矛盾を構築可能である:

- `measurement_status="completed"` + non-empty `failure_reason`
- `measurement_status="completed"` + failed `live_verification` gate
- `measurement_status="failed"` + empty `failure_reason`

`run_canonical()`がfailed Jobを早期拒否することは重要だが、完成したformal evidenceのsemantic validationとは別契約である。builder、writer、またはfinal evidence gateの別経路から矛盾が入った場合をfail-closedで拒否する保証がない。

必要なplanner判断:

1. production semantic validatorの追加を新しい明示scopeとして許可する
2. validatorの適用地点を決める
   - evidence build直後
   - privacy check前
   - evidence write直前
   - writer再読込後
3. schema互換性への影響を評価する
4. direct positive/negative testと既存suite回帰を必須にする

この判断なしにimplementerがproduction変更へ進んではならない。

## Remaining Documentation/Test Cleanup

### F1 — Medium: misleading semantic testが1件残っている

次が`JobResultVerifierTests`内に残る:

```text
test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification
```

周辺commentは「Semantic contradiction direct negative tests」、docstringはcompleted statusとfailed live verificationの矛盾拒否を主張するが、実際にはfailed Jobを渡して既存Job final gateのraiseを確認する長大testである。

同じJob A failure契約は`RunCanonicalTests.test_run_canonical_job_gate_fails_closed_when_job_a_failed`と重複する。

必要対応:

- この残存testを削除する
- semantic direct testとしてmatrix/reportへ含めない
- pure Job final gate testの重複を増やさない

### F2 — Medium: “matrix 267 FQN”はtraceability matrixの集合ではない

handoffは「matrix references 267 / unique 267」とするが、267はcanonical file全test definitionsの件数である。表示されたtraceability matrixは代表testだけを記載し、多くは`Class.test_method`形式で、plannerが要求した完全修飾名ではない。

full canonical suiteが267件PASSすることと、traceability matrixの各参照を完全修飾名で機械検証することは別である。

必要対応:

- matrixの参照だけを抽出してreferences / unique / missingを報告する
- canonical参照も`quality.test_s2_cr08_canonical.Class.test_method`形式にする
- measurement参照と同じ完全修飾形式へ統一する
- full suite 267件の件数は別表として扱う

### F3 — Medium: partial coverageとmissing ENDを同一扱いしている

handoff:

> partial coverageは既存の`test_wait_for_completion_missing_end_raises`でカバーされる

missing ENDはpartial coverageの一例だが、observer fieldの部分欠測、metrics coverage不足、time windowの一部未観測すべてを代表するわけではない。

既存の次を要件別に再評価する:

- `TransactionCollectorCorrelationTests.test_wait_for_completion_missing_end_raises`
- `S2Cr08MeasurementTests.test_build_evidence_partial_transaction_observer`
- `RunCanonicalTests.test_run_canonical_fails_closed_when_metrics_insufficient`
- observer field欠測を拒否する既存RunCanonical test

単に「partial coverage」と総称せず、各testが拒否する具体的なmissing field/conditionを記載すること。

## Required Next Step

### Planner

semantic consistency validatorをproductionへ追加する新scopeを作成するか判断する。

新scopeを作る場合の最低要件:

1. semantic validatorはpure functionとして最小実装
2. completed/failed状態、failure reason、全live verification gateの整合を検証
3. unknown/missing/malformed typeをfail-closed
4. final evidence write前に必ず呼ばれる
5. contradictionごとのdirect negative test
6. valid completed/failed evidenceのpositive test
7. privacy・manifest・fresh DB全回帰
8. `LIVE_BLOCKED = True`維持

### Implementer

plannerがscopeを更新するまではproduction変更を行わない。

許可されるcleanupは:

- 残存するmisleading/duplicate semantic testの削除
- handoffのmatrix count/FQN表記/coverage説明の訂正

cleanup後もsemantic validator未実装のため、P1 verdictはFAILのままとする。

## Non-Goals

- P2
- canonical `--dry-run` / `--live`
- 疑似本番または実Job投入
- service操作
- backup/restore
- threshold承認・変更
- `specification/RELEASE.md`の状態変更
- model/migration変更
- stage/commit
