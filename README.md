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

## Ollama Brain + Web Search
The app can optionally use Ollama as the logic engine with `kimi-k2.6:cloud` and Ollama web search. Do not put your key in the repo; export it in your shell before starting the server:

```bash
export OLLAMA_API_KEY="your_ollama_api_key"
export OLLAMA_MODEL="kimi-k2.6:cloud"
export USE_OLLAMA_BRAIN=1
export OLLAMA_WEB_SEARCH=1

uvicorn app.main:app --reload
```

Optional settings:
- `OLLAMA_BASE_URL`: defaults to `https://ollama.com` when `OLLAMA_API_KEY` is set, otherwise `http://localhost:11434`.
- `OLLAMA_TIMEOUT_SECONDS`: request timeout, default `35`.
- `OLLAMA_MAX_SEARCH_RESULTS`: web results per request, default `5`, max `10`.

Check configuration with:

```bash
curl http://localhost:8000/api/brain/status
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
- `GET /api/brain/status`
- `POST /api/brain/search`
- `GET /api/admin/export/sources`
- `POST /api/admin/import/sources`
