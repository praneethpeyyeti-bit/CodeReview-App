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

const SEVERITY_CONFIG: Record<Severity, { bg: string; text: string; dot: string; barColor: string }> = {
  CRITICAL: { bg: 'bg-red-600', text: 'text-white', dot: 'severity-dot-critical', barColor: 'bg-red-500' },
  HIGH:     { bg: 'bg-orange-500', text: 'text-white', dot: 'severity-dot-high', barColor: 'bg-orange-400' },
  MEDIUM:   { bg: 'bg-amber-400', text: 'text-amber-900', dot: 'severity-dot-medium', barColor: 'bg-amber-400' },
  LOW:      { bg: 'bg-blue-500', text: 'text-white', dot: 'severity-dot-low', barColor: 'bg-blue-400' },
  INFO:     { bg: 'bg-gray-400', text: 'text-white', dot: 'severity-dot-info', barColor: 'bg-gray-400' },
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

  const criticalCount = severityCounts.find((s) => s.severity === 'CRITICAL')?.count ?? 0;
  const highCount = severityCounts.find((s) => s.severity === 'HIGH')?.count ?? 0;
  const pass = criticalCount === 0 && highCount === 0;
  const maxSevCount = Math.max(...severityCounts.map((s) => s.count), 1);
  const modelLabel = models.find((m) => m.id === response.model_id)?.label ?? response.model_id;

  return (
    <div className="space-y-4 animate-fade-in-up">
      <div className="section-card">
        <button className="section-header w-full" onClick={() => setCollapsed((c) => !c)}>
          <h2>
            <svg className="w-4 h-4 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 19v-6a2 2 0 00-2-2H5a2 2 0 00-2 2v6a2 2 0 002 2h2a2 2 0 002-2zm0 0V9a2 2 0 012-2h2a2 2 0 012 2v10m-6 0a2 2 0 002 2h2a2 2 0 002-2m0 0V5a2 2 0 012-2h2a2 2 0 012 2v14a2 2 0 01-2 2h-2a2 2 0 01-2-2z" />
            </svg>
            Review Dashboard
          </h2>
          <div className="flex items-center gap-3">
            <span className="text-xs text-gray-400">{modelLabel}</span>
            <svg className={`w-4 h-4 text-gray-400 transition-transform duration-200 ${collapsed ? '' : 'rotate-180'}`} fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M19 9l-7 7-7-7" />
            </svg>
          </div>
        </button>

        {!collapsed && (
          <div className="p-6 space-y-6">
            {/* Top row: Verdict + Metrics */}
            <div className="grid grid-cols-1 lg:grid-cols-12 gap-5">
              {/* Verdict */}
              <div className={`lg:col-span-3 rounded-2xl p-5 flex items-center gap-4 verdict-ring ${
                pass
                  ? 'bg-gradient-to-br from-green-50 to-emerald-50 border-2 border-green-200'
                  : 'bg-gradient-to-br from-red-50 to-rose-50 border-2 border-red-200'
              }`}>
                <div className={`w-16 h-16 rounded-2xl flex items-center justify-center shadow-lg ${
                  pass ? 'bg-gradient-to-br from-green-500 to-emerald-600' : 'bg-gradient-to-br from-red-500 to-rose-600'
                }`}>
                  {pass ? (
                    <svg className="w-9 h-9 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                    </svg>
                  ) : (
                    <svg className="w-9 h-9 text-white" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
                    </svg>
                  )}
                </div>
                <div>
                  <p className={`text-2xl font-extrabold ${pass ? 'text-green-700' : 'text-red-700'}`}>
                    {pass ? 'PASS' : 'NEEDS WORK'}
                  </p>
                  <p className={`text-xs font-medium ${pass ? 'text-green-600' : 'text-red-600'}`}>
                    {pass ? 'No critical or high issues' : `${criticalCount + highCount} critical/high issue(s)`}
                  </p>
                </div>
              </div>

              {/* Metric cards */}
              <div className="lg:col-span-2 metric-card">
                <p className="metric-label">Total Findings</p>
                <p className="metric-value">{findings.length}</p>
              </div>

              <div className="lg:col-span-2 metric-card">
                <p className="metric-label">Files Reviewed</p>
                <p className="metric-value">{response.total_files}</p>
              </div>

              <div className="lg:col-span-2 metric-card">
                <p className="metric-label">Auto-Fixable</p>
                <p className="metric-value text-ui-orange">{findings.filter((f) => f.auto_fixable).length}</p>
              </div>

              {reviewDuration != null && (
                <div className="lg:col-span-3 metric-card">
                  <p className="metric-label">Review Time</p>
                  <p className="metric-value">
                    {reviewDuration >= 60 ? `${Math.floor(reviewDuration / 60)}m ${reviewDuration % 60}s` : `${reviewDuration}s`}
                  </p>
                </div>
              )}
            </div>

            {/* Severity breakdown bars */}
            <div>
              <p className="text-[11px] font-semibold uppercase tracking-wider text-ui-g500 mb-3">Severity Distribution</p>
              <div className="space-y-2.5">
                {severityCounts.map(({ severity, count }) => {
                  const cfg = SEVERITY_CONFIG[severity];
                  const pct = maxSevCount > 0 ? (count / maxSevCount) * 100 : 0;
                  return (
                    <div key={severity} className="flex items-center gap-3">
                      <span className={`severity-badge ${cfg.bg} ${cfg.text} w-20 justify-center text-[10px]`}>{severity}</span>
                      <div className="flex-1 bg-ui-g100 rounded-full h-2.5 overflow-hidden">
                        <div className={`severity-bar ${cfg.barColor}`} style={{ width: `${pct}%` }} />
                      </div>
                      <span className="text-sm font-bold text-ui-g700 w-8 text-right">{count}</span>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* Category pills */}
            {categoryCounts.length > 0 && (
              <div className="pt-4 border-t border-ui-g100">
                <p className="text-[11px] font-semibold uppercase tracking-wider text-ui-g500 mb-3">Filter by Category</p>
                <div className="flex flex-wrap gap-2">
                  {activeCategories.length > 0 && (
                    <button onClick={onClearCategories} className="category-pill bg-ui-g100 border-ui-g300 text-ui-g500 hover:text-ui-g700">
                      Clear All
                      <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  )}
                  {categoryCounts.sort((a, b) => b.count - a.count).map(({ category, count }) => {
                    const isActive = activeCategories.includes(category);
                    return (
                      <button key={category} onClick={() => onCategoryToggle(category)}
                        className={`category-pill ${isActive ? 'category-pill-active' : 'category-pill-inactive'}`}
                      >
                        {category}
                        <span className={`rounded-full px-1.5 py-0.5 text-[10px] font-bold min-w-[20px] text-center ${
                          isActive ? 'bg-ui-orange text-white' : 'bg-ui-g200 text-ui-g600'
                        }`}>
                          {count}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </div>
            )}

            {/* Metadata */}
            <div className="pt-4 border-t border-ui-g100 flex flex-wrap gap-x-6 gap-y-2 text-xs text-ui-g500">
              <span>Project: <strong className="text-ui-g700">{response.project_name}</strong></span>
              <span>Mode: <strong className="text-ui-g700">{response.upload_mode}</strong></span>
              {response.zip_file_name && <span>ZIP: <strong className="text-ui-g700">{response.zip_file_name}</strong></span>}
              <span>{new Date(response.reviewed_at).toLocaleString()}</span>
            </div>
          </div>
        )}
      </div>

      {/* Skipped files */}
      {response.skipped_files.length > 0 && (
        <div className="flex items-start gap-2.5 px-5 py-3.5 bg-amber-50 border border-amber-200 rounded-2xl text-sm text-amber-800 animate-fade-in">
          <svg className="w-5 h-5 mt-0.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          <div>
            <strong>{response.skipped_files.length} file(s) skipped</strong> (too large): {response.skipped_files.join(', ')}
          </div>
        </div>
      )}
    </div>
  );
}
