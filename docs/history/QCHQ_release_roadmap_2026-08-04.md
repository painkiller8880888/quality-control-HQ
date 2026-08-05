# Quality Control HQ 正式リリース認可までの実装ロードマップ

作成日: 2026-08-04  
対象リポジトリ: `painkiller8880888/quality-control-HQ`  
主な参照先: `specification/RELEASE.md`（正式リリース要件）、現行mainブランチ、`AGENTS.md`、Codex開発パイプライン文書。実施履歴・進捗・証跡はGitHubまたは凍結アーカイブを参照する。

## tl;dr

現在地は、MVP機能を増やす段階ではなく、正式リリースに必要な安全性、復旧性、業務承認、運用証跡を完成させる段階である。

疑似本番配信、PostgreSQL分離、WaitressとworkerのWindowsサービス化、永続ジョブキュー、排他・冪等性、主要な停止復旧試験、登録経路別分類のコード、PR用CIはかなり進んでいる。一方で、正式リリースを止めるCriticalとして、実バックアップ／復元、DB移行失敗からの復旧、分類ゴールデンデータ承認、自己登録方針、異常応答と情報漏洩、Excel・印刷の無人運用、共有PC上の本番TLS配信が残っている。

本書は2026-08-04時点の計画・履歴であり、現在状態や次回作業の正本ではない。正式リリース要件は`RELEASE.md`、実施履歴・進捗・証跡はGitHubまたは凍結アーカイブを参照する。

正式リリースまでのCritical pathは次の順番とする。

`進捗同期 → バックアップ／復元の実運用化 → S2-CR-08評価 → 分類・登録・エラー・認証 → DB移行復旧 → Excel／印刷 → 本番共有PC＋TLS → High項目と最終E2E → リリース判定`

---

## 1. 現在地

### 1.1 完了またはほぼ完了している領域

| 領域 | 現在の判定 | 補足 |
|---|---|---|
| 疑似本番基盤 | 合格済み | 開発DBと疑似本番DBの分離、Waitress、静的配信、WinSW、自動復旧、LAN制限、`DEBUG=False`などの試験記録がある。ただし共有PC上の正式本番とTLSは別途必要である。 |
| ジョブ非同期化 | 主要部分は合格済み | PostgreSQL永続queue、専用worker、lease、heartbeat、再試行、冪等性、依存待機、`quality_master`排他が実装されている。 |
| マスタ更新の停止復旧 | 合格済み | worker停止、DB backend切断、lease失効、重複配送、共有切断などの証跡がある。 |
| 登録経路別分類 | コード実装済み | OCR、見取り図、Excel／コード、特殊検査を別経路として扱う。業務ゴールデンデータ承認と機械31の実データ修正が残る。 |
| CI品質ゲート | mainへ統合済み | backend、frontend、dependency audit、Windows依存、secret scanがPRで動く。Rulesetの手動設定と全履歴secret scanは残る。 |
| Stage B backup/restoreのpure validation | 大部分を実装済み | strict schema、PlanOnly、Execute証跡、Cleanup、サービス所有権、retained dump、exact one-dropなどのコードとfake/static testが存在する。 |

### 1.2 部分実施または未完了の領域

| 領域 | 現在の判定 | 正式リリースを止める理由 |
|---|---|---|
| Stage B production provider | 未完了 | orchestratorは存在するが、実Windows／PostgreSQL／サービスへ接続するdeployment固有callbackが完成・承認されていない。 |
| バックアップ／復元の実地試験 | 未完了 | 別DBへの実restore、照合、Cleanup、証跡bundleが承認済み手順で完了していない。 |
| S2-CR-08 criterion 8 | 部分実施 | 6指標の正式評価と同条件A/B成功runが揃っていない。`criterion_8=not_evaluable`を維持する。 |
| DB本番移行／復旧 | 未完了 | 本番相当データのmigration時間、lock影響、途中失敗、rollback／restoreの実地証跡がない。 |
| 自己登録方針 | 未決・未実装 | 現行APIは匿名利用者がworkerを即時作成できる。閉じた社内システムとしては管理者作成方式を推奨する。 |
| エラー契約 | 部分実施 | `error_response`の呼び出し形は改善されているが、DRF標準`detail`やfield errorとの混在、内部path・例外漏洩の全経路試験が完了していない。 |
| Excel／印刷 | 未完了 | Office、マクロ、プリンタ、共有権限、紙切れ、ファイルlock、Excel残留の無人E2Eと復旧試験がない。 |
| 正式本番配信 | 未完了 | 共有PCへの再構築、TLS、Secure cookie、正式DNS／firewall、更新・切戻しが未完了である。 |
| 監視・監査・負荷 | 一部未完了 | health/readiness、通知、監査対象の網羅、長時間・同時利用試験などが残る。 |

---

## 2. ロードマップの運用原則

このロードマップでは、一つのIssueに一つの「確認可能な挙動境界」だけを入れる。Lunaへ長大な一括実装を渡さない。特に、バックアップ、DB作成・削除、認証、権限、TLS、印刷のIssueは、読み取り専用Scout、実装、fake/static検証、runtime実行を別Issueに分ける。

各Issueは、次の流れで進める。

`Issue要求 → Lunaによるread-only Scout → Web GPTによるPlan確定 → Luna実装 → verify → Draft PR → Web GPT独立レビュー → 修正 → CI → 人間によるマージ`

次の場合、Lunaは実装を続けずに停止する。

- 対象ファイルまたは責任領域が計画の2倍以上に広がった。
- DB schema、認証、権限、サービスアカウント、破壊的操作へ想定外に波及した。
- 既存試験の失敗原因が特定できない。
- 現行コードと`RELEASE.md`の正式要件、承認済み方針、Issue受入条件が矛盾する。
- 実runtime、サービス停止、DB作成・削除、印刷、共有アクセスが必要になったが、当該Issueに明示承認がない。

---

## 3. 全体ロードマップ

| フェーズ | 目的 | 初心者向けの説明 | 完了条件 |
|---|---|---|---|
| R0. 正本同期 | 正式要件とGitHub上の実施記録の参照先を分離する | 要件と履歴が混在すると、過去の状態を現行要件や次回作業と誤認する。 | `RELEASE.md`が正式要件・受入基準の正本であり、実施結果・進捗・証跡がGitHubまたは凍結アーカイブにある。 |
| R1. バックアップ／復元 | データを失っても戻せることを実証する | バックアップファイルを作っただけでは不十分で、別DBへ戻してアプリが使えることを確認して初めて復旧手段になる。 | 承認済みPlanOnly、Execute、Cleanup、整合確認、criterion 8評価が完了する。 |
| R2. 業務・認証・エラー | 誤分類、無断登録、越権、情報漏洩を防ぐ | 正しい利用者が正しい検査だけを扱い、失敗時にも秘密情報を画面へ出さない状態にする。 | ゴールデンデータ、登録方針、エラー契約、RBAC、認証防御が合格する。 |
| R3. DB移行／復旧 | 本番更新に失敗しても戻せるようにする | アプリ更新時にはDBの形も変わる。途中で止まった場合に業務データを壊さず戻せるかを事前に練習する。 | 本番相当migration、失敗注入、restore／rollback、照合が合格する。 |
| R4. Excel／印刷 | 外部ソフトと機器を無人で安全に動かす | Excelやプリンタはアプリ外で失敗する。紙切れやファイル使用中でも、二重印刷や永久停止を起こさないようにする。 | 成功E2Eと主要障害の復旧試験が全件成功する。 |
| R5. 正式本番配信 | 共有PC上でTLS付き本番を構築する | 疑似本番PCで動くことと、本番共有PCで安全に動くことは別である。本番機で一から再構築して証明する。 | TLS、Secure cookie、サービス復旧、更新・切戻し、本番データ移行が合格する。 |
| R6. High／運用 | 日常運用で壊れた状態を早く発見する | 正式リリース後は、障害を防ぐだけでなく、起きた障害を早く発見し、担当者が迷わず対応できる必要がある。 | Highが合格、または期限・責任者付きでリスク受容される。 |
| R7. リリース認可 | 証跡を一つの判定資料へまとめる | コードが動くという自己申告ではなく、誰が、何を、どの結果で承認したかを揃える。 | Critical全件、High判定、未決事項、最終E2Eが承認される。 |

---

## 4. 推奨Issueバックログ

### R0. 正本同期

#### R0-01 `RELEASE.md`の現行main同期

**何をするか**  
現行`deployment/windows/validate_stage_b_backup_restore.ps1`、関連test、commit、CI PRを読み、`RELEASE.md`の正式要件と、GitHub／凍結アーカイブにある実施記録の参照関係を確認する。

**何のためか**  
文書上はStage BのTODO 1が次作業になっているが、現行コードにはProcess result validation、execution evidence、Cleanup、production adapter境界が存在する。次のIssueが誤った開始地点を使わないようにする。

**短い実装計画**  
コード変更は行わず、状態を「実装済み」「fake/static合格」「runtime未実施」「承認待ち」に分ける。`LIVE_BLOCKED=True`と`criterion_8=not_evaluable`は変更しない。

**受入条件**  
`RELEASE.md`が正式要件・受入基準の正本として安定し、実施結果・未検証事項・runtime gapはGitHubまたは凍結アーカイブから再現できる。

#### R0-02 Critical承認台帳の作成

**何をするか**  
Criticalごとにowner、approver、期限、閾値、切戻し条件、証跡保存先を一表にする。

**何のためか**  
実装者が独自に数値や合否を決めることを防ぐ。

**短い実装計画**  
`specification/release-approval-register.md`などの文書を新設し、未承認を空欄ではなく`PENDING`と明記する。秘密値や実UNC pathは書かない。

**受入条件**  
全Criticalに責任者と状態があり、未承認項目が自動的にPASSにならない。

---

### R1. バックアップ／復元とS2-CR-08

このフェーズは現在の最優先である。実装済みorchestratorへ、実環境固有の処理を安全に接続し、別DBへ実際に復元できることを証明する。

#### R1-01 Stage B runtime provider gapのread-only Scout

**何をするか**  
orchestratorが要求する`Snapshot`、`Catalog`、`Process`、`Service`、`State`、`CreateRestore`、`DropRestore`について、現行deploymentスクリプトで再利用できる処理と不足処理を調べる。

**何のためか**  
既存コードと重複したproviderを作らず、実runtimeへの接続点を確定する。

**短い実装計画**  
変更を行わず、関連ファイル、callbackごとの入力・出力、使用予定コマンド、必要権限、既存test、未確認点を返す。

**受入条件**  
callback単位の依存表ができ、次Issueの変更範囲が3ファイル程度に限定できる。

#### R1-02 read-only runtime callbackの実装

**何をするか**  
`Snapshot`、`Catalog`、`State`、`Jobs`を実PostgreSQLから読み取るproviderを実装する。

**何のためか**  
変更前と変更後のDB状態を機械的に照合し、誤ったDBを操作しないためである。

**短い実装計画**  
新規providerファイル候補へcallbackを実装し、実行結果をstrict schemaへ変換する。最初はfake/static testだけを行い、実DBへは接続しない。

**受入条件**  
正常値、0件、複数候補、型不正、接続失敗、timeoutをfail-closedで処理する。

#### R1-03 PostgreSQL Process callbackの実装

**何をするか**  
`pg_dump`、`pg_restore --list`、`pg_restore`、`retained_dump`を起動するcallbackを実装する。

**何のためか**  
外部コマンドの成功を「終了コード0」だけで判断せず、サイズ、hash、対象、timeoutまで確認する。

**短い実装計画**  
shell文字列連結を避け、引数配列と限定したenvironmentを使う。stdout、stderr、exit code、timeoutをstrict resultへ変換し、秘密値を公開応答や証跡へ含めない。

**受入条件**  
各operationのpositive／negative testがあり、未知operation、malformed result、timeout、部分ファイルを成功扱いしない。

#### R1-04 Service・CreateRestore・DropRestore callbackの実装

**何をするか**  
Web／workerの停止・開始と状態readback、restore DBの作成・削除を実装する。

**何のためか**  
停止していないサービスや接続中DBを操作すると、復元中にデータが変わったり削除が失敗したりする。

**短い実装計画**  
サービスは「この実行が停止したものだけ」を再起動対象にする。DB作成・削除はendpoint、database、OID、owner、active connection、active Jobを再確認してから一度だけ実行する。

**受入条件**  
誤owner、誤OID、接続あり、Jobあり、既存非空DB、service state不一致ではmutationを行わない。Cleanupは明示承認なしに実行できない。

#### R1-05 production providerのnon-live統合試験

**何をするか**  
R1-02～04をorchestratorへ接続し、fakeまたは隔離されたcontrolled environmentで順序と失敗処理を確認する。

**何のためか**  
callback単体が正しくても、組み合わせた順序が誤っていれば復旧できないためである。

**短い実装計画**  
`PlanOnly`、`Execute`、`Cleanup`の入口を分け、既存testにprovider integration testを追加する。実疑似本番データはまだ操作しない。

**受入条件**  
stop-worker→stop-web→dump→list→create→restore→比較→start-web→start-worker、Cleanupのone-dropが期待どおりである。

#### R1-06 承認済みPlanOnly実行

**何をするか**  
実runtime設定を読み、DB、owner、client version、storage、service、active Job、protected targetを確認し、pending manifestを作る。

**何のためか**  
実際に変更する前に、対象が正しいことと、復元先が本番DBではないことを確認する。

**短い実装計画**  
このIssueではmutationを禁止する。実行環境、承認ID、期限、artifact hash、証跡rootを人間が指定する。

**受入条件**  
manifestとchecksumがatomicに作られ、privacy scanが通り、全preflightがPASSする。

#### R1-07 承認済みExecute復元リハーサル

**何をするか**  
別restore DBへ実dump／restoreを行い、件数、制約、semantic hash、InspectionFile path set、ログイン、主要E2Eを照合する。

**何のためか**  
バックアップが「作れる」だけでなく、「戻せて使える」ことを証明する。

**短い実装計画**  
R1-06のexact manifestへ紐づくapprovalだけを受理する。失敗時はdumpとpartial restoreを保持し、自動削除しない。

**受入条件**  
sourceを変更せず、restore DBが別OIDで作成され、照合表とatomic evidence bundleが完成する。

#### R1-08 承認済みCleanupリハーサル

**何をするか**  
R1-07の成功証跡へ紐づく別承認で、restore DBだけを削除する。

**何のためか**  
復元確認後の後片付けでも、本番DBやdumpを誤って削除しないことを証明する。

**短い実装計画**  
owner、OID、endpoint、active connection、active Job、dump hashを再確認する。DropRestoreはexact one回とする。

**受入条件**  
restore DBの不存在、dump保持、cleanup evidence、service状態、Job 0が確認できる。

#### R1-09 S2-CR-08 canonical A/B測定と判定

**何をするか**  
承認済み閾値で同条件A/Bを測定し、CPU、メモリ、DB接続、lock待ち、transaction時間、queue waitを評価する。

**何のためか**  
ジョブが安全でも、実運用で極端に遅い、またはDBを圧迫する場合は正式運用できない。

**短い実装計画**  
backup/restoreのreview完了後にだけ実施する。欠測または相関不能はPASSではなく`not_evaluable`とする。

**受入条件**  
必要な成功run数、threshold verdict、warning／fail時の再review記録が揃い、S2-CR-08を「合格」または明示的な未合格として更新できる。

---

### R2. 分類・自己登録・エラー・認証

#### R2-01 分類ゴールデンデータと機械31の業務承認

**何をするか**  
全クラス、競合、経路別共存、class 9を含む期待結果データを作り、品質管理責任者が承認する。機械31は画面からclass 2へ修正する。

**何のためか**  
分類ロジックがコード上で正しくても、業務責任者が期待する結果と一致しなければ検査漏れや誤発行が起きる。

**短い実装計画**  
golden dataをfixture化し、取込、表示、履歴、検査書、日報、サマリーの回帰試験へ使う。実データ修正はmigrationへ埋め込まない。

**受入条件**  
承認済み期待値と全経路の結果が一致し、機械31修正後の証跡がある。

#### R2-02 自己登録方針の決定

**何をするか**  
匿名自己登録、招待制、管理者作成のどれを採用するか決める。

**何のためか**  
方針を決めずにUIだけ隠すと、APIから利用者を作成できる状態が残る。

**推奨**  
工場内の限定利用であるため、管理者作成方式を推奨する。

**受入条件**  
採用方式、責任者、監査対象、例外手順が承認される。

#### R2-03 採用した登録経路の実装

**何をするか**  
選択外の登録APIとUIを無効化し、採用経路へ監査と濫用防止を加える。

**何のためか**  
未承認利用者の作成と、無効化したはずの裏口APIを防ぐ。

**短い実装計画**  
管理者作成方式の場合は匿名`auth/register/`を拒否し、admin APIで初期利用者を作る。成功・拒否をAuditLogへ記録する。

**受入条件**  
匿名、worker、adminの全経路を試験し、選択外経路がUI／API双方で利用できない。

#### R2-04 エラー経路台帳と契約試験

**何をするか**  
全APIの既知異常を列挙し、期待status、`error_code`、公開message、details、ログ内容を固定する。

**何のためか**  
異常処理を個別に直す前に、「利用者へ何を返し、ログへ何を残すか」を統一する。

**短い実装計画**  
認証、serializer、業務例外、Job失敗、404、500を表にし、現在の応答をtestで採取する。ここでは修正を最小限にする。

**受入条件**  
未試験の異常経路が見える状態になり、内部path、stack、secret候補を検出するnegative testがある。

#### R2-05 公開エラースキーマと相関IDの実装

**何をするか**  
公開エラーを統一し、内部例外を構造化ログへ、利用者へは相関IDと安全な文言だけを返す。

**何のためか**  
利用者が問い合わせできる一方で、ファイルpathや資格情報を漏らさないようにする。

**短い実装計画**  
DRF exception handlerまたは共通helperを導入し、既存APIを段階的に移す。既存の業務`error_code`は保持する。

**受入条件**  
既知異常が500／TypeErrorにならず、公開応答に内部情報がなく、ログから相関IDで追跡できる。

#### R2-06 RBAC・所有者分離の全API matrix試験

**何をするか**  
匿名、worker、admin、他利用者のID／日付を組み合わせて全APIを試験する。

**何のためか**  
画面上で見えなくても、URLやIDを変更して他人の検査データを読める可能性を潰す。

**短い実装計画**  
endpoint台帳からparameterized testを作り、read／write／delete／file／Jobを分類する。

**受入条件**  
許可表と自動試験結果が一致し、他利用者スコープへの越権が0件である。

#### R2-07 認証防御

**何をするか**  
ログイン試行制限、session期限・失効、password policy、無効利用者遮断を実装する。

**何のためか**  
パスワードを何度でも試せる状態や、無効化後もsessionが残る状態を防ぐ。

**短い実装計画**  
まず方針値を承認し、その後にlogin rate limit、session設定、password validator、is_active再確認を追加する。

**受入条件**  
正常ログインを壊さず、連続失敗、session期限、password変更、無効化を自動試験で確認する。

#### R2-08 監査対象の網羅

**何をするか**  
マスタ、設定、レイアウト、機械、発行、日報、非表示、利用者管理をAuditLogへ記録する。

**何のためか**  
誰が業務結果や設定を変えたかを後から説明できるようにする。

**短い実装計画**  
操作一覧を先に固定し、各write endpointへ共通監査helperを適用する。秘密値やファイル内容をdetailsへ保存しない。

**受入条件**  
対象操作、保持期間、閲覧者、改ざん防止方針が決まり、主要操作の監査testが通る。

---

### R3. DB本番移行／復旧

#### R3-01 本番相当データセットと移行計画

匿名化した本番相当データ、件数baseline、migration一覧、予想lock、停止時間、rollback条件を準備する。これは実migrationを安全に練習するための土台である。

#### R3-02 全migration適用リハーサル

承認済みデータへ全migrationを適用し、時間、lock、CPU、DB接続、サービス停止時間を記録する。migrationが通るだけではなく、業務E2Eが通ることを確認する。

#### R3-03 migration失敗注入と復旧

途中失敗を意図的に発生させ、transaction rollback、前backupからのrestore、前版アプリとの整合を確認する。自動で戻せないmigrationは、事前に明示して承認する。

#### R3-04 移行runbookと整合確認表

本番担当者が順番どおり実施できる手順書を作る。各手順には開始条件、成功判定、失敗時の停止位置、戻し方、証跡保存先を記載する。

---

### R4. Excel／印刷運用

#### R4-01 対応環境と`issued`意味の承認

Windows、Office、プリンタ、ERP、サービスアカウント、ライセンスを固定する。`issued`を受付、spool投入、物理印刷完了のどこで立てるかを決める。

#### R4-02 Excel／プリンタ資源の排他と冪等性

同じworkbook、macro、printerへ同時にJobが入らないresource keyを設計する。外部副作用Jobは自動再試行で二重印刷を起こさないようにする。

#### R4-03 無人E2E成功試験

サービスアカウントで検査書発行と日報生成・印刷を実行し、画面操作なしで完了することを確認する。

#### R4-04 障害試験

file lock、共有断、paper out、printer offline、Excel残留process、macro error、service再起動を一つずつ試験する。一括発行では他対象を継続するか、全体を停止するかを仕様どおり確認する。

#### R4-05 運用runbookと証跡承認

障害時に、作業者、管理者、IT担当者が行う操作を分ける。二重印刷を避ける再実行条件と、残留Excelを終了してよい条件を明記する。

---

### R5. 正式本番共有PCとTLS

#### R5-01 本番ネットワーク／TLS設計

正式DNS、TLS終端、certificate更新、LAN範囲、port、firewall、HTTPからHTTPSへの扱いを承認する。疑似本番のHTTP例外を本番へ自動継承しない。

#### R5-02 共有PCへ本番環境を再構築

PostgreSQL、DB role、Waitress、worker、環境変数、静的file、media、log、service accountを承認済み手順で一から構築する。疑似本番PCのfolderをそのままコピーして本番扱いしない。

#### R5-03 本番security acceptance

`DEBUG=False`、secret外部管理、host／origin限定、HTTPS、Secure／HttpOnly／SameSite cookie、CSRF、deployment check、認証試験を実施する。

#### R5-04 起動・停止・再起動・更新・切戻し

OS再起動、Waitress停止、worker停止、異常終了、version更新、frontend切替、migration前後、前版rollbackを本番PCで練習する。

#### R5-05 本番データ移行とsmoke

R3の手順で本番データを移し、件数、constraint、file参照、login、取込、check、検査書、日報、サマリーを確認する。

---

### R6. High項目と運用準備

#### R6-01 GitHub main Rulesetと全履歴secret scan

PR必須、required checks、conversation resolution、force push禁止を設定し、手動の全履歴secret scanを実施する。検出時は無条件allowlistで隠さない。

#### R6-02 構造化log、health、readiness、監視、通知

Web、DB、worker、UNC、印刷の状態を分けて確認できるendpointと監視を作る。通知先と一次対応手順を実地確認する。

#### R6-03 統合・負荷・長時間試験

最大件数、367日summary、同時利用、長時間master update、大容量upload、worker backlogを試験する。単発の成功だけでなく、一定時間安定することを確認する。

#### R6-04 SBOMと依存更新SLA

現行lockとauditに加え、Python／NodeのSBOM、更新周期、重大CVEの対応期限、緊急更新手順を決める。

#### R6-05 upload／media運用

保存先分離、quota、malware対策方針、孤児file清掃、backup対象、content validationを整備する。

---

### R7. 最終受入とリリース認可

#### R7-01 最終E2E・障害・復元試験

本番同等環境で、`login → import → classification → checks → inspection sheet → daily report → summary`を通す。続けてサービス再起動、DB復元、共有断、印刷障害を実施する。

#### R7-02 リリース証跡matrix

Criticalごとに、受入条件、証跡path、実施日、環境、commit／version、担当者、approver、判定を一表にする。HighはPASSまたは期限・責任者付きrisk acceptanceとする。

#### R7-03 リリース判定会

未決事項、既知制約、rollback条件、運用責任者、障害通知先を承認する。Criticalが1件でも未達なら正式リリース不可とする。

---

## 5. 直近の推奨着手順

次にGitHub Issueを作る順番は、次のとおりとする。

1. `R0-01 RELEASE.mdの現行main同期`
2. `R0-02 Critical承認台帳の作成`
3. `R1-01 Stage B runtime provider gapのread-only Scout`
4. `R1-02 read-only runtime callbackの実装`
5. `R1-03 PostgreSQL Process callbackの実装`
6. `R1-04 Service・CreateRestore・DropRestore callbackの実装`
7. `R1-05 production providerのnon-live統合試験`
8. 人間によるruntime prerequisiteと実行承認
9. `R1-06 承認済みPlanOnly実行`
10. `R1-07 承認済みExecute復元リハーサル`
11. `R1-08 承認済みCleanupリハーサル`
12. `R1-09 S2-CR-08 canonical A/B測定と判定`

R2以降へ先に着手することは可能であるが、正式リリースの最大の不確実性は復元可能性である。初心者開発では、多数の機能修正を先行させるより、まず「壊しても戻せる」状態を完成させたほうが安全である。

---

## 6. Issue作成用の最小テンプレート

```markdown
## 目的
このIssueで確認可能にする一つの挙動を書く。

## なぜ今行うか
前段Issueとの依存関係と、正式リリース要件との対応を書く。

## 現在の挙動
現行mainで確認済みの事実を書く。推測を書かない。

## 期待する挙動
変更後に利用者または運用者から見える結果を書く。

## In scope
今回変更してよいファイル、機能、testを書く。

## Out of scope
今回は変更しない領域、runtime操作、将来Issueを書く。

## 受入条件
- AC-1:
- AC-2:
- AC-3:

## 必須証跡
実行コマンド、exit code、test結果、必要なlogまたはevidence pathを書く。

## Scout指示
read-onlyで確認する関連ファイル、現状、依存、既存test、未確認点を書く。

## Lunaへの停止条件
仕様矛盾、変更範囲拡大、DB／権限／runtime操作、原因不明test failure時に停止して報告する。
```

---

## 7. Codex用Planを短く保つ基準

Lunaへ渡す実装Planは、原則として次の規模に抑える。

| 項目 | 目安 |
|---|---|
| 目的 | 1つの挙動境界 |
| 変更候補 | 1～3領域、通常は5ファイル以内 |
| 実装手順 | 4～8手順 |
| 受入条件 | 3～6件 |
| 検証 | 直接test＋既存回帰＋`scripts/verify.ps1` |
| runtime操作 | 通常Issueから分離し、人間の明示承認を必要とする |
| PR | Draftで作成し、未確認事項を空欄にしない |

Lunaが一度に、provider実装、実DB restore、service停止、evidence作成、RELEASE更新まで担当するIssueは大きすぎる。実装とruntime実行と文書承認は必ず分ける。

---

## 8. リリース判定の最終チェック

正式リリース認可の直前には、最低限、次を満たす。

- Critical全項目がPASSであり、必須証跡が存在する。
- S2-CR-08が`not_evaluable`のまま残っていない。
- 匿名自己登録の選択外経路が利用できない。
- 既知異常で内部path、stack、secretを返さない。
- 本番相当backupから別DBへrestoreでき、主要E2Eが通る。
- migration途中失敗から承認済み手順で復旧できる。
- Excel／印刷の成功と主要障害復旧が無人環境で確認されている。
- 共有PC上でTLS、Secure cookie、service自動復旧、更新・切戻しが確認されている。
- High項目がPASS、または期限・責任者付きrisk acceptanceになっている。
- release version、commit、設定票、運用責任者、rollback条件が判定会で承認されている。

この条件が揃うまでは、疑似本番で安定して動いていても「正式リリース可能」とは扱わない。
