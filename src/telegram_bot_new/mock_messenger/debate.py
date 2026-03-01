from __future__ import annotations

import asyncio
import re
import time
from dataclasses import dataclass
from typing import Any, Awaitable, Callable

from telegram_bot_new.mock_messenger.schemas import DebateStartRequest, DebateStatusResponse
from telegram_bot_new.mock_messenger.store import MockMessengerStore

EVENT_LINE_RE = re.compile(r"^\[(\d+|~)\]\[(\d{2}:\d{2}:\d{2})\]\[([a-z_]+)\]\s?(.*)$", re.IGNORECASE)
TURN_FAILED_RE = re.compile(r'"status"\s*:\s*"(error|failed|timeout)"|\bstatus\s*=\s*(error|failed|timeout)\b', re.IGNORECASE)
TURN_SUCCESS_RE = re.compile(r'"status"\s*:\s*"(ok|success|completed)"|\bstatus\s*=\s*(ok|success|completed)\b', re.IGNORECASE)

ERROR_HINTS = (
    "[error]",
    "[delivery_error]",
    "delivery_error",
    "executable not found",
    "send error",
    "failed to send telegram message",
)

DEFAULT_TURN_SECTIONS: tuple[str, ...] = ("주장", "반박", "질문")
FINAL_ROUND_SECTIONS: tuple[str, ...] = ("요약", "결론")

DebateSendFn = Callable[[str, int, int, str], Awaitable[dict[str, Any]]]


class ActiveDebateExistsError(RuntimeError):
    pass


class DebateNotFoundError(RuntimeError):
    pass


@dataclass
class TurnOutcome:
    done: bool
    status: str
    detail: str
    response_text: str | None = None
    error_text: str | None = None


class DebateOrchestrator:
    def __init__(
        self,
        *,
        store: MockMessengerStore,
        send_user_message: DebateSendFn,
        poll_interval_sec: float = 1.0,
        cool_down_sec: float = 1.0,
    ) -> None:
        self._store = store
        self._send_user_message = send_user_message
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._cool_down_sec = max(0.0, float(cool_down_sec))

        self._lock = asyncio.Lock()
        self._active_debate_id: str | None = None
        self._active_task: asyncio.Task[None] | None = None

    def set_send_message_handler(self, handler: DebateSendFn) -> None:
        self._send_user_message = handler

    async def start_debate(
        self,
        *,
        request: DebateStartRequest,
        participants: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._lock:
            active = self._store.get_active_debate()
            if active is not None:
                raise ActiveDebateExistsError(active.get("debate_id"))

            debate_id = self._store.create_debate(
                topic=request.topic.strip(),
                rounds_total=int(request.rounds),
                max_turn_sec=int(request.max_turn_sec),
                fresh_session=bool(request.fresh_session),
                participants=participants,
            )
            self._active_debate_id = debate_id
            self._active_task = asyncio.create_task(self._run_debate(debate_id), name=f"debate:{debate_id}")

        snapshot = self.get_debate_snapshot(debate_id)
        assert snapshot is not None
        return snapshot

    def get_debate_snapshot(self, debate_id: str) -> dict[str, Any] | None:
        debate = self._store.get_debate(debate_id=debate_id)
        if debate is None:
            return None

        turns = self._store.list_debate_turns(debate_id=debate_id)
        participants = self._store.list_debate_participants(debate_id=debate_id)
        current_turn = next((turn for turn in reversed(turns) if turn.get("status") == "running"), None)
        errors = [
            {
                "turn_id": int(turn["id"]),
                "round_no": int(turn["round_no"]),
                "speaker_bot_id": str(turn["speaker_bot_id"]),
                "speaker_label": str(turn["speaker_label"]),
                "status": str(turn["status"]),
                "error_text": str(turn.get("error_text") or turn.get("response_text") or turn.get("status")),
            }
            for turn in turns
            if str(turn.get("status")) in {"timeout", "error", "template_error", "stopped", "skipped"}
        ]
        payload: dict[str, Any] = {
            **debate,
            "current_turn": (
                {
                    "round": int(current_turn["round_no"]),
                    "position": int(current_turn["speaker_position"]),
                    "speaker_bot_id": str(current_turn["speaker_bot_id"]),
                    "speaker_label": str(current_turn["speaker_label"]),
                    "started_at": int(current_turn["started_at"]),
                }
                if current_turn
                else None
            ),
            "turns": turns,
            "errors": errors,
            "participants": participants,
        }
        return DebateStatusResponse.model_validate(payload).model_dump()

    def get_active_debate_snapshot(self) -> dict[str, Any] | None:
        active = self._store.get_active_debate()
        if active is None:
            return None
        debate_id = str(active.get("debate_id") or "")
        if not debate_id:
            return None
        return self.get_debate_snapshot(debate_id)

    async def stop_debate(self, debate_id: str) -> dict[str, Any]:
        snapshot = self.get_debate_snapshot(debate_id)
        if snapshot is None:
            raise DebateNotFoundError(debate_id)
        self._store.set_debate_stop_requested(debate_id=debate_id)
        updated = self.get_debate_snapshot(debate_id)
        assert updated is not None
        return updated

    async def shutdown(self) -> None:
        task = self._active_task
        if task is not None and not task.done():
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_debate(self, debate_id: str) -> None:
        try:
            debate = self._store.get_debate(debate_id=debate_id)
            if debate is None:
                return
            participants = self._store.list_debate_participants(debate_id=debate_id)
            self._store.set_debate_running(debate_id=debate_id)

            if debate.get("fresh_session"):
                await self._broadcast_control_command(participants, "/new")
            await self._broadcast_control_command(participants, "/stop")
            if self._cool_down_sec > 0:
                await asyncio.sleep(self._cool_down_sec)

            transcript: list[dict[str, Any]] = []
            rounds_total = int(debate.get("rounds_total") or 1)
            max_turn_sec = int(debate.get("max_turn_sec") or 90)

            for round_no in range(1, rounds_total + 1):
                # Final round is a single synthesis turn by the starter bot (position=1).
                round_participants = participants[:1] if rounds_total > 1 and round_no == rounds_total else participants
                for participant in round_participants:
                    if self._is_stop_requested(debate_id):
                        self._store.finish_debate(debate_id=debate_id, status="stopped")
                        return

                    position = int(participant.get("position") or 0)
                    speaker_label = str(participant.get("label") or participant.get("bot_id") or f"bot-{position}")
                    speaker_bot_id = str(participant.get("bot_id") or "")
                    is_final_conclusion_turn = rounds_total > 1 and round_no == rounds_total and position == 1
                    required_sections = FINAL_ROUND_SECTIONS if is_final_conclusion_turn else DEFAULT_TURN_SECTIONS
                    prompt_text = self._build_turn_prompt(
                        topic=str(debate.get("topic") or ""),
                        round_no=round_no,
                        rounds_total=rounds_total,
                        participant=participant,
                        participants=participants,
                        transcript=transcript,
                        is_final_conclusion_turn=is_final_conclusion_turn,
                    )
                    turn_id = self._store.insert_debate_turn_start(
                        debate_id=debate_id,
                        round_no=round_no,
                        speaker_position=position,
                        speaker_bot_id=speaker_bot_id,
                        speaker_label=speaker_label,
                        prompt_text=prompt_text,
                    )

                    try:
                        baseline = self._max_message_id(participant)
                        await self._send_participant_message(participant, prompt_text)
                        outcome = await self._wait_for_turn_result(
                            debate_id=debate_id,
                            participant=participant,
                            baseline_message_id=baseline,
                            max_turn_sec=max_turn_sec,
                        )
                    except Exception as error:
                        outcome = TurnOutcome(
                            done=True,
                            status="error",
                            detail="send_error",
                            error_text=str(error),
                        )

                    final_status = outcome.status
                    final_error = outcome.error_text
                    final_response = outcome.response_text
                    if outcome.status == "success":
                        template_ok, template_error, missing_sections = self._validate_template(
                            outcome.response_text or "",
                            required_sections=required_sections,
                        )
                        if not template_ok:
                            repaired = await self._attempt_template_repair(
                                debate_id=debate_id,
                                participant=participant,
                                round_no=round_no,
                                topic=str(debate.get("topic") or ""),
                                speaker_label=speaker_label,
                                speaker_bot_id=speaker_bot_id,
                                original_response=outcome.response_text or "",
                                missing_sections=missing_sections,
                                required_sections=required_sections,
                                max_turn_sec=max_turn_sec,
                            )
                            if repaired is not None and repaired.status == "success":
                                fixed_ok, fixed_error, _ = self._validate_template(
                                    repaired.response_text or "",
                                    required_sections=required_sections,
                                )
                                if fixed_ok:
                                    final_status = "success"
                                    final_error = None
                                    final_response = repaired.response_text
                                else:
                                    final_status = "template_error"
                                    final_error = fixed_error
                                    final_response = repaired.response_text
                            else:
                                final_status = "template_error"
                                final_error = template_error

                    self._store.finish_debate_turn(
                        turn_id=turn_id,
                        status=final_status,
                        response_text=final_response,
                        error_text=final_error,
                    )
                    if final_status == "stopped":
                        self._store.finish_debate(debate_id=debate_id, status="stopped")
                        return
                    transcript.append(
                        {
                            "round_no": round_no,
                            "speaker_label": speaker_label,
                            "speaker_bot_id": speaker_bot_id,
                            "status": final_status,
                            "response_text": final_response or "",
                            "error_text": final_error or "",
                        }
                    )

            self._store.finish_debate(debate_id=debate_id, status="completed")
        except asyncio.CancelledError:
            debate = self._store.get_debate(debate_id=debate_id)
            if debate is not None and debate.get("status") in {"queued", "running"}:
                self._store.finish_debate(debate_id=debate_id, status="stopped", error_summary="debate task cancelled")
            raise
        except Exception as error:  # pragma: no cover - safety net
            self._store.finish_debate(debate_id=debate_id, status="failed", error_summary=str(error))
        finally:
            async with self._lock:
                if self._active_debate_id == debate_id:
                    self._active_debate_id = None
                    self._active_task = None

    async def _broadcast_control_command(self, participants: list[dict[str, Any]], command: str) -> None:
        for participant in participants:
            try:
                await self._send_participant_message(participant, command)
            except Exception:
                continue

    async def _send_participant_message(self, participant: dict[str, Any], text: str) -> None:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        user_id = int(participant.get("user_id") or 0)
        await self._send_user_message(token, chat_id, user_id, text)

    def _max_message_id(self, participant: dict[str, Any]) -> int:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        rows = self._store.get_messages(token=token, chat_id=chat_id, limit=1)
        if not rows:
            return 0
        return int(rows[-1].get("message_id") or 0)

    async def _wait_for_turn_result(
        self,
        *,
        debate_id: str,
        participant: dict[str, Any],
        baseline_message_id: int,
        max_turn_sec: int,
    ) -> TurnOutcome:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        deadline = time.monotonic() + max(1, int(max_turn_sec))

        while time.monotonic() < deadline:
            if self._is_stop_requested(debate_id):
                return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
            outcome = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
            if outcome.done:
                return outcome
            await asyncio.sleep(self._poll_interval_sec)

        if self._is_stop_requested(debate_id):
            return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
        last = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
        if last.done:
            return last
        return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")

    async def _attempt_template_repair(
        self,
        *,
        debate_id: str,
        participant: dict[str, Any],
        round_no: int,
        topic: str,
        speaker_label: str,
        speaker_bot_id: str,
        original_response: str,
        missing_sections: list[str],
        required_sections: tuple[str, ...],
        max_turn_sec: int,
    ) -> TurnOutcome | None:
        try:
            repair_prompt = self._build_template_repair_prompt(
                topic=topic,
                round_no=round_no,
                speaker_label=speaker_label,
                speaker_bot_id=speaker_bot_id,
                original_response=original_response,
                missing_sections=missing_sections,
                required_sections=required_sections,
            )
            baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, repair_prompt)
            retry_budget = min(20, max(5, int(max_turn_sec // 3)))
            return await self._wait_for_turn_result(
                debate_id=debate_id,
                participant=participant,
                baseline_message_id=baseline,
                max_turn_sec=retry_budget,
            )
        except Exception:
            return None

    def _classify_turn_outcome(self, *, token: str, chat_id: int, baseline_message_id: int) -> TurnOutcome:
        messages = self._store.get_messages(token=token, chat_id=chat_id, limit=200)
        bot_messages = [
            message
            for message in messages
            if message.get("direction") == "bot" and int(message.get("message_id") or 0) > baseline_message_id
        ]
        if not bot_messages:
            return TurnOutcome(done=False, status="running", detail="waiting")

        latest_assistant = ""
        latest_fallback = ""
        saw_turn_completed = False

        for message in bot_messages:
            text = str(message.get("text") or "").strip()
            parsed = self._parse_event_text(text)
            if text and not parsed.get("has_event_line"):
                latest_fallback = text
            assistant_text = parsed.get("assistant_text") or ""
            if assistant_text:
                # Prefer the most complete assistant snapshot, but preserve additive chunks
                # when stream data arrives split across multiple messages.
                if not latest_assistant:
                    latest_assistant = assistant_text
                elif assistant_text in latest_assistant:
                    pass
                elif latest_assistant in assistant_text:
                    latest_assistant = assistant_text
                else:
                    latest_assistant = f"{latest_assistant}\n{assistant_text}".strip()
            if parsed.get("error_text"):
                error_text = str(parsed["error_text"])
                return TurnOutcome(done=True, status="error", detail="error_event", error_text=error_text)
            if parsed.get("turn_failed"):
                return TurnOutcome(done=True, status="error", detail="turn_failed", error_text=text or "turn failed")
            if parsed.get("turn_completed"):
                saw_turn_completed = True

            lowered = text.lower()
            if any(token in lowered for token in ERROR_HINTS):
                return TurnOutcome(done=True, status="error", detail="error_hint", error_text=text)

        # Streamed assistant chunks can arrive before the terminal turn_completed event.
        # Treat the turn as successful only after completion is observed.
        if saw_turn_completed and latest_assistant:
            return TurnOutcome(done=True, status="success", detail="assistant_message", response_text=latest_assistant)
        if saw_turn_completed:
            return TurnOutcome(done=True, status="success", detail="turn_completed", response_text=latest_fallback)
        return TurnOutcome(done=False, status="running", detail="waiting")

    def _parse_event_text(self, text: str) -> dict[str, Any]:
        assistant_parts: list[str] = []
        error_parts: list[str] = []
        turn_completed = False
        turn_failed = False
        current_type = ""
        has_event_line = False

        for raw_line in text.splitlines():
            line = raw_line.rstrip()
            event = EVENT_LINE_RE.match(line)
            if event:
                has_event_line = True
                current_type = event.group(3).lower()
                body = event.group(4).strip()
                if current_type == "assistant_message" and body:
                    assistant_parts.append(body)
                elif current_type in {"error", "delivery_error"} and body:
                    error_parts.append(body)
                elif current_type == "turn_completed":
                    turn_completed = True
                    if TURN_FAILED_RE.search(body):
                        turn_failed = True
                    elif TURN_SUCCESS_RE.search(body):
                        turn_failed = False
                continue

            continuation = line.strip()
            if not continuation or not current_type:
                continue
            if current_type == "assistant_message":
                assistant_parts.append(continuation)
            elif current_type in {"error", "delivery_error"}:
                error_parts.append(continuation)

        return {
            "assistant_text": "\n".join(part for part in assistant_parts if part).strip(),
            "error_text": "\n".join(part for part in error_parts if part).strip() or None,
            "turn_completed": turn_completed,
            "turn_failed": turn_failed,
            "has_event_line": has_event_line,
        }

    def _is_stop_requested(self, debate_id: str) -> bool:
        debate = self._store.get_debate(debate_id=debate_id)
        if debate is None:
            return True
        return bool(debate.get("stop_requested"))

    def _build_turn_prompt(
        self,
        *,
        topic: str,
        round_no: int,
        rounds_total: int,
        participant: dict[str, Any],
        participants: list[dict[str, Any]],
        transcript: list[dict[str, Any]],
        is_final_conclusion_turn: bool,
    ) -> str:
        speaker_label = str(participant.get("label") or participant.get("bot_id") or "Bot")
        speaker_bot_id = str(participant.get("bot_id") or "")
        position = int(participant.get("position") or 0)
        total = len(participants)
        transcript_text = self._build_transcript_summary(transcript)

        if is_final_conclusion_turn:
            return (
                "멀티봇 토론의 최종 라운드입니다.\n"
                f"주제: {topic}\n"
                f"현재 라운드: {round_no}/{rounds_total}\n"
                f"발언자: {speaker_label} ({speaker_bot_id})\n"
                "역할: 시작 발언자로서 전체 토론을 정리하고 최종 결론을 제시하세요.\n\n"
                "전체 토론 요약:\n"
                f"{transcript_text}\n\n"
                "반드시 아래 형식을 정확히 지켜서 답하세요.\n"
                "요약: (핵심 논점 3~5개를 통합 정리)\n"
                "결론: (최종 판단 1개 + 이유)\n"
                "전체 길이는 900자 이내로 작성하세요."
            )

        return (
            "멀티봇 토론을 진행합니다.\n"
            f"주제: {topic}\n"
            f"현재 라운드: {round_no}\n"
            f"발언 순서: {position}/{total}\n"
            f"발언자: {speaker_label} ({speaker_bot_id})\n\n"
            "최근 토론 요약:\n"
            f"{transcript_text}\n\n"
            "반드시 아래 형식을 정확히 지켜서 답하세요.\n"
            "주장: (핵심 주장 1개)\n"
            "반박: (직전 논점에 대한 반박 1개)\n"
            "질문: (다음 발언자에게 던질 질문 1개)\n"
            "전체 길이는 700자 이내로 작성하세요."
        )

    def _build_template_repair_prompt(
        self,
        *,
        topic: str,
        round_no: int,
        speaker_label: str,
        speaker_bot_id: str,
        original_response: str,
        missing_sections: list[str],
        required_sections: tuple[str, ...],
    ) -> str:
        missing = ", ".join(missing_sections) if missing_sections else "형식 준수"
        clipped = original_response.strip()
        if len(clipped) > 1000:
            clipped = f"{clipped[:1000]}..."
        format_lines = "\n".join(f"{section}: ..." for section in required_sections)
        return (
            "이전 답변에서 형식 누락이 감지되었습니다. 아래 규칙만 다시 맞춰서 재작성하세요.\n"
            f"주제: {topic}\n"
            f"라운드: {round_no}\n"
            f"발언자: {speaker_label} ({speaker_bot_id})\n"
            f"누락된 항목: {missing}\n\n"
            "이전 답변:\n"
            f"{clipped}\n\n"
            f"반드시 아래 {len(required_sections)}줄 형식으로만 출력하세요.\n"
            f"{format_lines}\n"
            "총 길이는 900자 이내."
        )

    def _build_transcript_summary(self, transcript: list[dict[str, Any]]) -> str:
        if not transcript:
            return "- 아직 이전 발언이 없습니다."
        lines: list[str] = []
        char_budget = 6000
        for row in transcript[-12:]:
            speaker = str(row.get("speaker_label") or row.get("speaker_bot_id") or "bot")
            status = str(row.get("status") or "unknown")
            body = str(row.get("response_text") or row.get("error_text") or status).strip()
            if len(body) > 240:
                body = f"{body[:240]}..."
            line = f"- {speaker} [{status}]: {body}"
            if sum(len(x) + 1 for x in lines) + len(line) > char_budget:
                break
            lines.append(line)
        return "\n".join(lines) if lines else "- 요약이 없습니다."

    def _validate_template(self, text: str, *, required_sections: tuple[str, ...]) -> tuple[bool, str | None, list[str]]:
        missing = [key for key in required_sections if key not in text]
        if missing:
            return False, f"missing sections: {', '.join(missing)}", missing
        return True, None, []
