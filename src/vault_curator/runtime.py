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
    capture = _resolve_stage_dir(
        vault,
        paths,
        primary_key="capture_dir",
        legacy_key="haiku_dir",
        default_name="Capture",
        legacy_default_name="Haiku",
    )
    synthesis = _resolve_stage_dir(
        vault,
        paths,
        primary_key="synthesis_dir",
        legacy_key="sonnet_dir",
        default_name="Synthesis",
        legacy_default_name="Sonnet",
    )
    polaris = vault / paths["polaris_dir"]
    reports = project_dir / paths["reports_dir"]
    return capture, synthesis, polaris, reports, vault


def _resolve_stage_dir(
    vault: Path,
    paths: dict,
    *,
    primary_key: str,
    legacy_key: str,
    default_name: str,
    legacy_default_name: str,
) -> Path:
    configured = paths.get(primary_key)
    if configured is None:
        configured = paths.get(legacy_key, default_name)

    candidate = vault / str(configured)
    migrated_default = vault / default_name
    if (
        configured == legacy_default_name
        and not candidate.exists()
        and migrated_default.exists()
    ):
        return migrated_default
    return candidate


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
