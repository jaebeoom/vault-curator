"""리뷰 상태 추적 — 이미 평가한 파일을 해시로 기록."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


_STATE_FILE = ".curator-state.json"


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_state(project_dir: Path) -> dict[str, str]:
    """상태 파일 로드. 없으면 빈 dict 반환."""
    state_path = project_dir / _STATE_FILE
    if state_path.exists():
        return json.loads(state_path.read_text(encoding="utf-8"))
    return {}


def save_state(project_dir: Path, state: dict[str, str]) -> None:
    """상태 파일 저장."""
    state_path = project_dir / _STATE_FILE
    state_path.write_text(
        json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def filter_new_files(
    files: list[Path], state: dict[str, str]
) -> list[Path]:
    """이미 평가하고 변경 없는 파일을 제외."""
    new: list[Path] = []
    for f in files:
        h = _file_hash(f)
        if state.get(f.name) != h:
            new.append(f)
    return new


def update_state(state: dict[str, str], files: list[Path]) -> dict[str, str]:
    """평가 완료된 파일들의 해시를 상태에 반영."""
    for f in files:
        state[f.name] = _file_hash(f)
    return state
