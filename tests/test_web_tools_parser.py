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
