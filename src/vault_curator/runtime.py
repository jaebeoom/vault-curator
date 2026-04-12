"""공통 런타임 경로와 설정 로더."""

from __future__ import annotations

import json
from pathlib import Path

import typer
from rich.console import Console


PROJECT_DIR = Path(__file__).resolve().parents[2]
PROMPT_FILE = PROJECT_DIR / ".curator-prompt.md"
RESULT_FILE = PROJECT_DIR / ".curator-result.json"
META_FILE = PROJECT_DIR / ".curator-meta.json"


def load_config(
    console: Console,
    *,
    project_dir: Path = PROJECT_DIR,
) -> dict:
    import tomllib

    config_path = project_dir / "config.toml"
    if not config_path.exists():
        console.print("[red]config.toml을 찾을 수 없습니다.[/red]")
        raise typer.Exit(1)
    return tomllib.loads(config_path.read_text(encoding="utf-8"))


def resolve_paths(
    cfg: dict,
    *,
    project_dir: Path = PROJECT_DIR,
) -> tuple[Path, Path, Path, Path, Path]:
    paths = cfg["paths"]
    vault = Path(paths["vault_root"]).expanduser()
    haiku = vault / paths["haiku_dir"]
    sonnet = vault / paths["sonnet_dir"]
    polaris = vault / paths["polaris_dir"]
    reports = project_dir / paths["reports_dir"]
    return haiku, sonnet, polaris, reports, vault


def load_expected_session_entries(
    *,
    meta_path: Path = META_FILE,
) -> dict[str, str]:
    if not meta_path.exists():
        return {}

    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    sessions = meta.get("sessions", {})
    if not isinstance(sessions, dict):
        return {}
    return {str(key): str(value) for key, value in sessions.items()}
