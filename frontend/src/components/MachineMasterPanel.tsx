import React, { useState, useEffect, useRef, useCallback, useMemo } from 'react';
import { Cpu, Plus, X, Search, Check, Save, Trash2 } from 'lucide-react';
import type { MachineDetail } from '../types';

interface MasterSearchResult {
  code: string;
  name: string;
  product_category: string | null;
}

interface MachineForm {
  machine_no: string;
  machine_name: string;
  shape_type: 'circle' | 'ellipse' | 'rectangle';
  map_x: number;
  map_y: number;
  width: number;
  height: number;
  is_active: boolean;
}

const defaultForm: MachineForm = {
  machine_no: '',
  machine_name: '',
  shape_type: 'circle',
  map_x: 0,
  map_y: 0,
  width: 50,
  height: 50,
  is_active: true,
};

const formatMachineNo = (machineNo: string): string => {
  const num = parseInt(machineNo, 10);
  if (isNaN(num)) return machineNo.padStart(3, '0');
  return num.toString().padStart(3, '0');
};

const getMachineDisplay = (machine: MachineDetail): string => {
  return `${formatMachineNo(machine.machine_no)}:${machine.machine_name}`;
};

export const MachineMasterPanel: React.FC = () => {
  const [machines, setMachines] = useState<MachineDetail[]>([]);
  const [selectedId, setSelectedId] = useState<number | null>(null);
  const [form, setForm] = useState<MachineForm>({ ...defaultForm });
  const [assignments, setAssignments] = useState<{ code: string; name: string }[]>([]);
  const [isSaving, setIsSaving] = useState(false);
  const [message, setMessage] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MasterSearchResult[]>([]);
  const [isSearching, setIsSearching] = useState(false);
  const searchTimerRef = useRef<number | null>(null);

  const sortedMachines = useMemo(() => {
    return [...machines].sort((a, b) => {
      const displayA = getMachineDisplay(a);
      const displayB = getMachineDisplay(b);
      return displayA.localeCompare(displayB);
    });
  }, [machines]);

  useEffect(() => {
    fetchMachines();
  }, []);

  const fetchMachines = async () => {
    try {
      const res = await fetch('/api/machine-master/');
      if (!res.ok) throw new Error('機械データの取得に失敗しました');
      const data: MachineDetail[] = await res.json();
      setMachines(data);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    }
  };

  const selectMachine = (id: number | null) => {
    setSelectedId(id);
    if (id === null) {
      setForm({ ...defaultForm });
      setAssignments([]);
      return;
    }
    const m = machines.find(x => x.id === id);
    if (m) {
      setForm({
        machine_no: m.machine_no,
        machine_name: m.machine_name,
        shape_type: m.shape_type,
        map_x: m.map_x,
        map_y: m.map_y,
        width: m.width,
        height: m.height,
        is_active: m.is_active,
      });
      setAssignments(m.assignments.map(a => ({ ...a })));
    }
  };

  const handleNew = () => {
    selectMachine(null);
  };

  const handleSave = async () => {
    setIsSaving(true);
    setMessage(null);
    try {
      const res = await fetch('/api/machine-master/', {
        method: 'PUT',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          id: selectedId,
          ...form,
          assignments: assignments.map(a => a.code),
        }),
      });
      if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || '保存に失敗しました');
      }
      const saved: MachineDetail = await res.json();
      setMessage({ type: 'success', text: '保存しました' });
      await fetchMachines();
      setSelectedId(saved.id);
    } catch (err: any) {
      setMessage({ type: 'error', text: err.message });
    } finally {
      setIsSaving(false);
    }
  };

  const handleSearch = useCallback((value: string) => {
    setSearchQuery(value);
    if (searchTimerRef.current) clearTimeout(searchTimerRef.current);
    if (!value.trim()) {
      setSearchResults([]);
      return;
    }
    searchTimerRef.current = window.setTimeout(async () => {
      setIsSearching(true);
      try {
        const res = await fetch(`/api/masters/search/?q=${encodeURIComponent(value.trim())}`);
        if (!res.ok) throw new Error('検索に失敗しました');
        const data: MasterSearchResult[] = await res.json();
        setSearchResults(data);
      } catch {
        // ignore
      } finally {
        setIsSearching(false);
      }
    }, 300);
  }, []);

  const addAssignment = (code: string, name: string) => {
    if (assignments.some(a => a.code === code)) return;
    setAssignments(prev => [...prev, { code, name }]);
    setSearchQuery('');
    setSearchResults([]);
  };

  const removeAssignment = (code: string) => {
    setAssignments(prev => prev.filter(a => a.code !== code));
  };

  return (
    <div className="machine-master-layout">
      <div className="machine-master-top card">
        <div className="machine-master-selector">
          <div className="form-group" style={{ flex: 1 }}>
            <label className="form-label"><Cpu size={14} /> 機械選択</label>
            <select
              className="form-control"
              value={selectedId ?? ''}
              onChange={e => selectMachine(e.target.value ? Number(e.target.value) : null)}
            >
              <option value="">-- 選択してください --</option>
              {sortedMachines.map(m => (
                <option key={m.id} value={m.id}>{getMachineDisplay(m)}</option>
              ))}
            </select>
          </div>
          <button className="btn btn-secondary" onClick={handleNew} style={{ marginTop: 22 }}>
            <Plus size={16} /> 新規機械追加
          </button>
        </div>
      </div>

      <div className="machine-master-body">
        <div className="card machine-master-left">
          <h2 className="card-title"><Cpu size={18} /> 機械情報</h2>
          <div className="form-grid">
            <div className="form-group">
              <label className="form-label">機械番号</label>
              <input className="form-control" value={form.machine_no} onChange={e => setForm(f => ({ ...f, machine_no: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label">機械名称</label>
              <input className="form-control" value={form.machine_name} onChange={e => setForm(f => ({ ...f, machine_name: e.target.value }))} />
            </div>
            <div className="form-group">
              <label className="form-label">形状</label>
              <select className="form-control" value={form.shape_type} onChange={e => setForm(f => ({ ...f, shape_type: e.target.value as any }))}>
                <option value="circle">Circle</option>
                <option value="ellipse">Ellipse</option>
                <option value="rectangle">Rectangle</option>
              </select>
            </div>
            <div className="form-row-2col">
              <div className="form-group">
                <label className="form-label">マップ X</label>
                <input type="number" className="form-control" value={form.map_x} onChange={e => setForm(f => ({ ...f, map_x: Number(e.target.value) }))} />
              </div>
              <div className="form-group">
                <label className="form-label">マップ Y</label>
                <input type="number" className="form-control" value={form.map_y} onChange={e => setForm(f => ({ ...f, map_y: Number(e.target.value) }))} />
              </div>
            </div>
            <div className="form-row-2col">
              <div className="form-group">
                <label className="form-label">幅</label>
                <input type="number" className="form-control" value={form.width} onChange={e => setForm(f => ({ ...f, width: Number(e.target.value) }))} />
              </div>
              <div className="form-group">
                <label className="form-label">高さ</label>
                <input type="number" className="form-control" value={form.height} onChange={e => setForm(f => ({ ...f, height: Number(e.target.value) }))} />
              </div>
            </div>
            <div className="form-group">
              <label className="form-label">
                <input type="checkbox" checked={form.is_active} onChange={e => setForm(f => ({ ...f, is_active: e.target.checked }))} style={{ marginRight: 6 }} />
                有効
              </label>
            </div>
          </div>
        </div>

        <div className="card machine-master-right">
          <h2 className="card-title"><Trash2 size={18} /> 割当品番</h2>

          <div className="machine-master-add-code">
            <div className="manual-add-search" style={{ flex: 1 }}>
              <Search size={16} className="search-icon" />
              <input
                type="text"
                className="manual-add-input"
                placeholder="品目コードまたは品目名で検索..."
                value={searchQuery}
                onChange={e => handleSearch(e.target.value)}
              />
            </div>
          </div>

          {isSearching && <div className="manual-add-loading">検索中...</div>}

          {searchResults.length > 0 && (
            <ul className="manual-add-result-list" style={{ marginBottom: 12 }}>
              {searchResults.map(r => (
                <li
                  key={r.code}
                  className={`manual-add-result-item ${assignments.some(a => a.code === r.code) ? 'selected' : ''}`}
                  onClick={() => addAssignment(r.code, r.name)}
                >
                  <div className="manual-add-result-info">
                    <span className="manual-add-result-code">{r.code}</span>
                    <span className="manual-add-result-name">{r.name}</span>
                  </div>
                  {assignments.some(a => a.code === r.code) && <Check size={16} className="check-icon" />}
                </li>
              ))}
            </ul>
          )}

          <div className="machine-master-assign-list">
            {assignments.length === 0 ? (
              <p className="empty-text" style={{ padding: 16, textAlign: 'center' }}>割当品番なし</p>
            ) : (
              assignments.map(a => (
                <div key={a.code} className="machine-master-assign-item">
                  <div className="machine-master-assign-info">
                    <span className="machine-master-assign-code">{a.code}</span>
                    <span className="machine-master-assign-name">{a.name}</span>
                  </div>
                  <button className="btn btn-icon-only btn-secondary" onClick={() => removeAssignment(a.code)} title="削除">
                    <X size={14} />
                  </button>
                </div>
              ))
            )}
          </div>
        </div>
      </div>

      {message && (
        <div className={`machine-master-message ${message.type}`}>
          {message.text}
        </div>
      )}

      <div className="machine-master-footer">
        <button className="btn btn-primary" onClick={handleSave} disabled={isSaving}>
          <Save size={16} /> {isSaving ? '保存中...' : '更新'}
        </button>
      </div>
    </div>
  );
};