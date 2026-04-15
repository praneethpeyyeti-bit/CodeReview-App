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
  const [selectedModelId, setSelectedModelId] = useState('anthropic.claude-3-7-sonnet-20250219-v1:0');
  const [dragOver, setDragOver] = useState(false);
  const [fileError, setFileError] = useState<string | null>(null);
  const [collapsed, setCollapsed] = useState(false);

  useEffect(() => {
    if (models.length > 0) {
      const recommended = models.find(
        (m) => m.recommended && m.provider === 'Anthropic'
      );
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
      const others = dropped.filter(
        (f) => !f.name.toLowerCase().endsWith('.xaml') && !f.name.toLowerCase().endsWith('.zip')
      );

      if (others.length > 0) {
        setFileError('Only .xaml and .zip files are accepted.');
        return;
      }
      if (xamls.length > 0 && zips.length > 0) {
        setFileError('Please upload either .xaml files or a single .zip, not both.');
        return;
      }
      if (zips.length > 1) {
        setFileError('Please drop a single .zip file.');
        return;
      }

      if (zips.length === 1) {
        if (xamlFiles.length > 0) {
          setFileError('Cannot add a .zip when .xaml files are already selected. Remove them first.');
          return;
        }
        setZipFile(zips[0]);
        if (!projectName) {
          setProjectName(zips[0].name.replace(/\.zip$/i, ''));
        }
      }
      if (xamls.length > 0) {
        if (zipFile) {
          setFileError('Cannot add .xaml files when a .zip is already selected. Remove it first.');
          return;
        }
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

    if (xamls.length > 0 && zips.length > 0) {
      setFileError('Please select either .xaml files or a single .zip, not both.');
    } else if (zips.length > 1) {
      setFileError('Please select a single .zip file.');
    } else if (zips.length === 1) {
      if (xamlFiles.length > 0) {
        setFileError('Cannot add a .zip when .xaml files are already selected. Remove them first.');
      } else {
        setZipFile(zips[0]);
        if (!projectName) {
          setProjectName(zips[0].name.replace(/\.zip$/i, ''));
        }
      }
    } else if (xamls.length > 0) {
      if (zipFile) {
        setFileError('Cannot add .xaml files when a .zip is already selected. Remove it first.');
      } else {
        setXamlFiles((prev) => [...prev, ...xamls]);
      }
    }

    e.target.value = '';
  };

  const removeXaml = (index: number) => {
    setXamlFiles((prev) => prev.filter((_, i) => i !== index));
  };

  const hasFiles = xamlFiles.length > 0 || zipFile !== null;
  const canSubmit = hasFiles && projectName.trim() !== '' && !isLoading;

  const handleSubmit = () => {
    const fd = new FormData();
    fd.append('project_name', projectName.trim());
    fd.append('model_id', selectedModelId);
    if (zipFile) {
      fd.append('files', zipFile);
    } else {
      xamlFiles.forEach((f) => fd.append('files', f));
    }
    const modelLabel =
      models.find((m) => m.id === selectedModelId)?.label ?? selectedModelId;
    onSubmit(fd, modelLabel);
  };

  const providers = [...new Set(models.map((m) => m.provider))];

  return (
    <div className="bg-white rounded-xl shadow-sm border border-ui-g200 overflow-hidden">
      {/* Card header */}
      <button
        className="w-full bg-ui-navy px-6 py-3 flex items-center justify-between cursor-pointer hover:bg-ui-navy-light transition-colors"
        onClick={() => setCollapsed((c) => !c)}
      >
        <h2 className="text-white font-semibold text-sm tracking-wide">Upload Project</h2>
        <div className="flex items-center gap-3">
          {hasFiles && (
            <span className="text-xs text-gray-400">
              {zipFile ? zipFile.name : `${xamlFiles.length} file(s) selected`}
            </span>
          )}
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
          {/* Drop zone */}
          <div
            className={`border-2 border-dashed rounded-xl p-6 text-left w-fit transition-all ${
              dragOver
                ? 'border-ui-orange bg-ui-orange-light'
                : 'border-ui-g300 bg-ui-g50'
            } ${isLoading ? 'opacity-50 pointer-events-none' : ''}`}
            onDragOver={(e) => {
              e.preventDefault();
              setDragOver(true);
            }}
            onDragLeave={() => setDragOver(false)}
            onDrop={handleDrop}
          >
            {/* Upload icon */}
            <div className="w-10 h-10 bg-ui-orange-light rounded-full flex items-center justify-center mb-2">
              <svg className="w-6 h-6 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M7 16a4 4 0 01-.88-7.903A5 5 0 1115.9 6L16 6a5 5 0 011 9.9M15 13l-3-3m0 0l-3 3m3-3v12" />
              </svg>
            </div>
            <p className="text-ui-g600 mb-2 text-sm">
              Drag & drop .xaml files or a .zip archive here, or click to browse
            </p>
            <input
              type="file"
              accept=".xaml,.zip"
              multiple
              onChange={handleFileInput}
              className="hidden"
              id="file-input"
              disabled={isLoading}
            />
            <label
              htmlFor="file-input"
              className="inline-block px-3 py-1.5 bg-white border border-ui-g300 rounded-lg text-xs font-medium text-ui-g700 cursor-pointer hover:border-ui-orange hover:text-ui-orange transition-colors"
            >
              Browse Files
            </label>
          </div>

          {fileError && (
            <p className="mt-2 text-sm text-red-600">{fileError}</p>
          )}

          {/* Selected XAML files list */}
          {xamlFiles.length > 0 && (
            <div className="mt-4 space-y-1">
              {xamlFiles.map((f, i) => (
                <div
                  key={`${f.name}-${i}`}
                  className="flex items-center justify-between bg-ui-g50 rounded-lg px-3 py-2 text-sm border border-ui-g100"
                >
                  <div className="flex items-center gap-2">
                    <svg className="w-4 h-4 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                      <path strokeLinecap="round" strokeLinejoin="round" d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z" />
                    </svg>
                    <span className="text-ui-g700 truncate">{f.name}</span>
                  </div>
                  <div className="flex items-center gap-3">
                    <span className="text-ui-g400 text-xs">
                      {(f.size / 1024).toFixed(1)} KB
                    </span>
                    <button
                      onClick={() => removeXaml(i)}
                      className="text-ui-g400 hover:text-red-500 transition-colors"
                      disabled={isLoading}
                    >
                      <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                        <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                      </svg>
                    </button>
                  </div>
                </div>
              ))}
            </div>
          )}

          {/* Selected ZIP file */}
          {zipFile && (
            <div className="mt-4 bg-ui-g50 rounded-lg px-4 py-3 flex items-center justify-between text-sm border border-ui-g100">
              <div className="flex items-center gap-2">
                <svg className="w-4 h-4 text-ui-orange" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M5 8h14M5 8a2 2 0 110-4h14a2 2 0 110 4M5 8v10a2 2 0 002 2h10a2 2 0 002-2V8" />
                </svg>
                <span className="text-ui-g700">{zipFile.name}</span>
                <span className="text-ui-g400 text-xs">— XAML files will be extracted automatically</span>
              </div>
              <button
                onClick={() => setZipFile(null)}
                className="text-ui-g400 hover:text-red-500 transition-colors"
                disabled={isLoading}
              >
                <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                  <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
                </svg>
              </button>
            </div>
          )}

          {/* Project name & Model in a row */}
          <div className="mt-5 grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div>
              <label className="block text-sm font-medium text-ui-g700 mb-1">
                Project Name
              </label>
              <input
                type="text"
                value={projectName}
                onChange={(e) => setProjectName(e.target.value)}
                placeholder="e.g. InvoiceProcessing"
                className="w-full border border-ui-g300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ui-orange focus:border-ui-orange transition-colors"
                disabled={isLoading}
              />
            </div>

            <div>
              <label className="block text-sm font-medium text-ui-g700 mb-1">
                LLM Model
              </label>
              {modelsLoading ? (
                <p className="text-sm text-ui-g400 py-2">Loading models...</p>
              ) : (
                <select
                  value={selectedModelId}
                  onChange={(e) => setSelectedModelId(e.target.value)}
                  className="w-full border border-ui-g300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ui-orange focus:border-ui-orange transition-colors"
                  disabled={isLoading}
                >
                  {providers.map((provider) => (
                    <optgroup key={provider} label={provider}>
                      {models
                        .filter((m) => m.provider === provider)
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.recommended ? '\u2605 ' : '  '}
                            {m.label}
                            {m.recommended ? ' [recommended]' : ''}
                          </option>
                        ))}
                    </optgroup>
                  ))}
                </select>
              )}
            </div>
          </div>

          <p className="text-xs text-ui-g400 mt-2">
            Consumes UiPath Agent Units. Model availability depends on your tenant region.
          </p>

          {/* Submit */}
          <div className="mt-6">
            <button
              onClick={handleSubmit}
              disabled={!canSubmit}
              className={`w-full py-3 rounded-lg text-sm font-semibold transition-all ${
                canSubmit
                  ? 'bg-ui-orange text-white hover:bg-ui-orange-dark shadow-md hover:shadow-lg'
                  : 'bg-ui-g200 text-ui-g400 cursor-not-allowed'
              }`}
            >
              {isLoading ? (
                <span className="flex items-center justify-center gap-2">
                  <svg className="animate-spin w-4 h-4" viewBox="0 0 24 24" fill="none">
                    <circle className="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" strokeWidth="4"/>
                    <path className="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/>
                  </svg>
                  Reviewing...
                </span>
              ) : (
                'Start Review'
              )}
            </button>
            {isLoading && (
              <p className="text-sm text-ui-g500 mt-2 text-center">
                Analysing with{' '}
                {models.find((m) => m.id === selectedModelId)?.label ??
                  selectedModelId}
                ... this may take a moment
              </p>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
