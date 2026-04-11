# Changelog

All notable changes to Crawlboy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.0.0] - 2026-04-11

### Added

- **Sitemap crawling** — sequentially crawls every URL from XML sitemaps with Crawl4AI
- **Nested sitemap support** — recursively follows `<sitemapindex>` entries
- **Markdown output** — converts crawled pages to Markdown, one file per URL with mirrored directory structure
- **HTML export** — optional `--save-html` flag to preserve raw HTML alongside Markdown
- **Image download** — `--download-images` to save media locally with content-addressed filenames (deduped across crawl) and automatic path rewriting in Markdown and HTML
- **Automatic sitemap discovery** — auto-detects sitemap from `robots.txt` or common paths (`/sitemap.xml`, `/sitemap_index.xml`, etc.)
- **Interactive CLI** — guided wizard with [questionary](https://github.com/tmbo/questionary) and [Rich](https://github.com/Textualize/rich) for easy configuration
- **Flexible URL modes** — direct sitemap URL (`--sitemap-url`) or site root discovery (`--site-url`)
- **Host filtering** — respects site origin by default; `--include-offsite-urls` to crawl all listed URLs
- **Error logging** — failures logged to `errors.jsonl` with paths and error details
- **Performance tuning** — configurable per-page delay, page timeout, and max URL limit
- **Browser control** — `--no-headless` to show browser window for debugging
- **Docker support** — includes Dockerfile for containerized execution with pre-installed browser dependencies
- **Fail-fast mode** — `--fail-fast` to stop on first error for rapid iteration

### Technical Details

- Built with [Crawl4AI](https://docs.crawl4ai.com/) for intelligent page crawling
- Supports Python 3.7+
- Docker image based on Playwright Python for browser automation
- Async-first architecture for efficient crawling
- XML namespace-safe sitemap parsing
