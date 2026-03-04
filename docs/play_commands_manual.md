# Play Commands Manual (Mock Dashboard UI)

## 1. 개요

`/_mock/ui` 대시보드에서 멀티봇을 대상으로 실행하는 Play 명령 모음입니다.
이 명령들은 Telegram 백엔드 slash command 라우터가 아니라 **웹 UI 클라이언트 오케스트레이션**으로 동작합니다.

- 입력 위치:
  - Timeline 입력창(`message-input`)
  - 좌측 병렬 입력창(`parallel-message-input`)
- 결과 표시:
  - `Parallel Results`
  - `Talk / Play Viewer`

## 2. 공통 옵션

- `--rounds <n>`
  - 라운드 수 (`1~8`)
- `--max-turn-sec <n>`
  - 봇별 턴 대기 시간 (`10~240`)
- `--keep-session`
  - 기본 동작(`/new` 수행) 대신 현재 세션 유지

## 3. 명령 목록

| Command | 기본 rounds | 최소 bots | 설명 |
|---|---:|---:|---|
| `/relay <주제>` | 3 | 2 | 릴레이 대사 이어쓰기 |
| `/pitchbattle <주제>` | 2 | 2 | 아이디어 피치 배틀 + 최종 판정 |
| `/quizbattle <주제>` | 2 | 2 | 퀴즈 배틀 + 최종 판정 |
| `/debate-lite <주제>` | 2 | 2 | 경량 토론 + 최종 판정 |
| `/improv <상황>` | 3 | 2 | 즉흥극 릴레이 |
| `/quest <미션>` | 3 | 2 | 협동 퀘스트 + 성공/실패 판정 |
| `/memechain <주제>` | 3 | 2 | 한 줄 밈 체인 |
| `/court <사건>` | 2 | 3 | 법정극 + 판결 |

## 4. 실행 예시

```text
/relay 퇴근길 지하철에서 생긴 일 --rounds 2
/pitchbattle 주말 사이드 프로젝트 아이디어 --rounds 2 --max-turn-sec 60
/quizbattle 한국사 상식 --rounds 1 --keep-session
/debate-lite 원격근무 vs 오피스근무 --rounds 2
/improv 우주 엘리베이터에서 길을 잃은 팀 --rounds 2
/quest 30분 안에 랜딩 페이지 초안 완성 --rounds 2 --max-turn-sec 45
/memechain 재택근무 현실 --rounds 2
/court 버그 배포 사고 책임 공방 --rounds 2
```

## 5. 추천 운영값

- 빠른 확인/데모:
  - `--rounds 1`
  - `--max-turn-sec 20~45`
- 안정 실행:
  - `--rounds 2~3`
  - `--max-turn-sec 60~120`
- 지연 감소 팁:
  - 참가 봇 수를 줄이고 rounds를 낮춘다.
  - 응답이 느린 provider는 모델을 경량 모델로 바꾼다.

## 6. 실패 복구 절차

1. `Parallel Results`에서 실패 행(FAIL) 상세를 확인
2. 필요 시 `/stop` 실행
3. 세션 꼬임 의심 시 `/new` 실행 후 재시도 (또는 Play 명령에서 `--keep-session` 제거)
4. 옵션 오탈자 여부 확인 (`--rounds`, `--max-turn-sec`, `--keep-session`만 허용)
5. `/court`는 최소 3개 봇 선택인지 확인

## 7. 판정 형식 참고

판정이 필요한 명령은 최종 턴에서 아래 형식 중 하나를 기대합니다.

- `WINNER: <speaker>`
- `VERDICT: <value>`
- `RESULT: SUCCESS|FAIL` (특히 `/quest`)

형식이 없으면 Viewer에 `[판정 실패]`가 표시되며, 실행은 완료 처리될 수 있습니다.
