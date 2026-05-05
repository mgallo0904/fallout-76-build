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