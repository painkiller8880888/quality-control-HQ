import React, { useState, useMemo, useEffect, useRef, useCallback } from 'react';
import type { InspectionTarget } from '../types';
import { AlertTriangle, ChevronDown, ChevronUp, FileCheck, CheckCircle2, Package, Database, ArrowUpDown, ArrowUp, ArrowDown, EyeOff, Plus, Printer, FileText, ListTree, Pencil } from 'lucide-react';
import { ManualAddModal } from './ManualAddModal';
import { SpecialAddModal } from './SpecialAddModal';
import { AssemblyStructureModal } from './AssemblyStructureModal';
import { CLASS_COLORS, CLASS_LABELS } from '../classStyles';

interface CheckUpdateItem {
  target_id: number;
  checks: Record<string, boolean>;
}

interface TargetsTableProps {
  targets: InspectionTarget[];
  highlightedTargetId: number | null;
  onTargetClick: (target: InspectionTarget) => void;
  selectedDate: string;
  onCheckUpdate: (date: string, items: CheckUpdateItem[]) => void;
  onHideTargets: (date: string, targetIds: number[]) => void;
  onIssueSheet: (date: string) => Promise<void>;
  onIssueDailyReport: (date: string) => Promise<void>;
  onWriteHistory: (date: string) => Promise<void>;
  onRefresh: () => void;
  isLoading?: boolean;
}

const getClassColor = (classNum: number | null) => {
  if (classNum === null || classNum === undefined) return { bg: '#f1f5f9', text: '#64748b' };
  return CLASS_COLORS[classNum] || { bg: '#f1f5f9', text: '#334155' };
};

export const TargetsTable: React.FC<TargetsTableProps> = ({
  targets,
  highlightedTargetId,
  onTargetClick,
  selectedDate,
  onCheckUpdate,
  onHideTargets,
  onIssueSheet,
  onIssueDailyReport,
  onWriteHistory,
  onRefresh,
  isLoading,
}) => {
  const [expandedRows, setExpandedRows] = useState<Record<number, boolean>>({});
  const [hideChecked, setHideChecked] = useState<Set<number>>(new Set());
  const [isHiding, setIsHiding] = useState(false);
  const [showManualAddModal, setShowManualAddModal] = useState(false);
  const [showSpecialAddModal, setShowSpecialAddModal] = useState(false);
  const [isIssuing, setIsIssuing] = useState(false);
  const [isIssuingDailyReport, setIsIssuingDailyReport] = useState(false);
  const [isWritingHistory, setIsWritingHistory] = useState(false);
  const [noteOpen, setNoteOpen] = useState(false);
  const [note, setNote] = useState('');
  const [noteError, setNoteError] = useState('');
  const [noteSaving, setNoteSaving] = useState(false);
  const [isPaneCollapsed, setIsPaneCollapsed] = useState(false);
  const openNote = async () => {
    setNote('');
    setNoteError('');
    try {
      const response = await fetch(`/api/inspection-note/?date=${encodeURIComponent(selectedDate)}`);
      if (!response.ok) throw new Error('ノートを取得できませんでした');
      setNote((await response.json()).note || '');
      setNoteOpen(true);
    } catch (error) {
      setNoteError(error instanceof Error ? error.message : 'ノートを取得できませんでした');
    }
  };
  const saveNote = async () => {
    setNoteSaving(true);
    setNoteError('');
    try {
      const response = await fetch('/api/inspection-note/', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ date: selectedDate, note }) });
      if (!response.ok) throw new Error('ノートを保存できませんでした');
      setNoteOpen(false);
    } catch (error) {
      setNoteError(error instanceof Error ? error.message : 'ノートを保存できませんでした');
    } finally { setNoteSaving(false); }
  };
  const observerRef = useRef<ResizeObserver | null>(null);
  const paneRef = useCallback((node: HTMLDivElement | null) => {
    if (observerRef.current) {
      observerRef.current.disconnect();
      observerRef.current = null;
    }
    if (node) {
      const observer = new ResizeObserver((entries) => {
        for (let entry of entries) {
          // Change layout if the pane width is 750px or less
          if (entry.contentRect.width <= 750) {
            setIsPaneCollapsed(true);
          } else {
            setIsPaneCollapsed(false);
          }
        }
      });
      observer.observe(node);
      observerRef.current = observer;
    }
  }, []);

  const [sortConfig, setSortConfig] = useState<{ key: keyof InspectionTarget | 'classLabel'; direction: 'asc' | 'desc' }>({ key: 'code', direction: 'asc' });

  // Drag-to-check state (A/B/C/D slots)
  const containerRef = useRef<HTMLDivElement>(null);
  interface AccumulatedData { target_id: number; checks: Record<string, boolean>; }
  const dragRef = useRef<{
    isDragging: boolean; startX: number; startY: number; slot: string;
    setChecked: boolean;
    processed: Set<string>; accumulated: Map<number, AccumulatedData>;
  }>({ isDragging: false, startX: 0, startY: 0, slot: '', setChecked: true, processed: new Set(), accumulated: new Map() });
  const [pendingChecks, setPendingChecks] = useState<Set<string>>(new Set());
  const autoScrollRafRef = useRef<number | null>(null);
  const lastMoveTimeRef = useRef(0);
  const THROTTLE_MS = 16;
  const DRAG_THRESHOLD = 5;
  const AUTO_SCROLL_MARGIN = 40;
  const AUTO_SCROLL_SPEED = 8;

  // Hide drag-select state
  const hideDragRef = useRef<{
    isDragging: boolean; startX: number; startY: number;
    direction: 'check' | 'uncheck' | null;
    processed: Set<number>;
  }>({ isDragging: false, startX: 0, startY: 0, direction: null, processed: new Set() });

  const getCheckKey = (targetId: number, slot: string) => `${targetId}:${slot}`;

  const getCellData = (el: HTMLElement | null) => {
    const cell = el?.closest('[data-check-target-id]') as HTMLElement | null;
    if (!cell) return null;
    const attr = cell.getAttribute('data-check-target-id');
    const slot = cell.getAttribute('data-check-slot');
    const targetId = attr ? parseInt(attr, 10) : null;
    if (targetId && slot) return { targetId, slot, element: cell };
    return null;
  };

  const getHideCellTargetId = (el: HTMLElement | null): number | null => {
    const cell = el?.closest('[data-hide-target-id]') as HTMLElement | null;
    if (!cell) return null;
    const id = cell.getAttribute('data-hide-target-id');
    return id ? parseInt(id, 10) : null;
  };

  const isCellChecked = (target: InspectionTarget, slot: string) =>
    !!target.checks?.[slot as keyof typeof target.checks] || pendingChecks.has(getCheckKey(target.target_id, slot));

  const processCell = useCallback((clientX: number, clientY: number) => {
    const drag = dragRef.current;
    const cellData = getCellData(document.elementFromPoint(clientX, clientY) as HTMLElement);
    if (!cellData || cellData.slot !== drag.slot) return;

    const key = getCheckKey(cellData.targetId, cellData.slot);
    if (drag.processed.has(key)) return;
    drag.processed.add(key);

    const target = targets.find(t => t.target_id === cellData.targetId);
    if (target?.checks?.[cellData.slot as keyof typeof target.checks] === drag.setChecked) return;

    const existing = drag.accumulated.get(cellData.targetId) || { target_id: cellData.targetId, checks: {} };
    existing.checks[cellData.slot] = drag.setChecked;
    drag.accumulated.set(cellData.targetId, existing);

    if (drag.setChecked) {
      setPendingChecks(prev => new Set(prev).add(key));
    } else {
      setPendingChecks(prev => { const s = new Set(prev); s.delete(key); return s; });
    }
  }, [targets]);

  const processHideCell = useCallback((clientX: number, clientY: number) => {
    const drag = hideDragRef.current;
    if (!drag.isDragging || drag.direction === null) return;

    const targetId = getHideCellTargetId(document.elementFromPoint(clientX, clientY) as HTMLElement);
    if (targetId === null) return;
    if (drag.processed.has(targetId)) return;
    drag.processed.add(targetId);

    const target = targets.find(t => t.target_id === targetId);
    if (!target) return;

    if (drag.direction === 'check') {
      setHideChecked(prev => new Set(prev).add(targetId));
    } else if (drag.direction === 'uncheck') {
      setHideChecked(prev => { const s = new Set(prev); s.delete(targetId); return s; });
    }
  }, [targets, hideChecked]);

  const lastPointerRef = useRef({ x: 0, y: 0 });

  const startAutoScroll = useCallback((speed: number) => {
    const container = containerRef.current;
    if (!container) return;
    const step = () => {
      if (autoScrollRafRef.current === null) return;
      container.scrollTop += speed;
      const { x, y } = lastPointerRef.current;
      processCell(x, y);
      processHideCell(x, y);
      autoScrollRafRef.current = requestAnimationFrame(step);
    };
    autoScrollRafRef.current = requestAnimationFrame(step);
  }, [processCell, processHideCell]);

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
      const items = Array.from(drag.accumulated.values()).map(data => ({
        target_id: data.target_id,
        checks: data.checks,
      }));
      onCheckUpdate(selectedDate, items);
    }

    drag.isDragging = false;
    drag.slot = '';
    drag.processed = new Set();
    drag.accumulated = new Map();
  }, [selectedDate, onCheckUpdate, stopAutoScroll]);

  const endHideDrag = useCallback(() => {
    const drag = hideDragRef.current;
    drag.isDragging = false;
    drag.direction = null;
    drag.processed = new Set();
    stopAutoScroll();
  }, [stopAutoScroll]);

  const handleCellPointerDown = useCallback((e: React.PointerEvent) => {
    const cellData = getCellData(e.currentTarget as HTMLElement);
    if (!cellData) return;
    e.stopPropagation();

    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    const target = targets.find(t => t.target_id === cellData.targetId);
    const isChecked = !!target?.checks?.[cellData.slot as keyof typeof target.checks];

    dragRef.current = {
      isDragging: false,
      startX: e.clientX,
      startY: e.clientY,
      slot: cellData.slot,
      setChecked: !isChecked,
      processed: new Set(),
      accumulated: new Map(),
    };
  }, [targets]);

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
      const cellData = getCellData((_e.currentTarget as HTMLElement).closest('[data-check-target-id]') as HTMLElement);
      if (cellData && selectedDate) {
        const target = targets.find(t => t.target_id === cellData.targetId);
        if (target) {
          const currentlyChecked = !!target.checks?.[cellData.slot as keyof typeof target.checks];
          const newChecked = !currentlyChecked;
          const key = getCheckKey(cellData.targetId, cellData.slot);

          if (newChecked) {
            setPendingChecks(prev => new Set(prev).add(key));
          } else {
            setPendingChecks(prev => { const s = new Set(prev); s.delete(key); return s; });
          }

          onCheckUpdate(selectedDate, [{
            target_id: target.target_id,
            checks: { [cellData.slot]: newChecked },
          }]);
        }
      }
    }

    endDrag();
  }, [endDrag, targets, selectedDate, onCheckUpdate]);

  // Hide checkbox pointer handlers
  const handleHidePointerDown = useCallback((e: React.PointerEvent) => {
    const targetId = getHideCellTargetId(e.currentTarget as HTMLElement);
    if (targetId === null) return;
    e.stopPropagation();

    (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);

    const isChecked = hideChecked.has(targetId);
    hideDragRef.current = {
      isDragging: false,
      startX: e.clientX,
      startY: e.clientY,
      direction: isChecked ? 'uncheck' : 'check',
      processed: new Set([targetId]),
    };
  }, [hideChecked]);

  const handleHidePointerMove = useCallback((e: React.PointerEvent) => {
    const drag = hideDragRef.current;
    if (!drag.isDragging && drag.direction === null) return;

    const dx = Math.abs(e.clientX - drag.startX);
    const dy = Math.abs(e.clientY - drag.startY);

    if (!drag.isDragging) {
      if (dx < DRAG_THRESHOLD && dy < DRAG_THRESHOLD) return;
      drag.isDragging = true;
      processHideCell(e.clientX, e.clientY);
      return;
    }

    lastPointerRef.current = { x: e.clientX, y: e.clientY };

    const now = performance.now();
    if (now - lastMoveTimeRef.current < THROTTLE_MS) return;
    lastMoveTimeRef.current = now;

    processHideCell(e.clientX, e.clientY);
    checkAutoScroll(e.clientX, e.clientY);
  }, [processHideCell, checkAutoScroll]);

  const handleHidePointerUp = useCallback((_e: React.PointerEvent) => {
    const drag = hideDragRef.current;
    const wasDrag = drag.isDragging;

    if (!wasDrag) {
      const targetId = getHideCellTargetId((_e.currentTarget as HTMLElement).closest('[data-hide-target-id]') as HTMLElement);
      if (targetId !== null) {
        setHideChecked(prev => {
          const s = new Set(prev);
          if (s.has(targetId)) s.delete(targetId); else s.add(targetId);
          return s;
        });
      }
    }

    endHideDrag();
  }, [endHideDrag]);

  // Window-level pointerup as backup
  useEffect(() => {
    const handleWindowUp = () => {
      if (dragRef.current.slot) endDrag();
      if (hideDragRef.current.direction !== null) endHideDrag();
    };
    window.addEventListener('pointerup', handleWindowUp);
    window.addEventListener('pointercancel', handleWindowUp);
    return () => {
      window.removeEventListener('pointerup', handleWindowUp);
      window.removeEventListener('pointercancel', handleWindowUp);
    };
  }, [endDrag, endHideDrag]);

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
        aVal = a.category ?? 9999;
        bVal = b.category ?? 9999;
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

  const handleIssueSheet = async () => {
    if (!selectedDate) return;
    setIsIssuing(true);
    try {
      await onIssueSheet(selectedDate);
    } finally {
      setIsIssuing(false);
    }
  };

  const handleIssueDailyReport = async () => {
    if (!selectedDate) return;
    setIsIssuingDailyReport(true);
    try {
      await onIssueDailyReport(selectedDate);
    } finally {
      setIsIssuingDailyReport(false);
    }
  };

  const handleWriteHistory = async () => {
    if (!selectedDate) return;
    setIsWritingHistory(true);
    try {
      await onWriteHistory(selectedDate);
    } finally {
      setIsWritingHistory(false);
    }
  };

  const handleExecuteHide = async () => {
    if (hideChecked.size === 0 || !selectedDate) return;
    setIsHiding(true);
    try {
      await onHideTargets(selectedDate, Array.from(hideChecked));
      setHideChecked(new Set());
    } finally {
      setIsHiding(false);
    }
  };

  const [printingTargetId, setPrintingTargetId] = useState<number | null>(null);
  const [structureModalCode, setStructureModalCode] = useState<string | null>(null);

  const handleOpenFile = useCallback(async (targetId: number) => {
    const popup = window.open('', '_blank');
    if (!popup) {
      alert('Unable to open a new tab. Check the browser popup settings.');
      return;
    }
    try {
    const res = await fetch(`/api/inspection-targets/${targetId}/file/`);
    const contentType = res.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
      const data = await res.json();
      if (data.status !== 'success') {
        alert('ファイルを開けませんでした');
      }
      popup.close();
    } else if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      popup.location.href = url;
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    } else {
      popup.close();
    }
    } catch {
      popup.close();
      alert('Unable to open the inspection file.');
    }
  }, []);

  const handlePrintFile = useCallback(async (targetId: number) => {
    setPrintingTargetId(targetId);
    try {
      const res = await fetch(`/api/inspection-targets/${targetId}/print-file/`, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
      });
      if (!res.ok) {
        const err = await res.json();
        alert(err.message || '印刷に失敗しました');
      }
    } catch {
      alert('印刷リクエストに失敗しました');
    } finally {
      setPrintingTargetId(null);
    }
  }, []);

  if (targets.length === 0) {
    if (isLoading) {
      return (
        <div className="loading-container">
          <div className="pulse-spinner"></div>
          <p>検査対象データを読み込んでいます...</p>
        </div>
      );
    }
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
    <div className="card table-card" ref={paneRef}>
      <div className="table-card-header">
        <h2 className="card-title">
          <FileCheck className="icon-title" size={20} />
           検査対象一覧
        </h2>
        <div className={`table-card-actions ${isPaneCollapsed ? 'collapsed' : ''}`}>
          {hideChecked.size > 0 && (
            <span className="hide-count-label">{hideChecked.size}件選択中</span>
          )}
          <button
            className="btn btn-primary btn-sm"
            onClick={() => setShowManualAddModal(true)}
          >
            <Plus size={18} />
            <span>追加</span>
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={() => setShowSpecialAddModal(true)}
          >
            <Plus size={18} />
            <span>特殊追加</span>
          </button>
          <button
            className="btn btn-issue btn-sm"
            onClick={handleIssueSheet}
            disabled={isIssuing}
          >
            <Printer size={18} />
            <span>{isIssuing ? '印刷中...' : '検査書'}</span>
          </button>
          <button
            className="btn btn-report btn-sm"
            onClick={handleIssueDailyReport}
            disabled={isIssuingDailyReport}
          >
            <FileText size={18} />
            <span>{isIssuingDailyReport ? '発行中...' : '日報'}</span>
          </button>
          <button className="btn btn-note btn-sm" onClick={() => void openNote()}>
            <Pencil size={18} /><span>ノート</span>
          </button>
          {noteError && !noteOpen && <span className="note-error" role="alert">{noteError}</span>}
          <button
            className="btn btn-outline btn-sm"
            onClick={handleWriteHistory}
            disabled={isWritingHistory}
          >
            <Database size={18} />
            <span>{isWritingHistory ? '記入中...' : '履歴'}</span>
          </button>
          <button
            className="btn btn-danger btn-sm"
            onClick={handleExecuteHide}
            disabled={hideChecked.size === 0 || isHiding}
          >
            <EyeOff size={18} />
            <span>{isHiding ? '非表示中...' : '非表示'}</span>
          </button>
        </div>
        {showManualAddModal && selectedDate && (
          <ManualAddModal
            selectedDate={selectedDate}
            onClose={() => setShowManualAddModal(false)}
            onAdded={onRefresh}
          />
        )}
        {showSpecialAddModal && selectedDate && (
          <SpecialAddModal
            selectedDate={selectedDate}
            onClose={() => setShowSpecialAddModal(false)}
            onAdded={onRefresh}
          />
        )}
        {noteOpen && (
          <div className="modal-overlay" onClick={() => setNoteOpen(false)}>
            <section className="card modal-content note-modal" role="dialog" aria-modal="true" aria-labelledby="note-title" onClick={event => event.stopPropagation()}>
              <div className="modal-header"><h3 id="note-title"><Pencil size={18} />{selectedDate} のノート</h3></div>
              <textarea autoFocus rows={8} value={note} onChange={event => setNote(event.target.value)} placeholder="当日の検査の感想・気づいたこと" />
              {noteError && <p className="auth-error" role="alert">{noteError}</p>}
              <div className="modal-actions"><button className="btn" onClick={() => setNoteOpen(false)}>キャンセル</button><button className="btn btn-primary" disabled={noteSaving} onClick={() => void saveNote()}>{noteSaving ? '保存中...' : '決定'}</button></div>
            </section>
          </div>
        )}
        {structureModalCode && (
          <AssemblyStructureModal
            code={structureModalCode}
            name={targets.find(t => t.code === structureModalCode)?.name ?? ''}
            onClose={() => setStructureModalCode(null)}
          />
        )}
      </div>
      <div className="table-responsive" ref={containerRef}>
        <table className={`targets-table ${isPaneCollapsed ? 'collapsed' : ''}`}>
          <thead>
            <tr>
              <th style={{ width: '40px' }}></th>
              {renderSortableTh('code', '品目コード')}
              {renderSortableTh('name', '品目名')}
              {renderSortableTh('classLabel', isPaneCollapsed ? '検査' : '検査分類')}
              <th>検査書</th>
              <th className="text-center" style={{ width: '48px' }}>A</th>
              <th className="text-center" style={{ width: '48px' }}>B</th>
              <th className="text-center" style={{ width: '48px' }}>C</th>
              <th className="text-center" style={{ width: '48px' }}>D</th>
              <th className="text-center" style={{ width: '48px' }}>非表示</th>
            </tr>
          </thead>
          <tbody>
            {sortedTargets.map((target) => {
              const hasWarnings = target.warnings && target.warnings.length > 0;
              const isExpanded = !!expandedRows[target.target_id];
              const isHighlighted = target.target_id === highlightedTargetId;
              const isHideChecked = hideChecked.has(target.target_id);
              const classNum = target.category;
              const classLabel = target.class_name ?? getClassLabel(classNum);
              const displayClassLabel = isPaneCollapsed ? classLabel.slice(0, 2) : classLabel;
              const classColor = getClassColor(classNum);

              return (
                <React.Fragment key={target.target_id}>
                  <tr
                    id={`target-row-${target.target_id}`}
                    className={`target-row ${hasWarnings ? 'row-has-warning' : ''} ${
                      isExpanded ? 'row-expanded' : ''
                    } ${isHighlighted ? 'row-highlight' : ''}`}
                    onClick={() => onTargetClick(target)}
                    onMouseDown={(e) => e.preventDefault()}
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
                      <span
                        style={{
                          display: 'inline-block',
                          padding: '2px 8px',
                          borderRadius: '9999px',
                          fontSize: '12px',
                          fontWeight: 600,
                          backgroundColor: classColor.bg,
                          color: classColor.text,
                        }}
                      >
                        {displayClassLabel}
                      </span>
                    </td>
                    <td>
                      {target.requires_inspection_sheet ? (
                        <span className="sheet-required text-emerald">要</span>
                      ) : (
                        <span className="sheet-not-required text-muted">不要</span>
                      )}
                    </td>
                    <td className="text-center check-cell"
                      data-check-target-id={target.target_id}
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
                      data-check-target-id={target.target_id}
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
                      data-check-target-id={target.target_id}
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
                      data-check-target-id={target.target_id}
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
                    <td className="text-center hide-check-cell"
                      data-hide-target-id={target.target_id}
                      onPointerDown={handleHidePointerDown}
                      onPointerMove={handleHidePointerMove}
                      onPointerUp={handleHidePointerUp}
                      onPointerCancel={handleHidePointerUp}
                      onClick={(e) => e.stopPropagation()}>
                      <span className={`hide-checkbox ${isHideChecked ? 'checked' : ''}`}>
                        {isHideChecked ? '✓' : ''}
                      </span>
                    </td>
                  </tr>

                  <tr className="target-detail-row">
                    <td colSpan={10}>
                      <div className={`target-detail-container ${isExpanded ? 'expanded' : ''}`}>
                        <div className="target-detail-inline">
                          <div className="target-detail-badges">
                            <span className="gh-badge gh-badge-category">
                              <span className="gh-badge-label"><Package size={12} />商品カテゴリ</span>
                              <span className="gh-badge-value"><span className="category-flag">{target.product_category ?? '-'}</span></span>
                            </span>
                            <span className="gh-badge gh-badge-source">
                              <span className="gh-badge-label"><Database size={12} />取込元</span>
                              <span className="gh-badge-value">{getSourceFlags(target)}</span>
                            </span>
                            {hasWarnings && (
                              <span
                                className="gh-badge gh-badge-warning warning-detail-trigger"
                                onClick={(e) => e.stopPropagation()}
                              >
                                <span className="gh-badge-label"><AlertTriangle size={12} className="text-rose" />警告</span>
                                <span className="gh-badge-value">{target.warnings.length}件</span>
                              </span>
                            )}
                          </div>
                          <div className={`target-detail-actions ${isPaneCollapsed ? 'collapsed' : ''}`}>
                            {target.has_inspection_file && (
                              <>
                                <button
                                  className="btn btn-outline btn-sm"
                                  onClick={(e) => { e.stopPropagation(); handleOpenFile(target.target_id); }}
                                >
                                  <FileText size={14} />
                                  <span>検査書</span>
                                </button>
                                <button
                                  className="btn btn-outline btn-sm"
                                  disabled={printingTargetId === target.target_id}
                                  onClick={(e) => { e.stopPropagation(); handlePrintFile(target.target_id); }}
                                >
                                  <Printer size={14} />
                                  <span>{printingTargetId === target.target_id ? '印刷中...' : '印刷'}</span>
                                </button>
                              </>
                            )}
                            <button
                              className="btn btn-outline btn-sm"
                              onClick={(e) => {
                                e.stopPropagation();
                                setStructureModalCode(target.code);
                              }}
                            >
                              <ListTree size={14} />
                              <span>構成</span>
                            </button>
                          </div>
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
