# Security Controls Matrix

| Control | Location | Test Coverage | CI Gate |
|---|---|---|---|
| Deny-by-default network targets | `crawlboy/crawler.py` (`validate_network_target`) | `tests/security/test_security_controls.py` | `security.yml` pytest job |
| Sitemap recursion/volume/size limits | `crawlboy/crawler.py` (`collect_urls_from_sitemap`, `fetch_sitemap_bytes`) | `tests/security/test_security_controls.py` | `security.yml` pytest job |
| Media size limits | `crawlboy/crawler.py` (`ensure_image_downloaded`) | `tests/security/test_security_controls.py` | `security.yml` pytest job |
| URL redaction in logs and errors | `crawlboy/crawler.py`, `crawlboy/cli.py` | `tests/security/test_security_controls.py` | `security.yml` pytest job |
| Output path containment | `crawlboy/crawler.py` (`safe_out_path`) | `tests/security/test_security_controls.py` | `security.yml` pytest job |
| Dependency vulnerability scanning | CI only | N/A | `security.yml` pip-audit |
| Static security linting | CI only | N/A | `security.yml` bandit |
| Minimum coverage threshold | `pyproject.toml` | Whole test suite | `ci.yml` pytest-cov |
