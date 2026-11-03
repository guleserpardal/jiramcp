# Katkı

1. `main` dalında çalışmayın; her değişiklik için dal açın (`feat/…`, `fix/…`).
2. Geliştirme ortamı: `uv sync --frozen --dev`.
3. Göndermeden önce:
   ```bash
   uv run pytest tests/unit -q
   uv run ruff check src tests
   uv run ruff format --check src tests
   uv run mypy src
   ```
4. Yeni özellik testle, hata düzeltmesi regresyon testiyle gelir.
5. Bağımlılık değiştiyse `requirements.txt`'i yeniden üretin (bkz. README).
6. Commit türleri: `feat`, `fix`, `docs`, `refactor`, `test`, `chore`, `perf`, `ci`.
7. Değişiklik pull request ile `main`'e alınır.
