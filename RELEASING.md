# Releasing to PyPI

## Release checklist

1. Set version in `crawlboy/__init__.py` (`__version__`; `pyproject.toml` reads it via Hatch).
2. Move `[Unreleased]` notes to a dated section in `CHANGELOG.md`.
3. Commit on `main`, e.g. `chore: release X.Y.Z`.
4. Tag and push:
   ```bash
   git tag -a vX.Y.Z -m "Release X.Y.Z"
   git push origin main
   git push origin vX.Y.Z
   ```
5. Create a **GitHub Release** from the tag (Publish release).
6. Build and upload to PyPI:
   ```bash
   python -m pip install build twine
   python -m build
   twine check dist/*
   twine upload dist/*   # uses PYPI_API_TOKEN or ~/.pypirc
   ```
7. Confirm on [pypi.org/project/crawlboy/](https://pypi.org/project/crawlboy/):
   ```bash
   pip install crawlboy==X.Y.Z
   crawl4ai-setup
   pip install 'lxml>=6.1.0'   # optional; fixes PYSEC-2026-87 until crawl4ai updates its pin
   pip install 'nltk @ git+https://github.com/nltk/nltk@v3.10.0-rc1'   # optional; fixes PYSEC-2026-597 until nltk 3.10.0 is on PyPI
   ```

## Local build check

```bash
pip install -e ".[dev]"
python -m build
twine check dist/*
```
