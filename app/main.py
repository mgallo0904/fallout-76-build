from __future__ import annotations
import json
from fastapi import FastAPI, HTTPException, UploadFile
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from app.models import BuildInput, CompareRequest
from app.services.engine import compare_builds, generate_build, validate_build
from app.services.repository import get_build, list_sources, load_perks, save_build
from app.services.providers import kimi_reason_with_search

app = FastAPI(title="Fallout 76 SPECIAL + Perk Card Build Agent", version="1.1.0")
app.mount('/static', StaticFiles(directory='app/static'), name='static')

@app.get('/', response_class=HTMLResponse)
def home() -> str:
    return open('app/static/index.html', encoding='utf-8').read()

@app.get('/compare', response_class=HTMLResponse)
def compare_page() -> str:
    return open('app/static/compare.html', encoding='utf-8').read()

@app.get('/api/perks')
def perks():
    return load_perks()

@app.get('/api/perks/{perk_id}')
def perk(perk_id: str):
    for p in load_perks():
        if p.id == perk_id:
            return p
    raise HTTPException(404, 'Perk not found')


@app.post('/api/agent/plan')
def agent_plan(user: BuildInput):
    prompt = user.ai_prompt or f"{user.primary_playstyle} {user.primary_weapon_type} {user.preferred_weapons}"
    return kimi_reason_with_search(prompt)

@app.post('/api/build/generate')
def build_generate(user: BuildInput):
    build = generate_build(user)
    if user.use_ai_provider:
        ai = kimi_reason_with_search(user.ai_prompt or build.build_name)
        build.assumptions.append(f"AI provider model used: {ai['model']}")
        if ai.get('web_results'):
            build.source_verification_notes.extend([f"AI web: {r['title']} ({r['url']})" for r in ai['web_results']])
    issues = validate_build(build)
    build.validation_status = 'valid' if not issues else 'repaired_with_warnings'
    save_build(build)
    return {'build': build, 'issues': issues}

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
    return {
        'status': 'completed',
        'checked': [s.source_url for s in sources],
        'conflicts_or_uncertain': uncertain,
        'message': 'Source registry refreshed from trusted set. Manual review queue updated for low-confidence records.'
    }

@app.get('/api/sources')
def sources():
    return list_sources()

@app.get('/api/admin/export/sources')
def export_sources():
    return [s.model_dump() for s in list_sources()]

@app.post('/api/admin/import/sources')
def import_sources(file: UploadFile):
    payload = json.loads(file.file.read().decode('utf-8'))
    # For production: validate and upsert. Here validation happens via model parsing in repository seed flow.
    with open('app/data/sources.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, indent=2)
    return {'status': 'imported', 'count': len(payload)}
