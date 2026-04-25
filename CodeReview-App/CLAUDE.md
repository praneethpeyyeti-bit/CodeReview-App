# UiPath XAML Code Review App

## Project Overview

Full-stack code review tool for UiPath RPA XAML workflows. **Static analysis is the default** — deterministic, instant, zero auth, zero agent units. **AI-Powered review** (Claude, GPT-4, Gemini via UiPath AI Trust Layer) is opt-in per request. Both modes cover the same 38 unique Workflow Analyzer rules across 7 categories; auto-fix handles 17 rules (including file-level deletion of empty workflows and renaming activities still using Studio default names).

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
    static_reviewer.py     # Static analysis engine (37 rule checker functions, no LLM)
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
- 37 rule checker functions run deterministically on parsed XAML data
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
| Naming | ST-NMG-* | 12 | Variable/argument prefixes, PascalCase body, length, duplication, shadowing, name collisions, defaults, default-Studio-name detection |
| Design Best Practices | ST-DBP-* | 10 | Empty catch, high arg count, nested flowcharts, undefined outputs, empty workflow, persistence, serialization, delays |
| UI Automation | UI-DBP-*, UI-PRR-004, UI-REL-001, UI-SEC-* | 6 | Container usage, Excel scope, hardcoded delays, idx in selectors, sensitive data |
| Performance | UI-PRR-* | 3 | Simulate click/type, application reuse |
| Reliability | GEN-REL-* | 1 | Empty sequences |
| Security | UI-SEC-*, UX-DBP-029 | 3 | Sensitive data exposure, unauthorized apps, insecure passwords |
| General | GEN-* | 5 | Unused variables/arguments, empty sequences, project structure, package restrictions |

Note: Source Excel has 41 rows (some rules appear in multiple categories), plus ST-NMG-010 (PascalCase enforcement) and ST-NMG-020 (Default Studio Display Name) added locally — 38 unique rule IDs.

## Auto-Fix Rules (18 Rules)

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
| ST-NMG-020 | Rename activities still using the Studio default DisplayName (missing or equals type name). UI activities use selector content; non-UI use type-specific descriptors (Assign target variable, LogMessage text, InvokeWorkflowFile filename, Delay duration, If/While condition, etc.). Activities with no derivable descriptor are skipped. Runs LAST in the NMG tier so descriptors reflect the final post-rename, post-shorten variable/argument names | ET-guided discovery + positional regex (insert if no DisplayName, replace if DisplayName=type) |
| ST-DBP-003 | Insert `<ui:LogMessage Level="Error">` inside the empty Catch body Sequence (includes exception type, message, source). Auto-injects `xmlns:ui` on the Activity root when not already declared | ET-guided discovery + positional regex insertion before `</Sequence>` |
| ST-DBP-023 | Delete empty workflow file on accept | File deletion via `delete` flag (fix response) + `os.remove()` in `/api/fix/accept` |
| GEN-001 | Remove unused `<Variable/>` declarations | Element removal |
| GEN-003 / GEN-REL-001 | Remove empty Sequence elements — both self-closing `<Sequence/>` and open-tag `<Sequence>[metadata-only]</Sequence>` (by flagged DisplayName). Structural Catch-body Sequences are excluded (ST-DBP-003 handles those). Also handles no-DisplayName empty Sequences (matched by IdRef) when `Sequence` itself is in the flagged set | Element removal with metadata-only verification |
| ST-NMG-005-SIBLINGS | Disambiguate sibling-scope variables sharing the same name by suffixing with a bare digit (`dt_FoldersData2`, `dt_FoldersData3`, ...). Only renames within the owner activity's text span via `_find_owner_text_span` (anchored on `WorkflowViewState.IdRef`) so cross-scope references stay intact. UiPath ST-NMG-005 flags any cross-scope name reuse as "Variable Overrides Variable" — our static reviewer is more conservative and only flags ancestor shadows, so this rule has no corresponding finding and runs as a post-convergence pass on every file. Skips true ancestor shadows (already removed by ST-NMG-005). After this pass runs, `_fix_gen_001` re-runs to clean up declarations that were previously hidden as "used" by the flat reviewer but are now provably orphaned (e.g. `dt_AssetsData8` with no in-scope expression refs) | ET-guided owner discovery + scope-bounded `_rename_in_xaml` |

After auto-fix, findings for fixed rules get `status = "Fixed"` in the review grid.

### Detection-only rules (21)
The remaining 21 rules (ST-DBP-002/007/020/024/025/026/027/028, UI-DBP-006/013, UI-PRR-001/002/003/004, UI-REL-001, UI-SEC-004/010, UX-DBP-029, GEN-002, GEN-004/005) are detected with specific recommendations but require manual fix. UiPath's WPF-based XAML parser rejects programmatic insertion of elements-with-attributes inside property-element contexts — that's what blocks auto-fix for most UI-side rules.

### Activity-naming rules at a glance

| Rule | What it flags | What auto-fix does |
|---|---|---|
| ST-NMG-004 | Same DisplayName used by 2+ activities | Renames the 2nd..Nth occurrence using selector or type-specific descriptors |
| ST-NMG-020 | Activity uses Studio default name (missing or equals type) | Inserts/replaces DisplayName using selector or type-specific descriptors |

Both rules can apply to the same activity (e.g., 3 Assigns all named "Assign" → ST-NMG-004 flags 1 finding for the duplication, ST-NMG-020 flags 3 findings for default-naming). The fixer runs ST-NMG-020 last so its descriptors pull from finalized variable/argument names.

### Fix pipeline ordering

`_rule_priority()` in [xaml_fixer.py](backend/services/xaml_fixer.py) controls execution order. The tiers are:

1. **Priority 0** — Security (UI-SEC-*, UX-DBP-029)
2. **Priority 1** — Removals + design fixes: ST-NMG-005 (shadow), ST-NMG-006 (var-arg collision), ST-NMG-012 (argument defaults), GEN-001 (unused variable), ST-DBP-* (empty catch, empty workflow, etc.)
3. **Priority 2** — Prefix renames: ST-NMG-001/002/009/011 — add `str_`/`in_`/`out_`/`io_`/`dt_` before downstream rules see them
4. **Priority 3** — Case correction: ST-NMG-010 — splits concatenated lowercase runs via wordninja and PascalCases
5. **Priority 4** — Length shortening: ST-NMG-008/016 — runs last on properly-cased names so it can drop whole middle words instead of naively truncating
6. **Priority 5** — Default-name rewrite: ST-NMG-020 — runs LAST in the NMG tier so its descriptors (which pull from `<Assign.To>`, `Message`, etc.) reference the final post-rename variable/argument names
7. **Priority 6** — Remaining NMG rules (e.g. ST-NMG-004)
8. **Priority 7-8** — UI Automation / Performance / Reliability / General
9. **Post-convergence (after the loop terminates)**: `_fix_st_nmg_005_siblings` disambiguates sibling-scope variable duplicates (no corresponding finding — runs unconditionally on the converged content), then `_fix_gen_001` re-runs against a fresh re-review to remove any orphan declarations that disambiguation surfaced

Example: if ST-NMG-002 ran before ST-NMG-012, renaming `Name="test"` to `Name="in_test"` would happen first, but the attribute-form default `this:Main.test="value"` would still reference the old name. ST-NMG-012 removes the default attribute first so the subsequent rename applies cleanly.

### Collision guards on rename rules

ST-NMG-001/002/009/011 (prefix-add) and ST-NMG-008/016 (length-shorten) all consult `_collect_declared_names(content)` before applying a rename. If the candidate `new_name` is already declared as a variable or argument anywhere in the file, the rule **skips** the rename and surfaces a `SKIPPED` line in the change log instead of corrupting the workflow. Scenarios this protects against:

- **Pre-existing duplicate**: file has both `URLCredentialTarget` and `str_URLCredentialTarget`. Without the guard, ST-NMG-001 would rename the first to `str_URLCredentialTarget`, producing two declarations with the same name and UiPath rejecting the file with "A variable, RuntimeArgument or DelegateArgument already exists with the name 'X'. Names must be unique within an environment scope." With the guard the second is left at its original name and a SKIPPED log entry surfaces.
- **Shorten-into-collision**: `_shorten_name`'s middle-word-drop algorithm can map distinct originals to the same shortened name (e.g. `URLSpecificCredentialTarget` and `URLTenantSpecificCredentialTarget` both → `URLCredentialTarget`; `in_FolderMigrationTemplateFilePath` and `in_FolderMigrationWorkbookFilePath` both → `in_FolderMigrationFilePath`). ST-NMG-008/016 pre-compute every proposal and group by target — any group with 2+ originals is skipped to keep the names distinct.

`fix_xaml` propagates SKIPPED messages even when a handler returns `modified=False` (so the user sees why a finding wasn't auto-fixed) and dedupes the final change log to avoid repeats from convergence-loop reflagging.

### `_rename_in_xaml` covers four reference forms

Every rename uses `_rename_in_xaml` to update declarations + every reference. The scanner handles:

1. **Variable/Argument declarations**: `Name="oldName"`
2. **InvokeWorkflowFile keys**: `Key="oldName"`
3. **VB-expression references** in four shapes:
   - **3a**: simple bracket interiors `[oldName + 1]` — every occurrence in the bracket, not just the first
   - **3b**: `ExpressionText="..."` attribute values on `<mva:VisualBasicValue>` / `<mva:VisualBasicReference>`
   - **3c**: attribute-value VB expressions whose body contains inner brackets — e.g. `Condition="[X.StartsWith(&quot;[&quot;)]"`. The simple bracket walker in (3a) skips these because `\[([^\[\]]+)\]` can't match expressions with internal `[` / `]`. Without this pattern, the declaration was renamed but the reference stayed at the old name, producing UiPath BC30451 "X is not declared".
   - **3d**: element-text VB expressions with inner brackets — e.g. `<InArgument>[String.Format("//*[{0}]", X.Select(...))]</InArgument>`. Same root cause as (3c), but in element text instead of an attribute value.
4. **Attribute-form root references**: `this:Main.oldName="value"` on the Activity root

The lookbehind `(?<![\w.])` on the word regex prevents (a) double-renaming when the simple bracket walker has already done the work and (b) crossing `.` so `credential.Password` stays intact even when an argument `Password` is being renamed.

### Convergence loop — rules cascade until stable

`fix_xaml()` runs up to **5 passes** in a convergence loop. Between passes it re-parses the current XAML and re-invokes the static reviewer (`review_single_file`) to produce a fresh set of findings. This means a chain like `Filtercandidate… (38 chars)` → `str_Filtercandidate… (42 chars, too long)` → `str_FilterCandidateDetailsFromSapTableData (42 chars, PascalCase)` → `str_FilterCandidateTableData (28 chars)` all completes in one `/api/fix` call, because the length violation introduced on pass 1 is detected by the re-review and fixed on pass 2.

Every handler either consults its findings list OR re-scans the current XAML (ST-NMG-008/010/016 use re-scan so they compose correctly regardless of what earlier passes changed). The static reviewer is authoritative for subsequent passes; AI mode does not re-invoke the LLM between passes to avoid burning agent units.

### Determinism

Both modes aim for byte-identical output on the same input across runs:

- **Static**: no `uuid`, `random`, or wall-clock reads in fixers; `ST-DBP-003` generates LogMessage IDs as `LogMessage_AutoFix_001/002/…` (counter-based). `Counter.items()` iterations are explicitly `sorted()` so finding order is stable. Variable-scope tracking uses owner IdRef with a deterministic owner-counter fallback.
- **AI**: LLM called with `temperature=0`, `seed=42`, `response_format=json_object`. Parallel batches collected in **submission order** (not `as_completed`) so batch interleaving is stable. Post-processing sorts all findings by `(file_name, rule_id, activity_path)` before assigning `CR-###` IDs.

Verified: 3 consecutive identical static reviews produce the same finding hash; 3 consecutive fixes produce byte-identical XAML output.

### Rule scoping notes
- **GEN-REL-001 Empty Sequences** only flags standalone user-authored Sequences. Sequences that are direct children of `<ActivityAction>` (catch handler bodies) are marked `is_structural_wrapper` by the parser and skipped — they're covered by ST-DBP-003. Sequences inside `TryCatch.Try` and `TryCatch.Finally` *are* flagged (no other rule covers them). The fixer also handles no-DisplayName empty Sequences (matched by IdRef) — without that fallback, `<Sequence sap2010:WorkflowViewState.IdRef="Sequence_46">` style empty blocks would be flagged but never removed because the matcher required a `DisplayName=` substring.
- **ST-DBP-003 Empty Catch** discovery uses the full `_META_ELEMENTS` set (including XAML primitives like `x:Boolean`, `x:String`) so metadata inside ViewState Dictionaries isn't miscounted as activity content.
- **Variable scope** tracking uses the owning Sequence's `WorkflowViewState.IdRef` (or DisplayName + owner-counter fallback), not just the property-element wrapper name. This gives each Sequence's variables a distinct scope so ST-NMG-005 shadow detection actually fires.
- **Argument defaults** are detected in both element-form (`<this:Main.argName>...</this:Main.argName>`) and attribute-form (`this:Main.argName="..."` on the Activity root). `_rename_in_xaml` also updates attribute-form references when renaming so `this:Main.oldName="value"` becomes `this:Main.newName="value"` and UiPath Studio doesn't error with "The property (oldName) is either invalid or not defined".
- **`_body_is_pascal_case`** uses wordninja to distinguish a single long English word (e.g. `Description`, `Authentication`, `Configuration` — valid PascalCase, no internal boundary) from concatenated soup (`Filtercandidatedetailsfromsaptabledata` — needs splitting). The earlier strict heuristic ("long body without internal uppercase/digit = bad") false-flagged real single words.
- **ST-NMG-020 Default Studio Display Name** excludes statement-like activities whose type IS the meaningful name (`Break`, `Continue`, `Rethrow`, `Throw`, `ActivityFunc`, `ActivityAction`, `Pick`, `PickBranch`, `TerminateWorkflow`). Renaming `Break` to a synthetic descriptor adds noise without information.
- **ST-NMG-004 Display Name Duplication** reviewer's `generic_names` set is aligned with the fixer's `_GENERIC_DISPLAY_NAMES` (Sequence, Flowchart, FlowDecision, FlowStep, **Body, TryCatch, Try, Catch, Finally**) so the reviewer doesn't flag duplicates the fixer would deliberately leave alone as scaffolding.
- **Sibling-scope variable disambiguation** uses a numeric suffix without underscore (`X2`, `X3`) rather than `X_2` so the body remains valid PascalCase (an underscore in the body would re-trigger ST-NMG-010). Scope-bounded rename is anchored on `WorkflowViewState.IdRef` via `_find_owner_text_span`; the open-tag regex uses `(?=[\s/>])` lookahead instead of `\b` to avoid false-positive matches on property elements like `<Sequence.Variables>` (which would corrupt depth-counting because their closes `</Sequence.Variables>` don't match the close regex).

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
