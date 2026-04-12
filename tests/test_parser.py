from vault_curator import parser


def test_parse_file_adds_suffixes_for_duplicate_times(tmp_path) -> None:
    haiku_file = tmp_path / "2026-04-10.md"
    haiku_file.write_text(
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

    sessions = parser.parse_file(haiku_file)

    assert sessions[0].session_id.startswith("2026-04-10_01:37__")
    assert sessions[1].session_id.startswith("2026-04-10_01:37__")
    assert sessions[0].session_id != sessions[1].session_id
    assert sessions[2].session_id == "2026-04-10_01:38"
