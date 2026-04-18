import json
import hashlib

from vault_curator import parser, state


def _session_file_text() -> str:
    return "\n".join(
        [
            "## AI 세션 (09:00, test-model)",
            "**나**: 첫 판단",
            "**AI**: 첫 응답",
            "---",
            "## AI 세션 (09:30, test-model)",
            "**나**: 둘째 판단",
            "**AI**: 둘째 응답",
            "#stage/capture #daily",
        ]
    )


def test_load_state_migrates_legacy_file_hash_state(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    capture_dir = tmp_path / "Capture"
    capture_dir.mkdir()
    capture_file = capture_dir / "2026-04-07.md"
    capture_file.write_text(_session_file_text(), encoding="utf-8")

    file_hash = hashlib.sha256(capture_file.read_bytes()).hexdigest()
    (project_dir / ".curator-state.json").write_text(
        json.dumps({capture_file.name: file_hash}, ensure_ascii=False),
        encoding="utf-8",
    )

    migrated = state.load_state(project_dir, capture_dir=capture_dir)

    sessions = parser.parse_file(capture_file)
    assert migrated == {
        session.session_id: state.session_hash(session)
        for session in sessions
    }

    stored = json.loads(
        (project_dir / ".curator-state.json").read_text(encoding="utf-8")
    )
    assert stored["version"] == 2
    assert stored["sessions"] == migrated


def test_filter_new_sessions_only_returns_new_or_changed_sessions(
    tmp_path,
) -> None:
    capture_file = tmp_path / "2026-04-07.md"
    capture_file.write_text(_session_file_text(), encoding="utf-8")
    sessions = parser.parse_file(capture_file)
    session_state = state.build_state_entries([sessions[0]])

    pending = state.filter_new_sessions(sessions, session_state)

    assert [session.session_id for session in pending] == ["2026-04-07_09:30"]

    changed = parser.CaptureSession(
        date=sessions[0].date,
        time=sessions[0].time,
        model=sessions[0].model,
        raw_text=sessions[0].raw_text + "\n추가 문장",
        tags=sessions[0].tags,
        user_turns=sessions[0].user_turns,
        ai_turns=sessions[0].ai_turns,
    )
    pending_changed = state.filter_new_sessions(
        [changed],
        state.build_state_entries([sessions[0]]),
    )
    assert [session.session_id for session in pending_changed] == [
        "2026-04-07_09:00"
    ]


def test_load_state_migrates_legacy_duplicate_session_ids(tmp_path) -> None:
    project_dir = tmp_path / "project"
    project_dir.mkdir()
    capture_dir = tmp_path / "Capture"
    capture_dir.mkdir()
    capture_file = capture_dir / "2026-04-10.md"
    capture_file.write_text(
        "\n".join(
            [
                "## AI 세션 (01:37, test-model)",
                "**나**: 첫 판단",
                "**AI**: 첫 응답",
                "---",
                "## AI 세션 (01:37, test-model)",
                "**나**: 둘째 판단",
                "**AI**: 둘째 응답",
            ]
        ),
        encoding="utf-8",
    )

    sessions = parser.parse_file(capture_file)
    legacy_state = {
        "version": 2,
        "sessions": {
            "2026-04-10_01:37__1": "legacy-one",
            "2026-04-10_01:37__2": "legacy-two",
        },
    }
    (project_dir / ".curator-state.json").write_text(
        json.dumps(legacy_state, ensure_ascii=False),
        encoding="utf-8",
    )

    migrated = state.load_state(project_dir, capture_dir=capture_dir)

    assert sorted(migrated) == sorted(session.session_id for session in sessions)
    assert all(key.startswith("2026-04-10_01:37__") for key in migrated)
    assert "2026-04-10_01:37__1" not in migrated
    assert "2026-04-10_01:37__2" not in migrated
