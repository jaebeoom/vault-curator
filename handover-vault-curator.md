# Handover: Vault Curator (Haiku 자동 품질 선별)

> 2026-03-29 세션에서 정리. 별도 세션에서 플랜 모드로 본격 설계 예정.

---

## 배경

- 텔레그램 봇(`telegram-llm-bot`)이 AI 세션을 `Vault/Haiku/`에 자동 저장 중
- Haiku가 계속 쌓이는데 Sonnet 승격 여부를 직접 검토할 시간이 부족
- AI가 주기적으로 Haiku를 읽고 Sonnet 승격 후보를 선별해주는 시스템 필요

## 핵심 결정 사항

### 별도 프로젝트로 분리

- 프로젝트명(가칭): `vault-curator`
- `telegram-llm-bot`의 하위 기능이 아닌 독립 프로젝트
- 이유: 봇은 **입력→저장**(수도꼭지), curator는 **저장된 것을 읽고 평가**(체). 관심사가 다름

```
Projects/
├── telegram-llm-bot/     # 입력 & 대화 & Haiku 저장 (기존)
└── vault-curator/        # Haiku 품질 선별 (신규)
```

### bot.py의 세션 저장 기능은 현행 유지

- `save_session_to_vault()` + `tagger.py`는 이미 깔끔하게 분리되어 있음
- vault-curator가 이 코드를 재사용할 일 없음 (curator는 .md를 읽는 거지 쓰는 게 아님)
- `tagger.py`가 나중에 공유될 가능성은 있으나, 그때 가서 리팩토링해도 늦지 않음

### X 아티클 변환은 별도

- X 아티클 PDF→MD 변환은 기존 `x-to-pdf` 프로젝트와 관련
- vault-curator 스코프에 포함하지 않음

## vault-curator가 해야 할 일

1. `Vault/Haiku/` 내 .md 파일들을 읽음
2. 각 세션의 품질을 평가 (Sonnet 승격 가치가 있는가)
3. 승격 후보 리포트 생성 (후보 목록 + 각각의 이유)
4. **최종 승격 판단은 사람이 함** — AI는 1차 필터 역할만

## 설계 시 고려할 것

### 선별 기준 (초안)

- 독립적인 사고가 담겨 있는가 (단순 번역/요약이 아닌가)
- 반복 등장하는 주제와 연결되는가
- 나중에 에세이(Opus)로 발전할 가능성이 있는가

### Think Tank 시리즈에서 참고할 요소

- **인테이크 필터 4단계** (출처 검증 → 근거 검증 → 반대 시나리오 → 적용성)
  - Haiku→Sonnet 승격 기준에 통합 가능
- **의사결정 추적** — `#decision` 태그를 tag-taxonomy에 추가하는 것도 검토
- **사고 렌즈** (분해, 반전, 2차 효과, 리프레이밍, 사전부검) — curator 스코프는 아니지만 관련 참고 자료
- 상세 내용: `/Users/nathan/Library/Mobile Documents/com~apple~CloudDocs/Atelier/vault-improvement-ideas.md`

### 트리거 방식 (미정)

- Claude Code에서 직접 실행
- 크론/스케줄로 주 1회 자동
- 텔레그램 봇에 `/review` 커맨드 추가 (봇은 호출만, 로직은 curator)

### 기존 Vault 구조 참고

- 파이프라인: Haiku(날것) → Sonnet(정제된 조각) → Opus(완성 에세이)
- 태그 체계: `Vault/Polaris/AI/tag-taxonomy.md`
- Vault 사용법: `Vault/Polaris/Human/how-to-use-this-vault.md`
- Sonnet 템플릿: `Vault/Templates/sonnet-template.md`

### 현재 Haiku 파일 구조

- 경로: `Vault/Haiku/YYYY-MM-DD.md`
- 하루에 여러 세션이 `---`로 구분되어 하나의 파일에 저장
- 각 세션 헤더: `## AI 세션 (HH:MM, 모델명)`
- 발화자: `**나**: ...`, `**AI**: ...`
- 소스 표시: `**나** (X 포스트 첨부): ...`, `**나** (YouTube 첨부): ...`
- 태그: 세션 끝에 `#haiku #daily #from/telegram-bot #tech/ai ...`
