# Handoff: planner → implementer

## Role

あなたはimplementer（OpenCode）。

reviewer Safety Stopを受け、S2-CR-08 P1のblocking gapであるformal evidence semantic consistency validatorを最小実装する。指示範囲外へ広げず、完了後は`.implementer/HANDOFF.md`をreviewer向けに更新して停止すること。

## Goal

既存evidence schemaへfieldを追加せず、`measurement_status`、`failure_reason`、`live_verification`および既存final gate field間の自己矛盾をfail-closedで拒否する。

完成したcanonical formal evidenceが書き込まれる前にsemantic validationを必ず通ることを保証する。

`LIVE_BLOCKED = True`を維持し、P2へ進まない。

## Authorized Production Scope

今回に限り、次の最小production変更を許可する。

- `backend/quality/s2_cr08_canonical.py`
  - private pure validator追加
  - `build_canonical_evidence()`のbase semantic check
  - `run_canonical()`完成evidenceのfinal semantic check
- `backend/quality/management/commands/measure_s2_cr08_canonical.py`
  - dry-run/live formal evidenceの書込直前semantic check
- 必要なimport

許可しない:

- model/migration変更
- evidence field追加・削除・rename
- schema version変更
- status vocabulary拡張
- generic measurement writerの大規模変更
- 既存gateの緩和

## Design

### 1. Pure validator

`backend/quality/s2_cr08_canonical.py`へ、外部I/Oを行わないprivate functionを追加する。

推奨signature:

```python
def _validate_canonical_evidence_semantics(evidence, *, require_final=False):
    ...
```

契約:

- validなら`True`を返す
- invalidならboundedでprivacy-safeな理由を持つ`RuntimeError`または`ValueError`をraiseする
- dictを破壊・補正しない
- truthy/falsyへ丸めず、既知fieldはexact typeで検証する
- unknown status/run modeへfallbackしない
- raw evidence、job ID、path、token、PID/portをexceptionへ含めない

### 2. Base semantic rules

すべてのprofileで:

- `evidence`はdict
- `run_mode`は`"dry_run"`または`"live"`だけ
- `measurement_status`はprofileで許可された値だけ
- `failure_reason`は存在する場合string

#### dry-run

- `run_mode == "dry_run"`
- `measurement_status == "not_executed"`
- preflight成功時は`failure_reason == ""`
- preflight失敗時は`failure_reason == "preflight_failed"`
- `live_verification`を要求しない
- `measurement_status`のcompleted/failedは拒否

既存`build_canonical_evidence(..., run_mode="dry_run")`のshapeを維持する。

#### live base/failure evidence

- `run_mode == "live"`
- statusは`"completed"`または`"failed"`だけ
- completedなら`failure_reason`は空文字または未設定
- failedなら`failure_reason`はnon-empty string
- `require_final=False`ではminimum failure evidenceを許容し、`live_verification`を必須にしない

既存`_build_minimum_evidence()`のfailure pathを壊さない。

### 3. Final live semantic rules

`require_final=True`かつ`run_mode=="live"`の正式成功evidenceでは、少なくとも次を要求する。

- `measurement_status == "completed"`
- `failure_reason == ""`
- `live_verification`がdict
- 次のfieldが`type(value) is bool`かつすべて`True`
  - `job_a_succeeded`
  - `job_b_succeeded`
  - `observer_a_completed`
  - `observer_b_completed`
  - `postflight_pass`
  - `metrics_ok`
  - `metrics_thread_alive`
- `metrics_coverage_ok`がexact bool `True`
- `recovery_ok`がexact bool `True`
- `cleanup_failures`が空list
- `transaction_completed`がexact bool `True`
- `observation_ok`がexact bool `True`

既存fieldだけを検証し、新fieldを追加しない。

`attempt_count_a/b`を検証する場合は、既存`_verify_job_result()`のsingle-attempt契約と一致させる。今回の必須範囲では、既存Job final gateで保証済みならsemantic validatorへ重複実装しなくてよい。

### 4. Required call sites

#### `build_canonical_evidence()`

- return直前に`require_final=False`でbase validation
- dry-run return pathもvalidationを通す
- contradictory caller inputをそのまま返さない

#### `_build_minimum_evidence()`

- return直前に`require_final=False`でbase validation
- failed status + empty reason等を拒否

#### `run_canonical()`

- `live_verification`、`metrics_coverage_ok`、`recovery_ok`、`cleanup_failures`等のenrichment完了後
- privacy checkより前
- `require_final=True`でvalidation
- validation failure時はevidenceを返さない

#### management command

- dry-runの`write_evidence()`直前にbase validation
- liveの`write_evidence()`直前にfinal validation
- commandからvalidator failureを成功扱いせず`CommandError`へ変換
- write前に失敗し、partial evidence directoryを作らないこと

同じevidenceに対する再validationは許容する。validatorはpureかつdeterministicにする。

## Direct Tests

`backend/quality/test_s2_cr08_canonical.py`へ最小限追加する。

### Positive

1. valid dry-run / preflight pass
2. valid dry-run / `preflight_failed`
3. valid live minimum failure evidence: failed + non-empty reason、`require_final=False`
4. valid completed final evidence: required fieldがすべて正しい

### Base negative

5. evidenceがnon-dict
6. unknown/missing/malformed `run_mode`
7. unknown/missing/malformed `measurement_status`
8. completed + non-empty `failure_reason`
9. failed + empty/missing/non-string `failure_reason`
10. dry-run + completed/failed
11. dry-run failure reasonが未知値

### Final negative

12. missing/non-dict `live_verification`
13. required live gateの各fieldがmissing
14. required live gateの各fieldがFalse
15. required live gateがtruthy非bool
16. `metrics_coverage_ok`がmissing/False/non-bool
17. `recovery_ok`がmissing/False/non-bool
18. `cleanup_failures`がmissing/non-list/non-empty
19. `transaction_completed`がmissing/False/non-bool
20. `observation_ok`がmissing/False/non-bool

table-driven subTestを使用し、各fieldごとに巨大fixtureを複製しない。

### Integration

21. `build_canonical_evidence()`がcompleted + non-empty reasonをraise
22. `_build_minimum_evidence()`がfailed + empty reasonをraise
23. `run_canonical()`がfinal validatorをprivacy check前に通す
24. management command dry-runでvalidator failure時にwriteしない
25. management command live write直前validator failure時にwriteしない

command live testで実Job・service操作を行わない。patch/mockでcall orderとno-writeを検証する。

## Required Cleanup

前reviewer指摘の残存misleading testを削除する:

```text
JobResultVerifierTests.test_run_canonical_rejects_completed_status_with_failed_job_a_in_live_verification
```

理由:

- semantic contradictionを入力していない
- existing Job final gate testと重複
- 100行超fixtureで最小変更原則に反する

既存の有効なdistribution/privacy testは保持する。

次は削除・緩和しない:

- bool priority key negative
- negative count negative
- total mismatch
- dynamic integer key privacy
- raw path rejection
- non-finite metrics
- transaction correlation/bounds

## Traceability and Report Accuracy

`.implementer/HANDOFF.md`では次を分離する。

1. traceability matrixに実際に記載したFQN set
2. canonical full suite definitions
3. measurement full suite definitions

matrixのcanonical参照も必ず完全修飾形式にする:

```text
quality.test_s2_cr08_canonical.ClassName.test_method
```

機械確認:

- matrix references
- matrix unique FQN
- missing FQN
- executed focused FQN
- matrix unique setとexecuted setの集合差
- canonical definitions / unique / duplicates
- measurement definitions / unique / duplicates

`matrix unique == executed focused`、集合差0を必須とする。full suite件数をmatrix件数として報告しない。

coverage説明ではmissing END、observer field欠測、metrics coverage不足、ordering violationを別条件として記載する。

## Validation

test DBはstale `--keepdb`に依存しないfresh DBを使う。

```powershell
cd backend
python manage.py test <semantic validator focused FQN> --verbosity=1 --noinput
python manage.py test <matrix exact unique FQN set> --verbosity=1 --noinput
python manage.py test quality.test_s2_cr08_canonical --verbosity=1 --noinput
python manage.py test quality.test_s2_cr08_measurement --verbosity=1 --noinput
python manage.py test `
  quality.test_job_queue.PersistentJobQueueApiTests `
  quality.test_job_queue.PersistentJobQueueRecoveryTests `
  quality.tests.PhaseTwoMasterUpdateTests `
  --verbosity=1 --noinput
python manage.py check
python manage.py makemigrations --check --dry-run
cd ..
git diff --check
```

各commandの正確な件数、結果、時間を記録する。

## Acceptance Criteria

1. pure semantic validatorが追加され、dictを変更しない
2. dry-run、live minimum failure、live finalの既存profileを明示的に区別する
3. completed + failure reasonを拒否する
4. failed + empty reasonを拒否する
5. final live required gatesのmissing/False/non-boolを拒否する
6. cleanup/recovery/coverage/transaction/observationの矛盾を拒否する
7. `build_canonical_evidence()`がcontradictory inputを返さない
8. `run_canonical()`がprivacy前にfinal validationを通す
9. CLIがwrite直前にvalidationし、failure時にwriteしない
10. direct testが実際にcontradictory evidenceをvalidatorへ入力する
11. misleading/duplicate semantic testを削除する
12. matrix FQN setとfocused実行setが完全一致
13. test method名に重複がない
14. fresh DB全suite、Django check、migration drift、diff checkがPASS
15. module/command双方で`LIVE_BLOCKED = True`
16. schema version、model、migration、evidence fieldを変更しない
17. scope外操作を行わない

## Safety Stop Conditions

以下の場合は実装を広げず`.implementer/HANDOFF.md`へ記録する:

- evidence field/schema version変更が必要
- model/migration変更が必要
- generic measurement writerの互換性を壊す必要がある
- valid dry-runまたはminimum failure evidenceを互換維持できない
- live/service/実Job/backup/restoreが必要
- fresh DBを安全に作成・破棄できない
- credential、raw path、token、PID/portが証跡・報告へ混入する
- 既存未コミット変更と安全に分離できない

## Non-Goals

- P2
- canonical `--dry-run` / `--live`の実行
- 疑似本番または実Job投入
- Windows service操作
- backup/restore
- threshold承認・変更
- `specification/RELEASE.md`の状態変更
- model/migration/schema version変更
- 無関係なrefactor
- stage/commit

## Deliverable

`.implementer/HANDOFF.md`を次の構成で更新する:

- Summary
- Scope
- Files Changed
- Semantic Validator Contract
- Call Sites
- Direct Tests
- Required Cleanup
- P1 Traceability Matrix
- Matrix FQN Verification
- Validation Results
- Test Count and Uniqueness
- Preserved Safety Conditions
- Not Performed
- Unverified Items / Remaining Risks
- Reviewer Focus

完了後はP2へ進まずユーザーへ戻すこと。
