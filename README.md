# ai-memory-mcp

**English** | [繁體中文](README.zh-TW.md)

Local, Markdown-first shared memory for AI coding agents, served over [MCP](https://modelcontextprotocol.io).

Every session of every tool (Claude Code, Codex CLI, Copilot CLI, ...) starts with amnesia. This gives them one
shared place to record decisions, dead ends and handoffs, and to look them up next time, so you stop re-explaining
your project.

> **Status: feature-complete, provided as-is.** This is a small tool I use myself. I do not offer support and
> I am not taking feature requests. Bug reports may go unanswered. Fork it freely (MIT).

## Why this one

- **Plain Markdown is the source of truth.** One `.md` file per memory: readable, greppable, diffable, committable.
- **The index is disposable.** SQLite only accelerates search. Delete `index.db` and it is rebuilt from your notes.
- **Local and private.** No cloud, no account. Optional semantic search uses a local Ollama model.
- **Any language.** Substring search works for Chinese/Japanese/Korean text, not just space-separated words.
- **Auditable.** Every read is logged (who, when, what query; never the results).

## Install

Requires Python 3.10+.

```bash
git clone https://github.com/bargisula/ai-memory-mcp.git
cd ai-memory-mcp
pipx install .          # or: pip install .
ai-memory doctor        # checks your setup
```

Then register the server with your MCP client. The command is `ai-memory-mcp` (stdio transport):

```bash
# Claude Code
claude mcp add -s user ai-memory -- ai-memory-mcp

# Codex CLI
codex mcp add ai-memory -- ai-memory-mcp
```

Any client that takes a JSON config (for example `~/.copilot/mcp-config.json`):

```json
{ "mcpServers": { "ai-memory": { "command": "ai-memory-mcp" } } }
```

If you use [uv](https://docs.astral.sh/uv/), you can skip the install and point the client at
`uvx --from git+https://github.com/bargisula/ai-memory-mcp ai-memory-mcp` instead.

The server ships usage instructions to the client automatically (check the handoff first, record decisions and
failures as you go), so no extra prompt file is required.

## Tools

| Tool | What it does |
|---|---|
| `record_memory(project, type, title, content, llm, tags)` | Save a note. `type` is `decision`, `progress`, `failure` or `handoff`. |
| `search_memory(query, project, type, limit)` | Substring search; every word must match. Returns short snippets. |
| `search_memory_semantic(query, project, limit)` | Meaning-based search (needs Ollama, see below). |
| `read_memory(path)` | Full text of one note. |
| `get_handoff(project, limit)` | Newest handoff notes with full text. Call first when resuming work. |
| `recent(project, limit)` | Latest notes of any type. |
| `list_projects()` | Projects that have notes. |
| `audit_usage(tool, llm, project, limit)` | Read audit log. |

Pass your own name in `llm` (for example `"Claude"`) so entries and reads can be attributed.

## Where your data lives

Default: `~/.ai-memory/` (override with `AI_MEMORY_HOME`).

```
~/.ai-memory/
  notes/<project>/2026-01-05-choose-database.md   <- the truth. Back this up / put it in git.
  index.db                                        <- disposable search index + audit log
```

A note looks like this, and you can write or edit them by hand:

```markdown
---
project: my-app
type: decision
llm: Claude
tags: database
ts: 2026-01-05T10:20:00+08:00
---

# Use SQLite

Single file, zero setup. Rejected Postgres: no concurrent writers needed.
```

After hand edits, deletions or copying notes from another machine, run `ai-memory reindex`. (A missing `index.db`
is rebuilt automatically the first time the server starts.)

## Configuration

All optional, all environment variables:

| Variable | Default | Meaning |
|---|---|---|
| `AI_MEMORY_HOME` | `~/.ai-memory` | Data directory |
| `AI_MEMORY_TYPES` | `decision,progress,failure,handoff` | Allowed note types, comma separated |
| `AI_MEMORY_EMBEDDINGS` | `on` | `off` disables semantic search entirely |
| `AI_MEMORY_EMBED_URL` | `http://localhost:11434/api/embeddings` | Ollama embeddings endpoint |
| `AI_MEMORY_EMBED_MODEL` | `nomic-embed-text` | Embedding model |

## Semantic search (optional)

```bash
ollama pull nomic-embed-text
ai-memory reindex --embed     # embed notes written before Ollama was available
```

Without Ollama everything else works; `search_memory_semantic` simply reports that it is unavailable.
Vectors are compared by brute force in Python, which is fine up to a few thousand notes.

## Command line

```
ai-memory doctor                  check the installation
ai-memory reindex [--embed]       rebuild the index from notes/
ai-memory handoff <project>       print the newest handoff (see hook below)
ai-memory search "<words>"        keyword search, JSON output
ai-memory audit                   read audit log, JSON output
ai-memory web [--port N]          open the read-only audit page in your browser
```

### Audit page

`ai-memory web` serves a small page at `http://127.0.0.1:8765` showing who read what and when, with filters for
caller, project, tool, status and query text. It is read-only, listens on 127.0.0.1 only, refuses requests whose
`Host` header is not loopback (DNS-rebinding protection), and follows your browser language (English or 繁體中文).

### Make handoffs load automatically (Claude Code)

Relying on the model to remember to call `get_handoff` is fragile. A `SessionStart` hook guarantees it. In
`.claude/settings.json` of your project:

```json
{
  "hooks": {
    "SessionStart": [
      { "hooks": [ { "type": "command", "command": "ai-memory handoff my-app" } ] }
    ]
  }
}
```

## Security notes

- Project names are restricted to letters, digits, `_`, `-`, `.`; anything path-like is rejected, so a prompt-injected
  agent cannot write outside `notes/`. `read_memory` is likewise confined to `notes/*.md`.
- Notes are plain text on disk. **Do not store secrets in memories.**
- The audit log stores tool, caller, project and the query text (first 500 characters), never result contents.

## Limits (by design)

- Single user, single machine. Concurrent writers are safe (files are created exclusively, SQLite runs in WAL mode),
  but there is no access control and no built-in sync. To sync, keep `notes/` in a git repository.
- No edit or delete tool. Edit or delete the Markdown file, then `ai-memory reindex`.
- Search is substring matching, not fuzzy or ranked by meaning (use the semantic tool for that).

## Coming from a private predecessor?

The note format is unchanged: copy your old `notes/` folder into `AI_MEMORY_HOME` and start the server. The index builds itself.

## Development

```bash
pip install -e ".[dev]"
pytest
```

## License

MIT. See [LICENSE](LICENSE).
