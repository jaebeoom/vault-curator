"""Capture .md 파일을 세션 단위로 파싱."""

from __future__ import annotations

from collections import Counter
import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path


@dataclass
class CaptureSession:
    date: str  # "2026-03-29"
    time: str  # "05:43"
    model: str  # "Qwen3.5-27B-..."
    raw_text: str
    capture_session_id: str | None = None
    tags: list[str] = field(default_factory=list)
    user_turns: int = 0
    ai_turns: int = 0
    file_path: Path | None = None
    duplicate_count: int = 1
    duplicate_suffix: str = ""

    @property
    def session_id(self) -> str:
        base = f"{self.date}_{self.time}"
        if self.duplicate_suffix:
            return f"{base}__{self.duplicate_suffix}"
        return base


_SESSION_HEADER_RE = re.compile(
    r"^## (?:(?P<ai_label>AI 세션) \((?P<ai_meta>.+?)\)|"
    r"(?P<manual_label>PDF 리서치 세션|책/독후감 세션|웹 리서치 세션))\s*$",
    re.MULTILINE,
)
_TIMED_AI_META_RE = re.compile(r"^(?P<time>\d{2}:\d{2}),\s*(?P<model>.+?)\s*$")
_CAPTURE_SESSION_ID_RE = re.compile(
    r"^<!--\s*capture:session-id=(?P<session_id>.+?)\s*-->\s*$",
    re.MULTILINE,
)
_META_LINE_RE_TEMPLATE = r"^>\s+\*\*{label}:\*\*\s*(.+?)\s*$"
_TAG_RE = re.compile(r"#[\w/\-]+")
_TRAILING_DIVIDER_RE = re.compile(r"\n\s*---\s*$")


def _stable_duplicate_suffix(session: CaptureSession) -> str:
    return hashlib.sha1(session.raw_text.encode("utf-8")).hexdigest()[:8]


def _metadata_value(chunk: str, label: str) -> str:
    pattern = re.compile(
        _META_LINE_RE_TEMPLATE.format(label=re.escape(label)),
        re.MULTILINE,
    )
    match = pattern.search(chunk)
    return match.group(1).strip() if match else ""


def _capture_session_id(chunk: str) -> str | None:
    match = _CAPTURE_SESSION_ID_RE.search(chunk)
    if not match:
        return None
    return match.group("session_id").strip() or None


def _clean_session_chunk(chunk: str) -> str:
    return _TRAILING_DIVIDER_RE.sub("", chunk.strip()).strip()


def _session_time_and_model(match: re.Match[str], chunk: str) -> tuple[str, str]:
    ai_meta = match.group("ai_meta")
    if ai_meta:
        timed_match = _TIMED_AI_META_RE.match(ai_meta.strip())
        if timed_match:
            return timed_match.group("time"), timed_match.group("model").strip()

        start_time = _metadata_value(chunk, "시작")
        model = _metadata_value(chunk, "모델") or _metadata_value(chunk, "AI")
        return start_time or "00:00", model or ai_meta.strip()

    manual_label = match.group("manual_label") or "수동 Capture 세션"
    start_time = _metadata_value(chunk, "시작")
    model = _metadata_value(chunk, "AI") or _metadata_value(chunk, "모델")
    return start_time or "00:00", model or manual_label


def _session_chunks(text: str) -> list[tuple[re.Match[str], str]]:
    matches = list(_SESSION_HEADER_RE.finditer(text))
    chunks: list[tuple[re.Match[str], str]] = []
    for index, match in enumerate(matches):
        next_start = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        chunk = _clean_session_chunk(text[match.start() : next_start])
        if chunk:
            chunks.append((match, chunk))
    return chunks


def parse_file(path: Path) -> list[CaptureSession]:
    """하나의 Capture 일간 파일을 세션 리스트로 파싱."""
    text = path.read_text(encoding="utf-8")
    date = path.stem  # "2026-03-29"

    sessions: list[CaptureSession] = []

    for match, chunk in _session_chunks(text):
        time_str, model = _session_time_and_model(match, chunk)

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
        user_turns += len(re.findall(r"^###\s+내 생각\b", chunk, re.MULTILINE))
        ai_turns = len(re.findall(r"^\*\*AI\*\*:", chunk, re.MULTILINE))

        sessions.append(
            CaptureSession(
                date=date,
                time=time_str,
                model=model,
                raw_text=chunk.strip(),
                capture_session_id=_capture_session_id(chunk),
                tags=tags,
                user_turns=user_turns,
                ai_turns=ai_turns,
                file_path=path,
            )
        )

    time_groups: dict[str, list[CaptureSession]] = {}
    for session in sessions:
        time_groups.setdefault(session.time, []).append(session)

    for group in time_groups.values():
        if len(group) <= 1:
            continue

        suffix_counts = Counter(_stable_duplicate_suffix(session) for session in group)
        suffix_seen: Counter[str] = Counter()

        for session in group:
            suffix = _stable_duplicate_suffix(session)
            session.duplicate_count = len(group)
            if suffix_counts[suffix] > 1:
                suffix_seen[suffix] += 1
                session.duplicate_suffix = f"{suffix}-{suffix_seen[suffix]}"
            else:
                session.duplicate_suffix = suffix

    return sessions


def parse_directory(
    capture_dir: Path, since: str | None = None
) -> list[CaptureSession]:
    """Capture 디렉토리 전체를 파싱. since가 주어지면 해당 날짜 이후만."""
    files = sorted(capture_dir.glob("*.md"))
    if since:
        files = [f for f in files if f.stem >= since]

    all_sessions: list[CaptureSession] = []
    for f in files:
        all_sessions.extend(parse_file(f))

    return all_sessions
