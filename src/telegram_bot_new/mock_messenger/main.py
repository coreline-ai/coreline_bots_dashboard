from __future__ import annotations

import argparse
from pathlib import Path

import uvicorn

from telegram_bot_new.mock_messenger.api import create_app
from telegram_bot_new.mock_messenger.store import MockMessengerStore


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Mock Telegram-compatible messenger")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9082)
    parser.add_argument("--db-path", default=".mock_messenger/mock_messenger.db")
    parser.add_argument("--data-dir", default=".mock_messenger")
    parser.add_argument("--allow-get-updates-with-webhook", action="store_true")
    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()

    db_path = Path(args.db_path).expanduser().resolve()
    data_dir = Path(args.data_dir).expanduser().resolve()
    db_path.parent.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    store = MockMessengerStore(db_path=str(db_path), data_dir=str(data_dir))
    app = create_app(
        store=store,
        allow_get_updates_with_webhook=bool(args.allow_get_updates_with_webhook),
    )

    uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
