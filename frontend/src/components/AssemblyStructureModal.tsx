import React, { useState, useEffect, useCallback, useMemo } from 'react';
import { createPortal } from 'react-dom';
import { X, ChevronRight, ChevronDown, Crown, Folder, FileText, Package, Maximize2, Minimize2, Printer } from 'lucide-react';

interface StructureEdge {
  parent_code: string;
  child_code: string;
  parent_name: string;
  child_name: string;
  parent_department: string;
  parent_node_type_1: string;
  parent_node_type_2: string;
  parent_has_inspection_file: boolean;
  child_department: string;
  child_node_type_1: string;
  child_node_type_2: string;
  child_has_inspection_file: boolean;
  level: number;
  quantity: number | null;
}

interface StructureData {
  root_code: string;
  root_name: string;
  root_department: string;
  root_node_type_1: string;
  root_node_type_2: string;
  root_has_inspection_file: boolean;
  edges: StructureEdge[];
}

interface NodeMeta {
  department: string;
  node_type_1: string;
  node_type_2: string;
  has_inspection_file: boolean;
}

interface TreeNode {
  code: string;
  name: string;
  level: number;
  children: TreeNode[];
  quantity: number | null;
  meta: NodeMeta;
}

interface AssemblyStructureModalProps {
  code: string;
  name: string;
  onClose: () => void;
}

const GROUP_COLORS = ['var(--ast-group-0)', 'var(--ast-group-1)', 'var(--ast-group-2)'];

function buildTree(data: StructureData): TreeNode | null {
  const childrenOf = new Map<string, Array<{ child_code: string; quantity: number | null }>>();
  const nameMap = new Map<string, string>();
  const metaMap = new Map<string, NodeMeta>();

  const rootMeta: NodeMeta = {
    department: data.root_department || '',
    node_type_1: data.root_node_type_1 || '',
    node_type_2: data.root_node_type_2 || '',
    has_inspection_file: data.root_has_inspection_file || false,
  };
  nameMap.set(data.root_code, data.root_name);
  metaMap.set(data.root_code, rootMeta);

  for (const e of data.edges) {
    if (!childrenOf.has(e.parent_code)) {
      childrenOf.set(e.parent_code, []);
    }
    childrenOf.get(e.parent_code)!.push({ child_code: e.child_code, quantity: e.quantity });
    nameMap.set(e.parent_code, e.parent_name);
    nameMap.set(e.child_code, e.child_name);
    if (!metaMap.has(e.parent_code)) {
      metaMap.set(e.parent_code, {
        department: e.parent_department || '',
        node_type_1: e.parent_node_type_1 || '',
        node_type_2: e.parent_node_type_2 || '',
        has_inspection_file: e.parent_has_inspection_file || false,
      });
    }
    if (!metaMap.has(e.child_code)) {
      metaMap.set(e.child_code, {
        department: e.child_department || '',
        node_type_1: e.child_node_type_1 || '',
        node_type_2: e.child_node_type_2 || '',
        has_inspection_file: e.child_has_inspection_file || false,
      });
    }
  }

  const build = (code: string, level: number, quantity: number | null): TreeNode => {
    const children = (childrenOf.get(code) || []).map(
      c => build(c.child_code, level + 1, c.quantity)
    );
    return {
      code,
      name: nameMap.get(code) || code,
      level,
      children,
      quantity,
      meta: metaMap.get(code) || { department: '', node_type_1: '', node_type_2: '', has_inspection_file: false },
    };
  };

  return data.edges.length > 0 ? build(data.root_code, 1, null) : null;
}

function getAllCodes(node: TreeNode): string[] {
  const codes = [node.code];
  for (const child of node.children) {
    codes.push(...getAllCodes(child));
  }
  return codes;
}

interface LineInfo {
  isLast: boolean;
  ancestorHasMore: boolean[];
}

interface VisibleRow {
  node: TreeNode;
  l2Index: number;
  rowKey: string;
  line: LineInfo;
}

function computeLineInfo(rows: { node: TreeNode; rowKey: string }[]): LineInfo[] {
  const result: LineInfo[] = [];
  for (let i = 0; i < rows.length; i++) {
    const { rowKey } = rows[i];
    const depth = rowKey.split('-').length - 1;
    const parentPath = depth === 0 ? '' : rowKey.substring(0, rowKey.lastIndexOf('-'));

    const isLast = !rows.slice(i + 1).some(r => {
      const rp = depth === 0 ? '' : r.rowKey.substring(0, r.rowKey.lastIndexOf('-'));
      return rp === parentPath;
    });

    const ancestorHasMore: boolean[] = [];
    for (let d = 0; d < depth; d++) {
      const parts = rowKey.split('-');
      const ancestorPath = parts.slice(0, d + 1).join('-');
      const hasMore = rows.slice(i + 1).some(r => {
        const rParts = r.rowKey.split('-');
        if (rParts.length <= d) return false;
        return rParts.slice(0, d + 1).join('-') === ancestorPath;
      });
      ancestorHasMore.push(hasMore);
    }

    result.push({ isLast, ancestorHasMore });
  }
  return result;
}

export const AssemblyStructureModal: React.FC<AssemblyStructureModalProps> = ({ code, name, onClose }) => {
  const [tree, setTree] = useState<TreeNode | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [printingCode, setPrintingCode] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    const fetchStructure = async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await fetch(`/api/structure/?code=${encodeURIComponent(code)}`);
        if (!res.ok) {
          const err = await res.json().catch(() => ({}));
          throw new Error(err.message || '構成データの取得に失敗しました');
        }
        const data: StructureData = await res.json();
        if (cancelled) return;
        const t = buildTree(data);
        setTree(t);
        if (t) {
          setExpanded(new Set([t.code]));
        }
      } catch (err: any) {
        if (!cancelled) setError(err.message || '構成データの取得に失敗しました');
      } finally {
        if (!cancelled) setLoading(false);
      }
    };
    fetchStructure();
    return () => { cancelled = true; };
  }, [code]);

  const visibleRows = useMemo<VisibleRow[]>(() => {
    if (!tree) return [];
    const rows: { node: TreeNode; l2Index: number; rowKey: string }[] = [];
    let nextL2 = 0;

    const visit = (node: TreeNode, parentL2: number, path: string) => {
      const l2Index = node.level === 2 ? nextL2++ : parentL2;
      rows.push({ node, l2Index, rowKey: path });
      if (expanded.has(node.code) && node.children.length > 0) {
        for (let i = 0; i < node.children.length; i++) {
          visit(node.children[i], l2Index, `${path}-${i}`);
        }
      }
    };

    visit(tree, 0, '0');

    const lineInfos = computeLineInfo(rows);
    return rows.map((r, i) => ({ ...r, line: lineInfos[i] }));
  }, [tree, expanded]);

  const toggleExpand = useCallback((nodeCode: string) => {
    setExpanded(prev => {
      const next = new Set(prev);
      if (next.has(nodeCode)) {
        next.delete(nodeCode);
      } else {
        next.add(nodeCode);
      }
      return next;
    });
  }, []);

  const expandAll = useCallback(() => {
    if (!tree) return;
    setExpanded(new Set(getAllCodes(tree)));
  }, [tree]);

  const collapseAll = useCallback(() => {
    if (!tree) return;
    setExpanded(new Set([tree.code]));
  }, [tree]);

  const handleOpenFile = useCallback(async (nodeCode: string) => {
    const res = await fetch(`/api/inspection-file/open/?code=${encodeURIComponent(nodeCode)}`);
    const contentType = res.headers.get('Content-Type') || '';
    if (contentType.includes('application/json')) {
      const data = await res.json();
      if (data.status !== 'success') alert('ファイルを開けませんでした');
    } else if (res.ok) {
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      window.open(url, '_blank');
      setTimeout(() => URL.revokeObjectURL(url), 30000);
    }
  }, []);

  const handlePrintFile = useCallback(async (nodeCode: string) => {
    setPrintingCode(nodeCode);
    try {
      const res = await fetch(`/api/inspection-file/print/?code=${encodeURIComponent(nodeCode)}`, {
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
      setPrintingCode(null);
    }
  }, []);

  const renderNodeType = (meta: NodeMeta): string => {
    const parts: string[] = [];
    if (meta.node_type_1) parts.push(meta.node_type_1);
    if (meta.node_type_2) parts.push(meta.node_type_2);
    return parts.join('>');
  };

  return createPortal(
    <div className="modal-overlay ast-modal-overlay" onClick={onClose}>
      <div className="ast-modal-content" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            <Package size={18} />
            組立構成図
          </h3>
          <button className="btn btn-secondary btn-sm" onClick={onClose}>
            <X size={16} />
          </button>
        </div>

        <div className="ast-modal-body">
          <div className="ast-target-label">
            対象：<strong>{code}</strong> {name && <span className="text-muted">({name})</span>}
          </div>

          <div className="ast-toolbar">
            <button className="btn btn-ghost btn-xs" onClick={expandAll}>
              <Maximize2 size={12} /> すべて展開
            </button>
            <button className="btn btn-ghost btn-xs" onClick={collapseAll}>
              <Minimize2 size={12} /> すべて折りたたみ
            </button>
          </div>

          <div className="ast-main-area">
            <div className="ast-tree-area">
              {loading && (
                <div className="ast-loading">構成データを読み込んでいます...</div>
              )}
              {error && (
                <div className="ast-error">{error}</div>
              )}
              {!loading && !error && visibleRows.length === 0 && (
                <div className="ast-empty">構成データがありません</div>
              )}
              {!loading && !error && visibleRows.length > 0 && (
                <div className="ast-tree-scroll">
                  {visibleRows.map(({ node, l2Index, rowKey, line }) => {
                    const isExpanded = expanded.has(node.code);
                    const hasChildren = node.children.length > 0;
                    const groupColorIndex = l2Index % GROUP_COLORS.length;
                    const bgColor = node.level >= 2 ? GROUP_COLORS[groupColorIndex] : undefined;

                    let IconComponent;
                    if (node.level === 1) IconComponent = Crown;
                    else if (node.level === 2) IconComponent = Folder;
                    else IconComponent = FileText;

                    const metaStr = renderNodeType(node.meta);

                    return (
                      <div
                        key={rowKey}
                        className="ast-node-row"
                        style={{ backgroundColor: bgColor }}
                      >
                        <span className="ast-tree-lines" onClick={() => hasChildren && toggleExpand(node.code)}>
                          {line.ancestorHasMore.map((hasMore, i) => (
                            <span key={i} className="ast-line-seg">{hasMore ? '│' : ' '}</span>
                          ))}
                          <span className="ast-line-conn">{line.isLast ? '└' : '├'}</span>
                          {hasChildren ? (
                            isExpanded ? <ChevronDown size={12} className="ast-line-chevron" /> : <ChevronRight size={12} className="ast-line-chevron" />
                          ) : (
                            <span className="ast-line-chevron" />
                          )}
                        </span>
                        <span className="ast-node-icon">
                          <IconComponent size={13} />
                        </span>
                        <span className="ast-node-name">{node.name}</span>
                        <span className="ast-node-code">{node.code}</span>
                        {node.meta.department && (
                          <span className="ast-node-dept">{node.meta.department}</span>
                        )}
                        {metaStr && (
                          <span className="ast-node-type">{metaStr}</span>
                        )}
                        <span className="ast-node-spacer" />
                        {node.meta.has_inspection_file && (
                          <span className="ast-node-actions">
                            <button
                              className="ast-file-btn"
                              title="検査書表示"
                              onClick={e => { e.stopPropagation(); handleOpenFile(node.code); }}
                            >
                              <FileText size={12} />
                            </button>
                            <button
                              className="ast-file-btn"
                              title="印刷"
                              disabled={printingCode === node.code}
                              onClick={e => { e.stopPropagation(); handlePrintFile(node.code); }}
                            >
                              <Printer size={12} />
                            </button>
                          </span>
                        )}
                        {node.quantity != null && (
                          <span className="ast-node-qty">×{node.quantity}</span>
                        )}
                      </div>
                    );
                  })}
                </div>
              )}
            </div>
            <div className="ast-legend-area">
              <div className="ast-legend-title">凡例</div>
              <div className="ast-legend-item">
                <Crown size={14} className="ast-legend-icon" />
                <span>組立 (レベル1)</span>
              </div>
              <div className="ast-legend-item">
                <Folder size={14} className="ast-legend-icon" />
                <span>部品グループ (レベル2)</span>
              </div>
              <div className="ast-legend-item">
                <FileText size={14} className="ast-legend-icon" />
                <span>部品・材料 (レベル3+)</span>
              </div>
              <div className="ast-legend-divider" />
              <div className="ast-legend-title">グループ色</div>
              {[0, 1, 2].map(i => (
                <div className="ast-legend-item" key={i}>
                  <span className={`ast-color-swatch ast-swatch-${i}`} />
                  <span>グループ {i + 1}</span>
                </div>
              ))}
              <div className="ast-legend-divider" />
              <div className="ast-legend-title">操作</div>
              <div className="ast-legend-item">
                <ChevronRight size={12} /> <span>クリックで展開</span>
              </div>
              <div className="ast-legend-item">
                <ChevronDown size={12} /> <span>クリックで折りたたみ</span>
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>,
    document.body
  );
};
