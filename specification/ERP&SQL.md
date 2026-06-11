# ERPとSQLのテーブル構造

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

- `1`: 自動機。`1`: DBの`machine_assignment`テーブルにおいて、`machine_class`が`1`の機械に割り当てられたコード。また、`自動機検査書フォルダ1`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\★自動機(工程内検査))にファイルが存在するコード。
- `2`: 半自動機。`2`: DBの`machine_assignment`テーブルにおいて、`machine_class`が`2`の機械に割り当てられたコード。また、`自動機検査書フォルダ2`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\自動機\にファイルが存在し、かつ`自動機検査書フォルダ1`にファイルが存在しないコード。
- `3`: セッター。`セッターフォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\セッター\にファイルが存在するコード。
- `4`: プレス。DBの`master`において、`node_type_1`が`プレス`のコード。
- `5`: 二次加工。DBの`master`において、`node_type_1`が`加工`となって、かつ`department`が`製造管理部`または`生残技術部`のコード。
- `6`: 製品検査(1)。`製品検査(1)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (1)にファイルが存在するコード。
- `7`: 製品検査(2)。`製品検査(2)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (2)にファイルが存在するコード。
- `8`: 手動。上記のいずれにも該当しないコード。
- 検査書発行対象は `1` と `6` と `7` のみ。

## 4. データモデル方針

- ERP由来マスタと、日次業務データは分離する。
- 当日検査対象は `inspection_session` と `inspection_target` に保存する。
- 検査実績は `history` に保存する。
- 警告は `inspection_target_warning` に保存する。

## 5. テーブル定義

### 5.1 master

ERP由来の品目マスタ。

| column | type | note |
|---|---|---|
| master_id | PK | 主キー |
| code | UNIQUE | コード, ERPデータにおける10列目 |
| name |  | 名称, ERPデータにおける11列目 |
| node_type_1 |  | 作業種類1, PRODUCT.md参照 |
| node_type_2 |  | 作業種類2, PRODUCT.md参照 |
| category |  | 商品カテゴリ, PRODUCT.md参照 |
| department |  | 担当部署, ERPデータにおける17列目 |
| updated_at |  | 最終更新日時 |

### 5.2 class

コードのクラスを定義する。

| column | type | note |
|---|---|---|
| class_id | PK | 主キー |
| master_id | FK -> master.master_id | 対応品目 |
| class |  | `1 / 2 / 3 / 4 / 5 / 6 / 7 / 8`, PRODUCT.md参照 |
| updated_at |  | 最終更新日時 |

### 5.3 structure

親子構成を保持する。

| column | type | note |
|---|---|---|
| structure_id | PK | 主キー |
| root_code | INDEX | 構成ルートコード, ERPデータにおける2列目 |
| parent_code | INDEX | 親コード, ERPデータにおける9列目 |
| child_code | INDEX | 子コード, ERPデータにおける10列目 |
| level |  | 親ノード階層, ERPデータにおける12列目 |
| quantity |  | 使用数量, ERPデータにおける19列目 |

制約

- `UNIQUE(parent_code, child_code)`

### 5.4 inspection_file

検査書ファイル索引。既存文書の探索結果を保持する。

| column | type | note |
|---|---|---|
| inspection_file_id | PK | 主キー |
| master_id | FK -> master.master_id | 対応品目 |
| file_name |  | ファイル名 |
| file_path |  | フルパス |
| discovered_at |  | 探索日時 |

補足

- 検査書ファイル名には必ずコードを含む前提とする。
- フォルダ走査時にコード一致したファイルのみ登録する。
- ファイル名には複数のコードが記入されている場合がある。
- 走査フォルダ一覧
-- `自動機検査書フォルダ1`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\★自動機(工程内検査)
-- `自動機検査書フォルダ2`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\自動機\
-- `セッターフォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\巡回検査\セッター\
-- `製品検査(1)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (1)
-- `製品検査(2)フォルダ`\\192.168.1.210\@isk\★部門\④製造管理部\★品質保証\改正検査書\改正検査書\工程内検査\★new\製品検査 (2)

### 5.5 inspection_session

1営業日分の検査業務単位。

| column | type | note |
|---|---|---|
| session_id | PK | 主キー |
| target_date | UNIQUE | 対象日 |
| status |  | `open / closed` |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

### 5.6 inspection_target

当日検査対象のスナップショット。

| column | type | note |
|---|---|---|
| target_id | PK | 主キー |
| session_id | FK -> inspection_session.session_id | 対象日 |
| master_id | FK -> master.master_id, nullable | 未登録コード時はnull可 |
| raw_code |  | 取込元コード文字列 |
| normalized_code |  | 正規化後コード |
| source_ocr |  | bool |
| source_excel |  | bool |
| source_manual |  | bool |
| requires_inspection_sheet |  | bool |
| issue_status |  | `not_required / pending / issued / missing_file / skipped` |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

制約

- `UNIQUE(session_id, normalized_code)`

### 5.7 inspection_target_warning

当日検査対象に紐づく警告。

| column | type | note |
|---|---|---|
| warning_id | PK | 主キー |
| target_id | FK -> inspection_target.target_id | 対象 |
| error_code |  | `UNKNOWN_CODE` など |
| message |  | 表示文言 |
| details_json |  | 詳細 |
| created_at |  | 作成日時 |

### 5.8 history

検査済み時間帯の履歴。

| column | type | note |
|---|---|---|
| history_id | PK | 主キー |
| date |  | 日付 |
| master_id | FK -> master.master_id | 対象品目 |
| time_slot |  | `A / B / C / D` |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

制約

- `UNIQUE(date, master_id, time_slot)`

補足

- `history` はチェック済みのみ保持する。
- 未チェックはレコードなしで表現する。

### 5.9 machines

機械の定義。

| column | type | note |
|---|---|---|
| machine_id | PK | 主キー |
| machine_no | UNIQUE | 機械番号 |
| machine_name |  | 機械名称 |
| machine_category |  | 品目カテゴリ |
| machine_class |  | `1`, `2`, `3`, `4`, `5` |
| is_active |  | bool |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |


### 5.10 machine_assignments

機械と担当コードの対応。

| column | type | note |
|---|---|---|
| machine_assignment_id | PK | 主キー |
| machine_id | FK -> machines.machine_id | 機械 |
| master_id | FK -> master.master_id | 対応品目 |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

制約

- `UNIQUE(machine_id, code)`

### 5.11 jobs

非同期ジョブ管理。

| column | type | note |
|---|---|---|
| job_id | PK | 文字列可 |
| job_type |  | `master_update / plans_import / inspection_sheet_issue / daily_report_generate` |
| status |  | `queued / running / succeeded / failed` |
| request_payload_json |  | 実行引数 |
| result_json |  | 成功結果 |
| error_message |  | 失敗理由 |
| started_at |  | 開始日時 |
| finished_at |  | 終了日時 |

### 5.12 layout_master

見取り図定義。

| column | type | note |
|---|---|---|
| layout_id  | PK | 主キー |
| layout_name | UNIQUE | 見取り図名称 |
| background_image_path |  | 背景画像パス, nullable |
| grid_width |  | グリッド横数 |
| grid_height |  | グリッド縦数 |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

補足

- 背景画像は位置合わせ用の補助表示として利用する。
- 実際のレイアウト情報はグリッド座標で保持する。

### 5.13 layout_object_type

見取り図上の要素種別定義。

| column | type | note |
|---|---|---|
| object_type_id | PK | 主キー |
| code | UNIQUE | `machine / wall / path / area / stairs / entrance` |
| display_name |  | 表示名称  |
| color |  | 表示色 |
| image_path |  | 表示画像パス, nullable |
| selectable |  | bool |
| created_at |  | 作成日時 |

補足

- MVPでは巡回導線と機械配置に必要な要素のみ扱う。
- 要素追加はマスタ追加のみで拡張可能とする。

### 5.14 layout_object

見取り図上の配置オブジェクト。

| column | type | note |
|---|---|---|
| layout_object_id | PK | 主キー |
| layout_id | FK -> layout_master.layout_id | 見取り図 |
| object_type_id | FK -> layout_object_type.object_type_id | 要素種別 |
| machine_id | FK -> machines.machine_id, nullable | 機械要素時のみ使用 |
| object_name |  | 表示名 |
| grid_x |  | グリッドX座標 |
| grid_y |  | グリッドY座標 |
| width |  | 横幅 |
| height |  | 高さ |
| rotation |  | 回転角度 |
| meta_json |  | 拡張情報 |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

補足

- 座標およびサイズはグリッド単位で保持する。
- `machine_id` を持つことで当日検査対象との連携を行う。
- `meta_json` は将来的な拡張情報保持に利用可能とする。

## 6. チェック時間帯マスタ

- `A = 08:30-10:00`
- `B = 10:10-12:00`
- `C = 12:45-14:45`
- `D = 15:00-17:15`

MVPではDBテーブル化せずアプリケーション定数として保持してよい。
