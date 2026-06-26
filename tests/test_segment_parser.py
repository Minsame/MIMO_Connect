"""Test segment parser."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from core.segment_parser import SEG_CODE, SEG_MD, SEG_TEXT, parse_segments, strip_tags


def test_basic():
    raw = "[TEXT]\nHello, world.\n[CODE:python]\ndef f():\n    pass\n[TEXT]\nEnd."
    segs = parse_segments(raw)
    assert len(segs) == 3, f"expected 3 got {len(segs)}: {segs}"
    # TEXT is folded into MD (issue: 取消 text，统一按 md 解析)
    assert segs[0].kind == SEG_MD and segs[0].content == "Hello, world."
    assert segs[1].kind == SEG_CODE and segs[1].lang == "python" and "def f()" in segs[1].content
    assert segs[2].kind == SEG_MD and segs[2].content == "End."
    print("test_basic OK")


def test_untagged_prefix():
    raw = "Some text without tag.\n[MD]\n# Title"
    segs = parse_segments(raw)
    # Untagged prefix is now MD (folded), so it merges with the following MD.
    assert len(segs) == 1
    assert segs[0].kind == SEG_MD
    assert "Some text without tag." in segs[0].content
    assert "# Title" in segs[0].content
    print("test_untagged_prefix OK")


def test_merge_adjacent():
    raw = "[TEXT]\nA\n[TEXT]\nB"
    segs = parse_segments(raw)
    assert len(segs) == 1
    assert segs[0].content == "A\nB"
    print("test_merge_adjacent OK")


def test_strip_tags():
    raw = "[TEXT]\nHello\n[CODE:py]\nx=1\n[TEXT]\nBye"
    out = strip_tags(raw)
    assert "[TEXT]" not in out
    assert "[CODE" not in out
    assert "Hello" in out and "x=1" in out and "Bye" in out
    print("test_strip_tags OK")


def test_empty():
    assert parse_segments("") == []
    assert parse_segments(None or "") == []
    assert strip_tags("") == ""
    print("test_empty OK")


def test_tag_with_spaces():
    raw = "[ CODE :  bash ]\necho hi"
    segs = parse_segments(raw)
    assert len(segs) == 1
    assert segs[0].kind == SEG_CODE
    assert segs[0].lang == "bash"
    print("test_tag_with_spaces OK")


def test_realistic():
    raw = (
        "[TEXT]\n"
        "Hao de, wo lai bang ni shixian.\n"
        "[CODE:python]\n"
        "def hello():\n"
        "    print('hi')\n"
        "[TEXT]\n"
        "Yi shang shi he xin dai ma, ke yi yun xing.\n"
        "[MD]\n"
        "# Title\n"
        "- item 1\n"
        "- **bold**\n"
    )
    segs = parse_segments(raw)
    # TEXT folds into MD; the third (folded TEXT) and fourth (MD) segments are
    # adjacent MD and merge, so we get [MD, CODE, MD].
    kinds = [s.kind for s in segs]
    assert kinds == [SEG_MD, SEG_CODE, SEG_MD], kinds
    print("test_realistic OK")


if __name__ == "__main__":
    test_basic()
    test_untagged_prefix()
    test_merge_adjacent()
    test_strip_tags()
    test_empty()
    test_tag_with_spaces()
    test_realistic()
    print("\nAll segment_parser tests PASSED")
