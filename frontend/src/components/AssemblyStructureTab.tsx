import React, { useState } from 'react';
import { Package, Search } from 'lucide-react';
import { AssemblyStructureView } from './AssemblyStructureModal';

export const AssemblyStructureTab: React.FC = () => {
  const [inputCode, setInputCode] = useState<string>('');
  const [inputName, setInputName] = useState<string>('');
  const [code, setCode] = useState<string>('');
  const [name, setName] = useState<string>('');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const trimmed = inputCode.trim();
    if (!trimmed) return;
    setCode(trimmed);
    setName(inputName.trim());
  };

  return (
    <div className="ast-tab-container">
      <form className="ast-tab-input-bar" onSubmit={handleSubmit}>
        <div className="ast-tab-input-group">
          <label htmlFor="ast-tab-code">コード</label>
          <div className="ast-tab-input-with-icon">
            <Package size={16} className="ast-tab-input-icon" />
            <input
              id="ast-tab-code"
              type="text"
              value={inputCode}
              placeholder="ノードコードを入力"
              onChange={e => setInputCode(e.target.value)}
            />
          </div>
        </div>
        <div className="ast-tab-input-group">
          <label htmlFor="ast-tab-name">名称（任意）</label>
          <input
            id="ast-tab-name"
            type="text"
            value={inputName}
            placeholder="名称"
            onChange={e => setInputName(e.target.value)}
          />
        </div>
        <button type="submit" className="btn btn-primary btn-sm">
          <Search size={14} />
          表示
        </button>
      </form>

      {code ? (
        <AssemblyStructureView code={code} name={name} />
      ) : (
        <div className="ast-tab-empty">
          コードを入力して「表示」を押すと、組立構成図が表示されます。
        </div>
      )}
    </div>
  );
};

export default AssemblyStructureTab;
