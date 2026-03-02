from __future__ import annotations

import asyncio
import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable

from telegram_bot_new.mock_messenger.schemas import CoworkStartRequest, CoworkStatusResponse
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
ACTIVE_RUN_HINTS = (
    "a run is active",
    "run is already active",
    "already active in this chat",
    "use /stop first",
)
ALLOWED_ROLES = ("controller", "planner", "executor", "integrator")


CoworkSendFn = Callable[[str, int, int, str], Awaitable[dict[str, Any]]]


class ActiveCoworkExistsError(RuntimeError):
    pass


class CoworkNotFoundError(RuntimeError):
    pass


@dataclass
class TurnOutcome:
    done: bool
    status: str
    detail: str
    response_text: str | None = None
    error_text: str | None = None


class CoworkOrchestrator:
    def __init__(
        self,
        *,
        store: MockMessengerStore,
        send_user_message: CoworkSendFn,
        poll_interval_sec: float = 1.0,
        cool_down_sec: float = 1.0,
        artifact_root: str | Path | None = None,
    ) -> None:
        self._store = store
        self._send_user_message = send_user_message
        self._poll_interval_sec = max(0.05, float(poll_interval_sec))
        self._cool_down_sec = max(0.0, float(cool_down_sec))
        root = Path(artifact_root) if artifact_root is not None else (Path.cwd() / "cowork")
        self._artifact_root = root.expanduser().resolve()
        self._lock = asyncio.Lock()
        self._active_tasks: dict[str, asyncio.Task[None]] = {}

    def set_send_message_handler(self, handler: CoworkSendFn) -> None:
        self._send_user_message = handler

    async def start_cowork(
        self,
        *,
        request: CoworkStartRequest,
        participants: list[dict[str, Any]],
    ) -> dict[str, Any]:
        async with self._lock:
            active = self._store.get_active_cowork()
            if active is not None:
                raise ActiveCoworkExistsError(active.get("cowork_id"))

            normalized = self._normalize_roles(participants)
            cowork_id = self._store.create_cowork(
                task=request.task.strip(),
                max_parallel=int(request.max_parallel),
                max_turn_sec=int(request.max_turn_sec),
                fresh_session=bool(request.fresh_session),
                keep_partial_on_error=bool(request.keep_partial_on_error),
                participants=normalized,
            )
            self._active_tasks[cowork_id] = asyncio.create_task(self._run_cowork(cowork_id), name=f"cowork:{cowork_id}")

        snapshot = self.get_cowork_snapshot(cowork_id)
        assert snapshot is not None
        return snapshot

    def get_cowork_snapshot(self, cowork_id: str) -> dict[str, Any] | None:
        cowork = self._store.get_cowork(cowork_id=cowork_id)
        if cowork is None:
            return None
        stages = self._store.list_cowork_stages(cowork_id=cowork_id)
        tasks = self._store.list_cowork_tasks(cowork_id=cowork_id)
        participants = self._store.list_cowork_participants(cowork_id=cowork_id)
        current_stage_row = next((stage for stage in reversed(stages) if stage.get("status") == "running"), None)

        errors: list[dict[str, Any]] = []
        for stage in stages:
            status = str(stage.get("status") or "")
            if status in {"error", "timeout", "failed", "stopped"}:
                errors.append(
                    {
                        "source": "stage",
                        "source_id": int(stage["id"]),
                        "stage_type": str(stage.get("stage_type") or ""),
                        "task_no": None,
                        "bot_id": str(stage.get("actor_bot_id") or ""),
                        "label": str(stage.get("actor_label") or ""),
                        "role": str(stage.get("actor_role") or "executor"),
                        "status": status,
                        "error_text": str(stage.get("error_text") or stage.get("response_text") or status),
                    }
                )
        for task in tasks:
            status = str(task.get("status") or "")
            if status in {"error", "timeout", "failed", "stopped"}:
                errors.append(
                    {
                        "source": "task",
                        "source_id": int(task["id"]),
                        "stage_type": None,
                        "task_no": int(task.get("task_no") or 0),
                        "bot_id": str(task.get("assignee_bot_id") or ""),
                        "label": str(task.get("assignee_label") or ""),
                        "role": str(task.get("assignee_role") or "executor"),
                        "status": status,
                        "error_text": str(task.get("error_text") or task.get("response_text") or status),
                    }
                )

        payload: dict[str, Any] = {
            **cowork,
            "current_stage": str(current_stage_row.get("stage_type") or "") if current_stage_row else None,
            "current_actor": (
                {
                    "bot_id": str(current_stage_row.get("actor_bot_id") or ""),
                    "label": str(current_stage_row.get("actor_label") or ""),
                    "role": str(current_stage_row.get("actor_role") or "executor"),
                }
                if current_stage_row
                else None
            ),
            "stages": stages,
            "tasks": tasks,
            "errors": errors,
            "participants": participants,
            "final_report": cowork.get("final_report"),
            "artifacts": self._build_artifact_payload(cowork_id),
        }
        return CoworkStatusResponse.model_validate(payload).model_dump()

    def get_active_cowork_snapshot(self) -> dict[str, Any] | None:
        active = self._store.get_active_cowork()
        if active is None:
            return None
        cowork_id = str(active.get("cowork_id") or "")
        if not cowork_id:
            return None
        return self.get_cowork_snapshot(cowork_id)

    async def stop_cowork(self, cowork_id: str) -> dict[str, Any]:
        snapshot = self.get_cowork_snapshot(cowork_id)
        if snapshot is None:
            raise CoworkNotFoundError(cowork_id)
        self._store.set_cowork_stop_requested(cowork_id=cowork_id)
        updated = self.get_cowork_snapshot(cowork_id)
        assert updated is not None
        return updated

    def get_cowork_artifacts(self, cowork_id: str) -> dict[str, Any] | None:
        if self._store.get_cowork(cowork_id=cowork_id) is None:
            return None
        return self._build_artifact_payload(cowork_id)

    def resolve_artifact_path(self, cowork_id: str, filename: str) -> Path | None:
        safe_name = Path(filename).name
        if not safe_name or safe_name != filename:
            return None
        path = (self._artifact_root / cowork_id / safe_name).resolve()
        root = (self._artifact_root / cowork_id).resolve()
        try:
            path.relative_to(root)
        except ValueError:
            return None
        if not path.is_file():
            return None
        return path

    async def shutdown(self) -> None:
        async with self._lock:
            tasks = list(self._active_tasks.values())
            self._active_tasks.clear()
        for task in tasks:
            if task.done():
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass

    async def _run_cowork(self, cowork_id: str) -> None:
        try:
            cowork = self._store.get_cowork(cowork_id=cowork_id)
            if cowork is None:
                return
            participants = self._store.list_cowork_participants(cowork_id=cowork_id)
            if len(participants) < 2:
                self._store.finish_cowork(cowork_id=cowork_id, status="failed", error_summary="participants must be >= 2")
                return
            self._store.set_cowork_running(cowork_id=cowork_id)

            if cowork.get("fresh_session"):
                await self._broadcast_control_command(participants, "/new")
            await self._broadcast_control_command(participants, "/stop")
            if self._cool_down_sec > 0:
                await asyncio.sleep(self._cool_down_sec)

            if self._is_stop_requested(cowork_id):
                self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
                return

            role_map = self._role_map(participants)
            max_turn_sec = int(cowork.get("max_turn_sec") or 90)
            keep_partial = bool(cowork.get("keep_partial_on_error"))
            root_task = str(cowork.get("task") or "")

            plan_items = await self._stage_planning(
                cowork_id=cowork_id,
                task_text=root_task,
                planner=role_map["planner"],
                participants=participants,
                max_turn_sec=max_turn_sec,
                keep_partial=keep_partial,
            )
            if plan_items is None:
                return

            execution_rows = await self._stage_execution(
                cowork_id=cowork_id,
                task_text=root_task,
                plan_items=plan_items,
                executors=role_map["executors"],
                max_parallel=int(cowork.get("max_parallel") or 3),
                max_turn_sec=max_turn_sec,
            )
            if execution_rows is None:
                return

            integration_text = await self._stage_integration(
                cowork_id=cowork_id,
                task_text=root_task,
                integrator=role_map["integrator"],
                execution_rows=execution_rows,
                max_turn_sec=max_turn_sec,
            )
            if integration_text is None:
                return

            final_report = await self._stage_finalization(
                cowork_id=cowork_id,
                task_text=root_task,
                controller=role_map["controller"],
                integration_text=integration_text,
                execution_rows=execution_rows,
                max_turn_sec=max_turn_sec,
            )
            if final_report is None:
                return

            self._store.finish_cowork(cowork_id=cowork_id, status="completed", final_report=final_report)
        except asyncio.CancelledError:
            cowork = self._store.get_cowork(cowork_id=cowork_id)
            if cowork is not None and cowork.get("status") in {"queued", "running"}:
                self._store.finish_cowork(cowork_id=cowork_id, status="stopped", error_summary="cowork task cancelled")
            raise
        except Exception as error:  # pragma: no cover
            self._store.finish_cowork(cowork_id=cowork_id, status="failed", error_summary=str(error))
        finally:
            self._write_cowork_artifacts(cowork_id)
            async with self._lock:
                self._active_tasks.pop(cowork_id, None)

    async def _stage_planning(
        self,
        *,
        cowork_id: str,
        task_text: str,
        planner: dict[str, Any],
        participants: list[dict[str, Any]],
        max_turn_sec: int,
        keep_partial: bool,
    ) -> list[dict[str, Any]] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None
        prompt_text = self._build_planning_prompt(task_text=task_text, participants=participants, planner=planner)
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=1,
            stage_type="planning",
            actor_bot_id=str(planner.get("bot_id") or ""),
            actor_label=str(planner.get("label") or ""),
            actor_role=str(planner.get("role") or "planner"),
            prompt_text=prompt_text,
        )
        try:
            baseline = self._max_message_id(planner)
            await self._send_participant_message(planner, prompt_text)
            outcome = await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=planner,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception as error:
            outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))

        if self._looks_like_active_run_outcome(outcome):
            retry = await self._retry_turn_after_stop(
                cowork_id=cowork_id,
                participant=planner,
                prompt_text=prompt_text,
                max_turn_sec=max_turn_sec,
            )
            if retry is not None:
                outcome = retry

        if outcome.status == "success":
            plan_items = self._parse_planning_tasks(outcome.response_text or "")
            if not plan_items:
                plan_items = [self._fallback_plan_item(task_text)]
            self._store.finish_cowork_stage(stage_id=stage_id, status="success", response_text=outcome.response_text)
            return plan_items

        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status=outcome.status,
            response_text=outcome.response_text,
            error_text=outcome.error_text or outcome.detail,
        )
        if not keep_partial:
            self._store.finish_cowork(
                cowork_id=cowork_id,
                status="failed",
                error_summary=outcome.error_text or "planning failed",
            )
            return None
        return [self._fallback_plan_item(task_text)]

    async def _stage_execution(
        self,
        *,
        cowork_id: str,
        task_text: str,
        plan_items: list[dict[str, Any]],
        executors: list[dict[str, Any]],
        max_parallel: int,
        max_turn_sec: int,
    ) -> list[dict[str, Any]] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None

        execution_rows: list[dict[str, Any]] = []
        for index, item in enumerate(plan_items, start=1):
            assignee = executors[(index - 1) % len(executors)]
            task_id = self._store.insert_cowork_task(
                cowork_id=cowork_id,
                task_no=index,
                title=str(item.get("title") or f"Task {index}"),
                spec_json=item,
                assignee_bot_id=str(assignee.get("bot_id") or ""),
                assignee_label=str(assignee.get("label") or ""),
                assignee_role=str(assignee.get("role") or "executor"),
                status="pending",
            )
            execution_rows.append(
                {
                    "task_id": task_id,
                    "task_no": index,
                    "plan": item,
                    "assignee": assignee,
                }
            )

        semaphore = asyncio.Semaphore(max(1, int(max_parallel)))

        async def _run_one(row: dict[str, Any]) -> None:
            async with semaphore:
                if self._is_stop_requested(cowork_id):
                    self._store.finish_cowork_task(task_id=int(row["task_id"]), status="stopped", error_text="stop requested")
                    return

                assignee = row["assignee"]
                plan = row["plan"]
                self._store.start_cowork_task(task_id=int(row["task_id"]))
                prompt_text = self._build_execution_prompt(
                    task_text=task_text,
                    task_no=int(row["task_no"]),
                    plan=plan,
                    assignee=assignee,
                )
                stage_id = self._store.insert_cowork_stage_start(
                    cowork_id=cowork_id,
                    stage_no=2,
                    stage_type="execution",
                    actor_bot_id=str(assignee.get("bot_id") or ""),
                    actor_label=str(assignee.get("label") or ""),
                    actor_role=str(assignee.get("role") or "executor"),
                    prompt_text=prompt_text,
                )

                try:
                    baseline = self._max_message_id(assignee)
                    await self._send_participant_message(assignee, prompt_text)
                    outcome = await self._wait_for_turn_result(
                        cowork_id=cowork_id,
                        participant=assignee,
                        baseline_message_id=baseline,
                        max_turn_sec=max_turn_sec,
                    )
                except Exception as error:
                    outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))

                if self._looks_like_active_run_outcome(outcome):
                    retry = await self._retry_turn_after_stop(
                        cowork_id=cowork_id,
                        participant=assignee,
                        prompt_text=prompt_text,
                        max_turn_sec=max_turn_sec,
                    )
                    if retry is not None:
                        outcome = retry

                if outcome.status == "success":
                    self._store.finish_cowork_task(
                        task_id=int(row["task_id"]),
                        status="success",
                        response_text=outcome.response_text,
                    )
                    self._store.finish_cowork_stage(
                        stage_id=stage_id,
                        status="success",
                        response_text=outcome.response_text,
                    )
                else:
                    self._store.finish_cowork_task(
                        task_id=int(row["task_id"]),
                        status=outcome.status,
                        response_text=outcome.response_text,
                        error_text=outcome.error_text or outcome.detail,
                    )
                    self._store.finish_cowork_stage(
                        stage_id=stage_id,
                        status=outcome.status,
                        response_text=outcome.response_text,
                        error_text=outcome.error_text or outcome.detail,
                    )

        await asyncio.gather(*[_run_one(row) for row in execution_rows])
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None
        return self._store.list_cowork_tasks(cowork_id=cowork_id)

    async def _stage_integration(
        self,
        *,
        cowork_id: str,
        task_text: str,
        integrator: dict[str, Any],
        execution_rows: list[dict[str, Any]],
        max_turn_sec: int,
    ) -> str | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None

        prompt_text = self._build_integration_prompt(
            task_text=task_text,
            integrator=integrator,
            execution_rows=execution_rows,
        )
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=3,
            stage_type="integration",
            actor_bot_id=str(integrator.get("bot_id") or ""),
            actor_label=str(integrator.get("label") or ""),
            actor_role=str(integrator.get("role") or "integrator"),
            prompt_text=prompt_text,
        )
        try:
            baseline = self._max_message_id(integrator)
            await self._send_participant_message(integrator, prompt_text)
            outcome = await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=integrator,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception as error:
            outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))

        if outcome.status == "success":
            self._store.finish_cowork_stage(stage_id=stage_id, status="success", response_text=outcome.response_text)
            return str(outcome.response_text or "")

        fallback = self._fallback_integration_text(execution_rows)
        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status=outcome.status,
            response_text=fallback,
            error_text=outcome.error_text or outcome.detail,
        )
        return fallback

    async def _stage_finalization(
        self,
        *,
        cowork_id: str,
        task_text: str,
        controller: dict[str, Any],
        integration_text: str,
        execution_rows: list[dict[str, Any]],
        max_turn_sec: int,
    ) -> dict[str, Any] | None:
        if self._is_stop_requested(cowork_id):
            self._store.finish_cowork(cowork_id=cowork_id, status="stopped")
            return None

        prompt_text = self._build_finalization_prompt(
            task_text=task_text,
            controller=controller,
            integration_text=integration_text,
            execution_rows=execution_rows,
        )
        stage_id = self._store.insert_cowork_stage_start(
            cowork_id=cowork_id,
            stage_no=4,
            stage_type="finalization",
            actor_bot_id=str(controller.get("bot_id") or ""),
            actor_label=str(controller.get("label") or ""),
            actor_role=str(controller.get("role") or "controller"),
            prompt_text=prompt_text,
        )
        try:
            baseline = self._max_message_id(controller)
            await self._send_participant_message(controller, prompt_text)
            outcome = await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=controller,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception as error:
            outcome = TurnOutcome(done=True, status="error", detail="send_error", error_text=str(error))

        if outcome.status == "success":
            self._store.finish_cowork_stage(stage_id=stage_id, status="success", response_text=outcome.response_text)
            return self._build_final_report(
                integration_text=integration_text,
                finalization_text=str(outcome.response_text or ""),
                execution_rows=execution_rows,
            )

        fallback = self._fallback_finalization_text(task_text, execution_rows)
        self._store.finish_cowork_stage(
            stage_id=stage_id,
            status=outcome.status,
            response_text=fallback,
            error_text=outcome.error_text or outcome.detail,
        )
        return self._build_final_report(
            integration_text=integration_text,
            finalization_text=fallback,
            execution_rows=execution_rows,
        )

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
        cowork_id: str,
        participant: dict[str, Any],
        baseline_message_id: int,
        max_turn_sec: int,
    ) -> TurnOutcome:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        deadline = time.monotonic() + max(1, int(max_turn_sec))

        while time.monotonic() < deadline:
            if self._is_stop_requested(cowork_id):
                return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
            outcome = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
            if outcome.done:
                return outcome
            await asyncio.sleep(self._poll_interval_sec)

        if self._is_stop_requested(cowork_id):
            return TurnOutcome(done=True, status="stopped", detail="stop_requested", error_text="stop requested")
        last = self._classify_turn_outcome(token=token, chat_id=chat_id, baseline_message_id=baseline_message_id)
        if last.done:
            return last
        return TurnOutcome(done=True, status="timeout", detail="timeout", error_text="turn timeout")

    async def _retry_turn_after_stop(
        self,
        *,
        cowork_id: str,
        participant: dict[str, Any],
        prompt_text: str,
        max_turn_sec: int,
    ) -> TurnOutcome | None:
        try:
            stop_baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, "/stop")
            await self._wait_for_stop_ack(participant=participant, baseline_message_id=stop_baseline, timeout_sec=6)
            baseline = self._max_message_id(participant)
            await self._send_participant_message(participant, prompt_text)
            return await self._wait_for_turn_result(
                cowork_id=cowork_id,
                participant=participant,
                baseline_message_id=baseline,
                max_turn_sec=max_turn_sec,
            )
        except Exception:
            return None

    async def _wait_for_stop_ack(self, *, participant: dict[str, Any], baseline_message_id: int, timeout_sec: int) -> None:
        token = str(participant.get("token") or "")
        chat_id = int(participant.get("chat_id") or 0)
        deadline = time.monotonic() + max(1, int(timeout_sec))
        while time.monotonic() < deadline:
            messages = self._store.get_messages(token=token, chat_id=chat_id, limit=120)
            for message in messages:
                if message.get("direction") != "bot":
                    continue
                if int(message.get("message_id") or 0) <= baseline_message_id:
                    continue
                text = str(message.get("text") or "").lower()
                if "stop requested." in text or "no active run." in text or "stopping..." in text:
                    return
            await asyncio.sleep(self._poll_interval_sec)

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
                if not latest_assistant:
                    latest_assistant = assistant_text
                elif assistant_text in latest_assistant:
                    pass
                elif latest_assistant in assistant_text:
                    latest_assistant = assistant_text
                else:
                    latest_assistant = f"{latest_assistant}\n{assistant_text}".strip()
            if parsed.get("error_text"):
                return TurnOutcome(done=True, status="error", detail="error_event", error_text=str(parsed["error_text"]))
            if parsed.get("turn_failed"):
                return TurnOutcome(done=True, status="error", detail="turn_failed", error_text=text or "turn failed")
            if parsed.get("turn_completed"):
                saw_turn_completed = True

            lowered = text.lower()
            if self._contains_active_run_hint(lowered):
                return TurnOutcome(done=True, status="error", detail="active_run", error_text=text)
            if any(token_hint in lowered for token_hint in ERROR_HINTS):
                return TurnOutcome(done=True, status="error", detail="error_hint", error_text=text)

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

    @staticmethod
    def _contains_active_run_hint(text: str) -> bool:
        lowered = str(text or "").lower()
        return any(hint in lowered for hint in ACTIVE_RUN_HINTS)

    def _looks_like_active_run_outcome(self, outcome: TurnOutcome) -> bool:
        if outcome.status != "error":
            return False
        if str(outcome.detail).strip().lower() == "active_run":
            return True
        return self._contains_active_run_hint(str(outcome.error_text or "").lower())

    def _is_stop_requested(self, cowork_id: str) -> bool:
        cowork = self._store.get_cowork(cowork_id=cowork_id)
        if cowork is None:
            return True
        return bool(cowork.get("stop_requested"))

    def _normalize_roles(self, participants: list[dict[str, Any]]) -> list[dict[str, Any]]:
        normalized = [{**row} for row in participants]
        reserved = {"controller": False, "planner": False, "integrator": False}
        for row in normalized:
            role = str(row.get("role") or "executor").strip().lower()
            if role not in ALLOWED_ROLES:
                role = "executor"
            if role in reserved:
                if reserved[role]:
                    role = "executor"
                else:
                    reserved[role] = True
            row["role"] = role

        def has_role(name: str) -> bool:
            return any(str(row.get("role") or "") == name for row in normalized)

        def promote_executor_or_fallback(role_name: str, fallback_index: int) -> None:
            if has_role(role_name):
                return
            candidate = next((row for row in normalized if str(row.get("role") or "") == "executor"), None)
            if candidate is None:
                candidate = normalized[fallback_index]
            candidate["role"] = role_name

        promote_executor_or_fallback("controller", 0)
        promote_executor_or_fallback("planner", 0)
        promote_executor_or_fallback("integrator", -1)

        if all(str(row.get("role") or "") != "executor" for row in normalized):
            planner = next((row for row in normalized if str(row.get("role") or "") == "planner"), normalized[0])
            planner["role"] = "executor"
        return normalized

    def _role_map(self, participants: list[dict[str, Any]]) -> dict[str, Any]:
        controller = next((row for row in participants if str(row.get("role")) == "controller"), participants[0])
        planner = next((row for row in participants if str(row.get("role")) == "planner"), participants[0])
        integrator = next((row for row in participants if str(row.get("role")) == "integrator"), participants[-1])
        executors = [row for row in participants if str(row.get("role")) == "executor"]
        if not executors:
            executors = [planner]
        return {
            "controller": controller,
            "planner": planner,
            "integrator": integrator,
            "executors": executors,
        }

    @staticmethod
    def _fallback_plan_item(task_text: str) -> dict[str, Any]:
        return {
            "title": "요청 분석 및 실행 초안 작성",
            "goal": f"요청 '{task_text}'에 대한 실행 가능한 초안을 작성",
            "done_criteria": "핵심 작업 단계와 체크리스트를 제시",
            "risk": "요구사항 누락 가능성",
        }

    def _parse_planning_tasks(self, text: str) -> list[dict[str, Any]]:
        tasks: list[dict[str, Any]] = []
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if not (line.startswith("{") and line.endswith("}")):
                continue
            try:
                payload = json.loads(line)
            except Exception:
                continue
            if not isinstance(payload, dict):
                continue
            title = str(payload.get("title") or "").strip()
            goal = str(payload.get("goal") or "").strip()
            done_criteria = str(payload.get("done_criteria") or payload.get("doneCriteria") or "").strip()
            risk = str(payload.get("risk") or "").strip()
            if not title:
                continue
            tasks.append(
                {
                    "title": title,
                    "goal": goal,
                    "done_criteria": done_criteria,
                    "risk": risk,
                }
            )
            if len(tasks) >= 12:
                break
        return tasks

    def _build_planning_prompt(self, *, task_text: str, participants: list[dict[str, Any]], planner: dict[str, Any]) -> str:
        actor = str(planner.get("label") or planner.get("bot_id") or "Planner")
        roster = ", ".join(
            f"{str(row.get('label') or row.get('bot_id'))}:{str(row.get('role') or 'executor')}" for row in participants
        )
        return (
            "당신은 멀티봇 협업의 Planner입니다.\n"
            f"요청: {task_text}\n"
            f"참여자: {roster}\n"
            f"현재 Planner: {actor}\n\n"
            "아래 형식으로만 출력하세요. 각 줄은 JSON 객체 1개입니다.\n"
            '{"title":"작업명","goal":"목표","done_criteria":"완료조건","risk":"리스크"}\n'
            "최소 2개, 최대 8개 작업으로 분해하세요. 불필요한 설명 문장은 금지합니다."
        )

    def _build_execution_prompt(
        self,
        *,
        task_text: str,
        task_no: int,
        plan: dict[str, Any],
        assignee: dict[str, Any],
    ) -> str:
        return (
            "당신은 멀티봇 협업의 Executor입니다.\n"
            f"원본 요청: {task_text}\n"
            f"할당 작업 번호: {task_no}\n"
            f"작업명: {str(plan.get('title') or '')}\n"
            f"목표: {str(plan.get('goal') or '')}\n"
            f"완료조건: {str(plan.get('done_criteria') or '')}\n"
            f"리스크: {str(plan.get('risk') or '')}\n"
            f"담당자: {str(assignee.get('label') or assignee.get('bot_id') or '')}\n\n"
            "반드시 아래 형식으로 작성하세요.\n"
            "결과요약: (핵심 결과)\n"
            "검증: (완료조건 충족 여부)\n"
            "남은이슈: (없으면 '없음')\n"
            "총 700자 이내."
        )

    def _build_execution_summary(self, execution_rows: list[dict[str, Any]]) -> str:
        if not execution_rows:
            return "- 실행 결과가 없습니다."
        lines: list[str] = []
        for row in execution_rows:
            status = str(row.get("status") or "unknown")
            body = str(row.get("response_text") or row.get("error_text") or status).strip()
            if len(body) > 240:
                body = f"{body[:240]}..."
            lines.append(
                f"- T{int(row.get('task_no') or 0)} {str(row.get('title') or '')} / {str(row.get('assignee_label') or row.get('assignee_bot_id') or '')} [{status}] {body}"
            )
        return "\n".join(lines)

    def _build_integration_prompt(
        self,
        *,
        task_text: str,
        integrator: dict[str, Any],
        execution_rows: list[dict[str, Any]],
    ) -> str:
        execution_summary = self._build_execution_summary(execution_rows)
        return (
            "당신은 멀티봇 협업의 Integrator입니다.\n"
            f"원본 요청: {task_text}\n"
            f"담당자: {str(integrator.get('label') or integrator.get('bot_id') or '')}\n\n"
            "실행 결과 요약:\n"
            f"{execution_summary}\n\n"
            "반드시 아래 형식으로 답하세요.\n"
            "통합요약: ...\n"
            "충돌사항: ...\n"
            "누락사항: ...\n"
            "권장수정: ...\n"
            "총 900자 이내."
        )

    def _build_finalization_prompt(
        self,
        *,
        task_text: str,
        controller: dict[str, Any],
        integration_text: str,
        execution_rows: list[dict[str, Any]],
    ) -> str:
        execution_summary = self._build_execution_summary(execution_rows)
        clipped_integration = integration_text.strip()
        if len(clipped_integration) > 1800:
            clipped_integration = f"{clipped_integration[:1800]}..."
        return (
            "당신은 멀티봇 협업의 Controller입니다.\n"
            f"원본 요청: {task_text}\n"
            f"담당자: {str(controller.get('label') or controller.get('bot_id') or '')}\n\n"
            "Integrator 리포트:\n"
            f"{clipped_integration}\n\n"
            "실행 결과 요약:\n"
            f"{execution_summary}\n\n"
            "아래 형식을 정확히 지켜 최종 결론을 작성하세요.\n"
            "최종결론: ...\n"
            "실행체크리스트: ...\n"
            "즉시실행항목(Top3): 1) ... 2) ... 3) ...\n"
            "총 900자 이내."
        )

    def _extract_labeled_line(self, text: str, label: str) -> str | None:
        key = label.strip().lower()
        for raw_line in text.splitlines():
            line = raw_line.strip()
            if not line:
                continue
            if ":" in line:
                left, right = line.split(":", 1)
            elif "：" in line:
                left, right = line.split("：", 1)
            else:
                continue
            if left.strip().lower() != key:
                continue
            value = right.strip()
            return value or None
        return None

    def _extract_top3_actions(self, text: str) -> list[str]:
        line = self._extract_labeled_line(text, "즉시실행항목(Top3)") or ""
        if not line:
            return []
        chunks = re.split(r"\s*\d+\)\s*", line)
        actions = [chunk.strip(" -") for chunk in chunks if chunk.strip(" -")]
        return actions[:3]

    def _build_final_report(
        self,
        *,
        integration_text: str,
        finalization_text: str,
        execution_rows: list[dict[str, Any]],
    ) -> dict[str, Any]:
        integrated_summary = self._extract_labeled_line(integration_text, "통합요약")
        conflicts = self._extract_labeled_line(integration_text, "충돌사항")
        missing = self._extract_labeled_line(integration_text, "누락사항")
        recommended_fixes = self._extract_labeled_line(integration_text, "권장수정")
        final_conclusion = self._extract_labeled_line(finalization_text, "최종결론")
        execution_checklist = self._extract_labeled_line(finalization_text, "실행체크리스트")
        actions = self._extract_top3_actions(finalization_text)
        if not integrated_summary:
            integrated_summary = self._fallback_integration_text(execution_rows)
        if not final_conclusion:
            final_conclusion = finalization_text.splitlines()[0].strip() if finalization_text.strip() else "최종 결론 생성 실패"
        return {
            "integrated_summary": integrated_summary,
            "conflicts": conflicts or "없음",
            "missing": missing or "없음",
            "recommended_fixes": recommended_fixes or "없음",
            "final_conclusion": final_conclusion,
            "execution_checklist": execution_checklist or "- 완료 기준 검증\n- 누락 사항 재점검\n- 후속 실행 일정 수립",
            "immediate_actions_top3": actions or [
                "핵심 결과를 사용자와 합의",
                "실행 누락 항목을 보완",
                "후속 검증 라운드 예약",
            ],
        }

    def _fallback_integration_text(self, execution_rows: list[dict[str, Any]]) -> str:
        summary = self._build_execution_summary(execution_rows)
        return (
            f"통합요약: {summary}\n"
            "충돌사항: 자동 통합(LLM) 실패로 상세 충돌 분석 생략\n"
            "누락사항: 실패/타임아웃 항목 수동 재검토 필요\n"
            "권장수정: 실패 작업 재실행 및 결과 검증"
        )

    def _fallback_finalization_text(self, task_text: str, execution_rows: list[dict[str, Any]]) -> str:
        success_count = sum(1 for row in execution_rows if str(row.get("status") or "") == "success")
        total_count = len(execution_rows)
        return (
            f"최종결론: '{task_text}' 작업은 {success_count}/{total_count} 항목 완료 상태입니다.\n"
            "실행체크리스트: 1) 완료 항목 검증 2) 실패 항목 재시도 3) 통합 리포트 확정\n"
            "즉시실행항목(Top3): 1) 실패 작업 재실행 2) 누락사항 보완 3) 최종 승인"
        )

    def _artifact_dir(self, cowork_id: str) -> Path:
        return self._artifact_root / cowork_id

    def _build_artifact_payload(self, cowork_id: str) -> dict[str, Any] | None:
        root = self._artifact_dir(cowork_id)
        if not root.is_dir():
            return None
        files: list[dict[str, Any]] = []
        for path in sorted(root.iterdir(), key=lambda row: row.name):
            if not path.is_file():
                continue
            files.append(
                {
                    "name": path.name,
                    "path": str(path),
                    "url": f"/_mock/cowork/{cowork_id}/artifact/{path.name}",
                    "size_bytes": int(path.stat().st_size),
                }
            )
        if not files:
            return None
        return {"root_dir": str(root), "files": files}

    def _write_cowork_artifacts(self, cowork_id: str) -> None:
        snapshot = self.get_cowork_snapshot(cowork_id)
        if snapshot is None:
            return
        root = self._artifact_dir(cowork_id)
        root.mkdir(parents=True, exist_ok=True)

        result_json = root / "result.json"
        result_json.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")

        final_report = snapshot.get("final_report")
        if isinstance(final_report, dict):
            (root / "final_report.json").write_text(json.dumps(final_report, ensure_ascii=False, indent=2), encoding="utf-8")

        stages = snapshot.get("stages")
        if isinstance(stages, list):
            (root / "stages.json").write_text(json.dumps(stages, ensure_ascii=False, indent=2), encoding="utf-8")

        tasks = snapshot.get("tasks")
        if isinstance(tasks, list):
            (root / "tasks.json").write_text(json.dumps(tasks, ensure_ascii=False, indent=2), encoding="utf-8")

        (root / "summary.md").write_text(self._build_artifact_summary_md(snapshot), encoding="utf-8")

    def _build_artifact_summary_md(self, snapshot: dict[str, Any]) -> str:
        cowork_id = str(snapshot.get("cowork_id") or "")
        task_text = str(snapshot.get("task") or "")
        status = str(snapshot.get("status") or "unknown")
        stages = snapshot.get("stages") if isinstance(snapshot.get("stages"), list) else []
        tasks = snapshot.get("tasks") if isinstance(snapshot.get("tasks"), list) else []
        final_report = snapshot.get("final_report") if isinstance(snapshot.get("final_report"), dict) else {}
        lines: list[str] = [
            "# Cowork Result",
            "",
            f"- Cowork ID: `{cowork_id}`",
            f"- Status: `{status}`",
            f"- Task: {task_text}",
            "",
            "## Stage Summary",
            "",
            "| Stage | Type | Actor | Status | Duration(ms) |",
            "| --- | --- | --- | --- | ---: |",
        ]
        for row in stages:
            lines.append(
                f"| {int(row.get('stage_no') or 0)} | {str(row.get('stage_type') or '')} | "
                f"{str(row.get('actor_label') or row.get('actor_bot_id') or '')} | "
                f"{str(row.get('status') or '')} | {int(row.get('duration_ms') or 0)} |"
            )
        lines.extend(
            [
                "",
                "## Task Summary",
                "",
                "| Task | Assignee | Status | Duration(ms) |",
                "| --- | --- | --- | ---: |",
            ]
        )
        for row in tasks:
            lines.append(
                f"| {int(row.get('task_no') or 0)} | {str(row.get('assignee_label') or row.get('assignee_bot_id') or '')} | "
                f"{str(row.get('status') or '')} | {int(row.get('duration_ms') or 0)} |"
            )
        lines.extend(["", "## Final Report", ""])
        if final_report:
            lines.append("```json")
            lines.append(json.dumps(final_report, ensure_ascii=False, indent=2))
            lines.append("```")
        else:
            lines.append("최종 리포트 없음")
        lines.append("")
        return "\n".join(lines)
