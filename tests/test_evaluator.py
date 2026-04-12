import pytest

from vault_curator import evaluator
from vault_curator.parser import HaikuSession


def test_parse_verdicts_extracts_fenced_json_and_normalizes_fields() -> None:
    text = """```json
    {
      "sessions": [
        {
          "session_id": "2026-04-03_0645",
          "verdict": "strong_candidate",
          "reasoning": "판정 이유",
          "core_idea": "핵심",
          "suggested_title": "제목",
          "connected_themes": "#alpha #beta",
          "sonnet_draft": {
            "summary": "요약",
            "thought": "문장1. 문장2. 문장3. 문장4.",
            "connections": "개념A, 개념B",
            "source": "출처"
          }
        }
      ]
    }
    ```"""

    verdicts = evaluator.parse_verdicts(text)

    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.connected_themes == ["#alpha", "#beta"]
    assert verdict.sonnet_draft == {
        "summary": "요약",
        "thought": "문장1. 문장2. 문장3. 문장4.",
        "connections": "개념A, 개념B",
        "source": "출처",
    }


def test_parse_verdicts_handles_list_themes_and_invalid_draft() -> None:
    text = """
    {
      "sessions": [
        {
          "session_id": "2026-04-03_0700",
          "verdict": "borderline",
          "reasoning": "판정 이유",
          "connected_themes": ["#one", " #two ", ""],
          "sonnet_draft": "not-a-dict"
        }
      ]
    }
    """

    verdicts = evaluator.parse_verdicts(text)

    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.connected_themes == ["#one", "#two"]
    assert verdict.sonnet_draft is None


def test_parse_polished_sonnet_extracts_fenced_json() -> None:
    text = """```json
    {
      "title": "다듬은 제목",
      "summary": "요약",
      "thought": "문장1. 문장2. 문장3. 문장4.",
      "connections": "개념1, 개념2",
      "source": "출처"
    }
    ```"""

    polished = evaluator.parse_polished_sonnet(text)

    assert polished == {
        "suggested_title": "다듬은 제목",
        "summary": "요약",
        "thought": "문장1. 문장2. 문장3. 문장4.",
        "connections": "개념1, 개념2",
        "source": "출처",
    }


def test_parse_verdicts_extracts_json_inside_plain_text_wrapper() -> None:
    text = """
    아래가 결과입니다.
    {
      "sessions": [
        {
          "session_id": "2026-04-05_0900",
          "verdict": "skip",
          "reasoning": "테스트",
          "connected_themes": []
        }
      ]
    }
    감사합니다.
    """

    verdicts = evaluator.parse_verdicts(text)

    assert len(verdicts) == 1
    assert verdicts[0].session_id == "2026-04-05_0900"


def test_build_prompt_compresses_long_ai_turns() -> None:
    session = HaikuSession(
        date="2026-04-05",
        time="09:00",
        model="test-model",
        raw_text="\n".join(
            [
                "## AI 세션 (09:00, test-model)",
                "**나**",
                "내 생각은 이렇다.",
                "**AI**: " + ("설명 " * 200),
            ]
        ),
        tags=["#haiku"],
        user_turns=1,
        ai_turns=1,
    )

    prompt = evaluator.build_prompt([session], "context")

    assert "내 생각은 이렇다." in prompt
    assert "...[truncated]" in prompt


def test_build_prompt_keeps_multiple_ai_lines_of_context() -> None:
    session = HaikuSession(
        date="2026-04-05",
        time="09:00",
        model="test-model",
        raw_text="\n".join(
            [
                "## AI 세션 (09:00, test-model)",
                "**나**: 비교 프레임이 중요함",
                "**AI**: 첫 문장",
                "둘째 문장",
                "셋째 문장",
                "넷째 문장",
                "다섯째 문장",
            ]
        ),
        tags=["#haiku"],
        user_turns=1,
        ai_turns=1,
    )

    prompt = evaluator.build_prompt([session], "context")

    assert "첫 문장 | 둘째 문장 | 셋째 문장 | 넷째 문장" in prompt
    assert "...[truncated]" in prompt


def test_split_session_batches_respects_token_budget() -> None:
    polaris_context = "context"
    sessions = [
        HaikuSession(
            date="2026-04-07",
            time=f"0{i}:00",
            model="test-model",
            user_turns=2,
            ai_turns=2,
            tags=["#haiku"],
            raw_text="가" * 12000,
        )
        for i in range(1, 4)
    ]

    batches = evaluator.split_session_batches(
        sessions,
        polaris_context,
        max_tokens_per_batch=6000,
    )

    assert len(batches) == 3
    assert [batch[0].session_id for batch in batches] == [
        "2026-04-07_01:00",
        "2026-04-07_02:00",
        "2026-04-07_03:00",
    ]


def test_split_session_batches_keeps_small_sessions_together() -> None:
    polaris_context = "context"
    sessions = [
        HaikuSession(
            date="2026-04-07",
            time=f"0{i}:00",
            model="test-model",
            user_turns=1,
            ai_turns=1,
            tags=["#haiku"],
            raw_text="짧은 세션",
        )
        for i in range(1, 4)
    ]

    batches = evaluator.split_session_batches(
        sessions,
        polaris_context,
        max_tokens_per_batch=8000,
    )

    assert len(batches) == 1
    assert len(batches[0]) == 3


def test_validate_verdict_coverage_accepts_exact_match() -> None:
    verdicts = [
        evaluator.SessionVerdict(
            session_id="2026-04-07_03:09",
            verdict="skip",
            reasoning="ok",
        ),
        evaluator.SessionVerdict(
            session_id="2026-04-07_03:10",
            verdict="borderline",
            reasoning="ok",
        ),
    ]

    evaluator.validate_verdict_coverage(
        verdicts,
        ["2026-04-07_03:09", "2026-04-07_03:10"],
    )


def test_validate_verdict_coverage_rejects_missing_extra_and_duplicates() -> None:
    verdicts = [
        evaluator.SessionVerdict(
            session_id="2026-04-07_03:09",
            verdict="skip",
            reasoning="ok",
        ),
        evaluator.SessionVerdict(
            session_id="2026-04-07_03:09",
            verdict="borderline",
            reasoning="duplicate",
        ),
        evaluator.SessionVerdict(
            session_id="2026-04-07_03:11",
            verdict="skip",
            reasoning="extra",
        ),
    ]

    with pytest.raises(evaluator.VerdictCoverageError) as exc_info:
        evaluator.validate_verdict_coverage(
            verdicts,
            ["2026-04-07_03:09", "2026-04-07_03:10"],
        )

    message = str(exc_info.value)
    assert "missing=['2026-04-07_03:10']" in message
    assert "extra=['2026-04-07_03:11']" in message
    assert "duplicates=['2026-04-07_03:09']" in message
