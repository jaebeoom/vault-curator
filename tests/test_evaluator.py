from vault_curator import evaluator


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
