"""测试 conftest — 通过拦截 import 直接加载 qq.py 避免相对导入问题。"""
import builtins
import importlib.util
import os
import sys
from unittest.mock import MagicMock

import pytest

# ─── Mock qq.py 的所有顶层 import 依赖 ───

# telethon
mock_telethon_types = MagicMock()
sys.modules["telethon"] = MagicMock()
sys.modules["telethon.tl"] = MagicMock()
sys.modules["telethon.tl.types"] = mock_telethon_types

# astrbot 模块树
mock_logger = MagicMock()
mock_star = MagicMock()
mock_star.Context = type("Context", (), {})
mock_star.Star = type("Star", (), {"__init__": lambda self, *a, **kw: None})


def _make_comp(name):
    """创建一个模拟的 AstrBot 消息组件类。"""

    def _init(self, *args, **kwargs):
        if name == "MessageChain":
            initial = list(args[0]) if args else []
            self.chain = initial
            return
        if name == "Plain" and args:
            self.text = args[0]
        if name in {"Record", "Image", "Video", "File", "Node", "Nodes"} and args:
            self.value = args[0]
        for key, value in kwargs.items():
            setattr(self, key, value)

    cls = type(name, (), {
        "__init__": _init,
        "fromFileSystem": classmethod(lambda cls2, p: cls2(p)),
    })
    return cls


sys.modules["astrbot"] = MagicMock()
sys.modules["astrbot.api"] = MagicMock(logger=mock_logger, AstrBotConfig=dict, star=mock_star)
sys.modules["astrbot.api.star"] = mock_star
sys.modules["astrbot.api.event"] = MagicMock(MessageChain=_make_comp("MessageChain"))
sys.modules["astrbot.api.message_components"] = MagicMock(
    **{n: _make_comp(n) for n in ["Plain", "Image", "Record", "Video", "File", "Node", "Nodes"]}
)

# astrbot.core.utils.path_util
sys.modules["astrbot.core"] = MagicMock()
sys.modules["astrbot.core.utils"] = MagicMock()
mock_path_util = MagicMock()
mock_path_util.path_Mapping = None
sys.modules["astrbot.core.utils.path_util"] = mock_path_util

# ─── 模拟相对导入目标的模块 ───

mock_text_tools = MagicMock()
mock_text_tools.clean_telegram_text = lambda text, **kw: text
mock_text_tools.is_numeric_channel_id = lambda s: str(s).lstrip("-").isdigit()
mock_text_tools.to_telethon_entity = lambda s: int(s) if str(s).lstrip("-").isdigit() else s

mock_downloader = MagicMock()
mock_downloader.MediaDownloader = type("MediaDownloader", (), {})

# 注册为 qq.py 相对导入能解析到的包路径
_pkg = "astrbot_plugin_telegram_forwarder"
sys.modules[_pkg] = MagicMock()
sys.modules[f"{_pkg}.core"] = MagicMock()
sys.modules[f"{_pkg}.core.senders"] = MagicMock()
sys.modules[f"{_pkg}.core.senders.qq"] = MagicMock()
sys.modules[f"{_pkg}.common"] = MagicMock()
sys.modules[f"{_pkg}.common.text_tools"] = mock_text_tools
sys.modules[f"{_pkg}.core.downloader"] = mock_downloader

# ─── qq.py 源文件路径 ───

_qq_path = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "core", "senders", "qq.py",
)

# 记录真实 import，以便在 patch 内回调
_real_import = builtins.__import__


def _patched_import(name, globals=None, locals=None, fromlist=(), level=0):
    """拦截相对导入，将 ...common.text_tools 和 ..downloader 重定向到 mock 模块。"""
    if level > 0 and globals is not None:
        # 相对导入：根据 level 计算绝对包名
        package = globals.get("__package__", "") or ""
        if level >= 2 and package:
            parts = package.rsplit(".", level - 1)
            base = parts[0] if len(parts) > 1 else package
        else:
            base = package

        # 尝试拼出目标绝对名
        if fromlist:
            # from ...common.text_tools import X  → name 为空, fromlist 非空
            resolved = name  # 相对导入时 name 可能为空
            if not resolved:
                # 根据层级往上走
                pkg_parts = package.split(".") if package else []
                # level=3 表示往上3层
                if len(pkg_parts) >= level:
                    base_parts = pkg_parts[: len(pkg_parts) - level + 1]
                else:
                    base_parts = []
                # 但 fromlist 包含的模块名需要拼回去
                # 这种情况交给真实 import（让 __package__ 生效）
                pass

        # 对于我们的 mock 包，直接重定向
        if "common.text_tools" in (name or "") or "text_tools" in (fromlist or []):
            return mock_text_tools
        if "downloader" in (name or "") or "downloader" in (fromlist or []):
            return mock_downloader

    return _real_import(name, globals, locals, fromlist, level)


def load_qq_module():
    """加载 qq.py 为独立模块（绕过相对导入）。"""
    import types

    spec = importlib.util.spec_from_file_location(
        "astrbot_plugin_telegram_forwarder.core.senders.qq",
        _qq_path,
        submodule_search_locations=[],
    )
    mod = importlib.util.module_from_spec(spec)
    # 设置 __package__ 让相对导入有基础路径
    mod.__package__ = "astrbot_plugin_telegram_forwarder.core.senders"

    # 拦截 import
    builtins.__import__ = _patched_import
    try:
        spec.loader.exec_module(mod)
    finally:
        builtins.__import__ = _real_import

    return mod


@pytest.fixture
def qq_module():
    return load_qq_module()


@pytest.fixture
def sender(qq_module):
    return qq_module.QQSender(context=MagicMock(), config={}, downloader=MagicMock())
