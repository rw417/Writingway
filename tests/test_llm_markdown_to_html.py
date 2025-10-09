import textwrap

from util.llm_markdown_to_html import markdown_to_html


def test_heading_and_paragraphs():
    md = """
# Title

This is a paragraph.
"""
    html = markdown_to_html(md)
    assert '<h1>Title</h1>' in html
    assert '<p>This is a paragraph.' in html


def test_bold_italic_and_links():
    md = "This is **bold** and *italic* and a [link](https://example.com)."
    html = markdown_to_html(md)
    assert '<strong>bold</strong>' in html
    assert '<em>italic</em>' in html
    assert '<a href="https://example.com">link</a>' in html


def test_code_blocks_and_inline_code():
    md = textwrap.dedent("""
    Here is some code:

    ```python
    def f(x):
        return x*2
    ```

    And inline `x + 1` in text.
    """)
    html = markdown_to_html(md)
    assert '<pre><code class="language-python">' in html
    assert '&lt;=' not in html  # ensure code is escaped but present
    assert '<code>x + 1</code>' in html


def test_lists_and_images_blockquote_hr():
    md = textwrap.dedent("""
    - item one
    - item two

    1. first
    2. second

    > A quote line

    ![alt text](https://example.com/img.png)

    ---
    """)
    html = markdown_to_html(md)
    assert '<ul>' in html and '<li>item one</li>' in html
    assert '<ol>' in html and '<li>first</li>' in html
    assert '<blockquote>' in html and 'A quote line' in html
    assert '<img src="https://example.com/img.png"' in html
    assert '<hr' in html
