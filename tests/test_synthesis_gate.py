from vault_curator import synthesis_gate
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
        synthesis_draft={
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

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

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

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} >= {
        "invalid_thought_sentence_count",
        "placeholder_text",
    }


def test_apply_admission_gate_blocks_korean_placeholder_text(tmp_path) -> None:
    verdict = _strong_verdict(
        "2026-04-12_09:40",
        title="Synthesis 초안 편집 대기 중",
        summary="편집 규칙과 컨텍스트를 확인했으며, 실제 초안 입력을 기다리고 있습니다.",
    )

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {"placeholder_text"}


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

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

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

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == [verdict]
    assert blocked == []


def test_apply_admission_gate_allows_existing_session_note_with_matching_summary(
    tmp_path,
) -> None:
    existing = tmp_path / "old-note.md"
    existing.write_text(
        "<!-- vault-curator:session_id=2026-04-12_09:41 -->\n"
        "# 예전 제목\n\n"
        "> 한 줄 요약: 같은 핵심 요약입니다.\n\n"
        "## 생각\n\n"
        "기존 본문입니다.\n\n"
        "## 연결되는 것들\n\n"
        "개념1\n\n"
        "## 출처/계기\n\n"
        "출처\n\n"
        "#stage/synthesis #from/ai-session\n",
        encoding="utf-8",
    )
    verdict = _strong_verdict(
        "2026-04-12_09:41",
        title="새 제목",
        summary="같은 핵심 요약입니다.",
    )

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == [verdict]
    assert blocked == []


def test_apply_admission_gate_blocks_risky_existing_session_overwrite(
    tmp_path,
) -> None:
    existing = tmp_path / "old-note.md"
    existing.write_text(
        "<!-- vault-curator:session_id=2026-04-12_09:42 -->\n"
        "# AlphaFold와 TSMC: 기술 해자보다 인프라\n\n"
        "> 한 줄 요약: 생명과학 AI의 경쟁력은 모델 성능보다 실험 인프라와 파운드리 접근권에서 나온다.\n\n"
        "## 생각\n\n"
        "기존 본문입니다.\n\n"
        "## 연결되는 것들\n\n"
        "개념1\n\n"
        "## 출처/계기\n\n"
        "출처\n\n"
        "#stage/synthesis #from/ai-session\n",
        encoding="utf-8",
    )
    verdict = _strong_verdict(
        "2026-04-12_09:42",
        title="작업의 진입 계약과 문맥 관리",
        summary="AI 도구 사용에서는 요청 순서와 문맥 관리가 결과 품질을 좌우한다.",
    )

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {
        "unsafe_existing_note_rewrite"
    }


def test_apply_admission_gate_blocks_existing_file_conflict(
    tmp_path,
) -> None:
    conflict = tmp_path / "2026-04-12_09-34__제목.md"
    conflict.write_text("# 수동 생성된 파일\n", encoding="utf-8")
    verdict = _strong_verdict("2026-04-12_09:34", title="제목")

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {"filepath_conflict"}


def test_apply_admission_gate_blocks_duplicate_titles_within_batch(
    tmp_path,
) -> None:
    first = _strong_verdict("2026-04-12_09:35", title="중복 제목")
    second = _strong_verdict("2026-04-12_09:36", title="중복 제목")

    admitted, blocked = synthesis_gate.apply_admission_gate(
        [first, second],
        tmp_path,
    )

    assert admitted == []
    assert len(blocked) == 2
    assert all(
        any(issue.code == "duplicate_title_in_batch" for issue in blocked_item.issues)
        for blocked_item in blocked
    )


def test_apply_admission_gate_blocks_python_list_connections(tmp_path) -> None:
    verdict = _strong_verdict(
        "2026-04-12_09:37",
        connections="['개념1', '개념2']",
    )

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {
        "python_list_connections"
    }


def test_apply_admission_gate_blocks_tag_only_connections(tmp_path) -> None:
    verdict = _strong_verdict(
        "2026-04-12_09:38",
        connections="#tech/ai #investment",
    )

    admitted, blocked = synthesis_gate.apply_admission_gate([verdict], tmp_path)

    assert admitted == []
    assert len(blocked) == 1
    assert {issue.code for issue in blocked[0].issues} == {
        "tag_only_connections"
    }


def test_find_potential_duplicates_returns_similarity_warnings(
    tmp_path,
) -> None:
    existing = tmp_path / "existing.md"
    existing.write_text(
        "<!-- vault-curator:session_id=2026-04-12_09:00 -->\n"
        "# 메모리 슈퍼사이클과 외생 변수\n\n본문\n",
        encoding="utf-8",
    )
    verdict = _strong_verdict(
        "2026-04-12_09:39",
        title="메모리 사이클의 외생 변수",
    )

    warnings = synthesis_gate.find_potential_duplicates([verdict], tmp_path)

    assert len(warnings) == 1
    assert warnings[0].session_id == "2026-04-12_09:39"
    assert warnings[0].matches[0].title == "메모리 슈퍼사이클과 외생 변수"
