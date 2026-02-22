"""
Markdown → Telegram HTML converter.

Gemini outputs standard markdown. Telegram supports a subset of HTML.
This module converts between the two, handling:
  - **bold** / __bold__  → <b>text</b>
  - *italic* / _italic_  → <i>text</i>
  - ~~strikethrough~~    → <s>text</s>
  - `inline code`        → <code>text</code>
  - ```code blocks```    → <pre>text</pre>
  - [text](url)          → <a href="url">text</a>
  - HTML entity escaping for everything else

Edge cases handled:
  - Nested formatting (bold+italic)
  - Code blocks preserve content literally (no inner parsing)
  - URLs inside code blocks are not converted
  - Unmatched markers are left as-is
"""

import re
from html import escape as html_escape


def md_to_telegram_html(text: str) -> str:
    """Convert standard markdown to Telegram-compatible HTML."""
    if not text:
        return text

    # Step 1: Extract code blocks first to protect them from other transformations
    code_blocks: list[str] = []

    def _save_code_block(m: re.Match) -> str:
        lang = m.group(1) or ""
        code = html_escape(m.group(2).strip())
        # Telegram <pre> supports language via <code class="language-xxx">
        if lang:
            code_blocks.append(f'<pre><code class="language-{lang}">{code}</code></pre>')
        else:
            code_blocks.append(f"<pre>{code}</pre>")
        return f"\x00CODEBLOCK{len(code_blocks) - 1}\x00"

    text = re.sub(r"```(\w*)\n?(.*?)```", _save_code_block, text, flags=re.DOTALL)

    # Step 2: Extract inline code to protect from other transformations
    inline_codes: list[str] = []

    def _save_inline_code(m: re.Match) -> str:
        code = html_escape(m.group(1))
        inline_codes.append(f"<code>{code}</code>")
        return f"\x00INLINECODE{len(inline_codes) - 1}\x00"

    text = re.sub(r"`([^`]+)`", _save_inline_code, text)

    # Step 3: Escape HTML entities in the remaining text
    text = html_escape(text)

    # Step 4: Convert markdown links  [text](url) → <a href="url">text</a>
    text = re.sub(
        r"\[([^\]]+)\]\(([^)]+)\)",
        r'<a href="\2">\1</a>',
        text,
    )

    # Step 5: Convert formatting (order matters — longest markers first)

    # Bold+italic: ***text*** or ___text___
    text = re.sub(r"\*\*\*(.+?)\*\*\*", r"<b><i>\1</i></b>", text)
    text = re.sub(r"___(.+?)___", r"<b><i>\1</i></b>", text)

    # Bold: **text** or __text__
    text = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", text)
    text = re.sub(r"__(.+?)__", r"<b>\1</b>", text)

    # Italic: *text* or _text_ (but not inside words like some_variable_name)
    text = re.sub(r"(?<!\w)\*([^*]+?)\*(?!\w)", r"<i>\1</i>", text)
    text = re.sub(r"(?<!\w)_([^_]+?)_(?!\w)", r"<i>\1</i>", text)

    # Strikethrough: ~~text~~
    text = re.sub(r"~~(.+?)~~", r"<s>\1</s>", text)

    # Step 6: Convert markdown headers to bold (Telegram has no header tags)
    text = re.sub(r"^#{1,6}\s+(.+)$", r"<b>\1</b>", text, flags=re.MULTILINE)

    # Step 7: Convert bullet points (clean up markdown list markers)
    text = re.sub(r"^[\s]*[-*+]\s+", "• ", text, flags=re.MULTILINE)

    # Step 8: Restore code blocks and inline code
    for i, block in enumerate(code_blocks):
        text = text.replace(f"\x00CODEBLOCK{i}\x00", block)

    for i, code in enumerate(inline_codes):
        text = text.replace(f"\x00INLINECODE{i}\x00", code)

    return text
