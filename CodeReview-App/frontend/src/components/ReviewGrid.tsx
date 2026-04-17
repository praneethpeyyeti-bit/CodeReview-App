import { useRef, useState, useCallback } from 'react';
import { AgGridReact } from 'ag-grid-react';
import {
  AllCommunityModule,
  ModuleRegistry,
  ColDef,
  CellValueChangedEvent,
  ICellRendererParams,
} from 'ag-grid-community';
import { Finding, Severity, UploadMode } from '../models/finding';

ModuleRegistry.registerModules([AllCommunityModule]);

interface Props {
  findings: Finding[];
  setFindings: React.Dispatch<React.SetStateAction<Finding[]>>;
  uploadMode: UploadMode;
  fileNames: string[];
  activeFile: string | null;
  onFileChange: (file: string | null) => void;
}

const SEVERITY_BADGE: Record<Severity, string> = {
  CRITICAL: 'severity-badge severity-badge-critical',
  HIGH: 'severity-badge severity-badge-high',
  MEDIUM: 'severity-badge severity-badge-medium',
  LOW: 'severity-badge severity-badge-low',
  INFO: 'severity-badge severity-badge-info',
};

function SeverityRenderer(params: ICellRendererParams) {
  const severity = params.value as Severity;
  return <span className={SEVERITY_BADGE[severity] ?? ''}>{severity}</span>;
}

export default function ReviewGrid({ findings, setFindings, uploadMode, fileNames, activeFile, onFileChange }: Props) {
  const gridRef = useRef<AgGridReact>(null);
  const [quickFilter, setQuickFilter] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  const columnDefs: ColDef<Finding>[] = [
    { field: 'id', headerName: 'ID', width: 80, filter: true },
    { field: 'file_name', headerName: 'File', width: 140, filter: true },
    ...(uploadMode === 'zip'
      ? [{ field: 'zip_entry_path' as keyof Finding, headerName: 'ZIP Path', width: 220, filter: true }]
      : []),
    { field: 'severity', headerName: 'Severity', width: 110, filter: true, cellRenderer: SeverityRenderer },
    { field: 'category', headerName: 'Category', width: 170, filter: true },
    { field: 'rule_id', headerName: 'Rule', width: 100, filter: true },
    { field: 'rule_name', headerName: 'Rule Name', width: 180, filter: true },
    { field: 'activity_path', headerName: 'Location', width: 200, filter: true },
    { field: 'description', headerName: 'Description', width: 320, filter: true, wrapText: true, autoHeight: true },
    { field: 'recommendation', headerName: 'Recommendation', width: 320, filter: true, wrapText: true, autoHeight: true },
    { field: 'status', headerName: 'Status', width: 100, filter: true },
    { field: 'reviewer_notes', headerName: 'Notes', width: 260, editable: true, filter: true, cellEditor: 'agLargeTextCellEditor' },
  ];

  const onCellValueChanged = useCallback(
    (event: CellValueChangedEvent<Finding>) => {
      setFindings((prev) => prev.map((f) => (f.id === event.data!.id ? { ...event.data! } : f)));
    },
    [setFindings]
  );

  return (
    <div className="section-card animate-fade-in-up">
      <button className="section-header w-full" onClick={() => setCollapsed((c) => !c)}>
        <h2>
          <svg className="w-4 h-4 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          Detailed Findings
        </h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400 bg-white/10 px-2.5 py-0.5 rounded-full">
            {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </span>
          <svg className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${collapsed ? '' : 'rotate-180'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {!collapsed && (
        <>
          {/* Toolbar */}
          <div className="px-6 py-3 border-b border-ui-g100 bg-ui-g50/50 flex flex-wrap items-center gap-3">
            <div className="relative flex-1 max-w-xs">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ui-g400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input type="text" placeholder="Search findings..."
                value={quickFilter}
                onChange={(e) => { setQuickFilter(e.target.value); gridRef.current?.api?.setGridOption('quickFilterText', e.target.value); }}
                className="w-full border border-ui-g200 rounded-xl pl-9 pr-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-ui-orange/30 focus:border-ui-orange transition-all"
              />
            </div>
            <select value={activeFile ?? ''} onChange={(e) => onFileChange(e.target.value || null)}
              className="border border-ui-g200 rounded-xl px-3 py-2 text-sm bg-white focus:outline-none focus:ring-2 focus:ring-ui-orange/30"
            >
              <option value="">All Files</option>
              {fileNames.map((name) => <option key={name} value={name}>{name}</option>)}
            </select>
          </div>

          <div className="ag-theme-alpine" style={{ width: '100%', height: 600 }}>
            <AgGridReact<Finding>
              ref={gridRef}
              rowData={findings}
              columnDefs={columnDefs}
              rowHeight={90}
              onCellValueChanged={onCellValueChanged}
              getRowId={(params) => params.data.id}
            />
          </div>
        </>
      )}
    </div>
  );
}
