# Crawlboy

Sequentially crawls every URL from a sitemap (including nested sitemap indexes) with [Crawl4AI](https://docs.crawl4ai.com/core/quickstart/) and writes one Markdown file per page.

Output mirrors the URL path under `--out-dir/md/`: each path segment becomes a directory and the last segment becomes the filename.

```
/blog/articles/basic-git-commands/
→ {out-dir}/md/blog/articles/basic-git-commands.md
```

Site root (`/`) maps to `{out-dir}/md/index.md`. Failures are logged to `{out-dir}/errors.jsonl`.

## Features

- **Sitemap discovery** — auto-detect from `robots.txt` or common paths, or provide a direct URL
- **Nested sitemap indexes** — recursively follows `<sitemapindex>` entries
- **Markdown output** — one `.md` file per page, mirroring URL structure
- **HTML output** — optional raw HTML under `{out-dir}/html/` with `--save-html`
- **Image download** — saves images to `{out-dir}/media/` (content-addressed, deduped) and rewrites paths in Markdown/HTML with `--download-images`
- **Interactive CLI** — guided wizard with [questionary](https://github.com/tmbo/questionary) and [Rich](https://github.com/Textualize/rich)
- **Docker support** — runs headless out of the box

## Setup

```bash
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
crawl4ai-setup
```

> `crawl4ai-setup` installs Playwright/Chromium and can use several hundred MB of disk space. If something fails, run `crawl4ai-doctor`.

## Usage

### Direct sitemap URL

```bash
python sitemap_crawler.py --sitemap-url 'https://example.com/sitemap.xml' --out-dir ./out
```

### Auto-discover from site root

```bash
python sitemap_crawler.py --site-url 'https://www.example.com' --out-dir ./out
```

Discovery order: `robots.txt` → `/sitemap.xml` → `/sitemap_index.xml` → `/sitemap-index.xml` → `/wp-sitemap.xml`.

By default with `--site-url`, only URLs matching the site origin host are crawled. Use `--include-offsite-urls` to crawl all listed URLs.

### Interactive mode

```bash
python sitemap_crawler.py --interactive
# or
python sitemap_crawler.py -i
```

The wizard walks through URL mode, output directory, crawl options, and advanced settings before confirming. Requires a TTY — for Docker use `docker run -it ...`.

## Options

| Flag | Description | Default |
|------|-------------|---------|
| `--sitemap-url` | Direct sitemap URL | — |
| `--site-url` | Site root for auto-discovery | — |
| `--out-dir` | Output directory | — |
| `--delay` | Seconds to wait after each page | `0` |
| `--page-timeout-ms` | Navigation timeout in ms | `60000` |
| `--max-urls` | Cap number of URLs (for testing) | unlimited |
| `--save-html` | Write raw HTML under `html/` | off |
| `--download-images` | Save images under `media/` and rewrite paths | off |
| `--no-headless` | Show the browser window | off |
| `--fail-fast` | Stop on first crawl error | off |
| `--include-offsite-urls` | Crawl hosts outside site origin (`--site-url` only) | off |
| `-i`, `--interactive` | Launch guided wizard | off |

## Docker

```bash
docker build -t crawlboy .
docker run --rm -v "$(pwd)/out:/out" crawlboy \
  --site-url 'https://www.example.com' --out-dir /out
```
