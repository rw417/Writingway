"""Lightweight Markdown-to-HTML conversion helpers used by LLM output processing.

This module intentionally implements a small, safe subset of Markdown features
that the app needs to render LLM responses as HTML inside the editor UI.

Supported features (basic):
- headings (#, ##, ###)
- bold (**bold** or __bold__)
- italic (*italic* or _italic_)
- bold+italic (***text*** / ___text___)
- inline code (`code`)
- fenced code blocks (```lang\n...```) -> <pre><code class="language-lang">...
- links: [text](url)
- images: ![alt](url)
- unordered lists (-, *, +)
- ordered lists (1., 2., ...)
- blockquotes (lines starting with >)
- horizontal rules (---, ***, ___)

This is not a full CommonMark implementation. It's safe for converting typical
LLM-generated markdown into HTML for display.
"""
from __future__ import annotations

import re
from html import escape
from typing import List


def _escape_html(text: str) -> str:
    """Escape text for safe HTML but keep already intended HTML tags out.

    We call escape() for general text but not for code blocks which are then
    wrapped in <pre><code> and should remain escaped as well.
    """
    return escape(text)


def _legacy_markdown_to_html(text: str) -> str:
    """Convert a markdown-style string to HTML (simple, safe subset).

    Args:
        text: Input string containing markdown-like formatting.

    Returns:
        A HTML string representing the input markdown.
    """
    if not text:
        return ""

    # Normalize line endings
    text = text.replace('\r\n', '\n').replace('\r', '\n')

    # First, handle fenced code blocks ```lang\n...``` -> <pre><code class="language-lang">...</code></pre>
    def _fenced_code_repl(match: re.Match) -> str:
        lang = match.group('lang') or ''
        code = match.group('code') or ''
        code = escape(code)
        class_attr = f' class="language-{escape(lang)}"' if lang else ''
        return f"<pre><code{class_attr}>{code}</code></pre>"

    fenced_re = re.compile(r"^```(?P<lang>[^\n]*)\n(?P<code>.*?)\n```$", re.M | re.S)
    text = fenced_re.sub(_fenced_code_repl, text)

    # Handle horizontal rules
    text = re.sub(r"^([-*_]){3,}\s*$", "<hr/>", text, flags=re.M)

    # Handle headings (#...)
    # Inline formatting helper (must be defined before block-level passes that call it)
    def _inline_format(s: str) -> str:
        # Escape first
        s = _escape_html(s)

        # Images: ![alt](url)
        s = re.sub(r"!\[(?P<alt>.*?)\]\((?P<url>[^)]+)\)", lambda m: f'<img src="{escape(m.group("url"))}" alt="{escape(m.group("alt"))}"/>', s)

        # Links: [text](url)
        s = re.sub(r"\[(?P<text>.*?)\]\((?P<url>[^)]+)\)", lambda m: f'<a href="{escape(m.group("url"))}">{m.group("text")}</a>', s)

        # Bold+italic: ***text*** or ___text___
        s = re.sub(r"(\*\*\*|___)(?P<t>.+?)\1", r"<strong><em>\g<t></em></strong>", s)

        # Bold: **text** or __text__
        s = re.sub(r"(\*\*|__)(?P<t>.+?)\1", r"<strong>\g<t></strong>", s)

        # Italic: *text* or _text_
        s = re.sub(r"(\*|_)(?P<t>.+?)\1", r"<em>\g<t></em>", s)

        # Inline code: `code`
        s = re.sub(r"`([^`]+?)`", lambda m: f'<code>{escape(m.group(1))}</code>', s)

        return s

    def _heading_repl(m: re.Match) -> str:
        level = len(m.group('hashes'))
        content = m.group('text').strip()
        return f"<h{level}>{_inline_format(content)}</h{level}>"

    heading_re = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<text>.+)$", re.M)
    text = heading_re.sub(_heading_repl, text)

    # Blockquotes: lines starting with >
    def _blockquote_processor(lines: List[str]) -> List[str]:
        out: List[str] = []
        buf: List[str] = []
        in_block = False
        for line in lines:
            if line.lstrip().startswith('>'):
                in_block = True
                buf.append(line.lstrip()[1:].lstrip())
            else:
                if in_block:
                    out.append('<blockquote>' + '\n'.join(buf) + '</blockquote>')
                    buf = []
                    in_block = False
                out.append(line)
        if in_block and buf:
            out.append('<blockquote>' + '\n'.join(buf) + '</blockquote>')
        return out

    lines = text.split('\n')
    lines = _blockquote_processor(lines)

    # Lists: we'll do a simple pass to convert consecutive list lines
    def _lists_processor(lines: List[str]) -> List[str]:
        out: List[str] = []
        i = 0
        n = len(lines)
        while i < n:
            line = lines[i]
            ulist_match = re.match(r"^\s*([*+-])\s+(.*)$", line)
            olist_match = re.match(r"^\s*(\d+)\.\s+(.*)$", line)
            if ulist_match:
                items = []
                while i < n and re.match(r"^\s*([*+-])\s+(.*)$", lines[i]):
                    m = re.match(r"^\s*([*+-])\s+(.*)$", lines[i])
                    items.append(_inline_format(m.group(2).strip()))
                    i += 1
                out.append('<ul>')
                out.extend(f'<li>{it}</li>' for it in items)
                out.append('</ul>')
                continue
            elif olist_match:
                items = []
                while i < n and re.match(r"^\s*(\d+)\.\s+(.*)$", lines[i]):
                    m = re.match(r"^\s*(\d+)\.\s+(.*)$", lines[i])
                    items.append(_inline_format(m.group(2).strip()))
                    i += 1
                out.append('<ol>')
                out.extend(f'<li>{it}</li>' for it in items)
                out.append('</ol>')
                continue
            else:
                out.append(line)
                i += 1
        return out

    lines = _lists_processor(lines)

    # Now process inline formatting for remaining lines
    def _process_paragraphs(lines: List[str]) -> str:
        out_lines: List[str] = []
        para_buf: List[str] = []
        for line in lines:
            if line == '':
                if para_buf:
                    out_lines.append('<p>' + '\n'.join(para_buf) + '</p>')
                    para_buf = []
                else:
                    out_lines.append('')
            elif line.startswith('<') and re.match(r"^<(/?)(h\d|ul|ol|li|pre|code|blockquote|hr)", line):
                # Already an HTML block
                if para_buf:
                    out_lines.append('<p>' + '\n'.join(para_buf) + '</p>')
                    para_buf = []
                out_lines.append(line)
            else:
                para_buf.append(_inline_format(line))
        if para_buf:
            out_lines.append('<p>' + '\n'.join(para_buf) + '</p>')
        return '\n'.join(out_lines)

    # ... inline formatting helper moved earlier ...

    html = _process_paragraphs(lines)

    # Trim extra blank lines
    html = re.sub(r"\n{2,}", "\n", html)

    return html


# Prefer the well-maintained 'markdown' package if installed; otherwise
# expose the legacy implementation. The package provides better CommonMark
# compatibility and handles many edge cases our regexes miss.
try:
    from markdown import markdown as _md_package_markdown  # type: ignore
    _HAS_MARKDOWN = True
except Exception:
    _HAS_MARKDOWN = False


if _HAS_MARKDOWN:
    def markdown_to_html(text: str) -> str:
        try:
            # Use common extensions for fenced code, tables and sane lists.
            return _md_package_markdown(
                text or "",
                extensions=["fenced_code", "codehilite", "tables", "sane_lists", "nl2br"],
                output_format="html5",
            )
        except Exception:
            return _legacy_markdown_to_html(text)
else:
    markdown_to_html = _legacy_markdown_to_html


__all__ = ["markdown_to_html"]
