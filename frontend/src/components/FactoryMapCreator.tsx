import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Grid3X3, MousePointer2, Plus, Save, Trash2, Palette, X } from 'lucide-react';
import type { FactoryMapLayout, LayoutObject, LayoutObjectTypeCode, LayoutSummary, LayoutObjectType } from '../types';

interface MachineOption {
  id: number;
  machine_no: string;
  machine_name: string;
}

const fallbackTypes: { code: LayoutObjectTypeCode; display_name: string }[] = [
  { code: 'machine', display_name: '機械' },
  { code: 'wall', display_name: '壁' },
  { code: 'path', display_name: '通路' },
  { code: 'area', display_name: 'エリア' },
  { code: 'stairs', display_name: '階段' },
  { code: 'entrance', display_name: '出入口' },
];

const FALLBACK_COLORS: Record<string, string> = {
  machine: '#6366f1',
  wall: '#64748b',
  path: '#10b981',
  area: '#f59e0b',
  stairs: '#a855f7',
  entrance: '#06b6d4',
};

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

const objectFillColor = (object: LayoutObject, types: LayoutObjectType[]): string => {
  if (object.meta_json?.fill_color) return object.meta_json.fill_color;
  const typeDef = types.find((t) => t.code === object.type);
  if (typeDef?.color) return typeDef.color;
  return FALLBACK_COLORS[object.type] || '#6366f1';
};

export const FactoryMapCreator: React.FC = () => {
  const [layout, setLayout] = useState<FactoryMapLayout | null>(null);
  const [layouts, setLayouts] = useState<LayoutSummary[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [newType, setNewType] = useState<LayoutObjectTypeCode>('machine');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [dragOffset, setDragOffset] = useState<{ x: number; y: number } | null>(null);
  const [newLayoutName, setNewLayoutName] = useState('');
  const [editingLayoutId, setEditingLayoutId] = useState<number | null>(null);
  const [machines, setMachines] = useState<MachineOption[]>([]);
  const [showColorModal, setShowColorModal] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const selectedObject = useMemo(
    () => layout?.objects.find((object) => object.layout_object_id === selectedId) ?? null,
    [layout, selectedId],
  );

  const typeColorMap = useMemo(() => {
    const map: Record<string, string> = {};
    for (const t of layout?.object_types ?? []) {
      map[t.code] = t.color;
    }
    for (const t of fallbackTypes) {
      if (!map[t.code]) map[t.code] = FALLBACK_COLORS[t.code];
    }
    return map;
  }, [layout]);

  const loadLayout = async (layoutId?: number) => {
    setIsLoading(true);
    setStatusMessage(null);
    try {
      const url = layoutId ? `/api/factory-map/layout/?layout_id=${layoutId}` : '/api/factory-map/layout/';
      const response = await fetch(url);
      if (!response.ok) throw new Error(`見取り図の取得に失敗しました (${response.status})`);
      const data: FactoryMapLayout = await response.json();
      setLayout(data);
      setEditingLayoutId(data.layout_id);
    } catch (error: any) {
      setStatusMessage(error.message || '見取り図の取得に失敗しました。');
    } finally {
      setIsLoading(false);
    }
  };

  const loadLayoutList = async () => {
    try {
      const response = await fetch('/api/factory-map/layouts/');
      if (response.ok) {
        const data: LayoutSummary[] = await response.json();
        setLayouts(data);
      }
    } catch {
      // ignore
    }
  };

  const loadMachines = async () => {
    try {
      const response = await fetch('/api/factory-map/machines/');
      if (response.ok) {
        setMachines(await response.json());
      }
    } catch {
      // ignore
    }
  };

  useEffect(() => {
    const init = async () => {
      await Promise.all([loadLayoutList(), loadMachines()]);
      await loadLayout();
    };
    init();
  }, []);

  const handleSelectLayout = async (layoutId: number) => {
    await loadLayout(layoutId);
  };

  const handleCreateLayout = async () => {
    const name = newLayoutName.trim();
    if (!name) return;
    try {
      const response = await fetch('/api/factory-map/layouts/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ layout_name: name }),
      });
      if (response.ok) {
        const created: LayoutSummary = await response.json();
        setNewLayoutName('');
        setLayouts((prev) => [...prev, created]);
        await loadLayout(created.id);
      } else {
        const err = await response.json();
        setStatusMessage(err.message || 'レイアウトの作成に失敗しました。');
      }
    } catch (error: any) {
      setStatusMessage(error.message || 'レイアウトの作成に失敗しました。');
    }
  };

  const updateLayout = (updater: (layout: FactoryMapLayout) => FactoryMapLayout) => {
    setLayout((current) => (current ? updater(current) : current));
  };

  const updateObject = (id: number, patch: Partial<LayoutObject>) => {
    updateLayout((current) => ({
      ...current,
      objects: current.objects.map((object) => (
        object.layout_object_id === id ? { ...object, ...patch } : object
      )),
    }));
  };

  const handleAddObject = () => {
    if (!layout) return;
    const tempId = -Date.now();
    const nextObject: LayoutObject = {
      layout_object_id: tempId,
      type: newType,
      machine_id: null,
      machine_name: null,
      object_name: '',
      grid_x: 1,
      grid_y: 1,
      width: newType === 'path' ? 8 : 4,
      height: newType === 'path' ? 2 : 3,
      rotation: 0,
      meta_json: {},
    };
    setLayout({ ...layout, objects: [...layout.objects, nextObject] });
    setSelectedId(tempId);
  };

  const handleDeleteObject = () => {
    if (!layout || selectedId === null) return;
    setLayout({ ...layout, objects: layout.objects.filter((object) => object.layout_object_id !== selectedId) });
    setSelectedId(null);
  };

  const handleAssignMachine = (objectId: number, machineId: number | null) => {
    const machine = machineId ? machines.find((m) => m.id === machineId) : null;
    updateObject(objectId, {
      machine_id: machine?.id ?? null,
      machine_name: machine?.machine_name ?? null,
      object_name: machine ? machine.machine_name : '',
    });
  };

  const gridPointFromEvent = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!layout || !canvasRef.current) return null;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * layout.grid_width;
    const y = ((event.clientY - rect.top) / rect.height) * layout.grid_height;
    return { x: Math.round(x), y: Math.round(y) };
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLButtonElement>, object: LayoutObject) => {
    if (!layout || !canvasRef.current) return;
    const button = event.currentTarget;
    button.setPointerCapture(event.pointerId);
    setSelectedId(object.layout_object_id!);
    setDraggingId(object.layout_object_id!);
    const rect = canvasRef.current.getBoundingClientRect();
    const clickX = Math.round(((event.clientX - rect.left) / rect.width) * layout.grid_width);
    const clickY = Math.round(((event.clientY - rect.top) / rect.height) * layout.grid_height);
    setDragOffset({ x: clickX - object.grid_x, y: clickY - object.grid_y });

    const onPointerMove = (moveEvent: React.PointerEvent<HTMLButtonElement>) => {
      if (!layout || draggingId === null || dragOffset === null) return;
      const point = gridPointFromEvent(moveEvent as any);
      const obj = layout.objects.find((item) => item.layout_object_id === draggingId);
      if (!point || !obj) return;
      updateObject(draggingId, {
        grid_x: Math.round(clamp(point.x - dragOffset.x, 0, layout.grid_width - obj.width)),
        grid_y: Math.round(clamp(point.y - dragOffset.y, 0, layout.grid_height - obj.height)),
      });
    };

    const onPointerUp = () => {
      button.releasePointerCapture(event.pointerId);
      button.removeEventListener('pointermove', onPointerMove as any);
      button.removeEventListener('pointerup', onPointerUp as any);
      button.removeEventListener('pointercancel', onPointerUp as any);
      setDraggingId(null);
      setDragOffset(null);
    };

    button.addEventListener('pointermove', onPointerMove as any);
    button.addEventListener('pointerup', onPointerUp as any);
    button.addEventListener('pointercancel', onPointerUp as any);
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!layout || draggingId === null || dragOffset === null) return;
    const point = gridPointFromEvent(event);
    const object = layout.objects.find((item) => item.layout_object_id === draggingId);
    if (!point || !object) return;
    updateObject(draggingId, {
      grid_x: Math.round(clamp(point.x - dragOffset.x, 0, layout.grid_width - object.width)),
      grid_y: Math.round(clamp(point.y - dragOffset.y, 0, layout.grid_height - object.height)),
    });
  };

  const handlePointerUp = () => {
    setDraggingId(null);
    setDragOffset(null);
  };

  const handleSave = async () => {
    if (!layout) return;
    setIsSaving(true);
    setStatusMessage(null);
    try {
      const url = editingLayoutId ? `/api/factory-map/layout/?layout_id=${editingLayoutId}` : '/api/factory-map/layout/';
      const response = await fetch(url, {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          layout_name: layout.layout_name,
          background_image_path: '',
          grid_width: layout.grid_width,
          grid_height: layout.grid_height,
          objects: layout.objects.map((object) => ({
            type: object.type,
            machine_id: object.type === 'machine' ? object.machine_id : null,
            object_name: object.object_name ?? '',
            grid_x: object.grid_x,
            grid_y: object.grid_y,
            width: object.width,
            height: object.height,
            rotation: object.rotation ?? 0,
            meta_json: object.meta_json ?? {},
          })),
        }),
      });
      if (!response.ok) throw new Error(`保存に失敗しました (${response.status})`);
      const data: FactoryMapLayout = await response.json();
      setLayout(data);
      setEditingLayoutId(data.layout_id);
      setSelectedId(null);
      setStatusMessage('見取り図を保存しました。');
      await loadLayoutList();
    } catch (error: any) {
      setStatusMessage(error.message || '見取り図の保存に失敗しました。');
    } finally {
      setIsSaving(false);
    }
  };

  const handleGlobalColorChange = async (code: string, color: string) => {
    setLayout((current) => {
      if (!current) return current;
      return {
        ...current,
        object_types: current.object_types.map((t) =>
          t.code === code ? { ...t, color } : t
        ),
      };
    });
    try {
      await fetch(`/api/factory-map/object-type/${code}/`, {
        method: 'PATCH',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ color }),
      });
    } catch {
      // ignore
    }
  };

  const typeOptions = layout?.object_types?.length
    ? layout.object_types.map((item) => ({ code: item.code, display_name: item.display_name, color: item.color }))
    : fallbackTypes.map((t) => ({ ...t, color: FALLBACK_COLORS[t.code] }));

  if (isLoading) {
    return (
      <div className="card map-creator-card">
        <div className="map-empty-state">
          <div className="pulse-spinner"></div>
          <p>見取り図編集データを読み込んでいます...</p>
        </div>
      </div>
    );
  }

  return (
    <div className="map-creator-layout">
      <aside className="card map-tool-panel">
        <h2 className="card-title">
          <Grid3X3 className="icon-title" size={20} />
          見取り図作成
        </h2>

        <div className="layout-selector-section">
          <div className="layout-selector-row">
            <select
              className="form-control"
              value={editingLayoutId ?? ''}
              onChange={(e) => { const id = Number(e.target.value); if (id) handleSelectLayout(id); }}
            >
              {layouts.map((item) => (
                <option key={item.id} value={item.id}>{item.layout_name}</option>
              ))}
            </select>
            <button className="btn btn-secondary" type="button" onClick={handleCreateLayout} disabled={!newLayoutName.trim()}>
              <Plus size={14} />
            </button>
          </div>
          <input
            className="form-control"
            placeholder="新規レイアウト名..."
            value={newLayoutName}
            onChange={(e) => setNewLayoutName(e.target.value)}
            onKeyDown={(e) => { if (e.key === 'Enter') handleCreateLayout(); }}
          />
        </div>

        <div className="tool-panel-divider"></div>

        <div className="form-group">
          <label className="form-label">オブジェクト種別</label>
          <div style={{ display: 'flex', gap: 6, alignItems: 'center' }}>
            <select className="form-control" value={newType} onChange={(event) => setNewType(event.target.value as LayoutObjectTypeCode)}
              style={{ flex: 1 }}>
              {typeOptions.map((item) => (
                <option key={item.code} value={item.code}>{item.display_name}</option>
              ))}
            </select>
            <button className="btn btn-secondary" type="button" onClick={() => setShowColorModal(true)} title="色設定">
              <Palette size={14} />
            </button>
          </div>
        </div>

        <button className="btn btn-secondary" type="button" onClick={handleAddObject} disabled={!layout}>
          <Plus size={16} />
          追加
        </button>

        <div className="tool-panel-divider"></div>

        <div className="editor-grid-controls">
          <div className="form-group">
            <label className="form-label">Grid W</label>
            <input
              type="number"
              className="form-control"
              min={1}
              step={1}
              value={layout?.grid_width ?? 50}
              onChange={(event) => updateLayout((current) => ({ ...current, grid_width: Math.round(Number(event.target.value)) || 1 }))}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Grid H</label>
            <input
              type="number"
              className="form-control"
              min={1}
              step={1}
              value={layout?.grid_height ?? 50}
              onChange={(event) => updateLayout((current) => ({ ...current, grid_height: Math.round(Number(event.target.value)) || 1 }))}
            />
          </div>
        </div>

        {selectedObject && (
          <div className="selected-object-panel">
            <h3>
              <MousePointer2 size={16} />
              選択中
            </h3>

            <input
              className="form-control"
              placeholder="オブジェクト名 (任意)"
              value={selectedObject.object_name ?? ''}
              onChange={(event) => updateObject(selectedObject.layout_object_id!, { object_name: event.target.value })}
            />

            {selectedObject.type === 'machine' && (
              <div className="form-group">
                <label className="form-label">機械</label>
                <select
                  className="form-control"
                  value={selectedObject.machine_id ?? ''}
                  onChange={(e) => handleAssignMachine(selectedObject.layout_object_id!, e.target.value ? Number(e.target.value) : null)}
                >
                  <option value="">--- 未割当 ---</option>
                  {machines
                    .slice()
                    .sort((a, b) => Number(a.machine_no) - Number(b.machine_no))
                    .map((m) => (
                      <option key={m.id} value={m.id}>{String(m.machine_no).padStart(3, '0')}: {m.machine_name}</option>
                    ))}
                </select>
              </div>
            )}

            <div className="form-group">
              <label className="form-label">
                <Palette size={12} />
                色
              </label>
              <input
                type="color"
                className="form-control"
                style={{ padding: 4, height: 36 }}
                value={objectFillColor(selectedObject, layout?.object_types ?? [])}
                onChange={(event) => updateObject(selectedObject.layout_object_id!, {
                  meta_json: { ...selectedObject.meta_json, fill_color: event.target.value }
                })}
              />
            </div>

            <div className="editor-grid-controls">
              {(['grid_x', 'grid_y', 'width', 'height'] as const).map((field) => (
                <div className="form-group" key={field}>
                  <label className="form-label">{field}</label>
                  <input
                    type="number"
                    className="form-control"
                    min={field === 'width' || field === 'height' ? 1 : 0}
                    step={1}
                    value={selectedObject[field]}
                    onChange={(event) => updateObject(selectedObject.layout_object_id!, { [field]: Math.round(Number(event.target.value)) || 0 })}
                  />
                </div>
              ))}
            </div>

            <button className="btn btn-secondary danger-action" type="button" onClick={handleDeleteObject}>
              <Trash2 size={16} />
              削除
            </button>
          </div>
        )}

        <button className="btn btn-primary btn-submit" type="button" onClick={handleSave} disabled={!layout || isSaving}>
          <Save size={16} />
          {isSaving ? '保存中...' : '保存'}
        </button>
        {statusMessage && <div className="editor-status-message">{statusMessage}</div>}
      </aside>

      <section className="card map-creator-card">
        {layout && (
          <div
            ref={canvasRef}
            className="factory-map-canvas editor-canvas"
            style={{ aspectRatio: `${layout.grid_width} / ${layout.grid_height}` }}
            onPointerMove={handlePointerMove}
            onPointerUp={handlePointerUp}
            onPointerLeave={handlePointerUp}
          >
            {layout.objects.map((object) => {
              const color = objectFillColor(object, layout.object_types);
              return (
                <button
                  type="button"
                  key={object.layout_object_id}
                  className={`map-object editor-object map-object-${object.type} ${selectedId === object.layout_object_id ? 'is-selected' : ''}`}
                  style={{
                    left: `${(object.grid_x / layout.grid_width) * 100}%`,
                    top: `${(object.grid_y / layout.grid_height) * 100}%`,
                    width: `${(object.width / layout.grid_width) * 100}%`,
                    height: `${(object.height / layout.grid_height) * 100}%`,
                    background: `rgba(${parseInt(color.slice(1,3), 16)}, ${parseInt(color.slice(3,5), 16)}, ${parseInt(color.slice(5,7), 16)}, 0.35)`,
                    borderColor: color,
                  }}
                  onPointerDown={(event) => handlePointerDown(event, object)}
                >
                  <span>{object.object_name || object.type}</span>
                </button>
              );
            })}
          </div>
        )}
      </section>

      {showColorModal && (
        <div className="modal-overlay" onClick={() => setShowColorModal(false)}>
          <div className="modal-content card" onClick={(e) => e.stopPropagation()}>
            <div className="modal-header">
              <h3><Palette size={18} /> グローバル色設定</h3>
              <button className="btn btn-secondary" style={{ padding: '4px 8px' }} onClick={() => setShowColorModal(false)}>
                <X size={16} />
              </button>
            </div>
            <div className="modal-body">
              {typeOptions.map((item) => (
                <div key={item.code} className="color-setting-row">
                  <span className="color-setting-label">{item.display_name}</span>
                  <input
                    type="color"
                    className="color-picker-input"
                    value={typeColorMap[item.code] || FALLBACK_COLORS[item.code]}
                    onChange={(e) => handleGlobalColorChange(item.code, e.target.value)}
                  />
                  <span className="color-setting-hex">{typeColorMap[item.code] || FALLBACK_COLORS[item.code]}</span>
                </div>
              ))}
            </div>
          </div>
        </div>
      )}
    </div>
  );
};
