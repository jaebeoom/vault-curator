"""리포트, Sonnet 노트, state를 최종 반영."""

from __future__ import annotations

from pathlib import Path

import typer
from rich.console import Console

from vault_curator import evaluator, report, runtime, state


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
    _, sonnet_dir, _, reports_dir, _ = runtime.resolve_paths(
        cfg, project_dir=project_dir
    )

    if not rfile.exists():
        console.print(f"[red]결과 파일이 없습니다: {rfile}[/red]")
        raise typer.Exit(1)

    raw = rfile.read_text(encoding="utf-8")
    verdicts = evaluator.parse_verdicts(raw)
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

    report_path = report.generate_report(
        verdicts,
        reports_dir,
        expected_session_count=expected_session_count,
        deferred_sessions=deferred_sessions,
    )
    console.print(f"[bold green]리포트:[/bold green] {report_path}")
    if source_dates and len(source_dates) == 1:
        rollup_path = report.write_source_rollup(
            verdicts,
            reports_dir,
            source_dates[0],
            expected_session_count=expected_session_count,
            deferred_sessions=deferred_sessions,
        )
        console.print(f"[dim]Rollup:[/dim] {rollup_path}")

    written = report.write_sonnet_notes(verdicts, sonnet_dir)
    if written:
        console.print(
            f"[bold green]Sonnet 노트 {len(written)}개 생성:[/bold green]"
        )
        for path in written:
            console.print(f"  → {path.name}")

    if meta_file.exists():
        haiku_dir, _, _, _, _ = runtime.resolve_paths(
            cfg, project_dir=project_dir
        )
        st = state.load_state(project_dir, haiku_dir=haiku_dir)
        if expected_entries:
            state.save_state(
                project_dir,
                state.update_state(st, expected_entries),
            )
        meta_file.unlink()

    if prompt_file.exists():
        prompt_file.unlink()
    if result_file.exists():
        result_file.unlink()

    strong = sum(1 for verdict in verdicts if verdict.verdict == "strong_candidate")
    borderline = sum(1 for verdict in verdicts if verdict.verdict == "borderline")
    skipped = sum(1 for verdict in verdicts if verdict.verdict == "skip")
    console.print(
        f"\n[bold]결과: {strong} 승격 / {borderline} borderline / {skipped} skip[/bold]"
    )
