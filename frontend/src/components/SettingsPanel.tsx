import React, { useState, useEffect, useRef } from 'react';
import type { AppSettings, Job, ApiError } from '../types';
import { Save, Upload, FolderOpen, Loader2, Database, Plus, Trash2, CheckCircle2, AlertTriangle, Type } from 'lucide-react';

interface SettingsPanelProps {
  fontSize: number;
  onFontSizeChange: (size: number) => void;
}

export const SettingsPanel: React.FC<SettingsPanelProps> = ({ fontSize, onFontSizeChange }) => {
  const [csvPath, setCsvPath] = useState('');
  const [folderPaths, setFolderPaths] = useState<string[]>(['']);
  const [isLoading, setIsLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);
  const [isRunning, setIsRunning] = useState(false);
  const [saveMessage, setSaveMessage] = useState<string | null>(null);
  const [jobResult, setJobResult] = useState<any>(null);
  const pollingTimerRef = useRef<any>(null);

  useEffect(() => {
    fetchSettings();
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  const fetchSettings = async () => {
    setIsLoading(true);
    try {
      const response = await fetch('/api/settings/');
      if (!response.ok) throw new Error('設定の取得に失敗しました');
      const data: AppSettings = await response.json();
      setCsvPath(data.csv_path || '');
      setFolderPaths(data.inspection_folder_paths?.length ? data.inspection_folder_paths : ['']);
    } catch (err: any) {
      setSaveMessage('エラー: ' + err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const handleSave = async () => {
    setIsSaving(true);
    setSaveMessage(null);
    const validFolders = folderPaths.filter((p) => p.trim() !== '');
    try {
      const response = await fetch('/api/settings/', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          csv_path: csvPath,
          inspection_folder_paths: validFolders,
        }),
      });
      if (!response.ok) throw new Error('保存に失敗しました');
      setSaveMessage('設定を保存しました');
    } catch (err: any) {
      setSaveMessage('エラー: ' + err.message);
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
    } catch (err: any) {
      setJobResult({ status: 'failed', error_message: err.message });
      setIsRunning(false);
    }
  };

  const startPolling = (jobId: string) => {
    if (pollingTimerRef.current) clearInterval(pollingTimerRef.current);
    pollingTimerRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}/`);
        if (!response.ok) throw new Error('ジョブ状態の取得に失敗しました');
        const jobData: Job = await response.json();
        if (jobData.status === 'succeeded' || jobData.status === 'failed') {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsRunning(false);
          setJobResult(jobData);
        }
      } catch (err: any) {
        if (pollingTimerRef.current) {
          clearInterval(pollingTimerRef.current);
          pollingTimerRef.current = null;
        }
        setIsRunning(false);
        setJobResult({ status: 'failed', error_message: err.message });
      }
    }, 2500);
  };

  const addFolderPath = () => setFolderPaths([...folderPaths, '']);
  const removeFolderPath = (index: number) => {
    const updated = folderPaths.filter((_, i) => i !== index);
    setFolderPaths(updated.length ? updated : ['']);
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
          {folderPaths.map((path, index) => (
            <div key={index} className="folder-path-row">
              <input
                type="text"
                className="form-control"
                value={path}
                onChange={(e) => {
                  const updated = [...folderPaths];
                  updated[index] = e.target.value;
                  setFolderPaths(updated);
                }}
                placeholder="\\\\server\\share\\folder"
              />
              <button
                type="button"
                className="btn btn-secondary btn-icon-only"
                onClick={() => removeFolderPath(index)}
                disabled={folderPaths.length <= 1}
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
          <Type className="icon-title" size={20} />
          表示設定
        </h2>
        <div className="form-group">
          <label className="form-label">
            フォントサイズ ({fontSize}px)
          </label>
          <div style={{ display: 'flex', alignItems: 'center', gap: 12 }}>
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>小</span>
            <input
              type="range"
              min="13"
              max="22"
              step="0.5"
              value={fontSize}
              onChange={(e) => onFontSizeChange(parseFloat(e.target.value))}
              style={{ flex: 1, accentColor: 'var(--color-primary)' }}
            />
            <span style={{ fontSize: 13, color: 'var(--text-muted)' }}>大</span>
          </div>
        </div>
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
