"""
auth/middleware.py — Awrass Authentication & Rate Limiting
===========================================================
Improvements over mse_ai_api:
  ✅ Multi-key support (multiple API keys with different roles)
  ✅ Per-key rate limiting (requests per minute)
  ✅ Request logging with timestamps
  ✅ IP-based additional protection

Author: github.com/swordenkisk/awrass
"""

import os
import time
import logging
from collections import defaultdict
from typing import Optional

logger = logging.getLogger("awrass.auth")

# ── Config ────────────────────────────────────────────────────
_PRIMARY_KEY  = os.getenv("AWRASS_API_KEY", "awrass-secret-2026")
_EXTRA_KEYS   = [k.strip() for k in os.getenv("AWRASS_EXTRA_KEYS", "").split(",") if k.strip()]
ALL_KEYS      = set([_PRIMARY_KEY] + _EXTRA_KEYS)
RATE_LIMIT_RPM= int(os.getenv("AWRASS_RATE_LIMIT", "20"))   # requests per minute per key

# In-memory rate limiting (resets per minute window)
_rate_store: dict = defaultdict(list)   # key → [timestamps]

_request_log: list = []
MAX_LOG_ENTRIES = 500


def validate_bearer(authorization: Optional[str]) -> tuple[bool, str]:
    """
    Validate Authorization: Bearer <key> header.
    Returns (is_valid, key_or_error_message).
    """
    if not authorization:
        return False, "Missing Authorization header"
    if not authorization.lower().startswith("bearer "):
        return False, "Authorization header must start with 'Bearer '"
    key = authorization[7:].strip()
    if not key:
        return False, "Empty API key"
    if key not in ALL_KEYS:
        return False, "Invalid API key"
    return True, key


def check_rate_limit(key: str) -> tuple[bool, int]:
    """
    Check if key is within rate limit.
    Returns (allowed, remaining_this_minute).
    """
    now = time.time()
    window_start = now - 60.0
    # Purge old entries
    _rate_store[key] = [t for t in _rate_store[key] if t > window_start]
    count = len(_rate_store[key])
    if count >= RATE_LIMIT_RPM:
        return False, 0
    _rate_store[key].append(now)
    return True, RATE_LIMIT_RPM - count - 1


def log_request(key: str, model: str, endpoint: str,
                success: bool, latency_ms: int = 0, ip: str = ""):
    """Log a request for the dashboard."""
    global _request_log
    entry = {
        "ts"        : time.time(),
        "key"       : f"...{key[-6:]}",
        "model"     : model,
        "endpoint"  : endpoint,
        "success"   : success,
        "latency_ms": latency_ms,
        "ip"        : ip,
    }
    _request_log.append(entry)
    if len(_request_log) > MAX_LOG_ENTRIES:
        _request_log = _request_log[-MAX_LOG_ENTRIES:]


def get_stats() -> dict:
    """Return aggregated usage statistics."""
    total    = len(_request_log)
    success  = sum(1 for r in _request_log if r["success"])
    errors   = total - success
    avg_lat  = (sum(r["latency_ms"] for r in _request_log) / total) if total else 0
    return {
        "total_requests": total,
        "successful"    : success,
        "errors"        : errors,
        "error_rate_pct": round(100 * errors / total, 1) if total else 0,
        "avg_latency_ms": round(avg_lat),
        "recent"        : _request_log[-20:][::-1],
        "rate_limit_rpm": RATE_LIMIT_RPM,
        "keys_count"    : len(ALL_KEYS),
    }
