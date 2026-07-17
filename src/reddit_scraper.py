"""Reddit discussion collector for Zepto / quick commerce insights."""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from src.config import (
    REDDIT_CLIENT_ID,
    REDDIT_KEYWORDS,
    REDDIT_POST_LIMIT,
    REDDIT_SECRET,
    REDDIT_SUBREDDITS,
    REDDIT_USER_AGENT,
    has_reddit,
)
from src.database import clean_text

logger = logging.getLogger(__name__)


def _get_reddit_client():
    if not has_reddit():
        raise RuntimeError(
            "Reddit credentials missing. Set REDDIT_CLIENT_ID and REDDIT_SECRET in .env"
        )
    import praw

    return praw.Reddit(
        client_id=REDDIT_CLIENT_ID,
        client_secret=REDDIT_SECRET,
        user_agent=REDDIT_USER_AGENT,
    )


def _ts_to_iso(created_utc: float | None) -> str:
    if not created_utc:
        return datetime.now(timezone.utc).isoformat()
    return datetime.fromtimestamp(created_utc, tz=timezone.utc).isoformat()


def collect_reddit_discussions(
    subreddits: list[str] | None = None,
    keywords: list[str] | None = None,
    limit: int | None = None,
    include_comments: bool = True,
    max_comments_per_post: int = 15,
) -> list[dict[str, Any]]:
    """
    Search subreddits for Zepto / quick commerce discussions.

    Stores post titles, comment text, dates, and upvotes.
    """
    subreddits = subreddits or REDDIT_SUBREDDITS
    keywords = keywords or REDDIT_KEYWORDS
    limit = limit or REDDIT_POST_LIMIT

    reddit = _get_reddit_client()
    collected: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for keyword in keywords:
        query = keyword
        logger.info("Searching Reddit for '%s' across %s", query, subreddits)
        try:
            for submission in reddit.subreddit("+".join(subreddits)).search(
                query, sort="new", limit=limit, time_filter="year"
            ):
                post_id = f"post_{submission.id}"
                if post_id in seen_ids:
                    continue
                seen_ids.add(post_id)

                title = clean_text(submission.title or "")
                body = clean_text(submission.selftext or "")
                combined = f"{title}. {body}".strip() if body else title
                if not combined:
                    continue

                collected.append(
                    {
                        "source": "reddit",
                        "text": combined,
                        "rating": None,
                        "date": _ts_to_iso(getattr(submission, "created_utc", None)),
                        "category": "discussion",
                        "sentiment": None,
                        "theme": None,
                        "user_intent": None,
                        "app_version": None,
                        "title": title,
                        "upvotes": int(getattr(submission, "score", 0) or 0),
                        "external_id": post_id,
                    }
                )

                if not include_comments:
                    continue

                try:
                    submission.comments.replace_more(limit=0)
                    for comment in submission.comments.list()[:max_comments_per_post]:
                        comment_id = f"comment_{comment.id}"
                        if comment_id in seen_ids:
                            continue
                        body_c = clean_text(getattr(comment, "body", "") or "")
                        if not body_c or body_c in {"[deleted]", "[removed]"}:
                            continue
                        # Keep Zepto-relevant comments preferentially
                        lower = body_c.lower()
                        if not any(
                            k.lower() in lower
                            for k in (
                                "zepto",
                                "blinkit",
                                "instamart",
                                "grocery",
                                "delivery",
                                "quick commerce",
                            )
                        ):
                            # still keep high-upvote thread replies under Zepto posts
                            if int(getattr(comment, "score", 0) or 0) < 3:
                                continue

                        seen_ids.add(comment_id)
                        collected.append(
                            {
                                "source": "reddit",
                                "text": body_c,
                                "rating": None,
                                "date": _ts_to_iso(
                                    getattr(comment, "created_utc", None)
                                ),
                                "category": "comment",
                                "sentiment": None,
                                "theme": None,
                                "user_intent": None,
                                "app_version": None,
                                "title": title,
                                "upvotes": int(getattr(comment, "score", 0) or 0),
                                "external_id": comment_id,
                            }
                        )
                except Exception as exc:
                    logger.warning(
                        "Failed to load comments for %s: %s", submission.id, exc
                    )
        except Exception as exc:
            logger.error("Reddit search failed for '%s': %s", keyword, exc)

    logger.info("Collected %s Reddit items", len(collected))
    return collected


def collect_reddit_or_empty(**kwargs) -> list[dict[str, Any]]:
    """Safe wrapper — returns [] when credentials are missing."""
    if not has_reddit():
        logger.warning("Skipping Reddit collection — credentials not configured")
        return []
    try:
        return collect_reddit_discussions(**kwargs)
    except Exception as exc:
        logger.error("Reddit collection error: %s", exc)
        return []


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    rows = collect_reddit_or_empty(limit=5, include_comments=False)
    for row in rows[:5]:
        print(f"[{row.get('upvotes')}] {row['title'][:80]}")
