from __future__ import annotations

from crawlboy.meta_extract import (
    build_meta_frontmatter_document,
    extract_metatags_from_html,
    format_markdown_with_frontmatter,
    normalize_http_equiv_key,
)


def test_normalize_http_equiv_key() -> None:
    assert normalize_http_equiv_key("Content-Type") == "content-type"
    assert normalize_http_equiv_key("Content Type") == "content-type"


def test_extract_metatags_from_html_collects_title_meta_and_canonical() -> None:
    html = """<!doctype html><html><head>
<title>Hello</title>
<meta name="description" content="Desc here">
<meta property="og:title" content="OG Title">
<meta http-equiv="content-type" content="text/html; charset=utf-8">
<link rel="canonical" href="https://ex.com/a">
</head><body></body></html>"""
    d = extract_metatags_from_html(html)
    assert d["title"] == "Hello"
    assert d["canonical"] == "https://ex.com/a"
    assert d["name"]["description"] == "Desc here"
    assert d["property"]["og:title"] == "OG Title"
    assert d["http_equiv"]["content-type"] == "text/html; charset=utf-8"


def test_extract_metatags_duplicate_name_last_wins() -> None:
    html = '<meta name="x" content="first"><meta name="x" content="second">'
    d = extract_metatags_from_html(html)
    assert d["name"]["x"] == "second"


def test_extract_skips_meta_without_content() -> None:
    html = '<meta name="empty" content="">'
    d = extract_metatags_from_html(html)
    assert "name" not in d


def test_build_meta_frontmatter_document_empty_html() -> None:
    doc = build_meta_frontmatter_document("https://ex.com/page", "")
    assert doc == {"source_url": "https://ex.com/page"}
    assert "metatags" not in doc


def test_format_markdown_with_frontmatter_shape() -> None:
    html = '<title>T</title><meta name="d" content="D">'
    doc = build_meta_frontmatter_document("https://ex.com/", html)
    body = "# Hi\n"
    out = format_markdown_with_frontmatter(body, doc)
    assert out.startswith("---\n")
    assert "\n---\n\n" in out
    assert out.endswith(body)
    assert "source_url:" in out
    assert "metatags:" in out


def test_format_markdown_falls_back_to_source_url_when_oversized() -> None:
    pairs = "".join(
        f'<meta name="n{i}" content="{"x" * 200}">' for i in range(500)
    )
    html = f"<head>{pairs}</head>"
    doc = build_meta_frontmatter_document("https://x.com/", html)
    out = format_markdown_with_frontmatter("tail", doc)
    assert out.startswith("---\n")
    assert out.endswith("tail")
    assert "source_url:" in out
    assert "metatags:" not in out
