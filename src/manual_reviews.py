"""Manual CSV / Excel review upload — column detection and normalization."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path
from typing import Any, BinaryIO

import pandas as pd

from src.database import clean_text
from src.paths import DATA_DIR, ensure_runtime_dirs

logger = logging.getLogger(__name__)

MANUAL_REVIEWS_PATH = DATA_DIR / "manual_reviews.csv"
MANUAL_META_PATH = DATA_DIR / "manual_reviews_meta.json"

# Preferred column aliases (lowercase, stripped)
_TEXT_ALIASES = (
    "review_text",
    "text",
    "content",
    "review",
    "comment",
    "body",
    "feedback",
    "message",
    "description",
)
_RATING_ALIASES = ("rating", "score", "stars", "star", "rate")
_DATE_ALIASES = ("date", "review_date", "created_at", "timestamp", "time", "posted_at")
_SOURCE_ALIASES = ("source", "platform", "channel", "store")
_ID_ALIASES = ("review_id", "id", "external_id", "reviewid", "uid")


def _norm_col(name: Any) -> str:
    return str(name or "").strip().lower().replace(" ", "_")


def _find_column(columns: list[str], aliases: tuple[str, ...]) -> str | None:
    normalized = {_norm_col(c): c for c in columns}
    for alias in aliases:
        if alias in normalized:
            return normalized[alias]
    return None


def detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """Map logical fields to actual dataframe column names."""
    cols = list(df.columns)
    return {
        "text": _find_column(cols, _TEXT_ALIASES),
        "rating": _find_column(cols, _RATING_ALIASES),
        "date": _find_column(cols, _DATE_ALIASES),
        "source": _find_column(cols, _SOURCE_ALIASES),
        "review_id": _find_column(cols, _ID_ALIASES),
    }


def _read_upload(file_bytes: bytes, filename: str) -> pd.DataFrame:
    name = (filename or "").lower()
    buffer = BytesIO(file_bytes)
    if name.endswith(".xlsx") or name.endswith(".xls"):
        return pd.read_excel(buffer)
    # Default / .csv
    try:
        return pd.read_csv(buffer)
    except UnicodeDecodeError:
        buffer.seek(0)
        return pd.read_csv(buffer, encoding="latin-1")


def parse_manual_reviews(
    file_bytes: bytes,
    filename: str = "upload.csv",
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """
    Parse CSV/Excel bytes into normalized review dicts.

    Returns (records, info) where info includes detected columns and counts.
    """
    df = _read_upload(file_bytes, filename)
    if df is None or df.empty:
        return [], {"error": "File is empty or could not be read.", "rows": 0}

    mapping = detect_columns(df)
    if not mapping["text"]:
        return [], {
            "error": (
                "Could not detect a review text column. "
                "Expected one of: review_text, text, content, review."
            ),
            "columns": list(df.columns),
            "detected": mapping,
            "rows": 0,
        }

    records: list[dict[str, Any]] = []
    text_col = mapping["text"]
    rating_col = mapping["rating"]
    date_col = mapping["date"]
    id_col = mapping["review_id"]
    # mapping["source"] is reported in info; uploads always use source="manual"

    for _, row in df.iterrows():
        raw_text = row.get(text_col)
        if pd.isna(raw_text):
            continue
        text = clean_text(str(raw_text))
        if len(text) < 15:
            continue

        rating = None
        if rating_col is not None:
            try:
                val = row.get(rating_col)
                if pd.notna(val):
                    rating = float(val)
            except (TypeError, ValueError):
                rating = None

        date_str = None
        if date_col is not None:
            val = row.get(date_col)
            if pd.notna(val):
                date_str = str(val).strip()
        if not date_str:
            date_str = datetime.now(timezone.utc).isoformat()

        external_id = None
        if id_col is not None:
            val = row.get(id_col)
            if pd.notna(val) and str(val).strip():
                external_id = f"manual:{str(val).strip()}"
        if not external_id:
            digest = hashlib.sha256(
                f"{text.lower()}|{rating}|{date_str}".encode("utf-8")
            ).hexdigest()[:16]
            external_id = f"manual:{digest}"

        records.append(
            {
                "source": "manual",
                "text": text,
                "rating": rating,
                "date": date_str,
                "category": None,
                "external_id": external_id,
                "review_id": external_id,
                "title": None,
                "upvotes": None,
            }
        )

    info = {
        "filename": filename,
        "rows_in_file": int(len(df)),
        "parsed_count": len(records),
        "detected": mapping,
        "columns": [str(c) for c in df.columns],
    }
    logger.info(
        "Parsed manual upload %s: %s/%s rows usable",
        filename,
        len(records),
        len(df),
    )
    return records, info


def save_manual_reviews(records: list[dict[str, Any]], *, filename: str = "") -> Path:
    """Persist normalized manual reviews for the next analysis run."""
    import json

    ensure_runtime_dirs()
    path = MANUAL_REVIEWS_PATH
    rows = [
        {
            "review_id": r.get("external_id") or r.get("review_id") or "",
            "review_text": r.get("text") or "",
            "rating": r.get("rating"),
            "date": r.get("date"),
            "source": r.get("source") or "manual",
        }
        for r in records
    ]
    pd.DataFrame(rows).to_csv(path, index=False, encoding="utf-8")
    meta = {
        "last_uploaded": datetime.now(timezone.utc).isoformat(),
        "count": len(rows),
        "filename": filename,
        "path": str(path),
    }
    MANUAL_META_PATH.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return path


def load_manual_reviews() -> list[dict[str, Any]]:
    """Load previously uploaded manual reviews from disk."""
    path = MANUAL_REVIEWS_PATH
    if not path.exists():
        return []
    try:
        df = pd.read_csv(path)
    except Exception as exc:
        logger.error("Failed to load manual reviews: %s", exc)
        return []

    out: list[dict[str, Any]] = []
    for _, row in df.iterrows():
        text = clean_text(str(row.get("review_text") or row.get("text") or ""))
        if len(text) < 15:
            continue
        rating = row.get("rating")
        try:
            rating_f = float(rating) if pd.notna(rating) else None
        except (TypeError, ValueError):
            rating_f = None
        date_val = row.get("date")
        date_str = (
            str(date_val)
            if pd.notna(date_val)
            else datetime.now(timezone.utc).isoformat()
        )
        rid = str(row.get("review_id") or row.get("external_id") or "").strip()
        out.append(
            {
                "source": "manual",
                "text": text,
                "rating": rating_f,
                "date": date_str,
                "category": None,
                "external_id": rid or None,
                "review_id": rid or None,
                "title": None,
                "upvotes": None,
            }
        )
    return out


def get_manual_meta() -> dict[str, Any]:
    import json

    if not MANUAL_META_PATH.exists():
        if MANUAL_REVIEWS_PATH.exists():
            try:
                df = pd.read_csv(MANUAL_REVIEWS_PATH)
                return {"count": len(df), "last_uploaded": None, "filename": ""}
            except Exception:
                return {}
        return {}
    try:
        return json.loads(MANUAL_META_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def clear_manual_reviews() -> None:
    for path in (MANUAL_REVIEWS_PATH, MANUAL_META_PATH):
        try:
            if path.exists():
                path.unlink()
        except OSError as exc:
            logger.warning("Could not remove %s: %s", path, exc)


def parse_uploaded_file(uploaded_file: BinaryIO | Any) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Convenience wrapper for Streamlit UploadedFile objects."""
    filename = getattr(uploaded_file, "name", "upload.csv") or "upload.csv"
    raw = uploaded_file.read()
    if hasattr(uploaded_file, "seek"):
        try:
            uploaded_file.seek(0)
        except Exception:
            pass
    return parse_manual_reviews(raw, filename=filename)
