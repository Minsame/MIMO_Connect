"""引导草稿持久化层测试（断点续填能力的基础）。"""

from pathlib import Path

from core import config_io


def test_draft_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "draft.json"
    assert config_io.read_draft(p) == {}
    config_io.write_draft({"llm_provider": "deepseek", "llm_api_key": "sk-1"}, p)
    assert config_io.read_draft(p) == {"llm_provider": "deepseek", "llm_api_key": "sk-1"}


def test_draft_merges_and_skips_empty(tmp_path: Path) -> None:
    p = tmp_path / "draft.json"
    config_io.write_draft({"llm_provider": "deepseek", "llm_api_key": "sk-1"}, p)
    # 空值不应覆盖已有值，新键应合并进来。
    config_io.write_draft({"llm_api_key": "", "platform": "feishu"}, p)
    data = config_io.read_draft(p)
    assert data["llm_api_key"] == "sk-1"
    assert data["platform"] == "feishu"


def test_draft_clear(tmp_path: Path) -> None:
    p = tmp_path / "draft.json"
    config_io.write_draft({"x": "1"}, p)
    config_io.clear_draft(p)
    assert config_io.read_draft(p) == {}
    # 重复清除不报错。
    config_io.clear_draft(p)


def test_draft_corrupt_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "draft.json"
    p.write_text("{ not valid json", encoding="utf-8")
    assert config_io.read_draft(p) == {}
