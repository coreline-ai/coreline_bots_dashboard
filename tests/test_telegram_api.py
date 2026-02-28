from telegram_bot_new.telegram.api import extract_chat_id, parse_incoming_update


def test_extract_chat_id_from_message_and_callback() -> None:
    payload_message = {
        "update_id": 1,
        "message": {"chat": {"id": 100}, "from": {"id": 10}, "text": "hello"},
    }
    payload_callback = {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "from": {"id": 10},
            "message": {"chat": {"id": 200}, "message_id": 3},
        },
    }

    assert extract_chat_id(payload_message) == "100"
    assert extract_chat_id(payload_callback) == "200"


def test_parse_incoming_update_message() -> None:
    payload = {
        "update_id": 1,
        "message": {
            "chat": {"id": 100},
            "from": {"id": 10},
            "message_id": 99,
            "text": "hi",
        },
    }

    parsed = parse_incoming_update(payload)

    assert parsed is not None
    assert parsed.update_id == 1
    assert parsed.chat_id == 100
    assert parsed.user_id == 10
    assert parsed.text == "hi"


def test_parse_incoming_update_callback() -> None:
    payload = {
        "update_id": 2,
        "callback_query": {
            "id": "cb-1",
            "data": "stop_run",
            "from": {"id": 10},
            "message": {"chat": {"id": 100}, "message_id": 9},
        },
    }

    parsed = parse_incoming_update(payload)

    assert parsed is not None
    assert parsed.callback_query_id == "cb-1"
    assert parsed.callback_data == "stop_run"
    assert parsed.chat_id == 100
