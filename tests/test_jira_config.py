# tests/test_jira_config.py
import os
from unittest.mock import patch


def test_jira_config_reads_env_vars():
    with patch.dict(os.environ, {
        "JIRA_URL":   "https://test.atlassian.net",
        "JIRA_EMAIL": "test@example.com",
        "JIRA_TOKEN": "secret-token",
    }):
        import importlib
        import app.config as cfg
        importlib.reload(cfg)
        assert cfg.JIRA_URL   == "https://test.atlassian.net"
        assert cfg.JIRA_EMAIL == "test@example.com"
        assert cfg.JIRA_TOKEN == "secret-token"


def test_jira_config_defaults_to_empty():
    clean_env = {k: v for k, v in os.environ.items()
                 if k not in ("JIRA_URL", "JIRA_EMAIL", "JIRA_TOKEN")}
    with patch.dict(os.environ, clean_env, clear=True):
        import importlib
        import app.config as cfg
        importlib.reload(cfg)
        assert cfg.JIRA_URL   == ""
        assert cfg.JIRA_EMAIL == ""
        assert cfg.JIRA_TOKEN == ""
