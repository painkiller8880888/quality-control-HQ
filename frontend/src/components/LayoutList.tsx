import React, { useEffect, useState, useCallback } from 'react';
import { MapPin, ChevronDown, ChevronUp, GripVertical } from 'lucide-react';
import { DndContext, closestCenter, KeyboardSensor, PointerSensor, useSensor, useSensors, type DragEndEvent } from '@dnd-kit/core';
import { arrayMove, SortableContext, sortableKeyboardCoordinates, verticalListSortingStrategy, useSortable } from '@dnd-kit/sortable';
import { CSS } from '@dnd-kit/utilities';
import type { FactoryMapResponse, LayoutSummary, LayoutObject, LayoutObjectType } from '../types';

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

const STORAGE_KEY = 'layout-list-order';

interface LayoutMapData {
  layout: LayoutSummary;
  mapData: FactoryMapResponse | null;
  isLoading: boolean;
  error: string | null;
  isExpanded: boolean;
}

interface LayoutListProps {
  layouts: LayoutSummary[];
  selectedDate: string;
}

export const LayoutList: React.FC<LayoutListProps> = ({ layouts, selectedDate }) => {
  const [layoutMaps, setLayoutMaps] = useState<LayoutMapData[]>([]);

  const sensors = useSensors(
    useSensor(PointerSensor),
    useSensor(KeyboardSensor, {
      coordinateGetter: sortableKeyboardCoordinates,
    })
  );

  const loadSavedOrder = useCallback(() => {
    try {
      const saved = localStorage.getItem(STORAGE_KEY);
      if (saved) {
        return JSON.parse(saved) as number[];
      }
    } catch {
      // ignore
    }
    return null;
  }, []);

  const saveOrder = useCallback((order: number[]) => {
    try {
      localStorage.setItem(STORAGE_KEY, JSON.stringify(order));
    } catch {
      // ignore
    }
  }, []);

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

    const savedOrder = loadSavedOrder();
    let orderedLayouts = nonDefaultLayouts;
    if (savedOrder) {
      orderedLayouts = [...nonDefaultLayouts].sort((a, b) => {
        const aIndex = savedOrder.indexOf(a.id);
        const bIndex = savedOrder.indexOf(b.id);
        if (aIndex === -1 && bIndex === -1) return 0;
        if (aIndex === -1) return 1;
        if (bIndex === -1) return -1;
        return aIndex - bIndex;
      });
    }

    const initialMaps: LayoutMapData[] = orderedLayouts.map((layout) => ({
      layout,
      mapData: null,
      isLoading: true,
      error: null,
      isExpanded: true,
    }));
    setLayoutMaps(initialMaps);

    const fetchAll = async () => {
      await Promise.all(
        orderedLayouts.map(async (layout, index) => {
          try {
            const response = await fetch(`/api/factory-map/?date=${selectedDate}&layout_id=${layout.id}`);
            if (!response.ok) {
              throw new Error(`見取り図の取得に失敗しました (${response.status})`);
            }
            const data: FactoryMapResponse = await response.json();
            setLayoutMaps((prev) => {
              const next = [...prev];
              next[index] = { ...next[index], mapData: data, isLoading: false };
              return next;
            });
          } catch (err: any) {
            setLayoutMaps((prev) => {
              const next = [...prev];
              next[index] = { ...next[index], isLoading: false, error: err.message || '見取り図の取得に失敗しました。' };
              return next;
            });
          }
        })
      );
    };

    fetchAll();
  }, [layouts, selectedDate, loadSavedOrder]);

  const handleDragEnd = (event: DragEndEvent) => {
    const { active, over } = event;
    if (active.id !== over?.id) {
      setLayoutMaps((items) => {
        const oldIndex = items.findIndex((item) => item.layout.id === active.id);
        const newIndex = items.findIndex((item) => item.layout.id === over?.id);
        const newItems = arrayMove(items, oldIndex, newIndex);
        saveOrder(newItems.map((item) => item.layout.id));
        return newItems;
      });
    }
  };

  const toggleExpanded = (layoutId: number) => {
    setLayoutMaps((prev) =>
      prev.map((item) =>
        item.layout.id === layoutId ? { ...item, isExpanded: !item.isExpanded } : item
      )
    );
  };

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

  return (
    <DndContext
      sensors={sensors}
      collisionDetection={closestCenter}
      onDragEnd={handleDragEnd}
    >
      <SortableContext items={layoutMaps.map((item) => item.layout.id)} strategy={verticalListSortingStrategy}>
        <div className="layout-list-container">
          {layoutMaps.map(({ layout, mapData, isLoading, error, isExpanded }) => (
            <SortableLayoutItem
              key={layout.id}
              id={layout.id}
              layout={layout}
              mapData={mapData}
              isLoading={isLoading}
              error={error}
              isExpanded={isExpanded}
              onToggleExpanded={toggleExpanded}
            />
          ))}
        </div>
      </SortableContext>
    </DndContext>
  );
};

interface SortableLayoutItemProps {
  id: number;
  layout: LayoutSummary;
  mapData: FactoryMapResponse | null;
  isLoading: boolean;
  error: string | null;
  isExpanded: boolean;
  onToggleExpanded: (id: number) => void;
}

const SortableLayoutItem: React.FC<SortableLayoutItemProps> = ({
  id,
  layout,
  mapData,
  isLoading,
  error,
  isExpanded,
  onToggleExpanded,
}) => {
  const {
    attributes,
    listeners,
    setNodeRef,
    transform,
    transition,
    isDragging,
  } = useSortable({ id });

  const style = {
    transform: CSS.Transform.toString(transform),
    transition,
    opacity: isDragging ? 0.5 : 1,
  };

  const handleHeaderClick = (e: React.MouseEvent) => {
    if ((e.target as HTMLElement).closest('[data-drag-handle]')) return;
    onToggleExpanded(id);
  };

  return (
    <div ref={setNodeRef} style={style} className="layout-list-item card">
      <div
        className="layout-list-header"
        onClick={handleHeaderClick}
        style={{ cursor: 'pointer' }}
      >
        <button
          type="button"
          className="drag-handle"
          data-drag-handle
          {...attributes}
          {...listeners}
          aria-label="並び替え"
          title="ドラッグして並び替え"
        >
          <GripVertical size={18} className="text-muted" />
        </button>
        <h3 className="layout-list-title">{layout.layout_name}</h3>
        {isLoading && <div className="pulse-spinner small" />}
        {error && <span className="layout-list-error">{error}</span>}
        <button
          type="button"
          className="expand-toggle"
          onClick={(e) => {
            e.stopPropagation();
            onToggleExpanded(id);
          }}
          aria-label={isExpanded ? '折りたたむ' : '展開'}
        >
          {isExpanded ? <ChevronUp size={18} className="text-muted" /> : <ChevronDown size={18} className="text-muted" />}
        </button>
      </div>

      {isExpanded && (
        <>
          {isLoading ? (
            <div className="map-empty-state">
              <div className="pulse-spinner"></div>
              <p>見取り図を読み込んでいます...</p>
            </div>
          ) : error ? null : !mapData?.layout ? (
            <div className="map-empty-state">
              <MapPin size={28} className="text-muted" />
              <p>見取り図レイアウトがありません。</p>
            </div>
          ) : (
            <div className="factory-map-canvas" style={{ aspectRatio: `${mapData.layout.grid_width} / ${mapData.layout.grid_height}` }}>
              {mapData.layout.background_image_path && (
                <img className="factory-map-bg" src={mapData.layout.background_image_path} alt="" />
              )}
              {mapData.layout.objects.length === 0 ? (
                <div className="map-empty-inset">
                  <MapPin size={28} className="text-muted" />
                  <p>レイアウトにオブジェクトがありません</p>
                </div>
              ) : (
                mapData.layout.objects.map((object) => {
                  const targetCodes = object.machine_id ? (mapData.machines?.find((m) => m.machine_id === object.machine_id)?.target_codes ?? []) : [];
                  const isTarget = targetCodes.length > 0;
                  const color = objectFillColor(object, mapData.layout.object_types);

                  return (
                    <div
                      key={object.layout_object_id ?? `${object.type}-${object.grid_x}-${object.grid_y}`}
                      className={`map-object map-object-${object.type} ${isTarget ? 'is-target' : ''}`}
                      style={{
                        left: `${(object.grid_x / mapData.layout.grid_width) * 100}%`,
                        top: `${(object.grid_y / mapData.layout.grid_height) * 100}%`,
                        width: `${(object.width / mapData.layout.grid_width) * 100}%`,
                        height: `${(object.height / mapData.layout.grid_height) * 100}%`,
                        background: hexToRgba(color, 0.35),
                        borderColor: color,
                      }}
                      title={`${objectLabel(object)}${isTarget ? ` / 対象 ${targetCodes.length}件` : ''}`}
                    >
                      <span>{objectLabel(object)}</span>
                      {isTarget && <strong>{targetCodes.length}</strong>}
                    </div>
                  );
                })
              )}
            </div>
          )}
        </>
      )}
    </div>
  );
};