from telegram_bot_new.mock_messenger.routes.diagnostics import register_diagnostics_routes
from telegram_bot_new.mock_messenger.routes.mock_telegram import register_mock_telegram_routes
from telegram_bot_new.mock_messenger.routes.orchestration import register_orchestration_routes
from telegram_bot_new.mock_messenger.routes.ui import register_ui_routes

__all__ = [
    "register_diagnostics_routes",
    "register_mock_telegram_routes",
    "register_orchestration_routes",
    "register_ui_routes",
]
