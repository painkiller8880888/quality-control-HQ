# API仕様

## 0. 現行 API 台帳（2026-07-15）

共通事項: `/api/` 配下。`auth/session`, `auth/login`, `auth/register` 以外はログイン必須。セッション認証の変更系リクエストには CSRF トークンが必要。`admin` 表記のないものは `admin`/`worker` 共通だが、対象日データは原則ログイン利用者の所有スコープで処理される。

| method | path | 権限 | 概要 |
|---|---|---|---|
| GET | `auth/session/` | 匿名可 | 認証状態、利用者、CSRF cookie |
| POST | `auth/login/` | 匿名可 | ログイン |
| POST | `auth/register/` | 匿名可 | worker の即時自己登録とログイン |
| POST | `auth/logout/` | login | ログアウト |
| PUT | `me/settings/` | login | 個人テーマ設定 |
| PATCH | `me/profile/` | login | 表示名、パスワード、アバター更新 |
| GET | `me/avatar/` | login | 自分のアバター取得 |
| GET | `admin/users/` | admin | 利用者一覧 |
| PATCH | `admin/users/{user_id}/` | admin | ロール、有効状態、表示名更新 |
| GET | `jobs/{job_id}/` | login | ジョブ状態取得 |
| POST | `master/update/` | admin | CSVからマスタ更新 |
| POST | `master/seed/` | admin | マスタ投入 |
| GET | `masters/search/` | login | コード・品名検索 |
| GET, PUT | `settings/` | admin | システム設定 |
| POST | `erp/automate/` | admin | ERP自動操作と更新 |
| POST | `plans/import/` | login | 計画 Excel/PDF 取込 |
| GET | `inspection-targets/` | login | 自分の日別対象取得 |
| GET, PUT | `inspection-note/` | login | 自分の日別ノート取得・保存 |
| GET | `inspection-summary/` | admin | 期間集計 |
| GET | `inspection-summary/csv/{counts|notes}/` | admin | UTF-8 BOM付きCSV |
| POST | `inspection-targets/manual/` | login | 対象手動追加 |
| POST | `inspection-targets/bulk-hide/` | login | 対象一括非表示 |
| DELETE | `inspection-targets/{id}/` | login | 自分の対象を非表示化 |
| GET | `inspection-targets/{id}/file/` | login | 検査書を開く |
| POST | `inspection-targets/{id}/print-file/` | login | 検査書を印刷 |
| POST | `history/bulk-upsert/` | login | チェック一括保存 |
| GET, PATCH | `history/` | login | 自分の履歴取得・単一更新 |
| POST | `history/write-to-file/` | login | 履歴ファイル書込 |
| GET | `factory-map/` | login | 見取り図と当日状態 |
| GET | `factory-map/layout/` | login | レイアウト取得 |
| PUT | `factory-map/layout/` | admin | レイアウト保存 |
| GET | `factory-map/layout/{id}/` | login | 指定レイアウト取得 |
| DELETE | `factory-map/layout/{id}/` | admin | 指定レイアウト削除 |
| GET | `factory-map/layouts/` | login | レイアウト一覧 |
| POST | `factory-map/layouts/` | admin | レイアウト新規作成 |
| GET | `factory-map/machines/` | login | 機械候補一覧 |
| GET, PUT | `machine-master/` | admin | 機械と割当の編集 |
| PATCH | `factory-map/object-type/{code}/` | admin | 種別色更新 |
| POST | `inspection-sheet/issue/` | login | 検査書発行 |
| POST | `daily-report/generate/` | login | 日報生成 |
| POST | `daily-report/issue/` | login | 日報印刷 |
| GET, POST | `class9-settings/` | admin | クラス9設定一覧・登録 |
| DELETE | `class9-settings/{id}/` | admin | クラス9設定削除 |
| GET | `structure/` | login | 下位構成取得 |
| GET | `structure/reverse-roots/` | login | 上位ルート取得 |
| GET | `inspection-file/open/` | login | コード指定でファイルを開く |
| GET | `inspection-file/pdf/` | login | PDF表示用データ取得 |
| POST | `inspection-file/print/` | login | コード指定で印刷 |

`settings/` の検査書フォルダ設定は、既存の `inspection_folder_paths: string[]` に加えて
`inspection_folder_priorities: { [folderPath]: integer }` を受け付ける。優先順位は数値が大きいほど高く、
未指定は `0` とする。旧形式のリクエストも引き続き利用でき、削除済みパスの優先順位は保存時に除去する。

### 0.1 実装上の注意と未決事項

- Job系APIの正式リリース要件・受入基準は `RELEASE.md` を正本とする。実装状態や実施結果はGitHubのIssue／PR／commitを参照する。
- 匿名自己登録を正式運用で許可するかは未決。`register` は現在 worker を即時作成する。
- 一部例外応答は内部ファイルパスや例外文字列を返す。また `error_response` に未定義の `status=` を渡す経路があり、異常時 TypeError の可能性がある。

## 1. 共通方針

- REST API形式を利用する。
- 長時間処理の正式リリース要件・受入基準は `RELEASE.md` を正本とする。Job IDと202応答の形式は本書の各エンドポイント定義に従う。
- 日付は `YYYY-MM-DD` 形式、時刻はサーバーローカル時刻で扱う。
- エラー仕様は `ERROR.md` に従う。

## 2. 共通レスポンス

### 2.1 成功
以下は一部APIの例であり、実際の成功レスポンスは各エンドポイント定義を正とする。
```json
{
  "status": "success"
}
```

### 2.2 同期処理完了後のジョブ応答
```json
{
  "status": "accepted",
  "job_id": "job_20260519_001"
}
```

### 2.3 エラー
```json
{
  "error_code": "UNKNOWN_CODE",
  "message": "Unknown code: X9999",
  "details": {}
}
```

## 3. ジョブAPI

### 3.1 ジョブ状態取得
`GET /api/jobs/{job_id}/`

response
```json
{
  "job_id": "job_20260519_001",
  "job_type": "plans_import",
  "status": "running",
  "started_at": "2026-05-19T09:15:00+09:00",
  "finished_at": null,
  "error_message": null
}
```

## 4. ERPマスタ更新

### 4.1 更新実行
`POST /api/master/update/`

request
```json
{
  "force": false
}
```

response
```json
{
  "status": "accepted",
  "job_id": "job_20260519_002"
}
```

### 4.2 更新完了後のジョブ結果例
```json
{
  "job_id": "job_20260519_002",
  "job_type": "master_update",
  "status": "succeeded",
  "result": {
    "updated_master_count": 1520,
    "updated_structure_count": 8421,
    "inspection_file_count": 218
  }
}
```

## 5. 作業計画取込

### 5.1 OCR・Excel取込
`POST /api/plans/import/`

`multipart/form-data`
- `target_date`
- `scan_file` 任意
- `excel_file` 任意
- `sheet_name` Excel取込時は必須

少なくとも `scan_file` または `excel_file` のどちらか一方は必須。
Excel取込では指定したシートの `F4:F103` を読み取り、品目コード候補を抽出する。
OCR取込は工程class 1〜5を優先し、工程判定不能かつマスタにclass 8が明示登録済みの場合だけclass 8として登録する。class 6/7へのフォールバックは行わない。

response
```json
{
  "status": "accepted",
  "job_id": "job_20260519_003"
}
```

### 5.2 手動追加
`POST /api/inspection-targets/manual/`

コード検索からの製品検査追加専用。サーバーがclass 6/7を確定し、`class_override`指定は拒否する。

request
```json
{
  "date": "2026-05-19",
  "codes": ["C1234", "C5678"]
}
```

response
```json
{
  "status": "success",
  "added_count": 2
}
```

### 5.2.1 見取り図追加

`POST /api/inspection-targets/factory-map/`

```json
{"date":"2026-05-19","machine_id":31,"code":"C1234"}
```

指定機械への割当を検証し、工程class 1〜5をサーバー側で確定する。見取り図ではclass 8を登録しない。

### 5.2.2 特殊検査追加

`POST /api/inspection-targets/special/`

```json
{"date":"2026-05-19","codes":["C1234"]}
```

特殊検査設定済みコードだけをclass 9として登録する。クライアントはclass番号を指定しない。

### 5.3 取込完了後のジョブ結果例
```json
{
  "job_id": "job_20260519_003",
  "job_type": "plans_import",
  "status": "succeeded",
  "result": {
    "target_date": "2026-05-19",
    "session_id": 14,
    "imported_count": 23,
    "warning_count": 2
  }
}
```

## 6. 検査対象

### 6.1 検査対象取得
`GET /api/inspection-targets/?date=2026-05-19`

response
```json
[
  {
    "target_id": 101,
    "code": "C1234",
    "name": "ホルダーAssy",
    "category": 1,
    "source_flags": {
      "ocr": true,
      "excel": true,
      "manual": false
    },
    "requires_inspection_sheet": true,
    "issue_status": "pending",
    "warnings": [],
    "checks": {
      "A": true,
      "B": false,
      "C": false,
      "D": true
    }
  }
]
```

### 6.2 検査対象削除
`DELETE /api/inspection-targets/{target_id}/`

response
```json
{
  "status": "success"
}
```

## 7. 検査チェック

### 7.1 一括保存
`POST /api/history/bulk-upsert/`

request
```json
{
  "date": "2026-05-19",
  "items": [
    { "code": "C1234", "checks": { "A": true, "B": false, "C": false, "D": true } },
    { "code": "C5678", "checks": { "A": false, "B": true, "C": false, "D": false } }
  ]
}
```

response
```json
{
  "status": "success",
  "updated_count": 2
}
```

### 7.2 単一チェック更新
`PATCH /api/history/`

request
```json
{
  "date": "2026-05-19",
  "code": "C1234",
  "time": "B",
  "checked": true
}
```

response
```json
{
  "status": "success"
}
```

### 7.3 履歴取得
`GET /api/history/?date=2026-05-19`

response
```json
[
  {
    "code": "C1234",
    "time": "A"
  },
  {
    "code": "C1234",
    "time": "D"
  }
]
```

## 8. 見取り図

### 8.1 見取り図取得
`GET /api/factory-map/?date=2026-05-19`

response
```json
{
  "image_url": "/media/maps/factory.png",
  "machines": [
    {
      "machine_id": 127,
      "machine_no": "M-127",
      "machine_name": "全自動タップ機",
      "shape_type": "ellipse",
      "x": 320,
      "y": 440,
      "width": 180,
      "height": 80,
      "status": "pending",
      "assigned_codes": ["C1234", "C5678"],
      "target_codes": ["C1234"]
    }
  ],
  "warnings": [
    {
      "code": "C8888",
      "error_code": "NO_MATCHING_MACHINE"
    }
  ]
}
```

## 9. 検査書発行

### 9.1 個別・一括発行
`POST /api/inspection-sheet/issue/`

request
```json
{
  "date": "2026-05-19",
  "codes": ["C1234", "C5678"],
  "bulk": true
}
```

response
```json
{
  "status": "accepted",
  "job_id": "job_20260519_004"
}
```

### 9.2 発行完了後のジョブ結果例
```json
{
  "job_id": "job_20260519_004",
  "job_type": "inspection_sheet_issue",
  "status": "succeeded",
  "result": {
    "issued_count": 2,
    "skipped_count": 1,
    "missing_file_count": 0
  }
}
```

## 10. 日報生成

### 10.1 日報生成
`POST /api/daily-report/generate/`

request
```json
{
  "date": "2026-05-19"
}
```

response
```json
{
  "status": "accepted",
  "job_id": "job_20260519_005"
}
```

### 10.2 生成完了後のジョブ結果例
```json
{
  "job_id": "job_20260519_005",
  "job_type": "daily_report_generate",
  "status": "succeeded",
  "result": {
    "date": "2026-05-19",
    "excel_path": "\\\\server\\reports\\2026-05-19.xlsx"
  }
}
```

## 11. 検査ノート・サマリーAPI

- `GET /api/inspection-note/?date=YYYY-MM-DD`: ログインユーザー本人のノートを取得する。セッション未作成時は空文字。
- `PUT /api/inspection-note/`: `{ "date": "YYYY-MM-DD", "note": "..." }` を本人のセッションへ保存する。セッション未作成時は作成する。
- `GET /api/inspection-summary/?start=YYYY-MM-DD&end=YYYY-MM-DD&classes=1,2,...&inspectors=1,2,unknown`: 管理者限定。月候補、クラス別合計、指定クラス・検査者の両方に一致する上位10品目、0件日を含む日別・検査者別内訳、ノートを返す。`inspectors` はユーザーIDまたは未紐付け履歴を表す `unknown` のカンマ区切りで、省略時は全検査者、空文字時は上位品目0件となる。検査者内訳とノートは同名ユーザーを区別する `user_id` を含む。期間はinclusive、最大367日。不正な検査者トークンは400を返す。
- `GET /api/inspection-summary/csv/counts/?start=...&end=...`: 管理者限定。`日付,総数,クラス1,...,クラス9` のUTF-8 BOM付きCSV。
- `GET /api/inspection-summary/csv/notes/?start=...&end=...`: 管理者限定。空ノートを除き、`日付,検査者名,ノート内容` のUTF-8 BOM付きCSV。
