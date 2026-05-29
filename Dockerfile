# Playwright base includes browser deps; aligns with Crawl4AI's Playwright usage.
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY pyproject.toml README.md LICENSE ./
COPY crawlboy/ crawlboy/
RUN pip install --no-cache-dir . \
    && pip install --no-cache-dir 'lxml>=6.1.0' \
    && crawl4ai-setup

ENTRYPOINT ["crawlboy"]
