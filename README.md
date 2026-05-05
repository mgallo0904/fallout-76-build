# Fallout 76 SPECIAL + Perk Card Build Agent

Production-oriented FastAPI web backend + browser UI for validated Fallout 76 build generation.

## Features
- Build generation for **Power Armor Heavy Energy Gunner** archetype.
- Server-side validation (perk existence, rank legality, SPECIAL budget, PA restrictions, synergy mismatches).
- SQLite persistence for generated builds and source records.
- Build retrieval and side-by-side compare endpoint.
- Source registry with reliability/conflict surfacing.
- Admin JSON import/export for source records.

## Run
```bash
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Endpoints
- `GET /api/perks`
- `GET /api/perks/{id}`
- `POST /api/build/generate`
- `GET /api/build/{id}`
- `POST /api/build/validate`
- `POST /api/build/compare`
- `POST /api/research/update`
- `GET /api/sources`
- `GET /api/admin/export/sources`
- `POST /api/admin/import/sources`


## Ollama Provider (Kimi-k2.6:cloud)
- Set `OLLAMA_BASE_URL` (default `http://localhost:11434`)
- Set `OLLAMA_MODEL` (default `kimi-k2.6:cloud`)
- Use `POST /api/agent/plan` for reasoning + web-search context
- Set `use_ai_provider=true` in `/api/build/generate` payload to enrich build assumptions and verification notes.
