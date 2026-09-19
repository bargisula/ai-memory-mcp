"""Command line: `ai-memory <command>`. Useful for hooks, scripts and diagnosing problems."""
import argparse
import json
import sqlite3
import sys

from . import __version__, config, embed, index, store


def _print_json(data) -> None:
    print(json.dumps(data, ensure_ascii=False, indent=2))


def cmd_serve(_args) -> int:
    from .server import main as serve

    serve()
    return 0


def cmd_reindex(args) -> int:
    result = index.reindex(embed_missing=args.embed)
    print(f"indexed {result['indexed']} notes, embedded {result['embedded']} new")
    for rel in result["skipped"]:
        print(f"skipped (no memory frontmatter): {rel}", file=sys.stderr)
    return 0


def cmd_handoff(args) -> int:
    try:
        store.validate_project(args.project)
    except store.MemoryInputError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    for item in index.get_handoff(args.project, limit=args.limit):
        print(f"# {item['title']}  ({item['ts']}, {item['llm'] or 'unknown'})\n\n{item['content']}\n")
    return 0


def cmd_search(args) -> int:
    _print_json(index.search(args.query, project=args.project, limit=args.limit))
    return 0


def cmd_audit(args) -> int:
    _print_json(index.audit_log(limit=args.limit))
    return 0


def cmd_web(args) -> int:
    from .web import serve

    return serve(port=args.port, open_browser=not args.no_browser)


def cmd_doctor(_args) -> int:
    failed = False

    def report(level: str, message: str) -> None:
        nonlocal failed
        failed = failed or level == "fail"
        print(f"[{level:>4}] {message}")

    print(f"ai-memory {__version__}, data directory: {config.home()}")
    report("ok", f"python {sys.version.split()[0]}, sqlite {sqlite3.sqlite_version}")

    try:
        probe = sqlite3.connect(":memory:")
        probe.execute("CREATE VIRTUAL TABLE t USING fts5(x, tokenize='trigram')")
        report("ok", "SQLite FTS5 trigram available (substring search works for all languages)")
    except sqlite3.OperationalError:
        report("warn", "SQLite lacks FTS5 trigram; search falls back to slower LIKE scans")

    try:
        config.home().mkdir(parents=True, exist_ok=True)
        marker = config.home() / ".write-test"
        marker.write_text("ok", encoding="utf-8")
        marker.unlink()
        report("ok", "data directory is writable")
    except OSError as exc:
        report("fail", f"data directory not writable: {exc}")
        return 1

    stats = index.stats()
    if stats["notes_on_disk"] == stats["notes_indexed"]:
        report("ok", f"{stats['notes_indexed']} notes on disk, all indexed")
    else:
        report("warn", f"{stats['notes_on_disk']} .md files on disk but {stats['notes_indexed']} indexed; "
                       "run `ai-memory reindex` (files without memory frontmatter are skipped)")

    if not config.embeddings_enabled():
        report("info", "embeddings disabled (AI_MEMORY_EMBEDDINGS=off); search_memory_semantic unavailable")
    elif embed.embed("doctor check") is not None:
        report("ok", f"embeddings ready ({config.embed_model()}), {stats['embeddings']} stored")
    else:
        report("info", f"Ollama/{config.embed_model()} not reachable at {config.embed_url()}; "
                       "optional, only search_memory_semantic needs it")

    report("ok", f"allowed types: {', '.join(config.valid_types())}")
    return 1 if failed else 0


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass

    parser = argparse.ArgumentParser(prog="ai-memory", description="Local Markdown-first memory for AI agents.")
    parser.add_argument("--version", action="version", version=f"ai-memory {__version__}")
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("serve", help="run the MCP server over stdio (default)").set_defaults(func=cmd_serve)

    p = sub.add_parser("reindex", help="rebuild the search index from the Markdown notes")
    p.add_argument("--embed", action="store_true", help="also compute missing embeddings via Ollama")
    p.set_defaults(func=cmd_reindex)

    p = sub.add_parser("handoff", help="print the newest handoff notes for a project (handy in hooks)")
    p.add_argument("project")
    p.add_argument("--limit", type=int, default=1)
    p.set_defaults(func=cmd_handoff)

    p = sub.add_parser("search", help="keyword search, prints JSON")
    p.add_argument("query")
    p.add_argument("--project", default="")
    p.add_argument("--limit", type=int, default=10)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("audit", help="show the read audit log as JSON")
    p.add_argument("--limit", type=int, default=50)
    p.set_defaults(func=cmd_audit)

    p = sub.add_parser("web", help="open a read-only local page for browsing the audit log")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--no-browser", action="store_true", help="do not open a browser tab")
    p.set_defaults(func=cmd_web)

    sub.add_parser("doctor", help="check the installation").set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return (args.func if args.command else cmd_serve)(args)


if __name__ == "__main__":
    sys.exit(main())
