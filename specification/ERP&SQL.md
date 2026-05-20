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

## 3. カテゴリ定義

- 検査対象には7カテゴリがある。
- `1`: 自動機
- `2`: 半自動機
- `3`: 手動
- `4`: プレス
- `5`: 二次加工
- `6`: 製品検査(1)
- `7`: 製品検査(2)
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
| code | UNIQUE | コード |
| name |  | 名称 |
| node_type |  | 作業種類 |
| department |  | 担当部署 |
| category |  | カテゴリ |
| updated_at |  | 最終更新日時 |

### 5.2 structure

親子構成を保持する。

| column | type | note |
|---|---|---|
| structure_id | PK | 主キー |
| root_code | INDEX | 構成ルートコード |
| parent_code | INDEX | 親コード |
| child_code | INDEX | 子コード |
| level |  | 親ノード階層 |
| quantity |  | 使用数量 |

制約

- `UNIQUE(parent_code, child_code)`

### 5.3 inspection_file

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

### 5.4 inspection_session

1営業日分の検査業務単位。

| column | type | note |
|---|---|---|
| session_id | PK | 主キー |
| target_date | UNIQUE | 対象日 |
| status |  | `open / closed` |
| created_at |  | 作成日時 |
| updated_at |  | 更新日時 |

### 5.5 inspection_target

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

### 5.6 inspection_target_warning

当日検査対象に紐づく警告。

| column | type | note |
|---|---|---|
| warning_id | PK | 主キー |
| target_id | FK -> inspection_target.target_id | 対象 |
| error_code |  | `UNKNOWN_CODE` など |
| message |  | 表示文言 |
| details_json |  | 詳細 |
| created_at |  | 作成日時 |

### 5.7 history

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

### 5.8 machines

見取り図上の機械定義。

| column | type | note |
|---|---|---|
| machine_id | PK | 主キー |
| machine_no | UNIQUE | 機械番号 |
| machine_name |  | 機械名称 |
| shape_type |  | `circle / ellipse / rectangle` |
| map_x |  | 中心X座標 |
| map_y |  | 中心Y座標 |
| width |  | 幅 |
| height |  | 高さ |
| is_active |  | bool |

補足

- MVPでは `polygon` を扱わない。

### 5.9 machine_assignments

機械と担当コードの対応。

| column | type | note |
|---|---|---|
| machine_assignment_id | PK | 主キー |
| machine_id | FK -> machines.machine_id | 機械 |
| code | FK -> master.code | 担当コード |

制約

- `UNIQUE(machine_id, code)`

### 5.10 jobs

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

## 6. チェック時間帯マスタ

- `A = 08:30-10:00`
- `B = 10:10-12:00`
- `C = 12:45-14:45`
- `D = 15:00-17:15`

MVPではDBテーブル化せずアプリケーション定数として保持してよい。
