"""큐레이션 실행 파이프라인."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import typer
from rich.console import Console

from vault_curator import (
    context,
    drafting,
    evaluator,
    evaluation_runner,
    finalization,
    local_client,
    parser,
    preparation,
    runtime,
    sonnet_catalog,
    state,
)


@dataclass
class FileCycleResult:
    source_date: str
    session_count: int
    final_result_text: str
    deferred_sessions: dict[str, str]


def run_file_cycle(
    cfg: dict,
    file: Path,
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    keep_result: bool,
    polish_sonnet: bool,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    prompt_file: Path = runtime.PROMPT_FILE,
    result_file: Path = runtime.RESULT_FILE,
    meta_file: Path = runtime.META_FILE,
) -> FileCycleResult:
    _, sonnet_dir, polaris_dir, _, _ = runtime.resolve_paths(
        cfg, project_dir=project_dir
    )
    allowed_subject_tags = context.load_subject_tags(polaris_dir)
    _, session_batches = preparation.prepare_prompt_for_inputs(
        cfg,
        [(file, sessions)],
        console=console,
        project_dir=project_dir,
        prompt_file=prompt_file,
        meta_file=meta_file,
    )
    result_text = evaluation_runner.generate_local_result(
        session_batches,
        polaris_ctx,
        model_cfg,
        console=console,
        result_file=result_file,
    )
    verdicts = evaluator.parse_verdicts(result_text)
    verdicts, draft_failures = drafting.generate_sonnet_drafts(
        verdicts,
        sessions,
        polaris_ctx,
        model_cfg,
        console=console,
    )
    verdicts = drafting.exclude_failed_draft_verdicts(verdicts, draft_failures)
    verdicts = sonnet_catalog.normalize_verdicts(
        verdicts,
        sonnet_dir,
        allowed_subject_tags,
    )
    final_result_text = evaluator.verdicts_to_json(verdicts)
    result_file.write_text(final_result_text, encoding="utf-8")

    if polish_sonnet:
        polished_result = drafting.polish_sonnet_drafts(
            cfg,
            model_cfg,
            console=console,
            project_dir=project_dir,
            result_file=result_file,
        )
        if polished_result is not None:
            verdicts = evaluator.parse_verdicts(polished_result)
            verdicts = sonnet_catalog.normalize_verdicts(
                verdicts,
                sonnet_dir,
                allowed_subject_tags,
            )
            final_result_text = evaluator.verdicts_to_json(verdicts)
            result_file.write_text(final_result_text, encoding="utf-8")

    finalization.finalize_result(
        cfg,
        result_file,
        console=console,
        project_dir=project_dir,
        prompt_file=prompt_file,
        result_file=result_file,
        meta_file=meta_file,
        expected_session_entries=state.build_state_entries(
            [
                session
                for session in sessions
                if session.session_id not in draft_failures
            ]
        ),
        expected_session_count=len(sessions),
        deferred_sessions=draft_failures,
        source_dates=[file.stem],
    )

    if keep_result:
        result_file.write_text(final_result_text, encoding="utf-8")

    return FileCycleResult(
        source_date=file.stem,
        session_count=len(sessions),
        final_result_text=final_result_text,
        deferred_sessions=draft_failures,
    )


def run_local_cycle(
    cfg: dict,
    since: str | None,
    force: bool,
    model_cfg: local_client.LocalModelConfig,
    keep_result: bool,
    polish_sonnet: bool,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    prompt_file: Path = runtime.PROMPT_FILE,
    result_file: Path = runtime.RESULT_FILE,
    meta_file: Path = runtime.META_FILE,
) -> bool:
    haiku_dir, _, polaris_dir, _, _ = runtime.resolve_paths(
        cfg, project_dir=project_dir
    )
    polaris_ctx = context.load_polaris(polaris_dir)
    try:
        pending_inputs = preparation.select_pending_inputs(
            haiku_dir,
            since,
            force,
            console=console,
            project_dir=project_dir,
        )
    except typer.Exit as exc:
        if exc.exit_code == 0:
            return False
        raise

    total_files = len(pending_inputs)
    for index, (file, sessions) in enumerate(pending_inputs, 1):
        console.print(
            f"[bold cyan]파일 처리 중[/bold cyan] {index}/{total_files}: "
            f"{file.name}"
        )
        run_file_cycle(
            cfg,
            file,
            sessions,
            polaris_ctx,
            model_cfg,
            keep_result,
            polish_sonnet,
            console=console,
            project_dir=project_dir,
            prompt_file=prompt_file,
            result_file=result_file,
            meta_file=meta_file,
        )

    return True
