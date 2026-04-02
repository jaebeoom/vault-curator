"""Polaris 컨텍스트 문서 로더."""

from __future__ import annotations

from pathlib import Path


_CONTEXT_FILES = [
    "about-me.md",
    "top-of-mind.md",
    "tag-taxonomy.md",
    "writing-voice.md",
]


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
