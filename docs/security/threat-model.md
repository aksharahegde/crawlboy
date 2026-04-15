# Crawlboy Threat Model

## System overview

Crawlboy is a CLI that takes user-provided sitemap or site URLs, discovers target pages, crawls them with Crawl4AI/Playwright, and writes Markdown/HTML/media artifacts to disk.

## Assets

- Local filesystem integrity and availability under output paths.
- Crawl output data (`md/`, optional `html/`, `media/`, `errors.jsonl`).
- Process resources (CPU, memory, disk, network sockets).
- Network reachability from the machine running the CLI.
- Operational logs and persisted error records.

## Trust boundaries

- CLI arguments are trusted only as user intent, not as safe content.
- Remote sitemap/XML/HTML/media content is untrusted.
- Third-party dependencies and browser runtime are external execution surfaces.
- Filesystem writes cross from process memory into persistent storage.

## Threat actors

- Malicious site owner controlling sitemap and page content.
- Opportunistic attacker exploiting internal network reachability (SSRF-like behavior).
- Curious insider or CI user passing unsafe output directories or override flags.
- Adversarial content host serving oversized or malformed payloads for resource exhaustion.

## Attack surfaces

- URL intake and normalization (`--site-url`, `--sitemap-url`).
- Recursive sitemap discovery and XML parsing.
- Image download pipeline and media rewrite logic.
- Output path generation and artifact persistence.
- Logging and JSONL error serialization.

## Risk register

| ID | Risk | Severity | Impact | Mitigation |
|---|---|---|---|---|
| R1 | Internal network reachability via untrusted sitemap/image URLs | Medium | Unexpected access to loopback/private/link-local/metadata endpoints | Enforce deny-by-default network policy with explicit override flags |
| R2 | XML abuse and deep sitemap recursion | Medium | Memory/CPU exhaustion and crawl amplification | Enforce payload size caps, parse guards, recursion and URL ceilings |
| R3 | Sensitive data leakage in logs and `errors.jsonl` | Low-Medium | Query tokens/credentials persisted in plaintext | Centralized URL redaction for logs and persisted error records |
| R4 | Unbounded media download volume | Medium | Disk exhaustion and degraded runtime | Cap per-file and total media bytes, fail safely on breach |
| R5 | Unsafe output location in automated contexts | Low | Writes outside intended workspace if caller is untrusted | Resolve and validate writes remain under selected output root |

## Security objectives

- Default-deny dangerous network targets while preserving explicit opt-in behavior.
- Keep crawler execution bounded in depth, volume, and artifact size.
- Prevent accidental disclosure in operational output.
- Provide repeatable, automated regression checks in CI.
