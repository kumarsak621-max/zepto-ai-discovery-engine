"""Project path helpers — always relative to repo root (Linux / Streamlit Cloud safe)."""

from __future__ import annotations

from pathlib import Path

# Repo root (parent of src/)
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = ROOT_DIR / "data"
OUTPUT_DIR = ROOT_DIR / "output"
CACHE_DIR = ROOT_DIR / "cache"
DATABASE_DIR = ROOT_DIR / "database"


def ensure_runtime_dirs() -> None:
    """Create data / output / cache / database folders if missing."""
    for path in (DATA_DIR, OUTPUT_DIR, CACHE_DIR, DATABASE_DIR):
        path.mkdir(parents=True, exist_ok=True)


def resolve_under_root(path_value: str | Path) -> Path:
    """
    Resolve a path relative to the project root.
    Absolute paths are kept as-is (for advanced local overrides).
    """
    path = Path(path_value)
    if path.is_absolute():
        return path
    return (ROOT_DIR / path).resolve()
