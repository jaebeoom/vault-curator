"""Top-level Synthesis note parsing, normalization, and index generation."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import ast
import re
from typing import Iterable

from vault_curator.evaluator import SessionVerdict


WRITER_MANAGED_TAGS = frozenset(
    {
        "#stage/synthesis",
        "#from/ai-session",
        "#stage/capture",
        "#daily",
        "#sonnet",
        "#haiku",
        "#opus",
    }
)

_SESSION_MARKER_RE = re.compile(
    r"^<!-- vault-curator:session_id=(.+?) -->\s*$",
    re.MULTILINE,
)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_SUMMARY_RE = re.compile(r"^> 한 줄 요약:\s*(.+?)\s*$", re.MULTILINE)
_SECTION_RE_TEMPLATE = r"^## {heading}\s+(.*?)(?=^## |\Z)"
_TAG_TOKEN_RE = re.compile(r"#(?:[^\s#]+)")
_WIKILINK_RE = re.compile(r"^\[\[(.+?)\]\]$")
_FRONTMATTER_RE = re.compile(r"\A---\s*\n(.*?)\n---\s*(?:\n|\Z)", re.DOTALL)
_SESSION_ID_CREATED_AT_RE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})_(\d{2}):(\d{2})(?:__.+)?$"
)


@dataclass(frozen=True)
class SynthesisNote:
    path: Path
    date: str
    file_stem: str
    title: str
    summary: str
    thought: str
    connections: str
    source: str
    subject_tags: tuple[str, ...]
    session_id: str | None
    created_at: str | None = None
    has_frontmatter: bool = False


@dataclass(frozen=True)
class SynthesisLookup:
    by_title: dict[str, SynthesisNote]
    by_stem: dict[str, SynthesisNote]


def load_synthesis_notes(synthesis_dir: Path) -> list[SynthesisNote]:
    """Parse top-level Synthesis notes, excluding generated/manual view files."""
    notes: list[SynthesisNote] = []
    if not synthesis_dir.exists():
        return notes

    for path in sorted(synthesis_dir.glob("*.md")):
        if path.name in {"index.md", "views.md"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        notes.append(parse_synthesis_note(path, text))
    return notes


def parse_synthesis_note(path: Path, text: str) -> SynthesisNote:
    """Parse a Synthesis note into structured fields."""
    frontmatter = _parse_frontmatter(text)
    body = _strip_frontmatter(text)
    title_match = _TITLE_RE.search(body)
    summary_match = _SUMMARY_RE.search(body)
    session_match = _SESSION_MARKER_RE.search(body)
    frontmatter_session_id = _frontmatter_scalar(frontmatter, "session_id")
    frontmatter_created_at = _frontmatter_scalar(frontmatter, "created_at")
    session_id = session_match.group(1).strip() if session_match else None
    title = title_match.group(1).strip() if title_match else ""

    return SynthesisNote(
        path=path,
        date=path.stem[:10],
        file_stem=path.stem,
        title=title,
        summary=summary_match.group(1).strip() if summary_match else "",
        thought=_extract_section(body, "생각"),
        connections=_extract_section(body, "연결되는 것들"),
        source=_strip_trailing_tag_line(_extract_section(body, "출처/계기")),
        subject_tags=tuple(
            extract_subject_tags_from_text(body)
            or _frontmatter_tags_with_hash(frontmatter)
        ),
        session_id=session_id or frontmatter_session_id,
        created_at=frontmatter_created_at or _created_at_from_session_id(session_id),
        has_frontmatter=bool(frontmatter),
    )


def build_lookup(notes: Iterable[SynthesisNote]) -> SynthesisLookup:
    """Build exact-match lookup tables by title and file stem."""
    by_title: dict[str, SynthesisNote] = {}
    by_stem: dict[str, SynthesisNote] = {}
    for note in notes:
        if note.title and note.title not in by_title:
            by_title[note.title] = note
        by_stem[note.file_stem] = note
    return SynthesisLookup(by_title=by_title, by_stem=by_stem)


def normalize_verdicts(
    verdicts: list[SessionVerdict],
    synthesis_dir: Path,
    allowed_subject_tags: set[str],
) -> list[SessionVerdict]:
    """Normalize generated drafts against the existing top-level Synthesis catalog."""
    lookup = build_lookup(load_synthesis_notes(synthesis_dir))
    for verdict in verdicts:
        verdict.connected_themes = normalize_subject_tags(
            verdict.connected_themes,
            allowed_subject_tags,
        )
        if verdict.verdict != "strong_candidate" or not verdict.synthesis_draft:
            continue
        verdict.synthesis_draft["connections"] = render_connections(
            normalize_connections_items(
                verdict.synthesis_draft.get("connections", ""),
                lookup,
            )
        )
    return verdicts


def normalize_existing_synthesis_notes(
    synthesis_dir: Path,
    allowed_subject_tags: set[str],
) -> list[Path]:
    """Rewrite existing top-level Synthesis notes with normalized connections and tags."""
    notes = load_synthesis_notes(synthesis_dir)
    lookup = build_lookup(notes)
    changed: list[Path] = []

    for note in notes:
        normalized_tags = normalize_subject_tags(
            note.subject_tags,
            allowed_subject_tags,
        )
        normalized_connections = render_connections(
            normalize_connections_items(note.connections, lookup)
        )
        rendered = render_synthesis_note(
            session_id=note.session_id,
            title=note.title,
            summary=note.summary,
            thought=note.thought,
            connections=normalized_connections,
            source=note.source,
            subject_tags=normalized_tags,
        )

        try:
            current = note.path.read_text(encoding="utf-8")
        except OSError:
            continue
        if current == rendered:
            continue
        note.path.write_text(rendered, encoding="utf-8")
        changed.append(note.path)

    return changed


def backfill_synthesis_frontmatter(
    synthesis_dir: Path,
    allowed_subject_tags: set[str],
    *,
    dry_run: bool = False,
) -> list[Path]:
    """Insert canonical frontmatter into top-level Synthesis notes."""
    changed: list[Path] = []
    for note in load_synthesis_notes(synthesis_dir):
        normalized_tags = normalize_subject_tags(
            note.subject_tags,
            allowed_subject_tags,
        )
        rendered = render_synthesis_note(
            session_id=note.session_id,
            title=note.title,
            summary=note.summary,
            thought=note.thought,
            connections=note.connections,
            source=note.source,
            subject_tags=normalized_tags,
        )

        try:
            current = note.path.read_text(encoding="utf-8")
        except OSError:
            continue
        if current == rendered:
            continue
        changed.append(note.path)
        if not dry_run:
            note.path.write_text(rendered, encoding="utf-8")
    return changed


def write_index(
    synthesis_dir: Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    """Rebuild Vault/Synthesis/index.md from the current top-level Synthesis notes."""
    notes = load_synthesis_notes(synthesis_dir)
    index_path = synthesis_dir / "index.md"
    generated_at = generated_at or datetime.now()
    index_path.write_text(
        build_index_markdown(notes, generated_at=generated_at),
        encoding="utf-8",
    )
    return index_path


def build_index_markdown(
    notes: list[SynthesisNote],
    *,
    generated_at: datetime | None = None,
) -> str:
    """Build the markdown table for Vault/Synthesis/index.md."""
    generated_at = generated_at or datetime.now()
    lines = [
        "# Synthesis Index",
        "> top-level `Vault/Synthesis/*.md` 기준으로 재생성됨.",
        f"> 마지막 업데이트: {generated_at.strftime('%Y-%m-%d')}",
        "",
        "| 날짜 | 제목 | 파일 | 한 줄 요약 | 태그 | session_id |",
        "|------|------|------|-----------|------|------------|",
    ]

    for note in notes:
        title_link = f"[[{note.file_stem}|{note.title}]]" if note.title else note.file_stem
        tags = " ".join(note.subject_tags)
        lines.append(
            "| {date} | {title} | `{file}` | {summary} | {tags} | {session_id} |".format(
                date=_escape_table_cell(note.date),
                title=title_link,
                file=_escape_table_cell(note.file_stem),
                summary=_escape_table_cell(note.summary),
                tags=_escape_table_cell(tags),
                session_id=_escape_table_cell(note.session_id or ""),
            )
        )

    return "\n".join(lines) + "\n"


def render_synthesis_note(
    *,
    session_id: str | None,
    title: str,
    summary: str,
    thought: str,
    connections: str,
    source: str,
    subject_tags: Iterable[str],
) -> str:
    """Render a Synthesis note with canonical section and tag ordering."""
    tags = normalize_subject_tags(subject_tags, set())
    tag_line = "#stage/synthesis #from/ai-session"
    if tags:
        tag_line = f"{tag_line} {' '.join(tags)}"

    frontmatter = _render_frontmatter(
        title=title,
        session_id=session_id,
        subject_tags=tags,
    )
    marker = (
        f"<!-- vault-curator:session_id={session_id} -->\n"
        if session_id
        else ""
    )
    return (
        f"{frontmatter}"
        f"{marker}"
        f"# {title.strip()}\n\n"
        f"> 한 줄 요약: {summary.strip()}\n\n"
        f"## 생각\n\n"
        f"{thought.strip()}\n\n"
        f"## 연결되는 것들\n\n"
        f"{connections.strip()}\n\n"
        f"## 출처/계기\n\n"
        f"{source.strip()}\n\n"
        f"{tag_line}\n"
    )


def extract_subject_tags_from_text(text: str) -> list[str]:
    """Extract non-structural tags from the last tag line in a note."""
    last_tag_line = _extract_last_tag_line(text)
    if not last_tag_line:
        return []
    return normalize_subject_tags(_TAG_TOKEN_RE.findall(last_tag_line), set())


def normalize_subject_tags(
    tags: Iterable[str],
    allowed_subject_tags: set[str],
) -> list[str]:
    """Deduplicate subject tags and remove writer-managed/meta tags."""
    candidate_tags = list(tags)
    allowed = allowed_subject_tags or {
        tag
        for tag in candidate_tags
        if tag not in WRITER_MANAGED_TAGS
    }
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_tag in candidate_tags:
        tag = raw_tag.strip()
        if not tag or tag in WRITER_MANAGED_TAGS:
            continue
        if tag not in allowed or tag in seen:
            continue
        normalized.append(tag)
        seen.add(tag)
    return normalized


def looks_like_python_list(raw: str) -> bool:
    """Return True when a connections body is still a Python-style list string."""
    stripped = raw.strip()
    if not stripped.startswith("[") or not stripped.endswith("]"):
        return False
    if "[[" in stripped and "]]" in stripped:
        return False
    try:
        parsed = ast.literal_eval(stripped)
    except (SyntaxError, ValueError):
        return False
    return isinstance(parsed, list)


def is_tag_only_connections(raw: str) -> bool:
    """Return True when every connection candidate is just a tag."""
    items = parse_connection_candidates(raw)
    if not items:
        return False
    return all(_is_tag_item(item) for item in items)


def parse_connection_candidates(raw: str) -> list[str]:
    """Parse loose connection text into individual candidates."""
    stripped = raw.strip()
    if not stripped:
        return []

    if looks_like_python_list(stripped):
        try:
            parsed = ast.literal_eval(stripped)
        except (SyntaxError, ValueError):
            parsed = None
        if isinstance(parsed, list):
            return [str(item).strip() for item in parsed if str(item).strip()]

    items: list[str] = []
    for line in stripped.splitlines():
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.startswith("- ") or cleaned.startswith("* "):
            cleaned = cleaned[2:].strip()
        items.extend(_split_connection_line(cleaned))
    return [item for item in (_cleanup_connection_token(item) for item in items) if item]


def normalize_connections_items(
    raw: str,
    lookup: SynthesisLookup,
) -> list[str]:
    """Normalize connections into canonical plain-text lines or file-stem wikilinks."""
    normalized: list[str] = []
    seen: set[str] = set()
    for candidate in parse_connection_candidates(raw):
        rendered = _normalize_connection_candidate(candidate, lookup)
        if not rendered or rendered in seen:
            continue
        normalized.append(rendered)
        seen.add(rendered)
    return normalized


def render_connections(items: Iterable[str]) -> str:
    """Render normalized connection items as one line per item."""
    return "\n".join(item.strip() for item in items if item.strip())


def _extract_section(text: str, heading: str) -> str:
    pattern = re.compile(
        _SECTION_RE_TEMPLATE.format(heading=re.escape(heading)),
        re.MULTILINE | re.DOTALL,
    )
    match = pattern.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _strip_frontmatter(text: str) -> str:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return text
    return text[match.end() :]


def _parse_frontmatter(text: str) -> dict[str, str | list[str]]:
    match = _FRONTMATTER_RE.match(text)
    if not match:
        return {}

    data: dict[str, str | list[str]] = {}
    current_list_key: str | None = None
    for raw_line in match.group(1).splitlines():
        if not raw_line.strip():
            continue
        if current_list_key and raw_line.startswith("  - "):
            value = _parse_yaml_scalar(raw_line[4:].strip())
            current = data.setdefault(current_list_key, [])
            if isinstance(current, list):
                current.append(value)
            continue

        current_list_key = None
        key, sep, value = raw_line.partition(":")
        if not sep:
            continue
        key = key.strip()
        value = value.strip()
        if not key:
            continue
        if value:
            data[key] = _parse_yaml_scalar(value)
        else:
            data[key] = []
            current_list_key = key
    return data


def _frontmatter_tags_with_hash(
    frontmatter: dict[str, str | list[str]],
) -> list[str]:
    raw_tags = frontmatter.get("tags")
    if not isinstance(raw_tags, list):
        return []
    return normalize_subject_tags(
        [
            tag if str(tag).startswith("#") else f"#{tag}"
            for tag in raw_tags
        ],
        set(),
    )


def _frontmatter_scalar(
    frontmatter: dict[str, str | list[str]],
    key: str,
) -> str | None:
    value = frontmatter.get(key)
    return value if isinstance(value, str) else None


def _parse_yaml_scalar(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return value[1:-1].replace(r"\"", '"').replace(r"\\", "\\")
    return value


def _render_frontmatter(
    *,
    title: str,
    session_id: str | None,
    subject_tags: Iterable[str],
) -> str:
    date = _date_from_session_id(session_id)
    created_at = _created_at_from_session_id(session_id)
    lines = [
        "---",
        f"title: {_quote_yaml_string(title.strip())}",
        f"date: {date}" if date else 'date: ""',
        f"created_at: {created_at}" if created_at else 'created_at: ""',
        f"session_id: {_quote_yaml_string(session_id or '')}",
    ]
    tag_values = [_frontmatter_tag_value(tag) for tag in subject_tags]
    if tag_values:
        lines.append("tags:")
        lines.extend(f"  - {tag}" for tag in tag_values)
    else:
        lines.append("tags: []")
    lines.extend(["---", ""])
    return "\n".join(lines)


def _quote_yaml_string(value: str) -> str:
    escaped = value.replace("\\", r"\\").replace('"', r"\"")
    return f'"{escaped}"'


def _frontmatter_tag_value(tag: str) -> str:
    return tag.strip().lstrip("#")


def _date_from_session_id(session_id: str | None) -> str:
    match = _SESSION_ID_CREATED_AT_RE.match(session_id or "")
    if not match:
        return ""
    return match.group(1)


def _created_at_from_session_id(session_id: str | None) -> str:
    match = _SESSION_ID_CREATED_AT_RE.match(session_id or "")
    if not match:
        return ""
    date, hour, minute = match.groups()
    return f"{date}T{hour}:{minute}:00"


def _extract_last_tag_line(text: str) -> str:
    for line in reversed(text.splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        tokens = stripped.split()
        if tokens and all(token.startswith("#") for token in tokens):
            return stripped
    return ""


def _strip_trailing_tag_line(text: str) -> str:
    lines = text.splitlines()
    while lines and not lines[-1].strip():
        lines.pop()
    if not lines:
        return ""
    last_line = lines[-1].strip()
    tokens = last_line.split()
    if tokens and all(token.startswith("#") for token in tokens):
        lines.pop()
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines).strip()


def _split_connection_line(line: str) -> list[str]:
    items: list[str] = []
    current: list[str] = []
    quote: str | None = None
    wikilink_depth = 0
    index = 0

    while index < len(line):
        if quote:
            char = line[index]
            current.append(char)
            if char == quote:
                quote = None
            index += 1
            continue
        if line.startswith("[[", index):
            wikilink_depth += 1
            current.append("[[")
            index += 2
            continue
        if line.startswith("]]", index) and wikilink_depth > 0:
            wikilink_depth -= 1
            current.append("]]")
            index += 2
            continue
        char = line[index]
        if char in {"'", '"'}:
            quote = char
            current.append(char)
            index += 1
            continue
        if char == "," and wikilink_depth == 0:
            token = "".join(current).strip()
            if token:
                items.append(token)
            current = []
            index += 1
            continue
        current.append(char)
        index += 1

    tail = "".join(current).strip()
    if tail:
        items.append(tail)
    return items


def _cleanup_connection_token(token: str) -> str:
    cleaned = token.strip()
    if not cleaned:
        return ""
    if (
        cleaned.startswith("[")
        and cleaned.endswith("]")
        and not cleaned.startswith("[[")
        and not cleaned.endswith("]]")
    ):
        cleaned = cleaned[1:-1].strip()
    if len(cleaned) >= 2 and cleaned[0] == cleaned[-1] and cleaned[0] in {"'", '"'}:
        cleaned = cleaned[1:-1].strip()
    return cleaned


def _normalize_connection_candidate(
    candidate: str,
    lookup: SynthesisLookup,
) -> str | None:
    item = candidate.strip()
    if not item or _is_tag_item(item):
        return None

    wikilink_match = _WIKILINK_RE.match(item)
    if wikilink_match:
        link_body = wikilink_match.group(1).strip()
        target, _, alias = link_body.partition("|")
        resolved = _resolve_existing_note(alias.strip() or target.strip(), lookup)
        if resolved is not None:
            return f"[[{resolved.file_stem}|{resolved.title}]]"
        return _plain_connection_text(alias.strip() or target.strip())

    resolved = _resolve_existing_note(item, lookup)
    if resolved is not None:
        return f"[[{resolved.file_stem}|{resolved.title}]]"
    return _plain_connection_text(item)


def _resolve_existing_note(item: str, lookup: SynthesisLookup) -> SynthesisNote | None:
    candidate = _plain_connection_text(item)
    if not candidate:
        return None
    if candidate in lookup.by_title:
        return lookup.by_title[candidate]
    if candidate in lookup.by_stem:
        return lookup.by_stem[candidate]
    return None


def _plain_connection_text(item: str) -> str:
    candidate = item.strip()
    if candidate.endswith(".md"):
        candidate = candidate[:-3].strip()
    return candidate


def _is_tag_item(item: str) -> bool:
    tokens = [token for token in item.replace(",", " ").split() if token]
    return bool(tokens) and all(token.startswith("#") for token in tokens)


def _escape_table_cell(value: str) -> str:
    return value.replace("|", r"\|").replace("\n", " ").strip()
