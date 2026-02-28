from __future__ import annotations

import argparse
import asyncio
from pathlib import Path

from telegram_bot_new.runtime_embedded import run_bot_workers_only, run_embedded_bot
from telegram_bot_new.runtime_gateway import run_gateway_server
from telegram_bot_new.settings import get_global_settings, load_bots_config
from telegram_bot_new.supervisor import run_supervisor


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="telegram_bot_new entrypoint")
    sub = parser.add_subparsers(dest="command", required=True)

    p_supervisor = sub.add_parser("supervisor")
    p_supervisor.add_argument("--config", default="config/bots.yaml")
    p_supervisor.add_argument("--embedded-host", default="127.0.0.1")
    p_supervisor.add_argument("--embedded-base-port", type=int, default=8600)
    p_supervisor.add_argument("--gateway-host", default="0.0.0.0")
    p_supervisor.add_argument("--gateway-port", type=int, default=4312)

    p_run_bot = sub.add_parser("run-bot")
    p_run_bot.add_argument("--config", default="config/bots.yaml")
    p_run_bot.add_argument("--bot-id", required=True)
    p_run_bot.add_argument("--embedded-host", default="127.0.0.1")
    p_run_bot.add_argument("--embedded-port", type=int, default=8600)

    p_gateway = sub.add_parser("run-gateway")
    p_gateway.add_argument("--config", default="config/bots.yaml")
    p_gateway.add_argument("--host", default="0.0.0.0")
    p_gateway.add_argument("--port", type=int, default=4312)

    return parser


async def amain() -> None:
    parser = build_parser()
    args = parser.parse_args()

    settings = get_global_settings()
    config_path = Path(args.config).expanduser().resolve()

    if args.command == "supervisor":
        await run_supervisor(
            config_path=config_path,
            global_settings=settings,
            embedded_host=args.embedded_host,
            embedded_base_port=args.embedded_base_port,
            gateway_host=args.gateway_host,
            gateway_port=args.gateway_port,
        )
        return

    bots = load_bots_config(config_path, settings)

    if args.command == "run-bot":
        bot = next((b for b in bots if b.bot_id == args.bot_id), None)
        if bot is None:
            raise SystemExit(f"bot not found: {args.bot_id}")

        if bot.mode == "embedded":
            await run_embedded_bot(
                bot=bot,
                global_settings=settings,
                host=args.embedded_host,
                port=args.embedded_port,
            )
            return

        await run_bot_workers_only(bot=bot, global_settings=settings)
        return

    if args.command == "run-gateway":
        gateway_bots = [b for b in bots if b.mode == "gateway"]
        await run_gateway_server(
            bots=gateway_bots,
            global_settings=settings,
            host=args.host,
            port=args.port,
        )
        return

    raise SystemExit(f"unsupported command: {args.command}")


def main() -> None:
    try:
        asyncio.run(amain())
    except KeyboardInterrupt:
        return


if __name__ == "__main__":
    main()
