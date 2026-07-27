# Handoff: reviewer → implementer

## Review Scope

- 対象: 第二P0「transaction境界の正確性」、前回F1〜F4の再レビュー
- 確認対象:
  - `backend/quality/s2_cr08_canonical.py`
  - `backend/quality/test_s2_cr08_canonical.py`
  - `.implementer/HANDOFF.md`
- 実施: 差分レビュー、race direct probe、対象50 tests、Django check、migration drift、diff check
- 非実施: 疑似本番dry-run/live、Job投入、service操作、backup/restore
- `LIVE_BLOCKED = True`維持を確認

## Verdict

**FAIL**

前回F2、F3、F4はコード上で解消したが、F1のsame-port transition lower boundにraceが残る。前回snapshot直後からclock `after`取得までにtransactionが切り替わると、`end_lower > end_upper`となり、formal evidenceへ負のmeasurement errorを出力する。

第二P0は未達。P0 final gateへ進まず、`LIVE_BLOCKED = True`を維持する。

## Confirmed Fixes

### 前回F2: unrelated END false completion

解消を確認した。

- `wait_for_completion()`はA/Bそれぞれの`_xact_end_verified`を確認する。
- observer shimの`transaction_completed`も専用verified stateを返す。
- unrelated END negative testが追加された。

### 前回F3: disappearance lower bound

解消を確認した。

- disappearance END lowerは`_last_poll_before`を使用する。
- previous snapshotでactiveだったことから保証できる安全側のlowerになった。

### 前回F4: START ordering test

解消を確認した。

- `start_bound >= xact_start`を直接assertする。
- `start_bound`をtransaction開始下限ではなく、観測poll時刻として扱うことがtest上で明確になった。

## Findings

### F1 — Critical: same-port transitionのlowerにprevious `after`を使うため、END boundsが反転する

same-port transitionは次の値を記録する。

```text
end_lower = _last_poll_after
end_upper = new xact_start
```

前回pollの順序は次のとおり。

```text
previous before → snapshot(old active) → transaction transition/new xact_start → previous after
```

transitionがsnapshot直後、`previous after`取得前に起きることは可能である。この場合:

```text
new xact_start < previous after
end_upper < end_lower
```

reviewer race probe:

```text
lower_gt_upper=True
duration_lower_bound_seconds=3.0
duration_upper_bound_seconds=2.0
max_measurement_error_seconds=-1.0
```

`get_transactions()`はsame-portで`end_upper <= B xact_start`だけを確認するため、`end_lower > end_upper`でも受理し得る。続くformal evidence生成もorderingをrejectせず、負の`max_measurement_error_seconds`を出力する。

追加testは`xs_b`をprevious `after`より100µs後に固定しており、問題のraceを覆っていない。

該当箇所:

- `backend/quality/s2_cr08_canonical.py:779-780`
- `backend/quality/s2_cr08_canonical.py:800-812`
- `backend/quality/s2_cr08_canonical.py:827-839`
- `backend/quality/s2_cr08_canonical.py:898-905`
- `backend/quality/s2_cr08_canonical.py:2071-2074`
- `backend/quality/test_s2_cr08_canonical.py:2036-2069`

必要対応:

- same-port transition lowerにも、previous snapshotがold transactionを観測したことから保証できる安全側の時刻を使う。既に保持している`_last_poll_before`を候補として検討する。
- `new xact_start < previous after`を再現するdirect testを追加する。
- `end_lower <= end_upper`を正式経路およびevidence生成前のfail-closed invariantとして検証する。
- negative duration / negative measurement errorを許可しないtestを追加する。

### F2 — Medium: implementer handoffが現在コードと検証件数を反映していない

handoffは前回修正前の内容のままで、現在コードと矛盾する。

- disappearance lowerを`_last_poll_after`と記載しているが、コードは`_last_poll_before`
- same-port ENDを同一poll `before/after`と記載しているが、コードはprevious `after` / new `xact_start`
- new testsを10件、対象suiteを49件と記載しているが、現在はunrelated END probe追加後の50件
- 前回reviewer F1〜F4への対応内容がChangesに含まれていない

Handoff Rulesに従い、次review前に実装事実と独立して再現可能な検証件数へ更新する。

該当箇所:

- `.implementer/HANDOFF.md`

## Independent Validation

| Check | Result |
|---|---|
| `TransactionCollectorCorrelationTests` | PASS: 50/50, 20.574s |
| same-port transition race probe | **FAIL: lower > upperを再現** |
| formal transaction evidence probe | **FAIL: max_measurement_error_seconds=-1.0** |
| unrelated END completion | PASS: verified stateへ変更確認 |
| disappearance lower | PASS: `_last_poll_before`使用確認 |
| START ordering direct assert | PASS: test追加確認 |
| `manage.py check` | PASS |
| `manage.py makemigrations --check --dry-run` | PASS: No changes detected |
| `git diff --check` | PASS（line-ending warningのみ） |
| `LIVE_BLOCKED = True` | 維持確認 |

既存test DBが存在したため、対象50 testsは`--keepdb`で実行した。最初の短いtest呼出はtimeoutで中断し、その後の完走runのみを結果として記録した。

reviewerは疑似本番dry-run/live、Job投入、service操作、backup/restore、業務data変更を行っていない。

## Next Scope

次iterationはF1のsafe lower/invariant修正、race direct test、F2 handoff整合のみを対象とする。第二P0のreviewer PASSまでは第三P0 final gateへ進まない。
