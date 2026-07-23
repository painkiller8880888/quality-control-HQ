# Handoff: planner → implementer

# Goal

S2-CR-08で未測定の2指標を補う、最小の測定fixtureとevidence schemaを作成・検証する。

1. 後続Jobの総queue waitを、後続Jobの生成時刻と開始時刻から測定する。
2. `master_update`のDB transaction開始・終了をJob実行開始・終了と独立に測定する。
3. 既存証跡で代替できないと確定し、fixtureの事前検証が通った場合に限り、疑似本番でcanonical `master_update` A→Bを1セット再測定する。
4. 6指標の閾値はimplementerが決めず、責任者の承認入力が得られた場合だけ判定に使用する。

# Context

## 検証済み事実

- `.reviewer/HANDOFF.md`のverdictはPASSだが、これは訂正対応へのPASSでありS2-CR-08合格ではない。
- `specification/RELEASE.md`のS2-CR-08は「部分実施」。CPU、メモリ、DB接続数、lock待ちの4/6指標は測定済み。
- `runtime/pseudoprod/evidence/s2-criterion-8-20260723-095921/summary.corrected.json`は、transaction時間とJob実行時間を区別できず、FIFO Bの生成時刻がないため総queue waitを確定できないと結論している。
- 既存証跡で確定できるのはA完了→B開始のdispatch/handoff gap 2.177371秒と、Bの初回queued観測→開始の下限576.041648秒だけである。
- `Job`には`started_at` / `finished_at`があるが、現在のmodelに永続的な`created_at`はない。`master_update`は`services.import_master_csv()`の`@transaction.atomic`内で動作する。
- S2-CR-08の6指標には承認済み閾値がない。S2-HTTP-01の`IFC20260723-001`はHTTP応答とJob全体時間用であり流用できない。
- corrected evidenceと原証跡は保持対象。変更・削除しない。

## 未確認事項

- 責任者が承認する6指標の閾値、責任者名/役割、approval ID、承認日、review期限。
- 外部observerによるDB transaction終了時刻の測定精度。これはポーリング間隔による上下限付きとし、真値と偽らない。

# Scope

## 1. 測定evidence schemaとfixtureの作成

新規証跡directoryを`runtime/pseudoprod/evidence/s2-cr-08-measurement-<timestamp>/`とし、少なくとも以下を独立fieldとしてUTC/ISO 8601で記録する。

- `job_a_created_at`, `job_a_started_at`, `job_a_finished_at`
- `job_b_created_at`, `job_b_started_at`, `job_b_finished_at`
- `job_b_total_queue_wait_seconds = job_b_started_at - job_b_created_at`
- `job_b_handoff_gap_seconds = job_b_started_at - job_a_finished_at`
- `transaction_backend_pid` ではなく、共有不要なhash化したbackend correlation identifier
- PostgreSQLの同一client backendで観測した`xact_start`
- `transaction_end_lower_bound` と `transaction_end_upper_bound`
- `transaction_duration_lower_bound_seconds` と `transaction_duration_upper_bound_seconds`
- observerの`poll_interval_seconds`
- Job時間とtransaction時間を分けた定義

Job生成時刻は、本番model/schemaへ新規migrationを追加する前に、fixtureが同一DB sessionのserver timestampとJob insert成立を相関づけて取得できるか検証する。厳密な生成時刻が取得できない場合のみ、`Job.created_at = DateTimeField(auto_now_add=True)`とmigrationを最小候補とする。その場合はqueue取得順・dedupe・API serializerに影響しないことを自動試験で確認する。

DB transactionは、worker子processとPostgreSQL client backendを既存証跡と同等のPID/client-port照合で一意に対応づけ、`pg_stat_activity.xact_start`を観測する。終了は同一backendの同一`xact_start`が消えた最後の観測区間で上下限を記録する。ポーリング値だけで単一の「正確なtransaction終了時刻」を作らない。

## 2. fixture単体検証

- 短時間の専用fixture/自動試験で、Job生成、queue待機、transaction開始、transaction終了上下限を独立記録できることを先に確認する。
- fixtureは計測のみ。製品のqueue意味論、retry、dedupe、transaction境界を変えない。
- fixtureで一意なbackend対応を証明できなければ安全停止する。

## 3. 疑似本番再測定

既存corrected evidenceでは2指標を代替できないため、以下の全ゲート成功時のみcanonical `master_update` A→Bを1セット実行する。

- Web/workerが`Running` / `Automatic`、HTTP 200、active Job 0。
- migration/checkが正常。
- canonical input identity/hashと期待件数を既存baselineと照合。
- 更新前の業務表count/stable-content hash、InspectionFile distribution/pathsetを取得。
- custom-format full backupを取得し、restore-listを読めることとSHA-256を確認。
- configured UNC rootsはread/list成否のみ証跡化し、raw pathを保存しない。
- observerとmeasurement schemaの事前検証が成功。

AとBは安全なcanonical入力とし、BをAの後続queued Jobにする。A/Bが別Jobとなる既存の安全な手法が再現できなければ実行しない。実行後は両Jobの試行、最終状態、結果件数、warning、business hash、active Job 0、service live stateを確認する。

## 4. 閾値承認入力

6指標それぞれにつき、次を含む承認入力だけを受理する。

- 指標の定義と単位
- warning/fail閾値と比較演算子
- approval ID、承認日、承認者の役割
- 適用環境/データ量、review期限、再検討trigger

承認入力がない場合、測定値は記録してもverdictを`not_evaluable`、S2-CR-08を「部分実施」のままとする。閾値候補をimplementerの提案や承認済み値として記録しない。

## 5. 最小更新

- 追加evidenceは原本不変・追加のみとし、SHA-256 manifestを付ける。
- `specification/RELEASE.md`はS2-CR-08の実施行だけを、実測・承認状態に合わせて最小更新する。
- 永続`Job.created_at`が不要なら製品model/migrationは変更しない。必要な場合だけmodel、migration、直接関連testに限る。

# Non-Goals

- S2-SH-06、S2-PAR-01、並列worker導入、性能改善、transaction短縮、staging/swap方式の実装。
- 計測に不要なAPI/UI変更、リファクタ、DB schema変更。
- 個人AD accountのpassword/expiry/lockout変更。
- 承認のない閾値の作成、IFC20260723-001の流用、閾値なしでの合格判定。
- 既存の原証跡、corrected evidence、addendum、manifestの修正・削除。

# Constraints

- MVPの最小変更。測定fixtureは製品動作を変えない。
- 時刻は同一クロック基準のUTCで取得する。observer timestampとDB server timestampを混同しない。
- credential、token、cookie、session、raw request/header/body、raw UNC path、個人名、account名、SID、worker ID、execution token、生PID/client portを共有用証跡に保存しない。照合に必要な場合はメモリ上だけで使い、evidenceにはbooleanまたはSHA-256化したcorrelationだけを残す。
- 追加試験では実在業務fileを変更しない。自動restoreを前提に続行しない。
- 原証跡とbackupは削除しない。runtime evidenceがgitignoredであることをhandoffに明記する。

# Safety Stop Conditions

以下のどれかで新規Job投入前または実行中に安全停止し、復旧可能性とlive stateを確認してreviewerへ報告する。

- preflightでactive Jobが0でない、service/HTTP/DB/migration/check/backup/restore-list/canonical baselineのいずれかが不正。
- input identity、期待件数、業務hash/count、UNC read/list成否が既存baselineと不一致。
- fixtureがJob生成時刻を厳密に取得できない、またはworker子processとDB backendを一意に対応づけできない。
- 同じbackend/transactionを継続観測できない、observerが欠測・停止する、時計基準が混在する。
- A/Bが同一Jobにdedupeされる、BがA実行中に開始する、想定外のJobが起動する。
- AまたはBが想定外状態、timeout、warning、結果件数不一致、business hash不一致となる。
- credential/raw UNC path/個人情報が証跡に混入した疑い。共有用evidenceは確定せずrestricted扱いで報告する。
- 試験fixture/DDLが残る、active Jobが0に戻らない、serviceが最終live stateに戻らない。

# Acceptance Criteria

1. evidence schemaがJob生成/開始/終了、総queue wait、handoff gap、DB transaction開始/終了上下限、poll精度を独立fieldで表現する。
2. fixture単体検証で、後続Jobの`created_at < started_at <= finished_at`と、transactionの`xact_start < end_lower_bound <= end_upper_bound`を機械的に確認できる。
3. Job実行時間、総queue wait、handoff gap、transaction時間を別指標とし、dispatch gapを総queue waitとしない。
4. transaction終了がポーリング区間でしか確定できない場合、lower/upper boundと最大誤差を保持し、単一の厳密値として扱わない。
5. 疑似本番再測定を行う場合、全preflight/backupゲートに成功し、A/Bが逐次で各attempt 1・canonical success、最終active Job 0、business baseline不変、Web/worker Running・Automatic、HTTP 200となる。
6. 再測定を行わない場合、代替証跡または安全停止理由を、未検証の成功とせず明記する。
7. 新規evidenceにcredential、raw UNC path、個人情報、生の運用identifierが含まれず、原証跡はhash一致で不変である。
8. 6指標全てに承認入力がある場合だけ閾値判定を行う。不足時は`not_evaluable`およびS2-CR-08「部分実施」を維持する。
9. 作成した各evidence fileのSHA-256 manifestが実fileと一致する。
10. `specification/RELEASE.md`は実測事実、測定誤差、承認状態、証跡path/hash、残課題と一致する。

# Validation

- fixtureの直接単体試験。永続`Job.created_at`を追加した場合はmodel/migration checkとJob queueの関連自動試験。
- Django `check`、migration drift check、影響するbackend test。製品フロントを変更しない限りfrontend buildは不要。
- fixture出力JSON/JSONLのparse、必須field、timestamp ordering、時間差再計算。
- source/corrected evidenceの実行前後SHA-256一致、新規manifestの全entry一致。
- 再測定時はbackup SHA-256/restore-list、pre/post business count/hash、Job transition、transaction bound、queue wait、service/HTTP/active Jobの最終状態を再計算。
- privacy scanでcredential/token/cookie/session/raw UNC path/account名/SID/生PID/client portが共有用evidenceにないことを確認。
- `git diff --check`。

# Deliverable

`.implementer/HANDOFF.md`にreviewer向けstructured handoffを作成し、以下を分離して記載する。

- 変更fileと追加evidenceの一覧。
- fixture/evidence schemaの時刻定義、クロック出典、測定誤差。
- 既存証跡で代替不能と判断した根拠。
- 疑似本番再測定を実施したか、安全停止したか、その根拠。
- 実測値、再計算式、測定成否、閾値、判定を6指標別に示した表。
- 閾値承認入力の有無。入力がある場合はapproval ID/承認日/役割/review期限、ない場合は`not_evaluable`と残課題。
- preflight、backup、live service、business baseline、privacy、manifest、test、`git diff --check`の結果。
- 「検証済み事実」「未確認事項」「残リスク」を別立てで記載する。
