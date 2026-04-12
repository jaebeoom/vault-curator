"""로컬 모델 평가 실행과 배치 재분할."""

from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path

from rich.console import Console

from vault_curator import evaluator, local_client, parser, runtime


def resolve_local_model_config(
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


def should_split_batch(exc: local_client.LocalModelError) -> bool:
    detail = str(exc)
    return (
        "Prompt too long" in detail
        or "Timed out while calling local model" in detail
        or "exhausted output tokens before producing content" in detail
    )


def _split_batch(
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    batch_label: str,
    reason: str,
    *,
    console: Console,
) -> list[evaluator.SessionVerdict]:
    midpoint = len(sessions) // 2
    console.print(
        f"[yellow]배치 재분할:[/yellow] {batch_label} "
        f"({len(sessions)}개 세션, {reason})"
    )
    left = evaluate_session_batch(
        sessions[:midpoint],
        polaris_ctx,
        model_cfg,
        f"{batch_label}.1",
        console=console,
    )
    right = evaluate_session_batch(
        sessions[midpoint:],
        polaris_ctx,
        model_cfg,
        f"{batch_label}.2",
        console=console,
    )
    return left + right


def evaluate_session_batch(
    sessions: list[parser.HaikuSession],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    batch_label: str,
    *,
    console: Console,
) -> list[evaluator.SessionVerdict]:
    prompt = evaluator.build_prompt(sessions, polaris_ctx)
    console.print(
        f"[cyan]로컬 모델 평가 실행:[/cyan] "
        f"{model_cfg.model} @ {model_cfg.base_url} ({batch_label})"
    )
    try:
        result_text = local_client.generate_json(prompt, model_cfg)
        verdicts = evaluator.parse_verdicts(result_text)
        evaluator.validate_verdict_coverage(
            verdicts,
            [session.session_id for session in sessions],
        )
        return verdicts
    except evaluator.VerdictCoverageError:
        if len(sessions) <= 1:
            raise
        return _split_batch(
            sessions,
            polaris_ctx,
            model_cfg,
            batch_label,
            "coverage mismatch",
            console=console,
        )
    except local_client.LocalModelError as exc:
        if len(sessions) <= 1 or not should_split_batch(exc):
            raise
        return _split_batch(
            sessions,
            polaris_ctx,
            model_cfg,
            batch_label,
            "model retry",
            console=console,
        )


def generate_local_result(
    session_batches: list[list[parser.HaikuSession]],
    polaris_ctx: str,
    model_cfg: local_client.LocalModelConfig,
    *,
    console: Console,
    result_file: Path = runtime.RESULT_FILE,
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
            evaluate_session_batch(
                batch,
                polaris_ctx,
                replace(model_cfg, max_output_tokens=5000),
                label,
                console=console,
            )
        )

    result_text = evaluator.verdicts_to_json(all_verdicts)
    result_file.write_text(result_text, encoding="utf-8")
    console.print(f"로컬 평가 결과 저장: {result_file}")
    return result_text
