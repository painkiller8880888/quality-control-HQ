# 正式リリース要件

## 1. 位置づけと正本

本書は、Quality Control HQを正式リリースするための恒久的な要求、設計原則、試験ID、受入基準、必須証跡、リリース判定条件を定義する。正式リリースの可否は本書の基準で判定する。

実施日、担当者、実測値、Job ID、証跡ファイル、進捗、TODO、レビュー履歴、暫定案は本書に記録しない。これらはGitHubのIssue／PR／commitを正本とし、過去の詳細記録は凍結アーカイブを参照する。

数値目標や運用条件は、実装者が推測して合格扱いにしてはならない。業務責任者、運用責任者、必要に応じてアプリ責任者が、閾値、責任者、期限、切戻し条件を承認してから判定する。

## 2. 安定した設計原則

- 正式リリースでは、承認済み設定・コード・DB migration・テスト・運用手順を一つの版として識別できるようにする。
- 長時間処理や外部資源への副作用はHTTP要求から切り離し、永続的なJob、専用worker、冪等性、資源単位の排他、停止復旧を備える。
- DB更新は利用者へ中間状態を公開せず、失敗時に部分更新を確定しない。再試行や重複配送があっても二重登録・二重副作用を起こさない。
- 認証、認可、所有者分離、CSRF、監査、エラー応答、secret管理をfail-closedで設計する。内部パス、stack trace、secret、資格情報を利用者へ返さない。
- 外部依存（Windows、Office、ERP、共有フォルダ、プリンタ、サービスアカウント）を明示し、障害時の検出・復旧・再実行・二重実行防止を検証する。
- 受入基準を満たさない測定、不完全な証跡、再現不能な自己申告を合格の根拠にしない。

## 3. Critical要求

Criticalが1件でも受入基準を満たさない場合、正式リリース不可とする。

| 項目 | 防止するリスク／背景 | 受入基準 | 必須証跡 |
|---|---|---|---|
| 本番セキュリティ設定 | 開発用secret、デバッグ設定、過度に広いhost/origin、cookie設定不備による不正利用や情報漏洩 | 本番設定でsecretを外部管理し、`DEBUG=False`、host/originを限定、HTTPS、Secure/HttpOnly/SameSite cookieを設定する。Django deployment check、認証試験、CSRF試験が全件成功する | 承認済み設定票、check出力、認証／CSRF試験結果 |
| 正式配信構成 | 開発サーバー依存、静的・media配信不備、再起動後の停止、プロセス異常終了による業務停止 | 承認済みWSGI/ASGI、静的・media配信、TLS終端、サービス構成で、起動・停止・OS再起動・プロセス異常終了後の復旧手順が各1回成功する | 構成図、手順書、実施ログ、復旧ログ |
| Job非同期化と排他 | HTTP timeout、再送による二重処理、共有資源競合、worker停止による永久`running` | 承認済み応答時間・timeout・再試行条件の下で、永続queue/worker、冪等性、同一資源lockを実装し、同時要求、worker停止再開、重複配送の試験が全件成功する | 閾値承認記録、状態遷移表、競合表、試験ログ |
| 分類判定順の業務承認 | 複数条件一致や登録経路差による誤分類、表示・発行・集計の不一致 | 複数条件一致、全クラス、class 9、override有無を含む承認済みゴールデンデータで、取込・表示・発行・集計の期待値が全件一致する | 承認済みゴールデンデータ、回帰試験結果 |
| バックアップ／復元 | DB、media、帳票、共有ファイルの破損・消失時に復元できないリスク | 承認済みRPO/RTO、暗号化、保持期間に従い、本番同等データを別環境へ復元する。件数、制約、ファイル参照、ログイン、主要E2Eが整合する | 方針承認、backupログ、復元記録、整合確認表 |
| DB本番移行／復旧 | migrationの長時間lock、途中失敗、切戻し不能によるデータ破壊 | 匿名化した本番相当データへ全migrationを適用し、所要時間・lock影響を記録する。途中失敗を発生させ、承認済みrollbackまたはrestore手順で復旧し、整合確認が全件成功する | 移行計画、実行ログ、失敗復旧記録、照合結果 |
| エラー情報漏洩と異常時契約 | 内部path、例外、stack、secretの漏洩や、異常時の二次TypeError | 既知の異常経路で契約どおりのstatus/JSONを返し、500/TypeError、内部path、stack、secretを応答に含めないことを自動試験で確認する | 異常系一覧、契約試験結果、応答サンプル |
| 自己登録方針 | 匿名登録による不正利用、権限付与、監査不能 | 許可・招待・管理者作成のいずれかを責任者が承認し、選択外経路をUI/APIとも利用不可にする。選択経路の監査と濫用防止試験が成功する | 方針承認、RBAC／登録試験結果、監査ログ |
| Excel／印刷運用 | 対話型Office、マクロ、プリンタ、共有権限の失敗、lock・紙切れ・Excel残留による停止や二重発行 | Windows、Office、プリンタ、サービスアカウント、ライセンスを承認し、無人E2Eと、file lock・紙切れ・共有断・Excel残留からの復旧試験が全件成功する | 環境票、承認記録、E2E／障害試験ログ |

## 3.1 R1-02b Stage B read-only callback contract

Stage BのSnapshot、Catalog、Jobs、StateおよびPowerShell／Python helper境界は、以下のread-only契約に従う。公開結果、hash、manifest、evidenceは、ここで定義したexact field setとfail-closed条件から外れてはならない。

### 3.1.1 Snapshot hash contract

Snapshotのcanonicalizationは、既存`deployment/postgresql/stage_b_snapshot.py`の`digest()`、`canonical_json_bytes()`および既存golden testを正本とする。別のJSON encoding、key ordering、row orderingを導入しない。

Snapshotは、復元内容の同値比較に使う`semantic_payload`と、sourceの同一DB・同一内容を確認する`baseline_payload`を別々に構成する。

`semantic_payload`のexact key setは次のとおりとする。

```text
empty_proof
schema_inventory
migrations
quality_master
quality_masterclass
quality_structure
quality_inspectionfile
quality_appsetting
inspection_file_path_set_hash
```

`semantic_hash = digest(semantic_payload)`とする。`baseline_payload`のexact key setは、次の`identity`と、上記semantic payloadそのものを持つ`semantic`とする。

```text
identity:
  endpoint_hash
  database_hash
  oid_hash
  role_hash
  server_version_num_hash
semantic: semantic_payload
```

`baseline_hash = digest(baseline_payload)`とする。`host_hash`と`port_hash`は内部互換のために存在してもよいが、baseline payloadおよび公開callback resultへ含めない。日時、接続PID、backend PID、実行時刻、query durationその他のvolatile valueを公開結果またはhashへ追加しない。

公開Snapshot callback resultは次のshapeに固定する。

```text
{
  identity: { oid_hash },
  baseline_hash,
  semantic_hash
}
```

restore modeでは、観測した`oid_hash`が`expectedSourceOidHash`と同じ場合を成功扱いせず、fail-closedとする。

### 3.1.2 Catalog三state contract

Catalogは対象database名についてPostgreSQL catalogをread-onlyで照会し、候補が0件または1件であることを要求する。`connections`は対象DBへの他backend数であり、probe自身のbackendを除外する。

| state | 固定条件 |
|---|---|
| `absent` | 対象databaseが存在しない。`oid_hash = null`、`owner_hash = null`、`connections = 0`。 |
| `existing_empty` | 対象databaseが存在し、OIDとownerが期待値に一致し、他connectionが0で、Snapshotの`empty_proof.is_empty = true`。`oid_hash`と`owner_hash`を返す。 |
| `eligible` | 対象databaseが存在し、OIDとownerが作成後に固定されたrestore identityに一致し、他connectionが0で、Snapshotの`empty_proof.is_empty = false`。`oid_hash`と`owner_hash`を返す。 |

複数候補または判定不能、OID不一致、owner不一致、他connectionが1以上、empty proofの欠測または型不正、query失敗またはtimeoutは、新しいstateへ丸めず固定reason codeでfail-closedとする。`eligible`は一般に削除してよいDBを意味せず、同一executionで作成・記録されたrestore identityに一致する場合だけCleanup guardとして使用する。

### 3.1.3 Restore identity lifecycle

PostgreSQLのOIDは作成時に割り当てられるため、PlanOnlyで存在しない復元先のOIDを予測しない。

- `restore.state = "absent"`のPending manifestでは、`restore.oid_hash = null`を必須とする。`restore.owner_hash`は、作成前でも期待するrestore ownerのhashとして保持する。
- `restore.state = "existing_empty"`では、有効な`restore.oid_hash`を必須とする。
- sourceまたはprotected targetとの衝突判定は、利用可能なendpoint、database、OID identityを用いてfail-closedで行う。

CreateRestoreの成功結果は次のexact shapeとする。

```text
{
  success: true,
  oid_hash,
  owner_hash
}
```

作成直後にCatalogを再観測し、CreateRestore result、Catalog result、manifestのendpoint、database、expected ownerがすべて一致した場合だけ、restore identityをinvocation-localに固定する。OIDまたはownerの欠測、不一致、複数候補、timeoutは作成成功として先へ進めない。

Execute evidenceには、実際に使用した次のexact `restore_identity`を保存し、manifest hashへ結び付ける。

```text
restore_identity:
  endpoint_hash
  database_hash
  oid_hash
  owner_hash
```

Execute approvalには`manifest_sha256`を必須とし、Cleanup approvalには`manifest_sha256`と`execution_sha256`の両方を必須とする。actionごとのexact property setをvalidatorで固定する。Cleanupは、approvalがmanifestとexecution evidenceを正確に指名し、Catalogが`eligible`で、Catalog identityがExecution evidenceの`restore_identity`と一致し、他connectionが0で、active Jobsが0である場合だけ許可する。

### 3.1.4 Jobs contract

active Jobは全Jobについて次のpredicateだけで数える。

```sql
status IN ('queued', 'running')
```

`resource_key`、`job_type`、追加の論理削除filterは使用しない。結果は0以上の32-bit整数とする。query失敗、timeout、負数、overflow、collection、型不正はfail-closedとする。

### 3.1.5 State observation contract

`State(manifest)`はmanifestをそのままechoして観測を省略してはならない。各fieldの正本は次のとおりとする。

| field | 観測元 |
|---|---|
| `jobs` | Jobs providerによるDB再照会 |
| `source` | source Snapshotと接続identityの再観測 |
| `source_baseline_hash` | source Snapshotの再計算値 |
| `restore` | Catalog。存在する場合は必要に応じてrestore Snapshotも使用 |
| `clients` | 許可されたread-only binary/version probe |
| `storage.capacity_bytes` | 許可されたread-only filesystem capacity probe |
| `storage.root_hash` | probe対象として正規化したrootのhash |
| `storage.required_bytes`／`retention_days` | manifestに固定されたpolicy値を比較用に保持 |
| `owners` | PostgreSQL catalogと固定されたrestore identity |
| `services` | Windows serviceのread-only state probe |

service probeで許可する操作は`Get-Service`または同等のread-only CIM queryだけとする。`Start-Service`、`Stop-Service`、`Restart-Service`、設定変更、process killを含めない。service probeは内部的に`running`、`stopped`、`missing`、`unknown`を区別し、current-state guardが要求する箇所では`running`以外をfail-closedとする。restoreが`absent`の場合、Stateおよびvalidatorは`restore.oid_hash = null`を許可し、存在する場合は有効なhashを必須とする。

### 3.1.6 DB timeout and injection boundary

すべての外部観測に有限timeoutを設定する。既定値はPostgreSQL connect 5秒、PostgreSQL statement/query 15秒、lock 1秒、helper process transport 60秒とする。production値は設定可能だが、無制限値を許可しない。

testおよびprovider境界では、connection factory、query runner、clock／timeout source、helper invokerを注入可能とする。DB接続はread-only transaction／sessionとして構成し、少なくとも`default_transaction_read_only=on`を維持する。read-only providerからDDL／DML、advisory lock取得、service mutationを実行しない。

### 3.1.7 Helper transport schema

PowerShell 5.1とPython helper間はstdin／stdoutの単一JSON envelopeを使用する。Requestの共通shapeは次のとおりとする。

```text
{
  schema_version: 1,
  operation: "snapshot" | "catalog" | "jobs" | "state",
  payload: { ...operation-specific exact payload... },
  timeouts: {
    connect_seconds,
    query_seconds,
    lock_seconds
  }
}
```

Responseの共通shapeは次のとおりとする。

```text
{
  schema_version: 1,
  success: true | false,
  result: object | null,
  reason: null | fixed_reason_code
}
```

成功時は`result`を各callbackのexact validatorへ渡す。失敗時は`result = null`とし、raw exception、SQL、connection string、host、database、path、stdout／stderrを公開しない。extra／missing field、複数JSON、非JSON、型不正、timeoutはすべてfail-closedとする。

## 4. High要求

Highは、受入基準を満たすか、残存リスク・期限・責任者を明記した期限付き受容をリリース判定会で承認する。

### 4.1 登録経路別の分類安全化

- OCRは工程分類（class 1〜5）を優先し、工程判定不能時にマスタへ明示登録された場合だけclass 8を使用する。品名等からclass 8を推測せず、class 6/7へフォールバックしない。
- 見取り図は工程分類（class 1〜5）だけを使用し、class 8や製品検査ファイルへフォールバックしない。
- Excel／コード検索による手動追加は製品検査（class 6または7）だけを使用し、機械設定へフォールバックしない。
- class 1と2、class 6と7が同時成立する場合は、対象作成を中止して原因を記録する。
- 登録経路が異なる工程検査と製品検査は、確定クラス別の対象・履歴として同日に共存できる。
- class 9は特殊検査専用APIからのみ作成し、通常分類に参加させない。
- 対象には`registration_route`と確定クラスを保存し、チェック更新・表示・検査書選択は`target_id`と確定クラスを基準にする。確定クラス不明データは推測更新しない。

受入では、class 1/2競合、class 6/7競合、ファイルなし、class 2+7共存、class 1+6共存、通常クラス+9共存、別クラス間で履歴が混ざらないことを確認する。

### 4.2 その他の要求

| 項目 | 受入基準 |
|---|---|
| 認証防御 | ログイン試行制限、セッション期限・失効、パスワード方針、CSRF、無効ユーザー遮断を試験する |
| RBAC／所有者分離 | 全APIの匿名・worker・admin、他利用者ID・日付による越権を自動試験する |
| 監査 | マスタ、設定、レイアウト、機械、発行、日報、削除・非表示について、誰がいつ何を行ったかを記録し、改ざん防止と保持方針を決定する |
| ログ／health／監視 | 構造化ログ、相関ID、health/readiness、DB・worker・共有・印刷監視、通知と一次対応手順を実地確認する |
| CI／品質ゲート | backend test、frontend build、lint、migration check、依存脆弱性scan、secret scanを必須化する |
| 統合／負荷／長時間試験 | 最大日数・件数、367日集計、同時利用、ERP timeout、大容量ファイルを本番相当で合格させる |
| マスタ更新方式 | 現行の単一transactionによる `update_or_create` と InspectionFile 全削除再作成について、本番相当件数でlock時間・rollback・参照整合性を試験する。`staging -> validation -> swap` を採用する場合は設計、移行、切替失敗時の復旧基準を承認する |
| dependency lock／脆弱性 | Python/Node依存を再現可能に固定し、SBOM、定期更新、重大CVEのSLAを設定する。ERP経路のimport/E2Eをクリーン環境で成功させる |
| upload／media | 5MB、JPEG/PNG/WebP検証、保存先分離、マルウェア対策、quota、孤児ファイル清掃、backupを検証する |

## 5. Medium要求

- アクセシビリティ、対応ブラウザ・解像度、タイムゾーン・営業日境界を明文化して試験する。
- データ保持・削除、個人情報、アバター、監査ログの保管期間と問い合わせ手順を決める。
- 運用手順書、障害対応、利用者教育、管理者引継ぎ、変更管理、リリースノートを整備する。
- レイアウト背景画像、所有者ごとの閲覧範囲、複数adminの競合解決、版管理の仕様を決める。

## 6. 試験IDと安定した受入基準

以下のIDは試験項目を識別するためのものであり、個別の実施結果や証跡場所はGitHubまたは凍結アーカイブに記録する。表中の「承認済み条件」は、該当する閾値・RTO・retry方針が事前承認されていることを意味する。

| 試験ID | 試験内容 | 受入基準 |
|---|---|---|
| S2-SH-01 | OS再起動後のworker自動起動 | workerが承認済みサービス設定で自動起動し、Jobの受付・実行・完了と資源解放を確認する |
| S2-SH-02 | OS再起動後の検査書共有フォルダ読取 | 設定済みフォルダを読み取れ、索引件数・内容・参照整合性が再起動前後で一致する |
| S2-SH-03 | 共有切断・復旧時の部分索引防止 | 切断時に部分索引を確定せず、安全な失敗または承認済み再試行となり、復旧後に整合した索引を作成する |
| S2-SH-04 | 検査書共有フォルダの読取 | 対象フォルダのread/listが成功し、業務上許容しない警告が残らない |
| S2-SH-05 | 履歴・帳票などの共有書込 | 一時ファイルのwrite/read/overwrite/deleteが成功し、対象ファイルを意図せず変更しない |
| S2-SH-06 | サービス資格情報の変更・期限切れ運用 | 専用サービスアカウントの資格情報変更・期限切れを検出し、承認済みRTO内に復旧する。資格情報や個人アカウントを証跡へ露出しない |
| S2-HTTP-01 | APIからのJob受付と202応答 | 承認済みのWeb応答・Job実行・client timeout条件内で、処理完了を待たずJob IDと202を返す。warning/fail条件と測定範囲を証跡化する |
| S2-HTTP-02 | 重複要求の同一Job集約 | 同一内容の再送・別利用者からの重複要求が1回の実処理に集約され、同じJobを返す |
| S2-REF-01 | 更新中の参照APIのatomicity | 更新前または更新後の整合したsnapshotだけを返し、mixed、件数欠落、境界をまたぐ中間状態を返さない |
| S2-REC-01 | worker停止位置別の復旧 | 処理開始前、処理中、DB反映直前、DB反映直後の停止で、永久`running`、二重更新、中間データを残さず復旧する |
| S2-DB-01 | 一時DB切断時の復旧 | DB切断時にatomic rollbackまたは承認済み再試行を行い、最終状態と業務データの整合性を確認する |
| S2-DB-02 | lease失効時の再試行・安全な失敗 | retry可能なJobは承認済み回数・間隔で再試行し、外部副作用を持つJobは安全に失敗して自動二重実行しない |
| S2-DB-03 | Job重複配送の安全性 | 同一Jobを逐次・同時に配送しても業務関数は1回だけ実行され、旧executorは復旧後の試行をfinalizeできない |
| S2-TO-01 | timeout時の再試行と最終状態 | timeout発生時に承認済みretry回数・間隔・最終状態となり、資源とworker leaseを解放する |
| S2-PAR-01 | 独立Jobの並列化判定 | 並列化する場合は資源単位の排他、依存待機、capacity、復旧を検証し、条件を満たさない場合は期限・責任者付きで延期を承認する |
| S2-CR-08 | transaction時間、lock待ち、CPU、メモリ、DB接続数、後続Job待ち時間の測定 | 6指標を同一の相関定義で全区間測定し、承認済みthreshold内であることを確認する。相関不能・欠測・coverage不足は合格にせず、再測定または未評価として扱う |

## 7. 必須証跡の種類

- 承認済み設定票、構成図、責任者・期限・閾値・切戻し条件。
- Job状態遷移、競合・依存関係、冪等性、lock、retry、workerサービスの設計と試験ログ。
- 分類のゴールデンデータ、期待値、回帰試験結果。
- backup、restore、migration、rollback、復旧、件数・制約・参照整合性の記録。
- 認証、CSRF、RBAC、所有者分離、監査、異常応答、情報漏洩防止の試験結果。
- Windows、Office、ERP、共有フォルダ、プリンタ、サービスアカウントの環境票と障害復旧ログ。
- CI、build、lint、migration check、dependency、secret scan、統合・負荷・長時間試験の結果。
- 試験対象、入力、判定、実行環境、証跡の完全性を再確認できるmanifestまたは同等の整合記録。secret、token、資格情報、不要な個人情報は含めない。

## 8. リリース不可条件と最終受入

次のいずれかに該当する場合は正式リリース不可とする。

- Criticalの受入基準または必須証跡が一つでも欠けている。
- 閾値、責任者、期限、切戻し条件が未承認のまま合格判定している。
- 試験結果が再現不能、測定範囲不足、相関不能、または中間状態・二重処理・情報漏洩を示している。
- Highの残存リスクについて、期限・責任者付きの受容がない。
- 未決事項の判断記録、運用手順、障害対応、rollback条件が揃っていない。

最終受入には、Critical全項目の証跡、Highの合格または期限付きリスク受容、未決事項の判断記録が必要である。本番同等環境で「ログイン→取込→分類→チェック→検査書→日報→サマリー」のE2E、障害・復元・再起動試験を実施し、既知制約、運用責任者、rollback条件をリリース判定会で承認する。

## 9. リリース前に決定が必要な未決事項

1. 登録経路別分類のゴールデンデータと、機械31をclass 2へ直した結果の業務承認。
2. 匿名自己登録を許可するか、招待または管理者作成に限定するか。
3. レイアウトを共有資産とするか、所有者ごとに閲覧範囲を隔離するか。編集操作はadmin限定とする。
4. `issued`を印刷指示受付、スプール投入、物理印刷完了のどの時点とするか。
5. 対応するWindows、Office、プリンタ、ERPの版、サービスアカウント、ライセンス。
6. RPO/RTO、保持期間、監査ログ閲覧者、障害通知先。
