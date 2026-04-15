export type Severity = 'CRITICAL' | 'HIGH' | 'MEDIUM' | 'LOW' | 'INFO';
export type FindingStatus = 'Open' | 'Accepted' | 'Rejected' | 'Fixed';
export type UploadMode = 'individual' | 'zip';
export type FindingCategory =
  | 'Compile Errors'
  | 'Hallucinated Properties'
  | 'Security'
  | 'Error Handling'
  | 'Naming Conventions'
  | 'Logging'
  | 'Architecture'
  | 'Configuration'
  | 'Lint — Studio Crash'
  | 'Lint — Compile/Runtime'
  | 'Lint — Best Practice'
  | 'SAP'
  | 'UI Automation'
  | 'REFramework'
  | 'Data Handling'
  | string; // allow additional categories from expanded rule catalog

export interface ModelOption {
  id: string;
  label: string;
  provider: string;
  class: string;
  recommended: boolean;
}

export interface ModelsResponse {
  default: string;
  models: ModelOption[];
}

export interface Finding {
  id: string;
  file_name: string;
  zip_entry_path: string;
  workflow_name: string;
  severity: Severity;
  category: FindingCategory;
  rule_id: string;
  rule_name: string;
  activity_path: string;
  description: string;
  recommendation: string;
  auto_fixable: boolean;
  status: FindingStatus;
  reviewer_notes: string;
}

export interface ReviewResponse {
  project_name: string;
  upload_mode: UploadMode;
  zip_file_name: string | null;
  reviewed_at: string;
  total_files: number;
  skipped_files: string[];
  model_id: string;
  findings: Finding[];
}
