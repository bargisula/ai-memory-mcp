import pytest


@pytest.fixture(autouse=True)
def memory_home(tmp_path, monkeypatch):
    """Every test gets its own empty data directory and never touches Ollama."""
    home = tmp_path / "home"
    monkeypatch.setenv("AI_MEMORY_HOME", str(home))
    monkeypatch.setenv("AI_MEMORY_EMBEDDINGS", "off")
    monkeypatch.delenv("AI_MEMORY_TYPES", raising=False)
    return home
