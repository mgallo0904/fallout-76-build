# Fallout 76 SPECIAL + Perk Card Build Agent

Production-oriented FastAPI web backend + browser UI for validated Fallout 76 build generation.

## Features
- Build generation for **13 archetypes** across all current Fallout 76 weapon families and playstyles:
  - **Power Armor Heavy Energy Gunner**, **Bullet Storm Heavy Gunner**, **Cremator Pyromaniac**
  - **Onslaught Commando**, **Stealth Rifleman**, **Bow Stealth Sniper**
  - **Power Armor Shotgunner**, **Pepper Shaker Stealth Shotgunner** (April 21 2026 Fancy Pump-Action niche)
  - **VATS Gunslinger**, **Bloodied Melee Bruiser**
  - **Playable Ghoul Heavy**, **Playable Ghoul Commando**, **Playable Ghoul Melee Bruiser**
- Aligned with the **May 6 2026 live baseline**: Patch 62 (CAMP Revamp / Season 22) plus the April 21 2026 update. The April 28 maintenance is tracked as no build-impact, and Patch 68 / Protect Appalachia PTS notes are excluded from live defaults.
- Comprehensive perk database: 100+ regular perk cards including all 28 regular ghoul-only cards, plus 22 legendary perks including Action Diet, Feral Rage, Far-Flung Fireworks, Hack and Slash, Retribution, and all 7 Legendary SPECIAL stat perks.
- Interactive `/planner` UI with patch banner, SPECIAL sliders, perk picker by SPECIAL column, live validation.
- Server-side validation: perk existence + status, rank legality, SPECIAL budget incl. legendary stat perks, PA / VATS / bloodied / stealth synergy mismatches, **Ghoul Unyielding restriction**.
- SQLite persistence for generated builds and source records (auto-seeded at startup).
- Build retrieval and side-by-side compare endpoint.
- Source registry with reliability ordering and 2026 patch sources.
- Admin JSON import/export for source records.
- **Ollama brain (`kimi-k2.6:cloud`) by default** with strengthened patch-aware system prompt and Ollama Web Search grounding. Brain may refine narrative fields (assumptions, gear, mutations, weaknesses, notes, variants, swap cards, legendary perks, build name) but never mutates SPECIAL or core perk picks.

## Run
```bash
pip install -e .[dev]
uvicorn app.main:app --reload
```

## Ollama Brain + Web Search
The app can optionally use Ollama as a background refinement engine with `kimi-k2.6:cloud`. Build generation returns a deterministic build immediately, saves it, then marks `brain_status` as `pending` / `running` / `complete` / `failed` while the browser polls for updates. Do not put your key in the repo; export it in your shell before starting the server:

```bash
export OLLAMA_API_KEY="your_ollama_api_key_here"
export OLLAMA_MODEL="kimi-k2.6:cloud"
export OLLAMA_WEB_SEARCH=1

uvicorn app.main:app --reload
```

Optional settings:
- `USE_OLLAMA_BRAIN`: brain generation is enabled automatically when `OLLAMA_API_KEY` is present; set `USE_OLLAMA_BRAIN=0` to force deterministic local generation, or `USE_OLLAMA_BRAIN=1` to require brain mode explicitly.
- `OLLAMA_BASE_URL`: defaults to `https://ollama.com` when `OLLAMA_API_KEY` is set, otherwise `http://localhost:11434`.
- `OLLAMA_TIMEOUT_SECONDS`: request timeout, default `120`.
- `OLLAMA_MAX_SEARCH_RESULTS`: web results per request, default `5`, max `10`.
- `OLLAMA_BUILD_WEB_SEARCH`: defaults to `0`; build refinement uses the local source registry by default instead of doing live web search on every click. Set to `1` only when you want per-build web grounding and accept slower refinement.

Check configuration with:

```bash
curl http://localhost:8000/api/brain/status
```

## Endpoints
- `GET /api/archetypes`
- `GET /api/archetypes/{id}` — full archetype preview (SPECIAL allocation, perk picks, legendary perks, gear, weaknesses)
- `GET /api/perks` (default: verified only; `?include_deprecated=true` to include retired cards)
- `GET /api/perks/{id}`
- `GET /api/legendary-perks`
- `GET /api/legendary-perks/{id}`
- `POST /api/build/generate`
- `GET /api/build/{id}`
- `POST /api/build/validate`
- `POST /api/build/compare` (body: `{"build_ids": ["...", "..."]}`)
- `POST /api/research/update`
- `POST /api/brain/research` — kimi-k2.6:cloud + web-search grounded patch/meta digest (body: `{"query": "...", "max_results": 5}`)
- `GET /api/sources`
- `GET /api/admin/export/sources`
- `POST /api/admin/import/sources` (multipart, `file=sources.json`)
- `GET /api/brain/status`
- `POST /api/brain/search` (body: `{"query": "...", "max_results": 5}`)

## UI routes
- `/` Builder home (deterministic generator + brain enhancement)
- `/planner` Interactive perk planner with SPECIAL sliders, live validation, and archetype baselines
- `/compare` Compare 2-4 saved builds side by side
