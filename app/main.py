from __future__ import annotations

import json
from contextlib import asynccontextmanager
from typing import Any, List

from fastapi import BackgroundTasks, FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import ValidationError

from app.models import (
    BuildInput,
    CompareRequest,
    CompareResult,
    GeneratedBuild,
    GenerationMode,
    PerkCard,
    SourceRecord,
    WebSearchRequest,
    WebSearchResult,
)
from app.services.brain import (
    BrainError,
    brain_status,
    research_digest,
    research_patch_digest,
    web_search,
)
from app.services.build_pipeline import run_build_pipeline
from app.services.db import init_db
from app.services.engine import (
    compare_builds,
    prepare_build_for_response,
    refine_saved_build_with_brain,
    get_archetype_preview,
    list_archetypes,
    validate_build,
)
from app.services.repository import (
    get_build,
    list_sources,
    load_active_legendary_perks,
    load_active_perks,
    load_legendary_perks,
    load_perks,
    save_build,
    seed_sources,
    upsert_source,
)

@asynccontextmanager
async def _lifespan(_app: FastAPI):
    init_db()
    seed_sources()
    yield


app = FastAPI(
    title="Fallout 76 Build Agent",
    description="Agent-backed Fallout 76 SPECIAL and Perk Card builder, aligned with the May 6 2026 live baseline: Patch 62 + April 21 2026 update.",
    version="2.1.0",
    lifespan=_lifespan,
)

app.mount("/static", StaticFiles(directory="app/static"), name="static")


@app.get("/")
def read_root():
    return FileResponse("app/static/index.html")


@app.get("/compare")
def read_compare():
    return FileResponse("app/static/compare.html")


@app.get("/planner")
def read_planner():
    return FileResponse("app/static/planner.html")


# ---- Perks ----

@app.get("/api/perks", response_model=List[PerkCard])
def api_get_perks(
    include_deprecated: bool = False,
    limit: int | None = None,
    offset: int = 0,
):
    perks = load_perks() if include_deprecated else load_active_perks()
    if offset:
        perks = perks[offset:]
    if limit is not None:
        perks = perks[:limit]
    return perks


@app.get("/api/perks/{perk_id}", response_model=PerkCard)
def api_get_perk(perk_id: str):
    for p in load_perks():
        if p.id == perk_id:
            return p
    raise HTTPException(status_code=404, detail="Perk not found")


@app.get("/api/legendary-perks", response_model=List[PerkCard])
def api_get_legendary_perks(
    include_deprecated: bool = False,
    character_type: str | None = None,
    limit: int | None = None,
    offset: int = 0,
):
    perks = load_legendary_perks() if include_deprecated else load_active_legendary_perks()
    if character_type:
        ct = character_type.strip().lower()
        perks = [p for p in perks if p.character_restriction.lower() in ("any", ct)]
    if offset:
        perks = perks[offset:]
    if limit is not None:
        perks = perks[:limit]
    return JSONResponse(
        content=[p.model_dump(mode="json") for p in perks],
        headers={"Cache-Control": "max-age=3600"},
    )


@app.get("/api/legendary-perks/{perk_id}", response_model=PerkCard)
def api_get_legendary_perk(perk_id: str):
    for p in load_legendary_perks():
        if p.id == perk_id:
            return p
    raise HTTPException(status_code=404, detail="Legendary perk not found")


@app.get("/api/archetypes")
def api_get_archetypes():
    return list_archetypes()


@app.get("/api/archetypes/{archetype_id}")
def api_get_archetype_preview(archetype_id: str):
    preview = get_archetype_preview(archetype_id)
    if preview is None:
        raise HTTPException(status_code=404, detail="Archetype not found")
    return preview


# ---- Builds ----

@app.post("/api/build/generate", response_model=GeneratedBuild)
def api_generate_build(
    user_input: BuildInput,
    background_tasks: BackgroundTasks,
    generation_mode: GenerationMode = GenerationMode.hybrid,
):
    try:
        build = run_build_pipeline(user_input, mode=generation_mode)
        if build.brain_status == "pending":
            background_tasks.add_task(refine_saved_build_with_brain, build.id)
        return build
    except NotImplementedError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except BrainError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=exc.errors()) from exc
    except Exception as exc:
        raise HTTPException(status_code=500, detail=f"An error occurred: {exc}") from exc


@app.post("/api/build/validate", response_model=List[str])
def api_validate_build(build: GeneratedBuild):
    return validate_build(build)


@app.get("/api/build/{build_id}", response_model=GeneratedBuild)
def api_get_build(build_id: str):
    build = get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    return build


@app.get("/api/build/{build_id}/repair-notes")
def api_get_build_repair_notes(build_id: str):
    build = get_build(build_id)
    if not build:
        raise HTTPException(status_code=404, detail="Build not found")
    return {
        "build_id": build_id,
        "repair_notes": build.repair_notes,
        "generation_mode": build.generation_mode,
    }


@app.post("/api/build/compare", response_model=CompareResult)
def api_compare_builds(request: CompareRequest):
    builds = [get_build(bid) for bid in request.build_ids]
    if not all(builds):
        raise HTTPException(status_code=404, detail="One or more builds not found")
    return compare_builds([b for b in builds if b is not None])


# ---- Sources ----

@app.get("/api/sources", response_model=List[SourceRecord])
def api_list_sources():
    return list_sources()


@app.get("/api/admin/export/sources", response_model=List[SourceRecord])
def api_export_sources():
    return list_sources()


@app.post("/api/admin/import/sources")
def api_import_sources(file: UploadFile = File(...)):
    content = file.file.read().decode("utf-8")
    try:
        data = json.loads(content)
    except (json.JSONDecodeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=f"Invalid JSON: {exc}") from exc
    if not isinstance(data, list):
        raise HTTPException(status_code=400, detail="Payload must be a JSON list")

    imported = 0
    errors: list[str] = []
    for index, item in enumerate(data):
        try:
            record = SourceRecord.model_validate(item)
        except Exception as exc:  # pydantic validation
            errors.append(f"item[{index}]: {exc}")
            continue
        upsert_source(record)
        imported += 1
    payload: dict[str, Any] = {"imported": imported, "errors": errors}
    if errors and imported == 0:
        return JSONResponse(payload, status_code=400)
    if errors:
        # partial success
        return JSONResponse(payload, status_code=207)
    return payload


# ---- Brain / research ----

@app.get("/api/brain/status")
def api_brain_status():
    return brain_status()


@app.post("/api/brain/search", response_model=List[WebSearchResult])
def api_brain_search(request: WebSearchRequest):
    try:
        return web_search(request.query, request.max_results)
    except BrainError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/research/update")
def api_research_update():
    try:
        return research_digest(list_sources())
    except BrainError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@app.post("/api/brain/research")
def api_brain_research(request: WebSearchRequest):
    try:
        return research_patch_digest(request.query, request.max_results)
    except BrainError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
