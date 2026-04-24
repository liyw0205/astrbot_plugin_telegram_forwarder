import asyncio
import importlib.util
import shutil
import sqlite3
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch


def load_client_module():
    root = Path(__file__).resolve().parents[1]
    module_path = root / "core" / "client.py"
    module_name = "astrbot_plugin_telegram_forwarder.core.client"

    stubbed_modules = {
        "socks": SimpleNamespace(HTTP=1, SOCKS5=2),
        "telethon": SimpleNamespace(TelegramClient=MagicMock()),
        "astrbot": MagicMock(),
        "astrbot.api": SimpleNamespace(
            logger=MagicMock(),
            AstrBotConfig=dict,
        ),
    }

    with patch.dict(sys.modules, stubbed_modules):
        sys.modules.pop(module_name, None)
        spec = importlib.util.spec_from_file_location(module_name, module_path)
        mod = importlib.util.module_from_spec(spec)
        assert spec.loader is not None
        spec.loader.exec_module(mod)
        return mod


def make_legacy_session_db(path: Path):
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE sessions (
            dc_id integer primary key,
            server_address text,
            port integer,
            auth_key blob,
            takeout_id integer,
            tmp_auth_key blob
        )
        """
    )
    conn.execute(
        """
        INSERT INTO sessions
        (dc_id, server_address, port, auth_key, takeout_id, tmp_auth_key)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (5, "149.154.167.51", 443, b"auth-key", 9, b"tmp-key"),
    )
    conn.commit()
    conn.close()


def make_test_dir() -> Path:
    root = Path(__file__).resolve().parents[1] / ".pytest_tmp"
    root.mkdir(exist_ok=True)
    path = root / f"session-schema-{uuid.uuid4().hex}"
    path.mkdir()
    return path


def test_load_client_module_restores_sys_modules_after_stubbing():
    sentinel_socks = object()
    sentinel_telethon = object()
    sentinel_astrbot = object()
    sentinel_api = object()

    with patch.dict(
        sys.modules,
        {
            "socks": sentinel_socks,
            "telethon": sentinel_telethon,
            "astrbot": sentinel_astrbot,
            "astrbot.api": sentinel_api,
        },
    ):
        load_client_module()

        assert sys.modules["socks"] is sentinel_socks
        assert sys.modules["telethon"] is sentinel_telethon
        assert sys.modules["astrbot"] is sentinel_astrbot
        assert sys.modules["astrbot.api"] is sentinel_api


def test_migrate_legacy_session_schema():
    client_module = load_client_module()
    wrapper = client_module.TelegramClientWrapper

    tmp_dir = make_test_dir()
    try:
        session_path = tmp_dir / "user_session"
        session_file = tmp_dir / "user_session.session"
        make_legacy_session_db(session_file)

        wrapper._ensure_compatible_session_schema(str(session_path))

        conn = sqlite3.connect(session_file)
        cols = conn.execute("PRAGMA table_info(sessions)").fetchall()
        row = conn.execute("SELECT * FROM sessions").fetchone()
        conn.close()

        assert [col[1] for col in cols] == [
            "dc_id",
            "server_address",
            "port",
            "auth_key",
            "takeout_id",
        ]
        assert row == (5, "149.154.167.51", 443, b"auth-key", 9)
        assert (tmp_dir / "user_session.session.bak").exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_skip_migration_for_current_schema():
    client_module = load_client_module()
    wrapper = client_module.TelegramClientWrapper

    tmp_dir = make_test_dir()
    try:
        session_path = tmp_dir / "user_session"
        session_file = tmp_dir / "user_session.session"

        conn = sqlite3.connect(session_file)
        conn.execute(
            """
            CREATE TABLE sessions (
                dc_id integer primary key,
                server_address text,
                port integer,
                auth_key blob,
                takeout_id integer
            )
            """
        )
        conn.execute(
            """
            INSERT INTO sessions
            (dc_id, server_address, port, auth_key, takeout_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (2, "149.154.167.50", 443, b"ok", None),
        )
        conn.commit()
        conn.close()

        wrapper._ensure_compatible_session_schema(str(session_path))

        conn = sqlite3.connect(session_file)
        cols = conn.execute("PRAGMA table_info(sessions)").fetchall()
        row = conn.execute("SELECT * FROM sessions").fetchone()
        conn.close()

        assert [col[1] for col in cols] == [
            "dc_id",
            "server_address",
            "port",
            "auth_key",
            "takeout_id",
        ]
        assert row == (2, "149.154.167.50", 443, b"ok", None)
        assert not (tmp_dir / "user_session.session.bak").exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_restore_backup_when_migration_write_fails():
    client_module = load_client_module()
    wrapper = client_module.TelegramClientWrapper

    tmp_dir = make_test_dir()
    try:
        session_path = tmp_dir / "user_session"
        session_file = tmp_dir / "user_session.session"
        make_legacy_session_db(session_file)

        real_connect = client_module.sqlite3.connect
        connect_calls = 0

        class FailingInsertConnection:
            def __init__(self, conn):
                self._conn = conn

            def execute(self, *args, **kwargs):
                return self._conn.execute(*args, **kwargs)

            def executemany(self, sql, params):
                if "INSERT INTO sessions" in sql:
                    raise sqlite3.OperationalError("simulated insert failure")
                return self._conn.executemany(sql, params)

            def commit(self):
                return self._conn.commit()

            def close(self):
                return self._conn.close()

        def connect_with_failing_insert(*args, **kwargs):
            nonlocal connect_calls
            connect_calls += 1
            conn = real_connect(*args, **kwargs)
            if connect_calls == 2:
                return FailingInsertConnection(conn)
            return conn

        with patch.object(client_module.sqlite3, "connect", side_effect=connect_with_failing_insert):
            try:
                wrapper._ensure_compatible_session_schema(str(session_path))
            except sqlite3.OperationalError:
                pass

        conn = sqlite3.connect(session_file)
        cols = conn.execute("PRAGMA table_info(sessions)").fetchall()
        row = conn.execute("SELECT * FROM sessions").fetchone()
        legacy_exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='sessions_legacy'"
        ).fetchone()
        conn.close()

        assert [col[1] for col in cols] == [
            "dc_id",
            "server_address",
            "port",
            "auth_key",
            "takeout_id",
            "tmp_auth_key",
        ]
        assert row == (5, "149.154.167.51", 443, b"auth-key", 9, b"tmp-key")
        assert legacy_exists is None
        assert (tmp_dir / "user_session.session.bak").exists()
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)


def test_clear_cache_closes_cached_session_before_removal():
    client_module = load_client_module()
    session_path = "synthetic/session/user_session"
    cached_client = MagicMock()
    cached_client.session = MagicMock()
    client_module.get_client_cache().clear()
    client_module.get_auth_cache().clear()
    client_module.get_client_cache()[session_path] = cached_client
    client_module.get_auth_cache()[session_path] = True

    client_module.TelegramClientWrapper.clear_cache(session_path)

    cached_client.session.close.assert_called_once_with()
    assert session_path not in client_module.get_client_cache()
    assert session_path not in client_module.get_auth_cache()


def test_disconnect_and_clear_cache_closes_session_even_when_client_looks_disconnected():
    client_module = load_client_module()
    session_path = "synthetic/session/user_session"
    cached_client = MagicMock()
    cached_client.is_connected.return_value = False
    cached_client.disconnect = AsyncMock()
    cached_client.session = MagicMock()
    client_module.get_client_cache().clear()
    client_module.get_auth_cache().clear()
    client_module.get_client_cache()[session_path] = cached_client

    asyncio.run(client_module.TelegramClientWrapper.disconnect_and_clear_cache(session_path))

    cached_client.session.close.assert_called()
    assert session_path not in client_module.get_client_cache()


def test_ensure_connected_rebuilds_once_on_wrong_session_id_then_returns_false_if_still_disconnected():
    client_module = load_client_module()
    wrapper = object.__new__(client_module.TelegramClientWrapper)
    wrapper.config = {"forward_config": {"wrong_session_rebuild_enabled": True}}
    wrapper.plugin_data_dir = "synthetic/session"

    old_client = MagicMock()
    old_client.is_connected.return_value = False
    old_client.connect = AsyncMock(side_effect=RuntimeError("wrong session ID"))

    new_client = MagicMock()
    new_client.is_connected.return_value = False
    new_client.connect = AsyncMock(return_value=None)

    wrapper.client = old_client
    wrapper._session_path = MagicMock(return_value="synthetic/session/user_session")
    wrapper._init_client = MagicMock(side_effect=lambda: setattr(wrapper, "client", new_client))

    with patch.object(
        client_module.TelegramClientWrapper,
        "disconnect_and_clear_cache",
        new=AsyncMock(),
    ) as disconnect_and_clear_cache:
        connected = asyncio.run(wrapper.ensure_connected())

    assert connected is False
    old_client.connect.assert_awaited_once_with()
    disconnect_and_clear_cache.assert_awaited_once_with("synthetic/session/user_session")
    wrapper._init_client.assert_called_once_with()
    new_client.connect.assert_awaited_once_with()


def test_ensure_connected_reraises_wrong_session_error_when_rebuild_disabled():
    client_module = load_client_module()
    wrapper = object.__new__(client_module.TelegramClientWrapper)
    wrapper.config = {"forward_config": {"wrong_session_rebuild_enabled": False}}
    wrapper.plugin_data_dir = "synthetic/session"

    client = MagicMock()
    client.is_connected.return_value = False
    client.connect = AsyncMock(side_effect=RuntimeError("Wrong Session Id"))
    wrapper.client = client
    wrapper._session_path = MagicMock(return_value="synthetic/session/user_session")
    wrapper._init_client = MagicMock()

    with patch.object(
        client_module.TelegramClientWrapper,
        "disconnect_and_clear_cache",
        new=AsyncMock(),
    ) as disconnect_and_clear_cache:
        try:
            asyncio.run(wrapper.ensure_connected())
            assert False, "expected wrong session error to be re-raised"
        except RuntimeError as exc:
            assert "Wrong Session Id" in str(exc)

    disconnect_and_clear_cache.assert_not_awaited()
    wrapper._init_client.assert_not_called()


def test_ensure_connected_returns_false_when_second_connect_fails_after_rebuild():
    client_module = load_client_module()
    wrapper = object.__new__(client_module.TelegramClientWrapper)
    wrapper.config = {"forward_config": {"wrong_session_rebuild_enabled": True}}
    wrapper.plugin_data_dir = "synthetic/session"

    old_client = MagicMock()
    old_client.is_connected.return_value = False
    old_client.connect = AsyncMock(side_effect=RuntimeError("wrong session ID"))

    new_client = MagicMock()
    new_client.is_connected.return_value = False
    new_client.connect = AsyncMock(side_effect=RuntimeError("network still broken"))

    wrapper.client = old_client
    wrapper._session_path = MagicMock(return_value="synthetic/session/user_session")
    wrapper._init_client = MagicMock(side_effect=lambda: setattr(wrapper, "client", new_client))

    with patch.object(
        client_module.TelegramClientWrapper,
        "disconnect_and_clear_cache",
        new=AsyncMock(),
    ) as disconnect_and_clear_cache:
        connected = asyncio.run(wrapper.ensure_connected())

    assert connected is False
    disconnect_and_clear_cache.assert_awaited_once_with("synthetic/session/user_session")
    wrapper._init_client.assert_called_once_with()
    new_client.connect.assert_awaited_once_with()
