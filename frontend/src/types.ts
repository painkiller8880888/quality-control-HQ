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
  product_category: string | null;
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

export interface MasterUpdateJobResult {
  updated_master_count: number;
  updated_class_count: number;
  updated_structure_count: number;
  inspection_file_count: number;
  source: string;
  folder_warnings?: string[];
}

export interface AppSettings {
  id: number;
  csv_path: string;
  inspection_folder_paths: string[];
  updated_at: string;
}

export interface ApiError {
  status: 'error';
  error_code: string;
  message: string;
  details?: Record<string, any>;
}

export type LayoutObjectTypeCode = 'machine' | 'wall' | 'path' | 'area' | 'stairs' | 'entrance';

export interface LayoutObjectType {
  object_type_id: number;
  code: LayoutObjectTypeCode;
  display_name: string;
  color: string;
  image_path: string;
  selectable: boolean;
}

export interface LayoutObject {
  layout_object_id?: number;
  type: LayoutObjectTypeCode;
  machine_id: number | null;
  machine_no?: string | null;
  machine_name?: string | null;
  object_name: string;
  grid_x: number;
  grid_y: number;
  width: number;
  height: number;
  rotation?: number;
  meta_json?: Record<string, any>;
}

export interface FactoryMapMachine {
  machine_id: number;
  machine_no: string;
  machine_name: string;
  shape_type: 'circle' | 'ellipse' | 'rectangle';
  x: number;
  y: number;
  width: number;
  height: number;
  status: 'idle' | 'pending';
  assigned_codes: string[];
  target_codes: string[];
}

export interface FactoryMapWarning {
  code: string;
  error_code: string;
}

export interface FactoryMapLayout {
  layout_id: number;
  layout_name: string;
  background_image_path: string;
  grid_width: number;
  grid_height: number;
  object_types: LayoutObjectType[];
  objects: LayoutObject[];
}

export interface FactoryMapResponse {
  image_url: string;
  layout: FactoryMapLayout;
  machines: FactoryMapMachine[];
  warnings: FactoryMapWarning[];
}
