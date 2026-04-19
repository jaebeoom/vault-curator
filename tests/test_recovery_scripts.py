import importlib.util
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _load_script(name: str):
    path = ROOT / "scripts" / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_cleanup_history_matches_suffixed_session_ids() -> None:
    cleanup_history = _load_script("cleanup_history")
    session_id = "2026-04-10_01:37__abcdef12-1"

    assert cleanup_history.SESSION_ID_RE.findall(
        f"<!-- vault-curator:session_id={session_id} -->"
    ) == [session_id]
    assert cleanup_history.REPORT_ENTRY_RE.findall(
        f"### 1. 제목 ({session_id})"
    ) == [("제목", session_id)]


def test_cleanup_history_reads_v2_state_dates(tmp_path) -> None:
    cleanup_history = _load_script("cleanup_history")
    reports_dir = tmp_path / "reports"
    reports_dir.mkdir()
    state_path = tmp_path / ".curator-state.json"
    state_path.write_text(
        """
{
  "version": 2,
  "sessions": {
    "2026-04-10_01:37__abcdef12": "hash-one",
    "2026-04-11_03:02": "hash-two"
  }
}
""".strip(),
        encoding="utf-8",
    )
    (reports_dir / "2026-04-10_120000.md").write_text(
        "# Haiku Review\n\n### 1. 제목 (2026-04-10_01:37__abcdef12)\n",
        encoding="utf-8",
    )

    assert cleanup_history.compute_state_without_report(
        reports_dir,
        state_path,
    ) == ["2026-04-11"]


def test_recover_reports_matches_suffixed_session_ids() -> None:
    recover_reports = _load_script("recover_reports")
    session_id = "2026-04-10_01:37__abcdef12"

    marker_match = recover_reports.SESSION_MARKER_RE.search(
        f"<!-- vault-curator:session_id={session_id} -->"
    )

    assert marker_match is not None
    assert marker_match.group(1) == session_id
    assert recover_reports.REPORT_ENTRY_RE.findall(
        f"### 1. 제목 ({session_id})"
    ) == [("제목", session_id)]
