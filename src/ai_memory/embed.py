"""Optional embeddings via a local Ollama server. Every failure degrades to None."""
import json
import urllib.error
import urllib.request

from . import config

_MAX_CHARS = 2000


def embed(text: str) -> list[float] | None:
    if not config.embeddings_enabled():
        return None
    try:
        req = urllib.request.Request(
            config.embed_url(),
            data=json.dumps({"model": config.embed_model(), "prompt": text[:_MAX_CHARS]}).encode("utf-8"),
            headers={"Content-Type": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            vec = json.loads(resp.read()).get("embedding")
            return vec if isinstance(vec, list) and vec else None
    except (urllib.error.URLError, OSError, ValueError):
        return None


def cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return 0.0 if na == 0 or nb == 0 else dot / (na * nb)
