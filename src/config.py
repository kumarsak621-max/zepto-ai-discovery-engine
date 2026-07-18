"""Central configuration loaded from environment / Streamlit secrets."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

from src.paths import DATA_DIR, DATABASE_DIR, ROOT_DIR, ensure_runtime_dirs, resolve_under_root

logger = logging.getLogger(__name__)

load_dotenv(ROOT_DIR / ".env")
load_dotenv()


def _secret_or_env(name: str, default: str = "") -> str:
    """Prefer Streamlit secrets (Community Cloud), then OS env, then default."""
    try:
        import streamlit as st

        secrets = getattr(st, "secrets", None)
        if secrets is not None:
            try:
                if name in secrets:
                    value = secrets.get(name)
                    if value is not None and str(value).strip() != "":
                        return str(value).strip()
            except Exception:
                pass
    except Exception:
        pass
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


def _first_env(*names: str, default: str = "") -> str:
    for name in names:
        value = _secret_or_env(name, "")
        if value:
            return value
    return default


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


def get_gemini_api_key() -> str:
    """
    Single source for the Gemini API key.

    Order:
      1. Streamlit Secrets — st.secrets.get("GEMINI_API_KEY", "")
      2. Environment / .env — os.getenv("GEMINI_API_KEY", "")
    """
    try:
        import streamlit as st

        key = st.secrets.get("GEMINI_API_KEY", "")
        if key is not None and str(key).strip():
            return str(key).strip()
    except Exception:
        # Outside Streamlit, or secrets not configured yet
        pass
    return (os.getenv("GEMINI_API_KEY", "") or "").strip()


def get_gemini_model() -> str:
    """Gemini model name from Streamlit Secrets, then env / .env."""
    try:
        import streamlit as st

        model = st.secrets.get("GEMINI_MODEL", "")
        if model is not None and str(model).strip():
            return str(model).strip()
    except Exception:
        pass
    return (os.getenv("GEMINI_MODEL", "") or "gemini-2.0-flash").strip() or "gemini-2.0-flash"


# Public config values used across the app (never hardcode secrets)
GEMINI_API_KEY = get_gemini_api_key()
GEMINI_MODEL = get_gemini_model()

REDDIT_CLIENT_ID = _env_str("REDDIT_CLIENT_ID", "")
REDDIT_CLIENT_SECRET = _first_env("REDDIT_CLIENT_SECRET", "REDDIT_SECRET", default="")
REDDIT_SECRET = REDDIT_CLIENT_SECRET
REDDIT_USER_AGENT = _env_str(
    "REDDIT_USER_AGENT", "zepto_ai_engine/1.0 by ZeptoPMResearch"
)
REDDIT_POST_LIMIT = _env_int("REDDIT_POST_LIMIT", 50)

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

LIVE_CHAT_SOURCES = ("playstore", "appstore", "reddit")

REDDIT_SUBREDDITS = [
    "india",
    "IndianFood",
    "bangalore",
    "mumbai",
    "delhi",
]

REDDIT_KEYWORDS = [
    "Zepto",
    "quick commerce",
    "Zepto review",
    "Blinkit vs Zepto",
    "online grocery shopping",
]

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
    """True when a non-empty Gemini API key is available (Secrets or .env)."""
    # Re-resolve so Streamlit Cloud Secrets work even if config imported early
    global GEMINI_API_KEY, GEMINI_MODEL
    GEMINI_API_KEY = get_gemini_api_key()
    GEMINI_MODEL = get_gemini_model()
    return bool(GEMINI_API_KEY.strip())


def has_reddit() -> bool:
    return bool(
        REDDIT_CLIENT_ID
        and REDDIT_CLIENT_ID != "your_reddit_client_id"
        and REDDIT_CLIENT_SECRET
        and REDDIT_CLIENT_SECRET
        not in {"your_reddit_secret", "your_reddit_client_secret"}
    )


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
            "GEMINI_API_KEY is not set. Analysis and chatbot will use rule-based "
            "fallbacks until you add the key in Streamlit Cloud Secrets / .env."
        )
    if not has_reddit():
        warnings.append("Reddit is not configured.")
    try:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.append(
            f"Cannot create database directory {DATABASE_PATH.parent}: {exc}"
        )
    return warnings
