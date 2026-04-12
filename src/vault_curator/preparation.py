"""입력 선택과 평가 프롬프트 준비."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console

from vault_curator import context, evaluator, parser, runtime, state


def select_pending_inputs(
    haiku_dir: Path,
    since: str | None,
    force: bool,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
) -> list[tuple[Path, list[parser.HaikuSession]]]:
    files = sorted(haiku_dir.glob("*.md"))
    if since:
        files = [f for f in files if f.stem >= since]

    if not files:
        console.print("[yellow]평가할 Haiku 파일이 없습니다.[/yellow]")
        raise typer.Exit(0)

    session_state = (
        {} if force else state.load_state(project_dir, haiku_dir=haiku_dir)
    )
    pending_inputs: list[tuple[Path, list[parser.HaikuSession]]] = []

    for file in files:
        sessions = parser.parse_file(file)
        pending_sessions = (
            sessions
            if force
            else state.filter_new_sessions(sessions, session_state)
        )
        if pending_sessions:
            pending_inputs.append((file, pending_sessions))

    if not pending_inputs:
        console.print(
            "[green]모든 세션이 이미 평가되었습니다. "
            "--force로 재평가할 수 있습니다.[/green]"
        )
        raise typer.Exit(0)

    return pending_inputs


def prepare_prompt(
    cfg: dict,
    since: str | None,
    force: bool,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    prompt_file: Path = runtime.PROMPT_FILE,
    meta_file: Path = runtime.META_FILE,
) -> tuple[str, list[list[parser.HaikuSession]]]:
    haiku_dir, _, _, _, _ = runtime.resolve_paths(cfg, project_dir=project_dir)
    pending_inputs = select_pending_inputs(
        haiku_dir,
        since,
        force,
        console=console,
        project_dir=project_dir,
    )
    return prepare_prompt_for_inputs(
        cfg,
        pending_inputs,
        console=console,
        project_dir=project_dir,
        prompt_file=prompt_file,
        meta_file=meta_file,
    )


def prepare_prompt_for_inputs(
    cfg: dict,
    pending_inputs: list[tuple[Path, list[parser.HaikuSession]]],
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    prompt_file: Path = runtime.PROMPT_FILE,
    meta_file: Path = runtime.META_FILE,
) -> tuple[str, list[list[parser.HaikuSession]]]:
    _, _, polaris_dir, _, _ = runtime.resolve_paths(cfg, project_dir=project_dir)

    all_sessions: list[parser.HaikuSession] = []
    files: list[Path] = []
    for file, sessions in pending_inputs:
        files.append(file)
        all_sessions.extend(sessions)

    console.print(
        f"파일 {len(files)}개, 대기 세션 {len(all_sessions)}개 발견"
    )

    polaris_ctx = context.load_polaris(polaris_dir)
    max_tokens_per_batch = cfg.get("evaluation", {}).get(
        "max_tokens_per_batch", 32000
    )
    session_batches = evaluator.split_session_batches(
        all_sessions, polaris_ctx, max_tokens_per_batch
    )
    prompt_chunks = [
        evaluator.build_prompt(batch, polaris_ctx) for batch in session_batches
    ]
    prompt = prompt_chunks[0] if len(prompt_chunks) == 1 else "\n\n".join(
        [
            f"# Batch {index}/{len(prompt_chunks)}\n\n{chunk}"
            for index, chunk in enumerate(prompt_chunks, 1)
        ]
    )

    prompt_file.write_text(prompt, encoding="utf-8")
    console.print(
        f"평가 프롬프트 생성: {prompt_file} (배치 {len(prompt_chunks)}개)"
    )

    meta = {
        "files": [str(f) for f in files],
        "sessions": state.build_state_entries(all_sessions),
    }
    meta_file.write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return prompt, session_batches
