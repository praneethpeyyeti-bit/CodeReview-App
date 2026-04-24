# UiPath XAML Code Review App

## Project Overview

Full-stack code review tool for UiPath RPA XAML workflows. **Static analysis is the default** — deterministic, instant, zero auth, zero agent units. **AI-Powered review** (Claude, GPT-4, Gemini via UiPath AI Trust Layer) is opt-in per request. Both modes cover the same 37 unique Workflow Analyzer rules across 7 categories; auto-fix handles 16 rules (including file-level deletion of empty workflows).

## Architecture

- **Backend**: Python FastAPI (port 8000) — `backend/`
- **Frontend**: React + TypeScript + Vite (port 5173) — `frontend/`
- **Static Analysis** (default): Deterministic rule checking on parsed XAML — no model, no auth, <1s
- **LLM Integration** (opt-in): Via UiPath LangChain SDK (`uipath_langchain`); uses `temperature=0 + seed=42` plus submission-order batch collection and post-processing sort for byte-stable output

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

### Static Analysis (default)
- The **default** for both the UI (toggle opens on Static) and the API (POST `/api/review` with no `model_id` runs static)
- Returns results instantly (< 1 second) — sync response, no job polling
- Zero UiPath auth, zero Agent Units
- 36 rule checker functions run deterministically on parsed XAML data
- Backed by `DEFAULT_MODE = "static"` in [main.py](backend/main.py); `/api/models` exposes `"default": "static"` + `"default_ai_model": "<claude-id>"`

### AI-Powered Review (opt-in)
- Flip the UI toggle to "AI-Powered (opt-in)" and pick a model (Claude, GPT-4o, Gemini)
- API callers pass `model_id=<model-id>` explicitly
- Requires per-user `uipath auth` and active token (see README "AI-Powered Review Setup")
- Takes 30-60 seconds with polling
- Uses LLM to analyze against prompt-defined rules. `temperature=0`, `seed=42`, submission-order batch collection, and a final sort-by-(file, rule, entity) make output byte-stable across runs unless the model fingerprint changes upstream

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

`_rule_priority()` in [xaml_fixer.py](backend/services/xaml_fixer.py) controls execution order. The tiers are:

1. **Priority 0** — Security (UI-SEC-*, UX-DBP-029)
2. **Priority 1** — Removals + design fixes: ST-NMG-005 (shadow), ST-NMG-006 (var-arg collision), ST-NMG-012 (argument defaults), GEN-001 (unused variable), ST-DBP-* (empty catch, empty workflow, etc.)
3. **Priority 2** — Prefix renames: ST-NMG-001/002/009/011 — add `str_`/`in_`/`out_`/`io_`/`dt_` before downstream rules see them
4. **Priority 3** — Case correction: ST-NMG-010 — splits concatenated lowercase runs via wordninja and PascalCases
5. **Priority 4** — Length shortening: ST-NMG-008/016 — runs last on properly-cased names so it can drop whole middle words instead of naively truncating
6. **Priority 5** — Remaining NMG rules (e.g. ST-NMG-004)
7. **Priority 6-7** — UI Automation / Performance / Reliability / General

Example: if ST-NMG-002 ran before ST-NMG-012, renaming `Name="test"` to `Name="in_test"` would happen first, but the attribute-form default `this:Main.test="value"` would still reference the old name. ST-NMG-012 removes the default attribute first so the subsequent rename applies cleanly.

### Convergence loop — rules cascade until stable

`fix_xaml()` runs up to **5 passes** in a convergence loop. Between passes it re-parses the current XAML and re-invokes the static reviewer (`review_single_file`) to produce a fresh set of findings. This means a chain like `Filtercandidate… (38 chars)` → `str_Filtercandidate… (42 chars, too long)` → `str_FilterCandidateDetailsFromSapTableData (42 chars, PascalCase)` → `str_FilterCandidateTableData (28 chars)` all completes in one `/api/fix` call, because the length violation introduced on pass 1 is detected by the re-review and fixed on pass 2.

Every handler either consults its findings list OR re-scans the current XAML (ST-NMG-008/010/016 use re-scan so they compose correctly regardless of what earlier passes changed). The static reviewer is authoritative for subsequent passes; AI mode does not re-invoke the LLM between passes to avoid burning agent units.

### Determinism

Both modes aim for byte-identical output on the same input across runs:

- **Static**: no `uuid`, `random`, or wall-clock reads in fixers; `ST-DBP-003` generates LogMessage IDs as `LogMessage_AutoFix_001/002/…` (counter-based). `Counter.items()` iterations are explicitly `sorted()` so finding order is stable. Variable-scope tracking uses owner IdRef with a deterministic owner-counter fallback.
- **AI**: LLM called with `temperature=0`, `seed=42`, `response_format=json_object`. Parallel batches collected in **submission order** (not `as_completed`) so batch interleaving is stable. Post-processing sorts all findings by `(file_name, rule_id, activity_path)` before assigning `CR-###` IDs.

Verified: 3 consecutive identical static reviews produce the same finding hash; 3 consecutive fixes produce byte-identical XAML output.

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
