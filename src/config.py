"""Central configuration loaded from environment / Streamlit secrets."""

from __future__ import annotations

import logging
import os
from pathlib import Path

from dotenv import load_dotenv

logger = logging.getLogger(__name__)

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")
# Also support platform env without .env file
load_dotenv()


def _secret_or_env(name: str, default: str = "") -> str:
    """Prefer Streamlit secrets (Community Cloud), then OS env, then default."""
    try:
        import streamlit as st

        if hasattr(st, "secrets") and name in st.secrets:
            value = st.secrets.get(name)
            if value is not None and str(value).strip() != "":
                return str(value).strip()
    except Exception:
        # Outside Streamlit, or secrets not configured yet
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


DATABASE_PATH = Path(
    _env_str("DATABASE_PATH", str(ROOT_DIR / "database" / "feedback.db"))
)
COLLECTION_NAME = "zepto_customer_feedback"

GEMINI_API_KEY = _env_str("GEMINI_API_KEY", "")
GEMINI_MODEL = _env_str("GEMINI_MODEL", "gemini-2.0-flash")

REDDIT_CLIENT_ID = _env_str("REDDIT_CLIENT_ID", "")
REDDIT_SECRET = _env_str("REDDIT_SECRET", "")
REDDIT_USER_AGENT = _env_str(
    "REDDIT_USER_AGENT", "zepto_ai_engine/1.0 by ZeptoPMResearch"
)

TWITTER_BEARER_TOKEN = _env_str("TWITTER_BEARER_TOKEN", "")

PLAYSTORE_APP_ID = _env_str("PLAYSTORE_APP_ID", "com.zeptoconsumerapp")
PLAYSTORE_APP_NAME = "Zepto: Groceries in minutes"
PLAYSTORE_REVIEW_COUNT = _env_int("PLAYSTORE_REVIEW_COUNT", 100)
REDDIT_POST_LIMIT = _env_int("REDDIT_POST_LIMIT", 50)
DAILY_SCHEDULE_HOUR = _env_int("DAILY_SCHEDULE_HOUR", 6)

# Server bind (used by app.py launcher / Procfile / Railway)
HOST = _env_str("HOST", "0.0.0.0")
PORT = _env_int("PORT", 8000)

REDDIT_SUBREDDITS = [
    "india",
    "IndianFood",
    "IndianGaming",
    "bangalore",
    "mumbai",
    "delhi",
]

REDDIT_KEYWORDS = [
    "Zepto",
    "quick commerce",
    "Zepto experience",
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
    return bool(GEMINI_API_KEY and GEMINI_API_KEY != "your_gemini_api_key_here")


def has_reddit() -> bool:
    return bool(
        REDDIT_CLIENT_ID
        and REDDIT_CLIENT_ID != "your_reddit_client_id"
        and REDDIT_SECRET
        and REDDIT_SECRET != "your_reddit_secret"
    )


def validate_runtime_config() -> list[str]:
    """
    Return human-readable warnings for missing optional config.
    Never raises — callers display warnings instead of crashing.
    """
    warnings: list[str] = []
    if not has_gemini():
        warnings.append(
            "GEMINI_API_KEY is not set. Analysis and chatbot will use rule-based "
            "fallbacks until you add the key in Streamlit Cloud Secrets / .env."
        )
    if not has_reddit():
        warnings.append(
            "Reddit credentials are optional. Set REDDIT_CLIENT_ID and REDDIT_SECRET "
            "in Streamlit Cloud Secrets to enable Reddit collection."
        )
    try:
        DATABASE_PATH.parent.mkdir(parents=True, exist_ok=True)
    except OSError as exc:
        warnings.append(
            f"Cannot create database directory {DATABASE_PATH.parent}: {exc}"
        )
    return warnings
