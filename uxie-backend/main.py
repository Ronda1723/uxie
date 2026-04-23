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


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
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
async def health():
    return {"status": "ok"}
