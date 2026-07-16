# エラーハンドリング

## 0. 現行実装と正式リリース要件（2026-07-15）

現行APIは概ね `{ "error_code": string, "message": string, "details": object }` を返すが、DRF標準の `detail` やフィールド別エラーも併存する。認証は 401、権限不足は 403、競合は 409、未検出は 404 を使用する。

| priority | 不足・リスク | 受入基準 |
|---|---|---|
| Critical | `error_response` に `status=` を渡す経路で TypeError の可能性 | 全異常系テストで意図したHTTP statusとJSONが返り、500/TypeErrorにならない |
| Critical | 例外文字列・内部ファイルパスのクライアント返却 | 5xx応答に内部パス、スタック、認証情報を含めず、相関IDのみ返す |
| High | エラースキーマが統一されていない | 認証/serializer/業務例外を含め、公開スキーマを文書化して契約テストを通す |
| High | 本番ログ、監視、health check がない | 構造化ログ、相関ID、死活/依存先監視、通知先が検証済み |
| High | ERP/Excel/印刷の失敗時再実行・排他が不明確 | 多重実行を防ぎ、失敗後に安全に再実行でき、結果を監査できる |

利用者向け文言と運用ログは分離する。ログへのパスワード、セッションID、個人情報、ファイル内容の記録は禁止する。

## 1. 共通エラースキーマ
`error_response` を使う業務エラーは以下の形式で返す。DRF標準の認証エラー、`detail`、serializerのフィールド別エラーは現状この形式に統一されていない。

```json
{
  "error_code": "UNKNOWN_CODE",
  "message": "Unknown code: X9999",
  "details": {}
}
```

補足
- 発生したエラーはサーバーログに保存する。
- 同期実行中に作成される Job の失敗も同じ `error_code` を内部的に保持する。真の非同期ジョブは未実装。

## 2. エラーコード一覧

### 2.1 入力・取込系
- `UNKNOWN_CODE`
  マスタ未登録コードが入力またはOCR/Excel取込から検出された。
- `MATCH_FAILED`
  OCR処理でコード認識に失敗した。
- `INVALID_REQUEST`
  必須パラメータ不足、型不正、日付不正など。
- `DUPLICATE_TARGET`
  同一日の同一コードが重複登録された。

### 2.2 ERP更新系
- `ERP_AUTOMATION_FAILED`
  ERP自動操作そのものに失敗した。

`CIRCULAR_REFERENCE` と `MASTER_REFRESH_ABORTED` は現行コードから返されない。staging検証や循環参照検証を将来実装する場合の候補コードであり、現行エラー一覧には含めない。

### 2.3 検査書発行系
- `FILE_NOT_FOUND`
  対応する検査書ファイルが存在しない。
- `INSPECTION_SHEET_ISSUE_FAILED`
  Excelマクロ実行に失敗した。

### 2.4 日報出力系
- `FILE_IN_USE`
  出力先ファイルが使用中で更新できない。
- `DAILY_REPORT_GENERATE_FAILED`
  日報生成処理に失敗した。

### 2.5 見取り図系
- `NO_MATCHING_MACHINE`
  対応機械が未登録である。

### 2.6 ジョブ系
- `JOB_FAILED`
  ジョブが失敗状態で終了した。

現行の `GET /api/jobs/{job_id}/` は、本人が作成した該当Jobがない場合に `get_object_or_404` によるHTTP 404とDRF標準の `{ "detail": "..." }` 応答を返す。`JOB_NOT_FOUND` はエラースキーマ統一を将来実装する場合の候補コードであり、現行コード一覧には含めない。

## 3. 取り込み時の扱い

### 3.1 コード重複
- 同一セッション内で同じコードが複数回現れても、`inspection_target` には1件のみ保持する。
- 取込元フラグは統合する。

### 3.2 未登録コード
- `UNKNOWN_CODE` は無視せず、当日対象候補として `inspection_target` に残してよい。
- ただし `master_id` は `null` とし、警告を紐づける。
- UIでは警告表示し、必要なら後で手修正できるようにする。

### 3.3 OCR失敗
- `MATCH_FAILED` は対象として登録しない。
- ログには残し、ジョブ結果に件数を含める。

## 4. ERP更新失敗時の扱い
- 循環参照や検証エラーが1件でもある場合、当該更新全体を本番反映しない。
- 既存本番データは保持する。
- UIには更新失敗として返す。

## 5. 検査書発行失敗時の扱い
- `FILE_NOT_FOUND` の対象は `issue_status = missing_file` とする。
- 一括発行全体は継続し、他コードの処理を止めない。
- 個別発行では当該コードのみ失敗として返す。

## 6. 日報生成失敗時の扱い
- 日報Excelの生成に失敗しても、保存済みの検査チェック履歴は巻き戻さない。
- 再実行で復旧可能とする。

## 7. 見取り図警告の扱い
- `NO_MATCHING_MACHINE` は致命エラーではなく警告として扱う。
- 対象コード自体は検査対象一覧に残す。

## 8. UI表示方針
- 致命エラーはトーストまたはダイアログで表示する。
- 業務継続可能なものは警告一覧として表示する。
- ジョブ失敗時は対象ジョブと原因コードを明示する。

## 9. 登録経路別分類

- `CLASS_1_2_CONFLICT`（409）: class 1と2の機械設定が同時に存在する。
- `CLASS_6_7_CONFLICT`（409）: 製品検査(1)と(2)の両方に検査書が存在する。
- `PROCESS_CLASS_NOT_FOUND`（400）: 見取り図で工程class 1〜5を判定できない、またはOCRで工程class 1〜5を判定できず明示class 8も存在しない。
- `PRODUCT_INSPECTION_FILE_NOT_FOUND`（400）: Excel／コード追加用の製品検査書がない。
- `CLASS_9_SETTING_NOT_FOUND`（400）: 特殊検査設定がない。
- `INVALID_REGISTRATION_ROUTE`（400）: サーバー内部で未定義の登録経路が指定された。
- `TARGET_NOT_FOUND`（400）: 履歴更新対象が本人の当日対象として存在しない。
- `AMBIGUOUS_INSPECTION_FILE`（400）: 確定クラスに対応する検査書候補が複数ある。

公開レスポンスには内部ファイルのフルパスを含めない。

## 10. 検査サマリー関連

- `INVALID_DATE`: ノートAPIの日付がISO日付として不正。
- `INVALID_PERIOD`: `start` / `end` が不正、開始が終了より後、または期間が367日を超える。
- `INVALID_CLASSES`: `classes` がカンマ区切り整数でない。
- `INVALID_INSPECTORS`: `inspectors` がユーザーIDまたは `unknown` のカンマ区切りとして不正。
- `INVALID_CSV_TYPE`: CSV種別が `counts` / `notes` 以外。
- 管理者限定APIへ作業者がアクセスした場合はHTTP 403を返す。
