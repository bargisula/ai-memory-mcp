"""Markdown storage: the single source of truth. Everything else can be rebuilt from it."""
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from . import config

# Letters/digits/underscore in any script, plus '.' and '-' inside. Must start with a
# word char and not end with '.' (Windows silently strips trailing dots).
# Rejects path separators, '..', absolute paths and drive letters.
_PROJECT_RE = re.compile(r"^\w(?:[\w.\-]{0,78}[\w\-])?$")
_FRONTMATTER_RE = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n?(.*)\Z", re.DOTALL)


class MemoryInputError(ValueError):
    """User-facing validation error (bad project name, bad type, bad path)."""


@dataclass
class Note:
    path: str  # relative to notes/, forward slashes: "<project>/<file>.md"
    project: str
    type: str
    llm: str
    tags: str
    ts: str
    title: str
    content: str


def validate_project(project: str) -> str:
    if not isinstance(project, str) or not _PROJECT_RE.match(project):
        raise MemoryInputError(
            "project must be 1-80 chars: letters, digits, '_', '-', '.', "
            f"starting with a letter/digit/'_' and not ending with '.' (got {project!r})"
        )
    return project


def validate_type(type_: str) -> str:
    allowed = config.valid_types()
    if type_ not in allowed:
        raise MemoryInputError(f"type must be one of {sorted(allowed)}, got {type_!r}")
    return type_


def slugify(title: str) -> str:
    slug = re.sub(r"[^\w-]+", "-", title.strip())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug[:50] or "note"


def _one_line(value: str) -> str:
    """Frontmatter values must stay on one line or they corrupt the header."""
    return re.sub(r"\s+", " ", value).strip()


def write_note(project: str, type_: str, title: str, content: str, llm: str = "", tags: str = "") -> Note:
    validate_project(project)
    validate_type(type_)
    title = _one_line(title)
    if not title:
        raise MemoryInputError("title must not be empty")

    now = datetime.now(timezone.utc).astimezone()
    ts = now.isoformat(timespec="seconds")
    proj_dir = config.notes_dir() / project
    proj_dir.mkdir(parents=True, exist_ok=True)

    body = (
        "---\n"
        f"project: {project}\n"
        f"type: {type_}\n"
        f"llm: {_one_line(llm)}\n"
        f"tags: {_one_line(tags)}\n"
        f"ts: {ts}\n"
        "---\n\n"
        f"# {title}\n\n{content}\n"
    )

    base = f"{now.strftime('%Y-%m-%d')}-{slugify(title)}"
    counter = 1
    while True:
        name = f"{base}.md" if counter == 1 else f"{base}-{counter}.md"
        try:
            # 'x' fails if the file exists, so two writers can never overwrite each other.
            with open(proj_dir / name, "x", encoding="utf-8", newline="\n") as fh:
                fh.write(body)
            break
        except FileExistsError:
            counter += 1

    return Note(
        path=f"{project}/{name}",
        project=project,
        type=type_,
        llm=_one_line(llm),
        tags=_one_line(tags),
        ts=ts,
        title=title,
        content=content,
    )


def parse_note(text: str, rel_path: str) -> Note | None:
    """Parse one Markdown file. Returns None for files that are not memory notes."""
    m = _FRONTMATTER_RE.match(text)
    if not m:
        return None
    meta = {}
    for line in m.group(1).splitlines():
        key, sep, value = line.partition(":")
        if sep:
            meta[key.strip()] = value.strip()
    body = m.group(2).lstrip("\r\n")
    title = Path(rel_path).stem
    heading = re.match(r"# (.+?)\r?\n", body)
    if heading:
        title = heading.group(1).strip()
        body = body[heading.end():].lstrip("\r\n")
    project = meta.get("project") or rel_path.split("/", 1)[0]
    return Note(
        path=rel_path,
        project=project,
        type=meta.get("type", ""),
        llm=meta.get("llm", ""),
        tags=meta.get("tags", ""),
        ts=meta.get("ts", ""),
        title=title,
        content=body.rstrip("\r\n"),
    )


def resolve_note_path(rel_path: str) -> Path:
    """Map a relative note path to a real file, refusing anything outside notes/."""
    root = config.notes_dir().resolve()
    target = (root / rel_path).resolve()
    if target.suffix != ".md" or not target.is_relative_to(root) or target == root:
        raise MemoryInputError(f"not a note path: {rel_path!r}")
    if not target.is_file():
        raise MemoryInputError(f"no such note: {rel_path!r}")
    return target


def read_note(rel_path: str) -> Note:
    target = resolve_note_path(rel_path)
    rel = target.relative_to(config.notes_dir().resolve()).as_posix()
    note = parse_note(target.read_text(encoding="utf-8"), rel)
    if note is None:
        raise MemoryInputError(f"file has no memory frontmatter: {rel_path!r}")
    return note


def iter_note_paths():
    """Yield every *.md file under notes/ as a posix path relative to notes/."""
    root = config.notes_dir()
    if not root.is_dir():
        return
    for p in sorted(root.rglob("*.md")):
        yield p.relative_to(root).as_posix()
