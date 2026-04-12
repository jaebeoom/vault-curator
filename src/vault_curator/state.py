"""리뷰 상태 추적 — 이미 평가한 세션을 해시로 기록."""

from __future__ import annotations

from collections import Counter
import hashlib
import json
from pathlib import Path

from vault_curator import parser


_STATE_FILE = ".curator-state.json"
_STATE_VERSION = 2


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def session_hash(session: parser.HaikuSession) -> str:
    payload = f"{session.session_id}\n{session.raw_text}".encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def build_state_entries(
    sessions: list[parser.HaikuSession],
) -> dict[str, str]:
    return {session.session_id: session_hash(session) for session in sessions}


def _state_path(project_dir: Path) -> Path:
    return project_dir / _STATE_FILE


def _is_v2_state(data: object) -> bool:
    return (
        isinstance(data, dict)
        and data.get("version") == _STATE_VERSION
        and isinstance(data.get("sessions"), dict)
    )


def _looks_like_legacy_file_state(data: object) -> bool:
    if not isinstance(data, dict) or not data:
        return False
    return all(
        isinstance(key, str)
        and key.endswith(".md")
        and isinstance(value, str)
        for key, value in data.items()
    )


def _migrate_legacy_file_state(
    legacy_state: dict[str, str],
    haiku_dir: Path,
) -> dict[str, str]:
    migrated: dict[str, str] = {}

    for filename, recorded_hash in legacy_state.items():
        path = haiku_dir / filename
        if not path.exists():
            continue
        if _file_hash(path) != recorded_hash:
            # 파일이 이후에 변경됐다면 보수적으로 다시 평가하게 둔다.
            continue
        for session in parser.parse_file(path):
            migrated[session.session_id] = session_hash(session)

    return migrated


def _migrate_duplicate_session_ids(
    session_state: dict[str, str],
    haiku_dir: Path,
) -> dict[str, str]:
    migrated = dict(session_state)
    changed = False

    for path in sorted(haiku_dir.glob("*.md")):
        sessions = parser.parse_file(path)
        time_counts = Counter(session.time for session in sessions)
        time_seen: Counter[str] = Counter()

        for session in sessions:
            if time_counts[session.time] <= 1:
                continue

            time_seen[session.time] += 1
            legacy_id = f"{session.date}_{session.time}__{time_seen[session.time]}"
            if legacy_id == session.session_id or legacy_id not in migrated:
                continue

            migrated[session.session_id] = session_hash(session)
            del migrated[legacy_id]
            changed = True

    return migrated if changed else session_state


def load_state(
    project_dir: Path,
    haiku_dir: Path | None = None,
) -> dict[str, str]:
    """상태 파일 로드. 구버전 파일-기반 상태는 세션-기반으로 마이그레이션."""
    state_path = _state_path(project_dir)
    if not state_path.exists():
        return {}

    data = json.loads(state_path.read_text(encoding="utf-8"))
    if _is_v2_state(data):
        sessions = data["sessions"]
        loaded = {str(key): str(value) for key, value in sessions.items()}
        if haiku_dir is None:
            return loaded

        migrated = _migrate_duplicate_session_ids(loaded, haiku_dir)
        if migrated != loaded:
            save_state(project_dir, migrated)
        return migrated

    if _looks_like_legacy_file_state(data) and haiku_dir is not None:
        migrated = _migrate_legacy_file_state(data, haiku_dir)
        save_state(project_dir, migrated)
        return migrated

    return {}


def save_state(project_dir: Path, state: dict[str, str]) -> None:
    """상태 파일 저장."""
    state_path = _state_path(project_dir)
    payload = {
        "version": _STATE_VERSION,
        "sessions": dict(sorted(state.items())),
    }
    state_path.write_text(
        json.dumps(payload, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )


def filter_new_sessions(
    sessions: list[parser.HaikuSession],
    state: dict[str, str],
) -> list[parser.HaikuSession]:
    """이미 평가하고 변경 없는 세션을 제외."""
    new: list[parser.HaikuSession] = []
    for session in sessions:
        if state.get(session.session_id) != session_hash(session):
            new.append(session)
    return new


def update_state(
    state: dict[str, str],
    entries: dict[str, str],
) -> dict[str, str]:
    """평가 완료된 세션 해시를 상태에 반영."""
    state.update(entries)
    return state
