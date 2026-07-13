import React, { useState, useEffect } from 'react';
import { Plus, X, Check, AlertTriangle } from 'lucide-react';
import type { Class9Setting } from '../types';

interface SpecialAddModalProps {
  selectedDate: string;
  onClose: () => void;
  onAdded: () => void;
}

export const SpecialAddModal: React.FC<SpecialAddModalProps> = ({ selectedDate, onClose, onAdded }) => {
  const [settings, setSettings] = useState<Class9Setting[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());
  const [isLoading, setIsLoading] = useState(true);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    fetchSettings();
  }, []);

  const fetchSettings = async () => {
    setIsLoading(true);
    try {
      const res = await fetch('/api/class9-settings/');
      if (!res.ok) throw new Error('特殊検査設定の取得に失敗しました');
      const data: Class9Setting[] = await res.json();
      setSettings(data);
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsLoading(false);
    }
  };

  const toggleSelect = (code: string) => {
    setSelectedCodes(prev => {
      const next = new Set(prev);
      if (next.has(code)) next.delete(code);
      else next.add(code);
      return next;
    });
  };

  const handleAdd = async () => {
    if (selectedCodes.size === 0) return;
    setIsAdding(true);
    setError(null);
    try {
      const res = await fetch('/api/inspection-targets/manual/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          date: selectedDate,
          codes: Array.from(selectedCodes),
          class_override: 9,
        }),
      });
      if (!res.ok) throw new Error('追加に失敗しました');
      onAdded();
      onClose();
    } catch (err: any) {
      setError(err.message);
    } finally {
      setIsAdding(false);
    }
  };

  return (
    <div className="modal-overlay modal-overlay-top" onClick={onClose}>
      <div className="modal-content manual-add-modal card" onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3><Plus size={18} /> 特殊検査追加</h3>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          {error && <p className="manual-add-error">{error}</p>}

          {isLoading && (
            <div className="manual-add-loading">読み込み中...</div>
          )}

          {!isLoading && settings.length === 0 && (
            <div className="no-class9-hint">
              <AlertTriangle size={16} />
              <p>特殊検査(クラス9)に設定された品番がありません。設定タブで登録してください。</p>
            </div>
          )}

          {!isLoading && settings.length > 0 && (
            <>
              <p className="manual-add-result-count">登録済み {settings.length} 件</p>
              <ul className="manual-add-result-list">
                {settings.map(r => (
                  <li
                    key={r.code}
                    className={`manual-add-result-item ${selectedCodes.has(r.code) ? 'selected' : ''}`}
                    onClick={() => toggleSelect(r.code)}
                  >
                    <div className="manual-add-result-info">
                      <span className="manual-add-result-code">{r.code}</span>
                      <span className="manual-add-result-name">{r.name}</span>
                      {r.inspection_sheet_path && (
                        <span className="manual-add-result-path">{r.inspection_sheet_path}</span>
                      )}
                    </div>
                    {selectedCodes.has(r.code) && <Check size={16} className="check-icon" />}
                  </li>
                ))}
              </ul>
            </>
          )}
        </div>
        <div className="modal-footer">
          {selectedCodes.size > 0 && (
            <div className="manual-add-selected-info">{selectedCodes.size}件選択中</div>
          )}
          <button
            className="btn btn-primary"
            onClick={handleAdd}
            disabled={selectedCodes.size === 0 || isAdding}
          >
            {isAdding ? '追加中...' : `特殊検査追加 (${selectedCodes.size}件)`}
          </button>
        </div>
      </div>
    </div>
  );
};