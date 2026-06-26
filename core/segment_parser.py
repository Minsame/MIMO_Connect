"""Segment parser for tagged MiMo Code output.

MiMo is instructed (via the format prompt injected by the agent adapter)
to tag each output region with [TEXT] / [MD] / [CODE:lang] / [TABLE] tags.
This module turns the tagged stream back into structured segments so the
platform layer can pick the right message type per segment.

The parser is forgiving: untagged text falls back to TEXT, unknown tags
fall back to MD, and tag stripping never raises on malformed input.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List


SEG_TEXT = "text"
SEG_MD = "md"
SEG_CODE = "code"
SEG_TABLE = "table"


@dataclass
class Segment:
    kind: str
    content: str
    lang: str = ""
    meta: dict = field(default_factory=dict)


# Match a tag line standing on its own.
# Examples that match:
#   [TEXT]
#   [MD]
#   [CODE:python]
#   [CODE: bash ]
#   [TABLE]
_TAG_RE = re.compile(
    r"^\s*\[\s*(TEXT|MD|CODE|TABLE)\s*(?::\s*([^\]]*?))?\s*\]\s*$",
    re.IGNORECASE,
)


def _tag_to_kind(tag: str) -> str:
    tag = tag.upper()
    # TEXT is intentionally folded into MD: the platform renders everything
    # (except CODE/TABLE) through the markdown path so markdown in ordinary
    # replies is always parsed instead of shown raw. See issue "取消 text，
    # 统一按 md 解析".
    if tag == "TEXT":
        return SEG_MD
    if tag == "MD":
        return SEG_MD
    if tag == "CODE":
        return SEG_CODE
    if tag == "TABLE":
        return SEG_TABLE
    return SEG_MD


def parse_segments(raw: str) -> List[Segment]:
    """Split raw MiMo output into typed segments by tag lines.

    Untagged content before the first tag is returned as an MD segment so
    any markdown it contains is parsed (TEXT is folded into MD — see
    _tag_to_kind). Adjacent segments of the same kind+lang are merged.
    """
    if not raw:
        return []

    lines = raw.splitlines()
    segments: List[Segment] = []
    current_kind = SEG_MD
    current_lang = ""
    buffer: List[str] = []

    def flush():
        if not buffer:
            return
        content = "\n".join(buffer).strip("\n")
        if not content.strip():
            buffer.clear()
            return
        if segments and segments[-1].kind == current_kind and segments[-1].lang == current_lang:
            segments[-1].content = (segments[-1].content + "\n" + content).strip("\n")
        else:
            segments.append(Segment(kind=current_kind, content=content, lang=current_lang))
        buffer.clear()

    for line in lines:
        m = _TAG_RE.match(line)
        if m:
            flush()
            current_kind = _tag_to_kind(m.group(1))
            current_lang = (m.group(2) or "").strip()
            continue
        buffer.append(line)
    flush()

    # Post-process: strip redundant markdown fences inside CODE segments.
    # MiMo sometimes outputs both a [CODE:lang] tag and the ```lang ... ```
    # markdown wrapper, which causes nested fences when the platform layer
    # re-wraps the body. Detect and remove the inner wrapper.
    for seg in segments:
        if seg.kind == SEG_CODE:
            seg.content, inferred_lang = _strip_inner_fence(seg.content)
            if not seg.lang and inferred_lang:
                seg.lang = inferred_lang

    # Post-process: split code blocks out of MD segments.
    # If an MD segment contains ```-fenced code blocks, extract them as
    # separate CODE segments so the platform can render them properly.
    segments = _split_code_from_md(segments)

    return segments


def _split_code_from_md(segments: List[Segment]) -> List[Segment]:
    """Extract fenced code blocks from MD segments into separate CODE segments."""
    result: List[Segment] = []
    fence_re = re.compile(r"^```(\w*)\s*$")

    for seg in segments:
        if seg.kind != SEG_MD:
            result.append(seg)
            continue

        lines = seg.content.splitlines()
        in_fence = False
        fence_lang = ""
        fence_buffer: List[str] = []
        md_buffer: List[str] = []

        for line in lines:
            m = fence_re.match(line.strip())
            if m and not in_fence:
                # Starting a code block
                in_fence = True
                fence_lang = m.group(1)
                # Flush any preceding MD content
                if md_buffer:
                    md_content = "\n".join(md_buffer).strip()
                    if md_content:
                        result.append(Segment(kind=SEG_MD, content=md_content))
                    md_buffer = []
                continue
            elif m and in_fence and line.strip() == "```":
                # Ending a code block
                in_fence = False
                code_content = "\n".join(fence_buffer)
                if code_content.strip():
                    result.append(Segment(kind=SEG_CODE, content=code_content, lang=fence_lang))
                fence_buffer = []
                fence_lang = ""
                continue

            if in_fence:
                fence_buffer.append(line)
            else:
                md_buffer.append(line)

        # Flush remaining content
        if md_buffer:
            md_content = "\n".join(md_buffer).strip()
            if md_content:
                result.append(Segment(kind=SEG_MD, content=md_content))
        if fence_buffer:
            # Unclosed fence - treat as code anyway
            code_content = "\n".join(fence_buffer)
            if code_content.strip():
                result.append(Segment(kind=SEG_CODE, content=code_content, lang=fence_lang))

    return result


def _strip_inner_fence(body: str) -> tuple[str, str]:
    """If body is wrapped in ```lang\\n...\\n``` , peel one layer.

    Returns (cleaned_body, inferred_lang). inferred_lang is "" if the
    opening fence had no language tag.
    """
    if not body:
        return body, ""
    stripped = body.strip("\n")
    if not stripped.startswith("```"):
        return body, ""
    lines = stripped.splitlines()
    if len(lines) < 2 or not lines[-1].strip().startswith("```"):
        return body, ""
    opening = lines[0].strip()
    inferred_lang = opening[3:].strip()
    inner = "\n".join(lines[1:-1])
    return inner, inferred_lang


def strip_tags(raw: str) -> str:
    """Return the raw text with all tag lines removed.

    Useful for: history persistence, voice synthesis (where the tag
    label should never be spoken), and logging.
    """
    if not raw:
        return raw
    cleaned_lines = [line for line in raw.splitlines() if not _TAG_RE.match(line)]
    return "\n".join(cleaned_lines).strip()


def has_any_tag(raw: str) -> bool:
    """Whether raw contains at least one well-formed tag line.

    Used by the platform layer to decide whether a chunk needs
    LLM-driven re-tagging before being dispatched.
    """
    if not raw:
        return False
    for line in raw.splitlines():
        if _TAG_RE.match(line):
            return True
    return False
