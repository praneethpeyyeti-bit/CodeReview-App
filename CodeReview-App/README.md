# UiPath XAML Code Review App

An AI-powered and static analysis code review tool for UiPath RPA workflows. Upload XAML files or ZIP projects, get instant analysis against 37 Workflow Analyzer rules, and auto-fix 16 rules (naming conventions, PascalCase, duplicate display names, shadows, length limits, argument defaults, empty catches, empty sequences, unused variables).

## Features

- **Static Analysis (No AI)** — Instant results from 36 rule checkers, no auth or Agent Units needed
- **AI-Powered Review** — Deep analysis using Claude, GPT-4, Gemini via UiPath AI Trust Layer
- **37 Workflow Analyzer Rules** — Naming, design, UI automation, performance, reliability, security, and general quality
- **Auto-Fix 16 Rules** — Variable/argument prefix renaming, PascalCase body conversion, duplicate DisplayName rewrites (selector-derived), shadow removal, length trimming, argument-default cleanup, empty-catch Log Message injection, empty-sequence removal, unused-variable removal, empty-workflow file deletion
- **Side-by-Side Diff** — Preview all changes before accepting
- **Folder Structure Preserved** — Fixed files maintain original ZIP directory layout
- **Excel Export** — Styled report with executive summary, findings, per-file breakdown, and rule coverage
- **Two-Page UI** — Clean upload page with animated workflow pipeline, full results dashboard

## Prerequisites

- **Python** >= 3.11
- **Node.js** >= 18
- **UiPath CLI** (optional) — Only needed for AI model review (`uipath auth`)

## Quick Start

### 1. Backend

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 3. Open the App

Navigate to [http://localhost:5173](http://localhost:5173)

## Usage

1. **Choose analysis mode** — Toggle between "Static Analysis" (default, instant) or "AI-Powered"
2. **Upload files** — Drag & drop `.xaml` files or a `.zip` project archive
3. **Enter project name** and click "Start Review"
4. **Review findings** — Filter by severity, category, or file in the dashboard
5. **Auto-fix** — Click "Auto-Fix" to apply safe naming corrections
6. **Review diffs** — Inspect changes side-by-side before accepting
7. **Accept & save** — Fixed files saved preserving original folder structure
8. **Export** — Download findings as an Excel report

## Review Modes

| Mode | Speed | Auth Required | Rules | Agent Units |
|------|-------|:---:|:---:|:---:|
| Static Analysis | < 1 second | No | 36 checkers | None |
| Claude 3.7 Sonnet | 30-60 seconds | Yes | 37 (via prompt) | Yes |
| GPT-4o / Gemini | 30-60 seconds | Yes | 37 (via prompt) | Yes |

## Auto-Fix Rules (16)

Text-level operations on raw XAML — safe for UiPath Studio to open without errors.

| Rule | What it Fixes | Method |
|------|--------------|--------|
| ST-NMG-001 | Add type prefix to variables (`str_`, `int_`, `dt_`, `bln_`, `dtm_`, `ts_`, `arr_`, `dic_`) | Regex rename |
| ST-NMG-002 | Add direction prefix to arguments (`in_`, `out_`, `io_`) | Regex rename |
| ST-NMG-004 | Rename duplicate DisplayNames using selector-derived labels (e.g. `Click 'Save'`); counter fallback | Positional attribute-value rewrite |
| ST-NMG-005 | Remove inner-scope shadow variable declarations; keep outermost | Element removal |
| ST-NMG-006 | Remove variable that collides with an argument; retain argument | Element removal |
| ST-NMG-008 | Shorten variable name > 30 chars (preserves prefix, drops middle words) | Regex rename |
| ST-NMG-009 | Add `dt_` prefix to DataTable variables | Regex rename |
| ST-NMG-010 | Convert non-PascalCase variable/argument bodies (e.g. `str_variable1` → `str_Variable1`, `dt_sales_data` → `dt_SalesData`, `str_Filtercandidatedetailsfromsaptabledata` → `str_FilterCandidateDetailsFromSapTableData` via wordninja word-splitter) | Regex rename, re-scans current XAML |
| ST-NMG-011 | Add direction prefix (`in_`/`out_`/`io_`) to DataTable arguments | Regex rename |
| ST-NMG-012 | Remove default values for **In** arguments (Out/InOut skipped). Handles both element-form (`<this:Main.arg>...</this:Main.arg>`) and attribute-form (`this:Main.arg="value"` on root) | Element removal + attribute strip |
| ST-NMG-016 | Shorten argument name > 30 chars | Regex rename |
| ST-DBP-003 | Insert `<ui:LogMessage Level="Error">` inside empty Catch body (includes exception type, message, source). Auto-adds `xmlns:ui` on the Activity root if missing | ET-guided + positional insertion |
| ST-DBP-023 | Delete empty workflow file on accept | File-level deletion via fix-response `delete` flag |
| GEN-001 | Remove unused `<Variable/>` declarations | Element removal |
| GEN-003 / GEN-REL-001 | Remove empty Sequence elements — both self-closing `<Sequence/>` and open-tag `<Sequence>[metadata only]</Sequence>` | Element removal with metadata-only check |

After auto-fix, findings for fixed rules show `status = "Fixed"` in the review grid.

### Detection-Only Rules (21)

The remaining 21 rules are detected and reported with specific recommendations, but require manual fix in UiPath Studio. UiPath's WPF-based XAML parser rejects programmatic insertion of elements-with-attributes inside property-element contexts — that's what blocks auto-fix for most UI-side rules (SimulateClick on `<Click><Click.Target>...</Click.Target></Click>`, etc.).

### Rule Scoping Notes
- **GEN-REL-001 Empty Sequences** only flags user-authored empty Sequences. Catch-body Sequences (direct children of `<ActivityAction>`) are skipped because **ST-DBP-003** handles them. Sequences inside `TryCatch.Try` / `TryCatch.Finally` *are* flagged — an empty Finally has no other rule covering it.
- **Fix execution order**: the backend runs removal rules (shadow, unused variable, argument default, empty catch, empty workflow) **before** rename rules (ST-NMG-001/002/004/008/009/010/011/016). Otherwise a rename would target names that should have been deleted, or stale attribute references like `this:Main.oldName="value"` would survive after a rename.
- **Attribute-form argument defaults**: UiPath serializes some argument defaults as attributes on the root Activity (e.g., `<Activity this:Main.argName="value">`). The parser detects both this form and the element-form `<this:Main.argName>...</this:Main.argName>`. Both are detected for ST-NMG-012 and correctly updated when renames happen.

## Rule Catalog (37 Unique Rules, 7 Categories)

### Naming (ST-NMG) — 11 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| ST-NMG-001 | Variables Naming Convention | Yes |
| ST-NMG-002 | Arguments Naming Convention | Yes |
| ST-NMG-004 | Display Name Duplication | Yes |
| ST-NMG-005 | Variable Overrides Variable | Yes |
| ST-NMG-006 | Variable Overrides Argument | Yes |
| ST-NMG-008 | Variable Length Exceeded | Yes |
| ST-NMG-009 | DataTable Variable Prefix | Yes |
| ST-NMG-010 | PascalCase Convention | Yes |
| ST-NMG-011 | DataTable Argument Naming | Yes |
| ST-NMG-012 | Argument Default Values | Yes |
| ST-NMG-016 | Argument Length Exceeded | Yes |

### Design Best Practices (ST-DBP) — 10 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| ST-DBP-002 | High Arguments Count | No |
| ST-DBP-003 | Empty Catch Block | Yes |
| ST-DBP-007 | Multiple Flowchart Layers | No |
| ST-DBP-020 | Undefined Output Properties | No |
| ST-DBP-023 | Empty Workflow | Yes |
| ST-DBP-024 | Persistence Activity Check | No |
| ST-DBP-025 | Variables Serialization | No |
| ST-DBP-026 | Delay Activity Usage | No |
| ST-DBP-027 | Persistence Best Practice | No |
| ST-DBP-028 | Arguments Serialization | No |

### UI Automation — 6 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| UI-DBP-006 | Container Usage | No |
| UI-DBP-013 | Excel Automation Misuse | No |
| UI-PRR-004 | Hardcoded Delays | No |
| UI-REL-001 | Large idx in Selectors | No |
| UI-SEC-004 | Sensitive Data in Selectors | No |
| UI-SEC-010 | App URL Restrictions | No |

### Performance (UI-PRR) — 3 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| UI-PRR-001 | Simulate Click Not Used | No |
| UI-PRR-002 | Simulate Type Not Used | No |
| UI-PRR-003 | Open Application Misuse | No |

### Reliability (GEN-REL) — 1 rule
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| GEN-REL-001 | Empty Sequences | Yes |

### Security — 3 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| UI-SEC-004 | Sensitive Data Exposure | No |
| UI-SEC-010 | Unauthorized App Usage | No |
| UX-DBP-029 | Insecure Password Usage | No |

### General (GEN) — 5 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| GEN-001 | Unused Variables | Yes |
| GEN-002 | Unused Arguments | No |
| GEN-003 | Empty Sequences | Yes |
| GEN-004 | Project Structure Issues | No |
| GEN-005 | Package Restrictions | No |

Note: Source Excel has 41 rows (some rules listed in multiple categories), plus ST-NMG-010 added locally for PascalCase enforcement — 37 unique rule IDs.

## Project Structure

```
backend/
  main.py                      # FastAPI server & API endpoints
  models/schemas.py            # Pydantic data models
  prompts/code_review_prompt.py # LLM system prompt (AI mode only)
  services/
    static_reviewer.py         # Static analysis engine (36 rule checker functions)
    llm_reviewer.py            # LLM invocation & batching
    xaml_parser.py             # Enhanced XAML parsing (properties, selectors, catch blocks, expressions)
    xaml_fixer.py              # Auto-fix engine (6 rules)
    zip_extractor.py           # ZIP file handling
    token_refresh.py           # OAuth token auto-refresh

frontend/src/
  context/ReviewContext.tsx    # Shared state provider
  pages/
    HomePage.tsx               # Upload + static/AI toggle + workflow animation
    ResultsPage.tsx            # Dashboard + grid + auto-fix + diff
  components/                  # UploadZone, SummaryPanel, ReviewGrid, DiffViewer, etc.
  services/
    apiClient.ts               # API client (sync + async polling)
    excelExporter.ts           # Excel report (37 rules, 7 categories)
```

## Tech Stack

- **Backend**: FastAPI, Python 3.11+, Pydantic
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, AG Grid, React Router
- **Static Analysis**: Pure Python XML parsing + regex (no external dependencies)
- **AI**: UiPath LangChain SDK (Claude, GPT-4, Gemini) — optional
- **Export**: xlsx-js-style (Excel workbook generation)

## License

Internal use only.
