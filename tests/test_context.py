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


def test_load_polaris_uses_readme_first_contract(tmp_path) -> None:
    for name, body in {
        "README.md": "readme",
        "tag-taxonomy.md": "taxonomy",
        "writing-voice.md": "voice",
        "about-me.md": "about",
        "top-of-mind.md": "focus",
    }.items():
        (tmp_path / name).write_text(body, encoding="utf-8")

    loaded = context.load_polaris(tmp_path)

    assert loaded.index("### README.md") < loaded.index("### tag-taxonomy.md")
    assert loaded.index("### tag-taxonomy.md") < loaded.index(
        "### writing-voice.md"
    )
    assert loaded.index("### writing-voice.md") < loaded.index(
        "### about-me.md"
    )
    assert loaded.index("### about-me.md") < loaded.index(
        "### top-of-mind.md"
    )


def test_load_polaris_can_skip_optional_personal_context(tmp_path) -> None:
    for name, body in {
        "README.md": "readme",
        "tag-taxonomy.md": "taxonomy",
        "writing-voice.md": "voice",
        "about-me.md": "about",
        "top-of-mind.md": "focus",
    }.items():
        (tmp_path / name).write_text(body, encoding="utf-8")

    loaded = context.load_polaris(
        tmp_path, include_optional_context=False
    )

    assert "### README.md" in loaded
    assert "### tag-taxonomy.md" in loaded
    assert "### writing-voice.md" in loaded
    assert "### about-me.md" not in loaded
    assert "### top-of-mind.md" not in loaded
