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

import logging
import time
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncSession

import admin
import auth
import limits
import proxy
import referral
from auth import current_user
from db import User, get_db, init_db


logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
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
    try:
        yield
    finally:
        await proxy.close_http()


app = FastAPI(title="Uxie Backend", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Electron renderer runs as file://
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def _timing(request: Request, call_next):
    t0 = time.perf_counter()
    try:
        resp = await call_next(request)
    except Exception:
        dt_ms = (time.perf_counter() - t0) * 1000
        _log.exception("%s %s EXC %.0fms", request.method, request.url.path, dt_ms)
        raise
    dt_ms = (time.perf_counter() - t0) * 1000
    # Health gets a lot of traffic from uptime pings — keep it quiet
    if request.url.path != "/health":
        _log.info("%s %s %d %.0fms", request.method, request.url.path, resp.status_code, dt_ms)
    return resp


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


# ── Admin dashboard ───────────────────────────────────────────────────────────

app.add_api_route("/admin/dashboard",    admin.dashboard_html, methods=["GET"], response_class=__import__("fastapi").responses.HTMLResponse)
app.add_api_route("/admin/stats.json",   admin.stats_json,     methods=["GET"])
app.add_api_route("/admin/users.json",   admin.users_json,     methods=["GET"])
app.add_api_route("/admin/user/{user_id}.json", admin.user_detail_json, methods=["GET"])


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
        # Cutover probe: set to the current org so we can see Railway redeploy
        # after the github.com/Ronda1723 -> github.com/uxie-app transfer.
        "source": "uxie-app",
    }

    status_code = 200 if db_ok else 503
    return fastapi.responses.JSONResponse(content=payload, status_code=status_code)
