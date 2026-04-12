#!/usr/bin/env python3

from __future__ import annotations

import argparse
import re
import tomllib
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]

SESSION_MARKER_RE = re.compile(
    r"<!--\s+vault-curator:session_id=(20\d{2}-\d{2}-\d{2}_\d{2}:\d{2})\s+-->"
)
REPORT_ENTRY_RE = re.compile(
    r"^###\s+\d+\.\s+(.*?)\s+\((20\d{2}-\d{2}-\d{2}_\d{2}:\d{2})\)$",
    re.MULTILINE,
)
SUMMARY_RE = re.compile(r"^>\s+한 줄 요약:\s+(.*)$", re.MULTILINE)
TAG_RE = re.compile(r"(#[^\s#]+)")


@dataclass
class RecoveredNote:
    session_id: str
    title: str
    summary: str
    themes: list[str]
    source_name: str


def resolve_project_paths(
    *,
    root: Path = ROOT,
    sonnet_dir_override: str | None = None,
) -> tuple[Path, Path]:
    reports_dir = root / "reports"
    if sonnet_dir_override:
        return reports_dir, Path(sonnet_dir_override).expanduser()

    config_path = root / "config.toml"
    if not config_path.exists():
        raise SystemExit(
            "config.toml not found. Pass --sonnet-dir or create a local config.toml."
        )

    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    paths = cfg.get("paths", {})
    vault_root_value = paths.get("vault_root")
    sonnet_dir_value = paths.get("sonnet_dir")
    if not vault_root_value or not sonnet_dir_value:
        raise SystemExit(
            "config.toml must define [paths].vault_root and [paths].sonnet_dir."
        )

    vault_root = Path(vault_root_value).expanduser()
    sonnet_dir = Path(sonnet_dir_value).expanduser()
    if not sonnet_dir.is_absolute():
        sonnet_dir = vault_root / sonnet_dir
    return reports_dir, sonnet_dir


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def extract_summary(text: str) -> str:
    match = SUMMARY_RE.search(text)
    return match.group(1).strip() if match else ""


def extract_themes(text: str) -> list[str]:
    for line in reversed(text.splitlines()):
        if line.startswith("#sonnet "):
            return [tag for tag in TAG_RE.findall(line) if tag != "#sonnet"]
    return []


def covered_session_ids(reports_dir: Path) -> set[str]:
    covered: set[str] = set()
    for path in sorted(reports_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        covered.update(session_id for _, session_id in REPORT_ENTRY_RE.findall(text))
    return covered


def collect_recoverable_notes(
    date: str,
    reports_dir: Path,
    sonnet_dir: Path,
) -> list[RecoveredNote]:
    covered = covered_session_ids(reports_dir)
    recovered: list[RecoveredNote] = []

    for path in sorted(sonnet_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        marker = SESSION_MARKER_RE.search(text)
        if marker is None:
            continue

        session_id = marker.group(1)
        if not session_id.startswith(f"{date}_"):
            continue
        if session_id in covered:
            continue

        recovered.append(
            RecoveredNote(
                session_id=session_id,
                title=extract_title(text, path.stem.replace("_", " ")),
                summary=extract_summary(text),
                themes=extract_themes(text),
                source_name=path.name,
            )
        )

    return sorted(recovered, key=lambda note: note.session_id)


def unique_report_path(reports_dir: Path, date: str) -> Path:
    candidate = reports_dir / f"{date}_recovered.md"
    if not candidate.exists():
        return candidate

    suffix = 1
    while True:
        candidate = reports_dir / f"{date}_recovered-{suffix:02d}.md"
        if not candidate.exists():
            return candidate
        suffix += 1


def build_report(date: str, notes: list[RecoveredNote]) -> str:
    lines: list[str] = []
    lines.append(f"# Haiku Review (Recovered): {date}\n")
    lines.append("> Recovery basis: existing Sonnet notes")
    lines.append("> Original evaluator counts were not retained")
    lines.append("> Sessions evaluated: unknown")
    lines.append(f"> Recovered strong candidates: {len(notes)}")
    lines.append("> Borderline: unknown")
    lines.append("> Skipped: unknown\n")

    if notes:
        lines.append("## 복구된 Sonnet 승격 후보\n")
        for index, note in enumerate(notes, 1):
            theme_text = " ".join(note.themes) if note.themes else "(not retained)"
            summary = note.summary if note.summary else "(summary not retained)"
            lines.append(f"### {index}. {note.title} ({note.session_id})")
            lines.append(f"- **핵심:** {summary}")
            lines.append(
                "- **복구 근거:** 기존 Sonnet 노트가 보존되어 있어 제목/요약/테마를 재구성함. "
                "원본 evaluator reasoning은 보존되지 않아 그대로 복원할 수 없음."
            )
            lines.append(f"- **테마:** {theme_text}")
            lines.append(f"- **복구 출처:** `{note.source_name}`")
            lines.append(f"- **소스:** [[{date}]]\n")
    else:
        lines.append("## 복구 결과\n")
        lines.append(
            "- 이 날짜에 대해 보존된 Sonnet 노트가 없어 strong candidate 리포트를 복구할 수 없었습니다.\n"
        )

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Recover a report for YYYY-MM-DD")
    parser.add_argument(
        "--sonnet-dir",
        help="Override Sonnet directory instead of reading config.toml",
    )
    args = parser.parse_args()

    reports_dir, sonnet_dir = resolve_project_paths(
        sonnet_dir_override=args.sonnet_dir
    )
    reports_dir.mkdir(parents=True, exist_ok=True)
    notes = collect_recoverable_notes(args.date, reports_dir, sonnet_dir)
    report_path = unique_report_path(reports_dir, args.date)
    report_path.write_text(build_report(args.date, notes), encoding="utf-8")
    print(report_path)
    print(f"recovered strong candidates: {len(notes)}")


if __name__ == "__main__":
    main()
