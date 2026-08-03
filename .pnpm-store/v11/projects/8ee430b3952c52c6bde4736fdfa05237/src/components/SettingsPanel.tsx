import React, { useState, useEffect, useRef } from 'react';
import type { AppSettings, Job, ApiError, Class9Setting, MasterUpdateJobResult } from '../types';
import { Save, Upload, FolderOpen, Loader2, Database, Plus, Trash2, CheckCircle2, AlertTriangle, Play, Monitor, FileSpreadsheet, Bug } from 'lucide-react';
import { getErrorMessage } from '../utils';

interface InspectionFolderRow {
  id: number;
  path: string;
  priority: number;
}

interface MasterUpdateJobState {
  status: Job['status'];
  error_message: string | null;
  result: MasterUpdateJobResult | null;
}

const folderPathComparisonKey = (path: string) => {
  let normalized = path.trim().replace(/\//g, '\\');
  while (normalized.length > 1 && normalized.endsWith('\\') && !/^[a-zA-Z]:\\$/.test(normalized)) {
    normalized = normalized.slice(0, -1);
  }
  return normalized.toLocaleLowerCase();
};

export const SettingsPanel: React.FC = () => {
  const [csvPath, setCsvPath] = useState('');
  const [folderRows, setFolderRows] = useState<InspectionFolderRow[]>([]);
  const [erpPath, setErpPath] = useState('');
  const [historyFilePath, setHistoryFilePath] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [isErpRunning, setIsErpRunning] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [historyWriteResult] = useState<string | null>(null);
  const [erpResult, setErpResult] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<MasterUpdateJobState | null>(null);
  const pollingTimerRef = useRef<number | null>(null);
  const nextFolderRowId = useRef(1);

  // Class 9 settings
  const [class9Settings, setClass9Settings] = useState<Class9Setting[]>([]);
  const [class9Code, setClass9Code] = useState('');
  const [class9SheetPath, setClass9SheetPath] = useState('');
  const [class9SearchResults, setClass9SearchResults] = useState<{ code: string; name: string }[]>([]);
  const [isClass9Searching, setIsClass9Searching] = useState(false);
  const [isClass9Saving, setIsClass9Saving] = useState(false);
  const [class9Message, setClass9Message] = useState<string | null>(null);
  const searchTimerRef = useRef<number | null>(null);

  async function fetchSettings(): Promise<AppSettings> {
    const response = await fetch('/api/settings/');
    if (!response.ok) throw new Error('設定の取得に失敗しました');
    return await response.json();
  }

  async function fetchClass9Settings(): Promise<Class9Setting[] | null> {
    try {
      const res = await fetch('/api/class9-settings/');
      if (!res.ok) return null;
      return await res.json();
    } catch {
      return null;
    }
  }

  useEffect(() => {
    let cancelled = false;
    void fetchSettings()
      .then((data) => {
        if (cancelled) return;
        setCsvPath(data.csv_path || '');
        const paths = data.inspection_folder_paths ?? [];
        setFolderRows(paths.map((path) => ({
          id: nextFolderRowId.current++,
          path,
          priority: data.inspection_folder_priorities?.[path] ?? 0,
        })));
        setErpPath(data.erp_path || '');
        setHistoryFilePath(data.history_file_path || '');
      })
      .catch((err: unknown) => {
        if (!cancelled) setSaveMessage('エラー: ' + getErrorMessage(err, '設定の取得に失敗しました'));
      })
      .finally(() => {
        if (!cancelled) setIsLoading(false);
      });
    void fetchClass9Settings()
      .then((data) => {
        if (!cancelled && data) setClass9Settings(data);
      })
      .catch(() => {
        // Keep the existing silent handling for optional class 9 settings.
      });
    return () => {
      cancelled = true;
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  const handleClass9CodeSearch = (value: string) => {
    setClass9Code(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!value.trim()) {
      setClass9SearchResults([]);
      return;
    }
    searchTimerRef.current = window.setTimeout(async () => {
      setIsClass9Searching(true);
      try {
        const res = await fetch(`/api/masters/search/?q=${encodeURIComponent(value.trim())}`);
        if (res.ok) {
          setClass9SearchResults(await res.json());
        }
      } catch {
        // ignore
      } finally {
        setIsClass9Searching(false);
      }
    }, 300);
  };

  const handleClass9Add = async () => {
    if (!class9Code.trim()) return;
    setIsClass9Saving(true);
    setClass9Message(null);
    try {
      const res = await fetch('/api/class9-settings/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          code: class9Code.trim(),
          inspection_sheet_path: class9SheetPath.trim(),
        }),
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.message || '登録に失敗しました');
      }
      setClass9Code('');
      setClass9SheetPath('');
      setClass9SearchResults([]);
      const data = await fetchClass9Settings();
      if (data) setClass9Settings(data);
      setClass9Message('特殊検査(クラス9)を登録しました');
    } catch (err) {
      setClass9Message('エラー: ' + getErrorMessage(err, '登録に失敗しました'));
    } finally {
      setIsClass9Saving(false);
    }
  };

  const handleClass9Delete = async (id: number) => {
    try {
      const res = await fetch(`/api/class9-settings/${id}/`, { method: 'DELETE' });
      if (!res.ok) throw new Error('削除に失敗しました');
      const data = await fetchClass9Settings();
      if (data) setClass9Settings(data);
    } catch (err) {
      setClass9Message('エラー: ' + getErrorMessage(err, '削除に失敗しました'));
    }
  };

  const handleSave = async () => {
    setSaveMessage(null);
    const trimmedRows = folderRows.map((row) => ({ ...row, path: row.path.trim() }));
    if (trimmedRows.some((row) => !row.path)) {
      setSaveMessage('エラー: 空のフォルダパスは保存できません。不要な行は削除してください。');
      return;
    }
    const comparisonKeys = trimmedRows.map((row) => folderPathComparisonKey(row.path));
    if (new Set(comparisonKeys).size !== comparisonKeys.length) {
      setSaveMessage('エラー: 同じフォルダパスが複数指定されています。');
      return;
    }
    const validFolders = trimmedRows.map((row) => row.path);
    const validPriorities = Object.fromEntries(trimmedRows.map((row) => [row.path, row.priority]));
    setIsSaving(true);
    try {
      const response = await fetch('/api/settings/', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          csv_path: csvPath,
          inspection_folder_paths: validFolders,
          inspection_folder_priorities: validPriorities,
          erp_path: erpPath,
          history_file_path: historyFilePath,
        }),
      });
      if (!response.ok) {
        const error = await response.json().catch(() => null);
        const detail = error?.inspection_folder_paths?.[0] || error?.inspection_folder_priorities?.[0];
        throw new Error(detail || '保存に失敗しました');
      }
      setFolderRows(trimmedRows);
      setSaveMessage('設定を保存しました');
    } catch (err) {
      setSaveMessage('エラー: ' + getErrorMessage(err, '保存に失敗しました'));
    } finally {
      setIsSaving(false);
    }
  };

  const handleRunUpdate = async () => {
    setJobResult(null);
    setIsRunning(true);
    try {
      const response = await fetch('/api/master/update/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ force: false }),
      });
      if (!response.ok) {
        const errData: ApiError = await response.json();
        throw new Error(errData.message || '更新に失敗しました');
      }
      const { job_id } = await response.json();
      startPolling(job_id);
    } catch (err) {
      setJobResult({ status: 'failed', error_message: getErrorMessage(err, '更新に失敗しました'), result: null });
      setIsRunning(false);
    }
  };

  const startPolling = (jobId: string) => {
    if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    pollingTimerRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}/`);
        if (!response.ok) throw new Error('ジョブ状態の取得に失敗しました');
        const jobData: MasterUpdateJobState = await response.json();
        if (jobData.status === 'succeeded' || jobData.status === 'failed') {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsRunning(false);
          setJobResult(jobData);
        }
      } catch (err) {
        if (pollingTimerRef.current) {
          clearInterval(pollingTimerRef.current);
          pollingTimerRef.current = null;
        }
        setIsRunning(false);
        setJobResult({ status: 'failed', error_message: getErrorMessage(err, 'ジョブ状態の取得に失敗しました'), result: null });
      }
    }, 2500);
  };

  const handleRunErp = async () => {
    setErpResult(null);
    setIsErpRunning(true);
    try {
      const response = await fetch('/api/erp/automate/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ csv_path: csvPath, erp_path: erpPath }),
      });
      if (!response.ok) {
        const errData: ApiError = await response.json();
        throw new Error(errData.message || 'ERP自動化の実行に失敗しました');
      }
      const { job_id } = await response.json();
      startErpPolling(job_id);
    } catch (err) {
      setErpResult('エラー: ' + getErrorMessage(err, 'ERP自動化の実行に失敗しました'));
      setIsErpRunning(false);
    }
  };

  const startErpPolling = (jobId: string) => {
    const interval = setInterval(async () => {
      try {
        const res = await fetch(`/api/jobs/${jobId}/`);
        if (!res.ok) throw new Error('ジョブ状態の取得に失敗しました');
        const jobData: Job = await res.json();
        if (jobData.status === 'succeeded' || jobData.status === 'failed') {
          clearInterval(interval);
          setIsErpRunning(false);
          if (jobData.status === 'succeeded') {
            setErpResult('ERP自動化が完了しました');
          } else {
            setErpResult('エラー: ' + (jobData.error_message || 'ERP自動化に失敗しました'));
          }
        }
      } catch (err) {
        clearInterval(interval);
        setIsErpRunning(false);
        setErpResult('エラー: ' + getErrorMessage(err, 'ジョブ状態の取得に失敗しました'));
      }
    }, 2500);
  };

  const addFolderPath = () => setFolderRows((rows) => [
    ...rows,
    { id: nextFolderRowId.current++, path: '', priority: 0 },
  ]);
  const removeFolderPath = (id: number) => {
    setFolderRows((rows) => rows.filter((row) => row.id !== id));
  };

  const updateFolderRow = (id: number, updates: Partial<Pick<InspectionFolderRow, 'path' | 'priority'>>) => {
    setFolderRows((rows) => rows.map((row) => row.id === id ? { ...row, ...updates } : row));
  };

  if (isLoading) {
    return (
      <div className="loading-container">
        <div className="pulse-spinner"></div>
        <p>設定を読み込んでいます...</p>
      </div>
    );
  }

  return (
    <div className="settings-grid">
      <div className="card">
        <h2 className="card-title">
          <Database className="icon-title" size={20} />
          構成CSVファイル
        </h2>
        <div className="form-group">
          <label className="form-label">
            <FolderOpen size={14} className="label-icon" />
            CSVファイルパス
          </label>
          <input
            type="text"
            className="form-control"
            value={csvPath}
            onChange={(e) => setCsvPath(e.target.value)}
            placeholder="例: C:\path\to\master.csv または temp/master.csv"
          />
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">
          <FolderOpen className="icon-title" size={20} />
          検査書フォルダ
        </h2>
        <div className="form-group">
          <label className="form-label">フォルダパス一覧（複数指定可）</label>
          <p className="form-hint">優先順位は数値が大きいフォルダほど先に選ばれます。</p>
          <div className="folder-path-headings" aria-hidden="true">
            <span>フォルダパス</span>
            <span>優先順位</span>
            <span></span>
          </div>
          {folderRows.map((row) => (
            <div key={row.id} className="folder-path-row">
              <input
                type="text"
                className="form-control"
                value={row.path}
                onChange={(e) => updateFolderRow(row.id, { path: e.target.value })}
                placeholder="\\\\server\\share\\folder"
              />
              <input
                type="number"
                step="1"
                className="form-control folder-priority-input"
                value={row.priority}
                onChange={(e) => updateFolderRow(row.id, { priority: Number.parseInt(e.target.value, 10) || 0 })}
                aria-label={`${row.path || '新しいフォルダ'}の優先順位`}
                title="優先順位（大きい数値ほど優先）"
              />
              <button
                type="button"
                className="btn btn-secondary btn-icon-only"
                onClick={() => removeFolderPath(row.id)}
                title="削除"
              >
                <Trash2 size={16} />
              </button>
            </div>
          ))}
          <button type="button" className="btn btn-secondary" onClick={addFolderPath}>
            <Plus size={16} />
            フォルダを追加
          </button>
        </div>
      </div>

      <div className="card">
        <h2 className="card-title">
          <Monitor className="icon-title" size={20} />
          ERP自動操作
        </h2>
        <div className="form-group">
          <label className="form-label">
            <FolderOpen size={14} className="label-icon" />
            ERP実行ファイルパス
          </label>
          <input
            type="text"
            className="form-control"
            value={erpPath}
            onChange={(e) => setErpPath(e.target.value)}
            placeholder="例: C:\Program Files\ERP\erp.exe"
          />
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={handleRunErp} disabled={isErpRunning}>
            {isErpRunning ? <Loader2 size={16} className="animate-spin" /> : <Play size={16} />}
            ERP自動化を実行
          </button>
        </div>
        {erpResult && (
          <div className={`card-body-flex ${erpResult.startsWith('エラー') ? 'text-rose' : 'text-emerald'}`}>
            {erpResult.startsWith('エラー') ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
            <span>{erpResult}</span>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">
          <FileSpreadsheet className="icon-title" size={20} />
          工程内検査履歴
        </h2>
        <div className="form-group">
          <label className="form-label">
            <FolderOpen size={14} className="label-icon" />
            履歴ファイルパス
          </label>
          <input
            type="text"
            className="form-control"
            value={historyFilePath}
            onChange={(e) => setHistoryFilePath(e.target.value)}
            placeholder="例: temp/history.xlsx"
          />
        </div>
        {historyWriteResult && (
          <div className={`card-body-flex ${historyWriteResult.startsWith('エラー') ? 'text-rose' : 'text-emerald'}`}>
            {historyWriteResult.startsWith('エラー') ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
            <span>{historyWriteResult}</span>
          </div>
        )}
      </div>

      <div className="card">
        <h2 className="card-title">
          <Bug className="icon-title" size={20} />
          特殊検査(クラス9)設定
        </h2>
        <div className="form-group">
          <label className="form-label">品番検索</label>
          <input
            type="text"
            className="form-control"
            value={class9Code}
            onChange={e => handleClass9CodeSearch(e.target.value)}
            placeholder="品目コードまたは品目名で検索..."
          />
          {isClass9Searching && <div className="manual-add-loading">検索中...</div>}
          {class9SearchResults.length > 0 && (
            <ul className="class9-search-results">
              {class9SearchResults.map(r => (
                <li key={r.code} className="class9-search-item" onClick={() => { setClass9Code(r.code); setClass9SearchResults([]); }}>
                  <span className="font-mono">{r.code}</span>
                  <span className="text-muted">{r.name}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
        <div className="form-group">
          <label className="form-label">
            検査書ファイルパス (任意)
          </label>
          <input
            type="text"
            className="form-control"
            value={class9SheetPath}
            onChange={e => setClass9SheetPath(e.target.value)}
            placeholder="\\\\server\\share\\folder\\file.xlsx (省略可)"
          />
        </div>
        <div className="form-actions">
          <button type="button" className="btn btn-primary" onClick={handleClass9Add} disabled={isClass9Saving || !class9Code.trim()}>
            {isClass9Saving ? <Loader2 size={16} className="animate-spin" /> : <Plus size={16} />}
            クラス9として登録
          </button>
        </div>
        {class9Settings.length > 0 && (
          <div className="class9-list">
            <h4>登録済み ({class9Settings.length}件)</h4>
            {class9Settings.map(s => (
              <div key={s.id} className="class9-list-item">
                <div className="class9-list-info">
                  <span className="font-mono font-bold">{s.code}</span>
                  <span className="text-muted">{s.name}</span>
                  {s.inspection_sheet_path && (
                    <span className="class9-path">{s.inspection_sheet_path}</span>
                  )}
                </div>
                <button type="button" className="btn btn-danger btn-icon-only" onClick={() => handleClass9Delete(s.id)} title="削除">
                  <Trash2 size={14} />
                </button>
              </div>
            ))}
          </div>
        )}
        {class9Message && (
          <div className={`card-body-flex ${class9Message.startsWith('エラー') ? 'text-rose' : 'text-emerald'}`}>
            {class9Message.startsWith('エラー') ? <AlertTriangle size={16} /> : <CheckCircle2 size={16} />}
            <span>{class9Message}</span>
          </div>
        )}
      </div>

      <div className="settings-actions">
        <button type="button" className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
          {isSaving ? <Loader2 size={16} className="animate-spin" /> : <Save size={16} />}
          設定を保存
        </button>
        <button type="button" className="btn btn-primary" onClick={handleRunUpdate} disabled={isRunning}>
          {isRunning ? <Loader2 size={16} className="animate-spin" /> : <Upload size={16} />}
          DB更新を実行
        </button>
      </div>

      {saveMessage && (
        <div className={`card ${saveMessage.startsWith('エラー') ? 'error-card-global' : ''}`}>
          <div className="card-body-flex">
            {saveMessage.startsWith('エラー') ? (
              <AlertTriangle size={20} className="text-rose" />
            ) : (
              <CheckCircle2 size={20} className="text-emerald" />
            )}
            <span>{saveMessage}</span>
          </div>
        </div>
      )}

      {jobResult && (
        <div className="card">
          <h2 className="card-title">
            <Database className="icon-title" size={20} />
            DB更新結果
          </h2>
          {jobResult.status === 'failed' ? (
            <div className="error-alert">
              <div className="error-alert-header">
                <AlertTriangle size={16} />
                更新失敗
              </div>
              <div className="error-msg">{jobResult.error_message || jobResult.error_message}</div>
            </div>
          ) : (
            <div className="summary-metrics-grid four-columns">
              <div className="metric-box">
                <span className="metric-label">Master更新数</span>
                <span className="metric-value text-emerald">{jobResult.result?.updated_master_count ?? 0}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Class更新数</span>
                <span className="metric-value text-emerald">{jobResult.result?.updated_class_count ?? 0}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">Structure更新数</span>
                <span className="metric-value text-emerald">{jobResult.result?.updated_structure_count ?? 0}</span>
              </div>
              <div className="metric-box">
                <span className="metric-label">検査書ファイル数</span>
                <span className="metric-value text-emerald">{jobResult.result?.inspection_file_count ?? 0}</span>
              </div>
            </div>
          )}
          <div className="job-meta">
            <span>Source: <code>{jobResult.result?.source || '-'}</code></span>
            {jobResult.result?.folder_warnings && jobResult.result.folder_warnings.length > 0 && (
              <div className="warning-alert-box">
                <AlertTriangle size={16} className="warning-alert-icon" />
                <div>
                  {jobResult.result.folder_warnings.map((w: string, i: number) => (
                    <div key={i}>{w}</div>
                  ))}
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
};
