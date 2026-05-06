# Project Review

## What the project does

This repository is a production-oriented Fallout 76 build-planning service composed of:

- A FastAPI backend exposing deterministic build generation and validation APIs.
- A static web UI (`/`, `/planner`, `/compare`) for interactive use.
- JSON-backed data catalogs for perks, legendary perks, and curated source records.
- SQLite persistence for generated builds and source metadata.
- An optional Ollama-powered "brain" layer that enriches narrative sections and performs web-search grounded meta checks.

## Architectural overview

- **`app/main.py`** wires routes, startup lifecycle, static file hosting, and HTTP error handling.
- **`app/models.py`** defines Pydantic schemas for perks, source records, build inputs/outputs, and comparison payloads.
- **`app/services/engine.py`** holds deterministic build logic using archetype blueprints plus strict validation rules.
- **`app/services/repository.py`** manages JSON data loading and SQLite read/write operations.
- **`app/services/db.py`** owns DB schema initialization and connection management.
- **`app/services/brain.py`** integrates with Ollama chat/web-search APIs and applies controlled narrative enhancements.

## Key behaviors

- Supports 13 archetypes, including ghoul-specific variants.
- Validates perk rank legality, SPECIAL budget, synergy constraints, and ghoul restrictions.
- Stores generated builds for retrieval and side-by-side comparison.
- Seeds source records into SQLite on startup and supports import/export admin flows.
- Requires `OLLAMA_API_KEY` for brain mode; returns deterministic behavior when brain is unavailable.

## Strengths

- Clear separation of concerns across API, engine, persistence, and AI integration.
- Defensive error handling around external brain calls.
- Strong model typing and request constraints via Pydantic.
- Good feature coverage through focused test modules.

## Immediate improvement opportunities

1. Add pagination metadata to list APIs (`/api/perks`, `/api/legendary-perks`) to improve client UX at scale.
2. Introduce migration/versioning for SQLite schema changes (e.g., Alembic or lightweight internal migration table).
3. Strengthen deterministic-vs-brain auditability by storing enhancement diffs as a dedicated structured field.
4. Add CI test environment bootstrap to ensure `.[dev]` dependencies (especially `httpx`) are always present before `pytest`.
5. Consider caching immutable JSON catalogs in memory to reduce repeated file parsing under load.
