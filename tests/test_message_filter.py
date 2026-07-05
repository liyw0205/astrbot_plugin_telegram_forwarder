"""MessageFilter 过滤逻辑单元测试。"""

import importlib.util
from pathlib import Path
from types import SimpleNamespace


def load_filter_module():
    """以隔离模块形式加载 message_filter.py（astrbot/telethon 由 conftest 全局 mock）。"""
    path = Path(__file__).resolve().parents[1] / "core" / "filters" / "message_filter.py"
    spec = importlib.util.spec_from_file_location("test_message_filter_module", path)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def _msg(text):
    """构造一个仅带 .text 属性的轻量 Message 替身。"""
    return SimpleNamespace(text=text)


class TestFilterMessagesShortCircuit:
    def test_no_forward_config_returns_all(self):
        m = load_filter_module()
        f = m.MessageFilter({})
        msgs = [("ch", _msg("hello")), ("ch", _msg("world"))]
        assert f.filter_messages(msgs) == msgs

    def test_empty_rules_returns_all(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": [], "filter_regex": ""}})
        msgs = [("ch", _msg("hello"))]
        assert f.filter_messages(msgs) == msgs


class TestKeywordFilter:
    def test_keyword_hit_drops_message(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": ["spam"]}})
        result = f.filter_messages(
            [("ch", _msg("this is spam")), ("ch", _msg("ok"))]
        )
        assert len(result) == 1
        assert result[0][1].text == "ok"

    def test_keyword_case_insensitive(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": ["SPAM"]}})
        assert f.filter_messages([("ch", _msg("This is Spam"))]) == []

    def test_multiple_keywords_any_match(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": ["foo", "bar"]}})
        result = f.filter_messages(
            [
                ("ch", _msg("has foo")),
                ("ch", _msg("has bar")),
                ("ch", _msg("none")),
            ]
        )
        assert len(result) == 1
        assert result[0][1].text == "none"

    def test_none_text_kept(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": ["x"]}})
        # msg.text 为 None 时 (None or "").lower() == ""，不命中关键词，原样保留
        result = f.filter_messages([("ch", _msg(None))])
        assert len(result) == 1


class TestRegexFilter:
    def test_regex_hit_drops_message(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_regex": r"\b\d{4}\b"}})
        assert f.filter_messages([("ch", _msg("code 1234"))]) == []
        assert len(f.filter_messages([("ch", _msg("no digits"))])) == 1

    def test_invalid_regex_does_not_raise(self):
        m = load_filter_module()
        # 非法正则被 try/except 捕获并 logger.error，不抛出，消息原样保留
        f = m.MessageFilter({"forward_config": {"filter_regex": "((("}})
        result = f.filter_messages([("ch", _msg("hello"))])
        assert len(result) == 1

    def test_regex_is_case_sensitive(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_regex": "ERROR"}})
        assert f.filter_messages([("ch", _msg("error lowercase"))]) == [
            ("ch", _msg("error lowercase"))
        ]
        assert f.filter_messages([("ch", _msg("ERROR upper"))]) == []


class TestLoggerCallback:
    def test_logger_func_called_on_keyword_drop(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_keywords": ["bad"]}})
        logs = []
        f.filter_messages([("ch", _msg("bad word"))], logger_func=logs.append)
        assert any("Filtered by keyword" in s for s in logs)

    def test_logger_func_called_on_regex_drop(self):
        m = load_filter_module()
        f = m.MessageFilter({"forward_config": {"filter_regex": "drop"}})
        logs = []
        f.filter_messages([("ch", _msg("please drop me"))], logger_func=logs.append)
        assert any("Filtered by regex" in s for s in logs)


class TestCombinedRules:
    def test_keyword_and_regex_both_apply(self):
        m = load_filter_module()
        f = m.MessageFilter(
            {
                "forward_config": {
                    "filter_keywords": ["ads"],
                    "filter_regex": r"\b\d{6}\b",
                }
            }
        )
        result = f.filter_messages(
            [
                ("ch", _msg("buy now ads")),  # keyword hit
                ("ch", _msg("code 123456")),  # regex hit
                ("ch", _msg("clean message")),
            ]
        )
        assert len(result) == 1
        assert result[0][1].text == "clean message"
