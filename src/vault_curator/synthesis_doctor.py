"""Synthesis vault consistency checks."""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import re

from vault_curator import synthesis_catalog, synthesis_gate


_SESSION_ID_RE = re.compile(
    r"^\d{4}-\d{2}-\d{2}_\d{2}:\d{2}(?:__[A-Za-z0-9][A-Za-z0-9_-]*)?$"
)
_WIKILINK_RE = re.compile(r"\[\[([^\]|]+)(?:\|[^\]]*)?\]\]")
_INDEX_DATE_RE = re.compile(r"^> 마지막 업데이트: .*$", re.MULTILINE)


@dataclass(frozen=True)
class SynthesisDoctorIssue:
    code: str
    severity: str
    message: str
    path: Path | None = None


def inspect_synthesis_dir(synthesis_dir: Path) -> list[SynthesisDoctorIssue]:
    """Return deterministic consistency issues for top-level Synthesis notes."""
    if not synthesis_dir.exists():
        return [
            SynthesisDoctorIssue(
                code="missing_synthesis_dir",
                severity="error",
                message=f"Synthesis dir does not exist: {synthesis_dir}",
            )
        ]

    notes = synthesis_catalog.load_synthesis_notes(synthesis_dir)
    issues: list[SynthesisDoctorIssue] = []

    _add_duplicate_title_issues(notes, issues)
    _add_duplicate_session_id_issues(notes, issues)

    stems = {note.file_stem for note in notes}
    for note in notes:
        issues.extend(_inspect_note(note, stems))

    issues.extend(_inspect_index(synthesis_dir, notes))
    return sorted(
        issues,
        key=lambda issue: (
            _severity_order(issue.severity),
            issue.code,
            str(issue.path or ""),
            issue.message,
        ),
    )


def _add_duplicate_title_issues(
    notes: list[synthesis_catalog.SynthesisNote],
    issues: list[SynthesisDoctorIssue],
) -> None:
    by_title: dict[str, list[synthesis_catalog.SynthesisNote]] = defaultdict(list)
    for note in notes:
        if note.title:
            by_title[note.title].append(note)

    for title, matches in by_title.items():
        if len(matches) <= 1:
            continue
        files = ", ".join(note.path.name for note in matches)
        issues.append(
            SynthesisDoctorIssue(
                code="duplicate_title",
                severity="error",
                message=f"Duplicate Synthesis title `{title}` in: {files}",
            )
        )


def _add_duplicate_session_id_issues(
    notes: list[synthesis_catalog.SynthesisNote],
    issues: list[SynthesisDoctorIssue],
) -> None:
    by_session: dict[str, list[synthesis_catalog.SynthesisNote]] = defaultdict(list)
    for note in notes:
        if note.session_id:
            by_session[note.session_id].append(note)

    for session_id, matches in by_session.items():
        if len(matches) <= 1:
            continue
        files = ", ".join(note.path.name for note in matches)
        issues.append(
            SynthesisDoctorIssue(
                code="duplicate_session_id",
                severity="error",
                message=f"Duplicate session_id `{session_id}` in: {files}",
            )
        )


def _inspect_note(
    note: synthesis_catalog.SynthesisNote,
    stems: set[str],
) -> list[SynthesisDoctorIssue]:
    issues: list[SynthesisDoctorIssue] = []

    if not note.title:
        issues.append(
            SynthesisDoctorIssue(
                code="missing_title",
                severity="error",
                message="Missing H1 title.",
                path=note.path,
            )
        )

    if not note.session_id:
        issues.append(
            SynthesisDoctorIssue(
                code="missing_session_id",
                severity="warning",
                message="Missing vault-curator session_id marker.",
                path=note.path,
            )
        )
    elif not _SESSION_ID_RE.match(note.session_id):
        issues.append(
            SynthesisDoctorIssue(
                code="invalid_session_id",
                severity="warning",
                message=f"Unexpected session_id format: {note.session_id}",
                path=note.path,
            )
        )

    if note.title:
        expected_title_fragment = re.sub(r"\s+", "_", note.title)
        actual_title_fragment = _filename_title_fragment(note.path)
        if actual_title_fragment and actual_title_fragment != expected_title_fragment:
            issues.append(
                SynthesisDoctorIssue(
                    code="filename_title_mismatch",
                    severity="warning",
                    message=(
                        "Filename title fragment does not match H1 title: "
                        f"`{actual_title_fragment}` != `{expected_title_fragment}`"
                    ),
                    path=note.path,
                )
            )

    for field_name, value in (
        ("title", note.title),
        ("summary", note.summary),
        ("thought", note.thought),
        ("connections", note.connections),
        ("source", note.source),
    ):
        if value and synthesis_gate.contains_placeholder_text(value):
            issues.append(
                SynthesisDoctorIssue(
                    code="placeholder_text",
                    severity="error",
                    message=f"{field_name} contains placeholder-like text.",
                    path=note.path,
                )
            )

    for target in _wikilink_targets(note.connections):
        if target not in stems:
            issues.append(
                SynthesisDoctorIssue(
                    code="broken_synthesis_wikilink",
                    severity="warning",
                    message=f"connections links to missing Synthesis note: [[{target}]]",
                    path=note.path,
                )
            )

    return issues


def _inspect_index(
    synthesis_dir: Path,
    notes: list[synthesis_catalog.SynthesisNote],
) -> list[SynthesisDoctorIssue]:
    index_path = synthesis_dir / "index.md"
    if not index_path.exists():
        return [
            SynthesisDoctorIssue(
                code="missing_index",
                severity="warning",
                message="Synthesis index.md is missing.",
                path=index_path,
            )
        ]

    try:
        current = index_path.read_text(encoding="utf-8")
    except OSError as exc:
        return [
            SynthesisDoctorIssue(
                code="unreadable_index",
                severity="error",
                message=f"Cannot read Synthesis index.md: {exc}",
                path=index_path,
            )
        ]

    expected = synthesis_catalog.build_index_markdown(
        notes,
        generated_at=datetime(2000, 1, 1),
    )
    if _normalize_index(current) != _normalize_index(expected):
        return [
            SynthesisDoctorIssue(
                code="index_drift",
                severity="warning",
                message="Synthesis index.md does not match current top-level notes.",
                path=index_path,
            )
        ]
    return []


def _filename_title_fragment(path: Path) -> str:
    if "__" not in path.stem:
        return ""
    return path.stem.split("__", 1)[1]


def _wikilink_targets(text: str) -> list[str]:
    targets: list[str] = []
    for match in _WIKILINK_RE.finditer(text):
        target = match.group(1).strip().split("#", 1)[0]
        if target:
            targets.append(Path(target).name)
    return targets


def _normalize_index(text: str) -> str:
    without_date = _INDEX_DATE_RE.sub("> 마지막 업데이트: <ignored>", text)
    return without_date.strip()


def _severity_order(severity: str) -> int:
    return {"error": 0, "warning": 1}.get(severity, 2)
