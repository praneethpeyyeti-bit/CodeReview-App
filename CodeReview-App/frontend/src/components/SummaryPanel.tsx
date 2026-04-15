import { useState } from 'react';
import { Finding, ReviewResponse, ModelOption, Severity } from '../models/finding';

interface Props {
  response: ReviewResponse;
  findings: Finding[];
  models: ModelOption[];
  activeCategories: string[];
  onCategoryToggle: (category: string) => void;
  onClearCategories: () => void;
  reviewDuration?: number | null;
}

const SEVERITY_ORDER: Severity[] = ['CRITICAL', 'HIGH', 'MEDIUM', 'LOW', 'INFO'];

const SEVERITY_STYLES: Record<Severity, { bg: string; text: string; ring: string }> = {
  CRITICAL: { bg: 'bg-red-600', text: 'text-white', ring: 'ring-red-200' },
  HIGH: { bg: 'bg-orange-500', text: 'text-white', ring: 'ring-orange-200' },
  MEDIUM: { bg: 'bg-amber-400', text: 'text-amber-900', ring: 'ring-amber-200' },
  LOW: { bg: 'bg-blue-500', text: 'text-white', ring: 'ring-blue-200' },
  INFO: { bg: 'bg-ui-g400', text: 'text-white', ring: 'ring-gray-200' },
};

export default function SummaryPanel({ response, findings, models, activeCategories, onCategoryToggle, onClearCategories, reviewDuration }: Props) {
  const [collapsed, setCollapsed] = useState(false);

  const severityCounts = SEVERITY_ORDER.map((s) => ({
    severity: s,
    count: findings.filter((f) => f.severity === s).length,
  }));

  const categories = [...new Set(findings.map((f) => f.category))];
  const categoryCounts = categories.map((c) => ({
    category: c,
    count: findings.filter((f) => f.category === c).length,
  }));

  const criticalCount =
    severityCounts.find((s) => s.severity === 'CRITICAL')?.count ?? 0;
  const highCount =
    severityCounts.find((s) => s.severity === 'HIGH')?.count ?? 0;
  const pass = criticalCount === 0 && highCount === 0;

  const modelLabel =
    models.find((m) => m.id === response.model_id)?.label ?? response.model_id;

  return (
    <div className="space-y-5">
      {/* Report header */}
      <div className="bg-white rounded-xl shadow-sm border border-ui-g200 overflow-hidden">
        <button
          className="w-full bg-ui-navy px-6 py-3 flex items-center justify-between cursor-pointer hover:bg-ui-navy-light transition-colors"
          onClick={() => setCollapsed((c) => !c)}
        >
          <h2 className="text-white font-semibold text-sm tracking-wide">Review Report</h2>
          <div className="flex items-center gap-3">
            <div className="flex items-center gap-3 text-xs text-gray-400">
              <span>Model: {modelLabel}</span>
              <span>{new Date(response.reviewed_at).toLocaleString()}</span>
            </div>
            <svg
              className={`w-4 h-4 text-gray-400 transition-transform ${collapsed ? '' : 'rotate-180'}`}
              fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}
            >
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </button>

        {!collapsed && (
          <div className="p-6">
            {/* Score & verdict */}
            <div className="flex flex-wrap items-start gap-6">
              {/* Verdict card */}
              <div className={`flex items-center gap-4 px-6 py-4 rounded-xl ${
                pass
                  ? 'bg-green-50 border-2 border-green-200'
                  : 'bg-red-50 border-2 border-red-200'
              }`}>
                <div className={`w-14 h-14 rounded-full flex items-center justify-center ${
                  pass ? 'bg-green-500' : 'bg-red-500'
                }`}>
                  {pass ? (
                    <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-8 h-8 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  )}
                </div>
                <div>
                  <p className={`text-2xl font-bold ${pass ? 'text-green-700' : 'text-red-700'}`}>
                    {pass ? 'PASS' : 'FAIL'}
                  </p>
                  <p className={`text-xs ${pass ? 'text-green-600' : 'text-red-600'}`}>
                    {pass ? 'No critical or high severity issues' : `${criticalCount + highCount} critical/high issue(s) found`}
                  </p>
                </div>
              </div>

              {/* Total findings */}
              <div className="bg-ui-g50 rounded-xl px-6 py-4 border border-ui-g200">
                <p className="text-xs text-ui-g500 uppercase font-medium tracking-wider">Total Findings</p>
                <p className="text-3xl font-bold text-ui-navy mt-1">{findings.length}</p>
              </div>

              {/* Severity breakdown */}
              <div className="flex-1 min-w-[300px]">
                <p className="text-xs text-ui-g500 uppercase font-medium tracking-wider mb-2">Severity Breakdown</p>
                <div className="flex gap-2">
                  {severityCounts.map(({ severity, count }) => {
                    const style = SEVERITY_STYLES[severity];
                    return (
                      <div
                        key={severity}
                        className={`flex-1 rounded-lg px-3 py-2 text-center ring-1 ${style.ring} bg-white`}
                      >
                        <span className={`severity-badge inline-block px-2 py-0.5 rounded text-xs font-bold ${style.bg} ${style.text}`}>
                          {severity}
                        </span>
                        <p className="text-xl font-bold text-ui-g800 mt-1">{count}</p>
                      </div>
                    );
                  })}
                </div>
              </div>
            </div>

            {/* Category chips — interactive */}
            {categoryCounts.length > 0 && (
              <div className="mt-5 pt-5 border-t border-ui-g100">
                <p className="text-xs text-ui-g500 uppercase font-medium tracking-wider mb-2">Categories</p>
                <div className="flex flex-wrap gap-2">
                  {activeCategories.length > 0 && (
                    <button
                      onClick={onClearCategories}
                      className="inline-flex items-center gap-1 rounded-full px-3 py-1.5 text-xs bg-ui-g100 border border-ui-g300 text-ui-g500 hover:text-ui-g700 hover:border-ui-g400 transition-colors cursor-pointer"
                    >
                      Clear All
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                  {categoryCounts
                    .sort((a, b) => b.count - a.count)
                    .map(({ category, count }) => {
                      const isActive = activeCategories.includes(category);
                      return (
                        <button
                          key={category}
                          onClick={() => onCategoryToggle(category)}
                          className={`inline-flex items-center gap-1.5 rounded-full px-3 py-1.5 text-xs transition-colors cursor-pointer ${
                            isActive
                              ? 'bg-ui-orange-light border-2 border-ui-orange text-ui-orange font-semibold'
                              : 'bg-ui-g50 border border-ui-g200 text-ui-g700 hover:border-ui-orange'
                          }`}
                        >
                          {category}
                          <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold min-w-[20px] text-center ${
                            isActive ? 'bg-ui-orange text-white' : 'bg-ui-orange text-white'
                          }`}>
                            {count}
                          </span>
                        </button>
                      );
                    })}
                </div>
              </div>
            )}

            {/* Metadata row */}
            <div className="mt-5 pt-4 border-t border-ui-g100 flex flex-wrap gap-6 text-xs text-ui-g500">
              <span className="flex items-center gap-1">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 7v10a2 2 0 002 2h14a2 2 0 002-2V9a2 2 0 00-2-2h-6l-2-2H5a2 2 0 00-2 2z" />
                </svg>
                Project: <strong className="text-ui-g700">{response.project_name}</strong>
              </span>
              <span className="flex items-center gap-1">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
                Files: <strong className="text-ui-g700">{response.total_files}</strong>
              </span>
              <span className="flex items-center gap-1">
                Mode: <strong className="text-ui-g700">{response.upload_mode}</strong>
              </span>
              {response.zip_file_name && (
                <span>
                  ZIP: <strong className="text-ui-g700">{response.zip_file_name}</strong>
                </span>
              )}
              {reviewDuration != null && (
                <span className="flex items-center gap-1">
                  <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                    <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4l3 3m6-3a9 9 0 11-18 0 9 9 0 0118 0z" />
                  </svg>
                  Review time: <strong className="text-ui-g700">
                    {reviewDuration >= 60
                      ? `${Math.floor(reviewDuration / 60)}m ${reviewDuration % 60}s`
                      : `${reviewDuration}s`}
                  </strong>
                </span>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Skipped files warning */}
      {response.skipped_files.length > 0 && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800 flex items-start gap-2">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          <div>
            <strong>{response.skipped_files.length} file(s) were skipped</strong>{' '}
            (too large): {response.skipped_files.join(', ')}
          </div>
        </div>
      )}
    </div>
  );
}
