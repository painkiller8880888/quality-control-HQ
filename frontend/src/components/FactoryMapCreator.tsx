import React, { useEffect, useMemo, useRef, useState } from 'react';
import { Grid3X3, Image, MousePointer2, Plus, Save, Trash2 } from 'lucide-react';
import type { FactoryMapLayout, LayoutObject, LayoutObjectTypeCode } from '../types';

const fallbackTypes: { code: LayoutObjectTypeCode; display_name: string }[] = [
  { code: 'machine', display_name: '機械' },
  { code: 'wall', display_name: '壁' },
  { code: 'path', display_name: '通路' },
  { code: 'area', display_name: 'エリア' },
  { code: 'stairs', display_name: '階段' },
  { code: 'entrance', display_name: '出入口' },
];

const clamp = (value: number, min: number, max: number) => Math.max(min, Math.min(max, value));

export const FactoryMapCreator: React.FC = () => {
  const [layout, setLayout] = useState<FactoryMapLayout | null>(null);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [newType, setNewType] = useState<LayoutObjectTypeCode>('machine');
  const [machineIdInput, setMachineIdInput] = useState('');
  const [statusMessage, setStatusMessage] = useState<string | null>(null);
  const [isLoading, setIsLoading] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [draggingId, setDraggingId] = useState<number | null>(null);
  const [bgImageError, setBgImageError] = useState(false);
  const canvasRef = useRef<HTMLDivElement | null>(null);

  const selectedObject = useMemo(
    () => layout?.objects.find((object) => object.layout_object_id === selectedId) ?? null,
    [layout, selectedId],
  );

  useEffect(() => {
    const loadLayout = async () => {
      setIsLoading(true);
      setStatusMessage(null);
      try {
        const response = await fetch('/api/factory-map/layout/');
        if (!response.ok) throw new Error(`見取り図の取得に失敗しました (${response.status})`);
        const data: FactoryMapLayout = await response.json();
        setLayout(data);
      } catch (error: any) {
        setStatusMessage(error.message || '見取り図の取得に失敗しました。');
      } finally {
        setIsLoading(false);
      }
    };
    loadLayout();
  }, []);

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
    const objectName = newType === 'machine' ? '機械' : fallbackTypes.find((item) => item.code === newType)?.display_name ?? newType;
    const machineId = newType === 'machine' && machineIdInput ? Number(machineIdInput) : null;
    const nextObject: LayoutObject = {
      layout_object_id: tempId,
      type: newType,
      machine_id: Number.isFinite(machineId) ? machineId : null,
      object_name: objectName,
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

  const gridPointFromEvent = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!layout || !canvasRef.current) return null;
    const rect = canvasRef.current.getBoundingClientRect();
    const x = ((event.clientX - rect.left) / rect.width) * layout.grid_width;
    const y = ((event.clientY - rect.top) / rect.height) * layout.grid_height;
    return { x: Math.round(x), y: Math.round(y) };
  };

  const handlePointerMove = (event: React.PointerEvent<HTMLDivElement>) => {
    if (!layout || draggingId === null) return;
    const point = gridPointFromEvent(event);
    const object = layout.objects.find((item) => item.layout_object_id === draggingId);
    if (!point || !object) return;
    updateObject(draggingId, {
      grid_x: clamp(point.x, 0, layout.grid_width - object.width),
      grid_y: clamp(point.y, 0, layout.grid_height - object.height),
    });
  };

  const handleSave = async () => {
    if (!layout) return;
    setIsSaving(true);
    setStatusMessage(null);
    try {
      const response = await fetch('/api/factory-map/layout/', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          layout_name: layout.layout_name,
          background_image_path: layout.background_image_path,
          grid_width: layout.grid_width,
          grid_height: layout.grid_height,
          objects: layout.objects.map((object) => ({
            type: object.type,
            machine_id: object.type === 'machine' ? object.machine_id : null,
            object_name: object.object_name,
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
      setSelectedId(null);
      setStatusMessage('見取り図を保存しました。');
    } catch (error: any) {
      setStatusMessage(error.message || '見取り図の保存に失敗しました。');
    } finally {
      setIsSaving(false);
    }
  };

  const typeOptions = layout?.object_types?.length
    ? layout.object_types.map((item) => ({ code: item.code, display_name: item.display_name }))
    : fallbackTypes;

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

        <div className="form-group">
          <label className="form-label">オブジェクト種別</label>
          <select className="form-control" value={newType} onChange={(event) => setNewType(event.target.value as LayoutObjectTypeCode)}>
            {typeOptions.map((item) => (
              <option key={item.code} value={item.code}>{item.display_name}</option>
            ))}
          </select>
        </div>

        {newType === 'machine' && (
          <div className="form-group">
            <label className="form-label">machine_id</label>
            <input className="form-control" value={machineIdInput} onChange={(event) => setMachineIdInput(event.target.value)} placeholder="未指定可" />
          </div>
        )}

        <button className="btn btn-secondary" type="button" onClick={handleAddObject} disabled={!layout}>
          <Plus size={16} />
          追加
        </button>

        <div className="tool-panel-divider"></div>

        <div className="form-group">
          <label className="form-label">
            <Image size={16} className="label-icon" />
            背景画像パス
          </label>
          <input
            className="form-control"
            value={layout?.background_image_path ?? ''}
            onChange={(event) => updateLayout((current) => ({ ...current, background_image_path: event.target.value }))}
          />
          {bgImageError && layout?.background_image_path && (
            <div className="editor-field-error">画像URLが正しくないか、アクセスできません</div>
          )}
        </div>

        <div className="editor-grid-controls">
          <div className="form-group">
            <label className="form-label">Grid W</label>
            <input
              type="number"
              className="form-control"
              min={1}
              value={layout?.grid_width ?? 50}
              onChange={(event) => updateLayout((current) => ({ ...current, grid_width: Number(event.target.value) || 1 }))}
            />
          </div>
          <div className="form-group">
            <label className="form-label">Grid H</label>
            <input
              type="number"
              className="form-control"
              min={1}
              value={layout?.grid_height ?? 50}
              onChange={(event) => updateLayout((current) => ({ ...current, grid_height: Number(event.target.value) || 1 }))}
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
              value={selectedObject.object_name}
              onChange={(event) => updateObject(selectedObject.layout_object_id!, { object_name: event.target.value })}
            />
            <div className="editor-grid-controls">
              {(['grid_x', 'grid_y', 'width', 'height'] as const).map((field) => (
                <div className="form-group" key={field}>
                  <label className="form-label">{field}</label>
                  <input
                    type="number"
                    className="form-control"
                    min={field === 'width' || field === 'height' ? 1 : 0}
                    value={selectedObject[field]}
                    onChange={(event) => updateObject(selectedObject.layout_object_id!, { [field]: Number(event.target.value) || 0 })}
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
            onPointerUp={() => setDraggingId(null)}
            onPointerLeave={() => setDraggingId(null)}
          >
            {layout.background_image_path && (
              <img className="factory-map-bg" src={layout.background_image_path} alt=""
                onError={() => setBgImageError(true)}
                onLoad={() => setBgImageError(false)}
              />
            )}
            {bgImageError && layout.background_image_path && (
              <div className="map-bg-error">背景画像を読み込めませんでした</div>
            )}
            {layout.objects.map((object) => (
              <button
                type="button"
                key={object.layout_object_id}
                className={`map-object editor-object map-object-${object.type} ${selectedId === object.layout_object_id ? 'is-selected' : ''}`}
                style={{
                  left: `${(object.grid_x / layout.grid_width) * 100}%`,
                  top: `${(object.grid_y / layout.grid_height) * 100}%`,
                  width: `${(object.width / layout.grid_width) * 100}%`,
                  height: `${(object.height / layout.grid_height) * 100}%`,
                }}
                onPointerDown={(event) => {
                  event.currentTarget.setPointerCapture(event.pointerId);
                  setSelectedId(object.layout_object_id!);
                  setDraggingId(object.layout_object_id!);
                }}
              >
                <span>{object.object_name || object.type}</span>
              </button>
            ))}
          </div>
        )}
      </section>
    </div>
  );
};
