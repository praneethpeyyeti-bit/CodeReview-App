import json
import logging
import os

logger = logging.getLogger("llm_reviewer")

from dotenv import load_dotenv

load_dotenv(override=True)

from langchain_core.messages import SystemMessage, HumanMessage

from models.schemas import ReviewContext, Finding
from prompts.code_review_prompt import SYSTEM_PROMPT, build_user_message

# Lazy imports — only import UiPath classes when actually needed,
# so the module can be loaded even without uipath_langchain installed.
_UiPathAzureChatOpenAI = None
_UiPathChat = None


def _ensure_imports():
    global _UiPathAzureChatOpenAI, _UiPathChat
    if _UiPathAzureChatOpenAI is None:
        from uipath_langchain.chat.models import (
            UiPathAzureChatOpenAI,
            UiPathChat,
        )
        _UiPathAzureChatOpenAI = UiPathAzureChatOpenAI
        _UiPathChat = UiPathChat


# Models served by UiPathAzureChatOpenAI
AZURE_OPENAI_MODELS = {
    "gpt-4o-2024-08-06",
    "gpt-4o-2024-05-13",
    "gpt-4o-mini-2024-07-18",
    "gpt-4.1-mini-2025-04-14",
    "o3-mini-2025-01-31",
}

# Models served by UiPathChat (multi-vendor)
UIPATH_CHAT_MODELS = {
    "anthropic.claude-3-7-sonnet-20250219-v1:0",
    "anthropic.claude-3-5-sonnet-20241022-v2:0",
    "anthropic.claude-3-5-sonnet-20240620-v1:0",
    "anthropic.claude-3-haiku-20240307-v1:0",
    "gemini-2.0-flash-001",
    "gemini-1.5-pro-001",
    "gpt-4o-2024-08-06",
    "gpt-4o-mini-2024-07-18",
    "o3-mini-2025-01-31",
}

ALL_MODELS = AZURE_OPENAI_MODELS | UIPATH_CHAT_MODELS
DEFAULT_MODEL = "anthropic.claude-3-7-sonnet-20250219-v1:0"


def _create_llm(model_id: str):
    """Return the correct UiPath LangChain chat model for the given model_id."""
    # Re-read .env every time so token refreshes are picked up
    load_dotenv(override=True)
    _ensure_imports()

    params = dict(
        model=model_id,
        temperature=0,
        max_tokens=8000,
        timeout=300,
        max_retries=2,
        seed=42,
        model_kwargs={"response_format": {"type": "json_object"}},
    )

    if model_id in AZURE_OPENAI_MODELS:
        return _UiPathAzureChatOpenAI(**params)

    if model_id in UIPATH_CHAT_MODELS:
        return _UiPathChat(**params, agenthub_config="agentsplayground")

    raise ValueError(
        f"Unknown model '{model_id}'. "
        f"Supported: {sorted(ALL_MODELS)}"
    )


def review_with_llm(
    contexts: list[ReviewContext],
    project_name: str,
    model_id: str = DEFAULT_MODEL,
) -> list[Finding]:
    llm = _create_llm(model_id)

    # Token budget: ~200k model limit minus ~15k for system prompt and output
    # Rough estimate: 1 char ≈ 0.3 tokens for structured JSON
    MAX_BATCH_CHARS = 80_000  # ~24k tokens per batch, safe margin

    def _build_batches() -> list[list[ReviewContext]]:
        batches = []
        current_batch: list[ReviewContext] = []
        current_chars = 0
        for ctx in contexts:
            ctx_chars = len(json.dumps(ctx.model_dump()))
            if current_batch and current_chars + ctx_chars > MAX_BATCH_CHARS:
                batches.append(current_batch)
                current_batch = []
                current_chars = 0
            current_batch.append(ctx)
            current_chars += ctx_chars
        if current_batch:
            batches.append(current_batch)
        return batches

    batches = _build_batches()
    logger.info(
        "Review '%s': %d file(s) split into %d batch(es) — sizes: %s",
        project_name, len(contexts), len(batches),
        [len(b) for b in batches],
    )

    def _review_batch(batch_idx: int, batch: list[ReviewContext]) -> list[Finding]:
        logger.info("Processing batch %d/%d (%d files)...", batch_idx, len(batches), len(batch))
        batch_llm = _create_llm(model_id)
        messages = [
            SystemMessage(content=SYSTEM_PROMPT),
            HumanMessage(content=build_user_message(batch, project_name)),
        ]
        try:
            response = batch_llm.invoke(messages)
        except OSError as e:
            # [Errno 22] Invalid argument — common on Windows when the
            # token is expired/invalid and the SSL handshake fails, or
            # when the HTTP connection is reset.
            import traceback
            logger.error("OSError during LLM call: %s\n%s", e, traceback.format_exc())
            raise RuntimeError(
                f"Network/OS error during LLM call: {e}. "
                "This often means the authentication token has expired. "
                "Try refreshing the token (click the refresh button or run 'uipath auth'), "
                "then retry the review."
            ) from e
        except Exception as e:
            error_msg = str(e)
            if "401" in error_msg or "Unauthorized" in error_msg:
                raise RuntimeError(
                    "UiPath authentication expired. "
                    "Run 'uipath auth' in the backend directory to refresh the token, "
                    "then restart the server."
                ) from e
            if "417" in error_msg or "routing rule" in error_msg.lower():
                raise RuntimeError(
                    f"Model '{model_id}' is not available in your tenant region. "
                    "Try selecting a different model."
                ) from e
            raise

        raw_json = response.content
        if not raw_json or not raw_json.strip():
            raise RuntimeError(
                "LLM returned an empty response. The token may have expired. "
                "Run 'uipath auth' to refresh, then restart the server."
            )

        # Strip markdown fences if the LLM wraps the JSON
        cleaned = raw_json.strip()
        if cleaned.startswith("```"):
            lines = cleaned.split("\n")
            lines = [l for l in lines if not l.strip().startswith("```")]
            cleaned = "\n".join(lines)

        try:
            parsed = json.loads(cleaned)
        except json.JSONDecodeError:
            retry_messages = messages + [
                response,
                HumanMessage(
                    content=(
                        "Your previous response was not valid JSON. "
                        "Return ONLY a valid JSON object with a 'findings' "
                        "key and nothing else."
                    )
                ),
            ]
            response = batch_llm.invoke(retry_messages)
            cleaned = response.content.strip()
            if cleaned.startswith("```"):
                lines = cleaned.split("\n")
                lines = [l for l in lines if not l.strip().startswith("```")]
                cleaned = "\n".join(lines)
            parsed = json.loads(cleaned)

        batch_findings = []
        for item in parsed.get("findings", []):
            batch_findings.append(
                Finding(**item, status="Open", reviewer_notes="")
            )
        logger.info("Batch %d/%d complete — %d findings", batch_idx, len(batches), len(batch_findings))
        return batch_findings

    # Run batches in parallel (up to 3 concurrent)
    from concurrent.futures import ThreadPoolExecutor, as_completed

    all_findings: list[Finding] = []
    max_workers = min(3, len(batches))

    if len(batches) == 1:
        all_findings = _review_batch(1, batches[0])
    else:
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = {
                executor.submit(_review_batch, idx, batch): idx
                for idx, batch in enumerate(batches, 1)
            }
            for future in as_completed(futures):
                all_findings.extend(future.result())

    # Assign sequential IDs across all batches
    for i, finding in enumerate(all_findings, start=1):
        finding.id = f"CR-{i:03d}"

    return all_findings
