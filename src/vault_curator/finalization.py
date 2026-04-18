"""리포트, Synthesis 노트, state를 최종 반영."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from vault_curator import (
    context,
    evaluator,
    report,
    runtime,
    synthesis_catalog,
    synthesis_gate,
    state,
)


def finalize_result(
    cfg: dict,
    rfile: Path,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    prompt_file: Path = runtime.PROMPT_FILE,
    result_file: Path = runtime.RESULT_FILE,
    meta_file: Path = runtime.META_FILE,
    expected_session_entries: dict[str, str] | None = None,
    expected_session_count: int | None = None,
    deferred_sessions: dict[str, str] | None = None,
    source_dates: list[str] | None = None,
) -> None:
    _, synthesis_dir, polaris_dir, reports_dir, _ = runtime.resolve_paths(
        cfg, project_dir=project_dir
    )

    if not rfile.exists():
        console.print(f"[red]결과 파일이 없습니다: {rfile}[/red]")
        raise typer.Exit(1)

    raw = rfile.read_text(encoding="utf-8")
    verdicts = evaluator.parse_verdicts(raw)
    allowed_subject_tags = context.load_subject_tags(polaris_dir)
    verdicts = synthesis_catalog.normalize_verdicts(
        verdicts,
        synthesis_dir,
        allowed_subject_tags,
    )
    expected_entries = (
        expected_session_entries
        if expected_session_entries is not None
        else runtime.load_expected_session_entries(meta_path=meta_file)
    )
    if expected_entries:
        evaluator.validate_verdict_coverage(
            verdicts,
            list(expected_entries),
        )
    else:
        console.print(
            "[yellow]경고: 기대 세션 메타가 없어 coverage 검증과 상태 갱신을 건너뜁니다.[/yellow]"
        )

    admitted_verdicts, blocked_drafts = synthesis_gate.apply_admission_gate(
        verdicts,
        synthesis_dir,
    )
    potential_duplicates = synthesis_gate.find_potential_duplicates(
        admitted_verdicts,
        synthesis_dir,
    )
    blocked_session_ids = {blocked.session_id for blocked in blocked_drafts}
    admitted_entries = (
        {
            session_id: session_hash
            for session_id, session_hash in expected_entries.items()
            if session_id not in blocked_session_ids
        }
        if expected_entries is not None
        else None
    )

    report_path = report.generate_report(
        admitted_verdicts,
        reports_dir,
        expected_session_count=expected_session_count,
        deferred_sessions=deferred_sessions,
        blocked_drafts=blocked_drafts,
        potential_duplicates=potential_duplicates,
    )
    console.print(f"[bold green]리포트:[/bold green] {report_path}")
    if source_dates and len(source_dates) == 1:
        rollup_path = report.write_source_rollup(
            admitted_verdicts,
            reports_dir,
            source_dates[0],
            expected_session_count=expected_session_count,
            deferred_sessions=deferred_sessions,
            blocked_drafts=blocked_drafts,
            potential_duplicates=potential_duplicates,
        )
        console.print(f"[dim]Rollup:[/dim] {rollup_path}")

    if blocked_drafts:
        console.print(
            f"[yellow]Admission gate 차단:[/yellow] {len(blocked_drafts)}개"
        )
        for blocked in blocked_drafts:
            reason_text = "; ".join(issue.message for issue in blocked.issues)
            console.print(f"  → {blocked.session_id}: {reason_text}")

    written = report.write_synthesis_notes(admitted_verdicts, synthesis_dir)
    index_path = synthesis_catalog.write_index(synthesis_dir)
    if written:
        console.print(
            f"[bold green]Synthesis 노트 {len(written)}개 생성:[/bold green]"
        )
        for path in written:
            console.print(f"  → {path.name}")
    console.print(f"[dim]Synthesis index:[/dim] {index_path}")

    if meta_file.exists():
        capture_dir, _, _, _, _ = runtime.resolve_paths(
            cfg, project_dir=project_dir
        )
        st = state.load_state(project_dir, capture_dir=capture_dir)
        if admitted_entries:
            state.save_state(
                project_dir,
                state.update_state(st, admitted_entries),
            )
        meta_file.unlink()

    if prompt_file.exists():
        prompt_file.unlink()
    if result_file.exists():
        result_file.unlink()

    strong = sum(
        1 for verdict in admitted_verdicts if verdict.verdict == "strong_candidate"
    )
    borderline = sum(
        1 for verdict in admitted_verdicts if verdict.verdict == "borderline"
    )
    skipped = sum(
        1 for verdict in admitted_verdicts if verdict.verdict == "skip"
    )
    blocked = len(blocked_drafts)
    console.print(
        f"\n[bold]결과: {strong} 승격 / {borderline} borderline / "
        f"{skipped} skip / {blocked} blocked[/bold]"
    )
