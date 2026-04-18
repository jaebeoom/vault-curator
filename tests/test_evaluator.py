import pytest

from vault_curator import evaluator
from vault_curator.parser import CaptureSession


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
          "synthesis_draft": {
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
    assert verdict.synthesis_draft == {
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
          "synthesis_draft": "not-a-dict"
        }
      ]
    }
    """

    verdicts = evaluator.parse_verdicts(text)

    assert len(verdicts) == 1
    verdict = verdicts[0]
    assert verdict.connected_themes == ["#one", "#two"]
    assert verdict.synthesis_draft is None


def test_parse_polished_synthesis_extracts_fenced_json() -> None:
    text = """```json
    {
      "title": "다듬은 제목",
      "summary": "요약",
      "thought": "문장1. 문장2. 문장3. 문장4.",
      "connections": "개념1, 개념2",
      "source": "출처"
    }
    ```"""

    polished = evaluator.parse_polished_synthesis(text)

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
    session = CaptureSession(
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
        tags=["#stage/capture"],
        user_turns=1,
        ai_turns=1,
    )

    prompt = evaluator.build_prompt([session], "context")

    assert "내 생각은 이렇다." in prompt
    assert "...[truncated]" in prompt


def test_build_prompt_keeps_multiple_ai_lines_of_context() -> None:
    session = CaptureSession(
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
        tags=["#stage/capture"],
        user_turns=1,
        ai_turns=1,
    )

    prompt = evaluator.build_prompt([session], "context")

    assert "첫 문장 | 둘째 문장 | 셋째 문장 | 넷째 문장" in prompt
    assert "...[truncated]" in prompt


def test_build_prompt_preserves_manual_thought_section() -> None:
    session = CaptureSession(
        date="2026-04-05",
        time="09:00",
        model="Claude Opus 4.6",
        raw_text="\n".join(
            [
                "## PDF 리서치 세션",
                "### 핵심 발췌",
                "AI가 요약한 본문",
                "### 내 생각",
                "필자의 판단은 별도로 보존되어야 한다.",
                "이 문장은 Synthesis framing의 핵심이다.",
                "**AI**: 보조 설명",
            ]
        ),
        tags=["#stage/capture", "#from/pdf"],
        user_turns=1,
        ai_turns=1,
    )

    prompt = evaluator.build_prompt([session], "context")

    assert "### 내 생각" in prompt
    assert "필자의 판단은 별도로 보존되어야 한다." in prompt
    assert "이 문장은 Synthesis framing의 핵심이다." in prompt


def test_build_synthesis_draft_prompt_mentions_nathan_framing_and_source_comment() -> None:
    session = CaptureSession(
        date="2026-04-05",
        time="09:00",
        model="test-model",
        raw_text="\n".join(
            [
                "## AI 세션 (09:00, test-model)",
                "**나**: 후한 말 난세구만 ㅋㅋ",
                "<!-- source: https://x.com/test/status/123 -->",
                "**AI**: 설명",
            ]
        ),
        tags=["#stage/capture"],
        user_turns=1,
        ai_turns=1,
    )
    verdict = evaluator.SessionVerdict(
        session_id=session.session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심 아이디어",
        suggested_title="제목",
        connected_themes=["#topic/test"],
    )

    prompt = evaluator.build_synthesis_draft_prompt(verdict, session, "context")

    assert "Nathan의 짧은 평가/비유/결론" in prompt
    assert "`<!-- source: ... -->`가 있으면" in prompt
    assert "<!-- source: https://x.com/test/status/123 -->" in prompt


def test_build_compact_synthesis_draft_prompt_keeps_source_comment_in_excerpt() -> None:
    session = CaptureSession(
        date="2026-04-05",
        time="09:00",
        model="test-model",
        raw_text="\n".join(
            [
                "## AI 세션 (09:00, test-model)",
                "**나**: 비교 프레임이 중요함",
                "<!-- source: https://www.youtube.com/watch?v=abcdefghijk -->",
                "**AI**: 설명",
            ]
        ),
        tags=["#stage/capture"],
        user_turns=1,
        ai_turns=1,
    )
    verdict = evaluator.SessionVerdict(
        session_id=session.session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심 아이디어",
        suggested_title="제목",
        connected_themes=["#topic/test"],
    )

    prompt = evaluator.build_compact_synthesis_draft_prompt(verdict, session)

    assert "<!-- source: https://www.youtube.com/watch?v=abcdefghijk -->" in prompt
    assert "Nathan 판단의 보조 근거" in prompt


def test_build_compact_synthesis_draft_prompt_uses_manual_thought_excerpt() -> None:
    session = CaptureSession(
        date="2026-04-05",
        time="09:00",
        model="Claude Opus 4.6",
        raw_text="\n".join(
            [
                "## AI 세션 (claude.ai)",
                "### 핵심 발췌",
                "AI 요약",
                "### 내 생각",
                "필자의 독립 판단",
                "후속 기준",
            ]
        ),
        tags=["#stage/capture", "#from/claude-ai"],
        user_turns=1,
        ai_turns=0,
    )
    verdict = evaluator.SessionVerdict(
        session_id=session.session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심 아이디어",
        suggested_title="제목",
        connected_themes=["#topic/test"],
    )

    prompt = evaluator.build_compact_synthesis_draft_prompt(verdict, session)

    assert "### 내 생각" in prompt
    assert "필자의 독립 판단" in prompt


def test_split_session_batches_respects_token_budget() -> None:
    polaris_context = "context"
    sessions = [
        CaptureSession(
            date="2026-04-07",
            time=f"0{i}:00",
            model="test-model",
            user_turns=2,
            ai_turns=2,
            tags=["#stage/capture"],
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
        CaptureSession(
            date="2026-04-07",
            time=f"0{i}:00",
            model="test-model",
            user_turns=1,
            ai_turns=1,
            tags=["#stage/capture"],
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
