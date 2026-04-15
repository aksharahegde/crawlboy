from __future__ import annotations

import asyncio
import socket
from pathlib import Path

import httpx
import pytest
from hypothesis import given, strategies as st

from crawlboy import crawler


def test_redact_url_for_logs_removes_credentials_query_and_fragment() -> None:
    redacted = crawler.redact_url_for_logs(
        "https://user:pass@example.com/a/b?token=secret#frag"
    )
    assert redacted == "https://example.com/a/b"


def test_normalize_site_url_strips_userinfo() -> None:
    assert crawler.normalize_site_url("https://user:pass@Example.com:443/x") == (
        "https://example.com:443"
    )


def test_safe_out_path_rejects_path_escape(tmp_path: Path) -> None:
    out = tmp_path / "out"
    out.mkdir()
    with pytest.raises(RuntimeError):
        crawler.safe_out_path(out.resolve(), Path("../outside.txt"))


def test_validate_network_target_blocks_private_ip() -> None:
    with pytest.raises(ValueError):
        crawler.validate_network_target(
            "http://127.0.0.1/sitemap.xml", allow_unsafe_network_targets=False
        )


def test_validate_network_target_allows_override() -> None:
    crawler.validate_network_target(
        "http://127.0.0.1/sitemap.xml", allow_unsafe_network_targets=True
    )


def test_validate_network_target_blocks_resolved_private(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_getaddrinfo(*_a, **_k):
        return [(socket.AF_INET, socket.SOCK_STREAM, 0, "", ("192.168.1.1", 0))]

    monkeypatch.setattr(socket, "getaddrinfo", fake_getaddrinfo)
    with pytest.raises(ValueError):
        crawler.validate_network_target(
            "https://example.com/", allow_unsafe_network_targets=False
        )


def test_collect_urls_from_sitemap_enforces_max_urls(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml = (
        b"<urlset><url><loc>https://example.com/1</loc></url>"
        b"<url><loc>https://example.com/2</loc></url></urlset>"
    )

    async def fake_fetch(*_args, **_kwargs) -> bytes:
        return xml

    monkeypatch.setattr(crawler, "fetch_sitemap_bytes", fake_fetch)
    client = httpx.AsyncClient()
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(
                crawler.collect_urls_from_sitemap(
                    client,
                    "https://example.com/sitemap.xml",
                    max_urls=1,
                )
            )
    finally:
        asyncio.run(client.aclose())


def test_collect_urls_from_sitemap_enforces_max_depth(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    xml = (
        b"<sitemapindex><sitemap><loc>https://example.com/child.xml</loc>"
        b"</sitemap></sitemapindex>"
    )

    async def fake_fetch(*_args, **_kwargs) -> bytes:
        return xml

    monkeypatch.setattr(crawler, "fetch_sitemap_bytes", fake_fetch)
    client = httpx.AsyncClient()
    try:
        with pytest.raises(RuntimeError):
            asyncio.run(
                crawler.collect_urls_from_sitemap(
                    client,
                    "https://example.com/root.xml",
                    max_depth=0,
                )
            )
    finally:
        asyncio.run(client.aclose())


def test_ensure_image_downloaded_enforces_media_file_limit(tmp_path: Path) -> None:
    body = b"x" * 32

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, content=body, headers={"content-type": "image/png"})

    transport = httpx.MockTransport(handler)
    client = httpx.AsyncClient(transport=transport)
    media_dir = tmp_path / "media"
    cache: dict[str, Path] = {}
    try:
        saved, saved_bytes = asyncio.run(
            crawler.ensure_image_downloaded(
                client,
                "https://example.com/a.png",
                "https://example.com/a.png",
                media_dir,
                cache,
                referer="https://example.com/page",
                user_agent="test-agent",
                allow_unsafe_network_targets=False,
                max_media_file_bytes=16,
                max_media_total_remaining_bytes=1024,
            )
        )
        assert saved is None
        assert saved_bytes == 0
    finally:
        asyncio.run(client.aclose())


@given(st.from_regex(r"[a-zA-Z0-9/_-]{1,64}", fullmatch=True))
def test_url_to_relative_md_path_is_safe(segment: str) -> None:
    rel = crawler.url_to_relative_md_path(f"https://example.com/{segment}")
    assert not rel.is_absolute()
    assert ".." not in rel.parts
    assert rel.suffix == ".md"
