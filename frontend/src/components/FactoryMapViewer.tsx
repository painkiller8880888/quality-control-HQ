import React from 'react';
import { AlertTriangle, Map as MapIcon, MapPin } from 'lucide-react';
import type { FactoryMapResponse, LayoutObject } from '../types';

interface FactoryMapViewerProps {
  mapData: FactoryMapResponse | null;
  isLoading: boolean;
  selectedDate: string;
}

const objectLabel = (object: LayoutObject) => {
  if (object.machine_name) return object.machine_name;
  if (object.object_name) return object.object_name;
  return object.type;
};

export const FactoryMapViewer: React.FC<FactoryMapViewerProps> = ({ mapData, isLoading, selectedDate }) => {
  const layout = mapData?.layout;
  const objects = layout?.objects ?? [];
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
      ) : !layout || objects.length === 0 ? (
        <div className="map-empty-state">
          <MapPin size={28} className="text-muted" />
          <p>見取り図レイアウトがまだ登録されていません。</p>
        </div>
      ) : (
        <div className="factory-map-canvas" style={{ aspectRatio: `${layout.grid_width} / ${layout.grid_height}` }}>
          {layout.background_image_path && (
            <img className="factory-map-bg" src={layout.background_image_path} alt="" />
          )}
          {objects.map((object) => {
            const targetCodes = object.machine_id ? machineTargets.get(object.machine_id) ?? [] : [];
            const isTarget = targetCodes.length > 0;

            return (
              <div
                key={object.layout_object_id ?? `${object.type}-${object.grid_x}-${object.grid_y}`}
                className={`map-object map-object-${object.type} ${isTarget ? 'is-target' : ''}`}
                style={{
                  left: `${(object.grid_x / layout.grid_width) * 100}%`,
                  top: `${(object.grid_y / layout.grid_height) * 100}%`,
                  width: `${(object.width / layout.grid_width) * 100}%`,
                  height: `${(object.height / layout.grid_height) * 100}%`,
                }}
                title={`${objectLabel(object)}${isTarget ? ` / 対象 ${targetCodes.length}件` : ''}`}
              >
                <span>{objectLabel(object)}</span>
                {isTarget && <strong>{targetCodes.length}</strong>}
              </div>
            );
          })}
        </div>
      )}

      {mapData && mapData.warnings.length > 0 && (
        <div className="map-warning-strip">
          <AlertTriangle size={15} />
          <span>機械割当なし: {mapData.warnings.map((warning) => warning.code).join(', ')}</span>
        </div>
      )}
    </div>
  );
};
