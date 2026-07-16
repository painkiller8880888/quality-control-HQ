import React, { useState, useRef, useCallback } from 'react';
import { Search, Plus, X, Check } from 'lucide-react';

interface MasterSearchResult {
  code: string;
  name: string;
  product_category: string | null;
}

interface ManualAddModalProps {
  selectedDate: string;
  onClose: () => void;
  onAdded: () => void;
}

export const ManualAddModal: React.FC<ManualAddModalProps> = ({ selectedDate, onClose, onAdded }) => {
  const [query, setQuery] = useState('');
  const [results, setResults] = useState<MasterSearchResult[]>([]);
  const [selectedCodes, setSelectedCodes] = useState<Set<string>>(new Set());
  const [isSearching, setIsSearching] = useState(false);
  const [isAdding, setIsAdding] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const timerRef = useRef<number | null>(null);

  const handleSearch = useCallback((value: string) => {
    setQuery(value);
    if (timerRef.current) {
      clearTimeout(timerRef.current);
    }
    if (!value.trim()) {
      setResults([]);
      return;
    }
    timerRef.current = window.setTimeout(async () => {
      setIsSearching(true);
      setError(null);
      try {
        const res = await fetch(`/api/masters/search/?q=${encodeURIComponent(value.trim())}`);
        if (!res.ok) throw new Error('検索に失敗しました');
        const data: MasterSearchResult[] = await res.json();
        setResults(data);
      } catch (err: any) {
        setError(err.message);
      } finally {
        setIsSearching(false);
      }
    }, 300);
  }, []);

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
        body: JSON.stringify({ date: selectedDate, codes: Array.from(selectedCodes) }),
      });
      if (!res.ok) {
        const data = await res.json().catch(() => ({}));
        throw new Error(data.message || '追加に失敗しました');
      }
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
          <h3><Plus size={18} /> 品番手動追加</h3>
          <button type="button" className="btn btn-secondary" onClick={onClose}>
            <X size={16} />
          </button>
        </div>
        <div className="modal-body">
          <div className="manual-add-search">
            <Search size={16} className="search-icon" />
            <input
              type="text"
              className="manual-add-input"
              placeholder="品目コードまたは品目名で検索..."
              value={query}
              onChange={e => handleSearch(e.target.value)}
              autoFocus
            />
          </div>

          {error && <p className="manual-add-error">{error}</p>}

          {isSearching && (
            <div className="manual-add-loading">検索中...</div>
          )}

          {!isSearching && results.length > 0 && (
            <>
              <p className="manual-add-result-count">{results.length}件ヒット</p>
              <ul className="manual-add-result-list">
                {results.map(r => (
                  <li
                    key={r.code}
                    className={`manual-add-result-item ${selectedCodes.has(r.code) ? 'selected' : ''}`}
                    onClick={() => toggleSelect(r.code)}
                  >
                    <div className="manual-add-result-info">
                      <span className="manual-add-result-code">{r.code}</span>
                      <span className="manual-add-result-name">{r.name}</span>
                    </div>
                    {selectedCodes.has(r.code) && <Check size={16} className="check-icon" />}
                  </li>
                ))}
              </ul>
            </>
          )}

          {!isSearching && query.trim() && results.length === 0 && (
            <p className="manual-add-no-result">該当する品番が見つかりませんでした</p>
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
            {isAdding ? '追加中...' : `追加 (${selectedCodes.size}件)`}
          </button>
        </div>
      </div>
    </div>
  );
};
