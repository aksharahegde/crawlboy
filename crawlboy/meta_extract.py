from __future__ import annotations

import logging
import re
from html.parser import HTMLParser
from typing import Any

import yaml

log = logging.getLogger(__name__)

_META_VALUE_MAX = 8 * 1024
_FRONTMATTER_MAX = 64 * 1024
_TRUNC_SUFFIX = "\n... [truncated]"


def truncate_meta_value(s: str, max_len: int = _META_VALUE_MAX) -> str:
    if max_len <= 0:
        return ""
    if len(s) <= max_len:
        return s
    take = max_len - len(_TRUNC_SUFFIX)
    if take <= 0:
        return _TRUNC_SUFFIX.strip()
    return s[:take] + _TRUNC_SUFFIX


def normalize_http_equiv_key(raw: str) -> str:
    return (raw or "").strip().lower().replace(" ", "-")


def _rel_token_set(rel: str) -> set[str]:
    return {t.lower() for t in re.split(r"[\s,]+", rel.strip()) if t}


def _truncate_strings(obj: Any, max_len: int) -> Any:
    if isinstance(obj, dict):
        return {k: _truncate_strings(v, max_len) for k, v in obj.items()}
    if isinstance(obj, str):
        return truncate_meta_value(obj, max_len)
    return obj


class _MetaHtmlParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_title = False
        self._title_buf: list[str] = []
        self.title: str | None = None
        self.canonical: str | None = None
        self.name_map: dict[str, str] = {}
        self.property_map: dict[str, str] = {}
        self.http_equiv_map: dict[str, str] = {}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        ad = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            content = (ad.get("content") or "").strip()
            if not content:
                return
            if "name" in ad:
                self.name_map[ad["name"].strip()] = content
            elif "property" in ad:
                self.property_map[ad["property"].strip()] = content
            elif "http-equiv" in ad:
                key = normalize_http_equiv_key(ad["http-equiv"])
                if key:
                    self.http_equiv_map[key] = content
        elif tag == "link" and self.canonical is None:
            rel = ad.get("rel", "")
            href = (ad.get("href") or "").strip()
            if href and _rel_token_set(rel) & {"canonical"}:
                self.canonical = href
        elif tag == "title":
            self._in_title = True
            self._title_buf = []

    def handle_endtag(self, tag: str) -> None:
        if tag == "title" and self._in_title:
            self._in_title = False
            text = "".join(self._title_buf).strip()
            if text:
                self.title = text
            self._title_buf = []

    def handle_data(self, data: str) -> None:
        if self._in_title:
            self._title_buf.append(data)


def extract_metatags_from_html(html: str) -> dict[str, Any]:
    if not html.strip():
        return {}
    p = _MetaHtmlParser()
    try:
        p.feed(html)
        p.close()
    except Exception as exc:
        log.debug("meta HTML parse incomplete: %s", exc)
    out: dict[str, Any] = {}
    if p.title:
        out["title"] = p.title
    if p.canonical:
        out["canonical"] = p.canonical
    if p.name_map:
        out["name"] = dict(p.name_map)
    if p.property_map:
        out["property"] = dict(p.property_map)
    if p.http_equiv_map:
        out["http_equiv"] = dict(p.http_equiv_map)
    return out


def build_meta_frontmatter_document(source_url: str, html: str) -> dict[str, Any]:
    doc: dict[str, Any] = {"source_url": source_url.strip()}
    tags = extract_metatags_from_html(html)
    if tags:
        doc["metatags"] = tags
    return doc


def format_markdown_with_frontmatter(body: str, document: dict[str, Any]) -> str:
    vm = _META_VALUE_MAX
    while vm >= 256:
        doc_t = _truncate_strings(document, vm)
        block = yaml.safe_dump(
            doc_t,
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        ).rstrip() + "\n"
        if len(block) <= _FRONTMATTER_MAX:
            return f"---\n{block}---\n\n{body}"
        vm //= 2
    log.warning(
        "Meta frontmatter exceeds size limit after truncation; emitting source_url only"
    )
    minimal: dict[str, Any] = {
        "source_url": truncate_meta_value(str(document.get("source_url", "")), 512),
    }
    block = (
        yaml.safe_dump(
            minimal,
            sort_keys=True,
            allow_unicode=True,
            default_flow_style=False,
        ).rstrip()
        + "\n"
    )
    return f"---\n{block}---\n\n{body}"
