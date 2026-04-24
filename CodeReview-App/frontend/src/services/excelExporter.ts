import * as XLSX from 'xlsx-js-style';
import {
  ReviewResponse,
  Finding,
  ModelOption,
  Severity,
  FindingCategory,
} from '../models/finding';

const ALL_CATEGORIES: FindingCategory[] = [
  'Naming',
  'Design Best Practices',
  'UI Automation',
  'Performance',
  'Reliability',
  'Security',
  'General',
];

const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];

// All 41 Workflow Analyzer rules
export const ALL_RULES: { rule_id: string; rule_name: string; category: FindingCategory }[] = [
  // Naming (12)
  { rule_id: 'ST-NMG-001', rule_name: 'Variables Naming Convention', category: 'Naming' },
  { rule_id: 'ST-NMG-002', rule_name: 'Arguments Naming Convention', category: 'Naming' },
  { rule_id: 'ST-NMG-004', rule_name: 'Display Name Duplication', category: 'Naming' },
  { rule_id: 'ST-NMG-005', rule_name: 'Variable Overrides Variable', category: 'Naming' },
  { rule_id: 'ST-NMG-006', rule_name: 'Variable Overrides Argument', category: 'Naming' },
  { rule_id: 'ST-NMG-008', rule_name: 'Variable Length Exceeded', category: 'Naming' },
  { rule_id: 'ST-NMG-009', rule_name: 'Datatable Variable Prefix', category: 'Naming' },
  { rule_id: 'ST-NMG-010', rule_name: 'PascalCase Convention', category: 'Naming' },
  { rule_id: 'ST-NMG-011', rule_name: 'DataTable Argument Naming', category: 'Naming' },
  { rule_id: 'ST-NMG-012', rule_name: 'Argument Default Values', category: 'Naming' },
  { rule_id: 'ST-NMG-016', rule_name: 'Argument Length Exceeded', category: 'Naming' },
  { rule_id: 'ST-NMG-020', rule_name: 'Default Studio Display Name', category: 'Naming' },
  // Design Best Practices (10)
  { rule_id: 'ST-DBP-002', rule_name: 'High Arguments Count', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-003', rule_name: 'Empty Catch Block', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-007', rule_name: 'Multiple Flowchart Layers', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-020', rule_name: 'Undefined Output Properties', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-023', rule_name: 'Empty Workflow', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-024', rule_name: 'Persistence Activity Check', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-025', rule_name: 'Variables Serialization', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-026', rule_name: 'Delay Activity Usage', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-027', rule_name: 'Persistence Best Practice', category: 'Design Best Practices' },
  { rule_id: 'ST-DBP-028', rule_name: 'Arguments Serialization', category: 'Design Best Practices' },
  // UI Automation (6)
  { rule_id: 'UI-DBP-006', rule_name: 'Container Usage', category: 'UI Automation' },
  { rule_id: 'UI-DBP-013', rule_name: 'Excel Automation Misuse', category: 'UI Automation' },
  { rule_id: 'UI-PRR-004', rule_name: 'Hardcoded Delays', category: 'UI Automation' },
  { rule_id: 'UI-REL-001', rule_name: 'Large idx in Selectors', category: 'UI Automation' },
  { rule_id: 'UI-SEC-004', rule_name: 'Sensitive Data in Selectors', category: 'UI Automation' },
  { rule_id: 'UI-SEC-010', rule_name: 'App URL Restrictions', category: 'UI Automation' },
  // Performance (3)
  { rule_id: 'UI-PRR-001', rule_name: 'Simulate Click Not Used', category: 'Performance' },
  { rule_id: 'UI-PRR-002', rule_name: 'Simulate Type Not Used', category: 'Performance' },
  { rule_id: 'UI-PRR-003', rule_name: 'Open Application Misuse', category: 'Performance' },
  // Reliability (2)
  { rule_id: 'UI-REL-001', rule_name: 'Selector Index Too Large', category: 'Reliability' },
  { rule_id: 'GEN-REL-001', rule_name: 'Empty Sequences', category: 'Reliability' },
  // Security (3)
  { rule_id: 'UI-SEC-004', rule_name: 'Sensitive Data Exposure', category: 'Security' },
  { rule_id: 'UI-SEC-010', rule_name: 'Unauthorized App Usage', category: 'Security' },
  { rule_id: 'UX-DBP-029', rule_name: 'Insecure Password Usage', category: 'Security' },
  // General (5)
  { rule_id: 'GEN-001', rule_name: 'Unused Variables', category: 'General' },
  { rule_id: 'GEN-002', rule_name: 'Unused Arguments', category: 'General' },
  { rule_id: 'GEN-003', rule_name: 'Empty Sequences', category: 'General' },
  { rule_id: 'GEN-004', rule_name: 'Project Structure Issues', category: 'General' },
  { rule_id: 'GEN-005', rule_name: 'Package Restrictions', category: 'General' },
];

const HEADER_STYLE = {
  fill: { fgColor: { rgb: '0D1B2A' } },
  font: { color: { rgb: 'FFFFFF' }, bold: true, sz: 11 },
  alignment: { horizontal: 'center' as const },
};

function applyHeaderStyle(ws: XLSX.WorkSheet, headerRow: number = 0) {
  const range = XLSX.utils.decode_range(ws['!ref'] || 'A1');
  for (let col = range.s.c; col <= range.e.c; col++) {
    const cellRef = XLSX.utils.encode_cell({ r: headerRow, c: col });
    if (ws[cellRef]) {
      ws[cellRef].s = HEADER_STYLE;
    }
  }
}

export function exportToExcel(
  response: ReviewResponse,
  currentFindings: Finding[],
  models: ModelOption[]
): void {
  const wb = XLSX.utils.book_new();
  const date = new Date().toISOString().slice(0, 10);
  const modelLabel =
    models.find((m) => m.id === response.model_id)?.label ?? response.model_id;

  // ── Sheet 1: Executive Summary ──
  const summaryData: (string | number)[][] = [
    ['UiPath XAML Code Review — Executive Summary'],
    [],
    ['Project Name', response.project_name],
    ['Upload Mode', response.upload_mode],
    ['ZIP File', response.zip_file_name ?? 'N/A'],
    ['Review Date', new Date(response.reviewed_at).toLocaleString()],
    ['Total Files Reviewed', response.total_files],
    ['Skipped Files', response.skipped_files.join(', ') || 'None'],
    ['Model Used', modelLabel],
    [],
    ['Severity', 'Count'],
    ...SEVERITY_ORDER.map((s) => [
      s,
      currentFindings.filter((f) => f.severity === s).length,
    ]),
    [],
    ['Category', 'Count'],
    ...ALL_CATEGORIES.map((c) => [
      c,
      currentFindings.filter((f) => f.category === c).length,
    ]),
    [],
    [
      'Overall Status',
      currentFindings.some(
        (f) => f.severity === 'CRITICAL' || f.severity === 'HIGH'
      )
        ? 'FAIL'
        : 'PASS',
    ],
  ];
  const ws1 = XLSX.utils.aoa_to_sheet(summaryData);
  XLSX.utils.book_append_sheet(wb, ws1, 'Executive Summary');

  // ── Sheet 2: All Findings ──
  const findingHeaders = [
    'ID', 'File', 'ZIP Path', 'Workflow', 'Severity', 'Category',
    'Rule ID', 'Rule Name', 'Location', 'Description', 'Recommendation',
    'Auto-Fixable', 'Status', 'Reviewer Notes',
  ];
  const findingRows = currentFindings.map((f) => [
    f.id, f.file_name, f.zip_entry_path, f.workflow_name,
    f.severity, f.category, f.rule_id, f.rule_name,
    f.activity_path, f.description, f.recommendation,
    f.auto_fixable ? 'Yes' : 'No', f.status, f.reviewer_notes,
  ]);
  const ws2 = XLSX.utils.aoa_to_sheet([findingHeaders, ...findingRows]);
  ws2['!autofilter'] = { ref: `A1:N${findingRows.length + 1}` };
  ws2['!freeze'] = { xSplit: 0, ySplit: 1, topLeftCell: 'A2', activePane: 'bottomLeft', state: 'frozen' };
  applyHeaderStyle(ws2);
  XLSX.utils.book_append_sheet(wb, ws2, 'All Findings');

  // ── Sheet 3: Per File Summary ──
  const fileNames = [...new Set(currentFindings.map((f) => f.file_name))];
  const fileHeaders = [
    'File Name', 'ZIP Path', 'Workflow Name',
    'CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO', 'Total', 'Status',
  ];
  const fileRows = fileNames.map((name) => {
    const ff = currentFindings.filter((f) => f.file_name === name);
    const counts = SEVERITY_ORDER.map(
      (s) => ff.filter((f) => f.severity === s).length
    );
    const hasCritHigh = counts[0] > 0 || counts[1] > 0;
    return [
      name,
      ff[0]?.zip_entry_path ?? '',
      ff[0]?.workflow_name ?? '',
      ...counts,
      ff.length,
      hasCritHigh ? 'FAIL' : 'PASS',
    ];
  });
  const ws3 = XLSX.utils.aoa_to_sheet([fileHeaders, ...fileRows]);
  applyHeaderStyle(ws3);
  XLSX.utils.book_append_sheet(wb, ws3, 'Per File Summary');

  // ── Sheet 4: Rule Coverage ──
  const ruleHeaders = [
    'Rule ID', 'Rule Name', 'Category', 'Findings Count', 'Result',
  ];
  const ruleRows = ALL_RULES.map((r) => {
    const count = currentFindings.filter(
      (f) => f.rule_id === r.rule_id
    ).length;
    return [r.rule_id, r.rule_name, r.category, count, count > 0 ? 'Issues Found' : 'Clean'];
  });
  const ws4 = XLSX.utils.aoa_to_sheet([ruleHeaders, ...ruleRows]);
  applyHeaderStyle(ws4);
  XLSX.utils.book_append_sheet(wb, ws4, 'Rule Coverage');

  // Download
  const safeName = response.project_name.replace(/[^a-zA-Z0-9_-]/g, '_');
  XLSX.writeFile(wb, `UiPath_CodeReview_${safeName}_${date}.xlsx`);
}
