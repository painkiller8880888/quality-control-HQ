export type JobStatus = 'queued' | 'running' | 'succeeded' | 'failed';

export interface SourceSummary {
  source: string;
  read_count: number;
  added_count: number;
  duplicate_count: number;
  match_failed_count?: number;
  page_count?: number;
  mode?: string;
}

export interface JobResult {
  target_date: string;
  session_id: number;
  imported_count: number;
  warning_count: number;
  warning_summary: Record<string, number>;
  sources: SourceSummary[];
  missing_plan_file?: boolean;
}

export interface Job {
  job_id: string;
  job_type: string;
  status: JobStatus;
  started_at: string | null;
  finished_at: string | null;
  error_message: string | null;
  result: JobResult | null;
}

export interface InspectionTargetWarning {
  error_code: string;
  message: string;
  details: Record<string, any>;
}

export interface InspectionTarget {
  target_id: number;
  code: string;
  name: string;
  category: number | null;
  source_flags: {
    ocr: boolean;
    excel: boolean;
    manual: boolean;
  };
  requires_inspection_sheet: boolean;
  issue_status: string;
  warnings: InspectionTargetWarning[];
  checks: {
    A: boolean;
    B: boolean;
    C: boolean;
    D: boolean;
  };
}

export interface ApiError {
  status: 'error';
  error_code: string;
  message: string;
  details?: Record<string, any>;
}
