from app import config


def test_env_int_default(monkeypatch):
    monkeypatch.delenv("QW_INT", raising=False)
    assert config._env_int("QW_INT", 7) == 7


def test_env_int_parses(monkeypatch):
    monkeypatch.setenv("QW_INT", "42")
    assert config._env_int("QW_INT", 7) == 42


def test_env_int_bad_falls_back(monkeypatch):
    monkeypatch.setenv("QW_INT", "not-a-number")
    assert config._env_int("QW_INT", 7) == 7


def test_env_float_parses(monkeypatch):
    monkeypatch.setenv("QW_FLOAT", "1.5")
    assert config._env_float("QW_FLOAT", 0.0) == 1.5


def test_env_bool_truthy_and_falsy(monkeypatch):
    monkeypatch.setenv("QW_BOOL", "true")
    assert config._env_bool("QW_BOOL", False) is True
    monkeypatch.setenv("QW_BOOL", "0")
    assert config._env_bool("QW_BOOL", True) is False


def test_new_settings_exist_with_defaults():
    assert config.MAX_TOOL_OUTPUT_CHARS == 32000
    assert config.ROUTINE_LOG_MAX_CHARS == 10000
    assert config.MAX_HISTORY == 30
    assert int(config.ASK_TIMEOUT) == 120
