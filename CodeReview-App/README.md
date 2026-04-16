# UiPath XAML Code Review App

An AI-powered code review tool for UiPath RPA workflows. Upload XAML files or ZIP projects, get instant analysis against 47 Workflow Analyzer rules, and auto-fix naming convention violations.

## Features

- **AI-Powered Review** - Analyze UiPath XAML workflows using Claude, GPT-4, Gemini, and more via UiPath AI Trust Layer
- **47 Workflow Analyzer Rules** - Naming conventions, design best practices, UI automation, performance, reliability, security, and general quality checks
- **Auto-Fix** - Automatically fix naming convention violations (variable/argument prefixes) with side-by-side diff preview
- **Multiple Upload Modes** - Upload individual `.xaml` files or a `.zip` project archive
- **Excel Export** - Export findings to a styled Excel workbook with summary, details, rule coverage, and statistics
- **Interactive Results** - Filter findings by severity, category, and file using AG Grid
- **Token Auto-Refresh** - Background OAuth token management for uninterrupted sessions

## Screenshots

The app provides:
1. **Upload Zone** - Drag & drop files, select LLM model, enter project name
2. **Summary Panel** - Pass/fail verdict, severity breakdown, category counts
3. **Findings Grid** - Searchable, filterable data table with all findings
4. **Diff Viewer** - Side-by-side before/after comparison for auto-fixes

## Prerequisites

- **Python** >= 3.11
- **Node.js** >= 18
- **UiPath CLI** - Authenticated with `uipath auth`

## Quick Start

### 1. Clone the repository

```bash
git clone <repository-url>
cd CodeReview-APP
```

### 2. Backend Setup

```bash
cd backend
pip install -r requirements.txt
```

Authenticate with UiPath (one-time setup):

```bash
uipath auth
```

This creates `.uipath/.auth.json` and populates `.env` with your access token. The server auto-refreshes the token in the background.

Start the backend:

```bash
python -m uvicorn main:app --reload --port 8000
```

### 3. Frontend Setup

```bash
cd frontend
npm install
npm run dev
```

### 4. Open the App

Navigate to [http://localhost:5173](http://localhost:5173)

## Usage

1. **Enter a project name** for your review
2. **Select an LLM model** (Claude 3.7 Sonnet recommended)
3. **Upload files** - drag & drop `.xaml` files or a `.zip` project
4. **Click "Start Review"** - the review runs asynchronously with progress polling
5. **Review findings** - filter by severity, category, or file
6. **Auto-fix** - click "Auto-Fix" to apply naming convention fixes
7. **Review diffs** - inspect changes in the side-by-side diff viewer
8. **Accept fixes** - save corrected files to the output directory
9. **Export** - download findings as an Excel report

## Supported LLM Models

| Model | Provider | Class |
|-------|----------|-------|
| Claude 3.7 Sonnet (recommended) | Anthropic | UiPathChat |
| Claude 3.5 Sonnet v2 | Anthropic | UiPathChat |
| Claude 3.5 Sonnet | Anthropic | UiPathChat |
| Claude 3 Haiku | Anthropic | UiPathChat |
| GPT-4o | OpenAI | UiPathAzureChatOpenAI |
| GPT-4o Mini | OpenAI | UiPathAzureChatOpenAI |
| GPT-4.1 Mini | OpenAI | UiPathAzureChatOpenAI |
| o3 Mini | OpenAI | UiPathAzureChatOpenAI |
| Gemini 2.0 Flash | Google | UiPathChat |
| Gemini 1.5 Pro | Google | UiPathChat |

## Rule Catalog

### Naming (ST-NMG)
| Rule ID | Rule Name | Auto-Fix |
|---------|-----------|----------|
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

### Design Best Practices (ST-DBP)
| Rule ID | Rule Name |
|---------|-----------|
| ST-DBP-002 | High Arguments Count |
| ST-DBP-003 | Empty Catch Block |
| ST-DBP-007 | Multiple Flowchart Layers |
| ST-DBP-020 | Undefined Output Properties |
| ST-DBP-023 | Empty Workflow |
| ST-DBP-024 | Persistence Activity Check |
| ST-DBP-025 | Variables Serialization |
| ST-DBP-026 | Delay Activity Usage |
| ST-DBP-027 | Persistence Best Practice |
| ST-DBP-028 | Arguments Serialization |

### UI Automation
| Rule ID | Rule Name |
|---------|-----------|
| UI-DBP-006 | Container Usage |
| UI-DBP-013 | Excel Automation Misuse |
| UI-DBP-030 | Forbidden Variables in Selectors |
| UI-PRR-004 | Hardcoded Delays |
| UI-REL-001 | Large idx in Selectors |
| UI-SEC-004 | Sensitive Data in Selectors |
| UI-SEC-010 | App URL Restrictions |

### Performance
| Rule ID | Rule Name |
|---------|-----------|
| UI-PRR-001 | Simulate Click Not Used |
| UI-PRR-002 | Simulate Type Not Used |
| UI-PRR-003 | Open Application Misuse |

### Reliability
| Rule ID | Rule Name |
|---------|-----------|
| UI-REL-001 | Selector Index Too Large |
| GEN-REL-001 | Empty Sequences |

### Security
| Rule ID | Rule Name |
|---------|-----------|
| UI-SEC-004 | Sensitive Data Exposure |
| UI-SEC-010 | Unauthorized App Usage |
| UX-DBP-029 | Insecure Password Usage |

### General
| Rule ID | Rule Name |
|---------|-----------|
| GEN-001 | Unused Variables |
| GEN-002 | Unused Arguments |
| GEN-003 | Empty Sequences |
| GEN-004 | Project Structure Issues |
| GEN-005 | Package Restrictions |

## Project Structure

```
CodeReview-APP/
├── backend/
│   ├── main.py                      # FastAPI server & API endpoints
│   ├── requirements.txt             # Python dependencies
│   ├── models/
│   │   └── schemas.py               # Pydantic data models
│   ├── prompts/
│   │   └── code_review_prompt.py    # LLM system prompt (47 rules)
│   ├── services/
│   │   ├── llm_reviewer.py          # LLM invocation & batching
│   │   ├── xaml_parser.py           # XAML parsing & context extraction
│   │   ├── xaml_fixer.py            # Auto-fix engine
│   │   ├── zip_extractor.py         # ZIP file handling
│   │   └── token_refresh.py         # OAuth token auto-refresh
│   └── output/                      # Saved original & modified files
│
├── frontend/
│   ├── src/
│   │   ├── pages/ReviewPage.tsx     # Main review workflow
│   │   ├── components/
│   │   │   ├── UploadZone.tsx       # File upload & model selection
│   │   │   ├── ReviewGrid.tsx       # Findings data grid
│   │   │   ├── SummaryPanel.tsx     # Review summary & metrics
│   │   │   ├── DiffViewer.tsx       # Side-by-side diff viewer
│   │   │   ├── ExportButton.tsx     # Excel export
│   │   │   └── RulesCatalogModal.tsx# Rule reference modal
│   │   ├── models/finding.ts        # TypeScript interfaces
│   │   └── services/
│   │       ├── apiClient.ts         # API client & polling
│   │       └── excelExporter.ts     # Excel workbook generation
│   └── package.json
│
├── CLAUDE.md                        # Claude Code project context
└── README.md                        # This file
```

## API Reference

### `GET /api/health`
Returns server health and token status.

### `GET /api/models`
Returns available LLM models with recommended flag.

### `POST /api/review`
Submit XAML files for review. Returns a `job_id` for polling.

**Form Data:**
- `project_name` (string, required)
- `model_id` (string, optional, default: Claude 3.7 Sonnet)
- `files` (file[], required) - `.xaml` files or a single `.zip`

### `GET /api/review/{job_id}`
Poll review job status. Returns findings when complete.

### `POST /api/fix`
Apply auto-fixes to uploaded XAML files based on review findings.

### `POST /api/fix/accept`
Save accepted modified files to the output directory.

### `POST /api/refresh-token`
Manually trigger OAuth token refresh.

## Tech Stack

- **Backend**: FastAPI, Python 3.11+, UiPath LangChain SDK, Pydantic
- **Frontend**: React 18, TypeScript, Vite, Tailwind CSS, AG Grid
- **LLM**: UiPath AI Trust Layer (Claude, GPT-4, Gemini)
- **Export**: xlsx-js-style (Excel workbook generation)

## License

Internal use only.
