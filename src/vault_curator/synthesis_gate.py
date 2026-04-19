"""Synthesis admission gate.

적재 전에 형태적으로 실패한 Synthesis 초안을 차단한다.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
import re

from vault_curator.evaluator import SessionVerdict
from vault_curator import synthesis_catalog


_SESSION_MARKER_TEMPLATE = "<!-- vault-curator:session_id={session_id} -->"
_SESSION_MARKER_RE = re.compile(
    r"^<!-- vault-curator:session_id=(.+?) -->\s*$",
    re.MULTILINE,
)
_LEGACY_SOURCE_TEMPLATE = re.compile(
    r"^## 출처/계기\s+.*?\b{session_id}\b",
    re.MULTILINE | re.DOTALL,
)
_PLACEHOLDER_TOKEN_RE = re.compile(
    r"\b(?:tbd|todo|placeholder|n/?a)\b",
    re.IGNORECASE,
)
_PLACEHOLDER_PHRASES = (
    "초안 편집 대기",
    "실제 초안 입력",
    "초안 입력을 기다",
    "입력 대기",
    "입력을 기다리고",
    "컨텍스트를 확인했으며",
    "제공된 원본을 기다",
)
_UNSAFE_REWRITE_TITLE_THRESHOLD = 0.35
_UNSAFE_REWRITE_SUMMARY_THRESHOLD = 0.35


@dataclass(frozen=True)
class GateIssue:
    code: str
    message: str


@dataclass(frozen=True)
class BlockedSynthesisDraft:
    verdict: SessionVerdict
    issues: tuple[GateIssue, ...]

    @property
    def session_id(self) -> str:
        return self.verdict.session_id


@dataclass(frozen=True)
class ExistingSynthesisNote:
    path: Path
    title: str
    summary: str
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
    synthesis_dir: Path,
) -> tuple[list[SessionVerdict], list[BlockedSynthesisDraft]]:
    """강한 후보 Synthesis draft를 검사해 통과/차단 verdict로 나눈다."""
    strong_titles = [
        verdict.suggested_title.strip()
        for verdict in verdicts
        if verdict.verdict == "strong_candidate" and verdict.suggested_title.strip()
    ]
    title_counts = Counter(strong_titles)
    existing_notes = _load_existing_notes(synthesis_dir)

    admitted: list[SessionVerdict] = []
    blocked: list[BlockedSynthesisDraft] = []

    for verdict in verdicts:
        if verdict.verdict != "strong_candidate":
            admitted.append(verdict)
            continue

        issues = inspect_verdict(
            verdict,
            synthesis_dir,
            existing_notes,
            title_counts,
        )
        if issues:
            blocked.append(
                BlockedSynthesisDraft(verdict=verdict, issues=tuple(issues))
            )
            continue

        admitted.append(verdict)

    return admitted, blocked


def inspect_verdict(
    verdict: SessionVerdict,
    synthesis_dir: Path,
    existing_notes: list[ExistingSynthesisNote] | None = None,
    title_counts: Counter[str] | None = None,
) -> list[GateIssue]:
    """단일 strong_candidate verdict에 대한 gate 이슈를 계산한다."""
    issues: list[GateIssue] = []

    if verdict.verdict != "strong_candidate":
        return issues

    title = verdict.suggested_title.strip()
    draft = verdict.synthesis_draft

    if not draft:
        return [
            GateIssue(
                "missing_synthesis_draft",
                "strong_candidate인데 synthesis_draft가 없습니다.",
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
        if synthesis_catalog.looks_like_python_list(connections):
            issues.append(
                GateIssue(
                    "python_list_connections",
                    "connections가 Python list 형태로 남아 있습니다.",
                )
            )
        if synthesis_catalog.is_tag_only_connections(connections):
            issues.append(
                GateIssue(
                    "tag_only_connections",
                    "connections가 태그만으로 구성되어 있습니다.",
                )
            )

    existing_notes = (
        existing_notes if existing_notes is not None else _load_existing_notes(synthesis_dir)
    )
    title_counts = title_counts or Counter()

    if title and title_counts.get(title, 0) > 1:
        issues.append(
            GateIssue(
                "duplicate_title_in_batch",
                f"같은 배치 안에 동일한 제목이 중복되었습니다: {title}",
            )
        )

    existing_path = _find_existing_note_path(synthesis_dir, verdict.session_id)
    proposed_path = (
        existing_path
        if existing_path is not None
        else _build_new_note_path(synthesis_dir, verdict.session_id, title)
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
        elif existing_session_id is None and not _looks_like_legacy_synthesis_note(
            existing_path,
            verdict.session_id,
        ):
            issues.append(
                GateIssue(
                    "filepath_conflict",
                    f"같은 파일명이 이미 존재하고 소유권을 확인할 수 없습니다: {existing_path.name}",
                )
            )
        else:
            existing_note = _find_existing_note_record(existing_notes, existing_path)
            if existing_note is not None and _is_risky_existing_note_rewrite(
                existing_note,
                title,
                draft,
            ):
                issues.append(
                    GateIssue(
                        "unsafe_existing_note_rewrite",
                        "기존 같은 session_id Synthesis 노트와 새 초안의 제목/요약이 크게 달라 "
                        f"덮어쓰기를 차단합니다: {existing_path.name}",
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
                    f"같은 제목을 가진 기존 Synthesis 노트가 있습니다: {note.path.name}",
                )
            )
            break

    return issues


def find_potential_duplicates(
    verdicts: list[SessionVerdict],
    synthesis_dir: Path,
    *,
    similarity_threshold: float = 0.6,
    max_matches: int = 3,
) -> list[PotentialDuplicateWarning]:
    """기존 top-level Synthesis과 유사한 strong_candidate 제목을 warning으로 찾는다."""
    existing_notes = _load_existing_notes(synthesis_dir)
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


def _load_existing_notes(synthesis_dir: Path) -> list[ExistingSynthesisNote]:
    if not synthesis_dir.exists():
        return []

    notes: list[ExistingSynthesisNote] = []
    for path in sorted(synthesis_dir.glob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        notes.append(_parse_existing_note(path, text))
    return notes


def _parse_existing_note(path: Path, text: str) -> ExistingSynthesisNote:
    parsed = synthesis_catalog.parse_synthesis_note(path, text)
    return ExistingSynthesisNote(
        path=path,
        title=parsed.title,
        summary=parsed.summary,
        session_id=parsed.session_id,
    )


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

    if any(phrase in stripped for phrase in _PLACEHOLDER_PHRASES):
        return True

    return bool(_PLACEHOLDER_TOKEN_RE.search(stripped))


def _find_existing_note_record(
    existing_notes: list[ExistingSynthesisNote],
    existing_path: Path,
) -> ExistingSynthesisNote | None:
    for note in existing_notes:
        if note.path == existing_path:
            return note
    return None


def _is_risky_existing_note_rewrite(
    existing_note: ExistingSynthesisNote,
    new_title: str,
    draft: dict[str, str],
) -> bool:
    existing_title = existing_note.title.strip()
    existing_summary = existing_note.summary.strip()
    new_summary = str(draft.get("summary", "")).strip()

    if not (existing_title and existing_summary and new_title and new_summary):
        return False

    title_similarity = _text_similarity(existing_title, new_title)
    summary_similarity = _text_similarity(existing_summary, new_summary)
    return (
        title_similarity < _UNSAFE_REWRITE_TITLE_THRESHOLD
        and summary_similarity < _UNSAFE_REWRITE_SUMMARY_THRESHOLD
    )


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


def _slugify_session_id(session_id: str) -> str:
    return session_id.replace(":", "-")


def _build_new_note_path(
    synthesis_dir: Path,
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
    return synthesis_dir / filename


def _looks_like_legacy_synthesis_note(path: Path, session_id: str) -> bool:
    try:
        text = path.read_text(encoding="utf-8")
    except OSError:
        return False

    if not _has_synthesis_signature(text):
        return False

    legacy_source_pattern = re.compile(
        _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
        _LEGACY_SOURCE_TEMPLATE.flags,
    )
    return bool(legacy_source_pattern.search(text))


def _find_existing_note_path(
    synthesis_dir: Path,
    session_id: str,
) -> Path | None:
    marker = _session_marker(session_id)
    safe_session_id = _slugify_session_id(session_id)
    legacy_matches: list[Path] = []

    if not synthesis_dir.exists():
        return None

    for path in sorted(synthesis_dir.glob("*.md")):
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

        if not _has_synthesis_signature(text):
            continue

        legacy_source_pattern = re.compile(
            _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
            _LEGACY_SOURCE_TEMPLATE.flags,
        )
        if legacy_source_pattern.search(text):
            legacy_matches.append(path)

    return legacy_matches[0] if len(legacy_matches) == 1 else None


def _title_similarity(left: str, right: str) -> float:
    return _text_similarity(left, right)


def _text_similarity(left: str, right: str) -> float:
    left_norm = re.sub(r"\s+", " ", left).strip().casefold()
    right_norm = re.sub(r"\s+", " ", right).strip().casefold()
    if not left_norm or not right_norm:
        return 0.0
    if left_norm == right_norm:
        return 1.0
    if left_norm in right_norm or right_norm in left_norm:
        shorter = min(len(left_norm), len(right_norm))
        longer = max(len(left_norm), len(right_norm))
        return max(0.8, shorter / longer)
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def _has_synthesis_signature(text: str) -> bool:
    return (
        "#from/ai-session" in text
        and ("#stage/synthesis" in text or "#sonnet" in text)
    )
