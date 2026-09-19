from ai_memory import config, embed, index, store


def add(project="p", type_="decision", title="t", content="c", **kw):
    note = store.write_note(project, type_, title, content, **kw)
    index.index_note(note)
    return note


def test_english_search():
    add(title="Use SQLite", content="Single file, zero setup.")
    assert [r["title"] for r in index.search("sqlite")] == ["Use SQLite"]


def test_chinese_substring_inside_running_text():
    add(title="選型決策", content="我們決定採用本機語意搜尋方案")
    assert index.search("語意搜尋")
    assert index.search("本機語意")


def test_short_chinese_query_uses_like_fallback():
    add(title="選型決策", content="我們決定採用本機語意搜尋方案")
    assert index.search("決定")
    assert index.search("方案")


def test_hyphen_and_quotes_do_not_break_search():
    add(title="ai-memory design", content='he said "hello" and left')
    assert index.search("ai-memory")
    assert index.search('"hello"')
    assert index.search('AND OR NOT ( * :') == []


def test_all_words_must_match():
    add(title="alpha beta", content="one")
    add(title="alpha gamma", content="two")
    assert len(index.search("alpha")) == 2
    assert [r["title"] for r in index.search("alpha gamma")] == ["alpha gamma"]


def test_like_wildcards_are_literal():
    add(title="growth", content="revenue up 100% this year")
    add(title="other", content="nothing relevant")
    assert [r["title"] for r in index.search("100%")] == ["growth"]
    assert index.search("_") == []


def test_empty_query_returns_nothing():
    add()
    assert index.search("   ") == []


def test_filters_by_project_and_type():
    add(project="a", type_="decision", content="needle")
    add(project="b", type_="failure", content="needle")
    assert len(index.search("needle")) == 2
    assert [r["project"] for r in index.search("needle", project="a")] == ["a"]
    assert [r["type"] for r in index.search("needle", type_="failure")] == ["failure"]


def test_search_results_carry_snippet_not_full_text():
    add(content="x" * 1000)
    hit = index.search("xxx")[0]
    assert len(hit["snippet"]) <= index.SNIPPET_CHARS + 1
    assert "content" not in hit


def test_handoff_returns_full_content_newest_first():
    add(type_="handoff", title="old", content="first")
    add(type_="handoff", title="new", content="second " * 200)
    add(type_="decision", title="ignored", content="nope")
    out = index.get_handoff("p", limit=5)
    assert [h["title"] for h in out] == ["new", "old"]
    assert out[0]["content"].startswith("second") and len(out[0]["content"]) > index.SNIPPET_CHARS


def test_recent_and_list_projects():
    add(project="b")
    add(project="a")
    assert index.list_projects() == ["a", "b"]
    assert len(index.recent(limit=1)) == 1


def test_index_rebuilds_itself_when_db_deleted():
    add(title="survives", content="the notes are the truth")
    config.db_path().unlink()
    for suffix in ("-wal", "-shm"):
        p = config.db_path().with_name(config.db_path().name + suffix)
        p.unlink(missing_ok=True)
    assert [r["title"] for r in index.search("survives")] == ["survives"]


def test_copied_notes_are_indexed_on_first_start(memory_home):
    note = store.write_note("p", "decision", "moved in", "from another machine")
    assert not config.db_path().exists()
    assert [r["path"] for r in index.search("machine")] == [note.path]


def test_reindex_picks_up_hand_edits_and_deletions():
    a = add(title="keep", content="original text")
    b = add(title="drop", content="to be deleted")
    path_a = config.notes_dir() / a.path
    path_a.write_text(path_a.read_text(encoding="utf-8").replace("original text", "edited text"), encoding="utf-8")
    (config.notes_dir() / b.path).unlink()

    result = index.reindex()
    assert result["indexed"] == 1
    assert index.search("edited")
    assert not index.search("original")
    assert not index.search("deleted")


def test_reindex_skips_files_without_frontmatter():
    add()
    (config.notes_dir() / "README.md").write_text("# not a memory\n", encoding="utf-8")
    result = index.reindex()
    assert result["indexed"] == 1 and result["skipped"] == ["README.md"]


def test_semantic_search_none_when_embeddings_off():
    add()
    assert index.semantic_search("anything") is None


def test_semantic_search_ranks_by_similarity(monkeypatch):
    vectors = {"cats": [1.0, 0.0], "cars": [0.0, 1.0]}
    monkeypatch.setattr(embed, "embed", lambda text: next((v for k, v in vectors.items() if k in text), [0.5, 0.5]))
    add(title="cats", content="about cats")
    add(title="cars", content="about cars")
    hits = index.semantic_search("cars please", limit=2)
    assert [h["title"] for h in hits] == ["cars", "cats"]
    assert hits[0]["score"] > hits[1]["score"]


def test_reindex_drops_stale_embedding_when_text_changes(monkeypatch):
    monkeypatch.setattr(embed, "embed", lambda text: [1.0, 0.0])
    note = add(title="cats", content="about cats")
    assert index.stats()["embeddings"] == 1

    path = config.notes_dir() / note.path
    path.write_text(path.read_text(encoding="utf-8").replace("about cats", "totally different"), encoding="utf-8")
    index.reindex()
    assert index.stats()["embeddings"] == 0

    index.reindex(embed_missing=True)
    assert index.stats()["embeddings"] == 1


def test_audit_log_records_reads_and_filters():
    index.audit("search_memory", llm="Claude", project="p", query="q", result_count=2)
    index.audit("recent", llm="Codex")
    assert [r["llm"] for r in index.audit_log(llm="Claude")] == ["Claude"]
    assert index.audit_log(tool="recent")[0]["ok"] is True


def test_concurrent_writers_on_a_fresh_home_all_get_indexed():
    from concurrent.futures import ThreadPoolExecutor

    from ai_memory import server

    with ThreadPoolExecutor(12) as pool:
        results = list(pool.map(lambda i: server.record_memory("race", "progress", "same title", f"body {i}"), range(24)))

    assert all(r.get("indexed") is True for r in results), [r for r in results if not r.get("indexed")]
    stats = index.stats()
    assert stats["notes_on_disk"] == stats["notes_indexed"] == 24
