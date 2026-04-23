"""
Usage telemetry — records per-user LLM and STT events for the admin dashboard.

Cost estimates are rough constants here (updated as of early 2026); swap with
provider-reported numbers when we wire the real billing APIs.

All recording functions are fire-and-forget from the request path's perspective
— callers pass an AsyncSession but failures are swallowed into a log line so
analytics never take a user-facing request down.
"""

from __future__ import annotations

import logging
import time
from contextlib import asynccontextmanager

from sqlalchemy.ext.asyncio import AsyncSession

from db import LLMUsage, STTUsage

_log = logging.getLogger("usage")


# Rough per-1M-token pricing (USD). Safe upper bounds — we'd rather
# over-estimate cost than under-estimate during monitoring.
_LLM_PRICING: dict[tuple[str, str], tuple[float, float]] = {
    # (provider, model_prefix) -> (input_per_1m, output_per_1m)
    ("openai",  "gpt-4o"):                (2.50, 10.00),
    ("openai",  "gpt-4o-mini"):           (0.15,  0.60),
    ("openai",  "gpt-4.1"):               (2.00,  8.00),
    ("groq",    "llama-3.1-8b-instant"):  (0.05,  0.08),
    ("groq",    "llama-3.3-70b"):         (0.59,  0.79),
}
_LLM_DEFAULT = (2.50, 10.00)  # conservative default if model isn't mapped


def estimate_llm_cost_usd(provider: str, model: str, prompt_tokens: int, completion_tokens: int) -> float:
    key = None
    for (p, m), price in _LLM_PRICING.items():
        if p == provider and model.startswith(m):
            key = (p, m)
            break
    inp_per_1m, out_per_1m = _LLM_PRICING.get(key, _LLM_DEFAULT) if key else _LLM_DEFAULT
    return (prompt_tokens * inp_per_1m + completion_tokens * out_per_1m) / 1_000_000


# Deepgram Nova-3 streaming: ~$0.0043/min. Average dictation session ≈ 5s of
# audio — a coarse MVP estimate until we reconcile against Deepgram's
# Usage API by key tag.
_STT_AVG_SECONDS_PER_SESSION = 5.0
_STT_PRICE_PER_SECOND = 0.0043 / 60.0


def estimate_stt_cost_usd(seconds: float | None = None) -> float:
    s = seconds if seconds is not None else _STT_AVG_SECONDS_PER_SESSION
    return s * _STT_PRICE_PER_SECOND


async def record_llm_usage(
    db: AsyncSession,
    *,
    user_id: int,
    provider: str,
    model: str,
    action: str,
    prompt_tokens: int,
    completion_tokens: int,
    duration_ms: int,
) -> None:
    try:
        row = LLMUsage(
            user_id=user_id,
            provider=provider,
            model=model,
            action=action,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            cost_usd_est=estimate_llm_cost_usd(provider, model, prompt_tokens, completion_tokens),
            duration_ms=duration_ms,
        )
        db.add(row)
        await db.commit()
    except Exception as e:
        _log.warning("record_llm_usage failed: %s", e)


async def record_stt_usage(
    db: AsyncSession,
    *,
    user_id: int,
    deepgram_key_id: str | None = None,
) -> None:
    try:
        row = STTUsage(
            user_id=user_id,
            provider="deepgram",
            deepgram_key_id=deepgram_key_id,
            cost_usd_est=estimate_stt_cost_usd(),
        )
        db.add(row)
        await db.commit()
    except Exception as e:
        _log.warning("record_stt_usage failed: %s", e)


@asynccontextmanager
async def time_ms():
    """Usage:  async with time_ms() as t: ...   # t.ms available after the block"""
    start = time.perf_counter()
    class _T:
        ms = 0
    t = _T()
    try:
        yield t
    finally:
        t.ms = int((time.perf_counter() - start) * 1000)
