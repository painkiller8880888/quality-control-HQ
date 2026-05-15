- エラーレスポンス
以下形式で標準化
{
  "status": "error",
  "error_code": "INVALID_CODE",
  "message": "Unknown product code: X9999"
}

1. ERPマスタ更新API
POST /api/master/update/
ERP自動操作を実行し、CSVをDBへ取り込む。

request
{
  "force": false
}

response
{
  "status": "success",
  "updated_master_count": 1520,
  "updated_structure_count": 8421,
  "inspection_file_count": 218
}

2. OCR取込API
POST /api/plans/import/
スキャンPDFとExcelを解析し、当日検査対象を生成。

multipart/form-data

scan_file: plan.pdf
excel_file: production.xlsx

response
{
  "target_date": "2025-09-21",
  "codes": [
    "C1234",
    "C5678",
    "A1122"
  ],
  "warnings": [
    "UNKNOWN CODE: X9999"
  ]
}

3. 検査対象取得API
GET /api/inspection-targets/?date=2025-09-21

response
[
  {
    "code": "C1234",
    "name": "ホルダーAssy",
    "category": 1,
    "requires_inspection_sheet": true,
    "checks": {
      "A": true,
      "B": false,
      "C": false,
      "D": true
    }
  }
]

4. 検査チェック更新API
PATCH /api/history/

request
{
  "date": "2025-09-21",
  "code": "C1234",
  "time": "B",
  "checked": true
}

response
{
  "status": "success"
}

5. 見取り図取得API
GET /api/factory-map/
React側がSVG描画に使用。

response
{
  "image_url": "/media/maps/factory.png",
  "machines": [
    {
      "machine_id": 127,
      "machine_name": "全自動タップ機",
      "shape_type": "ellipse",
      "x": 320,
      "y": 440,
      "width": 180,
      "height": 80,
      "status": "pending",
      "codes": [
        "C1234",
        "C5678"
      ]
    }
  ]
}

6. 検査書発行API
POST /api/inspection-sheet/issue/

request
{
  "codes": [
    "C1234",
    "C5678"
  ],
  "bulk": true
}

response
{
  "status": "success",
  "issued_count": 2,
  "skipped_count": 1
}

7. 日報発行API
POST /api/daily-report/generate/

request
{
  "date": "2025-09-21"
}
]
response
{
  "status": "success",
  "excel_path": "\\\\server\\reports\\2025-09-21.xlsx"
}

8. 検査履歴取得API
GET /api/history/?date=2025-09-21

response
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

