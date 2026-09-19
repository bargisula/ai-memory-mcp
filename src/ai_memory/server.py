"""MCP server (stdio). Thin layer: validation and error shaping live here, logic in store/index."""
from mcp.server.fastmcp import FastMCP

from . import config, index, store

INSTRUCTIONS = """\
Shared, persistent project memory that survives across sessions and across different AI tools.

- Before working on a project: call get_handoff(project), then search_memory(query, project) \
for earlier decisions and dead ends.
- After a meaningful decision -> record_memory(type="decision"). After hitting a dead end or a \
failed approach -> type="failure". When stopping or handing over -> type="handoff".
- Search results carry a short snippet; use read_memory(path) for the full text.
- Always pass your own name in `llm` so entries can be attributed.
"""

mcp = FastMCP("ai-memory", instructions=INSTRUCTIONS)


def _err(exc: Exception) -> dict:
    return {"error": str(exc)}


@mcp.tool()
def record_memory(project: str, type: str, title: str, content: str, llm: str = "", tags: str = "") -> dict:
    """
    Save one memory: a decision, progress update, failure, or handoff summary.

    project: project name; letters, digits, '_', '-', '.' only (e.g. "my-app")
    type: one of decision / progress / failure / handoff (configurable via AI_MEMORY_TYPES)
    title: one-line title
    content: the details; multi-paragraph Markdown is fine
    llm: who is writing this (e.g. "Claude", "Codex"); strongly recommended
    tags: comma-separated keywords, optional
    """
    try:
        note = store.write_note(project, type, title, content, llm=llm, tags=tags)
    except store.MemoryInputError as exc:
        return _err(exc)
    try:
        embedded = index.index_note(note)
    except Exception as exc:  # the Markdown file is already safe; only indexing failed
        return {"ok": True, "path": note.path, "ts": note.ts, "indexed": False,
                "warning": f"saved but not indexed ({exc}); run `ai-memory reindex`"}
    return {"ok": True, "path": note.path, "ts": note.ts, "indexed": True, "embedded": embedded}


@mcp.tool()
def search_memory(query: str, project: str = "", type: str = "", limit: int = 10, llm: str = "") -> list[dict]:
    """
    Keyword search over titles, content and tags. Every space-separated word must appear.
    Works for any language, including Chinese/Japanese substrings. Not FTS syntax: quotes and
    operators are treated as plain text.

    query: words to look for
    project: restrict to one project; empty searches all
    type: restrict to decision/progress/failure/handoff; empty searches all
    limit: max results (default 10, capped at 100)
    llm: your name, for the usage audit log
    """
    results = index.search(query, project=project, type_=type, limit=limit)
    index.audit("search_memory", llm=llm, project=project, query=query, result_count=len(results))
    return results


@mcp.tool()
def search_memory_semantic(query: str, project: str = "", limit: int = 5, llm: str = "") -> list[dict]:
    """
    Meaning-based search using local Ollama embeddings; finds related notes that share no keywords.
    Requires Ollama running with the nomic-embed-text model (see README); otherwise returns an
    error and you should use search_memory instead.

    query: a natural-language description
    project: restrict to one project; empty searches all
    limit: max results (default 5)
    llm: your name, for the usage audit log
    """
    results = index.semantic_search(query, project=project, limit=limit)
    if results is None:
        msg = "embeddings unavailable (Ollama not reachable, model missing, or AI_MEMORY_EMBEDDINGS=off)"
        index.audit("search_memory_semantic", llm=llm, project=project, query=query, ok=False, error=msg)
        return [{"error": f"{msg}; use search_memory instead"}]
    index.audit("search_memory_semantic", llm=llm, project=project, query=query, result_count=len(results))
    return results


@mcp.tool()
def read_memory(path: str, llm: str = "") -> dict:
    """
    Read one memory in full. `path` is the value returned by other tools, e.g. "my-app/2026-01-05-choose-db.md".
    """
    try:
        note = store.read_note(path)
    except store.MemoryInputError as exc:
        index.audit("read_memory", llm=llm, query=path, ok=False, error=str(exc))
        return _err(exc)
    index.audit("read_memory", llm=llm, project=note.project, query=path, result_count=1)
    return {"path": note.path, "project": note.project, "type": note.type, "llm": note.llm,
            "tags": note.tags, "ts": note.ts, "title": note.title, "content": note.content}


@mcp.tool()
def get_handoff(project: str, limit: int = 3, llm: str = "") -> list[dict]:
    """
    Newest handoff summaries for a project, with full content. Call this first when resuming work.

    project: project name
    limit: max summaries (default 3, newest first)
    llm: your name, for the usage audit log
    """
    results = index.get_handoff(project, limit=limit)
    index.audit("get_handoff", llm=llm, project=project, result_count=len(results))
    return results


@mcp.tool()
def recent(project: str = "", limit: int = 10, llm: str = "") -> list[dict]:
    """
    Latest memories of any type, newest first.

    project: restrict to one project; empty means all
    limit: max results (default 10)
    llm: your name, for the usage audit log
    """
    results = index.recent(project=project, limit=limit)
    index.audit("recent", llm=llm, project=project, result_count=len(results))
    return results


@mcp.tool()
def list_projects(llm: str = "") -> list[str]:
    """List every project that has at least one memory."""
    results = index.list_projects()
    index.audit("list_projects", llm=llm, result_count=len(results))
    return results


@mcp.tool()
def audit_usage(tool: str = "", llm: str = "", project: str = "", limit: int = 50) -> list[dict]:
    """Who read what and when (newest first). Search result contents are not logged."""
    return index.audit_log(tool=tool, llm=llm, project=project, limit=limit)


def main() -> None:
    config.home().mkdir(parents=True, exist_ok=True)
    mcp.run()


if __name__ == "__main__":
    main()
