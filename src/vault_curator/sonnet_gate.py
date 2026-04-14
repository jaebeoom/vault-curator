"""Sonnet admission gate.

적재 전에 형태적으로 실패한 Sonnet 초안을 차단한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re

from vault_curator.evaluator import SessionVerdict
from vault_curator import sonnet_catalog


_SESSION_MARKER_TEMPLATE = "<!-- vault-curator:session_id={session_id} -->"
_SESSION_MARKER_RE = re.compile(
    r"^<!-- vault-curator:session_id=(.+?) -->\s*$",
    re.MULTILINE,
)
_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$", re.MULTILINE)
_LEGACY_SOURCE_TEMPLATE = re.compile(
    r"^## 출처/계기\s+.*?\b{session_id}\b",
    re.MULTILINE | re.DOTALL,
)
_PLACEHOLDER_TOKEN_RE = re.compile(
    r"\b(?:tbd|todo|placeholder|n/?a)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class GateIssue:
    code: str
    message: str


@dataclass(frozen=True)
class BlockedSonnetDraft:
    verdict: SessionVerdict
    issues: tuple[GateIssue, ...]

    @property
    def session_id(self) -> str:
        return self.verdict.session_id


@dataclass(frozen=True)
class ExistingSonnetNote:
    path: Path
    title: str
    session_id: str | None


@dataclass(frozen=True)
class DuplicateCandidate:
    title: str
    path: Path
    similarity: float


@dataclass(frozen=True)
class PotentialDuplicateWarning:
    verdict: SessionVerdict
    matches: tuple[DuplicateCandidate, ...]

    @property
    def session_id(self) -> str:
        return self.verdict.session_id


def apply_admission_gate(
    verdicts: list[SessionVerdict],
    sonnet_dir: Path,
) -> tuple[list[SessionVerdict], list[BlockedSonnetDraft]]:
    """강한 후보 Sonnet draft를 검사해 통과/차단 verdict로 나눈다."""
    strong_titles = [
        verdict.suggested_title.strip()
        for verdict in verdicts
        if verdict.verdict == "strong_candidate" and verdict.suggested_title.strip()
    ]
    title_counts = Counter(strong_titles)
    existing_notes = _load_existing_notes(sonnet_dir)

    admitted: list[SessionVerdict] = []
    blocked: list[BlockedSonnetDraft] = []

    for verdict in verdicts:
        if verdict.verdict != "strong_candidate":
            admitted.append(verdict)
            continue

        issues = inspect_verdict(
            verdict,
            sonnet_dir,
            existing_notes,
            title_counts,
        )
        if issues:
            blocked.append(
                BlockedSonnetDraft(verdict=verdict, issues=tuple(issues))
            )
            continue

        admitted.append(verdict)

    return admitted, blocked


def inspect_verdict(
    verdict: SessionVerdict,
    sonnet_dir: Path,
    existing_notes: list[ExistingSonnetNote] | None = None,
    title_counts: Counter[str] | None = None,
) -> list[GateIssue]:
    """단일 strong_candidate verdict에 대한 gate 이슈를 계산한다."""
    issues: list[GateIssue] = []

    if verdict.verdict != "strong_candidate":
        return issues

    title = verdict.suggested_title.strip()
    draft = verdict.sonnet_draft

    if not draft:
        return [
            GateIssue(
                "missing_sonnet_draft",
                "strong_candidate인데 sonnet_draft가 없습니다.",
            )
        ]

    if not title:
        issues.append(GateIssue("empty_title", "제목이 비어 있습니다."))

    for field_name in ("summary", "thought", "source"):
        value = str(draft.get(field_name, "")).strip()
        if not value:
            issues.append(
                GateIssue(
                    f"missing_{field_name}",
                    f"{field_name}가 비어 있습니다.",
                )
            )

    thought = str(draft.get("thought", "")).strip()
    if thought:
        sentence_count = _count_sentences(thought)
        if sentence_count != 4:
            issues.append(
                GateIssue(
                    "invalid_thought_sentence_count",
                    f"thought 문장 수가 4문장이 아닙니다 (현재: {sentence_count}).",
                )
            )

    placeholder_fields = {
        "title": title,
        "summary": str(draft.get("summary", "")).strip(),
        "thought": thought,
        "connections": str(draft.get("connections", "")).strip(),
        "source": str(draft.get("source", "")).strip(),
    }
    for field_name, value in placeholder_fields.items():
        if _contains_placeholder_text(value):
            issues.append(
                GateIssue(
                    "placeholder_text",
                    f"{field_name}에 placeholder처럼 보이는 텍스트가 있습니다.",
                )
            )

    connections = str(draft.get("connections", "")).strip()
    if connections:
        if sonnet_catalog.looks_like_python_list(connections):
            issues.append(
                GateIssue(
                    "python_list_connections",
                    "connections가 Python list 형태로 남아 있습니다.",
                )
            )
        if sonnet_catalog.is_tag_only_connections(connections):
            issues.append(
                GateIssue(
                    "tag_only_connections",
                    "connections가 태그만으로 구성되어 있습니다.",
                )
            )

    existing_notes = (
        existing_notes if existing_notes is not None else _load_existing_notes(sonnet_dir)
    )
    title_counts = title_counts or Counter()

    if title and title_counts.get(title, 0) > 1:
        issues.append(
            GateIssue(
                "duplicate_title_in_batch",
                f"같은 배치 안에 동일한 제목이 중복되었습니다: {title}",
            )
        )

    existing_path = _find_existing_note_path(sonnet_dir, verdict.session_id)
    proposed_path = (
        existing_path
        if existing_path is not None
        else _build_new_note_path(sonnet_dir, verdict.session_id, title)
    )

    if existing_path is None and proposed_path.exists():
        issues.append(
            GateIssue(
                "filepath_conflict",
                f"같은 파일명이 이미 존재합니다: {proposed_path.name}",
            )
        )
    elif existing_path is not None:
        existing_session_id = _extract_session_id(existing_path)
        if (
            existing_session_id is not None
            and existing_session_id != verdict.session_id
        ):
            issues.append(
                GateIssue(
                    "session_marker_conflict",
                    f"재사용 대상 노트에 다른 session_id marker가 있습니다: {existing_path.name}",
                )
            )
        elif existing_session_id is None and not _looks_like_legacy_sonnet_note(
            existing_path,
            verdict.session_id,
        ):
            issues.append(
                GateIssue(
                    "filepath_conflict",
                    f"같은 파일명이 이미 존재하고 소유권을 확인할 수 없습니다: {existing_path.name}",
                )
            )

    if title:
        for note in existing_notes:
            if note.path == existing_path:
                continue
            if note.title != title:
                continue
            if note.session_id == verdict.session_id:
                continue
            issues.append(
                GateIssue(
                    "title_collision",
                    f"같은 제목을 가진 기존 Sonnet 노트가 있습니다: {note.path.name}",
                )
            )
            break

    return issues


def find_potential_duplicates(
    verdicts: list[SessionVerdict],
    sonnet_dir: Path,
    *,
    similarity_threshold: float = 0.6,
    max_matches: int = 3,
) -> list[PotentialDuplicateWarning]:
    """기존 top-level Sonnet과 유사한 strong_candidate 제목을 warning으로 찾는다."""
    existing_notes = _load_existing_notes(sonnet_dir)
    warnings: list[PotentialDuplicateWarning] = []

    for verdict in verdicts:
        if verdict.verdict != "strong_candidate":
            continue
        title = verdict.suggested_title.strip()
        if not title:
            continue

        matches: list[DuplicateCandidate] = []
        for note in existing_notes:
            if not note.title or note.session_id == verdict.session_id:
                continue
            similarity = _title_similarity(title, note.title)
            if similarity < similarity_threshold or note.title == title:
                continue
            matches.append(
                DuplicateCandidate(
                    title=note.title,
                    path=note.path,
                    similarity=similarity,
                )
            )

        if not matches:
            continue
        matches.sort(key=lambda item: item.similarity, reverse=True)
        warnings.append(
            PotentialDuplicateWarning(
                verdict=verdict,
                matches=tuple(matches[:max_matches]),
            )
        )

    return warnings


def _load_existing_notes(sonnet_dir: Path) -> list[ExistingSonnetNote]:
    if not sonnet_dir.exists():
        return []

    notes: list[ExistingSonnetNote] = []
    for path in sorted(sonnet_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        notes.append(
            ExistingSonnetNote(
                path=path,
                title=_extract_title_text(text),
                session_id=_extract_session_id_from_text(text),
            )
        )
    return notes


def _count_sentences(text: str) -> int:
    return len(
        [
            fragment.strip()
            for fragment in re.findall(r"[^.!?]+(?:[.!?]+|$)", text)
            if fragment.strip()
        ]
    )


def _contains_placeholder_text(text: str) -> bool:
    stripped = text.strip()
    if not stripped:
        return False

    if stripped in {"...", "…", "-", "--", "미정"}:
        return True

    return bool(_PLACEHOLDER_TOKEN_RE.search(stripped))


def _session_marker(session_id: str) -> str:
    return _SESSION_MARKER_TEMPLATE.format(session_id=session_id)


def _extract_session_id(path: Path) -> str | None:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return None
    return _extract_session_id_from_text(text)


def _extract_session_id_from_text(text: str) -> str | None:
    match = _SESSION_MARKER_RE.search(text)
    if not match:
        return None
    return match.group(1).strip() or None


def _extract_title_text(text: str) -> str:
    match = _TITLE_RE.search(text)
    if not match:
        return ""
    return match.group(1).strip()


def _slugify_session_id(session_id: str) -> str:
    return session_id.replace(":", "-")


def _build_new_note_path(
    sonnet_dir: Path,
    session_id: str,
    suggested_title: str,
) -> Path:
    safe_title = re.sub(r"\s+", "_", suggested_title) if suggested_title else ""
    safe_session_id = _slugify_session_id(session_id)
    filename = (
        f"{safe_session_id}__{safe_title}.md"
        if safe_title
        else f"{safe_session_id}.md"
    )
    return sonnet_dir / filename


def _looks_like_legacy_sonnet_note(path: Path, session_id: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if "#sonnet" not in text or "#from/ai-session" not in text:
        return False

    legacy_source_pattern = re.compile(
        _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
        _LEGACY_SOURCE_TEMPLATE.flags,
    )
    return bool(legacy_source_pattern.search(text))


def _find_existing_note_path(
    sonnet_dir: Path,
    session_id: str,
) -> Path | None:
    marker = _session_marker(session_id)
    safe_session_id = _slugify_session_id(session_id)
    legacy_matches: list[Path] = []

    if not sonnet_dir.exists():
        return None

    for path in sorted(sonnet_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue

        if marker in text:
            return path

        if (
            path.name.startswith(f"{safe_session_id}__")
            or path.stem == safe_session_id
        ):
            return path

        if "#sonnet" not in text or "#from/ai-session" not in text:
            continue

        legacy_source_pattern = re.compile(
            _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
            _LEGACY_SOURCE_TEMPLATE.flags,
        )
        if legacy_source_pattern.search(text):
            legacy_matches.append(path)

    return legacy_matches[0] if len(legacy_matches) == 1 else None


def _title_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", " ", left).strip().casefold()
    right_norm = re.sub(r"\s+", " ", right).strip().casefold()
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()
