import { useState, useMemo, useEffect } from 'react';
import { useNavigate } from 'react-router-dom';
import { useReview } from '../context/ReviewContext';
import { submitFix, FixFileResult } from '../services/apiClient';
import SummaryPanel from '../components/SummaryPanel';
import ReviewGrid from '../components/ReviewGrid';
import ExportButton from '../components/ExportButton';
import RulesCatalogModal from '../components/RulesCatalogModal';
import DiffViewer from '../components/DiffViewer';

export default function ResultsPage() {
  const navigate = useNavigate();
  const {
    models,
    reviewResponse, findings, setFindings,
    reviewDuration, lastFormData, clearReview,
  } = useReview();

  // Redirect to home if no review data
  useEffect(() => {
    if (!reviewResponse) navigate('/', { replace: true });
  }, [reviewResponse, navigate]);

  // Filters
  const [activeCategories, setActiveCategories] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);

  const handleCategoryToggle = (category: string) => {
    setActiveCategories((prev) =>
      prev.includes(category) ? prev.filter((c) => c !== category) : [...prev, category]
    );
  };

  // Rules modal
  const [showRulesModal, setShowRulesModal] = useState(false);

  // Auto-fix
  const [isFixing, setIsFixing] = useState(false);
  const [fixResults, setFixResults] = useState<FixFileResult[] | null>(null);
  const [showDiffView, setShowDiffView] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [projectJson, setProjectJson] = useState<string | null>(null);
  const [fixId, setFixId] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [fixSummary, setFixSummary] = useState<{
    totalChanges: number;
    filesModified: number;
    filesDeleted: number;
    findingsFixed: number;
    findingsUnmatched: number;
  } | null>(null);

  const handleAutoFix = async () => {
    if (!reviewResponse || !lastFormData) return;
    setIsFixing(true);
    setError(null);
    setFixSummary(null);
    try {
      const fixFd = new FormData();
      fixFd.append('project_name', reviewResponse.project_name);
      fixFd.append('findings_json', JSON.stringify(findings));
      const origFiles = lastFormData.getAll('files');
      for (const file of origFiles) fixFd.append('files', file);
      const res = await submitFix(fixFd);
      setFixResults(res.files);
      setProjectJson(res.project_json ?? null);
      setFixId(res.fix_id ?? null);
      setShowDiffView(true);

      let totalChanges = 0;
      let filesModified = 0;
      let filesDeleted = 0;
      for (const f of res.files) {
        if (f.delete) filesDeleted++;
        if (f.changes.length > 0) filesModified++;
        totalChanges += f.changes.length;
      }

      // Mark every auto-fixable finding as Fixed. Rules are processed
      // uniformly — the user asked to fix everything going forward.
      let findingsFixed = 0;
      setFindings((prev) =>
        prev.map((f) => {
          if (f.auto_fixable) {
            findingsFixed++;
            return { ...f, status: 'Fixed' as const };
          }
          return f;
        })
      );

      setFixSummary({
        totalChanges,
        filesModified,
        filesDeleted,
        findingsFixed,
        findingsUnmatched: 0,
      });
    } catch (err: any) {
      setError(err.message ?? 'Auto-fix failed');
    } finally {
      setIsFixing(false);
    }
  };

  const handleFixAccepted = (path: string) => { setSavedPath(path); setShowDiffView(false); };
  const handleNewReview = () => { clearReview(); navigate('/'); setFixSummary(null); };

  const filteredFindings = useMemo(() => {
    let result = findings;
    if (activeCategories.length > 0) result = result.filter((f) => activeCategories.includes(f.category));
    if (activeFile) result = result.filter((f) => f.file_name === activeFile);
    return result;
  }, [findings, activeCategories, activeFile]);

  const fileNames = useMemo(() => [...new Set(findings.map((f) => f.file_name))].sort(), [findings]);
  const fixableCount = findings.filter((f) => f.auto_fixable).length;

  if (!reviewResponse) return null;

  return (
    <div className="space-y-6">
      {/* Top bar: back + actions */}
      <div className="flex items-center justify-between animate-fade-in">
        <button onClick={handleNewReview} className="inline-flex items-center gap-2 text-sm text-ui-g500 hover:text-ui-navy font-medium transition-colors">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 19l-7-7m0 0l7-7m-7 7h18" />
          </svg>
          New Review
        </button>
        <div className="flex items-center gap-2 text-xs text-ui-g400">
          <span className="bg-ui-g100 px-2.5 py-1 rounded-full font-medium">{reviewResponse.project_name}</span>
        </div>
      </div>

      {error && (
        <div className="flex items-center gap-2.5 px-5 py-3.5 bg-red-50 border border-red-200 rounded-2xl text-sm text-red-800 animate-scale-in">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span><strong>Error:</strong> {error}</span>
        </div>
      )}

      <SummaryPanel
        response={reviewResponse}
        findings={findings}
        models={models}
        activeCategories={activeCategories}
        onCategoryToggle={handleCategoryToggle}
        onClearCategories={() => setActiveCategories([])}
        reviewDuration={reviewDuration}
      />

      {/* Action bar */}
      <div className="flex items-center gap-3 flex-wrap animate-fade-in">
        <ExportButton response={reviewResponse} findings={findings} models={models} />

        <button onClick={() => setShowRulesModal(true)} className="btn-secondary">
          <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
          </svg>
          View Rules
        </button>

        {fixableCount > 0 && lastFormData && (
          <button
            onClick={handleAutoFix}
            disabled={isFixing || findings.length === 0}
            className="btn-success"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
            </svg>
            {isFixing ? 'Applying...' : `Auto-Fix (${fixableCount})`}
          </button>
        )}

        {savedPath && (
          <span className="text-xs text-green-600 font-medium flex items-center gap-1.5 bg-green-50 px-3 py-1.5 rounded-full border border-green-200">
            <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
            </svg>
            Saved to: {savedPath}
          </span>
        )}

        {fixResults && !savedPath && (
          <button onClick={() => setShowDiffView(true)} className="text-sm text-ui-orange hover:text-ui-orange-dark font-medium underline underline-offset-2">
            View diff again
          </button>
        )}
      </div>

      {fixSummary && !savedPath && (
        <div className="px-5 py-3.5 bg-green-50 border border-green-200 rounded-2xl text-sm animate-fade-in">
          <div className="flex items-start gap-2.5">
            <svg className="w-5 h-5 flex-shrink-0 text-green-600 mt-0.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            <div className="flex-1 text-green-900">
              <p className="font-medium">
                Applied <strong>{fixSummary.totalChanges}</strong> change{fixSummary.totalChanges === 1 ? '' : 's'} across{' '}
                <strong>{fixSummary.filesModified}</strong> file{fixSummary.filesModified === 1 ? '' : 's'}
                {fixSummary.filesDeleted > 0 && (
                  <> · <strong>{fixSummary.filesDeleted}</strong> file{fixSummary.filesDeleted === 1 ? '' : 's'} marked for deletion</>
                )}.
              </p>
            </div>
          </div>
        </div>
      )}

      {/* Active filters */}
      {(activeCategories.length > 0 || activeFile) && (
        <div className="flex items-center gap-2 text-sm flex-wrap animate-fade-in">
          <span className="text-ui-g500 text-xs font-medium">Filters:</span>
          {activeCategories.map((cat) => (
            <span key={cat} className="inline-flex items-center gap-1 bg-ui-orange-light border border-ui-orange/30 rounded-full px-3 py-1 text-xs text-ui-orange font-semibold">
              {cat}
              <button onClick={() => handleCategoryToggle(cat)} className="hover:text-ui-orange-dark ml-0.5">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          ))}
          {activeFile && (
            <span className="inline-flex items-center gap-1 bg-blue-50 border border-blue-200 rounded-full px-3 py-1 text-xs text-blue-700 font-semibold">
              {activeFile}
              <button onClick={() => setActiveFile(null)} className="hover:text-blue-900 ml-0.5">
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </span>
          )}
          <button onClick={() => { setActiveCategories([]); setActiveFile(null); }} className="text-xs text-ui-g400 hover:text-ui-g700 font-medium underline underline-offset-2">
            Clear all
          </button>
        </div>
      )}

      <ReviewGrid
        findings={filteredFindings}
        setFindings={setFindings}
        uploadMode={reviewResponse.upload_mode}
        fileNames={fileNames}
        activeFile={activeFile}
        onFileChange={setActiveFile}
      />

      {showRulesModal && <RulesCatalogModal onClose={() => setShowRulesModal(false)} />}

      {showDiffView && fixResults && (
        <DiffViewer
          projectName={reviewResponse.project_name}
          files={fixResults}
          projectJson={projectJson}
          fixId={fixId}
          onClose={() => setShowDiffView(false)}
          onAccepted={handleFixAccepted}
        />
      )}
    </div>
  );
}
