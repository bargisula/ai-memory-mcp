from concurrent.futures import ThreadPoolExecutor

import pytest

from ai_memory import config, store


@pytest.mark.parametrize("name", ["my-app", "AI_friend", "Teaching-Agent", "專案名", "v1.2", "a"])
def test_valid_project_names(name):
    assert store.validate_project(name) == name


@pytest.mark.parametrize(
    "name",
    ["", "../x", "a/b", "a\\b", "C:\\Windows\\x", "/etc/x", "..", ".hidden", "-x", "a.", "x" * 81, "a b", None],
)
def test_bad_project_names_rejected(name):
    with pytest.raises(store.MemoryInputError):
        store.validate_project(name)


def test_write_note_creates_file_inside_notes(memory_home):
    note = store.write_note("my-app", "decision", "Pick SQLite", "Because it is simple.", llm="Claude", tags="db")
    target = memory_home / "notes" / "my-app" / note.path.split("/")[1]
    assert target.is_file()
    text = target.read_text(encoding="utf-8")
    assert "type: decision" in text and "# Pick SQLite" in text and "Because it is simple." in text


def test_traversal_project_writes_nothing(memory_home, tmp_path):
    with pytest.raises(store.MemoryInputError):
        store.write_note("../../evil", "decision", "x", "y")
    assert not (tmp_path / "evil").exists()
    assert not list(tmp_path.rglob("*.md"))


def test_unknown_type_rejected():
    with pytest.raises(store.MemoryInputError):
        store.write_note("p", "gossip", "t", "c")


def test_custom_types_from_env(monkeypatch):
    monkeypatch.setenv("AI_MEMORY_TYPES", "idea, todo")
    assert store.write_note("p", "idea", "t", "c").type == "idea"
    with pytest.raises(store.MemoryInputError):
        store.write_note("p", "decision", "t", "c")


def test_multiline_metadata_cannot_corrupt_frontmatter():
    note = store.write_note("p", "decision", "line one\nline two", "body", llm="a\nb", tags="x\ny")
    parsed = store.read_note(note.path)
    assert parsed.title == "line one line two"
    assert parsed.llm == "a b" and parsed.tags == "x y"


def test_same_title_never_overwrites():
    a = store.write_note("p", "decision", "Same title", "first")
    b = store.write_note("p", "decision", "Same title", "second")
    assert a.path != b.path
    assert store.read_note(a.path).content == "first"
    assert store.read_note(b.path).content == "second"


def test_concurrent_writers_get_distinct_files():
    with ThreadPoolExecutor(8) as pool:
        notes = list(pool.map(lambda i: store.write_note("p", "progress", "Same", f"n{i}"), range(8)))
    assert len({n.path for n in notes}) == 8
    assert {store.read_note(n.path).content for n in notes} == {f"n{i}" for i in range(8)}


@pytest.mark.parametrize("bad", ["../../secret.md", "p/../../secret.md", "/etc/passwd.md", "C:\\x.md", "p/note.txt", "p", ""])
def test_read_note_refuses_paths_outside_notes(bad, memory_home, tmp_path):
    (tmp_path / "secret.md").write_text("---\nproject: p\ntype: decision\n---\n# s\n\nsecret", encoding="utf-8")
    store.write_note("p", "decision", "t", "c")
    with pytest.raises(store.MemoryInputError):
        store.read_note(bad)


def test_parse_legacy_note_format():
    text = "---\nproject: my-app\ntype: handoff\nllm: Claude\ntags: a,b\nts: 2026-08-22T10:00:00+08:00\n---\n\n# 收尾交接\n\n下一步：剪片。\n"
    note = store.parse_note(text, "my-app/2026-08-22-收尾交接.md")
    assert (note.project, note.type, note.llm, note.title) == ("my-app", "handoff", "Claude", "收尾交接")
    assert note.content == "下一步：剪片。"
    assert note.ts == "2026-08-22T10:00:00+08:00"


def test_parse_ignores_files_without_frontmatter():
    assert store.parse_note("# just a readme\n", "README.md") is None


def test_home_defaults_to_dot_ai_memory(monkeypatch):
    monkeypatch.delenv("AI_MEMORY_HOME")
    assert config.home().name == ".ai-memory"
