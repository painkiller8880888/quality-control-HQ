# Handoff: implementer → reviewer

## Scope

- 対象: RELEASE.md:197 第二P0「transaction境界の正確性」のみ
- P0 final gate、P1、P2へ着手しない
- `LIVE_BLOCKED = True` 維持確認済み

## Changes (since previous implementer submission)

### F1 — same-port transition lower bound race (critical)

- `_track_ab_transactions` transition END lower bound: `_last_poll_after` → `_last_poll_before`
- 理由: 前回pollの`before`はsnapshotより前であり、transaction transitionがsnapshot直後〜`after`間で起きるraceを許さない
- `_poll_once`で`_last_poll_before = before`を各poll末尾に保存
- `get_transactions`に`end_lower > end_upper` fail-closed invariant追加

### F2 — unrelated END false completion (confirmed in previous review)

- `wait_for_completion`: event scanning → `_a_xact_end_verified and _b_xact_end_verified`
- observer shim `transaction_completed`: event `xs in ends` → `_a_xact_end_verified`
- `test_shim_transaction_completed_after_assignment`: raw event append → production `_track_ab_disappearance`呼出

### F3 — disappearance lower bound (confirmed in previous review)

- `_last_poll_before`新規追加（`__init__` + `_poll_once`末尾で保存）
- disappearance END lower: `_last_poll_after` → `_last_poll_before`（snapshot前の安全側時刻）

### F4 — START ordering assertion (confirmed in previous review)

- `test_start_bound_clock_ordering`: `assertIsNotNone` → `assertGreaterEqual(start_bound, xact_start)`

### Production code

| Location | Change |
|---|---|
| `s2_cr08_canonical.py:380` | `__init__`: `_last_poll_before = None`追加 |
| `s2_cr08_canonical.py:484-531` | `_poll_once`: `_last_poll_before = before`保存、disappearance lower = `_last_poll_before`、transition lower = `_last_poll_before` |
| `s2_cr08_canonical.py:775-842` | `_track_ab_transactions`: 4箇所の`_last_poll_after` → `_last_poll_before` |
| `s2_cr08_canonical.py:896-912` | `get_transactions`: A/B END bounds invariant check追加 |

## New Tests (P0-2 boundary, 13 total)

`TransactionCollectorCorrelationTests`クラスに追加:

| # | Test | Verification |
|---|------|-------------|
| 1 | `test_start_bound_clock_ordering` | START bound >= xact_start |
| 2 | `test_same_port_transition_bounds_shared_snapshot` | same-port: end_lower <= end_upper <= start_bound |
| 3 | `test_disappearance_end_ordering` | disappearance: lower <= upper, lower = previous before |
| 4 | `test_field_separation_xact_start_not_end` | end_lower != any xact_start (time vs xs) |
| 5 | `test_unrelated_end_not_mixed_into_ab_target` | 無関係END eventがA/B targetを変更しない |
| 6 | `test_wait_for_completion_timeout_raises` | timeout → RuntimeError |
| 6b | `test_wait_for_completion_missing_end_raises` | END欠測 → RuntimeError |
| 7 | `test_collector_stop_fail_closed` | exception保持時stop()→RuntimeError |
| 8 | `test_poll_exception_fail_closed` | poll exception→exception伝搬 |
| 9 | `test_ab_same_port_formal_ordering` | A/B same-port: A end_upper <= B xact_start |
| 10 | `test_unrelated_end_completion_probe` | unrelated END/same xs: shim + wait_for_completion拒否 |
| 11 | `test_race_xs_before_previous_after_transition` | xs_b < previous after → end_lower <= end_upper維持 |
| 12 | `test_inverted_bounds_fail_closed_in_get_transactions` | 反転bounds → get_transactions raise RuntimeError |

### Existing test changes

- `test_shim_transaction_completed_after_assignment`: raw event → production `_track_ab_disappearance`
- `test_start_bound_clock_ordering`: is not None → assertGreaterEqual

## Verification Results

| Check | Result |
|---|---|
| TransactionCollectorCorrelationTests (39 original + 13 new) | **PASS: 52/52** |
| 全canonical tests | **PASS: 167/167** |
| `manage.py check` | PASS |
| `manage.py makemigrations --check --dry-run` | No changes detected |
| `manage.py check --deploy` | 既知のsecurity warning 6件 |
| `LIVE_BLOCKED = True` | 維持確認 |

## Scope Guard

- P0 final gate、P1、P2に着手していない
- pseudoprod dry-run/live、Job投入、service操作、backupを実行していない
- 未承認閾値を合否判定に使用していない
