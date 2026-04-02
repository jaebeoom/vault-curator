"""Haiku .md 파일을 세션 단위로 파싱."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class HaikuSession:
    date: str  # "2026-03-29"
    time: str  # "05:43"
    model: str  # "Qwen3.5-27B-..."
    raw_text: str
    tags: list[str] = field(default_factory=list)
    user_turns: int = 0
    ai_turns: int = 0
    file_path: Path | None = None

    @property
    def session_id(self) -> str:
        return f"{self.date}_{self.time}"


_HEADER_RE = re.compile(
    r"^## AI 세션 \((\d{2}:\d{2}),\s*(.+?)\)\s*$", re.MULTILINE
)
_TAG_RE = re.compile(r"#[\w/\-]+")


def parse_file(path: Path) -> list[HaikuSession]:
    """하나의 Haiku 일간 파일을 세션 리스트로 파싱."""
    text = path.read_text(encoding="utf-8")
    date = path.stem  # "2026-03-29"

    # --- 구분자로 청크 분리
    chunks = re.split(r"\n---\n", text)
    sessions: list[HaikuSession] = []

    for chunk in chunks:
        match = _HEADER_RE.search(chunk)
        if not match:
            continue  # 날짜 헤더 등 세션이 아닌 청크 스킵

        time_str = match.group(1)
        model = match.group(2)

        # 태그 추출 (청크 마지막 줄에서)
        lines = chunk.strip().splitlines()
        tags: list[str] = []
        for line in reversed(lines):
            line = line.strip()
            if line and all(
                tok.startswith("#") for tok in line.split() if tok
            ):
                tags = _TAG_RE.findall(line)
                break
            elif line:
                break

        # 턴 카운트
        user_turns = len(re.findall(r"^\*\*나\*\*", chunk, re.MULTILINE))
        ai_turns = len(re.findall(r"^\*\*AI\*\*:", chunk, re.MULTILINE))

        sessions.append(
            HaikuSession(
                date=date,
                time=time_str,
                model=model,
                raw_text=chunk.strip(),
                tags=tags,
                user_turns=user_turns,
                ai_turns=ai_turns,
                file_path=path,
            )
        )

    return sessions


def parse_directory(
    haiku_dir: Path, since: str | None = None
) -> list[HaikuSession]:
    """Haiku 디렉토리 전체를 파싱. since가 주어지면 해당 날짜 이후만."""
    files = sorted(haiku_dir.glob("*.md"))
    if since:
        files = [f for f in files if f.stem >= since]

    all_sessions: list[HaikuSession] = []
    for f in files:
        all_sessions.extend(parse_file(f))

    return all_sessions
