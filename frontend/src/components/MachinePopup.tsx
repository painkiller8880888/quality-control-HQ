import React from 'react';
import { X, Target, Plus, ScrollText } from 'lucide-react';
import type { AssignedItem, InspectionTarget } from '../types';

interface MachinePopupProps {
  machineNo: string;
  machineId: number;
  machineName: string;
  assignedItems: AssignedItem[];
  targetCodes: string[];
  targets: InspectionTarget[];
  onClose: () => void;
  onScrollToTarget: (targetId: number) => void;
  onRegisterTarget: (machineId: number, code: string) => void;
}

export const MachinePopup: React.FC<MachinePopupProps> = ({
  machineNo,
  machineId,
  machineName,
  assignedItems,
  targetCodes,
  targets,
  onClose,
  onScrollToTarget,
  onRegisterTarget,
}) => {
  const processTargets = targets.filter(
    t => targetCodes.includes(t.code) && t.category !== null && t.category >= 1 && t.category <= 5,
  );
  const targetCodeSet = new Set(processTargets.map(t => t.code));
  const registeredTargetMap = new Map<string, InspectionTarget>();
  for (const t of processTargets) {
    registeredTargetMap.set(t.code, t);
  }

  const sortedItems = [...assignedItems].sort((a, b) => {
    const aIsTarget = targetCodeSet.has(a.code) ? 0 : 1;
    const bIsTarget = targetCodeSet.has(b.code) ? 0 : 1;
    return aIsTarget - bIsTarget;
  });

  return (
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal-content machine-popup card" onClick={(e) => e.stopPropagation()}>
        <div className="modal-header">
          <h3>
            <Target size={18} />
            {machineNo} {machineName}
          </h3>
          <button
            type="button"
            className="btn btn-secondary"
            style={{ padding: '4px 8px' }}
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          <p className="machine-popup-subtitle">
            登録品目 ({assignedItems.length}件)
          </p>
          <ul className="machine-popup-list">
            {sortedItems.map((item) => {
              const isRegistered = targetCodeSet.has(item.code);
              const registeredTarget = registeredTargetMap.get(item.code);
              return (
                <li
                  key={item.code}
                  className={`machine-popup-item ${isRegistered ? 'is-registered' : ''}`}
                  onClick={() => {
                    if (isRegistered && registeredTarget) {
                      onScrollToTarget(registeredTarget.target_id);
                      onClose();
                    } else if (!isRegistered) {
                      onRegisterTarget(machineId, item.code);
                    }
                  }}
                >
                  <div className="machine-popup-item-info">
                    <span className="machine-popup-item-code">{item.code}</span>
                    <span className="machine-popup-item-name">{item.name}</span>
                  </div>
                  <div className="machine-popup-item-action">
                    {isRegistered ? (
                      <span className="machine-popup-badge registered-badge">
                        <ScrollText size={12} />
                        登録済
                      </span>
                    ) : (
                      <span className="machine-popup-badge unregistered-badge">
                        <Plus size={12} />
                        追加
                      </span>
                    )}
                  </div>
                </li>
              );
            })}
          </ul>
        </div>
      </div>
    </div>
  );
};
