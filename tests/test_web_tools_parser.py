import os
from unittest.mock import patch


def test_get_credential_found():
    with patch.dict(os.environ, {"CRED_GMAIL_USER": "user@gmail.com"}):
        from app.config import get_credential
        assert get_credential("GMAIL_USER") == "user@gmail.com"


def test_get_credential_case_insensitive():
    with patch.dict(os.environ, {"CRED_MY_KEY": "secret"}):
        from app.config import get_credential
        assert get_credential("my_key") == "secret"


def test_get_credential_missing_returns_empty():
    from app.config import get_credential
    assert get_credential("DOES_NOT_EXIST_XYZ") == ""


def test_parse_web_click_id_selector():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("do the thing [WEB_CLICK:#submit-btn] now")
    assert tool == "web_click"
    assert args["selector"] == "#submit-btn"


def test_parse_web_click_class_selector():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_CLICK:.login-button]")
    assert tool == "web_click"
    assert args["selector"] == ".login-button"


def test_parse_web_type_plain_text():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_TYPE:#email:user@example.com]")
    assert tool == "web_type"
    assert args["selector"] == "#email"
    assert args["text"] == "user@example.com"


def test_parse_web_type_credential_reference():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_TYPE:#password:$CRED_GMAIL_PASS]")
    assert tool == "web_type"
    assert args["selector"] == "#password"
    assert args["text"] == "$CRED_GMAIL_PASS"


def test_parse_web_wait():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_WAIT:.dashboard-loaded]")
    assert tool == "web_wait"
    assert args["selector"] == ".dashboard-loaded"


def test_parse_web_get_text():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_GET_TEXT]")
    assert tool == "web_get_text"
    assert args == {}


def test_parse_web_extract_selector_only():
    from app.agents.tools import parse_tool_call
    tool, args = parse_tool_call("[WEB_EXTRACT:.result-table]")
    assert tool == "web_extract"
    assert args["selector"] == ".result-table"
