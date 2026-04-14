"""Top-level Sonnet note parsing, normalization, and index generation."""

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
        "#sonnet",
        "#from/ai-session",
        "#haiku",
        "#daily",
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


@dataclass(frozen=True)
class SonnetNote:
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


@dataclass(frozen=True)
class SonnetLookup:
    by_title: dict[str, SonnetNote]
    by_stem: dict[str, SonnetNote]


def load_sonnet_notes(sonnet_dir: Path) -> list[SonnetNote]:
    """Parse top-level Sonnet notes, excluding the generated index."""
    notes: list[SonnetNote] = []
    if not sonnet_dir.exists():
        return notes

    for path in sorted(sonnet_dir.glob("*.md")):
        if path.name == "index.md":
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        notes.append(parse_sonnet_note(path, text))
    return notes


def parse_sonnet_note(path: Path, text: str) -> SonnetNote:
    """Parse a Sonnet note into structured fields."""
    title_match = _TITLE_RE.search(text)
    summary_match = _SUMMARY_RE.search(text)
    session_match = _SESSION_MARKER_RE.search(text)

    return SonnetNote(
        path=path,
        date=path.stem[:10],
        file_stem=path.stem,
        title=title_match.group(1).strip() if title_match else "",
        summary=summary_match.group(1).strip() if summary_match else "",
        thought=_extract_section(text, "생각"),
        connections=_extract_section(text, "연결되는 것들"),
        source=_strip_trailing_tag_line(_extract_section(text, "출처/계기")),
        subject_tags=tuple(extract_subject_tags_from_text(text)),
        session_id=session_match.group(1).strip() if session_match else None,
    )


def build_lookup(notes: Iterable[SonnetNote]) -> SonnetLookup:
    """Build exact-match lookup tables by title and file stem."""
    by_title: dict[str, SonnetNote] = {}
    by_stem: dict[str, SonnetNote] = {}
    for note in notes:
        if note.title and note.title not in by_title:
            by_title[note.title] = note
        by_stem[note.file_stem] = note
    return SonnetLookup(by_title=by_title, by_stem=by_stem)


def normalize_verdicts(
    verdicts: list[SessionVerdict],
    sonnet_dir: Path,
    allowed_subject_tags: set[str],
) -> list[SessionVerdict]:
    """Normalize generated drafts against the existing top-level Sonnet catalog."""
    lookup = build_lookup(load_sonnet_notes(sonnet_dir))
    for verdict in verdicts:
        verdict.connected_themes = normalize_subject_tags(
            verdict.connected_themes,
            allowed_subject_tags,
        )
        if verdict.verdict != "strong_candidate" or not verdict.sonnet_draft:
            continue
        verdict.sonnet_draft["connections"] = render_connections(
            normalize_connections_items(
                verdict.sonnet_draft.get("connections", ""),
                lookup,
            )
        )
    return verdicts


def normalize_existing_sonnet_notes(
    sonnet_dir: Path,
    allowed_subject_tags: set[str],
) -> list[Path]:
    """Rewrite existing top-level Sonnet notes with normalized connections and tags."""
    notes = load_sonnet_notes(sonnet_dir)
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
        rendered = render_sonnet_note(
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


def write_index(
    sonnet_dir: Path,
    *,
    generated_at: datetime | None = None,
) -> Path:
    """Rebuild Vault/Sonnet/index.md from the current top-level Sonnet notes."""
    notes = load_sonnet_notes(sonnet_dir)
    index_path = sonnet_dir / "index.md"
    generated_at = generated_at or datetime.now()
    index_path.write_text(
        build_index_markdown(notes, generated_at=generated_at),
        encoding="utf-8",
    )
    return index_path


def build_index_markdown(
    notes: list[SonnetNote],
    *,
    generated_at: datetime | None = None,
) -> str:
    """Build the markdown table for Vault/Sonnet/index.md."""
    generated_at = generated_at or datetime.now()
    lines = [
        "# Sonnet Index",
        "> top-level `Vault/Sonnet/*.md` 기준으로 재생성됨.",
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


def render_sonnet_note(
    *,
    session_id: str | None,
    title: str,
    summary: str,
    thought: str,
    connections: str,
    source: str,
    subject_tags: Iterable[str],
) -> str:
    """Render a Sonnet note with canonical section and tag ordering."""
    tags = normalize_subject_tags(subject_tags, set())
    tag_line = "#sonnet #from/ai-session"
    if tags:
        tag_line = f"{tag_line} {' '.join(tags)}"

    marker = (
        f"<!-- vault-curator:session_id={session_id} -->\n"
        if session_id
        else ""
    )
    return (
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
    lookup: SonnetLookup,
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
    lookup: SonnetLookup,
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


def _resolve_existing_note(item: str, lookup: SonnetLookup) -> SonnetNote | None:
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
