import { useState, useEffect, useMemo, useRef } from 'react';
import { Finding, ModelOption, ReviewResponse } from '../models/finding';
import { getModels, submitReview, submitFix, FixFileResult } from '../services/apiClient';
import UploadZone from '../components/UploadZone';
import SummaryPanel from '../components/SummaryPanel';
import ReviewGrid from '../components/ReviewGrid';
import ExportButton from '../components/ExportButton';
import RulesCatalogModal from '../components/RulesCatalogModal';
import DiffViewer from '../components/DiffViewer';

export default function ReviewPage() {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [reviewResponse, setReviewResponse] = useState<ReviewResponse | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filters
  const [activeCategories, setActiveCategories] = useState<string[]>([]);
  const [activeFile, setActiveFile] = useState<string | null>(null);

  const handleCategoryToggle = (category: string) => {
    setActiveCategories((prev) =>
      prev.includes(category)
        ? prev.filter((c) => c !== category)
        : [...prev, category]
    );
  };

  // Rules modal
  const [showRulesModal, setShowRulesModal] = useState(false);

  // Auto-fix state
  const [isFixing, setIsFixing] = useState(false);
  const [fixResults, setFixResults] = useState<FixFileResult[] | null>(null);
  const [showDiffView, setShowDiffView] = useState(false);
  const [savedPath, setSavedPath] = useState<string | null>(null);
  const [projectJson, setProjectJson] = useState<string | null>(null);
  const [reviewDuration, setReviewDuration] = useState<number | null>(null);

  // Store the last submitted FormData so we can re-submit for re-run
  const lastFormDataRef = useRef<FormData | null>(null);
  const lastModelLabelRef = useRef<string>('');

  useEffect(() => {
    getModels()
      .then((res) => {
        setModels(res.models);
        setModelsLoading(false);
      })
      .catch((err) => {
        console.error('Failed to load models:', err);
        setModelsError(
          'Could not load model list from backend. Using defaults.'
        );
        setModelsLoading(false);
      });
  }, []);

  const handleSubmit = async (formData: FormData, modelLabel: string) => {
    setIsLoading(true);
    setError(null);
    setActiveCategories([]);
    setActiveFile(null);
    setFixResults(null);
    setSavedPath(null);

    // Clone the formData for potential re-use
    lastFormDataRef.current = formData;
    lastModelLabelRef.current = modelLabel;

    const startTime = Date.now();
    try {
      const res = await submitReview(formData);
      setReviewDuration(Math.round((Date.now() - startTime) / 1000));
      setReviewResponse(res);
      setFindings(res.findings.map((f) => ({ ...f })));
    } catch (err: any) {
      const msg = err.message ?? 'Unknown error';
      setError(msg);
      if (msg.includes('Region')) {
        setError(msg + ' — Try selecting a different model for your region.');
      }
    } finally {
      setIsLoading(false);
    }
  };

  const handleAutoFix = async () => {
    if (!reviewResponse || !lastFormDataRef.current) return;
    setIsFixing(true);
    setError(null);

    try {
      // Build fix request with the original files + findings
      const fixFd = new FormData();
      fixFd.append('project_name', reviewResponse.project_name);
      fixFd.append('findings_json', JSON.stringify(findings));

      // Re-attach files from the original FormData
      const origFiles = lastFormDataRef.current.getAll('files');
      for (const file of origFiles) {
        fixFd.append('files', file);
      }

      const res = await submitFix(fixFd);
      setFixResults(res.files);
      setProjectJson(res.project_json ?? null);
      setShowDiffView(true);
    } catch (err: any) {
      setError(err.message ?? 'Auto-fix failed');
    } finally {
      setIsFixing(false);
    }
  };

  const handleFixAccepted = (path: string) => {
    setSavedPath(path);
    setShowDiffView(false);
  };

  // Compute filtered findings
  const filteredFindings = useMemo(() => {
    let result = findings;
    if (activeCategories.length > 0) {
      result = result.filter((f) => activeCategories.includes(f.category));
    }
    if (activeFile) {
      result = result.filter((f) => f.file_name === activeFile);
    }
    return result;
  }, [findings, activeCategories, activeFile]);

  // Unique file names for the file filter dropdown
  const fileNames = useMemo(
    () => [...new Set(findings.map((f) => f.file_name))].sort(),
    [findings]
  );

  const fixableCount = findings.filter((f) => f.auto_fixable).length;

  return (
    <div className="space-y-6">
      {modelsError && (
        <div className="bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 text-sm text-amber-800 flex items-center gap-2">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          {modelsError}
        </div>
      )}

      <UploadZone
        onSubmit={handleSubmit}
        isLoading={isLoading}
        models={models}
        modelsLoading={modelsLoading}
      />

      {error && (
        <div className="bg-red-50 border border-red-200 rounded-xl px-4 py-3 text-sm text-red-800 flex items-center gap-2">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M10 14l2-2m0 0l2-2m-2 2l-2-2m2 2l2 2m7-2a9 9 0 11-18 0 9 9 0 0118 0z" />
          </svg>
          <span><strong>Error:</strong> {error}</span>
        </div>
      )}

      {reviewResponse && (
        <>
          <SummaryPanel
            response={reviewResponse}
            findings={findings}
            models={models}
            activeCategories={activeCategories}
            onCategoryToggle={handleCategoryToggle}
            onClearCategories={() => setActiveCategories([])}
            reviewDuration={reviewDuration}
          />

          <div className="flex items-center gap-3 flex-wrap">
            <ExportButton
              response={reviewResponse}
              findings={findings}
              models={models}
            />
            <button
              onClick={() => setShowRulesModal(true)}
              className="flex items-center gap-2 px-4 py-2 bg-ui-navy text-white text-sm font-medium rounded-lg hover:bg-ui-navy-light transition-colors"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
              </svg>
              View Rules
            </button>
            <button
              onClick={handleAutoFix}
              disabled={isFixing || findings.length === 0}
              className="flex items-center gap-2 px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
              </svg>
              {isFixing ? 'Applying Fixes...' : 'Auto-Fix'}
            </button>

            {savedPath && (
              <span className="text-xs text-green-600 flex items-center gap-1">
                <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 13l4 4L19 7" />
                </svg>
                Fixes saved to: {savedPath}
              </span>
            )}

            {fixResults && !savedPath && (
              <button
                onClick={() => setShowDiffView(true)}
                className="text-sm text-ui-orange hover:text-ui-orange-dark underline"
              >
                View diff again
              </button>
            )}
          </div>

          {/* Active filter indicators */}
          {(activeCategories.length > 0 || activeFile) && (
            <div className="flex items-center gap-2 text-sm flex-wrap">
              <span className="text-ui-g500">Filtering by:</span>
              {activeCategories.map((cat) => (
                <span key={cat} className="inline-flex items-center gap-1 bg-ui-orange-light border border-ui-orange rounded-full px-3 py-1 text-xs text-ui-orange font-medium">
                  {cat}
                  <button onClick={() => handleCategoryToggle(cat)} className="hover:text-ui-orange-dark">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </span>
              ))}
              {activeFile && (
                <span className="inline-flex items-center gap-1 bg-blue-50 border border-blue-300 rounded-full px-3 py-1 text-xs text-blue-700 font-medium">
                  {activeFile}
                  <button onClick={() => setActiveFile(null)} className="hover:text-blue-900">
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={3}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </span>
              )}
              <button
                onClick={() => { setActiveCategories([]); setActiveFile(null); }}
                className="text-xs text-ui-g400 hover:text-ui-g700 underline"
              >
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
        </>
      )}

      {showRulesModal && (
        <RulesCatalogModal onClose={() => setShowRulesModal(false)} />
      )}

      {showDiffView && fixResults && reviewResponse && (
        <DiffViewer
          projectName={reviewResponse.project_name}
          files={fixResults}
          projectJson={projectJson}
          onClose={() => setShowDiffView(false)}
          onAccepted={handleFixAccepted}
        />
      )}
    </div>
  );
}
