"""큐레이팅 리포트 생성 및 Synthesis 노트 작성."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from vault_curator.evaluator import SessionVerdict
from vault_curator import synthesis_catalog
from vault_curator.synthesis_gate import BlockedSynthesisDraft, PotentialDuplicateWarning

_SESSION_MARKER_TEMPLATE = "<!-- vault-curator:session_id={session_id} -->"
_LEGACY_SOURCE_TEMPLATE = re.compile(
    r"^## 출처/계기\s+.*?\b{session_id}\b",
    re.MULTILINE | re.DOTALL,
)


def generate_report(
    verdicts: list[SessionVerdict],
    reports_dir: Path,
    expected_session_count: int | None = None,
    deferred_sessions: dict[str, str] | None = None,
    blocked_drafts: list[BlockedSynthesisDraft] | None = None,
    potential_duplicates: list[PotentialDuplicateWarning] | None = None,
) -> Path:
    """마크다운 리포트를 생성하고 파일 경로를 반환."""
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    stem = now.strftime("%Y-%m-%d_%H%M%S")
    report_path = _resolve_unique_report_path(reports_dir, stem)
    content = _build_report_markdown(
        verdicts,
        now,
        expected_session_count=expected_session_count,
        deferred_sessions=deferred_sessions,
        blocked_drafts=blocked_drafts,
        potential_duplicates=potential_duplicates,
    )
    report_path.write_text(content, encoding="utf-8")
    return report_path


def write_source_rollup(
    verdicts: list[SessionVerdict],
    reports_dir: Path,
    source_date: str,
    expected_session_count: int | None = None,
    deferred_sessions: dict[str, str] | None = None,
    blocked_drafts: list[BlockedSynthesisDraft] | None = None,
    potential_duplicates: list[PotentialDuplicateWarning] | None = None,
) -> Path:
    """소스 날짜별 최신 상태를 덮어쓰는 canonical rollup을 작성."""
    rollup_dir = reports_dir / "by-date"
    rollup_dir.mkdir(parents=True, exist_ok=True)
    report_path = rollup_dir / f"{source_date}.md"
    content = _build_report_markdown(
        verdicts,
        datetime.now(),
        expected_session_count=expected_session_count,
        deferred_sessions=deferred_sessions,
        blocked_drafts=blocked_drafts,
        potential_duplicates=potential_duplicates,
    )
    report_path.write_text(content, encoding="utf-8")
    return report_path


def _build_report_markdown(
    verdicts: list[SessionVerdict],
    now: datetime,
    expected_session_count: int | None = None,
    deferred_sessions: dict[str, str] | None = None,
    blocked_drafts: list[BlockedSynthesisDraft] | None = None,
    potential_duplicates: list[PotentialDuplicateWarning] | None = None,
) -> str:
    deferred_sessions = deferred_sessions or {}
    blocked_drafts = blocked_drafts or []
    potential_duplicates = potential_duplicates or []
    strong = [v for v in verdicts if v.verdict == "strong_candidate"]
    borderline = [v for v in verdicts if v.verdict == "borderline"]
    skipped = [v for v in verdicts if v.verdict == "skip"]
    lines: list[str] = []
    lines.append(f"# Capture Review: {now.strftime('%Y-%m-%d %H:%M')}\n")
    total_sessions = (
        expected_session_count
        if expected_session_count is not None
        else len(verdicts) + len(deferred_sessions)
    )
    lines.append(f"> Sessions evaluated: {total_sessions}")
    lines.append(f"> Strong candidates: {len(strong)}")
    lines.append(f"> Borderline: {len(borderline)}")
    lines.append(f"> Skipped: {len(skipped)}\n")
    if deferred_sessions:
        lines.append(f"> Deferred: {len(deferred_sessions)}\n")
    if blocked_drafts:
        lines.append(f"> Blocked by gate: {len(blocked_drafts)}\n")

    # Strong candidates
    if strong:
        lines.append("## Synthesis 승격 후보\n")
        for i, v in enumerate(strong, 1):
            lines.append(f"### {i}. {v.suggested_title} ({v.session_id})")
            lines.append(f"- **핵심:** {v.core_idea}")
            lines.append(f"- **이유:** {v.reasoning}")
            lines.append(
                f"- **테마:** {' '.join(v.connected_themes)}"
            )
            lines.append(
                f"- **소스:** [[{v.session_id.split('_')[0]}]]\n"
            )

    # Borderline
    if borderline:
        lines.append("## Borderline (승격 안 함)\n")
        for v in borderline:
            lines.append(f"- **{v.session_id}**: {v.reasoning}\n")

    if deferred_sessions:
        lines.append("## Deferred (재시도 필요)\n")
        for session_id, reason in deferred_sessions.items():
            short_reason = reason.replace("\n", " ")[:160]
            lines.append(f"- **{session_id}**: {short_reason}\n")

    if blocked_drafts:
        lines.append("## Blocked by Admission Gate\n")
        for blocked in blocked_drafts:
            title = blocked.verdict.suggested_title or "(untitled)"
            lines.append(f"### {title} ({blocked.session_id})")
            for issue in blocked.issues:
                lines.append(f"- {issue.message}")
                for detail in issue.details:
                    lines.append(f"  - {detail}")
            lines.append("")

    if potential_duplicates:
        lines.append("## Potential Duplicates\n")
        for warning in potential_duplicates:
            title = warning.verdict.suggested_title or "(untitled)"
            lines.append(f"### {title} ({warning.session_id})")
            for match in warning.matches:
                lines.append(
                    f"- {match.title} ({match.path.name}, similarity {match.similarity:.2f})"
                )
            lines.append("")

    # Skipped
    if skipped:
        lines.append("## Skipped\n")
        lines.append("| Session | Reason |")
        lines.append("|---------|--------|")
        for v in skipped:
            short_reason = v.reasoning[:80].replace("|", "/")
            lines.append(f"| {v.session_id} | {short_reason} |")
        lines.append("")

    return "\n".join(lines)


def _resolve_unique_report_path(reports_dir: Path, stem: str) -> Path:
    report_path = reports_dir / f"{stem}.md"
    if not report_path.exists():
        return report_path

    suffix = 1
    while True:
        report_path = reports_dir / f"{stem}-{suffix:02d}.md"
        if not report_path.exists():
            return report_path
        suffix += 1


def _session_marker(session_id: str) -> str:
    return _SESSION_MARKER_TEMPLATE.format(session_id=session_id)


def _find_existing_note_path(
    synthesis_dir: Path,
    session_id: str,
) -> Path | None:
    marker = _session_marker(session_id)
    safe_session_id = _slugify_session_id(session_id)
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

        if not _has_synthesis_signature(text):
            continue

        legacy_source_pattern = re.compile(
            _LEGACY_SOURCE_TEMPLATE.pattern.format(session_id=re.escape(session_id)),
            _LEGACY_SOURCE_TEMPLATE.flags,
        )
        if legacy_source_pattern.search(text):
            legacy_matches.append(path)

    return legacy_matches[0] if len(legacy_matches) == 1 else None


def _slugify_session_id(session_id: str) -> str:
    return session_id.replace(":", "-")


def write_synthesis_notes(
    verdicts: list[SessionVerdict],
    synthesis_dir: Path,
) -> list[Path]:
    """strong_candidate의 synthesis_draft를 Vault/Synthesis/에 직접 작성."""
    synthesis_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    strong = [
        v
        for v in verdicts
        if v.verdict == "strong_candidate" and v.synthesis_draft
    ]

    for v in strong:
        draft = v.synthesis_draft
        assert draft is not None

        safe_title = v.suggested_title.strip()
        safe_title = re.sub(r"\s+", "_", safe_title) if safe_title else ""
        existing_path = _find_existing_note_path(synthesis_dir, v.session_id)
        if existing_path is not None:
            filepath = existing_path
        else:
            safe_session_id = _slugify_session_id(v.session_id)
            filename = (
                f"{safe_session_id}__{safe_title}.md"
                if safe_title
                else f"{safe_session_id}.md"
            )
            filepath = synthesis_dir / filename

        content = (
            synthesis_catalog.render_synthesis_note(
                session_id=v.session_id,
                title=v.suggested_title,
                summary=draft.get("summary", ""),
                thought=draft.get("thought", ""),
                connections=draft.get("connections", ""),
                source=draft.get("source", ""),
                subject_tags=v.connected_themes,
            )
        )

        _backup_existing_note(filepath, content)
        filepath.write_text(content, encoding="utf-8")
        written.append(filepath)

    return written


def _backup_existing_note(filepath: Path, new_content: str) -> Path | None:
    if not filepath.exists():
        return None

    current = filepath.read_text(encoding="utf-8")
    if current == new_content:
        return None

    backup_dir = filepath.parent / ".backup"
    backup_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_path = _resolve_unique_backup_path(
        backup_dir / f"{timestamp}__{filepath.name}"
    )
    backup_path.write_text(current, encoding="utf-8")
    return backup_path


def _resolve_unique_backup_path(path: Path) -> Path:
    if not path.exists():
        return path

    suffix = 1
    while True:
        candidate = path.with_name(f"{path.stem}-{suffix:02d}{path.suffix}")
        if not candidate.exists():
            return candidate
        suffix += 1


def _has_synthesis_signature(text: str) -> bool:
    return (
        "#from/ai-session" in text
        and ("#stage/synthesis" in text or "#sonnet" in text)
    )
