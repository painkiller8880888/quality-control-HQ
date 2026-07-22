import React, { useState, useEffect, useRef } from 'react';
import './App.css';
import { ImportForm } from './components/ImportForm';
import { ImportSummary } from './components/ImportSummary';
import { SettingsPanel } from './components/SettingsPanel';

import { TargetsTable } from './components/TargetsTable';
import { LayoutList } from './components/LayoutList';
import { FactoryMapCreator } from './components/FactoryMapCreator';
import { MachineMasterPanel } from './components/MachineMasterPanel';
import { AssemblyStructureModal } from './components/AssemblyStructureModal';
import { InspectionSummary } from './components/InspectionSummary';
import type { Job, InspectionTarget, ApiError, LayoutSummary } from './types';
import { ShieldAlert, RefreshCw, Layers, Map as MapIcon, Cpu, Settings, Palette, Upload, CheckCircle2, Database, Menu, Search, X, CircleUserRound, LogOut, ClipboardList } from 'lucide-react';

interface AuthUser {
  id: number; login_name: string; display_name: string; avatar_url: string | null;
  role: 'admin' | 'worker'; settings: { theme: ThemeMode; browser_settings_imported: boolean };
}

const AvatarImage: React.FC<{ src: string | null; alt: string; fallbackSize: number }> = ({ src, alt, fallbackSize }) => {
  const [failedSrc, setFailedSrc] = useState<string | null>(null);
  return src && failedSrc !== src
    ? <img src={src} alt={alt} onError={() => setFailedSrc(src)} />
    : <CircleUserRound size={fallbackSize} aria-hidden="true" />;
};

const csrfToken = () => document.cookie.match(/(?:^|; )csrftoken=([^;]+)/)?.[1] || '';
const nativeFetch = window.fetch.bind(window);
const apiFetch = (input: RequestInfo | URL, init: RequestInit = {}) => {
  const method = (init.method || 'GET').toUpperCase();
  const headers = new Headers(init.headers);
  if (!['GET', 'HEAD', 'OPTIONS', 'TRACE'].includes(method)) headers.set('X-CSRFToken', csrfToken());
  return nativeFetch(input, { ...init, headers, credentials: 'same-origin' });
};
window.fetch = apiFetch as typeof window.fetch;

async function importBrowserSettings(user: AuthUser): Promise<AuthUser> {
  localStorage.removeItem('fontSize');
  if (user.settings.browser_settings_imported) return user;
  const response = await apiFetch('/api/me/settings/', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: localStorage.getItem('theme') || 'normal' }) });
  return response.ok ? { ...user, settings: await response.json() } : user;
}

interface MasterSearchResult {
  code: string;
  name: string;
}

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

const getTodayString = () => {
  const today = new Date();
  const yyyy = today.getFullYear();
  const mm = String(today.getMonth() + 1).padStart(2, '0');
  const dd = String(today.getDate()).padStart(2, '0');
  return `${yyyy}-${mm}-${dd}`;
};

export const App: React.FC = () => {
  const [authUser, setAuthUser] = useState<AuthUser | null>(null);
  const [authChecked, setAuthChecked] = useState(false);
  const [authMode, setAuthMode] = useState<'login' | 'register'>('login');
  const [authId, setAuthId] = useState('');
  const [authPassword, setAuthPassword] = useState('');
  const [authError, setAuthError] = useState<string | null>(null);
  const [userMenuOpen, setUserMenuOpen] = useState(false);
  const [profileModalOpen, setProfileModalOpen] = useState(false);
  const [profileDisplayName, setProfileDisplayName] = useState('');
  const [profileAvatar, setProfileAvatar] = useState<File | null>(null);
  const [currentPassword, setCurrentPassword] = useState('');
  const [newPassword, setNewPassword] = useState('');
  const [newPasswordConfirm, setNewPasswordConfirm] = useState('');
  const [profileError, setProfileError] = useState<string | null>(null);
  const [profileSaving, setProfileSaving] = useState(false);
  const [activeTab, setActiveTab] = useState<'dashboard' | 'summary' | 'mapCreator' | 'machineMaster' | 'settings'>('dashboard');
  const [isNavigationOpen, setIsNavigationOpen] = useState(false);
  const [isImportModalOpen, setIsImportModalOpen] = useState(false);
  const [isStructureSearchOpen, setIsStructureSearchOpen] = useState(false);
  const [structureQuery, setStructureQuery] = useState('');
  const [structureResults, setStructureResults] = useState<MasterSearchResult[]>([]);
  const [isStructureSearching, setIsStructureSearching] = useState(false);
  const [structureSearchError, setStructureSearchError] = useState<string | null>(null);
  const [selectedStructure, setSelectedStructure] = useState<MasterSearchResult | null>(null);
  const structureSearchTimerRef = useRef<number | null>(null);
  const structureSearchAbortRef = useRef<AbortController | null>(null);
  const navigationDialogRef = useRef<HTMLElement | null>(null);
  const importDialogRef = useRef<HTMLElement | null>(null);
  const searchDialogRef = useRef<HTMLElement | null>(null);
  const profileDialogRef = useRef<HTMLElement | null>(null);
  const userMenuRef = useRef<HTMLDivElement | null>(null);
  const userMenuTriggerRef = useRef<HTMLButtonElement | null>(null);
  const structureSearchTriggerRef = useRef<HTMLButtonElement | null>(null);
  const suppressDialogFocusRestoreRef = useRef(false);
  const [selectedDate, setSelectedDate] = useState<string>(getTodayString);
  const [currentJob, setCurrentJob] = useState<Job | null>(null);
  const [activeMasterJob, setActiveMasterJob] = useState<Job | null>(null);
  const [targets, setTargets] = useState<InspectionTarget[]>([]);
  const [isLoadingJob, setIsLoadingJob] = useState<boolean>(false);
  const [isLoadingTargets, setIsLoadingTargets] = useState<boolean>(false);
  const [globalError, setGlobalError] = useState<string | null>(null);
  const [successMessage, setSuccessMessage] = useState<string | null>(null);
  const successTimerRef = useRef<any>(null);
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
  const pollingTimerRef = useRef<any>(null);
  const profileAvatarPreview = React.useMemo(() => profileAvatar ? URL.createObjectURL(profileAvatar) : null, [profileAvatar]);

  useEffect(() => () => { if (profileAvatarPreview) URL.revokeObjectURL(profileAvatarPreview); }, [profileAvatarPreview]);
  useEffect(() => {
    if (!userMenuOpen) return;
    userMenuRef.current?.querySelector<HTMLButtonElement>('[role="menuitem"]')?.focus();
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key !== 'Escape') return;
      setUserMenuOpen(false);
      userMenuTriggerRef.current?.focus();
    };
    const closeOnOutsideClick = (event: PointerEvent) => {
      if (!userMenuRef.current?.contains(event.target as Node)) setUserMenuOpen(false);
    };
    document.addEventListener('keydown', closeOnEscape);
    document.addEventListener('pointerdown', closeOnOutsideClick);
    return () => {
      document.removeEventListener('keydown', closeOnEscape);
      document.removeEventListener('pointerdown', closeOnOutsideClick);
    };
  }, [userMenuOpen]);

  useEffect(() => {
    apiFetch('/api/auth/session/').then(async response => {
      const data = await response.json();
      if (data.authenticated) {
        const currentUser = await importBrowserSettings(data.user);
        setAuthUser(currentUser); setTheme(currentUser.settings.theme);
        void fetchLayouts(); void fetchTargets(getTodayString());
      }
    }).finally(() => setAuthChecked(true));
    // Session bootstrap and its initial data fetch intentionally run only once.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    document.documentElement.setAttribute('data-theme', theme);
    localStorage.setItem('theme', theme);
  }, [theme]);

  useEffect(() => {
    if (!authUser) {
      setActiveMasterJob(null);
      return;
    }
    let cancelled = false;
    const refreshActiveMaster = async () => {
      try {
        const response = await apiFetch('/api/jobs/active-master/');
        if (response.ok && !cancelled) setActiveMasterJob(await response.json());
      } catch {
        // Transient polling failures do not replace the normal API error display.
      }
    };
    void refreshActiveMaster();
    const timer = window.setInterval(refreshActiveMaster, 5000);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [authUser]);

  useEffect(() => {
    return () => {
      if (pollingTimerRef.current) {
        clearInterval(pollingTimerRef.current);
      }
      if (successTimerRef.current) {
        clearTimeout(successTimerRef.current);
      }
      if (structureSearchTimerRef.current) {
        clearTimeout(structureSearchTimerRef.current);
      }
      structureSearchAbortRef.current?.abort();
    };
  }, []);

  const submitAuthentication = async (event: React.FormEvent) => {
    event.preventDefault(); setAuthError(null);
    const response = await apiFetch(`/api/auth/${authMode}/`, { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ login_name: authId, password: authPassword }) });
    const data = await response.json();
    if (!response.ok) { setAuthError(data.detail || data.login_name?.[0] || '認証に失敗しました。'); return; }
    const currentUser = await importBrowserSettings(data.user);
    setAuthUser(currentUser); setTheme(currentUser.settings.theme); setAuthPassword(''); void fetchLayouts(); void fetchTargets(selectedDate);
  };
  const logoutUser = async () => { await apiFetch('/api/auth/logout/', { method: 'POST' }); setAuthUser(null); setUserMenuOpen(false); setActiveTab('dashboard'); };
  const cycleTheme = () => { const next = getNextTheme(theme); setTheme(next); void apiFetch('/api/me/settings/', { method: 'PUT', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify({ theme: next }) }); };
  const openProfileModal = () => { userMenuTriggerRef.current?.focus(); setUserMenuOpen(false); setProfileDisplayName(authUser?.display_name || ''); setProfileAvatar(null); setCurrentPassword(''); setNewPassword(''); setNewPasswordConfirm(''); setProfileError(null); setProfileModalOpen(true); };
  const saveProfile = async (event: React.FormEvent) => {
    event.preventDefault(); setProfileSaving(true); setProfileError(null);
    const body = new FormData(); body.set('display_name', profileDisplayName); if (profileAvatar) body.set('avatar', profileAvatar);
    if (currentPassword || newPassword || newPasswordConfirm) { body.set('current_password', currentPassword); body.set('new_password', newPassword); body.set('new_password_confirm', newPasswordConfirm); }
    try { const response = await apiFetch('/api/me/profile/', { method: 'PATCH', body }); const data = await response.json(); if (!response.ok) { const error = Object.values(data).flat().find(value => typeof value === 'string'); setProfileError(typeof error === 'string' ? error : 'プロフィールを更新できませんでした。'); return; } setAuthUser(data.user); setProfileModalOpen(false); }
    catch { setProfileError('プロフィールを更新できませんでした。'); } finally { setProfileSaving(false); }
  };

  useEffect(() => {
    const dialog = isNavigationOpen
      ? navigationDialogRef.current
      : isImportModalOpen
        ? importDialogRef.current
        : isStructureSearchOpen && !selectedStructure
          ? searchDialogRef.current
          : profileModalOpen ? profileDialogRef.current : null;
    if (!dialog) return;

    const previouslyFocused = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const getFocusable = () => Array.from(dialog.querySelectorAll<HTMLElement>(
      'button:not([disabled]), input:not([disabled]), select:not([disabled]), textarea:not([disabled]), [href], [tabindex]:not([tabindex="-1"])'
    ));
    getFocusable()[0]?.focus();

    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        event.preventDefault();
        if (isNavigationOpen) setIsNavigationOpen(false);
        else if (isImportModalOpen) setIsImportModalOpen(false);
        else if (profileModalOpen) setProfileModalOpen(false);
        else closeStructureSearch();
        return;
      }
      if (event.key !== 'Tab') return;
      const focusable = getFocusable();
      if (focusable.length === 0) {
        event.preventDefault();
        return;
      }
      const first = focusable[0];
      const last = focusable[focusable.length - 1];
      if (event.shiftKey && document.activeElement === first) {
        event.preventDefault();
        last.focus();
      } else if (!event.shiftKey && document.activeElement === last) {
        event.preventDefault();
        first.focus();
      }
    };
    document.addEventListener('keydown', handleKeyDown);
    return () => {
      document.removeEventListener('keydown', handleKeyDown);
      if (suppressDialogFocusRestoreRef.current) {
        suppressDialogFocusRestoreRef.current = false;
      } else {
        previouslyFocused?.focus();
      }
    };
  }, [isNavigationOpen, isImportModalOpen, isStructureSearchOpen, selectedStructure, profileModalOpen]);

  async function fetchLayouts() {
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
  }

  async function fetchTargets(date: string) {
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
  }

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

  const handleImportStart = async (targetDate: string, scanFile: File | null, excelFile: File | null, sheetName: string) => {
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
    if (sheetName) {
      formData.append('sheet_name', sheetName);
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

  const handleTargetDateChange = (date: string) => {
    setSelectedDate(date);
    if (date) {
      fetchTargets(date);
    } else {
      setTargets([]);
    }
  };

  const handleStructureSearch = (value: string) => {
    setStructureQuery(value);
    setStructureSearchError(null);
    if (structureSearchTimerRef.current) clearTimeout(structureSearchTimerRef.current);
    structureSearchAbortRef.current?.abort();
    if (!value.trim()) {
      setStructureResults([]);
      setIsStructureSearching(false);
      return;
    }
    structureSearchTimerRef.current = window.setTimeout(async () => {
      const controller = new AbortController();
      structureSearchAbortRef.current = controller;
      setIsStructureSearching(true);
      try {
        const response = await fetch(`/api/masters/search/?q=${encodeURIComponent(value.trim())}`, { signal: controller.signal });
        if (!response.ok) throw new Error('検索に失敗しました');
        setStructureResults(await response.json());
      } catch (err: any) {
        if (err.name === 'AbortError') return;
        setStructureResults([]);
        setStructureSearchError(err.message || '検索に失敗しました');
      } finally {
        if (structureSearchAbortRef.current === controller) {
          structureSearchAbortRef.current = null;
          setIsStructureSearching(false);
        }
      }
    }, 300);
  };

  const closeStructureSearch = () => {
    structureSearchAbortRef.current?.abort();
    setIsStructureSearchOpen(false);
    setSelectedStructure(null);
    window.setTimeout(() => structureSearchTriggerRef.current?.focus(), 0);
  };

  const openSelectedStructure = (result: MasterSearchResult) => {
    suppressDialogFocusRestoreRef.current = true;
    setSelectedStructure(result);
  };

  const navigateTo = (tab: typeof activeTab) => {
    setActiveTab(tab);
    setIsNavigationOpen(false);
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

  const handleRegisterTarget = async (machineId: number, code: string) => {
    if (!selectedDate) return;
    try {
      const response = await fetch('/api/inspection-targets/factory-map/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date: selectedDate, machine_id: machineId, code }),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        setGlobalError(data.message || '見取り図からの追加に失敗しました');
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

  const handleHideTargets = async (date: string, targetIds: number[]) => {
    const response = await fetch('/api/inspection-targets/bulk-hide/', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ date, target_ids: targetIds }),
    });
    if (!response.ok) {
      const errData = await response.json().catch(() => ({}));
      throw new Error(errData.message || '非表示に失敗しました');
    }
    await fetchTargets(date);
  };

  const handleIssueSheet = async (date: string) => {
    setGlobalError(null);
    try {
      const response = await fetch('/api/inspection-sheet/issue/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date }),
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.message || '検査書印刷の開始に失敗しました');
      }
      const { job_id } = await response.json();
      await new Promise<void>((resolve, reject) => {
        const poll = setInterval(async () => {
          try {
            const res = await fetch(`/api/jobs/${job_id}/`);
            const jobData: Job = await res.json();
            setCurrentJob(jobData);
            if (jobData.status === 'succeeded') {
              clearInterval(poll);
              fetchTargets(date);
              resolve();
            } else if (jobData.status === 'failed') {
              clearInterval(poll);
              reject(new Error(jobData.error_message || '印刷ジョブが失敗しました'));
            }
          } catch {
            // continue polling
          }
        }, 2000);
      });
    } catch (err: any) {
      setGlobalError(err.message || '検査書印刷の開始に失敗しました');
      throw err;
    }
  };

  const showSuccess = (message: string) => {
    setSuccessMessage(message);
    if (successTimerRef.current) clearTimeout(successTimerRef.current);
    successTimerRef.current = setTimeout(() => setSuccessMessage(null), 4000);
  };

  const handleWriteHistory = async (date: string) => {
    setGlobalError(null);
    try {
      const response = await fetch('/api/history/write-to-file/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date }),
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.message || '履歴ファイルへの記入に失敗しました');
      }
      const data = await response.json();
      if (data.written_count > 0) {
        showSuccess(`履歴ファイルに ${data.written_count} 件記入しました`);
      } else {
        showSuccess('記入対象の履歴がありません');
      }
      fetchTargets(date);
    } catch (err: any) {
      setGlobalError(err.message || '履歴ファイルへの記入に失敗しました');
      throw err;
    }
  };

  const handleIssueDailyReport = async (date: string) => {
    setGlobalError(null);
    try {
      const response = await fetch('/api/daily-report/issue/', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ date }),
      });
      if (!response.ok) {
        const errData = await response.json().catch(() => ({}));
        throw new Error(errData.message || '日報発行の開始に失敗しました');
      }
      const { job_id } = await response.json();
      await new Promise<void>((resolve, reject) => {
        const poll = setInterval(async () => {
          try {
            const res = await fetch(`/api/jobs/${job_id}/`);
            const jobData: Job = await res.json();
            setCurrentJob(jobData);
            if (jobData.status === 'succeeded') {
              clearInterval(poll);
              resolve();
            } else if (jobData.status === 'failed') {
              clearInterval(poll);
              reject(new Error(jobData.error_message || '日報発行ジョブが失敗しました'));
            }
          } catch {
            // continue polling
          }
        }, 2000);
      });
    } catch (err: any) {
      setGlobalError(err.message || '日報発行の開始に失敗しました');
      throw err;
    }
  };

  const handleCheckUpdate = (date: string, items: { target_id: number; checks: Record<string, boolean> }[]) => {
    setTargets(prev => prev.map(t => {
      const item = items.find(i => i.target_id === t.target_id);
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

  if (!authChecked) return <div className="auth-screen"><div className="auth-card">読み込み中...</div></div>;
  if (!authUser) return <div className="auth-screen"><form className="auth-card" onSubmit={submitAuthentication}><CircleUserRound size={64} aria-hidden="true" /><h1>Quality Control HQ</h1><h2>{authMode === 'login' ? 'ログイン' : '新規登録'}</h2><label>ユーザーID<input autoFocus required value={authId} onChange={e => setAuthId(e.target.value)} /></label><label>パスワード<input type="password" required minLength={8} value={authPassword} onChange={e => setAuthPassword(e.target.value)} /></label>{authError && <p className="auth-error">{authError}</p>}<button type="submit">{authMode === 'login' ? 'ログイン' : '作業者として登録'}</button><button type="button" className="auth-switch" onClick={() => { setAuthMode(authMode === 'login' ? 'register' : 'login'); setAuthError(null); }}>{authMode === 'login' ? '新規登録はこちら' : 'ログインへ戻る'}</button></form></div>;
  const permittedActiveTab = authUser.role === 'worker' ? 'dashboard' : activeTab;

  return (
    <div className="app-container">
      <header className="app-header">
        <button type="button" className="header-icon-btn" onClick={() => setIsNavigationOpen(true)} title="メニュー" aria-label="メニューを開く">
          <Menu size={22} />
        </button>
        <div className="header-logo-section">
          <div className="header-logo">
            <Layers size={24} className="text-primary" />
          </div>
          <h1>品質管理 HQ (Quality Control HQ)</h1>
        </div>
        <div className="header-right">
          <button ref={structureSearchTriggerRef} type="button" className="header-search-trigger" onClick={() => setIsStructureSearchOpen(true)}>
            <Search size={17} />
            <span>コード / 品名検索</span>
          </button>
          <label className="header-date-control">
            <span>対象日</span>
            <input type="date" value={selectedDate} onChange={event => handleTargetDateChange(event.target.value)} />
          </label>
          <button type="button" className="header-icon-btn" onClick={handleRefreshTargets} disabled={isLoadingTargets} title="更新" aria-label="検査対象を更新">
            <RefreshCw size={17} className={isLoadingTargets ? 'animate-spin' : ''} />
          </button>
          <button type="button" className="header-icon-btn" onClick={() => setIsImportModalOpen(true)} title="取込 / ジョブステータス" aria-label="取込を開く">
            <Upload size={18} />
          </button>
          <button
            type="button"
            className="header-icon-btn"
            onClick={cycleTheme}
            title={`テーマ切替: ${THEME_LABELS[getNextTheme(theme)]}`}
            aria-label={`テーマ切替。現在は${THEME_LABELS[theme]}、次は${THEME_LABELS[getNextTheme(theme)]}`}
          >
            <Palette size={18} />
          </button>
          <div ref={userMenuRef} className="user-menu-wrap">
            <button ref={userMenuTriggerRef} id="user-menu-trigger" type="button" className="header-user-button" onClick={() => setUserMenuOpen(!userMenuOpen)} aria-haspopup="menu" aria-controls="user-menu" aria-expanded={userMenuOpen} aria-label="ユーザーメニュー"><AvatarImage src={authUser.avatar_url} alt="" fallbackSize={28} /></button>
            {userMenuOpen && <div id="user-menu" className="user-menu" role="menu" aria-labelledby="user-menu-trigger"><button type="button" role="menuitem" onClick={openProfileModal}><Settings size={17} aria-hidden="true" />設定</button><div className="user-menu-separator" role="separator" /><button type="button" role="menuitem" onClick={() => { setUserMenuOpen(false); void logoutUser(); }}><LogOut size={17} aria-hidden="true" />ログアウト</button></div>}
          </div>
        </div>
      </header>

      <main className={`app-main ${permittedActiveTab !== 'dashboard' ? 'scrollable' : ''}`}>

        {activeMasterJob && (
          <div className="warning-alert-box" role="status">
            <ShieldAlert size={18} className="warning-alert-icon" />
            <div>
              <strong>マスタ更新中</strong>
              <span> 確定済みの旧版データを表示しています。Job: {activeMasterJob.job_id}</span>
            </div>
          </div>
        )}
        {successMessage && (
          <div className="card success-card-global">
            <CheckCircle2 size={20} className="success-icon" />
            <div className="error-content">
              <p>{successMessage}</p>
            </div>
          </div>
        )}
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

        {permittedActiveTab === 'dashboard' ? (
          <div className="dashboard-grid">
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
                <TargetsTable
                  targets={targets}
                  highlightedTargetId={highlightedTargetId}
                  onTargetClick={handleTargetClick}
                  selectedDate={selectedDate}
                  onCheckUpdate={handleCheckUpdate}
                  onHideTargets={handleHideTargets}
                  onIssueSheet={handleIssueSheet}
                  onIssueDailyReport={handleIssueDailyReport}
                  onWriteHistory={handleWriteHistory}
                  onRefresh={handleRefreshTargets}
                  isLoading={isLoadingTargets}
                />
              </div>
            </div>
          </div>
        ) : permittedActiveTab === 'summary' ? (
          <InspectionSummary />
        ) : permittedActiveTab === 'machineMaster' ? (
          <MachineMasterPanel />
        ) : permittedActiveTab === 'settings' ? (
          <SettingsPanel />
        ) : (
          <FactoryMapCreator />
        )}
      </main>

      {isNavigationOpen && (
        <div className="navigation-overlay" onClick={() => setIsNavigationOpen(false)}>
          <aside ref={navigationDialogRef} className="navigation-drawer" role="dialog" aria-modal="true" aria-label="メインメニュー" onClick={event => event.stopPropagation()}>
            <div className="navigation-drawer-header">
              <div className="header-logo"><Layers size={20} /></div>
              <strong>メニュー</strong>
              <button type="button" className="header-icon-btn" onClick={() => setIsNavigationOpen(false)} aria-label="閉じる"><X size={18} /></button>
            </div>
            <button className={activeTab === 'dashboard' ? 'active' : ''} onClick={() => navigateTo('dashboard')}><Layers size={17} />巡回ダッシュボード</button>
            <hr />
            {authUser.role === 'admin' && <><button className={activeTab === 'summary' ? 'active' : ''} onClick={() => navigateTo('summary')}><ClipboardList size={17} />検査サマリー</button>
            <button className={activeTab === 'mapCreator' ? 'active' : ''} onClick={() => navigateTo('mapCreator')}><MapIcon size={17} />見取り図作成</button>
            <button className={activeTab === 'machineMaster' ? 'active' : ''} onClick={() => navigateTo('machineMaster')}><Cpu size={17} />機械マスタ編集</button>
            <hr />
            <button className={activeTab === 'settings' ? 'active' : ''} onClick={() => navigateTo('settings')}><Settings size={17} />管理者設定</button></>}
          </aside>
        </div>
      )}

      {isImportModalOpen && (
        <div className="modal-overlay" onClick={() => setIsImportModalOpen(false)}>
          <section ref={importDialogRef} className="card modal-content import-status-modal" role="dialog" aria-modal="true" aria-labelledby="import-dialog-title" onClick={event => event.stopPropagation()}>
            <div className="modal-header"><h3 id="import-dialog-title"><Upload size={18} />取込 / ジョブステータス</h3><button className="header-icon-btn" onClick={() => setIsImportModalOpen(false)} aria-label="閉じる"><X size={18} /></button></div>
            <div className="modal-body import-status-content">
              <ImportForm onImportStart={handleImportStart} targetDate={selectedDate} onTargetDateChange={handleTargetDateChange} isLoading={isLoadingJob} />
              {currentJob ? <ImportSummary job={currentJob} /> : (
                <div className="card import-status-empty-card">
                  <h2 className="card-title"><Database className="icon-title" size={20} />ジョブステータス</h2>
                  <p className="modal-empty-message">実行中または直近のジョブはありません。</p>
                </div>
              )}
            </div>
          </section>
        </div>
      )}

      {profileModalOpen && <div className="modal-overlay" onClick={() => setProfileModalOpen(false)}><section ref={profileDialogRef} className="card modal-content profile-modal" role="dialog" aria-modal="true" aria-labelledby="profile-dialog-title" onClick={event => event.stopPropagation()}><div className="modal-header"><h3 id="profile-dialog-title">アカウント設定</h3><button type="button" className="header-icon-btn" onClick={() => setProfileModalOpen(false)} aria-label="閉じる"><X size={18} /></button></div><form className="profile-form" onSubmit={saveProfile}><section className="profile-form-section" aria-labelledby="profile-basic-title"><h4 id="profile-basic-title">プロフィール / 基本情報</h4><label>ログイン名<input value={authUser.login_name} disabled /></label><label>ユーザー名<input value={profileDisplayName} maxLength={255} onChange={event => setProfileDisplayName(event.target.value)} /></label><label>アバター画像<input type="file" accept="image/jpeg,image/png,image/webp" onChange={event => setProfileAvatar(event.target.files?.[0] || null)} /></label><div className="profile-avatar-preview"><AvatarImage src={profileAvatarPreview || authUser.avatar_url} alt={profileAvatarPreview ? '選択したアバターのプレビュー' : '現在のアバター'} fallbackSize={56} /></div></section><div className="profile-section-separator" role="separator" /><section className="profile-form-section" aria-labelledby="profile-password-title"><h4 id="profile-password-title">パスワード変更</h4><p className="profile-section-note">変更する場合のみ入力してください。</p><label>現在のパスワード<input type="password" autoComplete="current-password" value={currentPassword} onChange={event => setCurrentPassword(event.target.value)} /></label><label>新しいパスワード<input type="password" minLength={8} autoComplete="new-password" value={newPassword} onChange={event => setNewPassword(event.target.value)} /></label><label>新しいパスワード（確認）<input type="password" minLength={8} autoComplete="new-password" value={newPasswordConfirm} onChange={event => setNewPasswordConfirm(event.target.value)} /></label></section>{profileError && <p className="auth-error" role="alert">{profileError}</p>}<div className="profile-actions"><button type="button" className="btn" onClick={() => setProfileModalOpen(false)}>キャンセル</button><button type="submit" className="btn btn-primary" disabled={profileSaving}>{profileSaving ? '保存中...' : '保存'}</button></div></form></section></div>}

      {isStructureSearchOpen && !selectedStructure && (
        <div className="modal-overlay modal-overlay-top" onClick={closeStructureSearch}>
          <section ref={searchDialogRef} className="card modal-content structure-search-modal" role="dialog" aria-modal="true" aria-labelledby="structure-search-title" onClick={event => event.stopPropagation()}>
            <div className="modal-header"><h3 id="structure-search-title"><Search size={18} />コード / 品名検索</h3><button className="header-icon-btn" onClick={closeStructureSearch} aria-label="閉じる"><X size={18} /></button></div>
            <div className="structure-search-input"><Search size={17} /><input autoFocus value={structureQuery} onChange={event => handleStructureSearch(event.target.value)} placeholder="コードまたは品名を入力" /></div>
            <div className="structure-search-results">
              {isStructureSearching ? <p>検索中...</p> : structureSearchError ? <p className="search-error">{structureSearchError}</p> : structureQuery && structureResults.length === 0 ? <p>候補が見つかりません。</p> : structureResults.map(result => (
                <button key={result.code} onClick={() => openSelectedStructure(result)}><strong>{result.code}</strong><span>{result.name}</span></button>
              ))}
            </div>
          </section>
        </div>
      )}
      {isStructureSearchOpen && selectedStructure && <AssemblyStructureModal code={selectedStructure.code} name={selectedStructure.name} onClose={closeStructureSearch} />}

      <footer className="app-footer">
        <p>&copy; {new Date().getFullYear()} Quality Control HQ. All rights reserved.</p>
      </footer>
    </div>
  );
};

export default App;
