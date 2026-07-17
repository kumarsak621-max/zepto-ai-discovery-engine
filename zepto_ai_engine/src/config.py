"""Central configuration loaded from environment variables."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parent.parent
load_dotenv(ROOT_DIR / ".env")

DATABASE_PATH = ROOT_DIR / "database" / "feedback.db"
COLLECTION_NAME = "zepto_customer_feedback"

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash")

REDDIT_CLIENT_ID = os.getenv("REDDIT_CLIENT_ID", "")
REDDIT_SECRET = os.getenv("REDDIT_SECRET", "")
REDDIT_USER_AGENT = os.getenv(
    "REDDIT_USER_AGENT", "zepto_ai_engine/1.0 by ZeptoPMResearch"
)

TWITTER_BEARER_TOKEN = os.getenv("TWITTER_BEARER_TOKEN", "")

PLAYSTORE_APP_ID = os.getenv("PLAYSTORE_APP_ID", "com.zeptoconsumerapp")
PLAYSTORE_APP_NAME = "Zepto: Groceries in minutes"
PLAYSTORE_REVIEW_COUNT = int(os.getenv("PLAYSTORE_REVIEW_COUNT", "100"))
REDDIT_POST_LIMIT = int(os.getenv("REDDIT_POST_LIMIT", "50"))
DAILY_SCHEDULE_HOUR = int(os.getenv("DAILY_SCHEDULE_HOUR", "6"))

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

# Themes that indicate barriers to exploring new categories (e.g. personal care)
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