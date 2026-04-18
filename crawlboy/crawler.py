#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import gzip
import hashlib
import ipaddress
import json
import logging
import os
import re
import socket
import sys
import time
from defusedxml import ElementTree as ET
from pathlib import Path
from typing import Iterable
from urllib.parse import urldefrag, urlparse, urljoin, urlunparse

import httpx
from crawl4ai import AsyncWebCrawler, BrowserConfig, CacheMode, CrawlerRunConfig

from crawlboy.meta_extract import (
    build_meta_frontmatter_document,
    format_markdown_with_frontmatter,
)

log = logging.getLogger(__name__)

DEFAULT_MAX_SITEMAP_BYTES = 5_000_000
DEFAULT_MAX_SITEMAP_URLS = 50_000
DEFAULT_MAX_SITEMAP_DEPTH = 32
DEFAULT_MAX_MEDIA_FILE_BYTES = 10_000_000
DEFAULT_MAX_MEDIA_TOTAL_BYTES = 250_000_000


def _local_tag(tag: str) -> str:
    if "}" in tag:
        return tag.rsplit("}", 1)[-1]
    return tag


def _decode_sitemap_body(content: bytes, url: str) -> bytes:
    if url.endswith(".gz") or content[:2] == b"\x1f\x8b":
        return gzip.decompress(content)
    return content


def _host_is_denied_ip(host: str) -> bool:
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        return False
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


def _resolved_ips_denied(host: str) -> bool:
    try:
        infos = socket.getaddrinfo(host, None, proto=socket.IPPROTO_TCP)
    except socket.gaierror:
        return True
    seen: set[str] = set()
    for info in infos:
        addr = info[4][0]
        if addr in seen:
            continue
        seen.add(addr)
        try:
            ip = ipaddress.ip_address(addr)
        except ValueError:
            continue
        if (
            ip.is_private
            or ip.is_loopback
            or ip.is_link_local
            or ip.is_multicast
            or ip.is_reserved
            or ip.is_unspecified
        ):
            return True
    return False


def validate_network_target(url: str, *, allow_unsafe_network_targets: bool) -> None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"}:
        raise ValueError(f"Only http/https URLs are allowed: {url!r}")
    host = parsed.hostname
    if not host:
        raise ValueError(f"URL has no hostname: {url!r}")
    if allow_unsafe_network_targets:
        return
    if _host_is_denied_ip(host) or _resolved_ips_denied(host):
        raise ValueError(f"Blocked unsafe network target: {url!r}")


async def fetch_sitemap_bytes(
    client: httpx.AsyncClient,
    url: str,
    *,
    allow_unsafe_network_targets: bool,
    max_sitemap_bytes: int,
) -> bytes:
    validate_network_target(url, allow_unsafe_network_targets=allow_unsafe_network_targets)
    response = await client.get(url, follow_redirects=True)
    response.raise_for_status()
    content_length = response.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_sitemap_bytes:
                raise RuntimeError(
                    f"Sitemap too large by content-length ({content_length} > {max_sitemap_bytes}) for {url!r}"
                )
        except ValueError:
            pass
    decoded = _decode_sitemap_body(response.content, str(response.url))
    if len(decoded) > max_sitemap_bytes:
        raise RuntimeError(
            f"Sitemap too large after decode ({len(decoded)} > {max_sitemap_bytes}) for {url!r}"
        )
    return decoded


def _parse_root(xml_bytes: bytes) -> ET.Element:
    return ET.fromstring(xml_bytes)


async def collect_urls_from_sitemap(
    client: httpx.AsyncClient,
    sitemap_url: str,
    *,
    allow_unsafe_network_targets: bool = False,
    max_depth: int = DEFAULT_MAX_SITEMAP_DEPTH,
    max_urls: int = DEFAULT_MAX_SITEMAP_URLS,
    max_sitemap_bytes: int = DEFAULT_MAX_SITEMAP_BYTES,
    _depth: int = 0,
) -> list[str]:
    if _depth > max_depth:
        raise RuntimeError(f"Sitemap nesting exceeded max_depth={max_depth}")

    log.debug(
        "fetch_sitemap depth=%d url=%s",
        _depth,
        redact_url_for_logs(sitemap_url),
    )
    xml_bytes = await fetch_sitemap_bytes(
        client,
        sitemap_url,
        allow_unsafe_network_targets=allow_unsafe_network_targets,
        max_sitemap_bytes=max_sitemap_bytes,
    )
    root = _parse_root(xml_bytes)
    root_name = _local_tag(root.tag)

    if root_name == "sitemapindex":
        out: list[str] = []
        child_locs = 0
        for sm in root:
            if _local_tag(sm.tag) != "sitemap":
                continue
            loc_text = None
            for child in sm:
                if _local_tag(child.tag) == "loc" and child.text and child.text.strip():
                    loc_text = child.text.strip()
                    break
            if not loc_text:
                continue
            child_locs += 1
            resolved = urljoin(sitemap_url, loc_text)
            log.debug(
                "sitemap_index depth=%d child_sitemap=%s",
                _depth,
                redact_url_for_logs(resolved),
            )
            out.extend(
                await collect_urls_from_sitemap(
                    client,
                    resolved,
                    allow_unsafe_network_targets=allow_unsafe_network_targets,
                    max_depth=max_depth,
                    max_urls=max_urls,
                    max_sitemap_bytes=max_sitemap_bytes,
                    _depth=_depth + 1,
                )
            )
            if len(out) > max_urls:
                raise RuntimeError(
                    f"Sitemap URL count exceeded max_sitemap_urls={max_urls}"
                )
        log.debug(
            "sitemap_index depth=%d child_sitemaps=%d merged_page_urls=%d",
            _depth,
            child_locs,
            len(out),
        )
        return out

    if root_name == "urlset":
        urls: list[str] = []
        for uel in root:
            if _local_tag(uel.tag) != "url":
                continue
            for child in uel:
                if _local_tag(child.tag) == "loc" and child.text and child.text.strip():
                    urls.append(child.text.strip())
                    if len(urls) > max_urls:
                        raise RuntimeError(
                            f"Sitemap URL count exceeded max_sitemap_urls={max_urls}"
                        )
                    break
        log.debug(
            "urlset depth=%d sitemap_url=%s loc_count=%d",
            _depth,
            redact_url_for_logs(sitemap_url),
            len(urls),
        )
        return urls

    raise ValueError(
        f"Unsupported sitemap root element: {root_name!r} in {redact_url_for_logs(sitemap_url)!r}"
    )


def dedupe_preserve_order(urls: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for u in urls:
        if u in seen:
            continue
        seen.add(u)
        out.append(u)
    return out


FALLBACK_SITEMAP_PATHS = (
    "/sitemap.xml",
    "/sitemap_index.xml",
    "/sitemap-index.xml",
    "/wp-sitemap.xml",
)


def normalize_site_url(url: str) -> str:
    u = url.strip().rstrip("/")
    if not u:
        raise ValueError("Empty --site-url")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parsed = urlparse(u)
    if not parsed.hostname:
        raise ValueError(f"Invalid --site-url: {url!r}")
    host = parsed.hostname.lower()
    if parsed.port:
        netloc = f"{host}:{parsed.port}"
    else:
        netloc = host
    return f"{parsed.scheme}://{netloc}"


def redact_url_for_logs(url: str) -> str:
    try:
        parsed = urlparse(url)
    except Exception:
        return url
    netloc = parsed.hostname or ""
    if parsed.port:
        netloc = f"{netloc}:{parsed.port}"
    if not parsed.scheme:
        return url
    return urlunparse((parsed.scheme, netloc, parsed.path, "", "", ""))


def safe_out_path(out_dir: Path, relative_path: Path) -> Path:
    target = (out_dir / relative_path).resolve()
    if not target.is_relative_to(out_dir):
        raise RuntimeError(f"Refusing to write outside out_dir: {relative_path!r}")
    return target


def parse_robots_sitemap_lines(text: str, origin: str) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        if line.lower().startswith("sitemap:"):
            loc = line.split(":", 1)[1].strip()
            if not loc:
                continue
            resolved = urldefrag(urljoin(origin + "/", loc))[0]
            if resolved not in seen:
                seen.add(resolved)
                out.append(resolved)
    return out


async def url_looks_like_sitemap(
    client: httpx.AsyncClient,
    url: str,
    *,
    allow_unsafe_network_targets: bool,
    max_sitemap_bytes: int,
) -> bool:
    try:
        validate_network_target(
            url, allow_unsafe_network_targets=allow_unsafe_network_targets
        )
        response = await client.get(
            url, follow_redirects=True, timeout=httpx.Timeout(60.0)
        )
        if response.status_code != 200:
            return False
        body = _decode_sitemap_body(response.content, str(response.url))
        if len(body) > max_sitemap_bytes:
            return False
        root = ET.fromstring(body)
        return _local_tag(root.tag) in ("urlset", "sitemapindex")
    except Exception:
        return False


async def discover_sitemap_entry_urls(
    client: httpx.AsyncClient,
    site_url: str,
    *,
    allow_unsafe_network_targets: bool,
    max_sitemap_bytes: int,
) -> list[str]:
    origin = normalize_site_url(site_url)
    robots_url = urljoin(origin + "/", "robots.txt")
    try:
        validate_network_target(
            robots_url, allow_unsafe_network_targets=allow_unsafe_network_targets
        )
        response = await client.get(
            robots_url, follow_redirects=True, timeout=httpx.Timeout(60.0)
        )
        if response.status_code == 200:
            found = parse_robots_sitemap_lines(response.text, origin)
            if found:
                return found
    except Exception as exc:
        log.debug("robots.txt fetch failed for %s: %s", redact_url_for_logs(robots_url), exc)

    for path in FALLBACK_SITEMAP_PATHS:
        candidate = urljoin(origin + "/", path.lstrip("/"))
        if await url_looks_like_sitemap(
            client,
            candidate,
            allow_unsafe_network_targets=allow_unsafe_network_targets,
            max_sitemap_bytes=max_sitemap_bytes,
        ):
            return [candidate]
    return []


async def collect_page_urls_for_site(
    client: httpx.AsyncClient,
    site_url: str,
    *,
    allow_unsafe_network_targets: bool,
    max_sitemap_depth: int,
    max_sitemap_urls: int,
    max_sitemap_bytes: int,
) -> list[str]:
    origin = normalize_site_url(site_url)
    entries = await discover_sitemap_entry_urls(
        client,
        site_url,
        allow_unsafe_network_targets=allow_unsafe_network_targets,
        max_sitemap_bytes=max_sitemap_bytes,
    )
    if not entries:
        raise RuntimeError(
            "No sitemap found for this site; use --sitemap-url with a direct sitemap URL."
        )
    log.info(
        "Discovered %d sitemap entr%s for %s",
        len(entries),
        "ies" if len(entries) != 1 else "y",
        redact_url_for_logs(origin),
    )
    preview = [redact_url_for_logs(e) for e in entries[:5]]
    if len(entries) > 5:
        log.info("Sitemap entry URLs: %s … (%d more)", ", ".join(preview), len(entries) - 5)
    else:
        log.info("Sitemap entry URLs: %s", ", ".join(preview))
    merged: list[str] = []
    for entry in entries:
        merged.extend(
            await collect_urls_from_sitemap(
                client,
                entry,
                allow_unsafe_network_targets=allow_unsafe_network_targets,
                max_depth=max_sitemap_depth,
                max_urls=max_sitemap_urls,
                max_sitemap_bytes=max_sitemap_bytes,
            )
        )
        if len(merged) > max_sitemap_urls:
            raise RuntimeError(
                f"Sitemap URL count exceeded max_sitemap_urls={max_sitemap_urls}"
            )
    return dedupe_preserve_order(merged)


def filter_urls_same_host(urls: Iterable[str], site_origin: str) -> list[str]:
    host = urlparse(site_origin).netloc.lower()
    out: list[str] = []
    for u in urls:
        if urlparse(u).netloc.lower() == host:
            out.append(u)
    return out


def sanitize_segment(seg: str) -> str:
    s = seg.strip()
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", s)
    slug = re.sub(r"-{2,}", "-", slug).strip("-").lower()
    if not slug:
        slug = "segment"
    if len(slug) > 120:
        slug = slug[:120].rstrip("-")
    return slug


def url_to_relative_md_path(url: str) -> Path:
    parsed = urlparse(url)
    path = parsed.path.strip("/")
    if not path:
        return Path("index.md")
    raw_segments = [s for s in path.split("/") if s]
    segments = [sanitize_segment(s) for s in raw_segments]
    if not segments:
        return Path("index.md")
    if len(segments) == 1:
        return Path(f"{segments[0]}.md")
    *dirs, name = segments
    return Path(*dirs) / f"{name}.md"


def relative_md_path_with_collision(url: str, used: dict[str, str]) -> Path:
    base = url_to_relative_md_path(url)
    key = base.as_posix()
    prior = used.get(key)
    if prior is None:
        used[key] = url
        return base
    if prior == url:
        return base
    h = hashlib.sha256(url.encode()).hexdigest()[:10]
    parent = base.parent
    stem = base.stem
    suffix = base.suffix
    candidate = parent / f"{stem}-{h}{suffix}"
    key_c = candidate.as_posix()
    n = 0
    while key_c in used and used[key_c] != url:
        n += 1
        candidate = parent / f"{stem}-{h}-{n}{suffix}"
        key_c = candidate.as_posix()
    used[key_c] = url
    return candidate


def markdown_text(result) -> str:
    md = result.markdown
    if md is None:
        return ""
    if isinstance(md, str):
        return md
    return str(md)


def normalize_asset_url(u: str) -> str:
    return urldefrag(u.strip())[0]


def collect_page_image_urls(base_url: str, html: str, media: dict | None) -> list[str]:
    out: list[str] = []
    seen: set[str] = set()

    def add(raw: str) -> None:
        if not raw or raw.startswith("data:") or raw.startswith("javascript:"):
            return
        abs_u = normalize_asset_url(urljoin(base_url, raw.strip()))
        if not abs_u.startswith(("http://", "https://")):
            return
        if abs_u not in seen:
            seen.add(abs_u)
            out.append(abs_u)

    if media:
        for item in media.get("images") or []:
            if isinstance(item, dict):
                s = item.get("src") or ""
            else:
                s = getattr(item, "src", None) or ""
            if s:
                add(s)

    for m in re.finditer(r"<img\b[^>]*>", html, re.I):
        tag = m.group(0)
        sm = re.search(r"\bsrc\s*=\s*([\"'])([^\"']+)\1", tag, re.I)
        if sm:
            add(sm.group(2))
        ssm = re.search(r"\bsrcset\s*=\s*([\"'])([^\"']+)\1", tag, re.I)
        if ssm:
            for part in ssm.group(2).split(","):
                tok = part.strip().split()
                if tok:
                    add(tok[0])

    for m in re.finditer(r"<source\b[^>]*>", html, re.I):
        tag = m.group(0)
        sm = re.search(r"\bsrc\s*=\s*([\"'])([^\"']+)\1", tag, re.I)
        if sm:
            add(sm.group(2))
        ssm = re.search(r"\bsrcset\s*=\s*([\"'])([^\"']+)\1", tag, re.I)
        if ssm:
            for part in ssm.group(2).split(","):
                tok = part.strip().split()
                if tok:
                    add(tok[0])

    return out


def pick_image_extension(url: str, content_type: str | None) -> str:
    ct = (content_type or "").split(";")[0].strip().lower()
    mapping = {
        "image/jpeg": ".jpg",
        "image/jpg": ".jpg",
        "image/png": ".png",
        "image/gif": ".gif",
        "image/webp": ".webp",
        "image/avif": ".avif",
        "image/svg+xml": ".svg",
        "image/bmp": ".bmp",
        "image/x-icon": ".ico",
    }
    if ct in mapping:
        return mapping[ct]
    path = urlparse(url).path.lower()
    for ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".svg", ".ico"):
        if path.endswith(ext):
            return ".jpg" if ext == ".jpeg" else ext
    return ".bin"


async def ensure_image_downloaded(
    client: httpx.AsyncClient,
    absolute_url: str,
    url_key: str,
    media_dir: Path,
    cache: dict[str, Path],
    referer: str,
    user_agent: str,
    allow_unsafe_network_targets: bool,
    max_media_file_bytes: int,
    max_media_total_remaining_bytes: int,
) -> tuple[Path | None, int]:
    if url_key in cache:
        return cache[url_key], 0
    try:
        validate_network_target(
            absolute_url,
            allow_unsafe_network_targets=allow_unsafe_network_targets,
        )
        resp = await client.get(
            absolute_url,
            follow_redirects=True,
            timeout=httpx.Timeout(90.0),
            headers={"Referer": referer, "User-Agent": user_agent},
        )
        resp.raise_for_status()
    except Exception:
        return None, 0
    content_length = resp.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > max_media_file_bytes:
                return None, 0
            if int(content_length) > max_media_total_remaining_bytes:
                return None, 0
        except ValueError:
            pass
    body = resp.content
    if len(body) > max_media_file_bytes:
        return None, 0
    if len(body) > max_media_total_remaining_bytes:
        return None, 0
    ext = pick_image_extension(str(resp.url), resp.headers.get("content-type"))
    stem = hashlib.sha256(url_key.encode()).hexdigest()[:16]
    name = f"{stem}{ext}"
    dest = media_dir / name
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(body)
    rel = Path("media") / name
    cache[url_key] = rel
    return rel, len(body)


def link_from_output_file(output_file: Path, asset_rel_to_out: Path, out_dir: Path) -> str:
    target = (out_dir / asset_rel_to_out).resolve()
    start = output_file.parent.resolve()
    return Path(os.path.relpath(target, start)).as_posix()


_MD_IMG = re.compile(r"!\[([^\]]*)\]\(\s*([^)]+?)\s*\)")


def rewrite_markdown_images(md: str, base_url: str, url_to_rel: dict[str, str]) -> str:
    def repl(m: re.Match) -> str:
        alt = m.group(1)
        inner = m.group(2).strip()
        if inner.startswith("<") and inner.endswith(">"):
            inner = inner[1:-1].strip()
        url_part = inner.split()[0].strip("\"'")
        if not url_part:
            return m.group(0)
        resolved = normalize_asset_url(urljoin(base_url, url_part))
        new = url_to_rel.get(resolved)
        if not new:
            return m.group(0)
        return f"![{alt}]({new})"

    return _MD_IMG.sub(repl, md)


def _rewrite_srcset_attr(value: str, base_url: str, url_to_rel: dict[str, str]) -> str:
    parts_out: list[str] = []
    for chunk in value.split(","):
        chunk = chunk.strip()
        if not chunk:
            continue
        tokens = chunk.split()
        url_part = tokens[0]
        rest = " ".join(tokens[1:])
        resolved = normalize_asset_url(urljoin(base_url, url_part))
        new_u = url_to_rel.get(resolved)
        if new_u:
            parts_out.append(f"{new_u} {rest}".strip() if rest else new_u)
        else:
            parts_out.append(chunk)
    return ", ".join(parts_out)


def rewrite_html_image_urls(html: str, base_url: str, url_to_rel: dict[str, str]) -> str:
    def fix_tag(m: re.Match) -> str:
        full = m.group(0)

        def src_sub(m2: re.Match) -> str:
            q, val = m2.group(1), m2.group(2)
            resolved = normalize_asset_url(urljoin(base_url, val.strip()))
            new_p = url_to_rel.get(resolved)
            if not new_p:
                return m2.group(0)
            return f"src={q}{new_p}{q}"

        full = re.sub(r"src\s*=\s*([\"'])([^\"']+)\1", src_sub, full, flags=re.I)

        def srcset_sub(m2: re.Match) -> str:
            q, val = m2.group(1), m2.group(2)
            new_val = _rewrite_srcset_attr(val, base_url, url_to_rel)
            return f"srcset={q}{new_val}{q}"

        full = re.sub(r"srcset\s*=\s*([\"'])([^\"']+)\1", srcset_sub, full, flags=re.I)
        return full

    return re.sub(r"<(?:img|source)\b[^>]*>", fix_tag, html, flags=re.I)


async def run(args: argparse.Namespace) -> int:
    out_dir = Path(args.out_dir).resolve()
    out_dir.mkdir(parents=True, exist_ok=True)
    if (
        args.max_sitemap_depth <= 0
        or args.max_sitemap_urls <= 0
        or args.max_sitemap_bytes <= 0
        or args.max_media_file_bytes <= 0
        or args.max_media_total_bytes <= 0
    ):
        raise SystemExit(
            "All security limit flags must be positive integers."
        )
    errors_path = safe_out_path(out_dir, Path("errors.jsonl"))

    log.info(
        "Crawl start out_dir=%s max_urls=%s delay=%s page_timeout_ms=%s headless=%s "
        "download_images=%s save_html=%s meta_frontmatter=%s fail_fast=%s user_agent=%s allow_unsafe_network_targets=%s",
        out_dir,
        args.max_urls,
        args.delay,
        args.page_timeout_ms,
        args.headless,
        args.download_images,
        args.save_html,
        args.meta_frontmatter,
        args.fail_fast,
        args.user_agent,
        args.allow_unsafe_network_targets,
    )
    if args.site_url:
        log.info(
            "Source mode=site_url site_url=%s include_offsite_urls=%s",
            redact_url_for_logs(args.site_url),
            args.include_offsite_urls,
        )
    else:
        log.info(
            "Source mode=sitemap_url sitemap_url=%s",
            redact_url_for_logs(args.sitemap_url),
        )

    limits = httpx.Limits(max_keepalive_connections=5, max_connections=10)
    urls: list[str] = []
    async with httpx.AsyncClient(
        headers={"User-Agent": args.user_agent},
        timeout=httpx.Timeout(120.0),
        limits=limits,
    ) as http_client:
        try:
            if args.site_url:
                site_origin = normalize_site_url(args.site_url)
                urls = await collect_page_urls_for_site(
                    http_client,
                    args.site_url,
                    allow_unsafe_network_targets=args.allow_unsafe_network_targets,
                    max_sitemap_depth=args.max_sitemap_depth,
                    max_sitemap_urls=args.max_sitemap_urls,
                    max_sitemap_bytes=args.max_sitemap_bytes,
                )
                pre_host_filter = len(urls)
                if not args.include_offsite_urls:
                    urls = filter_urls_same_host(urls, site_origin)
                    if pre_host_filter != len(urls):
                        log.info(
                            "Host filter same_host=%s kept=%d dropped=%d",
                            redact_url_for_logs(site_origin),
                            len(urls),
                            pre_host_filter - len(urls),
                        )
            else:
                urls = await collect_urls_from_sitemap(
                    http_client,
                    args.sitemap_url,
                    allow_unsafe_network_targets=args.allow_unsafe_network_targets,
                    max_depth=args.max_sitemap_depth,
                    max_urls=args.max_sitemap_urls,
                    max_sitemap_bytes=args.max_sitemap_bytes,
                )
        except (RuntimeError, ValueError) as exc:
            log.error("%s", exc)
            return 2

        pre_dedupe = len(urls)
        urls = dedupe_preserve_order(urls)
        if pre_dedupe != len(urls):
            log.info("Deduped URLs: %d -> %d", pre_dedupe, len(urls))
        if args.max_urls is not None:
            capped = urls[: max(0, args.max_urls)]
            if len(capped) != len(urls):
                log.info("Applied max_urls=%s: %d -> %d", args.max_urls, len(urls), len(capped))
            urls = capped

        log.info("Final URL queue: %d pages", len(urls))
        for u in urls:
            log.debug("queue url=%s", redact_url_for_logs(u))

        if not urls:
            log.warning("No URLs to crawl; exiting")
            return 0

        browser_config = BrowserConfig(headless=args.headless)
        run_kw: dict = {
            "cache_mode": CacheMode.BYPASS,
            "page_timeout": args.page_timeout_ms,
        }
        if args.download_images:
            run_kw["image_score_threshold"] = -999
        run_config = CrawlerRunConfig(**run_kw)

        img_threshold = run_kw.get("image_score_threshold")
        log.info(
            "Starting AsyncWebCrawler headless=%s cache_mode=%s page_timeout_ms=%s image_score_threshold=%s",
            args.headless,
            getattr(run_kw["cache_mode"], "name", str(run_kw["cache_mode"])),
            args.page_timeout_ms,
            img_threshold,
        )

        output_path_map: dict[str, str] = {}
        image_cache: dict[str, Path] = {}
        media_dir = safe_out_path(out_dir, Path("media"))
        media_total_bytes = 0
        exit_code = 0
        attempted = 0
        successes = 0
        failures = 0
        t_crawl = time.perf_counter()

        async with AsyncWebCrawler(config=browser_config) as crawler:
            n = len(urls)
            for i, url in enumerate(urls):
                rel_md = relative_md_path_with_collision(url, output_path_map)
                out_rel = (Path("md") / rel_md).as_posix()
                log.info("Crawl %d/%d start url=%s", i + 1, n, redact_url_for_logs(url))
                try:
                    validate_network_target(
                        url,
                        allow_unsafe_network_targets=args.allow_unsafe_network_targets,
                    )
                except ValueError as exc:
                    exit_code = 1
                    failures += 1
                    attempted += 1
                    err = str(exc)
                    log.error(
                        "Crawl %d/%d blocked url=%s error=%s",
                        i + 1,
                        n,
                        redact_url_for_logs(url),
                        err,
                    )
                    record = {
                        "url": redact_url_for_logs(url),
                        "output_path": out_rel,
                        "error": err,
                    }
                    with errors_path.open("a", encoding="utf-8") as ef:
                        ef.write(json.dumps(record) + "\n")
                    if args.fail_fast:
                        break
                    continue
                try:
                    result = await crawler.arun(url=url, config=run_config)
                except Exception as exc:
                    exit_code = 1
                    failures += 1
                    attempted += 1
                    err = repr(exc)
                    log.error(
                        "Crawl %d/%d failed url=%s error=%s",
                        i + 1,
                        n,
                        redact_url_for_logs(url),
                        err,
                    )
                    record = {
                        "url": redact_url_for_logs(url),
                        "output_path": out_rel,
                        "error": err,
                    }
                    with errors_path.open("a", encoding="utf-8") as ef:
                        ef.write(json.dumps(record) + "\n")
                    if args.fail_fast:
                        break
                    continue

                if not result.success:
                    exit_code = 1
                    failures += 1
                    attempted += 1
                    err = result.error_message or "crawl failed"
                    log.error(
                        "Crawl %d/%d failed url=%s error=%s",
                        i + 1,
                        n,
                        redact_url_for_logs(url),
                        err,
                    )
                    record = {
                        "url": redact_url_for_logs(url),
                        "output_path": out_rel,
                        "error": err,
                    }
                    with errors_path.open("a", encoding="utf-8") as ef:
                        ef.write(json.dumps(record) + "\n")
                    if args.fail_fast:
                        break
                    continue

                md = markdown_text(result)
                html_body = result.html or ""
                base_for_assets = (
                    (getattr(result, "redirected_url", None) or "").strip()
                    or (result.url or "").strip()
                    or url
                )
                media_dict = result.media if isinstance(result.media, dict) else {}

                if args.download_images:
                    img_urls = collect_page_image_urls(
                        base_for_assets, html_body, media_dict
                    )
                    url_to_rel: dict[str, str] = {}
                    md_path = safe_out_path(out_dir, Path("md") / rel_md)
                    new_saves = 0
                    cache_hits = 0
                    failed_img = 0
                    for abs_u in img_urls:
                        key = normalize_asset_url(abs_u)
                        in_cache_before = key in image_cache
                        remaining_media_bytes = max(
                            0, args.max_media_total_bytes - media_total_bytes
                        )
                        if remaining_media_bytes <= 0:
                            failed_img += 1
                            continue
                        saved, saved_bytes = await ensure_image_downloaded(
                            http_client,
                            abs_u,
                            key,
                            media_dir,
                            image_cache,
                            referer=base_for_assets,
                            user_agent=args.user_agent,
                            allow_unsafe_network_targets=args.allow_unsafe_network_targets,
                            max_media_file_bytes=args.max_media_file_bytes,
                            max_media_total_remaining_bytes=remaining_media_bytes,
                        )
                        if saved is not None:
                            media_total_bytes += saved_bytes
                            url_to_rel[key] = link_from_output_file(
                                md_path, saved, out_dir
                            )
                            if in_cache_before:
                                cache_hits += 1
                            else:
                                new_saves += 1
                        elif not in_cache_before:
                            failed_img += 1
                            log.debug(
                                "Image download failed url=%s",
                                redact_url_for_logs(abs_u),
                            )
                    log.info(
                        "Images page %d/%d discovered=%d saved_new=%d cache_hits=%d failed=%d",
                        i + 1,
                        n,
                        len(img_urls),
                        new_saves,
                        cache_hits,
                        failed_img,
                    )
                    md = rewrite_markdown_images(md, base_for_assets, url_to_rel)
                    if args.save_html and html_body:
                        html_body = rewrite_html_image_urls(
                            html_body, base_for_assets, url_to_rel
                        )

                if args.meta_frontmatter:
                    fm_doc = build_meta_frontmatter_document(
                        source_url=base_for_assets,
                        html=html_body,
                    )
                    md = format_markdown_with_frontmatter(md, fm_doc)

                md_path = safe_out_path(out_dir, Path("md") / rel_md)
                md_path.parent.mkdir(parents=True, exist_ok=True)
                md_path.write_text(md, encoding="utf-8")

                html_note = ""
                if args.save_html and html_body:
                    html_path = safe_out_path(
                        out_dir, Path("html") / rel_md.with_suffix(".html")
                    )
                    html_path.parent.mkdir(parents=True, exist_ok=True)
                    html_path.write_text(html_body, encoding="utf-8")
                    html_note = f" html={html_path.relative_to(out_dir).as_posix()}"

                successes += 1
                attempted += 1
                log.info(
                    "Crawl %d/%d ok output=%s%s",
                    i + 1,
                    n,
                    out_rel,
                    html_note,
                )

                if args.delay > 0 and i + 1 < len(urls):
                    log.debug("Sleeping delay=%s seconds after successful crawl", args.delay)
                    await asyncio.sleep(args.delay)

        elapsed = time.perf_counter() - t_crawl
        log.info(
            "Crawl finished attempted=%d successes=%d failures=%d elapsed_s=%.2f exit_code=%s",
            attempted,
            successes,
            failures,
            elapsed,
            exit_code,
        )

    return exit_code


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Crawl sitemap URLs with Crawl4AI, write files per page.")
    p.add_argument(
        "-i",
        "--interactive",
        action="store_true",
        help="Interactive wizard (banner, prompts, Space to toggle options)",
    )
    src = p.add_mutually_exclusive_group(required=False)
    src.add_argument(
        "--sitemap-url",
        default=None,
        help="Direct URL of sitemap.xml or sitemap index (recursive child sitemaps supported)",
    )
    src.add_argument(
        "--site-url",
        default=None,
        help="Site origin (e.g. https://www.example.com); discover sitemap via robots.txt or common paths",
    )
    p.add_argument(
        "--out-dir",
        default=None,
        help="Directory for output files (required unless --interactive)",
    )
    p.add_argument(
        "--include-offsite-urls",
        action="store_true",
        help="With --site-url, crawl URLs on other hosts too (default: only URLs matching the site host)",
    )
    p.add_argument(
        "--allow-unsafe-network-targets",
        action="store_true",
        help="Allow crawling private/loopback/link-local/reserved network targets (unsafe)",
    )
    p.add_argument(
        "--max-sitemap-depth",
        type=int,
        default=DEFAULT_MAX_SITEMAP_DEPTH,
        help=f"Maximum nested sitemap index depth (default: {DEFAULT_MAX_SITEMAP_DEPTH})",
    )
    p.add_argument(
        "--max-sitemap-urls",
        type=int,
        default=DEFAULT_MAX_SITEMAP_URLS,
        help=f"Maximum URLs accepted from sitemap expansion (default: {DEFAULT_MAX_SITEMAP_URLS})",
    )
    p.add_argument(
        "--max-sitemap-bytes",
        type=int,
        default=DEFAULT_MAX_SITEMAP_BYTES,
        help=f"Maximum decoded sitemap payload bytes (default: {DEFAULT_MAX_SITEMAP_BYTES})",
    )
    p.add_argument(
        "--max-media-file-bytes",
        type=int,
        default=DEFAULT_MAX_MEDIA_FILE_BYTES,
        help=f"Maximum bytes for one downloaded media file (default: {DEFAULT_MAX_MEDIA_FILE_BYTES})",
    )
    p.add_argument(
        "--max-media-total-bytes",
        type=int,
        default=DEFAULT_MAX_MEDIA_TOTAL_BYTES,
        help=f"Maximum total bytes for downloaded media files (default: {DEFAULT_MAX_MEDIA_TOTAL_BYTES})",
    )
    p.add_argument(
        "--delay",
        type=float,
        default=0.0,
        help="Seconds to sleep after each successful crawl (not after last)",
    )
    p.add_argument(
        "--page-timeout-ms",
        type=int,
        default=60_000,
        help="Page navigation timeout in milliseconds",
    )
    p.add_argument(
        "--headless",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Run browser headless (default: true)",
    )
    p.add_argument(
        "--max-urls",
        type=int,
        default=None,
        help="Maximum number of URLs to crawl (after dedupe)",
    )
    p.add_argument(
        "--save-html",
        action="store_true",
        help="Also write HTML under html/ mirroring the same path hierarchy as md/",
    )
    p.add_argument(
        "--meta-frontmatter",
        action="store_true",
        help="Prepend YAML frontmatter with source_url and HTML meta tags (title, canonical, meta name/property/http-equiv)",
    )
    p.add_argument(
        "--download-images",
        action="store_true",
        help="Download page images to media/ and rewrite links in .md (and .html with --save-html)",
    )
    p.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop on first crawl failure",
    )
    p.add_argument(
        "--user-agent",
        default="crawlboy/1.0 (+https://github.com/aksharahegde/crawlboy)",
        help="User-Agent for sitemap HTTP fetch",
    )
    p.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Verbose DEBUG logging",
    )
    return p


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    if sys.stderr.isatty() and not os.environ.get("NO_COLOR"):
        try:
            from rich.console import Console
            from rich.logging import RichHandler

            logging.basicConfig(
                level=level,
                format="%(message)s",
                datefmt="[%X]",
                handlers=[
                    RichHandler(
                        console=Console(stderr=True),
                        rich_tracebacks=True,
                        show_path=False,
                    )
                ],
            )
            return
        except ImportError:
            pass
    logging.basicConfig(
        level=level,
        format="%(levelname)s %(asctime)s %(message)s",
        stream=sys.stderr,
    )


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    if args.interactive:
        from crawlboy.cli import run_interactive_wizard

        args = run_interactive_wizard()
    else:
        if not (args.sitemap_url or args.site_url):
            parser.error(
                "one of the arguments --sitemap-url --site-url is required (or use --interactive)"
            )
        if args.out_dir is None:
            parser.error("the following arguments are required: --out-dir (or use --interactive)")
    configure_logging(args.verbose)
    code = asyncio.run(run(args))
    raise SystemExit(code)


if __name__ == "__main__":
    main()
