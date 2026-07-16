import React, { useEffect, useMemo, useState } from 'react';
import { BarChart3, ChevronDown, ChevronRight, Download, Filter, MessageSquareText } from 'lucide-react';
import { CLASS_COLORS, CLASS_LABELS } from '../classStyles';

type Inspector = { user_id: number | null; name: string; total: number; classes: Record<string, number> };
type Note = { user_id: number | null; inspector: string; note: string };
type Day = { date: string; total: number; classes: Record<string, number>; inspectors: Inspector[]; notes: Note[] };
type Summary = { months: string[]; class_totals: Record<string, number>; top_items: { code: string; name: string; count: number }[]; days: Day[] };

const allClasses = () => new Set(Object.keys(CLASS_LABELS).map(Number));
const monthPeriod = (month: string) => {
  const [year, value] = month.split('-').map(Number);
  return { start: `${month}-01`, end: `${month}-${new Date(year, value, 0).getDate()}` };
};
const dateKey = (year: number, month: number, day: number) =>
  `${year}-${String(month).padStart(2, '0')}-${String(day).padStart(2, '0')}`;
const nthMonday = (year: number, month: number, nth: number) => {
  const firstDay = new Date(year, month - 1, 1).getDay();
  return 1 + ((8 - firstDay) % 7) + (nth - 1) * 7;
};
const equinoxDay = (year: number, spring: boolean) => {
  if (year <= 1979) return Math.floor((spring ? 20.8357 : 23.2588) + 0.242194 * (year - 1980) - Math.floor((year - 1983) / 4));
  if (year <= 2099) return Math.floor((spring ? 20.8431 : 23.2488) + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4));
  return Math.floor((spring ? 21.851 : 24.2488) + 0.242194 * (year - 1980) - Math.floor((year - 1980) / 4));
};

const japaneseHolidays = (year: number) => {
  const holidays = new Set<string>();
  const add = (month: number, day: number) => holidays.add(dateKey(year, month, day));
  if (year < 1948 || year > 2150) return holidays;

  if (year >= 1949) {
    add(1, 1);
    add(1, year >= 2000 ? nthMonday(year, 1, 2) : 15);
    if (year >= 1967) add(2, 11);
    if (year >= 2020) add(2, 23); else if (year >= 1989 && year <= 2018) add(12, 23);
    add(3, equinoxDay(year, true));
    add(4, 29);
    add(5, 3);
    if (year >= 2007) add(5, 4);
    add(5, 5);
  }
  if (year >= 1996 && year <= 2002) add(7, 20);
  if (year >= 2003 && year !== 2020 && year !== 2021) add(7, nthMonday(year, 7, 3));
  if (year >= 2016 && year !== 2020 && year !== 2021) add(8, 11);
  if (year >= 1966) add(9, year >= 2003 ? nthMonday(year, 9, 3) : 15);
  add(9, equinoxDay(year, false));
  if (year >= 1966 && year !== 2020 && year !== 2021) add(10, year >= 2000 ? nthMonday(year, 10, 2) : 10);
  add(11, 3);
  add(11, 23);

  if (year === 1959) add(4, 10);
  if (year === 1989) add(2, 24);
  if (year === 1990) add(11, 12);
  if (year === 1993) add(6, 9);
  if (year === 2019) { add(5, 1); add(10, 22); }
  if (year === 2020) { add(7, 23); add(7, 24); add(8, 10); }
  if (year === 2021) { add(7, 22); add(7, 23); add(8, 8); }

  // 国民の休日制度は1986年から適用。日曜は制度の対象外。
  if (year >= 1986) {
    const date = new Date(year, 0, 2);
    while (date.getFullYear() === year) {
      const key = dateKey(year, date.getMonth() + 1, date.getDate());
      const previous = new Date(date); previous.setDate(previous.getDate() - 1);
      const next = new Date(date); next.setDate(next.getDate() + 1);
      if (date.getDay() !== 0 && !holidays.has(key)
        && holidays.has(dateKey(previous.getFullYear(), previous.getMonth() + 1, previous.getDate()))
        && holidays.has(dateKey(next.getFullYear(), next.getMonth() + 1, next.getDate()))) holidays.add(key);
      date.setDate(date.getDate() + 1);
    }
  }

  // 振替休日制度は1973-04-12施行。2007年からは次の非祝日まで繰り越す。
  if (year >= 1973) {
    for (const holiday of [...holidays]) {
      const date = new Date(`${holiday}T00:00:00`);
      if (date.getDay() !== 0 || (year === 1973 && date < new Date(1973, 3, 12))) continue;
      do date.setDate(date.getDate() + 1); while (year >= 2007 && holidays.has(dateKey(date.getFullYear(), date.getMonth() + 1, date.getDate())));
      holidays.add(dateKey(date.getFullYear(), date.getMonth() + 1, date.getDate()));
    }
  }
  return holidays;
};

const holidayCache = new Map<number, Set<string>>();
// Exported for deterministic holiday regression checks without rendering the component.
// eslint-disable-next-line react-refresh/only-export-components
export const isJapaneseBusinessDay = (value: string) => {
  const [year, month, day] = value.split('-').map(Number);
  const date = new Date(year, month - 1, day);
  if (date.getDay() === 0 || date.getDay() === 6) return false;
  if (!holidayCache.has(year)) holidayCache.set(year, japaneseHolidays(year));
  return !holidayCache.get(year)?.has(value);
};

const inspectorToken = (userId: number | null) => userId === null ? 'unknown' : String(userId);
const inspectorName = (inspector: Inspector) => inspector.name?.trim() || '不明な検査者';

const SummaryFilterPicker = ({ classes, onClassesChange, inspectors, selectedInspectors, onInspectorsChange, onInspectorsSelectAll, onClose }: {
  classes: Set<number>;
  onClassesChange: (value: Set<number>) => void;
  inspectors: Inspector[];
  selectedInspectors: Set<string>;
  onInspectorsChange: (value: Set<string>) => void;
  onInspectorsSelectAll: () => void;
  onClose: () => void;
}) => {
  const nameCounts = new Map<string, number>();
  inspectors.forEach(inspector => {
    const name = inspectorName(inspector);
    nameCounts.set(name, (nameCounts.get(name) || 0) + 1);
  });

  return <div className="summary-filter-popover">
    <div className="summary-filter-pane">
      <strong>クラス</strong>
      <div className="summary-filter-actions"><button type="button" onClick={() => onClassesChange(allClasses())}>全選択</button><button type="button" onClick={() => onClassesChange(new Set())}>全解除</button></div>
      {Object.entries(CLASS_LABELS).map(([key, label]) => {
        const no = Number(key);
        return <label key={no}><input type="checkbox" checked={classes.has(no)} onChange={() => {
          const next = new Set(classes);
          if (next.has(no)) next.delete(no); else next.add(no);
          onClassesChange(next);
        }} />{label}</label>;
      })}
    </div>
    <div className="summary-filter-pane">
      <strong>検査者</strong>
      <div className="summary-filter-actions"><button type="button" onClick={onInspectorsSelectAll}>全選択</button><button type="button" onClick={() => onInspectorsChange(new Set())}>全解除</button></div>
      {inspectors.map(inspector => {
        const token = inspectorToken(inspector.user_id);
        const name = inspectorName(inspector);
        const label = (nameCounts.get(name) || 0) > 1 ? `${name} (#${inspector.user_id ?? 'unknown'})` : name;
        return <label key={token}><input type="checkbox" checked={selectedInspectors.has(token)} onChange={() => {
          const next = new Set(selectedInspectors);
          if (next.has(token)) next.delete(token); else next.add(token);
          onInspectorsChange(next);
        }} />{label}</label>;
      })}
    </div>
    <button className="btn btn-sm summary-filter-close" onClick={onClose}>閉じる</button>
  </div>;
};

const NoteIcon = ({ notes }: { notes: string[] }) => {
  if (notes.length === 0) return null;
  const text = notes.join('\n');
  return <span className="note-indicator" title={text} aria-label={`ノート: ${text}`} tabIndex={0}><MessageSquareText size={15} /></span>;
};

export const InspectionSummary: React.FC = () => {
  const now = new Date();
  const currentMonth = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, '0')}`;
  const initial = monthPeriod(currentMonth);
  const [month, setMonth] = useState(currentMonth);
  const [start, setStart] = useState(initial.start);
  const [end, setEnd] = useState(initial.end);
  const [data, setData] = useState<Summary | null>(null);
  const [error, setError] = useState('');
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [topClasses, setTopClasses] = useState(allClasses);
  const [graphClasses, setGraphClasses] = useState(allClasses);
  const [topInspectors, setTopInspectors] = useState<Set<string> | null>(null);
  const [graphInspectors, setGraphInspectors] = useState<Set<string> | null>(null);
  const [picker, setPicker] = useState<'top' | 'graph' | null>(null);
  const [hoveredPoint, setHoveredPoint] = useState<number | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    const params = new URLSearchParams({ start, end, classes: [...topClasses].join(',') });
    if (topInspectors !== null) params.set('inspectors', [...topInspectors].join(','));
    fetch(`/api/inspection-summary/?${params}`, { signal: controller.signal })
      .then(async response => {
        if (!response.ok) throw new Error((await response.json()).message || '集計を取得できませんでした');
        setData(await response.json());
        setError('');
      })
      .catch(reason => { if ((reason as DOMException).name !== 'AbortError') setError(reason.message); });
    return () => controller.abort();
  }, [start, end, topClasses, topInspectors]);

  const inspectorOptions = useMemo(() => {
    const options = new Map<string, Inspector>();
    data?.days.forEach(day => day.inspectors.forEach(inspector => {
      if (inspector.total > 0) options.set(inspectorToken(inspector.user_id), inspector);
    }));
    return [...options.values()];
  }, [data]);
  const allInspectorTokens = useMemo(() => new Set(inspectorOptions.map(inspector => inspectorToken(inspector.user_id))), [inspectorOptions]);
  const selectedTopInspectors = topInspectors ?? allInspectorTokens;
  const selectedGraphInspectors = graphInspectors ?? allInspectorTokens;

  const businessDays = useMemo(() => {
    return data?.days.filter(day => isJapaneseBusinessDay(day.date)) || [];
  }, [data]);
  const graphPoints = useMemo(() => businessDays.map(day => ({
    date: day.date,
    value: day.inspectors
      .filter(inspector => selectedGraphInspectors.has(inspectorToken(inspector.user_id)))
      .reduce((total, inspector) => total + [...graphClasses].reduce((sum, no) => sum + (inspector.classes[String(no)] || 0), 0), 0),
  })), [businessDays, graphClasses, selectedGraphInspectors]);
  const maxGraph = Math.max(1, ...graphPoints.map(point => point.value));
  const pointPosition = (value: number, index: number) => ({
    x: graphPoints.length === 1 ? 50 : index * 100 / (graphPoints.length - 1),
    y: 95 - value * 85 / maxGraph,
  });
  const line = graphPoints.map((point, index) => {
    const position = pointPosition(point.value, index);
    return `${position.x},${position.y}`;
  }).join(' ');

  const exportCsv = async (type: 'counts' | 'notes') => {
    const response = await fetch(`/api/inspection-summary/csv/${type}/?start=${start}&end=${end}`);
    if (!response.ok) { setError('CSVを出力できませんでした'); return; }
    const blob = await response.blob();
    const filename = `inspection-${type}_${start}_${end}.csv`;
    const pickerApi = (window as Window & { showDirectoryPicker?: () => Promise<{ getFileHandle: (name: string, options: { create: boolean }) => Promise<{ createWritable: () => Promise<{ write: (value: Blob) => Promise<void>; close: () => Promise<void> }> }> }> }).showDirectoryPicker;
    if (pickerApi) {
      try {
        const dir = await pickerApi.call(window);
        const file = await dir.getFileHandle(filename, { create: true });
        const writer = await file.createWritable();
        await writer.write(blob);
        await writer.close();
        return;
      } catch (reason) {
        if ((reason as DOMException).name === 'AbortError') return;
      }
    }
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    anchor.click();
    URL.revokeObjectURL(url);
  };
  const changeMonth = (value: string) => {
    setTopInspectors(null);
    setGraphInspectors(null);
    setMonth(value);
    const period = monthPeriod(value);
    setStart(period.start);
    setEnd(period.end);
  };

  return <div className="inspection-summary-page">
    <section className="card summary-controls">
      <div className="summary-control-fields">
        <label>月<select value={month} onChange={event => changeMonth(event.target.value)}>{[...new Set([currentMonth, ...(data?.months || [])])].map(value => <option key={value}>{value}</option>)}</select></label>
        <div className="summary-date-range"><label>開始<input type="date" value={start} onChange={event => { setTopInspectors(null); setGraphInspectors(null); setStart(event.target.value); }} /></label><label>終了<input type="date" value={end} onChange={event => { setTopInspectors(null); setGraphInspectors(null); setEnd(event.target.value); }} /></label></div>
        <div className="summary-csv-actions"><button className="btn btn-sm" onClick={() => void exportCsv('counts')}><Download size={14} />検査回数CSV</button><button className="btn btn-sm" onClick={() => void exportCsv('notes')}><Download size={14} />ノートCSV</button></div>
        {error && <p className="auth-error">{error}</p>}
      </div>
      <div className="summary-category-section">
        <h3>カテゴリ別検査回数</h3>
        <div className="warning-summary-badges class-count-grid">{Object.entries(CLASS_LABELS).map(([key, label]) => {
          const colors = CLASS_COLORS[Number(key)];
          return <div key={key} className="warning-summary-badge" style={{ borderColor: colors.text }}><span className="warning-badge-label" style={{ background: colors.bg, color: colors.text }}>{label}</span><span className="warning-badge-count" style={{ background: colors.text }}>{data?.class_totals[key] || 0}件</span></div>;
        })}</div>
      </div>
    </section>

    <section className="card summary-overview">
      <div className="summary-subheading summary-subheading-first"><h3>上位10品目</h3><button className="btn btn-sm" onClick={() => setPicker(picker === 'top' ? null : 'top')}><Filter size={14} />フィルタ</button>{picker === 'top' && <SummaryFilterPicker classes={topClasses} onClassesChange={setTopClasses} inspectors={inspectorOptions} selectedInspectors={selectedTopInspectors} onInspectorsChange={setTopInspectors} onInspectorsSelectAll={() => setTopInspectors(null)} onClose={() => setPicker(null)} />}</div>
      <div className="summary-top-items-wrap"><table className="summary-top-items"><thead><tr><th>品名</th><th>コード</th><th>回数</th></tr></thead><tbody>{data?.top_items.map(item => <tr key={item.code}><td>{item.name}</td><td><small>{item.code}</small></td><td>{item.count}</td></tr>)}</tbody></table></div>
      <div className="summary-subheading"><h3><BarChart3 size={16} />日ごとの検査回数</h3><button className="btn btn-sm" onClick={() => setPicker(picker === 'graph' ? null : 'graph')}><Filter size={14} />フィルタ</button>{picker === 'graph' && <SummaryFilterPicker classes={graphClasses} onClassesChange={setGraphClasses} inspectors={inspectorOptions} selectedInspectors={selectedGraphInspectors} onInspectorsChange={setGraphInspectors} onInspectorsSelectAll={() => setGraphInspectors(null)} onClose={() => setPicker(null)} />}</div>
      <div className="summary-line-chart">
        {graphPoints.length > 0 ? <>
          <div className="summary-chart-plot">
            <svg viewBox="0 0 100 100" preserveAspectRatio="none" aria-label="営業日ごとの検査回数">
              <polyline points={line} fill="none" stroke="var(--primary-color, #2563eb)" strokeWidth="2" vectorEffect="non-scaling-stroke" />
            </svg>
            {graphPoints.map((point, index) => {
              const position = pointPosition(point.value, index);
              const width = 100 / graphPoints.length;
              return <button key={point.date} type="button" className="summary-chart-point" style={{ left: `${Math.max(0, position.x - width / 2)}%`, top: 0, width: `${width}%`, height: '100%' }} onMouseEnter={() => setHoveredPoint(index)} onMouseLeave={() => setHoveredPoint(null)} onFocus={() => setHoveredPoint(index)} onBlur={() => setHoveredPoint(null)} aria-label={`${point.date}: ${point.value}件`}>
                <span className="summary-chart-dot" style={{ left: `${graphPoints.length === 1 ? 50 : (position.x - Math.max(0, position.x - width / 2)) / width * 100}%`, top: `${position.y}%` }} />
              </button>;
            })}
            {hoveredPoint !== null && graphPoints[hoveredPoint] && (() => {
            const point = graphPoints[hoveredPoint];
            const position = pointPosition(point.value, hoveredPoint);
            return <div className="summary-chart-tooltip" style={{ left: `${position.x}%`, top: `${position.y}%` }}><span>{point.date}</span><strong>実績 {point.value}件</strong></div>;
            })()}
          </div>
          <div className="chart-axis"><span>{graphPoints[0].date}</span><strong>最大 {maxGraph}</strong><span>{graphPoints.at(-1)?.date}</span></div>
        </> : <p className="summary-chart-empty">対象期間に営業日がありません</p>}
      </div>
    </section>

    <section className="card summary-details">
      <h3>日別詳細</h3>
      <div className="summary-table-wrap"><table><thead><tr><th></th><th>日付</th><th>総数</th>{Object.entries(CLASS_LABELS).map(([key, label]) => <th key={key} style={{ background: CLASS_COLORS[Number(key)].bg, color: CLASS_COLORS[Number(key)].text }}>{label}</th>)}<th>ノート</th></tr></thead><tbody>{data?.days.map(day => <React.Fragment key={day.date}>
        <tr><td><button className="summary-expand" aria-label={`${day.date}の検査者別内訳を${expanded.has(day.date) ? '閉じる' : '開く'}`} onClick={() => {
          const next = new Set(expanded);
          if (next.has(day.date)) next.delete(day.date); else next.add(day.date);
          setExpanded(next);
        }}>{expanded.has(day.date) ? <ChevronDown /> : <ChevronRight />}</button></td><td>{day.date}</td><td>{day.total}</td>{Object.keys(CLASS_LABELS).map(no => <td key={no}>{day.classes[no]}</td>)}<td><NoteIcon notes={day.notes.map(note => `${note.inspector}: ${note.note}`)} /></td></tr>
        {expanded.has(day.date) && day.inspectors.map(person => <tr className="inspector-row" key={`${day.date}-${person.user_id ?? 'unknown'}`}><td></td><td>{person.name}</td><td>{person.total}</td>{Object.keys(CLASS_LABELS).map(no => <td key={no}>{person.classes[no]}</td>)}<td><NoteIcon notes={day.notes.filter(note => note.user_id === person.user_id).map(note => note.note)} /></td></tr>)}
      </React.Fragment>)}</tbody></table></div>
    </section>
  </div>;
};
