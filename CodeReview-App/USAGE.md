# UiPath Code Review App — Usage Guide

Step-by-step walkthrough of every flow in the app, plus troubleshooting tips for the issues that come up most often.

> **TL;DR** — Upload a ZIP or `.xaml` files → choose **Static** (default) or **AI** → click **Start Review** → click **Auto-Fix** to apply 18 deterministic fixes → click **Browse...** in the diff viewer to save to a folder of your choice.

---

## Table of contents

1. [Before you start](#1-before-you-start)
2. [Starting the app](#2-starting-the-app)
3. [Uploading a project](#3-uploading-a-project)
4. [Choosing Static vs AI mode](#4-choosing-static-vs-ai-mode)
5. [Reading the results dashboard](#5-reading-the-results-dashboard)
6. [Running Auto-Fix](#6-running-auto-fix)
7. [Reviewing the side-by-side diff](#7-reviewing-the-side-by-side-diff)
8. [Saving fixed files (Browse-folder vs server-side)](#8-saving-fixed-files)
9. [Exporting an Excel report](#9-exporting-an-excel-report)
10. [Troubleshooting](#10-troubleshooting)
11. [Glossary of rule IDs](#11-glossary-of-rule-ids)

---

## 1. Before you start

| Need | Why |
|---|---|
| Python ≥ 3.11 | Backend runs on FastAPI |
| Node.js ≥ 18 | Frontend runs on Vite |
| A modern Chromium browser (Chrome/Edge) | The Browse-folder save flow uses the File System Access API — only available on Chromium-based browsers |
| `uipath auth` (one-time) | **Only if** you want AI-powered review. Static mode needs no UiPath auth. |

The app is local-only — both servers bind to `127.0.0.1` and never expose anything to the network.

---

## 2. Starting the app

Open two terminals.

**Terminal 1 — backend:**

```bash
cd backend
pip install -r requirements.txt
python -m uvicorn main:app --reload --port 8000
```

Wait for `Application startup complete.` Then check it's healthy:

```bash
curl http://127.0.0.1:8000/api/health
```

You should see `"status":"ok"`. The `"token"` block is irrelevant for Static mode — the field reading `"valid": false` only matters when you want AI mode.

**Terminal 2 — frontend:**

```bash
cd frontend
npm install
npm run dev
```

Vite prints `Local: http://localhost:5173/`. Open that URL in Chrome or Edge.

> If port 8000 or 5173 is busy, the next free port is used; the frontend's API client reads `VITE_API_URL` from `frontend/.env.local` if you need to override.

---

## 3. Uploading a project

The home page (`/`) has a single drag-and-drop zone:

- **Drag a `.zip`** of a UiPath project (the one Studio publishes — ZIP of the project folder).
- **Or drag one or more `.xaml` files** directly. The reviewer will analyze them in isolation, but cross-file features (cross-file argument reconciliation, project structure rules) only fire when you upload the whole project as a ZIP.

After dropping, type a **Project Name** (free text, used in exports) and click **Start Review**.

> Up to 50 MB ZIPs are accepted. Larger uploads are rejected with HTTP 400 — re-zip with only the relevant folders, or split the project.

---

## 4. Choosing Static vs AI mode

The mode toggle sits above the upload zone. The two modes give the same rule coverage but very different runtime characteristics.

| | **Static (default)** | **AI-powered (opt-in)** |
|---|---|---|
| Speed | < 1 second | 30–60 seconds |
| Auth | None | Requires `uipath auth` |
| Cost | Free | Consumes UiPath Agent Units |
| Determinism | Byte-stable across runs | Byte-stable on the same model fingerprint |
| Best for | Every CI run, every commit, large projects | Spot-check on critical workflows |

**Static** is the right default for almost every situation. Only switch to **AI-powered** when you want a model's anti-pattern reasoning on top of the rule catalog.

If AI is selected, pick a model from the dropdown — Claude 3.7 Sonnet is the recommended default (most reasoned output, lowest false-positive rate). Other supported models: Claude 3.5 Sonnet v2, Claude 3 Haiku, GPT-4o, GPT-4.1 Mini, o3 Mini, Gemini 2.0 Flash, Gemini 1.5 Pro.

---

## 5. Reading the results dashboard

After analysis completes, the app navigates to `/results`. The page has three regions:

### 5.1 Top: severity bars + metric cards

- **Severity bars** — Critical / High / Medium / Low / Info colour-coded by count.
- **Metric cards** — Files reviewed, total findings, auto-fixable count, fixed count.

### 5.2 Middle: summary panel

- **Category filter chips** — Click a category (Naming / Design / UI Automation / Performance / Reliability / Security / General) to scope the grid to only that family.
- **Rule catalog button** — Opens a modal with every rule, its severity, category, description, and recommendation. Useful when reviewing findings.

### 5.3 Bottom: AG Grid findings table

Sortable / filterable / groupable columns:

| Column | Notes |
|---|---|
| Status | `Open`, `Fixed` (after Auto-Fix), or empty |
| Rule ID | e.g. `ST-NMG-002` — clickable to see rule detail |
| Rule Name | Plain-English name |
| Severity | Coloured chip |
| Category | Same families as the filter chips |
| File | Relative path inside the ZIP |
| Activity / Variable | Where the finding is anchored |
| Description | What's wrong |
| Recommendation | Suggested fix (used by manual-fix rules) |

Click any row to highlight the corresponding entry in the rule catalog modal.

---

## 6. Running Auto-Fix

Click the **Auto-Fix** button (top-right of the dashboard). The backend runs the cascading fix pipeline: priority-ordered rule handlers, up to 5 iterations of static re-review until nothing else changes, then two project-wide post-passes (DisplayName cleanup + InvokeWorkflowFile reconciliation).

What gets fixed automatically (18 rules):

- **Naming** — type prefixes (`str_`, `dt_`, ...), direction prefixes (`in_`/`out_`/`io_`), PascalCase, length-shorten, dedupe
- **Activity rename (ST-NMG-020)** — every default-named activity gets a content-derived name. Containers inherit from their first inner activity.
- **Removals** — empty Sequence, empty workflow file, unused Variable, shadow Variable, var-arg collision, In-argument default values
- **Empty catch (ST-DBP-003)** — injects a `LogMessage` Level=Error
- **Sibling-scope variable disambiguation** — runs after convergence

What's NEVER fixed automatically (21 detection-only rules): UI Simulate input flags, browser/UiElement serialization, Excel scope, hardcoded delays, and similar "needs design judgement" rules. These show up in the grid with a recommendation but no Status=Fixed badge.

> If something can't be fixed without breaking the workflow (e.g. a rename would create a duplicate name), the row gets a `SKIPPED` line in the change log explaining why. The finding stays Open.

---

## 7. Reviewing the side-by-side diff

When Auto-Fix completes, the **Diff Viewer** modal opens automatically.

### Layout

- **Left sidebar** — every fixed file with a checkbox. Uncheck a file to exclude its changes from the save (the original content is saved instead).
- **Main pane** — three rows per file:
  1. **Changes panel** — bullet list of every edit (`ST-NMG-002: Renamed argument 'X' -> 'in_X'`, `ST-NMG-020: Cleanup — stripped invalid DisplayName`, `ST-NMG-002: Reconciled InvokeWorkflowFile arg key`, etc.).
  2. **Original / Modified** column headers (red / green).
  3. **Diff body** — line-by-line side-by-side with insertions in green, deletions in red, unchanged lines in gray.

### Tips

- Use the **file list checkboxes** to drop a file from the save before clicking Accept — handy when one file's changes look right and another's don't.
- Files marked `Will be deleted` (red, line-through) are workflows the empty-workflow rule (ST-DBP-023) wants to remove. The Save flow will actually delete them on disk if you keep them checked.
- The **Saving X/Y...** counter on the Save button shows live progress — you'll see it advance file-by-file.

---

## 8. Saving fixed files

Click **Accept All & Save**. A path/folder prompt appears.

### 8.1 Browse-folder (Chrome / Edge — recommended)

1. Click **Browse...**
2. The native folder picker opens. Pick the destination folder (anywhere — Desktop, an existing project folder, a fresh empty folder).
3. The selected folder name appears as `Selected folder: <name>` in the prompt.
4. Click **Save**. Files write **directly from the browser** to your chosen folder via the File System Access API. The XAMLs are sent from browser memory, and non-XAML project assets (`.cs`, `project.json`, screenshots, the `.entities/` folder, etc.) are fetched from the backend's `/api/fix/passthrough/{fix_id}` endpoint and written as bytes.
5. The save uses bounded parallel writes (concurrency 6). For a typical ~30-file project this finishes in a few seconds.

> The first time you pick a folder per session, Chrome shows a permission dialog asking to allow editing in that folder. Click **Allow**. The permission scopes to that folder for the session only.

### 8.2 Backend POST fallback

If you don't click Browse, the input field accepts a server-side path:

- Leave it empty → files go to `backend/output/<project_name>/`
- Type an absolute path like `C:\fixed\MyProject` → files go there

The backend writes the files and returns the saved location. Use this when:

- You're on a browser without FSA support (older Firefox, Safari)
- The destination is a server-side path the browser couldn't reach anyway

### 8.3 What's preserved

Either flow preserves the **original ZIP folder structure** exactly. If your input was `MyProject/Main.xaml` + `MyProject/Workflows/Sub.xaml`, both files land in the same relative locations under your chosen folder. No `modified/` subfolder, no flattening, no renaming.

> If a path can't be written (illegal characters, Windows reserved name like `CON`, etc.), that single entry is skipped and surfaced as an error in the banner — the rest of the save still completes.

---

## 9. Exporting an Excel report

Click **Export Excel** in the dashboard toolbar. The download starts immediately. The workbook has four sheets:

| Sheet | What's in it |
|---|---|
| **Executive Summary** | Severity counts, fixed count, top 5 rules by frequency, file health rollup |
| **Findings** | Every finding row with Rule ID, severity, file, description, recommendation, status |
| **Per-File Breakdown** | Findings grouped by file with a per-file health score |
| **Rule Coverage** | All 38 rules with whether they fired on this project |

Useful for sharing review results with stakeholders who can't (or won't) run the app themselves.

---

## 10. Troubleshooting

### Studio fails to load a fixed file with `Could not find member 'DisplayName' in type 'uix:TargetX'`

Cause: a previous version of the auto-fixer wrongly injected `DisplayName` onto a typed UI sub-component (`Target`, `TargetApp`, `TargetAnchorable`, `VerifyExecution*`, etc.).

Fix: re-upload the project and run **Auto-Fix** again. The cleanup pass at the start of `fix_xaml` strips every invalid `DisplayName` from these elements automatically. The fix is permanent — the current rule code never injects `DisplayName` here.

### Studio fails to run a test case with `argument doesn't exist on the called workflow`

Cause: a callee workflow's argument was renamed (prefix add + PascalCase) but a caller's `InvokeWorkflowFile` is still binding the old key.

Fix: re-upload the project ZIP (the WHOLE project — not just the broken file) and run **Auto-Fix** again. The post-pass `reconcile_invoke_workflow_keys` rewrites every caller's `x:Key` to match the renamed arg. You'll see `ST-NMG-002: Reconciled InvokeWorkflowFile arg key 'old' -> 'new'` entries in the diff viewer.

### "Saving X/Y..." stalls

If the counter stops advancing, FSA may be hung on a specific file (Studio has it open and locked, antivirus is scanning, etc.). The error banner will eventually surface the offending path. Refresh the tab and try again.

### Browse-folder button isn't there / says "not supported"

You're on a browser without File System Access API support — Firefox and Safari don't expose it. Either:
- Switch to Chrome or Edge, or
- Use the type-a-path fallback in the same prompt and the backend will save server-side.

### `/api/fix` returns 404 on `passthrough` files

The fix-id cache is per-server-process and not persisted. If you restart the backend between Auto-Fix and Save, the passthrough cache is empty. Re-run Auto-Fix to repopulate, then Save.

### AI-mode review returns 401 / 403

Token expired or your tenant doesn't have the chosen model enabled.

```bash
# Re-authenticate (must run from backend/ directory)
cd backend
uipath auth
```

Then `curl http://127.0.0.1:8000/api/health` should show `"valid": true` again.

### "No .xaml files found" on upload

The ZIP doesn't contain any XAMLs at the top level or in subfolders. Re-zip including the workflow files. Hidden XAMLs in `.local/`, `.entities/`, `lib/` are intentionally skipped.

### Static review reports findings but Auto-Fix produces 0 changes

Look at the rule IDs — if every finding is from the detection-only set (UI-PRR-*, ST-DBP-025/028, etc.), there's nothing to auto-fix. The findings need manual changes in Studio. The Excel export's Recommendation column tells you what to do per finding.

---

## 11. Glossary of rule IDs

| Prefix | Family | What it covers |
|---|---|---|
| `ST-NMG-*` | Naming | Variable & argument prefixes, PascalCase, length, duplicate display names, default Studio names |
| `ST-DBP-*` | Design Best Practices | Empty catch, persistence, serialization, argument count, undefined outputs |
| `UI-DBP-*` | UI design | Container usage, Excel scope misuse |
| `UI-PRR-*` | Performance | Simulate click/type, hardcoded delays, application reuse |
| `UI-REL-*` | Reliability | Selector index sizes |
| `UI-SEC-*` | Security | Sensitive data in selectors, unauthorized apps |
| `UX-DBP-*` | UX design | Insecure password handling |
| `GEN-*` | General | Unused variables/arguments, project structure, package restrictions |
| `GEN-REL-*` | General reliability | Empty Sequences |

Click any rule in the dashboard's Rule catalog modal to see its full description, severity, and recommended fix.

---

## Need more detail?

- **[README.md](README.md)** — features overview + setup
- **[CLAUDE.md](CLAUDE.md)** — engineering reference for contributors (architecture, fix pipeline, scoping notes)
- **[backend/services/xaml_fixer.py](backend/services/xaml_fixer.py)** — ground truth for every auto-fix rule
- **[backend/services/static_reviewer.py](backend/services/static_reviewer.py)** — ground truth for every detection rule
