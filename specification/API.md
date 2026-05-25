# API仕様

## 1. 共通方針

- REST API形式を利用する。
- 長時間処理は非同期ジョブとして起動する。
- 日付は `YYYY-MM-DD` 形式、時刻はサーバーローカル時刻で扱う。
- エラー仕様は `ERROR.md` に従う。

## 2. 共通レスポンス

### 2.1 成功
```json
{
  "status": "success"
}
```

### 2.2 非同期ジョブ受付
```json
{
  "status": "accepted",
  "job_id": "job_20260519_001"
}
```

### 2.3 エラー
```json
{
  "status": "error",
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

少なくとも `scan_file` または `excel_file` のどちらか一方は必須。

response
```json
{
  "status": "accepted",
  "job_id": "job_20260519_003"
}
```

### 5.2 手動追加
`POST /api/inspection-targets/manual/`

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
