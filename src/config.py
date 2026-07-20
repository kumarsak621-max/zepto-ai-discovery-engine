"""Central configuration loaded from environment / Streamlit secrets."""

from __future__ import annotations

import logging
import os

from dotenv import load_dotenv

from src.paths import DATA_DIR, DATABASE_DIR, ROOT_DIR, ensure_runtime_dirs, resolve_under_root

logger = logging.getLogger(__name__)

load_dotenv(ROOT_DIR / ".env")
load_dotenv()


_SECRETS_AVAILABLE: bool | None = None


def _secret_or_env(name: str, default: str = "") -> str:
    """Prefer Streamlit secrets (Community Cloud), then OS env, then default."""
    global _SECRETS_AVAILABLE
    if _SECRETS_AVAILABLE is not False:
        try:
            import streamlit as st

            secrets = getattr(st, "secrets", None)
            if secrets is not None:
                try:
                    value = secrets.get(name)
                    _SECRETS_AVAILABLE = True
                    if value is not None and str(value).strip() != "":
                        return str(value).strip()
                except Exception:
                    _SECRETS_AVAILABLE = False
        except Exception:
            _SECRETS_AVAILABLE = False
    value = os.getenv(name, default)
    return (value or default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _secret_or_env(name, "")
    if raw is None or str(raw).strip() == "":
        return default
    try:
        return int(str(raw).strip())
    except ValueError:
        logger.warning(
            "Invalid integer for %s=%r — using default %s", name, raw, default
        )
        return default


def _env_str(name: str, default: str = "") -> str:
    return _secret_or_env(name, default)


try:
    ensure_runtime_dirs()
except OSError as exc:
    logger.warning("Could not create runtime directories: %s", exc)

_db_override = _env_str("DATABASE_PATH", "")
DATABASE_PATH = (
    resolve_under_root(_db_override)
    if _db_override
    else (DATABASE_DIR / "feedback.db")
)

COLLECTION_NAME = "zepto_customer_feedback"


def get_gemini_api_keys() -> list[str]:
    """
    All configured Gemini API keys (up to 10).

    Supports legacy GEMINI_API_KEY plus GEMINI_API_KEY_1 … GEMINI_API_KEY_10
    from Streamlit Secrets or environment / .env.
    """
    from src.gemini_key_manager import load_gemini_api_keys

    return load_gemini_api_keys()


def get_gemini_api_key() -> str:
    """
    Active / primary Gemini API key (backward compatible).

    Prefers the key manager's active key when available, else the first loaded key.
    """
    try:
        from src.gemini_key_manager import get_key_manager

        mgr = get_key_manager()
        if mgr.has_keys():
            return mgr.get_active_key()
    except Exception:
        pass
    keys = get_gemini_api_keys()
    return keys[0] if keys else ""


def get_gemini_model() -> str:
    """Gemini model name from Streamlit Secrets, then env / .env."""
    model = _secret_or_env("GEMINI_MODEL", "")
    return (model or "gemini-flash-latest").strip() or "gemini-flash-latest"


# Public config values used across the app (never hardcode secrets)
GEMINI_API_KEY = get_gemini_api_key()
GEMINI_MODEL = get_gemini_model()
GEMINI_API_KEYS = get_gemini_api_keys()

TWITTER_BEARER_TOKEN = _env_str("TWITTER_BEARER_TOKEN", "")

PLAYSTORE_APP_ID = _env_str("PLAYSTORE_APP_ID", "com.zeptoconsumerapp")
PLAYSTORE_APP_NAME = "Zepto: Groceries in minutes"
PLAYSTORE_REVIEW_COUNT = _env_int("PLAYSTORE_REVIEW_COUNT", 500)
PLAYSTORE_CACHE_TTL_HOURS = _env_int("PLAYSTORE_CACHE_TTL_HOURS", 6)

# Apple App Store (iTunes RSS) — Zepto: Groceries in minutes
APPSTORE_APP_ID = _env_str("APPSTORE_APP_ID", "1575323645")
APPSTORE_COUNTRY = _env_str("APPSTORE_COUNTRY", "in")
APPSTORE_REVIEW_COUNT = _env_int("APPSTORE_REVIEW_COUNT", 200)
APPSTORE_ENABLED = _env_str("APPSTORE_ENABLED", "1").lower() not in {
    "0",
    "false",
    "no",
    "off",
}

DAILY_SCHEDULE_HOUR = _env_int("DAILY_SCHEDULE_HOUR", 6)
LIVE_CACHE_TTL_HOURS = _env_int("LIVE_CACHE_TTL_HOURS", 6)

REVIEWS_CSV_PATH = DATA_DIR / "reviews.csv"
LIVE_META_PATH = DATA_DIR / "live_reviews_meta.json"

LIVE_CHAT_SOURCES = ("playstore", "appstore")

THEME_TAXONOMY = [
    "Product discovery issue",
    "Category awareness",
    "Trust issue",
    "Pricing concern",
    "Delivery experience",
    "Habitual buying",
    "App usability",
    "Product quality",
    "Customer support",
    "Other",
]

INTENT_TAXONOMY = ["Complaint", "Suggestion", "Question", "Appreciation"]

SENTIMENT_VALUES = ["Positive", "Negative", "Neutral"]

CUSTOMER_SEGMENTS = [
    "Price-sensitive shoppers",
    "Convenience-first users",
    "Health-conscious users",
    "Premium shoppers",
    "Frequent buyers",
    "Impulse shoppers",
    "Occasional buyers",
    # Legacy labels kept for already-analyzed reviews
    "Habitual grocery buyer",
    "Price-sensitive shopper",
    "Quality / trust conscious",
    "New category explorer",
    "Convenience seeker",
    "Comparison shopper",
    "Support-frustrated user",
    "General shopper",
]

EXPLORATION_BARRIER_THEMES = [
    "Product discovery issue",
    "Category awareness",
    "Trust issue",
    "Pricing concern",
]


def has_gemini() -> bool:
    """True when at least one Gemini API key is available (Secrets or .env)."""
    global GEMINI_API_KEY, GEMINI_MODEL, GEMINI_API_KEYS
    GEMINI_API_KEYS = get_gemini_api_keys()
    GEMINI_MODEL = get_gemini_model()
    # Prefer the currently active failover key when the manager is available
    try:
        GEMINI_API_KEY = get_gemini_api_key()
    except Exception:
        GEMINI_API_KEY = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
    return bool(GEMINI_API_KEYS)


def has_appstore() -> bool:
    return bool(APPSTORE_ENABLED and APPSTORE_APP_ID)


def validate_runtime_config() -> list[str]:
    warnings: list[str] = []
    try:
        ensure_runtime_dirs()
    except OSError as exc:
        warnings.append(f"Cannot create data/output/cache folders: {exc}")

    if not has_gemini():
        warnings.append(
            "No Gemini API key set. Add GEMINI_API_KEY or GEMINI_API_KEY_1…_10 "
            "in Streamlit Cloud Secrets / .env. Analysis and chatbot will use "
            "rule-based fallbacks until then."
        )
    else:
        n = len(get_gemini_api_keys())
        if n > 1:
            warnings.append(
                f"{n} Gemini API keys loaded — automatic failover is enabled."
            )
    try:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.append(
            f"Cannot create database directory {DATABASE_PATH.parent}: {exc}"
        )
    return warnings
