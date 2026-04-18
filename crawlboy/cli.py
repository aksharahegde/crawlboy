#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sys
from urllib.parse import urlparse

import questionary
from questionary import Style

from crawlboy.crawler import (
    DEFAULT_MAX_MEDIA_FILE_BYTES,
    DEFAULT_MAX_MEDIA_TOTAL_BYTES,
    DEFAULT_MAX_SITEMAP_BYTES,
    DEFAULT_MAX_SITEMAP_DEPTH,
    DEFAULT_MAX_SITEMAP_URLS,
    normalize_site_url,
    redact_url_for_logs,
)
from rich import box
from rich.align import Align
from rich.console import Console
from rich.panel import Panel
from rich.text import Text

_DEFAULT_UA = "crawlboy/1.0 (+https://github.com/aksharahegde/crawlboy)"

_QSTYLE = Style(
    [
        ("qmark", "fg:cyan bold"),
        ("question", "bold"),
        ("answer", "fg:green"),
        ("pointer", "fg:cyan bold"),
        ("highlighted", "fg:cyan bold"),
        ("selected", "fg:green"),
        ("instruction", "fg:ansibrightblack"),
    ]
)


def _normalize_sitemap_url(url: str) -> str:
    u = url.strip()
    if not u:
        raise ValueError("URL cannot be empty")
    if not u.startswith(("http://", "https://")):
        u = "https://" + u
    parsed = urlparse(u)
    if not parsed.netloc:
        raise ValueError("Sitemap URL needs a host (e.g. https://example.com/sitemap.xml)")
    return u


def _validate_site_url(text: str) -> bool | str:
    try:
        normalize_site_url(text)
    except ValueError as e:
        return str(e)
    return True


def _validate_sitemap_url(text: str) -> bool | str:
    try:
        _normalize_sitemap_url(text)
    except ValueError as e:
        return str(e)
    return True


def _validate_float_non_neg(text: str) -> bool | str:
    t = text.strip()
    if not t:
        return True
    try:
        v = float(t)
    except ValueError:
        return "Enter a number"
    if v < 0:
        return "Must be >= 0"
    return True


def _validate_int_positive(text: str) -> bool | str:
    t = text.strip()
    if not t:
        return True
    try:
        v = int(t, 10)
    except ValueError:
        return "Enter an integer"
    if v <= 0:
        return "Must be > 0"
    return True


def _validate_max_urls(text: str) -> bool | str:
    t = text.strip()
    if not t:
        return True
    try:
        v = int(t, 10)
    except ValueError:
        return "Enter an integer or leave empty"
    if v < 0:
        return "Must be >= 0"
    return True


def _validate_positive_int(text: str) -> bool | str:
    t = text.strip()
    if not t:
        return True
    try:
        v = int(t, 10)
    except ValueError:
        return "Enter a positive integer"
    if v <= 0:
        return "Must be > 0"
    return True


def _validate_out_dir(text: str) -> bool | str:
    if not text.strip():
        return "Output directory cannot be empty"
    return True


def _print_banner(console: Console) -> None:
    title = Text()
    title.append("crawlboy", style="bold cyan")
    subtitle = Text(
        "Crawl sitemap URLs with Crawl4AI — markdown per page",
        style="dim",
    )
    inner = Text.assemble(title, "\n", subtitle)
    panel = Panel(
        Align.center(inner),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )
    console.print()
    console.print(panel)
    console.print()


def run_interactive_wizard() -> argparse.Namespace:
    if not sys.stdin.isatty():
        print("Interactive mode requires a terminal (stdin must be a TTY).", file=sys.stderr)
        raise SystemExit(2)

    console = Console(stderr=False)
    _print_banner(console)

    mode = questionary.select(
        "How do you want to provide URLs?",
        choices=[
            questionary.Choice(
                "Discover sitemap from a site (robots.txt / common paths)",
                value="site",
            ),
            questionary.Choice(
                "Use a direct sitemap URL (.xml or index)",
                value="sitemap",
            ),
        ],
        style=_QSTYLE,
    ).ask()

    if mode is None:
        raise SystemExit(1)

    if mode == "site":
        url_raw = questionary.text(
            "Site origin (e.g. https://www.example.com or example.com)",
            validate=_validate_site_url,
            style=_QSTYLE,
        ).ask()
        if url_raw is None:
            raise SystemExit(1)
        site_url = normalize_site_url(url_raw)
        sitemap_url = None
    else:
        url_raw = questionary.text(
            "Sitemap URL",
            validate=_validate_sitemap_url,
            style=_QSTYLE,
        ).ask()
        if url_raw is None:
            raise SystemExit(1)
        site_url = None
        sitemap_url = _normalize_sitemap_url(url_raw)

    out_dir = questionary.text(
        "Output directory",
        default="out",
        validate=_validate_out_dir,
        style=_QSTYLE,
    ).ask()
    if out_dir is None:
        raise SystemExit(1)
    out_dir = out_dir.strip()

    toggles = questionary.checkbox(
        "Options — Space toggles, Enter confirms",
        choices=[
            questionary.Choice(
                "Include off-site URLs (only applies to site discovery mode)",
                value="include_offsite",
            ),
            questionary.Choice("Save raw HTML under html/", value="save_html"),
            questionary.Choice(
                "Add YAML frontmatter with page meta tags",
                value="meta_frontmatter",
            ),
            questionary.Choice(
                "Download images to media/ and rewrite links",
                value="download_images",
            ),
            questionary.Choice("Stop on first failure (fail fast)", value="fail_fast"),
            questionary.Choice(
                "Run browser headless (recommended)",
                value="headless",
                checked=True,
            ),
            questionary.Choice("Verbose DEBUG logging", value="verbose"),
            questionary.Choice(
                "Allow unsafe network targets (private/loopback — use with care)",
                value="unsafe_network",
            ),
        ],
        style=_QSTYLE,
    ).ask()

    if toggles is None:
        raise SystemExit(1)

    delay_s = "0"
    page_timeout_s = "60000"
    max_urls_s = ""
    user_agent = _DEFAULT_UA

    if questionary.confirm(
        "Edit advanced settings (delay, timeouts, max URLs, user-agent)?",
        default=False,
        style=_QSTYLE,
    ).ask():
        delay_s = questionary.text(
            "Delay after each successful page (seconds, 0 = none)",
            default=delay_s,
            validate=_validate_float_non_neg,
            style=_QSTYLE,
        ).ask()
        if delay_s is None:
            raise SystemExit(1)

        page_timeout_s = questionary.text(
            "Page timeout (milliseconds)",
            default=page_timeout_s,
            validate=_validate_int_positive,
            style=_QSTYLE,
        ).ask()
        if page_timeout_s is None:
            raise SystemExit(1)

        max_urls_s = questionary.text(
            "Max URLs to crawl (empty = no limit)",
            default=max_urls_s,
            validate=_validate_max_urls,
            style=_QSTYLE,
        ).ask()
        if max_urls_s is None:
            raise SystemExit(1)

        ua = questionary.text(
            "User-Agent string",
            default=user_agent,
            style=_QSTYLE,
        ).ask()
        if ua is None:
            raise SystemExit(1)
        if ua.strip():
            user_agent = ua.strip()

    max_sitemap_depth_s = str(DEFAULT_MAX_SITEMAP_DEPTH)
    max_sitemap_urls_s = str(DEFAULT_MAX_SITEMAP_URLS)
    max_sitemap_bytes_s = str(DEFAULT_MAX_SITEMAP_BYTES)
    max_media_file_bytes_s = str(DEFAULT_MAX_MEDIA_FILE_BYTES)
    max_media_total_bytes_s = str(DEFAULT_MAX_MEDIA_TOTAL_BYTES)

    if questionary.confirm(
        "Edit security limits (sitemap depth, URL cap, payload size, media caps)?",
        default=False,
        style=_QSTYLE,
    ).ask():
        max_sitemap_depth_s = questionary.text(
            "Max nested sitemap index depth",
            default=max_sitemap_depth_s,
            validate=_validate_positive_int,
            style=_QSTYLE,
        ).ask()
        if max_sitemap_depth_s is None:
            raise SystemExit(1)

        max_sitemap_urls_s = questionary.text(
            "Max URLs from sitemap expansion",
            default=max_sitemap_urls_s,
            validate=_validate_positive_int,
            style=_QSTYLE,
        ).ask()
        if max_sitemap_urls_s is None:
            raise SystemExit(1)

        max_sitemap_bytes_s = questionary.text(
            "Max decoded sitemap bytes per file",
            default=max_sitemap_bytes_s,
            validate=_validate_positive_int,
            style=_QSTYLE,
        ).ask()
        if max_sitemap_bytes_s is None:
            raise SystemExit(1)

        max_media_file_bytes_s = questionary.text(
            "Max bytes per downloaded image",
            default=max_media_file_bytes_s,
            validate=_validate_positive_int,
            style=_QSTYLE,
        ).ask()
        if max_media_file_bytes_s is None:
            raise SystemExit(1)

        max_media_total_bytes_s = questionary.text(
            "Max total bytes for all downloaded images",
            default=max_media_total_bytes_s,
            validate=_validate_positive_int,
            style=_QSTYLE,
        ).ask()
        if max_media_total_bytes_s is None:
            raise SystemExit(1)

    try:
        delay = float(delay_s.strip() or "0")
    except ValueError:
        delay = 0.0
    try:
        page_timeout_ms = int(page_timeout_s.strip(), 10)
    except ValueError:
        page_timeout_ms = 60_000
    max_urls: int | None
    if max_urls_s.strip():
        max_urls = int(max_urls_s.strip(), 10)
    else:
        max_urls = None

    try:
        max_sitemap_depth = int(max_sitemap_depth_s.strip(), 10)
    except ValueError:
        max_sitemap_depth = DEFAULT_MAX_SITEMAP_DEPTH
    try:
        max_sitemap_urls = int(max_sitemap_urls_s.strip(), 10)
    except ValueError:
        max_sitemap_urls = DEFAULT_MAX_SITEMAP_URLS
    try:
        max_sitemap_bytes = int(max_sitemap_bytes_s.strip(), 10)
    except ValueError:
        max_sitemap_bytes = DEFAULT_MAX_SITEMAP_BYTES
    try:
        max_media_file_bytes = int(max_media_file_bytes_s.strip(), 10)
    except ValueError:
        max_media_file_bytes = DEFAULT_MAX_MEDIA_FILE_BYTES
    try:
        max_media_total_bytes = int(max_media_total_bytes_s.strip(), 10)
    except ValueError:
        max_media_total_bytes = DEFAULT_MAX_MEDIA_TOTAL_BYTES

    headless_on = "headless" in toggles

    display_url = redact_url_for_logs(site_url or (sitemap_url or ""))
    summary_lines = [
        f"[cyan]Mode:[/] {'site' if site_url else 'sitemap'}",
        f"[cyan]URL:[/] {display_url}",
        f"[cyan]Out:[/] {out_dir}",
        f"[cyan]Headless:[/] {headless_on}",
        f"[cyan]Verbose:[/] {'verbose' in toggles}",
    ]
    console.print(Panel("\n".join(summary_lines), title="Summary", border_style="green"))

    if not questionary.confirm("Start crawl now?", default=True, style=_QSTYLE).ask():
        console.print("[yellow]Cancelled.[/]")
        raise SystemExit(0)

    return argparse.Namespace(
        site_url=site_url,
        sitemap_url=sitemap_url,
        out_dir=out_dir,
        include_offsite_urls="include_offsite" in toggles,
        delay=delay,
        page_timeout_ms=page_timeout_ms,
        headless=headless_on,
        max_urls=max_urls,
        save_html="save_html" in toggles,
        meta_frontmatter="meta_frontmatter" in toggles,
        download_images="download_images" in toggles,
        fail_fast="fail_fast" in toggles,
        user_agent=user_agent,
        verbose="verbose" in toggles,
        interactive=True,
        allow_unsafe_network_targets="unsafe_network" in toggles,
        max_sitemap_depth=max_sitemap_depth,
        max_sitemap_urls=max_sitemap_urls,
        max_sitemap_bytes=max_sitemap_bytes,
        max_media_file_bytes=max_media_file_bytes,
        max_media_total_bytes=max_media_total_bytes,
    )
