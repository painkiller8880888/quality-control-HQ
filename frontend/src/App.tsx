import React, { useState, useEffect, useRef } from 'react';
import { ImportForm } from './components/ImportForm';
import { ImportSummary } from './components/ImportSummary';
import { WarningSummaryCard } from './components/WarningSummaryCard';
import { TargetsTable } from './components/TargetsTable';
import { FactoryMapViewer } from './components/FactoryMapViewer';
import { FactoryMapCreator } from './components/FactoryMapCreator';
import type { Job, InspectionTarget, ApiError, FactoryMapResponse } from './types';
import { ShieldAlert, RefreshCw, Layers, Map as MapIcon, PanelLeftClose, PanelLeftOpen } from 'lucide-react';

export const App: React.FC = () => {
  const [activeTab, setActiveTab] = useState<'dashboard' | 'mapCreator'>('dashboard');
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState<boolean>(false);
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [targets, setTargets] = useState<InspectionTarget[]>([]);
  const [factoryMap, setFactoryMap] = useState<FactoryMapResponse | null>(null);
  const [isLoadingJob, setIsLoadingJob] = useState<boolean>(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState<boolean>(false);
  const [isLoadingFactoryMap, setIsLoadingFactoryMap] = useState<boolean>(false);
  const [globalError, setGlobalError] = useState<string | null>(null);

  const pollingTimerRef = useRef<any>(null);

  // Clear timers on unmount
  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
    };
  }, []);

  useEffect(() => {
    if (selectedDate) {
      fetchFactoryMap(selectedDate);
    }
  }, [selectedDate]);

  // Fetch targets for selected date
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

  const fetchFactoryMap = async (date: string) => {
    if (!date) return;
    setIsLoadingFactoryMap(true);

    try {
      const response = await fetch(`/api/factory-map/?date=${date}`);
      if (!response.ok) {
        throw new Error(`見取り図の取得に失敗しました (${response.status})`);
      }
      const data: FactoryMapResponse = await response.json();
      setFactoryMap(data);
    } catch (err: any) {
      setGlobalError(err.message || '見取り図の取得に失敗しました。');
      setFactoryMap(null);
    } finally {
      setIsLoadingFactoryMap(false);
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

  // Poll job status
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
          // Stop polling when job is done
          if (pollingTimerRef.current) {
            clearInterval(pollingTimerRef.current);
            pollingTimerRef.current = null;
          }
          setIsLoadingJob(false);

          if (jobData.status === 'succeeded') {
            // Load new targets
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
    }, 2500); // Poll every 2.5 seconds
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

      // Set initial job state
      setCurrentJob({
        job_id: jobId,
        job_type: 'PLANS_IMPORT',
        status: 'queued',
        started_at: new Date().toISOString(),
        finished_at: null,
        error_message: null,
        result: null,
      });

      // Start polling status
      startPolling(jobId, targetDate);
    } catch (err: any) {
      setGlobalError(err.message || '取込処理の開始に失敗しました。');
      setIsLoadingJob(false);
    }
  };

  const handleRefreshTargets = () => {
    if (selectedDate) {
      fetchTargets(selectedDate);
      fetchFactoryMap(selectedDate);
    }
  };

  return (
    <div className="app-container">
      <header className="app-header">
        <div className="header-logo-section">
          <div className="header-logo">
            <Layers size={24} className="text-primary" />
          </div>
          <h1>品質管理 HQ (Quality Control HQ)</h1>
        </div>
        <div className="header-tagline">巡回検査計画・OCR取込ダッシュボード</div>
      </header>

      <main className="app-main">
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
        </nav>

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
                  <ImportForm onImportStart={handleImportStart} isLoading={isLoadingJob} />
                  <ImportSummary job={currentJob} />
                </>
              )}
            </aside>

            <div className="dashboard-workspace">
              <FactoryMapViewer
                mapData={factoryMap}
                isLoading={isLoadingFactoryMap}
                selectedDate={selectedDate}
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
                      disabled={isLoadingTargets || isLoadingFactoryMap}
                      title="再読み込み"
                    >
                      <RefreshCw size={16} className={isLoadingTargets || isLoadingFactoryMap ? 'animate-spin' : ''} />
                    </button>
                  </div>
                )}

                <WarningSummaryCard targets={targets} />
                
                {isLoadingTargets ? (
                  <div className="loading-container">
                    <div className="pulse-spinner"></div>
                    <p>検査対象データを読み込んでいます...</p>
                  </div>
                ) : (
                  <TargetsTable targets={targets} />
                )}
              </div>
            </div>
          </div>
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
