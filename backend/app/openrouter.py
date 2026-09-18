"""OpenRouter provider for the grounded explanation layer (Gemma 4).

MetrIQ's results are produced by the deterministic pipeline. This module is the
only place that talks to OpenRouter, and NOTHING in the inspection pipeline
(OCR, declarations, product identification, compliance, package label,
hallmarking, escalation, records, report) imports it. If OpenRouter is down,
mis-configured or out of free quota, every one of those still works — only the
optional explanation is unavailable.

    app/llm.py       LocalLLM           -> LM Studio (unchanged, used by /ask)
    app/openrouter.py OpenRouterLLM     -> OpenRouter -> Gemma 4

Both expose the same ``generate(system_prompt=..., user_prompt=...) -> str``
surface, so the explanation layer stays provider-replaceable.

Configuration (environment; ``backend/.env`` is read by ``load_env_file()``):

    OPENROUTER_API_KEY       required — server-side only, never sent to the browser
    OPENROUTER_MODEL         default "google/gemma-4-31b-it:free"
    OPENROUTER_BASE_URL      default "https://openrouter.ai/api/v1"
    OPENROUTER_TIMEOUT       seconds, default 60
    OPENROUTER_DAILY_LIMIT   default 45  (free tier allows ~50/day — headroom kept)
    OPENROUTER_MINUTE_LIMIT  default 15  (free tier allows ~20/min)

The free tier is treated as a hard product constraint: the limiter refuses a
request locally BEFORE it reaches OpenRouter, requests are never retried
automatically, and nothing in the application calls the provider on its own —
only an explicit user action does.
"""

from __future__ import annotations

import os
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import httpx

from app.llm import LLMError

DEFAULT_MODEL = "google/gemma-4-31b-it:free"
DEFAULT_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_TIMEOUT = 60.0
DEFAULT_DAILY_LIMIT = 45
DEFAULT_MINUTE_LIMIT = 15

# OpenRouter uses these for attribution only. No user data, no key.
_REFERER = "https://metriq.local"
_TITLE = "MetrIQ Inspection Assistant"

# User-facing messages per failure code. They never contain the key, the URL,
# the request body or a raw provider error.
MESSAGES: dict[str, str] = {
    "NOT_CONFIGURED": (
        "The AI explanation service is not configured on this server. "
        "The underlying MetrIQ inspection remains available."
    ),
    "DAILY_LIMIT": (
        "AI explanation limit reached for today. "
        "The underlying MetrIQ inspection remains available."
    ),
    "RATE_LIMITED": (
        "AI explanations are being requested too quickly. Please wait a moment. "
        "The underlying MetrIQ inspection remains available."
    ),
    "TIMEOUT": (
        "The explanation service did not respond in time. "
        "The underlying MetrIQ inspection remains available."
    ),
    "PROVIDER_ERROR": (
        "The explanation service is temporarily unavailable. "
        "The underlying MetrIQ inspection remains available."
    ),
    "BAD_RESPONSE": (
        "The explanation service returned an unusable response. "
        "The underlying MetrIQ inspection remains available."
    ),
}


class CopilotUnavailable(LLMError):
    """The explanation layer could not answer. Never a compliance failure.

    ``code`` is one of MESSAGES' keys and is safe to show a user; ``str(exc)``
    is the matching sentence. Internal details (API key, URL, provider payload)
    are deliberately not carried.
    """

    def __init__(self, code: str, message: str | None = None) -> None:
        self.code = code
        super().__init__(message or MESSAGES.get(code, MESSAGES["PROVIDER_ERROR"]))


def load_env_file(path: Path | None = None) -> None:
    """Read ``backend/.env`` into the process environment (once, best effort).

    Plain ``KEY=value`` lines; ``#`` comments and blank lines are ignored.
    A variable already set in the real environment always wins, so an export
    still overrides the file. No dependency, no interpolation, no surprises.
    The file is gitignored — this is how the OpenRouter key stays out of git,
    out of the frontend and off the command line.
    """
    env_path = path or Path(__file__).resolve().parents[1] / ".env"
    try:
        text = env_path.read_text(encoding="utf-8")
    except OSError:
        return

    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def _int_env(name: str, default: int) -> int:
    try:
        return max(0, int(os.environ[name]))
    except (KeyError, ValueError):
        return default


class UsageLimiter:
    """Local guard for the OpenRouter free tier: N per UTC day, M per minute.

    In-process and intentionally simple (a hackathon prototype runs one API
    process). It only ever *refuses* requests, so if the counter is lost on a
    restart the worst case is the provider's own 429, which is handled too.
    """

    def __init__(self, daily: int | None = None, per_minute: int | None = None) -> None:
        self.daily = _int_env("OPENROUTER_DAILY_LIMIT", DEFAULT_DAILY_LIMIT) if daily is None else daily
        self.per_minute = _int_env("OPENROUTER_MINUTE_LIMIT", DEFAULT_MINUTE_LIMIT) if per_minute is None else per_minute
        self._lock = threading.Lock()
        self._day = self._today()
        self._day_count = 0
        self._recent: list[float] = []

    @staticmethod
    def _today() -> str:
        return datetime.now(timezone.utc).strftime("%Y-%m-%d")

    def _prune(self, now: float) -> None:
        if self._day != self._today():
            self._day, self._day_count = self._today(), 0
        self._recent = [t for t in self._recent if now - t < 60.0]

    def snapshot(self) -> dict:
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            return {
                "daily_limit": self.daily,
                "daily_used": self._day_count,
                "daily_remaining": max(0, self.daily - self._day_count),
                "minute_limit": self.per_minute,
                "minute_remaining": max(0, self.per_minute - len(self._recent)),
            }

    def refund_day(self) -> None:
        """Give back the daily slot of a request the provider never served.

        OpenRouter's own free daily counter only counts served requests, so a
        429, a timeout or an outage must not eat into the day's allowance. The
        per-minute count is kept — it is the burst guard, and a failing service
        should not be hammered.
        """
        with self._lock:
            if self._day == self._today() and self._day_count > 0:
                self._day_count -= 1

    def reserve(self) -> None:
        """Count one request, or raise before anything leaves this machine."""
        with self._lock:
            now = time.monotonic()
            self._prune(now)
            if self._day_count >= self.daily:
                raise CopilotUnavailable("DAILY_LIMIT")
            if len(self._recent) >= self.per_minute:
                raise CopilotUnavailable("RATE_LIMITED")
            self._day_count += 1
            self._recent.append(now)


class OpenRouterLLM:
    """Client for OpenRouter's OpenAI-compatible chat-completions endpoint.

    One request per call, no automatic retry (the free quota is scarce), and
    every failure becomes a CopilotUnavailable with a short user-facing message.
    """

    def __init__(
        self,
        api_key: str | None = None,
        model: str | None = None,
        base_url: str | None = None,
        timeout: float | None = None,
        limiter: UsageLimiter | None = None,
    ) -> None:
        load_env_file()
        self._api_key = api_key if api_key is not None else os.environ.get("OPENROUTER_API_KEY", "")
        self.model = model or os.environ.get("OPENROUTER_MODEL") or DEFAULT_MODEL
        self.base_url = (base_url or os.environ.get("OPENROUTER_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
        try:
            self.timeout = float(timeout if timeout is not None else os.environ.get("OPENROUTER_TIMEOUT", DEFAULT_TIMEOUT))
        except ValueError:
            self.timeout = DEFAULT_TIMEOUT
        self.limiter = limiter or UsageLimiter()

    @property
    def configured(self) -> bool:
        """True when a key is present. The key itself is never exposed."""
        return bool(self._api_key.strip())

    def status(self) -> dict:
        """Safe status for the UI: configured flag, model id, remaining budget.

        Deliberately contains no API key and no fragment of one.
        """
        return {
            "configured": self.configured,
            "provider": "openrouter",
            "model": self.model,
            **self.limiter.snapshot(),
        }

    def generate(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.0,
        max_tokens: int = 700,
    ) -> str:
        if not self.configured:
            raise CopilotUnavailable("NOT_CONFIGURED")

        self.limiter.reserve()

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            response = httpx.post(
                f"{self.base_url}/chat/completions",
                json=payload,
                headers={
                    "Authorization": f"Bearer {self._api_key}",
                    "HTTP-Referer": _REFERER,
                    "X-Title": _TITLE,
                },
                timeout=self.timeout,
            )
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            self.limiter.refund_day()
            raise CopilotUnavailable(_status_code(exc.response.status_code)) from exc
        except httpx.TimeoutException as exc:
            self.limiter.refund_day()
            raise CopilotUnavailable("TIMEOUT") from exc
        except httpx.HTTPError as exc:  # connection refused, DNS, TLS, ...
            self.limiter.refund_day()
            raise CopilotUnavailable("PROVIDER_ERROR") from exc

        try:
            data = response.json()
            content = data["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError) as exc:
            self.limiter.refund_day()
            raise CopilotUnavailable("BAD_RESPONSE") from exc

        if not isinstance(content, str) or not content.strip():
            self.limiter.refund_day()
            raise CopilotUnavailable("BAD_RESPONSE")

        return content.strip()


def _status_code(status: int) -> str:
    """Map an OpenRouter HTTP status to a safe failure code."""
    if status in (401, 403):
        return "NOT_CONFIGURED"  # missing / invalid / revoked key
    if status == 402:
        return "DAILY_LIMIT"     # free credits exhausted
    if status == 429:
        return "RATE_LIMITED"
    return "PROVIDER_ERROR"
