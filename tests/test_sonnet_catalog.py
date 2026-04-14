from datetime import datetime

from vault_curator import sonnet_catalog


def test_normalize_connections_items_rewrites_exact_matches_and_drops_tags() -> None:
    note = sonnet_catalog.SonnetNote(
        path=None,  # type: ignore[arg-type]
        date="2026-04-01",
        file_stem="2026-04-01_10-00__기존_노트",
        title="기존 노트",
        summary="요약",
        thought="생각",
        connections="",
        source="출처",
        subject_tags=("#tech/ai",),
        session_id="2026-04-01_10:00",
    )
    lookup = sonnet_catalog.build_lookup([note])

    items = sonnet_catalog.normalize_connections_items(
        "['기존 노트', '#tech/ai', '새 개념']",
        lookup,
    )

    assert items == [
        "[[2026-04-01_10-00__기존_노트|기존 노트]]",
        "새 개념",
    ]


def test_normalize_existing_sonnet_notes_rewrites_connections_and_tags(
    tmp_path,
) -> None:
    sonnet_dir = tmp_path / "Sonnet"
    sonnet_dir.mkdir()
    note = sonnet_dir / "2026-04-12_09-30__테스트.md"
    note.write_text(
        "\n".join(
            [
                "<!-- vault-curator:session_id=2026-04-12_09:30 -->",
                "# 테스트",
                "",
                "> 한 줄 요약: 요약",
                "",
                "## 생각",
                "",
                "문장1. 문장2. 문장3. 문장4.",
                "",
                "## 연결되는 것들",
                "",
                "['개념1', '#tech/ai']",
                "",
                "## 출처/계기",
                "",
                "출처",
                "",
                "#sonnet #from/ai-session #tech/ai #unknown #from/ai-session",
            ]
        ),
        encoding="utf-8",
    )

    changed = sonnet_catalog.normalize_existing_sonnet_notes(
        sonnet_dir,
        {"#tech/ai", "#investment"},
    )

    assert changed == [note]
    text = note.read_text(encoding="utf-8")
    assert "['개념1', '#tech/ai']" not in text
    assert "\n개념1\n" in text
    assert "#unknown" not in text
    assert text.rstrip().endswith("#sonnet #from/ai-session #tech/ai")


def test_write_index_builds_table_for_top_level_notes(tmp_path) -> None:
    sonnet_dir = tmp_path / "Sonnet"
    sonnet_dir.mkdir()
    (sonnet_dir / "2026-04-12_09-30__테스트.md").write_text(
        "\n".join(
            [
                "<!-- vault-curator:session_id=2026-04-12_09:30 -->",
                "# 테스트",
                "",
                "> 한 줄 요약: 요약",
                "",
                "## 생각",
                "",
                "문장1. 문장2. 문장3. 문장4.",
                "",
                "## 연결되는 것들",
                "",
                "개념1",
                "",
                "## 출처/계기",
                "",
                "출처",
                "",
                "#sonnet #from/ai-session #tech/ai",
            ]
        ),
        encoding="utf-8",
    )

    index_path = sonnet_catalog.write_index(
        sonnet_dir,
        generated_at=datetime(2026, 4, 14, 9, 0),
    )

    text = index_path.read_text(encoding="utf-8")
    assert index_path.name == "index.md"
    assert "# Sonnet Index" in text
    assert "마지막 업데이트: 2026-04-14" in text
    assert "[[2026-04-12_09-30__테스트|테스트]]" in text
