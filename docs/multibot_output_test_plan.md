# Multi-Bot Output Test Plan

## 목표
- 멀티 봇(3~4개) 협업 시나리오를 테스트 케이스로 고정한다.
- 각 케이스 실행 후 결과물을 `result/` 폴더에 자동 저장한다.

## 결과 저장 경로
- 루트: `result/multibot_test_results`
- 케이스별: `result/multibot_test_results/TCxx_*`

## 테스트 케이스

### TC01 Render Success (3 bots)
- 목적: 렌더링 요청에서 실행 링크를 포함한 완료 판정 확인
- 기대 결과:
  - `status=completed`
  - `final_report.completion_status=passed`
  - `execution_link` 존재

### TC02 Render Failure Missing Link (3 bots)
- 목적: 렌더링 요청인데 링크가 없을 때 실패 판정 확인
- 기대 결과:
  - `status=failed`
  - `quality_gate_failures`에 링크 누락 관련 메시지 포함

### TC03 Gemini Human Input Fallback (3 bots)
- 목적: Gemini 휴먼 입력 요구 시 Codex 자동 전환 후 작업 지속 확인
- 기대 결과:
  - `status=completed`
  - `/mode codex`, `/model gpt-5` 명령이 실행됨

### TC04 Parallel Execution With 4 Bots
- 목적: 4봇 구성을 통한 분업 및 다중 태스크 결과 생성 확인
- 기대 결과:
  - `status=completed`
  - 태스크 3개 이상 생성 및 실행 결과 저장

## 저장 결과물 형식
- `snapshot.json`: 코워크 최종 스냅샷
- `case_meta.json`: 케이스 설명/기대값/실행결과 요약
- `summary.md`: 사람이 읽기 쉬운 결과 요약
- `cowork_artifacts/*`: 오케스트레이터가 생성한 원본 결과 파일 복사본

## 실행
```bash
python3.11 -m pytest -q tests/test_multibot_output_generation.py
```
