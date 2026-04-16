# UiPath XAML Code Review App

## Project Overview

Full-stack AI-powered code review tool for UiPath RPA XAML workflows. Uses LLMs (Claude, GPT-4, Gemini) via UiPath AI Trust Layer to analyze workflows against 47 Workflow Analyzer rules and provides auto-fix capabilities for naming convention violations.

## Architecture

- **Backend**: Python FastAPI (port 8000) — `backend/`
- **Frontend**: React + TypeScript + Vite (port 5173) — `frontend/`
- **LLM Integration**: UiPath LangChain SDK (`uipath_langchain`)

## Running the App

```bash
# Backend
cd backend
pip install -r requirements.txt
uipath auth   # one-time OAuth setup
python -m uvicorn main:app --reload --port 8000

# Frontend
cd frontend
npm install
npm run dev
```

## Key Commands

```bash
# Backend tests
cd backend && python -m pytest

# Frontend build
cd frontend && npm run build

# Type check frontend
cd frontend && npx tsc -b
```

## Project Structure

```
backend/
  main.py                  # FastAPI app, endpoints, async job queue
  models/schemas.py        # Pydantic models (Finding, ReviewContext, etc.)
  prompts/code_review_prompt.py  # LLM system prompt with 47 rules
  services/
    llm_reviewer.py        # LLM invocation, batching, JSON parsing
    xaml_parser.py          # XAML XML parsing -> ReviewContext
    xaml_fixer.py           # Auto-fix engine (naming prefixes)
    zip_extractor.py        # ZIP file extraction
    token_refresh.py        # Background OAuth token refresh
  .env                     # UiPath tokens & config (auto-managed)
  .uipath/.auth.json       # OAuth tokens (auto-refreshed)

frontend/src/
  App.tsx                  # Root layout component
  pages/ReviewPage.tsx     # Main workflow orchestration
  components/
    UploadZone.tsx         # File upload + model selection
    ReviewGrid.tsx         # AG Grid findings table
    SummaryPanel.tsx       # Severity/category breakdown
    DiffViewer.tsx         # Side-by-side diff viewer
    ExportButton.tsx       # Excel export trigger
    RulesCatalogModal.tsx  # Rule reference modal
  models/finding.ts        # TypeScript interfaces
  services/
    apiClient.ts           # API client + polling logic
    excelExporter.ts       # Excel workbook generation
```

## API Endpoints

| Endpoint | Method | Purpose |
|----------|--------|---------|
| `/api/health` | GET | Server health + token status |
| `/api/models` | GET | Available LLM model catalog |
| `/api/review` | POST | Submit XAML files for async review |
| `/api/review/{job_id}` | GET | Poll review job status/results |
| `/api/fix` | POST | Apply auto-fixes to XAML files |
| `/api/fix/accept` | POST | Save modified files to output dir |
| `/api/refresh-token` | POST | Manual OAuth token refresh |

## Rule Catalog (47 Rules)

Rules are sourced from UiPath Workflow Analyzer and organized into 7 categories:
- **Naming** (ST-NMG-*): Variable/argument prefixes, length, duplication
- **Design Best Practices** (ST-DBP-*): Empty catch, serialization, delays
- **UI Automation** (UI-DBP-*, UI-PRR-004, UI-REL-001, UI-SEC-*): Containers, selectors, sensitive data
- **Performance** (UI-PRR-*): Simulate click/type, app reuse
- **Reliability** (UI-REL-*, GEN-REL-*): Selector stability, empty sequences
- **Security** (UI-SEC-*, UX-DBP-029): Sensitive data, password handling
- **General** (GEN-*): Unused vars/args, project structure, packages

## Auto-Fix Rules

Only naming convention fixes are auto-applied (safe, no logic changes):
- **ST-NMG-001**: Add type prefix to variables (str_, int_, dt_, bln_, etc.)
- **ST-NMG-002**: Add direction prefix to arguments (in_, out_, io_)
- **ST-NMG-009**: Add dt_ prefix to DataTable variables
- **ST-NMG-011**: Add dt_ prefix to DataTable arguments

## Code Conventions

- Backend uses Python type hints and Pydantic models throughout
- Frontend uses TypeScript strict mode with Tailwind CSS
- XAML fixes must never alter workflow logic — only cosmetic/naming changes
- LLM responses are expected as JSON with `findings` array
- Token refresh runs automatically in background; `.env` and `.auth.json` stay in sync
- Review jobs run async via `asyncio.to_thread` with in-memory job store

## Environment

- Python >= 3.11
- Node.js >= 18
- UiPath CLI authenticated (`uipath auth`)
- Default model: Claude 3.7 Sonnet (`anthropic.claude-3-7-sonnet-20250219-v1:0`)
