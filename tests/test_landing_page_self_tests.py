from __future__ import annotations

import asyncio
import json
import shutil
from pathlib import Path
from typing import Any, Callable

import pytest

from telegram_bot_new.mock_messenger.cowork import CoworkOrchestrator
from telegram_bot_new.mock_messenger.schemas import CoworkProfileRef, CoworkStartRequest
from telegram_bot_new.mock_messenger.store import MockMessengerStore

RESULT_ROOT = Path.cwd() / "result" / "landing_page_self_tests"
PREVIEW_PORT = 9095


async def _wait_terminal(orchestrator: CoworkOrchestrator, cowork_id: str, timeout_sec: float = 8.0) -> dict[str, Any]:
    deadline = asyncio.get_running_loop().time() + timeout_sec
    snapshot: dict[str, Any] | None = None
    while asyncio.get_running_loop().time() < deadline:
        snapshot = orchestrator.get_cowork_snapshot(cowork_id)
        assert snapshot is not None
        if str(snapshot.get("status")) in {"completed", "stopped", "failed"}:
            return snapshot
        await asyncio.sleep(0.05)
    assert snapshot is not None
    return snapshot


def _participants() -> list[dict[str, Any]]:
    return [
        {
            "profile_id": "p-a",
            "label": "Bot A",
            "bot_id": "bot-a",
            "token": "token-a",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "controller",
            "adapter": "gemini",
        },
        {
            "profile_id": "p-b",
            "label": "Bot B",
            "bot_id": "bot-b",
            "token": "token-b",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "planner",
            "adapter": "codex",
        },
        {
            "profile_id": "p-c",
            "label": "Bot C",
            "bot_id": "bot-c",
            "token": "token-c",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "integrator",
            "adapter": "claude",
        },
        {
            "profile_id": "p-d",
            "label": "Bot D",
            "bot_id": "bot-d",
            "token": "token-d",
            "chat_id": 1001,
            "user_id": 9001,
            "role": "executor",
            "adapter": "codex",
        },
    ]


def _request(task: str, participants: list[dict[str, Any]]) -> CoworkStartRequest:
    profiles = [
        CoworkProfileRef(
            profile_id=str(row["profile_id"]),
            label=str(row["label"]),
            bot_id=str(row["bot_id"]),
            token=str(row["token"]),
            chat_id=int(row["chat_id"]),
            user_id=int(row["user_id"]),
            role=str(row["role"]),
        )
        for row in participants
    ]
    return CoworkStartRequest(
        task=task,
        profiles=profiles,
        max_parallel=2,
        max_turn_sec=10,
        fresh_session=True,
        keep_partial_on_error=True,
        scenario={
            "project_id": "landing-page-self-tests",
            "objective": task,
            "brand_tone": "감성적이면서 신뢰감",
            "target_audience": "꽃 구매 관심 고객",
            "core_cta": "지금 꽃다발 주문",
            "required_sections": ["hero", "product", "trust", "cta"],
            "forbidden_elements": ["허위 할인 문구"],
            "constraints": ["모바일 우선", "1페이지 구성"],
            "deadline": "2026-03-31",
            "priority": "P1",
        },
    )


def _plan_task_line(
    *,
    task_id: str,
    title: str,
    goal: str,
    done_criteria: str,
    risk: str,
    parallel_group: str = "G1",
) -> str:
    return json.dumps(
        {
            "id": task_id,
            "title": title,
            "goal": goal,
            "done_criteria": done_criteria,
            "risk": risk,
            "owner_role": "implementer",
            "parallel_group": parallel_group,
            "dependencies": [],
            "artifacts": ["design_spec.md"],
            "estimated_hours": 1.5,
        },
        ensure_ascii=False,
    )


def _sender_factory(*, execution_link: str, variant_name: str) -> Callable[[str, int, int, str], Any]:
    async def sender(token: str, chat_id: int, user_id: int, text: str) -> dict[str, Any]:
        del user_id
        store = sender.store
        store.enqueue_user_message(token=token, chat_id=chat_id, user_id=9001, text=text)
        if text.startswith("/"):
            store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
            return {"ok": True}
        lowered = text.lower()
        if "planner" in lowered:
            body = "\n".join(
                [
                    _plan_task_line(
                        task_id="T1",
                        title="정보 구조 설계",
                        goal="섹션 구성",
                        done_criteria="Hero/상품/신뢰/CTA 정의",
                        risk="요구 누락",
                        parallel_group="G1",
                    ),
                    _plan_task_line(
                        task_id="T2",
                        title="UI 구현",
                        goal="랜딩 페이지 HTML/CSS 완성",
                        done_criteria="반응형 1페이지",
                        risk="스타일 붕괴",
                        parallel_group="G1",
                    ),
                    _plan_task_line(
                        task_id="T3",
                        title="검증",
                        goal="실행 링크와 품질 점검",
                        done_criteria="링크+체크리스트 제출",
                        risk="미검증",
                        parallel_group="G2",
                    ),
                ]
            )
        elif "integrator" in lowered:
            body = (
                f"통합요약: {variant_name} 랜딩 페이지 통합 완료\n"
                "충돌사항: 없음\n"
                "누락사항: 없음\n"
                "권장수정: 카피라이팅 A/B 실험\n"
                f"증빙링크: {execution_link}"
            )
        elif "controller" in lowered:
            body = (
                f"최종결론: {variant_name} 랜딩 페이지 실행 가능\n"
                "실행체크리스트: 디자인/반응형/CTA 점검 완료\n"
                f"실행링크: {execution_link}\n"
                "증빙요약: 브라우저 렌더링 경로 확인\n"
                "즉시실행항목(Top3): 1) QA 2) 카피 튜닝 3) 배포"
            )
        else:
            body = (
                f"결과요약: {variant_name} 페이지 구현 완료\n"
                "검증: 완료조건 충족\n"
                f"실행링크: {execution_link}\n"
                "증빙: 구조/스타일/반응형 체크\n"
                "남은이슈: 없음"
            )
        store.store_bot_message(token=token, chat_id=chat_id, text=f"[1][12:00:00][assistant_message] {body}")
        store.store_bot_message(token=token, chat_id=chat_id, text='[1][12:00:01][turn_completed] {"status":"success"}')
        return {"ok": True
                }

    return sender


def _write_landing_html(case_dir: Path, *, title: str, tagline: str, accent: str, hero_bg: str) -> Path:
    html = f"""<!doctype html>
<html lang="ko">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{title}</title>
  <style>
    :root {{
      --bg: {hero_bg};
      --accent: {accent};
      --text: #1c1c1c;
      --muted: #5e5e5e;
      --card: #ffffffcc;
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      font-family: "Pretendard", "Apple SD Gothic Neo", sans-serif;
      color: var(--text);
      background: linear-gradient(160deg, #fff8f6, #fff);
    }}
    .hero {{
      min-height: 58vh;
      padding: 56px 20px;
      background: radial-gradient(circle at 20% 20%, #fff, var(--bg));
    }}
    .wrap {{ max-width: 1080px; margin: 0 auto; }}
    h1 {{ margin: 0 0 12px; font-size: 42px; line-height: 1.1; }}
    p {{ margin: 0; color: var(--muted); font-size: 18px; }}
    .cta {{
      display: inline-block;
      margin-top: 22px;
      background: var(--accent);
      color: #fff;
      text-decoration: none;
      padding: 12px 18px;
      border-radius: 999px;
      font-weight: 700;
    }}
    .grid {{
      padding: 28px 20px 56px;
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
      gap: 14px;
    }}
    .card {{
      background: var(--card);
      border: 1px solid #f2e9e6;
      border-radius: 16px;
      padding: 18px;
      box-shadow: 0 8px 24px #0000000f;
    }}
    .card h3 {{ margin: 0 0 8px; }}
  </style>
</head>
<body>
  <section class="hero">
    <div class="wrap">
      <h1>{title}</h1>
      <p>{tagline}</p>
      <a class="cta" href="#products">지금 주문하기</a>
    </div>
  </section>
  <section id="products" class="grid wrap">
    <article class="card"><h3>봄 부케</h3><p>라넌큘러스 + 튤립 믹스</p></article>
    <article class="card"><h3>축하 꽃바구니</h3><p>리시안셔스 + 장미 프리미엄</p></article>
    <article class="card"><h3>당일 배송</h3><p>서울/경기 일부 지역 3시간 내</p></article>
  </section>
</body>
</html>
"""
    page = case_dir / "landing-page.html"
    page.write_text(html, encoding="utf-8")
    return page


def _write_case_result(
    *,
    case_id: str,
    title: str,
    expected_status: str,
    snapshot: dict[str, Any],
    artifact_payload: dict[str, Any] | None,
) -> Path:
    case_dir = RESULT_ROOT / case_id
    if case_dir.exists():
        shutil.rmtree(case_dir)
    case_dir.mkdir(parents=True, exist_ok=True)

    (case_dir / "snapshot.json").write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    meta = {
        "case_id": case_id,
        "title": title,
        "expected_status": expected_status,
        "actual_status": snapshot.get("status"),
        "cowork_id": snapshot.get("cowork_id"),
        "final_report": snapshot.get("final_report"),
    }
    (case_dir / "case_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")

    if artifact_payload and isinstance(artifact_payload.get("files"), list):
        out_dir = case_dir / "cowork_artifacts"
        out_dir.mkdir(parents=True, exist_ok=True)
        for row in artifact_payload["files"]:
            src = Path(str(row.get("path") or ""))
            if src.is_file():
                shutil.copy2(src, out_dir / src.name)

    return case_dir


async def _run_case(
    *,
    tmp_path: Path,
    case_id: str,
    task_text: str,
    variant_name: str,
    title: str,
    tagline: str,
    accent: str,
    hero_bg: str,
) -> None:
    store = MockMessengerStore(
        db_path=str(tmp_path / f"{case_id}.db"),
        data_dir=str(tmp_path / f"{case_id}-data"),
    )
    execution_link = f"http://127.0.0.1:{PREVIEW_PORT}/{case_id}/landing-page.html"
    sender = _sender_factory(execution_link=execution_link, variant_name=variant_name)
    sender.store = store  # type: ignore[attr-defined]
    orchestrator = CoworkOrchestrator(
        store=store,
        send_user_message=sender,
        poll_interval_sec=0.02,
        cool_down_sec=0.0,
        artifact_root=tmp_path / f"{case_id}-artifacts",
    )
    try:
        participants = _participants()
        started = await orchestrator.start_cowork(request=_request(task_text, participants), participants=participants)
        snapshot = await _wait_terminal(orchestrator, str(started["cowork_id"]))
        assert snapshot["status"] == "completed"
        assert str(snapshot["final_report"]["completion_status"]) == "passed"
        case_dir = _write_case_result(
            case_id=case_id,
            title=title,
            expected_status="completed",
            snapshot=snapshot,
            artifact_payload=orchestrator.get_cowork_artifacts(str(started["cowork_id"])),
        )
        _write_landing_html(case_dir, title=title, tagline=tagline, accent=accent, hero_bg=hero_bg)
        summary = (
            f"# {case_id}\n\n"
            f"- status: `{snapshot['status']}`\n"
            f"- execution_link: `{execution_link}`\n"
            f"- preview_file: `landing-page.html`\n"
        )
        (case_dir / "summary.md").write_text(summary, encoding="utf-8")
    finally:
        await orchestrator.shutdown()
        store.close()


@pytest.mark.asyncio
async def test_tc01_classic_flower_shop(tmp_path: Path) -> None:
    await _run_case(
        tmp_path=tmp_path,
        case_id="TC01_classic_flower_shop",
        task_text="클래식 꽃집 랜딩 페이지 생성",
        variant_name="Classic Flower Shop",
        title="Bloom Atelier",
        tagline="도심 속 계절 꽃을 가장 신선하게 전해드립니다.",
        accent="#d9487b",
        hero_bg="#ffe6ef",
    )


@pytest.mark.asyncio
async def test_tc02_seasonal_campaign(tmp_path: Path) -> None:
    await _run_case(
        tmp_path=tmp_path,
        case_id="TC02_seasonal_campaign",
        task_text="시즌 프로모션 꽃집 랜딩 페이지 생성",
        variant_name="Seasonal Campaign",
        title="Spring Limited Bouquet",
        tagline="이번 주 한정 컬렉션, 조기 품절 전에 만나보세요.",
        accent="#ff6a3d",
        hero_bg="#fff0de",
    )


@pytest.mark.asyncio
async def test_tc03_polished_live_preview(tmp_path: Path) -> None:
    await _run_case(
        tmp_path=tmp_path,
        case_id="TC03_polished_live_preview",
        task_text="고급형 꽃집 랜딩 페이지 생성",
        variant_name="Polished Live Preview",
        title="Maison Florale Signature",
        tagline="프리미엄 플로럴 큐레이션과 맞춤 배송 경험.",
        accent="#2f7d5a",
        hero_bg="#e7f7ef",
    )
