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

const SEVERITY_CLASSES: Record<Severity, string> = {
  CRITICAL: 'bg-red-600 text-white',
  HIGH: 'bg-orange-500 text-white',
  MEDIUM: 'bg-amber-400 text-amber-900',
  LOW: 'bg-blue-500 text-white',
  INFO: 'bg-gray-400 text-white',
};

function SeverityRenderer(params: ICellRendererParams) {
  const severity = params.value as Severity;
  return (
    <span
      className={`severity-badge inline-block px-2 py-0.5 rounded text-xs font-bold ${SEVERITY_CLASSES[severity] ?? ''}`}
    >
      {severity}
    </span>
  );
}

export default function ReviewGrid({ findings, setFindings, uploadMode, fileNames, activeFile, onFileChange }: Props) {
  const gridRef = useRef<AgGridReact>(null);
  const [quickFilter, setQuickFilter] = useState('');
  const [collapsed, setCollapsed] = useState(false);

  const columnDefs: ColDef<Finding>[] = [
    { field: 'id', headerName: 'ID', width: 80, filter: true },
    { field: 'file_name', headerName: 'File', width: 140, filter: true },
    ...(uploadMode === 'zip'
      ? [
          {
            field: 'zip_entry_path' as keyof Finding,
            headerName: 'ZIP Path',
            width: 220,
            filter: true,
          },
        ]
      : []),
    {
      field: 'severity',
      headerName: 'Severity',
      width: 110,
      filter: true,
      cellRenderer: SeverityRenderer,
    },
    { field: 'category', headerName: 'Category', width: 170, filter: true },
    { field: 'rule_id', headerName: 'Rule', width: 90, filter: true },
    { field: 'rule_name', headerName: 'Rule Name', width: 180, filter: true },
    {
      field: 'activity_path',
      headerName: 'Location',
      width: 200,
      filter: true,
    },
    {
      field: 'description',
      headerName: 'Description',
      width: 320,
      filter: true,
      wrapText: true,
      autoHeight: true,
    },
    {
      field: 'recommendation',
      headerName: 'Recommendation',
      width: 320,
      filter: true,
      wrapText: true,
      autoHeight: true,
    },
    {
      field: 'status',
      headerName: 'Status',
      width: 100,
      filter: true,
    },
    {
      field: 'reviewer_notes',
      headerName: 'Reviewer Notes',
      width: 260,
      editable: true,
      filter: true,
      cellEditor: 'agLargeTextCellEditor',
    },
  ];

  const onCellValueChanged = useCallback(
    (event: CellValueChangedEvent<Finding>) => {
      setFindings((prev) =>
        prev.map((f) => (f.id === event.data!.id ? { ...event.data! } : f))
      );
    },
    [setFindings]
  );

  return (
    <div className="bg-white rounded-xl shadow-sm border border-ui-g200 overflow-hidden">
      {/* Card header */}
      <button
        className="w-full bg-ui-navy px-6 py-3 flex items-center justify-between cursor-pointer hover:bg-ui-navy-light transition-colors"
        onClick={() => setCollapsed((c) => !c)}
      >
        <h2 className="text-white font-semibold text-sm tracking-wide">Detailed Findings</h2>
        <div className="flex items-center gap-3">
          <span className="text-xs text-gray-400">
            {findings.length} finding{findings.length !== 1 ? 's' : ''}
          </span>
          <svg
            className={`w-4 h-4 text-gray-400 transition-transform ${collapsed ? '' : 'rotate-180'}`}
            fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
          >
            <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
          </svg>
        </div>
      </button>

      {!collapsed && (
        <>
          {/* Toolbar */}
          <div className="px-6 py-3 border-b border-ui-g100 bg-ui-g50 flex flex-wrap items-center gap-3">
            <div className="relative flex-1 max-w-xs">
              <svg className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-ui-g400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              <input
                type="text"
                placeholder="Filter findings..."
                value={quickFilter}
                onChange={(e) => {
                  setQuickFilter(e.target.value);
                  gridRef.current?.api?.setGridOption('quickFilterText', e.target.value);
                }}
                className="w-full border border-ui-g300 rounded-lg pl-9 pr-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ui-orange focus:border-ui-orange transition-colors"
              />
            </div>

            {/* File filter dropdown */}
            <select
              value={activeFile ?? ''}
              onChange={(e) => onFileChange(e.target.value || null)}
              className="border border-ui-g300 rounded-lg px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ui-orange"
            >
              <option value="">All Files</option>
              {fileNames.map((name) => (
                <option key={name} value={name}>
                  {name}
                </option>
              ))}
            </select>
          </div>

          {/* Grid */}
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
