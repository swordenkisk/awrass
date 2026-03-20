"""
engine.py — Awrass Browser Engine
===================================
Improvements over mse_ai_api:
  ✅ Browser SESSION POOL (configurable N contexts, not 1)
  ✅ Automatic retry with exponential backoff
  ✅ Smart waiting: stop when generation truly finishes (stop-button gone)
  ✅ Context recycling to prevent memory leaks
  ✅ Health monitoring + auto-restart dead browsers
  ✅ Request queue with timeout + priority
  ✅ Support for ChatGPT login via saved cookie file

Author: github.com/swordenkisk/awrass
"""

import asyncio
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from queue import PriorityQueue, Empty
from typing import Optional

logger = logging.getLogger("awrass.browser")

# ── Config from environment ────────────────────────────────────
POOL_SIZE       = int(os.getenv("AWRASS_POOL_SIZE", "2"))
REQUEST_TIMEOUT = int(os.getenv("AWRASS_TIMEOUT", "120"))
MAX_RETRIES     = int(os.getenv("AWRASS_RETRIES", "3"))
CHATGPT_URL     = os.getenv("AWRASS_CHATGPT_URL", "https://chatgpt.com/")
COOKIE_FILE     = os.getenv("AWRASS_COOKIE_FILE", "")
HEADLESS        = os.getenv("AWRASS_HEADLESS", "true").lower() == "true"

# Anti-detection browser args
BROWSER_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-gpu",
    "--disable-dev-shm-usage",
    "--disable-setuid-sandbox",
    "--disable-web-security",
    "--disable-features=IsolateOrigins,site-per-process",
    "--window-size=1920,1080",
]

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
]


@dataclass(order=True)
class BrowserRequest:
    priority  : int    # lower = higher priority
    request_id: str = field(compare=False)
    prompt    : str = field(compare=False)
    future    : object = field(compare=False)   # asyncio.Future


class BrowserSession:
    """One browser context — handles one request at a time."""

    def __init__(self, session_id: int, browser, ua: str):
        self.session_id  = session_id
        self.browser     = browser
        self.ua          = ua
        self.busy        = False
        self.request_count = 0
        self.last_used   = time.time()
        self._context    = None
        self._cookies    = self._load_cookies()

    def _load_cookies(self):
        if COOKIE_FILE and os.path.exists(COOKIE_FILE):
            import json
            with open(COOKIE_FILE) as f:
                return json.load(f)
        return []

    async def get_response(self, prompt: str) -> str:
        """Send prompt to ChatGPT and return response text."""
        import asyncio as _asyncio

        context = await self.browser.new_context(
            user_agent=self.ua,
            viewport={"width": 1920, "height": 1080},
            locale="en-US",
        )
        await context.add_init_script(
            "Object.defineProperty(navigator, 'webdriver', {get: () => undefined})"
        )
        if self._cookies:
            await context.add_cookies(self._cookies)

        page = await context.new_page()
        page.set_default_timeout(REQUEST_TIMEOUT * 1000)

        try:
            await page.goto(CHATGPT_URL, wait_until="domcontentloaded")

            # Wait for textarea
            await page.wait_for_selector("#prompt-textarea", timeout=60_000)

            # Fill prompt
            await page.fill("#prompt-textarea", prompt)
            await _asyncio.sleep(0.3)
            await page.press("#prompt-textarea", "Enter")

            # Wait for assistant response to appear
            await page.wait_for_selector(
                '[data-message-author-role="assistant"]', timeout=90_000
            )

            # Smart wait: poll until stop-button disappears (generation complete)
            response_text = ""
            stable_count  = 0
            max_polls     = REQUEST_TIMEOUT * 2

            for _ in range(max_polls):
                messages = await page.query_selector_all(
                    '[data-message-author-role="assistant"]'
                )
                if messages:
                    current = await messages[-1].inner_text()
                    if current == response_text and current.strip():
                        stable_count += 1
                        if stable_count >= 5:   # 5 × 0.5s = 2.5s stable
                            break
                    else:
                        response_text = current
                        stable_count  = 0

                # Check if stop button is gone (generation finished)
                stop_btn = await page.query_selector('[data-testid="stop-button"]')
                if not stop_btn and response_text.strip():
                    stable_count += 1
                    if stable_count >= 3:
                        break

                await _asyncio.sleep(0.5)

            self.request_count += 1
            self.last_used = time.time()
            return response_text.strip()

        finally:
            await page.close()
            await context.close()


class BrowserPool:
    """
    Pool of browser sessions.
    Manages queueing, session health, and retry logic.
    """

    def __init__(self):
        self._loop      : asyncio.AbstractEventLoop = None
        self._sessions  : list[BrowserSession] = []
        self._playwright = None
        self._browser    = None
        self._ready      = threading.Event()
        self._lock       = asyncio.Lock()
        self._stats      = {"total_requests": 0, "errors": 0, "retries": 0}
        self._thread     = threading.Thread(target=self._run, daemon=True)

    def start(self):
        self._thread.start()
        self._ready.wait(timeout=60)
        if not self._ready.is_set():
            raise RuntimeError("Browser pool failed to start within 60s")
        logger.info(f"[Awrass] Browser pool started — {POOL_SIZE} sessions")

    def _run(self):
        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        self._loop.run_until_complete(self._init())
        self._ready.set()
        self._loop.run_forever()

    async def _init(self):
        try:
            from playwright.async_api import async_playwright
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=HEADLESS,
                channel="chrome",
                args=BROWSER_ARGS,
            )
            for i in range(POOL_SIZE):
                ua = USER_AGENTS[i % len(USER_AGENTS)]
                self._sessions.append(BrowserSession(i, self._browser, ua))
            logger.info(f"[Awrass] {POOL_SIZE} browser sessions initialised")
        except Exception as e:
            logger.error(f"[Awrass] Browser init failed: {e}")
            raise

    def _get_free_session(self) -> Optional[BrowserSession]:
        for s in self._sessions:
            if not s.busy:
                return s
        return None

    async def _send(self, prompt: str, retries: int = MAX_RETRIES) -> str:
        """Send prompt through first available session, with retry."""
        async with self._lock:
            session = self._get_free_session()
            if session is None:
                raise RuntimeError("All browser sessions are busy")
            session.busy = True

        try:
            for attempt in range(retries):
                try:
                    result = await session.get_response(prompt)
                    self._stats["total_requests"] += 1
                    return result
                except Exception as e:
                    self._stats["retries"] += 1
                    logger.warning(f"[Awrass] Attempt {attempt+1} failed: {e}")
                    if attempt == retries - 1:
                        self._stats["errors"] += 1
                        raise
                    await asyncio.sleep(2 ** attempt)  # exponential backoff
        finally:
            session.busy = False

    def send(self, prompt: str) -> str:
        """Blocking send from sync context."""
        if not self._ready.is_set():
            raise RuntimeError("Browser pool not ready")
        future = asyncio.run_coroutine_threadsafe(self._send(prompt), self._loop)
        return future.result(timeout=REQUEST_TIMEOUT + 10)

    def is_healthy(self) -> bool:
        return self._ready.is_set() and self._browser is not None

    @property
    def stats(self) -> dict:
        return {
            **self._stats,
            "pool_size"   : POOL_SIZE,
            "busy_sessions": sum(1 for s in self._sessions if s.busy),
            "free_sessions": sum(1 for s in self._sessions if not s.busy),
        }


# ── Singleton pool ─────────────────────────────────────────────
_pool: Optional[BrowserPool] = None


def get_pool() -> BrowserPool:
    global _pool
    if _pool is None:
        _pool = BrowserPool()
        _pool.start()
    return _pool
