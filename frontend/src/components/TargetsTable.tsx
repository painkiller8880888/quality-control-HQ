import React, { useState } from 'react';
import type { InspectionTarget } from '../types';
import { AlertTriangle, ChevronDown, ChevronUp, FileCheck, CheckCircle2 } from 'lucide-react';

interface TargetsTableProps {
  targets: InspectionTarget[];
}

export const TargetsTable: React.FC<TargetsTableProps> = ({ targets }) => {
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({});

  const toggleRow = (targetId: number) => {
    setExpandedRows((prev) => ({
      ...prev,
      [targetId]: !prev[targetId],
    }));
  };

  const getJapaneseErrorLabel = (code: string) => {
    const labels: Record<string, string> = {
      UNKNOWN_CODE: '未登録コード',
      DUPLICATE_TARGET: '重複対象',
      MATCH_FAILED: 'OCR読取失敗',
    };
    return labels[code] || code;
  };

  const getIssueStatusBadge = (status: string) => {
    const statusMap: Record<string, { text: string; className: string }> = {
      not_required: { text: '発行不要', className: 'status-not-required' },
      pending: { text: '未発行', className: 'status-pending' },
      issued: { text: '発行済', className: 'status-issued' },
      missing_file: { text: 'ファイル未発見', className: 'status-missing-file' },
      skipped: { text: 'スキップ', className: 'status-skipped' },
    };

    const config = statusMap[status] || { text: status, className: 'status-unknown' };
    return <span className={`badge ${config.className}`}>{config.text}</span>;
  };

  if (targets.length === 0) {
    return (
      <div className="card empty-card">
        <p className="empty-text">検査対象がありません。対象日を指定して取込を行ってください。</p>
      </div>
    );
  }

  return (
    <div className="card table-card">
      <h2 className="card-title">
        <FileCheck className="icon-title" size={20} />
        検査対象一覧 (全 {targets.length} 件)
      </h2>
      <div className="table-responsive">
        <table className="targets-table">
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              <th>品目コード</th>
              <th>品目名</th>
              <th>カテゴリ</th>
              <th>取込元</th>
              <th>検査書</th>
              <th>発行状態</th>
              <th className="text-center">A</th>
              <th className="text-center">B</th>
              <th className="text-center">C</th>
              <th className="text-center">D</th>
              <th className="text-center">警告</th>
            </tr>
          </thead>
          <tbody>
            {targets.map((target) => {
              const hasWarnings = target.warnings && target.warnings.length > 0;
              const isExpanded = !!expandedRows[target.target_id];

              return (
                <React.Fragment key={target.target_id}>
                  <tr
                    className={`target-row ${hasWarnings ? 'row-has-warning' : ''} ${
                      isExpanded ? 'row-expanded' : ''
                    }`}
                    onClick={() => hasWarnings && toggleRow(target.target_id)}
                    style={{ cursor: hasWarnings ? 'pointer' : 'default' }}
                  >
                    <td>
                      {hasWarnings ? (
                        isExpanded ? (
                          <ChevronUp size={16} className="text-muted" />
                        ) : (
                          <ChevronDown size={16} className="text-muted" />
                        )
                      ) : null}
                    </td>
                    <td>
                      <span className="font-mono font-bold">{target.code}</span>
                    </td>
                    <td>
                      <span className="target-name">{target.name}</span>
                    </td>
                    <td>
                      <span className="text-muted">{target.category ?? '-'}</span>
                    </td>
                    <td>
                      <div className="source-flags-container">
                        {target.source_flags?.ocr && <span className="source-flag ocr-flag">OCR</span>}
                        {target.source_flags?.excel && <span className="source-flag excel-flag">Excel</span>}
                        {target.source_flags?.manual && <span className="source-flag manual-flag">手動</span>}
                        {!target.source_flags?.ocr && !target.source_flags?.excel && !target.source_flags?.manual && (
                          <span className="text-muted">-</span>
                        )}
                      </div>
                    </td>
                    <td>
                      {target.requires_inspection_sheet ? (
                        <span className="sheet-required text-emerald">要</span>
                      ) : (
                        <span className="sheet-not-required text-muted">不要</span>
                      )}
                    </td>
                    <td>{getIssueStatusBadge(target.issue_status)}</td>
                    <td className="text-center">
                      {target.checks?.A ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center">
                      {target.checks?.B ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center">
                      {target.checks?.C ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center">
                      {target.checks?.D ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center">
                      {hasWarnings ? (
                        <span className="warning-count-badge">
                          <AlertTriangle size={12} />
                          {target.warnings.length}
                        </span>
                      ) : (
                        <span className="text-emerald font-bold">-</span>
                      )}
                    </td>
                  </tr>

                  {hasWarnings && isExpanded && (
                    <tr className="warning-details-row">
                      <td colSpan={12}>
                        <div className="warning-details-container">
                          <h4 className="warning-details-title">
                            <AlertTriangle size={14} className="text-rose" />
                            警告詳細 ({target.warnings.length}件)
                          </h4>
                          <ul className="warning-details-list">
                            {target.warnings.map((warn, i) => (
                              <li key={i} className="warning-detail-item">
                                <div className="warning-detail-header">
                                  <span className="badge warning-type-label-badge">
                                    {getJapaneseErrorLabel(warn.error_code)}
                                  </span>
                                  <code className="warning-code-raw">{warn.error_code}</code>
                                </div>
                                <p className="warning-message-text">{warn.message}</p>
                                {warn.details && Object.keys(warn.details).length > 0 && (
                                  <div className="warning-json-details">
                                    <strong>詳細データ:</strong>
                                    <pre>{JSON.stringify(warn.details, null, 2)}</pre>
                                  </div>
                                )}
                              </li>
                            ))}
                          </ul>
                        </div>
                      </td>
                    </tr>
                  )}
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
