"""vault-curator CLI entrypoints."""

from __future__ import annotations

import time
from pathlib import Path
from typing import Annotated, Iterator

import typer
from rich.console import Console
from rich.table import Table

from vault_curator import (
    drafting,
    evaluation_runner,
    evaluator,
    finalization,
    local_client,
    locking,
    parser,
    pipeline,
    preparation,
    runtime,
    synthesis_doctor,
)

app = typer.Typer(help="Capture → Synthesis 품질 선별 도구")
doctor_app = typer.Typer(help="환경과 Vault 정합성 점검")
app.add_typer(doctor_app, name="doctor")
console = Console()

_PROJECT_DIR = runtime.PROJECT_DIR
_PROMPT_FILE = runtime.PROMPT_FILE
_RESULT_FILE = runtime.RESULT_FILE
_LOCK_DIR = _PROJECT_DIR / ".curation.lock"
_LOCK_PID_FILE = _LOCK_DIR / "pid"
_SKIP_CLI_LOCK_ENV = locking.SKIP_CLI_LOCK_ENV

SinceOption = Annotated[
    str | None,
    typer.Option(help="이 날짜 이후만 평가 (YYYY-MM-DD)"),
]
ForceOption = Annotated[bool, typer.Option(help="전체 재평가")]
BaseUrlOption = Annotated[
    str | None,
    typer.Option(
        help="OpenAI-호환 로컬 서버 base URL "
        "(예: http://127.0.0.1:1234/v1)"
    ),
]
ModelOption = Annotated[
    str | None,
    typer.Option(help="로컬 서버에서 사용할 모델명"),
]
ApiKeyOption = Annotated[
    str | None,
    typer.Option(help="필요할 경우 API 키"),
]
TemperatureOption = Annotated[
    float, typer.Option(help="생성 temperature")
]
TimeoutOption = Annotated[int, typer.Option(help="요청 타임아웃(초)")]
KeepResultOption = Annotated[
    bool, typer.Option(help="원본 응답 JSON 파일을 유지")
]
PolishSynthesisOption = Annotated[
    bool,
    typer.Option(help="strong_candidate Synthesis 초안을 한 번 더 다듬기"),
]
IntervalOption = Annotated[
    int | None,
    typer.Option(help="새 파일 확인 주기(초)"),
]
ResultFileOption = Annotated[
    str | None,
    typer.Option(help="평가 결과 JSON 파일 경로 (기본: .curator-result.json)"),
]


def _is_pid_alive(pid: int) -> bool:
    return locking.is_pid_alive(pid)


def _write_lock_pid() -> None:
    locking.write_lock_pid(_LOCK_PID_FILE)


def _acquire_cli_lock() -> bool:
    return locking.acquire_cli_lock(
        _LOCK_DIR,
        console,
        pid_file=_LOCK_PID_FILE,
        is_pid_alive_fn=_is_pid_alive,
    )


def _release_cli_lock() -> None:
    locking.release_cli_lock(_LOCK_DIR)


def _cli_lock() -> Iterator[None]:
    return locking.cli_lock(
        _LOCK_DIR,
        console,
        skip_env_var=_SKIP_CLI_LOCK_ENV,
        pid_file=_LOCK_PID_FILE,
    )


def _load_config() -> dict:
    return runtime.load_config(console, project_dir=_PROJECT_DIR)


def _resolve_paths(cfg: dict) -> tuple[Path, Path, Path, Path, Path]:
    return runtime.resolve_paths(cfg, project_dir=_PROJECT_DIR)


def _select_pending_inputs(
    capture_dir: Path,
    since: str | None,
    force: bool,
) -> list[tuple[Path, list[parser.CaptureSession]]]:
    return preparation.select_pending_inputs(
        capture_dir,
        since,
        force,
        console=console,
        project_dir=_PROJECT_DIR,
    )


def _prepare_prompt(
    cfg: dict,
    since: str | None,
    force: bool,
) -> tuple[str, list[list[parser.CaptureSession]]]:
    return preparation.prepare_prompt(
        cfg,
        since,
        force,
        console=console,
        project_dir=_PROJECT_DIR,
        prompt_file=_PROMPT_FILE,
    )


def _prepare_prompt_for_inputs(
    cfg: dict,
    pending_inputs: list[tuple[Path, list[parser.CaptureSession]]],
) -> tuple[str, list[list[parser.CaptureSession]]]:
    return preparation.prepare_prompt_for_inputs(
        cfg,
        pending_inputs,
        console=console,
        project_dir=_PROJECT_DIR,
        prompt_file=_PROMPT_FILE,
    )


def _load_expected_session_entries() -> dict[str, str]:
    return runtime.load_expected_session_entries()


def _finalize_result(
    cfg: dict,
    rfile: Path,
    expected_session_entries: dict[str, str] | None = None,
    expected_session_count: int | None = None,
    deferred_sessions: dict[str, str] | None = None,
    source_dates: list[str] | None = None,
) -> None:
    finalization.finalize_result(
        cfg,
        rfile,
        console=console,
        project_dir=_PROJECT_DIR,
        prompt_file=_PROMPT_FILE,
        result_file=_RESULT_FILE,
        expected_session_entries=expected_session_entries,
        expected_session_count=expected_session_count,
        deferred_sessions=deferred_sessions,
        source_dates=source_dates,
    )


def _resolve_local_model_config(
    cfg: dict,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float,
    timeout_seconds: int,
) -> local_client.LocalModelConfig:
    return evaluation_runner.resolve_local_model_config(
        cfg,
        base_url,
        model,
        api_key,
        temperature,
        timeout_seconds,
    )


def _resolve_local_model_resolution(
    cfg: dict,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float,
    timeout_seconds: int,
) -> evaluation_runner.ResolvedLocalModelConfig:
    return evaluation_runner.resolve_local_model_resolution(
        cfg,
        base_url,
        model,
        api_key,
        temperature,
        timeout_seconds,
    )


def _print_local_model_resolution(
    resolution: evaluation_runner.ResolvedLocalModelConfig,
) -> None:
    model_cfg = resolution.config
    console.print(
        "[dim]로컬 모델 설정:[/dim] "
        f"{model_cfg.model} @ {model_cfg.base_url} "
        f"(model: {resolution.model_source}, "
        f"endpoint: {resolution.base_url_source})"
    )


def _should_split_batch(exc: local_client.LocalModelError) -> bool:
    return evaluation_runner.should_split_batch(exc)


def _evaluate_session_batch(
    sessions: list[parser.CaptureSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    batch_label: str,
) -> list[evaluator.SessionVerdict]:
    return evaluation_runner.evaluate_session_batch(
        sessions,
        polaris_ctx,
        model_cfg,
        batch_label,
        console=console,
    )


def _generate_single_synthesis_draft(
    verdict: evaluator.SessionVerdict,
    session: parser.CaptureSession,
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
) -> dict[str, str]:
    return drafting.generate_single_synthesis_draft(
        verdict,
        session,
        polaris_ctx,
        model_cfg,
        console=console,
    )


def _exclude_failed_draft_verdicts(
    verdicts: list[evaluator.SessionVerdict],
    failed_session_ids: set[str] | dict[str, str],
) -> list[evaluator.SessionVerdict]:
    return drafting.exclude_failed_draft_verdicts(
        verdicts,
        failed_session_ids,
    )


def _run_local_cycle(
    cfg: dict,
    since: str | None,
    force: bool,
    model_cfg: local_client.LocalModelConfig,
    keep_result: bool,
    polish_synthesis: bool,
) -> bool:
    return pipeline.run_local_cycle(
        cfg,
        since,
        force,
        model_cfg,
        keep_result,
        polish_synthesis,
        console=console,
        project_dir=_PROJECT_DIR,
        prompt_file=_PROMPT_FILE,
        result_file=_RESULT_FILE,
    )


@app.command()
def prepare(
    since: SinceOption = None,
    force: ForceOption = False,
) -> None:
    """Capture를 파싱하고 평가 프롬프트를 생성합니다."""
    with _cli_lock():
        cfg = _load_config()
        _prepare_prompt(cfg, since, force)


@app.command()
def finalize(
    result_file: ResultFileOption = None,
) -> None:
    """평가 결과 JSON을 읽어 리포트와 Synthesis 노트를 생성합니다."""
    with _cli_lock():
        cfg = _load_config()
        rfile = Path(result_file) if result_file else _RESULT_FILE
        if not rfile.exists():
            console.print(
                f"[red]결과 파일이 없습니다: {rfile}[/red]\n"
                "평가 결과 JSON을 .curator-result.json에 저장해주세요."
            )
            raise typer.Exit(1)
        try:
            _finalize_result(cfg, rfile)
        except evaluator.VerdictCoverageError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc


@app.command("local-run")
def local_run(
    since: SinceOption = None,
    force: ForceOption = False,
    base_url: BaseUrlOption = None,
    model: ModelOption = None,
    api_key: ApiKeyOption = None,
    temperature: TemperatureOption = 0.2,
    timeout_seconds: TimeoutOption = 180,
    keep_result: KeepResultOption = False,
    polish_synthesis: PolishSynthesisOption = True,
) -> None:
    """로컬 AI로 평가를 실행하고 바로 리포트/Synthesis까지 생성합니다."""
    with _cli_lock():
        cfg = _load_config()
        resolution = _resolve_local_model_resolution(
            cfg,
            base_url,
            model,
            api_key,
            temperature,
            timeout_seconds,
        )
        _print_local_model_resolution(resolution)
        model_cfg = resolution.config
        try:
            _run_local_cycle(
                cfg,
                since,
                force,
                model_cfg,
                keep_result,
                polish_synthesis,
            )
        except local_client.LocalModelError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc
        except evaluator.VerdictCoverageError as exc:
            console.print(f"[red]{exc}[/red]")
            raise typer.Exit(1) from exc


@app.command("watch-local")
def watch_local(
    since: SinceOption = None,
    interval_seconds: IntervalOption = None,
    base_url: BaseUrlOption = None,
    model: ModelOption = None,
    api_key: ApiKeyOption = None,
    temperature: TemperatureOption = 0.2,
    timeout_seconds: TimeoutOption = 180,
    keep_result: KeepResultOption = False,
    polish_synthesis: PolishSynthesisOption = True,
) -> None:
    """새 Capture를 계속 감시하며 로컬 AI로 자동 큐레이팅합니다."""
    with _cli_lock():
        cfg = _load_config()
        interval_seconds = interval_seconds or cfg.get("automation", {}).get(
            "interval_seconds", 300
        )
        interval_seconds = max(10, interval_seconds)
        resolution = _resolve_local_model_resolution(
            cfg,
            base_url,
            model,
            api_key,
            temperature,
            timeout_seconds,
        )
        _print_local_model_resolution(resolution)
        model_cfg = resolution.config

        console.print(
            "[bold green]자동 큐레이팅 시작[/bold green] "
            f"(주기: {interval_seconds}초)"
        )
        while True:
            try:
                processed = _run_local_cycle(
                    cfg,
                    since,
                    False,
                    model_cfg,
                    keep_result,
                    polish_synthesis,
                )
                if not processed:
                    console.print(
                        f"[dim]새로운 Capture 없음. {interval_seconds}초 후 재시도[/dim]"
                    )
                time.sleep(interval_seconds)
            except KeyboardInterrupt:
                console.print("\n[yellow]자동 큐레이팅을 종료했습니다.[/yellow]")
                raise typer.Exit(0)
            except local_client.LocalModelError as exc:
                console.print(f"[red]{exc}[/red]")
                console.print(
                    f"[dim]{interval_seconds}초 후 다시 시도합니다.[/dim]"
                )
                time.sleep(interval_seconds)
            except evaluator.VerdictCoverageError as exc:
                console.print(f"[red]{exc}[/red]")
                console.print(
                    f"[dim]{interval_seconds}초 후 다시 시도합니다.[/dim]"
                )
                time.sleep(interval_seconds)


@doctor_app.callback(invoke_without_command=True)
def doctor(ctx: typer.Context) -> None:
    """환경 헬스체크."""
    if ctx.invoked_subcommand is not None:
        return

    cfg = _load_config()
    capture_dir, synthesis_dir, polaris_dir, _, vault = _resolve_paths(cfg)

    checks = [
        ("Vault root", vault.exists()),
        ("Capture dir", capture_dir.exists()),
        ("Synthesis dir", synthesis_dir.exists()),
        ("Polaris dir", polaris_dir.exists()),
        ("config.toml", (_PROJECT_DIR / "config.toml").exists()),
        ("README.md", (polaris_dir / "README.md").exists()),
        ("about-me.md", (polaris_dir / "about-me.md").exists()),
        ("top-of-mind.md", (polaris_dir / "top-of-mind.md").exists()),
        ("tag-taxonomy.md", (polaris_dir / "tag-taxonomy.md").exists()),
        ("writing-voice.md", (polaris_dir / "writing-voice.md").exists()),
    ]

    capture_count = (
        len(list(capture_dir.glob("*.md"))) if capture_dir.exists() else 0
    )

    table = Table(title="Doctor Check")
    table.add_column("Item")
    table.add_column("Status")
    for name, ok in checks:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status)
    table.add_row("Capture files", f"{capture_count}개")

    console.print(table)

    if all(ok for _, ok in checks):
        console.print("\n[bold green]모든 체크 통과![/bold green]")
    else:
        console.print("\n[bold red]일부 항목이 실패했습니다.[/bold red]")
        raise typer.Exit(1)


@doctor_app.command("synthesis")
def doctor_synthesis() -> None:
    """Synthesis 노트 정합성을 점검합니다."""
    cfg = _load_config()
    _, synthesis_dir, _, _, _ = _resolve_paths(cfg)
    issues = synthesis_doctor.inspect_synthesis_dir(synthesis_dir)

    table = Table(title="Synthesis Doctor")
    table.add_column("Severity")
    table.add_column("Code")
    table.add_column("File")
    table.add_column("Message")
    for issue in issues:
        severity = (
            "[red]error[/red]"
            if issue.severity == "error"
            else "[yellow]warning[/yellow]"
        )
        table.add_row(
            severity,
            issue.code,
            issue.path.name if issue.path else "",
            issue.message,
        )

    if issues:
        console.print(table)
        console.print(f"\n[bold red]Synthesis doctor: {len(issues)} issue(s)[/bold red]")
        raise typer.Exit(1)

    console.print("[bold green]Synthesis doctor: clean[/bold green]")


if __name__ == "__main__":
    app()
