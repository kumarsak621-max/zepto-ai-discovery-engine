"""
Multi-key Gemini API manager with automatic key + model failover.

Supports GEMINI_API_KEY and GEMINI_API_KEY_1 … GEMINI_API_KEY_10
(Streamlit Secrets or environment / .env). Never logs full key values.

Uses the modern `google.genai` SDK (with legacy google.generativeai fallback).
"""

from __future__ import annotations

import logging
import os
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_KEYS = 10
DEFAULT_TIMEOUT_SEC = 60
DEFAULT_BACKOFF_BASE_SEC = 0.4
DEFAULT_BACKOFF_MAX_SEC = 6.0
DEFAULT_CIRCUIT_COOLDOWN_SEC = 60.0

ALL_KEYS_EXHAUSTED_MSG = (
    "All Gemini API keys failed after trying every configured key."
)

# Preferred models — primary first, then resilient free-tier aliases.
DEFAULT_MODEL_CANDIDATES = (
    "gemini-flash-latest",
    "gemini-2.0-flash-lite",
    "gemini-2.0-flash",
    "gemini-2.5-flash-lite",
    "gemini-1.5-flash",
)

_RETRYABLE_TOKENS = (
    "429",
    "rate limit",
    "quota",
    "resource_exhausted",
    "resource exhausted",
    "timeout",
    "timed out",
    "deadline exceeded",
    "temporarily unavailable",
    "service unavailable",
    "503",
    "502",
    "504",
    "500",
    "internal",
    "unavailable",
    "connection reset",
    "connection aborted",
    "server error",
    "try again",
    "404",
    "not found",
    "not supported",
)

_AUTH_TOKENS = (
    "401",
    "403",
    "api key",
    "api key not valid",
    "api_key_invalid",
    "invalid api key",
    "invalid authentication",
    "access_token_type_unsupported",
    "permission_denied",
    "permission denied",
    "unauthenticated",
    "consumer_invalid",
)

_SECRETS_AVAILABLE: bool | None = None


def _try_streamlit_secret(name: str) -> str | None:
    global _SECRETS_AVAILABLE
    if _SECRETS_AVAILABLE is False:
        return None
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is None:
            _SECRETS_AVAILABLE = False
            return None
        try:
            value = secrets.get(name)
        except Exception:
            _SECRETS_AVAILABLE = False
            return None
        _SECRETS_AVAILABLE = True
        if value is not None and str(value).strip():
            return str(value).strip()
        return None
    except Exception:
        _SECRETS_AVAILABLE = False
        return None


def _secret_or_env(name: str) -> str:
    secret = _try_streamlit_secret(name)
    if secret:
        return secret
    return (os.getenv(name, "") or "").strip()


def _env_float(name: str, default: float) -> float:
    raw = _secret_or_env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = _secret_or_env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


_PLACEHOLDER_PREFIXES = (
    "your_api",
    "your_key",
    "your_primary",
    "changeme",
    "replace_me",
    "xxx",
    "todo",
)


def _is_placeholder_key(key: str) -> bool:
    lower = key.lower().strip()
    if not lower:
        return True
    if any(lower.startswith(p) for p in _PLACEHOLDER_PREFIXES):
        return True
    return lower in {"none", "null", "n/a", "na", "test", "dummy"}


def _sanitize_error(err: str, *, limit: int = 400) -> str:
    import re

    text = (err or "").strip()
    text = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "[REDACTED_KEY]", text)
    text = re.sub(r"\bAQ\.[A-Za-z0-9_-]{20,}\b", "[REDACTED_KEY]", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    return text[:limit]


def load_gemini_api_keys() -> list[str]:
    """
    Load Gemini API keys from Secrets / env.

    Order: GEMINI_API_KEY, then GEMINI_API_KEY_1 … _10.
    Empty / placeholder / duplicate values are skipped.
    """
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(value: str) -> None:
        key = (value or "").strip()
        if not key or key in seen or _is_placeholder_key(key):
            return
        seen.add(key)
        ordered.append(key)

    _add(_secret_or_env("GEMINI_API_KEY"))
    for i in range(1, MAX_KEYS + 1):
        _add(_secret_or_env(f"GEMINI_API_KEY_{i}"))

    if len(ordered) > MAX_KEYS:
        logger.warning(
            "More than %s unique Gemini keys configured; using the first %s.",
            MAX_KEYS,
            MAX_KEYS,
        )
    return ordered[:MAX_KEYS]


def resolve_model_candidates(preferred: str | None = None) -> list[str]:
    """Build ordered unique model list: preferred → resilient defaults."""
    ordered: list[str] = []
    seen: set[str] = set()

    def _add(name: str) -> None:
        n = (name or "").strip()
        if not n or n in seen:
            return
        seen.add(n)
        ordered.append(n)

    if preferred:
        _add(preferred)
    else:
        _add(_secret_or_env("GEMINI_MODEL") or "")
    for name in DEFAULT_MODEL_CANDIDATES:
        _add(name)
    return ordered or ["gemini-flash-latest"]


def is_retryable_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(t in text for t in _AUTH_TOKENS):
        return True
    return any(t in text for t in _RETRYABLE_TOKENS)


def is_all_keys_exhausted_error(exc: BaseException | str | None) -> bool:
    text = str(exc or "")
    return ALL_KEYS_EXHAUSTED_MSG in text or "all gemini api keys failed" in text.lower()


@dataclass
class KeyManagerStats:
    total_keys: int = 0
    active_index: int = 0
    successful_requests: int = 0
    failed_requests: int = 0
    failovers: int = 0
    last_error: str = ""
    last_success_at: str = ""
    last_failover_at: str = ""
    model_name: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "total_keys": self.total_keys,
            "active_index": self.active_index,
            "active_key_display": (
                f"Key {self.active_index + 1} of {self.total_keys}"
                if self.total_keys
                else "None"
            ),
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "failovers": self.failovers,
            "last_error": self.last_error or "-",
            "last_success_at": self.last_success_at or "-",
            "last_failover_at": self.last_failover_at or "-",
            "model_name": self.model_name or "-",
        }


@dataclass
class GeminiKeyManager:
    """Single shared Gemini client manager with key + model failover."""

    keys: list[str] = field(default_factory=list)
    active_index: int = 0
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    backoff_base_sec: float = DEFAULT_BACKOFF_BASE_SEC
    backoff_max_sec: float = DEFAULT_BACKOFF_MAX_SEC
    circuit_cooldown_sec: float = DEFAULT_CIRCUIT_COOLDOWN_SEC
    stats: KeyManagerStats = field(default_factory=KeyManagerStats)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _circuit_open_until: float = field(default=0.0, repr=False)
    _active_model: str = field(default="")

    @classmethod
    def from_env(cls) -> "GeminiKeyManager":
        keys = load_gemini_api_keys()
        mgr = cls(
            keys=keys,
            active_index=0,
            timeout_sec=_env_float("GEMINI_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC),
            backoff_base_sec=_env_float(
                "GEMINI_BACKOFF_BASE_SEC", DEFAULT_BACKOFF_BASE_SEC
            ),
            backoff_max_sec=_env_float(
                "GEMINI_BACKOFF_MAX_SEC", DEFAULT_BACKOFF_MAX_SEC
            ),
            circuit_cooldown_sec=_env_float(
                "GEMINI_CIRCUIT_COOLDOWN_SEC", DEFAULT_CIRCUIT_COOLDOWN_SEC
            ),
        )
        mgr.stats.total_keys = len(keys)
        models = resolve_model_candidates()
        mgr._active_model = models[0]
        mgr.stats.model_name = models[0]
        logger.info(
            "Gemini key manager initialized: total_keys=%s models=%s",
            len(keys),
            models,
        )
        return mgr

    def reload(self) -> None:
        with self._lock:
            prev = list(self.keys)
            self.keys = load_gemini_api_keys()
            if self.active_index >= len(self.keys):
                self.active_index = 0
            self.timeout_sec = _env_float("GEMINI_TIMEOUT_SEC", DEFAULT_TIMEOUT_SEC)
            self.backoff_base_sec = _env_float(
                "GEMINI_BACKOFF_BASE_SEC", DEFAULT_BACKOFF_BASE_SEC
            )
            self.backoff_max_sec = _env_float(
                "GEMINI_BACKOFF_MAX_SEC", DEFAULT_BACKOFF_MAX_SEC
            )
            self.circuit_cooldown_sec = _env_float(
                "GEMINI_CIRCUIT_COOLDOWN_SEC", DEFAULT_CIRCUIT_COOLDOWN_SEC
            )
            self.stats.total_keys = len(self.keys)
            self.stats.active_index = self.active_index
            if self.keys != prev:
                self._circuit_open_until = 0.0
            if not self._active_model:
                models = resolve_model_candidates()
                self._active_model = models[0]
                self.stats.model_name = models[0]

    def has_keys(self) -> bool:
        with self._lock:
            return bool(self.keys)

    def key_count(self) -> int:
        with self._lock:
            return len(self.keys)

    def active_key_label(self) -> str:
        with self._lock:
            n = len(self.keys)
            if not n:
                return "No Gemini keys configured"
            return f"Using Gemini Key {self.active_index + 1} of {n}"

    def get_active_key(self) -> str:
        with self._lock:
            if not self.keys:
                return ""
            return self.keys[self.active_index]

    def get_stats(self) -> dict[str, Any]:
        with self._lock:
            self.stats.total_keys = len(self.keys)
            self.stats.active_index = self.active_index
            if not self.stats.model_name:
                self.stats.model_name = self._active_model or resolve_model_candidates()[0]
            return self.stats.to_dict()

    def reset_circuit(self) -> None:
        with self._lock:
            self._circuit_open_until = 0.0

    def _generate_once(self, api_key: str, model_name: str, prompt: str) -> str:
        """Single request via google.genai (preferred) or legacy generativeai."""
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        def _call_new_sdk() -> str:
            from google import genai

            client = genai.Client(api_key=api_key)
            response = client.models.generate_content(
                model=model_name,
                contents=prompt,
            )
            text = getattr(response, "text", None)
            if text is None:
                # Some SDK responses nest candidates
                try:
                    text = response.candidates[0].content.parts[0].text
                except Exception:
                    text = str(response)
            return (text or "").strip()

        def _call_legacy_sdk() -> str:
            import google.generativeai as genai_legacy

            genai_legacy.configure(api_key=api_key)
            model = genai_legacy.GenerativeModel(model_name)
            response = model.generate_content(prompt)
            return (response.text or "").strip()

        def _call() -> str:
            try:
                return _call_new_sdk()
            except ImportError:
                logger.warning("google.genai not installed — using legacy google.generativeai")
                return _call_legacy_sdk()
            except Exception as exc:
                # If new SDK fails for non-API reasons, try legacy once
                msg = str(exc).lower()
                if "no module" in msg or "cannot import" in msg:
                    return _call_legacy_sdk()
                raise

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                return future.result(timeout=self.timeout_sec)
            except FuturesTimeout as exc:
                raise TimeoutError(
                    f"Gemini request timed out after {self.timeout_sec:.0f}s"
                ) from exc

    def generate_content(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        on_key_used: Callable[[str], None] | None = None,
    ) -> str:
        """
        Generate text with automatic key + model failover.

        Strategy:
          for each model candidate:
            for each API key (starting at active):
              try request → return on success
        Raises ALL_KEYS_EXHAUSTED_MSG only after every key×model pair failed.
        """
        if not self.keys:
            self.reload()
        if not self.keys:
            raise RuntimeError(
                "No Gemini API keys configured. Set GEMINI_API_KEY or "
                "GEMINI_API_KEY_1…GEMINI_API_KEY_10 in .env / Streamlit Secrets."
            )

        prompt = (prompt or "").strip()
        if not prompt:
            raise ValueError("Gemini prompt is empty — cannot call the API.")

        with self._lock:
            if self._circuit_open_until and time.time() < self._circuit_open_until:
                remaining = max(0.0, self._circuit_open_until - time.time())
                reason = (
                    f"{ALL_KEYS_EXHAUSTED_MSG} "
                    f"(circuit open ~{remaining:.0f}s remaining; "
                    f"last_error={self.stats.last_error or 'n/a'})"
                )
                logger.error("Gemini circuit open — refusing request: %s", reason)
                print(f"[AI DEBUG] circuit OPEN: {reason}", flush=True)
                try:
                    from src.gemini_debug import record_ai_failure

                    record_ai_failure(
                        RuntimeError(reason),
                        stage="circuit_open",
                        extra={"last_error": self.stats.last_error},
                    )
                except Exception:
                    logger.exception("record_ai_failure on circuit open failed")
                raise RuntimeError(reason)

        models = resolve_model_candidates(model_name)
        with self._lock:
            n_keys = len(self.keys)
            start = self.active_index % n_keys

        key_order = [(start + offset) % n_keys for offset in range(n_keys)]
        last_error: Exception | None = None
        attempt = 0

        logger.info(
            "Gemini request start: total_keys=%s active_key=%s models=%s prompt_chars=%s",
            n_keys,
            start + 1,
            models,
            len(prompt),
        )
        print(
            f"[AI DEBUG] request start keys={n_keys} active_key={start + 1} "
            f"models={models} prompt_chars={len(prompt)}",
            flush=True,
        )

        for model in models:
            for idx in key_order:
                attempt += 1
                with self._lock:
                    key = self.keys[idx]
                    n_keys = len(self.keys)
                key_number = idx + 1

                logger.info(
                    "Gemini attempt: key_number=%s/%s model=%s attempt=%s",
                    key_number,
                    n_keys,
                    model,
                    attempt,
                )
                print(
                    f"[AI DEBUG] attempt={attempt} key={key_number}/{n_keys} model={model}",
                    flush=True,
                )
                if on_key_used:
                    try:
                        on_key_used(f"Key {key_number} of {n_keys}")
                    except Exception as cb_exc:
                        logger.warning("on_key_used callback failed: %s", cb_exc)

                try:
                    text = self._generate_once(key, model, prompt)
                    if not text:
                        raise RuntimeError("Gemini returned an empty response")
                    with self._lock:
                        self.active_index = idx
                        self._active_model = model
                        self.stats.active_index = idx
                        self.stats.model_name = model
                        self.stats.successful_requests += 1
                        self.stats.last_success_at = time.strftime(
                            "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
                        )
                        self._circuit_open_until = 0.0
                    logger.info(
                        "Gemini request success: key_number=%s model=%s attempt=%s",
                        key_number,
                        model,
                        attempt,
                    )
                    print(
                        f"[AI DEBUG] request end SUCCESS key={key_number} model={model} "
                        f"attempt={attempt}",
                        flush=True,
                    )
                    try:
                        from src.gemini_debug import record_ai_success

                        record_ai_success(stage="generate_content")
                    except Exception:
                        logger.exception("record_ai_success failed")
                    return text
                except Exception as exc:
                    last_error = exc
                    reason = _sanitize_error(str(exc))
                    with self._lock:
                        self.stats.failed_requests += 1
                        self.stats.last_error = reason
                        self.stats.failovers += 1
                        self.stats.last_failover_at = time.strftime(
                            "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
                        )
                        self.active_index = (idx + 1) % n_keys
                        self.stats.active_index = self.active_index

                    tb = traceback.format_exc()
                    logger.error(
                        "Gemini failover: key_number=%s model=%s "
                        "attempt=%s reason=%s next_key=%s\n%s",
                        key_number,
                        model,
                        attempt,
                        reason[:240],
                        (idx + 1) % n_keys + 1,
                        tb,
                    )
                    print(
                        f"[AI DEBUG] FAILOVER key={key_number} model={model} "
                        f"attempt={attempt} reason={reason[:240]}\n{tb}",
                        flush=True,
                    )

                    backoff = min(
                        self.backoff_max_sec,
                        self.backoff_base_sec * (2 ** min(attempt - 1, 3)),
                    )
                    time.sleep(backoff)

        safe_last = _sanitize_error(str(last_error))
        with self._lock:
            cooldown = max(
                15.0, float(self.circuit_cooldown_sec or DEFAULT_CIRCUIT_COOLDOWN_SEC)
            )
            self._circuit_open_until = time.time() + cooldown
            self.stats.last_error = safe_last

        final_tb = traceback.format_exc() if last_error else ""
        logger.error(
            "Gemini FINAL exception — exhausted all keys/models: attempts=%s "
            "total_keys=%s models=%s last_reason=%s\n%s",
            attempt,
            n_keys,
            models,
            safe_last[:240],
            final_tb,
        )
        print(
            f"[AI DEBUG] FINAL EXCEPTION attempts={attempt} keys={n_keys} "
            f"models={models} last={safe_last}\n{final_tb}",
            flush=True,
        )
        try:
            from src.gemini_debug import record_ai_failure

            record_ai_failure(
                last_error or RuntimeError(ALL_KEYS_EXHAUSTED_MSG),
                stage="generate_content_exhausted",
                attempt=attempt,
                extra={"models_tried": models, "total_keys": n_keys},
            )
        except Exception:
            logger.exception("record_ai_failure failed after exhaustion")
        raise RuntimeError(ALL_KEYS_EXHAUSTED_MSG) from last_error



_MANAGER: GeminiKeyManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_key_manager() -> GeminiKeyManager:
    """Singleton Gemini manager — only one shared client manager in the app."""
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = GeminiKeyManager.from_env()
        else:
            _MANAGER.reload()
        return _MANAGER


def generate_with_failover(prompt: str, *, model_name: str | None = None) -> str:
    """Module-level helper used by analysis / chatbot / discovery."""
    if not (prompt or "").strip():
        raise ValueError("Gemini prompt is empty")
    mgr = get_key_manager()
    if not mgr.has_keys():
        raise RuntimeError(
            "No Gemini API keys configured. Set GEMINI_API_KEY / GEMINI_API_KEY_1…_5 "
            "in Streamlit Secrets or .env."
        )
    return mgr.generate_content(prompt, model_name=model_name)


def gemini_status() -> dict[str, Any]:
    return get_key_manager().get_stats()


def gemini_active_label() -> str:
    return get_key_manager().active_key_label()
