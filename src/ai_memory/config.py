"""Runtime configuration, read from environment variables on every call."""
import os
from pathlib import Path

DEFAULT_TYPES = ("decision", "progress", "failure", "handoff")


def home() -> Path:
    """Data directory. Holds notes/ (source of truth) and index.db (rebuildable)."""
    return Path(os.environ.get("AI_MEMORY_HOME") or Path.home() / ".ai-memory").expanduser()


def notes_dir() -> Path:
    return home() / "notes"


def db_path() -> Path:
    return home() / "index.db"


def valid_types() -> tuple[str, ...]:
    raw = os.environ.get("AI_MEMORY_TYPES", "")
    types = tuple(t.strip() for t in raw.split(",") if t.strip())
    return types or DEFAULT_TYPES


def embeddings_enabled() -> bool:
    return os.environ.get("AI_MEMORY_EMBEDDINGS", "on").strip().lower() not in {"off", "0", "false", "no"}


def embed_url() -> str:
    return os.environ.get("AI_MEMORY_EMBED_URL", "http://localhost:11434/api/embeddings")


def embed_model() -> str:
    return os.environ.get("AI_MEMORY_EMBED_MODEL", "nomic-embed-text")
