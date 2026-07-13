import React, { useEffect, useState } from 'react';
import { MapPin } from 'lucide-react';
import type { FactoryMapResponse, FactoryMapMachine, InspectionTarget, LayoutSummary, LayoutObject, LayoutObjectType } from '../types';
import { MachinePopup } from './MachinePopup';

const FALLBACK_COLORS: Record<string, string> = {
  machine: '#6366f1',
  wall: '#64748b',
  path: '#10b981',
  area: '#f59e0b',
  stairs: '#a855f7',
  entrance: '#06b6d4',
};

const objectLabel = (object: LayoutObject) => {
  if (object.machine_no) return object.machine_no;
  if (object.object_name) return object.object_name;
  return object.type;
};

const objectFillColor = (object: LayoutObject, types: LayoutObjectType[]): string => {
  if (object.meta_json?.fill_color) return object.meta_json.fill_color;
  const typeDef = types.find((t) => t.code === object.type);
  if (typeDef?.color) return typeDef.color;
  return FALLBACK_COLORS[object.type] || '#6366f1';
};

const hexToRgba = (hex: string, alpha: number): string => {
  const r = parseInt(hex.slice(1, 3), 16);
  const g = parseInt(hex.slice(3, 5), 16);
  const b = parseInt(hex.slice(5, 7), 16);
  return `rgba(${r}, ${g}, ${b}, ${alpha})`;
};

interface LayoutMapData {
  layout: LayoutSummary;
  mapData: FactoryMapResponse | null;
  isLoading: boolean;
  error: string | null;
}

interface LayoutListProps {
  layouts: LayoutSummary[];
  selectedDate: string;
  activeLayoutId: number | null;
  setActiveLayoutId: (id: number) => void;
  highlightedTargetCode: string | null;
  targets: InspectionTarget[];
  onScrollToTarget: (targetId: number) => void;
  onRegisterTarget: (code: string) => void;
}

export const LayoutList: React.FC<LayoutListProps> = ({
  layouts,
  selectedDate,
  activeLayoutId,
  setActiveLayoutId,
  highlightedTargetCode,
  targets,
  onScrollToTarget,
  onRegisterTarget,
}) => {
  const [layoutMaps, setLayoutMaps] = useState<LayoutMapData[]>([]);
  const [selectedMachine, setSelectedMachine] = useState<FactoryMapMachine | null>(null);

  useEffect(() => {
    if (!selectedDate) {
      setLayoutMaps([]);
      return;
    }

    const nonDefaultLayouts = layouts.filter((l) => l.layout_name !== 'default');
    if (nonDefaultLayouts.length === 0) {
      setLayoutMaps([]);
      return;
    }

    const initialMaps: LayoutMapData[] = nonDefaultLayouts.map((layout) => ({
      layout,
      mapData: null,
      isLoading: true,
      error: null,
    }));
    setLayoutMaps(initialMaps);

    const fetchAll = async () => {
      await Promise.all(
        nonDefaultLayouts.map(async (layout) => {
          try {
            const response = await fetch(`/api/factory-map/?date=${selectedDate}&layout_id=${layout.id}`);
            if (!response.ok) {
              throw new Error(`見取り図の取得に失敗しました (${response.status})`);
            }
            const data: FactoryMapResponse = await response.json();
            setLayoutMaps((prev) => {
              const next = [...prev];
              const targetIdx = next.findIndex(item => item.layout.id === layout.id);
              if (targetIdx !== -1) {
                next[targetIdx] = { ...next[targetIdx], mapData: data, isLoading: false };
              }
              return next;
            });
          } catch (err: any) {
            setLayoutMaps((prev) => {
              const next = [...prev];
              const targetIdx = next.findIndex(item => item.layout.id === layout.id);
              if (targetIdx !== -1) {
                next[targetIdx] = { ...next[targetIdx], isLoading: false, error: err.message || '見取り図の取得に失敗しました。' };
              }
              return next;
            });
          }
        })
      );
    };

    fetchAll();
  }, [layouts, selectedDate, targets]);

  // Synchronize layout switching when a target code is clicked in the list
  // Only auto-switch when highlightedTargetCode changes to a NEW code,
  // so manual segment button clicks are never overridden.
  useEffect(() => {
    if (!highlightedTargetCode || layoutMaps.length === 0) return;

    const foundLayoutMap = layoutMaps.find(lm => {
      if (!lm.mapData?.layout?.objects) return false;
      const machineIdsOnLayout = new Set(
        lm.mapData.layout.objects
          .filter((obj) => obj.type === 'machine' && obj.machine_id != null)
          .map((obj) => obj.machine_id)
      );
      return lm.mapData.machines?.some(
        (m) => machineIdsOnLayout.has(m.machine_id) && m.target_codes?.includes(highlightedTargetCode)
      );
    });
    if (foundLayoutMap && foundLayoutMap.layout.id !== activeLayoutId) {
      setActiveLayoutId(foundLayoutMap.layout.id);
    }
  }, [highlightedTargetCode, layoutMaps, activeLayoutId, setActiveLayoutId]);

  if (layoutMaps.length === 0) {
    return (
      <div className="card factory-map-card">
        <div className="map-empty-state">
          <MapPin size={28} className="text-muted" />
          <p>表示する見取り図がありません。</p>
        </div>
      </div>
    );
  }

  const activeMap = layoutMaps.find((item) => item.layout.id === activeLayoutId) || layoutMaps[0];

  return (
    <div className="layout-list-container" style={{ height: '100%', display: 'flex', flexDirection: 'column' }}>
      <div className="layout-list-item card" style={{ flex: 1, display: 'flex', flexDirection: 'column', minHeight: 0 }}>
        <div className="map-segment-control">
          {layoutMaps.map(({ layout, mapData }) => {
            const machineIdsOnLayout = new Set(
              mapData?.layout?.objects
                ?.filter((obj) => obj.type === 'machine' && obj.machine_id != null)
                ?.map((obj) => obj.machine_id) ?? []
            );
            const targetCount = mapData?.machines
              ?.filter((m) => machineIdsOnLayout.has(m.machine_id))
              ?.reduce((sum, m) => sum + m.target_codes.length, 0) ?? 0;
            return (
              <button
                key={layout.id}
                type="button"
                className={`map-segment-button ${activeLayoutId === layout.id ? 'active' : ''}`}
                onClick={() => setActiveLayoutId(layout.id)}
              >
                {layout.layout_name}
                {targetCount > 0 && <span className="map-segment-badge">{targetCount}</span>}
              </button>
            );
          })}
        </div>
        <div className="layout-list-header">
          <h3 className="layout-list-title">{activeMap.layout.layout_name}</h3>
          {activeMap.isLoading && <div className="pulse-spinner small" />}
          {activeMap.error && <span className="layout-list-error">{activeMap.error}</span>}
        </div>

        <div style={{ flex: 1, display: 'flex', flexDirection: 'column', justifyContent: 'center', minHeight: 0, overflow: 'hidden', padding: '10px 0' }}>
          {activeMap.isLoading ? (
            <div className="map-empty-state">
              <div className="pulse-spinner"></div>
              <p>見取り図を読み込んでいます...</p>
            </div>
          ) : activeMap.error ? (
            <div className="map-empty-state">
              <p className="layout-list-error">{activeMap.error}</p>
            </div>
          ) : !activeMap.mapData?.layout ? (
            <div className="map-empty-state">
              <MapPin size={28} className="text-muted" />
              <p>見取り図レイアウトがありません。</p>
            </div>
          ) : (
            <div 
              className="factory-map-canvas" 
              style={{ 
                aspectRatio: `${activeMap.mapData.layout.grid_width} / ${activeMap.mapData.layout.grid_height}`,
                maxHeight: '100%',
                maxWidth: '100%',
                margin: '0 auto',
              }}
            >
              {activeMap.mapData.layout.background_image_path && (
                <img className="factory-map-bg" src={activeMap.mapData.layout.background_image_path} alt="" />
              )}
              {activeMap.mapData.layout.objects.length === 0 ? (
                <div className="map-empty-inset">
                  <MapPin size={28} className="text-muted" />
                  <p>レイアウトにオブジェクトがありません</p>
                </div>
              ) : (
                activeMap.mapData.layout.objects.map((object) => {
                  const targetCodes = object.machine_id ? (activeMap.mapData?.machines?.find((m) => m.machine_id === object.machine_id)?.target_codes ?? []) : [];
                  const isTarget = targetCodes.length > 0;
                  const color = objectFillColor(object, activeMap.mapData!.layout.object_types);
                  const isHighlighted = isTarget && highlightedTargetCode && targetCodes.includes(highlightedTargetCode);

                  return (
                    <div
                      key={object.layout_object_id ?? `${object.type}-${object.grid_x}-${object.grid_y}`}
                      className={`map-object map-object-${object.type} ${isTarget ? 'is-target' : ''} ${isHighlighted ? 'highlighted' : ''}`}
                      style={{
                        left: `${(object.grid_x / activeMap.mapData!.layout.grid_width) * 100}%`,
                        top: `${(object.grid_y / activeMap.mapData!.layout.grid_height) * 100}%`,
                        width: `${(object.width / activeMap.mapData!.layout.grid_width) * 100}%`,
                        height: `${(object.height / activeMap.mapData!.layout.grid_height) * 100}%`,
                        background: hexToRgba(color, 0.35),
                        borderColor: color,
                      }}
                      title={`${objectLabel(object)}${isTarget ? ` / 対象 ${targetCodes.length}件` : ''}`}
                      onClick={() => {
                        if (object.machine_id) {
                          const machine = activeMap.mapData?.machines?.find((m) => m.machine_id === object.machine_id);
                          if (machine) setSelectedMachine(machine);
                        }
                      }}
                    >
                      <span>{objectLabel(object)}</span>
                      {isTarget && <strong>{targetCodes.length}</strong>}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </div>
      </div>

      {selectedMachine && (
        <MachinePopup
          machineNo={selectedMachine.machine_no}
          machineName={selectedMachine.machine_name}
          assignedItems={selectedMachine.assigned_items}
          targetCodes={selectedMachine.target_codes}
          targets={targets}
          onClose={() => setSelectedMachine(null)}
          onScrollToTarget={onScrollToTarget}
          onRegisterTarget={onRegisterTarget}
        />
      )}
    </div>
  );
};