"""
Social Media Data Module — Twitter/X API placeholder.

Supports the interface for:
- keyword search
- sentiment analysis hooks
- conversation extraction

Wire TWITTER_BEARER_TOKEN when X API access is available.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.config import TWITTER_BEARER_TOKEN
from src.database import clean_text

logger = logging.getLogger(__name__)

DEFAULT_KEYWORDS = [
    "Zepto",
    "Zepto app",
    "Zepto review",
    "quick commerce Zepto",
    "Blinkit vs Zepto",
]


class TwitterCollector:
    """Placeholder collector for Twitter/X customer conversations."""

    def __init__(self, bearer_token: str | None = None):
        self.bearer_token = bearer_token or TWITTER_BEARER_TOKEN
        self.enabled = bool(self.bearer_token and self.bearer_token.strip())

    def is_configured(self) -> bool:
        return self.enabled

    def search_keywords(
        self,
        keywords: list[str] | None = None,
        max_results: int = 50,
    ) -> list[dict[str, Any]]:
        """
        Search recent tweets by keyword.

        Currently a stub — returns [] until TWITTER_BEARER_TOKEN is set
        and the live API client is implemented.
        """
        keywords = keywords or DEFAULT_KEYWORDS
        if not self.enabled:
            logger.info(
                "Twitter/X module is a placeholder. Set TWITTER_BEARER_TOKEN to enable."
            )
            return []

        # Future: use tweepy / requests against Twitter API v2 recent search
        logger.warning(
            "Twitter/X API client not yet wired. Keywords requested: %s (max=%s)",
            keywords,
            max_results,
        )
        return []

    def extract_conversations(
        self, conversation_id: str
    ) -> list[dict[str, Any]]:
        """Extract a conversation thread by ID (placeholder)."""
        if not self.enabled:
            return []
        logger.warning(
            "Conversation extraction not implemented yet for id=%s", conversation_id
        )
        return []

    def analyze_sentiment_placeholder(
        self, texts: list[str]
    ) -> list[dict[str, str]]:
        """
        Lightweight local sentiment stub for social posts.
        Production path should use Gemini via gemini_analysis.py.
        """
        results = []
        for text in texts:
            lower = text.lower()
            if any(w in lower for w in ("love", "great", "awesome", "best")):
                sentiment = "Positive"
            elif any(w in lower for w in ("hate", "worst", "scam", "delay", "refund")):
                sentiment = "Negative"
            else:
                sentiment = "Neutral"
            results.append({"text": text, "sentiment": sentiment})
        return results

    def normalize_tweet(self, tweet: dict[str, Any]) -> dict[str, Any]:
        """Normalize a raw tweet payload into the shared review schema."""
        text = clean_text(tweet.get("text") or "")
        created = tweet.get("created_at") or datetime.now(timezone.utc).isoformat()
        return {
            "source": "twitter",
            "text": text,
            "rating": None,
            "date": created,
            "category": "social",
            "sentiment": None,
            "theme": None,
            "user_intent": None,
            "app_version": None,
            "title": tweet.get("conversation_id"),
            "upvotes": tweet.get("public_metrics", {}).get("like_count")
            if isinstance(tweet.get("public_metrics"), dict)
            else tweet.get("like_count"),
            "external_id": f"tweet_{tweet.get('id')}",
        }


def collect_twitter_mentions(
    keywords: list[str] | None = None,
    max_results: int = 50,
) -> list[dict[str, Any]]:
    """Module-level entrypoint used by the data pipeline."""
    collector = TwitterCollector()
    return collector.search_keywords(keywords=keywords, max_results=max_results)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    tc = TwitterCollector()
    print(f"Configured: {tc.is_configured()}")
    print(f"Results: {len(collect_twitter_mentions())}")
