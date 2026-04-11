# Playwright base includes browser deps; aligns with Crawl4AI’s Playwright usage.
FROM mcr.microsoft.com/playwright/python:v1.50.0-noble

ENV PYTHONUNBUFFERED=1
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt \
    && crawl4ai-setup

COPY sitemap_crawler.py .

ENTRYPOINT ["python", "/app/sitemap_crawler.py"]
