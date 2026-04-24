"""
Background service that automatically refreshes the UiPath access token
using the OAuth2 refresh_token grant before it expires.

Reads from .uipath/.auth.json, refreshes via the identity endpoint,
and writes the new tokens back to both .auth.json and .env.
"""

import asyncio
import json
import os
import time
import base64
import logging
import httpx

logger = logging.getLogger("token_refresh")

AUTH_JSON_PATH = os.path.join(os.path.dirname(__file__), "..", ".uipath", ".auth.json")
ENV_PATH = os.path.join(os.path.dirname(__file__), "..", ".env")
CLIENT_ID = "36dea5b8-e8bb-423d-8e7b-c808df8f1c00"

# Refresh 10 minutes before expiry to give a comfortable buffer
REFRESH_BUFFER_SECONDS = 600


def _get_identity_url() -> str:
    """Derive the identity token endpoint from the current access token's issuer."""
    try:
        auth_data = _read_auth_json()
        token = auth_data.get("access_token", "")
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        issuer = claims.get("iss", "")
        # issuer looks like "https://staging.uipath.com/identity_"
        # token endpoint is at "{issuer}/connect/token" but with identity_ → identity_
        base = issuer.rstrip("/")
        return f"{base}/connect/token"
    except Exception:
        # Fallback to staging
        uipath_url = os.getenv("UIPATH_URL", "")
        if "staging" in uipath_url:
            return "https://staging.uipath.com/identity_/connect/token"
        return "https://cloud.uipath.com/identity_/connect/token"


def _read_auth_json() -> dict:
    with open(AUTH_JSON_PATH, "r") as f:
        return json.load(f)


def _write_auth_json(data: dict) -> None:
    with open(AUTH_JSON_PATH, "w") as f:
        json.dump(data, f)


def _update_env_token(new_token: str) -> None:
    """Update the UIPATH_ACCESS_TOKEN in the .env file."""
    lines = []
    token_found = False

    if os.path.exists(ENV_PATH):
        with open(ENV_PATH, "r") as f:
            for line in f:
                if line.startswith("UIPATH_ACCESS_TOKEN="):
                    lines.append(f"UIPATH_ACCESS_TOKEN={new_token}\n")
                    token_found = True
                else:
                    lines.append(line)

    if not token_found:
        lines.append(f"UIPATH_ACCESS_TOKEN={new_token}\n")

    with open(ENV_PATH, "w") as f:
        f.writelines(lines)

    # Also update the current process environment
    os.environ["UIPATH_ACCESS_TOKEN"] = new_token


def _get_token_expiry(token: str) -> float:
    """Extract the 'exp' claim from a JWT and return it as a Unix timestamp."""
    try:
        payload = token.split(".")[1]
        payload += "=" * (4 - len(payload) % 4)
        claims = json.loads(base64.urlsafe_b64decode(payload))
        return float(claims.get("exp", 0))
    except Exception:
        return 0


def _seconds_until_expiry(token: str) -> float:
    exp = _get_token_expiry(token)
    if exp == 0:
        return 0
    return exp - time.time()


async def _do_refresh(refresh_token: str) -> dict:
    """Perform the OAuth2 refresh_token grant and return the new token data."""
    token_url = _get_identity_url()
    logger.info("Refreshing token via %s", token_url)

    async with httpx.AsyncClient(timeout=30) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "refresh_token",
                "client_id": CLIENT_ID,
                "refresh_token": refresh_token,
            },
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        resp.raise_for_status()
        return resp.json()


async def refresh_once() -> bool:
    """Attempt a single token refresh. Returns True on success."""
    try:
        auth_data = _read_auth_json()
        refresh_token = auth_data.get("refresh_token")
        if not refresh_token:
            logger.warning("No refresh_token found in .auth.json — cannot auto-refresh")
            return False

        new_data = await _do_refresh(refresh_token)

        new_access_token = new_data.get("access_token", "")
        new_refresh_token = new_data.get("refresh_token", refresh_token)

        if not new_access_token:
            logger.error("Refresh response missing access_token")
            return False

        # Update .auth.json
        auth_data["access_token"] = new_access_token
        auth_data["refresh_token"] = new_refresh_token
        auth_data["expires_in"] = new_data.get("expires_in", 3600)
        if "scope" in new_data:
            auth_data["scope"] = new_data["scope"]
        _write_auth_json(auth_data)

        # Update .env and process env
        _update_env_token(new_access_token)

        ttl = _seconds_until_expiry(new_access_token)
        logger.info(
            "Token refreshed successfully — new token expires in %.0f minutes",
            ttl / 60,
        )
        return True

    except httpx.HTTPStatusError as e:
        logger.error(
            "Token refresh HTTP error %s: %s",
            e.response.status_code,
            e.response.text[:500],
        )
        return False
    except Exception as e:
        logger.error("Token refresh failed: %s", e)
        return False


async def token_refresh_loop():
    """
    Background loop that monitors token expiry and refreshes proactively.

    Runs forever — designed to be started as an asyncio task during app startup.
    """
    logger.info("Token auto-refresh background service started")

    while True:
        try:
            auth_data = _read_auth_json()
            access_token = auth_data.get("access_token", "")
            remaining = _seconds_until_expiry(access_token)

            if remaining <= 0:
                # Token already expired — refresh immediately
                logger.warning("Token already expired — refreshing now")
                success = await refresh_once()
                if not success:
                    # Wait a bit before retrying
                    await asyncio.sleep(60)
                    continue
            elif remaining <= REFRESH_BUFFER_SECONDS:
                # Token expiring soon — refresh now
                logger.info(
                    "Token expires in %.0f seconds (< %d buffer) — refreshing",
                    remaining,
                    REFRESH_BUFFER_SECONDS,
                )
                success = await refresh_once()
                if not success:
                    await asyncio.sleep(60)
                    continue
            else:
                # Token is still valid — sleep until REFRESH_BUFFER_SECONDS before expiry
                sleep_for = remaining - REFRESH_BUFFER_SECONDS
                logger.info(
                    "Token valid for %.0f more minutes — next refresh in %.0f minutes",
                    remaining / 60,
                    sleep_for / 60,
                )
                await asyncio.sleep(sleep_for)
                continue

            # After a successful refresh, re-check how long the new token is valid
            auth_data = _read_auth_json()
            access_token = auth_data.get("access_token", "")
            remaining = _seconds_until_expiry(access_token)
            sleep_for = max(remaining - REFRESH_BUFFER_SECONDS, 60)
            logger.info("Next refresh in %.0f minutes", sleep_for / 60)
            await asyncio.sleep(sleep_for)

        except Exception as e:
            logger.error("Unexpected error in refresh loop: %s", e)
            await asyncio.sleep(120)
