import * as XLSX from 'xlsx-js-style';
import {
  ReviewResponse,
  Finding,
  ModelOption,
  Severity,
  FindingCategory,
} from '../models/finding';

const ALL_CATEGORIES: FindingCategory[] = [
  'Compile Errors',
  'Hallucinated Properties',
  'Security',
  'Error Handling',
  'Naming Conventions',
  'Logging',
  'Architecture',
  'Configuration',
  'Lint — Studio Crash',
  'Lint — Compile/Runtime',
  'Lint — Best Practice',
  'SAP',
  'UI Automation',
  'REFramework',
  'Data Handling',
];

const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];

// All 65 rules for the Rule Coverage sheet
export const ALL_RULES: { rule_id: string; rule_name: string; category: FindingCategory }[] = [
  { rule_id: 'COMP-001', rule_name: 'Undeclared Variable', category: 'Compile Errors' },
  { rule_id: 'COMP-002', rule_name: 'Type Mismatch', category: 'Compile Errors' },
  { rule_id: 'COMP-003', rule_name: 'Missing Argument Mapping', category: 'Compile Errors' },
  { rule_id: 'COMP-004', rule_name: 'Missing Invoked Workflow', category: 'Compile Errors' },
  { rule_id: 'COMP-005', rule_name: 'Unknown Column Reference', category: 'Compile Errors' },
  { rule_id: 'HALL-001', rule_name: 'ClickBeforeTyping Property', category: 'Hallucinated Properties' },
  { rule_id: 'HALL-002', rule_name: 'EmptyField Property', category: 'Hallucinated Properties' },
  { rule_id: 'HALL-003', rule_name: 'SendWindowMessage Property', category: 'Hallucinated Properties' },
  { rule_id: 'HALL-004', rule_name: 'Invalid Namespace', category: 'Hallucinated Properties' },
  { rule_id: 'HALL-005', rule_name: 'Raw String for Enum', category: 'Hallucinated Properties' },
  { rule_id: 'SEC-001', rule_name: 'Hardcoded Credential', category: 'Security' },
  { rule_id: 'SEC-002', rule_name: 'Credential Pattern in Value', category: 'Security' },
  { rule_id: 'SEC-003', rule_name: 'Logging Sensitive Data', category: 'Security' },
  { rule_id: 'SEC-004', rule_name: 'Dynamic Code Injection', category: 'Security' },
  { rule_id: 'SEC-005', rule_name: 'Hardcoded Authorization Header', category: 'Security' },
  { rule_id: 'ERR-001', rule_name: 'UI Activity Outside TryCatch', category: 'Error Handling' },
  { rule_id: 'ERR-002', rule_name: 'HTTP Request Outside TryCatch', category: 'Error Handling' },
  { rule_id: 'ERR-003', rule_name: 'Main Missing Exception Handler', category: 'Error Handling' },
  { rule_id: 'ERR-004', rule_name: 'Empty TryCatch', category: 'Error Handling' },
  { rule_id: 'ERR-005', rule_name: 'Loop Invoke Without TryCatch', category: 'Error Handling' },
  { rule_id: 'ERR-006', rule_name: 'File Op Without Existence Check', category: 'Error Handling' },
  { rule_id: 'NAME-001', rule_name: 'String Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-002', rule_name: 'Int Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-003', rule_name: 'Boolean Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-004', rule_name: 'DataTable Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-005', rule_name: 'Array/List Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-006', rule_name: 'In Argument Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-007', rule_name: 'Out Argument Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-008', rule_name: 'InOut Argument Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-009', rule_name: 'File Name PascalCase', category: 'Naming Conventions' },
  { rule_id: 'NAME-010', rule_name: 'Default DisplayName', category: 'Naming Conventions' },
  { rule_id: 'NAME-011', rule_name: 'Special Characters in Name', category: 'Naming Conventions' },
  { rule_id: 'NAME-012', rule_name: 'DateTime/TimeSpan Prefix', category: 'Naming Conventions' },
  { rule_id: 'NAME-013', rule_name: 'Dictionary Variable Prefix', category: 'Naming Conventions' },
  { rule_id: 'LOG-001', rule_name: 'Missing Start Log', category: 'Logging' },
  { rule_id: 'LOG-002', rule_name: 'Missing End Log', category: 'Logging' },
  { rule_id: 'LOG-003', rule_name: 'Inappropriate Log Level', category: 'Logging' },
  { rule_id: 'LOG-004', rule_name: 'Exception Not Logged Before Rethrow', category: 'Logging' },
  { rule_id: 'LOG-005', rule_name: 'Loop Missing Transaction Log', category: 'Logging' },
  { rule_id: 'ARCH-001', rule_name: 'Workflow Too Long', category: 'Architecture' },
  { rule_id: 'ARCH-002', rule_name: 'Orphan Workflow', category: 'Architecture' },
  { rule_id: 'ARCH-003', rule_name: 'Circular Invocation', category: 'Architecture' },
  { rule_id: 'ARCH-004', rule_name: 'Flowchart in REFramework', category: 'Architecture' },
  { rule_id: 'ARCH-005', rule_name: 'Hardcoded Selectors', category: 'Architecture' },
  { rule_id: 'ARCH-006', rule_name: 'Deep Nesting', category: 'Architecture' },
  { rule_id: 'CONF-001', rule_name: 'Hardcoded URL', category: 'Configuration' },
  { rule_id: 'CONF-002', rule_name: 'Hardcoded File Path', category: 'Configuration' },
  { rule_id: 'CONF-003', rule_name: 'Hardcoded Email Address', category: 'Configuration' },
  { rule_id: 'CONF-004', rule_name: 'Hardcoded Timeout', category: 'Configuration' },
  { rule_id: 'CONF-005', rule_name: 'Missing Config Key', category: 'Configuration' },
  // Lint — Studio Crash rules
  { rule_id: 'LINT-017', rule_name: 'NExtractDataGeneric DataTable Attr', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-023', rule_name: 'TargetAnchorable Element', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-028', rule_name: 'Invalid ElementType Enum', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-057', rule_name: 'ReferencesForImplementation TypeArgs', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-073', rule_name: 'Hallucinated NExtractData Props', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-076', rule_name: 'Invoke Argument Type Mismatch', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-087', rule_name: 'Wrong xmlns on DataTable/DataRow', category: 'Lint — Studio Crash' },
  { rule_id: 'LINT-088', rule_name: 'Variable Declaration Order', category: 'Lint — Studio Crash' },
  // Lint — Compile/Runtime rules
  { rule_id: 'LINT-007', rule_name: 'Fully-Qualified Throw', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-020', rule_name: 'AddQueueItem x:String Children', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-030', rule_name: 'NSelectItem InteractionMode', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-031', rule_name: 'ContinueOnError on X-suffix', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-032', rule_name: 'SpecialFolder.Temp Usage', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-033', rule_name: 'InvokeCode SQL Operations', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-034', rule_name: 'InvokeCode Screenshot Capture', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-035', rule_name: 'InvokeCode File.Delete', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-040', rule_name: 'Wrong Enum Namespace', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-050', rule_name: 'Undeclared Argument Key', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-051', rule_name: 'GetQueueItem in Dispatcher', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-053', rule_name: 'Unsupported InteractionMode', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-054', rule_name: 'QueueName vs QueueType', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-055', rule_name: 'Empty Out/InOut Binding', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-056', rule_name: 'Arg Direction Mismatch', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-060', rule_name: 'Missing Required Arguments', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-067', rule_name: 'Undeclared Variable', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-071', rule_name: 'Double-Escaped Quotes', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-079', rule_name: 'Duplicate Arguments', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-080', rule_name: 'NSelectItem Null Item', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-081', rule_name: 'Undeclared Var in Main Invoke', category: 'Lint — Compile/Runtime' },
  { rule_id: 'LINT-083', rule_name: 'Double-Bracketed Expression', category: 'Lint — Compile/Runtime' },
  // Lint — Best Practice rules
  { rule_id: 'LINT-026', rule_name: 'Persistence in Sub-Workflow', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-027', rule_name: 'InvokeCode DataTable Creation', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-036', rule_name: 'Network Call Without RetryScope', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-037', rule_name: 'Hardcoded URL', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-038', rule_name: 'Browser Missing Incognito', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-041', rule_name: 'FuzzySelector Default', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-047', rule_name: 'OpenMode Not Never', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-058', rule_name: 'UI Activity Outside AppCard', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-062', rule_name: 'Missing Log Bookends', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-097', rule_name: 'CSS Selector in Selector', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-101', rule_name: 'Circular Dependency', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-102', rule_name: 'Orphaned Workflow', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-103', rule_name: 'UI-Heavy Without TryCatch', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-104', rule_name: 'Hardcoded User Path', category: 'Lint — Best Practice' },
  { rule_id: 'LINT-105', rule_name: 'Missing Tab Sync Delay', category: 'Lint — Best Practice' },
  // SAP rules
  { rule_id: 'SAP-001', rule_name: 'SAP Outside NSAPLogon', category: 'SAP' },
  { rule_id: 'SAP-002', rule_name: 'Missing Status Bar Check', category: 'SAP' },
  { rule_id: 'SAP-003', rule_name: 'Wrong Toolbar Button Activity', category: 'SAP' },
  { rule_id: 'SAP-004', rule_name: 'Direct Table Cell Selector', category: 'SAP' },
  { rule_id: 'SAP-005', rule_name: 'Volatile Dynpro Number', category: 'SAP' },
  { rule_id: 'SAP-006', rule_name: 'Hardcoded SAP Value', category: 'SAP' },
  // UI Automation rules
  { rule_id: 'UI-001', rule_name: 'UI Activity Outside AppCard', category: 'UI Automation' },
  { rule_id: 'UI-002', rule_name: 'AppCard Missing InUiElement', category: 'UI Automation' },
  { rule_id: 'UI-003', rule_name: 'CSS Selector Usage', category: 'UI Automation' },
  { rule_id: 'UI-004', rule_name: 'FuzzySelector Default', category: 'UI Automation' },
  { rule_id: 'UI-005', rule_name: 'Missing Tab Sync', category: 'UI Automation' },
  // REFramework rules
  { rule_id: 'REF-001', rule_name: 'Flowchart in REFramework', category: 'REFramework' },
  { rule_id: 'REF-002', rule_name: 'Init Does Too Much', category: 'REFramework' },
  { rule_id: 'REF-003', rule_name: 'Modified SetTransactionStatus', category: 'REFramework' },
  { rule_id: 'REF-004', rule_name: 'KillProcess in CloseAll', category: 'REFramework' },
  { rule_id: 'REF-005', rule_name: 'Login Without Validation', category: 'REFramework' },
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
    ['LLM Model Used', modelLabel],
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

  // ── Sheet 3: Security Findings ──
  const secFindings = currentFindings.filter((f) => f.category === 'Security');
  const secRows = secFindings.map((f) => [
    f.id, f.file_name, f.zip_entry_path, f.workflow_name,
    f.severity, f.category, f.rule_id, f.rule_name,
    f.activity_path, f.description, f.recommendation,
    f.auto_fixable ? 'Yes' : 'No', f.status, f.reviewer_notes,
  ]);
  const ws3 = XLSX.utils.aoa_to_sheet([findingHeaders, ...secRows]);
  applyHeaderStyle(ws3);
  XLSX.utils.book_append_sheet(wb, ws3, 'Security Findings');

  // ── Sheet 4: Error Handling Findings ──
  const errFindings = currentFindings.filter(
    (f) => f.category === 'Error Handling'
  );
  const errRows = errFindings.map((f) => [
    f.id, f.file_name, f.zip_entry_path, f.workflow_name,
    f.severity, f.category, f.rule_id, f.rule_name,
    f.activity_path, f.description, f.recommendation,
    f.auto_fixable ? 'Yes' : 'No', f.status, f.reviewer_notes,
  ]);
  const ws4 = XLSX.utils.aoa_to_sheet([findingHeaders, ...errRows]);
  applyHeaderStyle(ws4);
  XLSX.utils.book_append_sheet(wb, ws4, 'Error Handling Findings');

  // ── Sheet 5: Per File Summary ──
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
  const ws5 = XLSX.utils.aoa_to_sheet([fileHeaders, ...fileRows]);
  applyHeaderStyle(ws5);
  XLSX.utils.book_append_sheet(wb, ws5, 'Per File Summary');

  // ── Sheet 6: Rule Coverage ──
  const ruleHeaders = [
    'Rule ID', 'Rule Name', 'Category', 'Findings Count', 'Result',
  ];
  const ruleRows = ALL_RULES.map((r) => {
    const count = currentFindings.filter(
      (f) => f.rule_id === r.rule_id
    ).length;
    return [r.rule_id, r.rule_name, r.category, count, count > 0 ? 'Issues Found' : 'Clean'];
  });
  const ws6 = XLSX.utils.aoa_to_sheet([ruleHeaders, ...ruleRows]);
  applyHeaderStyle(ws6);
  XLSX.utils.book_append_sheet(wb, ws6, 'Rule Coverage');

  // Download
  const safeName = response.project_name.replace(/[^a-zA-Z0-9_-]/g, '_');
  XLSX.writeFile(wb, `UiPath_CodeReview_${safeName}_${date}.xlsx`);
}
