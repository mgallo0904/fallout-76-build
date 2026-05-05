from __future__ import annotations
import json
from pathlib import Path
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError as PydanticValidationError
from app.models import BuildInput, CompareRequest, SourceRecord, WebSearchRequest
from app.services.brain import BrainError, brain_status, enhance_build_with_brain, get_brain_config, research_digest, web_search
from app.services.engine import compare_builds, generate_build, validate_build
from app.services.repository import get_build, list_sources, load_perks, save_build, seed_sources

BASE_DIR = Path(__file__).resolve().parent
DATA_DIR = BASE_DIR / 'data'
STATIC_DIR = BASE_DIR / 'static'

app = FastAPI(title="Fallout 76 SPECIAL + Perk Card Build Agent", version="1.2.0")
app.mount('/static', StaticFiles(directory=str(STATIC_DIR)), name='static')


@app.get('/', response_class=HTMLResponse)
def home() -> str:
    return (STATIC_DIR / 'index.html').read_text(encoding='utf-8')


@app.get('/compare', response_class=HTMLResponse)
def compare_page() -> str:
    return (STATIC_DIR / 'compare.html').read_text(encoding='utf-8')


@app.get('/api/perks')
def perks():
    return load_perks()


@app.get('/api/perks/{perk_id}')
def perk(perk_id: str):
    for p in load_perks():
        if p.id == perk_id:
            return p
    raise HTTPException(404, 'Perk not found')


@app.post('/api/build/generate')
def build_generate(user: BuildInput):
    build = generate_build(user)
    issues = validate_build(build)
    brain = enhance_build_with_brain(user, build, issues)
    issues = validate_build(build)
    build.validation_status = 'valid' if not issues else 'repaired_with_warnings'
    save_build(build)
    return {'build': build, 'issues': issues, 'brain': brain}


@app.get('/api/build/{build_id}')
def build_get(build_id: str):
    b = get_build(build_id)
    if not b:
        raise HTTPException(404, 'Build not found')
    return b


@app.post('/api/build/validate')
def build_validate(user: BuildInput):
    b = generate_build(user)
    return {'issues': validate_build(b)}


@app.post('/api/build/compare')
def build_compare(req: CompareRequest):
    builds = []
    for bid in req.build_ids:
        b = get_build(bid)
        if not b:
            raise HTTPException(404, f'Build not found: {bid}')
        builds.append(b)
    return compare_builds(builds)


@app.post('/api/research/update')
def research_update():
    sources = list_sources()
    uncertain = [s.source_url for s in sources if s.reliability_score < 0.9]
    brain = research_digest(sources)
    searched_urls = [r['url'] for r in brain.get('search_results', [])]
    conflicts = list(dict.fromkeys(uncertain + brain.get('conflicts_or_uncertain', [])))
    return {
        'status': 'completed',
        'checked': [s.source_url for s in sources] + searched_urls,
        'conflicts_or_uncertain': conflicts,
        'brain': brain,
        'message': 'Source registry refreshed. Ollama web search/digest is included when configured.'
    }


@app.get('/api/brain/status')
def get_brain_status():
    return brain_status()


@app.post('/api/brain/search')
def search_web(req: WebSearchRequest):
    cfg = get_brain_config()
    if not cfg.web_search_enabled:
        raise HTTPException(503, 'Ollama web search is disabled. Set OLLAMA_API_KEY and OLLAMA_WEB_SEARCH=1.')
    try:
        return {'results': web_search(req.query, req.max_results, cfg)}
    except BrainError as exc:
        raise HTTPException(503, str(exc)) from exc


@app.get('/api/sources')
def sources():
    return list_sources()


@app.get('/api/admin/export/sources')
def export_sources():
    return [s.model_dump() for s in list_sources()]


@app.post('/api/admin/import/sources')
def import_sources(file: UploadFile):
    try:
        payload = json.loads(file.file.read().decode('utf-8'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise HTTPException(400, f'Invalid JSON payload: {exc}') from exc

    if not isinstance(payload, list):
        raise HTTPException(400, 'Payload must be a JSON list of source records')

    try:
        validated = [SourceRecord.model_validate(item).model_dump(mode='json') for item in payload]
    except PydanticValidationError as exc:
        raise HTTPException(422, f'Source record validation failed: {exc}') from exc

    (DATA_DIR / 'sources.json').write_text(json.dumps(validated, indent=2), encoding='utf-8')
    seed_sources(force=True)
    return {'status': 'imported', 'count': len(validated)}
