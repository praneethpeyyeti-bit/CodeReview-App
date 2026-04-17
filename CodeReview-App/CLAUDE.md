# UiPath XAML Code Review App

## Project Overview

Full-stack code review tool for UiPath RPA XAML workflows. Features both **static analysis** (instant, no AI) and **AI-powered review** (Claude, GPT-4, Gemini via UiPath AI Trust Layer). Analyzes workflows against 37 unique Workflow Analyzer rules across 7 categories and provides auto-fix for 5 rules.

## Architecture

- **Backend**: Python FastAPI (port 8000) — `backend/`
- **Frontend**: React + TypeScript + Vite (port 5173) — `frontend/`
- **Static Analysis**: Deterministic rule checking on parsed XAML — no model needed
- **LLM Integration**: Optional, via UiPath LangChain SDK (`uipath_langchain`)

## Running the App

```bash
# Backend
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

Note: `uipath auth` is only needed if using the AI model path (not required for static analysis).

## Key Commands

```bash
# Frontend build
cd frontend && npm run build

# Type check frontend
cd frontend && npx tsc -b
```

## Project Structure

```
backend/
  main.py                  # FastAPI app, endpoints, async job queue
  models/schemas.py        # Pydantic models (Finding, ReviewContext, ActivitySummary, etc.)
  prompts/code_review_prompt.py  # LLM system prompt (used only with AI models)
  services/
    static_reviewer.py     # Static analysis engine (36 rule checker functions, no LLM)
    llm_reviewer.py        # LLM invocation, batching, JSON parsing
    xaml_parser.py          # XAML XML parsing -> ReviewContext (properties, selectors, catch blocks, expressions)
    xaml_fixer.py           # Auto-fix engine (5 rules: naming prefixes + unused variable removal)
    zip_extractor.py        # ZIP file extraction
    token_refresh.py        # Background OAuth token refresh
  .env                     # UiPath tokens & config (auto-managed)
  .uipath/.auth.json       # OAuth tokens (auto-refreshed)

frontend/src/
  App.tsx                  # Router shell (BrowserRouter + ReviewProvider)
  context/ReviewContext.tsx # Shared state provider (models, review data, form data)
  pages/
    HomePage.tsx           # Upload zone + feature cards + workflow animation
    ResultsPage.tsx        # Dashboard + grid + auto-fix + diff viewer
  components/
    UploadZone.tsx         # File upload + static/AI toggle + model selection
    ReviewGrid.tsx         # AG Grid findings table
    SummaryPanel.tsx       # Severity bars, metric cards, category filters
    DiffViewer.tsx         # Side-by-side diff viewer
    ExportButton.tsx       # Excel export trigger
    RulesCatalogModal.tsx  # Rule reference modal
  models/finding.ts        # TypeScript interfaces
  services/
    apiClient.ts           # API client (handles both sync static + async LLM polling)
    excelExporter.ts       # Excel workbook generation (37 rules, 7 categories)
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Server health + token status |
| `/api/models` | GET | Available model catalog |
| `/api/review` | POST | Submit review (sync for static, async for LLM) |
| `/api/review/{job_id}` | GET | Poll LLM review job status/results |
| `/api/fix` | POST | Apply auto-fixes, returns `fixed_rule_ids` |
| `/api/fix/accept` | POST | Save fixed files preserving ZIP folder structure |
| `/api/refresh-token` | POST | Manual OAuth token refresh |

## Two Review Modes

### Static Analysis (No AI)
- Toggle "Static Analysis" in the upload zone (default)
- Returns results instantly (< 1 second)
- No UiPath auth, no Agent Units consumed
- 36 rule checker functions run deterministically on parsed XAML data

### AI-Powered Review
- Toggle "AI-Powered" and select a model (Claude, GPT-4, Gemini)
- Requires `uipath auth` and active token
- Takes 30-60 seconds with polling
- Uses LLM to analyze against prompt-defined rules

## Rule Catalog (37 Unique Rules, 7 Categories)

| Category | Prefix | Count | Rules |
|----------|--------|:-----:|-------|
| Naming | ST-NMG-* | 10 | Variable/argument prefixes, length, duplication, shadowing, name collisions, defaults |
| Design Best Practices | ST-DBP-* | 10 | Empty catch, high arg count, nested flowcharts, undefined outputs, empty workflow, persistence, serialization, delays |
| UI Automation | UI-DBP-*, UI-PRR-004, UI-REL-001, UI-SEC-* | 7 | Container usage, Excel scope, dynamic selectors, hardcoded delays, idx in selectors, sensitive data |
| Performance | UI-PRR-* | 3 | Simulate click/type, application reuse |
| Reliability | GEN-REL-* | 1 | Empty sequences |
| Security | UI-SEC-*, UX-DBP-029 | 3 | Sensitive data exposure, unauthorized apps, insecure passwords |
| General | GEN-* | 5 | Unused variables/arguments, empty sequences, project structure, package restrictions |

Note: Source Excel has 41 rows (some rules appear in multiple categories), but 37 unique rule IDs.

## Auto-Fix Rules (5 Rules)

Only text-level renames and element removal — never modifies XML structure or attributes.

| Rule | Fix | Method |
|------|-----|--------|
| ST-NMG-001 | Add type prefix to variables (str_, int_, dt_, bln_, dtm_, ts_, arr_, dic_) | Regex rename across all XAML locations |
| ST-NMG-002 | Add direction prefix to arguments (in_, out_, io_) | Regex rename across all XAML locations |
| ST-NMG-009 | Add dt_ prefix to DataTable variables | Regex rename |
| ST-NMG-011 | Add dt_ prefix to DataTable arguments | Regex rename |
| GEN-001 | Remove unused variable declarations | Remove self-closing `<Variable/>` element |

After auto-fix, findings for fixed rules get `status = "Fixed"` in the review grid.

### Why only 5 auto-fix rules?

UiPath uses a WPF-based XAML parser that is stricter than standard XML. Any modification that inserts elements with attributes (SimulateClick, LogMessage, Sequence) inside property element contexts causes `Unexpected ATTRIBUTE in NonemptyPropertyElement` parse errors in UiPath Studio. Only text-level renames and self-closing element removal are safe.

**Detection-only rules (32):** Detected and reported with specific fix recommendations, but require manual fix in UiPath Studio.

## Code Conventions

- Backend uses Python type hints and Pydantic models
- Frontend uses TypeScript strict mode with Tailwind CSS
- XAML fixes must only do text-level renames or self-closing element removal — never insert elements or modify attributes
- Fixed files preserve the original ZIP folder structure (no `modified/` subfolder)
- Static analysis returns `ReviewResponse` directly; LLM returns `job_id` for polling
- Token refresh runs automatically in background
- Upload zone uses toggle buttons for Static/AI mode (not a dropdown)

## Environment

- Python >= 3.11
- Node.js >= 18
- UiPath CLI authenticated (`uipath auth`) — only for AI model path
