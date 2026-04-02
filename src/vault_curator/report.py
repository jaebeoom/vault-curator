"""큐레이팅 리포트 생성 및 Sonnet 노트 작성."""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from vault_curator.evaluator import SessionVerdict


def generate_report(
    verdicts: list[SessionVerdict],
    reports_dir: Path,
) -> Path:
    """마크다운 리포트를 생성하고 파일 경로를 반환."""
    reports_dir.mkdir(parents=True, exist_ok=True)

    now = datetime.now()
    filename = f"{now.strftime('%Y-%m-%d_%H%M')}.md"
    report_path = reports_dir / filename

    strong = [v for v in verdicts if v.verdict == "strong_candidate"]
    borderline = [v for v in verdicts if v.verdict == "borderline"]
    skipped = [v for v in verdicts if v.verdict == "skip"]

    lines: list[str] = []
    lines.append(f"# Haiku Review: {now.strftime('%Y-%m-%d %H:%M')}\n")
    lines.append(f"> Sessions evaluated: {len(verdicts)}")
    lines.append(f"> Strong candidates: {len(strong)}")
    lines.append(f"> Borderline: {len(borderline)}")
    lines.append(f"> Skipped: {len(skipped)}\n")

    # Strong candidates
    if strong:
        lines.append("## Sonnet 승격 후보\n")
        for i, v in enumerate(strong, 1):
            lines.append(f"### {i}. {v.suggested_title} ({v.session_id})")
            lines.append(f"- **핵심:** {v.core_idea}")
            lines.append(f"- **이유:** {v.reasoning}")
            lines.append(
                f"- **테마:** {' '.join(v.connected_themes)}"
            )
            lines.append(
                f"- **소스:** [[{v.session_id.split('_')[0]}]]\n"
            )

    # Borderline
    if borderline:
        lines.append("## Borderline (승격 안 함)\n")
        for v in borderline:
            lines.append(f"- **{v.session_id}**: {v.reasoning}\n")

    # Skipped
    if skipped:
        lines.append("## Skipped\n")
        lines.append("| Session | Reason |")
        lines.append("|---------|--------|")
        for v in skipped:
            short_reason = v.reasoning[:80].replace("|", "/")
            lines.append(f"| {v.session_id} | {short_reason} |")
        lines.append("")

    report_path.write_text("\n".join(lines), encoding="utf-8")
    return report_path


def write_sonnet_notes(
    verdicts: list[SessionVerdict],
    sonnet_dir: Path,
) -> list[Path]:
    """strong_candidate의 sonnet_draft를 Vault/Sonnet/에 직접 작성."""
    sonnet_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    strong = [
        v
        for v in verdicts
        if v.verdict == "strong_candidate" and v.sonnet_draft
    ]

    for v in strong:
        draft = v.sonnet_draft
        assert draft is not None

        # 파일명은 공백을 언더스코어로 고정해 Vault 내 일관성을 맞춘다.
        safe_title = v.suggested_title.strip()
        if not safe_title:
            safe_title = v.session_id
        safe_title = re.sub(r"\s+", "_", safe_title)
        filename = f"{safe_title}.md"
        filepath = sonnet_dir / filename

        # 중복 방지
        if filepath.exists():
            filepath = sonnet_dir / f"{safe_title} ({v.session_id}).md"

        content = (
            f"# {v.suggested_title}\n\n"
            f"> 한 줄 요약: {draft.get('summary', '')}\n\n"
            f"## 생각\n\n"
            f"{draft.get('thought', '')}\n\n"
            f"## 연결되는 것들\n\n"
            f"{draft.get('connections', '')}\n\n"
            f"## 출처/계기\n\n"
            f"{draft.get('source', '')}\n\n"
            f"#sonnet #from/ai-session {' '.join(v.connected_themes)}\n"
        )

        filepath.write_text(content, encoding="utf-8")
        written.append(filepath)

    return written
