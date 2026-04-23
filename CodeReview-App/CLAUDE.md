# UiPath XAML Code Review App

## Project Overview

Full-stack code review tool for UiPath RPA XAML workflows. Features both **static analysis** (instant, no AI) and **AI-powered review** (Claude, GPT-4, Gemini via UiPath AI Trust Layer). Analyzes workflows against 37 unique Workflow Analyzer rules across 7 categories and provides auto-fix for 16 rules (including file-level deletion of empty workflows).

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
    xaml_fixer.py           # Auto-fix engine (15 rules: naming, duplicate DisplayName, shadows, length, defaults, empty catch, empty sequences, unused vars/args)
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
    excelExporter.ts       # Excel workbook generation (36 rules, 7 categories)
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
| Naming | ST-NMG-* | 11 | Variable/argument prefixes, PascalCase body, length, duplication, shadowing, name collisions, defaults |
| Design Best Practices | ST-DBP-* | 10 | Empty catch, high arg count, nested flowcharts, undefined outputs, empty workflow, persistence, serialization, delays |
| UI Automation | UI-DBP-*, UI-PRR-004, UI-REL-001, UI-SEC-* | 6 | Container usage, Excel scope, hardcoded delays, idx in selectors, sensitive data |
| Performance | UI-PRR-* | 3 | Simulate click/type, application reuse |
| Reliability | GEN-REL-* | 1 | Empty sequences |
| Security | UI-SEC-*, UX-DBP-029 | 3 | Sensitive data exposure, unauthorized apps, insecure passwords |
| General | GEN-* | 5 | Unused variables/arguments, empty sequences, project structure, package restrictions |

Note: Source Excel has 41 rows (some rules appear in multiple categories), plus ST-NMG-010 added locally for PascalCase enforcement — 37 unique rule IDs.

## Auto-Fix Rules (16 Rules)

Text-level operations on raw XAML — regex rename, positional attribute-value rewrite, element removal, or contained-insertion inside `<Catch>` delegate bodies. Never inserts elements with attributes into property-element contexts (which corrupts UiPath's WPF XAML parser).

| Rule | Fix | Method |
|------|-----|--------|
| ST-NMG-001 | Add type prefix to variables (`str_`, `int_`, `dt_`, `bln_`, `dtm_`, `ts_`, `arr_`, `dic_`) | Regex rename across all XAML locations |
| ST-NMG-002 | Add direction prefix to arguments (`in_`, `out_`, `io_`) | Regex rename across all XAML locations |
| ST-NMG-004 | Rename duplicate DisplayNames using selector-derived labels (e.g. `Click 'Save'`); counter fallback | Positional regex on the Nth `DisplayName="..."` occurrence |
| ST-NMG-005 | Keep the outermost Variable, remove inner-scope shadow declarations | Remove all `<Variable Name="X"/>` occurrences except the first |
| ST-NMG-006 | Remove variable that collides with an argument name; retain the argument | Remove `<Variable Name="X"/>` |
| ST-NMG-008 | Shorten variable name > 30 chars (preserve prefix, drop middle camelCase words) | Regex rename |
| ST-NMG-009 | Add `dt_` prefix to DataTable variables | Regex rename |
| ST-NMG-010 | Convert non-PascalCase variable/argument bodies to PascalCase (keeps prefix; strips underscores; capitalizes words; uses `wordninja` to split concatenated lowercase runs like `Filtercandidatedetailsfromsaptabledata` → `FilterCandidateDetailsFromSapTableData`) | Regex rename — re-scans current XAML state |
| ST-NMG-011 | Add direction prefix (`in_`/`out_`/`io_`) to DataTable arguments | Regex rename |
| ST-NMG-012 | Remove default-value for **In** arguments (Out/InOut are ignored since they can't have defaults). Handles both element-form `<this:WfName.argName>...</...>` and attribute-form `this:WfName.argName="..."` on the Activity root | Element removal + attribute stripping |
| ST-NMG-016 | Shorten argument name > 30 chars | Regex rename |
| ST-DBP-003 | Insert `<ui:LogMessage Level="Error">` inside the empty Catch body Sequence (includes exception type, message, source). Auto-injects `xmlns:ui` on the Activity root when not already declared | ET-guided discovery + positional regex insertion before `</Sequence>` |
| ST-DBP-023 | Delete empty workflow file on accept | File deletion via `delete` flag (fix response) + `os.remove()` in `/api/fix/accept` |
| GEN-001 | Remove unused `<Variable/>` declarations | Element removal |
| GEN-003 / GEN-REL-001 | Remove empty Sequence elements — both self-closing `<Sequence/>` and open-tag `<Sequence>[metadata-only]</Sequence>` (by flagged DisplayName). Structural Catch-body Sequences are excluded (ST-DBP-003 handles those). | Element removal with metadata-only verification |

After auto-fix, findings for fixed rules get `status = "Fixed"` in the review grid.

### Detection-only rules (21)
The remaining 21 rules (ST-DBP-002/007/020/024/025/026/027/028, UI-DBP-006/013, UI-PRR-001/002/003/004, UI-REL-001, UI-SEC-004/010, UX-DBP-029, GEN-002, GEN-004/005) are detected with specific recommendations but require manual fix. UiPath's WPF-based XAML parser rejects programmatic insertion of elements-with-attributes inside property-element contexts — that's what blocks auto-fix for most UI-side rules.

### Fix pipeline ordering

`_rule_priority()` in [xaml_fixer.py](backend/services/xaml_fixer.py) controls execution order. **Removal rules must run before rename rules** so stale references don't survive:

1. **Priority 0** — Security (UI-SEC-*, UX-DBP-029)
2. **Priority 1** — Removals + design fixes: ST-NMG-005 (shadow), ST-NMG-006 (var-arg collision), ST-NMG-012 (argument defaults), GEN-001 (unused variable), ST-DBP-* (empty catch, empty workflow, etc.)
3. **Priority 2** — Renames: ST-NMG-001/002/004/008/009/010/011/016
4. **Priority 3-4** — UI Automation, Performance, Reliability, General rules

Example of ordering mattering: if ST-NMG-002 ran before ST-NMG-012, renaming `Name="test"` to `Name="in_test"` would happen first, but the attribute-form default `this:Main.test="value"` would still reference the old name. ST-NMG-012 removes the default attribute first so the subsequent rename applies cleanly.

### Rule scoping notes
- **GEN-REL-001 Empty Sequences** only flags standalone user-authored Sequences. Sequences that are direct children of `<ActivityAction>` (catch handler bodies) are marked `is_structural_wrapper` by the parser and skipped — they're covered by ST-DBP-003. Sequences inside `TryCatch.Try` and `TryCatch.Finally` *are* flagged (no other rule covers them).
- **ST-DBP-003 Empty Catch** discovery uses the full `_META_ELEMENTS` set (including XAML primitives like `x:Boolean`, `x:String`) so metadata inside ViewState Dictionaries isn't miscounted as activity content.
- **Variable scope** tracking uses the owning Sequence's `WorkflowViewState.IdRef` (or DisplayName + owner-counter fallback), not just the property-element wrapper name. This gives each Sequence's variables a distinct scope so ST-NMG-005 shadow detection actually fires.
- **Argument defaults** are detected in both element-form (`<this:Main.argName>...</this:Main.argName>`) and attribute-form (`this:Main.argName="..."` on the Activity root). `_rename_in_xaml` also updates attribute-form references when renaming so `this:Main.oldName="value"` becomes `this:Main.newName="value"` and UiPath Studio doesn't error with "The property (oldName) is either invalid or not defined".

## Code Conventions

- Backend uses Python type hints and Pydantic models
- Frontend uses TypeScript strict mode with Tailwind CSS
- XAML fixes must operate on raw text (positional regex or string replacement) — never re-serialize via ET.tostring (drops xmlns). Never insert elements into property-element contexts.
- Fixed files preserve the original ZIP folder structure (no `modified/` subfolder)
- Static analysis returns `ReviewResponse` directly; LLM returns `job_id` for polling
- Token refresh runs automatically in background
- Upload zone uses toggle buttons for Static/AI mode (not a dropdown)

## Environment

- Python >= 3.11
- Node.js >= 18
- UiPath CLI authenticated (`uipath auth`) — only for AI model path
