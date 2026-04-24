"""
Cloudflare R2 client — S3-compatible storage for per-session audio debug blobs.

R2 is S3 API-compatible, so boto3 works with a custom endpoint_url and the
signature_version='s3v4'. Region is always 'auto' for R2.
"""

from __future__ import annotations

import logging
from typing import Optional

from settings import get_settings

_log = logging.getLogger("r2")
_client = None
_client_lock_ready = False


def _endpoint() -> str:
    s = get_settings()
    return f"https://{s.r2_account_id}.r2.cloudflarestorage.com"


def configured() -> bool:
    s = get_settings()
    return bool(s.r2_account_id and s.r2_access_key_id and s.r2_secret_access_key and s.r2_bucket_name)


def get_client():
    """Returns a cached boto3 S3 client pointed at R2, or None if not configured."""
    global _client
    if _client is not None:
        return _client
    if not configured():
        return None
    import boto3
    from botocore.config import Config
    s = get_settings()
    _client = boto3.client(
        "s3",
        endpoint_url=_endpoint(),
        aws_access_key_id=s.r2_access_key_id,
        aws_secret_access_key=s.r2_secret_access_key,
        region_name="auto",
        config=Config(signature_version="s3v4", s3={"addressing_style": "path"}),
    )
    return _client


def put_bytes(key: str, body: bytes, content_type: str = "audio/wav") -> bool:
    """Upload a byte blob to R2. Returns True on success, False on failure."""
    client = get_client()
    if client is None:
        return False
    try:
        s = get_settings()
        import asyncio
        # boto3 is sync; push to a thread so we don't block the event loop.
        asyncio.get_event_loop().run_in_executor(
            None,
            lambda: client.put_object(
                Bucket=s.r2_bucket_name,
                Key=key,
                Body=body,
                ContentType=content_type,
            ),
        )
        return True
    except Exception as e:
        _log.warning("r2 put_bytes failed: %s", e)
        return False


async def put_bytes_async(key: str, body: bytes, content_type: str = "audio/wav") -> bool:
    """Async variant that actually waits for the upload to complete."""
    client = get_client()
    if client is None:
        return False
    try:
        s = get_settings()
        import asyncio
        await asyncio.get_running_loop().run_in_executor(
            None,
            lambda: client.put_object(
                Bucket=s.r2_bucket_name,
                Key=key,
                Body=body,
                ContentType=content_type,
            ),
        )
        return True
    except Exception as e:
        _log.warning("r2 put_bytes_async failed: %s", e)
        return False


def presigned_get_url(key: str, expires_in_seconds: int = 3600) -> Optional[str]:
    """Generate a time-limited GET URL the browser can hit directly."""
    client = get_client()
    if client is None:
        return None
    try:
        s = get_settings()
        return client.generate_presigned_url(
            "get_object",
            Params={"Bucket": s.r2_bucket_name, "Key": key},
            ExpiresIn=expires_in_seconds,
        )
    except Exception as e:
        _log.warning("r2 presigned_get_url failed: %s", e)
        return None


def build_audio_key(user_id: int, session_id: str) -> str:
    """Object key convention. Partitioned by user for easy admin scanning."""
    # keep session_id hex-only to avoid weird chars in the URL
    safe = "".join(c for c in session_id if c.isalnum() or c in "-_")
    return f"user_{user_id}/{safe}.wav"


def pcm_to_wav(pcm_bytes: bytes, sample_rate: int = 16000) -> bytes:
    """Wrap raw int16 PCM mono bytes in a WAV container so the browser <audio>
    tag can play it without extra codecs."""
    import io
    import wave
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)            # int16 = 2 bytes
        w.setframerate(sample_rate)
        w.writeframes(pcm_bytes)
    return buf.getvalue()
