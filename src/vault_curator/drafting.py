"""Sonnet 초안 생성과 polish 단계."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from vault_curator import (
    context,
    evaluator,
    local_client,
    parser,
    runtime,
)


def polish_single_sonnet(
    verdict: evaluator.SessionVerdict,
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    *,
    console: Console,
) -> bool:
    """단일 Sonnet draft를 polish 결과로 덮어쓴다."""
    assert verdict.sonnet_draft is not None

    draft_payload = {
        "title": verdict.suggested_title,
        "summary": verdict.sonnet_draft.get("summary", ""),
        "thought": verdict.sonnet_draft.get("thought", ""),
        "connections": verdict.sonnet_draft.get("connections", ""),
        "source": verdict.sonnet_draft.get("source", ""),
    }
    try:
        polished = evaluator.parse_polished_sonnet(
            local_client.generate_json(
                evaluator.build_polish_prompt(draft_payload, polaris_ctx),
                replace(model_cfg, max_output_tokens=3000),
            )
        )
    except (json.JSONDecodeError, local_client.LocalModelError) as exc:
        console.print(
            f"[yellow]Polish 생략:[/yellow] {verdict.session_id} ({exc})"
        )
        return False

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
    return True


def polish_sonnet_drafts(
    cfg: dict,
    model_cfg: local_client.LocalModelConfig,
    *,
    console: Console,
    project_dir: Path = runtime.PROJECT_DIR,
    result_file: Path = runtime.RESULT_FILE,
) -> str | None:
    """strong_candidate Sonnet draft들을 polish하고 최종 JSON을 반환."""
    raw = result_file.read_text(encoding="utf-8")
    verdicts = evaluator.parse_verdicts(raw)
    strong = [
        verdict
        for verdict in verdicts
        if verdict.verdict == "strong_candidate" and verdict.sonnet_draft
    ]
    if not strong:
        return None

    console.print(f"[cyan]Sonnet polish 실행:[/cyan] {len(strong)}개 초안")
    _, _, polaris_dir, _, _ = runtime.resolve_paths(cfg, project_dir=project_dir)
    polaris_ctx = context.load_polaris(polaris_dir)
    applied = 0
    for verdict in strong:
        if polish_single_sonnet(
            verdict, polaris_ctx, model_cfg, console=console
        ):
            applied += 1

    polished_result = evaluator.verdicts_to_json(verdicts)
    result_file.write_text(polished_result, encoding="utf-8")
    console.print(f"[green]Polish 적용 완료[/green] ({applied}/{len(strong)})")
    return polished_result


def generate_single_sonnet_draft(
    verdict: evaluator.SessionVerdict,
    session: parser.HaikuSession,
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    *,
    console: Console,
) -> dict[str, str]:
    try:
        return evaluator.parse_polished_sonnet(
            local_client.generate_json(
                evaluator.build_sonnet_draft_prompt(
                    verdict,
                    session,
                    polaris_ctx,
                ),
                model_cfg,
            )
        )
    except (json.JSONDecodeError, local_client.LocalModelError) as exc:
        console.print(
            f"[yellow]Compact draft fallback:[/yellow] {verdict.session_id} ({exc})"
        )
        return evaluator.parse_polished_sonnet(
            local_client.generate_json(
                evaluator.build_compact_sonnet_draft_prompt(
                    verdict,
                    session,
                ),
                replace(model_cfg, max_output_tokens=3000),
            )
        )


def generate_sonnet_drafts(
    verdicts: list[evaluator.SessionVerdict],
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    *,
    console: Console,
) -> tuple[list[evaluator.SessionVerdict], dict[str, str]]:
    """strong_candidate에 대해서만 Sonnet 초안을 개별 생성한다."""
    session_map = {session.session_id: session for session in sessions}
    draft_cfg = replace(model_cfg, max_output_tokens=2200)
    failed_sessions: dict[str, str] = {}

    for verdict in verdicts:
        if verdict.verdict != "strong_candidate":
            continue
        session = session_map.get(verdict.session_id)
        if session is None:
            continue
        console.print(
            f"[cyan]Sonnet 초안 생성:[/cyan] {verdict.session_id}"
        )
        try:
            draft = generate_single_sonnet_draft(
                verdict,
                session,
                polaris_ctx,
                draft_cfg,
                console=console,
            )
        except (json.JSONDecodeError, local_client.LocalModelError) as exc:
            failed_sessions[verdict.session_id] = str(exc)
            console.print(
                f"[yellow]Sonnet 초안 보류:[/yellow] {verdict.session_id} ({exc})"
            )
            continue

        verdict.suggested_title = (
            draft["suggested_title"] or verdict.suggested_title
        )
        verdict.sonnet_draft = {
            "summary": draft["summary"],
            "thought": draft["thought"],
            "connections": draft["connections"],
            "source": draft["source"],
        }

    return verdicts, failed_sessions


def exclude_failed_draft_verdicts(
    verdicts: list[evaluator.SessionVerdict],
    failed_session_ids: set[str] | dict[str, str],
) -> list[evaluator.SessionVerdict]:
    if not failed_session_ids:
        return verdicts
    return [
        verdict
        for verdict in verdicts
        if verdict.session_id not in failed_session_ids
    ]
