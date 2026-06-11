import React, { useState, useMemo, useEffect } from 'react';
import type { InspectionTarget } from '../types';
import { AlertTriangle, ChevronDown, ChevronUp, FileCheck, CheckCircle2, Package, Database, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

interface TargetsTableProps {
  targets: InspectionTarget[];
  highlightedTargetId: number | null;
  onTargetClick: (target: InspectionTarget) => void;
}

const CLASS_LABELS: Record<number, string> = {
  1: '自動機',
  2: '半自動機',
  3: 'セッター',
  4: 'プレス',
  5: '二次加工',
  6: '製品検査(1)',
  7: '製品検査(2)',
  8: '手動',
};

export const TargetsTable: React.FC<TargetsTableProps> = ({
  targets,
  highlightedTargetId,
  onTargetClick,
}) => {
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({});

  useEffect(() => {
    if (highlightedTargetId === null) return;
    const el = document.getElementById(`target-row-${highlightedTargetId}`);
    if (el) {
      el.scrollIntoView({
        behavior: 'smooth',
        block: 'center',
      });
    }
  }, [highlightedTargetId]);
  const [sortConfig, setSortConfig] = useState<{ key: keyof InspectionTarget | 'classLabel'; direction: 'asc' | 'desc' }>({ key: 'code', direction: 'asc' });

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

  const getClassLabel = (classNum: number | null): string => {
    if (classNum === null || classNum === undefined) return '-';
    return CLASS_LABELS[classNum] || `クラス${classNum}`;
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

  const getSourceFlags = (target: InspectionTarget) => {
    const flags: React.ReactNode[] = [];
    if (target.source_flags?.ocr) flags.push(<span key="ocr" className="source-flag ocr-flag">OCR</span>);
    if (target.source_flags?.excel) flags.push(<span key="excel" className="source-flag excel-flag">Excel</span>);
    if (target.source_flags?.manual) flags.push(<span key="manual" className="source-flag manual-flag">手動</span>);
    if (flags.length === 0) flags.push(<span key="none" className="text-muted">-</span>);
    return flags;
  };

  const handleSort = (key: keyof InspectionTarget | 'classLabel') => {
    setSortConfig((prev) => ({
      key,
      direction: prev.key === key && prev.direction === 'asc' ? 'desc' : 'asc',
    }));
  };

  const sortedTargets = useMemo(() => {
    return [...targets].sort((a, b) => {
      let aVal: string | number;
      let bVal: string | number;

      if (sortConfig.key === 'classLabel') {
        aVal = getClassLabel(a.class);
        bVal = getClassLabel(b.class);
      } else {
        const key = sortConfig.key;
        const aRaw = a[key];
        const bRaw = b[key];
        aVal = (typeof aRaw === 'string' || typeof aRaw === 'number') ? aRaw : String(aRaw ?? '');
        bVal = (typeof bRaw === 'string' || typeof bRaw === 'number') ? bRaw : String(bRaw ?? '');
      }

      if (aVal === null || aVal === undefined) aVal = '';
      if (bVal === null || bVal === undefined) bVal = '';

      if (typeof aVal === 'string' && typeof bVal === 'string') {
        aVal = aVal.toLowerCase();
        bVal = bVal.toLowerCase();
      }

      if (aVal < bVal) return sortConfig.direction === 'asc' ? -1 : 1;
      if (aVal > bVal) return sortConfig.direction === 'asc' ? 1 : -1;
      return 0;
    });
  }, [targets, sortConfig]);

  if (targets.length === 0) {
    return (
      <div className="card empty-card">
        <p className="empty-text">検査対象がありません。対象日を指定して取込を行ってください。</p>
      </div>
    );
  }

  const renderSortIcon = (key: keyof InspectionTarget | 'classLabel') => {
    if (sortConfig.key !== key) return <ArrowUpDown size={14} className="text-muted sort-icon" />;
    return sortConfig.direction === 'asc' ? <ArrowUp size={14} className="text-primary sort-icon" /> : <ArrowDown size={14} className="text-primary sort-icon" />;
  };

  const renderSortableTh = (key: keyof InspectionTarget | 'classLabel', label: string) => (
    <th onClick={() => handleSort(key)} style={{ cursor: 'pointer', userSelect: 'none', whiteSpace: 'nowrap' }}>
      <div className="sortable-th-content">
        <span>{label}</span>
        {renderSortIcon(key)}
      </div>
    </th>
  );

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
              {renderSortableTh('code', '品目コード')}
              {renderSortableTh('name', '品目名')}
              {renderSortableTh('classLabel', '検査分類')}
              <th>検査書</th>
              {renderSortableTh('issue_status', '発行状態')}
              <th className="text-center">A</th>
              <th className="text-center">B</th>
              <th className="text-center">C</th>
              <th className="text-center">D</th>
            </tr>
          </thead>
          <tbody>
            {sortedTargets.map((target) => {
              const hasWarnings = target.warnings && target.warnings.length > 0;
              const isExpanded = !!expandedRows[target.target_id];
              const isHighlighted = target.target_id === highlightedTargetId;

              return (
                <React.Fragment key={target.target_id}>
                  <tr
                    id={`target-row-${target.target_id}`}
                    className={`target-row ${hasWarnings ? 'row-has-warning' : ''} ${
                      isExpanded ? 'row-expanded' : ''
                    } ${isHighlighted ? 'row-highlight' : ''}`}
                    onClick={() => onTargetClick(target)}
                    style={{ cursor: 'pointer' }}
                  >
                    <td onClick={(e) => { e.stopPropagation(); toggleRow(target.target_id); }}>
                      {isExpanded ? (
                        <ChevronUp size={16} className="text-muted" />
                      ) : (
                        <ChevronDown size={16} className="text-muted" />
                      )}
                    </td>
                    <td>
                      <span className="font-mono font-bold">{target.code}</span>
                    </td>
                    <td>
                      <span className="target-name">{target.name}</span>
                    </td>
                    <td>
                      <span className="text-muted">{getClassLabel(target.class)}</span>
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
                  </tr>

                  <tr className="target-detail-row">
                    <td colSpan={10}>
                      <div className={`target-detail-container ${isExpanded ? 'expanded' : ''}`}>
                        <div className="target-detail-grid">
                          <div className="target-detail-item">
                            <div className="target-detail-label">
                              <Package size={14} />
                              商品カテゴリ
                            </div>
                            <div className="target-detail-value">
                              {target.product_category ?? '-'}
                            </div>
                          </div>
                          <div className="target-detail-item">
                            <div className="target-detail-label">
                              <Database size={14} />
                              取込元
                            </div>
                            <div className="target-detail-value">
                              <div className="source-flags-container">
                                {getSourceFlags(target)}
                              </div>
                            </div>
                          </div>
                          {hasWarnings && (
                            <div className="target-detail-item warning-detail-trigger">
                              <div className="target-detail-label">
                                <AlertTriangle size={14} className="text-rose" />
                                警告 ({target.warnings.length}件)
                              </div>
                              <div className="target-detail-value">
                                <span className="warning-count-badge">
                                  <AlertTriangle size={12} />
                                  {target.warnings.length}件 - クリックで展開
                                </span>
                              </div>
                            </div>
                          )}
                        </div>

                        {hasWarnings && isExpanded && (
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
                        )}
                      </div>
                    </td>
                  </tr>
                </React.Fragment>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
};
