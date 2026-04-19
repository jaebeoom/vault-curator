"""로컬 모델 평가 실행과 배치 재분할."""

from __future__ import annotations

import os
from dataclasses import dataclass, replace
from pathlib import Path

from rich.console import Console

from vault_curator import evaluator, local_client, parser, runtime


@dataclass(frozen=True)
class ResolvedLocalModelConfig:
    config: local_client.LocalModelConfig
    base_url_source: str
    model_source: str
    api_key_source: str


def _resolve_required_setting(
    cli_value: str | None,
    cli_source: str,
    env_names: tuple[str, ...],
    config_value: str | None,
    config_source: str,
    default_value: str,
    default_source: str,
) -> tuple[str, str]:
    if cli_value:
        return cli_value, cli_source

    for env_name in env_names:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value, f"env:{env_name}"

    if config_value:
        return config_value, config_source

    return default_value, default_source


def _resolve_optional_setting(
    cli_value: str | None,
    cli_source: str,
    env_names: tuple[str, ...],
    config_value: str | None,
    config_source: str,
) -> tuple[str | None, str]:
    if cli_value:
        return cli_value, cli_source

    for env_name in env_names:
        env_value = os.getenv(env_name)
        if env_value:
            return env_value, f"env:{env_name}"

    if config_value:
        return config_value, config_source

    return None, "unset"


def resolve_local_model_resolution(
    cfg: dict,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float,
    timeout_seconds: int,
) -> ResolvedLocalModelConfig:
    local_cfg = cfg.get("local", {})
    resolved_base_url, base_url_source = _resolve_required_setting(
        base_url,
        "cli:--base-url",
        ("OMLX_BASE_URL", "VAULT_CURATOR_LOCAL_BASE_URL"),
        local_cfg.get("base_url"),
        "config.toml:local.base_url",
        "http://127.0.0.1:1234/v1",
        "default",
    )
    resolved_model, model_source = _resolve_required_setting(
        model,
        "cli:--model",
        ("OMLX_MODEL", "VAULT_CURATOR_LOCAL_MODEL"),
        local_cfg.get("model"),
        "config.toml:local.model",
        cfg["evaluation"]["model"],
        "config.toml:evaluation.model",
    )
    resolved_api_key, api_key_source = _resolve_optional_setting(
        api_key,
        "cli:--api-key",
        ("OMLX_API_KEY", "VAULT_CURATOR_LOCAL_API_KEY"),
        local_cfg.get("api_key"),
        "config.toml:local.api_key",
    )
    return ResolvedLocalModelConfig(
        config=local_client.LocalModelConfig(
            base_url=resolved_base_url,
            model=resolved_model,
            api_key=resolved_api_key,
            temperature=temperature,
            timeout_seconds=timeout_seconds,
        ),
        base_url_source=base_url_source,
        model_source=model_source,
        api_key_source=api_key_source,
    )


def resolve_local_model_config(
    cfg: dict,
    base_url: str | None,
    model: str | None,
    api_key: str | None,
    temperature: float,
    timeout_seconds: int,
) -> local_client.LocalModelConfig:
    return resolve_local_model_resolution(
        cfg,
        base_url,
        model,
        api_key,
        temperature,
        timeout_seconds,
    ).config


def should_split_batch(exc: local_client.LocalModelError) -> bool:
    detail = str(exc)
    return (
        "Prompt too long" in detail
        or "Timed out while calling local model" in detail
        or "exhausted output tokens before producing content" in detail
    )


def _split_batch(
    sessions: list[parser.CaptureSession],
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


def _repair_time_only_session_ids(
    verdicts: list[evaluator.SessionVerdict],
    sessions: list[parser.CaptureSession],
) -> list[evaluator.SessionVerdict]:
    if len(sessions) == 1:
        session = sessions[0]
        exact_matches = [
            verdict for verdict in verdicts if verdict.session_id == session.session_id
        ]
        if exact_matches:
            return [exact_matches[0]]

        time_matches = [
            verdict for verdict in verdicts if verdict.session_id == session.time
        ]
        if time_matches:
            time_matches[0].session_id = session.session_id
            return [time_matches[0]]

        if len(verdicts) == 1:
            verdicts[0].session_id = session.session_id
            return verdicts

    expected_ids = {session.session_id for session in sessions}
    time_to_session_id: dict[str, str] = {}
    duplicated_times: set[str] = set()
    for session in sessions:
        if session.time in time_to_session_id:
            duplicated_times.add(session.time)
        time_to_session_id[session.time] = session.session_id

    for verdict in verdicts:
        if verdict.session_id in expected_ids:
            continue
        if verdict.session_id in duplicated_times:
            continue
        repaired = time_to_session_id.get(verdict.session_id)
        if repaired is not None:
            verdict.session_id = repaired

    return verdicts


def evaluate_session_batch(
    sessions: list[parser.CaptureSession],
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
        verdicts = _repair_time_only_session_ids(verdicts, sessions)
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
    session_batches: list[list[parser.CaptureSession]],
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
