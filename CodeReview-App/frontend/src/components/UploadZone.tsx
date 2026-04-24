import { useState, useEffect, useCallback, DragEvent, ChangeEvent } from 'react';
import { ModelOption } from '../models/finding';

interface Props {
  onSubmit: (formData: FormData, modelLabel: string) => void;
  isLoading: boolean;
  models: ModelOption[];
  modelsLoading: boolean;
}

export default function UploadZone({
  onSubmit,
  isLoading,
  models,
  modelsLoading,
}: Props) {
  const [xamlFiles, setXamlFiles] = useState<File[]>([]);
  const [zipFile, setZipFile] = useState<File | null>(null);
  const [projectName, setProjectName] = useState('');
  const [useAI, setUseAI] = useState(false);
  const [selectedModelId, setSelectedModelId] = useState('anthropic.claude-3-7-sonnet-20250219-v1:0');
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);

  useEffect(() => {
    if (models.length > 0) {
      const recommended = models.find((m) => m.recommended && m.provider === 'Anthropic');
      if (recommended) setSelectedModelId(recommended.id);
    }
  }, [models]);

  const handleDrop = useCallback(
    (e: DragEvent) => {
      e.preventDefault();
      setDragOver(false);
      setFileError(null);
      const dropped = Array.from(e.dataTransfer.files);
      const xamls = dropped.filter((f) => f.name.toLowerCase().endsWith('.xaml'));
      const zips = dropped.filter((f) => f.name.toLowerCase().endsWith('.zip'));
      const others = dropped.filter((f) => !f.name.toLowerCase().endsWith('.xaml') && !f.name.toLowerCase().endsWith('.zip'));

      if (others.length > 0) { setFileError('Only .xaml and .zip files are accepted.'); return; }
      if (xamls.length > 0 && zips.length > 0) { setFileError('Upload either .xaml files or a single .zip, not both.'); return; }
      if (zips.length > 1) { setFileError('Please drop a single .zip file.'); return; }

      if (zips.length === 1) {
        if (xamlFiles.length > 0) { setFileError('Remove existing .xaml files first.'); return; }
        setZipFile(zips[0]);
        if (!projectName) setProjectName(zips[0].name.replace(/\.zip$/i, ''));
      }
      if (xamls.length > 0) {
        if (zipFile) { setFileError('Remove existing .zip first.'); return; }
        setXamlFiles((prev) => [...prev, ...xamls]);
      }
    },
    [projectName, xamlFiles.length, zipFile]
  );

  const handleFileInput = (e: ChangeEvent<HTMLInputElement>) => {
    setFileError(null);
    const selected = Array.from(e.target.files || []);
    const xamls = selected.filter((f) => f.name.toLowerCase().endsWith('.xaml'));
    const zips = selected.filter((f) => f.name.toLowerCase().endsWith('.zip'));

    if (xamls.length > 0 && zips.length > 0) setFileError('Select either .xaml files or a single .zip, not both.');
    else if (zips.length > 1) setFileError('Select a single .zip file.');
    else if (zips.length === 1) {
      if (xamlFiles.length > 0) setFileError('Remove existing .xaml files first.');
      else { setZipFile(zips[0]); if (!projectName) setProjectName(zips[0].name.replace(/\.zip$/i, '')); }
    } else if (xamls.length > 0) {
      if (zipFile) setFileError('Remove existing .zip first.');
      else setXamlFiles((prev) => [...prev, ...xamls]);
    }
    e.target.value = '';
  };

  const removeXaml = (index: number) => setXamlFiles((prev) => prev.filter((_, i) => i !== index));
  const hasFiles = xamlFiles.length > 0 || zipFile !== null;
  const canSubmit = hasFiles && projectName.trim() !== '' && !isLoading;

  const handleSubmit = () => {
    const fd = new FormData();
    fd.append('project_name', projectName.trim());
    const modelId = useAI ? selectedModelId : 'static';
    fd.append('model_id', modelId);
    if (zipFile) fd.append('files', zipFile);
    else xamlFiles.forEach((f) => fd.append('files', f));
    const modelLabel = useAI
      ? (models.find((m) => m.id === selectedModelId)?.label ?? selectedModelId)
      : 'Static Analysis';
    onSubmit(fd, modelLabel);
  };

  const aiModels = models.filter((m) => m.id !== 'static');
  const providers = [...new Set(aiModels.map((m) => m.provider))];

  return (
    <div className="section-card animate-fade-in flex flex-col flex-1">
      <div className="section-header flex-shrink-0">
        <h2>
          <svg className="w-4 h-4 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
            <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
          </svg>
          Upload Project
        </h2>
        {hasFiles && (
          <span className="text-xs text-gray-400 bg-white/10 px-2.5 py-0.5 rounded-full">
            {zipFile ? zipFile.name : `${xamlFiles.length} file(s)`}
          </span>
        )}
      </div>

      <div className="px-4 py-3 flex-1 flex flex-col gap-2.5">
        {/* Drop zone — fills available space */}
        <div
          className={`border-2 border-dashed rounded-lg px-4 transition-all flex-1 flex flex-col items-center justify-center min-h-0 ${
            dragOver ? 'border-ui-orange bg-ui-orange-light' : 'border-ui-g300 bg-ui-g50'
          } ${isLoading ? 'opacity-50 pointer-events-none' : ''}`}
          onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
          onDragLeave={() => setDragOver(false)}
          onDrop={handleDrop}
        >
          <div className="w-10 h-10 bg-ui-orange-light rounded-xl flex items-center justify-center mb-2">
            <svg className="w-5 h-5 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={1.5}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
            </svg>
          </div>
          <p className="text-ui-g700 text-xs font-medium">Drag & drop files here</p>
          <p className="text-ui-g400 text-[10px] mb-2">.xaml files or a .zip project archive</p>
          <input type="file" accept=".xaml,.zip" multiple onChange={handleFileInput} className="hidden" id="file-input" disabled={isLoading} />
          <label htmlFor="file-input" className="px-4 py-1.5 bg-white border border-ui-g300 rounded-lg text-xs font-semibold text-ui-g700 cursor-pointer hover:border-ui-orange hover:text-ui-orange transition-all hover:shadow-sm">
            Browse Files
          </label>

          {/* File list inside drop zone */}
          {xamlFiles.length > 0 && (
            <div className="w-full mt-3 space-y-0.5 animate-fade-in">
              {xamlFiles.map((f, i) => (
                <div key={`${f.name}-${i}`} className="flex items-center justify-between bg-white/70 rounded px-2.5 py-1 text-xs border border-ui-g200">
                  <div className="flex items-center gap-1.5">
                    <svg className="w-3.5 h-3.5 text-ui-orange flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span className="text-ui-g700 font-medium truncate">{f.name}</span>
                    <span className="text-ui-g400">{(f.size / 1024).toFixed(1)} KB</span>
                  </div>
                  <button onClick={() => removeXaml(i)} className="text-ui-g400 hover:text-red-500 transition-colors" disabled={isLoading}>
                    <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                    </svg>
                  </button>
                </div>
              ))}
            </div>
          )}

          {zipFile && (
            <div className="w-full mt-3 flex items-center justify-between bg-white/70 rounded-lg px-3 py-1.5 border border-ui-orange/20 animate-scale-in">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-ui-orange flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8" />
                </svg>
                <div>
                  <p className="text-ui-g700 font-semibold text-[11px] leading-tight">{zipFile.name}</p>
                  <p className="text-ui-g500 text-[9px] leading-tight">XAML files extracted automatically</p>
                </div>
              </div>
              <button onClick={() => setZipFile(null)} className="text-ui-g400 hover:text-red-500 transition-colors" disabled={isLoading}>
                <svg className="w-3 h-3" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}
        </div>

        {fileError && (
          <div className="flex items-center gap-2 px-3 py-1.5 bg-red-50 border border-red-200 rounded-lg text-xs text-red-700">
            <svg className="w-3.5 h-3.5 flex-shrink-0" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M12 8v4m0 4h.01M21 12a9 9 0 11-18 0 9 9 0 0118 0z" />
            </svg>
            {fileError}
          </div>
        )}

        {/* Project name */}
        <div>
          <label className="block text-[10px] font-semibold text-ui-g500 mb-0.5 uppercase tracking-wider">Project Name</label>
          <input type="text" value={projectName} onChange={(e) => setProjectName(e.target.value)} placeholder="e.g. InvoiceProcessing"
            className="w-full border border-ui-g200 rounded-lg px-3 py-1.5 text-sm bg-ui-g50 focus:bg-white focus:outline-none focus:ring-1 focus:ring-ui-orange/30 focus:border-ui-orange transition-all"
            disabled={isLoading}
          />
        </div>

        {/* Analysis mode toggle */}
        <div>
          <label className="block text-[10px] font-semibold text-ui-g500 mb-1.5 uppercase tracking-wider">Analysis Mode</label>
          <div className="flex gap-2">
            <button type="button" onClick={() => setUseAI(false)} disabled={isLoading}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold border transition-all ${
                !useAI
                  ? 'bg-ui-navy text-white border-ui-navy shadow-sm'
                  : 'bg-white text-ui-g500 border-ui-g200 hover:border-ui-g400'
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9 12l2 2 4-4m6 2a9 9 0 11-18 0 9 9 0 0118 0z" />
              </svg>
              Static Analysis (default)
            </button>
            <button type="button" onClick={() => setUseAI(true)} disabled={isLoading}
              className={`flex-1 flex items-center justify-center gap-1.5 py-2 rounded-lg text-xs font-semibold border transition-all ${
                useAI
                  ? 'bg-ui-navy text-white border-ui-navy shadow-sm'
                  : 'bg-white text-ui-g500 border-ui-g200 hover:border-ui-g400'
              }`}
            >
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M9.813 15.904L9 18.75l-.813-2.846a4.5 4.5 0 00-3.09-3.09L2.25 12l2.846-.813a4.5 4.5 0 003.09-3.09L9 5.25l.813 2.846a4.5 4.5 0 003.09 3.09L15.75 12l-2.846.813a4.5 4.5 0 00-3.09 3.09z" />
              </svg>
              AI-Powered (opt-in)
            </button>
          </div>
          {!useAI && (
            <p className="text-[10px] text-ui-g400 mt-1">Instant results. No AI model or auth required.</p>
          )}
        </div>

        {/* AI model selector — only visible when AI mode is selected */}
        {useAI && (
          <div className="animate-fade-in">
            <label className="block text-[10px] font-semibold text-ui-g500 mb-0.5 uppercase tracking-wider">AI Model</label>
            {modelsLoading ? (
              <div className="h-8 bg-ui-g100 rounded-lg animate-pulse" />
            ) : (
              <select value={selectedModelId} onChange={(e) => setSelectedModelId(e.target.value)}
                className="w-full border border-ui-g200 rounded-lg px-3 py-1.5 text-sm bg-ui-g50 focus:bg-white focus:outline-none focus:ring-1 focus:ring-ui-orange/30 focus:border-ui-orange transition-all"
                disabled={isLoading}
              >
                {providers.map((provider) => (
                  <optgroup key={provider} label={provider}>
                    {aiModels.filter((m) => m.provider === provider).map((m) => (
                      <option key={m.id} value={m.id}>
                        {m.recommended ? '\u2605 ' : '  '}{m.label}{m.recommended ? ' [recommended]' : ''}
                      </option>
                    ))}
                  </optgroup>
                ))}
              </select>
            )}
            <p className="text-[10px] text-ui-g400 mt-0.5">Requires UiPath auth. Consumes Agent Units.</p>
          </div>
        )}

        {/* Submit */}
        <button onClick={handleSubmit} disabled={!canSubmit}
          className={`w-full py-2 rounded-lg text-sm font-bold transition-all ${
            canSubmit
              ? 'bg-orange-gradient text-white shadow-glow-orange hover:shadow-lg hover:-translate-y-0.5'
              : 'bg-ui-g200 text-ui-g400 cursor-not-allowed'
          }`}
        >
          {isLoading ? (
            <span className="flex items-center justify-center gap-2">
              <svg className="animate-spin w-3.5 h-3.5" viewBox="0 0 24 24" fill="none">
                <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
              </svg>
              {useAI ? 'Analyzing with AI...' : 'Analyzing...'}
            </span>
          ) : (
            <span className="flex items-center justify-center gap-1.5">
              <svg className="w-3.5 h-3.5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M21 21l-6-6m2-5a7 7 0 11-14 0 7 7 0 0114 0z" />
              </svg>
              {useAI ? 'Start AI Review' : 'Start Review'}
            </span>
          )}
        </button>
        {isLoading && (
          <p className="text-[10px] text-ui-g500 text-center loading-pulse">
            {useAI
              ? `Analysing with ${models.find((m) => m.id === selectedModelId)?.label ?? selectedModelId}...`
              : 'Running static analysis...'}
          </p>
        )}
      </div>
    </div>
  );
}
