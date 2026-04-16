import os
import sys
import asyncio
import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv

load_dotenv(override=True)  # Must be called before importing uipath_langchain

from fastapi import FastAPI, UploadFile, File, Form, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

# Add backend directory to path so models/services can be imported
sys.path.insert(0, os.path.dirname(__file__))

from models.schemas import ReviewResponse, Finding
from services.zip_extractor import extract_xaml_from_zip
from services.xaml_parser import parse_xaml_file
from services.llm_reviewer import (
    review_with_llm,
    ALL_MODELS,
    DEFAULT_MODEL,
)
from services.token_refresh import token_refresh_loop, refresh_once, _seconds_until_expiry, _read_auth_json
from services.xaml_fixer import fix_xaml

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("main")

_refresh_task: asyncio.Task | None = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Start the background token refresh on startup, cancel on shutdown."""
    global _refresh_task
    logger.info("Starting background token auto-refresh service")
    _refresh_task = asyncio.create_task(token_refresh_loop())
    yield
    if _refresh_task:
        _refresh_task.cancel()
        try:
            await _refresh_task
        except asyncio.CancelledError:
            pass
        logger.info("Token auto-refresh service stopped")


app = FastAPI(title="UiPath XAML Code Review", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ──────────────────────────────────────────────────────────────
# Model catalog — returned by GET /api/models
# ──────────────────────────────────────────────────────────────
MODEL_CATALOG = [
    {
        "id": "gpt-4o-2024-08-06",
        "label": "GPT-4o (2024-08-06)",
        "provider": "OpenAI",
        "class": "UiPathAzureChatOpenAI",
        "recommended": False,
    },
    {
        "id": "gpt-4o-mini-2024-07-18",
        "label": "GPT-4o Mini",
        "provider": "OpenAI",
        "class": "UiPathAzureChatOpenAI",
        "recommended": False,
    },
    {
        "id": "gpt-4.1-mini-2025-04-14",
        "label": "GPT-4.1 Mini",
        "provider": "OpenAI",
        "class": "UiPathAzureChatOpenAI",
        "recommended": False,
    },
    {
        "id": "o3-mini-2025-01-31",
        "label": "o3 Mini",
        "provider": "OpenAI",
        "class": "UiPathAzureChatOpenAI",
        "recommended": False,
    },
    {
        "id": "anthropic.claude-3-7-sonnet-20250219-v1:0",
        "label": "Claude 3.7 Sonnet",
        "provider": "Anthropic",
        "class": "UiPathChat",
        "recommended": True,
    },
    {
        "id": "anthropic.claude-3-5-sonnet-20241022-v2:0",
        "label": "Claude 3.5 Sonnet v2",
        "provider": "Anthropic",
        "class": "UiPathChat",
        "recommended": False,
    },
    {
        "id": "anthropic.claude-3-5-sonnet-20240620-v1:0",
        "label": "Claude 3.5 Sonnet",
        "provider": "Anthropic",
        "class": "UiPathChat",
        "recommended": False,
    },
    {
        "id": "anthropic.claude-3-haiku-20240307-v1:0",
        "label": "Claude 3 Haiku",
        "provider": "Anthropic",
        "class": "UiPathChat",
        "recommended": False,
    },
    {
        "id": "gemini-2.0-flash-001",
        "label": "Gemini 2.0 Flash",
        "provider": "Google",
        "class": "UiPathChat",
        "recommended": False,
    },
    {
        "id": "gemini-1.5-pro-001",
        "label": "Gemini 1.5 Pro",
        "provider": "Google",
        "class": "UiPathChat",
        "recommended": False,
    },
]


@app.get("/api/health")
async def health():
    try:
        auth_data = _read_auth_json()
        token = auth_data.get("access_token", "")
        remaining = _seconds_until_expiry(token)
        token_status = {
            "valid": remaining > 0,
            "expires_in_minutes": round(remaining / 60, 1) if remaining > 0 else 0,
            "auto_refresh": _refresh_task is not None and not _refresh_task.done(),
        }
    except Exception:
        token_status = {"valid": False, "expires_in_minutes": 0, "auto_refresh": False}

    return {
        "status": "ok",
        "uipath_url": os.getenv("UIPATH_URL", "not configured"),
        "token": token_status,
    }


@app.post("/api/refresh-token")
async def manual_refresh():
    """Manually trigger a token refresh."""
    success = await refresh_once()
    if success:
        auth_data = _read_auth_json()
        remaining = _seconds_until_expiry(auth_data.get("access_token", ""))
        return {
            "status": "refreshed",
            "expires_in_minutes": round(remaining / 60, 1),
        }
    raise HTTPException(
        status_code=502,
        detail="Token refresh failed. Check server logs or run 'uipath auth' manually.",
    )


@app.get("/api/models")
async def get_models():
    return {
        "default": DEFAULT_MODEL,
        "models": MODEL_CATALOG,
    }


# ──────────────────────────────────────────────────────────────
# Background job store for long-running reviews
# ──────────────────────────────────────────────────────────────
_review_jobs: dict[str, dict] = {}


async def _run_review_job(
    job_id: str,
    contexts: list,
    project_name: str,
    model_id: str,
    upload_mode: str,
    zip_file_name: str | None,
    skipped_files: list[str],
):
    """Run the LLM review in background and store result in _review_jobs."""
    logger.info("Job %s: starting review for '%s' (%d files)", job_id[:8], project_name, len(contexts))
    try:
        findings = await asyncio.to_thread(
            review_with_llm, contexts, project_name, model_id
        )
        logger.info("Job %s: completed with %d findings", job_id[:8], len(findings))
        _review_jobs[job_id]["result"] = ReviewResponse(
            project_name=project_name,
            upload_mode=upload_mode,
            zip_file_name=zip_file_name,
            reviewed_at=datetime.now(timezone.utc).isoformat(),
            total_files=len(contexts),
            skipped_files=skipped_files,
            model_id=model_id,
            findings=findings,
        )
        _review_jobs[job_id]["status"] = "completed"
    except Exception as e:
        import traceback
        logger.error("Job %s: FAILED — %s\n%s", job_id[:8], e, traceback.format_exc())
        _review_jobs[job_id]["status"] = "failed"
        _review_jobs[job_id]["error"] = str(e)


@app.post("/api/review")
async def review(
    project_name: str = Form(...),
    model_id: str = Form(DEFAULT_MODEL),
    files: list[UploadFile] = File(...),
):
    # Reload .env to pick up refreshed tokens
    load_dotenv(override=True)

    # Validate model_id
    if model_id not in ALL_MODELS:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Unknown model_id '{model_id}'. "
                "Call GET /api/models for the supported list."
            ),
        )

    # Determine upload mode
    is_zip = len(files) == 1 and (
        files[0].filename or ""
    ).lower().endswith(".zip")

    skipped_files: list[str] = []
    xaml_contents: list[dict] = []
    zip_file_name: str | None = None

    if is_zip:
        upload_mode = "zip"
        zip_file_name = files[0].filename or "upload.zip"
        zip_bytes = await files[0].read()

        try:
            result = extract_xaml_from_zip(zip_bytes, zip_file_name)
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

        xaml_contents = result["files"]
        skipped_files = result["skipped_files"]
    else:
        upload_mode = "individual"
        for f in files:
            fname = f.filename or "unknown.xaml"
            if not fname.lower().endswith(".xaml"):
                skipped_files.append(fname)
                continue
            content = (await f.read()).decode("utf-8", errors="replace")
            xaml_contents.append(
                {
                    "file_name": fname,
                    "zip_entry_path": "",
                    "content": content,
                }
            )

    if not xaml_contents:
        raise HTTPException(
            status_code=400,
            detail="No .xaml files found in the upload.",
        )

    # Parse XAML files
    contexts = []
    for item in xaml_contents:
        try:
            ctx = parse_xaml_file(
                item["file_name"], item["zip_entry_path"], item["content"]
            )
            contexts.append(ctx)
        except Exception as e:
            raise HTTPException(
                status_code=422,
                detail=f"Failed to parse '{item['file_name']}': {e}",
            )

    # Start background job
    job_id = str(uuid.uuid4())
    _review_jobs[job_id] = {
        "status": "running",
        "total_files": len(contexts),
        "result": None,
        "error": None,
    }

    asyncio.create_task(
        _run_review_job(
            job_id, contexts, project_name, model_id,
            upload_mode, zip_file_name, skipped_files,
        )
    )

    return {"job_id": job_id, "status": "running", "total_files": len(contexts)}


@app.get("/api/review/{job_id}")
async def get_review_status(job_id: str):
    """Poll for review job status and results."""
    job = _review_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job not found")

    if job["status"] == "running":
        return {"job_id": job_id, "status": "running"}

    if job["status"] == "failed":
        detail = job["error"] or "Unknown error"
        # Clean up
        del _review_jobs[job_id]
        raise HTTPException(status_code=502, detail=f"LLM review failed: {detail}")

    # completed
    result = job["result"]
    # Clean up
    del _review_jobs[job_id]
    return result


@app.post("/api/fix")
async def apply_fixes(
    project_name: str = Form(...),
    findings_json: str = Form(...),
    files: list[UploadFile] = File(...),
):
    """
    Apply auto-fixes to uploaded XAML files based on review findings.
    Saves originals to output/{project_name}/original/.
    Returns per-file original vs modified content with change lists.
    """
    import json as json_mod

    # Parse findings
    try:
        raw_findings = json_mod.loads(findings_json)
        parsed_findings = [Finding(**f) for f in raw_findings]
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid findings JSON: {e}")

    # Determine upload mode & extract XAML content
    is_zip = len(files) == 1 and (files[0].filename or "").lower().endswith(".zip")
    xaml_contents: list[dict] = []
    project_json: str | None = None

    if is_zip:
        zip_bytes = await files[0].read()
        try:
            result = extract_xaml_from_zip(zip_bytes, files[0].filename or "upload.zip")
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))
        xaml_contents = result["files"]
        project_json = result.get("project_json")
    else:
        for f in files:
            fname = f.filename or "unknown.xaml"
            if not fname.lower().endswith(".xaml"):
                continue
            content = (await f.read()).decode("utf-8", errors="replace")
            xaml_contents.append({
                "file_name": fname,
                "zip_entry_path": "",
                "content": content,
            })

    if not xaml_contents:
        raise HTTPException(status_code=400, detail="No .xaml files found.")

    # Save originals
    base_dir = os.path.join(os.path.dirname(__file__), "output", project_name)
    orig_dir = os.path.join(base_dir, "original")
    os.makedirs(orig_dir, exist_ok=True)

    for item in xaml_contents:
        orig_path = os.path.join(orig_dir, item["file_name"])
        with open(orig_path, "w", encoding="utf-8") as fp:
            fp.write(item["content"])

    # Save project.json to original folder if present
    if project_json:
        pj_path = os.path.join(orig_dir, "project.json")
        with open(pj_path, "w", encoding="utf-8") as fp:
            fp.write(project_json)

    # Apply fixes per file
    fix_results = []
    for item in xaml_contents:
        file_findings = [
            f for f in parsed_findings
            if f.file_name == item["file_name"]
        ]
        if not file_findings:
            fix_results.append({
                "file_name": item["file_name"],
                "original_content": item["content"],
                "modified_content": item["content"],
                "changes": [],
            })
            continue

        result = fix_xaml(item["content"], file_findings)
        fix_results.append({
            "file_name": item["file_name"],
            "original_content": result["original_content"],
            "modified_content": result["modified_content"],
            "changes": result["changes_applied"],
        })

    return {"project_name": project_name, "files": fix_results, "project_json": project_json}


@app.post("/api/fix/accept")
async def accept_fixes(request: Request):
    """
    Save accepted modified XAML files to output/{project_name}/modified/.
    Accepts JSON body (no size limit) instead of Form data.
    """
    body = await request.json()
    project_name = body.get("project_name", "")
    file_list = body.get("files", [])
    project_json = body.get("project_json")
    output_dir = body.get("output_dir", "")

    if not project_name:
        raise HTTPException(status_code=400, detail="project_name is required")

    if output_dir:
        base_dir = os.path.join(output_dir, project_name)
    else:
        base_dir = os.path.join(os.path.dirname(__file__), "output", project_name)
    mod_dir = os.path.join(base_dir, "modified")
    os.makedirs(mod_dir, exist_ok=True)

    saved = 0
    for item in file_list:
        file_name = item.get("file_name", "")
        modified_content = item.get("modified_content", "")
        if not file_name:
            continue
        out_path = os.path.join(mod_dir, file_name)
        with open(out_path, "w", encoding="utf-8") as fp:
            fp.write(modified_content)
        saved += 1

    # Save project.json to modified folder if present
    if project_json:
        pj_path = os.path.join(mod_dir, "project.json")
        with open(pj_path, "w", encoding="utf-8") as fp:
            fp.write(project_json)

    return {
        "saved_path": os.path.abspath(mod_dir),
        "file_count": saved,
    }
