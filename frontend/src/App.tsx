import React, { useState, useEffect, useRef } from 'react';
import { ImportForm } from './components/ImportForm';
import { ImportSummary } from './components/ImportSummary';
import { WarningSummaryCard } from './components/WarningSummaryCard';
import { TargetsTable } from './components/TargetsTable';
import type { Job, InspectionTarget, ApiError } from './types';
import { ShieldAlert, RefreshCw, Layers } from 'lucide-react';

export const App: React.FC = () => {
  const [selectedDate, setSelectedDate] = useState<string>('');
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [targets, setTargets] = useState<InspectionTarget[]>([]);
  const [isLoadingJob, setIsLoadingJob] = useState<boolean>(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState<boolean>(false);
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

        <div className="dashboard-grid">
          <div className="dashboard-sidebar">
            <ImportForm onImportStart={handleImportStart} isLoading={isLoadingJob} />
            <ImportSummary job={currentJob} />
          </div>

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
      </main>

      <footer className="app-footer">
        <p>&copy; {new Date().getFullYear()} Quality Control HQ. All rights reserved.</p>
      </footer>
    </div>
  );
};

export default App;
