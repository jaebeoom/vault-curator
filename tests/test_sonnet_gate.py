from vault_curator import sonnet_gate
from vault_curator.evaluator import SessionVerdict


def _strong_verdict(
    session_id: str,
    title: str = "제목",
    *,
    summary: str = "요약",
    thought: str = "문장1. 문장2. 문장3. 문장4.",
    connections: str = "개념1, 개념2",
    source: str = "출처",
) -> SessionVerdict:
    return SessionVerdict(
        session_id=session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심",
        suggested_title=title,
        connected_themes=["#tech/ai"],
        sonnet_draft={
            "summary": summary,
            "thought": thought,
            "connections": connections,
            "source": source,
        },
    )


def test_apply_admission_gate_blocks_empty_title_and_missing_fields(
    tmp_path,
) -> None:
    verdict = _strong_verdict(
        "2026-04-12_09:30",
        title="",
        summary="",
        source="",
    )

    admitted, blocked = sonnet_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert blocked[0].session_id == "2026-04-12_09:30"
    assert {issue.code for issue in blocked[0].issues} >= {
        "empty_title",
        "missing_summary",
        "missing_source",
    }


def test_apply_admission_gate_blocks_invalid_thought_and_placeholder_text(
    tmp_path,
) -> None:
    verdict = _strong_verdict(
        "2026-04-12_09:31",
        thought="문장1. 문장2.",
        summary="TBD",
    )

    admitted, blocked = sonnet_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} >= {
        "invalid_thought_sentence_count",
        "placeholder_text",
    }


def test_apply_admission_gate_blocks_title_collision_with_existing_note(
    tmp_path,
) -> None:
    existing = tmp_path / "existing.md"
    existing.write_text(
        "<!-- vault-curator:session_id=2026-04-12_09:00 -->\n"
        "# 같은 제목\n\n본문\n",
        encoding="utf-8",
    )
    verdict = _strong_verdict("2026-04-12_09:32", title="같은 제목")

    admitted, blocked = sonnet_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {"title_collision"}


def test_apply_admission_gate_allows_existing_session_note_reuse(
    tmp_path,
) -> None:
    existing = tmp_path / "old-note.md"
    existing.write_text(
        "<!-- vault-curator:session_id=2026-04-12_09:33 -->\n"
        "# 예전 제목\n\n본문\n",
        encoding="utf-8",
    )
    verdict = _strong_verdict("2026-04-12_09:33", title="새 제목")

    admitted, blocked = sonnet_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == [verdict]
    assert blocked == []


def test_apply_admission_gate_blocks_existing_file_conflict(
    tmp_path,
) -> None:
    conflict = tmp_path / "2026-04-12_09-34__제목.md"
    conflict.write_text("# 수동 생성된 파일\n", encoding="utf-8")
    verdict = _strong_verdict("2026-04-12_09:34", title="제목")

    admitted, blocked = sonnet_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {"filepath_conflict"}


def test_apply_admission_gate_blocks_duplicate_titles_within_batch(
    tmp_path,
) -> None:
    first = _strong_verdict("2026-04-12_09:35", title="중복 제목")
    second = _strong_verdict("2026-04-12_09:36", title="중복 제목")

    admitted, blocked = sonnet_gate.apply_admission_gate(
        [first, second],
        tmp_path,
    )

    assert admitted == []
    assert len(blocked) == 2
    assert all(
        any(issue.code == "duplicate_title_in_batch" for issue in blocked_item.issues)
        for blocked_item in blocked
    )
