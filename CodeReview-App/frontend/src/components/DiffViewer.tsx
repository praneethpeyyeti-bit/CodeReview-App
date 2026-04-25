import { useState } from 'react';
import { FixFileResult, acceptFix } from '../services/apiClient';

interface Props {
  projectName: string;
  files: FixFileResult[];
  projectJson?: string | null;
  fixId?: string | null;
  onClose: () => void;
  onAccepted: (savedPath: string) => void;
}

interface SideBySideLine {
  leftNum: number | null;
  leftContent: string;
  leftType: 'same' | 'remove' | 'empty';
  rightNum: number | null;
  rightContent: string;
  rightType: 'same' | 'add' | 'empty';
}

function computeSideBySideDiff(original: string, modified: string): SideBySideLine[] {
  const origLines = original.split('\n');
  const modLines = modified.split('\n');
  const m = origLines.length;
  const n = modLines.length;

  // Build LCS table
  const dp: number[][] = Array.from({ length: m + 1 }, () => Array(n + 1).fill(0));
  for (let i = 1; i <= m; i++) {
    for (let j = 1; j <= n; j++) {
      if (origLines[i - 1] === modLines[j - 1]) {
        dp[i][j] = dp[i - 1][j - 1] + 1;
      } else {
        dp[i][j] = Math.max(dp[i - 1][j], dp[i][j - 1]);
      }
    }
  }

  // Backtrack to produce unified diff items
  const items: { type: 'same' | 'add' | 'remove'; content: string }[] = [];
  let i = m, j = n;
  while (i > 0 || j > 0) {
    if (i > 0 && j > 0 && origLines[i - 1] === modLines[j - 1]) {
      items.unshift({ type: 'same', content: origLines[i - 1] });
      i--; j--;
    } else if (j > 0 && (i === 0 || dp[i][j - 1] >= dp[i - 1][j])) {
      items.unshift({ type: 'add', content: modLines[j - 1] });
      j--;
    } else {
      items.unshift({ type: 'remove', content: origLines[i - 1] });
      i--;
    }
  }

  // Convert to side-by-side rows
  const result: SideBySideLine[] = [];
  let leftNum = 1;
  let rightNum = 1;
  let idx = 0;

  while (idx < items.length) {
    const item = items[idx];

    if (item.type === 'same') {
      result.push({
        leftNum: leftNum++,
        leftContent: item.content,
        leftType: 'same',
        rightNum: rightNum++,
        rightContent: item.content,
        rightType: 'same',
      });
      idx++;
    } else if (item.type === 'remove') {
      // Check if next item is an 'add' — pair them on the same row
      if (idx + 1 < items.length && items[idx + 1].type === 'add') {
        result.push({
          leftNum: leftNum++,
          leftContent: item.content,
          leftType: 'remove',
          rightNum: rightNum++,
          rightContent: items[idx + 1].content,
          rightType: 'add',
        });
        idx += 2;
      } else {
        result.push({
          leftNum: leftNum++,
          leftContent: item.content,
          leftType: 'remove',
          rightNum: null,
          rightContent: '',
          rightType: 'empty',
        });
        idx++;
      }
    } else {
      // 'add' without preceding 'remove'
      result.push({
        leftNum: null,
        leftContent: '',
        leftType: 'empty',
        rightNum: rightNum++,
        rightContent: item.content,
        rightType: 'add',
      });
      idx++;
    }
  }

  return result;
}

export default function DiffViewer({ projectName, files, projectJson, fixId, onClose, onAccepted }: Props) {
  const [activeFileIndex, setActiveFileIndex] = useState(0);
  const [accepting, setAccepting] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [showOutputPrompt, setShowOutputPrompt] = useState(false);
  const [outputDir, setOutputDir] = useState('');
  // Track which files have their fixes excluded (use original content instead)
  const [excludedFiles, setExcludedFiles] = useState<Set<string>>(new Set());

  const activeFile = files[activeFileIndex];
  const isExcluded = excludedFiles.has(activeFile.file_name);
  const hasChanges = files.some((f) => f.changes.length > 0 && !excludedFiles.has(f.file_name));
  const diff = computeSideBySideDiff(
    activeFile.original_content,
    isExcluded ? activeFile.original_content : activeFile.modified_content
  );

  const toggleFileExclusion = (fileName: string) => {
    setExcludedFiles((prev) => {
      const next = new Set(prev);
      if (next.has(fileName)) {
        next.delete(fileName);
      } else {
        next.add(fileName);
      }
      return next;
    });
  };

  const handleAcceptAll = () => {
    setShowOutputPrompt(true);
  };

  const handleConfirmSave = async () => {
    setAccepting(true);
    setError(null);
    setShowOutputPrompt(false);
    try {
      const filesToSave = files.map((f) => {
        const excluded = excludedFiles.has(f.file_name);
        const willDelete = Boolean(f.delete) && !excluded;
        return {
          file_name: f.file_name,
          zip_entry_path: f.zip_entry_path || '',
          modified_content:
            !willDelete && f.changes.length > 0 && !excluded
              ? f.modified_content
              : f.original_content,
          delete: willDelete,
        };
      });
      const res = await acceptFix(projectName, filesToSave, outputDir || undefined, projectJson, fixId);
      onAccepted(res.saved_path);
    } catch (err: any) {
      setError(err.message ?? 'Failed to save fixes');
    } finally {
      setAccepting(false);
    }
  };

  const bgClass = (type: string) => {
    if (type === 'add') return 'bg-green-50';
    if (type === 'remove') return 'bg-red-50';
    if (type === 'empty') return 'bg-gray-50';
    return '';
  };

  const textClass = (type: string) => {
    if (type === 'add') return 'text-green-800';
    if (type === 'remove') return 'text-red-800 line-through';
    if (type === 'empty') return '';
    return 'text-ui-g700';
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
      <div className="bg-white rounded-xl shadow-2xl w-full max-w-[95vw] max-h-[90vh] flex flex-col overflow-hidden mx-4">
        {/* Header */}
        <div className="bg-ui-navy px-6 py-4 flex items-center justify-between flex-shrink-0">
          <div>
            <h2 className="text-white font-semibold text-base">Auto-Fix Preview — Side by Side</h2>
            <p className="text-gray-400 text-xs mt-0.5">
              {(() => {
                const included = files.filter((f) => !excludedFiles.has(f.file_name));
                const modified = included.filter((f) => f.changes.length > 0).length;
                const deleted = included.filter((f) => f.delete).length;
                const totalChanges = included.reduce((s, f) => s + f.changes.length, 0);
                return (
                  <>
                    {totalChanges} change{totalChanges === 1 ? '' : 's'} across {modified} of {files.length} files
                    {deleted > 0 && ` · ${deleted} to delete`}
                    {excludedFiles.size > 0 && ` · ${excludedFiles.size} excluded`}
                  </>
                );
              })()}
            </p>
          </div>
          <div className="flex items-center gap-3">
            {hasChanges && (
              <button
                onClick={handleAcceptAll}
                disabled={accepting}
                className="px-4 py-1.5 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
              >
                {accepting ? 'Saving...' : 'Accept All & Save'}
              </button>
            )}
            <button
              onClick={onClose}
              className="text-gray-400 hover:text-white transition-colors"
            >
              <svg className="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
                <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
              </svg>
            </button>
          </div>
        </div>

        {error && (
          <div className="px-6 py-2 bg-red-50 border-b border-red-200 text-sm text-red-700">
            {error}
          </div>
        )}

        {showOutputPrompt && (
          <div className="px-6 py-4 bg-ui-g50 border-b border-ui-g200">
            <p className="text-sm font-medium text-ui-g700 mb-2">Choose output folder</p>
            <p className="text-xs text-ui-g500 mb-3">
              Leave empty to use the default server output directory.
            </p>
            <div className="flex items-center gap-3">
              <input
                type="text"
                value={outputDir}
                onChange={(e) => setOutputDir(e.target.value)}
                placeholder="e.g. C:\output\MyProject"
                className="flex-1 border border-ui-g300 rounded-lg px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-ui-orange focus:border-ui-orange"
              />
              <button
                onClick={handleConfirmSave}
                disabled={accepting}
                className="px-4 py-2 bg-green-600 text-white text-sm font-medium rounded-lg hover:bg-green-700 transition-colors disabled:opacity-50"
              >
                {accepting ? 'Saving...' : 'Save'}
              </button>
              <button
                onClick={() => setShowOutputPrompt(false)}
                className="px-4 py-2 bg-ui-g200 text-ui-g700 text-sm font-medium rounded-lg hover:bg-ui-g300 transition-colors"
              >
                Cancel
              </button>
            </div>
          </div>
        )}

        <div className="flex flex-1 overflow-hidden">
          {/* File sidebar */}
          <div className="w-56 border-r border-ui-g200 overflow-y-auto bg-ui-g50 flex-shrink-0">
            {files.map((f, idx) => {
              const fileExcluded = excludedFiles.has(f.file_name);
              const willDelete = Boolean(f.delete);
              return (
                <div
                  key={f.file_name}
                  className={`border-b border-ui-g100 transition-colors ${
                    idx === activeFileIndex
                      ? 'bg-white border-l-2 border-l-ui-orange'
                      : 'hover:bg-white'
                  }`}
                >
                  <button
                    onClick={() => setActiveFileIndex(idx)}
                    className="w-full text-left px-4 pt-3 pb-1 text-sm"
                  >
                    <div className={`truncate ${fileExcluded ? 'text-ui-g400 line-through' : willDelete ? 'text-red-700 font-medium' : 'text-ui-g700 font-medium'}`}>{f.file_name}</div>
                  </button>
                  <div className="px-4 pb-2 text-xs">
                    {f.changes.length > 0 ? (
                      <label className="flex items-center gap-1.5 cursor-pointer">
                        <input
                          type="checkbox"
                          checked={!fileExcluded}
                          onChange={() => toggleFileExclusion(f.file_name)}
                          className="accent-ui-orange w-3.5 h-3.5"
                        />
                        <span className={fileExcluded ? 'text-ui-g400 line-through' : willDelete ? 'text-red-600 font-medium' : 'text-green-600'}>
                          {willDelete ? 'Will be deleted' : `${f.changes.length} fix(es)`}
                        </span>
                      </label>
                    ) : (
                      <span className="text-ui-g400">No changes</span>
                    )}
                  </div>
                </div>
              );
            })}
          </div>

          {/* Diff content */}
          <div className="flex-1 flex flex-col overflow-hidden">
            {/* Changes summary */}
            {activeFile.changes.length > 0 && (
              <div className={`px-4 py-2 border-b flex-shrink-0 ${
                isExcluded
                  ? 'bg-amber-50 border-amber-200'
                  : 'bg-green-50 border-green-200'
              }`}>
                {isExcluded ? (
                  <p className="text-xs font-medium text-amber-700">
                    Fixes excluded — original content will be saved for this file.
                  </p>
                ) : (
                  <>
                    <p className="text-xs font-medium text-green-800 mb-1">Changes applied:</p>
                    <ul className="text-xs text-green-700 space-y-0.5">
                      {activeFile.changes.map((c, i) => (
                        <li key={i} className="flex items-start gap-1">
                          <span className="text-green-500 mt-0.5">+</span>
                          {c}
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </div>
            )}

            {/* Column headers */}
            <div className="flex border-b border-ui-g200 flex-shrink-0">
              <div className="flex-1 px-4 py-1.5 bg-red-50 text-xs font-semibold text-red-700 border-r border-ui-g200">
                Original
              </div>
              <div className="flex-1 px-4 py-1.5 bg-green-50 text-xs font-semibold text-green-700">
                Modified
              </div>
            </div>

            {/* Side-by-side diff */}
            <div className="flex-1 overflow-auto font-mono text-xs">
              {activeFile.changes.length === 0 ? (
                <div className="flex items-center justify-center h-full text-ui-g400">
                  No auto-fixes applicable to this file
                </div>
              ) : (
                <table className="w-full table-fixed">
                  <tbody>
                    {diff.map((line, idx) => (
                      <tr key={idx}>
                        {/* Left side (original) */}
                        <td className={`w-8 text-right pr-1 select-none border-r border-ui-g100 leading-5 ${bgClass(line.leftType)}`}>
                          <span className="text-ui-g400">{line.leftNum ?? ''}</span>
                        </td>
                        <td className={`border-r border-ui-g200 px-2 whitespace-pre overflow-hidden leading-5 ${bgClass(line.leftType)}`}>
                          <span className={textClass(line.leftType)}>{line.leftContent}</span>
                        </td>
                        {/* Right side (modified) */}
                        <td className={`w-8 text-right pr-1 select-none border-r border-ui-g100 leading-5 ${bgClass(line.rightType)}`}>
                          <span className="text-ui-g400">{line.rightNum ?? ''}</span>
                        </td>
                        <td className={`px-2 whitespace-pre overflow-hidden leading-5 ${bgClass(line.rightType)}`}>
                          <span className={textClass(line.rightType)}>{line.rightContent}</span>
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  );
}
