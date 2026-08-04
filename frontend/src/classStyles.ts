export const CLASS_LABELS: Record<number, string> = {
  1: '自動機', 2: '半自動機', 3: 'セッター', 4: 'プレス', 5: '二次加工',
  6: '製品検査(1)', 7: '製品検査(2)', 8: '手動', 9: '特殊検査',
};

export const CLASS_COLORS: Record<number, { bg: string; text: string }> = {
  1: { bg: '#dbeafe', text: '#1e40af' }, 2: { bg: '#fef3c7', text: '#92400e' },
  3: { bg: '#dcfce7', text: '#166534' }, 4: { bg: '#fae8ff', text: '#86198f' },
  5: { bg: '#ffedd5', text: '#9a3412' }, 6: { bg: '#e0e7ff', text: '#3730a3' },
  7: { bg: '#fce7f3', text: '#9d174d' }, 8: { bg: '#f1f5f9', text: '#334155' },
  9: { bg: '#fff1f0', text: '#cf1322' },
};
