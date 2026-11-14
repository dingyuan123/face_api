"""将服务端维护的受信任 Markdown 文档转换为安全 HTML。"""

from __future__ import annotations

import html
import re

HEADING_PATTERN = re.compile(r"^(#{1,6})\s+(.+?)\s*$")
UNORDERED_ITEM_PATTERN = re.compile(r"^\s*[-*+]\s+(.+)$")
ORDERED_ITEM_PATTERN = re.compile(r"^\s*\d+[.)]\s+(.+)$")
HORIZONTAL_RULE_PATTERN = re.compile(r"^\s*(?:-{3,}|\*{3,}|_{3,})\s*$")
FENCE_PATTERN = re.compile(r"^\s*```")
INLINE_CODE_PATTERN = re.compile(r"`([^`]+)`")
BOLD_PATTERN = re.compile(r"\*\*(.+?)\*\*")
LINK_PATTERN = re.compile(r"\[([^\]]+)]\(([^)\s]+)\)")


def markdown_to_safe_html(source: str) -> str:
    """解析项目内维护的 Markdown，转义原始 HTML，避免公开页面产生脚本注入。"""
    lines = source.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    rendered: list[str] = []
    index = 0

    while index < len(lines):
        line = lines[index]
        if not line.strip():
            index += 1
            continue

        if FENCE_PATTERN.match(line):
            index += 1
            code_lines: list[str] = []
            while index < len(lines) and not FENCE_PATTERN.match(lines[index]):
                code_lines.append(lines[index])
                index += 1
            index += 1
            rendered.append(f"<pre><code>{html.escape('\n'.join(code_lines))}</code></pre>")
            continue

        heading = HEADING_PATTERN.match(line)
        if heading:
            level = len(heading.group(1))
            rendered.append(f"<h{level}>{_render_inline(heading.group(2))}</h{level}>")
            index += 1
            continue

        if HORIZONTAL_RULE_PATTERN.match(line):
            rendered.append("<hr>")
            index += 1
            continue

        unordered_items: list[str] = []
        while index < len(lines):
            item = UNORDERED_ITEM_PATTERN.match(lines[index])
            if not item:
                break
            unordered_items.append(f"<li>{_render_inline(item.group(1))}</li>")
            index += 1
        if unordered_items:
            rendered.append(f"<ul>{''.join(unordered_items)}</ul>")
            continue

        ordered_items: list[str] = []
        while index < len(lines):
            item = ORDERED_ITEM_PATTERN.match(lines[index])
            if not item:
                break
            ordered_items.append(f"<li>{_render_inline(item.group(1))}</li>")
            index += 1
        if ordered_items:
            rendered.append(f"<ol>{''.join(ordered_items)}</ol>")
            continue

        paragraph_lines: list[str] = []
        while index < len(lines):
            candidate = lines[index]
            if (
                not candidate.strip()
                or HEADING_PATTERN.match(candidate)
                or HORIZONTAL_RULE_PATTERN.match(candidate)
                or FENCE_PATTERN.match(candidate)
                or UNORDERED_ITEM_PATTERN.match(candidate)
                or ORDERED_ITEM_PATTERN.match(candidate)
            ):
                break
            paragraph_lines.append(candidate.strip())
            index += 1
        rendered.append(f"<p>{'<br>'.join(_render_inline(item) for item in paragraph_lines)}</p>")

    return "\n".join(rendered)


def extract_title(source: str, fallback: str) -> str:
    """读取文档首个一级标题作为页面标题。"""
    for line in source.splitlines():
        match = HEADING_PATTERN.match(line)
        if match and len(match.group(1)) == 1:
            return html.escape(match.group(2).strip())
    return html.escape(fallback)


def _render_inline(value: str) -> str:
    """渲染受控的行内 Markdown，同时保持所有原始 HTML 被转义。"""
    escaped = html.escape(value, quote=False)
    escaped = INLINE_CODE_PATTERN.sub(lambda match: f"<code>{match.group(1)}</code>", escaped)
    escaped = BOLD_PATTERN.sub(lambda match: f"<strong>{match.group(1)}</strong>", escaped)

    def render_link(match: re.Match[str]) -> str:
        label = match.group(1)
        raw_url = html.unescape(match.group(2))
        if not raw_url.lower().startswith(("http://", "https://")):
            return match.group(0)
        return f'<a href="{html.escape(raw_url, quote=True)}" rel="noopener noreferrer">{label}</a>'

    return LINK_PATTERN.sub(render_link, escaped)
