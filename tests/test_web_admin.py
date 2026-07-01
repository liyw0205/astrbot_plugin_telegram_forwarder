import asyncio
import importlib.util
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


class FakeConfig(dict):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.save_config = MagicMock()


class DummyStringSession:
    def __init__(self, *args, **kwargs):
        self.auth_key = None

    @staticmethod
    def save(session):
        return ""


class DummyTelegramClientWrapper:
    @staticmethod
    def clear_cache(session_path):
        return None

    @staticmethod
    def _ensure_compatible_session_schema(session_path):
        return None

    @staticmethod
    async def disconnect_and_clear_cache(session_path):
        return None


def _package(name: str, path: Path | None = None) -> ModuleType:
    module = ModuleType(name)
    module.__path__ = [] if path is None else [str(path)]
    return module


def load_web_admin_module() -> ModuleType:
    root = Path(__file__).resolve().parents[1]
    module_path = root / "core" / "web_admin.py"
    module_name = "astrbot_plugin_telegram_forwarder.core.web_admin"

    stubbed_modules = {
        "telethon": MagicMock(),
        "telethon.errors": SimpleNamespace(
            FloodWaitError=Exception,
            PhoneCodeExpiredError=Exception,
            PhoneCodeInvalidError=Exception,
            SessionPasswordNeededError=Exception,
        ),
        "telethon.sessions": SimpleNamespace(StringSession=DummyStringSession),
        "astrbot": MagicMock(),
        "astrbot.api": SimpleNamespace(logger=MagicMock()),
        "astrbot_plugin_telegram_forwarder": _package(
            "astrbot_plugin_telegram_forwarder", root
        ),
        "astrbot_plugin_telegram_forwarder.core": _package(
            "astrbot_plugin_telegram_forwarder.core", root / "core"
        ),
        "astrbot_plugin_telegram_forwarder.core.client": SimpleNamespace(
            TelegramClientWrapper=DummyTelegramClientWrapper
        ),
    }

    with patch.dict(sys.modules, stubbed_modules):
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        mod = importlib.util.module_from_spec(spec)
        mod.__package__ = "astrbot_plugin_telegram_forwarder.core"
        assert spec.loader is not None
        spec.loader.exec_module(mod)
    return mod


@pytest.fixture
def web_admin_module():
    return load_web_admin_module()


@pytest.fixture
def web_admin(web_admin_module):
    loop = asyncio.new_event_loop()
    plugin = SimpleNamespace(
        config=FakeConfig(
            {
                "web_config": {
                    "enabled": True,
                    "host": "127.0.0.1",
                    "port": 8180,
                    "token": "secret-token",
                }
            }
        ),
        client_wrapper=SimpleNamespace(is_authorized=MagicMock(return_value=False)),
        activate_runtime_after_authorized=AsyncMock(),
    )
    server = web_admin_module.WebAdminServer(plugin, loop)
    server._run_on_loop = lambda coro, timeout=45.0: loop.run_until_complete(coro)
    try:
        yield SimpleNamespace(
            server=server,
            plugin=plugin,
            module=web_admin_module,
            loop=loop,
        )
    finally:
        loop.close()


def test_auth_check_accepts_header_and_body_tokens(web_admin):
    client = web_admin.server.app.test_client()

    x_token = client.post(
        "/api/auth/check",
        headers={"X-Admin-Token": "secret-token"},
    )
    assert x_token.status_code == 200
    assert x_token.get_json()["data"]["authorized"] is True

    bearer = client.post(
        "/api/auth/check",
        headers={"Authorization": "Bearer secret-token"},
    )
    assert bearer.status_code == 200
    assert bearer.get_json()["data"]["authorized"] is True

    body = client.post("/api/auth/check", json={"token": "secret-token"})
    assert body.status_code == 200
    assert body.get_json()["data"]["authorized"] is True


def test_query_token_is_not_accepted(web_admin):
    client = web_admin.server.app.test_client()

    auth_check = client.post("/api/auth/check?token=secret-token")
    assert auth_check.status_code == 200
    assert auth_check.get_json()["data"]["authorized"] is False

    protected = client.get("/api/status?token=secret-token")
    assert protected.status_code == 401
