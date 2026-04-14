from datetime import datetime as real_datetime

from vault_curator import report, sonnet_gate
from vault_curator.evaluator import SessionVerdict


class FixedDatetime(real_datetime):
    @classmethod
    def now(cls) -> "FixedDatetime":
        return cls(2026, 4, 12, 9, 30, 0)


def _strong_verdict(session_id: str, title: str) -> SessionVerdict:
    return SessionVerdict(
        session_id=session_id,
        verdict="strong_candidate",
        reasoning="판정 이유",
        core_idea="핵심",
        suggested_title=title,
        connected_themes=["#tech/ai"],
        sonnet_draft={
            "summary": "요약",
            "thought": "문장1. 문장2. 문장3. 문장4.",
            "connections": "개념1, 개념2",
            "source": f"{session_id}에서 출발",
        },
    )


def test_generate_report_avoids_same_stem_collisions(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(report, "datetime", FixedDatetime)

    verdicts = [_strong_verdict("2026-04-07_03:09", "제목")]

    first = report.generate_report(verdicts, tmp_path)
    second = report.generate_report(verdicts, tmp_path)

    assert first.name == "2026-04-12_093000.md"
    assert second.name == "2026-04-12_093000-01.md"
    assert first.read_text(encoding="utf-8")
    assert second.read_text(encoding="utf-8")


def test_generate_report_marks_deferred_sessions(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(report, "datetime", FixedDatetime)

    verdicts = [_strong_verdict("2026-04-07_03:09", "제목")]

    report_path = report.generate_report(
        verdicts,
        tmp_path,
        expected_session_count=2,
        deferred_sessions={
            "2026-04-07_03:10": "Local model exhausted output tokens",
        },
    )

    text = report_path.read_text(encoding="utf-8")
    assert "> Sessions evaluated: 2" in text
    assert "> Deferred: 1" in text
    assert "## Deferred (재시도 필요)" in text
    assert "2026-04-07_03:10" in text


def test_generate_report_marks_blocked_drafts(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(report, "datetime", FixedDatetime)

    verdicts = [_strong_verdict("2026-04-07_03:09", "정상 제목")]
    blocked = [
        sonnet_gate.BlockedSonnetDraft(
            verdict=_strong_verdict("2026-04-07_03:11", "막힌 제목"),
            issues=(
                sonnet_gate.GateIssue(
                    "empty_title",
                    "제목이 비어 있습니다.",
                ),
            ),
        )
    ]

    report_path = report.generate_report(
        verdicts,
        tmp_path,
        blocked_drafts=blocked,
    )

    text = report_path.read_text(encoding="utf-8")
    assert "> Blocked by gate: 1" in text
    assert "## Blocked by Admission Gate" in text
    assert "막힌 제목 (2026-04-07_03:11)" in text
    assert "제목이 비어 있습니다." in text


def test_generate_report_marks_potential_duplicates(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(report, "datetime", FixedDatetime)

    verdicts = [_strong_verdict("2026-04-07_03:09", "메모리 사이클의 외생 변수")]
    warnings = [
        sonnet_gate.PotentialDuplicateWarning(
            verdict=verdicts[0],
            matches=(
                sonnet_gate.DuplicateCandidate(
                    title="메모리 슈퍼사이클과 외생 변수",
                    path=tmp_path / "existing.md",
                    similarity=0.72,
                ),
            ),
        )
    ]

    report_path = report.generate_report(
        verdicts,
        tmp_path,
        potential_duplicates=warnings,
    )

    text = report_path.read_text(encoding="utf-8")
    assert "## Potential Duplicates" in text
    assert "메모리 슈퍼사이클과 외생 변수" in text
    assert "similarity 0.72" in text


def test_write_source_rollup_overwrites_canonical_file(
    monkeypatch, tmp_path
) -> None:
    monkeypatch.setattr(report, "datetime", FixedDatetime)
    verdicts = [_strong_verdict("2026-04-07_03:09", "제목")]

    rollup_path = report.write_source_rollup(
        verdicts,
        tmp_path,
        "2026-04-07",
        expected_session_count=1,
    )

    assert rollup_path.name == "2026-04-07.md"
    assert rollup_path.parent.name == "by-date"
    assert "> Sessions evaluated: 1" in rollup_path.read_text(encoding="utf-8")


def test_write_sonnet_notes_reuses_existing_session_note(tmp_path) -> None:
    sonnet_dir = tmp_path / "Sonnet"
    sonnet_dir.mkdir()
    existing = sonnet_dir / "old-title.md"
    existing.write_text(
        "# Old Title\n\n## 출처/계기\n\n2026-04-07_03:09 세션에서 출발\n\n#sonnet #from/ai-session #tech/ai\n",
        encoding="utf-8",
    )

    verdict = _strong_verdict("2026-04-07_03:09", "새 제목")

    written = report.write_sonnet_notes([verdict], sonnet_dir)

    assert written == [existing]
    files = list(sonnet_dir.glob("*.md"))
    assert files == [existing]
    text = existing.read_text(encoding="utf-8")
    assert "<!-- vault-curator:session_id=2026-04-07_03:09 -->" in text
    assert text.startswith(
        "<!-- vault-curator:session_id=2026-04-07_03:09 -->\n# 새 제목"
    )


def test_write_sonnet_notes_does_not_reuse_note_on_loose_session_mention(
    tmp_path,
) -> None:
    sonnet_dir = tmp_path / "Sonnet"
    sonnet_dir.mkdir()
    unrelated = sonnet_dir / "other-note.md"
    unrelated.write_text(
        "# 다른 노트\n\n본문에서 2026-04-07_03:09를 언급만 함.\n",
        encoding="utf-8",
    )

    verdict = _strong_verdict("2026-04-07_03:09", "새 제목")

    written = report.write_sonnet_notes([verdict], sonnet_dir)

    assert len(written) == 1
    assert written[0] != unrelated
    assert written[0].name == "2026-04-07_03-09__새_제목.md"
    assert unrelated.exists()


def test_write_sonnet_notes_uses_session_id_in_new_filenames(tmp_path) -> None:
    verdict = _strong_verdict(
        "2026-04-07_03:09",
        "자산의 세대교체: 원가 방어력과 고정비 부담의 트레이드오프",
    )

    written = report.write_sonnet_notes([verdict], tmp_path)

    assert len(written) == 1
    assert (
        written[0].name
        == "2026-04-07_03-09__자산의_세대교체:_원가_방어력과_고정비_부담의_트레이드오프.md"
    )
    assert written[0].read_text(encoding="utf-8").startswith(
        "<!-- vault-curator:session_id=2026-04-07_03:09 -->"
    )
