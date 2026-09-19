"""SQLite index over the Markdown notes. Deleting index.db loses nothing: it is rebuilt from notes/."""
import hashlib
import json
import re
import sqlite3
from datetime import datetime, timezone

from . import config, embed, store

SNIPPET_CHARS = 300
_MAX_LIMIT = 100


def _digest(note: store.Note) -> str:
    return hashlib.sha1(f"{note.title}\n{note.content}".encode("utf-8")).hexdigest()


def _clamp(limit: int) -> int:
    return max(1, min(int(limit), _MAX_LIMIT))


def has_fts(conn: sqlite3.Connection) -> bool:
    return conn.execute("SELECT 1 FROM sqlite_master WHERE name = 'memory_fts'").fetchone() is not None


def _init_schema(conn: sqlite3.Connection) -> None:
    conn.execute("""
        CREATE TABLE IF NOT EXISTS memories (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            path TEXT NOT NULL UNIQUE,
            project TEXT NOT NULL,
            type TEXT NOT NULL,
            llm TEXT NOT NULL DEFAULT '',
            tags TEXT NOT NULL DEFAULT '',
            ts TEXT NOT NULL DEFAULT '',
            title TEXT NOT NULL,
            content TEXT NOT NULL
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_memories_project_ts ON memories(project, ts)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS embeddings (
            path TEXT PRIMARY KEY,
            digest TEXT NOT NULL,
            vector TEXT NOT NULL
        )
    """)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS usage_audit (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            ts TEXT NOT NULL,
            tool TEXT NOT NULL,
            llm TEXT NOT NULL DEFAULT '',
            project TEXT NOT NULL DEFAULT '',
            query TEXT NOT NULL DEFAULT '',
            result_count INTEGER NOT NULL DEFAULT 0,
            ok INTEGER NOT NULL DEFAULT 1,
            error TEXT NOT NULL DEFAULT ''
        )
    """)
    try:
        # trigram lets CJK text be searched by substring; the default tokenizer cannot.
        conn.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS memory_fts "
            "USING fts5(title, content, tags, tokenize='trigram')"
        )
    except sqlite3.OperationalError:
        pass  # SQLite without FTS5 trigram: search falls back to LIKE.


def connect() -> sqlite3.Connection:
    """Open the index, creating it (and rebuilding from notes/ if they already exist)."""
    config.home().mkdir(parents=True, exist_ok=True)
    fresh = not config.db_path().exists()
    conn = sqlite3.connect(config.db_path(), timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA busy_timeout=5000")
    _init_schema(conn)
    if fresh:
        _rebuild(conn, embed_missing=False)
    return conn


def _upsert(conn: sqlite3.Connection, note: store.Note) -> None:
    fts = has_fts(conn)
    row = conn.execute("SELECT id FROM memories WHERE path = ?", (note.path,)).fetchone()
    values = (note.project, note.type, note.llm, note.tags, note.ts, note.title, note.content)
    if row:
        rid = row["id"]
        conn.execute(
            "UPDATE memories SET project=?, type=?, llm=?, tags=?, ts=?, title=?, content=? WHERE id=?",
            (*values, rid),
        )
        if fts:
            conn.execute("DELETE FROM memory_fts WHERE rowid = ?", (rid,))
    else:
        rid = conn.execute(
            "INSERT INTO memories (project, type, llm, tags, ts, title, content, path) VALUES (?,?,?,?,?,?,?,?)",
            (*values, note.path),
        ).lastrowid
    if fts:
        conn.execute(
            "INSERT INTO memory_fts (rowid, title, content, tags) VALUES (?,?,?,?)",
            (rid, note.title, note.content, note.tags),
        )


def _store_embedding(conn: sqlite3.Connection, note: store.Note, vec: list[float]) -> None:
    conn.execute(
        "INSERT OR REPLACE INTO embeddings (path, digest, vector) VALUES (?,?,?)",
        (note.path, _digest(note), json.dumps(vec)),
    )


def index_note(note: store.Note) -> bool:
    """Index one freshly written note. Returns whether an embedding was stored."""
    vec = embed.embed(f"{note.title}\n{note.content}")
    conn = connect()
    try:
        # Take the write lock before reading, so check-then-insert cannot race another writer.
        conn.execute("BEGIN IMMEDIATE")
        _upsert(conn, note)
        if vec is not None:
            _store_embedding(conn, note, vec)
        conn.commit()
    finally:
        conn.close()
    return vec is not None


def _rebuild(conn: sqlite3.Connection, embed_missing: bool) -> dict:
    # The scan happens inside the write lock: any note whose file already exists is seen,
    # and a concurrent writer's index step lands either wholly before or wholly after this.
    conn.execute("BEGIN IMMEDIATE")
    try:
        notes = []
        skipped = []
        for rel in store.iter_note_paths():
            try:
                note = store.parse_note((config.notes_dir() / rel).read_text(encoding="utf-8"), rel)
            except (OSError, UnicodeDecodeError):
                note = None
            if note is None or not note.type:
                skipped.append(rel)
                continue
            notes.append(note)

        conn.execute("DELETE FROM memories")
        if has_fts(conn):
            conn.execute("DELETE FROM memory_fts")
        for note in notes:
            _upsert(conn, note)

        # Keep an embedding only while its note still exists with unchanged text.
        digests = {n.path: _digest(n) for n in notes}
        kept = {r["path"]: r["digest"] for r in conn.execute("SELECT path, digest FROM embeddings")}
        for path, digest in kept.items():
            if digests.get(path) != digest:
                conn.execute("DELETE FROM embeddings WHERE path = ?", (path,))
        have = {r["path"] for r in conn.execute("SELECT path FROM embeddings")}
        conn.commit()
    except BaseException:
        conn.rollback()
        raise

    # Embedding calls hit the network, so they run after the lock is released.
    embedded = 0
    if embed_missing:
        for note in notes:
            if note.path in have:
                continue
            vec = embed.embed(f"{note.title}\n{note.content}")
            if vec is not None:
                conn.execute("BEGIN IMMEDIATE")
                _store_embedding(conn, note, vec)
                conn.commit()
                embedded += 1
    return {"indexed": len(notes), "skipped": skipped, "embedded": embedded}


def reindex(embed_missing: bool = False) -> dict:
    """Rebuild the whole index from notes/. Safe to run any time, e.g. after hand-editing notes."""
    conn = connect()
    try:
        return _rebuild(conn, embed_missing)
    finally:
        conn.close()


def _snippet(content: str) -> str:
    flat = re.sub(r"\s+", " ", content).strip()
    return flat if len(flat) <= SNIPPET_CHARS else flat[:SNIPPET_CHARS].rstrip() + "…"


def _summary(row: sqlite3.Row) -> dict:
    return {
        "path": row["path"],
        "project": row["project"],
        "type": row["type"],
        "llm": row["llm"],
        "title": row["title"],
        "tags": row["tags"],
        "ts": row["ts"],
        "snippet": _snippet(row["content"]),
    }


def _full(row: sqlite3.Row) -> dict:
    d = _summary(row)
    del d["snippet"]
    d["content"] = row["content"]
    return d


def like_escape(token: str) -> str:
    return token.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def search(query: str, project: str = "", type_: str = "", limit: int = 10) -> list[dict]:
    """Substring search. Every whitespace-separated word must appear (AND). Input is never parsed as FTS syntax."""
    tokens = query.split()
    if not tokens:
        return []
    conn = connect()
    try:
        filters, params = "", []
        if project:
            filters += " AND memories.project = ?"
            params.append(project)
        if type_:
            filters += " AND memories.type = ?"
            params.append(type_)

        if has_fts(conn) and all(len(t) >= 3 for t in tokens):
            match = " AND ".join('"' + t.replace('"', '""') + '"' for t in tokens)
            rows = conn.execute(
                "SELECT memories.* FROM memory_fts JOIN memories ON memories.id = memory_fts.rowid "
                f"WHERE memory_fts MATCH ?{filters} ORDER BY memory_fts.rank LIMIT ?",
                (match, *params, _clamp(limit)),
            ).fetchall()
        else:
            like = ""
            like_params = []
            for t in tokens:
                like += " AND (title LIKE ? ESCAPE '\\' OR content LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')"
                pat = f"%{like_escape(t)}%"
                like_params += [pat, pat, pat]
            rows = conn.execute(
                f"SELECT * FROM memories WHERE 1=1{like}{filters.replace('memories.', '')} "
                "ORDER BY ts DESC LIMIT ?",
                (*like_params, *params, _clamp(limit)),
            ).fetchall()
        return [_summary(r) for r in rows]
    finally:
        conn.close()


def semantic_search(query: str, project: str = "", limit: int = 5) -> list[dict] | None:
    """Cosine similarity over stored embeddings. Returns None when embeddings are unavailable."""
    qvec = embed.embed(query)
    if qvec is None:
        return None
    conn = connect()
    try:
        sql = "SELECT memories.*, embeddings.vector FROM embeddings JOIN memories ON memories.path = embeddings.path"
        params: list = []
        if project:
            sql += " WHERE memories.project = ?"
            params.append(project)
        scored = sorted(
            ((embed.cosine(qvec, json.loads(r["vector"])), r) for r in conn.execute(sql, params)),
            key=lambda x: x[0],
            reverse=True,
        )
        out = []
        for score, row in scored[: _clamp(limit)]:
            d = _summary(row)
            d["score"] = round(score, 4)
            out.append(d)
        return out
    finally:
        conn.close()


def get_handoff(project: str, limit: int = 3) -> list[dict]:
    conn = connect()
    try:
        rows = conn.execute(
            "SELECT * FROM memories WHERE project = ? AND type = 'handoff' ORDER BY ts DESC, id DESC LIMIT ?",
            (project, _clamp(limit)),
        ).fetchall()
        return [_full(r) for r in rows]
    finally:
        conn.close()


def recent(project: str = "", limit: int = 10) -> list[dict]:
    conn = connect()
    try:
        if project:
            rows = conn.execute(
                "SELECT * FROM memories WHERE project = ? ORDER BY ts DESC, id DESC LIMIT ?",
                (project, _clamp(limit)),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY ts DESC, id DESC LIMIT ?", (_clamp(limit),)
            ).fetchall()
        return [_summary(r) for r in rows]
    finally:
        conn.close()


def list_projects() -> list[str]:
    conn = connect()
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT project FROM memories ORDER BY project")]
    finally:
        conn.close()


def audit(
    tool: str,
    *,
    llm: str = "",
    project: str = "",
    query: str = "",
    result_count: int = 0,
    ok: bool = True,
    error: str = "",
) -> None:
    """Record a read. Never raises: auditing must not break the tool being audited."""
    try:
        conn = connect()
        try:
            conn.execute(
                "INSERT INTO usage_audit (ts, tool, llm, project, query, result_count, ok, error) "
                "VALUES (?,?,?,?,?,?,?,?)",
                (
                    datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
                    tool,
                    llm,
                    project,
                    query[:500],
                    result_count,
                    int(ok),
                    error[:500],
                ),
            )
            conn.commit()
        finally:
            conn.close()
    except sqlite3.Error:
        return


def audit_log(tool: str = "", llm: str = "", project: str = "", limit: int = 50) -> list[dict]:
    conn = connect()
    try:
        sql, params = "SELECT ts, tool, llm, project, query, result_count, ok, error FROM usage_audit WHERE 1=1", []
        for column, value in (("tool", tool), ("llm", llm), ("project", project)):
            if value:
                sql += f" AND {column} = ?"
                params.append(value)
        sql += " ORDER BY id DESC LIMIT ?"
        params.append(_clamp(limit))
        return [{**dict(r), "ok": bool(r["ok"])} for r in conn.execute(sql, params)]
    finally:
        conn.close()


def stats() -> dict:
    conn = connect()
    try:
        return {
            "notes_on_disk": sum(1 for _ in store.iter_note_paths()),
            "notes_indexed": conn.execute("SELECT count(*) FROM memories").fetchone()[0],
            "embeddings": conn.execute("SELECT count(*) FROM embeddings").fetchone()[0],
            "fts_trigram": has_fts(conn),
        }
    finally:
        conn.close()
