# UI仕様書

## 0. 現行 UI・権限（2026-07-15）

- 未認証時はログイン/新規登録画面を表示する。登録すると worker として即時ログインする。
- ヘッダーはメニュードロワー、構成検索、日付、更新、取込/ジョブ、ユーザーメニューを持つ。ユーザー設定では表示名、アバター、パスワードを変更できる。
- 全利用者に「巡回ダッシュボード」を表示する。`admin` のみ「検査サマリー」「見取り図作成」「機械マスタ編集」「管理者設定」を表示する。worker が別タブ状態を持っていても dashboard に強制する。
- 巡回ダッシュボードは見取り図、対象一覧、時間帯チェック、ノート、検査書発行、日報/履歴出力を扱う。対象日は利用者ごとのセッションに対応する。
- 検査サマリーは admin 限定で、期間、クラス、検査者による集計と counts/notes CSV を提供する。
- UIの表示制御だけでなく、管理APIにも `IsAdmin` が設定される。ただし全エンドポイントについて自動RBAC回帰試験を正式リリース条件とする。

未実装: 本番向けエラー画面、オフライン/再送制御、アクセシビリティ総合試験、背景画像アップロード、長時間ジョブの非同期進捗。正式要件は `RELEASE.md` を参照。

本ドキュメントは品質管理HQアプリケーションのメインUI仕様を定義する。

---

## 1. 技術スタック

| 項目 | 採用技術 |
| --- | --- |
| フレームワーク | React 19 + TypeScript |
| ビルドツール | Vite 8 |
| スタイリング | CSS (カスタム、フレームワーク無し) |
| アイコン | lucide-react |
| フォント | Outfit (見出し)、Inter (本文)、JetBrains Mono (コード) |

### 1.1 プロジェクト構成

```
frontend/
├── src/
│   ├── App.tsx
│   ├── index.css
│   ├── types.ts
│   └── components/
│       ├── ImportForm.tsx
│       ├── ImportSummary.tsx
│       ├── WarningSummaryCard.tsx
│       ├── TargetsTable.tsx
│       ├── FactoryMapViewer.tsx
│       └── FactoryMapCreator.tsx
```

---

## 2. 画面構成

### 2.1 全体レイアウト

シングルページアプリケーション。ルーティングは追加せず、App内stateでタブを切り替える。

```
┌────────────────────────────────────────────────────────────┐
│ ヘッダー                                                     │
│ [Layers] 品質管理 HQ (Quality Control HQ)                   │
├────────────────────────────────────────────────────────────┤
│ メニュードロワー（必要時にオーバーレイ表示）                 │
├────────────────────────────────────────────────────────────┤
│ 巡回ダッシュボード ┌──────────────┬─────────────────────┐ │
│                    │ 見取り図表示  │ 警告・対象一覧       │ │
│                    └──────────────┴─────────────────────┘ │
│ 取込 / ジョブステータスはモーダル表示                       │
└────────────────────────────────────────────────────────────┘
```

### 2.2 タブ

| タブ | 内容 |
| --- | --- |
| 巡回ダッシュボード | 見取り図表示、検査対象一覧、チェック、ノート、発行 |
| 検査サマリー | admin限定の期間集計とCSV |
| 見取り図作成 | admin限定。`UI_MAP_CREATOR.md` 準拠の複数レイアウト編集UI |
| 機械マスタ編集 | admin限定の機械・割当編集 |
| 管理者設定 | admin限定の設定・ユーザー管理 |

- `activeTab` を `App` で保持する。
- タブ切替で `selectedDate`、`currentJob`、`targets` は破棄しない。

### 2.3 navigation drawer / import modal

- メニューはヘッダーボタンからオーバーレイドロワーとして開く。
- `ImportForm` と `ImportSummary` は「取込 / ジョブステータス」モーダルに表示する。
- ドロワーとモーダルは閉じても `App` が保持する対象日・対象一覧・ジョブ状態を破棄しない。

### 2.4 巡回ダッシュボード

- メイン領域は2カラム。
- 左: `FactoryMapViewer` による見取り図表示。
- 右: 対象日表示、再読込ボタン、`WarningSummaryCard`、`TargetsTable`。
- 1024px以下では縦積み表示にする。

### 2.5 見取り図作成

- 詳細仕様は `specification/UI_MAP_CREATOR.md` を正とする。
- MVPでは rectangle ベースのグリッド編集に限定する。
- polygon、自由描画、ズーム編集、回転編集、経路探索、モバイル編集UIは対象外。

---

## 3. デザインシステム

### 3.1 カラーパレット

| 役割 | 変数名 | 値 |
| --- | --- | --- |
| 背景グラデーション(開始) | `--bg-gradient-start` | `#0f172a` |
| 背景グラデーション(終了) | `--bg-gradient-end` | `#020617` |
| カード背景 | `--card-bg` | `rgba(30, 41, 59, 0.7)` |
| カード枠線 | `--card-border` | `rgba(255, 255, 255, 0.08)` |
| テキスト(1次) | `--text-primary` | `#f8fafc` |
| テキスト(2次) | `--text-secondary` | `#cbd5e1` |
| テキスト(補助) | `--text-muted` | `#64748b` |
| プライマリ | `--color-primary` | `#6366f1` |
| 成功 | `--color-success` | `#10b981` |
| 警告 | `--color-warning` | `#f59e0b` |
| 危険 | `--color-danger` | `#f43f5e` |

### 3.2 UI原則

- 既存のダークテーマ、カード、角丸、lucide-react アイコンを維持する。
- メイン左の見取り図は巡回作業者が最初に視認できる大きさにする。
- 作業計画・OCR取込・ジョブ状況は取込モーダルに集約する。
- 装飾目的のカード追加や不要な説明文は避ける。

---

## 4. コンポーネント仕様

### 4.1 ImportForm

- 作業計画・OCR取込フォーム。
- 入力項目は対象日、OCRスキャンファイル、計画Excelファイル。
- 既存のPOST `/api/plans/import/` を使用する。
- モーダルを閉じてもジョブ状態は `App` 側に残る。

### 4.2 ImportSummary

- ジョブステータス表示。
- `queued / running / succeeded / failed` を表示する。
- `succeeded` 時は取込結果メトリクス、警告統計、取込元内訳を表示する。

### 4.3 FactoryMapViewer

- 閲覧専用の見取り図表示。
- `GET /api/factory-map/?date=YYYY-MM-DD` を使用する。
- レイアウトオブジェクトをグリッド比率で配置する。
- 当日検査対象に紐づく machine は強調表示し、対象コード数をバッジ表示する。
- レイアウト未登録時は空状態を表示する。
- `NO_MATCHING_MACHINE` 警告がある場合は下部に対象コードを表示する。

### 4.4 FactoryMapCreator

- 見取り図作成タブの編集UI。
- `GET /api/factory-map/layout/` で現在レイアウトを取得する。
- `PUT /api/factory-map/layout/` でレイアウトを保存する。
- オブジェクト種別は `machine / wall / path / area / stairs / entrance`。
- 複数レイアウトの追加・選択、オブジェクトのドラッグ移動、サイズ変更、削除、保存を提供する。背景画像は未実装。

### 4.5 WarningSummaryCard / TargetsTable

- 既存の警告サマリーと検査対象一覧を維持する。
- 見取り図追加後も対象一覧の列、警告展開、チェック表示の挙動は変更しない。

---

## 5. データフローとAPI連携

### 5.1 取込フロー

```
ImportForm
  → POST /api/plans/import/
  → GET /api/jobs/{job_id}/ polling
  → succeeded
  → GET /api/inspection-targets/?date=YYYY-MM-DD
  → GET /api/factory-map/?date=YYYY-MM-DD
```

### 5.2 見取り図表示

`GET /api/factory-map/?date=YYYY-MM-DD`

主なレスポンス:

- `image_url`
- `layout`
- `layout.objects`
- `layout.object_types`
- `machines`
- `warnings`

### 5.3 見取り図保存

`GET /api/factory-map/layout/`

`PUT /api/factory-map/layout/`

- 選択中の複数レイアウトのいずれかを対象とし、`layout_id` で指定する。未指定時はデフォルトを取得する。
- 保存時はオブジェクト一覧を丸ごと置換する。
- `grid_x`, `grid_y`, `width`, `height` はグリッド単位。

---

## 6. 状態管理

| 状態 | 保持場所 | 内容 |
| --- | --- | --- |
| activeTab | App | 表示中タブ |
| isNavigationOpen | App | メニュードロワー開閉状態 |
| isImportModalOpen | App | 取込モーダル開閉状態 |
| selectedDate | App | 選択中対象日 |
| currentJob | App | 現在実行中/完了のジョブ |
| targets | App | 検査対象リスト |
| factoryMap | App | 見取り図表示データ |
| isLoadingJob | App | ジョブポーリング中 |
| isLoadingTargets | App | 検査対象取得中 |
| isLoadingFactoryMap | App | 見取り図取得中 |
| globalError | App | グローバルエラー |
| pollingTimerRef | App | ジョブポーリングタイマー |
| expandedRows | TargetsTable | 展開中の警告行 |

---

## 7. TypeScript型定義

| 型 | 用途 |
| --- | --- |
| JobStatus / Job | ジョブ状態 |
| InspectionTarget | 検査対象 |
| FactoryMapResponse | 見取り図表示APIレスポンス |
| FactoryMapMachine | 見取り図上の機械 |
| FactoryMapWarning | 見取り図連携警告 |
| FactoryMapLayout | レイアウト全体 |
| LayoutObject | レイアウト上の配置オブジェクト |
| LayoutObjectType | 配置オブジェクト種別 |

---

## 8. レスポンシブ対応

- 1024px以上: ヘッダー + dashboard workspace。ドロワーはオーバーレイ表示。
- workspaceは見取り図 / 対象一覧の2カラム。
- 1024px以下: 見取り図、対象一覧、編集UIを縦積みにする。ドロワーと取込モーダルは画面幅に合わせる。

---

## 9. MVP制限事項

以下は今回のメインUI改修では対象外。

- polygon
- 自由描画
- 見取り図ズーム編集
- 見取り図回転編集
- 最短経路探索
- リアルタイム設備状態表示
- モバイル専用編集UI
- 検査書個別/一括発行UI
- 日報生成トリガーUI

## 10. 検査サマリータブとノート

管理者ナビゲーションに検査サマリータブを表示する。1920×1080を基準に2列レイアウトとし、左列はコントロールおよびサマリー・グラフ、右列は日別詳細表とする。狭い画面では1列に並べる。

コントロールは月選択、開始日・終了日、検査回数CSV、ノートCSVを備える。上位10品目とSVG折れ線グラフには独立したクラス選択ポップオーバーを設ける。詳細表は総数とクラス1〜9を共通色で表示し、行展開で検査者別内訳を表示する。ノート通知ドットは全ノートを `検査者名: ノート` の改行区切りでツールチップ表示し、同形式でコピーする。

検査対象一覧ヘッダーの「日報」と「履歴」の間には紫色の鉛筆アイコン付き「ノート」ボタンを置き、日付別の入力ダイアログを開く。
