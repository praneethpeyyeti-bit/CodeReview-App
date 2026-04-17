import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useReview } from '../context/ReviewContext';
import { submitReview } from '../services/apiClient';
import UploadZone from '../components/UploadZone';

export default function HomePage() {
  const navigate = useNavigate();
  const {
    models, modelsLoading, modelsError,
    setReviewResponse, setFindings, setReviewDuration,
    setLastFormData, setLastModelLabel,
  } = useReview();

  const [isLoading, setIsLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const handleSubmit = async (formData: FormData, modelLabel: string) => {
    setIsLoading(true);
    setError(null);
    setLastFormData(formData);
    setLastModelLabel(modelLabel);

    const startTime = Date.now();
    try {
      const res = await submitReview(formData);
      setReviewDuration(Math.round((Date.now() - startTime) / 1000));
      setReviewResponse(res);
      setFindings(res.findings.map((f) => ({ ...f })));
      navigate('/results');
    } catch (err: any) {
      const msg = err.message ?? 'Unknown error';
      setError(msg.includes('Region') ? msg + ' — Try selecting a different model.' : msg);
    } finally {
      setIsLoading(false);
    }
  };

  return (
    <div className="space-y-3 animate-fade-in">
      {modelsError && (
        <div className="flex items-center gap-2.5 px-5 py-3.5 bg-amber-50 border border-amber-200 rounded-2xl text-sm text-amber-800">
          <svg className="w-5 h-5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M12 9v2m0 4h.01m-6.938 4h13.856c1.54 0 2.502-1.667 1.732-2.5L13.732 4c-.77-.833-1.964-.833-2.732 0L4.082 16.5c-.77.833.192 2.5 1.732 2.5z" />
          </svg>
          {modelsError}
        </div>
      )}

      {/* Split layout: left description + right upload */}
      <div className="grid grid-cols-1 lg:grid-cols-5 gap-6 items-stretch">
        {/* Left: Description */}
        <div className="lg:col-span-2 pt-4 lg:pt-8 animate-fade-in">
          <h2 className="text-3xl font-extrabold text-ui-navy tracking-tight leading-tight">
            Review Your<br />UiPath Workflows
          </h2>
          <p className="text-ui-g500 mt-3 text-sm leading-relaxed">
            Upload XAML files or a project ZIP and get AI-powered analysis against 47 Workflow Analyzer rules in seconds.
          </p>

          {/* Feature list */}
          <div className="mt-8 space-y-4">
            <div className="flex items-start gap-3">
              <div className="w-9 h-9 bg-ui-orange-light rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg className="w-4.5 h-4.5 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 5H7a2 2 0 00-2 2v12a2 2 0 002 2h10a2 2 0 002-2V7a2 2 0 00-2-2h-2M9 5a2 2 0 002 2h2a2 2 0 002-2M9 5a2 2 0 012-2h2a2 2 0 012 2" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-ui-g700">47 Workflow Analyzer Rules</p>
                <p className="text-xs text-ui-g400 mt-0.5">Naming, design, security, performance, reliability checks</p>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="w-9 h-9 bg-ui-orange-light rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg className="w-4.5 h-4.5 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11 5H6a2 2 0 00-2 2v11a2 2 0 002 2h11a2 2 0 002-2v-5m-1.414-9.414a2 2 0 112.828 2.828L11.828 15H9v-2.828l8.586-8.586z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-ui-g700">Auto-Fix with Diff Preview</p>
                <p className="text-xs text-ui-g400 mt-0.5">Automatically fix naming convention violations across all locations</p>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="w-9 h-9 bg-ui-orange-light rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg className="w-4.5 h-4.5 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M12 10v6m0 0l-3-3m3 3l3-3m2 8H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-ui-g700">Excel Export</p>
                <p className="text-xs text-ui-g400 mt-0.5">Download findings as a styled report for leadership review</p>
              </div>
            </div>

            <div className="flex items-start gap-3">
              <div className="w-9 h-9 bg-ui-orange-light rounded-xl flex items-center justify-center flex-shrink-0 mt-0.5">
                <svg className="w-4.5 h-4.5 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m5.618-4.016A11.955 11.955 0 0112 2.944a11.955 11.955 0 01-8.618 3.04A12.02 12.02 0 003 9c0 5.591 3.824 10.29 9 11.622 5.176-1.332 9-6.03 9-11.622 0-1.042-.133-2.052-.382-3.016z" />
                </svg>
              </div>
              <div>
                <p className="text-sm font-semibold text-ui-g700">AI Trust Layer</p>
                <p className="text-xs text-ui-g400 mt-0.5">Claude, GPT-4, Gemini via UiPath secure gateway</p>
              </div>
            </div>
          </div>
        </div>

        {/* Right: Upload zone */}
        <div className="lg:col-span-3 flex flex-col">
          <UploadZone
            onSubmit={handleSubmit}
            isLoading={isLoading}
            models={models}
            modelsLoading={modelsLoading}
          />
        </div>
      </div>

      {/* Animated workflow pipeline */}
      <div className="animate-fade-in-up" style={{ animationDelay: '0.3s', animationFillMode: 'both' }}>
        <div className="relative rounded-2xl px-8 py-7 overflow-hidden"
             style={{ background: 'linear-gradient(135deg, #0d1b2a 0%, #1b2d45 50%, #253b56 100%)' }}>

          <p className="text-[10px] font-semibold uppercase tracking-widest text-gray-400 mb-6 relative">How It Works</p>

          <div className="relative flex items-center justify-between">
            {/* Step 1: Upload */}
            <div className="flex-1 text-center group pipeline-icon pipeline-icon-1">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center
                              transition-all duration-500 group-hover:scale-110 group-hover:bg-white/20 group-hover:border-ui-orange/50">
                <svg className="w-6 h-6 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M3 16.5v2.25A2.25 2.25 0 005.25 21h13.5A2.25 2.25 0 0021 18.75V16.5m-13.5-9L12 3m0 0l4.5 4.5M12 3v13.5" />
                </svg>
              </div>
              <p className="text-xs font-semibold text-white mt-2.5">Upload</p>
              <p className="text-[10px] text-gray-400 mt-0.5">.xaml or .zip</p>
            </div>

            {/* Arrow 1→2 */}
            <div className="flex-shrink-0 w-12 flex items-center justify-center pipeline-arrow pipeline-arrow-1">
              <svg className="w-8 h-8 text-ui-orange/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </div>

            {/* Step 2: Parse */}
            <div className="flex-1 text-center group pipeline-icon pipeline-icon-2">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center
                              transition-all duration-500 group-hover:scale-110 group-hover:bg-white/20 group-hover:border-blue-400/50">
                <svg className="w-6 h-6 text-blue-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M17.25 6.75L22.5 12l-5.25 5.25m-10.5 0L1.5 12l5.25-5.25m7.5-3l-4.5 16.5" />
                </svg>
              </div>
              <p className="text-xs font-semibold text-white mt-2.5">Parse XAML</p>
              <p className="text-[10px] text-gray-400 mt-0.5">Extract context</p>
            </div>

            {/* Arrow 2→3 */}
            <div className="flex-shrink-0 w-12 flex items-center justify-center pipeline-arrow pipeline-arrow-2">
              <svg className="w-8 h-8 text-blue-400/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </div>

            {/* Step 3: AI Review */}
            <div className="flex-1 text-center group pipeline-icon pipeline-icon-3">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center
                              transition-all duration-500 group-hover:scale-110 group-hover:bg-white/20 group-hover:border-purple-400/50">
                <svg className="w-6 h-6 text-purple-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09zM18.259 8.715L18 9.75l-.259-1.035a3.375 3.375 0 00-2.455-2.456L14.25 6l1.036-.259a3.375 3.375 0 002.455-2.456L18 2.25l.259 1.035a3.375 3.375 0 002.455 2.456L21.75 6l-1.036.259a3.375 3.375 0 00-2.455 2.456z" />
                </svg>
              </div>
              <p className="text-xs font-semibold text-white mt-2.5">AI Review</p>
              <p className="text-[10px] text-gray-400 mt-0.5">47 rules checked</p>
            </div>

            {/* Arrow 3→4 */}
            <div className="flex-shrink-0 w-12 flex items-center justify-center pipeline-arrow pipeline-arrow-3">
              <svg className="w-8 h-8 text-purple-400/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </div>

            {/* Step 4: Results */}
            <div className="flex-1 text-center group pipeline-icon pipeline-icon-4">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center
                              transition-all duration-500 group-hover:scale-110 group-hover:bg-white/20 group-hover:border-emerald-400/50">
                <svg className="w-6 h-6 text-emerald-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M10.125 2.25h-4.5c-.621 0-1.125.504-1.125 1.125v17.25c0 .621.504 1.125 1.125 1.125h12.75c.621 0 1.125-.504 1.125-1.125v-9M10.125 2.25h.375a9 9 0 019 9v.375M10.125 2.25A3.375 3.375 0 0113.5 5.625v1.5c0 .621.504 1.125 1.125 1.125h1.5a3.375 3.375 0 013.375 3.375M9 15l2.25 2.25L15 12" />
                </svg>
              </div>
              <p className="text-xs font-semibold text-white mt-2.5">Results</p>
              <p className="text-[10px] text-gray-400 mt-0.5">Dashboard</p>
            </div>

            {/* Arrow 4→5 */}
            <div className="flex-shrink-0 w-12 flex items-center justify-center pipeline-arrow pipeline-arrow-4">
              <svg className="w-8 h-8 text-emerald-400/60" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M13.5 4.5L21 12m0 0l-7.5 7.5M21 12H3" />
              </svg>
            </div>

            {/* Step 5: Auto-Fix */}
            <div className="flex-1 text-center group pipeline-icon pipeline-icon-5">
              <div className="w-14 h-14 mx-auto rounded-2xl bg-white/10 backdrop-blur border border-white/20 flex items-center justify-center
                              transition-all duration-500 group-hover:scale-110 group-hover:bg-white/20 group-hover:border-amber-400/50">
                <svg className="w-6 h-6 text-amber-400" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M11.42 15.17l-5.384-5.383a1.745 1.745 0 01-.514-1.243V5.247c0-.69.56-1.25 1.25-1.25h3.297c.464 0 .91.184 1.238.513l5.384 5.383a1.75 1.75 0 010 2.475l-3.796 3.796a1.745 1.745 0 01-2.475 0z" />
                  <path strokeLinecap="round" strokeLinejoin="round" d="M7.5 8.25h.008v.008H7.5V8.25z" />
                </svg>
              </div>
              <p className="text-xs font-semibold text-white mt-2.5">Auto-Fix</p>
              <p className="text-[10px] text-gray-400 mt-0.5">Rename & save</p>
            </div>
          </div>
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
    </div>
  );
}
