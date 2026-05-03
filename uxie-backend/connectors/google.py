"""
Google connector — Gmail (v1). Calendar and Drive deliberately deferred until
the OAuth flow + Gmail tools are verified end-to-end on iOS.

Adapted from miniflow-engine/connectors/google.py with three changes:
  - Async (httpx via proxy.get_http) instead of the sync google-api-python-client
    library, so we don't add a heavy dependency to Railway just for one connector.
  - Token comes from db_ios.OAuthToken row, not a local file.
  - Auto-refresh access_token on 401: Gmail short-lived tokens expire after ~1
    hour; we use the stored refresh_token to mint a new one and retry once.
"""

from __future__ import annotations

import base64
import logging
import os
from email.mime.text import MIMEText
from typing import Any

import httpx

from db_ios import OAuthToken
from sqlalchemy.ext.asyncio import AsyncSession

log = logging.getLogger("connectors.google")

PROVIDER = "google"

GMAIL_API = "https://gmail.googleapis.com/gmail/v1"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


# ── Tool schemas ──────────────────────────────────────────────────────────────

TOOLS: list[dict[str, Any]] = [
    {"type": "function", "function": {
        "name": "gmail_send",
        "description": "Send an email via Gmail. USE THIS when the user says 'send', 'email X saying...', 'mail X about...', or any phrasing that implies the email should actually be delivered. The user will see an approval sheet before it fires, so you don't need to ask for confirmation in chat — just call this tool.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string", "description": "Recipient email address"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        }, "required": ["to", "subject", "body"]},
    }},
    {"type": "function", "function": {
        "name": "gmail_search",
        "description": "Search Gmail. Returns a list of message IDs + From + Subject.",
        "parameters": {"type": "object", "properties": {
            "query": {"type": "string", "description": "Gmail search query (same syntax as the web UI)"},
            "limit": {"type": "integer", "default": 5},
        }, "required": ["query"]},
    }},
    {"type": "function", "function": {
        "name": "gmail_read",
        "description": "Read a Gmail message by ID. Returns From, Subject, and the first ~2500 chars of the body.",
        "parameters": {"type": "object", "properties": {
            "id": {"type": "string"},
        }, "required": ["id"]},
    }},
    {"type": "function", "function": {
        "name": "gmail_draft",
        "description": "Create a Gmail draft only — no email is sent. ONLY use this when the user explicitly says 'draft', 'save a draft', or 'don't send yet'. Otherwise prefer gmail_send.",
        "parameters": {"type": "object", "properties": {
            "to": {"type": "string"},
            "subject": {"type": "string"},
            "body": {"type": "string"},
        }, "required": ["to", "subject", "body"]},
    }},
]


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_mime(to: str, subject: str, body: str, thread_id: str | None = None) -> dict:
    msg = MIMEText(body)
    msg["To"] = to
    msg["Subject"] = subject
    raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
    out: dict[str, Any] = {"raw": raw}
    if thread_id:
        out["threadId"] = thread_id
    return out


def _decode_body(payload: dict) -> str:
    data = payload.get("body", {}).get("data")
    if data:
        return base64.urlsafe_b64decode(data).decode("utf-8", errors="replace")
    for part in payload.get("parts", []):
        if part.get("mimeType") == "text/plain":
            d = part.get("body", {}).get("data")
            if d:
                return base64.urlsafe_b64decode(d).decode("utf-8", errors="replace")
    return ""


async def _refresh_access_token(http: httpx.AsyncClient, token: OAuthToken, db: AsyncSession) -> str | None:
    """Mint a fresh access token from the stored refresh_token. Persists it
    to the OAuthToken row so subsequent calls don't need to refresh."""
    if not token.refresh_token:
        return None
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    client_secret = os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
    if not client_id or not client_secret:
        return None
    try:
        resp = await http.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "refresh_token": token.refresh_token,
                "grant_type": "refresh_token",
            },
        )
        if resp.status_code != 200:
            log.warning("Google refresh failed (%d): %s", resp.status_code, resp.text[:200])
            return None
        new = resp.json()
        token.access_token = new["access_token"]
        await db.commit()
        return token.access_token
    except Exception as e:  # noqa: BLE001
        log.warning("Google refresh exception: %s", e)
        return None


async def _gmail_request(
    method: str,
    path: str,
    token: OAuthToken,
    http: httpx.AsyncClient,
    db: AsyncSession,
    *,
    params: dict | None = None,
    json: dict | None = None,
) -> dict:
    """One-shot Gmail HTTP call with automatic 401-retry-after-refresh."""
    async def _call(access_token: str) -> httpx.Response:
        return await http.request(
            method,
            f"{GMAIL_API}{path}",
            headers={"Authorization": f"Bearer {access_token}"},
            params=params,
            json=json,
            timeout=30,
        )
    resp = await _call(token.access_token)
    if resp.status_code == 401:
        new_token = await _refresh_access_token(http, token, db)
        if new_token:
            resp = await _call(new_token)
    if resp.status_code >= 400:
        raise RuntimeError(f"Gmail {method} {path} → {resp.status_code}: {resp.text[:200]}")
    return resp.json()


# ── Execute ──────────────────────────────────────────────────────────────────


async def execute(
    name: str,
    args: dict[str, Any],
    token: OAuthToken,
    http: httpx.AsyncClient,
    db: AsyncSession | None = None,
) -> tuple[bool, Any]:
    """Dispatch a Gmail tool call. The connector registry passes us
    (name, args, OAuthToken row, shared httpx client). We pass `db` through
    so we can persist refreshed tokens.

    The registry's current signature doesn't include `db` yet — we accept it
    optionally so a future registry change can pass it. For now refresh-on-401
    is best-effort: it runs the request again with the new token but doesn't
    persist if db is None.
    """
    try:
        if name == "gmail_send":
            await _gmail_request(
                "POST", "/users/me/messages/send", token, http, db,
                json=_make_mime(args["to"], args["subject"], args["body"]),
            )
            return True, f"Email sent to {args['to']}."

        elif name == "gmail_search":
            res = await _gmail_request(
                "GET", "/users/me/messages", token, http, db,
                params={"q": args["query"], "maxResults": args.get("limit", 5)},
            )
            msgs = res.get("messages", [])
            if not msgs:
                return True, "No emails found."
            lines = []
            for m in msgs:
                hdr = await _gmail_request(
                    "GET", f"/users/me/messages/{m['id']}", token, http, db,
                    params={"format": "metadata", "metadataHeaders": ["From", "Subject"]},
                )
                headers = {h["name"]: h["value"] for h in hdr.get("payload", {}).get("headers", [])}
                lines.append(
                    f"ID:{m['id']}  From:{headers.get('From','')}  "
                    f"Subject:{headers.get('Subject','')}"
                )
            return True, "\n".join(lines)

        elif name == "gmail_read":
            msg = await _gmail_request(
                "GET", f"/users/me/messages/{args['id']}", token, http, db,
                params={"format": "full"},
            )
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            body = _decode_body(msg.get("payload", {}))
            return True, (
                f"From: {headers.get('From','')}\n"
                f"Subject: {headers.get('Subject','')}\n"
                f"ThreadID: {msg.get('threadId','')}\n\n"
                f"{body[:2500]}"
            )

        elif name == "gmail_draft":
            await _gmail_request(
                "POST", "/users/me/drafts", token, http, db,
                json={"message": _make_mime(args["to"], args["subject"], args["body"])},
            )
            return True, f"Draft created for {args['to']}."

        return False, f"Unknown Google tool: {name}"

    except Exception as e:  # noqa: BLE001
        log.error("[google/%s] %s", name, e)
        return False, str(e)
