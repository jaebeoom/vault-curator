#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import re
import shutil
import tomllib
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SESSION_MARKER_TEMPLATE = "<!-- vault-curator:session_id={session_id} -->"
SESSION_ID_RE = re.compile(r"20\d{2}-\d{2}-\d{2}_\d{2}:\d{2}")
REPORT_ENTRY_RE = re.compile(
    r"^###\s+\d+\.\s+(.*?)\s+\((20\d{2}-\d{2}-\d{2}_\d{2}:\d{2})\)$",
    re.MULTILINE,
)
SESSION_DATE_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
MANUAL_NOTE_SESSION_MAP = {
    "ABF_독점_체제의_균열과_글래스_인터포저의_기술적_탈출구": {"2026-04-06_18:14"},
    "기호와_물리_사이의_간극:_xAI가_직면한_멀티모달_정렬의_과제": {"2026-04-06_08:26"},
    "능동적_거부와_수동적_회피:_견유학파와_탕핑족의_실존적_궤적의_차이": {
        "2026-04-06_21:36"
    },
    "도구적_합리성과_미학적_질감_사이의_간극": {"2026-04-06_17:26"},
}


@dataclass
class NoteRecord:
    path: Path
    title: str
    text: str
    session_ids: set[str]
    mtime: float


def resolve_project_paths(
    *,
    root: Path = ROOT,
    synthesis_dir_override: str | None = None,
) -> tuple[Path, Path, Path]:
    reports_dir = root / "reports"
    state_path = root / ".curator-state.json"
    if synthesis_dir_override:
        return reports_dir, state_path, Path(synthesis_dir_override).expanduser()

    config_path = root / "config.toml"
    if not config_path.exists():
        raise SystemExit(
            "config.toml not found. Pass --synthesis-dir or create a local config.toml."
        )

    cfg = tomllib.loads(config_path.read_text(encoding="utf-8"))
    paths = cfg.get("paths", {})
    vault_root_value = paths.get("vault_root")
    synthesis_dir_value = paths.get("synthesis_dir", paths.get("sonnet_dir"))
    if not vault_root_value or not synthesis_dir_value:
        raise SystemExit(
            "config.toml must define [paths].vault_root and [paths].synthesis_dir."
        )

    vault_root = Path(vault_root_value).expanduser()
    configured_synthesis_dir = Path(synthesis_dir_value).expanduser()
    synthesis_dir = (
        configured_synthesis_dir
        if configured_synthesis_dir.is_absolute()
        else vault_root / configured_synthesis_dir
    )
    migrated_default = vault_root / "Synthesis"
    if (
        synthesis_dir_value == "Sonnet"
        and not synthesis_dir.exists()
        and migrated_default.exists()
    ):
        synthesis_dir = migrated_default
    return reports_dir, state_path, synthesis_dir


def normalize_title(title: str) -> str:
    return re.sub(r"\s+", "_", title.strip())


def safe_session_filename(session_id: str, title: str) -> str:
    safe_session = session_id.replace(":", "-")
    safe_title = normalize_title(title)
    return f"{safe_session}__{safe_title}.md" if safe_title else f"{safe_session}.md"


def session_marker(session_id: str) -> str:
    return SESSION_MARKER_TEMPLATE.format(session_id=session_id)


def extract_title(text: str, fallback: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return fallback


def load_report_title_map(reports_dir: Path) -> dict[str, set[str]]:
    title_map: dict[str, set[str]] = defaultdict(set)
    for report_path in sorted(reports_dir.glob("*.md")):
        text = report_path.read_text(encoding="utf-8")
        for title, session_id in REPORT_ENTRY_RE.findall(text):
            title_map[normalize_title(title)].add(session_id)
    return title_map


def scan_notes(
    synthesis_dir: Path,
    title_map: dict[str, set[str]],
) -> list[NoteRecord]:
    records: list[NoteRecord] = []
    for path in sorted(synthesis_dir.glob("*.md")):
        text = path.read_text(encoding="utf-8")
        title = extract_title(text, path.stem.replace("_", " "))
        session_ids = set(SESSION_ID_RE.findall(text))
        session_ids.update(title_map.get(normalize_title(title), set()))
        session_ids.update(MANUAL_NOTE_SESSION_MAP.get(normalize_title(title), set()))
        records.append(
            NoteRecord(
                path=path,
                title=title,
                text=text,
                session_ids=session_ids,
                mtime=path.stat().st_mtime,
            )
        )
    return records


def update_note_text(text: str, session_id: str) -> str:
    marker = session_marker(session_id)
    if marker in text:
        return text
    lines = text.splitlines()
    return "\n".join([marker, *lines]) + ("\n" if text.endswith("\n") else "")


def unique_archive_path(archive_dir: Path, name: str) -> Path:
    candidate = archive_dir / name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = archive_dir / f"{stem}-{index:02d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def unique_target_path(target_dir: Path, name: str) -> Path:
    candidate = target_dir / name
    if not candidate.exists():
        return candidate

    stem = candidate.stem
    suffix = candidate.suffix
    index = 1
    while True:
        candidate = target_dir / f"{stem}-{index:02d}{suffix}"
        if not candidate.exists():
            return candidate
        index += 1


def choose_keep(records: list[NoteRecord]) -> NoteRecord:
    return max(records, key=lambda record: (record.mtime, record.path.name))


def write_history_audit(
    reports_dir: Path,
    duplicate_groups: dict[str, list[NoteRecord]],
    unmatched: list[NoteRecord],
    archived: list[tuple[Path, Path]],
    renamed: list[tuple[Path, Path]],
    state_without_report: list[str],
) -> Path:
    now = datetime.now().strftime("%Y-%m-%d_%H%M%S")
    audit_path = reports_dir / f"{now}_history_cleanup.md"
    lines: list[str] = []
    lines.append(f"# History Cleanup: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
    lines.append(f"- Duplicate session groups: {len(duplicate_groups)}")
    lines.append(f"- Archived duplicate notes: {len(archived)}")
    lines.append(f"- Renamed/normalized notes: {len(renamed)}")
    lines.append(f"- Unmatched notes left untouched: {len(unmatched)}\n")

    if duplicate_groups:
        lines.append("## Duplicate Session Groups\n")
        for session_id, records in sorted(duplicate_groups.items()):
            lines.append(f"- `{session_id}`")
            for record in sorted(records, key=lambda r: r.path.name):
                lines.append(f"  - {record.path.name}")
        lines.append("")

    if archived:
        lines.append("## Archived Notes\n")
        for src, dst in archived:
            lines.append(f"- `{src.name}` -> `{dst}`")
        lines.append("")

    if renamed:
        lines.append("## Renamed Notes\n")
        for src, dst in renamed:
            lines.append(f"- `{src.name}` -> `{dst.name}`")
        lines.append("")

    if unmatched:
        lines.append("## Unmatched Notes\n")
        for record in unmatched:
            lines.append(f"- `{record.path.name}`")
        lines.append("")

    if state_without_report:
        lines.append("## State Dates Without Retained Reports\n")
        for date in state_without_report:
            lines.append(f"- `{date}`")
        lines.append("")

    audit_path.write_text("\n".join(lines), encoding="utf-8")
    return audit_path


def compute_state_without_report(reports_dir: Path, state_path: Path) -> list[str]:
    state = json.loads(state_path.read_text(encoding="utf-8"))
    if isinstance(state, dict) and isinstance(state.get("sessions"), dict):
        state_session_ids = [str(session_id) for session_id in state["sessions"]]
    elif isinstance(state, dict):
        state_session_ids = [str(filename).removesuffix(".md") for filename in state]
    else:
        state_session_ids = []

    state_dates = {
        match.group(1)
        for session_id in state_session_ids
        if (match := SESSION_DATE_RE.search(session_id))
    }
    retained_report_dates = {
        match.group(1) for _, session_id in REPORT_ENTRY_RE.findall(
            "\n".join(
                path.read_text(encoding="utf-8")
                for path in sorted(reports_dir.glob("*.md"))
            )
        )
        if (match := SESSION_DATE_RE.search(session_id))
    }
    return sorted(state_dates - retained_report_dates)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true")
    parser.add_argument(
        "--synthesis-dir",
        "--sonnet-dir",
        dest="synthesis_dir",
        help="Override Synthesis directory instead of reading config.toml",
    )
    args = parser.parse_args()

    reports_dir, state_path, synthesis_dir = resolve_project_paths(
        synthesis_dir_override=args.synthesis_dir
    )
    title_map = load_report_title_map(reports_dir)
    records = scan_notes(synthesis_dir, title_map)
    matched_records = [record for record in records if len(record.session_ids) == 1]
    unmatched_records = [record for record in records if len(record.session_ids) != 1]

    by_session: dict[str, list[NoteRecord]] = defaultdict(list)
    for record in matched_records:
        session_id = next(iter(record.session_ids))
        by_session[session_id].append(record)

    duplicate_groups = {
        session_id: group
        for session_id, group in by_session.items()
        if len(group) > 1
    }

    archive_dir = synthesis_dir / "_history_archive" / "vault-curator-dedup-2026-04-12"
    archived: list[tuple[Path, Path]] = []
    renamed: list[tuple[Path, Path]] = []

    print(f"matched session groups: {len(by_session)}")
    print(f"duplicate groups: {len(duplicate_groups)}")
    print(f"unmatched notes: {len(unmatched_records)}")

    for session_id, group in sorted(by_session.items()):
        keep = choose_keep(group)
        keep_target = keep.path.parent / safe_session_filename(session_id, keep.title)
        if keep_target != keep.path:
            keep_target = unique_target_path(keep.path.parent, keep_target.name)

        print(f"[keep] {session_id}: {keep.path.name} -> {keep_target.name}")
        for record in sorted(group, key=lambda r: (r.path != keep.path, r.path.name)):
            if record.path == keep.path:
                continue
            archive_target = unique_archive_path(archive_dir, record.path.name)
            print(f"[archive] {session_id}: {record.path.name} -> {archive_target}")

        if args.apply:
            updated_text = update_note_text(keep.text, session_id)
            if keep_target != keep.path:
                keep.path.rename(keep_target)
                renamed.append((keep.path, keep_target))
            keep_target.write_text(updated_text, encoding="utf-8")

            for record in group:
                if record.path == keep.path:
                    continue
                archive_target = unique_archive_path(archive_dir, record.path.name)
                archive_target.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(record.path), str(archive_target))
                archived.append((record.path, archive_target.relative_to(synthesis_dir)))

    state_without_report = compute_state_without_report(reports_dir, state_path)
    if args.apply:
        audit_path = write_history_audit(
            reports_dir=reports_dir,
            duplicate_groups=duplicate_groups,
            unmatched=unmatched_records,
            archived=archived,
            renamed=renamed,
            state_without_report=state_without_report,
        )
        print(f"audit: {audit_path}")


if __name__ == "__main__":
    main()
