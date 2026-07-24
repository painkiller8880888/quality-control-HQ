# Handoff: planner → implementer

## Goal

S2-CR-08のcanonical疑似本番再測定を安全に実行する前段として、外部Windows workerが実行する`master_update`を観測できる最小fixtureと、必須preflight/postflight gateを実装・自動検証する。

このiterationでは疑似本番canonical Jobを投入しない。実装と自動試験をreviewerへ渡し、reviewer PASS後の次iterationでのみ実地再測定へ進む。

## Current State

### 検証済み事実

- `.reviewer/HANDOFF.md`の最新verdictはfixture変更への`PASS`であり、S2-CR-08自体の合格ではない。
- `backend/quality/management/commands/measure_s2_cr08.py`は同一process/同一DB connectionでinline `queue_smoke`をclaim・実行する開発fixtureである。helpにも外部worker/canonical `master_update`非対応と明記されている。
- `backend/quality/s2_cr08_measurement.py`の`TransactionObserver`はtarget backend PIDを指定できるが、現行commandはcommand自身のDB backend PIDを指定する。外部worker backendの一意な発見・固定・継続観測は未実装。
- `Job.created_at`とmigration 0029、総queue wait、transaction上下限schema、ordering検証、SHA-256 manifestは実装済み。
- 測定fixtureの自動試験は34/34、関連queue試験16/16、backend全157/157、`PhaseTwoMasterUpdateTests` 33/33がreviewer環境で合格済み。
- 既存疑似本番証跡からCPU、メモリ、DB接続数、lock待ちの4指標は得られるが、canonical transaction時間と後続Jobの総queue waitは確定できない。
- `runtime/pseudoprod/evidence/s2-criterion-8-20260723-095921/summary.corrected.json`は6指標すべてを閾値未承認のため`not_evaluable`としている。
- 2026-07-23のplanner read-only確認では、`QualityControlHQ-Pseudoprod`と`QualityControlHQ-Worker-Pseudoprod`は`Running / Automatic`、`http://127.0.0.1:8080/`はHTTP 200、Django `check`はissue 0だった。
- 非昇格sessionでは`Get-CimInstance Win32_Service`がaccess deniedとなったが、`Get-Service`では状態とStartTypeを取得できた。fixtureは取得不能を成功扱いしない。
- repository rootの通常`.env`でDjango shellを起動すると疑似本番DBではなく、`quality_job`不存在だった。runnerは`deployment/pseudoprod/.env`を明示して接続先identityを検証し、暗黙の環境fallbackを禁止する。
- `.reviewer/HANDOFF.md`にはユーザー既存の未commit変更がある。変更・復元・stageしない。

### 未確認事項

- 6指標のwarning/fail閾値、comparison、approval ID、承認日、承認者の役割、review期限、再検討trigger。
- 外部worker child processとPostgreSQL backendを、この環境でどの既存情報から一意に対応づけるのが最小か。
- canonical再測定実行時点のactive Job、migration、backup、canonical input、業務baseline、UNC、service process tree。

## Scope

### 1. 外部worker transaction observer

既存`TransactionObserver`とevidence schemaを再利用し、外部workerがclaimした対象Jobの実行transactionだけを一意に観測する。

最低限、次の状態遷移を実装する。

1. 観測開始前の`pg_stat_activity`とworker process tree/接続をbaseline化する。
2. 対象Jobが`running`になり、`worker_id`、`execution_token`、heartbeat/leaseを所有したことを確認する。
3. 対象Jobを実行するexact child processのTCP client portと、`pg_stat_activity.pid/client_port/datname/usename/xact_start`をメモリ上で照合する。
4. 候補が1件だけであることを証明してbackendを固定する。0件または複数件なら安全停止する。
5. 同じbackend PID/client portと同じ`xact_start`をtransaction終了まで継続観測する。
6. 終了時刻はPostgreSQL `clock_timestamp()`でbracketした`end_lower_bound` / `end_upper_bound`として記録し、単一の厳密値に丸めない。

共有用evidenceには生PID、client port、worker ID、execution token、service account、SIDを保存しない。相関identifierはSHA-256化し、照合成否と候補数を記録する。生値がdebugに必要な場合はメモリ上だけで扱う。

既存`target_pid=None`の「新規backendが1件なら採用」だけでcanonicalを観測しない。対象Jobのexact childとの対応が必要である。

### 2. canonical runnerのdry-run/preflight

実地試験用runnerは、まず`--dry-run`または同等のnon-mutating modeを持つ。今回のvalidationではこのmodeだけを実行する。

preflightで以下をすべて機械判定し、各項目を`passed/failed/not_checked`で保存する。

- 実行hostとrepository rootが期待値。
- `deployment/pseudoprod/.env`を明示読込し、DB名/host/port/userの生値を保存せず、期待する疑似本番DB identityとの一致をboolean/hashで確認。
- migration 0029を含む期待migration適用済み、Django `check`成功。
- Web/worker serviceが存在し、`Running / Automatic`。取得不能はfail。
- HTTP 200。
- active Job 0、running Job 0。
- worker process treeを一意に取得できる。
- canonical input identity/content/path hashと期待件数が既知baseline一致。
- Master、MasterClass、Structure、InspectionFileを含む既存の業務count/stable-content hashとInspectionFile distribution/pathsetが既知baseline一致。
- configured UNC 7 rootのread/list成功。raw UNC pathは保存しない。
- custom-format full backup取得手順、backup SHA-256、non-empty `pg_restore --list`を実行可能。
- output evidence directoryが新規かつ空。
- privacy allowlist/denylistとmanifest生成処理が利用可能。

`--dry-run`はJobを作成せず、backupも作成せず、serviceを停止/開始せず、DB・UNC・業務fileを変更しない。backupについてはbinary/path/config/出力先の検証までとし、実backupは次iterationのlive run直前に取得する。

### 3. live modeの設計

reviewer PASS後に使えるlive modeを実装してよいが、今回実行してはならない。

live modeは次の順序を固定する。

1. preflight成功。
2. Web/workerを既存の承認済み手順で停止し、active Job 0を再確認。
3. custom-format full backupを取得し、SHA-256とrestore-listをfsyncした証跡へ保存。
4. serviceを復旧し、`Running / Automatic`、HTTP 200を再確認。
5. observerをbaseline/armed状態にする。
6. canonical Aと、Aに依存する別内容canonical Bを正式queue経路へ投入する。同一Jobへdedupeされたら中止。
7. A/Bを外部workerだけに実行させ、各transactionとJob/queue時間を観測する。
8. A成功後にBだけが開始し、同時running 0であることを確認する。
9. postflightで各attempt 1、canonical result件数/warning、active Job 0、business baseline不変、service live state、HTTP 200、UNC 7/7を確認する。
10. privacy scanとmanifest検証に成功した場合だけ共有用evidenceを確定する。

runner自身がJobをclaimしたり`execute_claimed_job()`を直接呼んだりしない。外部WinSW workerの本番経路を測定する。

### 4. evidence schema

既存`s2-cr-08-measurement-v3`を互換的に拡張する。少なくとも以下を保持する。

- fixture/schema version、run mode、UTC measurement date。
- preflight/postflightの項目別結果と総合結果。
- Job A/Bのhash化identifier、`created_at`、`started_at`、`finished_at`、attempt、status、結果要約。
- Bの`total_queue_wait_seconds`とA完了からの`handoff_gap_seconds`を別field。
- A/Bそれぞれのtransaction `xact_start`、終了lower/upper bound、duration lower/upper、最大測定誤差、poll回数/間隔。
- exact child/backend相関のmethod、candidate count、一意性boolean、hash化correlation。
- CPU、メモリ、DB接続数、lock待ちの測定値。既存canonical証跡の値を新run値としてコピーしない。
- backup metadata、canonical input/baseline/postflight一致boolean。
- threshold approvalは別sectionとし、承認入力がなければ6指標すべて`not_evaluable`。

値が取れなかったfieldを0やnull成功として扱わず、`measurement_status`とfailure reasonを持つ。

### 5. 自動試験

実DB/processを必要とする部分は依存境界を小さくmock/fake可能にし、以下を追加する。

- external backend候補0件、1件、複数件。
- exact child/client-port/backend相関成功と、途中でidentityが変化した場合の失敗。
- observer開始前baseline transactionを対象と誤認しない。
- A/B別々のtransactionを取得し、Bのtotal queue waitとhandoff gapを混同しない。
- observer thread例外、欠測、timeoutでevidenceを確定しない。
- dry-runがJob/DB/service/backupを変更しない。
- DB環境fallback、service状態取得不能、active Job非0、migration不一致、HTTP非200、baseline不一致、backup tool/restore-list検証不可でfail closed。
- privacy scanが生PID/client port、credential、token、cookie/session、raw UNC path、account/SIDを拒否する。
- live modeが明示flag/confirmationなしに開始しない。
- manifest生成と全entry再検証。

thread/DB connectionは`finally`でcloseし、join timeout後のlive threadを残さない。

## Non-Goals

- 今回のiterationでのcanonical疑似本番Job投入、実backup、service停止/再起動。
- S2-SH-06残件、S2-PAR-01、並列worker、性能改善、transaction短縮、staging/swap。
- 6指標の閾値提案・承認代行、IFC20260723-001の流用。
- 製品queue、retry、dedupe、transaction境界、API/UIの仕様変更。
- 既存evidence、corrected/addendum、backup、manifestの修正・削除。
- `.reviewer/HANDOFF.md`の変更。

## Constraints

- MVPの最小変更。既存`measure_s2_cr08.py`のinline smoke用途を壊さない。
- 運用fixtureは可能なら新command/moduleとし、製品runtime pathへの影響を局所化する。
- OS/process観測には既存dependencyを優先し、新dependency追加は必要性を示す。
- timestampはUTCで、Job/Python clockとPostgreSQL server clockの出典を明記する。
- evidenceは追加のみ。runtime evidenceはgitignoredであることをhandoffへ明記する。
- credentialや`.env`値をstdout/stderr/evidence/test failureへ出さない。
- file書込は一時file→flush/fsync→atomic replace相当とし、不完全evidenceを正式manifestへ含めない。
- ユーザー既存変更を保持し、scope外fileを変更しない。

## Safety Stop Conditions

以下のいずれかでfail closedとする。

- 疑似本番environment identityを明示確認できない。
- active/running Jobが0でない。
- service/HTTP/DB/migration/check/canonical baseline/UNC/backup準備のいずれかが失敗。
- exact child processまたはDB backendが0件・複数件・途中変化。
- observerがtransaction開始前にarmedにならない、欠測、停止、clock混在。
- A/Bがdedupe、順序違反、同時running、unexpected Job起動。
- attempt/status/result/count/warning/business hashが期待外。
- credential/raw path/個人情報/生運用identifier混入の疑い。
- final active Job 0、service live state、HTTP 200へ戻らない。

安全停止時は未検証の成功を記録せず、取得済みのrestricted diagnostic、復旧確認、再実行条件だけをhandoffする。

## Acceptance Criteria

1. 外部worker exact childとPostgreSQL backendを一意に相関し、A/Bの実行transactionを別々に上下限付きで観測できる。
2. 候補0件/複数件、identity変化、observer失敗でfail closedし、正式evidenceを確定しない。
3. dry-run preflightはnon-mutatingで、Job作成、backup、service操作、業務file変更が0件である。
4. 誤った`.env`や通常開発DBへのfallbackを検出して停止する。
5. Job実行時間、total queue wait、handoff gap、transaction時間を別指標としてschema化する。
6. live modeは外部worker経路だけを使い、明示的なlive承認flagなしでは開始しない。
7. 6指標の閾値承認不足時は`not_evaluable`を維持し、S2-CR-08を合格へ変更しない。
8. 共有用evidenceにcredential、raw UNC path、個人情報、生PID/client port/worker ID/token/account/SIDがない。
9. 自動試験、Django check、migration drift、関連queue regression、`git diff --check`が合格する。
10. 今回は`specification/RELEASE.md`のS2-CR-08状態を「部分実施」から変更しない。dry-run結果を追記する場合も実地測定と誤認させない。

## Validation

- `quality.test_s2_cr08_measurement`と新規external observer/preflight test。
- `PersistentJobQueueApiTests`、`PersistentJobQueueRecoveryTests`、`PhaseTwoMasterUpdateTests`。
- backend全試験をfresh test DBで実行。
- Django `check`、`makemigrations --check --dry-run`。
- dry-runを疑似本番明示envで実行し、実行前後のJob count/hash、service PID/state、backup directory、業務count/hashが不変であることを確認。
- fixture出力JSONのschema、timestamp ordering、差分再計算、privacy denylist、manifestを再検証。
- `git diff --check`。
- frontendを変更しない限りfrontend build/lintは不要。既存lint issueを本scopeへ混ぜない。

## Deliverable

`.implementer/HANDOFF.md`にreviewer向けstructured handoffを作成し、以下を分離して記載する。

- 変更file、設計したprocess/backend相関method、failure mode。
- dry-run/preflightの項目別結果と、non-mutatingである証拠。
- 自動試験とregression結果。
- live modeが未実行であること、reviewer PASS後に必要な実地手順。
- 閾値承認入力の有無と`not_evaluable`維持。
- privacy、manifest、scope外の既存変更。
- 「検証済み事実」「未確認事項」「残リスク」「次の実地試験条件」。
