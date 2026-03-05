# Baseline Decision Log

- Project: verify-fix-03
- Task: T1 기준 동결 및 인수 규칙 확정
- Updated: 2026-03-05
- Owner: Bot B (Implementer)

## 1) 입력 상충 정리
- required_sections 입력이 `hero/features/cta/faq` 와 `hero/product/trust/cta` 및 원본 요구 `hero/products/reviews/faq`로 분산됨.
- core_cta 입력이 `지금 시작`, `지금 시작하기`, 원본 핵심 CTA `오늘 주문`으로 분산됨.

## 2) 최종 동결 기준 (Single Source of Truth)
- 필수 섹션(전부 포함):
  - `hero`
  - `products` (`product`와 동의어로 취급)
  - `features`
  - `reviews` (`trust`와 동의어로 취급)
  - `faq`
  - `cta`
- CTA 정책:
  - Primary CTA: `오늘 주문`
  - Secondary CTA: `지금 시작하기`

## 3) 금지/허용 카피 규칙
- 금지:
  - 허위 사실(예: 존재하지 않는 인증/수상/제휴 표기)
  - 검증 불가 과장(예: "전국 1위 보장", "100% 만족 보장" 등)
  - 오해 유발 절대 표현(예: "무조건 최저가")
- 허용:
  - 검증 가능한 운영 정보(예: 배송 가능 시간, 실제 운영 정책)
  - 주관적 감성 표현(예: "은은한 향의 프리미엄 꽃다발")

## 4) 인수(acceptance) 기준
- 구현물과 QA는 본 문서의 섹션/CTA/카피 규칙을 우선 참조한다.
- 섹션 누락 0건, Primary CTA 문구 불일치 0건, 허위·과장 문구 0건이어야 한다.

## 5) 승인 로그 (Bot A)
| round | date | actor | status | note |
|---|---|---|---|---|
| R2-T1 | 2026-03-05 | Bot B | submitted | 기준 동결안 작성 및 Bot A 승인 요청 등록 |
| R2-T1 | 2026-03-05 | Bot A | pending | 승인 회신 대기 |
