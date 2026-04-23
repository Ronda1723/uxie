"""
Uxie Backend — FastAPI entry point.

Endpoints:
  POST /auth/send-otp
  POST /auth/verify-otp
  POST /llm/stream
  POST /llm/chat
  POST /stt/session
  POST /referral/redeem
  GET  /referral/stats
  GET  /user/status
  GET  /health
"""

from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

import auth
import limits
import proxy
import referral
from auth import current_user
from db import User, get_db, init_db


import logging
_log = logging.getLogger("main")

@asynccontextmanager
async def lifespan(app: FastAPI):
    try:
        await init_db()
        _log.info("Database ready")
    except Exception as e:
        _log.critical(
            f"Database connection failed: {e}\n"
            "ACTION REQUIRED: Add a PostgreSQL service in Railway and ensure "
            "DATABASE_URL is set in this service's environment variables."
        )
        raise
    yield


app = FastAPI(title="Uxie Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron renderer runs as file://
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── Auth ──────────────────────────────────────────────────────────────────────

app.add_api_route("/auth/send-otp", auth.send_otp, methods=["POST"])
app.add_api_route("/auth/verify-otp", auth.verify_otp, methods=["POST"])


# ── LLM + STT proxy ───────────────────────────────────────────────────────────

app.add_api_route("/llm/stream", proxy.llm_stream, methods=["POST"])
app.add_api_route("/llm/chat",   proxy.llm_chat,   methods=["POST"])
app.add_api_route("/stt/session", proxy.stt_session, methods=["POST"])


# ── Referral ──────────────────────────────────────────────────────────────────

app.add_api_route("/referral/redeem", referral.redeem_referral, methods=["POST"])
app.add_api_route("/referral/stats", referral.get_referral_stats, methods=["GET"])


# ── User status ───────────────────────────────────────────────────────────────

@app.get("/user/status")
async def user_status(
    db: AsyncSession = Depends(get_db),
    user: User = Depends(current_user),
):
    usage = await limits.get_usage_summary(db, user)
    return {
        "user_id": user.id,
        "email": user.email,
        **usage,
        "referral_code": user.referral_code,
        "referral_link": f"https://uxie.ai/r/{user.referral_code}",
    }


# ── Health ────────────────────────────────────────────────────────────────────

@app.get("/health")
async def health(db: AsyncSession = Depends(get_db)):
    from sqlalchemy import text
    from settings import get_settings
    from fastapi import Response
    import fastapi

    s = get_settings()
    dg = (s.deepgram_api_key or "").strip()

    # Probe DB with a lightweight query
    db_ok = False
    try:
        await db.execute(text("SELECT 1"))
        db_ok = True
    except Exception:
        pass

    payload = {
        "status": "ok" if db_ok else "degraded",
        "db": "ok" if db_ok else "unreachable — add PostgreSQL in Railway",
        "deepgram": "ok" if dg else "NOT SET — add DEEPGRAM_API_KEY in Railway",
        "deepgram_key_prefix": (dg[:8] + "...") if dg else None,
        "groq": "ok" if s.groq_api_key else "NOT SET",
        "openai": "ok" if s.openai_api_key else "NOT SET",
    }

    status_code = 200 if db_ok else 503
    return fastapi.responses.JSONResponse(content=payload, status_code=status_code)
