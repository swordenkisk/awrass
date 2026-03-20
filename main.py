"""
main.py — Awrass API Server
============================
OpenAI-compatible proxy server using ChatGPT web interface.
Drop-in replacement for OpenAI API — no API key costs.

Endpoints:
  POST /v1/chat/completions   — OpenAI Chat Completions API
  POST /v1/responses          — OpenAI Responses API
  GET  /v1/models             — List available models
  GET  /health                — Health check
  GET  /stats                 — Usage statistics
  GET  /dashboard             — Web dashboard UI
  GET  /docs                  — Interactive API documentation

Author: github.com/swordenkisk/awrass
"""

import logging
import os
import time
import uuid
from contextlib import asynccontextmanager
from typing import Any, Optional

from fastapi import FastAPI, Header, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from src.browser.engine import get_pool
from src.prompt.builder import build_prompt
from src.parser.response import (
    parse_response, build_openai_response, build_responses_api
)
from src.auth.middleware import (
    validate_bearer, check_rate_limit, log_request, get_stats
)

# ── Logging ───────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)
logger = logging.getLogger("awrass")

# ── Config ────────────────────────────────────────────────────
PORT          = int(os.getenv("AWRASS_PORT", "7777"))
HOST          = os.getenv("AWRASS_HOST", "0.0.0.0")
ARABIC_MODE   = os.getenv("AWRASS_ARABIC_MODE", "true").lower() == "true"
DEFAULT_MODEL = os.getenv("AWRASS_DEFAULT_MODEL", "gpt-4o-mini")


# ── Lifespan ──────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("🚀 Awrass starting — initialising browser pool...")
    try:
        get_pool()   # init singleton
        logger.info("✅ Browser pool ready")
    except Exception as e:
        logger.error(f"❌ Browser pool failed: {e}")
        logger.warning("⚠  Running in MOCK mode — browser unavailable")
    yield
    logger.info("Awrass shutting down")


# ── App ───────────────────────────────────────────────────────
app = FastAPI(
    title       = "Awrass — أوراس",
    description = "OpenAI-compatible ChatGPT proxy. Zero API costs.",
    version     = "2.0.0",
    lifespan    = lifespan,
    docs_url    = "/docs",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

templates = Jinja2Templates(directory="templates")
try:
    app.mount("/static", StaticFiles(directory="static"), name="static")
except Exception:
    pass


# ── Request models ────────────────────────────────────────────

class ChatMessage(BaseModel):
    role   : str
    content: Any  = None
    name   : Optional[str] = None
    type   : Optional[str] = None
    tool_calls: Optional[list] = None
    tool_call_id: Optional[str] = None
    call_id: Optional[str] = None
    arguments: Optional[Any] = None
    output : Optional[Any] = None

    model_config = {"extra": "allow"}


class ChatRequest(BaseModel):
    model           : str          = DEFAULT_MODEL
    messages        : list[ChatMessage]
    tools           : Optional[list] = None
    tool_choice     : Optional[Any]  = None
    temperature     : float          = 0.7
    max_tokens      : Optional[int]  = None
    stream          : bool           = False

    model_config = {"extra": "allow"}


class ResponsesRequest(BaseModel):
    model    : str           = DEFAULT_MODEL
    input    : Any                         # str or list
    tools    : Optional[list] = None
    previous_response_id: Optional[str] = None

    model_config = {"extra": "allow"}


# ── Auth dependency ───────────────────────────────────────────

def _auth(authorization: Optional[str], client_ip: str) -> str:
    valid, result = validate_bearer(authorization)
    if not valid:
        raise HTTPException(status_code=401, detail=result)
    allowed, remaining = check_rate_limit(result)
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail=f"Rate limit exceeded. Max {20} requests/minute.",
            headers={"X-RateLimit-Remaining": "0"},
        )
    return result


# ── Helper: call browser ──────────────────────────────────────

def _call_browser(prompt: str) -> str:
    """Send prompt to ChatGPT via browser pool, or return mock in dev mode."""
    pool = get_pool()
    if not pool.is_healthy():
        # Dev/test mode — return a structured mock
        return '{"tool_calls": []}' if "JSON" in prompt else "Mock response from Awrass."
    return pool.send(prompt)


# ── Endpoints ─────────────────────────────────────────────────

@app.post("/v1/chat/completions")
async def chat_completions(
    req         : ChatRequest,
    request     : Request,
    authorization: Optional[str] = Header(None),
):
    api_key = _auth(authorization, request.client.host)
    t0      = time.time()
    rid     = f"chatcmpl-{uuid.uuid4().hex}"

    messages = [m.model_dump() for m in req.messages]
    prompt   = build_prompt(messages, req.tools or [], arabic_mode=ARABIC_MODE)

    logger.info(f"[{rid}] /v1/chat/completions model={req.model} tools={len(req.tools or [])} prompt_len={len(prompt)}")

    try:
        raw      = _call_browser(prompt)
        parsed   = parse_response(raw)
        response = build_openai_response(parsed, model=req.model, request_id=rid)
        latency  = int((time.time() - t0) * 1000)
        log_request(api_key, req.model, "/v1/chat/completions", True, latency, request.client.host)
        logger.info(f"[{rid}] done in {latency}ms tool_call={parsed.is_tool_call}")
        return JSONResponse(content=response)
    except Exception as e:
        latency = int((time.time() - t0) * 1000)
        log_request(api_key, req.model, "/v1/chat/completions", False, latency)
        logger.error(f"[{rid}] error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/v1/responses")
async def responses_api(
    req         : ResponsesRequest,
    request     : Request,
    authorization: Optional[str] = Header(None),
):
    api_key = _auth(authorization, request.client.host)
    t0      = time.time()
    rid     = f"resp_{uuid.uuid4().hex}"

    # Normalise input to messages list
    if isinstance(req.input, str):
        messages = [{"role": "user", "content": req.input}]
    elif isinstance(req.input, list):
        messages = req.input
    else:
        messages = [{"role": "user", "content": str(req.input)}]

    prompt = build_prompt(messages, req.tools or [], arabic_mode=ARABIC_MODE)

    logger.info(f"[{rid}] /v1/responses model={req.model} tools={len(req.tools or [])}")

    try:
        raw      = _call_browser(prompt)
        parsed   = parse_response(raw)
        response = build_responses_api(parsed, model=req.model, request_id=rid)
        latency  = int((time.time() - t0) * 1000)
        log_request(api_key, req.model, "/v1/responses", True, latency, request.client.host)
        return JSONResponse(content=response)
    except Exception as e:
        log_request(api_key, req.model, "/v1/responses", False, 0)
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/v1/models")
async def list_models(authorization: Optional[str] = Header(None)):
    validate_bearer(authorization)
    models = [
        "gpt-4o", "gpt-4o-mini", "gpt-4-turbo", "gpt-4",
        "gpt-3.5-turbo", "o1", "o1-mini",
    ]
    ts = int(time.time())
    return {"object": "list", "data": [
        {"id": m, "object": "model", "created": ts,
         "owned_by": "awrass-proxy"} for m in models
    ]}


@app.get("/health")
async def health():
    pool = get_pool()
    return {
        "status"    : "ok" if pool.is_healthy() else "degraded",
        "version"   : "2.0.0",
        "app"       : "Awrass — أوراس",
        "browser"   : pool.is_healthy(),
        "pool_stats": pool.stats,
    }


@app.get("/stats")
async def stats(authorization: Optional[str] = Header(None)):
    validate_bearer(authorization)
    return {**get_stats(), "browser": get_pool().stats}


@app.get("/dashboard", response_class=HTMLResponse)
async def dashboard(request: Request):
    try:
        return templates.TemplateResponse("dashboard.html", {
            "request": request,
            "app_name": "Awrass — أوراس",
            "version" : "2.0.0",
        })
    except Exception:
        return HTMLResponse("<h1>Awrass Dashboard</h1><p>Templates not found. API is running.</p>")


# ── Entry point ───────────────────────────────────────────────
if __name__ == "__main__":
    import uvicorn
    print(f"\n{'='*52}")
    print("  أوراس — Awrass v2.0")
    print(f"  API: http://{HOST}:{PORT}/v1")
    print(f"  Dashboard: http://{HOST}:{PORT}/dashboard")
    print(f"  Docs: http://{HOST}:{PORT}/docs")
    print(f"{'='*52}\n")
    uvicorn.run("main:app", host=HOST, port=PORT, reload=False)
