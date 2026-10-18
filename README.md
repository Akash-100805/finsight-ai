# FinSight AI

FinSight AI is a monorepo. `services/news` holds the news ingestion service (imported with full history from `KushagraDixit05/finsight-data-pipeline`) and is being revamped. The TKG and multi-agent services will be added later as sibling services. Contracts shared by all services live in `shared/`.

## Layout

```
dev.py                  task runner (plain Python, Windows/PowerShell friendly)
.env.example            template for the root .env (git-ignored)
shared/                 shared contracts (populated in Phase 1)
services/news/          news service: src/, tests/, migrations/, pyproject.toml
docs/                   guide and documentation
docs/archive/           archived material (old news dev plan)
infra/                  reserved for deployment config
```

## Windows setup (PowerShell)

1. Install Python 3.12 and confirm `py -3.12 --version` works.
2. Create the virtual environment and install dependencies:
   ```powershell
   python dev.py setup
   ```
3. Copy `.env.example` to `.env` and fill in the keys. Use Neon's **direct** (non-pooled) connection strings ending in `?sslmode=require`.
4. Check the databases:
   ```powershell
   python dev.py db-check
   ```
5. Run the tests:
   ```powershell
   python dev.py test
   ```

Run `python dev.py` with no arguments to list all commands.

## Build guide

The specification for the news revamp is in [docs/NEWS_REVAMP_GUIDE.md](docs/NEWS_REVAMP_GUIDE.md).
