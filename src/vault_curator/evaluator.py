"""Haiku 세션 평가 — 프롬프트 준비 및 결과 파싱.

API 호출은 하지 않음. Claude Code가 평가를 직접 수행하고,
그 결과 JSON을 이 모듈이 파싱하는 구조.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from vault_curator.parser import HaikuSession


@dataclass
class SessionVerdict:
    session_id: str
    verdict: str  # "strong_candidate" | "borderline" | "skip"
    reasoning: str
    core_idea: str = ""
    suggested_title: str = ""
    connected_themes: list[str] = field(default_factory=list)
    sonnet_draft: dict[str, str] | None = None


EVALUATION_PROMPT = """\
당신은 Obsidian Vault의 Haiku → Sonnet 승격을 판단하는 1차 필터입니다.

## Vault 구조
- Haiku: 텔레그램 봇이 자동 저장하는 AI 대화 세션 (날것)
- Sonnet: 정제된 사고 조각 (하나의 노트 = 하나의 독립적 생각)
- Opus: Sonnet 조각들을 엮어 만든 완성 에세이

## 유저 컨텍스트
{polaris_context}

## 선별 기준 (세 가지 모두 충족해야 strong_candidate)

1. **독립적 판단**: Nathan(유저)이 요약 요청을 넘어서 자기만의 판단, 주장, 연결을 던졌는가.
   - "~라고 생각함", "~지 않을까", "차라리 ~가 현실적" 등
   - 단순 "요약해줘" → AI 답변으로 끝나면 탈락

2. **횡단적 연결**: 다른 영역의 프레임워크를 끌어와 새로운 통찰을 만들었는가.
   - 예: TSMC 파운드리 모델 → 바이오 파운드리 투자 테제
   - 한 영역 내 단순 Q&A는 해당 없음

3. **연쇄 심화**: 대화가 3턴 이상 발전하며 깊어졌는가.
   - 1~2턴 단발 질문은 탈락

## 즉시 탈락 패턴
- "이 내용을 간단히 요약해줘" → 후속 판단 없이 종료
- 순수 정보 학습 (개념 설명 요청, 학습 경로 질문)
- 빈 세션 / 컨텍스트 유실 / 번역 요청

## 판정 기준
- **strong_candidate**: 3가지 기준 모두 충족. Sonnet 초안을 생성할 것.
- **borderline**: 1~2가지만 충족. 리포트에 언급하되 승격하지 않음.
- **skip**: 즉시 탈락 패턴 또는 기준 미충족.

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요. JSON 외의 텍스트를 포함하지 마세요.

```json
{{
  "sessions": [
    {{
      "session_id": "YYYY-MM-DD_HH:MM",
      "verdict": "strong_candidate | borderline | skip",
      "reasoning": "판정 이유 (2~3문장, 한국어)",
      "core_idea": "핵심 아이디어 한 줄 (strong_candidate만)",
      "suggested_title": "제안 Sonnet 제목 (strong_candidate만)",
      "connected_themes": ["#tag1", "#tag2"],
      "sonnet_draft": {{
        "summary": "한 줄 요약",
        "thought": "정제된 생각 본문 (3~5문장)",
        "connections": "연결되는 노트/개념 (백링크 형식)",
        "source": "이 생각의 출처/계기"
      }}
    }}
  ]
}}
```

sonnet_draft는 strong_candidate인 경우에만 포함하세요.

## Sonnet 초안 작성 규칙
- sonnet_draft는 **대화 요약문**이 아니라, Vault/Sonnet에 들어갈 **정제된 사고 조각**이어야 합니다.
- 유저의 Writing Voice를 반드시 따르세요. 특히:
  - 자기 지칭은 가능하면 **"필자"**를 사용할 것
  - 학술적이되 딱딱하지 않은 문어체
  - 통념 제시 → 한계 지적 → 대안 프레임 제시 → 사례의 흐름
  - 필요할 때만 짧은 단문으로 강조
  - 감정 과잉, 인터넷 구어체, 과장된 자기확신 금지
- `thought`는 정확히 4문장으로 작성하세요.
  - 1문장: 통념 또는 기존 playbook 제시
  - 2문장: 그 한계 또는 이번 사례의 이탈 지점 지적
  - 3문장: 대안 프레임 제시. 가능하면 "다시 말해,"로 시작
  - 4문장: 열린 질문, 경고, 혹은 향후 판단 기준으로 마무리
- `thought`에서는 **유저 자신의 주장**이 전면에 와야 하며, 단순 사실 요약을 피하세요.
- 가능하면 "다시 말해," 같은 유저 특유의 연결 방식을 자연스럽게 반영하세요.
- `connections`는 1~3개의 plain text 개념 또는 확실한 기존 노트명만 적으세요. 확실하지 않으면 임의의 위키링크를 만들지 마세요.
- `source`는 "어떤 Haiku 세션에서 어떤 문제의식이 출발점이 되었는가"를 한 문장으로 간결히 적으세요.
"""


SONNET_POLISH_PROMPT = """\
당신은 Obsidian Vault의 Sonnet 초안을 유저의 Writing Voice에 맞춰 다듬는 편집자입니다.

## 유저 컨텍스트
{polaris_context}

## 편집 목표
- 아래 초안의 **핵심 주장과 구조는 유지**하되, 문체와 논증 밀도를 개선하세요.
- 새로운 사실이나 주장, 근거를 임의로 추가하지 마세요.
- 과장, 장식, 인터넷 구어체를 피하고 유저의 Writing Voice를 따르세요.

## 편집 규칙
- `title`: 원제의 핵심을 유지하되 더 응축된 제목이면 조정 가능
- `summary`: 한 줄 요약을 더 선명하게 압축
- `thought`: 정확히 4문장
  - 1문장: 통념, 기존 playbook, 혹은 일반적 기대 제시
  - 2문장: 그 한계나 이번 사례의 이탈 지점 지적
  - 3문장: 대안 프레임 제시. 가능하면 "다시 말해,"로 시작
  - 4문장: 열린 질문, 경고, 혹은 향후 판단 기준으로 마무리
- 가능하면 "필자"를 자연스럽게 사용
- `connections`: plain text 1~3개만. 임의 위키링크 금지
- `source`: 한 문장으로 간결하게 유지

## 원본 Sonnet 초안
```json
{draft_json}
```

## 출력 형식
반드시 아래 JSON 형식으로만 응답하세요.

```json
{{
  "title": "수정된 제목",
  "summary": "한 줄 요약",
  "thought": "정제된 생각 본문 4문장",
  "connections": "연결되는 개념 1~3개",
  "source": "출처/계기 한 문장"
}}
```
"""


def build_prompt(
    sessions: list[HaikuSession], polaris_context: str
) -> str:
    """평가 프롬프트 전체를 조합해 반환. Claude Code가 이걸 읽고 평가."""
    system = EVALUATION_PROMPT.format(polaris_context=polaris_context)

    parts = [system, "\n---\n\n# 평가 대상 세션\n"]
    for i, s in enumerate(sessions, 1):
        parts.append(
            f"## 세션 {i}: {s.session_id} (모델: {s.model})\n"
            f"유저 턴: {s.user_turns}, AI 턴: {s.ai_turns}\n"
            f"태그: {' '.join(s.tags)}\n\n"
            f"{s.raw_text}\n\n"
            f"---\n"
        )
    return "\n".join(parts)


def parse_verdicts(text: str) -> list[SessionVerdict]:
    """Claude Code의 평가 결과 JSON을 파싱."""
    # ```json ... ``` 블록이 있으면 추출
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    data: dict[str, Any] = json.loads(text)
    items = data["sessions"]

    verdicts: list[SessionVerdict] = []
    for item in items:
        verdicts.append(
            SessionVerdict(
                session_id=item["session_id"],
                verdict=item["verdict"],
                reasoning=item["reasoning"],
                core_idea=item.get("core_idea", ""),
                suggested_title=item.get("suggested_title", ""),
                connected_themes=item.get("connected_themes", []),
                sonnet_draft=item.get("sonnet_draft"),
            )
        )

    return verdicts


def build_polish_prompt(
    draft: dict[str, str],
    polaris_context: str,
) -> str:
    """Sonnet 초안을 문체 중심으로 다듬는 프롬프트."""
    return SONNET_POLISH_PROMPT.format(
        polaris_context=polaris_context,
        draft_json=json.dumps(draft, ensure_ascii=False, indent=2),
    )


def parse_polished_sonnet(text: str) -> dict[str, str]:
    """Polish 단계의 JSON 응답을 파싱."""
    json_match = re.search(r"```json\s*(.*?)\s*```", text, re.DOTALL)
    if json_match:
        text = json_match.group(1)

    data: dict[str, Any] = json.loads(text)
    return {
        "suggested_title": data.get("title", "").strip(),
        "summary": data.get("summary", "").strip(),
        "thought": data.get("thought", "").strip(),
        "connections": data.get("connections", "").strip(),
        "source": data.get("source", "").strip(),
    }


def verdicts_to_json(verdicts: list[SessionVerdict]) -> str:
    """verdict dataclass 리스트를 JSON 텍스트로 직렬화."""
    sessions: list[dict[str, Any]] = []
    for v in verdicts:
        item: dict[str, Any] = {
            "session_id": v.session_id,
            "verdict": v.verdict,
            "reasoning": v.reasoning,
            "core_idea": v.core_idea,
            "suggested_title": v.suggested_title,
            "connected_themes": v.connected_themes,
        }
        if v.sonnet_draft:
            item["sonnet_draft"] = v.sonnet_draft
        sessions.append(item)

    return json.dumps(
        {"sessions": sessions},
        ensure_ascii=False,
        indent=2,
    )
