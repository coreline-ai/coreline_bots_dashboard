from __future__ import annotations

from pathlib import Path

from telegram_bot_new.settings import GlobalSettings
from telegram_bot_new.supervisor import _load_desired_specs


def _settings() -> GlobalSettings:
    return GlobalSettings.model_validate({"DATABASE_URL": "postgresql+asyncpg://localhost/mock"})


def test_load_desired_specs_allows_empty_bots(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text("bots: []\n", encoding="utf-8")

    specs = _load_desired_specs(
        config_path=config,
        global_settings=_settings(),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
        gateway_host="127.0.0.1",
        gateway_port=4312,
    )
    assert specs == {}


def test_load_desired_specs_builds_embedded_and_gateway_specs(tmp_path: Path) -> None:
    config = tmp_path / "bots.yaml"
    config.write_text(
        "\n".join(
            [
                "bots:",
                "  - bot_id: bot-a",
                "    name: Bot A",
                "    mode: embedded",
                "    telegram_token: mock_token_1",
                "  - bot_id: bot-b",
                "    name: Bot B",
                "    mode: embedded",
                "    telegram_token: mock_token_2",
                "  - bot_id: bot-c",
                "    name: Bot C",
                "    mode: gateway",
                "    telegram_token: mock_token_3",
            ]
        ),
        encoding="utf-8",
    )

    specs = _load_desired_specs(
        config_path=config,
        global_settings=_settings(),
        embedded_host="127.0.0.1",
        embedded_base_port=8600,
        gateway_host="127.0.0.1",
        gateway_port=4312,
    )
    assert specs is not None
    assert "bot:bot-a:embedded" in specs
    assert "bot:bot-b:embedded" in specs
    assert "gateway" in specs
    assert "--embedded-port" in specs["bot:bot-a:embedded"].command
    assert "8600" in specs["bot:bot-a:embedded"].command
    assert "8601" in specs["bot:bot-b:embedded"].command
