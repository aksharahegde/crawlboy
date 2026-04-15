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

## Installation

```bash
pip install crawlboy
crawl4ai-setup
```

> `crawl4ai-setup` installs Playwright/Chromium and can use several hundred MB of disk space. If something fails, run `crawl4ai-doctor`.

### From source

```bash
git clone https://github.com/aksharahegde/crawlboy.git
cd crawlboy
pip install -e .
crawl4ai-setup
```

## Usage

### Direct sitemap URL

```bash
crawlboy --sitemap-url 'https://example.com/sitemap.xml' --out-dir ./out
```

### Auto-discover from site root

```bash
crawlboy --site-url 'https://www.example.com' --out-dir ./out
```

Discovery order: `robots.txt` → `/sitemap.xml` → `/sitemap_index.xml` → `/sitemap-index.xml` → `/wp-sitemap.xml`.

By default with `--site-url`, only URLs matching the site origin host are crawled. Use `--include-offsite-urls` to crawl all listed URLs.

### Interactive mode

```bash
crawlboy --interactive
# or
crawlboy -i
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
| `--allow-unsafe-network-targets` | Allow private/loopback/link-local/reserved targets (unsafe) | off |
| `--max-sitemap-depth` | Maximum nested sitemap index depth | `32` |
| `--max-sitemap-urls` | Maximum URLs accepted from sitemap expansion | `50000` |
| `--max-sitemap-bytes` | Maximum decoded bytes per sitemap payload | `5000000` |
| `--max-media-file-bytes` | Maximum bytes for one downloaded media file | `10000000` |
| `--max-media-total-bytes` | Maximum total bytes for downloaded media files | `250000000` |
| `-i`, `--interactive` | Launch guided wizard | off |

## Docker

```bash
docker build -t crawlboy .
docker run --rm -v "$(pwd)/out:/out" crawlboy \
  --site-url 'https://www.example.com' --out-dir /out
```

## For LLM Agents

Instructions for AI coding agents (Claude Code, Cursor, Copilot, etc.) to install and use Crawlboy.

### Installation

```bash
git clone https://github.com/aksharahegde/crawlboy.git
cd crawlboy
python -m venv .venv
source .venv/bin/activate
pip install -e .
crawl4ai-setup
```

### Running a Scrape

Crawl a site by auto-discovering its sitemap:

```bash
source .venv/bin/activate
crawlboy --site-url 'https://www.example.com' --out-dir ./out
```

Or provide a direct sitemap URL:

```bash
source .venv/bin/activate
crawlboy --sitemap-url 'https://example.com/sitemap.xml' --out-dir ./out
```

Useful flags for agent workflows:

- `--max-urls N` — limit to N pages (good for testing)
- `--save-html` — also save raw HTML
- `--download-images` — download images and rewrite paths in Markdown/HTML
- `--delay N` — wait N seconds between pages to avoid rate limiting
- `--fail-fast` — stop on first error instead of continuing

Output structure:

```
out/
├── md/          # One Markdown file per page, mirroring URL path
├── html/        # Raw HTML (with --save-html)
├── media/       # Downloaded images (with --download-images)
└── errors.jsonl # Failed URLs with error details
```

## Verified Working

Crawlboy has been tested and verified to work with real websites. Here's a recent test run:

**Command:**
```bash
crawlboy --site-url 'https://aksharahegde.xyz' --out-dir ./test-output --max-urls 5
```

**Test Results:**
- Auto-discovery: Found sitemap from `robots.txt` ✓
- Pages crawled: 5/5 successful, 0 failures
- Total time: ~13 seconds
- Redirect handling: Automatically handled aksharahegde.xyz → www.aksharahegde.xyz

**Output Generated:**
```
test-output/md/
├── index.md          (3.1 KB) — homepage content
├── blog.md           (3.2 KB) — blog page
├── projects.md       (5.3 KB) — projects page
├── resources.md      (628 B) — resources page
└── shop.md           (564 B) — shop page
```

All Markdown files contain properly formatted content with preserved links and page structure.

## Contributing

Contributions are welcome! Please follow these guidelines:

### Code Style

- Use Python 3.10+ compatible syntax
- Format code with [Black](https://github.com/psf/black) — run `black .` before committing
- Lint with [ruff](https://github.com/astral-sh/ruff) — run `ruff check .`
- Follow [PEP 8](https://pep8.org/) conventions

### Commit Messages

- Use present tense, imperative mood ("add feature", not "added feature")
- Be concise and descriptive (under 70 characters for the subject line)
- Reference issues if applicable (e.g., "Fix #123")
- Example: `Fix image path rewriting for nested URLs`

### Pull Requests

1. Fork the repository
2. Create a feature branch: `git checkout -b feature/your-feature`
3. Commit your changes with clear messages
4. Test thoroughly before pushing
5. Open a PR with a clear description of changes

### Testing

- Test the interactive CLI locally: `crawlboy -i`
- Test with both `--site-url` and `--sitemap-url` modes
- Verify output structure matches documentation
- Test with `--download-images` and `--save-html` flags
- Run against a small sitemap first (use `--max-urls`)

### Reporting Issues

Include:
- Steps to reproduce
- Python version and OS
- Full error output or stack trace
- Sample sitemap URL (if possible)


## Security

Crawlboy applies secure defaults to reduce abuse risk from untrusted sitemap and page content:

- Deny-by-default network target checks for private, loopback, link-local, multicast, reserved, and unspecified IP ranges
- Sitemap depth, URL count, and payload-size limits
- Media download file-size and total-size limits
- URL redaction in logs and `errors.jsonl` output
- Output path containment under `--out-dir`

Use `--allow-unsafe-network-targets` only in trusted internal environments where private network crawling is intentional.

See `SECURITY.md` and `docs/security/` for reporting and control details.
