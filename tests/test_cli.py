from vault_curator import cli, evaluator
from vault_curator.local_client import LocalModelError
from vault_curator.local_client import LocalModelConfig
from vault_curator.parser import CaptureSession


def _verdict(session_id: str, verdict: str = "strong_candidate") -> evaluator.SessionVerdict:
    return evaluator.SessionVerdict(
        session_id=session_id,
        verdict=verdict,
        reasoning="테스트",
    )


def test_resolve_local_model_resolution_reports_env_sources(monkeypatch) -> None:
    cfg = {
        "evaluation": {"model": "evaluation-model"},
        "local": {
            "base_url": "http://config.example/v1",
            "model": "config-model",
            "api_key": "config-key",
        },
    }
    monkeypatch.setenv("OMLX_BASE_URL", "http://env.example/v1")
    monkeypatch.setenv("OMLX_MODEL", "env-model")

    resolution = cli._resolve_local_model_resolution(
        cfg,
        None,
        None,
        None,
        0.2,
        180,
    )

    assert resolution.config.base_url == "http://env.example/v1"
    assert resolution.base_url_source == "env:OMLX_BASE_URL"
    assert resolution.config.model == "env-model"
    assert resolution.model_source == "env:OMLX_MODEL"
    assert resolution.api_key_source == "config.toml:local.api_key"


def test_resolve_local_model_resolution_prefers_cli_over_env(monkeypatch) -> None:
    cfg = {
        "evaluation": {"model": "evaluation-model"},
        "local": {
            "base_url": "http://config.example/v1",
            "model": "config-model",
        },
    }
    monkeypatch.setenv("OMLX_BASE_URL", "http://env.example/v1")
    monkeypatch.setenv("OMLX_MODEL", "env-model")

    resolution = cli._resolve_local_model_resolution(
        cfg,
        "http://cli.example/v1",
        "cli-model",
        "cli-key",
        0.2,
        180,
    )

    assert resolution.config.base_url == "http://cli.example/v1"
    assert resolution.base_url_source == "cli:--base-url"
    assert resolution.config.model == "cli-model"
    assert resolution.model_source == "cli:--model"
    assert resolution.api_key_source == "cli:--api-key"


def test_exclude_failed_draft_verdicts_drops_only_failed_sessions() -> None:
    verdicts = [
        _verdict("2026-04-09_01:03"),
        _verdict("2026-04-09_03:15"),
        _verdict("2026-04-09_09:28", verdict="borderline"),
    ]

    filtered = cli._exclude_failed_draft_verdicts(
        verdicts,
        {"2026-04-09_01:03"},
    )

    assert [verdict.session_id for verdict in filtered] == [
        "2026-04-09_03:15",
        "2026-04-09_09:28",
    ]


def test_exclude_failed_draft_verdicts_noops_without_failures() -> None:
    verdicts = [_verdict("2026-04-09_03:15", verdict="skip")]

    filtered = cli._exclude_failed_draft_verdicts(verdicts, set())

    assert filtered == verdicts


def test_should_split_batch_on_output_token_exhaustion() -> None:
    exc = LocalModelError(
        "Local model exhausted output tokens before producing content. Increase max_output_tokens for this stage."
    )

    assert cli._should_split_batch(exc) is True


def test_evaluate_session_batch_splits_on_coverage_error(monkeypatch) -> None:
    sessions = [
        CaptureSession(
            date="2026-04-10",
            time="01:37",
            model="test-model",
            raw_text="## AI 세션 (01:37, test-model)\n**나**: a\n**AI**: b",
        ),
        CaptureSession(
            date="2026-04-10",
            time="01:40",
            model="test-model",
            raw_text="## AI 세션 (01:40, test-model)\n**나**: c\n**AI**: d",
        ),
    ]
    responses = iter(
        [
            evaluator.verdicts_to_json(
                [
                    _verdict("2026-04-10_01:37", verdict="skip"),
                    _verdict("2026-04-10_01:37", verdict="borderline"),
                ]
            ),
            evaluator.verdicts_to_json(
                [_verdict("2026-04-10_01:37", verdict="skip")]
            ),
            evaluator.verdicts_to_json(
                [_verdict("2026-04-10_01:40", verdict="borderline")]
            ),
        ]
    )

    monkeypatch.setattr(
        cli.local_client,
        "generate_json",
        lambda prompt, model_cfg: next(responses),
    )

    verdicts = cli._evaluate_session_batch(
        sessions,
        "context",
        LocalModelConfig(
            base_url="http://127.0.0.1:8001/v1",
            model="test-model",
        ),
        "배치 1/1",
    )

    assert [verdict.session_id for verdict in verdicts] == [
        "2026-04-10_01:37",
        "2026-04-10_01:40",
    ]


def test_evaluate_session_batch_repairs_time_only_session_id(monkeypatch) -> None:
    sessions = [
        CaptureSession(
            date="2026-04-10",
            time="01:37",
            model="test-model",
            raw_text="## AI 세션 (01:37, test-model)\n**나**: a\n**AI**: b",
        )
    ]

    monkeypatch.setattr(
        cli.local_client,
        "generate_json",
        lambda prompt, model_cfg: evaluator.verdicts_to_json(
            [_verdict("01:37", verdict="skip")]
        ),
    )

    verdicts = cli._evaluate_session_batch(
        sessions,
        "context",
        LocalModelConfig(
            base_url="http://127.0.0.1:8001/v1",
            model="test-model",
        ),
        "배치 1/1",
    )

    assert [verdict.session_id for verdict in verdicts] == [
        "2026-04-10_01:37",
    ]


def test_evaluate_session_batch_repairs_single_session_mismatch(
    monkeypatch,
) -> None:
    sessions = [
        CaptureSession(
            date="2026-04-10",
            time="01:37",
            model="test-model",
            raw_text="## AI 세션 (01:37, test-model)\n**나**: a\n**AI**: b",
        )
    ]

    monkeypatch.setattr(
        cli.local_client,
        "generate_json",
        lambda prompt, model_cfg: evaluator.verdicts_to_json(
            [_verdict("2026-04-10_09:99", verdict="skip")]
        ),
    )

    verdicts = cli._evaluate_session_batch(
        sessions,
        "context",
        LocalModelConfig(
            base_url="http://127.0.0.1:8001/v1",
            model="test-model",
        ),
        "배치 1/1",
    )

    assert [verdict.session_id for verdict in verdicts] == [
        "2026-04-10_01:37",
    ]


def test_evaluate_session_batch_drops_single_session_extra_verdict(
    monkeypatch,
) -> None:
    sessions = [
        CaptureSession(
            date="2026-04-10",
            time="01:37",
            model="test-model",
            raw_text="## AI 세션 (01:37, test-model)\n**나**: a\n**AI**: b",
        )
    ]

    monkeypatch.setattr(
        cli.local_client,
        "generate_json",
        lambda prompt, model_cfg: evaluator.verdicts_to_json(
            [
                _verdict("2026-04-10_01:37", verdict="skip"),
                _verdict("06:25", verdict="borderline"),
            ]
        ),
    )

    verdicts = cli._evaluate_session_batch(
        sessions,
        "context",
        LocalModelConfig(
            base_url="http://127.0.0.1:8001/v1",
            model="test-model",
        ),
        "배치 1/1",
    )

    assert [verdict.session_id for verdict in verdicts] == [
        "2026-04-10_01:37",
    ]


def test_acquire_cli_lock_respects_live_existing_lock(
    monkeypatch, tmp_path
) -> None:
    lock_dir = tmp_path / ".curation.lock"
    lock_dir.mkdir()
    (lock_dir / "pid").write_text("4321\n", encoding="utf-8")

    monkeypatch.setattr(cli, "_LOCK_DIR", lock_dir)
    monkeypatch.setattr(cli, "_LOCK_PID_FILE", lock_dir / "pid")
    monkeypatch.setattr(cli, "_is_pid_alive", lambda pid: True)

    assert cli._acquire_cli_lock() is False


def test_generate_single_synthesis_draft_uses_compact_fallback(monkeypatch) -> None:
    verdict = evaluator.SessionVerdict(
        session_id="2026-04-10_09:09",
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심",
        suggested_title="제목",
        connected_themes=["#tech/ai"],
    )
    session = CaptureSession(
        date="2026-04-10",
        time="09:09",
        model="test-model",
        raw_text="## AI 세션 (09:09, test-model)\n**나**: user point\n**AI**: response",
    )
    responses = iter(
        [
            LocalModelError(
                "Local model exhausted output tokens before producing content."
            ),
            '{"title":"제목","summary":"요약","thought":"문장1. 문장2. 문장3. 문장4.","connections":"개념","source":"출처"}',
        ]
    )

    def fake_generate_json(prompt, model_cfg):
        result = next(responses)
        if isinstance(result, Exception):
            raise result
        return result

    monkeypatch.setattr(cli.local_client, "generate_json", fake_generate_json)

    draft = cli._generate_single_synthesis_draft(
        verdict,
        session,
        "context",
        LocalModelConfig(
            base_url="http://127.0.0.1:8001/v1",
            model="test-model",
        ),
    )

    assert draft["summary"] == "요약"
