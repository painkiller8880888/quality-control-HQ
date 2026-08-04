import React from 'react';
import type { InspectionTarget } from '../types';
import { ShieldAlert, ShieldCheck } from 'lucide-react';

interface WarningSummaryCardProps {
  targets: InspectionTarget[];
}

export const WarningSummaryCard: React.FC<WarningSummaryCardProps> = ({ targets }) => {
  const getJapaneseErrorLabel = (code: string) => {
    const labels: Record<string, string> = {
      UNKNOWN_CODE: '未登録コード',
      DUPLICATE_TARGET: '重複対象',
      MATCH_FAILED: 'OCR読取失敗',
    };
    return labels[code] || code;
  };

  // Aggregate warnings from targets
  const warningCounts: Record<string, number> = {};
  let totalWarnings = 0;
  const targetsWithWarnings = new Set<string>();

  targets.forEach((target) => {
    if (target.warnings && target.warnings.length > 0) {
      target.warnings.forEach((warn) => {
        const code = warn.error_code || 'UNKNOWN';
        warningCounts[code] = (warningCounts[code] || 0) + 1;
        totalWarnings += 1;
        targetsWithWarnings.add(target.code);
      });
    }
  });

  if (totalWarnings === 0) {
    return (
      <div className="card warning-summary-card success-state">
        <div className="card-body-flex">
          <div className="status-icon-container text-emerald">
            <ShieldCheck size={28} />
          </div>
          <div>
            <h3 className="card-subtitle-main">警告サマリ</h3>
            <p className="status-text-desc">現在、取込データに関連する警告（未登録コード、OCR読取失敗、重複など）は発生していません。</p>
          </div>
        </div>
      </div>
    );
  }

  return (
    <div className="card warning-summary-card danger-state">
      <h2 className="card-title text-rose">
        <ShieldAlert className="icon-title" size={20} />
        警告サマリ
      </h2>
      <p className="warning-desc">
        検査対象リスト内に合計 <strong>{totalWarnings}</strong> 件の警告が検出されました（対象品目: <strong>{targetsWithWarnings.size}</strong> 件）。
      </p>

      <div className="warning-grid">
        {Object.entries(warningCounts).map(([code, count]) => (
          <div key={code} className="warning-stat-card">
            <div className="warning-stat-header">
              <span className="warning-type-dot"></span>
              <span className="warning-type-name">{getJapaneseErrorLabel(code)}</span>
            </div>
            <div className="warning-stat-value">
              <strong>{count}</strong> <span className="unit">件</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
};
