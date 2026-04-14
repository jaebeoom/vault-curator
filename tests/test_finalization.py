from pathlib import Path

from rich.console import Console

from vault_curator import evaluator, finalization, state


def _cfg(vault_root: Path) -> dict:
    return {
        "paths": {
            "vault_root": str(vault_root),
            "haiku_dir": "Haiku",
            "sonnet_dir": "Sonnet",
            "polaris_dir": "Polaris/AI",
            "reports_dir": "reports",
        }
    }


def _write_taxonomy(vault_root: Path) -> None:
    polaris_dir = vault_root / "Polaris" / "AI"
    polaris_dir.mkdir(parents=True)
    (polaris_dir / "tag-taxonomy.md").write_text(
        "\n".join(
            [
                "# Tag Taxonomy",
                "",
                "## 구조 태그",
                "- `#sonnet`",
                "- `#haiku`",
                "- `#daily`",
                "",
                "## 상태 태그",
                "- `#draft`",
                "",
                "## 주제 태그",
                "- `#tech/ai`",
                "- `#investment`",
                "",
                "## 메타 태그",
                "- `#from/ai-session`",
            ]
        ),
        encoding="utf-8",
    )


def _strong_verdict(
    session_id: str,
    title: str,
    *,
    summary: str = "요약",
    thought: str = "문장1. 문장2. 문장3. 문장4.",
    source: str = "출처",
) -> evaluator.SessionVerdict:
    return evaluator.SessionVerdict(
        session_id=session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심",
        suggested_title=title,
        connected_themes=["#tech/ai"],
        sonnet_draft={
            "summary": summary,
            "thought": thought,
            "connections": "개념1, 개념2",
            "source": source,
        },
    )


def test_finalize_result_blocks_invalid_sonnet_and_skips_state_update(
    tmp_path,
) -> None:
    project_dir = tmp_path / "project"
    vault_root = tmp_path / "Vault"
    (vault_root / "Haiku").mkdir(parents=True)
    (vault_root / "Sonnet").mkdir(parents=True)
    _write_taxonomy(vault_root)
    project_dir.mkdir()

    result_file = project_dir / ".curator-result.json"
    prompt_file = project_dir / ".curator-prompt.md"
    meta_file = project_dir / ".curator-meta.json"
    prompt_file.write_text("prompt", encoding="utf-8")
    meta_file.write_text("{}", encoding="utf-8")
    result_file.write_text(
        evaluator.verdicts_to_json(
            [
                _strong_verdict("2026-04-12_09:30", "정상 제목"),
                _strong_verdict("2026-04-12_09:31", ""),
            ]
        ),
        encoding="utf-8",
    )

    finalization.finalize_result(
        _cfg(vault_root),
        result_file,
        console=Console(record=True),
        project_dir=project_dir,
        prompt_file=prompt_file,
        result_file=result_file,
        meta_file=meta_file,
        expected_session_entries={
            "2026-04-12_09:30": "hash-a",
            "2026-04-12_09:31": "hash-b",
        },
        expected_session_count=2,
    )

    sonnet_files = sorted((vault_root / "Sonnet").glob("*.md"))
    assert [path.name for path in sonnet_files] == [
        "2026-04-12_09-30__정상_제목.md",
        "index.md",
    ]
    index_text = (vault_root / "Sonnet" / "index.md").read_text(encoding="utf-8")
    assert "# Sonnet Index" in index_text
    assert "정상 제목" in index_text

    reports_dir = project_dir / "reports"
    report_files = sorted(reports_dir.glob("*.md"))
    assert len(report_files) == 1
    report_text = report_files[0].read_text(encoding="utf-8")
    assert "## Blocked by Admission Gate" in report_text
    assert "2026-04-12_09:31" in report_text
    assert "제목이 비어 있습니다." in report_text

    saved_state = state.load_state(project_dir, haiku_dir=vault_root / "Haiku")
    assert saved_state == {"2026-04-12_09:30": "hash-a"}
    assert not result_file.exists()
    assert not prompt_file.exists()
    assert not meta_file.exists()


def test_finalize_result_reports_blocked_count_in_console(tmp_path) -> None:
    project_dir = tmp_path / "project"
    vault_root = tmp_path / "Vault"
    (vault_root / "Haiku").mkdir(parents=True)
    (vault_root / "Sonnet").mkdir(parents=True)
    _write_taxonomy(vault_root)
    project_dir.mkdir()

    result_file = project_dir / ".curator-result.json"
    result_file.write_text(
        evaluator.verdicts_to_json(
            [_strong_verdict("2026-04-12_09:32", "", summary="")]
        ),
        encoding="utf-8",
    )

    console = Console(record=True)
    finalization.finalize_result(
        _cfg(vault_root),
        result_file,
        console=console,
        project_dir=project_dir,
        prompt_file=project_dir / ".curator-prompt.md",
        result_file=result_file,
        meta_file=project_dir / ".curator-meta.json",
        expected_session_entries={"2026-04-12_09:32": "hash-a"},
        expected_session_count=1,
    )

    console_text = console.export_text()
    assert "Admission gate 차단" in console_text
    assert "0 승격 / 0 borderline / 0 skip / 1 blocked" in console_text
