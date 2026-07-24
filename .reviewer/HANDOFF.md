# Handoff: reviewer → planner / implementer

## Review Target

- Date: 2026-07-24
- Implementer handoff: Iteration 9 v17
- Reviewed files:
  - `backend/quality/s2_cr08_canonical.py`
  - `backend/quality/management/commands/measure_s2_cr08_canonical.py`
  - `backend/quality/test_s2_cr08_canonical.py`

## Verdict

**FAIL**

v17ではSTART/transition snapshotのDB clock bracket、minimum/live privacy allowlist、cleanup identifier hash化が改善された。しかしA/B correlationはJob identityを使用せず先着transactionを割り当てるままで、通常の異PID A/B経路は未定義methodによりcrashする。final gateは計算順、postflight、metrics coverage、evidence反映のいずれも成立していない。

`LIVE_BLOCKED = True`を維持する。S2-CR-08は`部分実施` / `not_evaluable`のままとし、疑似本番`--dry-run` / `--live`の次段階へ進めない。

## Confirmed Improvements

- `_poll_once()`のSTARTとsame-port transition snapshotは`clock → poll → clock`の順になった。
- minimum evidenceの`job_hash`はprivacy allowlistへ追加され、reviewer probeでprivacy PASSした。
- Job verificationの既知nested fieldsはprivacy allowlistへ追加された。
- cleanup failure内のJob identifierはSHA-256 prefixへ変更された。
- worker service外backendの除外、same-port `END(old)`＋`START(new)`、queued Job CAS、UNC sanitizerは維持されている。
- `LIVE_BLOCKED = True`を確認した。

## Findings

### F1 — Critical: Job IDはcorrelationに使われず、先着worker transactionをA/Bへ誤割当する

`set_job_ids()`はIDをfieldへ保存するだけで、worker claim、execution ownership、exact child PIDとの照合に一度も使わない。`_poll_once()`はJob IDsがnon-nullなら、最初に見えたworker transactionをA、次をBとして割り当てる。

reviewer probe:

```text
snapshots:
  1. unrelated transaction
  2. real A, same PID/port
  3. real B, same PID/port

collector tracked:
  A = unrelated
  B = None

get_transactions():
  A = unrelated
  B = real A

observer shims:
  correlation_unique = True
  observation_ok = True
```

同一worker process tree内のheartbeat、別Job、補助queryをcanonical A/Bとして正式採用し得る。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:338-358`
- `backend/quality/s2_cr08_canonical.py:401-483`
- `backend/quality/s2_cr08_canonical.py:492-510`
- `backend/quality/s2_cr08_canonical.py:527-580`
- `backend/quality/management/commands/measure_s2_cr08_canonical.py:306-307`

必要対応:

- Jobのactual execution ownershipからexact childを確定し、そのclient portだけをA/Bへ割り当てる。
- Job IDを保存しただけでcorrelatedと扱わない。
- unrelated worker transaction、候補0件/複数件、identity変化はfail-closedにする。
- shimの`correlation_unique` / `observation_ok`を固定値にしない。

### F2 — Critical: 正常な異PID A/B経路が`AttributeError`で停止する

A/Bが異なるchild PIDで見つかり、`_a_xact_start`と`_b_xact_start`が揃うと、`get_transactions()`は存在しない`self._get_port_for_pid()`を呼ぶ。

reviewer probe:

```text
TRACK A B
AttributeError:
  'TransactionCollector' object has no attribute '_get_port_for_pid'
```

既存134 testsはこの経路を実行しないためPASSしている。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:498-503`

必要対応:

- A/B assignment時にexact `(pid, port)`を保持し、未定義lookupへ依存しない。
- 異PID、同PID/別port、same-port sequentialのdirect testを追加する。

### F3 — Critical: 「fail-closed」が先頭2 STARTへのfallbackでfail-openになる

`get_transactions()`はtracked A/Bが揃わなくても、START eventが2件あれば先頭2件を返す。handoffの「一意に相関できなければfail-closed」と「先頭2 STARTへfallback」は相互に矛盾する。

same-port A→B transitionでも`_b_xact_start`は設定されないため、このfallbackが通常利用される。fallback後もobserver shimは先頭2 eventを成功扱いする。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:456-472`
- `backend/quality/s2_cr08_canonical.py:492-510`
- `backend/quality/s2_cr08_canonical.py:527-580`

必要対応:

- fallbackを削除する。
- A/Bのexact correlationが成立しない場合はtimeout/errorとしてformal evidenceへ記録する。
- ambiguous/unrelated eventを返さないnegative testを追加する。

### F4 — Critical: live final gateは使用前参照され、formal evidenceへ反映されない

`live_verification`を構築する時点では、次の変数がまだ代入されていない。

- `job_a_ok`
- `job_b_ok`
- `obs_a_ok`
- `obs_b_ok`
- `postflight_pass`
- `metrics_ok`
- `coverage_ok`
- `recovery_ok`

このblockは`NameError`をcatchして`enrichment_errors`へ追加するため、`live_verification`が欠落する。変数はその後に計算されるが、evidenceを再構築しない。

またminimum evidenceの`measurement_status` / `failure_reason`はfinal gate計算前の値から更新されない。handoff記載の`measurement_status = "incomplete"`更新とfailure reasonへのgate理由追加は実装に存在しない。

該当箇所:

- `backend/quality/management/commands/measure_s2_cr08_canonical.py:549-568`
- `backend/quality/management/commands/measure_s2_cr08_canonical.py:573-597`
- `backend/quality/management/commands/measure_s2_cr08_canonical.py:599-627`

必要対応:

- 全enrichment成功/失敗結果を先に確定する。
- final gate計算後に`measurement_status`、`failure_reason`、`live_verification`を更新する。
- privacy check/writeはformal final evidence完成後だけ実行する。
- successと各gate failureのdirect command testを追加する。

### F5 — Critical: postflightとmetrics coverageがfinal gateになっていない

`postflight_pass`は代入箇所がなく、`all_gates_pass`にも含まれない。postflight mismatch、active/running Job残存、service/HTTP/UNC failureがあっても、他のbooleanがtrueならfinal gateを通り得る。

`coverage_ok`は無条件`True`で、first/last sampleがあってもTODOの`pass`だけである。したがってmetricsがA/B実行期間をcoverした証明にならない。

該当箇所:

- `backend/quality/management/commands/measure_s2_cr08_canonical.py:558`
- `backend/quality/management/commands/measure_s2_cr08_canonical.py:586-597`

必要対応:

- `_all_preflight_pass(postflight)`相当のclosed postflight gateを計算し、`all_gates_pass`へ含める。
- metrics first/last timestampとA/B実行区間からcoverageを実計算する。
- postflight各failureとmetrics coverage不足のnegative testを追加する。

### F6 — High: END boundsはsnapshotをbracketしていない

poll開始時の`before/current/after`はSTARTとtransitionには使われるが、backend disappearanceのEND処理ではsnapshot後に `_db_clock()`をさらに2回呼ぶ。ENDを検出したsnapshotのlower/upper boundではない。

さらに`_a_xact_end` / `_b_xact_end`には終了時刻ではなくold `xact_start`値を保存する。tracked A/B infoの5番目をend boundとして返す契約と一致しない。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:474-488`
- `backend/quality/s2_cr08_canonical.py:501-503`

必要対応:

- disappearance ENDにもpoll snapshotの同じ`before/after`を使用する。
- xact identityとend lower/upper boundを別fieldで保持する。
- START、transition END、disappearance ENDのclock ordering testを追加する。

### F7 — High: baseline backendを永久除外し、同connectionの新transactionも観測しない

baselineは`(pid, port)`だけで保持される。keyがbaselineにある場合、現在の`xact_start`がbaselineから変化しても毎poll `continue`するため、同じpersistent connection上の後続canonical transactionをすべて除外する。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:422-440`

必要対応:

- baseline identityは`(pid, port, xact_start)`として保持する。
- baseline transaction終了後、同connectionの新しい`xact_start`は新規候補として扱う。
- baseline-active→idle→Aとbaseline-active→zero-gap Aのtestを追加する。

### F8 — Medium: v17修正のdirect regression testがない

implementer handoff自身がdirect testsを次iterationへ延期している。`backend/quality/test_s2_cr08_canonical.py`には`TransactionCollector`、final gate、complete live evidenceのdirect coverageが追加されていない。

既存testsは全PASSするが、F1-F7を検出しない。live safety機能の変更とtestは同じiterationで完了させる必要がある。

最低限必要なcoverage:

- exact Job/child/backend correlation
- unrelated/ambiguous worker transaction fail-closed
- 異PID・same-port sequential A/B
- baseline identity transition
- START/END clock bracket
- collector lifecycle
- cleanup CAS/timeoutとservice recovery
- postflight/metricsを含むfinal gate
- complete live payload privacy
- raw Job identifier非出力

## Validation

| Check | Result |
|---|---|
| canonical + measurement、fresh test DB | PASS（134/134、85.023秒） |
| job queue API + recovery、fresh test DB | PASS（16/16、4.314秒） |
| `PhaseTwoMasterUpdateTests`、fresh test DB | PASS（33/33、0.698秒） |
| Django `check` | PASS、issue 0 |
| `makemigrations --check --dry-run` | PASS、変更なし |
| `git diff --check` | PASS（line-ending warningのみ） |
| minimum evidence with hashed Job ID privacy | PASS |
| unrelated→A→B same-port probe | FAIL、unrelated/AをA/Bとして返す |
| distinct PID A/B probe | FAIL、未定義`_get_port_for_pid()`でcrash |

合計: **183/183 selected existing tests PASS**

implementer handoffの`100/100`および合計`182/182`は現在の実行対象数と一致しない。reviewer環境でcanonical + measurementは134件、全selected testsは183件だった。

reviewerは疑似本番`--dry-run` / `--live`、Job投入、backup、service操作、業務data変更を実行していない。

## Verified Facts

- STARTとsame-port transitionのsnapshot bracketは改善された。
- minimum Job hashと既知Job verification fieldのprivacy schemaは改善された。
- cleanup failureのraw Job ID埋め込みは解消された。
- selected 183 existing tests、Django check、migration drift、diff checkは合格した。
- live safetyのdirect testsは未追加である。

## Unverified / Remaining

- exact Job/child/backend correlationは未実装・未検証。
- correct END boundsは未実装・未検証。
- final live evidence/gateは未成立。
- canonical疑似本番dry-run/liveはreviewer未実施。
- 6指標のwarning/fail閾値、approval ID、承認者役割、承認日、review期限は未承認。

## Required Next Action

1. `LIVE_BLOCKED = True`を維持する。
2. F1-F8を最小変更で同一iteration内に修正・direct testする。
3. event順序ではなくactual Job execution ownershipからA/Bを相関する。
4. fallbackと固定成功shimを削除し、ambiguous stateをfail-closedにする。
5. START/END boundsとbaseline identity semanticsを修正する。
6. postflight/metrics/cleanup/recoveryを含むfinal gateをformal evidence完成前に計算する。
7. fresh selected regressionとdirect negative testsを実行する。
8. `.implementer/HANDOFF.md`の実装事実とtest件数を実結果へ合わせて更新する。
9. reviewer PASS後にのみ疑似本番dry-run/liveの次段階へ進む。
