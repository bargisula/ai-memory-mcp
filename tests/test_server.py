from ai_memory import cli, server


def test_record_then_search_then_read_roundtrip():
    saved = server.record_memory("my-app", "decision", "Pick SQLite", "Because it is simple.", llm="Claude")
    assert saved["ok"] and saved["indexed"] and saved["embedded"] is False

    hits = server.search_memory("simple", project="my-app", llm="Claude")
    assert hits[0]["path"] == saved["path"]

    full = server.read_memory(saved["path"], llm="Claude")
    assert full["content"] == "Because it is simple." and full["llm"] == "Claude"


def test_record_rejects_traversal_and_bad_type(tmp_path):
    assert "error" in server.record_memory("../../evil", "decision", "t", "c")
    assert "error" in server.record_memory("p", "gossip", "t", "c")
    assert not list(tmp_path.rglob("*.md"))


def test_read_memory_refuses_outside_paths(tmp_path):
    (tmp_path / "secret.md").write_text("---\ntype: decision\n---\n# s\n\nsecret", encoding="utf-8")
    assert "error" in server.read_memory("../../secret.md")
    assert "error" in server.read_memory("nope/none.md")


def test_semantic_tool_reports_unavailable_instead_of_crashing():
    server.record_memory("p", "decision", "t", "c")
    out = server.search_memory_semantic("anything", llm="Claude")
    assert "error" in out[0] and "search_memory" in out[0]["error"]


def test_reads_are_audited_without_result_content():
    server.record_memory("p", "decision", "t", "secret body text")
    server.search_memory("secret", llm="Codex")
    server.get_handoff("p", llm="Codex")
    log = server.audit_usage(llm="Codex")
    assert {r["tool"] for r in log} == {"search_memory", "get_handoff"}
    assert "secret body text" not in str(log)


def test_server_advertises_usage_instructions():
    assert "get_handoff" in server.INSTRUCTIONS and "record_memory" in server.INSTRUCTIONS


def test_cli_doctor_reindex_and_handoff(capsys):
    server.record_memory("p", "handoff", "Stopping here", "Next: write the README.", llm="Claude")

    assert cli.main(["doctor"]) == 0
    assert "all indexed" in capsys.readouterr().out

    assert cli.main(["reindex"]) == 0
    assert "indexed 1 notes" in capsys.readouterr().out

    assert cli.main(["handoff", "p"]) == 0
    assert "Next: write the README." in capsys.readouterr().out

    assert cli.main(["handoff", "../bad"]) == 2
