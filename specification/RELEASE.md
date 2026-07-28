# 正式リリース準備仕様

## 1. 位置づけ

現行実装はMVPである。本書は正式リリースに不足する要素、優先度、受入基準を定義する。`Critical` が1件でも未達の場合は正式リリース不可とする。`High` はリリース判定会で残存リスクと期限・責任者の承認を必須とする。

## 2. Critical

数値目標が必要な項目は、実装開始前に業務責任者と運用責任者が閾値、責任者、承認期限を記録して承認する。未承認の閾値を実装者が仮定して合格扱いにしてはならない。

| 項目 | 現状/リスク | 合否判定可能な受入基準 | 必須証跡 |
|---|---|---|---|
| 本番セキュリティ設定 | 固定SECRET_KEY、DEBUG=True、localhost系ALLOWED_HOSTS、開発起動 | 本番設定で secret 外部管理、DEBUG=False、host/origin限定、HTTPS、Secure/HttpOnly/SameSite cookie を設定し、Django deployment check と認証/CSRF試験が全件成功 | 承認済み設定票、check出力、試験結果 |
| 正式配信構成 | Django runserver と Vite dev 前提 | 承認済み構成どおりのWSGI/ASGI、静的/media配信、TLS終端で、起動・停止・OS再起動・プロセス異常終了後の復旧手順を各1回実施して成功 | 構成図、手順書、実施ログ |
| ジョブ非同期化/排他 | HTTP内同期。ERPは最大300秒、Excel/印刷競合の恐れ | 責任者・期限付きで応答時間/timeout/再試行回数を承認後、永続queue/worker、冪等性、同一資源lockを実装し、同時要求・worker停止再開・重複配送の試験が全件成功 | 閾値承認記録、ジョブ状態遷移表、試験ログ |
| 分類判定順の業務承認 | 現行 `1/2→3→6→7→4→5→8` と旧仕様が不一致 | 複数条件一致、全クラス、クラス9、override有無を含むゴールデンデータを品質管理責任者が承認し、取込・表示・発行・集計の期待値が全件一致 | 承認済みデータ、回帰試験結果 |
| バックアップ/復元 | DB/media/Excel/共有ファイルの手順・実績なし | 責任者・期限付きでRPO/RTO、暗号化、保持期間を承認後、本番同等データを別環境へ復元し、件数・制約・ファイル参照・ログイン・主要E2Eの整合確認が全件成功 | 方針承認、バックアップログ、復元記録、整合確認表 |
| DB本番移行/復旧 | migrationの本番データ量リハーサルなし | 匿名化した本番相当データで全migrationを適用し、所要時間・lock影響を記録する。途中失敗を発生させ、承認済みrollback/restore手順で復旧し整合確認が全件成功 | 移行計画、実行ログ、失敗復旧記録、照合結果 |
| エラー情報漏洩/異常時TypeError | 内部path/例外返却と `error_response(status=...)` の潜在障害 | 既知の全異常経路で契約どおりのstatus/JSONを返し、500/TypeError、内部path、stack、secretを応答に含まないことを自動試験で確認 | 異常系一覧、契約試験結果、応答サンプル |
| 自己登録方針 | 匿名からworker即時作成 | 許可/招待/管理者作成のいずれかを責任者・期限付きで承認し、選択外経路がUI/APIとも利用不可、選択経路の監査と濫用防止試験が成功 | 方針承認、RBAC/登録試験結果、監査ログ |
| Excel/印刷運用 | 対話型Office、マクロ、プリンタ、共有権限依存 | Windows/Office/プリンタ/サービスアカウント/ライセンスを責任者・期限付きで承認し、無人E2Eとファイルlock・紙切れ・共有断・Excel残留からの復旧試験が全件成功 | 環境票、承認記録、E2E/障害試験ログ |

### 2.1 Criticalに対するリリース対策方針（段階的実装計画）

Criticalは一括で実装せず、障害の影響範囲を限定しながら段階的に対策する。ただし、途中段階の完了をもって正式リリース可とはしない。正式リリースには本章のCritical全項目について、受入基準と必須証跡が揃っていることを必要とする。

#### 基本原則

- 各段階の開始前に対象、責任者、期限、合否基準、切戻し条件を記録する。
- 1段階ごとに本番同等環境で試験し、前段階の回帰試験に合格してから次へ進む。
- 長時間処理、外部資源、データ更新をHTTPリクエストから切り離し、失敗や再起動後も状態を失わないようにする。
- 排他はシステム全体を止める単一ロックではなく、競合する資源と依存関係を明示して適用する。
- 未対応のCriticalは未解消として管理し、期限付きの作業計画をリリース判定会へ提示する。

#### 対策ロードマップ

| 段階 | 対象 | 主な成果 | 完了しても残るCritical |
|---|---|---|---|
| 0. 方針確定 | 全Critical | 閾値、責任者、期限、採用OS、DNS/LAN範囲、ジョブ競合表、分類順、自己登録方針を承認 | 実装・試験未完了の全項目 |
| 1. 疑似本番基盤 | 本番セキュリティ設定、正式配信構成、エラー情報漏洩の一部 | 現在の開発PC上にPostgreSQL/Djangoの疑似本番構成を作り、Waitress、静的配信、サービス常駐、ネットワーク制限、`DEBUG=False`を検証 | 共有PCへの本番移行、異常系試験、および他Critical |
| 2. ジョブ基盤 | ジョブ非同期化/排他 | 永続queue、専用worker、`quality_master`排他、冪等性、停止復旧、競合試験 | ジョブ以外の未完了Critical |
| 3. 業務・認証 | 分類判定順、自己登録方針、エラー情報漏洩 | 承認済みゴールデンデータ、登録経路制限、異常系契約試験 | 復旧・移行・Excel運用 |
| 4. 復旧・移行 | バックアップ/復元、DB本番移行/復旧 | 本番相当データによる移行、失敗、復元リハーサル | Excel/印刷運用 |
| 5. 外部運用 | Excel/印刷運用 | 無人E2E、排他、障害復旧、実行環境とライセンスの承認 | なし。全証跡が揃った場合のみリリース判定へ進む |

#### 第1段階: 現在PCでの疑似本番ネットワーク・配信構成

本段階では共有PCを使用しない。現在開発に使用しているWindows PC上にPostgreSQLと疑似本番Djangoを構築し、SQLサーバー、アプリサーバー、サービス常駐、ネットワーク制限、更新およびエラーハンドリングの挙動を本番移行前に確認する。検証完了後、同じ構成と承認済みビルドを共有PCへ移して本番環境を構築する。

##### 環境とデータの分離

- 現在PC上では1つのPostgreSQLインスタンスを使用し、その中に疑似本番用`quality_prodlike`と開発用DBを別データベースとして作成する。既存データ保全のため、当面の開発DBは現行`quality_control_hq`を維持する。同じPostgreSQLサーバーは使用するが、疑似本番と開発でデータベース、schema、DBユーザーは共有しない。
- 疑似本番Djangoは`quality_prodlike`だけに接続し、開発中のDjangoとテストは`quality_dev`だけに接続する。開発コードから`quality_prodlike`へ接続する運用は禁止する。
- DBユーザーは疑似本番実行用、開発用、migration実行用に分離する。通常の疑似本番サービスにはschema変更権限を与えず、疑似本番へのmigrationは承認済みビルドの更新手順からだけ実行する。
- 疑似本番と開発で、環境変数、`SECRET_KEY`、DB認証情報、media、ログ、作業用ディレクトリを分離する。疑似本番データを開発DBへ複製する場合は、業務データ・個人情報の匿名化と複製承認を必要とする。
- PostgreSQLは現在PC内の`127.0.0.1`または`localhost`だけで待ち受ける。疑似本番Djangoと開発Djangoはいずれもlocalhost接続とし、TCP `5432`をLANへ公開しない。開発環境を別PCへ移す場合は、直接公開ではなく承認済みSSHトンネルを使用する。

##### 疑似本番アプリの配信

- 疑似本番Djangoは開発用`runserver`ではなく、Waitressで`0.0.0.0:8080`に公開する。WinSWを第一候補として専用の低権限サービスアカウントでWindowsサービス化し、自動起動、異常終了時の自動再起動、標準出力・エラーログの保存を設定する。
- Vite開発サーバーは疑似本番配信に使用しない。フロントエンドを事前ビルドし、生成物をDjangoと同じ`8080`番ポートから配信する。開発用Vite/Djangoは開発用途に限り、疑似本番クライアントから到達できないようにする。
- 疑似本番クライアントはEdgeまたはChromeから`http://<現在PCのDNS名>:8080`へアクセスする。HTTPによる社内LAN公開は管理者承認済みの疑似本番条件として扱い、承認者、承認日、対象DNS名、ポート、LAN範囲を設定票に記録する。
- WindowsファイアウォールではTCP `8080`の受信を承認済み社内LANの送信元範囲に限って許可する。Publicプロファイルおよび範囲外ネットワークからの受信は拒否し、`5432`の受信許可規則は作成しない。
- 疑似本番Djangoは`DEBUG=False`、承認済みDNS名だけの`ALLOWED_HOSTS`、明示的なHTTP originの`CSRF_TRUSTED_ORIGINS`を使用する。`SECRET_KEY`とDB認証情報はソースコード外で管理する。HTTPではSecure cookieを使用できないため、疑似本番専用設定として例外を明示し、開発設定や将来の本番設定へ暗黙に流用しない。

想定する疑似本番経路は `Edge/Chrome -> 社内LAN -> 現在PCのDNS名:8080 -> Waitress -> 疑似本番Django -> localhost:5432 -> quality_prodlike` とする。開発経路は `現在PC上の開発Django -> localhost:5432 -> quality_dev` とし、両者をDB名とDBユーザーで隔離する。

##### 継続ビルドと更新

- 疑似本番更新の作業枠は60分、通常の利用停止目標は30分とする。停止時間はサービス停止から更新後の簡易E2E完了までとし、短縮は実績と手順自動化を確認した後に承認する。
- 疑似本番へ配置するフロントエンドとバックエンドには同一のリリース番号またはコミット識別子を付け、ビルド成果物と依存versionを記録する。
- 更新は、利用者への通知、疑似本番サービス停止、承認済みmigration、静的ファイル更新、サービス起動、簡易E2Eの順で実施する。アプリとDBの互換性を確認してから利用を再開する。
- 直前のビルド成果物と設定を保持し、アプリ更新失敗時に前版へ戻せるようにする。DB変更を伴う場合は、前版へ戻せるmigrationか、切戻し不能であることを事前に明示して承認する。
- Viteのハッシュ付き静的ファイルを使用し、更新後に古い画面と新しいAPIが混在しないことを確認する。画面またはログから稼働中versionを確認できるようにする。

##### 受入と本番移行

第1段階では、DB分離と権限遮断、DNS名による画面表示、`8080`のみのLAN疎通、`5432`の遮断、待受アドレス、OS再起動とWaitress異常終了後の自動復旧、Django deployment check、静的ファイル・直接URL・404・APIエラー応答、更新・前版切戻しを試験する。開発DBに対するmigration、データ投入、削除が`quality_prodlike`へ影響しないことも確認する。

証跡として構成図、HTTP利用の管理者承認、DB・ロール分離表、環境別設定票、ファイアウォール規則、待受設定、サービス設定、ビルド記録、疎通結果、異常応答サンプル、OS再起動・プロセス異常終了・更新・切戻しの実施ログを保存する。

共有PCへの本番移行では、疑似本番PCをそのまま本番機として扱わず、共有PCへPostgreSQL、DBロール、Waitressサービス、ファイアウォール、環境変数、ビルド成果物を承認済み手順で再構築する。本番データの移行と照合、本番PCでの再起動・復旧・疎通試験が完了するまで正式リリース可とはしない。疑似本番で承認されたHTTP利用を本番へ自動継承せず、本番共有PCでのHTTP継続範囲をリリース判定時に再確認する。

##### 第1段階の実施記録（2026-07-16）

| 確認項目 | 結果 |
|---|---|
| PostgreSQL待受 | `127.0.0.1:5432`だけで待受し、LANへ直接公開していないことを確認 |
| DB分離 | 開発`quality_control_hq`と疑似本番`quality_prodlike`を別DB・別ロールとし、双方の実行ロールから相手DBへ接続できないことを確認 |
| 疑似本番配信 | WinSWサービス`QualityControlHQ-Pseudoprod`がAutomatic/Running、Waitressが`0.0.0.0:8080`で待受 |
| DNS・静的配信 | `http://yashio10-pc.isokawa.local:8080/`がHTTP 200、Viteビルド済みJS/CSSが同一ポートでHTTP 200、indexは`Cache-Control: no-store` |
| Host制限 | 承認外HostをHTTP 400で拒否 |
| 認証・CSRF | 実HTTPでCSRF cookie発行、ログイン、セッション維持、ログアウトが成功。一時試験ユーザーは削除済み。実利用者のブラウザログイン成功を確認 |
| 異常終了復旧 | Waitress PID `10212`を異常終了させ、WinSWが14.7秒後に別PID `2008`で復旧。サービスRunning、HTTP 200を確認 |
| OS再起動復旧 | 現在PCの再起動後、PostgreSQLとWinSWサービスがともにRunningとなり、PostgreSQLは`127.0.0.1:5432`、Waitressは`0.0.0.0:8080`で待受し、DNS経由でHTTP 200を確認 |
| ファイアウォール遮断 | 許可IPの端末からTCP 8080へ接続でき、許可IP範囲外の別端末から接続できないことを実機確認 |
| HTTP例外 | 管理番号`IFC20260716-001`、対象は開発/疑似本番、有効期限2027-07-16。設定で承認ID・期限を必須化し、本番環境への流用を禁止 |
| 自動試験 | Django対象テスト107件、疑似本番設定安全試験6件、frontend build、collectstatic、migration、Waitress配信smokeが成功 |

第1段階の受入試験は全件合格とする。構成・DB分離・HTTP承認・ファイアウォール・サービス設定、ビルド、migration、認証、異常終了復旧、OS再起動復旧、範囲外端末遮断の証跡を本記録と実施ログで保持する。

#### 第2段階: ジョブ非同期化と`quality_master`排他

##### 現状と対策目標

現行の`Job`は状態を記録するが、処理本体はHTTPリクエスト内で同期実行される。約10分を要する`quality_master`更新中に別要求を受けた場合、Webサーバーに空きがあれば別スレッドで同時実行され、空きがなければHTTP接続上で待機する。いずれも永続queueによる安全な待機ではなく、重複更新、長時間ロック、タイムアウト、再送、サーバー再起動による状態不整合の原因となる。

目標構成は `ブラウザ -> Django API -> PostgreSQLの永続Job queue -> 専用worker -> 業務処理` とする。APIはJobを`queued`で確定後、処理完了を待たずに`job_id`とHTTP 202を返す。workerはWaitressとは別プロセス・別Windowsサービスとして起動し、OS再起動と異常終了後に自動復旧する。

##### 段階的な実装

1. **真の非同期化**: まずworkerを1プロセス・同時実行数1で導入する。workerはPostgreSQL上の`queued` Jobをトランザクション内で1件取得し、`SELECT FOR UPDATE SKIP LOCKED`相当の行ロックで二重取得を防いで`running`へ遷移させる。重い処理は取得トランザクションを確定した後に実行する。
2. **`quality_master`の重複抑止**: Jobに`resource_key="quality_master"`と、依頼内容を識別する`idempotency_key`を持たせる。同じ資源のJobが`queued`または`running`の場合、新規の同一依頼は実行せず既存`job_id`を返す。異なるCSV等を使う更新要求は待機させ、管理者画面に先行Jobを表示する。
3. **依存Jobの待機**: マスタ分類や検査対象作成など`quality_master`に依存するJobは、マスタ更新中は`queued`のまま待機し、`blocked_reason`と先行`job_id`を記録する。先行更新が成功した場合だけ実行し、失敗した場合は業務処理を行わず依存失敗として`failed`へ遷移させる。参照画面は更新前の確定データを表示可能とするが、「マスタ更新中」を表示する。
4. **停止復旧と再試行**: `attempt_count`、`heartbeat_at`、`lease_until`、`worker_id`、`available_at`を記録する。lease期限切れの`running` Jobは、外部副作用とDB状態を照合してから再実行または`failed`へ遷移させる。再試行回数、間隔、実行timeoutは責任者が実測値に基づいて承認する。
5. **制御された並列化**: 1workerで安全性を確認した後、`quality_master`と無関係なJobだけを別workerで並行実行できるようにする。資源ごとの排他を維持し、単一のグローバルロックで全Jobを10分間停止させない。
6. **マスタ更新時間とDBロックの短縮**: 現行のファイル走査と`update_or_create`、`InspectionFile`全削除再作成を含む長時間transactionを計測する。ファイル解析をtransaction外へ移し、stagingへの投入・件数/制約検証・短時間の切替・失敗時の破棄へ段階的に移行する。切替前の利用者処理は旧版、切替後は新版だけを参照し、中間状態を公開しない。

##### `quality_master`更新中の競合ルール

| 後続処理 | 扱い | 理由 |
|---|---|---|
| 同一内容の`quality_master`更新 | 新規実行せず既存`job_id`を返す | 二重更新と利用者の再送を防ぐ |
| 異なる内容の`quality_master`更新 | `queued`で待機し、先着順とする | 後勝ち上書きと`InspectionFile`再作成競合を防ぐ |
| マスタに依存する取込・分類 | `queued`で待機し、更新成功後だけ実行する。更新失敗時は依存失敗として終了する | 旧版マスタによる誤分類を防ぐ |
| マスタ参照だけの画面・API | 更新前の確定データで継続し、更新中表示を行う | 業務停止を抑えつつ中間状態を見せない |
| マスタと独立したJob | 第2段階前半では待機、並列化承認後は別workerで実行可 | 初期実装を単純化し、検証後に待ち時間を減らす |

Job状態は当面`queued / running / succeeded / failed`を維持し、依存待ちは`queued`と`blocked_reason`で表す。状態追加は運用上必要と確認された場合に限定する。成功記録の直前にworkerが停止すると同じJobが再配送され得るため、「完全に1回だけ」を前提とせず、同じ`idempotency_key`の再実行で二重登録・二重更新が起きない冪等な処理を受入条件とする。

##### 受入基準と証跡

以下を本番相当の約10分データで実施し、第2段階の合格条件とする。

1. `quality_master`更新APIが規定時間内に`job_id`と202を返し、更新処理がWaitressのリクエストスレッドを占有しない。
2. 同一更新を同一利用者・別利用者・再送で要求しても、実処理は1回だけで既存`job_id`を返す。
3. 異なるマスタ更新とマスタ依存Jobが先行更新の完了まで待機し、成功後は新版マスタで処理される。先行更新の失敗時は依存Jobを実行せず、依存失敗として記録される。
4. マスタ更新中の参照APIが中間状態を返さず、更新前または更新後の整合したデータだけを返す。
5. workerを処理開始前、処理中、DB反映直前、DB反映直後に停止し、永久`running`、二重更新、中間データを残さず復旧できる。
6. timeout、一時的DB切断、無効ファイル、worker再起動、Job重複配送で、承認済みの再試行回数と最終状態になる。
7. 独立Jobの並列化後も、`quality_master`の排他とマスタ依存Jobの待機が破られない。**S2-PAR-01延期承認期間中はN/A (deferred)。並列化導入時に本基準を必須化する。**
8. 10分更新について、transaction時間、行/table lock待ち、CPU、メモリ、DB接続数、後続Job待ち時間を記録し、承認済み閾値内である。

- 第2段階判定条件: 受入基準1–6, 8の全件成功（criterion 7は承認済み延期に伴いN/Aとして判定対象外）
- 並列化導入判断時: criterion 7を必須化し、全8基準の成功を必要とする

必須証跡は、ジョブ状態遷移表、Job間の競合・依存表、閾値承認記録、workerサービス設定、queue取得とlease設計、冪等性キー仕様、同時要求・重複配送・停止復旧・長時間試験のログ、DBロック計測結果、切戻し手順とする。

##### 第2段階の実施記録（2026-07-16〜17、継続中）

- PostgreSQL永続queue、`SELECT FOR UPDATE SKIP LOCKED`による取得、1 worker・同時実行1、子プロセス実行、heartbeat 30秒、lease 120秒、最大3試行、30秒・120秒・300秒の再試行を実装した。
- `quality_master`の内容ハッシュによる重複抑止、異なる更新の資源排他、マスタ依存Jobの待機、先行失敗時の依存失敗、参照画面の「マスタ更新中」表示を実装した。
- 実行timeoutは`quality_master` 30分、ERP 10分、その他15分とした。印刷・ERPなど外部副作用があるJobはlease失効時に自動再試行しない。
- 開発PostgreSQLで親workerから子プロセスを起動するqueue smokeが成功し、`queued -> running -> succeeded`、試行回数、heartbeat、lease解放を確認した。1秒timeout試験では永久`running`を残さず再試行待ちへ戻ることを確認した。
- backend 116件に第2段階試験を追加して合格し、frontend本番build、migration check、Django checkに合格した。
- 開発実データ10,807件のマスタ更新は209.478秒、試行1で成功した。5秒間隔45サンプルで最大CPU 22.7%、最大メモリ67.9%、DB接続5、DB待機lock 0を記録した。先行成功後に依存Jobが実行され成功すること、先行失敗時は依存Jobを実行せず`JobDependencyFailed`とすることを確認した。
- 検査書フォルダ7件は試験実行アカウントからアクセス不能であり、フォルダ単位の警告として継続しマスタ更新自体は成功するようにした。検査書3,305件を含む実地試験は、workerサービスアカウントへ共有アクセス権を付与した後に再実施する。
- 疑似本番へmigration 0027とfrontendを配置し、Webと専用workerの両サービスがStarted、HTTP 200、永続queue smoke成功を確認した。workerはローカルサービスアカウント`.\qc-service-worker`で起動確認後、UNC共有試験のためADアカウント`P1569@isokawa.local`へ切り替えた。
- 管理者PowerShellからworker子プロセスを強制終了し、PID `7824` から `2860` へ12.1秒で自動復旧した。workerサービスが`Running`であることを確認し、45秒以内の復旧基準に合格した。
- 疑似本番へは個人情報を含まない参照データだけを複製し、Master 16,244件、MasterClass 16,260件、Structure 44,772件、AppSetting 1件を照合した。ユーザー、履歴、監査ログ、アバター、媒体ファイルは複製していない。複製前fixtureを`runtime/pseudoprod/backup`へ保存した。
- 全検査書フォルダがアクセス不能の場合は、既存InspectionFileを削除せず警告として保持する回帰試験を追加した。疑似本番のInspectionFileは専用サービスアカウント設定後に再走査して作成する。
- 疑似本番の実データ10,807件によるマスタ更新は215.314秒、試行1で成功した。同一冪等性キーの再送は新規Jobを作らず同一`job_id`を返し、依存Jobは先行Jobの完了まで`queued`で待機した後に自動実行され成功した。最大CPU 67.6%、最大メモリ68.2%、DB接続4、DB待機lock 0を記録した。
- `.\qc-service-worker`から検査書UNC共有7件を走査したが、すべてアクセス不能だった。マスタ更新は成功し、全フォルダ不可時の保護により既存InspectionFileを保持した。共有サーバー側のSMB認証（共有サーバーが認証できるアカウント、共有権限およびNTFS権限）を設定後、検査書索引を再試験する。
- workerを`P1569@isokawa.local`へ切り替えた再試験では共有上の検査書を検出でき、SMB認証の改善を確認した。一方、品番`CDP0023`の同名検査書が製品検査(1)・(2)の両方に存在したため、577.000秒後に`CLASS_6_7_CONFLICT`で安全に失敗した。試行1、最大CPU 60.5%、最大メモリ59.7%、DB接続4、DB待機lock 0で、transaction rollbackによりInspectionFileの中間データは残らなかった。正しい保存先を業務確認して重複を解消後に再試験する。
- `CDP0023`の保存先競合解消後、`P1569@isokawa.local`のworkerで再試験し、10,807件のマスタ更新と3,304件のInspectionFile作成が640.119秒、試行1で成功した。設定済みUNC共有7件の警告は0件だった。最大CPU 21.7%、最大メモリ66.3%、DB接続4、DB待機lock 0で、サービスは完了後もRunning、未処理Job 0を確認した。
- 疑似本番の正式HTTP uploadで、バイト列は異なるがparser正規化後113,876行のhashが一致するマスタA・Bを別Jobとして投入した。Aは572.421秒、Bは872.992秒でいずれも試行1・canonical成功し、Aの`finished_at`から2.177秒後にBが開始、同時`running`は0だった。A完了直後とB完了後の業務stable hashはbaseline一致した。また、安全なunsupported sentinelの親マスタJobを試行1で失敗させたところ、正式HTTPで投入した依存plan Jobは自動的に親へ紐付き、`JobDependencyFailed`、試行0、`started_at`なしで終了し、業務処理非実行と業務count/hash不変を確認した。証跡は`runtime/pseudoprod/evidence/s2-http-fifo-dependency-20260721-130252`に保存した。
- 実`master_update`のtransaction内に試験専用advisory barrierを置いた停止復旧試験では、attempt 1のtoken所有、4業務表`RowExclusiveLock`、active advisory wait、fixtureがsole direct blockerであることを同時にfsyncした。exact child chain停止後、同一PID・client port・transaction・DB role・advisory waiterを再同定して対象backendだけを終了し、fixture lock保持中のbackend消失と1.047秒での6業務hash rollbackを確認した。試験DDLを削除・unlockした後、WinSWは30.687秒で復旧し、lease回収後のattempt 2はcanonical成功した。`succeeded`観測から0.062秒でexact process chainを再停止し、30.610秒復旧後130秒・130 sampleで再配送も状態変化もなかった。最終的にactive Job 0、Web/worker Running・Automatic、UNC 7/7、HTTP 200、試験DDL不存在、既存Job不変を確認した。

##### 第2段階の未試験チェック表

状態は `未実施 / 部分実施 / 合格 / 不合格 / 延期` のいずれかとする。各試験セッションの終了時に、実施した行だけ実施日、環境、結果要約、証跡、残課題を更新する。自動試験の合格を疑似本番の実地試験の代替にはしない。

| ID | 試験 | 状態 | 実施日 | 環境 | 結果要約 | 証跡 | 残課題 |
|---|---|---|---|---|---|---|---|
| S2-SH-01 | ADアカウント設定後のOS再起動でworkerが自動起動する | 合格 | 2026-07-21 | 疑似本番Windows / AD / PostgreSQL | pre証跡をmanifest 5/5で再検証後、OS boot timeがpre capture後の`2026-07-21T03:25:05.500Z`となり、preのWeb/worker process tree PIDが全て消失し、新treeの全process create timeが新boot以後であることを確認した。Web/workerは操作なしでSCM `Running`・`Auto`、service account hashがpre一致し、wrapper PIDはWeb 3328→7340、worker 16000→7648となった。HTTP 200、migration 0028、active/running 0を確認後、workerを停止せずcanonical `master_update`をtimeout 1,800秒でqueueへ投入し、`queued -> running -> succeeded`、attempt 1、676.589秒を記録した。完了後はworker・execution token・heartbeat・lease全解放、active/running 0、サービスprocess tree継続、HTTP 200だった | Job `job_20260721123459_f99a03b1`、pre `runtime/pseudoprod/evidence/s2-sh-01-02-pre-reboot-20260721-121513`、post `runtime/pseudoprod/evidence/s2-sh-01-02-post-reboot-20260721-123009`（同dir `checksums.sha256`） | なし |
| S2-SH-02 | OS再起動後も検査書UNC 7フォルダを読み取れる | 合格 | 2026-07-21 | 疑似本番Windows / AD | post-reboot初期captureで設定済みUNC 7 rootのidentity・host identity・root-level entry count・name-set hashがpreとindex単位で一致し、7/7でread/listに成功した。canonical CSV content/path identity、Master 16,244、MasterClass 16,263、Structure 44,772、InspectionFile 3,304、および4業務表stable-content hash、InspectionFile distribution/pathset hashが既知baselineと一致した。必須canonical Jobは10,807/1,001/113,876/3,304件、`single_atomic_update`、folder warning 0でattempt 1成功し、完了後も7 rootと全stable hashが初期/pre一致した。raw UNC path、credential、token値は証跡へ保存していない | Job `job_20260721123459_f99a03b1`、`runtime/pseudoprod/evidence/s2-sh-01-02-post-reboot-20260721-123009/application-post-reboot-summary.json`、同dir `job-transitions.jsonl` / `checksums.sha256` | なし |
| S2-SH-03 | マスタ更新中の共有切断・復旧で部分索引を確定せず、安全に失敗または再試行する | 合格 | 2026-07-21 | 疑似本番Windows / AD / PostgreSQL | canonical AppSettingのUNC 7 rootが全て読取可能、active Job 0、全業務表hash/countを確認し、custom full backupを取得した。uploadなしの全量`master_update`で対象SMB Client Sharesの`Metadata Requests/sec` 97.608とJobのtoken所有を同時観測後、このhostの対象server address・outbound TCP 445だけをfirewallで34.906秒遮断した。対象外SMB接続identityはrule追加直後も一致し、server側操作は行っていない。Jobはattempt 1、`OSError`でfailedとなり、Master・MasterClass・Structure・InspectionFileのstable-content hash/count、InspectionFile distribution/pathsetが全てpre一致した。rule削除後に7 rootの再読取を確認し、別のcanonical recovery Jobはattempt 1で成功、10,807/1,001/113,876/3,304件、warning 0、post hashと既存34 Job hashがpre一致、active 0となった。ruleは不存在、Web/worker Running・Automatic、HTTP 200、自動restore・OS再起動なし | Job `job_20260721114519_d9b54460`、recovery `job_20260721114750_cbe4ec19`、`runtime/pseudoprod/evidence/s2-sh-03-05-20260721-112409`、backup `quality_prodlike_pre_s2_sh03_20260721-112409.dump`（SHA-256 `8e1113b8b421d8a55aea96d6ae5b51c28a210ffc097b2647a94bac1a62ff46c6`） | なし |
| S2-SH-04 | 検査書UNC 7フォルダの読み取り | 合格 | 2026-07-17 | 疑似本番Windows / `P1569@isokawa.local` | 7フォルダの警告0件、InspectionFile 3,304件を作成 | 本節「第2段階の実施記録」の640.119秒実地試験記録 | OS再起動後の再確認はS2-SH-02で実施する |
| S2-SH-05 | 履歴ファイル、帳票出力先など書き込みが必要なUNCパスの書き込み | 合格 | 2026-07-21 | 疑似本番Windows / AD | 現在設定されているUNC書込対象はAppSettingの履歴workbook 1件だけであることをinventoryし、昇格fixtureの実行SIDとworkerサービスアカウントSIDが一致することをhashで照合した。実workbookの親に一意名tempを排他的作成し、47 bytesのwrite/read、83 bytesへのoverwrite/read、削除を確認した。実workbookは98,430 bytesでcontent SHA-256・mtimeが前後一致し、親直下4 entryの名前set hashも前後一致、tempは残存しなかった。実path、SID、アカウント名は証跡へ保存していない | `runtime/pseudoprod/evidence/s2-sh-03-05-20260721-112409/sh05-summary.json` | なし |
| S2-SH-06 | ADパスワード変更・期限切れ時のサービス資格情報更新運用 | 部分実施 | 2026-07-23 | 疑似本番Windows / AD / PostgreSQL | LogonUserW(LOGON32_LOGON_SERVICE)事前検証成功、AD lockout余裕確認(remaining=-1 threshold=0)、DPAPI暗号化rollback capsule作成・round-trip検証成功。Worker停止後、wrong credentialへ変更、Start-Service 1回→SCM認証失敗検出(detection 0.018s end-to-end <120s)。DPAPI capsule復元→Start-Service→Running(RTO 0.913s <900s)。service identity一致性確認。queue_smoke (job_sh06_smoke_957285613c40) succeeded attempt 1, 3.07秒。※訂正: (1)UNC 7/7は未実測(queue_smoke不使用)。(2)account名(P1569@isokawa.local)はrunner-output.log原本に記録有り。原本restricted保持、redacted copyを共有用とする。(3)capsule削除はmemory-only reference解放・GC。完全zeroization未証明。(4)detection 0.0004sはStopped観測時間。end-to-endは0.018s。(5)status='passed'はスクリプト固定値。詳細はaddendum.json参照 | `runtime/pseudoprod/evidence/s2-sh-06-20260723/addendum.json`(訂正・補足)、`同dir corrected-summary.json`(訂正版)、`同dir runner-output.redacted.log`(共有用)、`同dir checksums.sha256.v2`(v2 manifest)。原証跡 `summary.json` `runner-output.log`は保持 | 残条件: 専用非個人service accountでactual rotate/expiry。個人AD accountのrotate/expiry/lockout flag変更は禁止を維持。correct credentialによるUNC 7 root read/list別証跡追加は任意 |
| S2-HTTP-01 | 画面/APIからマスター更新を要求し、実HTTPで短時間に202を返す | 合格 | 2026-07-23 | 疑似本番HTTP / Windowsサービス / PostgreSQL | IFC20260723-001としてHTTP推奨閾値を正式承認。Web応答: warning >3秒 / fail >5秒 / client timeout 30秒。Master更新: warning >1200秒 / fail >1500秒 / hard timeout 1800秒。余裕: warning <600秒 / fail <300秒。直近3成功run中央値比+50%超でwarning、2回連続warningまたは1回failでレビュー。review期限: 2026-08-21または同条件成功10件の早い方。実測3件: main HTTP (job_20260721131121) 0.063秒/621.408秒, FIFO A (job_20260721132501) 0.422秒/572.421秒, FIFO B (job_20260721132502) 0.437秒/872.992秒。全件Web warning 3秒内・master warning 1200秒内・margin warning 600秒超で合格。承認日: 2026-07-23。※2.076/2.078/2.109秒は2026-07-17 dedupe試験(S2-HTTP-02)の同一Job応答時間であり、本試験のJob別値として扱わない。訂正詳細はaddendum.json参照 | 閾値承認記録 `runtime/pseudoprod/evidence/s2-http-threshold-20260723/threshold-approval.corrected.v2.json`、addendum `同dir addendum.json`、v2 manifest `同dir checksums.sha256.v2`。原証跡 `threshold-approval.json`は保持。既存Job `job_20260721131121_e8edaf53`、`job_20260721132501_0fca1b70`、`job_20260721132502_ce074195` | 直近3成功run中央値比+50%トリガーは初回基準適用後に初回warning判定が必要。性能劣化時の監視は運用フェーズで継続 |
| S2-HTTP-02 | 別ユーザーからの同一更新要求を実HTTPで同じJobへ集約する | 合格 | 2026-07-17 | 疑似本番HTTP / 2 admin session / PostgreSQL | A→B→Aの3要求が同一Job `job_20260717145144_6e6a67e8`を返し、`deduplicated`はfalse・true・true、pre/postのJob差分は1件だった。各response直後に許可schemaだけをfsyncし、created_by A、Job成功、baseline一致、一時session 2件とadmin Bの削除まで確認した | `runtime/pseudoprod/evidence/http-dedupe-20260717-145028/responses.jsonl`（3行、SHA-256 `3dc5264d7b3f265fc76ee2dd74a13ba21913295388ef92a2748697ef5beb80fc`）、同dirのbaseline・job-final・`SHA256SUMS`、Job `job_20260717145144_6e6a67e8` | なし。cookie、CSRF、password、session、login、raw body、headers、UNC pathは証跡へ保存していない |
| S2-REF-01 | 約10分の更新中に参照APIを反復し、中間状態や一部更新済みデータが見えない | 合格 | 2026-07-17 | 疑似本番HTTP / PostgreSQL / CAA0075 old→new専用fixture | 第8再試験ではCSV全113,876行を事前解析し、`code=CAA0075` 9行、`parent_code=CAA0075` 10行、先頭name、class 4、最終Structure quantity 0.029をexpected newとして固定した。fixture前のDB、InspectionFile、正式master/structure API、active Job 0、3サービスを照合し、full backup取得後、A所有Session/Targetを作成して単一transactionで名称sentinel、class 4削除、quantity 9.999だけをold化した。pre 10 cycleはoldで安定し、正式POST `force=false`は0.033秒でHTTP 202、Jobは試行1、514.923秒で成功、folder warning 0だった。全121 cycleを5秒間隔でstructure/target/jobから観測し、cycle 110までold、cycle 111でJob `succeeded`と同時に両endpointがnewとなり、post 10 cycleもnewで安定した。mixed、HTTP error、件数dip、boundary straddleは各0、combined/structure/targetのold→new切替は各1回、逆戻り0だった。DB canonical、全件数、active 0、3サービス、fixture cleanupを確認した。第7回のmixed 11件はJob成功後だけに生じたfixture仮定誤りで、製品atomicity不合格ではなく試験設計不合格として是正・guard付き復旧済み | 第8 Job `job_20260717165605_6a73477b`、`runtime/pseudoprod/evidence/ref-atomic-retest-20260717-165517`、full backup `quality_prodlike_pre_ref_atomic_retest_20260717-165517.dump`（SHA-256 `e7528efbb43fc92d2e43974362d30fd2fb433125af110f0afce116feb501cdf3`）、第7および復旧証跡 `runtime/pseudoprod/evidence/ref-atomic-20260717-160345` | 本項のatomicity基準は達成。attempt01/02と第6回可用性証跡は保持する。マスター更新時間の性能評価とtimeout余裕の承認はS2-HTTP-01の残課題として継続する |
| S2-REC-01 | worker停止位置別復旧（処理開始前・処理中・DB反映直前・反映直後） | 合格 | 2026-07-21 | 疑似本番Windows / PostgreSQL / 管理者昇格fixture | 既存のJob状態・resultの4 commit境界試験に加え、実`master_update` attempt 1のtoken所有、4業務表`RowExclusiveLock`、active advisory wait、fixture sole direct blockerを同時にfsyncし、exact child chain停止後に同一PID・client port・transaction・DB role・waiterを再同定して対象backendだけを終了した。fixture lock保持中にbackend消失、1.047秒で6業務hashがpre一致し、試験DDL削除・unlock後にWinSWが30.687秒で復旧した。lease回収後のattempt 2はcanonical 10,807/1,001/113,876/3,304件、warning 0、試行2で成功した。`succeeded`観測から0.062秒でexact process chainを停止し、30.610秒復旧後に130秒・130 sampleで状態不変・無再配送を確認した。pre/rollback/postの6業務hash、既存Job hashは一致し、試験trigger/function/waiter 0、active Job 0、UNC 7/7、Web/worker Running・Automatic、HTTP 200、自動restoreなしだった | Job `job_20260721160357_3b056f3a`、`runtime/pseudoprod/evidence/s2-rec-01-barrier3-20260721-155825`、full backup `quality_prodlike_pre_s2_rec01_barrier3_20260721-155825.dump`（SHA-256 `e79a88818c7de43ce70bf121472c7fdbe6600a8251f3a88ccda5145019499f53`）。補完する4境界証跡 `runtime/pseudoprod/evidence/s2-rec-01-20260721-091721`、safe-abort `runtime/pseudoprod/evidence/s2-rec-01-real-20260721-140121` | なし |
| S2-DB-01 | 一時的DB切断時の復旧と最終状態 | 合格 | 2026-07-21 | 疑似本番Windows / PostgreSQL / 管理者昇格fixture | Job基盤3地点の既存試験に加え、canonical AppSettingの全量CSV（37,757,656 bytes、uploadなし）で実`master_update`をtimeout 1,800秒として実行した。attempt 1のexact child main backendはOS socket local portと`pg_stat_activity.client_port`が1対1一致し、Master・MasterClass・Structure・InspectionFile全4表のgranted `RowExclusiveLock`を同時に持つ唯一のclient backendであることを確認して、そのbackendだけを終了した。0.313秒で`JobProcessFailed` retry queueへ遷移し、queued観測開始から1.078秒で4業務表のstable-content hash/countとInspectionFile distribution/pathsetが全てpre一致した。30秒後のattempt 2は541秒で成功し、canonical結果（Master 10,807、class 1,001、structure 113,876、InspectionFile 3,304、warning 0）、全post hash、既存32 Jobの全field hashがpre一致、active 0、token・worker・heartbeat・lease解放を確認した。custom full backup/restore-listを事前検証し、自動restoreは未使用。Web/worker Running・Automatic、HTTP 200。初回final guardはcanonical resultに存在しないtop-level `status`をfixtureが誤要求して安全停止したが、業務data/hash不一致ではなくguard修正後に同一完了状態を再検証した | Job `job_20260721101940_74ad455f`、`runtime/pseudoprod/evidence/s2-db-01-real-20260721-101020`、backup `quality_prodlike_pre_s2_db01_real_20260721-101020.dump`（SHA-256 `2e12104359c71474c38e1617d1fc27852eecfbea03cfaf9631a58f92e41dbd51`） | なし |
| S2-DB-02 | lease失効時の再試行または安全な失敗 | 合格 | 2026-07-21 | 疑似本番Windows / PostgreSQL / Django自動試験 | retry-safe専用Jobを実行せず3回lease失効させ、30.079秒後にattempt 2、120.031秒後にattempt 3へ再claimし、3回目は最大3試行で`WorkerLeaseExpired`/`failed`となった。外部副作用専用Jobはattempt 1のlease失効から0.015秒で`WorkerLeaseExpired`/`failed`となり、再claimされなかった。両Jobともtoken・worker・heartbeat・lease解放、active 0を確認し、既存15 Jobのsafe projection SHA-256とMaster 16,244、MasterClass 16,263、Structure 44,772、InspectionFile 3,304の前後一致を確認した | Job `job_20260721090535_2324b94e`、`job_20260721090805_2f537749`、`runtime/pseudoprod/evidence/s2-db-02-20260721-090405`、`quality.test_job_queue.PersistentJobQueueRecoveryTests.test_expired_retry_safe_job_is_requeued`、`test_expired_external_side_effect_job_fails_without_retry` | なし |
| S2-DB-03 | 同一Jobの重複配送で二重更新や永久`running`が発生しない | 合格 | 2026-07-21 | 疑似本番Windows / PostgreSQL / Django自動試験 | migration 0028適用後、専用`queue_smoke` 3 Jobで逐次重複配送は1回実行・1回skip、同時配送も1回実行・1回skipとなった。lease失効回収は`running(試行1) -> queued -> running(試行2) -> succeeded`となり、旧executorのfinalizeを拒否した。全Jobでtoken・worker・heartbeat・leaseが解放され、active 0、Master 16,244、MasterClass 16,263、Structure 44,772、InspectionFile 3,304の前後一致を確認した。自動試験では同一`master_update`の業務関数1回、lease回収後の旧executor成功・失敗時のrollbackも確認した | Job `job_20260721085533_b4fb2c08`、`job_20260721085533_cdf778fe`、`job_20260721085534_de3facc3`、`runtime/pseudoprod/evidence/s2-db-03-20260721-085226`、事前backup SHA-256 `ffdad1da380dc1c91c448750f1bbe5d5aa8b478f674f9ea2afe55a55c2e5733a`、`quality.test_job_queue.PersistentJobQueueRecoveryTests.test_stale_executor_cannot_commit_or_overwrite_recovered_attempt` | なし |
| S2-TO-01 | 疑似本番サービスでtimeout時の再試行回数、間隔、最終状態を確認する | 合格 | 2026-07-17 | 疑似本番Windows / PostgreSQL / 専用`queue_smoke` | sleep 5秒・timeout 1秒の専用Jobを0.25秒間隔で監視し、30.0秒・120.0秒後に再試行、169.516秒で`failed`、試行3、`JobTimeout`となった。lease・heartbeat・workerはclearされ、最終状態は5秒安定し、workerサービスもRunningを維持した | Job `job_timeout_smoke_350d0f053d`（DB行を保持）、状態遷移7件の実測ログ | なし。業務Job、サービス設定、`.env`は変更していない |
| S2-PAR-01 | 独立Job用の並列workerを第2段階で導入するか後段へ延期するか判断する | 延期 | 2026-07-23 | 設計・運用判断 | 判断日2026-07-23。approval ID: PAR01-DEC-20260723-001。期限2026-08-21またはgo-live/第3段階capacity reviewの早い方。owner: 運用責任者、co-review: 業務責任者 / アプリ責任者。concurrency=1、quality_master排他、依存待機を維持。acception criterion 7はN/A/deferred。applicable criteria(1–6,8)全件成功を第2段階合格条件とする。並列化導入時criterion 7必須化。再検討trigger全7条件をpar01-decision.jsonに定義 | 本記録（延期判断日2026-07-23）および `runtime/pseudoprod/evidence/par01-decision.json`（PAR01-DEC-20260723-001）。decision evidenceとRELEASEの双方に同一approval情報を記録済み | 正式延期のためrelease blockerではない。再検討trigger条件を監視する運用ルールの確立が必要 |
| S2-CR-08 | 受入基準8（transaction時間、lock待ち、CPU、メモリ、DB接続数、後続Job待ち時間）の現存証跡監査 | 部分実施 | 2026-07-23 | 疑似本番証跡監査 | 3証跡のSHA-256一致確認。CPU最大21.7%、メモリ最大66.3%、DB接続2〜4、waiting locks 0、granted locks 1〜65、Job実行時間641.118秒。FIFO A→B dispatch/handoff gap 2.177秒。CPU・メモリ・DB接続数・lock待ち・transaction時間・後続Job待ち時間のいずれも承認済み閾値なし。S2-HTTP-01のIFC20260723-001はWeb応答/master更新完了時間の閾値でありcriterion 8の対象外。**測定fixture拡充**: Jobごとに独立した`TransactionObserver`を`start_watching()`フェーズ制御で運用し、transaction時間とJob作成時刻を`job_a_transaction`/`job_b_transaction`として分離記録する。CLIはsmoke fixture専用に制限。fixture単体検証自動試験34件(quality.test_s2_cr08_measurement)が合格。疑似本番再測定は全preflight gate未充足のため安全停止（未実行）。6指標とも承認済み閾値なしのためverdictは`not_evaluable`、S2-CR-08は「部分実施」を維持 | `runtime/pseudoprod/evidence/s2-criterion-8-20260723-095921/`（summary・addendum・checksums.sha256）。測定fixture: `backend/quality/s2_cr08_measurement.py`（evidence schema v3・observer・検証）、`backend/quality/management/commands/measure_s2_cr08.py`（smoke fixture CLI）、`backend/quality/test_s2_cr08_measurement.py`（fixture単体検証自動試験34件）。`backend/quality/models.py` + `migrations/0029_job_created_at.py`（Job.created_atフィールド追加） | 承認済み閾値の設定と記録。疑似本番でのcanonical再測定（全preflight gate充足後）。fixture検証自動試験合格確認 |

#### S2-CR-08 自動試験・review実施記録（2026-07-28）

P0「final gateとformal evidence」の実装および回帰試験をfresh test DBで検証し、reviewer判定は**PASS**となった。今回のPASSはコード・契約・回帰試験の範囲に対するものであり、疑似本番でのcanonical `--dry-run`、backup/restore検証、live A/B測定、6指標の閾値承認を完了したことを意味しない。したがって、S2-CR-08全体の状態は引き続き**部分実施**、6指標のverdictは`not_evaluable`とし、`LIVE_BLOCKED = True`を維持する。

| 検証対象 | 結果 | 補足 |
|---|---:|---|
| `quality.test_s2_cr08_canonical` | PASS: 248/248 | fresh test DB。test methodは248 definitions / 248 uniqueで重複なし |
| `quality.test_s2_cr08_measurement` | PASS: 34/34 | fresh test DB |
| `PersistentJobQueueApiTests` | PASS: 4/4 | fresh test DB |
| `PersistentJobQueueRecoveryTests` | PASS: 12/12 | fresh test DB |
| `PhaseTwoMasterUpdateTests` | PASS: 33/33 | fresh test DB |
| queue + PhaseTwo合同 | PASS: 49/49 | 上記4/12/33の合同実行 |
| real collector postflight contract | PASS: 2/2 | 実`Master`・`InspectionFile`からcollector出力を作成し、positive shapeと`baseline_matched=False`のnegative shapeを検証 |
| Django system check | PASS | 問題なし |
| migration drift | PASS | `makemigrations --check --dry-run`: No changes detected |
| diff integrity | PASS | `git diff --check` exit 0。WindowsのCRLF warningのみ |
| safety gate | PASS | canonical `--dry-run` / `--live`、疑似本番Job投入、service操作、backup/restoreは未実施。module/command双方の`LIVE_BLOCKED = True`を確認 |

契約検証では、実`_inspection_file_distribution()`出力の整数priority key、非負count、`total == sum(by_priority.values())`、preflight/postflight共通shape、privacy filter通過を確認した。postflightは実collector出力に`passed=True`と`baseline_matched=True`を追加した実運用shapeを受理し、`baseline_matched=False`を拒否する。既存negative testでは`bool`・malformed型、total不一致、CPU/メモリの`inf`・`-inf`・`nan`をfail-closedで拒否する。

fresh DBでは全対象suiteが合格した。一方、過去のstale `--keepdb`を再利用した実行ではdata migration由来の初期dataが先行`TransactionTestCase`後に残らず、queue + PhaseTwo合同で失敗が再現された。このため正式なrelease証跡はfresh test DBの結果を基準とし、stale keepdbの結果を製品回帰として扱わない。

#### S2-CR-08 P2 canonical dry-run実施記録（2026-07-28）

P0/P1のreviewer PASS後の最初の疑似本番段階として、Job投入・service停止・backup/restore・live測定を行わないcanonical `--dry-run`を実施した。初回はmigration 0029未適用、worker停止、worker process tree不在、`AppSetting.inspection_folder_priorities`未設定を検出し、証跡を書いたうえで安全停止した。

技術的前提として、active/running Jobが0件であることとmigration planがnullableな`Job.created_at`列の追加1操作だけであることを確認し、疑似本番migration userで0029を適用した。その後、AutomaticのままStoppedだったworkerを起動し、Web/workerがともにRunning/Automatic、active/running Jobが0件であることを再確認した。フォルダ優先順位は、既存`AppSettingSerializer`の更新規則に従って設定済み7フォルダをすべて明示的な`0`へ正規化した。既存InspectionFile 3,304件も全件priority 0であり、この正規化によって現行の選択優先度は変更していない。

前提修正後の最終dry-runはexit 0で完了し、20 preflight keyすべてがPASSした。migration 0029、Web/worker service、HTTP、active/running Job 0、backup tool/preparedness、worker process tree、業務表count/hash、system metrics、InspectionFile distribution/pathset hash、UNC 7/7、canonical input/payloadを確認した。evidenceは`measurement_status=not_executed`、空の`failure_reason`、`privacy_check_passed=true`で、raw UNC path、drive path、PID/port tupleを含まない。完了後も両serviceはRunning/Automatic、active/running Jobは0件だった。

| 項目 | 結果 |
|---|---|
| 最終dry-run証跡 | `runtime/pseudoprod/evidence/s2-cr08-canonical-dryrun-20260728-cycle3/` |
| evidence schema | `s2-cr-08-canonical-v1` |
| preflight | PASS: 20/20 |
| canonical payload | CSV newline count 113,877、SHA-256 `16043f4274cc865c8fc77fcbe61d717378462d00c90b4ec7c2533b89508f5125`、UNC folder 7、priority entry 7 |
| 業務表count | Master 16,244、MasterClass 16,263、Structure 44,772、InspectionFile 3,304 |
| evidence integrity | `measurement.json` SHA-256 `3ff607867d885ef101d837404358a5fc6900b5e9a2722f13697451e99af55417`、manifest一致 |
| safety | Job投入なし、service停止なし、backup/restoreなし、liveなし、`LIVE_BLOCKED = True`維持 |

S2-CR-08は引き続き**部分実施**とする。過去記録の業務行113,876と今回fixtureのnewline count 113,877は定義が異なる可能性があるため、baseline row countとして自動採用しない。次の段階へ進む前に、canonical CSVの行数定義、CSV hash、UNC 7 root、業務表期待件数を業務責任者・運用責任者・アプリ責任者がapproval ID付きで承認する必要がある。承認後も、backup/restore検証をlive A/B測定より先に完了し、6指標のverdictは正式閾値承認まで`not_evaluable`を維持する。

### S2-CR-08 テスト方針の優先順位と暫定推奨閾値（未承認）

S2-CR-08は、既存回帰試験の件数増加よりも、測定対象の同一性、欠測時の安全停止、正式証跡の合否判定可能性を優先する。次の優先順位を崩さず、各修正とそのdirect positive/negative testを同一iterationで完了させる。後続優先度への着手は、先行優先度のreviewer PASS後とする。

1. **P0: A/Bと実transactionの一意な相関** — eventの先着順ではなく、対象Jobのclaim/execution ownership、exact child process、PostgreSQL backendの`(pid, client_port, xact_start)`を照合する。unrelated transaction、候補0件・複数件、identity変化はfallbackせずfail-closedとする。異PID、同PID・別port、same-port連続transaction、baseline connection再利用をdirect testする。
2. **P0: transaction境界の正確性** — START、same-port transition END/START、backend disappearance ENDを同一DB snapshotのclock lower/upper boundで記録し、transaction identityと終了boundを別fieldにする。clock順序、欠測、collector停止・timeoutをdirect testする。
3. **P0: final gateとformal evidence** — Job A/B結果、observer、postflight、metrics coverage、cleanup、service recoveryを先に確定し、その後に`measurement_status`、`failure_reason`、`live_verification`、privacy check、evidence writeを行う。いずれかの不足・不一致・例外を成功扱いしない。
4. **P1: 回帰・privacy・件数整合** — 上記P0の各failureを再現するnegative testを追加し、既存measurement、queue、recovery、`PhaseTwoMasterUpdateTests`もfresh test DBで実行する。implementer/reviewer handoffの試験対象、件数、結果を同一にする。
5. **P2: 疑似本番段階移行** — P0/P1のreviewer PASSまでは`LIVE_BLOCKED = True`を維持し、canonical `--dry-run`、Job投入、service操作、`--live`を実行しない。PASS後にpreflightを満たしたdry-run、backup/restore検証、live A/B測定の順で進める。

以下は2026-07-24時点の**承認前の初期案**であり、実装者による合格判定には使用しない。既存実測（CPU最大21.7%、別の疑似本番run最大67.6%、メモリ最大68.2%、DB接続最大5、waiting locks 0、Job実行時間514.923〜872.992秒、FIFO B queue wait下限576.042秒）を基に、初回canonical測定で異常を検知しつつ即時failを過剰発生させない幅として提案する。

| 指標 | warning暫定案 | fail暫定案 | 測定・判定条件 |
|---|---:|---:|---|
| host CPU使用率 | 最大値 `>70%` | 最大値 `>85%` | A enqueue前からB完了後まで5秒以下の間隔で測定する。sample欠落またはA/B実行区間未coverageは`not_evaluable` |
| hostメモリ使用率 | 最大値 `>75%` | 最大値 `>85%` | 同上。使用率だけでなく測定開始・終了時刻とsample数を証跡化する |
| DB接続数 | 最大 `>6` | 最大 `>8`、またはPostgreSQL `max_connections`の80%以上 | 対象DBの全client connectionを同一定義で数える。baseline値と対象Jobによる増分も併記する |
| row/table lock待ち | 業務tableのwaiting lockが1件以上 | 30秒以上継続、deadlock、lock timeoutのいずれか | 瞬間値だけでなく対象relation、初回・最終観測時刻、継続時間を記録する。試験用advisory lockは分離する |
| A/B各transaction時間 | `>600秒` | `>900秒` | Job全体時間ではなく、相関済み`xact_start`から終了boundまでを評価する。上下限が閾値をまたぐ場合はwarning側へ倒し、相関不能・終了欠測は`not_evaluable` |
| 後続Job Bの総queue wait | `>750秒` | `>1200秒` | `Job.created_at`からBの実行開始まで。A完了からB開始までのhandoff gapは別指標とし、補助guardとしてwarning `>10秒`、fail `>30秒`を提案する |

暫定案の正式採用には、業務責任者・運用責任者・アプリ責任者が、指標定義、warning/fail値、approval ID、承認日、owner、review期限を記録する。初回canonical A/B測定を含む同条件3組の成功runが揃った時点、または2026-08-21の早い方で再評価し、中央値、最大値、欠測、warning発生状況を確認する。承認完了までは6指標のverdictを`not_evaluable`、S2-CR-08を「部分実施」のままとする。

## 3. High

#### 第3段階（先行実装）: 登録経路別の分類安全化

- OCRは工程分類（class 1〜5）を優先し、工程判定不能時にマスタへ明示登録済みの場合だけclass 8を使用する。品名等からclass 8を推測せず、製品検査class 6/7へフォールバックしない。
- 見取り図は工程分類（class 1〜5）だけを使用し、明示class 8や製品検査ファイルへフォールバックしない。
- Excel／コード検索による手動追加は製品検査（class 6または7）だけを使用し、機械設定へフォールバックしない。
- class 1と2の同時成立は機械設定ミス、class 6と7の同時成立は検査書配置ミスとして対象作成を中止する。
- 同じ品目コードでも登録経路が異なる工程検査と製品検査は、確定クラス別の対象・履歴として同日に共存させる。
- class 9は特殊検査専用APIからのみ作成し、通常分類に参加させない。
- 対象には`registration_route`と確定クラスを保存し、チェック更新・表示・検査書選択は`target_id`と確定クラスを基準にする。既存の確定クラス不明データは`legacy`として推測更新しない。
- 機械31をclass 2へ直す実データ修正はmigrationへ決め打ちせず、運用時に機械マスタから実施する。

受入では、class 1/2競合、class 6/7競合、ファイルなし、class 2+7共存、class 1+6共存、通常クラス+9共存、別クラス間で履歴が混ざらないことを確認する。分類ルール自体は確定したが、本番データの機械31修正と業務責任者によるゴールデンデータ承認が終わるまでCriticalは未解消とする。

| 項目 | 受入基準 |
|---|---|
| 認証防御 | ログイン試行制限、セッション期限/失効、パスワード方針、CSRF、無効ユーザー遮断を試験 |
| RBAC/所有者分離 | 全APIの匿名/worker/admin、他利用者ID・日付による越権を自動試験 |
| 監査 | マスタ、設定、レイアウト、機械、発行、日報、削除/非表示を誰がいつ何に行ったか記録し改ざん・保持方針を決定 |
| ログ/health/監視 | 構造化ログ、相関ID、health/readiness、DB/worker/共有/印刷監視、通知と一次対応手順を実地確認 |
| CI/品質ゲート | backend test、frontend build、lint、migration check、依存脆弱性/secret scanを必須化。現状lint 45 errors/1 warningを解消 |
| 統合/負荷/長時間試験 | 最大日数・件数、367日集計、同時利用、ERP timeout、大容量ファイルを本番相当で合格 |
| マスタ更新方式 | 現行の単一transactionによる `update_or_create` と InspectionFile 全削除再作成について、本番相当件数でlock時間・rollback・参照整合性を試験する。`staging -> validation -> swap` を採用する場合は設計、移行、切替失敗時の復旧基準を承認する |
| dependency lock/脆弱性 | Python/Node依存を再現可能に固定し、SBOM、定期更新、重大CVEのSLAを設定する。特にコードがimportする `pywinauto`、`python-dotenv`、`psutil` が `requirements.txt` に未登録のため、正式なversion範囲を追加したクリーン環境でERP経路のimport/E2Eが成功することを品質ゲートとする |
| upload/media | 5MB、JPEG/PNG/WebP検証に加え、保存先分離、マルウェア対策、quota、孤児ファイル清掃、バックアップを検証 |

## 4. Medium

- アクセシビリティ、対応ブラウザ/解像度、タイムゾーン・営業日境界を明文化し試験する。
- データ保持・削除、個人情報、アバター、監査ログの保管期間と問い合わせ手順を決める。
- 運用手順書、障害対応、利用者教育、管理者引継ぎ、変更管理、リリースノートを整備する。
- レイアウト背景画像、所有者ごとの閲覧範囲、複数adminの競合解決、版管理の仕様を決める。

## 5. リリース判定で残す未決事項

1. 登録経路別分類のゴールデンデータと、機械31をclass 2へ直した結果の業務承認。
2. 匿名自己登録を許可するか。
3. レイアウトを共有資産とするか、所有者ごとに閲覧範囲を隔離するか。編集操作はadmin限定とする。
4. `issued` を印刷指示受付、スプール投入、物理印刷完了のどの時点とするか。
5. 対応する Windows/Office/プリンタ/ERP の版、サービスアカウントとライセンス。
6. RPO/RTO、保持期間、監査ログ閲覧者、障害通知先。

## 6. 最終受入

- Critical 全項目の証跡、High の合格または期限付きリスク受容、未決事項の承認記録が揃っている。
- 本番同等環境で「ログイン→取込→分類→チェック→検査書→日報→サマリー」のE2Eと、障害・復元・再起動試験に合格する。
- 既知制約、運用責任者、ロールバック条件をリリース判定会で承認する。

## 7. HTTP承認

- 管理番号: IFC20260716-001
- 対象環境: 開発/疑似本番
- 有効期限: 2027/7/16まで
