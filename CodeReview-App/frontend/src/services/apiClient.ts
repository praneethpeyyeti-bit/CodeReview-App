import { ModelsResponse, ReviewResponse } from '../models/finding';

const API_BASE = 'http://localhost:8000';

export async function getModels(): Promise<ModelsResponse> {
  const res = await fetch(`${API_BASE}/api/models`);
  if (!res.ok) throw new Error('Failed to load model list');
  return res.json();
}

export async function submitReview(
  formData: FormData
): Promise<ReviewResponse> {
  // Step 1: Submit review job (returns immediately)
  const submitRes = await fetch(`${API_BASE}/api/review`, {
    method: 'POST',
    body: formData,
  });
  if (!submitRes.ok) {
    const err = await submitRes.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail ?? `HTTP ${submitRes.status}`);
  }
  const { job_id } = await submitRes.json();

  // Step 2: Poll for results every 3 seconds
  const maxPolls = 400; // 400 * 3s = 20 minutes max
  let pollErrors = 0;
  for (let i = 0; i < maxPolls; i++) {
    await new Promise((resolve) => setTimeout(resolve, 3000));

    let pollRes: Response;
    try {
      pollRes = await fetch(`${API_BASE}/api/review/${job_id}`);
    } catch {
      // Network error during poll — retry up to 5 times
      pollErrors++;
      if (pollErrors > 5) throw new Error('Lost connection to server during review.');
      continue;
    }

    if (!pollRes.ok) {
      const err = await pollRes.json().catch(() => ({ detail: 'Unknown error' }));
      throw new Error(err.detail ?? `HTTP ${pollRes.status}`);
    }

    const data = await pollRes.json();
    if (data.status === 'running') continue;

    // Completed — data is the full ReviewResponse
    return data as ReviewResponse;
  }

  throw new Error('Review timed out after 20 minutes. Try with fewer files or a faster model.');
}

export interface FixFileResult {
  file_name: string;
  original_content: string;
  modified_content: string;
  changes: string[];
}

export interface FixResponse {
  project_name: string;
  files: FixFileResult[];
  project_json?: string | null;
}

export interface AcceptFixResponse {
  saved_path: string;
  file_count: number;
}

export async function submitFix(formData: FormData): Promise<FixResponse> {
  const res = await fetch(`${API_BASE}/api/fix`, { method: 'POST', body: formData });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}

export async function acceptFix(
  projectName: string,
  files: { file_name: string; modified_content: string }[],
  outputDir?: string,
  projectJson?: string | null
): Promise<AcceptFixResponse> {
  const res = await fetch(`${API_BASE}/api/fix/accept`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({
      project_name: projectName,
      files,
      output_dir: outputDir || '',
      project_json: projectJson || null,
    }),
  });
  if (!res.ok) {
    const err = await res.json().catch(() => ({ detail: 'Unknown error' }));
    throw new Error(err.detail ?? `HTTP ${res.status}`);
  }
  return res.json();
}
