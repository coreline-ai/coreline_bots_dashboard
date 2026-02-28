from __future__ import annotations

import asyncio
import logging
import signal
import sys
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from telegram_bot_new.settings import GlobalSettings, load_bots_config

LOGGER = logging.getLogger(__name__)


@dataclass(slots=True)
class ProcessSpec:
    name: str
    command: list[str]


async def run_supervisor(
    *,
    config_path: str | Path,
    global_settings: GlobalSettings,
    embedded_host: str,
    embedded_base_port: int,
    gateway_host: str,
    gateway_port: int,
) -> None:
    bots = load_bots_config(config_path, global_settings)

    specs: list[ProcessSpec] = []
    embedded_port = embedded_base_port

    for bot in bots:
        if bot.mode == "embedded":
            specs.append(
                ProcessSpec(
                    name=f"bot:{bot.bot_id}:embedded",
                    command=[
                        sys.executable,
                        "-m",
                        "telegram_bot_new.main",
                        "run-bot",
                        "--config",
                        str(config_path),
                        "--bot-id",
                        bot.bot_id,
                        "--embedded-host",
                        embedded_host,
                        "--embedded-port",
                        str(embedded_port),
                    ],
                )
            )
            embedded_port += 1
        else:
            specs.append(
                ProcessSpec(
                    name=f"bot:{bot.bot_id}:worker",
                    command=[
                        sys.executable,
                        "-m",
                        "telegram_bot_new.main",
                        "run-bot",
                        "--config",
                        str(config_path),
                        "--bot-id",
                        bot.bot_id,
                    ],
                )
            )

    if any(bot.mode == "gateway" for bot in bots):
        specs.append(
            ProcessSpec(
                name="gateway",
                command=[
                    sys.executable,
                    "-m",
                    "telegram_bot_new.main",
                    "run-gateway",
                    "--config",
                    str(config_path),
                    "--host",
                    gateway_host,
                    "--port",
                    str(gateway_port),
                ],
            )
        )

    if not specs:
        raise ValueError("no process specs generated from bots config")

    stop_event = asyncio.Event()
    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        with suppress(NotImplementedError):
            loop.add_signal_handler(
                sig,
                lambda s=sig: _request_shutdown(stop_event, f"received signal={s.name}"),
            )

    tasks = [
        asyncio.create_task(_run_with_restart(spec, global_settings.supervisor_restart_max_backoff_sec, stop_event))
        for spec in specs
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        stop_event.set()
        for task in tasks:
            task.cancel()
        for task in tasks:
            with suppress(asyncio.CancelledError):
                await task
        for sig in (signal.SIGINT, signal.SIGTERM):
            with suppress(NotImplementedError):
                loop.remove_signal_handler(sig)


def _request_shutdown(stop_event: asyncio.Event, reason: str) -> None:
    if stop_event.is_set():
        return
    LOGGER.info("supervisor shutdown requested: %s", reason)
    stop_event.set()


async def _run_with_restart(spec: ProcessSpec, max_backoff_sec: int, stop_event: asyncio.Event) -> None:
    attempt = 0

    while not stop_event.is_set():
        LOGGER.info("starting process name=%s command=%s", spec.name, " ".join(spec.command))
        process = await asyncio.create_subprocess_exec(*spec.command)
        process_wait_task = asyncio.create_task(process.wait())
        stop_wait_task = asyncio.create_task(stop_event.wait())
        done, pending = await asyncio.wait(
            {process_wait_task, stop_wait_task},
            return_when=asyncio.FIRST_COMPLETED,
        )
        for task in pending:
            task.cancel()
            with suppress(asyncio.CancelledError):
                await task

        if stop_wait_task in done:
            await _terminate_process(spec.name, process)
            with suppress(asyncio.CancelledError):
                await process_wait_task
            return

        return_code = process_wait_task.result()
        if stop_event.is_set():
            return

        attempt += 1
        backoff = min(max_backoff_sec, 2 ** min(attempt, 6))
        LOGGER.warning(
            "process exited name=%s rc=%s restart_in=%ss",
            spec.name,
            return_code,
            backoff,
        )
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=backoff)
            return
        except asyncio.TimeoutError:
            continue


async def _terminate_process(name: str, process: asyncio.subprocess.Process) -> None:
    if process.returncode is not None:
        return

    LOGGER.info("terminating child process name=%s pid=%s", name, process.pid)
    process.terminate()
    try:
        await asyncio.wait_for(process.wait(), timeout=10)
        return
    except asyncio.TimeoutError:
        LOGGER.warning("child process did not terminate in time name=%s pid=%s; killing", name, process.pid)
    except ProcessLookupError:
        return

    with suppress(ProcessLookupError):
        process.kill()
    with suppress(asyncio.TimeoutError):
        await asyncio.wait_for(process.wait(), timeout=5)
