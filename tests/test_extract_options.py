import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from core.engine import Engine


class FakeEngine(Engine):
    def __init__(self):
        pass


def test_prose_marker_not_treated_as_options():
    """A report that merely mentions '请选择：' in prose must NOT be parsed
    as an option list (this was the bug that swallowed the final reply)."""
    engine = FakeEngine()
    text = (
        "选项检测靠文本约定（`请选择：` + 编号），不是 CLI 协议级 options 事件。\n"
        "数据结构是 `SessionState.pending_options`。\n"
        "这是一段普通的讲解正文，没有真正的选项列表。"
    )
    before, options = engine._extract_options_from_text(text)
    assert options == []
    assert before == text


def test_real_option_list_is_parsed():
    engine = FakeEngine()
    text = (
        "我可以按两种方式实现，请选择：\n"
        "1. 使用 FastAPI\n"
        "2. 使用 Flask"
    )
    before, options = engine._extract_options_from_text(text)
    assert len(options) == 2
    assert options[0]["label"] == "使用 FastAPI"
    assert options[1]["label"] == "使用 Flask"
    assert before.endswith("我可以按两种方式实现，")


def test_marker_without_enumeration_is_not_options():
    engine = FakeEngine()
    text = "请选择：\n这只是一句没有编号的说明文字。"
    before, options = engine._extract_options_from_text(text)
    assert options == []
    assert before == text
