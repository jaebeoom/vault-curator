"""vault-curator CLI.

두 단계로 동작:
1. prepare — Haiku 파싱 + Polaris 컨텍스트 → 평가 프롬프트 파일 생성
2. finalize — 평가 결과 JSON → 리포트 + Sonnet 노트 작성
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Annotated

import typer
from rich.console import Console
from rich.table import Table

from vault_curator import context, evaluator, local_client, parser, report, state

app = typer.Typer(help="Haiku → Sonnet 품질 선별 도구")
console = Console()

_PROJECT_DIR = Path(__file__).resolve().parents[2]
_PROMPT_FILE = _PROJECT_DIR / ".curator-prompt.md"
_RESULT_FILE = _PROJECT_DIR / ".curator-result.json"

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
PolishSonnetOption = Annotated[
    bool,
    typer.Option(help="strong_candidate Sonnet 초안을 한 번 더 다듬기"),
]
IntervalOption = Annotated[
    int | None,
    typer.Option(help="새 파일 확인 주기(초)"),
]
ResultFileOption = Annotated[
    str | None,
    typer.Option(help="평가 결과 JSON 파일 경로 (기본: .curator-result.json)"),
]


def _load_config() -> dict:
    import tomllib

    config_path = _PROJECT_DIR / "config.toml"
    if not config_path.exists():
        console.print("[red]config.toml을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def _resolve_paths(cfg: dict) -> tuple[Path, Path, Path, Path, Path]:
    paths = cfg["paths"]
    vault = Path(paths["vault_root"]).expanduser()
    haiku = vault / paths["haiku_dir"]
    sonnet = vault / paths["sonnet_dir"]
    polaris = vault / paths["polaris_dir"]
    reports = _PROJECT_DIR / paths["reports_dir"]
    return haiku, sonnet, polaris, reports, vault


def _select_files(
    haiku_dir: Path,
    since: str | None,
    force: bool,
) -> list[Path]:
    files = sorted(haiku_dir.glob("*.md"))
    if since:
        files = [f for f in files if f.stem >= since]

    if not files:
        console.print("[yellow]평가할 Haiku 파일이 없습니다.[/yellow]")
        raise typer.Exit(0)

    if not force:
        st = state.load_state(_PROJECT_DIR)
        files = state.filter_new_files(files, st)
        if not files:
            console.print(
                "[green]모든 파일이 이미 평가되었습니다. "
                "--force로 재평가할 수 있습니다.[/green]"
            )
            raise typer.Exit(0)

    return files


def _prepare_prompt(
    cfg: dict,
    since: str | None,
    force: bool,
) -> tuple[str, list[list[parser.HaikuSession]]]:
    haiku_dir, _, polaris_dir, _, _ = _resolve_paths(cfg)
    files = _select_files(haiku_dir, since, force)
    return _prepare_prompt_for_files(cfg, files)


def _prepare_prompt_for_files(
    cfg: dict,
    files: list[Path],
) -> tuple[str, list[list[parser.HaikuSession]]]:
    _, _, polaris_dir, _, _ = _resolve_paths(cfg)

    all_sessions: list[parser.HaikuSession] = []
    for f in files:
        all_sessions.extend(parser.parse_file(f))

    console.print(f"파일 {len(files)}개, 세션 {len(all_sessions)}개 발견")

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

    _PROMPT_FILE.write_text(prompt, encoding="utf-8")
    console.print(
        f"평가 프롬프트 생성: {_PROMPT_FILE} (배치 {len(prompt_chunks)}개)"
    )

    meta = {"files": [str(f) for f in files]}
    (_PROJECT_DIR / ".curator-meta.json").write_text(
        json.dumps(meta, ensure_ascii=False), encoding="utf-8"
    )
    return prompt, session_batches


def _finalize_result(cfg: dict, rfile: Path) -> None:
    _, sonnet_dir, _, reports_dir, _ = _resolve_paths(cfg)

    if not rfile.exists():
        console.print(f"[red]결과 파일이 없습니다: {rfile}[/red]")
        raise typer.Exit(1)

    raw = rfile.read_text(encoding="utf-8")
    verdicts = evaluator.parse_verdicts(raw)

    report_path = report.generate_report(verdicts, reports_dir)
    console.print(f"[bold green]리포트:[/bold green] {report_path}")

    written = report.write_sonnet_notes(verdicts, sonnet_dir)
    if written:
        console.print(
            f"[bold green]Sonnet 노트 {len(written)}개 생성:[/bold green]"
        )
        for p in written:
            console.print(f"  → {p.name}")

    meta_path = _PROJECT_DIR / ".curator-meta.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        files = [Path(f) for f in meta["files"]]
        st = state.load_state(_PROJECT_DIR)
        state.save_state(_PROJECT_DIR, state.update_state(st, files))
        meta_path.unlink()

    if _PROMPT_FILE.exists():
        _PROMPT_FILE.unlink()
    if _RESULT_FILE.exists():
        _RESULT_FILE.unlink()

    strong = sum(1 for v in verdicts if v.verdict == "strong_candidate")
    border = sum(1 for v in verdicts if v.verdict == "borderline")
    skip = sum(1 for v in verdicts if v.verdict == "skip")
    console.print(
        f"\n[bold]결과: {strong} 승격 / {border} borderline / {skip} skip[/bold]"
    )


def _resolve_local_model_config(
    cfg: dict,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float,
    timeout_seconds: int,
) -> local_client.LocalModelConfig:
    local_cfg = cfg.get("local", {})
    resolved_base_url = (
        base_url
        or os.getenv("OMLX_BASE_URL")
        or os.getenv("VAULT_CURATOR_LOCAL_BASE_URL")
        or local_cfg.get("base_url")
        or "http://127.0.0.1:1234/v1"
    )
    resolved_model = (
        model
        or os.getenv("OMLX_MODEL")
        or os.getenv("VAULT_CURATOR_LOCAL_MODEL")
        or local_cfg.get("model")
        or cfg["evaluation"]["model"]
    )
    resolved_api_key = (
        api_key
        or os.getenv("OMLX_API_KEY")
        or os.getenv("VAULT_CURATOR_LOCAL_API_KEY")
        or local_cfg.get("api_key")
    )
    return local_client.LocalModelConfig(
        base_url=resolved_base_url,
        model=resolved_model,
        api_key=resolved_api_key,
        temperature=temperature,
        timeout_seconds=timeout_seconds,
    )


def _should_split_batch(exc: local_client.LocalModelError) -> bool:
    detail = str(exc)
    return "Prompt too long" in detail or "Timed out while calling local model" in detail


def _evaluate_session_batch(
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    batch_label: str,
) -> list[evaluator.SessionVerdict]:
    prompt = evaluator.build_prompt(sessions, polaris_ctx)
    console.print(
        f"[cyan]로컬 모델 평가 실행:[/cyan] "
        f"{model_cfg.model} @ {model_cfg.base_url} ({batch_label})"
    )
    try:
        result_text = local_client.generate_json(prompt, model_cfg)
        return evaluator.parse_verdicts(result_text)
    except local_client.LocalModelError as exc:
        if len(sessions) <= 1 or not _should_split_batch(exc):
            raise
        midpoint = len(sessions) // 2
        console.print(
            f"[yellow]배치 재분할:[/yellow] {batch_label} "
            f"({len(sessions)}개 세션)"
        )
        left = _evaluate_session_batch(
            sessions[:midpoint],
            polaris_ctx,
            model_cfg,
            f"{batch_label}.1",
        )
        right = _evaluate_session_batch(
            sessions[midpoint:],
            polaris_ctx,
            model_cfg,
            f"{batch_label}.2",
        )
        return left + right


def _generate_local_result(
    session_batches: list[list[parser.HaikuSession]],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
) -> str:
    """로컬 모델 1차 평가를 실행하고 결과 파일에 기록."""
    all_verdicts: list[evaluator.SessionVerdict] = []

    for index, batch in enumerate(session_batches, 1):
        label = (
            "배치 1/1"
            if len(session_batches) == 1
            else f"배치 {index}/{len(session_batches)}"
        )
        all_verdicts.extend(
            _evaluate_session_batch(
                batch,
                polaris_ctx,
                replace(model_cfg, max_output_tokens=1600),
                label,
            )
        )

    result_text = evaluator.verdicts_to_json(all_verdicts)
    _RESULT_FILE.write_text(result_text, encoding="utf-8")
    console.print(f"로컬 평가 결과 저장: {_RESULT_FILE}")
    return result_text


def _polish_single_sonnet(
    verdict: evaluator.SessionVerdict,
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
) -> None:
    """단일 Sonnet draft를 polish 결과로 덮어쓴다."""
    assert verdict.sonnet_draft is not None

    draft_payload = {
        "title": verdict.suggested_title,
        "summary": verdict.sonnet_draft.get("summary", ""),
        "thought": verdict.sonnet_draft.get("thought", ""),
        "connections": verdict.sonnet_draft.get("connections", ""),
        "source": verdict.sonnet_draft.get("source", ""),
    }
    polished = evaluator.parse_polished_sonnet(
        local_client.generate_json(
            evaluator.build_polish_prompt(draft_payload, polaris_ctx),
            replace(model_cfg, max_output_tokens=1000),
        )
    )
    verdict.suggested_title = (
        polished["suggested_title"] or verdict.suggested_title
    )
    verdict.sonnet_draft = {
        "summary": polished["summary"]
        or verdict.sonnet_draft.get("summary", ""),
        "thought": polished["thought"]
        or verdict.sonnet_draft.get("thought", ""),
        "connections": polished["connections"]
        or verdict.sonnet_draft.get("connections", ""),
        "source": polished["source"]
        or verdict.sonnet_draft.get("source", ""),
    }


def _polish_sonnet_drafts(
    cfg: dict,
    model_cfg: local_client.LocalModelConfig,
) -> str | None:
    """strong_candidate Sonnet draft들을 polish하고 최종 JSON을 반환."""
    raw = _RESULT_FILE.read_text(encoding="utf-8")
    verdicts = evaluator.parse_verdicts(raw)
    strong = [
        v
        for v in verdicts
        if v.verdict == "strong_candidate" and v.sonnet_draft
    ]
    if not strong:
        return None

    console.print(f"[cyan]Sonnet polish 실행:[/cyan] {len(strong)}개 초안")
    _, _, polaris_dir, _, _ = _resolve_paths(cfg)
    polaris_ctx = context.load_polaris(polaris_dir)
    for verdict in strong:
        _polish_single_sonnet(verdict, polaris_ctx, model_cfg)

    polished_result = evaluator.verdicts_to_json(verdicts)
    _RESULT_FILE.write_text(polished_result, encoding="utf-8")
    console.print("[green]Polish 적용 완료[/green]")
    return polished_result


def _generate_sonnet_drafts(
    verdicts: list[evaluator.SessionVerdict],
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
) -> list[evaluator.SessionVerdict]:
    """strong_candidate에 대해서만 Sonnet 초안을 개별 생성한다."""
    session_map = {session.session_id: session for session in sessions}
    draft_cfg = replace(model_cfg, max_output_tokens=1000)

    for verdict in verdicts:
        if verdict.verdict != "strong_candidate":
            continue
        session = session_map.get(verdict.session_id)
        if session is None:
            continue
        console.print(
            f"[cyan]Sonnet 초안 생성:[/cyan] {verdict.session_id}"
        )
        draft = evaluator.parse_polished_sonnet(
            local_client.generate_json(
                evaluator.build_sonnet_draft_prompt(
                    verdict, session, polaris_ctx
                ),
                draft_cfg,
            )
        )
        verdict.suggested_title = (
            draft["suggested_title"] or verdict.suggested_title
        )
        verdict.sonnet_draft = {
            "summary": draft["summary"],
            "thought": draft["thought"],
            "connections": draft["connections"],
            "source": draft["source"],
        }

    return verdicts


def _run_local_cycle(
    cfg: dict,
    since: str | None,
    force: bool,
    model_cfg: local_client.LocalModelConfig,
    keep_result: bool,
    polish_sonnet: bool,
) -> bool:
    haiku_dir, _, _, _, _ = _resolve_paths(cfg)
    _, _, polaris_dir, _, _ = _resolve_paths(cfg)
    polaris_ctx = context.load_polaris(polaris_dir)
    try:
        files = _select_files(haiku_dir, since, force)
    except typer.Exit as exc:
        if exc.exit_code == 0:
            return False
        raise

    processed = False
    total_files = len(files)

    for index, file in enumerate(files, 1):
        console.print(
            f"[bold cyan]파일 처리 중[/bold cyan] {index}/{total_files}: "
            f"{file.name}"
        )
        sessions = parser.parse_file(file)
        _, session_batches = _prepare_prompt_for_files(cfg, [file])
        result_text = _generate_local_result(
            session_batches, polaris_ctx, model_cfg
        )
        verdicts = evaluator.parse_verdicts(result_text)
        verdicts = _generate_sonnet_drafts(
            verdicts, sessions, polaris_ctx, model_cfg
        )
        final_result_text = evaluator.verdicts_to_json(verdicts)
        _RESULT_FILE.write_text(final_result_text, encoding="utf-8")

        if polish_sonnet:
            polished_result = _polish_sonnet_drafts(cfg, model_cfg)
            if polished_result is not None:
                final_result_text = polished_result

        _finalize_result(cfg, _RESULT_FILE)

        if keep_result:
            _RESULT_FILE.write_text(final_result_text, encoding="utf-8")

        processed = True

    return processed


@app.command()
def prepare(
    since: SinceOption = None,
    force: ForceOption = False,
) -> None:
    """Haiku를 파싱하고 평가 프롬프트를 생성합니다."""
    cfg = _load_config()
    _prepare_prompt(cfg, since, force)


@app.command()
def finalize(
    result_file: ResultFileOption = None,
) -> None:
    """평가 결과 JSON을 읽어 리포트와 Sonnet 노트를 생성합니다."""
    cfg = _load_config()

    # 결과 파일 로드
    rfile = Path(result_file) if result_file else _RESULT_FILE
    if not rfile.exists():
        console.print(
            f"[red]결과 파일이 없습니다: {rfile}[/red]\n"
            "평가 결과 JSON을 .curator-result.json에 저장해주세요."
        )
        raise typer.Exit(1)
    _finalize_result(cfg, rfile)


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
    polish_sonnet: PolishSonnetOption = True,
) -> None:
    """로컬 AI로 평가를 실행하고 바로 리포트/Sonnet까지 생성합니다."""
    cfg = _load_config()
    model_cfg = _resolve_local_model_config(
        cfg, base_url, model, api_key, temperature, timeout_seconds
    )
    try:
        _run_local_cycle(
            cfg, since, force, model_cfg, keep_result, polish_sonnet
        )
    except local_client.LocalModelError as exc:
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
    polish_sonnet: PolishSonnetOption = True,
) -> None:
    """새 Haiku를 계속 감시하며 로컬 AI로 자동 큐레이팅합니다."""
    cfg = _load_config()
    interval_seconds = interval_seconds or cfg.get("automation", {}).get(
        "interval_seconds", 300
    )
    interval_seconds = max(10, interval_seconds)
    model_cfg = _resolve_local_model_config(
        cfg, base_url, model, api_key, temperature, timeout_seconds
    )

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
                polish_sonnet,
            )
            if not processed:
                console.print(
                    f"[dim]새로운 Haiku 없음. {interval_seconds}초 후 재시도[/dim]"
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


@app.command()
def doctor() -> None:
    """환경 헬스체크."""
    cfg = _load_config()
    haiku_dir, sonnet_dir, polaris_dir, _, vault = _resolve_paths(cfg)

    checks = [
        ("Vault root", vault.exists()),
        ("Haiku dir", haiku_dir.exists()),
        ("Sonnet dir", sonnet_dir.exists()),
        ("Polaris dir", polaris_dir.exists()),
        ("config.toml", (_PROJECT_DIR / "config.toml").exists()),
        ("about-me.md", (polaris_dir / "about-me.md").exists()),
        ("top-of-mind.md", (polaris_dir / "top-of-mind.md").exists()),
        ("tag-taxonomy.md", (polaris_dir / "tag-taxonomy.md").exists()),
    ]

    haiku_count = (
        len(list(haiku_dir.glob("*.md"))) if haiku_dir.exists() else 0
    )

    table = Table(title="Doctor Check")
    table.add_column("Item")
    table.add_column("Status")
    for name, ok in checks:
        status = "[green]OK[/green]" if ok else "[red]FAIL[/red]"
        table.add_row(name, status)
    table.add_row("Haiku files", f"{haiku_count}개")

    console.print(table)

    if all(ok for _, ok in checks):
        console.print("\n[bold green]모든 체크 통과![/bold green]")
    else:
        console.print("\n[bold red]일부 항목이 실패했습니다.[/bold red]")
        raise typer.Exit(1)


if __name__ == "__main__":
    app()
