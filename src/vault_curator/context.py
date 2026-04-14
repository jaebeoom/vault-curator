"""Polaris 컨텍스트 문서 로더."""

from __future__ import annotations

from pathlib import Path
import re


_CONTEXT_FILES = [
    "about-me.md",
    "top-of-mind.md",
    "tag-taxonomy.md",
    "writing-voice.md",
]

_TAG_GROUP_HEADINGS = {
    "구조 태그": "structural",
    "상태 태그": "status",
    "주제 태그": "subject",
    "메타 태그": "meta",
}
_TAG_RE = re.compile(r"`(#[^`]+)`")


def load_polaris(polaris_dir: Path) -> str:
    """Polaris/AI 디렉토리에서 컨텍스트 문서들을 로드해 하나의 문자열로 반환."""
    sections: list[str] = []

    for filename in _CONTEXT_FILES:
        filepath = polaris_dir / filename
        if filepath.exists():
            content = filepath.read_text(encoding="utf-8").strip()
            sections.append(f"### {filename}\n\n{content}")

    if not sections:
        raise FileNotFoundError(
            f"Polaris 컨텍스트 파일을 찾을 수 없습니다: {polaris_dir}"
        )

    return "\n\n---\n\n".join(sections)


def load_allowed_tags(polaris_dir: Path) -> set[str]:
    """tag-taxonomy.md에서 허용 태그 전체를 로드한다."""
    groups = load_tag_groups(polaris_dir)
    allowed: set[str] = set()
    for tags in groups.values():
        allowed.update(tags)
    return allowed


def load_subject_tags(polaris_dir: Path) -> set[str]:
    """tag-taxonomy.md에서 주제 태그만 로드한다."""
    return load_tag_groups(polaris_dir).get("subject", set())


def load_tag_groups(polaris_dir: Path) -> dict[str, set[str]]:
    """tag-taxonomy.md를 섹션별 태그 집합으로 파싱한다."""
    taxonomy_path = polaris_dir / "tag-taxonomy.md"
    if not taxonomy_path.exists():
        raise FileNotFoundError(
            f"tag-taxonomy.md를 찾을 수 없습니다: {taxonomy_path}"
        )

    groups = {group: set() for group in _TAG_GROUP_HEADINGS.values()}
    current_group: str | None = None
    text = taxonomy_path.read_text(encoding="utf-8")
    for line in text.splitlines():
        stripped = line.strip()
        if stripped.startswith("## "):
            heading = stripped[3:].strip()
            current_group = None
            for prefix, group in _TAG_GROUP_HEADINGS.items():
                if heading.startswith(prefix):
                    current_group = group
                    break
            continue
        if current_group is None:
            continue
        for tag in _TAG_RE.findall(stripped):
            groups[current_group].add(tag)

    return groups
