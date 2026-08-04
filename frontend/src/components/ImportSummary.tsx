import React from 'react';
import type { Job } from '../types';
import { AlertCircle, CheckCircle, Clock, Database } from 'lucide-react';

interface ImportSummaryProps {
  job: Job | null;
}

export const ImportSummary: React.FC<ImportSummaryProps> = ({ job }) => {
  if (!job) return null;
  const errorDetails = job.result?.details;

  const getStatusBadge = (status: Job['status']) => {
    switch (status) {
      case 'queued':
        return <span className="status-badge queued"><Clock size={14} /> キュー待機中</span>;
      case 'running':
        return <span className="status-badge running"><div className="pulse-dot"></div> 実行中</span>;
      case 'succeeded':
        return <span className="status-badge succeeded"><CheckCircle size={14} /> 完了</span>;
      case 'failed':
        return <span className="status-badge failed"><AlertCircle size={14} /> 失敗</span>;
      default:
        return <span className="status-badge unknown">{status}</span>;
    }
  };

  const getJapaneseErrorLabel = (code: string) => {
    const labels: Record<string, string> = {
      UNKNOWN_CODE: '未登録コード',
      DUPLICATE_TARGET: '重複対象',
      MATCH_FAILED: 'OCR読取失敗',
    };
    return labels[code] || code;
  };

  return (
    <div className={`card summary-card status-${job.status}`}>
      <div className="summary-header">
        <h2 className="card-title">
          <Database className="icon-title" size={20} />
          ジョブステータス
        </h2>
        <div>{getStatusBadge(job.status)}</div>
      </div>

      <div className="job-meta">
        <div><strong>ジョブID:</strong> <code>{job.job_id}</code></div>
        {job.started_at && (
          <div><strong>開始時刻:</strong> {new Date(job.started_at).toLocaleString('ja-JP')}</div>
        )}
        {(job.attempt_count || 0) > 0 && <div><strong>試行回数:</strong> {job.attempt_count}</div>}
        {job.blocked_reason && <div><strong>待機理由:</strong> {job.blocked_reason}</div>}
      </div>

      {job.status === 'failed' && job.error_message && (
        <div className="error-alert">
          <div className="error-alert-header">
            <AlertCircle size={18} />
            <h4>ジョブエラーが発生しました</h4>
          </div>
          <p className="error-msg">{job.result?.error_message || job.error_message}</p>
          {errorDetails && (
            <dl className="error-details">
              {errorDetails.code && <><dt>品番</dt><dd>{errorDetails.code}</dd></>}
              {errorDetails.class !== undefined && <><dt>クラス</dt><dd>{errorDetails.class}</dd></>}
              {errorDetails.detected_classes && errorDetails.detected_classes.length > 0 && (
                <><dt>競合クラス</dt><dd>{errorDetails.detected_classes.join(' / ')}</dd></>
              )}
              {errorDetails.candidate_count !== undefined && <><dt>候補数</dt><dd>{errorDetails.candidate_count}件</dd></>}
              {errorDetails.candidate_file_names && errorDetails.candidate_file_names.length > 0 && (
                <><dt>検査書候補</dt><dd>{errorDetails.candidate_file_names.join(', ')}</dd></>
              )}
              {errorDetails.machine_numbers && errorDetails.machine_numbers.length > 0 && (
                <><dt>機械番号</dt><dd>{errorDetails.machine_numbers.join(', ')}</dd></>
              )}
            </dl>
          )}
        </div>
      )}

      {(job.status === 'queued' || job.status === 'running') && (
        <div className="loading-summary-body">
          <div className="loading-bar-container">
            <div className="loading-bar-fill animate-loading"></div>
          </div>
          <p className="loading-text">データを処理しています。しばらくお待ちください...</p>
        </div>
      )}

      {job.status === 'succeeded' && job.result && (
        <div className="summary-body">
          {job.result.missing_plan_file && (
            <div className="warning-alert-box">
              <AlertCircle size={18} className="warning-alert-icon" />
              <div>
                <strong>警告:</strong> 計画ファイルが見つかりません。マスタが不足している可能性があります。
              </div>
            </div>
          )}

          <div className="summary-metrics-grid">
            <div className="metric-box">
              <span className="metric-label">取込済件数</span>
              <span className="metric-value text-emerald">{job.result.imported_count}</span>
            </div>
            <div className="metric-box">
              <span className="metric-label">警告件数</span>
              <span className={`metric-value ${job.result.warning_count > 0 ? 'text-amber' : 'text-gray'}`}>
                {job.result.warning_count}
              </span>
            </div>
          </div>

          {Object.keys(job.result.warning_summary || {}).length > 0 && (
            <div className="warning-summary-details">
              <h3>ジョブ内警告統計</h3>
              <div className="warning-summary-badges">
                {Object.entries(job.result.warning_summary).map(([code, count]) => (
                  <div key={code} className="warning-summary-badge">
                    <span className="warning-badge-label">{getJapaneseErrorLabel(code)}</span>
                    <span className="warning-badge-count">{count} 件</span>
                  </div>
                ))}
              </div>
            </div>
          )}

          <div className="sources-section">
            <h3>取込元ごとの内訳</h3>
            <div className="sources-grid">
              {job.result.sources?.map((src, index) => (
                <div key={index} className="source-card">
                  <div className="source-card-header">
                    <span className="source-name">{src.source.toUpperCase()}</span>
                    {src.mode && <span className="source-mode-badge">{src.mode}</span>}
                  </div>
                  <div className="source-stats">
                    <div className="stat-row">
                      <span>読み込み件数:</span>
                      <strong>{src.read_count}</strong>
                    </div>
                    <div className="stat-row">
                      <span>追加件数:</span>
                      <strong>{src.added_count}</strong>
                    </div>
                    <div className="stat-row">
                      <span>重複排除件数:</span>
                      <strong>{src.duplicate_count}</strong>
                    </div>
                    {src.match_failed_count !== undefined && src.match_failed_count > 0 && (
                      <div className="stat-row text-rose">
                        <span>読取失敗件数:</span>
                        <strong>{src.match_failed_count}</strong>
                      </div>
                    )}
                    {src.page_count !== undefined && (
                      <div className="stat-row text-muted">
                        <span>ページ数:</span>
                        <strong>{src.page_count}</strong>
                      </div>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
