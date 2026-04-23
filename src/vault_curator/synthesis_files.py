"""Helpers for locating and naming Synthesis notes."""

from __future__ import annotations

from pathlib import Path
import re


_SESSION_MARKER_TEMPLATE = "<!-- vault-curator:session_id={session_id} -->"
_SESSION_MARKER_RE = re.compile(
    r"^<!-- vault-curator:session_id=(.+?) -->\s*$",
    re.MULTILINE,
)
_LEGACY_SOURCE_TEMPLATE = re.compile(
    r"^## 출처/계기\s+.*?\b{session_id}\b",
    re.MULTILINE | re.DOTALL,
)


def session_marker(session_id: str) -> str:
    return _SESSION_MARKER_TEMPLATE.format(session_id=session_id)


def extract_session_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return extract_session_id_from_text(text)


def extract_session_id_from_text(text: str) -> str | None:
    match = _SESSION_MARKER_RE.search(text)
    if not match:
        return None
    return match.group(1).strip() or None


def slugify_session_id(session_id: str) -> str:
    return session_id.replace(":", "-")


def build_note_path(
    synthesis_dir: Path,
    session_id: str,
    suggested_title: str,
) -> Path:
    safe_title = re.sub(r"\s+", "_", suggested_title.strip()) if suggested_title else ""
    safe_session_id = slugify_session_id(session_id)
    filename = (
        f"{safe_session_id}__{safe_title}.md"
        if safe_title
        else f"{safe_session_id}.md"
    )
    return synthesis_dir / filename


def find_existing_note_path(
    synthesis_dir: Path,
    session_id: str,
) -> Path | None:
    if not synthesis_dir.exists():
        return None

    marker = session_marker(session_id)
    safe_session_id = slugify_session_id(session_id)
    legacy_source_pattern = _legacy_source_pattern(session_id)
    legacy_matches: list[Path] = []

    for path in sorted(synthesis_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        if marker in text:
            return path

        if path.name.startswith(f"{safe_session_id}__") or path.stem == safe_session_id:
            return path

        if has_synthesis_signature(text) and legacy_source_pattern.search(text):
            legacy_matches.append(path)

    return legacy_matches[0] if len(legacy_matches) == 1 else None


def looks_like_legacy_synthesis_note(path: Path, session_id: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False
    return has_synthesis_signature(text) and bool(
        _legacy_source_pattern(session_id).search(text)
    )


def has_synthesis_signature(text: str) -> bool:
    return (
        "#from/ai-session" in text
        and ("#stage/synthesis" in text or "#sonnet" in text)
    )


def _legacy_source_pattern(session_id: str) -> re.Pattern[str]:
    return re.compile(
        _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
        _LEGACY_SOURCE_TEMPLATE.flags,
    )
