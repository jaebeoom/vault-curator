from vault_curator import parser


def test_parse_file_adds_suffixes_for_duplicate_times(tmp_path) -> None:
    capture_file = tmp_path / "2026-04-10.md"
    capture_file.write_text(
        "\n".join(
            [
                "## AI 세션 (01:37, test-model)",
                "**나**: 첫 세션",
                "**AI**: 첫 응답",
                "---",
                "## AI 세션 (01:37, test-model)",
                "**나**: 둘째 세션",
                "**AI**: 둘째 응답",
                "---",
                "## AI 세션 (01:38, test-model)",
                "**나**: 셋째 세션",
                "**AI**: 셋째 응답",
            ]
        ),
        encoding="utf-8",
    )

    sessions = parser.parse_file(capture_file)

    assert sessions[0].session_id.startswith("2026-04-10_01:37__")
    assert sessions[1].session_id.startswith("2026-04-10_01:37__")
    assert sessions[0].session_id != sessions[1].session_id
    assert sessions[2].session_id == "2026-04-10_01:38"


def test_parse_file_keeps_claude_manual_session_with_internal_dividers(tmp_path) -> None:
    capture_file = tmp_path / "2026-03-12.md"
    capture_file.write_text(
        "\n".join(
            [
                "# 2026-03-12 Wednesday",
                "",
                "---",
                "",
                "## AI 세션 (claude.ai, Opus 4.6)",
                "",
                "**나**: 첫 판단",
                "",
                "**AI**: 첫 응답",
                "",
                "---",
                "",
                "**나**: 두번째 판단",
                "",
                "**AI**: 두번째 응답",
                "",
                "#stage/capture #from/claude-ai #investment",
            ]
        ),
        encoding="utf-8",
    )

    sessions = parser.parse_file(capture_file)

    assert len(sessions) == 1
    session = sessions[0]
    assert session.session_id == "2026-03-12_00:00"
    assert session.model == "claude.ai, Opus 4.6"
    assert session.user_turns == 2
    assert session.ai_turns == 2
    assert "#from/claude-ai" in session.tags
    assert "두번째 판단" in session.raw_text


def test_parse_file_reads_capture_marker_without_replacing_timed_session_id(tmp_path) -> None:
    capture_file = tmp_path / "2026-04-10.md"
    capture_file.write_text(
        "\n".join(
            [
                "## AI 세션 (01:37, test-model)",
                "<!-- capture:session-id=tg:999:123456 -->",
                "",
                "**나**: 첫 세션",
                "**AI**: 첫 응답",
                "#stage/capture #from/telegram-bot",
            ]
        ),
        encoding="utf-8",
    )

    [session] = parser.parse_file(capture_file)

    assert session.session_id == "2026-04-10_01:37"
    assert session.capture_session_id == "tg:999:123456"


def test_parse_file_uses_manual_metadata_time_and_model(tmp_path) -> None:
    capture_file = tmp_path / "2026-04-14.md"
    capture_file.write_text(
        "\n".join(
            [
                "## AI 세션 (claude.ai)",
                "",
                "> **모델:** Claude Opus 4.6",
                "> **시작:** 13:45",
                "",
                "**나**: 핵심 질문",
                "**AI**: 응답",
                "<!-- capture:session-id=claude.ai:2026-04-14:01 -->",
                "#stage/capture #from/claude-ai",
            ]
        ),
        encoding="utf-8",
    )

    [session] = parser.parse_file(capture_file)

    assert session.session_id == "2026-04-14_13:45"
    assert session.model == "Claude Opus 4.6"
    assert session.capture_session_id == "claude.ai:2026-04-14:01"


def test_parse_file_supports_pdf_research_session(tmp_path) -> None:
    capture_file = tmp_path / "2026-04-15.md"
    capture_file.write_text(
        "\n".join(
            [
                "## PDF 리서치 세션",
                "",
                "> **AI:** Claude Opus 4.6",
                "> **시작:** 08:20",
                "",
                "### 핵심 발췌",
                "보고서 요약",
                "",
                "### 내 생각",
                "필자의 판단",
                "",
                "<!-- capture:session-id=pdf:2026-04-15:01 -->",
                "#stage/capture #from/pdf",
            ]
        ),
        encoding="utf-8",
    )

    [session] = parser.parse_file(capture_file)

    assert session.session_id == "2026-04-15_08:20"
    assert session.model == "Claude Opus 4.6"
    assert session.capture_session_id == "pdf:2026-04-15:01"
    assert session.user_turns == 1
