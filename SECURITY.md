# Security Policy

## Supported Versions

Only the latest published release is supported for security fixes.

## Reporting a Vulnerability

Please report vulnerabilities privately by opening a security advisory on GitHub:

- https://github.com/aksharahegde/crawlboy/security/advisories/new

Include:

- Impact summary
- Reproduction steps
- Proof-of-concept input (URL/sitemap payload)
- Suggested remediation if available

Do not open public issues for unpatched vulnerabilities.

## Security Posture Summary

Crawlboy uses secure defaults:

- Deny-by-default network target validation for private/loopback/link-local/reserved addresses
- Bounded sitemap depth, URL count, and sitemap payload size
- Bounded media download file size and total bytes
- URL redaction for logs and persisted `errors.jsonl` records
- Output path containment checks to keep writes under `--out-dir`

For trusted internal environments, overrides are explicit via CLI flags (for example `--allow-unsafe-network-targets`).
