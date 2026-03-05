# Role-Based Workflow Specification v1.0

## 1. 문서 목적
- 멀티봇 협업 개발을 역할 기반으로 표준화한다.
- 역할만 고정하고 기획/설계/구현/검증 산출물은 프로젝트 특성에 맞게 동적으로 생성한다.
- 설계 품질과 구현 품질을 게이트 기반으로 통제한다.
- 반복 가능한 개발 루틴(설계 보강, 결함 수정, 재검증)을 명문화한다.

## 2. 적용 범위
- 대상 역할: `Controller`, `Planner`, `Implementer`, `QA`
- 대상 작업: 신규 기능 개발, 리팩토링, UI/랜딩 페이지 생성, 품질 개선
- 제외: 인프라 긴급 장애 대응(핫픽스 룰 별도)

## 3. 핵심 원칙
- 역할 고정 원칙: 역할 정의와 책임 범위는 고정한다.
- 산출물 동적 원칙: 프로젝트별 목표/제약/브랜드/타깃에 따라 산출물은 동적으로 생성한다.
- 증빙 우선 원칙: 완료 선언보다 증빙(테스트/링크/로그/리포트)을 우선한다.
- 게이트 원칙: 설계 게이트, 구현 게이트, QA 게이트를 통과해야 다음 단계 진행 가능하다.
- 반복 제한 원칙: 설계 보강 최대 3회, QA 수정 반복은 품질 목표 충족 시까지 수행한다.

## 4. 역할 정의와 규정

### 4.1 Controller
#### 책임
- 최초 입력을 업무 목표로 정규화한다.
- 각 역할에 지시를 분배하고 진행 상태를 관리한다.
- 단계별 게이트 통과 여부를 판정한다.
- 최종 완료 보고서를 작성한다.

#### 권한
- 설계 승인/반려
- 구현 승인/반려
- QA 통과 승인
- 재작업 지시

#### 금지사항
- 설계 미통과 상태에서 구현 지시 금지
- QA 미통과 상태에서 완료 선언 금지
- 증빙 없는 완료 판정 금지

#### 필수 산출물
- `controller_kickoff.md`
- `controller_gate_review_round_N.md`
- `controller_final_report.md`

### 4.2 Planner
#### 책임
- 최초 프롬프트를 PLAN 기준(TRD/PRD/Design/DB/Test/Release)으로 해석한다.
- 병렬 가능한 태스크로 분해한다.
- 상세 설계 문서와 QA 테스트 문서를 생성한다.
- Controller 피드백을 반영해 최대 3회 보강한다.

#### 권한
- 태스크 분할/병합 제안
- 리스크/의존성 정의
- 테스트 항목 제안

#### 금지사항
- 구현 지시 없이 코드 변경 선언 금지
- 완료 기준 없는 태스크 생성 금지
- 병렬 가능성 검토 누락 금지

#### 필수 산출물
- `planning_tasks.json`
- `design_spec.md`
- `qa_test_plan.md`

### 4.3 Implementer
#### 책임
- 승인된 설계 문서 기준으로 구현한다.
- 구현 결과와 증빙(테스트 결과, 링크, 로그)을 제출한다.
- QA 결함 문서를 반영해 수정/재보고한다.

#### 권한
- 구현 세부 기술 선택
- 모듈 구조 제안
- 테스트 코드 작성/보강

#### 금지사항
- 승인되지 않은 설계 변경 단독 확정 금지
- QA 결함 미해결 상태의 완료 선언 금지
- 증빙 누락 금지

#### 필수 산출물
- `implementation_report_round_N.md`
- 코드 변경셋
- `test_execution_log_round_N.md`

### 4.4 QA
#### 책임
- Planner 테스트 계획 기반으로 검증 수행
- 결함 문서화(재현 절차/영향/우선순위)
- 수정 반영 후 재검증

#### 권한
- 품질 통과/실패 판정
- 추가 테스트 요구
- 결함 심각도 정의

#### 금지사항
- 재현 불가 결함 등록 금지
- 테스트 증빙 없는 실패/통과 판정 금지

#### 필수 산출물
- `qa_result_round_N.md`
- `defect_report_round_N.json`
- `qa_signoff.md`

## 5. PLAN 모드 설계 기준

### 5.1 기준 프레임
- TRD: 기술 구조, 모듈 경계, 의존성, 성능/확장성
- PRD: 사용자 요구, 기능 범위, 성공 기준
- Design: 정보 구조, UI 구성, 상호작용, 접근성
- DB: 데이터 모델, 마이그레이션, 정합성
- Test: 단위/통합/E2E 전략, 실패 조건
- Release: 배포 전략, 롤백, 모니터링

### 5.2 Planner 입력 포맷
```json
{
  "project_id": "string",
  "objective": "string",
  "brand_tone": "string",
  "target_audience": "string",
  "core_cta": "string",
  "required_sections": ["string"],
  "forbidden_elements": ["string"],
  "constraints": ["string"],
  "deadline": "YYYY-MM-DD",
  "priority": "P0|P1|P2"
}
```

### 5.3 Planner 출력 포맷 (필수)
```json
{
  "planning_tasks": [
    {
      "id": "T1",
      "title": "string",
      "goal": "string",
      "done_criteria": "string",
      "risk": "string",
      "owner_role": "planner|implementer|qa|controller",
      "parallel_group": "G1|G2|G3",
      "dependencies": ["T0"],
      "artifacts": ["file1.md", "file2.json"],
      "estimated_hours": 0.0
    }
  ],
  "design_doc_path": "design_spec.md",
  "qa_plan_path": "qa_test_plan.md"
}
```

## 6. 상태 머신과 게이트

### 6.1 상태
- `intake`
- `planning`
- `planning_review`
- `implementation`
- `qa`
- `rework`
- `completed`
- `failed`

### 6.2 게이트 규칙
- G1 설계 게이트:
  - 입력 요구사항 누락 없음
  - 태스크 완료조건 존재
  - 병렬 그룹/의존성 명시
  - QA 플랜 포함
- G2 구현 게이트:
  - 승인된 설계 대비 구현 추적 가능
  - 테스트 로그 첨부
  - 미해결 결함 목록 분리
- G3 QA 게이트:
  - Critical/High 결함 0건
  - 재현 절차 검증 완료
  - 최종 링크/아티팩트 접근 가능

## 7. 상세 루틴 (관계형 워크플로우)

| 단계 | From -> To | 입력 | 출력 | 반복/제한 |
| --- | --- | --- | --- | --- |
| 1 | User -> Controller | 최초 프롬프트 | 목표/범위 정의 | 1회 |
| 2 | Controller -> Planner | PLAN 기준 + 역할 지시 | 설계 요청서 | 1회 |
| 3 | Planner -> Controller | `planning_tasks.json`, 설계/QA 문서 | 설계안 | 최대 3회 보강 |
| 4 | Controller -> Planner | 검토 피드백 | 보강 지시 | 최대 3회 |
| 5 | Controller -> Implementer | 승인 설계안 | 구현 지시서 | 1회 |
| 6 | Implementer -> Controller/QA | 구현 결과/테스트 로그 | 구현 보고 | 반복 가능 |
| 7 | QA -> Implementer | 결함 문서 | 수정 요청 | 결함 해소까지 반복 |
| 8 | Implementer -> QA | 수정 반영 결과 | 재검증 요청 | 반복 |
| 9 | QA -> Controller | 최종 QA 통과 보고 | QA 승인 | 1회 |
| 10 | Controller -> User | 전체 결과 취합 | 최종 완료 보고 | 1회 |

## 8. 설계 보강 반복 규정 (최대 3회)
- Round 1: 기준 적합성 검토
- Round 2: 누락/충돌 보강
- Round 3: 최종 보정
- Round 3에서도 미달 시:
  - `planning_failed.md` 작성
  - 원인/차단요인/재시작 조건 명시

## 9. 병렬화 규정
- Planner는 태스크마다 `parallel_group` 지정 필수
- 같은 그룹은 병렬 가능
- 의존성 있는 태스크는 선행 완료 전 시작 금지
- QA는 병렬 태스크 완료 후 통합 검증 수행

## 10. 문서 규격 (체크박스 강제)

### 10.1 design_spec.md 템플릿
```md
# Design Spec

## Scope
- [ ] 요구사항 반영
- [ ] 제외 범위 명시

## Task Breakdown
- [ ] T1 ...
- [ ] T2 ...
- [ ] T3 ...

## Risks
- [ ] R1 ...
- [ ] R2 ...

## Self-Test Plan
- [ ] ST1 ...
- [ ] ST2 ...
```

### 10.2 qa_test_plan.md 템플릿
```md
# QA Test Plan

## Functional
- [ ] F1 ...
- [ ] F2 ...

## Non-Functional
- [ ] N1 ...
- [ ] N2 ...

## Regression
- [ ] R1 ...
- [ ] R2 ...
```

## 11. QA 결함 보고 규격
```json
{
  "defect_id": "D-001",
  "severity": "critical|high|medium|low",
  "summary": "string",
  "steps_to_reproduce": ["step1", "step2"],
  "expected": "string",
  "actual": "string",
  "evidence": ["log_path", "screenshot_path"],
  "owner": "implementer",
  "status": "open|fixed|verified|closed"
}
```

## 12. 최종 완료 조건 (Controller 승인 조건)
- 설계 문서 최신본 존재
- QA 승인(`qa_signoff.md`) 존재
- 결함 상태 `open` 0건
- 실행 링크/결과물 링크 유효
- 최종 보고서에 아래 항목 포함
  - 범위 대비 완료율
  - 남은 리스크
  - 운영 인계 정보

## 13. 산출물 디렉터리 규정
```
result/<project_id>/
  planning/
    planning_tasks.json
    design_spec.md
    qa_test_plan.md
  implementation/
    implementation_report_round_1.md
    test_execution_log_round_1.md
  qa/
    defect_report_round_1.json
    qa_result_round_1.md
    qa_signoff.md
  final/
    controller_final_report.md
```

## 14. 역할별 지시 템플릿

### 14.1 Controller -> Planner
```text
[지시]
- PLAN 기준(TRD/PRD/Design/DB/Test/Release)으로 분석
- 병렬 가능한 task로 분해
- planning_tasks.json + design_spec.md + qa_test_plan.md 제출
- 누락/충돌/모호성 0건 목표
```

### 14.2 Controller -> Implementer
```text
[지시]
- 승인된 design_spec 기준으로만 구현
- 각 task done_criteria 충족 증빙 첨부
- implementation_report_round_N.md 제출
```

### 14.3 QA -> Implementer
```text
[결함 전달]
- defect_id, 재현 단계, 기대/실제, 증빙 포함
- 수정 후 재검증 요청 전 self-test 로그 첨부
```

## 15. 준수 체크리스트
- [ ] 역할 고정 원칙 준수
- [ ] 산출물 동적 생성 원칙 준수
- [ ] 설계 게이트 통과 후 구현 착수
- [ ] QA 결함 반복 루프 수행
- [ ] 최종 보고서 완료

## 16. 변경 이력
- v1.0: 역할 기반 상세 규격 최초 제정

