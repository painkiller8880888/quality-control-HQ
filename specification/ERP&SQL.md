# ERPとSQLのテーブル構造（PostgreSQL 移行版）

## 0.1 Django モデル同期情報（2026-07-15）

スキーマの最終的な正は `backend/quality/models.py` と適用済み migration とする。旧SQL表記と異なる主要点は次のとおり。

| Django model | 物理テーブル | 現行の主要制約・補足 |
|---|---|---|
| `User` | `users` | `user_id` PK、`login_name` unique、role=`admin|worker`、avatar/last_login |
| `Master` | `quality_master` | code unique、node_type/node_type_1/node_type_2、department/category/product_category |
| `ClassMaster` | `quality_classmaster` | class_no unique |
| `MasterClass` | `quality_masterclass` | `(master,class_master)` unique、検査書パス。通常クラス9は除外運用 |
| `SpecialInspectionClass9` | `quality_specialinspectionclass9` | master と one-to-one、クラス9専用検査書パス |
| `AppSetting` | `quality_appsetting` | CSV、検査書フォルダ群、ERP、履歴ファイルの各パス |
| `Structure` | `quality_structure` | `(parent_code,child_code)` unique。root_code/level/quantity |
| `InspectionFile` | `quality_inspectionfile` | master FK、file_name/file_path、フォルダ優先順位、ファイル作成日時、探索日時 |
| `InspectionSession` | `quality_inspectionsession` | `(owner_user,target_date)` unique、status/history/note、論理削除・監査列 |
| `InspectionTarget` | `quality_inspectiontarget` | `(session,normalized_code,class_override)` unique (`nulls_distinct=False`)、source、発行状態、visible、論理削除・監査列 |
| `InspectionTargetWarning` | `quality_inspectiontargetwarning` | target FK、error_code/message/details |
| `History` | `quality_history` | `(created_by,date,master,time_slot,class_override)` unique (`nulls_distinct=False`)、A-D、発行済フラグ、論理削除・監査列 |
| `Machine` | `quality_machine` | machine_no unique、class は 1-6/10 またはNULL、shape は circle/ellipse/rectangle |
| `MachineAssignment` | `quality_machineassignment` | `(machine,code)` unique、assignment_class |
| `LayoutMaster` | `quality_layoutmaster` | layout_name unique、grid、owner_user。背景画像APIは未対応 |
| `LayoutObjectType` | `quality_layoutobjecttype` | code は machine/wall/path/area/stairs/entrance |
| `LayoutObject` | `quality_layoutobject` | layout/type/machine、grid位置・寸法、rotation、meta_json |
| `Job` | `quality_job` | 文字列 job_id PK、4 job_type、queued/running/succeeded/failed、payload/result/error |
| `UserSetting` | `user_settings` | user one-to-one、theme/font_size/browser_settings_imported |
| `SystemSetting` | `system_settings` | setting_key PK、value、updated_by |
| `AuditLog` | `audit_logs` | user、operation、table/record、details_json。operation のDB CHECKはない |

`PROTECT` FK と論理削除列は存在するが、全モデル・全APIで論理削除が一貫しているわけではない。バックアップ/リストア、保持期間、監査ログの対象操作は正式リリース前に決定する。

> 正式DBは PostgreSQL。SQLite互換は考慮しない。
> 実スキーマは `backend/quality/migrations/` の Django migration と `models.py` を正とする。`specification/migrations/` は補助SQLであり、単独では完全なスキーマ定義ではない。

## 0. 共通規約（PostgreSQL）

- 数値PKは identity を使用する。例外として `Job.job_id` と `SystemSetting.setting_key` は文字列PK、`UserSetting.user_id` はFK兼PKである。
- 真偽値は `BOOLEAN`。
- 日付のみの列は `DATE`。`USE_TZ=True` のため Django `DateTimeField` は PostgreSQL の `TIMESTAMP WITH TIME ZONE` として保存する。本章の `TIMESTAMPTZ` は同型の略記である。
- `PositiveSmallIntegerField` は PostgreSQL上では `SMALLINT` と非負CHECKに展開される。NULL可否は各行の `nullable` 表記を正とし、単なる `INTEGER` 表記から業務上の値域を推測しない。
- JSON文字列は `JSONB`（対象: details/details_json / request_payload / result / meta_json）。
- ENUMは使用せず `TEXT` + `CHECK` 制約で表現する。
- FK は削除動作を `ON DELETE RESTRICT` で明示する。
- ユーザー所有データには `owner_user_id`（users.user_id 参照）を付与する。
  - 対象: `inspection_session`, `layout_master`
- 作業管理系テーブルには監査列 `created_by`, `updated_by`, `deleted_at`, `deleted_by`（users.user_id 参照）を付与する。
  - 対象: `inspection_session`, `inspection_target`, `history`, `jobs`
  - いずれも **NULL 許可**（既存データ移行時の補完用）。
- マスタ編集等の操作履歴は `audit_logs` が担う（監査列ではなく audit_logs で記録）。
- 新規テーブル: `users`, `user_settings`, `system_settings`, `audit_logs`（### 5.15〜5.18）。

## 1. ERP上の製品構成

- ERP上では製品は複数ノードから成る構成として表現される。
- 各ノードはコード、名称、階層レベル、担当部署、数量などを持つ。
- コード体系は以下を前提とする。
- `A/B`: 出荷可能な完成品または製品
- `C`: 中間工程品
- `D`: 単体部品
- `E`: 原料

## 2. 構成データ取込ルール

- ERP出力は上から順に処理する。
- 階層レベル `n` のノードは、直前方向に存在する最も近い階層レベル `n-1` のノードを親とする。
- 構成取込時は循環参照を検証する。
- 検証に失敗した場合、当該更新全体を本番反映しない。

## 3. クラス定義

- 検査対象には7クラスがある。
- コードのクラスは作業工程に応じて決定されるため、部品、社外加工、梱包など検査のないコードには定義されない。
- 各コードのクラスはそれぞれ個別の方法で定義される。

- `1`: 自動機。`1`: DBの`machine_assignment`テーブルにおいて、`assignment_class`が`1`のコード。
- `2`: 半自動機。`2`: DBの`machine_assignment`テーブルにおいて、`assignment_class`が`2`のコード。
- `3`: セッター。DBの`machine_assignment`テーブルにおいて、`machine_class`が`3`の機械に割り当てられたコード。
- `4`: プレス。DBの`master`において、`node_type_1`が`プレス`のコード。
- `5`: 二次加工。DBの`master`において、`node_type_1`が`加工`となって、かつ`department`が`製造管理部`または`生残技術部`のコード。
- `6`: 製品検査(1)。`製品検査(1)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (1)にファイルが存在するコード。
- `7`: 製品検査(2)。`製品検査(2)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (2)にファイルが存在するコード。
- `8`: 手動。上記のいずれにも該当しないコード。
- `9`: 一般ルーチン外の特殊な検査。ユーザーが個別に設定する。同じ品番でも通常検査と特殊検査が混在することがあり、それぞれ別の検査として扱われる。

- 検査書発行対象は `1`, `6`, `7`, `9`のみ。
- クラス判定順は業務未決である。現行実装 `1/2 → 3 → 6 → 7 → 4 → 5 → 8` と旧仕様順が異なるため、`PRODUCT.md` と `RELEASE.md` の承認要件に従い、ここでは順序を確定しない。

### 3.1 クラス9（特殊検査）の定義と運用ルール

- クラス9はユーザーがUIの「特殊検査追加」から明示的に追加した検査対象**のみ**に適用される特例である。
- 自動取り込み（OCR / Excel）および通常の手動追加で作成された検査対象は、原則としてクラス9には分類されない。分類は `MasterClass`（クラス1〜8用の自動分類マスタ）に依存する。
- クラス9の判定根拠は `inspection_target.class_override == 9` および `history.class_override == 9` のみとする。**`MasterClass` にクラス9の登録があっても自動分類のトリガーにはしない。**
- クラス9用の検査書ファイルパスは、自動分類用の `MasterClass` ではなく、専用テーブル `special_inspection_class9`（`### 5.2.2`参照）で品目ごとに管理する。
- 「特殊検査追加」UIは、裏で `class_override=9` の検査対象を作成するとともに、必要に応じて `special_inspection_class9` に検査書パスを登録する（案a）。
- `MasterClass` のクラス9登録は廃止済み。過去に存在したクラス9登録はマイグレーション `0017_delete_class9_masterclass` で全削除されている。

## 4. データモデル方針

- ERP由来マスタと、日次業務データは分離する。
- 当日検査対象は `inspection_session` と `inspection_target` に保存する。
- 検査実績は `history` に保存する。
- 警告は `inspection_target_warning` に保存する。
- 複数ユーザーによるチーム利用を前提とし、所有権・監査・権限は §0 の規約に従う。

## 5. テーブル定義

### 5.1 Master / `quality_master`

ERP由来の品目マスタ。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| code | TEXT UNIQUE | コード, ERPデータにおける10列目 |
| name | TEXT | 名称, ERPデータにおける11列目 |
| node_type_1 | VARCHAR(64), nullable | 作業種類1, PRODUCT.md参照 |
| node_type_2 | VARCHAR(64), nullable | 作業種類2, PRODUCT.md参照 |
| node_type | VARCHAR(64), nullable | 旧互換ノード種別 |
| category | SMALLINT, nullable, CHECK >= 0 | Django `PositiveSmallIntegerField`; 商品カテゴリ |
| product_category | VARCHAR(128), nullable | 製品カテゴリ |
| department | TEXT | 担当部署, ERPデータにおける17列目 |
| updated_at | TIMESTAMPTZ | 最終更新日時 |

### 5.2 MasterClass / `quality_masterclass`

コードのクラスを定義する。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| master_id | FK -> quality_master.id ON DELETE RESTRICT | 対応品目 |
| class_master_id | FK -> quality_classmaster.id ON DELETE RESTRICT, nullable | クラス参照 |
| inspection_sheet_path | TEXT NOT NULL DEFAULT '' | 通常検査書パス |
| updated_at | TIMESTAMPTZ | 最終更新日時 |

### 5.2.1 ClassMaster / `quality_classmaster`

コードのクラスのマスタ情報

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| class_no | SMALLINT UNIQUE, CHECK >= 0 | Django `PositiveSmallIntegerField`。業務上の許可値は別途クラス定義に従う |
| class_name | TEXT | クラスの名称。###3参照 |

 補足
  - class_no : class_name
  - `1`: 自動機
  - `2`: 半自動機
  - `3`: セッター
  - `4`: プレス
  - `5`: 二次加工
  - `6`: 製品検査(1)
  - `7`: 製品検査(2)
  - `8`: 手動
  - `9`: 特殊検査（※自動分類には使用しない。詳細は `### 3.1` および `### 5.2.2` 参照）

### 5.2.2 SpecialInspectionClass9 / `quality_specialinspectionclass9`

クラス9（特殊検査）として扱う品目と、その専用検査書ファイルパスを定義する。自動分類用の `class` テーブル（`### 5.2`）とは独立したテーブル。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| master_id | FK -> quality_master.id ON DELETE RESTRICT, UNIQUE | 対応品目 |
| inspection_sheet_path | TEXT NOT NULL DEFAULT '' | クラス9専用検査書ファイルのフルパス |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

制約

- `UNIQUE(master_id)`

補足

- クラス9の判定そのものは `inspection_target.class_override` / `history.class_override` で行われる。本テーブルは検査書パスの引当のみに使用する。
- レコードが存在し、かつ `inspection_sheet_path` が空でない場合に、該当品目のクラス9検査対象へ専用検査書が発行される。

### 5.2.3 AppSetting / `quality_appsetting`

システム連携用パス設定。現行実装は実質1レコードを参照する。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| csv_path | TEXT NOT NULL DEFAULT '' | ERP構成CSV |
| inspection_folder_paths | JSONB NOT NULL DEFAULT '[]' | 検査書探索フォルダ一覧 |
| inspection_folder_priorities | JSONB NOT NULL DEFAULT '{}' | フォルダパスごとの優先順位。数値が大きいほど優先 |
| erp_path | TEXT NOT NULL DEFAULT '' | ERP実行パス |
| history_file_path | TEXT NOT NULL DEFAULT '' | 履歴ファイルパス |
| updated_at | TIMESTAMPTZ | 更新日時 |

### 5.3 Structure / `quality_structure`

親子構成を保持する。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| root_code | TEXT INDEX | 構成ルートコード, ERPデータにおける2列目 |
| parent_code | TEXT INDEX | 親コード, ERPデータにおける9列目 |
| child_code | TEXT INDEX | 子コード, ERPデータにおける10列目 |
| level | SMALLINT CHECK >= 0 | Django `PositiveSmallIntegerField`; 親ノード階層 |
| quantity | NUMERIC(12,3), nullable | 使用数量, ERPデータにおける19列目 |

制約

- `UNIQUE(parent_code, child_code)`

### 5.4 InspectionFile / `quality_inspectionfile`

検査書ファイル索引。既存文書の探索結果を保持する。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| master_id | FK -> quality_master.id ON DELETE RESTRICT | 対応品目 |
| file_name | TEXT | ファイル名 |
| file_path | TEXT | フルパス |
| priority | INTEGER NOT NULL DEFAULT 0 | スキャン元フォルダの優先順位 |
| file_created | TIMESTAMPTZ, nullable | ファイルシステムから取得できた作成日時 |
| discovered_at | TIMESTAMPTZ | 探索日時 |

補足

- 検査書ファイル名には必ずコードを含む前提とする。
- フォルダ走査時にコード一致したファイルのみ登録する。
- 同一品番の候補は優先順位や作成日時にかかわらず全件登録する。
- 表示・PDF・印刷・一括発行時は、対象classの候補から `priority` 降順、作成日時あり優先かつ新しい順、正規化パス昇順、ID昇順で1件を選ぶ。
- 作成日時は利用可能なら `st_birthtime`、Windowsでは `st_ctime` から取得する。取得不能時はNULLのまま登録を継続する。
- ファイル名には複数のコードが記入されている場合がある。
- 走査フォルダ一覧
-- `自動機検査書フォルダ1`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\★自動機(工程内検査)
-- `自動機検査書フォルダ2`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\自動機\
-- `セッターフォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\セッター\
-- `製品検査(1)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (1)
-- `製品検査(2)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (2)

### 5.5 InspectionSession / `quality_inspectionsession`

ログイン利用者ごと・対象日ごとの検査業務単位。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| target_date | DATE | 対象日 |
| status | VARCHAR(16) NOT NULL CHECK (status IN ('open','closed')) | 状態 |
| history | BOOLEAN NOT NULL DEFAULT FALSE | 履歴ファイルへの記入状態 |
| note | TEXT NOT NULL DEFAULT '' | 日別ノート |
| owner_user_id | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成者(所有者) |
| created_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成ユーザー |
| updated_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 更新ユーザー |
| deleted_at | TIMESTAMPTZ, nullable | 削除日時(論理削除) |
| deleted_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 削除ユーザー |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

制約

- `UNIQUE(owner_user_id, target_date)`

### 5.6 InspectionTarget / `quality_inspectiontarget`

当日検査対象のスナップショット。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| session_id | FK -> quality_inspectionsession.id ON DELETE RESTRICT | 対象日 |
| master_id | FK -> quality_master.id ON DELETE RESTRICT, nullable | 未登録コード時はnull可 |
| raw_code | VARCHAR(64) NOT NULL | 取込元コード文字列 |
| normalized_code | VARCHAR(32) NOT NULL | 正規化後コード |
| source_ocr | BOOLEAN NOT NULL DEFAULT FALSE | OCR取込 |
| source_excel | BOOLEAN NOT NULL DEFAULT FALSE | Excel取込 |
| source_manual | BOOLEAN NOT NULL DEFAULT FALSE | 手動追加 |
| requires_inspection_sheet | BOOLEAN NOT NULL DEFAULT FALSE | 検査書要否 |
| issue_status | VARCHAR(32) NOT NULL CHECK (issue_status IN ('not_required','pending','issued','missing_file','skipped')) | 検査書発行状態 |
| visible | BOOLEAN DEFAULT TRUE | UI表示フラグ |
| class_override | SMALLINT, nullable, CHECK >= 0 | Django `PositiveSmallIntegerField`; 明示クラス |
| registration_route | VARCHAR(16), NOT NULL | `ocr` / `excel` / `manual_code` / `factory_map` / `special` / `legacy` |
| created_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成ユーザー |
| updated_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 更新ユーザー |
| deleted_at | TIMESTAMPTZ, nullable | 削除日時(論理削除) |
| deleted_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 削除ユーザー |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

制約

- `UNIQUE(session_id, normalized_code, class_override) NULLS NOT DISTINCT`
- 新規対象では`class_override`を対象作成時の確定クラスとして保存する。`ocr`/`factory_map`は1〜5、`excel`/`manual_code`は6/7、`special`は9とし、既存の推測不能データだけ`legacy`と`NULL`を許容する。

インデックス

- `normalized_code`
- `master_id`
- `session_id`
- `issue_status`

### 5.7 InspectionTargetWarning / `quality_inspectiontargetwarning`

当日検査対象に紐づく警告。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| target_id | FK -> quality_inspectiontarget.id ON DELETE RESTRICT | 対象 |
| error_code | VARCHAR(64) NOT NULL | `UNKNOWN_CODE` など |
| message | TEXT | 表示文言 |
| details | JSONB | 詳細 |
| created_at | TIMESTAMPTZ | 作成日時 |

### 5.8 History / `quality_history`

検査済み時間帯の履歴。

| column | type | note |
|---|---|---|
| history_id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| date | DATE | 日付 |
| master_id | FK -> quality_master.id ON DELETE RESTRICT | 対象品目 |
| class_override | SMALLINT, nullable, CHECK >= 0 | Django `PositiveSmallIntegerField`; 未指定時は通常クラスを参照 |
| time_slot | VARCHAR(1) NOT NULL CHECK (time_slot IN ('A','B','C','D')) | 時間帯 |
| is_sheet_issued | BOOLEAN DEFAULT FALSE | 検査書印刷済みフラグ |
| created_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成ユーザー |
| updated_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 更新ユーザー |
| deleted_at | TIMESTAMPTZ, nullable | 削除日時(論理削除) |
| deleted_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 削除ユーザー |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

制約

- `UNIQUE(created_by_id, date, master_id, time_slot, class_override) NULLS NOT DISTINCT`

インデックス

- `date`
- `master_id`
- `class_override`
- `(date, class_override)`

補足

- `history` はチェック済みのみ保持する。
- 未チェックはレコードなしで表現する。

### 5.9 Machine / `quality_machine`

機械の定義。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| machine_no | VARCHAR(64) UNIQUE NOT NULL | 機械番号 |
| machine_name | VARCHAR(255) NOT NULL | 機械名称 |
| machine_class | SMALLINT, nullable, CHECK (machine_class IS NULL OR machine_class IN (1,2,3,4,5,6,10)) | 機械分類 |
| shape_type | VARCHAR(16) NOT NULL CHECK (shape_type IN ('circle','ellipse','rectangle')) | 図形種別 |
| map_x / map_y | DOUBLE PRECISION | 位置 |
| width / height | DOUBLE PRECISION | 寸法 |
| is_active | BOOLEAN | 有効フラグ |

補足

`machine_class`の対応表

- `1`: 自動機
- `2`: 半自動機
- `3`: セッター
- `4`: プレス
- `5`: 2次加工機
- `10`: 自動機・半自動機のハイブリッド

### 5.10 MachineAssignment / `quality_machineassignment`

機械と担当コードの対応。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| machine_id | FK -> quality_machine.id ON DELETE RESTRICT | 機械 |
| code_id | FK -> quality_master.code ON DELETE RESTRICT | 対応品目コード |
| assignment_class | SMALLINT, nullable, CHECK >= 0 | Django `PositiveSmallIntegerField`; 品目のclass定義 |

制約

- `UNIQUE(machine_id, code)`
- assignment_classは、machine_classが`1`,`2` の機械に割り当てられている場合はそのまま同じ値になる。`10`の機械に割り当てられている場合は個別設定が必要。

### 5.11 Job / `quality_job`

ジョブ状態管理。現行処理はHTTP内同期であり、非同期workerは未実装。

| column | type | note |
|---|---|---|
| job_id | VARCHAR(64) PK | 文字列主キー |
| job_type | VARCHAR(64) NOT NULL CHECK (job_type IN ('master_update','plans_import','inspection_sheet_issue','daily_report_generate')) | ジョブ種別 |
| status | VARCHAR(16) NOT NULL CHECK (status IN ('queued','running','succeeded','failed')) | 状態 |
| request_payload | JSONB | 実行引数 |
| result | JSONB | 成功結果 |
| error_message | TEXT | 失敗理由 |
| started_at | TIMESTAMPTZ, nullable | 開始日時 |
| finished_at | TIMESTAMPTZ, nullable | 終了日時 |
| created_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成ユーザー |
| updated_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 更新ユーザー |
| deleted_at | TIMESTAMPTZ, nullable | 削除日時(論理削除) |
| deleted_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 削除ユーザー |
| updated_at | TIMESTAMPTZ, nullable | 更新日時 |

### 5.12 LayoutMaster / `quality_layoutmaster`

見取り図定義。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| layout_name | VARCHAR(128) UNIQUE NOT NULL | 見取り図名称 |
| background_image_path | TEXT NOT NULL DEFAULT '' | 予約列。現行APIは常に空文字として扱う |
| grid_width | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; グリッド横数 |
| grid_height | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; グリッド縦数 |
| owner_user_id | FK -> users.user_id ON DELETE RESTRICT, nullable | 作成者(所有者) |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

補足

- 背景画像は現行未実装で、保存・表示しない。
- 実際のレイアウト情報はグリッド座標で保持する。
- 現行実装はレイアウト編集を `audit_logs` へ記録していない。正式リリース要件は `RELEASE.md` の監査項目に従う。

### 5.13 LayoutObjectType / `quality_layoutobjecttype`

見取り図上の要素種別定義。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| code | VARCHAR(32) UNIQUE NOT NULL CHECK (code IN ('machine','wall','path','area','stairs','entrance')) | 要素種別コード |
| display_name | VARCHAR(64) NOT NULL | 表示名称  |
| color | VARCHAR(32) NOT NULL | 表示色 |
| image_path | TEXT NOT NULL | 空文字可。現行DBではNULL不可 |
| selectable | BOOLEAN | 選択可否 |
| created_at | TIMESTAMPTZ | 作成日時 |

補足

- MVPでは巡回導線と機械配置に必要な要素のみ扱う。
- 要素追加はマスタ追加のみで拡張可能とする。

### 5.14 LayoutObject / `quality_layoutobject`

見取り図上の配置オブジェクト。

| column | type | note |
|---|---|---|
| id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| layout_id | FK -> quality_layoutmaster.id ON DELETE RESTRICT | 見取り図 |
| object_type_id | FK -> quality_layoutobjecttype.id ON DELETE RESTRICT | 要素種別 |
| machine_id | FK -> quality_machine.id ON DELETE RESTRICT, nullable | 機械要素時のみ使用 |
| object_name | VARCHAR(255) NOT NULL | 表示名 |
| grid_x | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; グリッドX座標 |
| grid_y | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; グリッドY座標 |
| width | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; 横幅 |
| height | INTEGER NOT NULL CHECK >= 0 | Django `PositiveIntegerField`; 高さ |
| rotation | DOUBLE PRECISION | 回転角度 |
| meta_json | JSONB | 拡張情報 |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

補足

- 座標およびサイズはグリッド単位で保持する。
- `machine_id` を持つことで当日検査対象との連携を行う。
- `meta_json` は将来的な拡張情報保持に利用可能とする。

### 5.15 User / `users`

ユーザー管理（認証・権限）。全クライアントは共通のPostgreSQLアカウントで接続し、ユーザーごとの権限制御はアプリケーション側で実施する。

| column | type | note |
|---|---|---|
| user_id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| login_name | TEXT UNIQUE | ログインID |
| display_name | TEXT | 表示名 |
| avatar | VARCHAR, nullable | アバターファイル名 |
| password_hash | TEXT | Django password hasher形式（現行設定の既定はPBKDF2） |
| role | TEXT CHECK (role IN ('admin','worker')) | 権限 |
| is_active | BOOLEAN | 有効フラグ |
| last_login | TIMESTAMPTZ, nullable | 最終ログイン |
| created_at | TIMESTAMPTZ | 作成日時 |
| updated_at | TIMESTAMPTZ | 更新日時 |

補足

- 削除は論理削除（`is_active = FALSE`）とし、関連レコードの監査列参照を維持する。
- ロール: `admin` = 全機能, `worker` = 検査実施 / 履歴閲覧 / ジョブ確認 / 個人設定変更。

### 5.16 UserSetting / `user_settings`

ユーザーごとの設定。

| column | type | note |
|---|---|---|
| user_id | PK, FK -> users.user_id ON DELETE RESTRICT | ユーザー |
| theme | TEXT | カラーテーマ |
| font_size | DOUBLE PRECISION | フォントサイズ |
| browser_settings_imported | BOOLEAN | ブラウザ設定取込済み |

補足

- ユーザーごと1行。将来項目追加時は列追加または本テーブル拡張とする。

### 5.17 SystemSetting / `system_settings`

システム全体で共有する設定。変更可能なのは管理者（admin）のみ。

| column | type | note |
|---|---|---|
| setting_key | TEXT PK | 設定キー |
| setting_value | TEXT | 設定値 |
| updated_by | FK -> users.user_id ON DELETE RESTRICT, nullable | 更新者 |
| updated_at | TIMESTAMPTZ | 更新日時 |

補足

- キー値方式とし、将来の設定項目追加に備える。
- 現行 `settings/` API の読取・更新はいずれも admin のみ。

### 5.18 AuditLog / `audit_logs`

主要な操作履歴（マスタ編集 / レイアウト編集 / システム設定変更 / ユーザー管理 / データ削除）。

| column | type | note |
|---|---|---|
| log_id | PK GENERATED BY DEFAULT AS IDENTITY | 主キー |
| user_id | FK -> users.user_id ON DELETE RESTRICT | 実行ユーザー |
| operation | VARCHAR(64) | 操作種別。DB CHECKなし |
| table_name | TEXT | 対象テーブル |
| record_id | TEXT | 対象レコードID（各テーブルのPKを文字列で保持） |
| logged_at | TIMESTAMPTZ | 実行日時 |
| details_json | JSONB | 操作内容 |

補足

- 操作種別はDB CHECKを持たず文字列で保持する。
- `record_id` は複合キーや文字列IDの場合も文字列で格納する。

## 6. チェック時間帯マスタ

- `A = 08:30-10:00`
- `B = 10:10-12:00`
- `C = 12:45-14:45`
- `D = 15:00-17:15`

MVPではDBテーブル化せずアプリケーション定数として保持してよい。

## 7. `quality_inspectionsession.note`

`quality_inspectionsession` に `note text NOT NULL DEFAULT ''` 相当のフィールドを追加する（Django migration `0023_inspectionsession_note`）。ノートの所有者はセッションの `owner_user_id` であり、既存の `(owner_user_id, target_date)` 一意制約に従う。

サマリー集計は `quality_history.deleted_at IS NULL` のレコードのみ対象とする。クラスは `quality_history.class_override`、未指定の場合は `quality_masterclass` → `quality_classmaster.class_no` の順で解決し、通常クラス判定ではクラス9を除外する。
