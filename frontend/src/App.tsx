import React, { useState, useEffect, useRef } from 'react';
import { ImportForm } from './components/ImportForm';
import { ImportSummary } from './components/ImportSummary';
import { SettingsPanel } from './components/SettingsPanel';

import { TargetsTable } from './components/TargetsTable';
import { LayoutList } from './components/LayoutList';
import { FactoryMapCreator } from './components/FactoryMapCreator';
import type { Job, InspectionTarget, ApiError, LayoutSummary } from './types';
import { ShieldAlert, RefreshCw, Layers, Map as MapIcon, Settings, PanelLeftClose, PanelLeftOpen, Sun, Moon, Palette } from 'lucide-react';

type ThemeMode = 'normal' | 'dark' | 'solarized-light' | 'solarized-dark';

const THEME_CYCLE: ThemeMode[] = ['normal', 'dark', 'solarized-light', 'solarized-dark'];

const THEME_LABELS: Record<ThemeMode, string> = {
  'normal': 'Normal',
  'dark': 'Dark',
  'solarized-light': 'Solarized Light',
  'solarized-dark': 'Solarized Dark',
};

const getNextTheme = (current: ThemeMode): ThemeMode => {
  const idx = THEME_CYCLE.indexOf(current);
  return THEME_CYCLE[(idx + 1) % THEME_CYCLE.length];
};

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'mapCreator' | 'settings'>('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [sidebarSegment, setSidebarSegment] = useState<'import' | 'status'>('import');
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [targets, setTargets] = useState<InspectionTarget[]>([]);
  const [isLoadingJob, setIsLoadingJob] = useState<boolean>(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState<boolean>(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [theme, setTheme] = useState<ThemeMode>(() => {
    if (typeof window !== 'undefined') {
      return (localStorage.getItem('theme') as ThemeMode) || 'normal';
    }
    return 'normal';
  });
  const [layouts, setLayouts] = useState<LayoutSummary[]>([]);
  const [activeLayoutId, setActiveLayoutId] = useState<number | null>(null);
  const [highlightedTargetCode, setHighlightedTargetCode] = useState<string | null>(null);
  const [highlightedTargetId, setHighlightedTargetId] = useState<number | null>(null);
  const [fontSize, setFontSize] = useState<number>(() => {
    if (typeof window !== 'undefined') {
      return parseFloat(localStorage.getItem('fontSize') || '17.33');
    }
    return 17.33;
  });

  const pollingTimerRef = useRef<any>(null);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    document.documentElement.style.setProperty('--font-size-base', `${fontSize}px`);
    localStorage.setItem('fontSize', String(fontSize));
  }, [fontSize]);

  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    fetchLayouts();
  }, []);

  const fetchLayouts = async () => {
    try {
      const response = await fetch('/api/factory-map/layouts/');
      if (response.ok) {
        const data: LayoutSummary[] = await response.json();
        setLayouts(data);
        if (data.length > 0 && activeLayoutId === null) {
          setActiveLayoutId(data[0].id);
        }
      }
    } catch {
      // ignore
    }
  };

  const fetchTargets = async (date: string) => {
    if (!date) return;
    setIsLoadingTargets(true);
    setGlobalError(null);

    try {
      const response = await fetch(`/api/inspection-targets/?date=${date}`);
      if (!response.ok) {
        let errMsg = `エラーが発生しました (${response.status})`;
        try {
          const errData: ApiError = await response.json();
          errMsg = `${getJapaneseErrorLabel(errData.error_code)}: ${errData.message}`;
        } catch {
          // ignore
        }
        throw new Error(errMsg);
      }
      const data: InspectionTarget[] = await response.json();
      setTargets(data);
    } catch (err: any) {
      setGlobalError(err.message || '検査対象の取得に失敗しました。');
      setTargets([]);
    } finally {
      setIsLoadingTargets(false);
    }
  };

  const getJapaneseErrorLabel = (code: string) => {
    const labels: Record<string, string> = {
      UNKNOWN_CODE: '未登録コード',
      DUPLICATE_TARGET: '重複対象',
      MATCH_FAILED: 'OCR読取失敗',
      INVALID_REQUEST: '無効なリクエスト',
    };
    return labels[code] || code;
  };

  const startPolling = (jobId: string, date: string) => {
    if (pollingTimerRef.current) {
      clearInterval(pollingTimerRef.current);
    }

    setIsLoadingJob(true);

    pollingTimerRef.current = setInterval(async () => {
      try {
        const response = await fetch(`/api/jobs/${jobId}/`);
        if (!response.ok) {
          throw new Error(`ジョブの取得に失敗しました (${response.status})`);
        }
        const jobData: Job = await response.json();
        setCurrentJob(jobData);

        if (jobData.status === 'succeeded' || jobData.status === 'failed') {
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsLoadingJob(false);

          if (jobData.status === 'succeeded') {
            fetchTargets(date);
          }
        }
      } catch (err: any) {
        console.error(err);
        setGlobalError(err.message || 'ジョブの追跡中にエラーが発生しました。');
        if (pollingTimerRef.current) {
          clearInterval(pollingTimerRef.current);
          pollingTimerRef.current = null;
        }
        setIsLoadingJob(false);
      }
    }, 2500);
  };

  const handleImportStart = async (targetDate: string, scanFile: File | null, excelFile: File | null) => {
    setGlobalError(null);
    setIsLoadingJob(true);
    setSelectedDate(targetDate);
    setCurrentJob(null);

    const formData = new FormData();
    formData.append('target_date', targetDate);
    if (scanFile) {
      formData.append('scan_file', scanFile);
    }
    if (excelFile) {
      formData.append('excel_file', excelFile);
    }

    try {
      const response = await fetch('/api/plans/import/', {
        method: 'POST',
        body: formData,
      });

      if (!response.ok) {
        let errMsg = `取込要求が拒否されました (${response.status})`;
        try {
          const errData: ApiError = await response.json();
          errMsg = `${getJapaneseErrorLabel(errData.error_code)}: ${errData.message}`;
        } catch {
          // ignore
        }
        throw new Error(errMsg);
      }

      const resData = await response.json();
      const jobId = resData.job_id;

      setCurrentJob({
        job_id: jobId,
        job_type: 'PLANS_IMPORT',
        status: 'queued',
        started_at: new Date().toISOString(),
        finished_at: null,
        error_message: null,
        result: null,
      });

      startPolling(jobId, targetDate);
    } catch (err: any) {
      setGlobalError(err.message || '取込処理の開始に失敗しました。');
      setIsLoadingJob(false);
    }
  };

  const handleRefreshTargets = () => {
    if (selectedDate) {
      fetchTargets(selectedDate);
    }
  };

  const handleScrollToTarget = (targetId: number) => {
    setHighlightedTargetId(targetId);
    const matched = targets.find((t) => t.target_id === targetId);
    if (matched) {
      setHighlightedTargetCode(matched.code);
    }
    setTimeout(() => {
      setHighlightedTargetId((prev) => (prev === targetId ? null : prev));
      setHighlightedTargetCode((prev) => (prev === (targets.find((t) => t.target_id === targetId)?.code ?? null) ? null : prev));
    }, 2500);
  };

  const handleRegisterTarget = async (code: string) => {
    if (!selectedDate) return;
    try {
      const response = await fetch('/api/inspection-targets/manual/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: selectedDate, codes: [code] }),
      });
      if (!response.ok) {
        console.error('手動追加に失敗しました');
        return;
      }
      await fetchTargets(selectedDate);
    } catch (err) {
      console.error('手動追加エラー:', err);
    }
  };

  const handleTargetClick = (target: InspectionTarget) => {
    setHighlightedTargetId(target.target_id);
    setHighlightedTargetCode(target.code);
    setTimeout(() => {
      setHighlightedTargetId((prev) => (prev === target.target_id ? null : prev));
      setHighlightedTargetCode((prev) => (prev === target.code ? null : prev));
    }, 2500);
  };

  const handleDeleteTargets = async (date: string, targetIds: number[]) => {
    const response = await fetch('/api/inspection-targets/bulk-delete/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, target_ids: targetIds }),
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.message || '削除に失敗しました');
    }
    setTargets(prev => prev.filter(t => !targetIds.includes(t.target_id)));
  };

  const handleCheckUpdate = (date: string, items: { code: string; checks: Record<string, boolean> }[]) => {
    setTargets(prev => prev.map(t => {
      const item = items.find(i => i.code === t.code);
      if (!item) return t;
      const newChecks = { ...t.checks };
      for (const [slot, checked] of Object.entries(item.checks)) {
        newChecks[slot as keyof typeof newChecks] = checked;
      }
      return { ...t, checks: newChecks };
    }));

    fetch('/api/history/bulk-upsert/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, items }),
    }).then(res => {
      if (!res.ok) fetchTargets(date);
    }).catch(() => fetchTargets(date));
  };

  const themeIcon = theme === 'normal' ? <Palette size={16} /> : theme === 'dark' ? <Moon size={16} /> : theme === 'solarized-light' ? <Sun size={16} /> : <Moon size={16} />;

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-logo-section">
          <div className="header-logo">
            <Layers size={24} className="text-primary" />
          </div>
          <h1>品質管理 HQ (Quality Control HQ)</h1>
        </div>
        <nav className="app-tabs" aria-label="メイン画面切替">
          <button
            type="button"
            className={`app-tab ${activeTab === 'dashboard' ? 'active' : ''}`}
            onClick={() => setActiveTab('dashboard')}
          >
            <Layers size={16} />
            巡回ダッシュボード
          </button>
          <button
            type="button"
            className={`app-tab ${activeTab === 'mapCreator' ? 'active' : ''}`}
            onClick={() => setActiveTab('mapCreator')}
          >
            <MapIcon size={16} />
            見取り図作成
          </button>
          <button
            type="button"
            className={`app-tab ${activeTab === 'settings' ? 'active' : ''}`}
            onClick={() => setActiveTab('settings')}
          >
            <Settings size={16} />
            設定
          </button>
        </nav>
        <div className="header-right">
          <span className="header-tagline">巡回検査計画・OCR取込ダッシュボード</span>
          <button
            type="button"
            className="theme-toggle-btn"
            onClick={() => setTheme(getNextTheme)}
            title={`テーマ切替: ${THEME_LABELS[getNextTheme(theme)]}`}
          >
            {themeIcon}
            {THEME_LABELS[theme]}
          </button>
        </div>
      </header>

      <main className={`app-main ${activeTab === 'mapCreator' || activeTab === 'settings' ? 'scrollable' : ''}`}>

        {globalError && (
          <div className="card error-card-global animate-shake">
            <ShieldAlert size={20} className="error-icon" />
            <div className="error-content">
              <h3>システムエラー</h3>
              <p>{globalError}</p>
            </div>
            <button className="error-close-btn" onClick={() => setGlobalError(null)}>&times;</button>
          </div>
        )}

        {activeTab === 'dashboard' ? (
          <div className={`dashboard-grid ${isSidebarCollapsed ? 'sidebar-collapsed' : ''}`}>
            <aside className="dashboard-sidebar">
              <button
                type="button"
                className="sidebar-toggle-btn"
                onClick={() => setIsSidebarCollapsed((current) => !current)}
                title={isSidebarCollapsed ? 'サイドバーを展開' : 'サイドバーを折りたたむ'}
              >
                {isSidebarCollapsed ? <PanelLeftOpen size={18} /> : <PanelLeftClose size={18} />}
              </button>
              {isSidebarCollapsed ? (
                <div className="collapsed-sidebar-rail">
                  <span>取込</span>
                  {currentJob && <span className={`collapsed-status-dot ${currentJob.status}`}></span>}
                </div>
              ) : (
                <>
                  <div className="sidebar-segment-control">
                    <button
                      type="button"
                      className={`sidebar-segment-btn ${sidebarSegment === 'import' ? 'active' : ''}`}
                      onClick={() => setSidebarSegment('import')}
                    >
                      取込
                    </button>
                    <button
                      type="button"
                      className={`sidebar-segment-btn ${sidebarSegment === 'status' ? 'active' : ''}`}
                      onClick={() => setSidebarSegment('status')}
                    >
                      ジョブステータス
                    </button>
                  </div>
                  {sidebarSegment === 'import' ? (
                    <ImportForm onImportStart={handleImportStart} isLoading={isLoadingJob} />
                  ) : (
                    <ImportSummary job={currentJob} />
                  )}
                </>
              )}
            </aside>

            <div className="dashboard-workspace">
              <LayoutList
                layouts={layouts}
                selectedDate={selectedDate}
                activeLayoutId={activeLayoutId}
                setActiveLayoutId={setActiveLayoutId}
                highlightedTargetCode={highlightedTargetCode}
                targets={targets}
                onScrollToTarget={handleScrollToTarget}
                onRegisterTarget={handleRegisterTarget}
              />

              <div className="dashboard-content">
                {selectedDate && (
                  <div className="targets-section-header">
                    <div className="targets-date-display">
                      <span>対象日:</span>
                      <strong>{selectedDate}</strong>
                    </div>
                    <button 
                      className="btn btn-secondary btn-icon-only" 
                      onClick={handleRefreshTargets}
                      disabled={isLoadingTargets}
                      title="再読み込み"
                    >
                      <RefreshCw size={16} className={isLoadingTargets ? 'animate-spin' : ''} />
                    </button>
                  </div>
                )}

                {isLoadingTargets ? (
                  <div className="loading-container">
                    <div className="pulse-spinner"></div>
                    <p>検査対象データを読み込んでいます...</p>
                  </div>
                ) : (
                  <TargetsTable
                    targets={targets}
                    highlightedTargetId={highlightedTargetId}
                    onTargetClick={handleTargetClick}
                    selectedDate={selectedDate}
                    onCheckUpdate={handleCheckUpdate}
                    onDeleteTargets={handleDeleteTargets}
                  />
                )}
              </div>
            </div>
          </div>
        ) : activeTab === 'settings' ? (
          <SettingsPanel fontSize={fontSize} onFontSizeChange={setFontSize} />
        ) : (
          <FactoryMapCreator />
        )}
      </main>

      <footer className="app-footer">
        <p>&copy; {new Date().getFullYear()} Quality Control HQ. All rights reserved.</p>
      </footer>
    </div>
  );
};

export default App;