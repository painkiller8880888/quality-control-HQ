import React from 'react';
import { Map as MapIcon, MapPin } from 'lucide-react';
import type { FactoryMapResponse, LayoutObject, LayoutObjectType } from '../types';

interface FactoryMapViewerProps {
  mapData: FactoryMapResponse | null;
  isLoading: boolean;
  selectedDate: string;
}

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

export const FactoryMapViewer: React.FC<FactoryMapViewerProps> = ({ mapData, isLoading, selectedDate }) => {
  const layout = mapData?.layout;
  const objects = layout?.objects ?? [];
  const objectTypes = layout?.object_types ?? [];
  const machines = mapData?.machines ?? [];

  const machineTargets = new window.Map<number, string[]>();
  machines.forEach((machine) => {
    machineTargets.set(machine.machine_id, machine.target_codes);
  });

  return (
    <div className="card factory-map-card">
      <div className="map-card-header">
        <h2 className="card-title">
          <MapIcon className="icon-title" size={20} />
          見取り図
        </h2>
        {selectedDate && <span className="map-date-badge">{selectedDate}</span>}
      </div>

      {isLoading ? (
        <div className="map-empty-state">
          <div className="pulse-spinner"></div>
          <p>見取り図を読み込んでいます...</p>
        </div>
      ) : !selectedDate ? (
        <div className="map-empty-state">
          <MapPin size={28} className="text-muted" />
          <p>対象日を指定すると見取り図を表示します。</p>
        </div>
      ) : !layout ? (
        <div className="map-empty-state">
          <MapPin size={28} className="text-muted" />
          <p>見取り図レイアウトがまだ登録されていません。</p>
        </div>
      ) : (
        <div className="factory-map-canvas" style={{ aspectRatio: `${layout.grid_width} / ${layout.grid_height}` }}>
          {objects.length === 0 ? (
            <div className="map-empty-inset">
              <MapPin size={28} className="text-muted" />
              <p>レイアウトにオブジェクトがありません</p>
            </div>
          ) : (
            objects.map((object) => {
            const targetCodes = object.machine_id ? machineTargets.get(object.machine_id) ?? [] : [];
            const isTarget = targetCodes.length > 0;
            const color = objectFillColor(object, objectTypes);

            return (
              <div
                key={object.layout_object_id ?? `${object.type}-${object.grid_x}-${object.grid_y}`}
                className={`map-object map-object-${object.type} ${isTarget ? 'is-target' : ''}`}
                style={{
                  left: `${(object.grid_x / layout.grid_width) * 100}%`,
                  top: `${(object.grid_y / layout.grid_height) * 100}%`,
                  width: `${(object.width / layout.grid_width) * 100}%`,
                  height: `${(object.height / layout.grid_height) * 100}%`,
                  background: hexToRgba(color, 0.35),
                  borderColor: color,
                }}
                title={`${objectLabel(object)}${isTarget ? ` / 対象 ${targetCodes.length}件` : ''}`}
              >
                <span>{objectLabel(object)}</span>
                {isTarget && <strong>{targetCodes.length}</strong>}
              </div>
            );
          }))}
        </div>
      )}


    </div>
  );
};
