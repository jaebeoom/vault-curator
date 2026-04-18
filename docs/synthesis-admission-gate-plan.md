# Synthesis Admission Gate Plan

> 2026-04-12 수정.
> 대상 프로젝트: `Projects/vault-curator`
> 이 문서는 기존 `vault health-check` 구상을 대체한다.

---

## 1. 한 줄 결론

지금은 `vault-curator`에 별도 `health-check` 서브시스템을 추가하지 않는다.

대신 기존 `Capture -> Synthesis` 파이프라인 안에 **Synthesis admission gate**를 넣는다.

- 목적은 "Vault 전체 감사"가 아니라 "형태적으로 실패한 Synthesis 적재 차단"
- 리포트, 로그, 상태파일은 계속 **프로젝트(repo) 내부**에 둔다
- `Polaris/AI`는 계속 **입력 컨텍스트**로만 사용한다
- `Capture` 원문은 수정하지 않는다

---

## 2. 왜 방향을 바꿨는가

기존 health-check 구상은 범위가 너무 넓었다.

- 현재 더 큰 문제는 `기존 Synthesis 전체의 건강도`보다 `생성 직후 Synthesis 품질 안정성`이다
- broad audit를 먼저 만들면 증상 보고서는 늘어나지만 생성 실패 원인은 그대로 남을 수 있다
- `Polaris`는 운영 산출물 저장소가 아니라 AI 컨텍스트 폴더다
- Vault는 second brain 레이어이고, 운영 로그/리포트 저장 위치로는 repo 내부가 더 자연스럽다

즉 v1의 우선순위는 `감사 체계 확대`가 아니라 `적재 전 방어막 추가`다.

---

## 3. 목표

기존 파이프라인에서 생성된 Synthesis 초안이 아래 조건을 만족하지 못하면 Vault에 쓰지 않는다.

1. 제목이 비어 있지 않다
2. 필수 필드가 비어 있지 않다
3. 최소 구조 규칙을 만족한다
4. 기존 Synthesis와 충돌 위험이 과도하지 않다
5. 실패 사유가 repo 내부 리포트에 남는다

이 기능은 "좋은 글을 보장"하지 않는다.
대신 "적재하면 안 되는 출력"을 걸러내는 것이 목적이다.

---

## 4. 비목표

이번 단계에서 하지 않을 것:

- Vault 전체 대상 `health-check` CLI
- `Polaris` 또는 `Archive` 스캔
- Vault 내부 `Polaris/Reports/...` 리포트 저장
- Synthesis 자동 수정
- AI 기반 Synthesis 의미 품질 평가
- `weak-source`, `orphan`, `contradiction` 같은 광범위 감사
- `Capture` 원문에 ID를 주입하는 작업

명시적 Capture ID가 필요하다면, 그것은 원칙적으로 Capture를 생성하는 upstream 프로젝트 책임이다.

---

## 5. 산출물 저장 원칙

### 리포트 / 로그

운영 산출물은 계속 프로젝트 내부에 둔다.

- 기본 리포트 경로: `reports/`
- 필요 시 하위 디렉토리 예시: `reports/admission-gate/`

이유:

- 현재 프로젝트도 이미 repo 내부 `reports/`를 사용 중이다
- Vault 내부 second brain과 운영 산출물을 섞지 않는다
- `Polaris/AI` 컨텍스트를 운영 리포트로 오염시키지 않는다

### 상태파일

상태파일도 프로젝트 내부에 둔다.

- 기존 `.curator-state.json` 유지
- gate 전용 상태가 꼭 필요해질 때만 별도 파일 추가

v1에서는 가능하면 새 상태파일 없이 구현한다.

---

## 6. v1 범위

### 6.1 Admission gate 대상

gate는 `strong_candidate`에 대해 draft 생성 및 optional polish가 끝난 뒤, Synthesis 파일 쓰기 직전에 실행한다.

위치 기준:

- 초안 생성: `drafting.py`
- 최종 반영: `finalization.py`
- 실제 gate 호출은 `finalization` 직전 또는 `write_synthesis_notes` 직전에 두는 것이 자연스럽다

### 6.2 Deterministic checks

v1에서는 deterministic rule만 적용한다.

필수 체크 후보:

1. `empty title`
   - `suggested_title`이 비어 있으면 차단
2. `missing required fields`
   - `summary`, `thought`, `source` 중 비어 있는 값이 있으면 차단
3. `thought sentence count`
   - `thought`가 정확히 4문장이 아니면 차단
4. `placeholder / obvious failure text`
   - `"TBD"`, `"todo"`, 빈 섹션 수준의 실패 출력은 차단
5. `session marker safety`
   - 다른 `session_id`를 가진 기존 노트를 잘못 덮어쓸 위험이 있으면 차단
6. `title / filename collision risk`
   - 기존 Synthesis 파일과 제목 또는 filename stem이 충돌하면 차단 또는 경고

### 6.3 차단 시 동작

gate 실패 시:

- 해당 Synthesis 노트는 Vault에 쓰지 않는다
- 실패 사유를 repo 내부 리포트에 남긴다
- 세션 자체를 조용히 성공 처리하지 않는다

즉 gate는 "경고만 출력"하는 장식이 아니라 **write blocker** 역할을 한다.

---

## 7. CLI 방향

새로운 `health-check` 명령은 만들지 않는다.

v1에서는 기존 명령 흐름을 유지한다.

```bash
PYTHONPATH=src uv run python -m vault_curator.cli local-run
PYTHONPATH=src uv run python -m vault_curator.cli watch-local
```

초기 선택지:

- gate를 기본 `on`으로 둔다
- 필요하면 디버그용 escape hatch만 추가한다

예시 옵션 초안:

```bash
PYTHONPATH=src uv run python -m vault_curator.cli local-run \
  --no-admission-gate
```

단, v1에서는 옵션 추가 없이 기본 적용으로 시작해도 된다.

---

## 8. Polaris에 대한 정리

`Polaris/AI`는 감사 대상이 아니라 컨텍스트 입력이다.

현재 의미:

- `about-me.md`
- `top-of-mind.md`
- `tag-taxonomy.md`
- `writing-voice.md`

이 폴더는 Synthesis 생성 프롬프트의 입력으로만 쓰고, 운영 리포트/로그를 쌓는 장소로 쓰지 않는다.

---

## 9. Capture ID에 대한 정리

현재 `Capture` 문서에는 명시적 고정 ID가 없다.
`vault-curator`는 날짜/시각과 내용 해시 기반의 파생 `session_id`를 내부적으로 사용한다.

이번 계획의 원칙:

- `vault-curator`가 `Capture` 원문을 수정해서 ID를 주입하지 않는다
- upstream에서 explicit ID가 도입되면, 이후 `vault-curator`가 그것을 읽도록 확장할 수 있다
- admission gate 작업은 explicit ID 도입 전에도 진행 가능하다

즉 ID 문제는 기록하되, 이번 구현의 선행 조건으로 두지 않는다.

---

## 10. 제안 파일 구조

가능하면 작은 모듈 하나로 시작한다.

추가 파일:

```text
src/vault_curator/synthesis_gate.py
tests/test_synthesis_gate.py
```

수정 파일:

```text
src/vault_curator/finalization.py
src/vault_curator/report.py
src/vault_curator/cli.py
README.md
```

필요 시 나중에만 추가:

```text
src/vault_curator/audit_synthesis.py
tests/test_audit_synthesis.py
```

초기에는 큰 서브시스템으로 분해하지 않는다.

---

## 11. 역할 분리

- `synthesis_gate.py`
  - gate rule 정의
  - draft 검사
  - 차단 사유 구조화
- `finalization.py`
  - gate 실행 orchestration
  - 통과한 verdict만 Synthesis write 단계로 전달
- `report.py`
  - blocked draft 섹션 추가
  - 기존 리포트 포맷 확장
- `cli.py`
  - 필요하면 gate toggle 옵션 추가

---

## 12. 구현 순서

### Phase 1. Gate rule 정의

1. gate failure dataclass 또는 단순 dict 구조 정의
2. `title`, `summary`, `thought`, `source` 검사 구현
3. `thought == 4 sentences` 검사 구현

완료 기준:

- isolated unit test에서 기본 실패 사례를 분류할 수 있다

### Phase 2. Synthesis 충돌 검사

1. 기존 Synthesis 디렉토리 스캔
2. `session_id` marker 충돌 검사
3. 제목/filename 충돌 위험 검사

완료 기준:

- 잘못된 덮어쓰기와 명백한 충돌이 write 전에 걸린다

### Phase 3. Pipeline 연결

1. `finalization`에 gate 적용
2. blocked verdict는 Synthesis write 대상에서 제외
3. console summary에 통과/차단 수 표시

완료 기준:

- 한 번의 `local-run`에서 통과분만 Synthesis에 적힌다

### Phase 4. Report 확장

1. 기존 리포트에 `Blocked by Admission Gate` 섹션 추가
2. 각 세션의 차단 사유를 짧게 출력
3. 필요하면 별도 gate 리포트 파일 분리

완료 기준:

- Synthesis에 안 적힌 이유를 repo 내부에서 추적할 수 있다

---

## 13. 테스트 계획

필수 테스트:

1. empty title 차단
2. missing required fields 차단
3. `thought` 문장 수 검사
4. placeholder text 차단
5. 기존 session marker 충돌 차단
6. title / filename collision 검사
7. gate 실패 시 Synthesis 파일이 쓰이지 않는지
8. gate 실패 사유가 리포트에 나타나는지

fixture 원칙:

- 실제 Synthesis 축소판 같은 작은 디렉토리 구조
- 기존 노트 2~4개
- 새 draft 3~5개
- 통과 사례와 차단 사례를 모두 포함

---

## 14. Done 정의

아래가 되면 v1 완료로 본다.

1. 기존 `local-run` / `watch-local` 흐름에서 admission gate가 동작한다
2. gate 실패 draft는 Synthesis에 쓰이지 않는다
3. 실패 사유가 repo 내부 리포트에 남는다
4. `Polaris/AI`는 계속 컨텍스트 입력으로만 쓰인다
5. 운영 리포트는 Vault가 아니라 repo 내부에 남는다
6. 관련 테스트가 통과한다
7. README에 동작 방식이 문서화된다

---

## 15. 후순위 후보

다음은 필요할 때만 검토한다.

1. upstream Capture generator의 explicit session ID 도입
2. 수동 실행형 `audit-synthesis` 명령
3. Synthesis 구조 lint의 범위 확대
4. 장기적으로 필요한 경우에만 Vault-level audit 재논의

여기서도 원칙은 같다.

- 먼저 생성 경로를 안정화한다
- 그 다음에야 사후 감사 범위를 넓힌다

---

## 16. 다음 세션 시작 체크리스트

다음 세션에서는 아래 순서로 바로 시작하면 된다.

1. `src/vault_curator/synthesis_gate.py`
   - gate rule과 failure 모델 구현
2. `tests/test_synthesis_gate.py`
   - fixture와 차단 케이스 먼저 작성
3. `src/vault_curator/finalization.py`
   - gate 적용 및 write blocker 연결
4. `src/vault_curator/report.py`
   - blocked draft 리포트 섹션 추가
5. `README.md`
   - admission gate 동작 설명 추가

이 순서를 지키면 큰 설계 변경 없이 바로 구현에 들어갈 수 있다.
