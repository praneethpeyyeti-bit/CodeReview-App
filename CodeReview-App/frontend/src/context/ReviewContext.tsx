import { createContext, useContext, useState, useEffect, useRef, ReactNode } from 'react';
import { Finding, ModelOption, ReviewResponse } from '../models/finding';
import { getModels } from '../services/apiClient';

interface ReviewContextType {
  // Models
  models: ModelOption[];
  modelsLoading: boolean;
  modelsError: string | null;

  // Review results
  reviewResponse: ReviewResponse | null;
  setReviewResponse: (r: ReviewResponse | null) => void;
  findings: Finding[];
  setFindings: React.Dispatch<React.SetStateAction<Finding[]>>;
  reviewDuration: number | null;
  setReviewDuration: (d: number | null) => void;

  // Form data for auto-fix (non-serializable, lives in context only)
  lastFormData: FormData | null;
  setLastFormData: (fd: FormData | null) => void;
  lastModelLabel: string;
  setLastModelLabel: (label: string) => void;

  // Reset
  clearReview: () => void;
}

const ReviewContext = createContext<ReviewContextType | null>(null);

export function useReview() {
  const ctx = useContext(ReviewContext);
  if (!ctx) throw new Error('useReview must be used within ReviewProvider');
  return ctx;
}

export function ReviewProvider({ children }: { children: ReactNode }) {
  const [models, setModels] = useState<ModelOption[]>([]);
  const [modelsLoading, setModelsLoading] = useState(true);
  const [modelsError, setModelsError] = useState<string | null>(null);

  const [reviewResponse, setReviewResponse] = useState<ReviewResponse | null>(null);
  const [findings, setFindings] = useState<Finding[]>([]);
  const [reviewDuration, setReviewDuration] = useState<number | null>(null);
  const [lastFormData, setLastFormData] = useState<FormData | null>(null);
  const [lastModelLabel, setLastModelLabel] = useState('');

  useEffect(() => {
    getModels()
      .then((res) => { setModels(res.models); setModelsLoading(false); })
      .catch(() => {
        setModelsError('Could not load model list from backend.');
        setModelsLoading(false);
      });
  }, []);

  const clearReview = () => {
    setReviewResponse(null);
    setFindings([]);
    setReviewDuration(null);
    setLastFormData(null);
    setLastModelLabel('');
  };

  return (
    <ReviewContext.Provider value={{
      models, modelsLoading, modelsError,
      reviewResponse, setReviewResponse,
      findings, setFindings,
      reviewDuration, setReviewDuration,
      lastFormData, setLastFormData,
      lastModelLabel, setLastModelLabel,
      clearReview,
    }}>
      {children}
    </ReviewContext.Provider>
  );
}
