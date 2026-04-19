from vault_curator import synthesis_catalog, synthesis_doctor


def _write_note(
    synthesis_dir,
    *,
    session_id: str,
    title: str,
    summary: str = "핵심 요약입니다.",
    connections: str = "개념1",
    filename: str | None = None,
) -> None:
    safe_session_id = session_id.replace(":", "-")
    safe_title = title.replace(" ", "_")
    path = synthesis_dir / (filename or f"{safe_session_id}__{safe_title}.md")
    path.write_text(
        synthesis_catalog.render_synthesis_note(
            session_id=session_id,
            title=title,
            summary=summary,
            thought="문장1. 문장2. 문장3. 문장4.",
            connections=connections,
            source=f"{session_id}에서 출발",
            subject_tags=["#tech/ai"],
        ),
        encoding="utf-8",
    )


def test_inspect_synthesis_dir_returns_clean_for_consistent_notes(tmp_path) -> None:
    synthesis_dir = tmp_path / "Synthesis"
    synthesis_dir.mkdir()
    _write_note(
        synthesis_dir,
        session_id="2026-04-12_09:30",
        title="좋은 제목",
    )
    synthesis_catalog.write_index(synthesis_dir)

    issues = synthesis_doctor.inspect_synthesis_dir(synthesis_dir)

    assert issues == []


def test_inspect_synthesis_dir_flags_duplicate_session_ids(tmp_path) -> None:
    synthesis_dir = tmp_path / "Synthesis"
    synthesis_dir.mkdir()
    _write_note(
        synthesis_dir,
        session_id="2026-04-12_09:31",
        title="첫 제목",
    )
    _write_note(
        synthesis_dir,
        session_id="2026-04-12_09:31",
        title="둘째 제목",
    )

    issues = synthesis_doctor.inspect_synthesis_dir(synthesis_dir)

    assert "duplicate_session_id" in {issue.code for issue in issues}


def test_inspect_synthesis_dir_flags_note_shape_issues(tmp_path) -> None:
    synthesis_dir = tmp_path / "Synthesis"
    synthesis_dir.mkdir()
    _write_note(
        synthesis_dir,
        session_id="2026-04-12_09:32",
        title="Synthesis 초안 편집 대기 중",
        summary="실제 초안 입력을 기다리고 있습니다.",
        connections="[[missing-note|없는 노트]]",
        filename="2026-04-12_09-32__다른_제목.md",
    )

    issues = synthesis_doctor.inspect_synthesis_dir(synthesis_dir)
    codes = {issue.code for issue in issues}

    assert "filename_title_mismatch" in codes
    assert "placeholder_text" in codes
    assert "broken_synthesis_wikilink" in codes


def test_inspect_synthesis_dir_flags_index_drift(tmp_path) -> None:
    synthesis_dir = tmp_path / "Synthesis"
    synthesis_dir.mkdir()
    _write_note(
        synthesis_dir,
        session_id="2026-04-12_09:33",
        title="좋은 제목",
    )
    (synthesis_dir / "index.md").write_text("# stale\n", encoding="utf-8")

    issues = synthesis_doctor.inspect_synthesis_dir(synthesis_dir)

    assert "index_drift" in {issue.code for issue in issues}
