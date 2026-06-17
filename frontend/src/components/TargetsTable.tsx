import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import type { InspectionTarget } from '../types';
import { AlertTriangle, ChevronDown, ChevronUp, FileCheck, CheckCircle2, Package, Database, ArrowUpDown, ArrowUp, ArrowDown } from 'lucide-react';

interface TargetsTableProps {
  targets: InspectionTarget[];
  highlightedTargetId: number | null;
  onTargetClick: (target: InspectionTarget) => void;
  selectedDate: string;
  onCheckUpdate: (date: string, items: { code: string; checks: Record<string, boolean> }[]) => void;
}

// const CHECK_SLOTS = ['A', 'B', 'C', 'D'] as const;

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
  selectedDate,
  onCheckUpdate,
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

  // Drag-to-check state
  const containerRef = useRef<HTMLDivElement>(null);
  const dragRef = useRef<{
    isDragging: boolean; startX: number; startY: number; slot: string;
    processed: Set<string>; accumulated: Map<string, Record<string, boolean>>;
  }>({ isDragging: false, startX: 0, startY: 0, slot: '', processed: new Set(), accumulated: new Map() });
  const [pendingChecks, setPendingChecks] = useState<Set<string>>(new Set());
  const autoScrollRafRef = useRef<number | null>(null);
  const lastMoveTimeRef = useRef(0);
  const THROTTLE_MS = 16;
  const DRAG_THRESHOLD = 5;
  const AUTO_SCROLL_MARGIN = 40;
  const AUTO_SCROLL_SPEED = 8;

  const getCheckKey = (code: string, slot: string) => `${code}:${slot}`;

  const getCellData = (el: HTMLElement | null) => {
    const cell = el?.closest('[data-check-code]') as HTMLElement | null;
    if (!cell) return null;
    const code = cell.getAttribute('data-check-code');
    const slot = cell.getAttribute('data-check-slot');
    if (code && slot) return { code, slot, element: cell };
    return null;
  };

  const isCellChecked = (target: InspectionTarget, slot: string) =>
    !!target.checks?.[slot as keyof typeof target.checks] || pendingChecks.has(getCheckKey(target.code, slot));

  const processCell = useCallback((clientX: number, clientY: number) => {
    const drag = dragRef.current;
    const cellData = getCellData(document.elementFromPoint(clientX, clientY) as HTMLElement);
    if (!cellData || cellData.slot !== drag.slot) return;

    const key = getCheckKey(cellData.code, cellData.slot);
    if (drag.processed.has(key)) return;
    drag.processed.add(key);

    const target = targets.find(t => t.code === cellData.code);
    if (target?.checks?.[cellData.slot as keyof typeof target.checks]) return;

    const existing = drag.accumulated.get(cellData.code) || {};
    existing[cellData.slot] = true;
    drag.accumulated.set(cellData.code, existing);

    setPendingChecks(prev => new Set(prev).add(key));
  }, [targets]);

  const lastPointerRef = useRef({ x: 0, y: 0 });

  const startAutoScroll = useCallback((speed: number) => {
    const container = containerRef.current;
    if (!container) return;
    const step = () => {
      if (autoScrollRafRef.current === null) return;
      container.scrollTop += speed;
      processCell(lastPointerRef.current.x, lastPointerRef.current.y);
      autoScrollRafRef.current = requestAnimationFrame(step);
    };
    autoScrollRafRef.current = requestAnimationFrame(step);
  }, [processCell]);

  const stopAutoScroll = useCallback(() => {
    if (autoScrollRafRef.current !== null) {
      cancelAnimationFrame(autoScrollRafRef.current);
      autoScrollRafRef.current = null;
    }
  }, []);

  const checkAutoScroll = useCallback((_clientX: number, clientY: number) => {
    const container = containerRef.current;
    if (!container) return;
    const rect = container.getBoundingClientRect();

    if (clientY - rect.top < AUTO_SCROLL_MARGIN && container.scrollTop > 0) {
      if (autoScrollRafRef.current === null) startAutoScroll(-AUTO_SCROLL_SPEED);
    } else if (rect.bottom - clientY < AUTO_SCROLL_MARGIN && container.scrollTop < container.scrollHeight - rect.height) {
      if (autoScrollRafRef.current === null) startAutoScroll(AUTO_SCROLL_SPEED);
    } else {
      stopAutoScroll();
    }
  }, [startAutoScroll, stopAutoScroll]);

  const endDrag = useCallback(() => {
    const drag = dragRef.current;
    if (!drag.slot) return;

    stopAutoScroll();

    if (drag.accumulated.size > 0 && selectedDate) {
      const items = Array.from(drag.accumulated.entries()).map(([code, checks]) => ({ code, checks }));
      onCheckUpdate(selectedDate, items);
    }

    drag.isDragging = false;
    drag.slot = '';
    drag.processed = new Set();
    drag.accumulated = new Map();
  }, [selectedDate, onCheckUpdate, stopAutoScroll]);

  const handleCellPointerDown = useCallback((e: React.PointerEvent) => {
    const cellData = getCellData(e.currentTarget as HTMLElement);
    if (!cellData) return;
    e.stopPropagation();

    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    dragRef.current = {
      isDragging: false,
      startX: e.clientX,
      startY: e.clientY,
      slot: cellData.slot,
      processed: new Set(),
      accumulated: new Map(),
    };
  }, []);

  const handleCellPointerMove = useCallback((e: React.PointerEvent) => {
    const drag = dragRef.current;
    if (!drag.slot) return;

    const dx = Math.abs(e.clientX - drag.startX);
    const dy = Math.abs(e.clientY - drag.startY);

    if (!drag.isDragging) {
      if (dx < DRAG_THRESHOLD && dy < DRAG_THRESHOLD) return;
      drag.isDragging = true;
      processCell(e.clientX, e.clientY);
      return;
    }

    lastPointerRef.current = { x: e.clientX, y: e.clientY };

    const now = performance.now();
    if (now - lastMoveTimeRef.current < THROTTLE_MS) return;
    lastMoveTimeRef.current = now;

    processCell(e.clientX, e.clientY);
    checkAutoScroll(e.clientX, e.clientY);
  }, [processCell, checkAutoScroll]);

  const handleCellPointerUp = useCallback((_e: React.PointerEvent) => {
    const drag = dragRef.current;
    const wasDrag = drag.isDragging;

    if (!wasDrag) {
      // Click (no drag) — toggle
      const cellData = getCellData((_e.currentTarget as HTMLElement).closest('[data-check-code]') as HTMLElement);
      if (cellData && selectedDate) {
        const target = targets.find(t => t.code === cellData.code);
        if (target) {
          const currentlyChecked = !!target.checks?.[cellData.slot as keyof typeof target.checks];
          const newChecked = !currentlyChecked;
          const key = getCheckKey(cellData.code, cellData.slot);

          if (newChecked) {
            setPendingChecks(prev => new Set(prev).add(key));
          } else {
            setPendingChecks(prev => { const s = new Set(prev); s.delete(key); return s; });
          }

          onCheckUpdate(selectedDate, [{ code: cellData.code, checks: { [cellData.slot]: newChecked } }]);
        }
      }
    }

    endDrag();
  }, [endDrag, targets, selectedDate, onCheckUpdate]);

  // Window-level pointerup as backup
  useEffect(() => {
    const handleWindowUp = () => {
      if (dragRef.current.slot) endDrag();
    };
    window.addEventListener('pointerup', handleWindowUp);
    window.addEventListener('pointercancel', handleWindowUp);
    return () => {
      window.removeEventListener('pointerup', handleWindowUp);
      window.removeEventListener('pointercancel', handleWindowUp);
    };
  }, [endDrag]);

  // Cleanup auto-scroll on unmount
  useEffect(() => { return () => stopAutoScroll(); }, [stopAutoScroll]);

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
      <div className="table-responsive" ref={containerRef}>
        <table className="targets-table">
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              {renderSortableTh('code', '品目コード')}
              {renderSortableTh('name', '品目名')}
              {renderSortableTh('classLabel', '検査分類')}
              <th>検査書</th>
              <th className="text-center" style={{ width: '48px' }}>A</th>
              <th className="text-center" style={{ width: '48px' }}>B</th>
              <th className="text-center" style={{ width: '48px' }}>C</th>
              <th className="text-center" style={{ width: '48px' }}>D</th>
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
                    <td className="text-center check-cell"
                      data-check-code={target.code}
                      data-check-slot="A"
                      onPointerDown={handleCellPointerDown}
                      onPointerMove={handleCellPointerMove}
                      onPointerUp={handleCellPointerUp}
                      onPointerCancel={handleCellPointerUp}>
                      {isCellChecked(target, 'A') ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center check-cell"
                      data-check-code={target.code}
                      data-check-slot="B"
                      onPointerDown={handleCellPointerDown}
                      onPointerMove={handleCellPointerMove}
                      onPointerUp={handleCellPointerUp}
                      onPointerCancel={handleCellPointerUp}>
                      {isCellChecked(target, 'B') ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center check-cell"
                      data-check-code={target.code}
                      data-check-slot="C"
                      onPointerDown={handleCellPointerDown}
                      onPointerMove={handleCellPointerMove}
                      onPointerUp={handleCellPointerUp}
                      onPointerCancel={handleCellPointerUp}>
                      {isCellChecked(target, 'C') ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                    <td className="text-center check-cell"
                      data-check-code={target.code}
                      data-check-slot="D"
                      onPointerDown={handleCellPointerDown}
                      onPointerMove={handleCellPointerMove}
                      onPointerUp={handleCellPointerUp}
                      onPointerCancel={handleCellPointerUp}>
                      {isCellChecked(target, 'D') ? (
                        <CheckCircle2 size={16} className="text-emerald" />
                      ) : (
                        <span className="check-dot-unchecked"></span>
                      )}
                    </td>
                  </tr>

                  <tr className="target-detail-row">
                    <td colSpan={9}>
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
