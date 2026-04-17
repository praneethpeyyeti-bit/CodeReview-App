# UiPath XAML Code Review App

An AI-powered and static analysis code review tool for UiPath RPA workflows. Upload XAML files or ZIP projects, get instant analysis against 37 Workflow Analyzer rules, and auto-fix 5 naming convention violations.

## Features

- **Static Analysis (No AI)** — Instant results from 36 rule checkers, no auth or Agent Units needed
- **AI-Powered Review** — Deep analysis using Claude, GPT-4, Gemini via UiPath AI Trust Layer
- **37 Workflow Analyzer Rules** — Naming, design, UI automation, performance, reliability, security, and general quality
- **Auto-Fix 5 Rules** — Variable/argument prefix renaming and unused variable removal
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

## Auto-Fix Rules (5)

Only text-level operations — safe for UiPath Studio to open without errors.

| Rule | What it Fixes | Method |
|------|--------------|--------|
| ST-NMG-001 | Add type prefix to variables (str_, int_, dt_, bln_, dtm_, ts_, arr_, dic_) | Regex rename |
| ST-NMG-002 | Add direction prefix to arguments (in_, out_, io_) | Regex rename |
| ST-NMG-009 | Add dt_ prefix to DataTable variables | Regex rename |
| ST-NMG-011 | Add dt_ prefix to DataTable arguments | Regex rename |
| GEN-001 | Remove unused variable declarations | XML element removal |

After auto-fix, findings for fixed rules show `status = "Fixed"` in the review grid.

### Detection-Only Rules (32)

The remaining 32 rules are detected and reported with specific recommendations, but require manual fix in UiPath Studio. UiPath's WPF-based XAML parser rejects programmatic insertion of elements with attributes — only text-level renames are safe.

## Rule Catalog (37 Unique Rules, 7 Categories)

### Naming (ST-NMG) — 10 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| ST-NMG-001 | Variables Naming Convention | Yes |
| ST-NMG-002 | Arguments Naming Convention | Yes |
| ST-NMG-004 | Display Name Duplication | No |
| ST-NMG-005 | Variable Overrides Variable | No |
| ST-NMG-006 | Variable Overrides Argument | No |
| ST-NMG-008 | Variable Length Exceeded | No |
| ST-NMG-009 | DataTable Variable Prefix | Yes |
| ST-NMG-011 | DataTable Argument Prefix | Yes |
| ST-NMG-012 | Argument Default Values | No |
| ST-NMG-016 | Argument Length Exceeded | No |

### Design Best Practices (ST-DBP) — 10 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| ST-DBP-002 | High Arguments Count | No |
| ST-DBP-003 | Empty Catch Block | No |
| ST-DBP-007 | Multiple Flowchart Layers | No |
| ST-DBP-020 | Undefined Output Properties | No |
| ST-DBP-023 | Empty Workflow | No |
| ST-DBP-024 | Persistence Activity Check | No |
| ST-DBP-025 | Variables Serialization | No |
| ST-DBP-026 | Delay Activity Usage | No |
| ST-DBP-027 | Persistence Best Practice | No |
| ST-DBP-028 | Arguments Serialization | No |

### UI Automation — 7 rules
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|:---:|
| UI-DBP-006 | Container Usage | No |
| UI-DBP-013 | Excel Automation Misuse | No |
| UI-DBP-030 | Forbidden Variables in Selectors | No |
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
| GEN-REL-001 | Empty Sequences | No |

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
| GEN-003 | Empty Sequences | No |
| GEN-004 | Project Structure Issues | No |
| GEN-005 | Package Restrictions | No |

Note: Source Excel has 41 rows (some rules listed in multiple categories), but 37 unique rule IDs.

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
    xaml_fixer.py              # Auto-fix engine (5 rules)
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
