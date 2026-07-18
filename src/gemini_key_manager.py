"""
Multi-key Gemini API manager with automatic failover, retries, and health stats.

Supports up to 10 keys via GEMINI_API_KEY / GEMINI_API_KEY_1 … GEMINI_API_KEY_10
(Streamlit Secrets or environment / .env). Never logs full key values.
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable

logger = logging.getLogger(__name__)

MAX_KEYS = 10
DEFAULT_MAX_ATTEMPTS = 6
DEFAULT_TIMEOUT_SEC = 45
DEFAULT_BACKOFF_BASE_SEC = 1.0
DEFAULT_BACKOFF_MAX_SEC = 16.0
DEFAULT_CIRCUIT_COOLDOWN_SEC = 120.0

_RETRYABLE_TOKENS = (
    "429",
    "rate limit",
    "quota",
    "resource exhausted",
    "resource_exhausted",
    "timeout",
    "timed out",
    "temporarily unavailable",
    "service unavailable",
    "503",
    "502",
    "504",
    "internal error",
    "500",
    "unavailable",
    "deadline exceeded",
    "connection reset",
    "connection aborted",
    "server error",
    "try again",
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
    "unauthenticated",
    "consumer_invalid",
    "permission denied",
)


_SECRETS_AVAILABLE: bool | None = None


def _try_streamlit_secret(name: str) -> str | None:
    """Return secret value if Streamlit Secrets are available (Cloud or local file)."""
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
            # Local runs without secrets.toml raise once; remember and skip later.
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
    """Prefer Streamlit Secrets (Community Cloud), then OS env / .env."""
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
    if lower in {"none", "null", "n/a", "na", "test", "dummy"}:
        return True
    return False


def _sanitize_error(err: str, *, limit: int = 300) -> str:
    """Strip anything that looks like an API key from error text."""
    import re

    text = (err or "").strip()
    # Long token-like strings (API keys)
    text = re.sub(r"(?i)(api[_-]?key\s*[=:]\s*)\S+", r"\1[REDACTED]", text)
    text = re.sub(r"\bAIza[0-9A-Za-z_-]{20,}\b", "[REDACTED_KEY]", text)
    text = re.sub(r"\bAQ\.[A-Za-z0-9_-]{20,}\b", "[REDACTED_KEY]", text)
    text = re.sub(r"(?i)bearer\s+\S+", "Bearer [REDACTED]", text)
    return text[:limit]


def load_gemini_api_keys() -> list[str]:
    """
    Load up to 10 Gemini API keys.

    Order:
      1. GEMINI_API_KEY (legacy single-key)
      2. GEMINI_API_KEY_1 … GEMINI_API_KEY_10

    Empty values are ignored. Duplicates are removed (first wins).
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


def is_retryable_error(exc: BaseException) -> bool:
    text = str(exc).lower()
    if any(t in text for t in _AUTH_TOKENS):
        # Auth failures on one key should failover to the next key
        return True
    return any(t in text for t in _RETRYABLE_TOKENS)


@dataclass
class KeyManagerStats:
    total_keys: int = 0
    active_index: int = 0  # 0-based
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
    """Thread-safe multi-key Gemini client with failover."""

    keys: list[str] = field(default_factory=list)
    active_index: int = 0
    max_attempts: int = DEFAULT_MAX_ATTEMPTS
    timeout_sec: float = DEFAULT_TIMEOUT_SEC
    backoff_base_sec: float = DEFAULT_BACKOFF_BASE_SEC
    backoff_max_sec: float = DEFAULT_BACKOFF_MAX_SEC
    circuit_cooldown_sec: float = DEFAULT_CIRCUIT_COOLDOWN_SEC
    stats: KeyManagerStats = field(default_factory=KeyManagerStats)
    _lock: threading.RLock = field(default_factory=threading.RLock, repr=False)
    _circuit_open_until: float = field(default=0.0, repr=False)

    @classmethod
    def from_env(cls) -> "GeminiKeyManager":
        keys = load_gemini_api_keys()
        mgr = cls(
            keys=keys,
            active_index=0,
            max_attempts=_env_int("GEMINI_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS),
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
        mgr.stats.active_index = 0
        return mgr

    def reload(self) -> None:
        with self._lock:
            prev_count = len(self.keys)
            self.keys = load_gemini_api_keys()
            if self.active_index >= len(self.keys):
                self.active_index = 0
            self.max_attempts = _env_int("GEMINI_MAX_ATTEMPTS", DEFAULT_MAX_ATTEMPTS)
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
            # New keys added → allow Gemini again immediately
            if len(self.keys) != prev_count:
                self._circuit_open_until = 0.0
            try:
                from src.config import get_gemini_model

                self.stats.model_name = get_gemini_model()
            except Exception:
                pass

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
                try:
                    from src.config import get_gemini_model

                    self.stats.model_name = get_gemini_model()
                except Exception:
                    self.stats.model_name = "gemini-2.0-flash"
            return self.stats.to_dict()

    def _switch_to_next(self, reason: str) -> bool:
        """Advance active key. Returns False if no other key exists."""
        with self._lock:
            if len(self.keys) <= 1:
                return False
            prev = self.active_index
            self.active_index = (self.active_index + 1) % len(self.keys)
            self.stats.failovers += 1
            self.stats.active_index = self.active_index
            self.stats.last_failover_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
            safe_reason = _sanitize_error(reason)
            self.stats.last_error = safe_reason
            logger.warning(
                "Gemini failover: Key %s → Key %s of %s | total_keys=%s "
                "success=%s failed=%s failovers=%s | %s",
                prev + 1,
                self.active_index + 1,
                len(self.keys),
                len(self.keys),
                self.stats.successful_requests,
                self.stats.failed_requests,
                self.stats.failovers,
                safe_reason[:160],
            )
            return True

    def _build_model(self, api_key: str, model_name: str):
        import google.generativeai as genai

        genai.configure(api_key=api_key)
        return genai.GenerativeModel(model_name)

    def generate_content(
        self,
        prompt: str,
        *,
        model_name: str | None = None,
        on_key_used: Callable[[str], None] | None = None,
    ) -> str:
        """
        Generate content with automatic key failover + exponential backoff.

        Returns response text. Raises RuntimeError if all keys fail.
        """
        from src.config import get_gemini_model

        # Reload from env only when empty (allows tests / runtime injection).
        # Call get_key_manager() / has_gemini() to pick up newly added secrets.
        if not self.keys:
            self.reload()
        if not self.keys:
            raise RuntimeError(
                "No Gemini API keys configured. Set GEMINI_API_KEY or "
                "GEMINI_API_KEY_1…GEMINI_API_KEY_10 in .env / Streamlit Secrets."
            )

        with self._lock:
            if self._circuit_open_until and time.time() < self._circuit_open_until:
                remaining = int(self._circuit_open_until - time.time())
                raise RuntimeError(
                    "All Gemini API keys failed recently. "
                    f"Using fallbacks for ~{max(remaining, 1)}s to keep the app responsive. "
                    f"Last error: {self.stats.last_error or 'unavailable'}"
                )

        model_name = (model_name or get_gemini_model()).strip() or "gemini-2.0-flash"
        with self._lock:
            self.stats.model_name = model_name
        last_error: Exception | None = None
        attempts = max(1, min(self.max_attempts, max(len(self.keys) * 2, 2)))

        for attempt in range(attempts):
            with self._lock:
                idx = self.active_index
                key = self.keys[idx]
                n_keys = len(self.keys)
                label = f"Key {idx + 1} of {n_keys}"

            logger.info(
                "Gemini attempt %s/%s using %s (model=%s, total_keys=%s)",
                attempt + 1,
                attempts,
                label,
                model_name,
                n_keys,
            )

            if on_key_used:
                try:
                    on_key_used(label)
                except Exception:
                    pass

            try:
                text = self._generate_once(key, model_name, prompt)
                with self._lock:
                    self.stats.successful_requests += 1
                    self.stats.last_success_at = time.strftime(
                        "%Y-%m-%d %H:%M:%S UTC", time.gmtime()
                    )
                    self.stats.active_index = idx
                    self.stats.model_name = model_name
                    self._circuit_open_until = 0.0
                logger.info(
                    "Gemini success with %s | success=%s failed=%s failovers=%s",
                    label,
                    self.stats.successful_requests,
                    self.stats.failed_requests,
                    self.stats.failovers,
                )
                return text
            except Exception as exc:
                last_error = exc
                err = _sanitize_error(str(exc))
                with self._lock:
                    self.stats.failed_requests += 1
                    self.stats.last_error = err

                if not is_retryable_error(exc):
                    logger.warning("Gemini non-standard error on %s: %s", label, err[:200])

                switched = self._switch_to_next(err)
                backoff = min(
                    self.backoff_max_sec,
                    self.backoff_base_sec * (2**attempt),
                )
                if attempt < attempts - 1:
                    logger.info(
                        "Retrying Gemini request (attempt %s/%s) after %.1fs; %s",
                        attempt + 2,
                        attempts,
                        backoff,
                        "switched key" if switched else "same/only key",
                    )
                    time.sleep(backoff)

        safe_last = _sanitize_error(str(last_error))
        with self._lock:
            cooldown = max(15.0, float(self.circuit_cooldown_sec or DEFAULT_CIRCUIT_COOLDOWN_SEC))
            self._circuit_open_until = time.time() + cooldown
            self.stats.last_error = safe_last
        logger.error(
            "All Gemini keys failed — opening circuit for %.0fs (fallbacks active)",
            cooldown,
        )
        raise RuntimeError(
            "All Gemini API keys failed after retries. "
            f"Last error: {safe_last}. "
            "Check quotas / key validity in Google AI Studio."
        )

    def _generate_once(self, api_key: str, model_name: str, prompt: str) -> str:
        from concurrent.futures import ThreadPoolExecutor, TimeoutError as FuturesTimeout

        def _call() -> str:
            model = self._build_model(api_key, model_name)
            response = model.generate_content(prompt)
            return (response.text or "").strip()

        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(_call)
            try:
                return future.result(timeout=self.timeout_sec)
            except FuturesTimeout as exc:
                raise TimeoutError(
                    f"Gemini request timed out after {self.timeout_sec:.0f}s"
                ) from exc


_MANAGER: GeminiKeyManager | None = None
_MANAGER_LOCK = threading.Lock()


def get_key_manager() -> GeminiKeyManager:
    global _MANAGER
    with _MANAGER_LOCK:
        if _MANAGER is None:
            _MANAGER = GeminiKeyManager.from_env()
        else:
            _MANAGER.reload()
        return _MANAGER


def generate_with_failover(prompt: str, *, model_name: str | None = None) -> str:
    """Module-level helper used by analysis / chatbot / discovery."""
    return get_key_manager().generate_content(prompt, model_name=model_name)


def gemini_status() -> dict[str, Any]:
    return get_key_manager().get_stats()


def gemini_active_label() -> str:
    return get_key_manager().active_key_label()
