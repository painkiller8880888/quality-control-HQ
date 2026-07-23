# Handoff: reviewer → planner / owner

## Review Target

`.implementer/HANDOFF.md` Iteration 8 の修正内容をレビューした。

対象:

- `backend/quality/management/commands/measure_s2_cr08.py`
- `backend/quality/test_s2_cr08_measurement.py`
- `backend/quality/job_queue.py`
- `backend/quality/models.py`
- `backend/quality/migrations/0029_job_created_at.py`
- `backend/quality/s2_cr08_measurement.py`
- `specification/RELEASE.md`
- `.implementer/HANDOFF.md`

## Verdict

**PASS**

今回の実装差分に対する必須修正はない。

このPASSは測定fixtureと関連変更へのレビュー判定であり、S2-CR-08自体の合格判定ではない。canonical疑似本番再測定と6指標の承認済み閾値が未完了であるため、S2-CR-08は引き続き`部分実施` / `not_evaluable`である。

## Verified Facts

- `_claim_specific_job()`と`claim_next_job()`は、同一resourceのclaim時にrow lock → transaction-scoped advisory lockの順で取得する。
- fixture同士、およびproduction claimとfixture claimの競合試験は、thread終了、別DB backend、errorなし、claim成功が1件だけであることを検証している。
- 競合threadは`finally`でDB connectionをcloseし、`join(timeout=10)`後に`is_alive()`を検証する。
- fixture abort時の`Job.result`は`status`、`error_message`、`exception_type`を含むfailure schemaとなる。
- `Job.created_at`のmodelとmigrationにdriftはない。
- `specification/RELEASE.md`のfixture試験数は34件で実行結果と一致する。
- `specification/RELEASE.md`はcanonical再測定未実施、閾値未承認、`部分実施` / `not_evaluable`を維持している。

## Validation

2026-07-23、reviewerがローカルPostgreSQL test DBで再実行した。

| Check | Result |
|---|---|
| `quality.test_s2_cr08_measurement` | PASS、34/34、49.816秒 |
| `PersistentJobQueueApiTests` + `PersistentJobQueueRecoveryTests` | PASS、16/16、4.502秒 |
| Django `check` | PASS、issue 0 |
| `makemigrations --check --dry-run` | PASS、変更なし |
| `git diff --check` | PASS |

実行コマンド:

```powershell
& '..\.venv\Scripts\python.exe' manage.py test quality.test_s2_cr08_measurement --keepdb
& '..\.venv\Scripts\python.exe' manage.py test quality.test_job_queue.PersistentJobQueueApiTests quality.test_job_queue.PersistentJobQueueRecoveryTests --keepdb
& '..\.venv\Scripts\python.exe' manage.py check
& '..\.venv\Scripts\python.exe' manage.py makemigrations --check --dry-run
git diff --check
```

## Unverified / Remaining

- canonical `master_update` A→Bの疑似本番再測定は未実施。
- 外部worker backendを対象にしたtransaction observerは未実装・未検証。
- 6指標のwarning/fail閾値、approval ID、承認者役割、承認日、review期限は未承認。
- preflight、backup、restore-list、canonical baseline、business hash、service live stateを含む疑似本番ゲートは未検証。
- 上記が完了するまでS2-CR-08を合格へ変更しない。

## Next Action

責任者の閾値承認入力を取得し、外部worker observerと全preflight gateを別スコープで計画・実装・レビューする。全ゲート成功時のみcanonical再測定へ進む。
