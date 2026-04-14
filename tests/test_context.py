from vault_curator import context


def test_load_subject_tags_accepts_headings_with_suffix_text(tmp_path) -> None:
    taxonomy = tmp_path / "tag-taxonomy.md"
    taxonomy.write_text(
        "\n".join(
            [
                "# Tag Taxonomy",
                "",
                "## 구조 태그 (어디에 속하는가)",
                "- `#sonnet`",
                "",
                "## 주제 태그 (무엇에 대한 것인가)",
                "- `#tech/ai`",
                "- `#investment`",
                "",
                "## 메타 태그",
                "- `#from/ai-session`",
            ]
        ),
        encoding="utf-8",
    )

    assert context.load_subject_tags(tmp_path) == {"#tech/ai", "#investment"}
