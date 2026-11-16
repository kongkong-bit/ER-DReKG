# DiseaseGraph Lab API

## Local development

1. Copy the root `.env.example` to `.env` and replace both secrets. Never commit `.env`.
2. Start local services with `docker compose up -d` after Docker Desktop is running.
3. In `backend/`, run `uv sync --default-index https://pypi.org/simple`, then `uv run alembic upgrade head`, then `uv run uvicorn app.main:app --reload`.
4. Open `/docs` for the generated OpenAPI interface.

For local API-only checks, set `DATABASE_URL=sqlite:///./diseasegraph.db`, `GRAPH_SOURCE=csv`, and `GRAPH_DATA_DIR=experiments/platform_phase_b`, then apply Alembic migrations. CSV mode reads the real bounded Phase B extract; it does not invent graph data. PostgreSQL/Neo4j mode is selected by environment variables after service startup and import.

Current endpoints are read-only for scientific outputs. Dataset registration always creates `validation_pending` state. Graph responses cap at 200 nodes, depth at 2, and use fixed query templates. Async job queue is intentionally deferred.

